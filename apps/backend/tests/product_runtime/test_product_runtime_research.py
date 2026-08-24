from __future__ import annotations

import tempfile
import os
import time
import uuid
import unittest
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from v3_backend.adapters.market_data.akshare import AkshareAShareEodAdapter
from v3_backend.contracts.common.dto import ContractValidationError
from v3_backend.contracts.product_entry import (
    SubmitResearchRequestV1,
    SubmitResearchResponseV1,
)
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_facades import build_product_facades
from v3_backend.runtime.product_research import _ensure_provider_admission
from v3_backend.runtime.product_release_acceptance import (
    DETERMINISTIC_SUCCESS,
    DETERMINISTIC_UNAVAILABLE,
    product_release_acceptance_provider_factory,
)
from v3_backend.runtime.product_runtime import ProductRuntime
from v3_backend.runtime.product_workers import (
    PRODUCT_HEARTBEAT_SECONDS,
    PRODUCT_LEASE_EXPIRY_SECONDS,
    ProductResearchWorkerConfig,
)
from v3_backend.control_plane.worker_supervisor import WorkerSupervisor
from v3_backend.workers.protocol import Progress, WorkerHeartbeat, WorkerHello
from v3_backend.errors import CapabilityUnavailableError, ResourceRejectedError
from v3_backend.contracts.registry import SERVICE_CONTRACTS
from v3_backend.runtime.composition_root import RuntimePorts, RuntimeSession
from v3_backend.runtime.framed_stdio import FrameDecoder, encode_frame
from v3_backend.runtime.handshake import create_hello, token_proof
from v3_backend.runtime.request_router import RequestRouter


class _Frame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        if orient != "records":
            raise AssertionError("the provider adapter must request records orientation")
        return list(self._rows)


class _FakeAkshare:
    __version__ = "1.18.84"
    __v3_source_kind__ = "TEST_EXTERNAL_PROVIDER_BOUNDARY"

    def stock_zh_a_hist(self, **request: object) -> _Frame:
        del request
        return _Frame(
            [
                {
                    "股票代码": "000001",
                    "日期": "2026-01-06",
                    "开盘": "10.00",
                    "最高": "11.00",
                    "最低": "9.50",
                    "收盘": "10.50",
                    "成交量": "1000",
                    "成交额": "10500",
                },
                {
                    "股票代码": "000001",
                    "日期": "2026-01-07",
                    "开盘": "10.50",
                    "最高": "11.50",
                    "最低": "10.00",
                    "收盘": "11.00",
                    "成交量": "1200",
                    "成交额": "13200",
                },
            ]
        )


def _provider_factory(_config):
    return AkshareAShareEodAdapter(
        connector_version_id="cov_akshare_eod_research_v1",
        loader=lambda: _FakeAkshare(),
        clock=lambda: datetime(2026, 1, 8, 8, 0, tzinfo=timezone.utc),
    )


def _facade_handler(product: ProductRuntime, operation_id: str):
    for facade in build_product_facades(product):
        handler = facade.handlers().get(operation_id)
        if handler is not None:
            return handler
    raise AssertionError(f"missing handler: {operation_id}")


def _request(project_id: str, revision_id: str, *, key: str = "research-1") -> dict[str, object]:
    return {
        "request_id": str(uuid.uuid4()),
        "project_id": project_id,
        "project_context_revision_id": revision_id,
        "expected_api_version": "1.0",
        "idempotency_key": key,
        "research_profile_id": "RESEARCH_FREE_DATA_V1",
        "strategy_profile_id": "RESEARCH_CLOSE_RANK_TOP1_V1",
        "source": {
            "provider_id": "pvd_akshare_eastmoney_a_share_eod_v1",
            "connector_version_id": "cov_akshare_eod_research_v1",
            "logical_dataset": "CN_A_SHARE_EOD",
            "frequency": "P1D",
            "symbol": "000001",
            "start_date": "20260106",
            "end_date": "20260107",
        },
    }


class ProductRuntimeResearchTests(unittest.TestCase):
    def test_lease_monitor_failure_stops_new_worker_admission(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-lease-monitor-failure-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_provider_factory=_provider_factory,
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=30.0,
                ),
            )
            project = create_project(
                product,
                display_name="Lease monitor failure",
                notes=None,
                idempotency_key="create-lease-monitor-failure",
            )
            submit = _facade_handler(product, "ProductEntryService.v1.submitResearch")
            with patch.object(
                product.research_workers.supervisor,
                "reap_expired",
                side_effect=OSError("synthetic lease persistence failure"),
            ):
                accepted = submit(
                    _request(
                        project["project_id"],
                        project["project_context_revision_id"],
                        key="lease-monitor-failure",
                    )
                )
                task_id = accepted["read_model"]["task_id"]
                try:
                    time.sleep(0.6)
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "research worker lease monitor failed",
                    ):
                        product.research_workers.reserve_capacity()
                finally:
                    self.assertTrue(
                        product.cancel_research_task(
                            task_id,
                            reason="TEST_CLEANUP",
                        )
                    )

    def test_internal_spawn_failure_closes_task_once_and_preserves_nonretryable_category(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-worker-spawn-internal-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_provider_factory=_provider_factory,
                research_worker_config=ProductResearchWorkerConfig(),
            )
            project = create_project(
                product,
                display_name="Internal spawn failure",
                notes=None,
                idempotency_key="create-internal-spawn-failure",
            )
            submit = _facade_handler(product, "ProductEntryService.v1.submitResearch")
            with patch.object(
                product.research_workers._factory,
                "spawn",
                side_effect=RuntimeError("synthetic process factory defect"),
            ):
                with self.assertRaises(RuntimeError):
                    submit(
                        _request(
                            project["project_id"],
                            project["project_context_revision_id"],
                            key="internal-spawn-failure",
                        )
                    )
            connection = product._connection(read_only=True)
            try:
                row = connection.execute(
                    """
                    SELECT t.state, a.state, a.error_code, l.state, w.state
                    FROM task AS t
                    JOIN run AS r ON r.task_id=t.task_id
                    JOIN task_attempt AS a ON a.run_id=r.run_id
                    JOIN worker_lease AS l ON l.attempt_id=a.attempt_id
                    JOIN worker AS w ON w.worker_id=l.worker_id
                    """
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(
                tuple(row),
                ("FAILED", "FAILED", "INTERNAL_ERROR", "REVOKED", "STOPPED"),
            )

    def test_post_spawn_persistence_failure_confirms_child_exit_before_task_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-worker-post-spawn-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_provider_factory=_provider_factory,
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=30.0,
                    cancel_grace_seconds=0.2,
                    terminate_timeout_seconds=0.2,
                    kill_timeout_seconds=0.2,
                ),
            )
            project = create_project(
                product,
                display_name="Post-spawn persistence failure",
                notes=None,
                idempotency_key="create-post-spawn-failure",
            )
            submit = _facade_handler(product, "ProductEntryService.v1.submitResearch")
            with patch.object(
                product.research_workers._lease_persistence,
                "set_process_id",
                side_effect=OSError("synthetic worker pid persistence failure"),
            ):
                with self.assertRaises(OSError):
                    submit(
                        _request(
                            project["project_id"],
                            project["project_context_revision_id"],
                            key="post-spawn-persistence-failure",
                        )
                    )
            self.assertFalse(product.research_workers.has_live_processes())
            connection = product._connection(read_only=True)
            try:
                row = connection.execute(
                    """
                    SELECT t.state, a.state, a.error_code, l.state, w.state
                    FROM task AS t
                    JOIN run AS r ON r.task_id=t.task_id
                    JOIN task_attempt AS a ON a.run_id=r.run_id
                    JOIN worker_lease AS l ON l.attempt_id=a.attempt_id
                    JOIN worker AS w ON w.worker_id=l.worker_id
                    """
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(
                tuple(row),
                ("FAILED", "FAILED", "TRANSIENT_IO", "REVOKED", "STOPPED"),
            )

    def test_spawn_failure_after_acceptance_is_durably_failed_not_orphan_queued(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-research-spawn-failure-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_provider_factory=_provider_factory,
                research_worker_config=ProductResearchWorkerConfig(),
            )
            project = create_project(
                product,
                display_name="Spawn failure",
                notes=None,
                idempotency_key="create-spawn-failure",
            )
            submit = _facade_handler(product, "ProductEntryService.v1.submitResearch")
            with patch.object(
                product.research_workers,
                "start",
                side_effect=OSError("synthetic spawn failure"),
            ):
                with self.assertRaises(OSError):
                    submit(
                        _request(
                            project["project_id"],
                            project["project_context_revision_id"],
                            key="spawn-failure-after-acceptance",
                        )
                    )
            connection = product._connection(read_only=True)
            try:
                row = connection.execute(
                    """
                    SELECT t.state, a.state, l.state, w.state
                    FROM task AS t
                    JOIN run AS r ON r.task_id=t.task_id
                    JOIN task_attempt AS a ON a.run_id=r.run_id
                    LEFT JOIN worker_lease AS l ON l.attempt_id=a.attempt_id
                    LEFT JOIN worker AS w ON w.worker_id=l.worker_id
                    """
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(
                tuple(row),
                ("FAILED", "FAILED", None, None),
                "a failure before WorkerSupervisor.dispatch must not fabricate a lease or worker",
            )

    def test_acc_c1_07_worker_capacity_rejects_before_task_acceptance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-research-capacity-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_provider_factory=_provider_factory,
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=30.0,
                    max_active_workers=1,
                ),
            )
            try:
                project = create_project(
                    product,
                    display_name="Worker capacity",
                    notes=None,
                    idempotency_key="create-worker-capacity",
                )
                submit = _facade_handler(product, "ProductEntryService.v1.submitResearch")
                first = submit(
                    _request(
                        project["project_id"],
                        project["project_context_revision_id"],
                        key="worker-capacity-first",
                    )
                )
                first_task_id = first["read_model"]["task_id"]
                self.assertTrue(product.research_workers.task_process(first_task_id).is_alive())
                connection = product._connection(read_only=True)
                try:
                    task_count_before = int(
                        connection.execute("SELECT COUNT(*) FROM task").fetchone()[0]
                    )
                finally:
                    connection.close()

                with self.assertRaises(ResourceRejectedError) as rejected:
                    submit(
                        _request(
                            project["project_id"],
                            project["project_context_revision_id"],
                            key="worker-capacity-second",
                        )
                    )
                self.assertEqual(
                    rejected.exception.details["reason_code"],
                    "WORKER_CAPACITY_EXCEEDED",
                )
                self.assertEqual(rejected.exception.details["limit"], 1)
                connection = product._connection(read_only=True)
                try:
                    self.assertEqual(
                        int(connection.execute("SELECT COUNT(*) FROM task").fetchone()[0]),
                        task_count_before,
                    )
                finally:
                    connection.close()
            finally:
                if product.research_workers is not None:
                    product.prepare_shutdown(None)
                    product.research_workers.shutdown_all()

    def test_isolated_shutdown_cancels_child_before_reconciliation_and_reports_process_truth(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-research-shutdown-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_provider_factory=_provider_factory,
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=30.0,
                ),
            )
            try:
                project = create_project(
                    product,
                    display_name="Shutdown process truth",
                    notes=None,
                    idempotency_key="create-shutdown-process-truth",
                )
                response = _facade_handler(product, "ProductEntryService.v1.submitResearch")(
                    _request(
                        project["project_id"],
                        project["project_context_revision_id"],
                        key="shutdown-running-worker",
                    )
                )
                task_id = response["read_model"]["task_id"]
                worker = product.research_workers.task_process(task_id)
                self.assertIsNotNone(worker)
                self.assertTrue(worker.is_alive())

                truth = product.prepare_shutdown(None)

                self.assertFalse(worker.is_alive())
                self.assertEqual(product.task_persistence.read_task(task_id).state.value, "CANCELLED")
                self.assertEqual(truth["execution_mode"], "ISOLATED_PRODUCT_PROCESS")
                self.assertEqual(
                    truth["active_task_policy"],
                    "CANCEL_AND_CONFIRM_EXIT_BEFORE_SHUTDOWN",
                )
                self.assertEqual(product.reconciliation_summary["tasks_failed"], 0)
                product.commit_shutdown()
            finally:
                product.research_workers.shutdown_all()

    def test_acc_c1_06_running_deadline_escalates_and_late_success_cannot_overwrite_cancelled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-research-deadline-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_provider_factory=_provider_factory,
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=30.0,
                    cooperative_cancel=False,
                    cancel_grace_seconds=0.1,
                    terminate_timeout_seconds=0.5,
                    kill_timeout_seconds=0.5,
                ),
            )
            try:
                project = create_project(
                    product,
                    display_name="Deadline escalation",
                    notes=None,
                    idempotency_key="create-deadline-escalation",
                )
                handlers = {}
                for facade in build_product_facades(product):
                    handlers.update(facade.handlers())
                request_id = "01890f3c-7b5a-7000-8000-000000000051"
                deadline_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=0.5)
                ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                body = _request(
                    project["project_id"],
                    project["project_context_revision_id"],
                    key="deadline-escalation",
                )
                body["request_id"] = request_id
                response = RequestRouter(handlers).route({
                    "kind": "request",
                    "request_id": request_id,
                    "operation_id": "ProductEntryService.v1.submitResearch",
                    "contract_version": "1.0.0",
                    "project_id": project["project_id"],
                    "project_context_revision_id": project["project_context_revision_id"],
                    "deadline_at": deadline_at,
                    "body": body,
                })
                self.assertEqual(response["status"], "OK")
                task_id = response["body"]["read_model"]["task_id"]
                worker = product.research_workers.task_process(task_id)
                self.assertIsNotNone(worker)
                self.assertTrue(worker.is_alive())

                connection = product._connection(read_only=True)
                try:
                    persisted = connection.execute(
                        """
                        SELECT t.execution_deadline_at, a.execution_deadline_at
                        FROM task AS t
                        JOIN run AS r ON r.task_id=t.task_id
                        JOIN task_attempt AS a ON a.run_id=r.run_id
                        WHERE t.task_id=?
                        """,
                        (task_id,),
                    ).fetchone()
                finally:
                    connection.close()
                self.assertEqual(tuple(persisted), (deadline_at, deadline_at))

                wait_until = time.monotonic() + 4.0
                task = product.task_persistence.read_task(task_id)
                while task.state.value != "CANCELLED" and time.monotonic() < wait_until:
                    time.sleep(0.02)
                    task = product.task_persistence.read_task(task_id)
                self.assertEqual(task.state.value, "CANCELLED")
                self.assertFalse(worker.is_alive(), "deadline terminal state requires confirmed child exit")
                self.assertEqual(
                    product.research_workers.termination_trace(task_id),
                    ("COOPERATIVE_CANCEL_REQUESTED", "TERMINATE_SENT", "EXIT_CONFIRMED"),
                )

                with product.task_persistence.begin() as unit:
                    stale_task = unit.require_task(task_id)
                    stale_run = unit.require_run(stale_task.active_run_id)
                    unit.commit()
                stale_attempt = product.task_persistence.latest_attempt(task_id)
                with self.assertRaises(Exception):
                    product.execution._finish_success(
                        stale_task,
                        stale_run,
                        stale_attempt,
                        outputs={},
                    )
                self.assertEqual(product.task_persistence.read_task(task_id).state.value, "CANCELLED")
            finally:
                product.research_workers.shutdown_all()

    def test_isolated_research_child_completes_canonical_result_without_blocking_acceptance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-research-isolated-success-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_worker_config=ProductResearchWorkerConfig(
                    provider_mode=DETERMINISTIC_SUCCESS,
                ),
            )
            try:
                project = create_project(
                    product,
                    display_name="Isolated success",
                    notes=None,
                    idempotency_key="create-isolated-success",
                )
                started = time.monotonic()
                response = _facade_handler(product, "ProductEntryService.v1.submitResearch")(
                    _request(project["project_id"], project["project_context_revision_id"])
                )
                self.assertLess(time.monotonic() - started, 2.0)
                task_id = response["read_model"]["task_id"]
                deadline = time.monotonic() + 15.0
                task = product.task_persistence.read_task(task_id)
                while task.state.value not in {"SUCCEEDED", "FAILED", "CANCELLED"} and time.monotonic() < deadline:
                    time.sleep(0.05)
                    task = product.task_persistence.read_task(task_id)
                worker = product.research_workers.task_process(task_id)
                if worker is not None:
                    worker.join(timeout=2.0)
                self.assertEqual(task.state.value, "SUCCEEDED")
                self.assertIsNotNone(worker)
                self.assertFalse(worker.is_alive())
            finally:
                product.research_workers.shutdown_all()

    def test_acc_c1_05_queued_research_stays_responsive_and_cancel_stops_actual_child(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-research-cancel-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_provider_factory=_provider_factory,
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=30.0,
                ),
            )
            try:
                project = create_project(
                    product,
                    display_name="Isolated cancellation",
                    notes=None,
                    idempotency_key="create-isolated-cancel",
                )
                submit = _facade_handler(product, "ProductEntryService.v1.submitResearch")
                started = time.monotonic()
                response = submit(_request(project["project_id"], project["project_context_revision_id"]))
                self.assertLess(time.monotonic() - started, 2.0)
                model = response["read_model"]
                self.assertEqual(model["accepted_state"], "QUEUED")

                task_id = model["task_id"]
                worker = product.research_workers.task_process(task_id)
                self.assertIsNotNone(worker)
                self.assertNotEqual(worker.pid, os.getpid())
                self.assertTrue(worker.is_alive(), "acceptance must own a real live child process")
                self.assertIsInstance(product.research_workers.supervisor, WorkerSupervisor)
                self.assertEqual(
                    product.research_workers.transport_kind,
                    "DEDICATED_COMMAND_AND_RESPONSE_PIPES",
                )
                self.assertEqual(PRODUCT_HEARTBEAT_SECONDS, 2)
                self.assertEqual(PRODUCT_LEASE_EXPIRY_SECONDS, 10)

                heartbeat_deadline = time.monotonic() + 3.0
                lease_row = None
                while time.monotonic() < heartbeat_deadline:
                    connection = product._connection(read_only=True)
                    try:
                        lease_row = connection.execute(
                            """
                            SELECT l.state, l.renewed_at, l.expires_at, w.heartbeat_at
                            FROM worker_lease AS l
                            JOIN worker AS w ON w.worker_id=l.worker_id
                            WHERE l.attempt_id=(
                              SELECT a.attempt_id FROM task_attempt AS a
                              JOIN run AS r ON r.run_id=a.run_id
                              WHERE r.task_id=? ORDER BY a.attempt_no DESC LIMIT 1
                            )
                            """,
                            (task_id,),
                        ).fetchone()
                    finally:
                        connection.close()
                    if lease_row is not None and lease_row[0] == "RENEWED":
                        break
                    time.sleep(0.02)
                self.assertIsNotNone(lease_row)
                self.assertEqual(lease_row[0], "RENEWED")
                self.assertIsNotNone(lease_row[1])
                self.assertEqual(lease_row[1], lease_row[3])
                renewed_at = datetime.fromisoformat(str(lease_row[1]).replace("Z", "+00:00"))
                expires_at = datetime.fromisoformat(str(lease_row[2]).replace("Z", "+00:00"))
                self.assertAlmostEqual(
                    (expires_at - renewed_at).total_seconds(),
                    PRODUCT_LEASE_EXPIRY_SECONDS,
                    delta=0.1,
                )
                response_trace = product.research_workers.response_trace(task_id)
                self.assertTrue(any(isinstance(item, WorkerHello) for item in response_trace))
                self.assertTrue(any(isinstance(item, WorkerHeartbeat) for item in response_trace))
                self.assertTrue(
                    any(
                        isinstance(item, Progress)
                        and item.phase == "DISPATCHED"
                        and item.work_unit == "pipeline_phases"
                        for item in response_trace
                    )
                )

                handlers = {}
                for facade in build_product_facades(product):
                    handlers.update(facade.handlers())
                token = bytes(range(32))
                fixed_hello = create_hello("isolated-backend", 1, "0.1.0", [], nonce="ab" * 32)
                transport_request_id = "01890f3c-7b5a-7000-8000-000000000041"
                health_control_id = "01890f3c-7b5a-7000-8000-000000000042"
                accept = {
                    "kind": "supervisor.accept",
                    "token_proof": token_proof(token, fixed_hello["nonce"]),
                    "requested_protocol": "v3.local/1.0",
                    "requested_asl_versions": {name: "1.0" for name in SERVICE_CONTRACTS},
                    "desktop_version": "0.1.0",
                    "project_id": project["project_id"],
                    "project_context_revision_id": project["project_context_revision_id"],
                    "last_project_event_sequence": 0,
                }
                health = {
                    "kind": "runtime.health",
                    "control_request_id": health_control_id,
                    "runtime_generation": 1,
                    "deadline_at": "2099-01-01T00:00:00Z",
                }
                task_request = {
                    "kind": "request",
                    "request_id": transport_request_id,
                    "operation_id": "TaskService.v1.getTask",
                    "contract_version": "1.0.0",
                    "project_id": project["project_id"],
                    "project_context_revision_id": project["project_context_revision_id"],
                    "body": {
                        "request_id": transport_request_id,
                        "project_id": project["project_id"],
                        "project_context_revision_id": project["project_context_revision_id"],
                        "expected_api_version": "1.0",
                        "task_id": task_id,
                    },
                }
                source = io.BytesIO(encode_frame(accept) + encode_frame(health) + encode_frame(task_request))
                sink = io.BytesIO()
                session = RuntimeSession(
                    RuntimePorts(operation_handlers=handlers, capabilities=product.capabilities()),
                    token,
                    "0.1.0",
                    backend_instance_id="isolated-backend",
                )
                transport_started = time.monotonic()
                with patch("v3_backend.runtime.composition_root.create_hello", return_value=fixed_hello):
                    session.run(source, sink)
                self.assertLess(time.monotonic() - transport_started, 0.5)
                decoded = FrameDecoder().feed(sink.getvalue())
                self.assertEqual(decoded[2]["kind"], "runtime.health")
                self.assertEqual(decoded[2]["control_request_id"], health_control_id)
                self.assertEqual(decoded[3]["kind"], "response")
                self.assertEqual(decoded[3]["status"], "OK")
                self.assertEqual(decoded[3]["body"]["read_model"]["task_id"], task_id)
                self.assertTrue(worker.is_alive(), "health/getTask evidence must be collected while child is running")

                get_task = _facade_handler(product, "TaskService.v1.getTask")
                read_started = time.monotonic()
                task_view = get_task({"request_id": str(uuid.uuid4()), "project_id": project["project_id"], "task_id": task_id})
                self.assertLess(time.monotonic() - read_started, 0.5)
                self.assertIn(task_view["read_model"]["state"], {"QUEUED", "RUNNING"})

                current = product.task_persistence.read_task(task_id)
                cancel = _facade_handler(product, "TaskService.v1.cancelTask")
                cancelled = cancel({
                    "request_id": str(uuid.uuid4()),
                    "project_id": project["project_id"],
                    "task_id": task_id,
                    "expected_state_version": current.state_version,
                    "reason": "ACC-C1-05 actual child cancellation",
                })
                self.assertFalse(worker.is_alive(), "CANCELLED is forbidden until the actual child exits")
                self.assertEqual(cancelled["read_model"]["state"], "CANCELLED")
                connection = product._connection(read_only=True)
                try:
                    attempt_state = connection.execute(
                        """
                        SELECT a.state FROM task_attempt AS a
                        JOIN run AS r ON r.run_id=a.run_id
                        WHERE r.task_id=? ORDER BY a.attempt_no DESC LIMIT 1
                        """,
                        (task_id,),
                    ).fetchone()[0]
                finally:
                    connection.close()
                self.assertEqual(attempt_state, "CANCELLED")
            finally:
                product.research_workers.shutdown_all()

    def test_release_acceptance_success_is_explicitly_test_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-release-acceptance-success-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_provider_factory=product_release_acceptance_provider_factory(
                    DETERMINISTIC_SUCCESS
                ),
            )
            project = create_project(
                product,
                display_name="V1 deterministic success",
                notes=None,
                idempotency_key="create-v1-success",
            )
            response = _facade_handler(product, "ProductEntryService.v1.submitResearch")(
                _request(project["project_id"], project["project_context_revision_id"])
            )
            self.assertEqual(response["read_model"]["accepted_state"], "QUEUED")
            connection = product._connection(read_only=True)
            try:
                row = connection.execute(
                    "SELECT source_metadata_json FROM raw_capture_truth_descriptor"
                ).fetchone()
            finally:
                connection.close()
            self.assertIsNotNone(row)
            self.assertIn('"source_kind":"TEST_EXTERNAL_PROVIDER_BOUNDARY"', row[0])

    def test_release_acceptance_unavailable_fails_before_any_canonical_chain(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-release-acceptance-unavailable-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_provider_factory=product_release_acceptance_provider_factory(
                    DETERMINISTIC_UNAVAILABLE
                ),
            )
            project = create_project(
                product,
                display_name="V1 deterministic unavailable",
                notes=None,
                idempotency_key="create-v1-unavailable",
            )
            connection = product._connection(read_only=True)
            try:
                before = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("task", "run", "result", "raw_capture", "artifact")
                }
            finally:
                connection.close()
            handler = _facade_handler(product, "ProductEntryService.v1.submitResearch")
            with self.assertRaisesRegex(
                CapabilityUnavailableError,
                "PROVIDER_ACQUISITION_UNAVAILABLE",
            ) as raised:
                handler(_request(project["project_id"], project["project_context_revision_id"]))
            self.assertEqual(
                raised.exception.details,
                {
                    "reason_code": "PROVIDER_ACQUISITION_UNAVAILABLE",
                    "provider_id": "pvd_akshare_eastmoney_a_share_eod_v1",
                    "connector_version_id": "cov_akshare_eod_research_v1",
                    "fallback_used": False,
                    "canonical_chain_created": False,
                },
            )
            connection = product._connection(read_only=True)
            try:
                after = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("task", "run", "result", "raw_capture", "artifact")
                }
                artifact_roles = [
                    row[0]
                    for row in connection.execute(
                        "SELECT semantic_role FROM artifact ORDER BY semantic_role"
                    )
                ]
            finally:
                connection.close()
            self.assertEqual(
                {name: after[name] for name in ("task", "run", "result", "raw_capture")},
                {name: before[name] for name in ("task", "run", "result", "raw_capture")},
            )
            self.assertEqual(after["artifact"] - before["artifact"], 1)
            self.assertEqual(artifact_roles, ["DATA_TRUTH_CAPABILITY_POLICY"])

    def test_closed_entry_and_clean_start_restart_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-research-") as directory:
            root = Path(directory)
            product = ProductRuntime(root, research_provider_factory=_provider_factory)
            project = create_project(
                product,
                display_name="Product research smoke",
                notes=None,
                idempotency_key="create-research-project",
            )
            request = _request(project["project_id"], project["project_context_revision_id"])
            dto = SubmitResearchRequestV1.from_mapping(request)
            handler = _facade_handler(product, "ProductEntryService.v1.submitResearch")
            response = handler(dto.to_wire())
            validated = SubmitResearchResponseV1.from_mapping(response)
            read_model = validated["read_model"]

            self.assertEqual(validated["truth_state"], "DEMO")
            self.assertEqual(read_model["accepted_state"], "QUEUED")
            self.assertEqual(read_model["maturity"], "PRODUCT_CONNECTED_CANDIDATE")
            self.assertEqual(read_model["truth_admission"], {"truth": "NOT_FORMAL", "admission": "PRE_ALPHA"})
            self.assertEqual(read_model["research_classification"], ["RESEARCH_ONLY", "APPROXIMATE"])

            task = product.task_persistence.read_task(read_model["task_id"])
            self.assertEqual(task.operation_id, "ProductEntryService.v1.submitResearch")
            self.assertEqual(task.active_run_id, read_model["run_id"])
            task_connection = product._connection(read_only=True)
            try:
                task_row = task_connection.execute(
                    "SELECT state FROM task WHERE task_id=?", (task.task_id,)
                ).fetchone()
            finally:
                task_connection.close()
            self.assertEqual(task_row["state"], "SUCCEEDED")
            result_connection = product._connection(read_only=True)
            try:
                result_row = result_connection.execute(
                    "SELECT result_id FROM result WHERE backtest_run_id=?", (task.active_run_id,)
                ).fetchone()
            finally:
                result_connection.close()
            self.assertIsNotNone(result_row)

            restarted = ProductRuntime(root, research_provider_factory=_provider_factory)
            replay_request = _request(
                project["project_id"], project["project_context_revision_id"], key="research-1"
            )
            replay = _facade_handler(restarted, "ProductEntryService.v1.submitResearch")
            replay_response = replay(replay_request)
            replay_model = replay_response["read_model"]
            self.assertEqual(replay_model["task_id"], read_model["task_id"])
            self.assertEqual(replay_model["run_id"], read_model["run_id"])
            self.assertNotIn("event_cursor", replay_model)

    def test_repeated_provider_admission_reuses_append_only_descriptor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-provider-admission-") as directory:
            product = ProductRuntime(Path(directory), research_provider_factory=_provider_factory)
            project = create_project(
                product,
                display_name="Provider admission retry",
                notes=None,
                idempotency_key="create-provider-admission-project",
            )
            adapter = _provider_factory(None)
            first_registry, first_config = _ensure_provider_admission(
                product,
                project_id=project["project_id"],
                adapter=adapter,
            )
            second_registry, second_config = _ensure_provider_admission(
                product,
                project_id=project["project_id"],
                adapter=adapter,
            )
            self.assertEqual(first_config, second_config)
            self.assertIsNot(first_registry, second_registry)

    def test_caller_numeric_truth_is_rejected_by_closed_contract(self) -> None:
        request = _request("prj_01ARZ3NDEKTSV4RRFFQ69G5FB", "pcr_01ARZ3NDEKTSV4RRFFQ69G5FB")
        request["observations"] = []
        with self.assertRaises(ContractValidationError):
            SubmitResearchRequestV1.from_mapping(request)


if __name__ == "__main__":
    unittest.main()
