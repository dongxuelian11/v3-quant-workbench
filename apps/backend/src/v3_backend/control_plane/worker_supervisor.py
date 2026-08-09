from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from v3_backend.domain.tasks.retry_policy import ErrorCategory
from v3_backend.workers.protocol import StagedOutputProposal, WorkerRequest, WorkerTerminal, validate_response

from .lease_manager import LeaseManager, WorkerLease
from .resource_governor import OperationProfile, ResourceGovernor
from .task_supervisor import IdentityAllocator, TaskSupervisor


class WorkerProcess(Protocol):
    def terminate(self) -> None: ...
    def cancel(self) -> None: ...
    def request_checkpoint(self) -> None: ...
    def is_alive(self) -> bool: ...


class WorkerProcessFactory(Protocol):
    def spawn(self, request: WorkerRequest) -> WorkerProcess: ...


@dataclass
class SupervisedWorker:
    lease: WorkerLease
    request: WorkerRequest
    process: WorkerProcess


class WorkerSupervisor:
    def __init__(
        self,
        governor: ResourceGovernor,
        leases: LeaseManager,
        tasks: TaskSupervisor,
        identities: IdentityAllocator,
        factory: WorkerProcessFactory,
    ) -> None:
        self.governor = governor
        self.leases = leases
        self.tasks = tasks
        self.identities = identities
        self.factory = factory
        self.workers: dict[str, SupervisedWorker] = {}
        self.staged_outputs: dict[str, list[StagedOutputProposal]] = {}

    def dispatch(self, request: WorkerRequest, profile: OperationProfile) -> WorkerLease:
        lease_id = self.identities.new("WorkerLease")
        grant = self.governor.admit(lease_id, profile)
        lease = self.leases.grant(
            lease_id, request.attempt_id, grant, lease_token=request.resource_lease_token
        )
        self.tasks.assign_lease(request.attempt_id, lease_id)
        try:
            process = self.factory.spawn(request)
        except Exception:
            self.tasks.transition_attempt(
                request.attempt_id, "ATTEMPT_FAILED", error_category=ErrorCategory.RETRYABLE_ADAPTER.value
            )
            self.leases.revoke(lease_id)
            self.governor.release(lease_id)
            raise
        self.workers[lease_id] = SupervisedWorker(lease, request, process)
        self.tasks.transition_attempt(request.attempt_id, "WORKER_DISPATCHED")
        return lease

    def acknowledge(self, lease_id: str, protocol_version: str, lease_token: str) -> None:
        worker = self.workers[lease_id]
        if (
            protocol_version != worker.request.protocol_version
            or lease_token != worker.lease.lease_token
        ):
            self._terminate_lost(lease_id, "protocol mismatch")
            raise ValueError("worker protocol mismatch")
        self.tasks.transition_attempt(worker.request.attempt_id, "WORKER_ACKNOWLEDGED")
        self.tasks.mark_task_started_for_attempt(worker.request.attempt_id)

    def heartbeat(self, lease_id: str, sequence: int, rss_bytes: int, scratch_bytes: int) -> None:
        try:
            self.leases.heartbeat(
                lease_id, sequence, rss_bytes=rss_bytes, scratch_bytes=scratch_bytes
            )
        except MemoryError:
            self.governor.worker_over_limit(lease_id, "lease memory/scratch limit")
            self._terminate_failed(lease_id, ErrorCategory.WORKER_OOM)

    def handle(self, lease_id: str, response: object) -> None:
        worker = self.workers[lease_id]
        try:
            checked = validate_response(response)  # type: ignore[arg-type]
        except Exception:
            self._terminate_failed(lease_id, ErrorCategory.SCHEMA_MISMATCH)
            return
        if isinstance(checked, StagedOutputProposal):
            self.staged_outputs.setdefault(worker.request.attempt_id, []).append(checked)
            return
        if isinstance(checked, WorkerTerminal):
            if checked.status == "SUCCEEDED":
                self.tasks.transition_attempt(worker.request.attempt_id, "ATTEMPT_SUCCEEDED")
                self._release(lease_id)
            elif checked.status == "CANCELLED":
                self.tasks.transition_attempt(worker.request.attempt_id, "ATTEMPT_CANCELLED")
                self._release(lease_id)
            else:
                category = ErrorCategory.WORKER_OOM if checked.error_category == "WORKER_OOM" else ErrorCategory.RETRYABLE_ADAPTER
                self._terminate_failed(lease_id, category)

    def cancel(self, attempt_id: str) -> None:
        for worker in self.workers.values():
            if worker.request.attempt_id == attempt_id:
                worker.process.cancel()
                return

    def reap_expired(self) -> tuple[str, ...]:
        lost: list[str] = []
        for lease in self.leases.expire_due():
            self._terminate_lost(lease.lease_id, "heartbeat expired", already_expired=True)
            lost.append(lease.attempt_id)
        return tuple(lost)

    def reconcile_startup(self) -> tuple[str, ...]:
        lost: list[str] = []
        for lease in self.leases.persistence.active():
            worker = self.workers.get(lease.lease_id)
            if worker is None or not worker.process.is_alive():
                self._terminate_lost(lease.lease_id, "no matching live supervised child")
                lost.append(lease.attempt_id)
        return tuple(lost)

    def _terminate_failed(self, lease_id: str, category: ErrorCategory) -> None:
        worker = self.workers[lease_id]
        self._safe_terminate(worker.process)
        self.tasks.transition_attempt(worker.request.attempt_id, "ATTEMPT_FAILED", error_category=category.value)
        self.leases.revoke(lease_id)
        self.governor.release(lease_id)

    def _terminate_lost(self, lease_id: str, reason: str, *, already_expired: bool = False) -> None:
        worker = self.workers.get(lease_id)
        if worker:
            self._safe_terminate(worker.process)
            attempt_id = worker.request.attempt_id
        else:
            attempt_id = self.leases.persistence.require(lease_id).attempt_id
        self.tasks.transition_attempt(attempt_id, "WORKER_LOST", error_category=ErrorCategory.WORKER_LOST.value)
        if not already_expired:
            self.leases.revoke(lease_id)
        self.governor.release(lease_id)

    def _release(self, lease_id: str) -> None:
        self.leases.release(lease_id)
        self.governor.release(lease_id)

    @staticmethod
    def _safe_terminate(process: WorkerProcess) -> None:
        try:
            process.terminate()
        except Exception:
            # Process cleanup failure must not take down the backend supervisor.
            pass
