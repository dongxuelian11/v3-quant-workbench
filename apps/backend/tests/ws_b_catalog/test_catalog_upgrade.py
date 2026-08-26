from __future__ import annotations

import hashlib
import io
import json
import multiprocessing
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest.mock import patch

from v3_backend.adapters.sqlite.backup import (
    atomic_replace_database,
    copy_database_file_exact,
)
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.errors.exceptions import (
    CatalogMigrationPrefixUnrecognizedError,
    CatalogUpgradeIntegrityError,
)
from v3_backend.migrations import discover_migrations
from v3_backend.migrations.runner import _apply_one
from v3_backend.migrations.upgrade import (
    _catalog_upgrade_lock,
    catalog_runtime_lease,
    upgrade_catalog,
)
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_runtime import (
    ProductRuntime,
    build_product_ports,
    mint_uuid7,
)
from v3_backend.runtime.request_router import RequestRouter
from v3_backend.runtime import bootstrap as runtime_bootstrap


def _hold_catalog_runtime_lease(
    catalog_path: str,
    ready: Any,
    release: Any,
) -> None:
    with catalog_runtime_lease(Path(catalog_path), busy_timeout_ms=1_000):
        ready.set()
        release.wait(10)


class CatalogUpgradeAndSessionIsolationTests(unittest.TestCase):
    def _create_exact_v5_catalog(self, root: Path) -> Path:
        source = (
            Path(__file__).parents[2]
            / "src"
            / "v3_backend"
            / "migrations"
            / "versions"
        )
        v5_versions = root / "v5-versions"
        v5_versions.mkdir()
        for name in (
            "0001_control_catalog.sql",
            "0002_data_truth.sql",
            "0003_portfolio_riskpolicy_owner.sql",
            "0004_risk_application_publication.sql",
            "0005_task_execution_deadline.sql",
        ):
            (v5_versions / name).write_bytes((source / name).read_bytes())

        catalog = root / "catalog.sqlite3"
        connection = sqlite3.connect(catalog, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            for migration in discover_migrations(v5_versions):
                _apply_one(
                    connection,
                    migration,
                    application_version="exact-v1.1-prefix",
                    backup=None,
                )
        finally:
            connection.close()
        return catalog

    @staticmethod
    def _route(
        router: RequestRouter,
        operation_id: str,
        *,
        project_id: str,
        project_context_revision_id: str,
        **fields: object,
    ) -> dict[str, object]:
        request_id = mint_uuid7()
        body = {
            "request_id": request_id,
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "expected_api_version": "1.0",
            **fields,
        }
        return router.route(
            {
                "kind": "request",
                "request_id": request_id,
                "operation_id": operation_id,
                "contract_version": "1.0",
                "project_id": project_id,
                "project_context_revision_id": project_context_revision_id,
                "body": body,
            }
        )

    @staticmethod
    def _catalog_snapshot(catalog: Path) -> tuple[str, tuple[tuple[object, ...], ...]]:
        connection = connect_catalog(catalog)
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            sessions = tuple(
                tuple(row)
                for row in connection.execute(
                    "SELECT * FROM desktop_session ORDER BY session_id"
                )
            )
        finally:
            connection.close()
        return hashlib.sha256(catalog.read_bytes()).hexdigest(), sessions

    def test_catalog_upgrade_lock_refuses_a_second_concurrent_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.sqlite3"
            with _catalog_upgrade_lock(catalog, busy_timeout_ms=100):
                with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                    with _catalog_upgrade_lock(catalog, busy_timeout_ms=0):
                        self.fail("a second upgrade owner entered the critical section")
            self.assertEqual(raised.exception.details["phase"], "UPGRADE_LOCK")

    def test_catalog_upgrade_waits_for_live_worker_runtime_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.sqlite3"
            context = multiprocessing.get_context("spawn")
            ready = context.Event()
            release = context.Event()
            worker = context.Process(
                target=_hold_catalog_runtime_lease,
                args=(str(catalog), ready, release),
            )
            worker.start()
            try:
                self.assertTrue(ready.wait(10), "worker did not publish its Catalog lease")
                with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                    upgrade_catalog(
                        catalog,
                        application_version="runtime-lease-test",
                        backup_dir=Path(directory) / "backups",
                        busy_timeout_ms=100,
                    )
                self.assertEqual(raised.exception.details["phase"], "RUNTIME_LEASE")
            finally:
                release.set()
                worker.join(10)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
            self.assertEqual(worker.exitcode, 0)
            upgraded = upgrade_catalog(
                catalog,
                application_version="runtime-lease-test-after-release",
                backup_dir=Path(directory) / "backups",
                busy_timeout_ms=1_000,
            )
            self.assertEqual(upgraded.receipt.result, "NO_CHANGE")

    def test_fresh_catalog_migration_failure_maps_to_stable_startup_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.sqlite3"
            versions_dir = Path(directory) / "broken-versions"
            versions_dir.mkdir()
            source = (
                Path(__file__).parents[2]
                / "src"
                / "v3_backend"
                / "migrations"
                / "versions"
                / "0001_control_catalog.sql"
            )
            (versions_dir / source.name).write_bytes(
                source.read_bytes()
                + b"\nCREATE TABLE migration_failure_probe(id INTEGER);\n"
                + b"CREATE TABLE migration_failure_probe(id INTEGER);\n"
            )
            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="fresh-error-mapping",
                    versions_dir=versions_dir,
                    backup_dir=Path(directory) / "backups",
                )
            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
            )

    def test_fresh_non_utf8_migration_maps_to_stable_startup_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.sqlite3"
            versions_dir = root / "non-utf8-versions"
            versions_dir.mkdir()
            source = (
                Path(__file__).parents[2]
                / "src"
                / "v3_backend"
                / "migrations"
                / "versions"
                / "0001_control_catalog.sql"
            )
            (versions_dir / source.name).write_bytes(source.read_bytes() + b"\xff")

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="fresh-non-utf8-error-mapping",
                    versions_dir=versions_dir,
                    backup_dir=root / "backups",
                )

            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
            )

    def test_fresh_catalog_migration_discovery_failure_maps_to_stable_startup_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.sqlite3"
            versions_dir = root / "broken-order-versions"
            versions_dir.mkdir()
            source = (
                Path(__file__).parents[2]
                / "src"
                / "v3_backend"
                / "migrations"
                / "versions"
                / "0001_control_catalog.sql"
            )
            (versions_dir / source.name).write_bytes(source.read_bytes())
            (versions_dir / "0003_broken_order.sql").write_bytes(
                source.read_bytes()
            )

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="fresh-discovery-error-mapping",
                    versions_dir=versions_dir,
                    backup_dir=root / "backups",
                )

            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
            )
            self.assertEqual(raised.exception.details["phase"], "MIGRATION_DISCOVERY")

    def test_staged_migration_read_failure_maps_to_stable_startup_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            versions_dir = root / "staged-read-failure-versions"
            versions_dir.mkdir()
            for migration in discover_migrations():
                (versions_dir / migration.path.name).write_bytes(
                    migration.path.read_bytes()
                )

            def make_migration_unreadable(phase: str) -> None:
                if phase != "AFTER_SOURCE_ADMISSION_BEFORE_BACKUP":
                    return
                migration_path = versions_dir / "0006_catalog_upgrade_session_integrity.sql"
                migration_path.unlink()
                migration_path.mkdir()

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="staged-read-error-mapping",
                    versions_dir=versions_dir,
                    backup_dir=root / "backups",
                    fault_hook=make_migration_unreadable,
                )

            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
            )

    def test_staged_non_utf8_migration_maps_to_stable_startup_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            versions_dir = root / "staged-non-utf8-versions"
            versions_dir.mkdir()
            for migration in discover_migrations():
                (versions_dir / migration.path.name).write_bytes(
                    migration.path.read_bytes()
                )
            migration_path = versions_dir / "0006_catalog_upgrade_session_integrity.sql"
            migration_path.write_bytes(migration_path.read_bytes() + b"\xff")

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="staged-non-utf8-error-mapping",
                    versions_dir=versions_dir,
                    backup_dir=root / "backups",
                )

            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
            )

    def test_missing_catalog_upgrade_receipt_column_is_rejected_before_row_reads(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.sqlite3"
            upgrade_catalog(
                catalog,
                application_version="receipt-shape-test",
                backup_dir=root / "backups",
            )
            connection = sqlite3.connect(catalog, isolation_level=None)
            try:
                connection.execute("DROP TABLE catalog_upgrade_receipt")
                connection.execute(
                    "CREATE TABLE catalog_upgrade_receipt(operation_id TEXT PRIMARY KEY)"
                )
            finally:
                connection.close()

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="receipt-shape-restart",
                    backup_dir=root / "backups",
                )

            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
            )
            self.assertIn("exact schema/integrity validation", str(raised.exception))

    def test_tampered_persisted_receipt_is_rejected_on_next_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.sqlite3"
            upgrade_catalog(
                catalog,
                application_version="receipt-integrity-test",
                backup_dir=Path(directory) / "backups",
            )
            connection = sqlite3.connect(catalog, isolation_level=None)
            try:
                connection.execute("PRAGMA ignore_check_constraints = ON")
                connection.execute(
                    "UPDATE catalog_upgrade_receipt SET final_catalog_sha256=?",
                    ("Z" * 64,),
                )
            finally:
                connection.close()
            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="receipt-integrity-test-restart",
                    backup_dir=Path(directory) / "backups",
                )
            self.assertIn("receipt final_catalog_sha256", str(raised.exception))

    def test_persisted_receipt_prefixes_must_match_the_admitted_migration_chain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.sqlite3"
            upgrade_catalog(
                catalog,
                application_version="receipt-prefix-chain-test",
                backup_dir=root / "backups",
            )
            connection = sqlite3.connect(catalog, isolation_level=None)
            try:
                connection.execute("PRAGMA ignore_check_constraints = ON")
                connection.execute(
                    "UPDATE catalog_upgrade_receipt SET target_schema_prefix_json=?",
                    ("[]",),
                )
            finally:
                connection.close()

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="receipt-prefix-chain-restart",
                    backup_dir=root / "backups",
                )
            self.assertIn("not an admitted chain", str(raised.exception))

    def test_catalog_startup_errors_cross_bootstrap_as_stable_redacted_diagnostics(
        self,
    ) -> None:
        cases = (
            (
                CatalogMigrationPrefixUnrecognizedError("private prefix path detail"),
                "CATALOG_MIGRATION_PREFIX_UNRECOGNIZED",
                "Catalog migration prefix is not admitted",
            ),
            (
                CatalogUpgradeIntegrityError("private integrity path detail"),
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
                "Catalog upgrade integrity verification failed",
            ),
        )
        for error, code, message in cases:
            with self.subTest(code=code):
                stderr = io.StringIO()
                with (
                    patch.object(runtime_bootstrap, "read_supervisor_token", return_value="token"),
                    patch.object(runtime_bootstrap, "_build_ports", side_effect=error),
                    redirect_stderr(stderr),
                ):
                    result = runtime_bootstrap.main(["--transport", "stdio-framed-v1"])
                self.assertEqual(result, 3)
                diagnostic = json.loads(stderr.getvalue())
                self.assertEqual(
                    diagnostic,
                    {"level": "ERROR", "code": code, "message": message},
                )
                self.assertNotIn("private", stderr.getvalue())

    def test_v5_staged_upgrade_refreshes_same_project_and_rejects_cross_project_without_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            v5_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            product = ProductRuntime(root)
            connection = connect_catalog(catalog, read_only=True)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)
                applied = tuple(
                    str(row[0])
                    for row in connection.execute(
                        "SELECT migration_id FROM schema_migration ORDER BY migration_id"
                    )
                )
                self.assertEqual(applied[-1], "0006_catalog_upgrade_session_integrity")
                receipt = connection.execute(
                    "SELECT * FROM catalog_upgrade_receipt"
                ).fetchone()
            finally:
                connection.close()
            self.assertIsNotNone(receipt)
            self.assertEqual(str(receipt["source_catalog_sha256"]), v5_sha256)
            self.assertEqual(str(receipt["result"]), "UPGRADED")
            self.assertTrue(str(receipt["operation_id"]).startswith("cup_"))
            self.assertEqual(str(receipt["integrity_check"]), "PASS")
            self.assertEqual(str(receipt["foreign_key_check"]), "PASS")
            self.assertEqual(
                str(receipt["replacement_mode"]),
                "SAME_VOLUME_ATOMIC_REPLACE",
            )
            self.assertEqual(
                str(receipt["final_catalog_sha256"]),
                str(receipt["staged_sha256_before_replace"]),
            )
            migrations = discover_migrations()
            self.assertEqual(
                json.loads(str(receipt["source_schema_prefix_json"])),
                [[item.migration_id, item.checksum_sha256] for item in migrations[:5]],
            )
            self.assertEqual(
                json.loads(str(receipt["target_schema_prefix_json"])),
                [[item.migration_id, item.checksum_sha256] for item in migrations],
            )
            backups = tuple((root / "backups").glob("catalog-before-upgrade-*.sqlite3"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                hashlib.sha256(backups[0].read_bytes()).hexdigest(),
                str(receipt["backup_sha256"]),
            )

            project_a = create_project(
                product,
                display_name="项目 A",
                idempotency_key="catalog-upgrade-project-a",
            )
            project_b = create_project(
                product,
                display_name="项目 B",
                idempotency_key="catalog-upgrade-project-b",
            )
            router = RequestRouter(build_product_ports(root).operation_handlers)
            session_id = mint_uuid7()

            opened = self._route(
                router,
                "ProjectSessionService.v1.openProject",
                project_id=project_a["project_id"],
                project_context_revision_id=project_a["project_context_revision_id"],
                project_locator=f"v3:{project_a['project_id']}",
                session_id=session_id,
            )
            self.assertEqual(opened["status"], "OK", opened)

            revised = self._route(
                router,
                "ProjectSessionService.v1.reviseProjectContext",
                project_id=project_a["project_id"],
                project_context_revision_id=project_a["project_context_revision_id"],
                base_revision_id=project_a["project_context_revision_id"],
                patch={"context_fields": {"notes": "revision two"}},
                idempotency_key="catalog-upgrade-revision-a2",
            )
            self.assertEqual(revised["status"], "OK", revised)
            revised_context_id = revised["body"]["read_model"][
                "project_context_revision_id"
            ]
            reopened = self._route(
                router,
                "ProjectSessionService.v1.openProject",
                project_id=project_a["project_id"],
                project_context_revision_id=revised_context_id,
                project_locator=f"v3:{project_a['project_id']}",
                session_id=session_id,
            )
            self.assertEqual(reopened["status"], "OK", reopened)

            before_hash, before_rows = self._catalog_snapshot(catalog)
            conflict = self._route(
                router,
                "ProjectSessionService.v1.openProject",
                project_id=project_b["project_id"],
                project_context_revision_id=project_b["project_context_revision_id"],
                project_locator=f"v3:{project_b['project_id']}",
                session_id=session_id,
            )
            self.assertEqual(conflict["status"], "ERROR", conflict)
            self.assertEqual(
                conflict["error"]["code"], "SESSION_PROJECT_BINDING_CONFLICT"
            )
            after_hash, after_rows = self._catalog_snapshot(catalog)
            self.assertEqual(after_rows, before_rows)
            self.assertEqual(after_hash, before_hash)

    def test_restart_recovers_upgrade_after_replace_before_receipt(self) -> None:
        class SimulatedProcessCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            def crash_after_replace(phase: str) -> None:
                if phase == "AFTER_REPLACE_BEFORE_RECEIPT":
                    raise SimulatedProcessCrash()

            with self.assertRaises(SimulatedProcessCrash):
                upgrade_catalog(
                    catalog,
                    application_version="crash-window-test",
                    backup_dir=root / "backups",
                    fault_hook=crash_after_replace,
                )

            replaced = connect_catalog(catalog, read_only=True)
            try:
                self.assertEqual(replaced.execute("PRAGMA user_version").fetchone()[0], 6)
                self.assertEqual(
                    replaced.execute("SELECT COUNT(*) FROM catalog_upgrade_receipt").fetchone()[0],
                    0,
                )
            finally:
                replaced.close()

            state_path = root / ".catalog.sqlite3.upgrade-state.v1.json"
            legacy_state = json.loads(state_path.read_text(encoding="utf-8"))
            legacy_state["schema_id"] = "urn:v3:catalog-upgrade-state:1.0.0"
            legacy_state.pop("staged_content_sha256")
            state_path.write_text(
                json.dumps(legacy_state, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            ProductRuntime(root)
            recovered = connect_catalog(catalog, read_only=True)
            try:
                receipts = recovered.execute(
                    """
                    SELECT source_catalog_sha256,result,recovery_action
                    FROM catalog_upgrade_receipt ORDER BY committed_at,operation_id
                    """
                ).fetchall()
            finally:
                recovered.close()
            self.assertEqual(len(receipts), 1)
            self.assertEqual(str(receipts[0]["source_catalog_sha256"]), source_sha256)
            self.assertEqual(str(receipts[0]["result"]), "UPGRADED")
            self.assertEqual(str(receipts[0]["recovery_action"]), "NONE")
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())

    def test_restart_resumes_verified_stage_before_replace(self) -> None:
        class SimulatedProcessCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            def crash_before_replace(phase: str) -> None:
                if phase == "AFTER_STAGE_STATE_BEFORE_REPLACE":
                    raise SimulatedProcessCrash()

            with self.assertRaises(SimulatedProcessCrash):
                upgrade_catalog(
                    catalog,
                    application_version="crash-window-test",
                    backup_dir=root / "backups",
                    fault_hook=crash_before_replace,
                )
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            self.assertTrue((root / ".catalog.sqlite3.upgrade-state.v1.json").is_file())

            ProductRuntime(root)
            recovered = connect_catalog(catalog, read_only=True)
            try:
                self.assertEqual(recovered.execute("PRAGMA user_version").fetchone()[0], 6)
                receipt = recovered.execute(
                    "SELECT source_catalog_sha256,result FROM catalog_upgrade_receipt"
                ).fetchone()
            finally:
                recovered.close()
            self.assertEqual(str(receipt["source_catalog_sha256"]), source_sha256)
            self.assertEqual(str(receipt["result"]), "UPGRADED")
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())

    def test_restart_promotes_fsynced_pending_state_before_recovery(self) -> None:
        class SimulatedProcessCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            state_path = root / ".catalog.sqlite3.upgrade-state.v1.json"

            def crash_before_state_activation(source: Path, destination: Path) -> None:
                if destination == state_path:
                    raise SimulatedProcessCrash()
                from v3_backend.adapters.sqlite.backup import durable_replace_file

                durable_replace_file(source, destination)

            with patch(
                "v3_backend.migrations.upgrade.durable_replace_file",
                side_effect=crash_before_state_activation,
            ):
                with self.assertRaises(SimulatedProcessCrash):
                    upgrade_catalog(
                        catalog,
                        application_version="pending-state-crash-test",
                        backup_dir=root / "backups",
                    )

            self.assertFalse(state_path.exists())
            self.assertTrue(state_path.with_name(state_path.name + ".pending").is_file())
            recovered = upgrade_catalog(
                catalog,
                application_version="pending-state-recovery-test",
                backup_dir=root / "backups",
            )
            self.assertEqual(recovered.receipt.result, "UPGRADED")
            self.assertFalse(state_path.exists())
            self.assertFalse(state_path.with_name(state_path.name + ".pending").exists())

    def test_post_replace_validation_failure_restores_exact_source_and_archives_rollback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            def corrupt_replacement(phase: str) -> None:
                if phase != "AFTER_REPLACE_BEFORE_RECEIPT":
                    return
                connection = sqlite3.connect(catalog)
                try:
                    connection.execute("DROP TABLE desktop_session")
                    connection.commit()
                finally:
                    connection.close()

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="post-replace-validation-test",
                    backup_dir=root / "backups",
                    fault_hook=corrupt_replacement,
                )
            self.assertEqual(
                raised.exception.code.value, "CATALOG_UPGRADE_INTEGRITY_FAILED"
            )
            self.assertEqual(
                raised.exception.details["recovery_action"], "RESTORED_BACKUP"
            )
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            restored = sqlite3.connect(catalog)
            try:
                self.assertEqual(restored.execute("PRAGMA user_version").fetchone()[0], 5)
                self.assertEqual(str(restored.execute("PRAGMA integrity_check").fetchone()[0]), "ok")
                self.assertEqual(tuple(restored.execute("PRAGMA foreign_key_check")), ())
            finally:
                restored.close()
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())
            rollback_receipts = tuple(
                (root / "backups").glob("catalog-upgrade-rollback-*.json")
            )
            self.assertEqual(len(rollback_receipts), 1)
            self.assertTrue(any(root.glob(".catalog.sqlite3.failed-upgrade-*")))

    def test_rollback_receipt_write_failure_maps_to_stable_recovery_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            def fail_rollback_receipt_write(
                source: Path,
                destination: Path,
            ) -> None:
                if destination.name.startswith("catalog-upgrade-rollback-"):
                    raise OSError("simulated rollback receipt write failure")
                from v3_backend.adapters.sqlite.backup import durable_replace_file

                durable_replace_file(source, destination)

            def corrupt_replacement(phase: str) -> None:
                if phase != "AFTER_REPLACE_BEFORE_RECEIPT":
                    return
                connection = sqlite3.connect(catalog)
                try:
                    connection.execute("DROP TABLE desktop_session")
                    connection.commit()
                finally:
                    connection.close()

            with patch(
                "v3_backend.migrations.upgrade.durable_replace_file",
                side_effect=fail_rollback_receipt_write,
            ):
                with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                    upgrade_catalog(
                        catalog,
                        application_version="rollback-receipt-error-mapping",
                        backup_dir=root / "backups",
                        fault_hook=corrupt_replacement,
                    )

            self.assertEqual(raised.exception.details["phase"], "ROLLBACK_RECEIPT")
            self.assertEqual(
                raised.exception.details["recovery_action"],
                "STOP_FOR_REVIEW",
            )
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            self.assertTrue((root / ".catalog.sqlite3.upgrade-state.v1.json").is_file())
            self.assertTrue(tuple(root.glob(".catalog.sqlite3.failed-upgrade-*")))

    def test_exact_copy_adopts_a_complete_staging_file_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sqlite3"
            destination = root / "destination.sqlite3"
            source.write_bytes(b"admitted-catalog-bytes")
            destination.with_name(destination.name + ".staging").write_bytes(
                source.read_bytes()
            )

            evidence = copy_database_file_exact(source, destination)

            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertEqual(evidence.byte_size, len(b"admitted-catalog-bytes"))
            self.assertFalse(
                destination.with_name(destination.name + ".staging").exists()
            )

    def test_post_replace_unreadable_bytes_still_restore_the_exact_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            def corrupt_replacement_bytes(phase: str) -> None:
                if phase == "AFTER_REPLACE_BEFORE_RECEIPT":
                    catalog.write_bytes(b"not-a-sqlite-database")

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="post-replace-unreadable-test",
                    backup_dir=root / "backups",
                    fault_hook=corrupt_replacement_bytes,
                )
            self.assertEqual(
                raised.exception.details["recovery_action"],
                "RESTORED_BACKUP",
            )
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            restored = sqlite3.connect(catalog)
            try:
                self.assertEqual(restored.execute("PRAGMA user_version").fetchone()[0], 5)
                self.assertEqual(str(restored.execute("PRAGMA integrity_check").fetchone()[0]), "ok")
            finally:
                restored.close()
            failed = tuple(root.glob(".catalog.sqlite3.failed-upgrade-*"))
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0].read_bytes(), b"not-a-sqlite-database")

    def test_post_replace_failure_with_unverified_backup_stops_before_isolation(self) -> None:
        for tamper_mode in ("MISSING", "MODIFIED"):
            with self.subTest(tamper_mode=tamper_mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                catalog = self._create_exact_v5_catalog(root)

                def tamper_backup_and_corrupt_replacement(phase: str) -> None:
                    if phase != "AFTER_REPLACE_BEFORE_RECEIPT":
                        return
                    backup = next((root / "backups").glob("catalog-before-upgrade-*.sqlite3"))
                    if tamper_mode == "MISSING":
                        backup.unlink()
                    else:
                        backup.write_bytes(b"tampered backup bytes")
                    connection = sqlite3.connect(catalog)
                    try:
                        connection.execute("DROP TABLE desktop_session")
                        connection.commit()
                    finally:
                        connection.close()

                with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                    upgrade_catalog(
                        catalog,
                        application_version="unverified-rollback-backup-test",
                        backup_dir=root / "backups",
                        fault_hook=tamper_backup_and_corrupt_replacement,
                    )
                self.assertEqual(
                    raised.exception.details["phase"],
                    "ROLLBACK_BACKUP_EVIDENCE",
                )
                self.assertEqual(
                    raised.exception.details["recovery_action"],
                    "STOP_FOR_REVIEW",
                )
                self.assertTrue(catalog.is_file())
                self.assertTrue((root / ".catalog.sqlite3.upgrade-state.v1.json").is_file())
                self.assertFalse(tuple(root.glob(".catalog.sqlite3.failed-upgrade-*")))
                self.assertFalse(tuple((root / "backups").glob("catalog-upgrade-rollback-*.json")))

    def test_rollback_activation_failure_preserves_failed_and_restore_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            replace_calls = 0

            def fail_rollback_activation(source: Path, destination: Path) -> None:
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise OSError("simulated rollback activation failure")
                atomic_replace_database(source, destination)

            def corrupt_replacement(phase: str) -> None:
                if phase != "AFTER_REPLACE_BEFORE_RECEIPT":
                    return
                connection = sqlite3.connect(catalog)
                try:
                    connection.execute("DROP TABLE desktop_session")
                    connection.commit()
                finally:
                    connection.close()

            with patch(
                "v3_backend.migrations.upgrade.atomic_replace_database",
                side_effect=fail_rollback_activation,
            ):
                with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                    upgrade_catalog(
                        catalog,
                        application_version="rollback-activation-failure-test",
                        backup_dir=root / "backups",
                        fault_hook=corrupt_replacement,
                    )
            self.assertEqual(raised.exception.details["phase"], "ROLLBACK_RESTORE")
            self.assertEqual(
                raised.exception.details["recovery_action"],
                "STOP_FOR_REVIEW",
            )
            self.assertTrue((root / ".catalog.sqlite3.upgrade-state.v1.json").is_file())
            self.assertTrue(tuple(root.glob(".catalog.sqlite3.failed-upgrade-*")))
            self.assertTrue(tuple(root.glob(".catalog.sqlite3.restore-*.staged")))

    def test_restart_completes_interrupted_rollback_without_missing_catalog(self) -> None:
        class SimulatedProcessCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()
            replace_calls = 0

            def crash_during_rollback_activation(
                source: Path, destination: Path
            ) -> None:
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise SimulatedProcessCrash()
                atomic_replace_database(source, destination)

            def corrupt_replacement(phase: str) -> None:
                if phase != "AFTER_REPLACE_BEFORE_RECEIPT":
                    return
                connection = sqlite3.connect(catalog)
                try:
                    connection.execute("DROP TABLE desktop_session")
                    connection.commit()
                finally:
                    connection.close()

            with patch(
                "v3_backend.migrations.upgrade.atomic_replace_database",
                side_effect=crash_during_rollback_activation,
            ):
                with self.assertRaises(SimulatedProcessCrash):
                    upgrade_catalog(
                        catalog,
                        application_version="rollback-crash-test",
                        backup_dir=root / "backups",
                        fault_hook=corrupt_replacement,
                    )

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="rollback-crash-recovery-test",
                    backup_dir=root / "backups",
                )
            self.assertEqual(
                raised.exception.details["recovery_action"],
                "RESTORED_BACKUP",
            )
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())
            self.assertTrue(tuple(root.glob(".catalog.sqlite3.failed-upgrade-*")))
            self.assertTrue(tuple((root / "backups").glob("catalog-upgrade-rollback-*.json")))

    def test_restart_deduplicates_committed_receipt_before_state_cleanup(self) -> None:
        class SimulatedProcessCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)

            def crash_after_receipt(phase: str) -> None:
                if phase == "AFTER_RECEIPT_BEFORE_STATE_CLEANUP":
                    raise SimulatedProcessCrash()

            with self.assertRaises(SimulatedProcessCrash):
                upgrade_catalog(
                    catalog,
                    application_version="receipt-cleanup-crash-test",
                    backup_dir=root / "backups",
                    fault_hook=crash_after_receipt,
                )
            before_restart = connect_catalog(catalog, read_only=True)
            try:
                operation_ids = tuple(
                    str(row[0])
                    for row in before_restart.execute(
                        "SELECT operation_id FROM catalog_upgrade_receipt"
                    )
                )
            finally:
                before_restart.close()
            self.assertEqual(len(operation_ids), 1)
            state_path = root / ".catalog.sqlite3.upgrade-state.v1.json"
            self.assertTrue(state_path.is_file())

            exact_state = state_path.read_text(encoding="utf-8")
            conflicting_state = json.loads(exact_state)
            conflicting_state["started_at"] = "2000-01-01T00:00:00.000000Z"
            state_path.write_text(
                json.dumps(conflicting_state, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CatalogUpgradeIntegrityError,
                "receipt conflicts with durable upgrade state",
            ):
                upgrade_catalog(
                    catalog,
                    application_version="receipt-state-conflict-test",
                    backup_dir=root / "backups",
                )
            self.assertTrue(state_path.is_file())
            legacy_state = json.loads(exact_state)
            legacy_state["schema_id"] = "urn:v3:catalog-upgrade-state:1.0.0"
            legacy_state.pop("staged_content_sha256")
            state_path.write_text(
                json.dumps(legacy_state, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CatalogUpgradeIntegrityError,
                "legacy Catalog upgrade state cannot reconcile",
            ) as legacy_raised:
                upgrade_catalog(
                    catalog,
                    application_version="legacy-receipt-state-test",
                    backup_dir=root / "backups",
                )
            self.assertEqual(
                legacy_raised.exception.details["phase"],
                "POST_RECEIPT_RECONCILIATION",
            )
            self.assertEqual(
                legacy_raised.exception.details["recovery_action"],
                "STOP_FOR_REVIEW",
            )
            self.assertTrue(state_path.is_file())
            state_path.write_text(exact_state, encoding="utf-8")

            recovered = upgrade_catalog(
                catalog,
                application_version="receipt-cleanup-recovery-test",
                backup_dir=root / "backups",
            )
            after_restart = connect_catalog(catalog, read_only=True)
            try:
                recovered_rows = tuple(
                    after_restart.execute(
                        "SELECT operation_id,committed_at FROM catalog_upgrade_receipt"
                    )
                )
            finally:
                after_restart.close()
            self.assertEqual(
                tuple(str(row["operation_id"]) for row in recovered_rows),
                operation_ids,
            )
            self.assertEqual(
                recovered.receipt.committed_at,
                str(recovered_rows[0]["committed_at"]),
                "recovery must return the exact durable receipt rather than a reconstructed timestamp",
            )
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())

    def test_receipt_commit_state_cleanup_failure_maps_to_stable_integrity_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            state_path = root / ".catalog.sqlite3.upgrade-state.v1.json"

            def replace_state_with_directory(phase: str) -> None:
                if phase != "AFTER_RECEIPT_BEFORE_STATE_CLEANUP":
                    return
                state_path.unlink()
                state_path.mkdir()

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="receipt-cleanup-error-mapping",
                    backup_dir=root / "backups",
                    fault_hook=replace_state_with_directory,
                )

            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
            )
            self.assertEqual(
                raised.exception.details["phase"],
                "POST_RECEIPT_STATE_CLEANUP",
            )
            self.assertEqual(
                raised.exception.details["recovery_action"],
                "STOP_FOR_REVIEW",
            )
            connection = connect_catalog(catalog, read_only=True)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM catalog_upgrade_receipt"
                    ).fetchone()[0],
                    1,
                )
            finally:
                connection.close()
            self.assertTrue(state_path.is_dir())

    def test_post_receipt_catalog_drift_stops_before_state_cleanup(self) -> None:
        class SimulatedProcessCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)

            def drift_after_receipt(phase: str) -> None:
                if phase == "AFTER_RECEIPT_BEFORE_STATE_CLEANUP":
                    connection = sqlite3.connect(catalog)
                    try:
                        connection.execute(
                            """
                            UPDATE schema_migration
                            SET application_version=?
                            WHERE migration_id=?
                            """,
                            (
                                "post-receipt-external-drift",
                                "0006_catalog_upgrade_session_integrity",
                            ),
                        )
                        connection.commit()
                    finally:
                        connection.close()
                    raise SimulatedProcessCrash()

            with self.assertRaises(SimulatedProcessCrash):
                upgrade_catalog(
                    catalog,
                    application_version="post-receipt-drift-test",
                    backup_dir=root / "backups",
                    fault_hook=drift_after_receipt,
                )

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="post-receipt-drift-recovery-test",
                    backup_dir=root / "backups",
                )
            self.assertEqual(
                raised.exception.details["phase"],
                "POST_RECEIPT_RECONCILIATION",
            )
            self.assertEqual(
                raised.exception.details["recovery_action"],
                "STOP_FOR_REVIEW",
            )
            self.assertTrue((root / ".catalog.sqlite3.upgrade-state.v1.json").is_file())

    def test_fresh_install_and_reopen_each_emit_a_non_conflicting_no_change_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ProductRuntime(root)
            first = connect_catalog(root / "catalog.sqlite3", read_only=True)
            try:
                first_receipts = first.execute(
                    "SELECT operation_id,result FROM catalog_upgrade_receipt"
                ).fetchall()
            finally:
                first.close()
            self.assertEqual(len(first_receipts), 1)
            self.assertEqual(str(first_receipts[0]["result"]), "NO_CHANGE")

            ProductRuntime(root)
            reopened = connect_catalog(root / "catalog.sqlite3", read_only=True)
            try:
                reopened_receipts = reopened.execute(
                    "SELECT operation_id,result FROM catalog_upgrade_receipt ORDER BY operation_id"
                ).fetchall()
            finally:
                reopened.close()
            self.assertEqual(len(reopened_receipts), 2)
            self.assertEqual(
                {str(row["result"]) for row in reopened_receipts}, {"NO_CHANGE"}
            )
            self.assertEqual(
                len({str(row["operation_id"]) for row in reopened_receipts}), 2
            )

    def test_checksum_drift_is_refused_before_any_catalog_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            connection = sqlite3.connect(catalog)
            try:
                connection.execute(
                    "UPDATE schema_migration SET checksum_sha256=? WHERE migration_id=?",
                    ("0" * 64, "0005_task_execution_deadline"),
                )
                connection.commit()
            finally:
                connection.close()
            before_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            with self.assertRaises(CatalogMigrationPrefixUnrecognizedError) as raised:
                ProductRuntime(root)
            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_MIGRATION_PREFIX_UNRECOGNIZED",
            )
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), before_sha256)
            self.assertFalse((root / "backups").exists())
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())

    def test_source_byte_drift_after_admission_is_refused_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            admitted_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()
            def change_source_before_backup(phase: str) -> None:
                if phase == "AFTER_SOURCE_ADMISSION_BEFORE_BACKUP":
                    connection = sqlite3.connect(catalog)
                    try:
                        connection.execute(
                            "UPDATE schema_migration SET application_version=? WHERE migration_id=?",
                            ("external-writer-after-admission", "0005_task_execution_deadline"),
                        )
                        connection.commit()
                    finally:
                        connection.close()

            with self.assertRaises(CatalogUpgradeIntegrityError):
                upgrade_catalog(
                    catalog,
                    application_version="source-drift-test",
                    backup_dir=root / "backups",
                    fault_hook=change_source_before_backup,
                )

            self.assertNotEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), admitted_sha256)
            connection = sqlite3.connect(catalog)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
                self.assertEqual(
                    connection.execute(
                        "SELECT application_version FROM schema_migration WHERE migration_id=?",
                        ("0005_task_execution_deadline",),
                    ).fetchone()[0],
                    "external-writer-after-admission",
                )
            finally:
                connection.close()
            self.assertFalse(any(root.glob(".catalog.sqlite3.upgrade-*.staged")))
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())
            self.assertFalse(any((root / "backups").glob("catalog-before-upgrade-*.sqlite3")))
            self.assertEqual(
                len(tuple((root / "backups").glob("catalog-before-upgrade-*.sqlite3.incomplete"))),
                1,
            )

    def test_source_byte_drift_after_staging_is_refused_before_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            admitted_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            def change_source_after_staged_migration(phase: str) -> None:
                if phase == "AFTER_STAGED_VALIDATION_BEFORE_SOURCE_RECHECK":
                    connection = sqlite3.connect(catalog)
                    try:
                        connection.execute(
                            "UPDATE schema_migration SET application_version=? WHERE migration_id=?",
                            ("external-writer-before-replace", "0005_task_execution_deadline"),
                        )
                        connection.commit()
                    finally:
                        connection.close()

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="late-source-drift-test",
                    backup_dir=root / "backups",
                    fault_hook=change_source_after_staged_migration,
                )

            self.assertEqual(raised.exception.details["phase"], "PRE_REPLACE_SOURCE")
            self.assertNotEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), admitted_sha256)
            connection = sqlite3.connect(catalog)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            finally:
                connection.close()
            self.assertTrue(any(root.glob(".catalog.sqlite3.upgrade-*.staged")))
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())

    def test_staged_migration_failure_preserves_source_and_diagnostic_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()
            source_versions = (
                Path(__file__).parents[2]
                / "src"
                / "v3_backend"
                / "migrations"
                / "versions"
            )
            failing_versions = root / "failing-versions"
            failing_versions.mkdir()
            for migration in source_versions.glob("*.sql"):
                if migration.name != "0006_catalog_upgrade_session_integrity.sql":
                    (failing_versions / migration.name).write_bytes(migration.read_bytes())
            (failing_versions / "0006_catalog_upgrade_session_integrity.sql").write_text(
                "THIS IS NOT VALID SQLITE;",
                encoding="utf-8",
            )

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                upgrade_catalog(
                    catalog,
                    application_version="staged-migration-failure-test",
                    versions_dir=failing_versions,
                    backup_dir=root / "backups",
                )
            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
            )
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            original = sqlite3.connect(catalog)
            try:
                self.assertEqual(original.execute("PRAGMA user_version").fetchone()[0], 5)
                self.assertEqual(str(original.execute("PRAGMA integrity_check").fetchone()[0]), "ok")
            finally:
                original.close()
            self.assertTrue(any(root.glob(".catalog.sqlite3.upgrade-*.staged")))
            self.assertTrue(any((root / "backups").glob("catalog-before-upgrade-*.sqlite3")))
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())

    def test_staged_schema_missing_required_session_trigger_is_refused_before_replace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()
            source_versions = (
                Path(__file__).parents[2]
                / "src"
                / "v3_backend"
                / "migrations"
                / "versions"
            )
            incomplete_versions = root / "incomplete-versions"
            incomplete_versions.mkdir()
            for migration in source_versions.glob("*.sql"):
                if migration.name != "0006_catalog_upgrade_session_integrity.sql":
                    (incomplete_versions / migration.name).write_bytes(migration.read_bytes())
            migration_0006 = (source_versions / "0006_catalog_upgrade_session_integrity.sql").read_text(
                encoding="utf-8"
            )
            migration_0006 = migration_0006[: migration_0006.index("DROP TRIGGER")]
            (incomplete_versions / "0006_catalog_upgrade_session_integrity.sql").write_text(
                migration_0006,
                encoding="utf-8",
            )

            with self.assertRaises(CatalogUpgradeIntegrityError):
                upgrade_catalog(
                    catalog,
                    application_version="missing-trigger-test",
                    versions_dir=incomplete_versions,
                    backup_dir=root / "backups",
                )
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            original = connect_catalog(catalog, read_only=True)
            try:
                self.assertEqual(original.execute("PRAGMA user_version").fetchone()[0], 5)
            finally:
                original.close()

    def test_staged_schema_rejects_semantically_broken_session_owner_trigger(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()
            source_versions = (
                Path(__file__).parents[2]
                / "src"
                / "v3_backend"
                / "migrations"
                / "versions"
            )
            malformed_versions = root / "malformed-versions"
            malformed_versions.mkdir()
            for migration in source_versions.glob("*.sql"):
                (malformed_versions / migration.name).write_bytes(migration.read_bytes())
            migration_0006_path = malformed_versions / "0006_catalog_upgrade_session_integrity.sql"
            migration_0006 = migration_0006_path.read_text(encoding="utf-8")
            malformed_trigger = """
DROP TRIGGER desktop_session_project_context_owner_insert_guard;

CREATE TRIGGER desktop_session_project_context_owner_insert_guard
BEFORE INSERT ON desktop_session
WHEN NOT EXISTS (
  SELECT 1 FROM project_context_revision
  WHERE project_context_revision_id=NEW.project_context_revision_id
    AND project_id=NEW.project_id
    OR 1=1
)
BEGIN
  SELECT RAISE(ABORT, 'desktop_session project/context binding mismatch');
END;
"""
            migration_0006_path.write_text(
                migration_0006.replace(
                    "DROP TRIGGER desktop_session_project_binding_immutable_guard;",
                    malformed_trigger
                    + "\nDROP TRIGGER desktop_session_project_binding_immutable_guard;",
                ),
                encoding="utf-8",
            )

            with self.assertRaises(CatalogUpgradeIntegrityError):
                upgrade_catalog(
                    catalog,
                    application_version="malformed-owner-trigger-test",
                    versions_dir=malformed_versions,
                    backup_dir=root / "backups",
                )

            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            connection = connect_catalog(catalog, read_only=True)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            finally:
                connection.close()

    def test_backup_write_interruption_preserves_source_and_isolates_partial_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            def interrupt_copy(source_stream, target_stream, *, length):
                del source_stream, length
                target_stream.write(b"incomplete-backup")
                target_stream.flush()
                raise OSError("simulated backup write interruption")

            with patch(
                "v3_backend.adapters.sqlite.backup.shutil.copyfileobj",
                side_effect=interrupt_copy,
            ):
                with self.assertRaises(OSError):
                    upgrade_catalog(
                        catalog,
                        application_version="backup-write-failure-test",
                        backup_dir=root / "backups",
                    )

            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())
            incomplete = tuple((root / "backups").glob("catalog-before-upgrade-*.sqlite3.incomplete"))
            self.assertEqual(len(incomplete), 1)
            self.assertEqual(incomplete[0].read_bytes(), b"incomplete-backup")

    def test_atomic_replace_failure_preserves_source_and_restart_uses_verified_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            with patch(
                "v3_backend.migrations.upgrade.atomic_replace_database",
                side_effect=OSError("simulated atomic replace failure"),
            ):
                with self.assertRaises(OSError):
                    upgrade_catalog(
                        catalog,
                        application_version="replace-failure-test",
                        backup_dir=root / "backups",
                    )

            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            self.assertTrue((root / ".catalog.sqlite3.upgrade-state.v1.json").is_file())
            self.assertTrue(any(root.glob(".catalog.sqlite3.upgrade-*.staged")))

            recovered = upgrade_catalog(
                catalog,
                application_version="replace-failure-recovery-test",
                backup_dir=root / "backups",
            )
            self.assertEqual(recovered.receipt.result, "UPGRADED")
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())

    def test_unknown_future_migration_is_refused_without_backup_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            connection = sqlite3.connect(catalog)
            try:
                connection.execute(
                    """
                    INSERT INTO schema_migration(
                      migration_id,checksum_sha256,applied_at,application_version,state
                    ) VALUES(?,?,?,?,?)
                    """,
                    ("9999_unknown_future", "9" * 64, "2026-01-01T00:00:00Z", "future", "APPLIED"),
                )
                connection.execute("PRAGMA user_version = 5")
                connection.commit()
            finally:
                connection.close()
            before_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            with self.assertRaises(CatalogMigrationPrefixUnrecognizedError):
                ProductRuntime(root)
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), before_sha256)
            self.assertFalse((root / "backups").exists())
            self.assertFalse((root / ".catalog.sqlite3.upgrade-state.v1.json").exists())

    def test_gap_non_applied_and_version_mismatch_are_refused_before_backup(self) -> None:
        mutations = {
            "gap": "DELETE FROM schema_migration WHERE migration_id='0003_portfolio_riskpolicy_owner'",
            "non-applied": "UPDATE schema_migration SET state='APPLYING' WHERE migration_id='0004_risk_application_publication'",
            "version-mismatch": "PRAGMA user_version = 4",
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                catalog = self._create_exact_v5_catalog(root)
                connection = sqlite3.connect(catalog)
                try:
                    connection.execute(mutation)
                    connection.commit()
                finally:
                    connection.close()
                before_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

                with self.assertRaises(CatalogMigrationPrefixUnrecognizedError):
                    ProductRuntime(root)
                self.assertEqual(
                    hashlib.sha256(catalog.read_bytes()).hexdigest(),
                    before_sha256,
                )
                self.assertFalse((root / "backups").exists())
                self.assertFalse(
                    (root / ".catalog.sqlite3.upgrade-state.v1.json").exists()
                )

    def test_recovery_refuses_staged_hash_drift_without_touching_source(self) -> None:
        class SimulatedProcessCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            def crash_before_replace(phase: str) -> None:
                if phase == "AFTER_STAGE_STATE_BEFORE_REPLACE":
                    raise SimulatedProcessCrash()

            with self.assertRaises(SimulatedProcessCrash):
                upgrade_catalog(
                    catalog,
                    application_version="state-drift-test",
                    backup_dir=root / "backups",
                    fault_hook=crash_before_replace,
                )
            state_path = root / ".catalog.sqlite3.upgrade-state.v1.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            staged = Path(state["staged_path"])
            with staged.open("ab") as stream:
                stream.write(b"drift")

            with self.assertRaises(CatalogUpgradeIntegrityError):
                ProductRuntime(root)
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            self.assertTrue(state_path.is_file())

    def test_recovery_maps_missing_backup_to_stable_integrity_error(self) -> None:
        class SimulatedProcessCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            def crash_before_replace(phase: str) -> None:
                if phase == "AFTER_STAGE_STATE_BEFORE_REPLACE":
                    raise SimulatedProcessCrash()

            with self.assertRaises(SimulatedProcessCrash):
                upgrade_catalog(
                    catalog,
                    application_version="missing-recovery-backup-test",
                    backup_dir=root / "backups",
                    fault_hook=crash_before_replace,
                )
            state_path = root / ".catalog.sqlite3.upgrade-state.v1.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            Path(str(state["backup_path"])).unlink()

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                ProductRuntime(root)
            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
            )
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
            self.assertTrue(state_path.is_file())

    def test_recovery_refuses_malformed_state_as_a_stable_integrity_error(self) -> None:
        class SimulatedProcessCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._create_exact_v5_catalog(root)
            source_sha256 = hashlib.sha256(catalog.read_bytes()).hexdigest()

            def crash_before_replace(phase: str) -> None:
                if phase == "AFTER_STAGE_STATE_BEFORE_REPLACE":
                    raise SimulatedProcessCrash()

            with self.assertRaises(SimulatedProcessCrash):
                upgrade_catalog(
                    catalog,
                    application_version="malformed-state-test",
                    backup_dir=root / "backups",
                    fault_hook=crash_before_replace,
                )
            state_path = root / ".catalog.sqlite3.upgrade-state.v1.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["source_schema_prefix"] = "not-a-prefix"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaises(CatalogUpgradeIntegrityError) as raised:
                ProductRuntime(root)
            self.assertEqual(
                raised.exception.code.value,
                "CATALOG_UPGRADE_INTEGRITY_FAILED",
            )
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), source_sha256)
