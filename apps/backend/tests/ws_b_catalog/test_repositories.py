from __future__ import annotations

import sqlite3

from v3_backend.adapters.sqlite.repositories import canonical_bounded_json
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.errors.exceptions import ConflictError, InvalidArgumentError
from v3_backend.repositories.unit_of_work import TransactionMode

from .support import NOW, CatalogTestCase


class RepositoryTests(CatalogTestCase):
    def test_project_revision_is_append_only_and_optimistic(self) -> None:
        with SQLiteUnitOfWork(self.connection) as unit:
            repositories = self.registry(unit)
            self.add_project(repositories)
            first = self.append_context(repositories)
            second = self.append_context(
                repositories,
                revision_id="pcr_test_2",
                base_revision_id=first["project_context_revision_id"],
            )
            self.assertEqual(second["revision_no"], 2)
            with self.assertRaises(ConflictError):
                self.append_context(
                    repositories,
                    revision_id="pcr_test_stale",
                    base_revision_id=first["project_context_revision_id"],
                )
            updated = repositories.project.save(
                "prj_test", {"display_name": "Renamed"}, expected_version=0
            )
            self.assertEqual(updated["row_version"], 1)
            with self.assertRaises(ConflictError):
                repositories.project.save(
                    "prj_test", {"display_name": "Stale"}, expected_version=0
                )
        with self.assertRaises(sqlite3.IntegrityError):
            with SQLiteUnitOfWork(self.connection):
                self.connection.execute(
                    "UPDATE project_context_revision SET created_by='mutated' WHERE project_context_revision_id='pcr_test_1'"
                )

    def test_alias_overlap_rejected_and_as_of_resolution(self) -> None:
        with SQLiteUnitOfWork(self.connection) as unit:
            repositories = self.registry(unit)
            artifact = self.publish_artifact(repositories)
            repositories.connector.table("connector").add_new(
                {
                    "connector_id": "con_test",
                    "stable_name": "test",
                    "publisher": "V3",
                    "state": "REGISTERED",
                    "created_at": NOW,
                }
            )
            repositories.connector.table("connector_version").add_new(
                {
                    "connector_version_id": "cov_test",
                    "connector_id": "con_test",
                    "semantic_version": "1.0.0",
                    "bundle_artifact_id": artifact["artifact_id"],
                    "bundle_sha256": artifact["sha256"],
                    "entrypoint": "test:main",
                    "declared_manifest_json": {},
                    "network_policy": "DENY",
                    "state": "ADMITTED",
                    "created_at": NOW,
                }
            )
            repositories.instrument.table("instrument").add_new(
                {
                    "instrument_id": "ins_test",
                    "asset_class": "CN_A_SHARE",
                    "exchange": "SZSE",
                    "listing_date": "2000-01-01",
                    "state": "ACTIVE",
                    "created_at": NOW,
                }
            )
            base = {
                "instrument_alias_id": "ial_test_1",
                "instrument_id": "ins_test",
                "connector_version_id": "cov_test",
                "provider_code": "000001.SZ",
                "effective_from": "2020-01-01",
                "effective_to": "2024-01-01",
                "available_time": NOW,
                "evidence_artifact_id": artifact["artifact_id"],
                "created_at": NOW,
            }
            repositories.instrument.add_alias(base)
            resolved = repositories.instrument.resolve_alias(
                "cov_test", "000001.SZ", "2023-01-01"
            )
            self.assertEqual(resolved["instrument_id"], "ins_test")
            with self.assertRaises(ConflictError):
                repositories.instrument.add_alias(
                    {
                        **base,
                        "instrument_alias_id": "ial_test_2",
                        "effective_from": "2023-01-01",
                        "effective_to": None,
                    }
                )

    def test_task_run_attempt_event_creation_and_ordered_replay(self) -> None:
        with SQLiteUnitOfWork(self.connection) as unit:
            repositories = self.registry(unit)
            self.add_project(repositories)
            revision = self.append_context(repositories)
            task, run = repositories.task.create_task_and_run(
                {
                    "task_id": "tsk_test",
                    "project_id": "prj_test",
                    "service_name": "TaskService",
                    "operation_id": "task.create",
                    "task_type": "TEST",
                    "display_name": "Test task",
                    "truth_state": "FORMAL",
                    "state": "QUEUED",
                    "created_by": "test",
                    "created_at": NOW,
                    "updated_at": NOW,
                },
                {
                    "run_id": "run_test",
                    "task_id": "tsk_test",
                    "run_no": 1,
                    "project_context_revision_id": revision["project_context_revision_id"],
                    "canonical_input_json": {"x": 1},
                    "input_hash": "1" * 64,
                    "code_version": "test",
                    "environment_profile_id": "env_test",
                    "state": "SEALED",
                    "created_at": NOW,
                },
            )
            attempt = repositories.task.create_attempt(
                {
                    "attempt_id": "att_test",
                    "run_id": run["run_id"],
                    "attempt_no": 1,
                    "state": "QUEUED",
                }
            )
            for index in range(2):
                event = repositories.task.append_event(
                    {
                        "task_event_id": f"tev_test_{index}",
                        "project_id": task["project_id"],
                        "task_id": task["task_id"],
                        "run_id": run["run_id"],
                        "attempt_id": attempt["attempt_id"],
                        "event_type": "TEST_EVENT",
                        "payload_json": {"index": index},
                        "occurred_at": NOW,
                        "persisted_at": NOW,
                    },
                    expected_stream_sequence=index,
                )
                self.assertEqual(event["project_sequence"], index + 1)
            replay = repositories.task.list_replay("prj_test")
            self.assertEqual([row["project_sequence"] for row in replay], [1, 2])
            with self.assertRaises(ConflictError):
                repositories.task.append_event(
                    {
                        "task_event_id": "tev_stale",
                        "project_id": "prj_test",
                        "task_id": "tsk_test",
                        "event_type": "STALE",
                        "payload_json": {},
                        "occurred_at": NOW,
                        "persisted_at": NOW,
                    },
                    expected_stream_sequence=0,
                )

    def test_artifact_reference_reachability_metadata(self) -> None:
        with SQLiteUnitOfWork(self.connection) as unit:
            repositories = self.registry(unit)
            artifact = self.publish_artifact(repositories)
            reference = repositories.artifact.add_reference(
                {
                    "artifact_reference_id": "arf_test",
                    "owner_type": "PROJECT",
                    "owner_id": "prj_test",
                    "role": "EVIDENCE",
                    "artifact_id": artifact["artifact_id"],
                    "state": "ACTIVE",
                    "created_at": NOW,
                }
            )
            self.assertIn(artifact["artifact_id"], repositories.artifact.reachable_set())
            repositories.artifact.release_reference(
                reference["artifact_reference_id"], released_at=NOW
            )
            self.assertNotIn(artifact["artifact_id"], repositories.artifact.reachable_set())

    def test_large_and_numeric_json_rejected(self) -> None:
        with self.assertRaises(InvalidArgumentError):
            canonical_bounded_json({"series": list(range(257))})
        with self.assertRaises(InvalidArgumentError):
            canonical_bounded_json({"text": "x" * (64 * 1024)})
        with SQLiteUnitOfWork(self.connection) as unit:
            repositories = self.registry(unit)
            self.add_project(repositories)
            with self.assertRaises(InvalidArgumentError):
                repositories.factor.table("factor_definition").add_new(
                    {
                        "factor_definition_id": "fad_test",
                        "project_id": "prj_test",
                        "stable_name": "too-large",
                        "definition_json": {"series": list(range(257))},
                        "created_at": NOW,
                    }
                )
        with self.assertRaises(sqlite3.IntegrityError):
            with SQLiteUnitOfWork(self.connection):
                self.connection.execute(
                    """
                    INSERT INTO factor_definition(
                      factor_definition_id, project_id, stable_name, definition_json, created_at
                    ) VALUES(?,?,?,?,?)
                    """,
                    ("fad_direct", "prj_test", "direct", '{"x":"' + "z" * 65536 + '"}', NOW),
                )

    def test_read_only_uow_rejects_writes(self) -> None:
        with SQLiteUnitOfWork(self.connection, TransactionMode.READ_ONLY) as unit:
            with self.assertRaises(RuntimeError):
                self.add_project(self.registry(unit), "prj_forbidden")
