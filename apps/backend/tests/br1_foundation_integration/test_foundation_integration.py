from __future__ import annotations

import hashlib
import importlib
import inspect
import pkgutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import v3_backend
from v3_backend.adapters.artifact_store.filesystem import FileSystemArtifactStore
from v3_backend.adapters.sqlite.artifact_publication import SQLiteArtifactPublicationPort
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry, canonical_bounded_json
from v3_backend.adapters.sqlite.task_persistence import SQLiteTaskPersistence
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.contracts.common.artifact_ref import ArtifactRefV1
from v3_backend.control_plane.checkpoint_manager import CheckpointManager, InMemoryCheckpointPort
from v3_backend.control_plane.event_log import CollectingPublisher, DurableEventLog
from v3_backend.control_plane.event_replay import EventReplay
from v3_backend.control_plane.task_supervisor import TaskSupervisor
from v3_backend.domain.artifacts.model import ArtifactReference
from v3_backend.domain.artifacts.publication import ArtifactPublication, publish_to_catalog
from v3_backend.domain.tasks.entities import AttemptState, RunIdentity, TaskState
from v3_backend.errors.exceptions import InvalidArgumentError
from v3_backend.migrations import apply_migrations
from v3_backend.repositories.unit_of_work import TransactionMode
from v3_backend.runtime.composition_root import RuntimePorts, build_runtime


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
NOW_WIRE = "2026-08-09T12:00:00Z"
PROJECT_ID = "prj_" + "0" * 26
REVISION_ID = "pcr_" + "0" * 26
REQUEST_ID = "01890f3c-7b5a-7000-8000-000000000001"


class DeterministicIdentities:
    prefixes = {"Task": "tsk_", "Run": "run_", "TaskAttempt": "att_", "TaskEvent": "tev_"}

    def __init__(self) -> None:
        self.value = 0

    def new(self, object_type: str) -> str:
        self.value += 1
        return self.prefixes[object_type] + str(self.value).zfill(26)


class ArtifactPublishCallbacks:
    def __init__(self, store: FileSystemArtifactStore, staging_token: str, digest: str, byte_size: int) -> None:
        self.store = store
        self.staging_token = staging_token
        self.digest = digest
        self.byte_size = byte_size
        self.result = None
        self.trace: list[str] = []

    def verify_staged(self) -> None:
        receipts = {item.staging_token: item for item in self.store.recover_staging()}
        receipt = receipts[self.staging_token]
        if (receipt.sha256, receipt.byte_size) != (self.digest, self.byte_size):
            raise AssertionError("staging receipt changed before PUBLISH")
        self.trace.append("verify")

    def publish_staged(self) -> None:
        self.result = self.store.publish(
            self.staging_token,
            expected_sha256=self.digest,
            expected_byte_size=self.byte_size,
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="pve_" + "0" * 26,
            published_at=NOW,
        )
        self.trace.append("publish")

    def compensate_unreferenced_staging(self) -> None:
        self.trace.append("compensate")
        if self.result is not None:
            self.store.delete_published_bytes(self.result.descriptor.artifact_id)
        else:
            self.store.discard_staging(
                self.staging_token,
                not_newer_than=NOW + timedelta(days=1),
                now=NOW + timedelta(days=1),
            )

    def notify_committed(self) -> None:
        self.trace.append("notify")


class FoundationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "catalog.sqlite3"
        self.artifact_root = self.root / "artifacts"
        apply_migrations(self.database_path, application_version="br1-integration-tests")
        self.store = FileSystemArtifactStore(self.artifact_root)
        self._reference_counter = 0
        self._seed_project()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _seed_project(self) -> None:
        connection = connect_catalog(self.database_path)
        try:
            with SQLiteUnitOfWork(connection) as unit:
                registry = SQLiteRepositoryRegistry(unit)
                registry.project.add_new(
                    {"project_id": PROJECT_ID, "display_name": "BR1 Integration", "created_at": NOW_WIRE, "state": "ACTIVE"}
                )
                registry.project.append_revision(
                    {
                        "project_context_revision_id": REVISION_ID,
                        "project_id": PROJECT_ID,
                        "context_json": {"project_id": PROJECT_ID},
                        "canonical_hash": hashlib.sha256(REVISION_ID.encode()).hexdigest(),
                        "created_by": "br1-integration-tests",
                        "created_at": NOW_WIRE,
                    },
                    base_revision_id=None,
                )
        finally:
            connection.close()

    def _supervisor(self) -> tuple[TaskSupervisor, SQLiteTaskPersistence, CollectingPublisher]:
        persistence = SQLiteTaskPersistence(self.database_path, clock=lambda: NOW)
        publisher = CollectingPublisher()
        supervisor = TaskSupervisor(
            DurableEventLog(persistence, publisher),
            DeterministicIdentities(),
            CheckpointManager(InMemoryCheckpointPort()),
            clock=lambda: NOW,
        )
        return supervisor, persistence, publisher

    @staticmethod
    def _run_identity() -> RunIdentity:
        return RunIdentity(
            project_context_revision_id=REVISION_ID,
            normalized_input_hash="a" * 64,
            code_version="git:br1-integration",
            environment_profile="cpu-test-v1",
            service_contract_version="1.0.0",
        )

    def _publish(self, payload: bytes, *, owner_id: str = "tsk_" + "9" * 26):
        receipt = self.store.stage_bytes(payload)
        callbacks = ArtifactPublishCallbacks(self.store, receipt.staging_token, receipt.sha256, receipt.byte_size)
        connection = connect_catalog(self.database_path)
        try:
            unit = SQLiteUnitOfWork(connection, TransactionMode.PUBLISH, publish_callbacks=callbacks)
            with unit:
                assert callbacks.result is not None
                descriptor = callbacks.result.descriptor
                self._reference_counter += 1
                reference = ArtifactReference(
                    reference_id="arf_" + str(self._reference_counter).zfill(26),
                    owner_id=owner_id,
                    artifact_id=descriptor.artifact_id,
                    role="TASK_OUTPUT",
                    created_at=NOW,
                )
                port = SQLiteArtifactPublicationPort(unit)
                publish_to_catalog(port, ArtifactPublication(descriptor, (reference,)))
                self.assertIs(type(port.registry), SQLiteRepositoryRegistry)
        finally:
            connection.close()
        return callbacks.result.descriptor, reference, callbacks.trace

    def _catalog_artifact(self, artifact_id: str) -> dict[str, object]:
        connection = connect_catalog(self.database_path, read_only=True)
        unit = SQLiteUnitOfWork(connection, TransactionMode.READ_ONLY)
        try:
            unit.begin()
            row = SQLiteRepositoryRegistry(unit).artifact.table("artifact").require(artifact_id)
            unit.commit()
            return row
        finally:
            if unit.active:
                unit.rollback()
            connection.close()

    def test_br1_x_001_artifact_ref_flows_to_artifact_descriptor(self) -> None:
        descriptor, _, _ = self._publish(b"artifact-ref-integration")
        contract_ref = ArtifactRefV1.from_wire(descriptor.to_artifact_ref())
        catalog = self._catalog_artifact(contract_ref.artifact_id)
        self.assertEqual(contract_ref.sha256, descriptor.sha256)
        self.assertEqual(contract_ref.byte_size, descriptor.byte_size)
        self.assertEqual(catalog["sha256"], contract_ref.sha256)
        self.assertEqual(catalog["storage_key"], descriptor.storage_key)

    def test_br1_x_002_publish_uow_and_artifact_boundary_use_one_catalog(self) -> None:
        descriptor, reference, trace = self._publish(b"publish-uow-integration")
        self.assertEqual(trace, ["verify", "publish", "notify"])
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            artifact_count = connection.execute(
                "SELECT COUNT(*) FROM artifact WHERE artifact_id=?", (descriptor.artifact_id,)
            ).fetchone()[0]
            reference_count = connection.execute(
                "SELECT COUNT(*) FROM artifact_reference WHERE artifact_reference_id=?", (reference.reference_id,)
            ).fetchone()[0]
            self.assertEqual((artifact_count, reference_count), (1, 1))
        finally:
            connection.close()

    def test_br1_x_003_task_run_attempt_persist_through_real_sqlite(self) -> None:
        supervisor, persistence, _ = self._supervisor()
        task, run, attempt = supervisor.accept(PROJECT_ID, "ModelService.v1.train", self._run_identity())
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            rows = (
                connection.execute("SELECT task_id FROM task WHERE task_id=?", (task.task_id,)).fetchone(),
                connection.execute("SELECT run_id FROM run WHERE run_id=?", (run.run_id,)).fetchone(),
                connection.execute("SELECT attempt_id FROM task_attempt WHERE attempt_id=?", (attempt.attempt_id,)).fetchone(),
            )
            self.assertTrue(all(row is not None for row in rows))
        finally:
            connection.close()
        self.assertEqual(persistence.read_task(task.task_id).active_run_id, run.run_id)
        self.assertEqual(persistence.latest_attempt(task.task_id).attempt_id, attempt.attempt_id)

    def test_br1_x_004_durable_event_commit_precedes_notify_and_replays(self) -> None:
        supervisor, persistence, publisher = self._supervisor()
        supervisor.accept(PROJECT_ID, "ModelService.v1.train", self._run_identity())
        self.assertEqual(persistence.trace[-4:], ["commit", "notify", "notify", "notify"])
        self.assertEqual([event.project_sequence for event in publisher.events], [1, 2, 3])
        replay = EventReplay(persistence).after(PROJECT_ID, 0)
        self.assertEqual([event.project_sequence for event in replay], [1, 2, 3])
        self.assertTrue(all(event.event_version == "1.0.0" for event in replay))

    def test_br1_x_005_runtime_dispatches_to_integrated_task_artifact_facade(self) -> None:
        supervisor, persistence, _ = self._supervisor()
        task, _, _ = supervisor.accept(PROJECT_ID, "ModelService.v1.train", self._run_identity())
        descriptor, _, _ = self._publish(b"runtime-facade-artifact", owner_id=task.task_id)
        observed: dict[str, object] = {}

        def get_task(dto: dict[str, object]) -> dict[str, object]:
            stored_task = persistence.read_task(str(dto["task_id"]))
            artifact = self._catalog_artifact(descriptor.artifact_id)
            payload = self.store.read_bytes(descriptor.artifact_id)
            observed.update(task=stored_task, artifact=artifact, payload=payload)
            return {
                "request_id": dto["request_id"],
                "truth_state": "UNAVAILABLE",
                "read_model": {"task_id": stored_task.task_id, "state": stored_task.state.value, "artifact_ref": descriptor.to_artifact_ref()},
            }

        runtime = build_runtime(
            bytes(range(32)),
            "br1-integration",
            RuntimePorts(operation_handlers={"TaskService.v1.getTask": get_task}),
        )
        response = runtime.router.route(
            {
                "kind": "request",
                "request_id": REQUEST_ID,
                "operation_id": "TaskService.v1.getTask",
                "contract_version": "1.0.0",
                "project_id": PROJECT_ID,
                "project_context_revision_id": REVISION_ID,
                "body": {
                    "request_id": REQUEST_ID,
                    "project_id": PROJECT_ID,
                    "project_context_revision_id": REVISION_ID,
                    "expected_api_version": "1.0",
                    "task_id": task.task_id,
                },
            }
        )
        self.assertEqual(response["status"], "OK")
        self.assertEqual(observed["payload"], b"runtime-facade-artifact")
        self.assertEqual(response["body"]["read_model"]["artifact_ref"]["artifact_id"], descriptor.artifact_id)

    def test_br1_x_006_restart_reopen_preserves_catalog_task_metadata(self) -> None:
        supervisor, persistence, _ = self._supervisor()
        task, _, attempt = supervisor.accept(PROJECT_ID, "ModelService.v1.train", self._run_identity())
        supervisor.assign_lease(attempt.attempt_id, "lea_" + "0" * 26)
        supervisor.transition_attempt(attempt.attempt_id, "WORKER_DISPATCHED")
        supervisor.transition_attempt(attempt.attempt_id, "WORKER_ACKNOWLEDGED")
        supervisor.mark_task_started_for_attempt(attempt.attempt_id)
        descriptor, _, _ = self._publish(b"restart-reopen", owner_id=task.task_id)
        reopened_tasks = SQLiteTaskPersistence(self.database_path, clock=lambda: NOW)
        reopened_store = FileSystemArtifactStore(self.artifact_root)
        reopened_task = reopened_tasks.read_task(task.task_id)
        reopened_attempt = reopened_tasks.latest_attempt(task.task_id)
        self.assertEqual((reopened_task.task_id, reopened_task.state), (task.task_id, TaskState.RUNNING))
        self.assertEqual(reopened_attempt.state, AttemptState.RUNNING)
        self.assertEqual(len(reopened_tasks.replay(PROJECT_ID, 0, 100)), 7)
        self.assertEqual(reopened_store.read_bytes(descriptor.artifact_id), b"restart-reopen")
        self.assertEqual(self._catalog_artifact(descriptor.artifact_id)["state"], "PUBLISHED")
        self.assertIsNot(reopened_tasks, persistence)

    def test_br1_x_007_large_payload_is_reference_only_in_catalog_transport(self) -> None:
        marker = b"BR1-LARGE-PAYLOAD-ONLY-IN-ARTIFACT-STORE\n"
        payload = marker * 30_000
        descriptor, _, _ = self._publish(payload)
        row = self._catalog_artifact(descriptor.artifact_id)
        self.assertNotIn("payload", row)
        self.assertNotIn("bytes", row)
        self.assertEqual(row["byte_size"], len(payload))
        self.assertEqual(self.store.read_bytes(descriptor.artifact_id), payload)
        with self.assertRaises(InvalidArgumentError):
            canonical_bounded_json({"raw_values": list(range(257))})

    def test_br1_x_008_unique_owners_and_no_legacy_fallback_modules(self) -> None:
        module_names = tuple(item.name for item in pkgutil.walk_packages(v3_backend.__path__, "v3_backend."))
        self.assertFalse(any("launcher" in name.lower() for name in module_names))
        self.assertFalse(any("backtest_core" in name.lower() for name in module_names))
        registry_classes: set[type[object]] = set()
        launcher_or_core_classes: set[type[object]] = set()
        for name in module_names:
            module = importlib.import_module(name)
            for _, value in inspect.getmembers(module, inspect.isclass):
                if value.__module__ != name:
                    continue
                if value.__name__.endswith("Registry"):
                    registry_classes.add(value)
                if value.__name__.endswith("Launcher") or value.__name__ == "BacktestCore":
                    launcher_or_core_classes.add(value)
        self.assertEqual(registry_classes, {SQLiteRepositoryRegistry})
        self.assertEqual(launcher_or_core_classes, set())
        runtime = build_runtime(
            bytes(range(32)),
            "br1-integration",
            RuntimePorts(operation_handlers={"TaskService.v1.getTask": lambda _: {}}),
        )
        self.assertEqual(runtime.router.bound_operation_ids, ("TaskService.v1.getTask",))


if __name__ == "__main__":
    unittest.main()
