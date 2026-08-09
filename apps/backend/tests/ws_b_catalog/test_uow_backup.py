from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from v3_backend.adapters.sqlite.backup import backup_database, restore_database
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.migrations import validate_schema
from v3_backend.repositories.unit_of_work import TransactionMode

from .support import CatalogTestCase


@dataclass
class FakePublishCallbacks:
    calls: list[str] = field(default_factory=list)

    def verify_staged(self) -> None:
        self.calls.append("verify")

    def publish_staged(self) -> None:
        self.calls.append("publish")

    def compensate_unreferenced_staging(self) -> None:
        self.calls.append("compensate")

    def notify_committed(self) -> None:
        self.calls.append("notify")


class UnitOfWorkAndBackupTests(CatalogTestCase):
    def test_commit_and_rollback(self) -> None:
        with SQLiteUnitOfWork(self.connection) as unit:
            self.add_project(self.registry(unit), "prj_committed")
        with self.assertRaises(RuntimeError):
            with SQLiteUnitOfWork(self.connection) as unit:
                self.add_project(self.registry(unit), "prj_rolled_back")
                raise RuntimeError("rollback")
        with SQLiteUnitOfWork(self.connection, TransactionMode.READ_ONLY) as unit:
            projects = self.registry(unit).project.table("project")
            self.assertIsNotNone(projects.get("prj_committed"))
            self.assertIsNone(projects.get("prj_rolled_back"))

    def test_publish_transaction_surface_orders_callbacks(self) -> None:
        callbacks = FakePublishCallbacks()
        with SQLiteUnitOfWork(
            self.connection, TransactionMode.PUBLISH, publish_callbacks=callbacks
        ) as unit:
            self.add_project(self.registry(unit), "prj_publish")
            self.assertEqual(callbacks.calls, ["verify", "publish"])
        self.assertEqual(callbacks.calls, ["verify", "publish", "notify"])

        failed = FakePublishCallbacks()
        with self.assertRaises(RuntimeError):
            with SQLiteUnitOfWork(
                self.connection, TransactionMode.PUBLISH, publish_callbacks=failed
            ):
                raise RuntimeError("metadata failure")
        self.assertEqual(failed.calls, ["verify", "publish", "compensate"])

    def test_backup_restore_roundtrip_and_restart(self) -> None:
        with SQLiteUnitOfWork(self.connection) as unit:
            self.add_project(self.registry(unit), "prj_persisted")
        self.connection.close()
        backup = self.root / "backup.sqlite3"
        restored = self.root / "restored.sqlite3"
        evidence = backup_database(self.database_path, backup)
        self.assertEqual(evidence.byte_size, backup.stat().st_size)
        restored_evidence = restore_database(backup, restored)
        self.assertGreater(restored_evidence.byte_size, 0)
        connection = connect_catalog(restored)
        try:
            validate_schema(connection)
            self.assertEqual(
                connection.execute(
                    "SELECT display_name FROM project WHERE project_id='prj_persisted'"
                ).fetchone()[0],
                "Test Project",
            )
        finally:
            connection.close()
        self.connection = connect_catalog(self.database_path)

    def test_restore_refuses_existing_destination(self) -> None:
        self.connection.close()
        backup = self.root / "backup.sqlite3"
        backup_database(self.database_path, backup)
        with self.assertRaises(FileExistsError):
            restore_database(backup, self.database_path)
        self.connection = connect_catalog(self.database_path)
