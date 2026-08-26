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
from typing import BinaryIO

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


UPGRADE_STATE_SCHEMA_ID = "urn:v3:catalog-upgrade-state:1.1.0"
LEGACY_UPGRADE_STATE_SCHEMA_ID = "urn:v3:catalog-upgrade-state:1.0.0"


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
            if _try_lock_stream(stream):
                locked = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CatalogUpgradeIntegrityError(
                    "another process owns the Catalog upgrade lock",
                    details={"phase": "UPGRADE_LOCK"},
                )
            time.sleep(min(0.05, remaining))
        yield
    finally:
        if locked:
            try:
                _unlock_stream(stream)
            finally:
                stream.close()
        else:
            stream.close()


def _try_lock_stream(stream: BinaryIO) -> bool:
    """Try an exclusive one-byte OS lock without waiting."""

    try:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_stream(stream: BinaryIO) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _runtime_lease_pattern(path: Path) -> str:
    return f".{path.name}.runtime-lease-*"


def _wait_for_runtime_leases(path: Path, busy_timeout_ms: int) -> None:
    """Block Catalog replacement while any worker holds a runtime lease.

    The upgrade lock is held by the caller, so no new worker can create a lease
    while this scan is in progress. A stale lease file is safe to remove once
    its OS lock can be acquired; a live worker keeps that lock until process
    exit or normal worker cleanup.
    """

    deadline = time.monotonic() + max(0, int(busy_timeout_ms)) / 1_000
    while True:
        blocked = False
        for lease_path in tuple(path.parent.glob(_runtime_lease_pattern(path))):
            try:
                stream = lease_path.open("a+b")
            except FileNotFoundError:
                continue
            close_stream = True
            try:
                if not _try_lock_stream(stream):
                    blocked = True
                    continue
                _unlock_stream(stream)
                stream.close()
                close_stream = False
                lease_path.unlink(missing_ok=True)
            finally:
                if close_stream:
                    stream.close()
        if not blocked:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CatalogUpgradeIntegrityError(
                "a live worker owns the Catalog runtime lease",
                details={"phase": "RUNTIME_LEASE"},
            )
        time.sleep(min(0.05, remaining))


@contextmanager
def catalog_runtime_lease(
    database_path: str | Path,
    *,
    busy_timeout_ms: int = 5_000,
) -> Iterator[None]:
    """Hold a worker lease that excludes Catalog replacement for its lifetime."""

    path = Path(database_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lease_path = path.with_name(
        f".{path.name}.runtime-lease-{os.getpid()}-{uuid.uuid4().hex}"
    )
    stream: BinaryIO | None = None
    locked = False
    try:
        # Admission is serialized with upgrade so an upgrade cannot pass its
        # lease scan while a worker is between admission and lease creation.
        with _catalog_upgrade_lock(path, busy_timeout_ms=busy_timeout_ms):
            stream = lease_path.open("xb")
            stream.write(f"pid={os.getpid()}\n".encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
            if not _try_lock_stream(stream):
                raise CatalogUpgradeIntegrityError(
                    "worker Catalog runtime lease could not be acquired",
                    details={"phase": "RUNTIME_LEASE"},
                )
            locked = True
        yield
    finally:
        if stream is not None:
            if locked:
                try:
                    _unlock_stream(stream)
                except OSError:
                    pass
            stream.close()
        try:
            lease_path.unlink(missing_ok=True)
        except OSError:
            # An unlocked stale marker is harmless; the next upgrade can
            # acquire its OS lock and remove it during the scan.
            pass


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


def _validate_receipt_identity(row: Mapping[str, object]) -> None:
    operation_id = row.get("operation_id")
    if (
        not isinstance(operation_id, str)
        or len(operation_id) != 36
        or not operation_id.startswith("cup_")
        or len(operation_id[4:]) != 32
        or any(character not in "0123456789abcdef" for character in operation_id[4:])
    ):
        raise CatalogUpgradeIntegrityError(
            "persisted Catalog upgrade receipt operation identity is invalid"
        )


def _validate_receipt_hashes(row: Mapping[str, object]) -> None:
    for field in (
        "source_catalog_path_fingerprint",
        "source_catalog_sha256",
        "staged_sha256_before_replace",
        "final_catalog_sha256",
    ):
        if not _is_sha256(row.get(field)):
            raise CatalogUpgradeIntegrityError(
                f"persisted Catalog upgrade receipt {field} is invalid"
            )
    for field in ("backup_path_fingerprint", "backup_sha256"):
        value = row.get(field)
        if value is not None and not _is_sha256(value):
            raise CatalogUpgradeIntegrityError(
                f"persisted Catalog upgrade receipt {field} is invalid"
            )


def _validate_receipt_prefixes(
    row: Mapping[str, object],
    migrations: tuple[Migration, ...],
) -> None:
    try:
        source_prefix = _state_prefix(
            json.loads(str(row["source_schema_prefix_json"])),
            "receipt_source_schema_prefix",
        )
        target_prefix = _state_prefix(
            json.loads(str(row["target_schema_prefix_json"])),
            "receipt_target_schema_prefix",
        )
    except (KeyError, json.JSONDecodeError, TypeError) as error:
        raise CatalogUpgradeIntegrityError(
            "persisted Catalog upgrade receipt migration prefixes are invalid"
        ) from error
    expected_prefix = _prefix(migrations, len(migrations))
    if (
        not source_prefix
        or not target_prefix
        or len(target_prefix) > len(expected_prefix)
        or target_prefix != expected_prefix[: len(target_prefix)]
        or len(source_prefix) > len(target_prefix)
        or source_prefix != target_prefix[: len(source_prefix)]
    ):
        raise CatalogUpgradeIntegrityError(
            "persisted Catalog upgrade receipt migration prefixes are not an admitted chain"
        )


def _validate_receipt_integrity(row: Mapping[str, object]) -> None:
    if row.get("integrity_check") != "PASS" or row.get("foreign_key_check") != "PASS":
        raise CatalogUpgradeIntegrityError(
            "persisted Catalog upgrade receipt integrity evidence is invalid"
        )
    if row.get("replacement_mode") != "SAME_VOLUME_ATOMIC_REPLACE":
        raise CatalogUpgradeIntegrityError(
            "persisted Catalog upgrade receipt replacement mode is invalid"
        )


def _validate_receipt_outcome(row: Mapping[str, object]) -> None:
    result = row.get("result")
    recovery_action = row.get("recovery_action")
    if result not in {"UPGRADED", "NO_CHANGE", "REFUSED", "ROLLED_BACK"}:
        raise CatalogUpgradeIntegrityError(
            "persisted Catalog upgrade receipt result is invalid"
        )
    if recovery_action not in {"NONE", "RESTORED_BACKUP"}:
        raise CatalogUpgradeIntegrityError(
            "persisted Catalog upgrade receipt recovery action is invalid"
        )
    has_backup = (
        row.get("backup_sha256") is not None
        and row.get("backup_path_fingerprint") is not None
    )
    if (result == "NO_CHANGE") != (not has_backup):
        raise CatalogUpgradeIntegrityError(
            "persisted Catalog upgrade receipt backup evidence does not match its result"
        )


def _validate_receipt_times_and_error(row: Mapping[str, object]) -> None:
    for field in ("started_at", "committed_at"):
        value = row.get(field)
        if not isinstance(value, str) or not value:
            raise CatalogUpgradeIntegrityError(
                f"persisted Catalog upgrade receipt {field} is invalid"
            )
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise CatalogUpgradeIntegrityError(
                f"persisted Catalog upgrade receipt {field} is not an ISO timestamp"
            ) from error
    error_code = row.get("error_code")
    if error_code is not None and (
        not isinstance(error_code, str) or not 1 <= len(error_code) <= 128
    ):
        raise CatalogUpgradeIntegrityError(
            "persisted Catalog upgrade receipt error code is invalid"
        )


def _validate_receipt_row(
    row: Mapping[str, object],
    migrations: tuple[Migration, ...],
) -> None:
    _validate_receipt_identity(row)
    _validate_receipt_hashes(row)
    _validate_receipt_prefixes(row, migrations)
    _validate_receipt_integrity(row)
    _validate_receipt_outcome(row)
    _validate_receipt_times_and_error(row)


def _validate_persisted_receipts(
    connection: sqlite3.Connection,
    migrations: tuple[Migration, ...],
) -> None:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_upgrade_receipt'"
    ).fetchone()
    if table is None:
        return
    rows = connection.execute("SELECT * FROM catalog_upgrade_receipt").fetchall()
    for row in rows:
        _validate_receipt_row(dict(row), migrations)


def _quote_sqlite_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _canonical_sqlite_value(value: object) -> object:
    if value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    raise CatalogUpgradeIntegrityError(
        f"Catalog content contains an unsupported SQLite value type: {type(value).__name__}"
    )


def _catalog_content_sha256(
    path: Path,
    *,
    excluded_receipt_operation_id: str | None = None,
) -> str:
    """Hash logical Catalog content while excluding only the pending receipt row."""

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro", uri=True, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        objects = connection.execute(
            """
            SELECT type,name,sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type,name
            """
        ).fetchall()
        canonical_objects: list[dict[str, object]] = []
        for item in objects:
            object_type = str(item["type"])
            name = str(item["name"])
            canonical: dict[str, object] = {
                "type": object_type,
                "name": name,
                "sql": None if item["sql"] is None else str(item["sql"]),
            }
            if object_type == "table":
                quoted_name = _quote_sqlite_identifier(name)
                columns = tuple(
                    str(row["name"])
                    for row in connection.execute(
                        f"PRAGMA table_info({quoted_name})"
                    ).fetchall()
                )
                try:
                    rows = connection.execute(
                        f"SELECT * FROM {quoted_name} ORDER BY rowid"
                    ).fetchall()
                except sqlite3.OperationalError:
                    order_by = ",".join(
                        _quote_sqlite_identifier(column) for column in columns
                    )
                    rows = connection.execute(
                        f"SELECT * FROM {quoted_name} ORDER BY {order_by}"
                    ).fetchall()
                if (
                    name == "catalog_upgrade_receipt"
                    and excluded_receipt_operation_id is not None
                ):
                    try:
                        operation_index = columns.index("operation_id")
                    except ValueError as error:
                        raise CatalogUpgradeIntegrityError(
                            "Catalog receipt table has no operation_id column"
                        ) from error
                    rows = tuple(
                        row
                        for row in rows
                        if str(row[operation_index])
                        != excluded_receipt_operation_id
                    )
                canonical["columns"] = columns
                canonical["rows"] = [
                    [_canonical_sqlite_value(value) for value in row]
                    for row in rows
                ]
            canonical_objects.append(canonical)
        payload = json.dumps(
            canonical_objects,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    except (OSError, sqlite3.DatabaseError) as error:
        raise CatalogUpgradeIntegrityError(
            "Catalog logical content could not be hashed"
        ) from error
    finally:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()


def _load_state(path: Path, backup_root: Path) -> dict[str, object] | None:
    state_path = _state_path(path)
    pending = state_path.with_name(state_path.name + ".pending")

    def read_raw(candidate: Path) -> dict[str, object]:
        try:
            raw_value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise CatalogUpgradeIntegrityError(
                "Catalog upgrade state is unreadable"
            ) from error
        if not isinstance(raw_value, dict):
            raise CatalogUpgradeIntegrityError(
                "Catalog upgrade state has an invalid closed shape"
            )
        return raw_value

    def validate(raw: dict[str, object]) -> dict[str, object]:
        base_required = {
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
        state_schema_id = raw.get("schema_id")
        if state_schema_id == UPGRADE_STATE_SCHEMA_ID:
            required = base_required | {"staged_content_sha256"}
        elif state_schema_id == LEGACY_UPGRADE_STATE_SCHEMA_ID:
            required = base_required
        else:
            raise CatalogUpgradeIntegrityError("Catalog upgrade state schema is unsupported")
        if set(raw) != required:
            raise CatalogUpgradeIntegrityError(
                "Catalog upgrade state has an invalid closed shape"
            )
        if raw["phase"] not in {
            "STAGED_VERIFIED",
            "REPLACED_PENDING_RECEIPT",
            "ROLLBACK_PENDING_RESTORE",
        }:
            raise CatalogUpgradeIntegrityError("Catalog upgrade state phase is invalid")
        operation_id = raw["operation_id"]
        if (
            not isinstance(operation_id, str)
            or not operation_id.startswith("cup_")
            or len(operation_id) != 36
            or any(character not in "0123456789abcdef" for character in operation_id[4:])
        ):
            raise CatalogUpgradeIntegrityError("Catalog upgrade state operation ID is invalid")
        hash_fields = [
            "source_catalog_path_fingerprint",
            "source_catalog_sha256",
            "backup_path_fingerprint",
            "backup_sha256",
            "staged_sha256",
        ]
        if state_schema_id == UPGRADE_STATE_SCHEMA_ID:
            hash_fields.append("staged_content_sha256")
        for field in hash_fields:
            if not _is_sha256(raw[field]):
                raise CatalogUpgradeIntegrityError(
                    f"Catalog upgrade state {field} is not a lowercase SHA-256"
                )
        source_prefix = _state_prefix(raw["source_schema_prefix"], "source_schema_prefix")
        target_prefix = _state_prefix(raw["target_schema_prefix"], "target_schema_prefix")
        if not source_prefix or len(source_prefix) >= len(target_prefix):
            raise CatalogUpgradeIntegrityError(
                "Catalog upgrade state prefixes are not an upgrade"
            )
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
            raise CatalogUpgradeIntegrityError(
                "Catalog upgrade backup path escaped its owner root"
            )
        if staged_path.parent != path.parent:
            raise CatalogUpgradeIntegrityError(
                "Catalog upgrade stage escaped the Catalog volume"
            )
        if _path_fingerprint(backup_path) != raw["backup_path_fingerprint"]:
            raise CatalogUpgradeIntegrityError("Catalog upgrade backup fingerprint drifted")
        return raw

    if not state_path.exists() and not pending.exists():
        return None
    candidate = pending if pending.exists() else state_path
    raw = validate(read_raw(candidate))
    if pending.exists():
        try:
            durable_replace_file(pending, state_path)
            sync_file(state_path)
        except OSError as error:
            raise CatalogUpgradeIntegrityError(
                "verified pending Catalog upgrade state could not be activated",
                details={
                    "phase": "UPGRADE_STATE_RECOVERY",
                    "recovery_action": "STOP_FOR_REVIEW",
                },
            ) from error
    return raw


def _prefix(
    migrations: tuple[Migration, ...], count: int
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (migration.migration_id, migration.checksum_sha256)
        for migration in migrations[:count]
    )


def _discover_migrations_for_upgrade(
    versions_dir: Path | None,
) -> tuple[Migration, ...]:
    try:
        return discover_migrations(versions_dir)
    except (MigrationError, OSError, UnicodeError) as error:
        raise CatalogUpgradeIntegrityError(
            "Catalog migration set could not be discovered",
            details={
                "phase": "MIGRATION_DISCOVERY",
                "recovery_action": "STOP_FOR_REVIEW",
            },
        ) from error


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


def _validate_current(
    path: Path,
    migrations: tuple[Migration, ...],
) -> SchemaReport:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro", uri=True, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        report = validate_schema(connection)
        _validate_persisted_receipts(connection, migrations)
        return report
    except (sqlite3.DatabaseError, SchemaValidationError) as error:
        raise CatalogUpgradeIntegrityError(
            "Catalog failed exact schema/integrity validation"
        ) from error
    finally:
        if connection is not None:
            connection.close()


def _rollback_paths(path: Path, operation_id: str) -> tuple[Path, Path]:
    token = operation_id.removeprefix("cup_")
    return (
        path.with_name(f".{path.name}.failed-upgrade-{token}"),
        path.with_name(f".{path.name}.restore-{token}.staged"),
    )


def _preserve_failed_database(
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
    copy_database_file_exact(path, failed_path)


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
    migrations: tuple[Migration, ...],
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
        _validate_receipt_row(dict(row), migrations)
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


def _recovery_file_evidence(path: Path, role: str) -> BackupEvidence:
    try:
        return database_file_evidence(path)
    except OSError as error:
        raise CatalogUpgradeIntegrityError(
            f"Catalog upgrade recovery {role} is missing or unreadable",
            details={"phase": "RECOVERY_FILE_EVIDENCE", "role": role},
        ) from error


def _verify_rollback_file(
    path: Path,
    *,
    role: str,
    expected_sha256: str,
    expected_byte_size: int,
    migrations: tuple[Migration, ...],
    applied_count: int,
) -> None:
    try:
        evidence = _recovery_file_evidence(path, role)
        if (
            evidence.sha256 != expected_sha256
            or evidence.byte_size != expected_byte_size
        ):
            raise CatalogUpgradeIntegrityError(f"Catalog upgrade {role} bytes drifted")
        if _read_prefix(path, migrations) != applied_count:
            raise CatalogUpgradeIntegrityError(f"Catalog upgrade {role} prefix drifted")
    except (CatalogMigrationPrefixUnrecognizedError, CatalogUpgradeIntegrityError) as error:
        raise CatalogUpgradeIntegrityError(
            f"verified Catalog {role} is unavailable for rollback",
            details={
                "phase": "ROLLBACK_BACKUP_EVIDENCE",
                "recovery_action": "STOP_FOR_REVIEW",
                "role": role,
            },
        ) from error


def _verify_rollback_backup(
    backup: BackupEvidence,
    source: BackupEvidence,
    migrations: tuple[Migration, ...],
    applied_count: int,
) -> None:
    if (
        backup.sha256 != source.sha256
        or backup.byte_size != source.byte_size
    ):
        raise CatalogUpgradeIntegrityError(
            "verified Catalog backup differs from the admitted source",
            details={
                "phase": "ROLLBACK_BACKUP_EVIDENCE",
                "recovery_action": "STOP_FOR_REVIEW",
                "role": "backup",
            },
        )
    _verify_rollback_file(
        backup.path,
        role="backup",
        expected_sha256=source.sha256,
        expected_byte_size=source.byte_size,
        migrations=migrations,
        applied_count=applied_count,
    )


def _recover_pending_rollback(
    path: Path,
    backup_root: Path,
    state: Mapping[str, object],
    receipt: CatalogUpgradeReceiptV1,
    migrations: tuple[Migration, ...],
    busy_timeout_ms: int,
) -> None:
    backup_path = Path(str(state["backup_path"])).resolve()
    backup = _recovery_file_evidence(backup_path, "backup")
    if (
        backup.sha256 != state["backup_sha256"]
        or backup.sha256 != receipt.source_catalog_sha256
    ):
        raise CatalogUpgradeIntegrityError("Catalog upgrade backup bytes drifted")
    if _read_prefix(backup_path, migrations) != len(receipt.source_schema_prefix):
        raise CatalogUpgradeIntegrityError("Catalog upgrade backup prefix drifted")

    failed, restored = _rollback_paths(path, receipt.operation_id)
    try:
        if not restored.is_file():
            copy_database_file_exact(backup.path, restored)
        _verify_rollback_file(
            restored,
            role="restore",
            expected_sha256=backup.sha256,
            expected_byte_size=backup.byte_size,
            migrations=migrations,
            applied_count=len(receipt.source_schema_prefix),
        )
    except (
        OSError,
        CatalogMigrationPrefixUnrecognizedError,
        CatalogUpgradeIntegrityError,
    ) as restore_error:
        raise CatalogUpgradeIntegrityError(
            "verified Catalog backup could not be staged for rollback",
            details={
                "phase": "ROLLBACK_BACKUP_EVIDENCE",
                "recovery_action": "STOP_FOR_REVIEW",
                "role": "restore",
            },
        ) from restore_error

    current_is_source = False
    if path.is_file():
        try:
            current = database_file_evidence(path)
        except OSError:
            current = None
        current_is_source = (
            current is not None
            and current.sha256 == backup.sha256
            and current.byte_size == backup.byte_size
        )
    try:
        if not current_is_source:
            if path.is_file() and not failed.is_file():
                _preserve_failed_database(path, failed, busy_timeout_ms)
            atomic_replace_database(restored, path)
    except (OSError, sqlite3.DatabaseError, CatalogUpgradeIntegrityError) as restore_error:
        raise CatalogUpgradeIntegrityError(
            "verified Catalog backup could not be activated for rollback",
            details={
                "phase": "ROLLBACK_RESTORE",
                "recovery_action": "STOP_FOR_REVIEW",
            },
        ) from restore_error

    _verify_rollback_file(
        path,
        role="restored",
        expected_sha256=backup.sha256,
        expected_byte_size=backup.byte_size,
        migrations=migrations,
        applied_count=len(receipt.source_schema_prefix),
    )
    _write_rollback_receipt(
        path,
        backup_root,
        state,
        backup,
        backup,
        failed,
        str(state["started_at"]),
    )
    raise CatalogUpgradeIntegrityError(
        "post-replacement validation failed; verified backup was restored",
        details={"recovery_action": "RESTORED_BACKUP"},
    )


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
    if state["phase"] == "ROLLBACK_PENDING_RESTORE":
        _recover_pending_rollback(
            path,
            backup_root,
            state,
            receipt,
            migrations,
            busy_timeout_ms,
        )
    persisted_receipt = _read_persisted_receipt(
        path,
        receipt.operation_id,
        migrations,
    )
    if persisted_receipt is not None:
        expected_persisted = replace(
            receipt,
            committed_at=persisted_receipt.committed_at,
        )
        if persisted_receipt != expected_persisted:
            raise CatalogUpgradeIntegrityError(
                "persisted Catalog upgrade receipt conflicts with durable upgrade state"
            )
        if state["schema_id"] == LEGACY_UPGRADE_STATE_SCHEMA_ID:
            # State 1.0 predates the logical-content digest.  Once its receipt
            # is durable, the old raw staged hash cannot prove that all
            # non-receipt content remained unchanged.  Refuse this ambiguity
            # explicitly instead of deleting the recovery state on trust.
            raise CatalogUpgradeIntegrityError(
                "legacy Catalog upgrade state cannot reconcile a committed receipt safely",
                details={
                    "phase": "POST_RECEIPT_RECONCILIATION",
                    "recovery_action": "STOP_FOR_REVIEW",
                },
            )
        _read_prefix(path, migrations)
        expected_content_sha256 = state.get("staged_content_sha256")
        if not _is_sha256(expected_content_sha256):
            raise CatalogUpgradeIntegrityError(
                "legacy Catalog upgrade state lacks post-receipt content evidence",
                details={
                    "phase": "POST_RECEIPT_RECONCILIATION",
                    "recovery_action": "STOP_FOR_REVIEW",
                },
            )
        if _catalog_content_sha256(
            path,
            excluded_receipt_operation_id=receipt.operation_id,
        ) != expected_content_sha256:
            raise CatalogUpgradeIntegrityError(
                "Catalog logical content drifted after the durable receipt commit",
                details={
                    "phase": "POST_RECEIPT_RECONCILIATION",
                    "recovery_action": "STOP_FOR_REVIEW",
                },
            )
        report = _validate_current(path, migrations)
        _remove_state(path)
        return CatalogUpgradeResult(
            path,
            MigrationResult(path, (), (), report),
            persisted_receipt,
        )

    backup_path = Path(str(state["backup_path"])).resolve()
    backup_evidence = _recovery_file_evidence(backup_path, "backup")
    if backup_evidence.sha256 != state["backup_sha256"]:
        raise CatalogUpgradeIntegrityError("Catalog upgrade backup bytes drifted")
    if _read_prefix(backup_path, migrations) != source_count:
        raise CatalogUpgradeIntegrityError("Catalog upgrade backup prefix drifted")

    current_evidence = _recovery_file_evidence(path, "Catalog")
    staged_path = Path(str(state["staged_path"])).resolve()
    if current_evidence.sha256 == receipt.source_catalog_sha256:
        if not staged_path.is_file():
            raise CatalogUpgradeIntegrityError(
                "Catalog still matches the source but its verified stage is missing"
            )
        staged_evidence = _recovery_file_evidence(staged_path, "stage")
        if staged_evidence.sha256 != receipt.staged_sha256_before_replace:
            raise CatalogUpgradeIntegrityError("Catalog upgrade staged bytes drifted")
        _validate_current(staged_path, migrations)
        atomic_replace_database(staged_path, path)
        state["phase"] = "REPLACED_PENDING_RECEIPT"
        _write_state(path, state)
    elif current_evidence.sha256 != receipt.staged_sha256_before_replace:
        raise CatalogUpgradeIntegrityError(
            "Catalog bytes match neither the admitted source nor verified replacement"
        )

    report = _validate_current(path, migrations)
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


def _write_rollback_receipt(
    path: Path,
    backup_root: Path,
    state: Mapping[str, object],
    source: BackupEvidence,
    backup: BackupEvidence,
    failed: Path,
    started_at: str,
) -> None:
    try:
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
            backup_root / f"catalog-upgrade-rollback-{state['operation_id']}.json",
            rollback_receipt,
        )
        _remove_state(path)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        CatalogUpgradeIntegrityError,
    ) as error:
        raise CatalogUpgradeIntegrityError(
            "Catalog rollback receipt or recovery state could not be finalized",
            details={
                "phase": "ROLLBACK_RECEIPT",
                "recovery_action": "STOP_FOR_REVIEW",
            },
        ) from error


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
        _wait_for_runtime_leases(path, busy_timeout_ms)
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
    migrations = _discover_migrations_for_upgrade(None)
    return _validate_current(path, migrations)


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
    migrations = _discover_migrations_for_upgrade(versions_dir)
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
        try:
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
        except (MigrationError, SchemaValidationError, sqlite3.DatabaseError, OSError) as error:
            raise CatalogUpgradeIntegrityError(
                "fresh Catalog migration or exact schema validation failed"
            ) from error

    started_at = _utc_now()
    applied_count = _read_prefix(path, migrations)
    if applied_count == len(migrations):
        report = _validate_current(path, migrations)
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
    except (
        MigrationError,
        SchemaValidationError,
        sqlite3.DatabaseError,
        OSError,
    ) as error:
        raise CatalogUpgradeIntegrityError(
            "staged Catalog migration or exact schema validation failed"
        ) from error
    _checkpoint_and_remove_sidecars(staged, busy_timeout_ms)
    _validate_current(staged, migrations)
    staged_content_sha256 = _catalog_content_sha256(staged)
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
        "staged_content_sha256": staged_content_sha256,
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
        report = _validate_current(path, migrations)
    except CatalogUpgradeIntegrityError as validation_error:
        _verify_rollback_backup(backup, source, migrations, applied_count)
        failed, restored = _rollback_paths(path, str(state["operation_id"]))
        state["phase"] = "ROLLBACK_PENDING_RESTORE"
        _write_state(path, state)
        try:
            copy_database_file_exact(backup.path, restored)
            _verify_rollback_file(
                restored,
                role="restore",
                expected_sha256=source.sha256,
                expected_byte_size=source.byte_size,
                migrations=migrations,
                applied_count=applied_count,
            )
        except (
            OSError,
            sqlite3.DatabaseError,
            CatalogMigrationPrefixUnrecognizedError,
            CatalogUpgradeIntegrityError,
        ) as restore_error:
            raise CatalogUpgradeIntegrityError(
                "verified Catalog backup could not be staged for rollback",
                details={
                    "phase": "ROLLBACK_BACKUP_EVIDENCE",
                    "recovery_action": "STOP_FOR_REVIEW",
                    "role": "restore",
                },
            ) from restore_error
        try:
            _preserve_failed_database(path, failed, busy_timeout_ms)
        except (OSError, sqlite3.DatabaseError, CatalogUpgradeIntegrityError) as preserve_error:
            raise CatalogUpgradeIntegrityError(
                "failed Catalog could not be preserved before rollback",
                details={
                    "phase": "ROLLBACK_FAILED_DATABASE",
                    "recovery_action": "STOP_FOR_REVIEW",
                },
            ) from preserve_error
        try:
            atomic_replace_database(restored, path)
        except OSError as restore_error:
            raise CatalogUpgradeIntegrityError(
                "verified Catalog backup could not be activated for rollback",
                details={
                    "phase": "ROLLBACK_RESTORE",
                    "recovery_action": "STOP_FOR_REVIEW",
                },
            ) from restore_error
        if _read_prefix(path, migrations) != applied_count:
            raise CatalogUpgradeIntegrityError(
                "restored Catalog migration prefix differs from the admitted source"
            ) from validation_error
        restored_evidence = database_file_evidence(path)
        if restored_evidence.sha256 != source.sha256:
            raise CatalogUpgradeIntegrityError(
                "restored Catalog bytes differ from the admitted source"
            ) from validation_error
        _write_rollback_receipt(
            path,
            backup_root,
            state,
            source,
            backup,
            failed,
            started_at,
        )
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
