from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.adapters.sqlite.backup import BackupEvidence, backup_database

from .validator import SchemaReport, validate_schema


_MIGRATION_NAME = re.compile(r"(?P<number>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql")


class MigrationError(RuntimeError):
    pass


class MigrationOrderError(MigrationError):
    pass


class LegacyDatabaseRefusedError(MigrationError):
    pass


@dataclass(frozen=True)
class Migration:
    number: int
    migration_id: str
    path: Path
    checksum_sha256: str


@dataclass(frozen=True)
class MigrationResult:
    database_path: Path
    applied: tuple[str, ...]
    backups: tuple[BackupEvidence, ...]
    schema_report: SchemaReport


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def discover_migrations(versions_dir: Path | None = None) -> tuple[Migration, ...]:
    root = versions_dir or Path(__file__).with_name("versions")
    migrations: list[Migration] = []
    for path in sorted(root.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationOrderError(f"invalid migration filename: {path.name}")
        raw = path.read_bytes()
        migrations.append(
            Migration(
                number=int(match.group("number")),
                migration_id=path.stem,
                path=path,
                checksum_sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    expected = list(range(1, len(migrations) + 1))
    observed = [migration.number for migration in migrations]
    if observed != expected:
        raise MigrationOrderError(f"migrations must be contiguous and ordered: {observed!r}")
    if not migrations:
        raise MigrationOrderError("no migrations discovered")
    return tuple(migrations)


def _split_sql(script: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise MigrationError("migration ends with an incomplete SQL statement")
    return tuple(statements)


def _user_tables(connection: sqlite3.Connection) -> frozenset[str]:
    return frozenset(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )


def _validate_applied_prefix(
    connection: sqlite3.Connection, migrations: tuple[Migration, ...]
) -> int:
    tables = _user_tables(connection)
    if not tables:
        return 0
    if "schema_migration" not in tables:
        raise LegacyDatabaseRefusedError(
            "refusing to mutate a non-empty database without the V3 schema_migration ledger"
        )
    rows = connection.execute(
        "SELECT migration_id, checksum_sha256, state FROM schema_migration ORDER BY migration_id"
    ).fetchall()
    if any(str(row[2]) != "APPLIED" for row in rows):
        raise MigrationOrderError("migration ledger contains a non-APPLIED entry")
    if len(rows) > len(migrations):
        raise MigrationOrderError("database contains unknown future migrations")
    for index, row in enumerate(rows):
        expected = migrations[index]
        if str(row[0]) != expected.migration_id:
            raise MigrationOrderError(
                f"migration order mismatch at position {index + 1}: {row[0]!r}"
            )
        if str(row[1]).lower() != expected.checksum_sha256:
            raise MigrationOrderError(f"migration checksum mismatch: {expected.migration_id}")
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version != len(rows):
        raise MigrationOrderError(
            f"user_version {version} does not match applied migration count {len(rows)}"
        )
    return len(rows)


def _apply_one(
    connection: sqlite3.Connection,
    migration: Migration,
    *,
    application_version: str,
    backup: BackupEvidence | None,
) -> None:
    statements = _split_sql(migration.path.read_text(encoding="utf-8-sig"))
    ledger_inserted = "schema_migration" in _user_tables(connection)
    connection.execute("BEGIN EXCLUSIVE")
    try:
        if ledger_inserted:
            connection.execute(
                """
                INSERT INTO schema_migration(
                    migration_id, checksum_sha256, applied_at, application_version, state,
                    backup_artifact_id
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    migration.migration_id,
                    migration.checksum_sha256,
                    _utc_now(),
                    application_version,
                    "APPLYING",
                    backup.artifact_id if backup else None,
                ),
            )
        for statement in statements:
            connection.execute(statement)
            if not ledger_inserted and "schema_migration" in _user_tables(connection):
                connection.execute(
                    """
                    INSERT INTO schema_migration(
                        migration_id, checksum_sha256, applied_at, application_version, state,
                        backup_artifact_id
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        migration.migration_id,
                        migration.checksum_sha256,
                        _utc_now(),
                        application_version,
                        "APPLYING",
                        None,
                    ),
                )
                ledger_inserted = True
        if not ledger_inserted:
            raise MigrationError("migration did not create the schema_migration ledger")
        connection.execute(
            "UPDATE schema_migration SET state='APPLIED', applied_at=? WHERE migration_id=?",
            (_utc_now(), migration.migration_id),
        )
        connection.execute(f"PRAGMA user_version = {migration.number}")
        violations = tuple(connection.execute("PRAGMA foreign_key_check"))
        if violations:
            raise MigrationError(f"foreign_key_check failed: {violations!r}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def apply_migrations(
    database_path: str | Path,
    *,
    application_version: str,
    versions_dir: Path | None = None,
    backup_dir: str | Path | None = None,
    busy_timeout_ms: int = 5_000,
) -> MigrationResult:
    path = Path(database_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = discover_migrations(versions_dir)
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    backups: list[BackupEvidence] = []
    applied_now: list[str] = []
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        applied_count = _validate_applied_prefix(connection, migrations)
        upgrading_existing_catalog = applied_count > 0
        # journal_mode mutates the database header. It is deliberately configured only
        # after the database has been admitted as fresh or as a known V3 Catalog.
        connection.execute("PRAGMA journal_mode = WAL")
        for migration in migrations[applied_count:]:
            backup: BackupEvidence | None = None
            if upgrading_existing_catalog:
                if backup_dir is None:
                    raise MigrationError("backup_dir is required before upgrading an existing Catalog")
                backup_path = Path(backup_dir).resolve() / (
                    f"catalog-before-{migration.migration_id}-{_utc_now().replace(':', '')}.sqlite3"
                )
                backup = backup_database(path, backup_path)
                backups.append(backup)
            _apply_one(
                connection,
                migration,
                application_version=application_version,
                backup=backup,
            )
            applied_count += 1
            applied_now.append(migration.migration_id)
        report = validate_schema(connection)
        return MigrationResult(path, tuple(applied_now), tuple(backups), report)
    finally:
        connection.close()
