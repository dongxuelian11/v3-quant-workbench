from __future__ import annotations

import sqlite3
from dataclasses import dataclass


EXPECTED_USER_VERSION = 2
EXPECTED_TABLES = frozenset(
    {
        "artifact",
        "artifact_reference",
        "backtest_run_spec",
        "checkpoint",
        "connector",
        "connector_admission",
        "connector_capability",
        "connector_version",
        "constraint_set_version",
        "credential_reference",
        "data_snapshot",
        "dataset_spec",
        "dataset_version",
        "desktop_session",
        "experiment",
        "factor_definition",
        "factor_version",
        "idempotency_record",
        "industry_membership",
        "industry_taxonomy_version",
        "instrument",
        "instrument_alias",
        "instrument_revision",
        "model_spec",
        "model_version",
        "optimization_problem",
        "optimization_solution",
        "portfolio_construction_spec",
        "portfolio_version",
        "prediction_signal_version",
        "project",
        "project_context_revision",
        "provenance_edge",
        "provenance_entity",
        "raw_capture",
        "resource_event",
        "result",
        "result_component",
        "risk_model_spec",
        "risk_model_version",
        "run",
        "schema_migration",
        "snapshot_partition",
        "snapshot_validation",
        "strategy_draft",
        "strategy_version",
        "study",
        "task",
        "task_attempt",
        "task_dependency",
        "task_event",
        "trial",
        "universe_definition",
        "universe_version",
        "worker",
        "worker_lease",
        "provider_descriptor",
        "provider_capability",
        "instrument_classification",
        "raw_capture_truth_descriptor",
        "trading_calendar_version",
        "trading_session",
        "snapshot_raw_capture",
        "snapshot_calendar",
        "corporate_action",
        "adjustment_factor_version",
        "universe_membership_interval",
    }
)


class SchemaValidationError(RuntimeError):
    """The database is not an exact, internally valid v1 Control Catalog."""


@dataclass(frozen=True)
class SchemaReport:
    table_count: int
    user_version: int
    applied_migrations: tuple[str, ...]
    foreign_key_violations: tuple[tuple[object, ...], ...]
    integrity_check: str
    invariant_violations: tuple[str, ...]


def _table_names(connection: sqlite3.Connection) -> frozenset[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return frozenset(str(row[0]) for row in rows)


def _invariant_violations(connection: sqlite3.Connection) -> list[str]:
    violations: list[str] = []
    duplicate_lease = connection.execute(
        """
        SELECT attempt_id FROM worker_lease
        WHERE state IN ('GRANTED','RENEWED')
        GROUP BY attempt_id HAVING COUNT(*) > 1 LIMIT 1
        """
    ).fetchone()
    if duplicate_lease is not None:
        violations.append("multiple active leases for one Attempt")

    alias_overlap = connection.execute(
        """
        SELECT 1
        FROM instrument_alias AS left_alias
        JOIN instrument_alias AS right_alias
          ON left_alias.instrument_alias_id < right_alias.instrument_alias_id
         AND left_alias.connector_version_id = right_alias.connector_version_id
         AND left_alias.provider_code = right_alias.provider_code
         AND (left_alias.effective_to IS NULL OR right_alias.effective_from < left_alias.effective_to)
         AND (right_alias.effective_to IS NULL OR left_alias.effective_from < right_alias.effective_to)
        LIMIT 1
        """
    ).fetchone()
    if alias_overlap is not None:
        violations.append("overlapping provider aliases")

    bad_universe = connection.execute(
        """
        SELECT 1 FROM project_context_revision AS revision
        LEFT JOIN universe_version AS universe
          ON universe.universe_version_id = revision.universe_version_id
        WHERE revision.universe_version_id IS NOT NULL
          AND (universe.universe_version_id IS NULL OR universe.state <> 'PUBLISHED')
        LIMIT 1
        """
    ).fetchone()
    if bad_universe is not None:
        violations.append("ProjectContext revision references missing or unpublished UniverseVersion")

    bad_snapshot = connection.execute(
        """
        SELECT 1 FROM project_context_revision AS revision
        LEFT JOIN data_snapshot AS snapshot ON snapshot.snapshot_id=revision.snapshot_id
        WHERE revision.snapshot_id IS NOT NULL
          AND (snapshot.snapshot_id IS NULL OR snapshot.state<>'PUBLISHED')
        LIMIT 1
        """
    ).fetchone()
    if bad_snapshot is not None:
        violations.append("ProjectContext revision references missing or unpublished SnapshotVersion")

    incompatible_pin = connection.execute(
        """
        SELECT 1 FROM project_context_revision AS revision
        JOIN universe_version AS universe ON universe.universe_version_id=revision.universe_version_id
        WHERE revision.snapshot_id IS NOT NULL AND universe.snapshot_id<>revision.snapshot_id
        LIMIT 1
        """
    ).fetchone()
    if incompatible_pin is not None:
        violations.append("ProjectContext Snapshot and Universe pins are incompatible")

    for table_row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ):
        table = str(table_row[0])
        if table == "artifact":
            continue
        columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]
        for column in columns:
            if column == "artifact_id" or column.endswith("_artifact_id"):
                # Catalog backup evidence predates the WS-C Artifact publication
                # integration and is explicitly an external boundary in WS-B.
                if table == "schema_migration" and column == "backup_artifact_id":
                    continue
                orphan = connection.execute(
                    f"""
                    SELECT 1 FROM "{table}" AS owner
                    LEFT JOIN artifact ON artifact.artifact_id = owner."{column}"
                    WHERE owner."{column}" IS NOT NULL
                      AND (artifact.artifact_id IS NULL OR artifact.state <> 'PUBLISHED')
                    LIMIT 1
                    """
                ).fetchone()
                if orphan is not None:
                    violations.append(f"{table}.{column} reaches a missing or unpublished Artifact")
    return violations


def validate_schema(connection: sqlite3.Connection, *, exact: bool = True) -> SchemaReport:
    tables = _table_names(connection)
    if exact and tables != EXPECTED_TABLES:
        missing = sorted(EXPECTED_TABLES - tables)
        extra = sorted(tables - EXPECTED_TABLES)
        raise SchemaValidationError(f"schema table mismatch: missing={missing}, extra={extra}")

    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version != EXPECTED_USER_VERSION:
        raise SchemaValidationError(
            f"expected user_version={EXPECTED_USER_VERSION}, observed {user_version}"
        )

    applied = tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT migration_id FROM schema_migration WHERE state='APPLIED' ORDER BY migration_id"
        )
    )
    if applied != ("0001_control_catalog", "0002_data_truth"):
        raise SchemaValidationError(f"unexpected applied migration sequence: {applied!r}")

    fk_violations = tuple(tuple(row) for row in connection.execute("PRAGMA foreign_key_check"))
    if fk_violations:
        raise SchemaValidationError(f"foreign key violations: {fk_violations!r}")

    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    if integrity != "ok":
        raise SchemaValidationError(f"integrity_check failed: {integrity}")

    violations = tuple(_invariant_violations(connection))
    if violations:
        raise SchemaValidationError(f"logical invariant violations: {violations!r}")

    return SchemaReport(
        table_count=len(tables),
        user_version=user_version,
        applied_migrations=applied,
        foreign_key_violations=fk_violations,
        integrity_check=integrity,
        invariant_violations=violations,
    )
