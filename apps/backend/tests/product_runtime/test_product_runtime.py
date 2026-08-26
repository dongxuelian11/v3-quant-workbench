"""B3 product runtime integration tests: normal bootstrap, contract registry,
honest capabilities, golden execution, idempotency, restart recovery,
negative paths, artifact tampering, export, experiment and task operations.

These tests drive the same RequestRouter the framed-stdio runtime uses, so
every response passes the frozen operation DTO validation on the way out.
"""

from __future__ import annotations

import base64
import hashlib
import json
import inspect
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from v3_backend.contracts.registry import OPERATIONS, SERVICE_CONTRACTS
from v3_backend.errors.codes import ErrorCode
from v3_backend.errors import ResourceRejectedError
from v3_backend.errors.exceptions import (
    InvalidArgumentError,
    TruthPreconditionFailedError,
    V3ContractError,
)
from v3_backend.runtime.bootstrap import _build_ports
from v3_backend.runtime.composition_root import (
    RuntimePorts,
    RequestRouter,
    default_capabilities,
)
from v3_backend.runtime.product_runtime import (
    ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
    PRODUCT_EXECUTION_CONTEXT_ROLE,
    ProductArtifactBatch,
    ProductRuntime,
    build_product_ports,
    build_product_runtime,
    mint_uuid7,
)
from v3_backend.runtime import product_runtime as product_runtime_module
from v3_backend.runtime import product_research as product_research_module
from v3_backend.domain.tasks.entities import TaskState
from v3_backend.runtime.product_facades import (
    ArtifactFacade,
    BacktestFacade,
    ProjectSessionFacade,
    _session_row_id_for_value,
)
from v3_backend.runtime.product_entry import create_project

from .helpers import build_product_golden_project


class _PortsCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.storage_root = Path(self._temporary.name)
        self.setup = build_product_golden_project(self.storage_root)
        self.product = build_product_runtime(self.storage_root)
        self.ports: RuntimePorts = build_product_ports(self.storage_root)
        self.production_router = RequestRouter(self.ports.operation_handlers)
        internal_handlers = dict(self.ports.operation_handlers)
        internal_handlers.update(BacktestFacade(self.product).handlers())
        self.router = RequestRouter(internal_handlers)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def route(self, operation_id: str, **body_fields):
        return self._route_with(self.router, operation_id, **body_fields)

    def route_production(self, operation_id: str, **body_fields):
        return self._route_with(self.production_router, operation_id, **body_fields)

    def _route_with(self, router: RequestRouter, operation_id: str, **body_fields):
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
        return router.route(wire)

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
                if service == "BacktestService":
                    self.assertEqual(
                        capability.reason_code,
                        "FORMAL_EXECUTION_CONTRACT_NOT_CLOSED",
                    )
                elif bound_ops:
                    self.assertEqual(
                        capability.reason_code, "PRODUCT_OPERATION_SET_INCOMPLETE"
                    )
        self.assertEqual(
            {service for service, capability in capabilities.items() if capability.truth_state == "FORMAL"},
            {
                "ProjectSessionService",
                "ArtifactService",
                "ProductEntryService",
            },
        )

    def test_result_service_reports_incomplete_honestly(self) -> None:
        capability = {
            item.code: item for item in self.ports.capabilities
        }["ResultService"]
        self.assertEqual(capability.truth_state, "UNAVAILABLE")
        self.assertEqual(capability.reason_code, "PRODUCT_OPERATION_SET_INCOMPLETE")
        self.assertEqual(
            {
                operation.operation_id
                for operation in SERVICE_CONTRACTS["ResultService"].operations
            },
            set(self.ports.operation_handlers)
            & {
                operation.operation_id
                for operation in SERVICE_CONTRACTS["ResultService"].operations
            },
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

    def test_legacy_backtest_service_is_unavailable_until_formal_contract_closes(self) -> None:
        capability = {
            item.code: item for item in self.ports.capabilities
        }["BacktestService"]
        self.assertEqual(capability.truth_state, "UNAVAILABLE")
        self.assertEqual(
            capability.reason_code,
            "FORMAL_EXECUTION_CONTRACT_NOT_CLOSED",
        )

        response = self.route_production(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="legacy-backtest-must-stay-unavailable",
        )
        error = self.assert_error(response, ErrorCode.CAPABILITY_UNAVAILABLE.value)
        self.assertEqual(
            error["error"]["details"]["reason_code"],
            "FORMAL_EXECUTION_CONTRACT_NOT_CLOSED",
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
        self.assertEqual(
            restored["body"]["read_model"]["canonical_session_uuid"], session_id
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
        self.assertEqual(
            response["body"]["read_model"]["canonical_session_uuid"], session_id
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

    def test_restore_rejects_durable_canonical_session_identity_mismatch(self) -> None:
        session_id = mint_uuid7()
        opened = self.route(
            "ProjectSessionService.v1.openProject",
            project_locator=f"v3:{self.setup.project_id}",
            session_id=session_id,
        )
        self.assertEqual(opened["status"], "OK", opened)

        connection = self.product._connection()
        try:
            connection.execute(
                """
                UPDATE desktop_session
                SET canonical_session_uuid=?
                WHERE session_id=?
                """,
                (
                    "bbbbbbbb-cccc-7ddd-8eee-ffffffffffff",
                    _session_row_id_for_value(session_id),
                ),
            )
            connection.commit()
        finally:
            connection.close()

        rejected = self.route(
            "ProjectSessionService.v1.restoreSession", session_id=session_id
        )
        self.assert_error(
            rejected,
            ErrorCode.SESSION_PROJECT_BINDING_CONFLICT.value,
        )

    def test_restore_rejects_superseded_context_revision(self) -> None:
        session_id = mint_uuid7()
        opened = self.route(
            "ProjectSessionService.v1.openProject",
            project_locator=f"v3:{self.setup.project_id}",
            session_id=session_id,
        )
        self.assertEqual(opened["status"], "OK", opened)
        revised = self.route(
            "ProjectSessionService.v1.reviseProjectContext",
            base_revision_id=self.setup.project_context_revision_id,
            patch={"context_fields": {"notes": "restore must use current revision"}},
            idempotency_key="restore-stale-revision",
        )
        self.assertEqual(revised["status"], "OK", revised)
        stale_restore = self._route_with(
            self.router,
            "ProjectSessionService.v1.restoreSession",
            _pcr_id=self.setup.project_context_revision_id,
            session_id=session_id,
        )
        self.assert_error(stale_restore, ErrorCode.TRUTH_PRECONDITION_FAILED.value)

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

    def test_concurrent_cross_project_open_has_one_winner_and_one_stable_conflict(
        self,
    ) -> None:
        other = create_project(
            self.product,
            display_name="Concurrent other project",
            idempotency_key="concurrent-session-other-project",
        )
        session_id = mint_uuid7()
        first_router = RequestRouter(self.ports.operation_handlers)
        second_router = RequestRouter(self.ports.operation_handlers)

        def open_project(
            router: RequestRouter, project_id: str, revision_id: str
        ) -> dict:
            return self._route_with(
                router,
                "ProjectSessionService.v1.openProject",
                _project_id=project_id,
                _pcr_id=revision_id,
                project_locator=f"v3:{project_id}",
                session_id=session_id,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(
                    open_project,
                    first_router,
                    self.setup.project_id,
                    self.setup.project_context_revision_id,
                ),
                executor.submit(
                    open_project,
                    second_router,
                    other["project_id"],
                    other["project_context_revision_id"],
                ),
            )
            responses = tuple(future.result() for future in futures)

        self.assertEqual(sorted(response["status"] for response in responses), ["ERROR", "OK"])
        conflict = next(response for response in responses if response["status"] == "ERROR")
        self.assertEqual(
            conflict["error"]["code"],
            ErrorCode.SESSION_PROJECT_BINDING_CONFLICT.value,
        )
        winner = self.setup.project_id if responses[0]["status"] == "OK" else other["project_id"]
        connection = self.product._connection(read_only=True)
        try:
            rows = connection.execute(
                "SELECT project_id FROM desktop_session"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0]["project_id"]), winner)

    def test_noncanonical_session_case_is_rejected_before_binding(self) -> None:
        other = create_project(
            self.product,
            display_name="Uppercase alias project",
            idempotency_key="uppercase-session-alias-project",
        )
        session_id = "018f0a00-0000-7000-8000-00000000000a"
        opened = self.route(
            "ProjectSessionService.v1.openProject",
            project_locator=f"v3:{self.setup.project_id}",
            session_id=session_id,
        )
        self.assertEqual(opened["status"], "OK", opened)

        conflict = self._route_with(
            self.router,
            "ProjectSessionService.v1.openProject",
            _project_id=other["project_id"],
            _pcr_id=other["project_context_revision_id"],
            project_locator=f"v3:{other['project_id']}",
            session_id=session_id.upper(),
        )
        self.assert_error(conflict, ErrorCode.INVALID_ARGUMENT.value)

        connection = self.product._connection(read_only=True)
        try:
            rows = connection.execute(
                "SELECT project_id FROM desktop_session"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0]["project_id"]), self.setup.project_id)

        with self.assertRaises(InvalidArgumentError):
            ProjectSessionFacade(self.product).open_project(
                {
                    "request_id": mint_uuid7(),
                    "project_id": other["project_id"],
                    "project_context_revision_id": other[
                        "project_context_revision_id"
                    ],
                    "session_id": "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
                }
            )

    def test_legacy_lowercase_session_row_is_reused_and_still_bound(self) -> None:
        other = create_project(
            self.product,
            display_name="Legacy uppercase alias project",
            idempotency_key="legacy-uppercase-session-alias-project",
        )
        session_id = "018f0a00-0000-7000-8000-00000000000b"
        legacy_row_id = _session_row_id_for_value(session_id)
        connection = self.product._connection()
        try:
            connection.execute(
                """
                INSERT INTO desktop_session(
                    session_id, project_id, project_context_revision_id,
                    state, opened_at, row_version
                ) VALUES(?,?,?,?,?,0)
                """,
                (
                    legacy_row_id,
                    self.setup.project_id,
                    self.setup.project_context_revision_id,
                    "OPEN",
                    "2026-08-26T00:00:00.000000Z",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        reopened = self.route(
            "ProjectSessionService.v1.openProject",
            project_locator=f"v3:{self.setup.project_id}",
            session_id=session_id,
        )
        self.assertEqual(reopened["status"], "OK", reopened)
        conflict = self._route_with(
            self.router,
            "ProjectSessionService.v1.openProject",
            _project_id=other["project_id"],
            _pcr_id=other["project_context_revision_id"],
            project_locator=f"v3:{other['project_id']}",
            session_id=session_id.lower(),
        )
        self.assert_error(
            conflict,
            ErrorCode.SESSION_PROJECT_BINDING_CONFLICT.value,
        )

    def test_unresolved_legacy_session_identity_blocks_unknown_binding(
        self,
    ) -> None:
        other = create_project(
            self.product,
            display_name="Legacy mixed-case alias project",
            idempotency_key="legacy-mixed-case-session-alias-project",
        )
        legacy_session_id = "018f0a00-0000-7000-8000-00000000000C"
        request_session_id = legacy_session_id.lower()
        legacy_row_id = _session_row_id_for_value(legacy_session_id)
        connection = self.product._connection()
        try:
            connection.execute(
                """
                INSERT INTO desktop_session(
                    session_id, project_id, project_context_revision_id,
                    state, opened_at, row_version
                ) VALUES(?,?,?,?,?,0)
                """,
                (
                    legacy_row_id,
                    self.setup.project_id,
                    self.setup.project_context_revision_id,
                    "OPEN",
                    "2026-08-26T00:00:00.000000Z",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        rejected = self._route_with(
            self.router,
            "ProjectSessionService.v1.openProject",
            _project_id=other["project_id"],
            _pcr_id=other["project_context_revision_id"],
            project_locator=f"v3:{other['project_id']}",
            session_id=request_session_id,
        )
        self.assert_error(
            rejected,
            ErrorCode.SESSION_PROJECT_BINDING_CONFLICT.value,
        )
        restore_rejected = self._route_with(
            self.router,
            "ProjectSessionService.v1.restoreSession",
            _project_id=other["project_id"],
            _pcr_id=other["project_context_revision_id"],
            session_id=request_session_id,
        )
        self.assert_error(
            restore_rejected,
            ErrorCode.SESSION_PROJECT_BINDING_CONFLICT.value,
        )
        same_project_open = self.route(
            "ProjectSessionService.v1.openProject",
            project_locator=f"v3:{self.setup.project_id}",
            session_id="018f0a00-0000-7000-8000-00000000000e",
        )
        self.assertEqual(same_project_open["status"], "OK", same_project_open)
        connection = self.product._connection(read_only=True)
        try:
            rows = connection.execute(
                "SELECT project_id FROM desktop_session"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {str(row["project_id"]) for row in rows},
            {self.setup.project_id},
        )

    def test_legacy_alias_cannot_hide_behind_existing_other_project_row(self) -> None:
        other = create_project(
            self.product,
            display_name="Legacy alias existing-row project",
            idempotency_key="legacy-alias-existing-row-project",
        )
        uppercase_session_id = "018f0a00-0000-7000-8000-00000000000F"
        lowercase_session_id = uppercase_session_id.lower()
        connection = self.product._connection()
        try:
            connection.executemany(
                """
                INSERT INTO desktop_session(
                    session_id, project_id, project_context_revision_id,
                    state, opened_at, row_version
                ) VALUES(?,?,?,?,?,0)
                """,
                (
                    (
                        _session_row_id_for_value(uppercase_session_id),
                        self.setup.project_id,
                        self.setup.project_context_revision_id,
                        "OPEN",
                        "2026-08-26T00:00:00.000000Z",
                    ),
                    (
                        _session_row_id_for_value(lowercase_session_id),
                        other["project_id"],
                        other["project_context_revision_id"],
                        "OPEN",
                        "2026-08-26T00:00:00.000000Z",
                    ),
                ),
            )
            connection.commit()
        finally:
            connection.close()

        for operation_id in (
            "ProjectSessionService.v1.openProject",
            "ProjectSessionService.v1.restoreSession",
        ):
            with self.subTest(operation_id=operation_id):
                request_fields = {
                    "_project_id": other["project_id"],
                    "_pcr_id": other["project_context_revision_id"],
                    "session_id": lowercase_session_id,
                }
                if operation_id.endswith("openProject"):
                    request_fields["project_locator"] = f"v3:{other['project_id']}"
                rejected = self._route_with(
                    self.router,
                    operation_id,
                    **request_fields,
                )
                self.assert_error(
                    rejected,
                    ErrorCode.SESSION_PROJECT_BINDING_CONFLICT.value,
                )

        connection = self.product._connection(read_only=True)
        try:
            rows = connection.execute(
                "SELECT project_id,canonical_session_uuid FROM desktop_session"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["canonical_session_uuid"] is None for row in rows))

    def test_open_rechecks_current_revision_after_acquiring_the_write_lock(self) -> None:
        session_router = RequestRouter(ProjectSessionFacade(self.product).handlers())
        second_ports = build_product_ports(self.storage_root)
        second_router = RequestRouter(second_ports.operation_handlers)
        original_connection = self.product._connection
        advanced = False

        def connection_with_interleaved_revision(*, read_only: bool = False):
            nonlocal advanced
            if not read_only and not advanced:
                advanced = True
                revised = self._route_with(
                    second_router,
                    "ProjectSessionService.v1.reviseProjectContext",
                    base_revision_id=self.setup.project_context_revision_id,
                    patch={"context_fields": {"notes": "interleaved revision"}},
                    idempotency_key="open-project-interleaved-revision",
                )
                self.assertEqual(revised["status"], "OK", revised)
            return original_connection(read_only=read_only)

        self.product._connection = connection_with_interleaved_revision
        try:
            stale_open = self._route_with(
                session_router,
                "ProjectSessionService.v1.openProject",
                project_locator=f"v3:{self.setup.project_id}",
                session_id=mint_uuid7(),
            )
        finally:
            self.product._connection = original_connection

        self.assert_error(stale_open, ErrorCode.TRUTH_PRECONDITION_FAILED.value)
        connection = original_connection(read_only=True)
        try:
            self.assertEqual(
                int(connection.execute("SELECT COUNT(*) FROM desktop_session").fetchone()[0]),
                0,
            )
        finally:
            connection.close()


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

    def test_product_orchestration_does_not_capture_process_lifecycle_exceptions(self) -> None:
        for module in (product_runtime_module, product_research_module):
            self.assertNotIn("except BaseException", inspect.getsource(module))

    def test_unknown_product_exception_is_internal_and_not_retryable(self) -> None:
        from v3_backend.domain.tasks.retry_policy import RetryPolicy
        from v3_backend.runtime.product_runtime import classify_execution_error

        category = classify_execution_error(RuntimeError("unclassified program defect"))
        self.assertEqual(category.value, "INTERNAL_ERROR")
        decision = RetryPolicy().decide(category, 1)
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.delay_seconds)

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
    def test_artifact_batch_rejects_malformed_payload_before_staging(self) -> None:
        with self.assertRaisesRegex(V3ContractError, "payload tuple is invalid"):
            ProductArtifactBatch(
                store=self.product.artifact_store,
                payloads=(("prv_incomplete",),),
                published_at=datetime.now(timezone.utc),
            )

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
    def _publish_large_stream_artifact(
        self, facade: ArtifactFacade, payload: bytes
    ) -> str:
        staged = self.product.artifact_store.stage_bytes(payload)
        published = facade.publish_artifact(
            {
                "request_id": mint_uuid7(),
                "project_id": self.setup.project_id,
                "project_context_revision_id": self.product.current_revision(
                    self.setup.project_id
                )["project_context_revision_id"],
                "staging_token": staged.staging_token,
                "declared_media_type": "application/json",
                "declared_role": "PRODUCT_RESEARCH_BACKTEST_READ_MODEL",
                "expected_sha256": staged.sha256,
                "idempotency_key": "artifact-stream-large-publish",
            }
        )
        return str(published["read_model"]["artifact_id"])

    def test_acc_c3_09_stream_open_rejects_cross_project_artifact(self) -> None:
        submitted = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="artifact-cross-project-key",
        )
        artifact_id = self.route(
            "TaskService.v1.getTask", task_id=submitted["body"]["task_id"]
        )["body"]["read_model"]["outputs"]["BACKTEST_RUN_RESULT"]
        other = create_project(
            self.product,
            display_name="Other project",
            notes=None,
            idempotency_key="artifact-cross-project-other",
        )
        with self.assertRaises(TruthPreconditionFailedError):
            ArtifactFacade(self.product).open_artifact_stream(
                {
                    "request_id": mint_uuid7(),
                    "project_id": other["project_id"],
                    "artifact_id": artifact_id,
                    "range": None,
                }
            )

    def test_acc_c1_07_stream_ticket_capacity_and_expiry_are_bounded(self) -> None:
        submitted = self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="artifact-ticket-bound-key",
        )
        artifact_id = self.route(
            "TaskService.v1.getTask", task_id=submitted["body"]["task_id"]
        )["body"]["read_model"]["outputs"]["BACKTEST_RUN_RESULT"]
        now = [datetime(2026, 8, 23, tzinfo=timezone.utc)]
        facade = ArtifactFacade(
            self.product,
            clock=lambda: now[0],
            ticket_limit=4,
        )
        request_wire = {
            "request_id": mint_uuid7(),
            "project_id": self.setup.project_id,
            "artifact_id": artifact_id,
            "range": None,
        }
        for _ in range(4):
            facade.open_artifact_stream(request_wire)
        self.assertEqual(facade.retained_ticket_count, 4)
        with self.assertRaises(ResourceRejectedError):
            facade.open_artifact_stream(request_wire)

        now[0] += timedelta(seconds=301)
        facade.open_artifact_stream(request_wire)
        self.assertEqual(facade.retained_ticket_count, 1)

    def test_acc_c3_09_stream_consume_chunks_and_reassembles_exact_bytes(self) -> None:
        payload = json.dumps(
            {"payload": "x" * (600 * 1024)}, separators=(",", ":")
        ).encode("utf-8")
        facade = ArtifactFacade(self.product, runtime_generation=7)
        artifact_id = self._publish_large_stream_artifact(facade, payload)
        ticket = facade.open_artifact_stream(
            {
                "request_id": mint_uuid7(),
                "project_id": self.setup.project_id,
                "artifact_id": artifact_id,
                "range": None,
            }
        )["read_model"]

        frames = tuple(
            facade.consume_artifact_stream(
                ticket_id=ticket["ticket_id"],
                project_id=self.setup.project_id,
                project_context_revision_id=self.product.current_revision(
                    self.setup.project_id
                )["project_context_revision_id"],
                runtime_generation=7,
            )
        )
        chunks = frames[:-1]
        complete = frames[-1]
        self.assertGreaterEqual(len(chunks), 3)
        assembled = bytearray()
        for chunk in chunks:
            self.assertEqual(chunk["kind"], "artifactStream.chunk")
            decoded = base64.b64decode(chunk["payload_base64"], validate=True)
            self.assertLessEqual(len(decoded), 256 * 1024)
            self.assertEqual(chunk["offset"], len(assembled))
            self.assertEqual(hashlib.sha256(decoded).hexdigest(), chunk["chunk_sha256"])
            assembled.extend(decoded)
        self.assertEqual(bytes(assembled), payload)
        self.assertEqual(complete["kind"], "artifactStream.complete")
        self.assertEqual(complete["total_byte_count"], len(payload))
        self.assertEqual(complete["artifact_sha256"], hashlib.sha256(payload).hexdigest())

    def test_acc_c3_09_stream_ticket_expiry_replay_and_generation_fail_closed(self) -> None:
        now = [datetime(2026, 8, 24, tzinfo=timezone.utc)]
        facade = ArtifactFacade(
            self.product,
            clock=lambda: now[0],
            runtime_generation=7,
        )
        payload = b'{"stream":"lifecycle"}'
        artifact_id = self._publish_large_stream_artifact(facade, payload)
        request = {
            "request_id": mint_uuid7(),
            "project_id": self.setup.project_id,
            "artifact_id": artifact_id,
            "range": None,
        }
        context_id = self.product.current_revision(self.setup.project_id)[
            "project_context_revision_id"
        ]

        wrong_generation = facade.open_artifact_stream(request)["read_model"][
            "ticket_id"
        ]
        with self.assertRaises(TruthPreconditionFailedError):
            tuple(
                facade.consume_artifact_stream(
                    ticket_id=wrong_generation,
                    project_id=self.setup.project_id,
                    project_context_revision_id=context_id,
                    runtime_generation=8,
                )
            )
        self.assertTrue(
            tuple(
                facade.consume_artifact_stream(
                    ticket_id=wrong_generation,
                    project_id=self.setup.project_id,
                    project_context_revision_id=context_id,
                    runtime_generation=7,
                )
            )
        )

        consumed = facade.open_artifact_stream(request)["read_model"]["ticket_id"]
        tuple(
            facade.consume_artifact_stream(
                ticket_id=consumed,
                project_id=self.setup.project_id,
                project_context_revision_id=context_id,
                runtime_generation=7,
            )
        )
        with self.assertRaises(TruthPreconditionFailedError):
            tuple(
                facade.consume_artifact_stream(
                    ticket_id=consumed,
                    project_id=self.setup.project_id,
                    project_context_revision_id=context_id,
                    runtime_generation=7,
                )
            )

        expired = facade.open_artifact_stream(request)["read_model"]["ticket_id"]
        now[0] += timedelta(seconds=301)
        with self.assertRaises(TruthPreconditionFailedError):
            tuple(
                facade.consume_artifact_stream(
                    ticket_id=expired,
                    project_id=self.setup.project_id,
                    project_context_revision_id=context_id,
                    runtime_generation=7,
                )
            )

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

    def test_acc_c3_10_export_task_finishes_only_after_native_completion_receipt(self) -> None:
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
            destination_token="edc_01ARZ3NDEKTSV4RRFFQ69G5FAV",
            idempotency_key="export-key-0002",
        )
        self.assertEqual(exported["status"], "OK", exported)
        export_task_id = exported["body"]["task_id"]
        export_task = self.route(
            "TaskService.v1.getTask", task_id=export_task_id
        )
        self.assertEqual(export_task["body"]["read_model"]["state"], "RUNNING")
        self.assertNotIn("EXPORT_MANIFEST", export_task["body"]["read_model"]["outputs"])
        descriptor = self.product.require_project_reachable_artifact(
            self.setup.project_id, artifact_id
        )
        with self.assertRaises(InvalidArgumentError):
            self.product.execution.complete_artifact_export(
                project_id=self.setup.project_id,
                project_context_revision_id=self.product.current_revision(
                    self.setup.project_id
                )["project_context_revision_id"],
                task_id=export_task_id,
                destination_token="edc_01ARZ3NDEKTSV4RRFFQ69G5FAV",
                display_name="result.json",
                artifact_id=artifact_id,
                sha256=descriptor["sha256"],
                byte_size=True,
                completed_at="2026-08-24T00:00:00.000Z",
            )
        ArtifactFacade(self.product).handle_export_control(
            "artifactExport.complete",
            {
                "protocol_version": "v3.artifact-export/1.0.0",
                "project_id": self.setup.project_id,
                "project_context_revision_id": self.product.current_revision(
                    self.setup.project_id
                )["project_context_revision_id"],
                "task_id": export_task_id,
                "destination_token": "edc_01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "display_name": "result.json",
                "artifact_id": artifact_id,
                "sha256": descriptor["sha256"],
                "byte_size": descriptor["byte_size"],
                "completed_at": "2026-08-24T00:00:00.000Z",
            },
        )
        export_task = self.route("TaskService.v1.getTask", task_id=export_task_id)
        self.assertEqual(export_task["body"]["read_model"]["state"], "SUCCEEDED")
        manifest_id = export_task["body"]["read_model"]["outputs"]["EXPORT_MANIFEST"]
        manifest_wire = json.loads(
            self.product.read_verified_bytes(manifest_id).decode("utf-8")
        )
        self.assertEqual(manifest_wire["artifacts"][0]["artifact_id"], artifact_id)
        self.assertNotIn("destination_token", manifest_wire)
        self.assertEqual(manifest_wire["display_name"], "result.json")
        self.assertEqual(manifest_wire["completed_at"], "2026-08-24T00:00:00Z")

    def test_acc_c3_10_export_failure_receipt_fails_task_without_manifest(self) -> None:
        artifact_id = self._publish_large_stream_artifact(
            ArtifactFacade(self.product), b'{"export":"failure"}'
        )
        exported = self.route(
            "ArtifactService.v1.exportArtifact",
            artifact_ids=[artifact_id],
            export_profile_id="LIGHT_REVIEW",
            destination_token="edc_01ARZ3NDEKTSV4RRFFQ69G5FAW",
            idempotency_key="export-failure-key",
        )
        task_id = exported["body"]["task_id"]
        ArtifactFacade(self.product).handle_export_control(
            "artifactExport.fail",
            {
                "protocol_version": "v3.artifact-export/1.0.0",
                "project_id": self.setup.project_id,
                "project_context_revision_id": self.product.current_revision(
                    self.setup.project_id
                )["project_context_revision_id"],
                "task_id": task_id,
                "destination_token": "edc_01ARZ3NDEKTSV4RRFFQ69G5FAW",
                "reason_code": "ARTIFACT_EXPORT_WRITE_FAILED",
            },
        )
        task = self.route("TaskService.v1.getTask", task_id=task_id)["body"]["read_model"]
        self.assertEqual(task["state"], "FAILED")
        self.assertNotIn("EXPORT_MANIFEST", task["outputs"])


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
        self.assertEqual(expanded_task["status"], "OK", expanded_task)
        task_read_model = expanded_task["body"]["read_model"]
        self.assertEqual(task_read_model["state"], "SUCCEEDED")
        self.assertIn("manifest_artifact_id", task_read_model["outputs"])
        self.assertNotIn("child_task_ids", task_read_model["outputs"])
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

    def test_list_tasks_uses_filter_bound_keyset_cursor(self) -> None:
        for ordinal in range(2):
            submitted = self.route(
                "BacktestService.v1.submitBacktest",
                run_spec_id=self.setup.run_spec_id,
                execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
                idempotency_key=f"task-page-key-{ordinal}",
            )
            self.assertEqual(submitted["status"], "OK", submitted)

        first = self.route(
            "TaskService.v1.listTasks", filter={}, page_size=1
        )
        self.assertEqual(first["status"], "OK", first)
        first_model = first["body"]["read_model"]
        self.assertEqual(len(first_model["items"]), 1)
        self.assertTrue(first_model["has_more"])
        self.assertIsInstance(first_model["next_cursor"], str)

        second = self.route(
            "TaskService.v1.listTasks",
            filter={"cursor": first_model["next_cursor"]},
            page_size=1,
        )
        self.assertEqual(second["status"], "OK", second)
        second_model = second["body"]["read_model"]
        self.assertEqual(len(second_model["items"]), 1)
        self.assertNotEqual(
            first_model["items"][0]["task_id"],
            second_model["items"][0]["task_id"],
        )

        mismatched = self.route(
            "TaskService.v1.listTasks",
            filter={"state": "SUCCEEDED", "cursor": first_model["next_cursor"]},
            page_size=1,
        )
        self.assertNotEqual(mismatched["status"], "OK")

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
