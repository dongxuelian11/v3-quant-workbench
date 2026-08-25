from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.adapters.sqlite.backup import (
    BackupEvidence,
    atomic_replace_database,
    copy_database_file_exact,
    database_file_evidence,
    durable_replace_file,
    sync_directory,
    sync_file,
)
from v3_backend.errors.exceptions import (
    CatalogMigrationPrefixUnrecognizedError,
    CatalogUpgradeIntegrityError,
)

from .runner import (
    LegacyDatabaseRefusedError,
    Migration,
    MigrationError,
    MigrationOrderError,
    MigrationResult,
    _validate_applied_prefix,
    apply_migrations,
    discover_migrations,
)
from .validator import SchemaReport, SchemaValidationError, validate_schema


UPGRADE_STATE_SCHEMA_ID = "urn:v3:catalog-upgrade-state:1.0.0"


@dataclass(frozen=True)
class CatalogUpgradeReceiptV1:
    operation_id: str
    source_catalog_path_fingerprint: str
    source_catalog_sha256: str
    source_schema_prefix: tuple[tuple[str, str], ...]
    target_schema_prefix: tuple[tuple[str, str], ...]
    backup_path_fingerprint: str | None
    backup_sha256: str | None
    staged_sha256_before_replace: str
    final_catalog_sha256: str
    integrity_check: str
    foreign_key_check: str
    replacement_mode: str
    started_at: str
    committed_at: str
    recovery_action: str
    result: str
    error_code: str | None


@dataclass(frozen=True)
class CatalogUpgradeResult:
    database_path: Path
    migration_result: MigrationResult
    receipt: CatalogUpgradeReceiptV1 | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _path_fingerprint(path: Path) -> str:
    resolved = str(path.resolve())
    canonical = resolved.casefold() if os.name == "nt" else resolved
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _state_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.upgrade-state.v1.json")


@contextmanager
def _catalog_upgrade_lock(
    path: Path,
    *,
    busy_timeout_ms: int,
) -> Iterator[None]:
    """Serialize Catalog replacement across processes; OS locks die with the owner."""

    lock_path = path.resolve().with_name(f".{path.name}.upgrade.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_path.open("a+b")
    if lock_path.stat().st_size == 0:
        stream.write(b"\0")
        stream.flush()
        os.fsync(stream.fileno())
    deadline = time.monotonic() + max(0, int(busy_timeout_ms)) / 1_000
    locked = False
    try:
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CatalogUpgradeIntegrityError(
                        "another process owns the Catalog upgrade lock",
                        details={"phase": "UPGRADE_LOCK"},
                    ) from error
                time.sleep(min(0.05, remaining))
        yield
    finally:
        if locked:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()
        else:
            stream.close()


def _write_durable_json(destination: Path, value: Mapping[str, object]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(destination.name + ".pending")
    payload = json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if pending.exists():
        pending.unlink()
    with pending.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    durable_replace_file(pending, destination)
    sync_file(destination)


def _write_state(path: Path, state: Mapping[str, object]) -> None:
    _write_durable_json(_state_path(path), state)


def _remove_state(path: Path) -> None:
    state_path = _state_path(path)
    state_path.unlink(missing_ok=True)
    state_path.with_name(state_path.name + ".pending").unlink(missing_ok=True)
    sync_directory(state_path.parent)


def _isolate_unadmitted_copy(path: Path) -> Path:
    incomplete = path.with_name(path.name + ".incomplete")
    durable_replace_file(path, incomplete)
    sync_file(incomplete)
    return incomplete


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _state_prefix(value: object, field: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        raise CatalogUpgradeIntegrityError(
            f"Catalog upgrade state {field} is not an ordered prefix"
        )
    prefix: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 2
            or not isinstance(item[0], str)
            or not _is_sha256(item[1])
        ):
            raise CatalogUpgradeIntegrityError(
                f"Catalog upgrade state {field} contains an invalid migration entry"
            )
        prefix.append((item[0], item[1]))
    return tuple(prefix)


def _load_state(path: Path, backup_root: Path) -> dict[str, object] | None:
    state_path = _state_path(path)
    if not state_path.exists():
        pending = state_path.with_name(state_path.name + ".pending")
        if pending.exists():
            raise CatalogUpgradeIntegrityError(
                "an incomplete Catalog upgrade-state write requires review"
            )
        return None
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogUpgradeIntegrityError(
            "Catalog upgrade state is unreadable"
        ) from error
    required = {
        "schema_id",
        "operation_id",
        "phase",
        "source_catalog_path_fingerprint",
        "source_catalog_sha256",
        "source_schema_prefix",
        "target_schema_prefix",
        "backup_path",
        "backup_path_fingerprint",
        "backup_sha256",
        "staged_path",
        "staged_sha256",
        "started_at",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise CatalogUpgradeIntegrityError("Catalog upgrade state has an invalid closed shape")
    if raw["schema_id"] != UPGRADE_STATE_SCHEMA_ID:
        raise CatalogUpgradeIntegrityError("Catalog upgrade state schema is unsupported")
    if raw["phase"] not in {"STAGED_VERIFIED", "REPLACED_PENDING_RECEIPT"}:
        raise CatalogUpgradeIntegrityError("Catalog upgrade state phase is invalid")
    operation_id = raw["operation_id"]
    if (
        not isinstance(operation_id, str)
        or not operation_id.startswith("cup_")
        or len(operation_id) != 36
        or any(character not in "0123456789abcdef" for character in operation_id[4:])
    ):
        raise CatalogUpgradeIntegrityError("Catalog upgrade state operation ID is invalid")
    for field in (
        "source_catalog_path_fingerprint",
        "source_catalog_sha256",
        "backup_path_fingerprint",
        "backup_sha256",
        "staged_sha256",
    ):
        if not _is_sha256(raw[field]):
            raise CatalogUpgradeIntegrityError(
                f"Catalog upgrade state {field} is not a lowercase SHA-256"
            )
    source_prefix = _state_prefix(raw["source_schema_prefix"], "source_schema_prefix")
    target_prefix = _state_prefix(raw["target_schema_prefix"], "target_schema_prefix")
    if not source_prefix or len(source_prefix) >= len(target_prefix):
        raise CatalogUpgradeIntegrityError("Catalog upgrade state prefixes are not an upgrade")
    if target_prefix[: len(source_prefix)] != source_prefix:
        raise CatalogUpgradeIntegrityError("Catalog upgrade state prefixes diverged")
    if not isinstance(raw["started_at"], str) or not raw["started_at"]:
        raise CatalogUpgradeIntegrityError("Catalog upgrade state start time is invalid")
    if not isinstance(raw["backup_path"], str) or not isinstance(
        raw["staged_path"], str
    ):
        raise CatalogUpgradeIntegrityError("Catalog upgrade state paths are invalid")
    if raw["source_catalog_path_fingerprint"] != _path_fingerprint(path):
        raise CatalogUpgradeIntegrityError("Catalog upgrade state belongs to another Catalog")
    backup_path = Path(str(raw["backup_path"])).resolve()
    staged_path = Path(str(raw["staged_path"])).resolve()
    if not backup_path.is_relative_to(backup_root.resolve()):
        raise CatalogUpgradeIntegrityError("Catalog upgrade backup path escaped its owner root")
    if staged_path.parent != path.parent:
        raise CatalogUpgradeIntegrityError("Catalog upgrade stage escaped the Catalog volume")
    if _path_fingerprint(backup_path) != raw["backup_path_fingerprint"]:
        raise CatalogUpgradeIntegrityError("Catalog upgrade backup fingerprint drifted")
    return raw


def _prefix(
    migrations: tuple[Migration, ...], count: int
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (migration.migration_id, migration.checksum_sha256)
        for migration in migrations[:count]
    )


def _read_prefix(path: Path, migrations: tuple[Migration, ...]) -> int:
    if not path.is_file() or path.stat().st_size < 16:
        raise CatalogMigrationPrefixUnrecognizedError(
            "Catalog is missing or too small to contain a SQLite header"
        )
    with path.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise CatalogMigrationPrefixUnrecognizedError(
                "Catalog does not have the SQLite format 3 header"
            )
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if quick_check != "ok":
            raise CatalogUpgradeIntegrityError(
                f"Catalog quick_check failed before upgrade: {quick_check}"
            )
        foreign_key = connection.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key is not None:
            raise CatalogUpgradeIntegrityError(
                f"Catalog foreign_key_check failed before upgrade: {tuple(foreign_key)!r}"
            )
        try:
            return _validate_applied_prefix(connection, migrations)
        except (LegacyDatabaseRefusedError, MigrationOrderError) as error:
            raise CatalogMigrationPrefixUnrecognizedError(str(error)) from error
    except sqlite3.DatabaseError as error:
        raise CatalogMigrationPrefixUnrecognizedError(
            "Catalog could not be read as an admitted SQLite migration prefix"
        ) from error
    finally:
        connection.close()


def _checkpoint_and_remove_sidecars(path: Path, busy_timeout_ms: int) -> None:
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        checkpoint = tuple(connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
        if checkpoint and int(checkpoint[0]) != 0:
            raise CatalogUpgradeIntegrityError(
                f"Catalog WAL checkpoint remained busy: {checkpoint!r}"
            )
    finally:
        connection.close()
    for suffix in ("-wal", "-shm"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
    sync_file(path)
    sync_directory(path.parent)


def _validate_current(path: Path) -> SchemaReport:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro", uri=True, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        return validate_schema(connection)
    except (sqlite3.DatabaseError, SchemaValidationError) as error:
        raise CatalogUpgradeIntegrityError(
            "Catalog failed exact schema/integrity validation"
        ) from error
    finally:
        if connection is not None:
            connection.close()


def _isolate_failed_database(
    path: Path,
    failed_path: Path,
    busy_timeout_ms: int,
) -> None:
    try:
        _checkpoint_and_remove_sidecars(path, busy_timeout_ms)
    except (OSError, sqlite3.DatabaseError, CatalogUpgradeIntegrityError):
        # An unreadable replacement cannot be checkpointed. Its handles are
        # already closed by the validator; retain any sidecars with the failed
        # bytes so they cannot attach to the restored Catalog.
        for suffix in ("-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists():
                isolated_sidecar = failed_path.with_name(failed_path.name + suffix)
                durable_replace_file(sidecar, isolated_sidecar)
    atomic_replace_database(path, failed_path)


def _insert_receipt(
    path: Path,
    receipt: CatalogUpgradeReceiptV1,
    busy_timeout_ms: int,
) -> None:
    connection = sqlite3.connect(path, isolation_level=None)
    committed = False
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO catalog_upgrade_receipt(
              operation_id,source_catalog_path_fingerprint,source_catalog_sha256,
              source_schema_prefix_json,target_schema_prefix_json,
              backup_path_fingerprint,backup_sha256,staged_sha256_before_replace,
              final_catalog_sha256,integrity_check,foreign_key_check,replacement_mode,
              started_at,committed_at,recovery_action,result,error_code
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                receipt.operation_id,
                receipt.source_catalog_path_fingerprint,
                receipt.source_catalog_sha256,
                json.dumps(receipt.source_schema_prefix, separators=(",", ":")),
                json.dumps(receipt.target_schema_prefix, separators=(",", ":")),
                receipt.backup_path_fingerprint,
                receipt.backup_sha256,
                receipt.staged_sha256_before_replace,
                receipt.final_catalog_sha256,
                receipt.integrity_check,
                receipt.foreign_key_check,
                receipt.replacement_mode,
                receipt.started_at,
                receipt.committed_at,
                receipt.recovery_action,
                receipt.result,
                receipt.error_code,
            ),
        )
        connection.commit()
        committed = True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    if committed:
        _checkpoint_and_remove_sidecars(path, busy_timeout_ms)


def _receipt_from_state(state: Mapping[str, object]) -> CatalogUpgradeReceiptV1:
    return CatalogUpgradeReceiptV1(
        operation_id=str(state["operation_id"]),
        source_catalog_path_fingerprint=str(
            state["source_catalog_path_fingerprint"]
        ),
        source_catalog_sha256=str(state["source_catalog_sha256"]),
        source_schema_prefix=_state_prefix(
            state["source_schema_prefix"], "source_schema_prefix"
        ),
        target_schema_prefix=_state_prefix(
            state["target_schema_prefix"], "target_schema_prefix"
        ),
        backup_path_fingerprint=str(state["backup_path_fingerprint"]),
        backup_sha256=str(state["backup_sha256"]),
        staged_sha256_before_replace=str(state["staged_sha256"]),
        final_catalog_sha256=str(state["staged_sha256"]),
        integrity_check="PASS",
        foreign_key_check="PASS",
        replacement_mode="SAME_VOLUME_ATOMIC_REPLACE",
        started_at=str(state["started_at"]),
        committed_at=_utc_now(),
        recovery_action="NONE",
        result="UPGRADED",
        error_code=None,
    )


def _read_persisted_receipt(
    path: Path,
    operation_id: str,
) -> CatalogUpgradeReceiptV1 | None:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro", uri=True, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        receipt_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_upgrade_receipt'"
        ).fetchone()
        if receipt_table is None:
            return None
        row = connection.execute(
            "SELECT * FROM catalog_upgrade_receipt WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        return CatalogUpgradeReceiptV1(
            operation_id=str(row["operation_id"]),
            source_catalog_path_fingerprint=str(
                row["source_catalog_path_fingerprint"]
            ),
            source_catalog_sha256=str(row["source_catalog_sha256"]),
            source_schema_prefix=_state_prefix(
                json.loads(str(row["source_schema_prefix_json"])),
                "source_schema_prefix",
            ),
            target_schema_prefix=_state_prefix(
                json.loads(str(row["target_schema_prefix_json"])),
                "target_schema_prefix",
            ),
            backup_path_fingerprint=(
                None
                if row["backup_path_fingerprint"] is None
                else str(row["backup_path_fingerprint"])
            ),
            backup_sha256=(
                None if row["backup_sha256"] is None else str(row["backup_sha256"])
            ),
            staged_sha256_before_replace=str(row["staged_sha256_before_replace"]),
            final_catalog_sha256=str(row["final_catalog_sha256"]),
            integrity_check=str(row["integrity_check"]),
            foreign_key_check=str(row["foreign_key_check"]),
            replacement_mode=str(row["replacement_mode"]),
            started_at=str(row["started_at"]),
            committed_at=str(row["committed_at"]),
            recovery_action=str(row["recovery_action"]),
            result=str(row["result"]),
            error_code=None if row["error_code"] is None else str(row["error_code"]),
        )
    except (sqlite3.DatabaseError, json.JSONDecodeError) as error:
        raise CatalogUpgradeIntegrityError(
            "persisted Catalog upgrade receipt is unreadable"
        ) from error
    finally:
        if connection is not None:
            connection.close()


def _reconcile_upgrade_state(
    path: Path,
    backup_root: Path,
    migrations: tuple[Migration, ...],
    busy_timeout_ms: int,
) -> CatalogUpgradeResult | None:
    state = _load_state(path, backup_root)
    if state is None:
        return None
    receipt = _receipt_from_state(state)
    expected_target = _prefix(migrations, len(migrations))
    source_count = len(receipt.source_schema_prefix)
    if receipt.target_schema_prefix != expected_target:
        raise CatalogUpgradeIntegrityError("Catalog upgrade target prefix drifted from code")
    if receipt.source_schema_prefix != expected_target[:source_count]:
        raise CatalogUpgradeIntegrityError("Catalog upgrade source prefix drifted from code")
    persisted_receipt = _read_persisted_receipt(path, receipt.operation_id)
    if persisted_receipt is not None:
        expected_persisted = replace(
            receipt,
            committed_at=persisted_receipt.committed_at,
        )
        if persisted_receipt != expected_persisted:
            raise CatalogUpgradeIntegrityError(
                "persisted Catalog upgrade receipt conflicts with durable upgrade state"
            )
        report = _validate_current(path)
        _remove_state(path)
        return CatalogUpgradeResult(
            path,
            MigrationResult(path, (), (), report),
            persisted_receipt,
        )

    backup_path = Path(str(state["backup_path"])).resolve()
    backup_evidence = database_file_evidence(backup_path)
    if backup_evidence.sha256 != state["backup_sha256"]:
        raise CatalogUpgradeIntegrityError("Catalog upgrade backup bytes drifted")
    if _read_prefix(backup_path, migrations) != source_count:
        raise CatalogUpgradeIntegrityError("Catalog upgrade backup prefix drifted")

    current_evidence = database_file_evidence(path)
    staged_path = Path(str(state["staged_path"])).resolve()
    if current_evidence.sha256 == receipt.source_catalog_sha256:
        if not staged_path.is_file():
            raise CatalogUpgradeIntegrityError(
                "Catalog still matches the source but its verified stage is missing"
            )
        staged_evidence = database_file_evidence(staged_path)
        if staged_evidence.sha256 != receipt.staged_sha256_before_replace:
            raise CatalogUpgradeIntegrityError("Catalog upgrade staged bytes drifted")
        _validate_current(staged_path)
        atomic_replace_database(staged_path, path)
        state["phase"] = "REPLACED_PENDING_RECEIPT"
        _write_state(path, state)
    elif current_evidence.sha256 != receipt.staged_sha256_before_replace:
        raise CatalogUpgradeIntegrityError(
            "Catalog bytes match neither the admitted source nor verified replacement"
        )

    report = _validate_current(path)
    _insert_receipt(path, receipt, busy_timeout_ms)
    _remove_state(path)
    applied = tuple(item[0] for item in receipt.target_schema_prefix[source_count:])
    return CatalogUpgradeResult(path, MigrationResult(path, applied, (), report), receipt)


def _receipt(
    *,
    path: Path,
    migrations: tuple[Migration, ...],
    applied_count: int,
    source_sha256: str,
    staged_sha256: str,
    backup: BackupEvidence | None,
    started_at: str,
    result: str,
    recovery_action: str = "NONE",
    error_code: str | None = None,
) -> CatalogUpgradeReceiptV1:
    return CatalogUpgradeReceiptV1(
        operation_id="cup_" + uuid.uuid4().hex,
        source_catalog_path_fingerprint=_path_fingerprint(path),
        source_catalog_sha256=source_sha256,
        source_schema_prefix=_prefix(migrations, applied_count),
        target_schema_prefix=_prefix(migrations, len(migrations)),
        backup_path_fingerprint=(
            None if backup is None else _path_fingerprint(backup.path)
        ),
        backup_sha256=None if backup is None else backup.sha256,
        staged_sha256_before_replace=staged_sha256,
        # This is the exact file hash at the atomic replacement boundary. The
        # receipt row is inserted immediately afterwards and is intentionally
        # not self-hashed.
        final_catalog_sha256=staged_sha256,
        integrity_check="PASS",
        foreign_key_check="PASS",
        replacement_mode="SAME_VOLUME_ATOMIC_REPLACE",
        started_at=started_at,
        committed_at=_utc_now(),
        recovery_action=recovery_action,
        result=result,
        error_code=error_code,
    )


def upgrade_catalog(
    database_path: str | Path,
    *,
    application_version: str,
    versions_dir: Path | None = None,
    backup_dir: str | Path,
    busy_timeout_ms: int = 5_000,
    fault_hook: Callable[[str], None] | None = None,
) -> CatalogUpgradeResult:
    path = Path(database_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _catalog_upgrade_lock(path, busy_timeout_ms=busy_timeout_ms):
        return _upgrade_catalog_locked(
            path,
            application_version=application_version,
            versions_dir=versions_dir,
            backup_dir=backup_dir,
            busy_timeout_ms=busy_timeout_ms,
            fault_hook=fault_hook,
        )


def require_current_catalog(
    database_path: str | Path,
) -> SchemaReport:
    """Verify an already-started Catalog without taking upgrade ownership.

    Worker processes share the parent's live Catalog. They may verify its exact
    migration prefix and schema, but must not checkpoint WAL files, remove
    sidecars, insert startup receipts, or enter an atomic replacement path.
    """

    path = Path(database_path).resolve()
    if not path.exists():
        raise CatalogUpgradeIntegrityError(
            "worker Catalog is missing after runtime startup",
            details={"phase": "REQUIRE_CURRENT"},
        )
    return _validate_current(path)


def _upgrade_catalog_locked(
    database_path: str | Path,
    *,
    application_version: str,
    versions_dir: Path | None = None,
    backup_dir: str | Path,
    busy_timeout_ms: int = 5_000,
    fault_hook: Callable[[str], None] | None = None,
) -> CatalogUpgradeResult:
    path = Path(database_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = discover_migrations(versions_dir)
    backup_root = Path(backup_dir).resolve()
    reconciled = _reconcile_upgrade_state(
        path,
        backup_root,
        migrations,
        busy_timeout_ms,
    )
    if reconciled is not None:
        return reconciled
    if not path.exists():
        started_at = _utc_now()
        migration_result = apply_migrations(
            path,
            application_version=application_version,
            versions_dir=versions_dir,
            backup_dir=backup_dir,
            busy_timeout_ms=busy_timeout_ms,
        )
        _checkpoint_and_remove_sidecars(path, busy_timeout_ms)
        current = database_file_evidence(path)
        receipt = _receipt(
            path=path,
            migrations=migrations,
            applied_count=len(migrations),
            source_sha256=current.sha256,
            staged_sha256=current.sha256,
            backup=None,
            started_at=started_at,
            result="NO_CHANGE",
        )
        _insert_receipt(path, receipt, busy_timeout_ms)
        return CatalogUpgradeResult(path, migration_result, receipt)

    started_at = _utc_now()
    applied_count = _read_prefix(path, migrations)
    if applied_count == len(migrations):
        report = _validate_current(path)
        _checkpoint_and_remove_sidecars(path, busy_timeout_ms)
        current = database_file_evidence(path)
        receipt = _receipt(
            path=path,
            migrations=migrations,
            applied_count=applied_count,
            source_sha256=current.sha256,
            staged_sha256=current.sha256,
            backup=None,
            started_at=started_at,
            result="NO_CHANGE",
        )
        _insert_receipt(path, receipt, busy_timeout_ms)
        return CatalogUpgradeResult(
            path,
            MigrationResult(path, (), (), report),
            receipt,
        )

    _checkpoint_and_remove_sidecars(path, busy_timeout_ms)
    source = database_file_evidence(path)
    if fault_hook is not None:
        fault_hook("AFTER_SOURCE_ADMISSION_BEFORE_BACKUP")
    backup_root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    backup_path = backup_root / f"catalog-before-upgrade-{token}.sqlite3"
    backup = copy_database_file_exact(path, backup_path)
    source_after_backup = database_file_evidence(path)
    if (
        source_after_backup.sha256 != source.sha256
        or source_after_backup.byte_size != source.byte_size
        or backup.sha256 != source.sha256
        or backup.byte_size != source.byte_size
    ):
        _isolate_unadmitted_copy(backup.path)
        raise CatalogUpgradeIntegrityError(
            "Catalog bytes changed after upgrade admission and before staging",
            details={"phase": "BACKUP_COPY"},
        )
    _read_prefix(backup.path, migrations)

    staged = path.with_name(f".{path.name}.upgrade-{token}.staged")
    staged_source = copy_database_file_exact(path, staged)
    source_after_staging = database_file_evidence(path)
    if (
        source_after_staging.sha256 != source.sha256
        or source_after_staging.byte_size != source.byte_size
        or staged_source.sha256 != source.sha256
        or staged_source.byte_size != source.byte_size
    ):
        raise CatalogUpgradeIntegrityError(
            "Catalog bytes changed after upgrade admission while staging",
            details={"phase": "STAGED_COPY"},
        )
    try:
        migration_result = apply_migrations(
            staged,
            application_version=application_version,
            versions_dir=versions_dir,
            backup_dir=backup_root / "staged-migration-backups" / token,
            busy_timeout_ms=busy_timeout_ms,
        )
    except (MigrationError, SchemaValidationError, sqlite3.DatabaseError) as error:
        raise CatalogUpgradeIntegrityError(
            "staged Catalog migration or exact schema validation failed"
        ) from error
    _checkpoint_and_remove_sidecars(staged, busy_timeout_ms)
    _validate_current(staged)
    staged_evidence = database_file_evidence(staged)
    if fault_hook is not None:
        fault_hook("AFTER_STAGED_VALIDATION_BEFORE_SOURCE_RECHECK")
    source_before_replace = database_file_evidence(path)
    if (
        source_before_replace.sha256 != source.sha256
        or source_before_replace.byte_size != source.byte_size
    ):
        raise CatalogUpgradeIntegrityError(
            "Catalog bytes changed after staging and before atomic replacement",
            details={"phase": "PRE_REPLACE_SOURCE"},
        )

    state: dict[str, object] = {
        "schema_id": UPGRADE_STATE_SCHEMA_ID,
        "operation_id": "cup_" + uuid.uuid4().hex,
        "phase": "STAGED_VERIFIED",
        "source_catalog_path_fingerprint": _path_fingerprint(path),
        "source_catalog_sha256": source.sha256,
        "source_schema_prefix": _prefix(migrations, applied_count),
        "target_schema_prefix": _prefix(migrations, len(migrations)),
        "backup_path": str(backup.path),
        "backup_path_fingerprint": _path_fingerprint(backup.path),
        "backup_sha256": backup.sha256,
        "staged_path": str(staged),
        "staged_sha256": staged_evidence.sha256,
        "started_at": started_at,
    }
    _write_state(path, state)
    if fault_hook is not None:
        fault_hook("AFTER_STAGE_STATE_BEFORE_REPLACE")

    atomic_replace_database(staged, path)
    state["phase"] = "REPLACED_PENDING_RECEIPT"
    _write_state(path, state)
    if fault_hook is not None:
        fault_hook("AFTER_REPLACE_BEFORE_RECEIPT")
    try:
        report = _validate_current(path)
    except CatalogUpgradeIntegrityError as validation_error:
        failed = path.with_name(f".{path.name}.failed-upgrade-{token}")
        _isolate_failed_database(path, failed, busy_timeout_ms)
        restored = path.with_name(f".{path.name}.restore-{token}.staged")
        copy_database_file_exact(backup.path, restored)
        atomic_replace_database(restored, path)
        if _read_prefix(path, migrations) != applied_count:
            raise CatalogUpgradeIntegrityError(
                "restored Catalog migration prefix differs from the admitted source"
            ) from validation_error
        restored_evidence = database_file_evidence(path)
        if restored_evidence.sha256 != source.sha256:
            raise CatalogUpgradeIntegrityError(
                "restored Catalog bytes differ from the admitted source"
            ) from validation_error
        rollback_receipt = {
            "schema_id": "urn:v3:catalog-upgrade-rollback-receipt:1.0.0",
            "operation_id": state["operation_id"],
            "source_catalog_path_fingerprint": state[
                "source_catalog_path_fingerprint"
            ],
            "source_catalog_sha256": source.sha256,
            "target_schema_prefix": state["target_schema_prefix"],
            "backup_path_fingerprint": state["backup_path_fingerprint"],
            "backup_sha256": backup.sha256,
            "failed_catalog_path_fingerprint": _path_fingerprint(failed),
            "recovery_action": "RESTORED_BACKUP",
            "result": "ROLLED_BACK",
            "error_code": "CATALOG_UPGRADE_INTEGRITY_FAILED",
            "started_at": started_at,
            "committed_at": _utc_now(),
        }
        _write_durable_json(
            backup_root
            / f"catalog-upgrade-rollback-{state['operation_id']}.json",
            rollback_receipt,
        )
        _remove_state(path)
        raise CatalogUpgradeIntegrityError(
            "post-replacement validation failed; verified backup was restored",
            details={"recovery_action": "RESTORED_BACKUP"},
        ) from validation_error

    receipt = _receipt_from_state(state)
    _insert_receipt(path, receipt, busy_timeout_ms)
    if fault_hook is not None:
        fault_hook("AFTER_RECEIPT_BEFORE_STATE_CLEANUP")
    _remove_state(path)
    return CatalogUpgradeResult(path, migration_result, receipt)
