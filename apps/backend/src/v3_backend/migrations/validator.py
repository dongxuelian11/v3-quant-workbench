from __future__ import annotations

import sqlite3
from dataclasses import dataclass


EXPECTED_USER_VERSION = 6
REQUIRED_TRIGGERS = frozenset(
    {
        "desktop_session_project_binding_immutable_guard",
        "desktop_session_project_context_owner_insert_guard",
        "desktop_session_project_context_owner_update_guard",
    }
)
_EXPECTED_TRIGGER_SQL = {
    "desktop_session_project_binding_immutable_guard": (
        "create trigger desktop_session_project_binding_immutable_guard "
        "before update of project_id on desktop_session "
        "when new.project_id<>old.project_id "
        "begin select raise(abort, 'desktop_session project binding is immutable'); end"
    ),
    "desktop_session_project_context_owner_insert_guard": (
        "create trigger desktop_session_project_context_owner_insert_guard "
        "before insert on desktop_session "
        "when not exists ( select 1 from project_context_revision "
        "where project_context_revision_id=new.project_context_revision_id "
        "and project_id=new.project_id ) "
        "begin select raise(abort, 'desktop_session project/context binding mismatch'); end"
    ),
    "desktop_session_project_context_owner_update_guard": (
        "create trigger desktop_session_project_context_owner_update_guard "
        "before update of project_id,project_context_revision_id on desktop_session "
        "when not exists ( select 1 from project_context_revision "
        "where project_context_revision_id=new.project_context_revision_id "
        "and project_id=new.project_id ) "
        "begin select raise(abort, 'desktop_session project/context binding mismatch'); end"
    ),
}
_EXPECTED_CANONICAL_SESSION_INDEX_SQL = (
    "create unique index desktop_session_canonical_uuid_unique "
    "on desktop_session(canonical_session_uuid) "
    "where canonical_session_uuid is not null"
)
EXPECTED_TABLES = frozenset(
    {
        "artifact",
        "artifact_reference",
        "backtest_run_spec",
        "checkpoint",
        "catalog_upgrade_receipt",
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
        "target_weight_vector_publication",
        "prediction_signal_version",
        "project",
        "project_context_revision",
        "publication_intent",
        "provenance_edge",
        "provenance_entity",
        "raw_capture",
        "resource_event",
        "result",
        "result_component",
        "risk_model_spec",
        "risk_model_version",
        "risk_policy_set_publication",
        "risk_application_receipt_publication",
        "risk_adjusted_weight_vector_publication",
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
        "task_output",
        "trial",
        "universe_definition",
        "universe_version",
        "worker",
        "worker_lease",
        "provider_descriptor",
        "connector_data_capability",
        "raw_capture_truth_descriptor",
        "snapshot_validation_profile",
        "snapshot_validation_requirement",
        "snapshot_validation_binding",
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


def _trigger_names(connection: sqlite3.Connection) -> frozenset[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    return frozenset(str(row[0]) for row in rows)


def _trigger_sql(connection: sqlite3.Connection, name: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    return " ".join(str(row[0]).casefold().split()) if row is not None else ""


def _require_trigger_shape(
    connection: sqlite3.Connection,
    name: str,
    error_message: str,
) -> None:
    if _trigger_sql(connection, name) != _EXPECTED_TRIGGER_SQL[name]:
        raise SchemaValidationError(error_message)


def _validate_required_trigger_shapes(connection: sqlite3.Connection) -> None:
    _require_trigger_shape(
        connection,
        "desktop_session_project_binding_immutable_guard",
        "desktop session binding trigger does not preserve same-project revision refresh",
    )

    _require_trigger_shape(
        connection,
        "desktop_session_project_context_owner_insert_guard",
        "desktop session insert trigger does not enforce project/context ownership",
    )
    _require_trigger_shape(
        connection,
        "desktop_session_project_context_owner_update_guard",
        "desktop session update trigger does not enforce project/context ownership",
    )


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
    session_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(desktop_session)")
    }
    if "canonical_session_uuid" not in session_columns:
        raise SchemaValidationError(
            "desktop_session is missing canonical_session_uuid identity"
        )
    canonical_index = next(
        (
            row
            for row in connection.execute("PRAGMA index_list(desktop_session)")
            if str(row[1]) == "desktop_session_canonical_uuid_unique"
        ),
        None,
    )
    if (
        canonical_index is None
        or int(canonical_index[2]) != 1
        or int(canonical_index[4]) != 1
    ):
        raise SchemaValidationError(
            "desktop_session canonical UUID index is not unique and partial"
        )
    canonical_index_columns = tuple(
        str(row[2])
        for row in connection.execute(
            'PRAGMA index_info("desktop_session_canonical_uuid_unique")'
        )
    )
    if canonical_index_columns != ("canonical_session_uuid",):
        raise SchemaValidationError(
            "desktop_session canonical UUID index has the wrong columns"
        )
    index_sql_row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type='index' AND name='desktop_session_canonical_uuid_unique'
        """
    ).fetchone()
    index_sql = (
        ""
        if index_sql_row is None or index_sql_row[0] is None
        else " ".join(str(index_sql_row[0]).casefold().split())
    )
    if index_sql != _EXPECTED_CANONICAL_SESSION_INDEX_SQL:
        raise SchemaValidationError(
            "desktop_session canonical UUID index predicate drifted"
        )
    invalid_session_uuid = connection.execute(
        """
        SELECT 1
        FROM desktop_session
        WHERE canonical_session_uuid IS NOT NULL
          AND (
            length(canonical_session_uuid)<>36
            OR length(replace(canonical_session_uuid,'-',''))<>32
            OR canonical_session_uuid<>lower(canonical_session_uuid)
            OR canonical_session_uuid GLOB '*[^0-9a-f-]*'
            OR substr(canonical_session_uuid,9,1)<>'-'
            OR substr(canonical_session_uuid,14,1)<>'-'
            OR substr(canonical_session_uuid,19,1)<>'-'
            OR substr(canonical_session_uuid,24,1)<>'-'
          )
        LIMIT 1
        """
    ).fetchone()
    if invalid_session_uuid is not None:
        raise SchemaValidationError(
            "desktop_session contains an invalid canonical UUID identity"
        )

    missing_triggers = sorted(REQUIRED_TRIGGERS - _trigger_names(connection))
    if missing_triggers:
        raise SchemaValidationError(
            f"required schema triggers are missing: {missing_triggers}"
        )
    _validate_required_trigger_shapes(connection)

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
    if applied != (
        "0001_control_catalog",
        "0002_data_truth",
        "0003_portfolio_riskpolicy_owner",
        "0004_risk_application_publication",
        "0005_task_execution_deadline",
        "0006_catalog_upgrade_session_integrity",
    ):
        raise SchemaValidationError(f"unexpected applied migration sequence: {applied!r}")

    first_fk_violation = connection.execute("PRAGMA foreign_key_check").fetchone()
    if first_fk_violation is not None:
        raise SchemaValidationError(
            f"foreign key violation: {tuple(first_fk_violation)!r}"
        )
    fk_violations: tuple[tuple[object, ...], ...] = ()

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
