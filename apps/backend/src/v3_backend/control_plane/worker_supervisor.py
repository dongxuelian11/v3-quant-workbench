from __future__ import annotations

import stat
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Protocol

from v3_backend.domain.tasks.retry_policy import ErrorCategory
from v3_backend.workers.protocol import (
    CheckpointProposal,
    Progress,
    StagedOutputProposal,
    WorkerRequest,
    WorkerTerminal,
    validate_response,
)

from .lease_manager import LeaseManager, WorkerLease
from .progress_persistence import (
    compatibility_hash_for_context,
    ProgressConflict,
    ReceiptStateConflict,
)
from .resource_governor import OperationProfile, ResourceGovernor
from .task_supervisor import IdentityAllocator, TaskSupervisor


RESOURCE_ENFORCEMENT_NOT_AVAILABLE = "RESOURCE_ENFORCEMENT_NOT_AVAILABLE"
DEADLINE_EXCEEDED_PRE_COMMIT = "DEADLINE_EXCEEDED_PRE_COMMIT"
MAX_PROPOSALS_PER_ATTEMPT = 32


class ResourceEnforcementUnavailable(RuntimeError):
    """A hard resource boundary could not be installed or verified."""


class WorkerProcess(Protocol):
    def terminate(self) -> None: ...
    def cancel(self) -> None: ...
    def request_checkpoint(self) -> None: ...
    def acknowledge_progress(self, sequence: int) -> None: ...
    def is_alive(self) -> bool: ...


class WorkerProcessFactory(Protocol):
    def spawn(self, request: WorkerRequest) -> WorkerProcess: ...


class WorkerJobController(Protocol):
    def assign(self, process: WorkerProcess, grant: object) -> None: ...

    def query(self, process: WorkerProcess) -> object: ...


@dataclass
class SupervisedWorker:
    lease: WorkerLease
    request: WorkerRequest
    process: WorkerProcess


@dataclass(frozen=True)
class _PendingTermination:
    """A Product-owned terminal decision awaiting OS exit confirmation."""

    kind: str
    error_code: str | None = None
    message: str | None = None
    reason_code: str | None = None
    already_expired: bool = False


class WorkerSupervisor:
    def __init__(
        self,
        governor: ResourceGovernor,
        leases: LeaseManager,
        tasks: TaskSupervisor,
        identities: IdentityAllocator,
        factory: WorkerProcessFactory,
        job_controller: WorkerJobController | None = None,
        progress_persistence: object | None = None,
        product_terminal_owner: bool = False,
    ) -> None:
        if not isinstance(product_terminal_owner, bool):
            raise ValueError("product_terminal_owner must be a boolean")
        self.governor = governor
        self.leases = leases
        self.tasks = tasks
        self.identities = identities
        self.factory = factory
        self.job_controller = job_controller
        self.progress_persistence = progress_persistence
        self.product_terminal_owner = product_terminal_owner
        self.workers: dict[str, SupervisedWorker] = {}
        self.staged_outputs: dict[str, list[StagedOutputProposal]] = {}
        self.checkpoint_proposals: dict[str, list[CheckpointProposal]] = {}
        self._pending_terminations: dict[str, _PendingTermination] = {}
        self._pressure_signals: set[tuple[str, str]] = set()
        self._lock = RLock()

    def dispatch(self, request: WorkerRequest, profile: OperationProfile) -> WorkerLease:
        with self._lock:
            return self._dispatch_locked(request, profile)

    def _dispatch_locked(self, request: WorkerRequest, profile: OperationProfile) -> WorkerLease:
        lease_id = self.identities.new("WorkerLease")
        grant = None
        lease = None
        process = None
        try:
            execution_context = None
            context_reader = getattr(self.progress_persistence, "execution_context_for_attempt", None)
            if callable(context_reader):
                execution_context = context_reader(request.attempt_id)
                if (
                    request.run_id != execution_context["run_id"]
                    or request.operation_id != execution_context["operation_id"]
                    or request.input_hash != execution_context["input_hash"]
                    or (
                        request.code_version is not None
                        and request.code_version != execution_context["code_version"]
                    )
                    or (
                        request.environment_profile_id is not None
                        and request.environment_profile_id
                        != execution_context["environment_profile"]
                    )
                ):
                    raise ValueError("WorkerRequest does not match the immutable Run context")
            grant = self.governor.admit(lease_id, profile)
            grant = self._bind_attempt_scratch_root(request, grant)
            policy_version = getattr(grant, "policy_version", None)
            if request.resource_policy_version is not None and request.resource_policy_version != policy_version:
                raise ValueError("worker request resource policy version does not match resolved grant")
            resolved_hash = getattr(grant, "resolved_resource_hash", None)
            if request.resolved_resource_hash is not None and request.resolved_resource_hash != resolved_hash:
                raise ValueError("worker request resource hash does not match resolved grant")
            runtime_generation_id = getattr(grant, "runtime_generation_id", None)
            if request.runtime_generation_id is not None and request.runtime_generation_id != runtime_generation_id:
                raise ValueError("worker request runtime generation does not match resolved grant")
            request = replace(
                request,
                resource_policy_version=policy_version,
                resolved_resource_hash=resolved_hash,
                runtime_generation_id=runtime_generation_id,
            )
            compatibility_hash = compatibility_hash_for_context(
                input_hash=request.input_hash,
                code_version=(
                    request.code_version
                    or ("UNSPECIFIED" if execution_context is None else execution_context["code_version"])
                ),
                environment_profile=(
                    request.environment_profile_id
                    or (
                        "UNSPECIFIED"
                        if execution_context is None
                        else execution_context["environment_profile"]
                    )
                ),
                operation_id=request.operation_id,
                operation_schema_version=request.operation_schema_version or "1.0.0",
                resource_policy_version=request.resource_policy_version or policy_version,
                resolved_resource_hash=request.resolved_resource_hash,
            )
            if request.compatibility_hash is not None and request.compatibility_hash != compatibility_hash:
                raise ValueError("worker request compatibility hash does not match canonical resolution")
            request = replace(request, compatibility_hash=compatibility_hash)
            lease = self.leases.grant(
                lease_id,
                request.attempt_id,
                grant,
                lease_token=request.resource_lease_token,
            )
            self.tasks.assign_lease(request.attempt_id, lease_id)
            bind_resolution = getattr(self.progress_persistence, "bind_runtime_resolution", None)
            if callable(bind_resolution):
                bind_resolution(
                    run_id=request.run_id,
                    attempt_id=request.attempt_id,
                    operation_schema_version=request.operation_schema_version or "1.0.0",
                    resource_policy_version=request.resource_policy_version or policy_version,
                    resolved_resource_json=grant.resolved_resource_json,
                    resolved_resource_hash=grant.resolved_resource_hash,
                    compatibility_hash=request.compatibility_hash,
                    runtime_generation_id=grant.runtime_generation_id,
                )
            # Persist the dispatch admission before creating an OS child.  If
            # either durable transition loses a race or the queue sidecar is
            # unavailable, the failure path below can close the Attempt while
            # no process exists.  Keeping these writes after spawn would make
            # a child live while the same handler is already writing terminal
            # failure truth, which violates the Product exit-proof boundary.
            mark_dispatched = getattr(self.progress_persistence, "mark_dispatched", None)
            if callable(mark_dispatched):
                task_id_for_attempt = getattr(
                    self.progress_persistence, "task_id_for_attempt", None
                )
                if not callable(task_id_for_attempt):
                    raise RuntimeError("progress persistence cannot resolve Attempt owner")
                mark_dispatched(task_id_for_attempt(request.attempt_id))
            self.tasks.transition_attempt(request.attempt_id, "WORKER_DISPATCHED")
            process = self.factory.spawn(request)
            supervised = SupervisedWorker(lease, request, process)
            self.workers[lease_id] = supervised
            return lease
        except Exception as error:
            if process is not None:
                self._safe_terminate(process)
                self._release_job(process)
            self.workers.pop(lease_id, None)
            self._clear_attempt_proposals(request.attempt_id)
            if lease is not None:
                try:
                    self.tasks.fail_attempt_before_start(
                        request.attempt_id,
                        error_category=(
                            RESOURCE_ENFORCEMENT_NOT_AVAILABLE
                            if isinstance(error, ResourceEnforcementUnavailable)
                            else (
                                ErrorCategory.TRANSIENT_IO.value
                                if isinstance(error, OSError)
                                else ErrorCategory.INTERNAL_ERROR.value
                            )
                        ),
                        error_message=str(error),
                        reason_code=(
                            RESOURCE_ENFORCEMENT_NOT_AVAILABLE
                            if isinstance(error, ResourceEnforcementUnavailable)
                            else None
                        ),
                    )
                except Exception:
                    # Preserve the original dispatch failure; the lease is
                    # still revoked below and startup reconciliation can see
                    # the durable Attempt if this secondary write fails.
                    pass
                try:
                    self.leases.revoke(lease_id)
                except Exception:
                    pass
            self.governor.release(lease_id)
            self._pressure_signals = {
                item for item in self._pressure_signals if item[0] != lease_id
            }
            raise

    @staticmethod
    def _bind_attempt_scratch_root(request: WorkerRequest, grant: object) -> object:
        """Give each Attempt a dedicated, bounded scratch namespace."""

        root = getattr(grant, "scratch_root", None)
        if root is None:
            return grant
        root_path = Path(str(root))
        if not root_path.is_absolute():
            raise ResourceEnforcementUnavailable(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: scratch root must be absolute"
            )

        def is_reparse(path: Path) -> bool:
            try:
                details = path.lstat()
            except OSError as error:
                raise ResourceEnforcementUnavailable(
                    f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: scratch path cannot be inspected"
                ) from error
            return stat.S_ISLNK(details.st_mode) or bool(
                getattr(details, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            )

        try:
            if is_reparse(root_path) or not root_path.is_dir():
                raise ResourceEnforcementUnavailable(
                    f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: scratch root is not a real directory"
                )
            root_resolved = root_path.resolve(strict=True)
            dedicated = root_path / request.attempt_id
            if dedicated.exists() and is_reparse(dedicated):
                raise ResourceEnforcementUnavailable(
                    f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: dedicated scratch path is a reparse point"
                )
            dedicated.mkdir(parents=True, exist_ok=True)
            if is_reparse(dedicated) or not dedicated.is_dir():
                raise ResourceEnforcementUnavailable(
                    f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: dedicated scratch path is not a real directory"
                )
            dedicated_resolved = dedicated.resolve(strict=True)
            try:
                dedicated_resolved.relative_to(root_resolved)
            except ValueError as error:
                raise ResourceEnforcementUnavailable(
                    f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: dedicated scratch path escapes its root"
                ) from error
        except ResourceEnforcementUnavailable:
            raise
        except OSError as error:
            raise ResourceEnforcementUnavailable(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: dedicated scratch path cannot be created"
            ) from error
        return replace(grant, scratch_root=str(dedicated_resolved))

    def acknowledge(self, lease_id: str, protocol_version: str, lease_token: str) -> None:
        with self._lock:
            worker = self.workers.get(lease_id)
            if worker is None:
                # A child can race the parent-side terminal cleanup.  The
                # durable Attempt/receipt owner has already decided its
                # outcome, so a late ACK is an observation, not a new start.
                return
            if lease_id in self._pending_terminations:
                # A Product child can race the parent-side termination ladder.
                # Until exit is observed, no late HELLO may reopen admission.
                return
            if (
                protocol_version != worker.request.protocol_version
                or lease_token != worker.lease.lease_token
            ):
                self._terminate_lost(lease_id, "protocol mismatch")
                raise ValueError("worker protocol mismatch")

            def reject_if_deadline_expired() -> None:
                deadline_at = worker.request.deadline_at
                if deadline_at is None:
                    return
                deadline = datetime.fromisoformat(deadline_at[:-1] + "+00:00")
                if datetime.now(timezone.utc) < deadline:
                    return
                message = "worker acknowledgement arrived after execution deadline"
                self._terminate_failed_before_start(
                    lease_id,
                    message,
                    error_code=DEADLINE_EXCEEDED_PRE_COMMIT,
                    reason_code=DEADLINE_EXCEEDED_PRE_COMMIT,
                )
                raise RuntimeError(message)

            reject_if_deadline_expired()
            if self.job_controller is not None:
                try:
                    self.job_controller.assign(worker.process, worker.lease.grant)
                    query = getattr(self.job_controller, "query", None)
                    if not callable(query):
                        raise ResourceEnforcementUnavailable(
                            f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: Job Object query is unavailable"
                        )
                    observed = query(worker.process)
                    self._verify_job_query(worker.process, worker.lease.grant, observed)
                except Exception as error:
                    message = f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: {error}"
                    self._terminate_failed_before_start(lease_id, message)
                    raise ResourceEnforcementUnavailable(message) from error
            reject_if_deadline_expired()
            mark_running = getattr(self.progress_persistence, "mark_receipt_running", None)
            if callable(mark_running):
                try:
                    mark_running(worker.request.attempt_id)
                except Exception as error:
                    message = f"operation receipt could not enter RUNNING: {error}"
                    self._terminate_failed_before_start(lease_id, message)
                    raise ResourceEnforcementUnavailable(message) from error
            reject_if_deadline_expired()
            try:
                self.tasks.transition_attempt(
                    worker.request.attempt_id, "WORKER_ACKNOWLEDGED"
                )
                self.tasks.mark_task_started_for_attempt(worker.request.attempt_id)
            except Exception:
                # Job assignment and receipt RUNNING both happen before the
                # aggregate owner is advanced.  If that final durable step
                # loses a race, the child must not remain admitted with an
                # ACK-capable lease.  Preserve cancellation intent when it
                # already won; otherwise close the Attempt as an internal
                # pre-start failure and let the product owner finish the Task.
                self._terminate_acknowledgement_failure(lease_id)
                raise

    @staticmethod
    def _verify_job_query(process: WorkerProcess, grant: object, observed: object) -> None:
        """Require read-back of every hard property before ACK_START."""

        expected_memory = getattr(grant, "memory_hard_limit_bytes", None)
        expected_cpu = getattr(grant, "job_cpu_rate_per_10000", None)
        if expected_cpu is None:
            # Legacy deterministic supervisors do not request hard Job Object
            # enforcement.  A real job controller is only admitted for grants
            # that carry a CPU rate.
            raise ResourceEnforcementUnavailable(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: grant has no CPU hard cap"
            )
        observed_memory = getattr(observed, "memory_limit_bytes", None)
        observed_cpu = getattr(observed, "cpu_rate_per_10000", None)
        kill_on_close = getattr(observed, "kill_on_close", None)
        hard_cpu_cap = getattr(observed, "hard_cpu_cap", None)
        expected_pid = getattr(process, "pid", None)
        if expected_pid is None:
            expected_pid = getattr(getattr(process, "process", None), "pid", None)
        observed_pid = getattr(observed, "process_id", None)
        if (
            not isinstance(expected_pid, int)
            or isinstance(expected_pid, bool)
            or expected_pid <= 0
            or observed_pid != expected_pid
            or observed_memory != expected_memory
            or observed_cpu != expected_cpu
            or kill_on_close is not True
            or hard_cpu_cap is not True
        ):
            raise ResourceEnforcementUnavailable(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: Job Object query mismatch"
            )

    def heartbeat(self, lease_id: str, sequence: int, rss_bytes: int, scratch_bytes: int) -> None:
        with self._lock:
            if lease_id in self._pending_terminations:
                return
            # Worker-reported RSS/scratch values are telemetry only.  Hard
            # resource authority comes from record_parent_sample(), whose
            # controller/Job Object observation is persisted separately.
            self.leases.heartbeat(
                lease_id, sequence, rss_bytes=rss_bytes, scratch_bytes=scratch_bytes
            )

    def record_parent_sample(
        self,
        lease_id: str,
        *,
        memory_bytes: int,
        scratch_bytes: int,
    ) -> None:
        """Persist a parent-owned sample and fence on a hard overage."""

        with self._lock:
            if lease_id in self._pending_terminations:
                return
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in (memory_bytes, scratch_bytes)
            ):
                raise ValueError("parent resource samples must be non-negative integers")
            worker = self.workers.get(lease_id)
            if worker is not None:
                self._signal_pressure_if_needed(
                    lease_id,
                    worker,
                    "MEMORY",
                    memory_bytes,
                    worker.lease.grant.memory_hard_limit_bytes,
                )
                self._signal_pressure_if_needed(
                    lease_id,
                    worker,
                    "SCRATCH",
                    scratch_bytes,
                    worker.lease.grant.scratch_budget_bytes,
                )
            try:
                self.leases.record_parent_sample(
                    lease_id,
                    memory_bytes=memory_bytes,
                    scratch_bytes=scratch_bytes,
                )
            except Exception as error:
                kind = getattr(error, "kind", None)
                if kind in {"RESOURCE_EXHAUSTED_MEMORY", "RESOURCE_EXHAUSTED_SCRATCH"}:
                    if worker is not None:
                        self._signal_pressure_if_needed(
                            lease_id,
                            worker,
                            "MEMORY" if kind.endswith("MEMORY") else "SCRATCH",
                            memory_bytes if kind.endswith("MEMORY") else scratch_bytes,
                            (
                                worker.lease.grant.memory_hard_limit_bytes
                                if kind.endswith("MEMORY")
                                else worker.lease.grant.scratch_budget_bytes
                            ),
                            force=True,
                        )
                    self._terminate_failed_code(lease_id, str(kind))
                    return
                raise

    def _signal_pressure_if_needed(
        self,
        lease_id: str,
        worker: SupervisedWorker,
        kind: str,
        observed: int,
        hard_limit: int,
        *,
        force: bool = False,
    ) -> None:
        if (
            isinstance(observed, bool)
            or not isinstance(observed, int)
            or observed < 0
            or isinstance(hard_limit, bool)
            or not isinstance(hard_limit, int)
            or hard_limit <= 0
        ):
            raise ValueError("resource pressure observation and limit are invalid")
        if hard_limit <= 0 or observed < hard_limit * 0.8:
            return
        key = (lease_id, kind)
        if key in self._pressure_signals and not force:
            return
        self._pressure_signals.add(key)
        self.governor.record_event(
            {
                "action": "PRESSURE",
                "resource_class": worker.lease.grant.resource_class,
                "resource": kind,
                "observed": observed,
                "soft_limit": int(hard_limit * 0.8),
                "hard_limit": hard_limit,
            }
        )
        signal = getattr(worker.process, "signal_resource_pressure", None)
        if callable(signal):
            try:
                signal(kind, observed, int(hard_limit * 0.8), hard_limit)
            except Exception:
                pass
        if force:
            cancel = getattr(worker.process, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass
        elif worker.request.checkpoint_policy != "NOT_AVAILABLE":
            request_checkpoint = getattr(worker.process, "request_checkpoint", None)
            if callable(request_checkpoint):
                try:
                    request_checkpoint()
                except Exception:
                    pass

    def handle(self, lease_id: str, response: object) -> None:
        with self._lock:
            worker = self.workers.get(lease_id)
            # ProductRuntime owns the durable terminal write for an isolated
            # child.  The typed terminal frame can therefore arrive after
            # that owner has released the supervisor tombstone; it is a late
            # observation, not a new state transition.
            if worker is None:
                return
            if lease_id in self._pending_terminations:
                return
            try:
                checked = validate_response(response)  # type: ignore[arg-type]
            except Exception:
                self._terminate_failed(lease_id, ErrorCategory.SCHEMA_MISMATCH)
                return
            if isinstance(checked, StagedOutputProposal):
                proposals = self.staged_outputs.setdefault(worker.request.attempt_id, [])
                if len(proposals) >= MAX_PROPOSALS_PER_ATTEMPT:
                    self._terminate_failed_code(
                        lease_id, "STAGED_OUTPUT_PROPOSALS_EXCEEDED"
                    )
                    return
                proposals.append(checked)
                return
            if isinstance(checked, CheckpointProposal):
                proposals = self.checkpoint_proposals.setdefault(
                    worker.request.attempt_id, []
                )
                if len(proposals) >= MAX_PROPOSALS_PER_ATTEMPT:
                    self._terminate_failed_code(
                        lease_id, "CHECKPOINT_PROPOSALS_EXCEEDED"
                    )
                    return
                proposals.append(checked)
                return
            if isinstance(checked, Progress):
                if self.progress_persistence is None:
                    self._terminate_failed_code(
                        lease_id, "PROGRESS_PERSISTENCE_REQUIRED"
                    )
                    return
                try:
                    persisted = self.progress_persistence.record_progress(
                        worker.request.attempt_id,
                        phase=checked.phase,
                        completed_units=checked.completed,
                        total_units=checked.total,
                        work_unit=checked.work_unit,
                        counters=checked.counters,
                        sequence=checked.sequence,
                    )
                except ProgressConflict:
                    self._terminate_failed_code(lease_id, "PROGRESS_CONFLICT")
                    return
                except KeyError:
                    self._terminate_failed_code(lease_id, "PROGRESS_ATTEMPT_NOT_FOUND")
                    return
                except ValueError:
                    self._terminate_failed_code(lease_id, "PROGRESS_INVALID")
                    return
                except Exception:
                    self._terminate_failed_code(lease_id, "PROGRESS_PERSISTENCE_ERROR")
                    return
                acknowledge = getattr(worker.process, "acknowledge_progress", None)
                if callable(acknowledge):
                    acknowledge(int(getattr(persisted, "sequence", checked.sequence or 0)))
                return
            if isinstance(checked, WorkerTerminal):
                current_state = self._current_attempt_state(worker.request.attempt_id)
                if current_state in {"SUCCEEDED", "FAILED", "CANCELLED", "LOST"}:
                    self._release(lease_id)
                    return
                # Product child processes persist their own canonical
                # Attempt/Task/receipt terminal state before sending this
                # frame.  The generic supervisor must not win a race and
                # mark Attempt SUCCEEDED first, otherwise ProductRuntime's
                # atomic finalization can no longer append final progress and
                # commit receipt finality.
                if self.product_terminal_owner:
                    return
                if checked.status == "SUCCEEDED":
                    self.tasks.transition_attempt(worker.request.attempt_id, "ATTEMPT_SUCCEEDED")
                    self._release(lease_id)
                elif checked.status == "CANCELLED":
                    self.tasks.transition_attempt(worker.request.attempt_id, "ATTEMPT_CANCELLED")
                    self._release(lease_id)
                else:
                    if checked.error_category in {
                        "RESOURCE_EXHAUSTED_MEMORY",
                        "RESOURCE_EXHAUSTED_SCRATCH",
                        RESOURCE_ENFORCEMENT_NOT_AVAILABLE,
                    }:
                        self._terminate_failed_code(
                            lease_id, str(checked.error_category)
                        )
                        return
                    try:
                        category = ErrorCategory(str(checked.error_category))
                    except ValueError:
                        category = ErrorCategory.SCHEMA_MISMATCH
                    self._terminate_failed(lease_id, category)

    def cancel(self, attempt_id: str) -> None:
        with self._lock:
            for worker in self.workers.values():
                if worker.request.attempt_id == attempt_id:
                    worker.process.cancel()
                    return

    def observe_externally_finalized(self, lease_id: str) -> None:
        """Release live resource accounting after the durable owner finalizes.

        Product workers publish their canonical Task/Attempt terminal state in
        their own SQLite UoW.  The generic supervisor still owns dispatch,
        acknowledgement, heartbeat, cancellation signalling, and resource
        admission, but must not replay a second terminal state transition.
        """
        with self._lock:
            pending = self._pending_terminations.get(lease_id)
            if pending is not None:
                worker = self.workers.get(lease_id)
                if worker is None:
                    # Keep the pending decision visible for reconciliation if
                    # the process handle was lost unexpectedly.
                    return
                try:
                    if worker.process.is_alive():
                        # A terminal decision is not durable until the OS
                        # process has actually exited.
                        return
                except Exception:
                    # An uninspectable process is an orphan boundary.  Keep
                    # the tombstone and let the Product reaper try again.
                    return
                self._pending_terminations.pop(lease_id, None)
                if pending.kind == "ACKNOWLEDGEMENT_FAILURE":
                    self._terminate_acknowledgement_failure(lease_id)
                elif pending.kind == "FAILED_CODE":
                    assert pending.error_code is not None
                    self._terminate_failed_code(lease_id, pending.error_code)
                elif pending.kind == "FAILED_BEFORE_START":
                    assert pending.error_code is not None
                    assert pending.message is not None
                    self._terminate_failed_before_start(
                        lease_id,
                        pending.message,
                        error_code=pending.error_code,
                        reason_code=pending.reason_code,
                    )
                elif pending.kind == "LOST":
                    self._terminate_lost(
                        lease_id,
                        pending.message or "worker process lost",
                        already_expired=pending.already_expired,
                    )
                return
            worker = self.workers.pop(lease_id, None)
            if worker is not None:
                self._release_job(worker.process)
                self._clear_attempt_proposals(worker.request.attempt_id)
            self.governor.release(lease_id)
            self._pressure_signals = {
                item for item in self._pressure_signals if item[0] != lease_id
            }

    def reap_expired(self) -> tuple[str, ...]:
        with self._lock:
            lost: list[str] = []
            for lease in self.leases.expire_due():
                self._terminate_lost(lease.lease_id, "heartbeat expired", already_expired=True)
                lost.append(lease.attempt_id)
            return tuple(lost)

    def reconcile_startup(self) -> tuple[str, ...]:
        with self._lock:
            lost: list[str] = []
            for lease in self.leases.persistence.active():
                worker = self.workers.get(lease.lease_id)
                if worker is None or not worker.process.is_alive():
                    self._terminate_lost(lease.lease_id, "no matching live supervised child")
                    lost.append(lease.attempt_id)
            return tuple(lost)

    def _terminate_failed(self, lease_id: str, category: ErrorCategory) -> None:
        self._terminate_failed_code(lease_id, category.value)

    def abort_before_start(
        self,
        lease_id: str,
        message: str,
        *,
        error_code: str = ErrorCategory.INTERNAL_ERROR.value,
        reason_code: str | None = None,
    ) -> None:
        """Close an admitted worker when handle transfer fails before ACK."""

        with self._lock:
            self._terminate_failed_before_start(
                lease_id,
                message,
                error_code=error_code,
                reason_code=reason_code,
            )

    def _terminate_acknowledgement_failure(self, lease_id: str) -> None:
        """Fence a worker when aggregate admission fails after ACK setup."""

        if self._defer_product_termination_if_live(
            lease_id,
            _PendingTermination(kind="ACKNOWLEDGEMENT_FAILURE"),
        ):
            return
        worker = self.workers.pop(lease_id, None)
        if worker is None:
            return
        self._clear_attempt_proposals(worker.request.attempt_id)
        self._pressure_signals = {
            item for item in self._pressure_signals if item[0] != lease_id
        }
        cancel = getattr(worker.process, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass
        self._safe_terminate(worker.process)
        self._release_job(worker.process)

        attempt_state, task_state = self._current_attempt_and_task_state(
            worker.request.attempt_id
        )
        if task_state == "CANCEL_REQUESTED":
            if attempt_state not in {"SUCCEEDED", "FAILED", "CANCELLED", "LOST"}:
                try:
                    self.tasks.transition_attempt(
                        worker.request.attempt_id, "ATTEMPT_CANCELLED"
                    )
                except Exception:
                    pass
            self._mark_receipt_failed(
                worker.request.attempt_id, "EXECUTION_CANCELLED_PRE_COMMIT"
            )
        elif attempt_state not in {"SUCCEEDED", "FAILED", "CANCELLED", "LOST"}:
            try:
                self.tasks.fail_attempt_before_start(
                    worker.request.attempt_id,
                    error_category=ErrorCategory.INTERNAL_ERROR.value,
                    error_message="aggregate Task start failed after worker ACK",
                )
            except Exception:
                pass
            self._mark_receipt_failed(
                worker.request.attempt_id, ErrorCategory.INTERNAL_ERROR.value
            )

        # Aggregate admission owns the original exception.  Always release
        # in-memory resource accounting even if durable lease cleanup loses a
        # concurrent terminal race; reconciliation can repair a transient
        # persistence failure later.
        self._close_lease(lease_id, revoke=True)

    def _terminate_failed_code(self, lease_id: str, error_code: str) -> None:
        if self._defer_product_termination_if_live(
            lease_id,
            _PendingTermination(kind="FAILED_CODE", error_code=error_code),
        ):
            return
        worker = self.workers.pop(lease_id, None)
        if worker is None:
            return
        self._clear_attempt_proposals(worker.request.attempt_id)
        self._pressure_signals = {
            item for item in self._pressure_signals if item[0] != lease_id
        }
        cancel = getattr(worker.process, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass
        self._safe_terminate(worker.process)
        self._release_job(worker.process)
        current_state = self._current_attempt_state(worker.request.attempt_id)
        transition_error: Exception | None = None
        if current_state not in {"SUCCEEDED", "FAILED", "CANCELLED", "LOST"}:
            try:
                self.tasks.transition_attempt(
                    worker.request.attempt_id, "ATTEMPT_FAILED", error_category=error_code
                )
            except Exception as error:
                # ProductRuntime may have committed success between the
                # durable read above and this transition.  Re-read before
                # deciding whether the failure is still authoritative; all
                # resource accounting must be released in either case.
                transition_error = error
                current_state = self._current_attempt_state(worker.request.attempt_id)
        lease_error = self._close_lease(lease_id, revoke=True)
        if current_state not in {"SUCCEEDED", "CANCELLED"}:
            self._mark_receipt_failed(worker.request.attempt_id, error_code)
        if transition_error is not None and current_state not in {
            "SUCCEEDED",
            "FAILED",
            "CANCELLED",
            "LOST",
        }:
            raise transition_error
        if lease_error is not None:
            raise lease_error

    def _terminate_failed_before_start(
        self,
        lease_id: str,
        message: str,
        *,
        error_code: str = RESOURCE_ENFORCEMENT_NOT_AVAILABLE,
        reason_code: str | None = RESOURCE_ENFORCEMENT_NOT_AVAILABLE,
    ) -> None:
        if self._defer_product_termination_if_live(
            lease_id,
            _PendingTermination(
                kind="FAILED_BEFORE_START",
                error_code=error_code,
                message=message,
                reason_code=reason_code,
            ),
        ):
            return
        worker = self.workers.pop(lease_id, None)
        if worker is None:
            return
        self._clear_attempt_proposals(worker.request.attempt_id)
        self._pressure_signals = {
            item for item in self._pressure_signals if item[0] != lease_id
        }
        self._safe_terminate(worker.process)
        self._release_job(worker.process)
        current_state = self._current_attempt_state(worker.request.attempt_id)
        if current_state not in {"SUCCEEDED", "FAILED", "CANCELLED", "LOST"}:
            try:
                self.tasks.fail_attempt_before_start(
                    worker.request.attempt_id,
                    error_category=error_code,
                    error_message=message,
                    reason_code=reason_code,
                )
            except Exception:
                # The acknowledgement caller owns the original admission
                # error.  Read back below and still close any accepted
                # operation receipt instead of leaving it RUNNING/ACCEPTED.
                pass
            current_state = self._current_attempt_state(worker.request.attempt_id)
        if current_state not in {"SUCCEEDED", "CANCELLED"}:
            self._mark_receipt_failed(
                worker.request.attempt_id,
                error_code,
            )
        self._close_lease(lease_id, revoke=True)

    def _mark_receipt_failed(self, attempt_id: str, error_code: str) -> None:
        try:
            receipt = self.progress_persistence.receipt_for_attempt(attempt_id)
        except (AttributeError, KeyError):
            return
        if receipt.state not in {"ACCEPTED", "RUNNING"}:
            return
        try:
            if receipt.state == "ACCEPTED":
                self.progress_persistence.transition_receipt(
                    receipt.operation_receipt_id,
                    expected_state="ACCEPTED",
                    new_state="FAILED",
                    error_code=error_code,
                )
            else:
                self.progress_persistence.transition_receipt(
                    receipt.operation_receipt_id,
                    expected_state="RUNNING",
                    new_state="FAILED",
                    error_code=error_code,
                )
        except (ReceiptStateConflict, KeyError, ValueError):
            return

    def _terminate_lost(self, lease_id: str, reason: str, *, already_expired: bool = False) -> None:
        if self._defer_product_termination_if_live(
            lease_id,
            _PendingTermination(
                kind="LOST",
                message=reason,
                already_expired=already_expired,
            ),
        ):
            return
        worker = self.workers.pop(lease_id, None)
        if worker:
            self._clear_attempt_proposals(worker.request.attempt_id)
            self._safe_terminate(worker.process)
            self._release_job(worker.process)
            attempt_id = worker.request.attempt_id
        else:
            attempt_id = self.leases.persistence.require(lease_id).attempt_id
            self._clear_attempt_proposals(attempt_id)
        current_state = self._current_attempt_state(attempt_id)
        transition_error: Exception | None = None
        if current_state not in {"SUCCEEDED", "FAILED", "CANCELLED", "LOST"}:
            try:
                self.tasks.transition_attempt(attempt_id, "WORKER_LOST", error_category=ErrorCategory.WORKER_LOST.value)
            except Exception as error:
                transition_error = error
                current_state = self._current_attempt_state(attempt_id)
        lease_error = self._close_lease(lease_id, revoke=not already_expired)
        self._pressure_signals = {
            item for item in self._pressure_signals if item[0] != lease_id
        }
        if current_state not in {"SUCCEEDED", "CANCELLED"}:
            self._mark_receipt_failed(attempt_id, ErrorCategory.WORKER_LOST.value)
        if transition_error is not None and current_state not in {
            "SUCCEEDED",
            "FAILED",
            "CANCELLED",
            "LOST",
        }:
            raise transition_error
        if lease_error is not None:
            raise lease_error

    def _current_attempt_and_task_state(
        self, attempt_id: str
    ) -> tuple[str | None, str | None]:
        """Read the aggregate owner pair without performing a mutation."""

        persistence = getattr(getattr(self.tasks, "event_log", None), "persistence", None)
        begin = getattr(persistence, "begin", None)
        if not callable(begin):
            return None, None
        try:
            with begin() as unit:
                attempt = unit.require_attempt(attempt_id)
                task = unit.require_task(attempt.task_id)
                return attempt.state.value, task.state.value
        except (KeyError, ValueError):
            return None, None

    def _current_attempt_state(self, attempt_id: str) -> str | None:
        """Read current Attempt truth without mutating the task owner."""

        persistence = getattr(getattr(self.tasks, "event_log", None), "persistence", None)
        begin = getattr(persistence, "begin", None)
        if not callable(begin):
            return None
        try:
            with begin() as unit:
                attempt = unit.require_attempt(attempt_id)
                return attempt.state.value
        except (KeyError, ValueError):
            return None

    def _release(self, lease_id: str) -> None:
        worker = self.workers.get(lease_id)
        if worker is not None:
            self._release_job(worker.process)
            attempt_id = worker.request.attempt_id
        else:
            attempt_id = None
        lease_error = self._close_lease(lease_id, revoke=False)
        self.workers.pop(lease_id, None)
        if attempt_id is not None:
            self._clear_attempt_proposals(attempt_id)
        if lease_error is not None:
            raise lease_error

    def _clear_attempt_proposals(self, attempt_id: str) -> None:
        self.staged_outputs.pop(attempt_id, None)
        self.checkpoint_proposals.pop(attempt_id, None)

    def _close_lease(self, lease_id: str, *, revoke: bool) -> Exception | None:
        """Close durable lease state while always releasing local accounting."""

        error: Exception | None = None
        try:
            if revoke:
                self.leases.revoke(lease_id)
            else:
                self.leases.release(lease_id)
        except Exception as caught:
            error = caught
        finally:
            self.governor.release(lease_id)
        return error

    def _release_job(self, process: WorkerProcess) -> None:
        release = getattr(self.job_controller, "release", None)
        if release is None:
            return
        try:
            release(process)
        except Exception:
            # Terminal resource cleanup is best-effort after the worker has
            # already been fenced; the durable lease/Attempt remains owned by
            # the supervisor.
            pass

    def _defer_product_termination_if_live(
        self, lease_id: str, pending: _PendingTermination
    ) -> bool:
        """Request cleanup without writing Product terminal truth before exit.

        Generic deterministic supervisors retain their historical synchronous
        behavior.  The real Product worker manager owns the process-exit
        proof and calls ``observe_externally_finalized`` after its bounded
        terminate/kill ladder; durable terminal mutations wait for that call.
        """

        if not self.product_terminal_owner:
            return False
        if lease_id in self._pending_terminations:
            return True
        worker = self.workers.get(lease_id)
        if worker is None:
            # There is no OS child left to await. Treat the durable lease as
            # immediately reconcilable; returning True here strands the lease
            # and Attempt after a product-owner restart loses its in-memory
            # worker handle.
            return False
        try:
            if not worker.process.is_alive():
                return False
        except Exception:
            # Do not write a terminal state for an uninspectable child.
            self._pending_terminations[lease_id] = pending
            return True
        self._pending_terminations[lease_id] = pending
        cancel = getattr(worker.process, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass
        self._safe_terminate(worker.process)
        return True

    @staticmethod
    def _safe_terminate(process: WorkerProcess) -> None:
        try:
            process.terminate()
        except Exception:
            # Process cleanup failure must not take down the backend supervisor.
            pass
