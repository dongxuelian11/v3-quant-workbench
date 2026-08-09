from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SQLiteConfig:
    database_path: Path
    busy_timeout_ms: int = 5_000
    read_only: bool = False


def connect_catalog(
    config: SQLiteConfig | str | Path, *, read_only: bool | None = None
) -> sqlite3.Connection:
    if isinstance(config, (str, Path)):
        config = SQLiteConfig(Path(config), read_only=bool(read_only))
    elif read_only is not None:
        config = SQLiteConfig(config.database_path, config.busy_timeout_ms, read_only)

    path = Path(config.database_path).resolve()
    if config.read_only:
        if not path.is_file():
            raise FileNotFoundError(path)
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro",
            uri=True,
            isolation_level=None,
            check_same_thread=True,
        )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, isolation_level=None, check_same_thread=True)

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {int(config.busy_timeout_ms)}")
    if config.read_only:
        connection.execute("PRAGMA query_only = ON")
    else:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
    return connection
