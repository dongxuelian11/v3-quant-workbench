"""Focused V1 Runtime Integrity regression tests."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.domain.tasks.events import PendingTaskEvent
from v3_backend.domain.tasks.retry_policy import ErrorCategory, RetryPolicy
from v3_backend.errors.exceptions import InvalidArgumentError
from v3_backend.runtime.composition_root import RequestRouter
from v3_backend.runtime.product_entry import _decode_files
from v3_backend.runtime.product_runtime import (
    ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
    BUILD_MANIFEST,
    PRODUCT_CODE_VERSION,
    ProductRuntime,
    build_product_ports,
    build_product_runtime,
    mint_v3_id,
    mint_uuid7,
)
from v3_backend.transport_contract import (
    MAX_FRAME_BYTES,
    MAX_PACKAGE_FILE_BASE64_CHARS,
    MAX_PACKAGE_FILE_BYTES,
    MAX_PACKAGE_FILE_COUNT,
    MAX_PACKAGE_TOTAL_BYTES,
    PACKAGE_ENVELOPE_OVERHEAD_BYTES,
    PACKAGE_FRAME_SAFETY_MARGIN_BYTES,
)

from .helpers import build_product_golden_project


class BuildManifestAndTransportTests(unittest.TestCase):
    def test_build_manifest_identity_is_stable_and_commit_bound(self) -> None:
        base = replace(
            BUILD_MANIFEST,
            schema_version="v3.build-manifest/1.0.0",
            build_manifest_id="bmanifest_sha256_" + "0" * 64,
            git_commit_sha="a" * 40,
            git_tree_sha="b" * 40,
            dirty_state="CLEAN",
            package_identity={"name": "test", "version": "1"},
            package_lock_sha256="c" * 64,
            backend_dependency_authority={"authority_sha256": "d" * 64},
            contract_schema_migration_levels={"migration_set_sha256": "e" * 64},
            generated_at="2026-08-20T00:00:00Z",
        )
        same_source_later = replace(base, generated_at="2026-08-20T00:00:01Z")
        different_commit = replace(base, git_commit_sha="f" * 40)

        self.assertEqual(base.stable_payload(), same_source_later.stable_payload())
        self.assertNotEqual(base.to_wire(), same_source_later.to_wire())

        def stable_identity(manifest) -> str:
            payload = json.dumps(
                manifest.stable_payload(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            return hashlib.sha256(payload).hexdigest()

        self.assertEqual(stable_identity(base), stable_identity(same_source_later))
        self.assertNotEqual(stable_identity(base), stable_identity(different_commit))
        self.assertEqual(PRODUCT_CODE_VERSION, BUILD_MANIFEST.code_version)
        self.assertIn(BUILD_MANIFEST.dirty_state, {"CLEAN", "DIRTY", "UNKNOWN"})

    def test_shared_package_bound_fits_frame_and_safe_max_plus_one_is_rejected(self) -> None:
        self.assertEqual(MAX_PACKAGE_TOTAL_BYTES, 688_128)
        self.assertEqual(
            MAX_PACKAGE_TOTAL_BYTES,
            ((MAX_FRAME_BYTES - PACKAGE_ENVELOPE_OVERHEAD_BYTES - PACKAGE_FRAME_SAFETY_MARGIN_BYTES) * 3) // 4,
        )
        self.assertEqual(
            MAX_PACKAGE_FILE_BASE64_CHARS,
            ((MAX_PACKAGE_FILE_BYTES + 2) // 3) * 4,
        )
        self.assertLess(
            ((MAX_PACKAGE_TOTAL_BYTES + 2) // 3) * 4 + PACKAGE_ENVELOPE_OVERHEAD_BYTES,
            MAX_FRAME_BYTES,
        )
        self.assertLessEqual(MAX_PACKAGE_FILE_COUNT, 64)

        def package_file(name: str, size: int) -> dict[str, object]:
            payload = b"x" * size
            return {
                "name": name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "byte_size": size,
                "payload_base64": base64.b64encode(payload).decode("ascii"),
            }

        exact = [
            package_file("spec.a.bin", 229_376),
            package_file("context.b.bin", 229_376),
            package_file("target.c.bin", 229_376),
        ]
        decoded = _decode_files(exact)
        self.assertEqual(sum(item.byte_size for item in decoded.values()), MAX_PACKAGE_TOTAL_BYTES)

        over = [
            package_file("spec.a.bin", 229_377),
            package_file("context.b.bin", 229_376),
            package_file("target.c.bin", 229_376),
        ]
        with self.assertRaisesRegex(InvalidArgumentError, "total transfer size"):
            _decode_files(over)


class TaskResultTruthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.temporary.name)
        self.setup = build_product_golden_project(self.storage_root)
        self.product = build_product_runtime(self.storage_root)
        self.router = RequestRouter(build_product_ports(self.storage_root).operation_handlers)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def route(self, operation_id: str, **body_fields):
        project_id = body_fields.pop("_project_id", self.setup.project_id)
        revision_id = body_fields.pop("_pcr_id", self.setup.project_context_revision_id)
        request_id = mint_uuid7()
        body = {
            "request_id": request_id,
            "project_id": project_id,
            "project_context_revision_id": revision_id,
            "expected_api_version": "1.0",
            **body_fields,
        }
        return self.router.route(
            {
                "kind": "request",
                "request_id": request_id,
                "operation_id": operation_id,
                "contract_version": "1.0",
                "project_id": project_id,
                "project_context_revision_id": revision_id,
                "body": body,
            }
        )

    def submit(self, key: str) -> dict:
        return self.route(
            "BacktestService.v1.submitBacktest",
            run_spec_id=self.setup.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key=key,
        )

    def test_task_a_b_relation_ignores_more_than_500_unrelated_events(self) -> None:
        accepted_a = self.submit("integrity-a")
        accepted_b = self.submit("integrity-b")
        task_a = accepted_a["body"]["task_id"]
        task_b = accepted_b["body"]["task_id"]
        run_a = accepted_a["body"]["run_id"]
        run_b = accepted_b["body"]["run_id"]
        result_a = self.route("TaskService.v1.getTask", task_id=task_a)["body"]["read_model"]["result_id"]
        result_b = self.route("TaskService.v1.getTask", task_id=task_b)["body"]["read_model"]["result_id"]
        self.assertIsInstance(result_a, str)
        self.assertIsInstance(result_b, str)
        self.assertNotEqual(result_a, result_b)

        with self.product.task_persistence.begin() as unit:
            for index in range(600):
                unit.append_event(
                    PendingTaskEvent(
                        event_id=mint_v3_id("tev_"),
                        event_version="1.0.0",
                        project_id=self.setup.project_id,
                        task_id=task_b,
                        event_type="UNRELATED_HISTORY_NOISE",
                        occurred_at=datetime.now(timezone.utc),
                        payload={"index": index},
                        run_id=run_b,
                    )
                )
            unit.commit()

        task_a_after_history = self.route("TaskService.v1.getTask", task_id=task_a)
        self.assertEqual(
            task_a_after_history["body"]["read_model"]["result_id"],
            result_a,
        )
        result_a_view = self.route(
            "ResultService.v1.getResult",
            result_id=result_a,
            section="summary",
            page={},
        )
        result_b_view = self.route(
            "ResultService.v1.getResult",
            result_id=result_b,
            section="summary",
            page={},
        )
        self.assertEqual(result_a_view["body"]["read_model"]["backtest_run_id"], run_a)
        self.assertEqual(result_b_view["body"]["read_model"]["backtest_run_id"], run_b)

    def test_task_result_missing_cross_project_and_malformed_fail_closed(self) -> None:
        task, _, _ = self.product.execution._create_task(
            operation_id="BacktestService.v1.submitBacktest",
            project_id=self.setup.project_id,
            project_context_revision_id=self.setup.project_context_revision_id,
            normalized_input_hash="1" * 64,
            context_artifact_id=None,
        )
        missing_relation = self.route("TaskService.v1.getTask", task_id=task.task_id)
        self.assertEqual(missing_relation["status"], "OK", missing_relation)
        self.assertIsNone(missing_relation["body"]["read_model"]["result_id"])

        missing_result = self.route(
            "ResultService.v1.getResult",
            result_id=mint_v3_id("res_"),
            section="summary",
            page={},
        )
        self.assertEqual(missing_result["status"], "ERROR", missing_result)

        malformed = self.route("TaskService.v1.getTask", task_id="not-a-task-id")
        self.assertEqual(malformed["status"], "ERROR", malformed)

        accepted = self.submit("integrity-cross-project")
        result_id = self.route(
            "TaskService.v1.getTask", task_id=accepted["body"]["task_id"]
        )["body"]["read_model"]["result_id"]
        wrong_project = self.route(
            "ResultService.v1.getResult",
            _project_id="prj_" + "A" * 26,
            result_id=result_id,
            section="summary",
            page={},
        )
        self.assertEqual(wrong_project["status"], "ERROR", wrong_project)


class WorkerTerminalTruthTests(unittest.TestCase):
    def test_failure_stops_worker_and_releases_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            setup = build_product_golden_project(Path(tmp))
            product = ProductRuntime(tmp)
            task, run, attempt = product.execution._create_task(
                operation_id="BacktestService.v1.submitBacktest",
                project_id=setup.project_id,
                project_context_revision_id=setup.project_context_revision_id,
                normalized_input_hash="2" * 64,
                context_artifact_id=None,
            )
            product.execution._transition_to_running(task, run, attempt)
            product.execution._finish_failure(
                task,
                run,
                attempt,
                error=ValueError("focused failure"),
                category=ErrorCategory.INVALID_ARGUMENT,
            )
            connection = product._connection(read_only=True)
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
            self.assertEqual(
                dict(row),
                {
                    "task_state": "FAILED",
                    "run_state": "TERMINAL",
                    "attempt_state": "FAILED",
                    "lease_state": "RELEASED",
                    "worker_state": "STOPPED",
                },
            )
            self.assertTrue(RetryPolicy().decide(ErrorCategory.TRANSIENT_IO, 1).allowed)
            self.assertFalse(RetryPolicy().decide(ErrorCategory.INVALID_ARGUMENT, 1).allowed)


if __name__ == "__main__":
    unittest.main()
