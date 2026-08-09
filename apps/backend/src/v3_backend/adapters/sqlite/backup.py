from __future__ import annotations

import hashlib
import os
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


def _evidence(path: Path) -> BackupEvidence:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return BackupEvidence(path, digest.hexdigest(), path.stat().st_size)


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
    os.replace(temporary, destination)
    return _evidence(destination)


def backup_database(source_path: str | Path, backup_path: str | Path) -> BackupEvidence:
    return _copy_database(Path(source_path).resolve(), Path(backup_path).resolve())


def restore_database(backup_path: str | Path, destination_path: str | Path) -> BackupEvidence:
    """Restore only to a new database path; in-place restore is intentionally unavailable."""

    return _copy_database(Path(backup_path).resolve(), Path(destination_path).resolve())
