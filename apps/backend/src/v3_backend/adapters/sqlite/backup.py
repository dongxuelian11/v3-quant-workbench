from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackupEvidence:
    path: Path
    sha256: str
    byte_size: int

    @property
    def artifact_id(self) -> str:
        return "art_sha256_" + self.sha256


def database_file_evidence(path: str | Path) -> BackupEvidence:
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return BackupEvidence(path, digest.hexdigest(), path.stat().st_size)


def sync_file(path: str | Path) -> None:
    # Windows rejects fsync on a read-only CRT descriptor even when the file
    # itself is readable. Open without truncation through a writable handle.
    with Path(path).resolve().open("r+b") as stream:
        os.fsync(stream.fileno())


def sync_directory(path: str | Path) -> None:
    directory = Path(path).resolve()
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        if os.name == "nt":
            # Python cannot portably fsync a Windows directory. Rename commit
            # points use MoveFileExW(MOVEFILE_WRITE_THROUGH) below instead.
            return
        raise
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _extended_windows_path(path: Path) -> str:
    value = str(path)
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def durable_replace_file(source_path: str | Path, destination_path: str | Path) -> None:
    source = Path(source_path).resolve()
    destination = Path(destination_path).resolve()
    if source.parent != destination.parent:
        raise ValueError("durable replacement must stay in one directory")
    if os.name != "nt":
        os.replace(source, destination)
        sync_directory(destination.parent)
        return

    import ctypes
    from ctypes import wintypes

    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file_ex.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
    move_file_ex.restype = wintypes.BOOL
    movefile_replace_existing = 0x1
    movefile_write_through = 0x8
    if not move_file_ex(
        _extended_windows_path(source),
        _extended_windows_path(destination),
        movefile_replace_existing | movefile_write_through,
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def atomic_replace_database(staged_path: str | Path, destination_path: str | Path) -> None:
    staged = Path(staged_path).resolve()
    destination = Path(destination_path).resolve()
    if staged.parent != destination.parent:
        raise ValueError("database replacement must stay in the destination directory")
    sync_file(staged)
    durable_replace_file(staged, destination)
    sync_file(destination)


def copy_database_file_exact(
    source_path: str | Path, destination_path: str | Path
) -> BackupEvidence:
    """Durably copy checkpointed database bytes without SQLite reserialization."""

    source = Path(source_path).resolve()
    destination = Path(destination_path).resolve()
    if source == destination:
        raise ValueError("source and destination database must differ")
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".staging")
    if temporary.exists():
        raise FileExistsError(temporary)
    try:
        with source.open("rb") as source_stream, temporary.open("xb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        durable_replace_file(temporary, destination)
        sync_file(destination)
    except Exception:
        if temporary.exists():
            incomplete = destination.with_name(destination.name + ".incomplete")
            try:
                durable_replace_file(temporary, incomplete)
                sync_file(incomplete)
            except OSError:
                # Preserve the original copy error. If even isolation cannot
                # complete, the uniquely named .staging file remains visible
                # for startup diagnosis instead of being mistaken for backup.
                pass
        raise
    evidence = database_file_evidence(destination)
    source_evidence = database_file_evidence(source)
    if evidence.sha256 != source_evidence.sha256 or evidence.byte_size != source_evidence.byte_size:
        incomplete = destination.with_name(destination.name + ".incomplete")
        durable_replace_file(destination, incomplete)
        sync_file(incomplete)
        raise OSError("exact database copy verification failed")
    return evidence


def _copy_database(source: Path, destination: Path) -> BackupEvidence:
    if source == destination:
        raise ValueError("source and destination database must differ")
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".staging")
    if temporary.exists():
        raise FileExistsError(temporary)
    source_connection = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    except Exception:
        destination_connection.close()
        source_connection.close()
        temporary.unlink(missing_ok=True)
        raise
    else:
        destination_connection.close()
        source_connection.close()
    sync_file(temporary)
    durable_replace_file(temporary, destination)
    sync_file(destination)
    return database_file_evidence(destination)


def backup_database(source_path: str | Path, backup_path: str | Path) -> BackupEvidence:
    return _copy_database(Path(source_path).resolve(), Path(backup_path).resolve())


def restore_database(backup_path: str | Path, destination_path: str | Path) -> BackupEvidence:
    """Restore only to a new database path; in-place restore is intentionally unavailable."""

    return _copy_database(Path(backup_path).resolve(), Path(destination_path).resolve())
