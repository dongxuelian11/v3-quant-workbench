from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "apps" / "backend" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from v3_backend.control_plane.progress_persistence import (
    DispatchStateConflict,
    ProgressConflict,
    ProgressPersistence,
    ReceiptStateConflict,
    RuntimeResolutionConflict,
    compatibility_hash_for_context,
)
from v3_backend.migrations import apply_migrations
from v3_backend.migrations.validator import validate_schema
from v3_backend.adapters.sqlite.connection import connect_catalog


NOW = "2026-08-27T00:00:00Z"
PROJECT = "prj_" + "A" * 26
CONTEXT = "pcr_" + "A" * 26
TASK = "tsk_" + "A" * 26
RUN = "run_" + "A" * 26
ATTEMPT = "att_" + "A" * 26


def seed_task(path: Path, *, canonical_input_json: str = "{}") -> None:
    connection = connect_catalog(path)
    try:
        connection.execute(
            "INSERT INTO project(project_id,display_name,created_at,state) VALUES(?,?,?,'ACTIVE')",
            (PROJECT, "progress", NOW),
        )
        connection.execute(
            """
            INSERT INTO project_context_revision(
              project_context_revision_id,project_id,revision_no,context_json,
              canonical_hash,created_by,created_at
            ) VALUES(?,?,1,'{}',?,'test',?)
            """,
            (CONTEXT, PROJECT, "a" * 64, NOW),
        )
        connection.execute(
            """
            INSERT INTO task(
              task_id,project_id,service_name,operation_id,task_type,display_name,
              truth_state,state,created_by,created_at,updated_at
            ) VALUES(?,?,?,'TaskService.v1.test','SINGLE','progress','UNAVAILABLE','QUEUED','test',?,?)
            """,
            (TASK, PROJECT, "TaskService", NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO run(
              run_id,task_id,run_no,project_context_revision_id,canonical_input_json,
              input_hash,code_version,environment_profile_id,state,created_at
            ) VALUES(?,?,1,?,?,?,'test-code','test-env','SEALED',?)
            """,
            (RUN, TASK, CONTEXT, canonical_input_json, "b" * 64, NOW),
        )
        connection.execute(
            """
            INSERT INTO task_attempt(
              attempt_id,run_id,attempt_no,state
            ) VALUES(?,?,1,'QUEUED')
            """,
            (ATTEMPT, RUN),
        )
        connection.commit()
    finally:
        connection.close()


class ProgressPersistenceTests(unittest.TestCase):
    def test_progress_is_strict_idempotent_and_dispatch_is_cas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            result = apply_migrations(path, application_version="ws-d-progress")
            self.assertEqual(result.schema_report.user_version, 8)
            seed_task(path)
            persistence = ProgressPersistence(path)

            hold = persistence.ensure_dispatch_hold(TASK)
            self.assertEqual(hold.state, "HOLD")
            with self.assertRaises(DispatchStateConflict):
                persistence.transition_dispatch(
                    TASK, expected_state="HOLD", new_state="READY"
                )
            ready = persistence.transition_dispatch(
                TASK,
                expected_state="HOLD",
                new_state="READY",
                user_confirmed_at=datetime.now(timezone.utc),
            )
            self.assertEqual(ready.state, "READY")

            connection = connect_catalog(path)
            try:
                connection.execute(
                    "UPDATE task_dispatch_control SET state='HOLD',hold_reason='TEST',user_confirmed_at=NULL,state_version=0 WHERE task_id=?",
                    (TASK,),
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(DispatchStateConflict):
                persistence.transition_dispatch(
                    TASK,
                    expected_state="HOLD",
                    new_state="READY",
                    user_confirmed_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
                )
            ready = persistence.transition_dispatch(
                TASK,
                expected_state="HOLD",
                new_state="READY",
                user_confirmed_at=datetime.now(timezone.utc),
            )
            self.assertEqual(ready.state, "READY")
            with self.assertRaises(DispatchStateConflict):
                persistence.transition_dispatch(
                    TASK, expected_state="HOLD", new_state="DISPATCHED"
                )
            dispatched = persistence.mark_dispatched(TASK)
            self.assertEqual(dispatched.state, "DISPATCHED")
            self.assertEqual(dispatched.state_version, 2)
            self.assertEqual(persistence.mark_dispatched(TASK), dispatched)
            same_state = persistence.transition_dispatch(
                TASK, expected_state="DISPATCHED", new_state="DISPATCHED"
            )
            self.assertEqual(same_state, dispatched)

            first = persistence.record_progress(
                ATTEMPT,
                phase="COMPUTING",
                completed_units=1,
                total_units=3,
                work_unit="rows",
                counters={"rows": 10},
                sequence=1,
            )
            duplicate = persistence.record_progress(
                ATTEMPT,
                phase="COMPUTING",
                completed_units=1,
                total_units=3,
                work_unit="rows",
                counters={"rows": 10},
                sequence=1,
            )
            self.assertEqual(first, duplicate)
            with self.assertRaises(ProgressConflict):
                persistence.record_progress(
                    ATTEMPT,
                    phase="COMPUTING",
                    completed_units=2,
                    total_units=3,
                    work_unit="rows",
                    counters={"rows": 10},
                    sequence=1,
                )
            with self.assertRaises(ProgressConflict):
                persistence.record_progress(
                    ATTEMPT,
                    phase="COMPUTING",
                    completed_units=3,
                    total_units=3,
                    work_unit="rows",
                    counters={},
                    sequence=3,
                )
            second = persistence.record_progress(
                ATTEMPT,
                phase="PUBLISHING",
                completed_units=3,
                total_units=3,
                work_unit="receipt",
                counters={"rows": 10},
            )
            self.assertEqual(second.sequence, 2)
            self.assertEqual([item.sequence for item in persistence.progress_timeline(ATTEMPT)], [1, 2])

            connection = connect_catalog(path, read_only=True)
            try:
                row = connection.execute(
                    "SELECT progress_sequence,last_progress_at FROM task_attempt WHERE attempt_id=?",
                    (ATTEMPT,),
                ).fetchone()
                self.assertEqual(int(row[0]), 2)
                self.assertTrue(row[1])
                event = connection.execute(
                    "SELECT payload_json FROM task_event WHERE attempt_id=? ORDER BY project_sequence DESC LIMIT 1",
                    (ATTEMPT,),
                ).fetchone()
                self.assertEqual(json.loads(str(event[0]))["sequence"], 2)
            finally:
                connection.close()

    def test_progress_stall_is_idempotent_and_records_one_control_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            apply_migrations(path, application_version="ws-d-stall")
            seed_task(path)
            persistence = ProgressPersistence(path)

            self.assertTrue(persistence.mark_progress_stalled(ATTEMPT))
            self.assertFalse(persistence.mark_progress_stalled(ATTEMPT))

            connection = connect_catalog(path, read_only=True)
            try:
                interruption = connection.execute(
                    "SELECT interruption_reason FROM task_attempt WHERE attempt_id=?",
                    (ATTEMPT,),
                ).fetchone()
                self.assertEqual(str(interruption[0]), "PROGRESS_STALLED")
                events = connection.execute(
                    "SELECT event_type,payload_json FROM task_event WHERE attempt_id=? AND event_type='PROGRESS_STALLED'",
                    (ATTEMPT,),
                ).fetchall()
                self.assertEqual(len(events), 1)
                self.assertEqual(json.loads(str(events[0][1])), {"reason_code": "PROGRESS_STALLED"})
            finally:
                connection.close()

    def test_progress_read_rejects_noncanonical_counter_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            apply_migrations(path, application_version="ws-d-progress-read-boundary")
            seed_task(path)
            persistence = ProgressPersistence(path)
            persistence.record_progress(
                ATTEMPT,
                phase="COMPUTING",
                completed_units=1,
                total_units=2,
                work_unit="rows",
                counters={"rows": 10},
                sequence=1,
            )

            for tampered in (
                "1",
                '{"rows":10,"rows":10}',
                ' {"rows":10}',
            ):
                connection = connect_catalog(path)
                try:
                    connection.execute(
                        "UPDATE attempt_progress SET counters_json=? WHERE attempt_id=? AND sequence=1",
                        (tampered, ATTEMPT),
                    )
                    connection.commit()
                finally:
                    connection.close()
                with self.subTest(tampered=tampered):
                    with self.assertRaisesRegex(ProgressConflict, "progress"):
                        persistence.latest_progress(ATTEMPT)

    def test_execution_context_reads_durable_run_input_and_deadlines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            apply_migrations(path, application_version="ws-d-context")
            seed_task(path, canonical_input_json='{"semantic":{"rows":3}}')
            connection = connect_catalog(path)
            try:
                connection.execute(
                    "UPDATE run SET operation_schema_version=?,resource_policy_version=? WHERE run_id=?",
                    ("op-schema/1", "policy/1", RUN),
                )
                connection.execute(
                    "UPDATE task SET execution_deadline_at=? WHERE task_id=?",
                    ("2026-08-27T01:02:03Z", TASK),
                )
                connection.execute(
                    "UPDATE task_attempt SET execution_deadline_at=? WHERE attempt_id=?",
                    ("2026-08-27T01:02:03Z", ATTEMPT),
                )
                connection.commit()
            finally:
                connection.close()

            context = ProgressPersistence(path).execution_context_for_attempt(ATTEMPT)
            self.assertEqual(context["canonical_input"], {"semantic": {"rows": 3}})
            self.assertEqual(context["operation_schema_version"], "op-schema/1")
            self.assertEqual(context["task_deadline_at"], "2026-08-27T01:02:03Z")
            self.assertEqual(context["attempt_deadline_at"], "2026-08-27T01:02:03Z")

    def test_generation_and_receipt_finality_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            apply_migrations(path, application_version="ws-d-receipt")
            seed_task(path)
            persistence = ProgressPersistence(path)
            persistence.create_generation("rgen_" + "A" * 26, process_identity_hash="c" * 64)
            connection = connect_catalog(path)
            try:
                connection.execute(
                    "UPDATE task_attempt SET runtime_generation_id=? WHERE attempt_id=?",
                    ("rgen_" + "A" * 26, ATTEMPT),
                )
                connection.commit()
            finally:
                connection.close()
            receipt = persistence.create_receipt(
                operation_receipt_id="opr_" + "A" * 26,
                correlation_id="corr-progress",
                operation_id="TaskService.v1.test",
                project_id=PROJECT,
                deadline_at=datetime(2026, 8, 27, 1, tzinfo=timezone.utc),
                runtime_generation_id="rgen_" + "A" * 26,
                task_id=TASK,
                run_id=RUN,
                attempt_id=ATTEMPT,
            )
            self.assertEqual(receipt.state, "ACCEPTED")
            running = persistence.transition_receipt(
                receipt.operation_receipt_id,
                expected_state="ACCEPTED",
                new_state="RUNNING",
            )
            with self.assertRaisesRegex(ValueError, "receipt outcome must be a JSON object"):
                persistence.transition_receipt(
                    receipt.operation_receipt_id,
                    expected_state="RUNNING",
                    new_state="COMMITTED",
                    outcome=[["task_id", TASK]],
                    commit_boundary_at=datetime.now(timezone.utc),
                )
            self.assertEqual(
                persistence.receipt(receipt.operation_receipt_id).state,
                "RUNNING",
            )
            committed = persistence.transition_receipt(
                receipt.operation_receipt_id,
                expected_state="RUNNING",
                new_state="COMMITTED",
                outcome={"task_id": TASK},
                commit_boundary_at=datetime.now(timezone.utc),
            )
            self.assertEqual(committed.state, "COMMITTED")
            with self.assertRaises(ReceiptStateConflict):
                persistence.transition_receipt(
                    receipt.operation_receipt_id,
                    expected_state="COMMITTED",
                    new_state="FAILED",
                    error_code="DEADLINE_EXCEEDED_PRE_COMMIT",
                )
            succeeded = persistence.transition_receipt(
                receipt.operation_receipt_id,
                expected_state="COMMITTED",
                new_state="SUCCEEDED",
            )
            self.assertEqual(succeeded.state, "SUCCEEDED")
            self.assertEqual(json.loads(str(succeeded.outcome_json))["task_id"], TASK)
            persistence.close_generation("rgen_" + "A" * 26)
            self.assertIsNotNone(persistence.receipt("opr_" + "A" * 26).terminal_at)

    def test_progress_can_be_committed_inside_the_task_terminal_uow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            apply_migrations(path, application_version="ws-d-progress-uow")
            seed_task(path)
            persistence = ProgressPersistence(path)
            connection = connect_catalog(path)
            try:
                connection.execute("BEGIN IMMEDIATE")
                record = persistence.record_progress_in_transaction(
                    connection,
                    ATTEMPT,
                    phase="PUBLISHED",
                    completed_units=3,
                    total_units=3,
                    work_unit="pipeline_phases",
                    counters={"canonical_terminal": 1},
                )
                connection.commit()
            finally:
                connection.close()
            self.assertEqual(record.phase, "PUBLISHED")
            self.assertEqual(
                [item.phase for item in persistence.progress_timeline(ATTEMPT)],
                ["PUBLISHED"],
            )

    def test_receipt_rejects_cross_context_identity_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            apply_migrations(path, application_version="ws-d-receipt-binding")
            seed_task(path)
            persistence = ProgressPersistence(path)
            with self.assertRaises(RuntimeResolutionConflict):
                persistence.create_receipt(
                    operation_receipt_id="opr_" + "B" * 26,
                    correlation_id="corr-binding",
                    operation_id="OtherService.v1.operation",
                    project_id=PROJECT,
                    deadline_at=datetime(2026, 8, 27, 1, tzinfo=timezone.utc),
                    task_id=TASK,
                    run_id=RUN,
                    attempt_id=ATTEMPT,
                )

    def test_rebind_rejects_a_closed_runtime_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            apply_migrations(path, application_version="ws-d-closed-generation")
            seed_task(path)
            persistence = ProgressPersistence(path)
            closed_generation = "rgen_closed_" + "D" * 26
            persistence.create_generation(
                closed_generation,
                process_identity_hash="e" * 64,
            )
            persistence.close_generation(closed_generation)
            persistence.ensure_dispatch_hold(TASK)

            connection = connect_catalog(path)
            try:
                connection.execute("BEGIN IMMEDIATE")
                with self.assertRaises(RuntimeResolutionConflict):
                    persistence.rebind_queued_attempt_generation_in_transaction(
                        connection,
                        ATTEMPT,
                        runtime_generation_id=closed_generation,
                    )
                connection.rollback()
            finally:
                connection.close()

            connection = connect_catalog(path, read_only=True)
            try:
                row = connection.execute(
                    "SELECT runtime_generation_id FROM task_attempt WHERE attempt_id=?",
                    (ATTEMPT,),
                ).fetchone()
            finally:
                connection.close()
            self.assertIsNone(row[0])

    def test_receipt_rejects_noncanonical_or_unpublished_artifact_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            apply_migrations(path, application_version="ws-d-receipt-artifact")
            seed_task(path)
            persistence = ProgressPersistence(path)
            persistence.create_receipt(
                operation_receipt_id="opr_" + "C" * 26,
                correlation_id="corr-artifact",
                operation_id="TaskService.v1.test",
                project_id=PROJECT,
                deadline_at=datetime(2026, 8, 27, 1, tzinfo=timezone.utc),
                task_id=TASK,
                run_id=RUN,
                attempt_id=ATTEMPT,
            )
            persistence.transition_receipt(
                "opr_" + "C" * 26,
                expected_state="ACCEPTED",
                new_state="RUNNING",
            )
            with self.assertRaises(ValueError):
                persistence.transition_receipt(
                    "opr_" + "C" * 26,
                    expected_state="RUNNING",
                    new_state="COMMITTED",
                    outcome_artifact_id="art_sha256_" + "a" * 63,
                    commit_boundary_at=datetime.now(timezone.utc),
                )

            staged_artifact_id = "art_sha256_" + "d" * 64
            connection = connect_catalog(path)
            try:
                connection.execute(
                    """
                    INSERT INTO artifact(
                      artifact_id,sha256,byte_size,media_type,semantic_role,
                      storage_key,safe_format_id,schema_fingerprint,state,
                      created_at,published_at,deleted_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL)
                    """,
                    (
                        staged_artifact_id,
                        "d" * 64,
                        1,
                        "application/octet-stream",
                        "TEST_STAGED_OUTCOME",
                        "sha256/" + "d" * 64,
                        None,
                        None,
                        "STAGED",
                        NOW,
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, "PUBLISHED Artifact"):
                persistence.transition_receipt(
                    "opr_" + "C" * 26,
                    expected_state="RUNNING",
                    new_state="COMMITTED",
                    outcome_artifact_id=staged_artifact_id,
                    commit_boundary_at=datetime.now(timezone.utc),
                )

            foreign_project = "prj_" + "B" * 26
            foreign_artifact_id = "art_sha256_" + "e" * 64
            local_artifact_id = "art_sha256_" + "f" * 64
            connection = connect_catalog(path)
            try:
                connection.execute(
                    "INSERT INTO project(project_id,display_name,created_at,state) VALUES(?,?,?,'ACTIVE')",
                    (foreign_project, "foreign", NOW),
                )
                for artifact_id, digest in (
                    (foreign_artifact_id, "e" * 64),
                    (local_artifact_id, "f" * 64),
                ):
                    connection.execute(
                        """
                        INSERT INTO artifact(
                          artifact_id,sha256,byte_size,media_type,semantic_role,
                          storage_key,safe_format_id,schema_fingerprint,state,
                          created_at,published_at,deleted_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL)
                        """,
                        (
                            artifact_id,
                            digest,
                            1,
                            "application/octet-stream",
                            "TEST_PUBLISHED_OUTCOME",
                            "sha256/" + digest,
                            None,
                            None,
                            "PUBLISHED",
                            NOW,
                            NOW,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO artifact_reference(
                      artifact_reference_id,owner_type,owner_id,role,artifact_id,
                      state,created_at
                    ) VALUES(?,?,?,?,?,'ACTIVE',?)
                    """,
                    (
                        "arf_" + "E" * 26,
                        "Project",
                        foreign_project,
                        "TEST_FOREIGN_OUTCOME",
                        foreign_artifact_id,
                        NOW,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO artifact_reference(
                      artifact_reference_id,owner_type,owner_id,role,artifact_id,
                      state,created_at
                    ) VALUES(?,?,?,?,?,'ACTIVE',?)
                    """,
                    (
                        "arf_" + "F" * 26,
                        "Project",
                        PROJECT,
                        "TEST_LOCAL_OUTCOME",
                        local_artifact_id,
                        NOW,
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaisesRegex(ValueError, "project-reachable"):
                persistence.transition_receipt(
                    "opr_" + "C" * 26,
                    expected_state="RUNNING",
                    new_state="COMMITTED",
                    outcome_artifact_id=foreign_artifact_id,
                    commit_boundary_at=datetime.now(timezone.utc),
                )
            committed = persistence.transition_receipt(
                "opr_" + "C" * 26,
                expected_state="RUNNING",
                new_state="COMMITTED",
                outcome_artifact_id=local_artifact_id,
                commit_boundary_at=datetime.now(timezone.utc),
            )
            self.assertEqual(committed.state, "COMMITTED")

    def test_runtime_resolution_rejects_noncanonical_json_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            apply_migrations(path, application_version="ws-d-resolution-json")
            seed_task(path)
            persistence = ProgressPersistence(path)
            resolved_json = '{"a": 1}'
            resolved_hash = hashlib.sha256(resolved_json.encode("utf-8")).hexdigest()
            compatibility_hash = compatibility_hash_for_context(
                input_hash="b" * 64,
                code_version="test-code",
                environment_profile="test-env",
                operation_id="TaskService.v1.test",
                operation_schema_version="1.0.0",
                resource_policy_version="test-policy",
                resolved_resource_hash=resolved_hash,
            )
            with self.assertRaises(ValueError):
                persistence.bind_runtime_resolution(
                    run_id=RUN,
                    attempt_id=ATTEMPT,
                    operation_schema_version="1.0.0",
                    resource_policy_version="test-policy",
                    resolved_resource_json=resolved_json,
                    resolved_resource_hash=resolved_hash,
                    compatibility_hash=compatibility_hash,
                    runtime_generation_id=None,
                )


if __name__ == "__main__":
    unittest.main()
