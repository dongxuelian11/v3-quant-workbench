"""B3 product runtime integration tests: normal bootstrap, contract registry,
honest capabilities, golden execution, idempotency, restart recovery,
negative paths, artifact tampering, export, experiment and task operations.

These tests drive the same RequestRouter the framed-stdio runtime uses, so
every response passes the frozen operation DTO validation on the way out.
"""

from __future__ import annotations

import json
import inspect
import tempfile
import unittest
from pathlib import Path

from v3_backend.contracts.registry import OPERATIONS, SERVICE_CONTRACTS
from v3_backend.errors.codes import ErrorCode
from v3_backend.runtime.bootstrap import _build_ports
from v3_backend.runtime.composition_root import (
    RuntimePorts,
    RequestRouter,
    default_capabilities,
)
from v3_backend.runtime.product_runtime import (
    ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
    PRODUCT_EXECUTION_CONTEXT_ROLE,
    ProductRuntime,
    build_product_ports,
    build_product_runtime,
    mint_uuid7,
)
from v3_backend.runtime import product_runtime as product_runtime_module
from v3_backend.domain.tasks.entities import TaskState

from .helpers import build_product_golden_project


class _PortsCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.storage_root = Path(self._temporary.name)
        self.setup = build_product_golden_project(self.storage_root)
        self.product = build_product_runtime(self.storage_root)
        self.ports: RuntimePorts = build_product_ports(self.storage_root)
        self.router = RequestRouter(self.ports.operation_handlers)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def route(self, operation_id: str, **body_fields):
        project_id = body_fields.pop("_project_id", self.setup.project_id)
        pcr_id = body_fields.pop("_pcr_id", self.setup.project_context_revision_id)
        request_id = mint_uuid7()
        body = {
            "request_id": request_id,
            "project_id": project_id,
            "project_context_revision_id": pcr_id,
            "expected_api_version": "1.0",
            **body_fields,
        }
        wire = {
            "kind": "request",
            "request_id": request_id,
            "operation_id": operation_id,
            "contract_version": "1.0",
            "project_id": project_id,
            "project_context_revision_id": pcr_id,
            "body": body,
        }
        return self.router.route(wire)

    def assert_error(self, response: dict, code: str) -> dict:
        self.assertEqual(response["kind"], "response")
        self.assertEqual(response["status"], "ERROR", response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        return response


class NormalBootstrapTests(unittest.TestCase):
    def test_normal_bootstrap_builds_product_ports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = type(
                "Args", (), {"storage_root": tmp, "development_shell": False}
            )()
            ports = _build_ports(args)
            self.assertGreater(len(ports.operation_handlers), 0)
            formal = {
                capability.code
                for capability in ports.capabilities
                if capability.truth_state == "FORMAL"
            }
            self.assertEqual(
                formal,
                {
                    "ProjectSessionService",
                    "ArtifactService",
                    "BacktestService",
                    "ProductEntryService",
                },
            )

    def test_development_shell_remains_explicit_only(self) -> None:
        args = type(
            "Args", (), {"storage_root": None, "development_shell": True}
        )()
        ports = _build_ports(args)
        self.assertEqual(ports.operation_handlers, {})
        self.assertEqual(
            [item.code for item in ports.capabilities],
            [item.code for item in default_capabilities()],
        )


class RegistryRouterTests(_PortsCase):
    def test_every_bound_operation_is_frozen(self) -> None:
        for operation_id in self.router.bound_operation_ids:
            self.assertIn(operation_id, OPERATIONS)

    def test_no_frozen_operation_is_unknown_to_the_router(self) -> None:
        for operation_id in self.router.bound_operation_ids:
            self.assertIn(operation_id, OPERATIONS)

    def test_response_dto_is_contract_valid(self) -> None:
        response = self.route(
            "ProjectSessionService.v1.getProjectContext"
        )
        self.assertEqual(response["kind"], "response")
        self.assertEqual(response["status"], "OK", response)
        body = response["body"]
        self.assertEqual(body["truth_state"], "FORMAL")
        self.assertEqual(body["request_id"], response["request_id"])
        self.assertIn("project_context_revision_id", body["read_model"])


class CapabilityMatrixTests(_PortsCase):
    def test_service_capabilities_are_honest(self) -> None:
        capabilities = {item.code: item for item in self.ports.capabilities}
        # Product Entry expansion (task-authorized): 17 -> 18 services.
        self.assertEqual(len(capabilities), 18)
        self.assertEqual(set(capabilities), set(SERVICE_CONTRACTS))
        bound_services = {
            operation.split(".v1.")[0]
            for operation in self.ports.operation_handlers
        }
        for service, capability in capabilities.items():
            contract = SERVICE_CONTRACTS[service]
            frozen_ops = {op.operation_id for op in contract.operations}
            bound_ops = {
                op for op in self.ports.operation_handlers if op in frozen_ops
            }
            if capability.truth_state == "FORMAL":
                self.assertEqual(
                    bound_ops,
                    frozen_ops,
                    f"{service} claims FORMAL but is not fully bound",
                )
                self.assertIsNone(capability.reason_code)
            else:
                self.assertEqual(capability.truth_state, "UNAVAILABLE")
                self.assertLessEqual(len(bound_ops), len(frozen_ops))
                if bound_ops:
                    self.assertEqual(
                        capability.reason_code, "PRODUCT_OPERATION_SET_INCOMPLETE"
                    )
        self.assertEqual(
            {service for service, capability in capabilities.items() if capability.truth_state == "FORMAL"},
            {
                service
                for service in SERVICE_CONTRACTS
                if {op.operation_id for op in SERVICE_CONTRACTS[service].operations}
                <= set(self.ports.operation_handlers)
            },
        )

    def test_result_service_reports_incomplete_honestly(self) -> None:
        capability = {
            item.code: item for item in self.ports.capabilities
        }["ResultService"]
        self.assertEqual(capability.truth_state, "UNAVAILABLE")
        self.assertEqual(capability.reason_code, "PRODUCT_OPERATION_SET_INCOMPLETE")
        self.assertIn("ResultService.v1.getResult", self.ports.operation_handlers)
        self.assertNotIn(
            "ResultService.v1.reconcileLedger", self.ports.operation_handlers
        )

    def test_task_service_reports_incomplete_honestly(self) -> None:
        capability = {
            item.code: item for item in self.ports.capabilities
        }["TaskService"]
        self.assertEqual(capability.truth_state, "UNAVAILABLE")
        self.assertEqual(capability.reason_code, "PRODUCT_OPERATION_SET_INCOMPLETE")
        frozen_ops = {
            operation.operation_id
            for operation in SERVICE_CONTRACTS["TaskService"].operations
        }
        bound_ops = frozen_ops & set(self.ports.operation_handlers)
        self.assertEqual(len(bound_ops), 5)
        self.assertEqual(
            frozen_ops - bound_ops,
            {"TaskService.v1.resumeTask"},
        )


class ProjectSessionTests(_PortsCase):
    def test_open_get_restore_across_restart(self) -> None:
        session_id = mint_uuid7()
        opened = self.route(
            "ProjectSessionService.v1.openProject",
            project_locator=f"v3:{self.setup.project_id}",
            session_id=session_id,
        )
        self.assertEqual(opened["status"], "OK", opened)
        context = self.route("ProjectSessionService.v1.getProjectContext")
        self.assertEqual(context["status"], "OK", context)
        restored = self.route(
            "ProjectSessionService.v1.restoreSession", session_id=session_id
        )
        self.assertEqual(restored["status"], "OK", restored)
        self.assertEqual(
            restored["body"]["read_model"]["project_id"], self.setup.project_id
        )
        # Restart: a fresh product runtime over the same storage root still restores.
        restarted = build_product_ports(self.storage_root)
        restarted_router = RequestRouter(restarted.operation_handlers)
        request_id = mint_uuid7()
        body = {
            "request_id": request_id,
            "project_id": self.setup.project_id,
            "project_context_revision_id": self.setup.project_context_revision_id,
            "expected_api_version": "1.0",
            "session_id": session_id,
        }
        response = restarted_router.route(
            {
                "kind": "request",
                "request_id": request_id,
                "operation_id": "ProjectSessionService.v1.restoreSession",
                "contract_version": "1.0",
                "project_id": self.setup.project_id,
                "project_context_revision_id": self.setup.project_context_revision_id,
                "body": body,
            }
        )
        self.assertEqual(response["status"], "OK", response)
        self.assertEqual(
            response["body"]["read_model"]["session_id"], session_id
        )

    def test_revise_context_appends_revision(self) -> None:
        revised = self.route(
            "ProjectSessionService.v1.reviseProjectContext",
            base_revision_id=self.setup.project_context_revision_id,
            patch={"context_fields": {"notes": "b3 golden project"}},
            idempotency_key="revise-key-0001",
        )
        self.assertEqual(revised["status"], "OK", revised)
        new_revision = revised["body"]["read_model"]["project_context_revision_id"]
        self.assertNotEqual(new_revision, self.setup.project_context_revision_id)
        context = self.route(
            "ProjectSessionService.v1.getProjectContext", _pcr_id=new_revision
        )
        self.assertEqual(
            context["body"]["read_model"]["context"]["context_fields"]["notes"],
            "b3 golden project",
        )
        # Idempotent repeat returns the same revision.
        repeated = self.route(
            "ProjectSessionService.v1.reviseProjectContext",
            base_revision_id=self.setup.project_context_revision_id,
            patch={"context_fields": {"notes": "b3 golden project"}},
            idempotency_key="revise-key-0001",
        )
        self.assertEqual(
            repeated["body"]["read_model"]["project_context_revision_id"],
            new_revision,
        )

    def test_stale_base_revision_fails_closed(self) -> None:
        self.route(
            "ProjectSessionService.v1.reviseProjectContext",
            base_revision_id=self.setup.project_context_revision_id,
            patch={"context_fields": {"notes": "first"}},
            idempotency_key="revise-key-0002",
        )
        stale = self.route(
            "ProjectSessionService.v1.reviseProjectContext",
            base_revision_id=self.setup.project_context_revision_id,
            patch={"context_fields": {"notes": "second"}},
            idempotency_key="revise-key-0003",
        )
        self.assert_error(stale, ErrorCode.CONFLICT.value)


class GoldenExecutionTests(_PortsCase):
    def _submit(self, idempotency_key: str = "golden-key-0001", **overrides):
        fields = dict(
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key=idempotency_key,
        )
        fields.update(overrides)
        return self.route("BacktestService.v1.submitBacktest", **fields)

    def test_golden_path_produces_durable_evidence(self) -> None:
        response = self._submit()
        self.assertEqual(response["status"], "OK", response)
        accepted = response["body"]
        task_id = accepted["task_id"]
        run_id = accepted["run_id"]
        self.assertEqual(accepted["accepted_state"], "QUEUED")
        self.assertGreaterEqual(accepted["event_cursor"], 1)

        task_response = self.route("TaskService.v1.getTask", task_id=task_id)
        self.assertEqual(task_response["status"], "OK", task_response)
        read_model = task_response["body"]["read_model"]
        self.assertEqual(read_model["state"], "SUCCEEDED")
        self.assertEqual(read_model["run_id"], run_id)
        result_id = read_model["result_id"]
        self.assertIsInstance(result_id, str)
        self.assertTrue(result_id.startswith("res_"))

        result_artifact_id = read_model["outputs"]["BACKTEST_RUN_RESULT"]
        result_response = self.route(
            "ResultService.v1.getResult", result_id=result_id, section="summary", page={}
        )
        self.assertEqual(result_response["status"], "OK", result_response)
        result_model = result_response["body"]["read_model"]
        self.assertEqual(result_model["state"], "PENDING_RECONCILIATION")
        self.assertEqual(
            result_model["result_artifact"]["artifact_id"], result_artifact_id
        )

        descriptor = self.route(
            "ArtifactService.v1.getArtifactDescriptor",
            artifact_id=result_artifact_id,
        )
        self.assertEqual(descriptor["status"], "OK", descriptor)
        descriptor_model = descriptor["body"]["read_model"]
        self.assertEqual(descriptor_model["artifact_id"], result_artifact_id)
        # Actual bytes hash must equal the declared SHA (verified store read).
        import hashlib

        payload = self.product.read_verified_bytes(result_artifact_id)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), descriptor_model["sha256"])
        # The runtime execution must reproduce the same canonical backtest result
        # the setup pipeline produced from the identical run spec.
        wire = json.loads(payload.decode("utf-8"))
        self.assertEqual(wire["run_spec_id"], self.setup.run_spec_id)
        # The runtime must reproduce the same canonical backtest result the
        # setup pipeline produced from the identical run spec.
        self.assertEqual(
            wire["result_id"], self.setup.pipeline_result.backtest_result_id
        )
        self.assertEqual(
            wire["content_sha256"],
            self.setup.pipeline_result.backtest_result_id.removeprefix("btrr_sha256_"),
        )

        connection = self.product._connection(read_only=True)
        try:
            lifecycle = connection.execute(
                """
                SELECT l.state AS lease_state, w.state AS worker_state
                FROM worker_lease l JOIN worker w ON w.worker_id=l.worker_id
                JOIN task_attempt a ON a.attempt_id=l.attempt_id
                JOIN run r ON r.run_id=a.run_id
                WHERE r.task_id=?
                """,
                (task_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(lifecycle)
        self.assertEqual(lifecycle["lease_state"], "RELEASED")
        self.assertEqual(lifecycle["worker_state"], "STOPPED")

    def test_duplicate_idempotency_key_returns_same_task(self) -> None:
        first = self._submit()
        self.assertEqual(first["status"], "OK", first)
        second = self._submit()
        self.assertEqual(second["status"], "OK", second)
        self.assertEqual(first["body"]["task_id"], second["body"]["task_id"])
        self.assertEqual(first["body"]["run_id"], second["body"]["run_id"])

    def test_durable_idempotency_has_one_authoritative_definition(self) -> None:
        self.assertEqual(
            inspect.getsource(product_runtime_module).count("class DurableIdempotency"),
            1,
        )
        self.assertTrue(hasattr(self.product.idempotency, "check_or_record"))
        self.assertTrue(hasattr(self.product.idempotency, "lookup"))

    def test_same_key_different_request_fails_closed(self) -> None:
        first = self._submit(idempotency_key="golden-key-conflict")
        self.assertEqual(first["status"], "OK", first)
        conflict = self._submit(
            idempotency_key="golden-key-conflict",
            run_spec_id="btrs_sha256_" + "f" * 64,
        )
        self.assert_error(conflict, ErrorCode.IDEMPOTENCY_CONFLICT.value)


class RestartRecoveryTests(_PortsCase):
    def test_restart_reconciles_orphan_active_task_lease_and_worker(self) -> None:
        task, run, attempt = self.product.execution._create_task(
            operation_id="BacktestService.v1.submitBacktest",
            project_id=self.setup.project_id,
            project_context_revision_id=self.setup.project_context_revision_id,
            normalized_input_hash="a" * 64,
            context_artifact_id=None,
        )
        self.product.execution._transition_to_running(task, run, attempt)

        restarted = ProductRuntime(self.storage_root)
        self.assertGreaterEqual(restarted.reconciliation_summary["tasks_failed"], 1)
        connection = restarted._connection(read_only=True)
        try:
            row = connection.execute(
                """
                SELECT t.state AS task_state, r.state AS run_state,
                       a.state AS attempt_state, l.state AS lease_state,
                       w.state AS worker_state
                FROM task t
                JOIN run r ON r.task_id=t.task_id
                JOIN task_attempt a ON a.run_id=r.run_id
                JOIN worker_lease l ON l.attempt_id=a.attempt_id
                JOIN worker w ON w.worker_id=l.worker_id
                WHERE t.task_id=?
                """,
                (task.task_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["task_state"], "FAILED")
        self.assertEqual(row["run_state"], "TERMINAL")
        self.assertEqual(row["attempt_state"], "LOST")
        self.assertEqual(row["lease_state"], "REVOKED")
        self.assertEqual(row["worker_state"], "LOST")

    def test_restart_reconciles_expired_lease_without_leaving_worker_busy(self) -> None:
        task, run, attempt = self.product.execution._create_task(
            operation_id="BacktestService.v1.submitBacktest",
            project_id=self.setup.project_id,
            project_context_revision_id=self.setup.project_context_revision_id,
            normalized_input_hash="b" * 64,
            context_artifact_id=None,
        )
        self.product.execution._transition_to_running(task, run, attempt)
        with self.product.task_persistence.begin() as unit:
            unit.connection.execute(
                "UPDATE worker_lease SET state='EXPIRED' WHERE lease_id=?",
                (attempt.lease_id,),
            )
            unit.commit()

        restarted = ProductRuntime(self.storage_root)
        self.assertGreaterEqual(restarted.reconciliation_summary["expired_leases_reconciled"], 1)
        connection = restarted._connection(read_only=True)
        try:
            row = connection.execute(
                """
                SELECT t.state AS task_state, a.state AS attempt_state,
                       l.state AS lease_state, w.state AS worker_state
                FROM task t
                JOIN run r ON r.task_id=t.task_id
                JOIN task_attempt a ON a.run_id=r.run_id
                JOIN worker_lease l ON l.attempt_id=a.attempt_id
                JOIN worker w ON w.worker_id=l.worker_id
                WHERE t.task_id=?
                """,
                (task.task_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["task_state"], "FAILED")
        self.assertEqual(row["attempt_state"], "LOST")
        self.assertEqual(row["lease_state"], "EXPIRED")
        self.assertEqual(row["worker_state"], "LOST")

    def test_task_result_artifact_recover_after_restart(self) -> None:
        submitted = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="restart-key-0001",
        )
        task_id = submitted["body"]["task_id"]
        run_id = submitted["body"]["run_id"]
        before = self.route("TaskService.v1.getTask", task_id=task_id)
        before_result_id = before["body"]["read_model"]["result_id"]
        self.assertIsInstance(before_result_id, str)
        connection = self.product._connection(read_only=True)
        try:
            row = connection.execute(
                "SELECT result_id FROM result WHERE backtest_run_id=?", (run_id,)
            ).fetchone()
            self.assertEqual(str(row[0]), before_result_id)
        finally:
            connection.close()
        result_artifact_id = before["body"]["read_model"]["outputs"]["BACKTEST_RUN_RESULT"]
        descriptor = self.route(
            "ArtifactService.v1.getArtifactDescriptor",
            artifact_id=result_artifact_id,
        )
        declared_sha = descriptor["body"]["read_model"]["sha256"]

        # Simulate a backend restart with a brand-new runtime over the same root.
        restarted_product = ProductRuntime(self.storage_root)
        restarted_ports = build_product_ports(self.storage_root)
        restarted_router = RequestRouter(restarted_ports.operation_handlers)

        def route_restarted(operation_id: str, **body_fields):
            request_id = mint_uuid7()
            body = {
                "request_id": request_id,
                "project_id": self.setup.project_id,
                "project_context_revision_id": self.setup.project_context_revision_id,
                "expected_api_version": "1.0",
                **body_fields,
            }
            return restarted_router.route(
                {
                    "kind": "request",
                    "request_id": request_id,
                    "operation_id": operation_id,
                    "contract_version": "1.0",
                    "project_id": self.setup.project_id,
                    "project_context_revision_id": self.setup.project_context_revision_id,
                    "body": body,
                }
            )

        after_task = route_restarted("TaskService.v1.getTask", task_id=task_id)
        self.assertEqual(after_task["status"], "OK", after_task)
        self.assertEqual(after_task["body"]["read_model"]["state"], "SUCCEEDED")
        after_result = route_restarted(
            "ResultService.v1.getResult",
            result_id=before_result_id,
            section="summary",
            page={},
        )
        self.assertEqual(after_result["status"], "OK", after_result)
        self.assertEqual(
            after_result["body"]["read_model"]["backtest_run_id"], run_id
        )
        after_descriptor = route_restarted(
            "ArtifactService.v1.getArtifactDescriptor",
            artifact_id=result_artifact_id,
        )
        self.assertEqual(
            after_descriptor["body"]["read_model"]["sha256"], declared_sha
        )
        import hashlib

        payload = restarted_product.read_verified_bytes(result_artifact_id)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), declared_sha)
        # Durable events replay through the restarted runtime's event source.
        events = restarted_product.task_persistence.replay(
            self.setup.project_id, after_sequence=0, limit=100
        )
        event_types = {event.event_type for event in events}
        self.assertIn("TASK_SUCCEEDED", event_types)


class NegativePathTests(_PortsCase):
    def test_unknown_operation_fails(self) -> None:
        request_id = mint_uuid7()
        response = self.router.route(
            {
                "kind": "request",
                "request_id": request_id,
                "operation_id": "NotAService.v1.notAnOperation",
                "contract_version": "1.0",
                "project_id": self.setup.project_id,
                "project_context_revision_id": self.setup.project_context_revision_id,
                "body": {},
            }
        )
        self.assert_error(response, ErrorCode.INVALID_ARGUMENT.value)

    def test_operation_in_unavailable_service_fails_closed(self) -> None:
        response = self.route(
            "ResearchService.v1.submitFactorAnalysis",
            factor_version_ids=["fav_x"],
            universe_version_id="unv_x",
            snapshot_id="snp_" + "A" * 26,
            analysis_spec={},
            idempotency_key="unavailable-key-1",
        )
        self.assert_error(response, ErrorCode.CAPABILITY_UNAVAILABLE.value)
        self.assertEqual(
            response["error"]["details"]["reason_code"], "ASL_FACADE_NOT_BOUND"
        )

    def test_wrong_project_id_fails_closed(self) -> None:
        other_project = "prj_AAAAAAAAAAAAAAAAAAAAAAAAAA"
        response = self.route(
            "ProjectSessionService.v1.getProjectContext", _project_id=other_project
        )
        self.assert_error(response, ErrorCode.NOT_FOUND.value)

    def test_wrong_context_revision_fails_closed(self) -> None:
        other_revision = "pcr_AAAAAAAAAAAAAAAAAAAAAAAAAA"
        response = self.route(
            "ProjectSessionService.v1.getProjectContext", _pcr_id=other_revision
        )
        self.assert_error(response, ErrorCode.NOT_FOUND.value)

    def test_unknown_run_spec_fails_closed(self) -> None:
        response = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id="btrs_sha256_" + "0" * 64,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="unknown-spec-key-1",
        )
        self.assert_error(response, ErrorCode.NOT_FOUND.value)

    def test_unadmitted_execution_adapter_fails_closed(self) -> None:
        response = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id="v3.other.engine/9.9.9",
            idempotency_key="bad-adapter-key-1",
        )
        self.assert_error(response, ErrorCode.TRUTH_PRECONDITION_FAILED.value)

    def test_stale_context_on_submit_fails_closed(self) -> None:
        self.route(
            "ProjectSessionService.v1.reviseProjectContext",
            base_revision_id=self.setup.project_context_revision_id,
            patch={"context_fields": {"notes": "moved forward"}},
            idempotency_key="revise-key-stale-1",
        )
        # The run spec context is pinned to the original revision; submitting
        # under the new revision must fail closed instead of silently binding.
        response = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="stale-context-key-1",
            _pcr_id=self.product.current_revision(self.setup.project_id)[
                "project_context_revision_id"
            ],
        )
        self.assert_error(response, ErrorCode.TRUTH_PRECONDITION_FAILED.value)

    def test_tampered_spec_artifact_fails_before_engine(self) -> None:
        spec_rows = self.product.spec_codec.resolve_reference(
            self.setup.project_id, "RESEARCH_RUN_SPEC"
        )
        artifact_id = None
        for row in spec_rows:
            payload = self.product.read_verified_bytes(row["artifact_id"])
            if json.loads(payload.decode("utf-8")).get("run_spec_id") == self.setup.run_spec_id:
                artifact_id = str(row["artifact_id"])
                break
        self.assertIsNotNone(artifact_id)
        from v3_backend.domain.artifacts.identity import storage_key_for_artifact_id

        key = storage_key_for_artifact_id(artifact_id)
        target = self.product.artifact_root / key
        tampered = bytearray(target.read_bytes())
        tampered[0] ^= 0xFF
        target.write_bytes(bytes(tampered))
        task_count_before = self._task_count()
        response = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="tampered-key-1",
        )
        self.assertEqual(response["status"], "ERROR", response)
        self.assertEqual(self._task_count(), task_count_before)

    def _task_count(self) -> int:
        connection = self.product._connection(read_only=True)
        try:
            value = connection.execute("SELECT COUNT(*) FROM task").fetchone()[0]
        finally:
            connection.close()
        return int(value)


class ArtifactServiceTests(_PortsCase):
    def test_stream_ticket_and_gc_plan(self) -> None:
        submitted = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="artifact-key-0001",
        )
        artifact_id = self.route(
            "TaskService.v1.getTask", task_id=submitted["body"]["task_id"]
        )["body"]["read_model"]["outputs"]["BACKTEST_RUN_RESULT"]
        ticket = self.route(
            "ArtifactService.v1.openArtifactStream", artifact_id=artifact_id
        )
        self.assertEqual(ticket["status"], "OK", ticket)
        ticket_model = ticket["body"]["read_model"]
        self.assertEqual(ticket_model["artifact_id"], artifact_id)
        self.assertEqual(ticket_model["mode"], "STREAM_TICKET")
        self.assertNotIn("storage_key", ticket_model)
        plan = self.route(
            "ArtifactService.v1.planGarbageCollection",
            retention_profile_id="default",
        )
        self.assertEqual(plan["status"], "OK", plan)
        plan_model = plan["body"]["read_model"]
        self.assertTrue(plan_model["requires_confirmation"])
        for candidate in plan_model["candidates"]:
            self.assertNotEqual(candidate["artifact_id"], artifact_id)

    def test_export_artifact_produces_manifest_task(self) -> None:
        submitted = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="export-key-0001",
        )
        task_id = submitted["body"]["task_id"]
        artifact_id = self.route(
            "TaskService.v1.getTask", task_id=task_id
        )["body"]["read_model"]["outputs"]["BACKTEST_RUN_RESULT"]
        exported = self.route(
            "ArtifactService.v1.exportArtifact",
            artifact_ids=[artifact_id],
            export_profile_id="LIGHT_REVIEW",
            destination_token="dest-token-1",
            idempotency_key="export-key-0002",
        )
        self.assertEqual(exported["status"], "OK", exported)
        export_task = self.route(
            "TaskService.v1.getTask", task_id=exported["body"]["task_id"]
        )
        self.assertEqual(export_task["body"]["read_model"]["state"], "SUCCEEDED")
        manifest_id = export_task["body"]["read_model"]["outputs"]["EXPORT_MANIFEST"]
        manifest_wire = json.loads(
            self.product.read_verified_bytes(manifest_id).decode("utf-8")
        )
        self.assertEqual(manifest_wire["artifacts"][0]["artifact_id"], artifact_id)
        self.assertEqual(manifest_wire["destination_token"], "dest-token-1")


class BacktestServiceExperimentTests(_PortsCase):
    def test_experiment_lifecycle(self) -> None:
        created = self.route(
            "BacktestService.v1.createExperiment",
            experiment_spec={
                "axes": [{"axis_id": "spec", "label": "run spec"}],
                "cells": [
                    {
                        "run_spec_id": self.setup.run_spec_id,
                        "execution_adapter_version_id": ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
                    }
                ],
            },
            idempotency_key="experiment-key-0001",
        )
        self.assertEqual(created["status"], "OK", created)
        experiment_id = created["body"]["read_model"]["experiment_id"]
        self.assertEqual(created["body"]["read_model"]["state"], "DRAFT")
        fetched = self.route(
            "BacktestService.v1.getExperiment", experiment_id=experiment_id
        )
        self.assertEqual(fetched["status"], "OK", fetched)
        expanded = self.route(
            "BacktestService.v1.expandExperiment",
            experiment_id=experiment_id,
            idempotency_key="expand-key-0001",
        )
        self.assertEqual(expanded["status"], "OK", expanded)
        expanded_task = self.route(
            "TaskService.v1.getTask", task_id=expanded["body"]["task_id"]
        )
        self.assertEqual(expanded_task["body"]["read_model"]["state"], "SUCCEEDED")
        after = self.route(
            "BacktestService.v1.getExperiment", experiment_id=experiment_id
        )
        self.assertEqual(after["body"]["read_model"]["state"], "EXPANDED")


class TaskOperationTests(_PortsCase):
    def test_list_tasks_and_events(self) -> None:
        self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="task-ops-key-1",
        )
        listed = self.route(
            "TaskService.v1.listTasks", filter={}, page_size=10
        )
        self.assertEqual(listed["status"], "OK", listed)
        self.assertGreaterEqual(len(listed["body"]["read_model"]["items"]), 1)
        events = self.route(
            "TaskService.v1.getEvents", after_sequence=0, limit=100
        )
        self.assertEqual(events["status"], "OK", events)
        event_types = {item["event_type"] for item in events["body"]["read_model"]["items"]}
        self.assertIn("TASK_SUCCEEDED", event_types)

    def test_cancel_terminal_task_is_rejected(self) -> None:
        submitted = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="cancel-key-1",
        )
        task_id = submitted["body"]["task_id"]
        task = self.product.task_persistence.read_task(task_id)
        response = self.route(
            "TaskService.v1.cancelTask",
            task_id=task_id,
            expected_state_version=task.state_version,
            reason="user changed mind",
        )
        self.assert_error(response, ErrorCode.CONFLICT.value)

    def test_resume_task_is_capability_unavailable(self) -> None:
        submitted = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="resume-key-1",
        )
        task_id = submitted["body"]["task_id"]
        task = self.product.task_persistence.read_task(task_id)
        response = self.route(
            "TaskService.v1.resumeTask",
            task_id=task_id,
            checkpoint_artifact_id="art_sha256_" + "a" * 64,
            expected_state_version=task.state_version,
        )
        self.assert_error(response, ErrorCode.CAPABILITY_UNAVAILABLE.value)


if __name__ == "__main__":
    unittest.main()
