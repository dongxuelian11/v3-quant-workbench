from __future__ import annotations

import json
import sqlite3
import sys


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: v1-release-catalog-probe.py <catalog.sqlite3>")
    connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("task", "run", "result", "raw_capture", "artifact")
        }
        row = connection.execute(
            "SELECT source_metadata_json FROM raw_capture_truth_descriptor "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        metadata = None if row is None else json.loads(str(row["source_metadata_json"]))
        artifact_roles = [
            str(item[0])
            for item in connection.execute(
                "SELECT semantic_role FROM artifact ORDER BY semantic_role"
            )
        ]
        print(
            json.dumps(
                {
                    "counts": counts,
                    "source_metadata": metadata,
                    "artifact_roles": artifact_roles,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
