from __future__ import annotations

import sqlite3
import tempfile
import unittest
import hashlib
from pathlib import Path

from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.migrations import (
    EXPECTED_TABLES,
    LegacyDatabaseRefusedError,
    MigrationError,
    MigrationOrderError,
    apply_migrations,
    discover_migrations,
)
from v3_backend.migrations.runner import _apply_one


class MigrationTests(unittest.TestCase):
    def test_fresh_database_has_exact_schema_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            result = apply_migrations(path, application_version="test")
            self.assertEqual(
                result.applied,
                (
                    "0001_control_catalog",
                    "0002_data_truth",
                    "0003_portfolio_riskpolicy_owner",
                ),
            )
            self.assertEqual(result.schema_report.table_count, 71)
            self.assertEqual(result.schema_report.user_version, 3)
            connection = connect_catalog(path)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                self.assertEqual(tables, EXPECTED_TABLES)
                self.assertGreater(
                    int(
                        connection.execute(
                            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
                        ).fetchone()[0]
                    ),
                    0,
                )
            finally:
                connection.close()

    def test_migration_is_idempotent_and_checksum_locked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            apply_migrations(path, application_version="test")
            second = apply_migrations(path, application_version="test")
            self.assertEqual(second.applied, ())
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "UPDATE schema_migration SET checksum_sha256=?", ("0" * 64,)
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(MigrationOrderError):
                apply_migrations(path, application_version="test")

    def test_discovery_refuses_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "0002_gap.sql").write_text("SELECT 1;", encoding="utf-8")
            with self.assertRaises(MigrationOrderError):
                discover_migrations(Path(directory))

    def test_legacy_database_is_never_mutated_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE legacy_prices(symbol TEXT)")
            connection.execute("INSERT INTO legacy_prices VALUES('000001.SZ')")
            connection.commit()
            connection.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(LegacyDatabaseRefusedError):
                apply_migrations(path, application_version="test")
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(
                    connection.execute("SELECT symbol FROM legacy_prices").fetchone()[0],
                    "000001.SZ",
                )
                self.assertIsNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'"
                    ).fetchone()
                )
            finally:
                connection.close()

    def test_existing_v1_catalog_requires_backup_before_each_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v1_versions = root / "v1"
            v1_versions.mkdir()
            source = (
                Path(__file__).parents[2]
                / "src"
                / "v3_backend"
                / "migrations"
                / "versions"
                / "0001_control_catalog.sql"
            )
            (v1_versions / source.name).write_bytes(source.read_bytes())
            path = root / "catalog.sqlite3"
            connection = sqlite3.connect(path, isolation_level=None)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                _apply_one(
                    connection,
                    discover_migrations(v1_versions)[0],
                    application_version="v1",
                    backup=None,
                )
                for symbol, role in (("a", "CONNECTOR_BUNDLE"), ("b", "RAW_CAPTURE")):
                    content_hash = symbol * 64
                    connection.execute(
                        """
                        INSERT INTO artifact(
                          artifact_id,sha256,byte_size,media_type,semantic_role,
                          storage_key,state,created_at,published_at
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            "art_sha256_" + content_hash,
                            content_hash,
                            1,
                            "application/octet-stream",
                            role,
                            f"sha256/{content_hash}",
                            "PUBLISHED",
                            "2020-01-01T00:00:00Z",
                            "2020-01-01T00:00:00Z",
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO connector(
                      connector_id,stable_name,publisher,state,created_at
                    ) VALUES('con_migration','migration-test','V3','REGISTERED',?)
                    """,
                    ("2020-01-01T00:00:00Z",),
                )
                connection.execute(
                    """
                    INSERT INTO connector_version(
                      connector_version_id,connector_id,semantic_version,
                      bundle_artifact_id,bundle_sha256,entrypoint,
                      declared_manifest_json,network_policy,state,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "cov_migration",
                        "con_migration",
                        "1.0.0",
                        "art_sha256_" + "a" * 64,
                        "a" * 64,
                        "v3:migration",
                        "{}",
                        "DENY",
                        "ADMITTED",
                        "2020-01-01T00:00:00Z",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO raw_capture(
                      raw_capture_id,connector_version_id,provider_dataset,
                      request_fingerprint,available_time,captured_at,ingested_at,
                      artifact_id,content_hash,state
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "raw_migration_sentinel",
                        "cov_migration",
                        "CN_EOD",
                        "c" * 64,
                        "UNAVAILABLE",
                        "2020-01-02T00:00:00Z",
                        "2020-01-02T00:01:00Z",
                        "art_sha256_" + "b" * 64,
                        "b" * 64,
                        "CAPTURED",
                    ),
                )
            finally:
                connection.close()
            with self.assertRaises(MigrationError):
                apply_migrations(path, application_version="v2")
            upgraded = apply_migrations(
                path,
                application_version="v2",
                backup_dir=root / "backups",
            )
            self.assertEqual(
                upgraded.applied,
                ("0002_data_truth", "0003_portfolio_riskpolicy_owner"),
            )
            self.assertEqual(len(upgraded.backups), 2)
            self.assertEqual(upgraded.schema_report.user_version, 3)
            connection = connect_catalog(path)
            try:
                self.assertIsNone(
                    connection.execute(
                        """
                        SELECT available_time FROM raw_capture
                        WHERE raw_capture_id='raw_migration_sentinel'
                        """
                    ).fetchone()[0]
                )
            finally:
                connection.close()
