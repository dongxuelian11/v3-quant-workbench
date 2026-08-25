from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from v3_backend.adapters.sqlite.backup import copy_database_file_exact
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.errors.exceptions import (
    CatalogMigrationPrefixUnrecognizedError,
    CatalogUpgradeIntegrityError,
)
from v3_backend.migrations import discover_migrations
from v3_backend.migrations.runner import _apply_one
from v3_backend.migrations.upgrade import _catalog_upgrade_lock, upgrade_catalog
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_runtime import (
    ProductRuntime,
    build_product_ports,
    mint_uuid7,
)
from v3_backend.runtime.request_router import RequestRouter
from v3_backend.runtime import bootstrap as runtime_bootstrap


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
                connection.execute("PRAGMA user_version = 6")
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
