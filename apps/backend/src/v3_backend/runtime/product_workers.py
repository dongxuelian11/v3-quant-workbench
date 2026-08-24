"""Production composition for isolated Product Research workers.

The canonical Task aggregate remains in the single SQLite Catalog.  Dispatch,
acknowledgement, heartbeat, cancellation signalling, lease expiry, and resource
admission run through the existing control-plane WorkerSupervisor.  Each child
opens its own ProductRuntime/SQLite unit of work and can only return bounded
typed worker protocol messages over a dedicated multiprocessing pipe.
"""

from __future__ import annotations

import multiprocessing
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from typing import Any

from v3_backend.adapters.sqlite.lease_persistence import SQLiteLeasePersistence
from v3_backend.control_plane.checkpoint_manager import (
    CheckpointManager,
    InMemoryCheckpointPort,
)
from v3_backend.control_plane.event_log import CollectingPublisher, DurableEventLog
from v3_backend.control_plane.lease_manager import LeaseManager
from v3_backend.control_plane.resource_governor import (
    FakeResourceSampler,
    HardwareProfile,
    OperationProfile,
    ResourceGovernor,
)
from v3_backend.control_plane.task_supervisor import TaskSupervisor
from v3_backend.control_plane.worker_supervisor import WorkerSupervisor
from v3_backend.domain.tasks.entities import TASK_TERMINAL_STATES
from v3_backend.errors import ResourceRejectedError
from v3_backend.workers.protocol import (
    PROTOCOL_VERSION,
    Progress,
    WorkerAcknowledge,
    WorkerCancel,
    WorkerHeartbeat,
    WorkerHello,
    WorkerRequest,
    WorkerTerminal,
    validate_command,
    validate_response,
)


DEFAULT_MAX_ACTIVE_RESEARCH_WORKERS = min(4, max(1, (os.cpu_count() or 2) - 1))
PRODUCT_HEARTBEAT_SECONDS = 2
PRODUCT_LEASE_EXPIRY_SECONDS = 10
_PRODUCT_RESEARCH_OPERATION = "ProductEntryService.v1.submitResearch"
_PRODUCT_RESEARCH_RESOURCE_CLASS = "PRODUCT_RESEARCH_CPU"
_PRODUCT_WORK_PROFILES = {
    "RESEARCH": (_PRODUCT_RESEARCH_OPERATION, _PRODUCT_RESEARCH_RESOURCE_CLASS),
    "LOCAL_DATA_IMPORT": (
        "ProductEntryService.v1.importLocalDataset",
        "PRODUCT_DATA_CPU",
    ),
    "FACTOR_STUDY": (
        "ProductEntryService.v1.submitFactorStudy",
        "PRODUCT_FACTOR_CPU",
    ),
}


@dataclass(frozen=True, slots=True)
class ProductResearchWorkerConfig:
    start_delay_seconds: float = 0.0
    provider_mode: str | None = None
    cooperative_cancel: bool = True
    cancel_grace_seconds: float = 5.0
    terminate_timeout_seconds: float = 5.0
    kill_timeout_seconds: float = 2.0
    max_active_workers: int | None = None


@dataclass(frozen=True, slots=True)
class _ResearchWorkerLaunch:
    storage_root: str
    prepared_request: Any
    task_id: str
    run_id: str
    attempt_id: str
    operation_id: str
    work_kind: str
    worker_request: WorkerRequest
    start_delay_seconds: float
    provider_mode: str | None
    cooperative_cancel: bool


def _safe_send(connection: Any, lock: Any, message: object) -> bool:
    try:
        with lock:
            connection.send(message)
        return True
    except (BrokenPipeError, EOFError, OSError):
        return False


def _product_worker_main(
    launch: _ResearchWorkerLaunch,
    cancel_event: Any,
    command_pipe: Any,
    response_pipe: Any,
) -> None:
    """Child entrypoint: typed messages only; canonical writes use child UoWs."""

    send_lock = RLock()
    heartbeat_stop = Event()
    heartbeat: Thread | None = None

    def stop_heartbeat() -> None:
        heartbeat_stop.set()
        if heartbeat is not None:
            heartbeat.join(timeout=0.5)

    def heartbeat_loop() -> None:
        sequence = 0
        while not heartbeat_stop.is_set():
            sequence += 1
            if not _safe_send(
                response_pipe,
                send_lock,
                WorkerHeartbeat(sequence=sequence, rss_bytes=0, scratch_bytes=0),
            ):
                return
            heartbeat_stop.wait(PRODUCT_HEARTBEAT_SECONDS)

    try:
        _safe_send(
            response_pipe,
            send_lock,
            WorkerHello(
                protocol_version=launch.worker_request.protocol_version,
                resource_lease_token=launch.worker_request.resource_lease_token,
            ),
        )
        while True:
            if cancel_event.is_set():
                _safe_send(response_pipe, send_lock, WorkerTerminal("CANCELLED"))
                return
            if not command_pipe.poll(0.05):
                continue
            command = validate_command(command_pipe.recv())
            if isinstance(command, WorkerCancel):
                _safe_send(response_pipe, send_lock, WorkerTerminal("CANCELLED"))
                return
            if (
                command.protocol_version != launch.worker_request.protocol_version
                or command.resource_lease_token != launch.worker_request.resource_lease_token
            ):
                raise ValueError("worker acknowledgement does not match dispatch")
            break

        heartbeat = Thread(target=heartbeat_loop, name="v3-product-heartbeat", daemon=True)
        heartbeat.start()
        _safe_send(
            response_pipe,
            send_lock,
            Progress(0, 3, {"accepted": 1}, phase="DISPATCHED", work_unit="pipeline_phases"),
        )

        if launch.start_delay_seconds > 0:
            if launch.cooperative_cancel:
                if cancel_event.wait(launch.start_delay_seconds):
                    _safe_send(response_pipe, send_lock, WorkerTerminal("CANCELLED"))
                    return
            else:
                time.sleep(launch.start_delay_seconds)
        if cancel_event.is_set():
            _safe_send(response_pipe, send_lock, WorkerTerminal("CANCELLED"))
            return

        from .product_research import _TaskHandles
        from .product_runtime import ProductRuntime

        provider_factory = None
        if launch.provider_mode is not None:
            from .product_release_acceptance import product_release_acceptance_provider_factory

            provider_factory = product_release_acceptance_provider_factory(launch.provider_mode)
        product = ProductRuntime(
            Path(launch.storage_root),
            research_provider_factory=provider_factory,
            reconcile_on_start=False,
        )
        with product.task_persistence.begin() as unit:
            handles = _TaskHandles(
                unit.require_task(launch.task_id),
                unit.require_run(launch.run_id),
                unit.require_attempt(launch.attempt_id),
            )
            unit.commit()
        _safe_send(
            response_pipe,
            send_lock,
            Progress(1, 3, {"sqlite_uow_opened": 1}, phase="EXECUTING", work_unit="pipeline_phases"),
        )
        if cancel_event.is_set():
            _safe_send(response_pipe, send_lock, WorkerTerminal("CANCELLED"))
            return
        if launch.work_kind == "RESEARCH":
            if (
                launch.operation_id != _PRODUCT_WORK_PROFILES["RESEARCH"][0]
                or launch.worker_request.operation_id != launch.operation_id
            ):
                raise ValueError("Product research worker operation binding drifted")
            product.research.execute_accepted(launch.prepared_request, handles)
        elif launch.work_kind == "LOCAL_DATA_IMPORT":
            if (
                launch.operation_id != _PRODUCT_WORK_PROFILES["LOCAL_DATA_IMPORT"][0]
                or launch.worker_request.operation_id != launch.operation_id
            ):
                raise ValueError("Product local-data worker operation binding drifted")
            product.data.execute_accepted(launch.prepared_request, handles)
        elif launch.work_kind == "FACTOR_STUDY":
            if (
                launch.operation_id != _PRODUCT_WORK_PROFILES["FACTOR_STUDY"][0]
                or launch.worker_request.operation_id != launch.operation_id
            ):
                raise ValueError("Product Factor worker operation binding drifted")
            product.factor.execute_accepted(launch.prepared_request, handles)
        else:
            raise ValueError(f"unsupported Product worker kind: {launch.work_kind}")
        stop_heartbeat()
        _safe_send(
            response_pipe,
            send_lock,
            Progress(3, 3, {"canonical_terminal": 1}, phase="PUBLISHED", work_unit="pipeline_phases"),
        )
        _safe_send(response_pipe, send_lock, WorkerTerminal("SUCCEEDED"))
    except Exception as error:
        stop_heartbeat()
        _safe_send(
            response_pipe,
            send_lock,
            WorkerTerminal("FAILED", "INTERNAL_ERROR", type(error).__name__[:128]),
        )
    finally:
        stop_heartbeat()
        try:
            command_pipe.close()
        except (EOFError, OSError):
            pass
        try:
            response_pipe.close()
        except (EOFError, OSError):
            pass


@dataclass
class _SpawnPayload:
    prepared_request: Any
    handles: Any
    operation_id: str
    work_kind: str


@dataclass
class _ProductWorkerProcess:
    process: multiprocessing.Process
    cancel_event: Any
    command_pipe: Any
    response_pipe: Any
    command_lock: Any

    def terminate(self) -> None:
        self.process.terminate()

    def cancel(self) -> None:
        self.cancel_event.set()
        _safe_send(self.command_pipe, self.command_lock, WorkerCancel("CANCEL_REQUESTED"))

    def acknowledge(self, protocol_version: str, resource_lease_token: str) -> None:
        if not _safe_send(
            self.command_pipe,
            self.command_lock,
            WorkerAcknowledge(protocol_version, resource_lease_token),
        ):
            raise RuntimeError("worker acknowledgement pipe is closed")

    def request_checkpoint(self) -> None:
        raise RuntimeError("CHECKPOINT_NOT_AVAILABLE")

    def is_alive(self) -> bool:
        return self.process.is_alive()


class _ProductProcessFactory:
    def __init__(
        self,
        context: Any,
        storage_root: Path,
        *,
        start_delay_seconds: float,
        provider_mode: str | None,
        cooperative_cancel: bool,
    ) -> None:
        self.context = context
        self.storage_root = storage_root
        self.start_delay_seconds = start_delay_seconds
        self.provider_mode = provider_mode
        self.cooperative_cancel = cooperative_cancel
        self._pending: dict[str, _SpawnPayload] = {}
        self._spawned: dict[str, _ProductWorkerProcess] = {}

    def stage(
        self,
        attempt_id: str,
        prepared_request: Any,
        handles: Any,
        *,
        operation_id: str,
        work_kind: str,
    ) -> None:
        if attempt_id in self._pending or attempt_id in self._spawned:
            raise RuntimeError("worker spawn context already exists")
        self._pending[attempt_id] = _SpawnPayload(
            prepared_request,
            handles,
            operation_id,
            work_kind,
        )

    def discard(self, attempt_id: str) -> None:
        self._pending.pop(attempt_id, None)

    def spawn(self, request: WorkerRequest) -> _ProductWorkerProcess:
        payload = self._pending.pop(request.attempt_id)
        receive_pipe, send_pipe = self.context.Pipe(duplex=False)
        command_receive, command_send = self.context.Pipe(duplex=False)
        cancel_event = self.context.Event()
        process = self.context.Process(
            target=_product_worker_main,
            args=(
                _ResearchWorkerLaunch(
                    storage_root=str(self.storage_root),
                    prepared_request=payload.prepared_request,
                    task_id=payload.handles.task.task_id,
                    run_id=payload.handles.run.run_id,
                    attempt_id=payload.handles.attempt.attempt_id,
                    operation_id=payload.operation_id,
                    work_kind=payload.work_kind,
                    worker_request=request,
                    start_delay_seconds=self.start_delay_seconds,
                    provider_mode=self.provider_mode,
                    cooperative_cancel=self.cooperative_cancel,
                ),
                cancel_event,
                command_receive,
                send_pipe,
            ),
            name=f"v3-product-{payload.work_kind.lower()}-{payload.handles.task.task_id}",
            daemon=False,
        )
        process.start()
        send_pipe.close()
        command_receive.close()
        worker = _ProductWorkerProcess(
            process,
            cancel_event,
            command_send,
            receive_pipe,
            RLock(),
        )
        self._spawned[request.attempt_id] = worker
        return worker

    def take(self, attempt_id: str) -> _ProductWorkerProcess:
        return self._spawned.pop(attempt_id)


class _ProductIdentityAllocator:
    _PREFIXES = {
        "WorkerLease": "lea_",
        "Worker": "wrk_",
        "TaskEvent": "tev_",
    }

    def __init__(self, mint: Any) -> None:
        self._mint = mint

    def new(self, object_type: str) -> str:
        try:
            return self._mint(self._PREFIXES[object_type])
        except KeyError as error:
            raise ValueError(f"unsupported Product control-plane identity: {object_type}") from error


@dataclass
class _WorkerSlot:
    worker: _ProductWorkerProcess
    task_id: str
    attempt_id: str
    lease_id: str
    execution_deadline_at: str | None
    handles: Any
    protocol_thread: Thread | None = None

    @property
    def process(self) -> multiprocessing.Process:
        return self.worker.process

    @property
    def cancel_event(self) -> Any:
        return self.worker.cancel_event


class ProductResearchWorkerManager:
    _TRACE_TOMBSTONE_LIMIT = 256
    _RESPONSE_TRACE_LIMIT = 64

    def __init__(
        self,
        product: Any,
        config: ProductResearchWorkerConfig,
    ) -> None:
        from .product_runtime import INLINE_ENVIRONMENT_PROFILE_ID, mint_v3_id

        self._product = product
        self._cancel_grace_seconds = max(0.01, float(config.cancel_grace_seconds))
        self._terminate_timeout_seconds = max(0.01, float(config.terminate_timeout_seconds))
        self._kill_timeout_seconds = max(0.01, float(config.kill_timeout_seconds))
        selected_limit = (
            DEFAULT_MAX_ACTIVE_RESEARCH_WORKERS
            if config.max_active_workers is None
            else int(config.max_active_workers)
        )
        if not 1 <= selected_limit <= DEFAULT_MAX_ACTIVE_RESEARCH_WORKERS:
            raise ValueError(
                "max_active_workers must be between 1 and "
                f"{DEFAULT_MAX_ACTIVE_RESEARCH_WORKERS}"
            )
        self._max_active_workers = selected_limit
        self._context = multiprocessing.get_context("spawn")
        identities = _ProductIdentityAllocator(mint_v3_id)
        lease_persistence = SQLiteLeasePersistence(
            product.database_path,
            identities.new,
            environment_profile_id=INLINE_ENVIRONMENT_PROFILE_ID,
        )
        leases = LeaseManager(lease_persistence)
        governor = ResourceGovernor(
            FakeResourceSampler(),
            HardwareProfile(
                profile_id=INLINE_ENVIRONMENT_PROFILE_ID,
                admitted=True,
                cpu_slots=max(1, selected_limit),
                memory_bytes=max(1, selected_limit) * 1024 * 1024 * 1024,
                max_concurrency=selected_limit,
            ),
        )
        tasks = TaskSupervisor(
            DurableEventLog(product.task_persistence, CollectingPublisher()),
            identities,
            CheckpointManager(InMemoryCheckpointPort()),
        )
        factory = _ProductProcessFactory(
            self._context,
            product.storage_root,
            start_delay_seconds=max(0.0, float(config.start_delay_seconds)),
            provider_mode=config.provider_mode,
            cooperative_cancel=bool(config.cooperative_cancel),
        )
        self.supervisor = WorkerSupervisor(governor, leases, tasks, identities, factory)
        self._lease_persistence = lease_persistence
        self._factory = factory
        self._slots: dict[str, _WorkerSlot] = {}
        self._reservations: set[str] = set()
        self._termination_traces: dict[str, tuple[str, ...]] = {}
        self._response_traces: dict[str, list[object]] = {}
        self._lock = RLock()
        self._stop_monitor = Event()
        self._monitor_error: Exception | None = None
        self._monitor_thread: Thread | None = None

    @property
    def transport_kind(self) -> str:
        return "DEDICATED_COMMAND_AND_RESPONSE_PIPES"

    def reserve_capacity(self) -> str:
        with self._lock:
            self._raise_monitor_error_locked()
            self._reap_locked()
            observed = len(self._slots) + len(self._reservations)
            if observed >= self._max_active_workers:
                raise ResourceRejectedError(
                    "Product worker capacity is exhausted",
                    details={
                        "reason_code": "WORKER_CAPACITY_EXCEEDED",
                        "limit": self._max_active_workers,
                        "observed": observed,
                    },
                )
            token = str(uuid.uuid4())
            self._reservations.add(token)
            return token

    def release_capacity(self, reservation_token: str) -> None:
        with self._lock:
            self._reservations.discard(reservation_token)

    def start(
        self,
        prepared_request: Any,
        handles: Any,
        *,
        reservation_token: str,
        operation_id: str = _PRODUCT_RESEARCH_OPERATION,
        work_kind: str = "RESEARCH",
        resource_class: str = _PRODUCT_RESEARCH_RESOURCE_CLASS,
    ) -> multiprocessing.Process:
        with self._lock:
            self._reap_locked()
            profile = _PRODUCT_WORK_PROFILES.get(work_kind)
            if profile is None or profile != (operation_id, resource_class):
                raise ValueError("Product worker kind/operation/resource binding is not admitted")
            if reservation_token not in self._reservations:
                raise RuntimeError("Product worker capacity reservation is absent or consumed")
            self._reservations.remove(reservation_token)
            task_id = handles.task.task_id
            attempt_id = handles.attempt.attempt_id
            if task_id in self._slots:
                raise RuntimeError("Product Task already owns a child process")
            lease_token = str(uuid.uuid4())
            request = WorkerRequest(
                attempt_id=attempt_id,
                run_id=handles.run.run_id,
                operation_id=operation_id,
                canonical_input={"request_hash": prepared_request.request_hash},
                input_hash=prepared_request.request_hash,
                read_tickets=(),
                staging_namespace=f"attempt/{attempt_id}",
                resource_lease_token=lease_token,
                cancellation_channel=f"cancel/{attempt_id}",
                checkpoint_policy="NOT_AVAILABLE",
            )
            self._factory.stage(
                attempt_id,
                prepared_request,
                handles,
                operation_id=operation_id,
                work_kind=work_kind,
            )
            try:
                lease = self.supervisor.dispatch(
                    request,
                    OperationProfile(
                        operation_id,
                        resource_class,
                        cpu_slots=1,
                        memory_hard_limit_bytes=1024 * 1024 * 1024,
                        scratch_budget_bytes=1024 * 1024 * 1024,
                        heartbeat_interval_seconds=PRODUCT_HEARTBEAT_SECONDS,
                        lease_expiry_seconds=PRODUCT_LEASE_EXPIRY_SECONDS,
                        resumable=False,
                    ),
                )
            except Exception:
                self._factory.discard(attempt_id)
                raise
            worker = self._factory.take(attempt_id)
            slot = _WorkerSlot(
                worker,
                task_id,
                attempt_id,
                lease.lease_id,
                prepared_request.execution_deadline_at,
                handles,
            )
            self._slots[task_id] = slot
            self._ensure_lease_monitor_started_locked()
            try:
                self._lease_persistence.set_process_id(
                    lease.lease_id,
                    worker.process.pid,
                )
                protocol_thread = Thread(
                    target=self._listen,
                    args=(slot,),
                    name=f"v3-worker-protocol-{task_id}",
                    daemon=True,
                )
                protocol_thread.start()
                slot.protocol_thread = protocol_thread
            except Exception:
                self._abort_partial_start(slot)
                raise
            if slot.execution_deadline_at is not None:
                Thread(
                    target=self._monitor_deadline,
                    args=(task_id, slot),
                    name=f"v3-deadline-{task_id}",
                    daemon=True,
                ).start()
            return worker.process

    def _abort_partial_start(self, slot: _WorkerSlot) -> None:
        """Fence a child whose dispatch succeeded but composition did not."""

        if not self.cancel(slot.task_id):
            raise RuntimeError(
                "partially started research child exit could not be confirmed"
            )
        try:
            self.supervisor.leases.revoke(slot.lease_id)
        finally:
            self.supervisor.observe_externally_finalized(slot.lease_id)
            try:
                slot.worker.command_pipe.close()
            except (EOFError, OSError):
                pass
            try:
                slot.worker.response_pipe.close()
            except (EOFError, OSError):
                pass
            with self._lock:
                self._slots.pop(slot.task_id, None)

    def task_process(self, task_id: str) -> multiprocessing.Process | None:
        with self._lock:
            slot = self._slots.get(task_id)
            return None if slot is None else slot.process

    def task_ids(self) -> tuple[str, ...]:
        with self._lock:
            self._reap_locked()
            return tuple(self._slots)

    def has_live_processes(self) -> bool:
        with self._lock:
            return any(slot.process.is_alive() for slot in self._slots.values())

    def termination_trace(self, task_id: str) -> tuple[str, ...]:
        with self._lock:
            return self._termination_traces.get(task_id, ())

    def response_trace(self, task_id: str) -> tuple[object, ...]:
        with self._lock:
            return tuple(self._response_traces.get(task_id, ()))

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            slot = self._slots.get(task_id)
        if slot is None:
            return False
        trace: list[str] = ["COOPERATIVE_CANCEL_REQUESTED"]
        self.supervisor.cancel(slot.attempt_id)
        slot.process.join(self._cancel_grace_seconds)
        if slot.process.is_alive():
            trace.append("TERMINATE_SENT")
            slot.process.terminate()
            slot.process.join(self._terminate_timeout_seconds)
        if slot.process.is_alive():
            trace.append("KILL_SENT")
            slot.process.kill()
            slot.process.join(self._kill_timeout_seconds)
        if not slot.process.is_alive():
            trace.append("EXIT_CONFIRMED")
        with self._lock:
            self._termination_traces[task_id] = tuple(trace)
            while len(self._termination_traces) > self._TRACE_TOMBSTONE_LIMIT:
                del self._termination_traces[next(iter(self._termination_traces))]
        if (
            slot.protocol_thread is not None
            and slot.protocol_thread is not current_thread()
        ):
            slot.protocol_thread.join(timeout=1.0)
        return not slot.process.is_alive()

    def shutdown_all(self) -> None:
        self._stop_monitor.set()
        with self._lock:
            task_ids = tuple(self._slots)
        for task_id in task_ids:
            slot = self._slots.get(task_id)
            if slot is not None and slot.process.is_alive():
                self.cancel(task_id)
            if (
                slot is not None
                and slot.protocol_thread is not None
                and slot.protocol_thread is not current_thread()
            ):
                slot.protocol_thread.join(timeout=1.0)
        with self._lock:
            self._reap_locked(force=True)

    def _record_response(self, task_id: str, response: object) -> None:
        with self._lock:
            trace = self._response_traces.setdefault(task_id, [])
            trace.append(response)
            if len(trace) > self._RESPONSE_TRACE_LIMIT:
                del trace[: len(trace) - self._RESPONSE_TRACE_LIMIT]
            while len(self._response_traces) > self._TRACE_TOMBSTONE_LIMIT:
                del self._response_traces[next(iter(self._response_traces))]

    def _listen(self, slot: _WorkerSlot) -> None:
        terminal: WorkerTerminal | None = None
        protocol_error: Exception | None = None
        try:
            while slot.process.is_alive() or slot.worker.response_pipe.poll(0.1):
                if not slot.worker.response_pipe.poll(0.1):
                    continue
                response = validate_response(slot.worker.response_pipe.recv())
                self._record_response(slot.task_id, response)
                if isinstance(response, WorkerHello):
                    self.supervisor.acknowledge(
                        slot.lease_id,
                        response.protocol_version,
                        response.resource_lease_token,
                    )
                    slot.worker.acknowledge(
                        response.protocol_version,
                        response.resource_lease_token,
                    )
                elif isinstance(response, WorkerHeartbeat):
                    self.supervisor.heartbeat(
                        slot.lease_id,
                        response.sequence,
                        response.rss_bytes,
                        response.scratch_bytes,
                    )
                elif isinstance(response, WorkerTerminal):
                    terminal = response
                    break
        except (EOFError, OSError):
            pass
        except Exception as error:
            protocol_error = error
        finally:
            slot.process.join(timeout=0.5)
            self.supervisor.observe_externally_finalized(slot.lease_id)
            try:
                slot.worker.command_pipe.close()
            except (EOFError, OSError):
                pass
            try:
                slot.worker.response_pipe.close()
            except (EOFError, OSError):
                pass

        if protocol_error is not None:
            self.cancel(slot.task_id)
            self._finalize_if_unowned(slot, protocol_error)
        elif terminal is None and not slot.process.is_alive():
            self._finalize_if_unowned(slot, RuntimeError("worker exited without typed terminal"))
        elif terminal is not None and terminal.status == "FAILED":
            self._finalize_if_unowned(
                slot,
                RuntimeError(terminal.safe_message or "isolated worker failed"),
            )

    def _finalize_if_unowned(self, slot: _WorkerSlot, error: Exception) -> None:
        from .product_runtime import classify_execution_error

        task = self._product.task_persistence.read_task(slot.task_id)
        if task.state in TASK_TERMINAL_STATES or task.state.value == "CANCEL_REQUESTED":
            return
        self._product.execution._finish_failure(
            slot.handles.task,
            slot.handles.run,
            slot.handles.attempt,
            error=error,
            category=classify_execution_error(error),
        )

    def _monitor_expired_leases(self) -> None:
        while not self._stop_monitor.wait(0.25):
            with self._lock:
                if not any(slot.process.is_alive() for slot in self._slots.values()):
                    return
            try:
                lost_attempts = self.supervisor.reap_expired()
            except Exception as error:
                with self._lock:
                    self._monitor_error = error
                return
            if not lost_attempts:
                continue
            with self._lock:
                affected = tuple(
                    slot.task_id
                    for slot in self._slots.values()
                    if slot.attempt_id in lost_attempts
                )
            for task_id in affected:
                self.cancel(task_id)
            self._product.reconciliation_summary = self._product._reconcile_execution_state()

    def _ensure_lease_monitor_started_locked(self) -> None:
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return
        self._monitor_thread = Thread(
            target=self._monitor_expired_leases,
            name="v3-product-lease-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def _raise_monitor_error_locked(self) -> None:
        if self._monitor_error is not None:
            raise RuntimeError("research worker lease monitor failed") from self._monitor_error

    def _monitor_deadline(self, task_id: str, slot: _WorkerSlot) -> None:
        assert slot.execution_deadline_at is not None
        deadline = datetime.fromisoformat(slot.execution_deadline_at[:-1] + "+00:00")
        while slot.process.is_alive():
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                break
            slot.process.join(min(remaining, 0.1))
        if not slot.process.is_alive():
            return
        try:
            self._product.cancel_research_task(
                task_id,
                reason="EXECUTION_DEADLINE_EXPIRED",
            )
        except Exception:
            self.cancel(task_id)

    def _reap_locked(self, *, force: bool = False) -> None:
        for task_id, slot in tuple(self._slots.items()):
            if force or not slot.process.is_alive():
                slot.process.join(timeout=0)
                del self._slots[task_id]


__all__ = [
    "DEFAULT_MAX_ACTIVE_RESEARCH_WORKERS",
    "PRODUCT_HEARTBEAT_SECONDS",
    "PRODUCT_LEASE_EXPIRY_SECONDS",
    "ProductResearchWorkerConfig",
    "ProductResearchWorkerManager",
]
