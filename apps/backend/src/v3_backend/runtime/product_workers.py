"""Production composition for isolated Product Research workers.

The canonical Task aggregate remains in the single SQLite Catalog.  Dispatch,
acknowledgement, heartbeat, cancellation signalling, lease expiry, and resource
admission run through the existing control-plane WorkerSupervisor.  Each child
opens its own ProductRuntime/SQLite unit of work and can only return bounded
typed worker protocol messages over a dedicated multiprocessing pipe.
"""

from __future__ import annotations

import multiprocessing
import hashlib
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
    SQLiteCheckpointPort,
)
from v3_backend.control_plane.event_log import CollectingPublisher, DurableEventLog
from v3_backend.control_plane.lease_manager import LeaseManager
from v3_backend.control_plane.resource_governor import (
    OperationProfile,
    ResourceGovernor,
)
from v3_backend.control_plane.host_resource_probe import SystemHostResourceProbe
from v3_backend.control_plane.task_supervisor import TaskSupervisor
from v3_backend.control_plane.worker_supervisor import WorkerSupervisor
from v3_backend.control_plane.windows_job_object import WindowsJobObjectController
from v3_backend.domain.tasks.entities import TASK_TERMINAL_STATES, TaskState
from v3_backend.domain.tasks.retry_policy import ErrorCategory
from v3_backend.errors import ResourceRejectedError
from v3_backend.provenance.canonical_hash import canonical_sha256
from v3_backend.workers.protocol import (
    FORBIDDEN_WORKER_FIELDS,
    MAX_BOUNDED_JSON_BYTES,
    PROTOCOL_VERSION,
    Progress,
    WorkerAcknowledge,
    WorkerCancel,
    WorkerCheckpointRequest,
    WorkerHeartbeat,
    WorkerHello,
    WorkerPause,
    WorkerProgressAck,
    WorkerResourcePressure,
    WorkerRequest,
    WorkerTerminal,
    decode_command,
    decode_response,
    encode_command,
    encode_response,
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
    "STRATEGY_AUTHORING": (
        "ProductEntryService.v1.publishResearchStrategy",
        "PRODUCT_STRATEGY_CPU",
    ),
    "RESEARCH_BACKTEST": (
        "ProductEntryService.v1.submitResearchBacktest",
        "PRODUCT_BACKTEST_CPU",
    ),
    "RESULT_RECONCILE_VERIFY": (
        "ResultService.v1.reconcileLedger",
        "PRODUCT_RESULT_RECONCILE_CPU",
    ),
    "RESULT_FINALIZE_VERIFY": (
        "ResultService.v1.finalizeResult",
        "PRODUCT_RESULT_FINALIZE_CPU",
    ),
}


class _ProgressStalledError(RuntimeError):
    reason_code = "PROGRESS_STALLED"


class _WorkerExitUnconfirmedError(RuntimeError):
    """A live child must be reaped before its Task can be finalized."""

    defer_task_finalization = True
    reason_code = "WORKER_EXIT_UNCONFIRMED"


def _worker_canonical_input(value: Any) -> dict[str, Any]:
    """Project durable input into protocol-safe, non-authoritative JSON."""

    def project(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: project(child)
                for key, child in item.items()
                if key not in FORBIDDEN_WORKER_FIELDS
            }
        if isinstance(item, list):
            return [project(child) for child in item]
        return item

    projected = project(value)
    if not isinstance(projected, dict):
        raise RuntimeError("RUN_CONTEXT_CORRUPT: canonical Run input projection is not an object")
    return projected


@dataclass(frozen=True, slots=True)
class ProductResearchWorkerConfig:
    start_delay_seconds: float = 0.0
    provider_mode: str | None = None
    cooperative_cancel: bool = True
    cancel_grace_seconds: float = 5.0
    terminate_timeout_seconds: float = 5.0
    kill_timeout_seconds: float = 2.0
    max_active_workers: int | None = None
    job_object_controller: Any | None = None
    progress_stall_seconds: int | None = None


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
    if isinstance(
        message,
        (
            WorkerAcknowledge,
            WorkerCancel,
            WorkerCheckpointRequest,
            WorkerPause,
            WorkerProgressAck,
            WorkerResourcePressure,
        ),
    ):
        frame = encode_command(message)
    elif isinstance(
        message,
        (WorkerHello, WorkerHeartbeat, Progress, WorkerTerminal),
    ):
        frame = encode_response(message)
    else:
        raise ValueError("unknown worker IPC message")
    try:
        with lock:
            connection.send_bytes(frame)
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
    control_stop = Event()
    control_thread: Thread | None = None
    catalog_lease = None
    catalog_lease_entered = False

    def stop_heartbeat() -> None:
        heartbeat_stop.set()
        if heartbeat is not None:
            heartbeat.join(timeout=0.5)

    def stop_control() -> None:
        control_stop.set()
        if control_thread is not None:
            control_thread.join(timeout=0.5)

    def control_loop() -> None:
        while not control_stop.is_set():
            try:
                if not command_pipe.poll(0.05):
                    continue
                command = decode_command(
                    command_pipe.recv_bytes(maxlength=MAX_BOUNDED_JSON_BYTES)
                )
                if isinstance(command, WorkerCancel):
                    cancel_event.set()
                elif isinstance(command, WorkerPause):
                    cancel_event.set()
                elif isinstance(command, WorkerResourcePressure):
                    if command.observed >= command.hard_limit:
                        cancel_event.set()
                elif isinstance(command, (WorkerCheckpointRequest, WorkerProgressAck)):
                    # Product domain adapters currently have no resumable
                    # checkpoint bytes.  The request is still consumed as a
                    # typed control signal and cannot publish anything itself.
                    continue
            except Exception:
                # A closed or malformed parent command channel is not a
                # permission to keep executing an unobservable child.
                cancel_event.set()
                return

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
            command = decode_command(
                command_pipe.recv_bytes(maxlength=MAX_BOUNDED_JSON_BYTES)
            )
            if isinstance(command, WorkerCancel):
                _safe_send(response_pipe, send_lock, WorkerTerminal("CANCELLED"))
                return
            if (
                command.protocol_version != launch.worker_request.protocol_version
                or command.resource_lease_token != launch.worker_request.resource_lease_token
            ):
                raise ValueError("worker acknowledgement does not match dispatch")
            break

        control_thread = Thread(
            target=control_loop,
            name="v3-product-control-listener",
            daemon=True,
        )
        control_thread.start()

        from v3_backend.migrations.upgrade import catalog_runtime_lease
        from .product_runtime import CATALOG_FILENAME

        catalog_lease = catalog_runtime_lease(
            Path(launch.storage_root) / CATALOG_FILENAME,
            busy_timeout_ms=5_000,
        )
        catalog_lease.__enter__()
        catalog_lease_entered = True
        # Publish the first advancement before the liveness loop.  A parent
        # observing the first heartbeat must never be able to conclude that a
        # worker has progressed while the initial durable progress record is
        # still absent (the two pipes are independently scheduled).
        _safe_send(
            response_pipe,
            send_lock,
            Progress(
                0,
                3,
                {"accepted": 1},
                phase="DISPATCHED",
                work_unit="pipeline_phases",
            ),
        )
        heartbeat = Thread(target=heartbeat_loop, name="v3-product-heartbeat", daemon=True)
        heartbeat.start()

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
        product = ProductRuntime.for_worker(
            Path(launch.storage_root),
            research_provider_factory=provider_factory,
            execution_deadline_at=launch.worker_request.deadline_at,
            correlation_id=launch.worker_request.correlation_id,
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
            Progress(
                1,
                3,
                {"runtime_context_bound": 1},
                phase="EXECUTING",
                work_unit="pipeline_phases",
            ),
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
        elif launch.work_kind == "STRATEGY_AUTHORING":
            if (
                launch.operation_id
                != _PRODUCT_WORK_PROFILES["STRATEGY_AUTHORING"][0]
                or launch.worker_request.operation_id != launch.operation_id
            ):
                raise ValueError("Product Strategy worker operation binding drifted")
            product.strategy.execute_accepted(launch.prepared_request, handles)
        elif launch.work_kind == "RESEARCH_BACKTEST":
            if (
                launch.operation_id
                != _PRODUCT_WORK_PROFILES["RESEARCH_BACKTEST"][0]
                or launch.worker_request.operation_id != launch.operation_id
            ):
                raise ValueError("Product Backtest worker operation binding drifted")
            product.backtest.execute_accepted(launch.prepared_request, handles)
        elif launch.work_kind == "RESULT_RECONCILE_VERIFY":
            if (
                launch.operation_id
                != _PRODUCT_WORK_PROFILES["RESULT_RECONCILE_VERIFY"][0]
                or launch.worker_request.operation_id != launch.operation_id
            ):
                raise ValueError(
                    "Product Result reconcile worker operation binding drifted"
                )
            product.results.execute_reconcile_accepted(
                launch.prepared_request, handles
            )
        elif launch.work_kind == "RESULT_FINALIZE_VERIFY":
            if (
                launch.operation_id
                != _PRODUCT_WORK_PROFILES["RESULT_FINALIZE_VERIFY"][0]
                or launch.worker_request.operation_id != launch.operation_id
            ):
                raise ValueError(
                    "Product Result finalize worker operation binding drifted"
                )
            product.results.execute_finalize_accepted(
                launch.prepared_request, handles
            )
        else:
            raise ValueError(f"unsupported Product worker kind: {launch.work_kind}")
        if cancel_event.is_set():
            # Never emit success telemetry after a fail-closed control signal;
            # the durable Product owner still wins if it already crossed its
            # commit boundary.
            _safe_send(response_pipe, send_lock, WorkerTerminal("CANCELLED"))
            return
        stop_heartbeat()
        # ProductRuntime owns the final PUBLISHED progress row and writes it
        # atomically with Attempt/Task/receipt terminality.  A post-return
        # pipe message would be late, non-durable telemetry and could be
        # rejected after the Attempt had already become terminal.
        _safe_send(response_pipe, send_lock, WorkerTerminal("SUCCEEDED"))
    except Exception as error:
        stop_heartbeat()
        _safe_send(
            response_pipe,
            send_lock,
            WorkerTerminal("FAILED", "INTERNAL_ERROR", type(error).__name__[:128]),
        )
    finally:
        stop_control()
        stop_heartbeat()
        if catalog_lease is not None and catalog_lease_entered:
            catalog_lease.__exit__(None, None, None)
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
    deadline_at: str | None = None

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
        if not _safe_send(
            self.command_pipe,
            self.command_lock,
            WorkerCheckpointRequest(
                "CONTROL_PLANE_REQUEST",
                self.deadline_at or wire_time(datetime.now(timezone.utc)),
            ),
        ):
            raise RuntimeError("checkpoint request pipe is closed")

    def pause(self, reason: str) -> None:
        if not _safe_send(
            self.command_pipe,
            self.command_lock,
            WorkerPause(reason),
        ):
            raise RuntimeError("pause request pipe is closed")

    def acknowledge_progress(self, sequence: int) -> None:
        if not _safe_send(
            self.command_pipe,
            self.command_lock,
            WorkerProgressAck(sequence),
        ):
            raise RuntimeError("progress acknowledgement pipe is closed")

    def signal_resource_pressure(
        self, kind: str, observed: int, soft_limit: int, hard_limit: int
    ) -> None:
        if not _safe_send(
            self.command_pipe,
            self.command_lock,
            WorkerResourcePressure(kind, observed, soft_limit, hard_limit),
        ):
            raise RuntimeError("resource pressure pipe is closed")

    def is_alive(self) -> bool:
        return self.process.is_alive()


class _ProductProcessFactory:
    _SPAWN_CLEANUP_TIMEOUT_SECONDS = 0.5

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
        worker = self._spawned.pop(attempt_id, None)
        if worker is None:
            return
        # WorkerSupervisor may fail after ``spawn`` has returned but before it
        # has taken ownership of the process (for example while persisting
        # DISPATCHED).  Do not leave that child and its parent-side pipe
        # handles hidden in the factory's staging map.
        self._terminate_started_process(worker.process)
        self._close_endpoint(worker.command_pipe)
        self._close_endpoint(worker.response_pipe)

    @staticmethod
    def _close_endpoint(endpoint: Any | None) -> None:
        if endpoint is None:
            return
        try:
            endpoint.close()
        except (EOFError, OSError):
            pass

    @classmethod
    def _terminate_started_process(cls, process: Any) -> None:
        """Bound cleanup for a child created before factory admission returned."""

        try:
            alive = bool(process.is_alive())
        except Exception:
            # A Process implementation may reject is_alive() after a partial
            # start.  Try the bounded termination ladder anyway; every step
            # is best effort and the original spawn error remains authoritative.
            alive = True
        if not alive:
            try:
                # A child may have exited before dispatch returned.  Joining
                # the already-dead process still releases the multiprocessing
                # handle and is safe for the partial-start cleanup path.
                process.join(0)
            except Exception:
                pass
            return
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.join(cls._SPAWN_CLEANUP_TIMEOUT_SECONDS)
        except Exception:
            pass
        try:
            if process.is_alive():
                process.kill()
                process.join(cls._SPAWN_CLEANUP_TIMEOUT_SECONDS)
        except Exception:
            pass

    def spawn(self, request: WorkerRequest) -> _ProductWorkerProcess:
        payload = self._pending.pop(request.attempt_id)
        receive_pipe = send_pipe = command_receive = command_send = None
        process = None
        started = False
        try:
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
            started = True
            # These are the parent-side duplicates.  A close failure must not
            # make a supervised child unreachable; the worker handle returned
            # below remains the owner of the live process and its active pipes.
            self._close_endpoint(send_pipe)
            self._close_endpoint(command_receive)
            worker = _ProductWorkerProcess(
                process,
                cancel_event,
                command_send,
                receive_pipe,
                RLock(),
                request.deadline_at,
            )
            self._spawned[request.attempt_id] = worker
            return worker
        except BaseException:
            # A Process.start() or worker construction failure occurs after the
            # lease has been admitted but before WorkerSupervisor receives a
            # process handle.  Close every endpoint and fence any child that
            # did start, otherwise the supervisor could finalize a Task while
            # an untracked OS process still owns its lease resources.
            if process is not None:
                try:
                    live = started or bool(process.is_alive())
                except Exception:
                    live = started
                if live:
                    self._terminate_started_process(process)
            for endpoint in (send_pipe, command_receive, command_send, receive_pipe):
                self._close_endpoint(endpoint)
            self._spawned.pop(request.attempt_id, None)
            raise

    def take(self, attempt_id: str) -> _ProductWorkerProcess:
        return self._spawned.pop(attempt_id)

    def detach_spawned(self, attempt_id: str) -> _ProductWorkerProcess | None:
        """Transfer a spawned child to the supervisor's failure owner.

        ``take`` is deliberately strict for the normal hand-off.  When that
        hand-off itself fails, the supervisor may still own a live child.  A
        failure path must be able to remove the factory bookkeeping without
        terminating or closing the process before ProductResearchWorkerManager
        can install its exit-proof reaper.
        """

        return self._spawned.pop(attempt_id, None)


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
    checkpoint_policy: str = "NOT_AVAILABLE"
    progress_stall_seconds: int | None = None
    started_monotonic: float = 0.0
    stall_signalled: bool = False
    stall_action_at: float | None = None
    protocol_thread: Thread | None = None
    # The child lease protects the worker's Catalog UoW.  This parent-side
    # lease extends the same replacement fence through process exit and the
    # listener's durable outcome reconciliation.  A Task can become terminal
    # before either of those boundaries, especially on Windows where an
    # exiting SQLite process may still own WAL sidecar handles.
    catalog_lease: Any | None = None

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
        if config.progress_stall_seconds is not None and (
            isinstance(config.progress_stall_seconds, bool)
            or not isinstance(config.progress_stall_seconds, int)
            or config.progress_stall_seconds <= 0
        ):
            raise ValueError("progress_stall_seconds must be a positive integer")
        self._configured_progress_stall_seconds = config.progress_stall_seconds
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
        scratch_root = product.storage_root / "runtime" / "scratch"
        scratch_root.mkdir(parents=True, exist_ok=True)
        governor = ResourceGovernor(
            host_probe=SystemHostResourceProbe(scratch_root),
            scratch_root=scratch_root,
            runtime_generation_id=product.runtime_generation_id,
        )
        self._resource_policy = governor.policy
        tasks = TaskSupervisor(
            DurableEventLog(product.task_persistence, CollectingPublisher()),
            identities,
            CheckpointManager(
                SQLiteCheckpointPort(product.database_path, product.artifact_store),
                require_complete_compatibility=True,
            ),
        )
        factory = _ProductProcessFactory(
            self._context,
            product.storage_root,
            start_delay_seconds=max(0.0, float(config.start_delay_seconds)),
            provider_mode=config.provider_mode,
            cooperative_cancel=bool(config.cooperative_cancel),
        )
        # The shipped Product runtime is Windows x64 only. Keep the native
        # Job Object as the Windows default, while allowing Ubuntu portability
        # CI (and explicit platform adapters) to exercise the lifecycle
        # without pretending that a Windows hard-enforcement primitive exists.
        # A non-Windows product caller must inject its own controller before
        # it can claim resource enforcement; there is no soft fallback here.
        self._job_controller = (
            config.job_object_controller
            if config.job_object_controller is not None
            else (WindowsJobObjectController() if os.name == "nt" else None)
        )
        self.supervisor = WorkerSupervisor(
            governor,
            leases,
            tasks,
            identities,
            factory,
            job_controller=self._job_controller,
            progress_persistence=product.progress_persistence,
            product_terminal_owner=True,
        )
        self._lease_persistence = lease_persistence
        self._factory = factory
        self._slots: dict[str, _WorkerSlot] = {}
        self._reservations: set[str] = set()
        self._termination_traces: dict[str, tuple[str, ...]] = {}
        self._response_traces: dict[str, list[object]] = {}
        # Admission/cancellation serialization must not reuse the state lock:
        # cancellation waits for the protocol listener, while the listener
        # records terminal responses under the state lock.  Holding the same
        # lock across that wait would strand the listener and its pipe handles.
        self._admission_lock = RLock()
        self._lock = RLock()
        self._stop_monitor = Event()
        self._monitor_error: Exception | None = None
        self._monitor_thread: Thread | None = None

    @property
    def transport_kind(self) -> str:
        return "DEDICATED_COMMAND_AND_RESPONSE_PIPES"

    @staticmethod
    def profile_for_operation(operation_id: str) -> tuple[str, str]:
        """Resolve the one admitted Product worker profile for an operation.

        TaskControl asks the existing worker owner for this binding so the
        runtime composition does not maintain a second operation/profile
        registry beside ``_PRODUCT_WORK_PROFILES``.
        """

        for work_kind, (candidate, resource_class) in _PRODUCT_WORK_PROFILES.items():
            if candidate == operation_id:
                return work_kind, resource_class
        raise KeyError(operation_id)

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

    def with_admission_lock(self, callback: Any) -> Any:
        """Run a Product admission/cancellation operation under one lock.

        Durable cancellation intent must not be recorded in the gap between a
        queued start's last read and its worker dispatch.  ProductRuntime uses
        this small owner seam so cancellation and ``start`` serialize without
        exposing the internal lock to the facade layer.
        """

        with self._admission_lock:
            return callback()

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
        with self._admission_lock, self._lock:
            self._reap_locked()
            profile = _PRODUCT_WORK_PROFILES.get(work_kind)
            if profile is None or profile != (operation_id, resource_class):
                raise ValueError("Product worker kind/operation/resource binding is not admitted")
            stall_seconds = self._configured_progress_stall_seconds
            if stall_seconds is None and self._resource_policy is not None:
                stall_seconds = self._resource_policy.operation_stall_seconds.get(
                    work_kind,
                    self._resource_policy.operation_stall_seconds.get("RESULT_VERIFY"),
                )
            if reservation_token not in self._reservations:
                raise RuntimeError("Product worker capacity reservation is absent or consumed")
            self._reservations.remove(reservation_token)
            task_id = handles.task.task_id
            attempt_id = handles.attempt.attempt_id
            if task_id in self._slots:
                raise RuntimeError("Product Task already owns a child process")
            current_task = self._product.task_persistence.read_task(task_id)
            if current_task.state is TaskState.CANCEL_REQUESTED:
                # A cancel can win before the worker has been registered.  No
                # OS child exists yet, so close the queued Attempt immediately
                # under this same admission lock instead of spawning work that
                # cannot receive the already-issued cancel signal.
                self._product.cancel_research_task(
                    task_id,
                    reason="CANCEL_REQUESTED_BEFORE_WORKER_ADMISSION",
                )
                raise RuntimeError("Product Task was cancelled before worker admission")
            if current_task.state in TASK_TERMINAL_STATES:
                raise RuntimeError("Product Task is already terminal before worker admission")
            lease_token = str(uuid.uuid4())
            context_reader = getattr(
                self._product.progress_persistence, "execution_context_for_attempt", None
            )
            if not callable(context_reader):
                raise RuntimeError("RUN_CONTEXT_CORRUPT: durable execution context reader is unavailable")
            try:
                context = context_reader(attempt_id)
            except Exception as error:
                raise RuntimeError(f"RUN_CONTEXT_CORRUPT: {error}") from error
            if any(
                context.get(name) != expected
                for name, expected in (
                    ("task_id", task_id),
                    ("run_id", handles.run.run_id),
                    ("attempt_id", attempt_id),
                    ("operation_id", operation_id),
                    ("input_hash", handles.run.identity.normalized_input_hash),
                    ("code_version", handles.run.identity.code_version),
                    ("environment_profile", handles.run.identity.environment_profile),
                )
            ):
                raise RuntimeError("RUN_CONTEXT_CORRUPT: immutable Task/Run context drifted")
            context_generation = context.get("runtime_generation_id")
            if context_generation not in {None, self._product.runtime_generation_id}:
                raise RuntimeError("RUN_CONTEXT_CORRUPT: Attempt runtime generation drifted")
            canonical_input = context.get("canonical_input")
            if not isinstance(canonical_input, dict):
                raise RuntimeError("RUN_CONTEXT_CORRUPT: canonical Run input is not an object")
            durable_semantic = canonical_input.get("semantic_request")
            if not isinstance(durable_semantic, dict):
                raise RuntimeError("RUN_CONTEXT_CORRUPT: durable semantic request is absent")
            protocol_canonical_input = _worker_canonical_input(canonical_input)
            durable_request_hash = canonical_input.get("request_hash")
            prepared_request_hash = getattr(prepared_request, "request_hash", None)
            if (
                not isinstance(durable_request_hash, str)
                or len(durable_request_hash) != 64
                or durable_request_hash != durable_request_hash.lower()
                or any(char not in "0123456789abcdef" for char in durable_request_hash)
            ):
                raise RuntimeError("RUN_CONTEXT_CORRUPT: durable request hash is invalid")
            if prepared_request_hash != durable_request_hash:
                raise RuntimeError("RUN_CONTEXT_CORRUPT: prepared request hash drifted")
            try:
                if canonical_sha256(durable_semantic) != str(context["input_hash"]):
                    raise RuntimeError("RUN_CONTEXT_CORRUPT: durable semantic input hash drifted")
                expected_request_hash = canonical_sha256(
                    {
                        "operation_id": operation_id,
                        "semantic_request": durable_semantic,
                    }
                )
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeError("RUN_CONTEXT_CORRUPT: durable semantic input is not canonical") from error
            if expected_request_hash != durable_request_hash:
                raise RuntimeError("RUN_CONTEXT_CORRUPT: durable request hash does not match semantic input")
            prepared_semantic = getattr(prepared_request, "semantic", None)
            if not isinstance(prepared_semantic, dict) or prepared_semantic != durable_semantic:
                raise RuntimeError("RUN_CONTEXT_CORRUPT: prepared semantic request drifted")
            if (
                getattr(prepared_request, "project_id", None) != handles.task.project_id
                or getattr(prepared_request, "project_context_revision_id", None)
                != handles.run.identity.project_context_revision_id
                or getattr(prepared_request, "scope", None) != canonical_input.get("scope")
            ):
                raise RuntimeError("RUN_CONTEXT_CORRUPT: prepared request owner binding drifted")
            task_deadline_at = context.get("task_deadline_at")
            attempt_deadline_at = context.get("attempt_deadline_at")
            if (
                task_deadline_at is not None
                and attempt_deadline_at is not None
                and task_deadline_at != attempt_deadline_at
            ):
                raise RuntimeError("RUN_CONTEXT_CORRUPT: Task and Attempt deadlines differ")
            execution_deadline_at = attempt_deadline_at or task_deadline_at
            prepared_deadline = getattr(prepared_request, "execution_deadline_at", None)
            if prepared_deadline != execution_deadline_at:
                raise RuntimeError("RUN_CONTEXT_CORRUPT: prepared deadline drifted")
            receipt = None
            try:
                receipt = self._product.progress_persistence.receipt_for_attempt(attempt_id)
            except KeyError:
                pass
            if execution_deadline_at is not None and receipt is None:
                raise RuntimeError("deadline-bound Product Task has no durable operation receipt")
            if receipt is not None:
                if receipt.operation_id != operation_id or receipt.attempt_id != attempt_id:
                    raise RuntimeError("operation receipt is not bound to this Product worker")
                if receipt.state not in {"ACCEPTED", "RUNNING"}:
                    raise RuntimeError(
                        f"operation receipt cannot start from {receipt.state}"
                    )
                if (
                    receipt.runtime_generation_id is not None
                    and receipt.runtime_generation_id != self._product.runtime_generation_id
                ):
                    raise RuntimeError("operation receipt runtime generation drifted")
                if execution_deadline_at is not None:
                    durable_deadline = datetime.fromisoformat(
                        execution_deadline_at[:-1] + "+00:00"
                    )
                    if durable_deadline.astimezone(timezone.utc) != receipt.deadline_at:
                        raise RuntimeError("operation receipt deadline does not match Product request")
                execution_deadline_at = (
                    receipt.deadline_at.astimezone(timezone.utc)
                    .isoformat(timespec="microseconds")
                    .replace("+00:00", "Z")
                )
            request = WorkerRequest(
                attempt_id=attempt_id,
                run_id=handles.run.run_id,
                operation_id=operation_id,
                canonical_input=protocol_canonical_input,
                input_hash=handles.run.identity.normalized_input_hash,
                read_tickets=(),
                staging_namespace=f"attempt/{attempt_id}",
                resource_lease_token=lease_token,
                cancellation_channel=f"cancel/{attempt_id}",
                checkpoint_policy="NOT_AVAILABLE",
                correlation_id=None if receipt is None else receipt.correlation_id,
                operation_receipt_id=(
                    None if receipt is None else receipt.operation_receipt_id
                ),
                deadline_at=execution_deadline_at,
                runtime_generation_id=self._product.runtime_generation_id,
                operation_schema_version=str(context["operation_schema_version"]),
                code_version=handles.run.identity.code_version,
                environment_profile_id=handles.run.identity.environment_profile,
                resource_policy_version=(
                    None
                    if str(context["resolved_resource_hash"]) == "0" * 64
                    else str(context["resource_policy_version"])
                ),
                resolved_resource_hash=(
                    None
                    if str(context["resolved_resource_hash"]) == "0" * 64
                    else str(context["resolved_resource_hash"])
                ),
                compatibility_hash=(
                    None
                    if str(context["compatibility_hash"]) == "0" * 64
                    else str(context["compatibility_hash"])
                ),
            )
            catalog_lease = None
            try:
                # The existing lease protocol is also the Catalog replacement
                # protocol. Hold a parent-side marker from spawn admission
                # until the supervisor has observed process exit and finished
                # its typed terminal reconciliation.
                from v3_backend.migrations.upgrade import catalog_runtime_lease

                catalog_lease = catalog_runtime_lease(
                    self._product.database_path,
                    busy_timeout_ms=5_000,
                )
                catalog_lease.__enter__()
                self._factory.stage(
                    attempt_id,
                    prepared_request,
                    handles,
                    operation_id=operation_id,
                    work_kind=work_kind,
                )
            except Exception:
                self._factory.discard(attempt_id)
                self._close_catalog_lease_handle(catalog_lease)
                raise
            try:
                lease = self.supervisor.dispatch(
                    request,
                    OperationProfile(
                        operation_id,
                        resource_class,
                        preset="CONSERVATIVE",
                        cpu_slots=1,
                        memory_hard_limit_bytes=1024 * 1024 * 1024,
                        scratch_budget_bytes=2 * 1024 * 1024 * 1024,
                        heartbeat_interval_seconds=PRODUCT_HEARTBEAT_SECONDS,
                        lease_expiry_seconds=PRODUCT_LEASE_EXPIRY_SECONDS,
                        resumable=False,
                        progress_stall_seconds=stall_seconds,
                    ),
                )
            except Exception:
                try:
                    self._factory.discard(attempt_id)
                finally:
                    self._close_catalog_lease_handle(catalog_lease)
                raise
            try:
                worker = self._factory.take(attempt_id)
            except Exception as error:
                # ``dispatch`` has already handed the same process wrapper to
                # WorkerSupervisor.  Preserve that handle across a failed
                # factory transfer so a live child cannot be finalized by the
                # Product caller before an exit proof exists.
                detached = self._factory.detach_spawned(attempt_id)
                supervised = self.supervisor.workers.get(lease.lease_id)
                if detached is None and supervised is not None:
                    detached = supervised.process
                if detached is None:
                    try:
                        self._factory.discard(attempt_id)
                        self.supervisor.abort_before_start(
                            lease.lease_id,
                            f"worker handle transfer failed: {error}",
                        )
                    finally:
                        self._close_catalog_lease_handle(catalog_lease)
                    raise
                slot = _WorkerSlot(
                    detached,
                    task_id,
                    attempt_id,
                    lease.lease_id,
                    execution_deadline_at,
                    handles,
                    checkpoint_policy=request.checkpoint_policy,
                    progress_stall_seconds=stall_seconds,
                    started_monotonic=time.monotonic(),
                    catalog_lease=catalog_lease,
                )
                self._slots[task_id] = slot
                try:
                    self._abort_partial_start_without_state_lock(slot)
                except _WorkerExitUnconfirmedError as exit_error:
                    raise exit_error from error
                raise
            slot = _WorkerSlot(
                worker,
                task_id,
                attempt_id,
                lease.lease_id,
                execution_deadline_at,
                handles,
                checkpoint_policy=request.checkpoint_policy,
                progress_stall_seconds=stall_seconds,
                started_monotonic=time.monotonic(),
                catalog_lease=catalog_lease,
            )
            self._slots[task_id] = slot
            try:
                self._ensure_lease_monitor_started_locked()
                self._lease_persistence.set_process_id(
                    lease.lease_id,
                    worker.process.pid,
                )
                self._lease_persistence.set_process_identity(
                    lease.lease_id,
                    process_id=worker.process.pid,
                    process_identity_hash=hashlib.sha256(
                        f"{self._product.runtime_generation_id}:{worker.process.pid}".encode(
                            "utf-8"
                        )
                    ).hexdigest(),
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
                self._abort_partial_start_without_state_lock(slot)
                raise
            try:
                if slot.execution_deadline_at is not None:
                    Thread(
                        target=self._monitor_deadline,
                        args=(task_id, slot),
                        name=f"v3-deadline-{task_id}",
                        daemon=True,
                    ).start()
            except Exception:
                self._abort_partial_start_without_state_lock(slot)
                raise
            return worker.process

    def _abort_partial_start_without_state_lock(self, slot: _WorkerSlot) -> None:
        """Abort a start while letting the protocol listener acquire state."""

        # ``start`` owns both admission and state locks.  The abort path waits
        # for the child/listener, and the listener records responses under the
        # state lock.  Release only the one state-lock acquisition made by
        # ``start``; admission remains held so a concurrent cancel cannot
        # interleave with this failure fence.
        self._lock.release()
        try:
            self._abort_partial_start(slot)
        finally:
            self._lock.acquire()

    def _abort_partial_start(self, slot: _WorkerSlot) -> None:
        """Fence a child whose dispatch succeeded but composition did not."""

        if not self.cancel(slot.task_id):
            error = _WorkerExitUnconfirmedError(
                "partially started research child exit could not be confirmed"
            )
            with self._lock:
                self._monitor_error = error
            # The caller must not finalize the Task while the OS process is
            # still live.  Keep the slot and let the bounded reaper perform
            # the same observe/reconcile sequence after exit confirmation.
            try:
                Thread(
                    target=self._observe_after_exit,
                    args=(slot, None, error),
                    name=f"v3-worker-start-reaper-{slot.task_id}",
                    daemon=True,
                ).start()
            except Exception as reaper_error:
                with self._lock:
                    self._monitor_error = reaper_error
                # Keep the exit-proof guarantee even if the process-wide
                # thread budget is exhausted: the bounded reaper can run on
                # this caller thread, and the original admission error still
                # remains the exception exposed to the Product caller.
                self._observe_after_exit(slot, None, reaper_error)
                raise error from reaper_error
            raise error
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
            self._release_catalog_lease(slot)
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
        return self._confirm_slot_exit(
            task_id,
            slot,
            request_cooperative_cancel=True,
        )

    def confirm_terminal_exit(self, task_id: str) -> bool:
        """Wait for a canonically terminal Task's process without rewriting Task truth.

        A child persists the Task terminal transition before it emits its typed
        terminal protocol message and exits.  Shutdown may therefore observe a
        terminal Task with a still-live process.  That process still has to be
        joined (and, if it fails to wind down, escalated), but the already-owned
        canonical Task state must not be changed to CANCELLED.
        """
        with self._lock:
            slot = self._slots.get(task_id)
        if slot is None:
            return True
        return self._confirm_slot_exit(
            task_id,
            slot,
            request_cooperative_cancel=False,
        )

    def _confirm_slot_exit(
        self,
        task_id: str,
        slot: _WorkerSlot,
        *,
        request_cooperative_cancel: bool,
    ) -> bool:
        trace: list[str] = []
        if request_cooperative_cancel:
            trace.append("COOPERATIVE_CANCEL_REQUESTED")
            try:
                self.supervisor.cancel(slot.attempt_id)
            except Exception:
                # A failed/closed command pipe is not an exit proof.  Continue
                # through the OS terminate/kill ladder and let the return
                # value decide whether Product finalization may proceed.
                trace.append("COOPERATIVE_CANCEL_FAILED")
        else:
            trace.append("TERMINAL_EXIT_WAIT_STARTED")
        slot.process.join(self._cancel_grace_seconds)
        if slot.process.is_alive():
            trace.append("TERMINATE_SENT")
            try:
                slot.process.terminate()
            except Exception as error:
                trace.append("TERMINATE_FAILED")
                with self._lock:
                    self._monitor_error = error
            slot.process.join(self._terminate_timeout_seconds)
        if slot.process.is_alive():
            trace.append("KILL_SENT")
            try:
                slot.process.kill()
            except Exception as error:
                trace.append("KILL_FAILED")
                with self._lock:
                    self._monitor_error = error
            slot.process.join(self._kill_timeout_seconds)
        if (
            slot.protocol_thread is not None
            and slot.protocol_thread is not current_thread()
        ):
            slot.protocol_thread.join(timeout=1.0)
        if not slot.process.is_alive():
            trace.append("EXIT_CONFIRMED")
        with self._lock:
            self._termination_traces[task_id] = tuple(trace)
            while len(self._termination_traces) > self._TRACE_TOMBSTONE_LIMIT:
                del self._termination_traces[next(iter(self._termination_traces))]
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
        exit_confirmed = False
        try:
            while slot.process.is_alive() or slot.worker.response_pipe.poll(0.1):
                if not slot.worker.response_pipe.poll(0.1):
                    continue
                response = decode_response(
                    slot.worker.response_pipe.recv_bytes(maxlength=MAX_BOUNDED_JSON_BYTES)
                )
                self._record_response(slot.task_id, response)
                if isinstance(response, WorkerHello):
                    self.supervisor.acknowledge(
                        slot.lease_id,
                        response.protocol_version,
                        response.resource_lease_token,
                    )
                    self._lease_persistence.set_enforcement(
                        slot.lease_id,
                        state="VERIFIED",
                        job_object_identity=f"job-object:{slot.process.pid}",
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
                    # Windows Job Object sampling is a hard-enforcement
                    # boundary. Ubuntu CI deliberately exercises the
                    # portable worker lifecycle without claiming Linux
                    # product support; an explicitly injected controller is
                    # still sampled through the same path.
                    if self._job_controller is not None:
                        self._sample_parent_resources(slot)
                elif isinstance(response, Progress):
                    self.supervisor.handle(slot.lease_id, response)
                elif isinstance(response, WorkerTerminal):
                    terminal = response
                    break
        except (EOFError, OSError):
            pass
        except Exception as error:
            protocol_error = error
        finally:
            slot.process.join(timeout=0.5)
            if slot.process.is_alive():
                # A closed response pipe without a typed terminal is an
                # orphan boundary.  Do not drop the last process handle when
                # the supervisor tombstone is released; force the bounded
                # terminate/kill ladder before declaring observation done.
                try:
                    slot.process.terminate()
                except Exception as error:
                    protocol_error = protocol_error or error
                slot.process.join(self._terminate_timeout_seconds)
            if slot.process.is_alive():
                try:
                    slot.process.kill()
                except Exception as error:
                    protocol_error = protocol_error or error
                slot.process.join(self._kill_timeout_seconds)
            exit_confirmed = not slot.process.is_alive()
            if exit_confirmed:
                self.supervisor.observe_externally_finalized(slot.lease_id)
                self._close_worker_pipes(slot)
            else:
                # A failed terminate/kill ladder is an orphan boundary.  Do
                # not release the supervisor tombstone or write Task failure
                # while the process may still be executing.  A bounded
                # reaper observes eventual exit and then applies the same
                # typed-outcome reconciliation path.
                reaper_error = RuntimeError(
                    "worker process exit could not be confirmed"
                )
                with self._lock:
                    self._monitor_error = reaper_error
                try:
                    Thread(
                        target=self._observe_after_exit,
                        args=(slot, terminal, protocol_error),
                        name=f"v3-worker-reaper-{slot.task_id}",
                        daemon=True,
                    ).start()
                except Exception as error:
                    # Thread creation is itself fallible.  Run the bounded
                    # observation inline so a reaper-start failure cannot
                    # leave an unowned live child with no future cleanup path.
                    with self._lock:
                        self._monitor_error = error
                    self._observe_after_exit(
                        slot,
                        terminal,
                        protocol_error or error,
                    )

        if exit_confirmed:
            try:
                self._reconcile_worker_outcome(slot, terminal, protocol_error)
            finally:
                # Do not release the parent replacement fence until all
                # parent-side Catalog reads/writes in reconciliation finish.
                self._release_catalog_lease(slot)

    @staticmethod
    def _close_worker_pipes(slot: _WorkerSlot) -> None:
        try:
            slot.worker.command_pipe.close()
        except (EOFError, OSError):
            pass
        try:
            slot.worker.response_pipe.close()
        except (EOFError, OSError):
            pass

    def _close_catalog_lease_handle(self, lease: Any | None) -> None:
        if lease is None:
            return
        try:
            lease.__exit__(None, None, None)
        except Exception as error:
            # The context manager leaves an unlocked stale marker recoverable
            # by the next upgrade. Surface a release failure to the manager
            # health gate instead of claiming a clean worker lifecycle.
            with self._lock:
                if self._monitor_error is None:
                    self._monitor_error = error

    def _release_catalog_lease(self, slot: _WorkerSlot) -> None:
        lease = getattr(slot, "catalog_lease", None)
        if lease is None:
            return
        slot.catalog_lease = None
        self._close_catalog_lease_handle(lease)

    def _observe_after_exit(
        self,
        slot: _WorkerSlot,
        terminal: WorkerTerminal | None,
        protocol_error: Exception | None,
    ) -> None:
        reap_deadline = time.monotonic() + max(
            1.0,
            self._terminate_timeout_seconds
            + self._kill_timeout_seconds
            + self._cancel_grace_seconds,
        )
        while slot.process.is_alive():
            remaining = reap_deadline - time.monotonic()
            if remaining <= 0:
                with self._lock:
                    self._monitor_error = RuntimeError(
                        f"worker process exit is still unconfirmed: {slot.task_id}"
                    )
                # Retain the slot and supervisor tombstone.  A live process
                # must not be converted into a terminal Task merely because
                # the bounded cleanup window elapsed.
                return
            slot.process.join(min(0.25, remaining))
        self.supervisor.observe_externally_finalized(slot.lease_id)
        self._close_worker_pipes(slot)
        try:
            self._reconcile_worker_outcome(slot, terminal, protocol_error)
        finally:
            self._release_catalog_lease(slot)

    def _reconcile_worker_outcome(
        self,
        slot: _WorkerSlot,
        terminal: WorkerTerminal | None,
        protocol_error: Exception | None,
    ) -> None:
        if slot.process.is_alive():
            return
        if protocol_error is not None:
            self._finalize_if_unowned(slot, protocol_error)
        elif terminal is None:
            self._finalize_if_unowned(
                slot, RuntimeError("worker exited without typed terminal")
            )
        elif terminal.status == "CANCELLED":
            # A cooperative cancel requested by ProductRuntime leaves the
            # Task in CANCEL_REQUESTED for the second, confirmed-exit UoW. A
            # spontaneous child cancellation has no such owner and must not
            # strand a QUEUED/RUNNING Task indefinitely.
            task = self._product.task_persistence.read_task(slot.task_id)
            if task.state.value not in {
                "CANCEL_REQUESTED",
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "PARTIAL",
            }:
                self._finalize_if_unowned(
                    slot,
                    (
                        _ProgressStalledError(
                            "PROGRESS_STALLED: worker made no durable progress"
                        )
                        if slot.stall_signalled
                        else RuntimeError("worker cancelled without a cancellation request")
                    ),
                )
        elif terminal.status == "FAILED":
            self._finalize_if_unowned(
                slot,
                RuntimeError(terminal.safe_message or "isolated worker failed"),
            )
        elif terminal.status == "SUCCEEDED":
            # A success frame is only telemetry.  ProductRuntime must have
            # already committed Task/Attempt/receipt finality; otherwise a
            # child cannot turn a missing publication into a false success.
            task = self._product.task_persistence.read_task(slot.task_id)
            if task.state not in TASK_TERMINAL_STATES:
                self._finalize_if_unowned(
                    slot,
                    RuntimeError(
                        "worker reported success without durable Task finality"
                    ),
                    category=ErrorCategory.WORKER_LOST,
                )

    def _sample_parent_resources(self, slot: _WorkerSlot) -> None:
        """Record only parent/controller observations as resource authority."""

        sampler = getattr(self._job_controller, "sample", None)
        if not callable(sampler):
            error = RuntimeError(
                "RESOURCE_ENFORCEMENT_NOT_AVAILABLE: parent resource sampler is unavailable"
            )
            with self._lock:
                self._monitor_error = error
            raise error
        try:
            lease = self._lease_persistence.require(slot.lease_id)
            scratch_root = lease.grant.scratch_root
            if not scratch_root:
                raise RuntimeError("dedicated Attempt scratch root is unavailable")
            observed = sampler(slot.worker, scratch_root)
            if (
                not isinstance(observed, tuple)
                or len(observed) != 2
                or any(
                    not isinstance(value, int) or isinstance(value, bool) or value < 0
                    for value in observed
                )
            ):
                raise RuntimeError("job resource sample shape is invalid")
            self.supervisor.record_parent_sample(
                slot.lease_id,
                memory_bytes=observed[0],
                scratch_bytes=observed[1],
            )
        except Exception as error:
            if getattr(error, "kind", None) in {
                "RESOURCE_EXHAUSTED_MEMORY",
                "RESOURCE_EXHAUSTED_SCRATCH",
            }:
                return
            with self._lock:
                self._monitor_error = error
            raise

    def _finalize_if_unowned(
        self,
        slot: _WorkerSlot,
        error: Exception,
        *,
        category: ErrorCategory | None = None,
    ) -> bool:
        from .product_runtime import classify_execution_error

        if slot.process.is_alive():
            return False
        durable_code = self._durable_failure_code(slot.attempt_id)
        if durable_code in {
            "RESOURCE_EXHAUSTED_MEMORY",
            "RESOURCE_EXHAUSTED_SCRATCH",
            "WORKER_OOM",
        }:
            # The parent-side lease/Job Object observation is authoritative.
            # Preserve that code when a hard kill prevents the child from
            # emitting a typed terminal frame.
            error = RuntimeError(f"{durable_code}: parent-owned worker termination")
            error.reason_code = durable_code  # type: ignore[attr-defined]
            if category is None:
                category = (
                    ErrorCategory.WORKER_OOM
                    if durable_code in {"RESOURCE_EXHAUSTED_MEMORY", "WORKER_OOM"}
                    else ErrorCategory.WORKER_LOST
                )
        task = self._product.task_persistence.read_task(slot.task_id)
        if task.state in TASK_TERMINAL_STATES or task.state.value == "CANCEL_REQUESTED":
            return True
        self._product.execution._finish_failure(
            slot.handles.task,
            slot.handles.run,
            slot.handles.attempt,
            error=error,
            category=(
                category
                or (
                    ErrorCategory.WORKER_LOST
                    if getattr(error, "reason_code", None) == "PROGRESS_STALLED"
                    else classify_execution_error(error)
                )
            ),
        )
        return True

    def _durable_failure_code(self, attempt_id: str) -> str | None:
        """Read parent-side terminal classification after a child disappears."""

        try:
            with self._product.task_persistence.begin() as unit:
                attempt = unit.require_attempt(attempt_id)
                unit.commit()
                return attempt.terminal_error_category
        except (KeyError, ValueError):
            return None

    def _monitor_expired_leases(self) -> None:
        while not self._stop_monitor.wait(0.25):
            with self._lock:
                if not any(slot.process.is_alive() for slot in self._slots.values()):
                    return
            self._monitor_progress_stalls()
            try:
                lost_attempts = self.supervisor.reap_expired()
            except Exception as error:
                with self._lock:
                    self._monitor_error = error
                return
            if not lost_attempts:
                continue
            with self._lock:
                affected_slots = tuple(
                    slot
                    for slot in self._slots.values()
                    if slot.attempt_id in lost_attempts
                )
            # reap_expired() fences the durable lease and sends the first
            # terminate signal, but it does not own an exit proof.  Do not
            # let global reconciliation turn an EXPIRED lease into a terminal
            # Task while its OS child may still be running.
            all_exits_confirmed = True
            for slot in affected_slots:
                if not self._confirm_slot_exit(
                    slot.task_id,
                    slot,
                    request_cooperative_cancel=False,
                ):
                    all_exits_confirmed = False
            if not all_exits_confirmed:
                with self._lock:
                    self._monitor_error = RuntimeError(
                        "expired worker process exit could not be confirmed"
                    )
                continue
            if affected_slots:
                self._product.reconciliation_summary = self._product._reconcile_execution_state()

    def _monitor_progress_stalls(self) -> None:
        """Fence a worker that is alive but no longer advances durable progress."""

        now_monotonic = time.monotonic()
        now_wall = datetime.now(timezone.utc)
        with self._lock:
            slots = tuple(self._slots.values())
        for slot in slots:
            if not slot.process.is_alive() or slot.progress_stall_seconds is None:
                continue
            try:
                latest = self._product.progress_persistence.latest_progress(slot.attempt_id)
            except KeyError:
                continue
            if latest is None:
                elapsed = now_monotonic - slot.started_monotonic
            else:
                elapsed = max(
                    0.0, (now_wall - latest.persisted_at).total_seconds()
                )
            if not slot.stall_signalled:
                if elapsed < slot.progress_stall_seconds:
                    continue
                try:
                    self._product.progress_persistence.mark_progress_stalled(
                        slot.attempt_id
                    )
                except Exception as error:
                    with self._lock:
                        self._monitor_error = error
                    return
                slot.stall_signalled = True
                if slot.checkpoint_policy != "NOT_AVAILABLE":
                    try:
                        slot.worker.request_checkpoint()
                    except Exception:
                        # A failed checkpoint request is itself a fail-closed
                        # signal; bounded cancellation below still applies.
                        pass
                    grace = (
                        self._resource_policy.cancellation_seconds.get(
                            "stall_checkpoint_grace", 0
                        )
                        if self._resource_policy is not None
                        else 0
                    )
                    slot.stall_action_at = now_monotonic + max(0, int(grace))
                else:
                    slot.stall_action_at = now_monotonic
            if slot.stall_action_at is None or now_monotonic < slot.stall_action_at:
                continue
            try:
                exited = self.cancel(slot.task_id)
                if not exited or slot.process.is_alive():
                    # A cancellation request is not proof of process exit.
                    # Leave the action armed for the next monitor pass and
                    # never terminalize a still-running child.
                    continue
                if self._finalize_if_unowned(
                    slot,
                    _ProgressStalledError(
                        "PROGRESS_STALLED: worker made no durable progress"
                    ),
                    category=ErrorCategory.WORKER_LOST,
                ):
                    slot.stall_action_at = None
            except Exception as error:
                with self._lock:
                    self._monitor_error = error
                return

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
            if slot.process.is_alive():
                if force:
                    # ``force`` means reap already-confirmed exits during
                    # shutdown; it is not permission to discard a live
                    # process handle.  Keeping the slot makes the orphan
                    # visible to has_live_processes() and the next monitor
                    # pass instead of falsely reporting a clean shutdown.
                    self._monitor_error = RuntimeError(
                        f"worker process exit is not confirmed: {task_id}"
                    )
                continue
            if slot.protocol_thread is not None and slot.protocol_thread.is_alive():
                # The listener owns terminal observation while it is still
                # unwinding.  Removing the slot here would lose its lease,
                # pipes, and typed-outcome reconciliation.
                continue
            slot.process.join(timeout=0)
            try:
                if slot.lease_id in self.supervisor.workers:
                    # This is the defensive path for a child that died before
                    # a listener could run its finally block.  Release the
                    # supervisor tombstone and reconcile the missing terminal
                    # frame before dropping the last process handle.
                    try:
                        self.supervisor.observe_externally_finalized(slot.lease_id)
                        self._close_worker_pipes(slot)
                        self._reconcile_worker_outcome(
                            slot,
                            None,
                            RuntimeError("worker exited without typed terminal"),
                        )
                    except Exception as error:
                        self._monitor_error = error
                else:
                    self._close_worker_pipes(slot)
            finally:
                self._release_catalog_lease(slot)
            del self._slots[task_id]


__all__ = [
    "DEFAULT_MAX_ACTIVE_RESEARCH_WORKERS",
    "PRODUCT_HEARTBEAT_SECONDS",
    "PRODUCT_LEASE_EXPIRY_SECONDS",
    "ProductResearchWorkerConfig",
    "ProductResearchWorkerManager",
]
