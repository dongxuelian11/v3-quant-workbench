from __future__ import annotations

import csv
import io
import json
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping
from unittest.mock import patch

from v3_backend.adapters.local_data import LocalDataImportIntentV1, LocalDataImportLimits
from v3_backend.contracts.registry import SERVICE_CONTRACTS, get_operation
from v3_backend.domain.backtest_runtime import (
    BacktestRunResult,
    Board,
    DeterministicAshareBacktestEngine,
    ExactInputReference,
)
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.tasks.entities import TASK_TERMINAL_STATES
from v3_backend.domain.tasks.retry_policy import ErrorCategory
from v3_backend.errors.exceptions import (
    CapabilityUnavailableError,
    IdempotencyConflictError,
    InvalidArgumentError,
    TruthPreconditionFailedError,
)
from v3_backend.runtime.product_backtest import (
    ExecutionPolicyRegistry,
    ProductCorporateActionService,
    ProductResearchBacktestService,
    ProductResearchBacktestSubmission,
    _BacktestTaskHandles,
)
from v3_backend.runtime.product_data import ProductDataService
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_factor import ProductFactorStudyService
from v3_backend.runtime.product_factor import ManifestAwareLocalSnapshotReader
from v3_backend.runtime.product_facades import (
    ProductEntryFacade,
    ResultFacade,
    TaskFacade,
    build_product_facades,
)
from v3_backend.runtime.composition_root import RuntimePorts, RuntimeSession
from v3_backend.runtime.framed_stdio import FrameDecoder, encode_frame
from v3_backend.runtime.handshake import create_hello, token_proof
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256
from v3_backend.runtime.product_publication import (
    FILLS_EXPORT_ROLE,
    LINEAGE_ROLE,
    ORDERS_EXPORT_ROLE,
    READ_MODEL_ROLE,
    SUMMARY_EXPORT_ROLE,
    ProductBacktestPublication,
)
from v3_backend.runtime.product_runtime import ProductRuntime, mint_v3_id, wire_time
from v3_backend.runtime.product_strategy import ProductStrategyService
from v3_backend.runtime.product_workers import ProductResearchWorkerConfig

from apps.backend.tests.v1_1_factor.test_factor_panel import GOLDEN_FORMULA
from apps.backend.tests.v1_1_strategy.test_product_strategy_authoring import _strategy_spec


FIRST_SESSION = date(2026, 7, 6)


def _test_resource_admission() -> ExactInputReference:
    digest = canonical_sha256(
        {"schema_version": "v3.test-resource-admission/1.0.0"}
    )
    return ExactInputReference(
        "RESOURCE_ADMISSION", "radm_sha256_" + digest, digest, PRE_ALPHA_CEILING
    )


def _admitted_panel_csv(
    *,
    strict_market_truth: bool = False,
    corporate_action_ref: str | None = None,
    corporate_action_offset: int = 10,
    first_session: date = FIRST_SESSION,
) -> bytes:
    header = ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
    if strict_market_truth:
        header.extend(
            [
                "is_suspended",
                "is_st",
                "tradable",
                "price_limit_up",
                "price_limit_down",
                "no_price_limit_session",
            ]
        )
    if corporate_action_ref is not None:
        header.append("corporate_action_ref")
    rows = [",".join(header)]
    for offset in range(70):
        session = first_session + timedelta(days=offset)
        for symbol, price in (
            ("600519", 100 if offset < 60 else 200),
            ("000001", 300 if offset < 60 else 150),
        ):
            volume = 10_000
            values = [
                symbol,
                session.isoformat(),
                str(price),
                str(price),
                str(price),
                str(price),
                str(volume),
                str(price * volume),
            ]
            if strict_market_truth:
                values.extend(["false", "false", "true", "100000", "0.01", "false"])
            if corporate_action_ref is not None:
                values.append(
                    corporate_action_ref
                    if offset == corporate_action_offset and symbol == "600519"
                    else ""
                )
            rows.append(",".join(values))
    return ("\n".join(rows) + "\n").encode("utf-8")


def _published_strategy(
    root: Path,
    *,
    strict_market_truth: bool = False,
    corporate_action_ref: str | None = None,
    corporate_action_events: tuple[Mapping[str, object], ...] = (),
    corporate_action_offset: int = 10,
    assumption_mode: str = "RESEARCH_APPROXIMATE",
    first_session: date = FIRST_SESSION,
):
    product = ProductRuntime(root)
    project = create_project(
        product,
        display_name="Product research Backtest",
        notes=None,
        idempotency_key="create-product-research-backtest",
    )
    if corporate_action_ref is not None and corporate_action_events:
        raise ValueError("tests must supply a missing ref or actual Corporate Action payload, not both")
    if corporate_action_events:
        corporate_action_ref = ProductCorporateActionService(product).publish_set(
            project_id=project["project_id"],
            events=corporate_action_events,
        )["corporate_action_set_id"]
    imported = ProductDataService(product).import_local_dataset(
        project_id=project["project_id"],
        project_context_revision_id=project["project_context_revision_id"],
        display_name="admitted-backtest-panel.csv",
        source=io.BytesIO(
            _admitted_panel_csv(
                strict_market_truth=strict_market_truth,
                corporate_action_ref=corporate_action_ref,
                corporate_action_offset=corporate_action_offset,
                first_session=first_session,
            )
        ),
        intent=LocalDataImportIntentV1(
            media_type="text/csv",
            volume_unit="SHARES",
            amount_unit="CNY",
            timezone="Asia/Shanghai",
            adjustment="UNADJUSTED",
        ),
        limits=LocalDataImportLimits(max_partition_bytes=6_000),
    )
    study = ProductFactorStudyService(product).run_factor_study(
        project_id=project["project_id"],
        project_context_revision_id=imported["project_context_revision_id"],
        formula_source=GOLDEN_FORMULA,
        analysis_output_name="MJ",
    )
    strategy_service = ProductStrategyService(product)
    spec = _strategy_spec(
        strategy_service,
        imported,
        study,
        assumption_mode=assumption_mode,
    )
    strategy = strategy_service.publish_strategy(
        project_id=project["project_id"],
        project_context_revision_id=imported["project_context_revision_id"],
        spec=spec,
    )
    return project, imported, strategy


def _wait_for_terminal(product: ProductRuntime, task_id: str):
    deadline = time.monotonic() + 20.0
    task = product.task_persistence.read_task(task_id)
    while time.monotonic() < deadline and task.state not in TASK_TERMINAL_STATES:
        time.sleep(0.05)
        task = product.task_persistence.read_task(task_id)
    return task


def _assumption_receipt(request, panel, execution_inputs) -> dict[str, object]:
    mode = execution_inputs.profile.assumption_mode
    return {
        "schema_version": "v3.research-assumption-receipt/1.0.0",
        "research_backtest_request_id": request.research_backtest_request_id,
        "assumption_mode": mode,
        "market_state_derivation": (
            "VERIFIED_CANONICAL_EXPLICIT_STATUS_FIELDS"
            if mode == "STRICT_FAIL_CLOSED"
            else "VERIFIED_BAR_PRESENT_AND_VOLUME_POSITIVE"
        ),
        "corporate_actions": "NO_ADMITTED_ACTIONS_IN_RESOLVED_RANGE",
        "snapshot_id": panel.snapshot_id,
        "snapshot_sha256": panel.manifest_sha256,
        "research_execution_profile_id": execution_inputs.profile.profile_id,
        "truth": "NOT_FORMAL",
        "admission": "PRE_ALPHA",
    }


class ProductResearchBacktestAcceptanceTests(unittest.TestCase):
    def test_acc_c3_01_runtime_session_remains_responsive_while_backtest_child_is_live(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-backtest-runtime-session-") as directory:
            root = Path(directory)
            project, imported, strategy = _published_strategy(root)
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=1.0
                ),
            )
            facade = ProductEntryFacade(product)
            submit_started = time.monotonic()
            accepted = facade.handlers()[
                "ProductEntryService.v1.submitResearchBacktest"
            ](
                {
                    "request_id": "01890f3c-7b5a-7000-8000-000000000911",
                    "project_id": project["project_id"],
                    "project_context_revision_id": imported[
                        "project_context_revision_id"
                    ],
                    "expected_api_version": "1.1",
                    "research_strategy_spec_id": strategy[
                        "research_strategy_spec_id"
                    ],
                    "session_start": FIRST_SESSION.isoformat(),
                    "session_end": (FIRST_SESSION + timedelta(days=69)).isoformat(),
                    "slippage_bps": "10",
                    "daily_volume_participation_rate": "0.1",
                    "idempotency_key": "acc-c3-01-runtime-session",
                }
            )
            try:
                self.assertLess(time.monotonic() - submit_started, 2.0)
                get_operation(
                    "ProductEntryService.v1.submitResearchBacktest"
                ).validate_response(accepted)
                self.assertEqual(accepted["read_model"]["accepted_state"], "QUEUED")
                task_id = str(accepted["read_model"]["task_id"])
                process = product.research_workers.task_process(task_id)
                self.assertIsNotNone(process)
                self.assertTrue(process.is_alive())

                handlers: dict[str, object] = {}
                for product_facade in build_product_facades(product):
                    handlers.update(product_facade.handlers())
                token = bytes(range(32))
                fixed_hello = create_hello(
                    "c3-backtest-runtime", 1, "0.1.0", [], nonce="ca" * 32
                )
                accept = {
                    "kind": "supervisor.accept",
                    "token_proof": token_proof(token, fixed_hello["nonce"]),
                    "requested_protocol": "v3.local/1.0",
                    "requested_asl_versions": {
                        name: "1.0" for name in SERVICE_CONTRACTS
                    },
                    "desktop_version": "0.1.0",
                    "project_id": project["project_id"],
                    "project_context_revision_id": imported[
                        "project_context_revision_id"
                    ],
                    "last_project_event_sequence": 0,
                }
                health = {
                    "kind": "runtime.health",
                    "control_request_id": "01890f3c-7b5a-7000-8000-000000000912",
                    "runtime_generation": 1,
                    "deadline_at": "2099-01-01T00:00:00Z",
                }

                def request_frame(request_id: str, operation_id: str, body: dict[str, object]):
                    return {
                        "kind": "request",
                        "request_id": request_id,
                        "operation_id": operation_id,
                        "contract_version": "1.0.0",
                        "project_id": project["project_id"],
                        "project_context_revision_id": imported[
                            "project_context_revision_id"
                        ],
                        "body": {
                            "request_id": request_id,
                            "project_id": project["project_id"],
                            "project_context_revision_id": imported[
                                "project_context_revision_id"
                            ],
                            "expected_api_version": "1.0",
                            **body,
                        },
                    }

                get_task = request_frame(
                    "01890f3c-7b5a-7000-8000-000000000913",
                    "TaskService.v1.getTask",
                    {"task_id": task_id},
                )
                get_events = request_frame(
                    "01890f3c-7b5a-7000-8000-000000000914",
                    "TaskService.v1.getEvents",
                    {"after_sequence": 0, "limit": 1000},
                )
                source = io.BytesIO(
                    encode_frame(accept)
                    + encode_frame(health)
                    + encode_frame(get_task)
                    + encode_frame(get_events)
                )
                sink = io.BytesIO()
                session = RuntimeSession(
                    RuntimePorts(
                        operation_handlers=handlers,
                        capabilities=product.capabilities(),
                    ),
                    token,
                    "0.1.0",
                    backend_instance_id="c3-backtest-runtime",
                )
                session_started = time.monotonic()
                with patch(
                    "v3_backend.runtime.composition_root.create_hello",
                    return_value=fixed_hello,
                ):
                    session.run(source, sink)
                self.assertLess(time.monotonic() - session_started, 0.5)
                decoded = FrameDecoder().feed(sink.getvalue())
                self.assertEqual(decoded[2]["kind"], "runtime.health")
                self.assertEqual(decoded[3]["status"], "OK")
                self.assertEqual(decoded[3]["body"]["read_model"]["task_id"], task_id)
                self.assertIn(
                    decoded[3]["body"]["read_model"]["state"],
                    {"QUEUED", "RUNNING"},
                )
                self.assertEqual(decoded[4]["status"], "OK")
                self.assertTrue(
                    any(
                        item["task_id"] == task_id
                        for item in decoded[4]["body"]["read_model"]["items"]
                    )
                )
                self.assertTrue(process.is_alive())
            finally:
                product.research_workers.shutdown_all()

    def test_retry_attempt_failure_does_not_retransition_terminal_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-backtest-retry-failure-") as directory:
            root = Path(directory)
            project, imported, strategy = _published_strategy(root)
            product = ProductRuntime(root)
            service = ProductResearchBacktestService(product)
            prepared = service._prepare_submission(
                ProductResearchBacktestSubmission(
                    project_id=project["project_id"],
                    project_context_revision_id=imported["project_context_revision_id"],
                    research_strategy_spec_id=strategy["research_strategy_spec_id"],
                    session_start=FIRST_SESSION,
                    session_end=FIRST_SESSION + timedelta(days=69),
                    slippage_bps="10",
                    daily_volume_participation_rate="0.1",
                    idempotency_key="retry-product-backtest-terminal-run-failure",
                )
            )
            handles = service._accept_request(prepared)
            product.execution._finish_failure(
                handles.task,
                handles.run,
                handles.attempt,
                error=OSError("first transient failure"),
                category=ErrorCategory.TRANSIENT_IO,
            )
            terminal_handles = _BacktestTaskHandles(
                product.task_persistence.read_task(handles.task.task_id),
                product.execution._read_run(handles.run.run_id),
                product.task_persistence.latest_attempt(handles.task.task_id),
            )
            with (
                patch.object(
                    product.execution,
                    "_record_progress",
                    side_effect=OSError("second attempt transient failure"),
                ),
                patch.object(product.execution, "_finish_failure") as finish_failure,
                self.assertRaises(OSError),
            ):
                service.execute_accepted(prepared, terminal_handles)
            self.assertFalse(finish_failure.call_args.kwargs["run_transition"])

    def test_declared_retry_from_start_replays_product_backtest_in_isolated_worker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-backtest-retry-") as directory:
            root = Path(directory)
            project, imported, strategy = _published_strategy(root)
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=0.25
                ),
            )
            service = ProductResearchBacktestService(product)
            submission = ProductResearchBacktestSubmission(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                research_strategy_spec_id=strategy["research_strategy_spec_id"],
                session_start=FIRST_SESSION,
                session_end=FIRST_SESSION + timedelta(days=69),
                slippage_bps="10",
                daily_volume_participation_rate="0.1",
                idempotency_key="retry-product-research-backtest",
            )
            prepared = service._prepare_submission(submission)
            service._lightweight_preflight(prepared)
            handles = service._accept_request(prepared)
            product.execution._finish_failure(
                handles.task,
                handles.run,
                handles.attempt,
                error=OSError("transient artifact read failure"),
                category=ErrorCategory.TRANSIENT_IO,
            )
            failed = product.task_persistence.read_task(handles.task.task_id)
            failed_attempt = product.task_persistence.latest_attempt(
                handles.task.task_id
            )
            self.assertEqual(failed.state.value, "FAILED")
            self.assertEqual(
                failed_attempt.terminal_error_category,
                ErrorCategory.TRANSIENT_IO.value,
            )

            try:
                retried = TaskFacade(product).retry_task(
                    {
                        "request_id": "01890f3c-7b5a-7000-8000-000000000901",
                        "project_id": project["project_id"],
                        "project_context_revision_id": imported[
                            "project_context_revision_id"
                        ],
                        "expected_api_version": "1.0",
                        "task_id": failed.task_id,
                        "failed_attempt_id": failed_attempt.attempt_id,
                        "expected_state_version": failed.state_version,
                    }
                )["read_model"]
                self.assertEqual(retried["task_id"], failed.task_id)
                self.assertEqual(retried["run_id"], failed.active_run_id)
                self.assertEqual(retried["attempt"]["ordinal"], 2)
                self.assertNotEqual(
                    retried["attempt"]["attempt_id"], failed_attempt.attempt_id
                )
                self.assertIn(
                    retried["state"],
                    {"QUEUED", "RUNNING", "SUCCEEDED"},
                    "retry must dispatch PRODUCT_RESEARCH_BACKTEST instead of "
                    "deterministically failing its persisted execution context",
                )
                terminal = _wait_for_terminal(product, failed.task_id)
                self.assertEqual(terminal.state.value, "SUCCEEDED")
                read_model = service.get_backtest(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                    research_backtest_request_id=prepared.research_backtest_request_id,
                )
                self.assertEqual(read_model["result_state"], "VALID")
            finally:
                product.research_workers.shutdown_all()

    def test_strict_profile_uses_verified_snapshot_state_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-strict-backtest-") as directory:
            root = Path(directory)
            project, imported, strategy = _published_strategy(
                root,
                strict_market_truth=True,
                assumption_mode="STRICT_FAIL_CLOSED",
            )
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(),
            )
            service = ProductResearchBacktestService(product)
            accepted = service.submit(
                ProductResearchBacktestSubmission(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                    research_strategy_spec_id=strategy[
                        "research_strategy_spec_id"
                    ],
                    session_start=FIRST_SESSION,
                    session_end=FIRST_SESSION + timedelta(days=69),
                    slippage_bps="0",
                    daily_volume_participation_rate="0.1",
                    idempotency_key="strict-product-backtest",
                )
            )
            try:
                task = _wait_for_terminal(product, accepted["task_id"])
                connection = product._connection(read_only=True)
                try:
                    terminal_events = [
                        json.loads(str(row[0]))
                        for row in connection.execute(
                            "SELECT payload_json FROM task_event WHERE task_id=? "
                            "ORDER BY project_sequence",
                            (accepted["task_id"],),
                        ).fetchall()
                    ]
                finally:
                    connection.close()
                self.assertEqual(task.state.value, "SUCCEEDED", terminal_events)
                task_read_model = TaskFacade(product).get_task(
                    {
                        "request_id": "09ad3401-2c22-4b84-9079-d301cab05f90",
                        "project_id": project["project_id"],
                        "task_id": accepted["task_id"],
                    }
                )["read_model"]
                self.assertEqual(task_read_model["state"], "SUCCEEDED")
                self.assertIsNotNone(task_read_model["result_id"])
                self.assertIn("BACKTEST_RUN_RESULT", task_read_model["outputs"])
                read_model = service.get_backtest(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                    research_backtest_request_id=accepted[
                        "research_backtest_request_id"
                    ],
                )
                self.assertEqual(read_model["assumption_mode"], "STRICT_FAIL_CLOSED")
                receipt = json.loads(
                    product.read_verified_bytes(
                        read_model["assumption_receipt_artifact_id"]
                    ).decode("utf-8")
                )
                self.assertEqual(receipt["assumption_mode"], "STRICT_FAIL_CLOSED")
                self.assertEqual(
                    receipt["market_state_derivation"],
                    "VERIFIED_CANONICAL_EXPLICIT_STATUS_FIELDS",
                )
                self.assertEqual(
                    ProductResearchBacktestService(ProductRuntime(root)).get_backtest(
                        project_id=project["project_id"],
                        project_context_revision_id=imported[
                            "project_context_revision_id"
                        ],
                        research_backtest_request_id=accepted[
                            "research_backtest_request_id"
                        ],
                    )["assumption_mode"],
                    "STRICT_FAIL_CLOSED",
                )
                connection = product._connection()
                try:
                    terminal_row = connection.execute(
                        "SELECT project_id,run_id,attempt_id,event_version,"
                        "occurred_at,persisted_at FROM task_event "
                        "WHERE task_id=? AND event_type='TASK_SUCCEEDED' "
                        "ORDER BY project_sequence DESC LIMIT 1",
                        (accepted["task_id"],),
                    ).fetchone()
                    self.assertIsNotNone(terminal_row)
                    next_sequence = int(
                        connection.execute(
                            "SELECT COALESCE(MAX(project_sequence),0)+1 "
                            "FROM task_event WHERE project_id=?",
                            (project["project_id"],),
                        ).fetchone()[0]
                    )
                    connection.execute(
                        "INSERT INTO task_event("
                        "task_event_id,project_id,project_sequence,task_id,run_id,"
                        "attempt_id,event_type,event_version,payload_json,occurred_at,"
                        "persisted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            mint_v3_id("tev_"),
                            project["project_id"],
                            next_sequence,
                            accepted["task_id"],
                            str(terminal_row["run_id"]),
                            str(terminal_row["attempt_id"]),
                            "TASK_SUCCEEDED",
                            int(terminal_row["event_version"]),
                            json.dumps(
                                {
                                    "result_id": task_read_model["result_id"],
                                    "result_state": "VALID",
                                    "outputs": [],
                                },
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            str(terminal_row["occurred_at"]),
                            str(terminal_row["persisted_at"]),
                        ),
                    )
                    connection.commit()
                finally:
                    connection.close()
                with self.assertRaisesRegex(
                    TruthPreconditionFailedError,
                    "outputs must be an object when present",
                ):
                    TaskFacade(product).get_task(
                        {
                            "request_id": "1b89fa89-4159-45e5-a90d-4d0a2a7de645",
                            "project_id": project["project_id"],
                            "task_id": accepted["task_id"],
                        }
                    )
            finally:
                product.research_workers.shutdown_all()

    def test_strict_unknown_state_fails_in_worker_without_valid_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-strict-unknown-") as directory:
            root = Path(directory)
            project, imported, strategy = _published_strategy(
                root, assumption_mode="STRICT_FAIL_CLOSED"
            )
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(),
            )
            service = ProductResearchBacktestService(product)
            accepted = service.submit(
                ProductResearchBacktestSubmission(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                    research_strategy_spec_id=strategy[
                        "research_strategy_spec_id"
                    ],
                    session_start=FIRST_SESSION,
                    session_end=FIRST_SESSION + timedelta(days=69),
                    slippage_bps="10",
                    daily_volume_participation_rate="0.1",
                    idempotency_key="fail-closed-strict-unknown",
                )
            )
            try:
                task = _wait_for_terminal(product, accepted["task_id"])
                self.assertEqual(task.state.value, "FAILED")
                connection = product._connection(read_only=True)
                try:
                    events = connection.execute(
                        "SELECT payload_json FROM task_event WHERE task_id=? "
                        "AND event_type='TASK_FAILED' ORDER BY project_sequence DESC",
                        (accepted["task_id"],),
                    ).fetchall()
                    valid_results = connection.execute(
                        "SELECT COUNT(*) FROM result WHERE project_id=? AND state='VALID'",
                        (project["project_id"],),
                    ).fetchone()[0]
                finally:
                    connection.close()
                self.assertTrue(
                    any(
                        "strict execution requires explicit trading-state fields"
                        in json.loads(str(row[0]))["error_message"]
                        for row in events
                    )
                )
                self.assertEqual(valid_results, 0)
                self.assertEqual(
                    product.references(
                        project["project_id"],
                        "PRODUCT_RESEARCH_BACKTEST_READ_MODEL",
                    ),
                    [],
                )
            finally:
                product.research_workers.shutdown_all()

    def test_known_corporate_action_fails_preflight_before_task_acceptance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-known-action-") as directory:
            root = Path(directory)
            project, imported, strategy = _published_strategy(
                root,
                corporate_action_ref="cax_sha256_" + "a" * 64,
            )
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(),
            )
            service = ProductResearchBacktestService(product)
            with self.assertRaisesRegex(
                CapabilityUnavailableError,
                "known corporate-action refs require an admitted Corporate Action owner",
            ):
                service.submit(
                    ProductResearchBacktestSubmission(
                        project_id=project["project_id"],
                        project_context_revision_id=imported[
                            "project_context_revision_id"
                        ],
                        research_strategy_spec_id=strategy[
                            "research_strategy_spec_id"
                        ],
                        session_start=FIRST_SESSION,
                        session_end=FIRST_SESSION + timedelta(days=69),
                        slippage_bps="10",
                        daily_volume_participation_rate="0.1",
                        idempotency_key="fail-closed-known-action",
                    )
                )
            connection = product._connection(read_only=True)
            try:
                task_count = connection.execute(
                    "SELECT COUNT(*) FROM task WHERE project_id=? AND operation_id=?",
                    (
                        project["project_id"],
                        "ProductEntryService.v1.submitResearchBacktest",
                    ),
                ).fetchone()[0]
                valid_results = connection.execute(
                    "SELECT COUNT(*) FROM result WHERE project_id=? AND state='VALID'",
                    (project["project_id"],),
                ).fetchone()[0]
            finally:
                connection.close()
                product.research_workers.shutdown_all()
            self.assertEqual(task_count, 0)
            self.assertEqual(valid_results, 0)

    def test_acc_c3_06_product_resolves_and_applies_admitted_corporate_action_payloads(self) -> None:
        cases = (
            (
                "cash-dividend",
                {
                    "instrument_id": "ins_cn_sse_600519",
                    "ex_date": (FIRST_SESSION + timedelta(days=65)).isoformat(),
                    "action_type": "CASH_DIVIDEND",
                    "cash_per_share": "0.1",
                    "ratio_numerator": 1,
                    "ratio_denominator": 1,
                },
                "CASH_DIVIDEND",
            ),
            (
                "integral-bonus-split",
                {
                    "instrument_id": "ins_cn_sse_600519",
                    "ex_date": (FIRST_SESSION + timedelta(days=65)).isoformat(),
                    "action_type": "BONUS_OR_SPLIT",
                    "cash_per_share": "0",
                    "ratio_numerator": 2,
                    "ratio_denominator": 1,
                },
                "BONUS_OR_SPLIT",
            ),
        )
        for label, event, expected_type in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix=f"v3-v1-1-product-action-{label}-"
            ) as directory:
                root = Path(directory)
                project, imported, strategy = _published_strategy(
                    root,
                    corporate_action_events=(event,),
                    corporate_action_offset=65,
                )
                product = ProductRuntime(
                    root,
                    research_worker_config=ProductResearchWorkerConfig(),
                )
                service = ProductResearchBacktestService(product)
                accepted = service.submit(
                    ProductResearchBacktestSubmission(
                        project_id=project["project_id"],
                        project_context_revision_id=imported[
                            "project_context_revision_id"
                        ],
                        research_strategy_spec_id=strategy[
                            "research_strategy_spec_id"
                        ],
                        session_start=FIRST_SESSION,
                        session_end=FIRST_SESSION + timedelta(days=69),
                        slippage_bps="10",
                        daily_volume_participation_rate="0.1",
                        idempotency_key=f"acc-c3-06-{label}",
                    )
                )
                try:
                    task = _wait_for_terminal(product, accepted["task_id"])
                    connection = product._connection(read_only=True)
                    try:
                        task_events = [
                            json.loads(str(row[0]))
                            for row in connection.execute(
                                "SELECT payload_json FROM task_event WHERE task_id=? "
                                "ORDER BY project_sequence",
                                (accepted["task_id"],),
                            ).fetchall()
                        ]
                    finally:
                        connection.close()
                    self.assertEqual(task.state.value, "SUCCEEDED", task_events)
                    read_model = service.get_backtest(
                        project_id=project["project_id"],
                        project_context_revision_id=imported[
                            "project_context_revision_id"
                        ],
                        research_backtest_request_id=accepted[
                            "research_backtest_request_id"
                        ],
                    )
                    run_spec = json.loads(
                        product.read_verified_bytes(
                            read_model["run_spec_artifact_id"]
                        ).decode("utf-8")
                    )
                    resolved_actions = [
                        action
                        for session in run_spec["sessions"]
                        for action in session["corporate_actions"]
                    ]
                    self.assertEqual(len(resolved_actions), 1)
                    self.assertEqual(
                        resolved_actions[0]["action_type"], expected_type
                    )
                    self.assertTrue(
                        resolved_actions[0]["action_id"].startswith("cae_sha256_")
                    )
                    action_ref = next(
                        ref
                        for ref in run_spec["exact_references"]
                        if ref["reference_kind"] == "CORPORATE_ACTIONS"
                    )
                    self.assertTrue(action_ref["source_id"].startswith("cax_sha256_"))
                    result = json.loads(
                        product.read_verified_bytes(
                            read_model["result_artifact_id"]
                        ).decode("utf-8")
                    )
                    if expected_type == "CASH_DIVIDEND":
                        dividend = next(
                            row
                            for row in result["cash_ledger"]
                            if row["kind"] == "CASH_DIVIDEND"
                        )
                        self.assertGreater(Decimal(dividend["amount"]), Decimal("0"))
                    else:
                        split = next(
                            row
                            for row in result["position_ledger"]
                            if row["reference_id"]
                            == resolved_actions[0]["action_id"]
                        )
                        self.assertGreater(split["quantity_delta"], 0)
                finally:
                    product.research_workers.shutdown_all()

    def test_acc_c3_06_fractional_rights_delisting_and_other_fail_preflight(self) -> None:
        cases = (
            ("fractional", "BONUS_OR_SPLIT", 3, 2),
            ("rights", "RIGHTS_ISSUE", 1, 1),
            ("delisting", "DELISTING", 1, 1),
            ("other", "OTHER", 1, 1),
        )
        for label, action_type, numerator, denominator in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix=f"v3-v1-1-product-action-reject-{label}-"
            ) as directory:
                root = Path(directory)
                project, imported, strategy = _published_strategy(
                    root,
                    corporate_action_events=(
                        {
                            "instrument_id": "ins_cn_sse_600519",
                            "ex_date": (
                                FIRST_SESSION + timedelta(days=65)
                            ).isoformat(),
                            "action_type": action_type,
                            "cash_per_share": "0",
                            "ratio_numerator": numerator,
                            "ratio_denominator": denominator,
                        },
                    ),
                    corporate_action_offset=65,
                )
                product = ProductRuntime(
                    root,
                    research_worker_config=ProductResearchWorkerConfig(),
                )
                service = ProductResearchBacktestService(product)
                with self.assertRaises(CapabilityUnavailableError) as raised:
                    service.submit(
                        ProductResearchBacktestSubmission(
                            project_id=project["project_id"],
                            project_context_revision_id=imported[
                                "project_context_revision_id"
                            ],
                            research_strategy_spec_id=strategy[
                                "research_strategy_spec_id"
                            ],
                            session_start=FIRST_SESSION,
                            session_end=FIRST_SESSION + timedelta(days=69),
                            slippage_bps="10",
                            daily_volume_participation_rate="0.1",
                            idempotency_key=f"acc-c3-06-reject-{label}",
                        )
                    )
                self.assertEqual(
                    raised.exception.details.get("reason_code"),
                    "CORPORATE_ACTION_NOT_AVAILABLE",
                )
                connection = product._connection(read_only=True)
                try:
                    task_count = connection.execute(
                        "SELECT COUNT(*) FROM task WHERE project_id=? AND operation_id=?",
                        (
                            project["project_id"],
                            "ProductEntryService.v1.submitResearchBacktest",
                        ),
                    ).fetchone()[0]
                finally:
                    connection.close()
                    product.research_workers.shutdown_all()
                self.assertEqual(task_count, 0)

    def test_strategy_binding_and_snapshot_coverage_fail_before_task_acceptance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-backtest-light-preflight-") as directory:
            root = Path(directory)
            project, imported, strategy = _published_strategy(root)
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(),
            )
            service = ProductResearchBacktestService(product)
            base = {
                "project_id": project["project_id"],
                "project_context_revision_id": imported[
                    "project_context_revision_id"
                ],
                "research_strategy_spec_id": strategy[
                    "research_strategy_spec_id"
                ],
                "session_start": FIRST_SESSION,
                "session_end": FIRST_SESSION + timedelta(days=69),
                "slippage_bps": "10",
                "daily_volume_participation_rate": "0.1",
            }
            with self.assertRaisesRegex(
                TruthPreconditionFailedError,
                "latest exact Strategy",
            ):
                service.submit(
                    ProductResearchBacktestSubmission(
                        **{
                            **base,
                            "research_strategy_spec_id": "rssv_sha256_" + "f" * 64,
                        },
                        idempotency_key="wrong-strategy-preflight",
                    )
                )
            with self.assertRaisesRegex(
                InvalidArgumentError,
                "exceeds current Snapshot coverage",
            ):
                service.submit(
                    ProductResearchBacktestSubmission(
                        **{
                            **base,
                            "session_start": FIRST_SESSION - timedelta(days=1),
                        },
                        idempotency_key="wrong-coverage-preflight",
                    )
                )
            connection = product._connection(read_only=True)
            try:
                task_count = connection.execute(
                    "SELECT COUNT(*) FROM task WHERE project_id=? AND operation_id=?",
                    (
                        project["project_id"],
                        "ProductEntryService.v1.submitResearchBacktest",
                    ),
                ).fetchone()[0]
            finally:
                connection.close()
                product.research_workers.shutdown_all()
            self.assertEqual(task_count, 0)

    def test_execution_policy_coverage_fails_before_task_acceptance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-policy-preflight-") as directory:
            root = Path(directory)
            uncovered_start = FIRST_SESSION - timedelta(days=1)
            project, imported, strategy = _published_strategy(
                root,
                first_session=uncovered_start,
            )
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(),
            )
            service = ProductResearchBacktestService(product)
            with self.assertRaises(CapabilityUnavailableError) as raised:
                service.submit(
                    ProductResearchBacktestSubmission(
                        project_id=project["project_id"],
                        project_context_revision_id=imported[
                            "project_context_revision_id"
                        ],
                        research_strategy_spec_id=strategy[
                            "research_strategy_spec_id"
                        ],
                        session_start=uncovered_start,
                        session_end=FIRST_SESSION + timedelta(days=68),
                        slippage_bps="10",
                        daily_volume_participation_rate="0.1",
                        idempotency_key="policy-coverage-preflight",
                    )
                )
            self.assertEqual(
                raised.exception.details,
                {
                    "reason_code": "EXECUTION_POLICY_COVERAGE_UNAVAILABLE",
                    "coverage_start": FIRST_SESSION.isoformat(),
                    "coverage_end": None,
                },
            )
            connection = product._connection(read_only=True)
            try:
                task_count = connection.execute(
                    "SELECT COUNT(*) FROM task WHERE project_id=? AND operation_id=?",
                    (
                        project["project_id"],
                        "ProductEntryService.v1.submitResearchBacktest",
                    ),
                ).fetchone()[0]
            finally:
                connection.close()
                product.research_workers.shutdown_all()
            self.assertEqual(task_count, 0)

    def test_execution_policy_registry_rejects_overlap_and_board_gaps(self) -> None:
        registry = ExecutionPolicyRegistry.bounded_v1_1()
        bundle = registry._bundles[0]
        with self.assertRaisesRegex(ValueError, "overlap"):
            ExecutionPolicyRegistry((bundle, bundle))
        board_gap = ExecutionPolicyRegistry(
            (replace(bundle, boards=(Board.SSE_MAIN,)),)
        )
        with self.assertRaises(CapabilityUnavailableError) as captured:
            board_gap.resolve(
                session_start=FIRST_SESSION,
                session_end=FIRST_SESSION,
                boards=(Board.SSE_MAIN, Board.SZSE_MAIN),
            )
        self.assertEqual(
            captured.exception.details["reason_code"],
            "EXECUTION_POLICY_COVERAGE_UNAVAILABLE",
        )

    def test_product_entry_and_project_home_restore_latest_strategy_and_valid_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-backtest-home-") as directory:
            root = Path(directory)
            project, imported, strategy = _published_strategy(root)
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(),
            )
            facade = ProductEntryFacade(product)
            self.assertIn(
                "ProductEntryService.v1.submitResearchBacktest",
                facade.handlers(),
                "the product bridge cannot call an unregistered Backtest operation",
            )

            accepted = facade.handlers()[
                "ProductEntryService.v1.submitResearchBacktest"
            ](
                {
                    "request_id": "11111111-1111-4111-8111-111111111111",
                    "project_id": project["project_id"],
                    "project_context_revision_id": imported[
                        "project_context_revision_id"
                    ],
                    "research_strategy_spec_id": strategy[
                        "research_strategy_spec_id"
                    ],
                    "session_start": FIRST_SESSION.isoformat(),
                    "session_end": (FIRST_SESSION + timedelta(days=69)).isoformat(),
                    "slippage_bps": "10",
                    "daily_volume_participation_rate": "0.1",
                    "idempotency_key": "product-backtest-home-1",
                }
            )
            try:
                get_operation(
                    "ProductEntryService.v1.submitResearchBacktest"
                ).validate_response(accepted)
                self.assertEqual(accepted["truth_state"], "NOT_FORMAL")
                self.assertEqual(accepted["read_model"]["accepted_state"], "QUEUED")
                task_id = accepted["read_model"]["task_id"]
                deadline = time.monotonic() + 20.0
                while time.monotonic() < deadline:
                    task = product.task_persistence.read_task(task_id)
                    if task.state in TASK_TERMINAL_STATES:
                        break
                    time.sleep(0.05)
                self.assertEqual(task.state.value, "SUCCEEDED")
                event_page = TaskFacade(product).get_events(
                    {
                        "request_id": "33333333-3333-4333-8333-333333333333",
                        "project_id": project["project_id"],
                        "after_sequence": 0,
                        "limit": 1000,
                    }
                )["read_model"]
                task_events = [
                    item
                    for item in event_page["items"]
                    if item["task_id"] == task_id
                    and item["event_type"] in {"TASK_PROGRESS", "TASK_SUCCEEDED"}
                ]
                self.assertEqual(
                    [item["event_type"] for item in task_events],
                    [
                        "TASK_PROGRESS",
                        "TASK_PROGRESS",
                        "TASK_PROGRESS",
                        "TASK_PROGRESS",
                        "TASK_PROGRESS",
                        "TASK_PROGRESS",
                        "TASK_SUCCEEDED",
                    ],
                )
                progress = [item["body"] for item in task_events[:-1]]
                self.assertEqual(
                    progress,
                    [
                        {
                            "phase": "DISPATCHED",
                            "completed_units": 0,
                            "total_units": 3,
                            "work_unit": "pipeline_phases",
                            "sequence": 1,
                            "counters": {"accepted": 1},
                        },
                        {
                            "phase": "EXECUTING",
                            "completed_units": 1,
                            "total_units": 3,
                            "work_unit": "pipeline_phases",
                            "sequence": 2,
                            "counters": {"runtime_context_bound": 1},
                        },
                        {
                            "phase": "VALIDATING",
                            "completed_units": 0,
                            "total_units": 4,
                            "work_unit": "CANONICAL_OWNER_RESOLUTION",
                            "sequence": 3,
                            "counters": {},
                        },
                        {
                            "phase": "COMPUTING",
                            "completed_units": 1,
                            "total_units": 4,
                            "work_unit": "DETERMINISTIC_BACKTEST",
                            "sequence": 4,
                            "counters": {},
                        },
                        {
                            "phase": "PUBLISHING",
                            "completed_units": 2,
                            "total_units": 4,
                            "work_unit": "RESULT_PUBLICATION",
                            "sequence": 5,
                            "counters": {},
                        },
                        {
                            "phase": "RECONCILING",
                            "completed_units": 3,
                            "total_units": 4,
                            "work_unit": "RESULT_RECONCILIATION",
                            "sequence": 6,
                            "counters": {},
                        },
                    ],
                )
            finally:
                product.research_workers.shutdown_all()

            restarted = ProductRuntime(root)
            home_response = ProductEntryFacade(restarted).get_project_home(
                {
                    "request_id": "22222222-2222-4222-8222-222222222222",
                    "project_id": project["project_id"],
                    "project_context_revision_id": imported[
                        "project_context_revision_id"
                    ],
                }
            )
            get_operation("ProductEntryService.v1.getProjectHome").validate_response(
                home_response
            )
            home = home_response["read_model"]
            self.assertEqual(
                home["backtest_policy_coverage"],
                ProductResearchBacktestService.bounded_policy_coverage(),
            )
            self.assertEqual(
                home["backtest_policy_coverage"]["coverage_start"],
                FIRST_SESSION.isoformat(),
            )
            self.assertIsNone(
                home["backtest_policy_coverage"]["coverage_end"]
            )
            self.assertEqual(
                home["strategy_authoring_profile"],
                {
                    "schema_version": "v3.product-strategy-authoring-profile/1.0.0",
                    "truth": "NOT_FORMAL",
                    "admission": "PRE_ALPHA",
                    "position_sizing_options": [
                        "SINGLE_ASSET_FULL_WEIGHT",
                        "EQUAL_WEIGHT_ACTIVE_SIGNALS",
                    ],
                    "max_positions_min": 1,
                    "max_positions_max": 20,
                    "gross_exposure_min": "0",
                    "gross_exposure_max": "1",
                    "rebalance": "NEXT_OPEN_AFTER_SIGNAL",
                    "profile_refs": ProductStrategyService.bounded_profile_ids(),
                    "assumption_profiles": list(
                        ProductStrategyService.bounded_assumption_profiles()
                    ),
                },
            )
            self.assertEqual(home["strategy_state"], "AVAILABLE")
            self.assertEqual(home["strategy_unavailable_reason"], "NONE")
            self.assertEqual(
                home["strategy"]["research_strategy_spec_id"],
                strategy["research_strategy_spec_id"],
            )
            self.assertEqual(home["backtest_state"], "AVAILABLE")
            self.assertEqual(home["backtest_unavailable_reason"], "NONE")
            self.assertEqual(home["backtest"]["result_state"], "VALID")
            self.assertEqual(home["backtest"]["truth"], "NOT_FORMAL")
            self.assertEqual(home["backtest"]["admission"], "PRE_ALPHA")
            self.assertEqual(
                home["backtest"]["assumption_mode"], "RESEARCH_APPROXIMATE"
            )
            self.assertEqual(
                home["backtest"]["research_strategy_spec_id"],
                strategy["research_strategy_spec_id"],
            )
            self.assertNotIn("orders", home["backtest"])
            self.assertNotIn("fills", home["backtest"])
            self.assertNotIn("analytics", home["backtest"])

    def test_durable_queue_resolves_actual_owners_and_finalizes_restart_readable_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-backtest-") as directory:
            root = Path(directory)
            project, imported, strategy = _published_strategy(root)
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=0.75
                ),
            )
            service = ProductResearchBacktestService(product)
            submission = ProductResearchBacktestSubmission(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                research_strategy_spec_id=strategy["research_strategy_spec_id"],
                session_start=FIRST_SESSION,
                session_end=FIRST_SESSION + timedelta(days=69),
                slippage_bps="10",
                daily_volume_participation_rate="0.1",
                idempotency_key="run-product-research-backtest-1",
            )

            connection = product._connection(read_only=True)
            try:
                task_count_before = int(
                    connection.execute("SELECT COUNT(*) FROM task").fetchone()[0]
                )
            finally:
                connection.close()
            preflight = service.preview(submission)
            self.assertEqual(preflight["status"], "PASS")
            self.assertEqual(preflight["side_effects"], "NONE")
            self.assertEqual(preflight["snapshot_id"], imported["snapshot_id"])
            self.assertEqual(
                preflight["universe_version_id"], imported["universe_version_id"]
            )
            self.assertEqual(preflight["commission_rate"], "0.0003")
            self.assertEqual(
                preflight["resource_estimate"]["memory_limit_bytes"],
                1024 * 1024 * 1024,
            )
            connection = product._connection(read_only=True)
            try:
                self.assertEqual(
                    int(connection.execute("SELECT COUNT(*) FROM task").fetchone()[0]),
                    task_count_before,
                )
            finally:
                connection.close()

            started = time.monotonic()
            accepted = service.submit(submission)
            elapsed = time.monotonic() - started
            try:
                self.assertLess(elapsed, 2.0)
                self.assertEqual(accepted["accepted_state"], "QUEUED")
                self.assertEqual(accepted["maturity"], "PRODUCT_CONNECTED")
                self.assertEqual(accepted["truth"], "NOT_FORMAL")
                self.assertEqual(accepted["admission"], "PRE_ALPHA")
                self.assertEqual(accepted["checkpoint_resume"], "UNAVAILABLE")
                self.assertTrue(
                    accepted["research_backtest_request_id"].startswith(
                        "rbrq_sha256_"
                    )
                )
                task = product.task_persistence.read_task(accepted["task_id"])
                self.assertEqual(task.state.value, "QUEUED")
                self.assertEqual(
                    product.references(
                        project["project_id"], "PRODUCT_RESEARCH_BACKTEST_READ_MODEL"
                    ),
                    [],
                    "Task acceptance must precede Snapshot/Strategy resolution and engine work",
                )

                deadline = time.monotonic() + 20.0
                while time.monotonic() < deadline:
                    task = product.task_persistence.read_task(accepted["task_id"])
                    if task.state in TASK_TERMINAL_STATES:
                        break
                    time.sleep(0.05)
                connection = product._connection(read_only=True)
                try:
                    terminal_events = [
                        json.loads(str(row[0]))
                        for row in connection.execute(
                            "SELECT payload_json FROM task_event WHERE task_id=? "
                            "ORDER BY project_sequence",
                            (accepted["task_id"],),
                        ).fetchall()
                    ]
                finally:
                    connection.close()
                self.assertEqual(task.state.value, "SUCCEEDED", terminal_events)

                read_model = service.get_backtest(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                    research_backtest_request_id=accepted[
                        "research_backtest_request_id"
                    ],
                )
                self.assertEqual(read_model["truth"], "NOT_FORMAL")
                self.assertEqual(read_model["admission"], "PRE_ALPHA")
                self.assertEqual(read_model["result_state"], "VALID")
                self.assertEqual(
                    read_model["engine_version"],
                    "v3.a_share_daily_eod_engine/0.3.0-research",
                )
                self.assertTrue(read_model["run_spec_id"].startswith("btrs_sha256_"))
                self.assertTrue(read_model["result_id"].startswith("res_"))
                self.assertTrue(read_model["analytics_id"].startswith("bra_sha256_"))
                self.assertTrue(
                    read_model["analytics_artifact_id"].startswith("art_sha256_")
                )
                self.assertTrue(
                    read_model["lineage_artifact_id"].startswith("art_sha256_")
                )
                summary_export = json.loads(
                    product.read_verified_bytes(
                        read_model["summary_export_artifact_id"]
                    ).decode("utf-8")
                )
                self.assertEqual(
                    summary_export["source_backtest_result_id"],
                    read_model["backtest_result_id"],
                )
                self.assertEqual(
                    summary_export["source_analytics_id"],
                    read_model["analytics_id"],
                )
                orders_export = list(
                    csv.DictReader(
                        io.StringIO(
                            product.read_verified_bytes(
                                read_model["orders_export_artifact_id"]
                            ).decode("utf-8")
                        )
                    )
                )
                fills_export = list(
                    csv.DictReader(
                        io.StringIO(
                            product.read_verified_bytes(
                                read_model["fills_export_artifact_id"]
                            ).decode("utf-8")
                        )
                    )
                )
                self.assertEqual(len(orders_export), read_model["order_count"])
                self.assertEqual(len(fills_export), read_model["fill_count"])
                self.assertTrue(
                    all(
                        row["source_backtest_result_id"]
                        == read_model["backtest_result_id"]
                        for row in (*orders_export, *fills_export)
                    )
                )
                run_spec = json.loads(
                    product.read_verified_bytes(
                        read_model["run_spec_artifact_id"]
                    ).decode("utf-8")
                )
                exact_refs = run_spec["exact_references"]
                exact_kinds = {str(item["reference_kind"]) for item in exact_refs}
                self.assertTrue(
                    {
                        "FACTOR_DEFINITION_ENTRY",
                        "FACTOR_MATERIALIZATION_ENTRY",
                        "FACTOR_DEFINITION_EXIT",
                        "FACTOR_MATERIALIZATION_EXIT",
                        "RESEARCH_STRATEGY_SPEC",
                        "STRATEGY_DEFINITION",
                        "STRATEGY_STATE",
                        "RISK_POLICY_SET",
                        "RESOURCE_ADMISSION",
                    }.issubset(exact_kinds)
                )
                for prefix in (
                    "SIGNAL:",
                    "PORTFOLIO_INTENT:",
                    "TARGET_WEIGHT:",
                    "RISK_APPLICATION:",
                    "RISK_ADJUSTED_WEIGHT:",
                ):
                    self.assertEqual(
                        len([kind for kind in exact_kinds if kind.startswith(prefix)]),
                        strategy["decision_chain_count"],
                    )
                resource_ref = next(
                    item
                    for item in exact_refs
                    if item["reference_kind"] == "RESOURCE_ADMISSION"
                )
                self.assertEqual(
                    resource_ref["source_id"],
                    "radm_sha256_" + resource_ref["content_sha256"],
                )
                self.assertGreater(read_model["fill_count"], 0)
                self.assertEqual(
                    read_model["first_fill_session_date"],
                    read_model["first_effective_session_date"],
                    "t-close signal must execute at the next admitted open, not t+2",
                )

                connection = product._connection(read_only=True)
                try:
                    intent = connection.execute(
                        "SELECT state FROM publication_intent WHERE task_id=?",
                        (accepted["task_id"],),
                    ).fetchone()
                    result = connection.execute(
                        "SELECT state FROM result WHERE result_id=?",
                        (read_model["result_id"],),
                    ).fetchone()
                    outputs = connection.execute(
                        "SELECT output_role,ordinal FROM task_output WHERE task_id=? "
                        "ORDER BY output_role,ordinal",
                        (accepted["task_id"],),
                    ).fetchall()
                finally:
                    connection.close()
                self.assertEqual(intent[0], "FINALIZED")
                self.assertEqual(result[0], "VALID")
                self.assertIn(
                    ("PRODUCT_RESULT_ANALYTICS", 0),
                    [(str(row[0]), int(row[1])) for row in outputs],
                )
                analytics = json.loads(
                    product.read_verified_bytes(
                        read_model["analytics_artifact_id"]
                    ).decode("utf-8")
                )
                self.assertEqual(
                    analytics["schema_version"],
                    "v3.backtest_result_analytics/1.1.0",
                )
                self.assertEqual(
                    analytics["core_analytics"]["source_result"]["result_id"],
                    read_model["backtest_result_id"],
                )
                self.assertEqual(
                    analytics["core_analytics"]["benchmark"]["status"],
                    "BENCHMARK_NOT_AVAILABLE",
                )
                self.assertIn("calmar", analytics["supplemental_metrics"])
                self.assertGreater(len(analytics["exposure_series"]), 0)
                lineage = json.loads(
                    product.read_verified_bytes(
                        read_model["lineage_artifact_id"]
                    ).decode("utf-8")
                )
                self.assertEqual(
                    lineage["schema_version"], "v3.product-result-lineage/1.0.0"
                )
                self.assertEqual(lineage["project_id"], project["project_id"])
                self.assertEqual(
                    lineage["result"]["result_id"], read_model["result_id"]
                )
                self.assertEqual(
                    lineage["result"]["backtest_result_id"],
                    read_model["backtest_result_id"],
                )
                self.assertEqual(
                    lineage["data"]["raw_capture_id"], imported["raw_capture_id"]
                )
                self.assertEqual(
                    lineage["data"]["snapshot_id"], imported["snapshot_id"]
                )
                self.assertEqual(
                    lineage["factors"]["entry"]["factor_definition_version_id"],
                    strategy["entry_signal_ref"]["factor_definition_version_id"],
                )
                self.assertEqual(
                    lineage["factors"]["exit"]["factor_definition_version_id"],
                    strategy["exit_signal_ref"]["factor_definition_version_id"],
                )
                self.assertGreater(len(lineage["strategy"]["decision_chains"]), 0)
                first_chain = lineage["strategy"]["decision_chains"][0]
                for key, prefix in (
                    ("signal_artifact_id", "sig_sha256_"),
                    ("target_weight_vector_id", "twv_sha256_"),
                    ("risk_application_receipt_id", "rar_sha256_"),
                ):
                    self.assertTrue(first_chain[key].startswith(prefix))
                self.assertEqual(
                    lineage["strategy"]["risk_policy_set_version_id"],
                    strategy["profile_refs"]["risk_policy_set_version_id"],
                )
                self.assertGreater(len(lineage["execution"]["orders"]), 0)
                self.assertGreater(len(lineage["execution"]["fills"]), 0)
                self.assertEqual(
                    lineage["result"]["analytics_id"], read_model["analytics_id"]
                )

                restarted = ProductResearchBacktestService(ProductRuntime(root)).get_backtest(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                    research_backtest_request_id=accepted[
                        "research_backtest_request_id"
                    ],
                )
                self.assertEqual(restarted, read_model)

                tampered_lineage = json.loads(json.dumps(lineage))
                tampered_lineage["result"]["backtest_result_id"] = (
                    "btrr_sha256_" + "0" * 64
                )
                lineage_payload = {
                    key: value
                    for key, value in tampered_lineage.items()
                    if key
                    not in {"artifact_type", "result_lineage_id", "content_sha256"}
                }
                lineage_digest = canonical_sha256(lineage_payload)
                tampered_lineage["content_sha256"] = lineage_digest
                tampered_lineage["result_lineage_id"] = (
                    "rln_sha256_" + lineage_digest
                )
                tampered_read_model = json.loads(json.dumps(read_model))
                tampered_read_model["result_lineage_id"] = tampered_lineage[
                    "result_lineage_id"
                ]
                publications = product.execution._publish_artifact_batch(
                    payloads=((
                        "prv_test_semantic_lineage_" + lineage_digest,
                        canonical_json_bytes(tampered_lineage),
                        LINEAGE_ROLE,
                        "v3.product-result-lineage/1.0.0",
                    ),),
                    references=((read_model["result_id"], LINEAGE_ROLE, 0),),
                )
                tampered_read_model["lineage_artifact_id"] = publications[
                    0
                ].descriptor.artifact_id
                # Publish the final read model only after its exact lineage Artifact ID
                # exists; both objects are content-addressed and project-reachable.
                product.execution._publish_artifact_batch(
                    payloads=((
                        "prv_test_semantic_backtest_read_model_bound_"
                        + accepted["research_backtest_request_id"],
                        canonical_json_bytes(tampered_read_model),
                        READ_MODEL_ROLE,
                        "v3.product-research-backtest-read-model/1.0.0",
                    ),),
                    references=((project["project_id"], READ_MODEL_ROLE, 0),),
                )
                with self.assertRaisesRegex(
                    TruthPreconditionFailedError,
                    "lineage binding drifted",
                ):
                    ProductResearchBacktestService(ProductRuntime(root)).get_backtest(
                        project_id=project["project_id"],
                        project_context_revision_id=imported[
                            "project_context_revision_id"
                        ],
                        research_backtest_request_id=accepted[
                            "research_backtest_request_id"
                        ],
                    )
            finally:
                product.research_workers.shutdown_all()

    def test_restart_recovers_cataloged_publication_across_reconciliation_boundaries(self) -> None:
        for fault_point, recovery_outcome in (
            ("BEFORE_INTENT_COMMIT", "WORKER_LOST"),
            ("AFTER_INTENT_STAGED", "FAILED"),
            ("AFTER_INITIAL_ARTIFACTS_PUBLISHED", "FAILED"),
            ("AFTER_CATALOG_COMMITTED", "FINALIZED"),
            ("AFTER_RECONCILIATION_PUBLISHED", "FINALIZED"),
            ("DURING_FINALIZE_TRANSACTION", "FINALIZED"),
        ):
            with self.subTest(fault_point=fault_point), tempfile.TemporaryDirectory(
                prefix="v3-v1-1-publication-recovery-"
            ) as directory:
                root = Path(directory)
                project, imported, published_strategy = _published_strategy(root)
                product = ProductRuntime(root, reconcile_on_start=False)
                service = ProductResearchBacktestService(product)
                submission = ProductResearchBacktestSubmission(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                    research_strategy_spec_id=published_strategy[
                        "research_strategy_spec_id"
                    ],
                    session_start=FIRST_SESSION,
                    session_end=FIRST_SESSION + timedelta(days=69),
                    slippage_bps="10",
                    daily_volume_participation_rate="0.1",
                    idempotency_key="publication-recovery-" + fault_point.lower(),
                )
                request = service._prepare_submission(submission)
                handles = service._accept_request(request)
                product.execution._transition_to_running(
                    handles.task, handles.run, handles.attempt
                )
                if recovery_outcome == "WORKER_LOST":
                    worker_id = mint_v3_id("wrk_")
                    lease_id = mint_v3_id("lea_")
                    now = wire_time(datetime.now(timezone.utc))
                    connection = product._connection()
                    try:
                        connection.execute(
                            "INSERT INTO worker(worker_id,worker_kind,process_id,"
                            "environment_profile_id,state,started_at) "
                            "VALUES(?, 'RESEARCH_BACKTEST', 999999, "
                            "'v3.test-crashed-worker/1.0.0', 'BUSY', ?)",
                            (worker_id, now),
                        )
                        connection.execute(
                            "INSERT INTO worker_lease(lease_id,attempt_id,worker_id,"
                            "cpu_slots,memory_limit_bytes,scratch_limit_bytes,state,"
                            "granted_at,expires_at) VALUES(?,?,?,1,1048576,1048576,"
                            "'GRANTED',?,?)",
                            (
                                lease_id,
                                handles.attempt.attempt_id,
                                worker_id,
                                now,
                                now,
                            ),
                        )
                        connection.commit()
                    finally:
                        connection.close()
                strategy_service = ProductStrategyService(product)
                strategy = strategy_service.get_strategy(
                    project_id=request.project_id,
                    project_context_revision_id=request.project_context_revision_id,
                    research_strategy_spec_id=request.research_strategy_spec_id,
                )
                panel = ManifestAwareLocalSnapshotReader(product).resolve(
                    project_id=request.project_id,
                    snapshot_id=str(strategy["snapshot_id"]),
                    universe_version_id=str(strategy["universe_version_id"]),
                )
                spec, execution_inputs, first_effective = service._build_run_spec(
                    request=request,
                    strategy_service=strategy_service,
                    strategy=strategy,
                    strategy_spec=service._strategy_spec(strategy),
                    panel=panel,
                    resource_admission=_test_resource_admission(),
                )
                result = DeterministicAshareBacktestEngine().run(
                    spec, research_execution=execution_inputs
                )

                def crash(point: str) -> None:
                    if point == fault_point:
                        raise SystemExit("simulated publication process crash")

                with self.assertRaises(SystemExit):
                    ProductBacktestPublication(
                        product, fault_injector=crash
                    ).finalize(
                        project_id=request.project_id,
                        handles=handles,
                        request_id=request.research_backtest_request_id,
                        strategy=strategy,
                        spec=spec,
                        execution_inputs=execution_inputs,
                        result=result,
                        assumption_receipt=_assumption_receipt(
                            request, panel, execution_inputs
                        ),
                        first_effective_session_date=first_effective,
                    )

                before = product._connection(read_only=True)
                try:
                    intent_before = before.execute(
                        "SELECT publication_intent_id,state FROM publication_intent "
                        "WHERE task_id=?",
                        (handles.task.task_id,),
                    ).fetchone()
                    result_before = before.execute(
                        "SELECT result_id,state FROM result WHERE backtest_run_id=?",
                        (handles.run.run_id,),
                    ).fetchone()
                    task_before = before.execute(
                        "SELECT state FROM task WHERE task_id=?",
                        (handles.task.task_id,),
                    ).fetchone()
                finally:
                    before.close()
                if recovery_outcome == "WORKER_LOST":
                    self.assertIsNone(intent_before)
                else:
                    self.assertEqual(
                        intent_before[1],
                        "CATALOG_COMMITTED"
                        if recovery_outcome == "FINALIZED"
                        else "STAGED",
                    )
                if recovery_outcome == "FINALIZED":
                    self.assertEqual(result_before[1], "PENDING_RECONCILIATION")
                else:
                    self.assertIsNone(result_before)
                self.assertNotEqual(task_before[0], "SUCCEEDED")

                restarted = ProductRuntime(root)
                after = restarted._connection(read_only=True)
                try:
                    intent_after = (
                        after.execute(
                            "SELECT state FROM publication_intent "
                            "WHERE publication_intent_id=?",
                            (intent_before[0],),
                        ).fetchone()
                        if intent_before is not None
                        else None
                    )
                    result_after = (
                        after.execute(
                            "SELECT state FROM result WHERE result_id=?",
                            (result_before[0],),
                        ).fetchone()
                        if result_before is not None
                        else None
                    )
                    task_after = after.execute(
                        "SELECT state FROM task WHERE task_id=?",
                        (handles.task.task_id,),
                    ).fetchone()
                    outputs = after.execute(
                        "SELECT output_role,ordinal FROM task_output WHERE task_id=? "
                        "ORDER BY output_role,ordinal",
                        (handles.task.task_id,),
                    ).fetchall()
                finally:
                    after.close()
                if recovery_outcome == "FINALIZED":
                    self.assertEqual(intent_after[0], "FINALIZED")
                    self.assertEqual(result_after[0], "VALID")
                    self.assertEqual(task_after[0], "SUCCEEDED")
                    output_roles = [
                        (str(row[0]), int(row[1])) for row in outputs
                    ]
                    self.assertEqual(len(output_roles), 12)
                    for required_role in (
                        "PRODUCT_RESULT_ANALYTICS",
                        "PRODUCT_RESULT_LINEAGE",
                        SUMMARY_EXPORT_ROLE,
                        ORDERS_EXPORT_ROLE,
                        FILLS_EXPORT_ROLE,
                    ):
                        self.assertIn((required_role, 0), output_roles)
                    recovered = restarted.backtest.get_backtest(
                        project_id=request.project_id,
                        project_context_revision_id=request.project_context_revision_id,
                        research_backtest_request_id=request.research_backtest_request_id,
                    )
                    self.assertEqual(recovered["result_state"], "VALID")
                    self.assertEqual(
                        recovered["publication_intent_id"], intent_before[0]
                    )
                    self.assertEqual(
                        ProductRuntime(root).backtest.get_backtest(
                            project_id=request.project_id,
                            project_context_revision_id=request.project_context_revision_id,
                            research_backtest_request_id=request.research_backtest_request_id,
                        ),
                        recovered,
                        "restart recovery must be idempotent",
                    )
                elif recovery_outcome == "FAILED":
                    self.assertEqual(intent_after[0], "FAILED")
                    self.assertIsNone(result_after)
                    self.assertEqual(task_after[0], "FAILED")
                    self.assertEqual(outputs, [])
                    restarted_again = ProductRuntime(root)
                    stable = restarted_again._connection(read_only=True)
                    try:
                        self.assertEqual(
                            stable.execute(
                                "SELECT state FROM publication_intent "
                                "WHERE publication_intent_id=?",
                                (intent_before[0],),
                            ).fetchone()[0],
                            "FAILED",
                        )
                    finally:
                        stable.close()
                else:
                    self.assertIsNone(intent_after)
                    self.assertIsNone(result_after)
                    self.assertEqual(task_after[0], "FAILED")
                    self.assertEqual(outputs, [])
                    self.assertGreaterEqual(
                        restarted.reconciliation_summary["tasks_failed"], 1
                    )

    def test_corrupt_reconciliation_never_exposes_a_valid_result(self) -> None:
        for corruption in (
            "LEDGER_SEQUENCE",
            "CASH_BALANCE",
            "FILL_LINK",
            "POSITION_BALANCE",
            "NAV",
        ):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory(
                prefix="v3-v1-1-reconciliation-corruption-"
            ) as directory:
                root = Path(directory)
                project, imported, published_strategy = _published_strategy(root)
                product = ProductRuntime(root, reconcile_on_start=False)
                service = ProductResearchBacktestService(product)
                request = service._prepare_submission(
                    ProductResearchBacktestSubmission(
                        project_id=project["project_id"],
                        project_context_revision_id=imported[
                            "project_context_revision_id"
                        ],
                        research_strategy_spec_id=published_strategy[
                            "research_strategy_spec_id"
                        ],
                        session_start=FIRST_SESSION,
                        session_end=FIRST_SESSION + timedelta(days=69),
                        slippage_bps="10",
                        daily_volume_participation_rate="0.1",
                        idempotency_key="corrupt-" + corruption.lower(),
                    )
                )
                handles = service._accept_request(request)
                product.execution._transition_to_running(
                    handles.task, handles.run, handles.attempt
                )
                strategy_service = ProductStrategyService(product)
                strategy = strategy_service.get_strategy(
                    project_id=request.project_id,
                    project_context_revision_id=request.project_context_revision_id,
                    research_strategy_spec_id=request.research_strategy_spec_id,
                )
                panel = ManifestAwareLocalSnapshotReader(product).resolve(
                    project_id=request.project_id,
                    snapshot_id=str(strategy["snapshot_id"]),
                    universe_version_id=str(strategy["universe_version_id"]),
                )
                spec, execution_inputs, first_effective = service._build_run_spec(
                    request=request,
                    strategy_service=strategy_service,
                    strategy=strategy,
                    strategy_spec=service._strategy_spec(strategy),
                    panel=panel,
                    resource_admission=_test_resource_admission(),
                )
                original = DeterministicAshareBacktestEngine().run(
                    spec, research_execution=execution_inputs
                )
                cash_ledger = original.cash_ledger
                position_ledger = original.position_ledger
                fills = original.fills
                nav = original.nav
                if corruption == "LEDGER_SEQUENCE":
                    cash_ledger = (
                        replace(cash_ledger[0], sequence=2),
                        *cash_ledger[1:],
                    )
                elif corruption == "CASH_BALANCE":
                    cash_ledger = (
                        replace(
                            cash_ledger[0],
                            balance_after=str(
                                Decimal(cash_ledger[0].balance_after) + Decimal("1")
                            ),
                        ),
                        *cash_ledger[1:],
                    )
                elif corruption == "FILL_LINK":
                    fills = (
                        replace(fills[0], order_id="ord_sha256_" + "0" * 64),
                        *fills[1:],
                    )
                elif corruption == "POSITION_BALANCE":
                    position_ledger = (
                        replace(
                            position_ledger[0],
                            quantity_after=position_ledger[0].quantity_after + 1,
                        ),
                        *position_ledger[1:],
                    )
                else:
                    nav = (
                        *nav[:-1],
                        replace(nav[-1], nav=str(Decimal(nav[-1].nav) + Decimal("1"))),
                    )
                corrupted = BacktestRunResult.create(
                    spec,
                    original.target_quantity_vectors,
                    original.orders,
                    fills,
                    original.diagnostics,
                    cash_ledger,
                    position_ledger,
                    original.holdings,
                    nav,
                )
                with self.assertRaises(TruthPreconditionFailedError):
                    ProductBacktestPublication(product).finalize(
                        project_id=request.project_id,
                        handles=handles,
                        request_id=request.research_backtest_request_id,
                        strategy=strategy,
                        spec=spec,
                        execution_inputs=execution_inputs,
                        result=corrupted,
                        assumption_receipt=_assumption_receipt(
                            request, panel, execution_inputs
                        ),
                        first_effective_session_date=first_effective,
                    )

                restarted = ProductRuntime(root)
                connection = restarted._connection(read_only=True)
                try:
                    result_row = connection.execute(
                        "SELECT result_id,state,invalid_reason_code,"
                        "reconciliation_artifact_id FROM result "
                        "WHERE backtest_run_id=?",
                        (handles.run.run_id,),
                    ).fetchone()
                    intent_row = connection.execute(
                        "SELECT state,last_error_code FROM publication_intent "
                        "WHERE task_id=?",
                        (handles.task.task_id,),
                    ).fetchone()
                    task_row = connection.execute(
                        "SELECT state FROM task WHERE task_id=?",
                        (handles.task.task_id,),
                    ).fetchone()
                finally:
                    connection.close()
                self.assertEqual(result_row[1], "INVALID")
                self.assertEqual(result_row[2], "RESIDUAL_VALIDATION_FAILED")
                self.assertIsNotNone(
                    result_row[3],
                    "invalid Result must retain a failure reconciliation Artifact",
                )
                self.assertEqual(intent_row[0], "FAILED")
                self.assertEqual(intent_row[1], "RESIDUAL_VALIDATION_FAILED")
                self.assertEqual(task_row[0], "FAILED")
                self.assertEqual(
                    restarted.references(
                        project["project_id"],
                        "PRODUCT_RESEARCH_BACKTEST_READ_MODEL",
                    ),
                    [],
                    "corrupt Result must not become a valid product read model",
                )
                descriptor = restarted.require_published_artifact(result_row[3])
                self.assertEqual(
                    descriptor["semantic_role"],
                    "PRODUCT_RESEARCH_RESULT_RECONCILIATION",
                )
                failure_receipt = json.loads(
                    restarted.read_verified_bytes(result_row[3]).decode("utf-8")
                )
                self.assertEqual(failure_receipt["decision"], "FAIL")
                self.assertEqual(
                    failure_receipt["reason_code"],
                    "RESIDUAL_VALIDATION_FAILED",
                )
                self.assertEqual(
                    failure_receipt["checks"]["RECOVERY_RECONCILIATION"],
                    "FAIL",
                )

    def test_plan_14_5_result_service_reuses_the_product_publication_owner(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="v3-v1-1-result-service-binding-"
        ) as directory:
            root = Path(directory)
            project, imported, strategy = _published_strategy(root)
            product = ProductRuntime(
                root,
                research_worker_config=ProductResearchWorkerConfig(),
            )
            service = ProductResearchBacktestService(product)
            accepted = service.submit(
                ProductResearchBacktestSubmission(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                    research_strategy_spec_id=strategy["research_strategy_spec_id"],
                    session_start=FIRST_SESSION,
                    session_end=FIRST_SESSION + timedelta(days=69),
                    slippage_bps="10",
                    daily_volume_participation_rate="0.1",
                    idempotency_key="result-service-source-publication",
                )
            )
            try:
                source_task = _wait_for_terminal(product, accepted["task_id"])
                self.assertEqual(source_task.state.value, "SUCCEEDED")
                published = product.backtest.get_latest_backtest(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                )
                analytics = json.loads(
                    product.read_verified_bytes(
                        published["analytics_artifact_id"]
                    ).decode("utf-8")
                )
                analytics_policy = analytics["core_analytics"]["analytics_policy"]
                source_result_row = product.require_result(published["result_id"])
                source_reconciliation_artifact_id = str(
                    source_result_row["reconciliation_artifact_id"]
                )

                connection = product._connection(read_only=True)
                try:
                    before = {
                        "results": connection.execute(
                            "SELECT COUNT(*) FROM result WHERE project_id=?",
                            (project["project_id"],),
                        ).fetchone()[0],
                        "intents": connection.execute(
                            "SELECT COUNT(*) FROM publication_intent WHERE project_id=?",
                            (project["project_id"],),
                        ).fetchone()[0],
                    }
                finally:
                    connection.close()

                facade = ResultFacade(product)
                handlers = facade.handlers()
                self.assertEqual(
                    set(handlers),
                    {
                        "ResultService.v1.reconcileLedger",
                        "ResultService.v1.finalizeResult",
                        "ResultService.v1.getResult",
                        "ResultService.v1.compareResults",
                    },
                )

                for index, section in enumerate(
                    (
                        "summary",
                        "analytics",
                        "orders",
                        "fills",
                        "positions",
                        "diagnostics",
                        "lineage",
                    ),
                    start=1,
                ):
                    response = handlers["ResultService.v1.getResult"](
                        {
                            "request_id": (
                                f"01890f3c-7b5a-7000-8000-{index:012d}"
                            ),
                            "project_id": project["project_id"],
                            "project_context_revision_id": imported[
                                "project_context_revision_id"
                            ],
                            "result_id": published["result_id"],
                            "section": section,
                            "page": {},
                        }
                    )
                    get_operation("ResultService.v1.getResult").validate_response(
                        response
                    )
                    read_model = response["read_model"]
                    self.assertEqual(read_model["truth"], "NOT_FORMAL")
                    self.assertEqual(read_model["admission"], "PRE_ALPHA")
                    self.assertEqual(read_model["result_state"], "VALID")
                    self.assertEqual(read_model["section"], section)
                    if section in {"orders", "fills", "positions", "diagnostics"}:
                        self.assertEqual(
                            read_model["stream_ref"]["artifact_id"],
                            published["result_artifact_id"],
                        )
                        self.assertEqual(
                            read_model["page"],
                            {
                                "delivery_mode": "FULL_ARTIFACT_STREAM",
                                "row_pagination_applied": False,
                                "requested_limit": None,
                                "cursor": None,
                                "next_cursor": None,
                            },
                        )
                        self.assertNotIn("rows", read_model)

                with self.assertRaises(CapabilityUnavailableError) as cursor_error:
                    handlers["ResultService.v1.getResult"](
                        {
                            "request_id": (
                                "01890f3c-7b5a-7000-8000-000000000099"
                            ),
                            "project_id": project["project_id"],
                            "project_context_revision_id": imported[
                                "project_context_revision_id"
                            ],
                            "result_id": published["result_id"],
                            "section": "orders",
                            "page": {"cursor": "not-implemented", "limit": 25},
                        }
                    )
                self.assertEqual(
                    cursor_error.exception.details["reason_code"],
                    "RESULT_ROW_CURSOR_NOT_AVAILABLE",
                )

                reconcile_request = {
                        "request_id": "01890f3c-7b5a-7000-8000-000000000101",
                        "project_id": project["project_id"],
                        "project_context_revision_id": imported[
                            "project_context_revision_id"
                        ],
                        "backtest_run_id": published["run_id"],
                        "ledger_manifest_artifact_id": published[
                            "ledger_manifest_artifact_id"
                        ],
                        "reconciliation_profile_id": (
                            "v3.product-result-reconciliation/1.0.0"
                        ),
                        "idempotency_key": "verify-existing-reconciliation",
                    }
                reconcile = handlers["ResultService.v1.reconcileLedger"](
                    reconcile_request
                )
                get_operation(
                    "ResultService.v1.reconcileLedger"
                ).validate_response(reconcile)
                finalize_request = {
                        "request_id": "01890f3c-7b5a-7000-8000-000000000102",
                        "project_id": project["project_id"],
                        "project_context_revision_id": imported[
                            "project_context_revision_id"
                        ],
                        "backtest_run_id": published["run_id"],
                        "reconciliation_artifact_id": (
                            source_reconciliation_artifact_id
                        ),
                        "analytics_spec": {
                            "analytics_policy_id": analytics_policy["policy_id"],
                            "analytics_policy_content_sha256": analytics_policy[
                                "content_sha256"
                            ],
                        },
                        "idempotency_key": "verify-existing-finalization",
                    }
                finalize = handlers["ResultService.v1.finalizeResult"](
                    finalize_request
                )
                get_operation("ResultService.v1.finalizeResult").validate_response(
                    finalize
                )
                self.assertEqual(reconcile["accepted_state"], "QUEUED")
                self.assertEqual(finalize["accepted_state"], "QUEUED")
                self.assertEqual(
                    _wait_for_terminal(product, reconcile["task_id"]).state.value,
                    "SUCCEEDED",
                )
                self.assertEqual(
                    _wait_for_terminal(product, finalize["task_id"]).state.value,
                    "SUCCEEDED",
                )
                reconcile_replay = handlers[
                    "ResultService.v1.reconcileLedger"
                ](reconcile_request)
                finalize_replay = handlers[
                    "ResultService.v1.finalizeResult"
                ](finalize_request)
                self.assertEqual(
                    (reconcile_replay["task_id"], reconcile_replay["run_id"]),
                    (reconcile["task_id"], reconcile["run_id"]),
                )
                self.assertEqual(
                    (finalize_replay["task_id"], finalize_replay["run_id"]),
                    (finalize["task_id"], finalize["run_id"]),
                )
                connection = product._connection(read_only=True)
                try:
                    verification_tasks_before_negative = connection.execute(
                        "SELECT COUNT(*) FROM task WHERE operation_id IN (?,?)",
                        (
                            "ResultService.v1.reconcileLedger",
                            "ResultService.v1.finalizeResult",
                        ),
                    ).fetchone()[0]
                finally:
                    connection.close()
                conflicting_reconcile = dict(reconcile_request)
                conflicting_reconcile["ledger_manifest_artifact_id"] = published[
                    "result_artifact_id"
                ]
                with self.assertRaises(IdempotencyConflictError):
                    handlers["ResultService.v1.reconcileLedger"](
                        conflicting_reconcile
                    )
                wrong_owner_reconcile = dict(conflicting_reconcile)
                wrong_owner_reconcile["idempotency_key"] = (
                    "wrong-ledger-owner-must-not-create-task"
                )
                with self.assertRaises(TruthPreconditionFailedError):
                    handlers["ResultService.v1.reconcileLedger"](
                        wrong_owner_reconcile
                    )
                connection = product._connection(read_only=True)
                try:
                    verification_tasks_after_negative = connection.execute(
                        "SELECT COUNT(*) FROM task WHERE operation_id IN (?,?)",
                        (
                            "ResultService.v1.reconcileLedger",
                            "ResultService.v1.finalizeResult",
                        ),
                    ).fetchone()[0]
                finally:
                    connection.close()
                self.assertEqual(
                    verification_tasks_after_negative,
                    verification_tasks_before_negative,
                    "rejected Result requests cannot create a Task",
                )

                connection = product._connection(read_only=True)
                try:
                    after = {
                        "results": connection.execute(
                            "SELECT COUNT(*) FROM result WHERE project_id=?",
                            (project["project_id"],),
                        ).fetchone()[0],
                        "intents": connection.execute(
                            "SELECT COUNT(*) FROM publication_intent WHERE project_id=?",
                            (project["project_id"],),
                        ).fetchone()[0],
                    }
                    command_outputs = connection.execute(
                        "SELECT task_id,output_role,artifact_id FROM task_output "
                        "WHERE task_id IN (?,?) ORDER BY task_id,output_role",
                        (reconcile["task_id"], finalize["task_id"]),
                    ).fetchall()
                finally:
                    connection.close()
                self.assertEqual(after, before, "Result commands cannot mint a second Result")
                self.assertEqual(
                    {
                        (str(row[0]), str(row[1]), str(row[2]))
                        for row in command_outputs
                    },
                    {
                        (
                            reconcile["task_id"],
                            "PRODUCT_RESEARCH_RESULT_RECONCILIATION",
                            source_reconciliation_artifact_id,
                        ),
                        (
                            finalize["task_id"],
                            "PRODUCT_RESULT_ANALYTICS",
                            published["analytics_artifact_id"],
                        ),
                    },
                )
                with self.assertRaises(CapabilityUnavailableError) as comparison:
                    handlers["ResultService.v1.compareResults"](
                        {
                            "request_id": "01890f3c-7b5a-7000-8000-000000000103",
                            "project_id": project["project_id"],
                            "project_context_revision_id": imported[
                                "project_context_revision_id"
                            ],
                            "result_ids": [published["result_id"], published["result_id"]],
                            "comparison_spec": {},
                        }
                    )
                self.assertEqual(
                    comparison.exception.details["reason_code"],
                    "RESULT_COMPARISON_NOT_AVAILABLE",
                )
            finally:
                product.research_workers.shutdown_all()


if __name__ == "__main__":
    unittest.main()
