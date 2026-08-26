from __future__ import annotations

import sqlite3
from dataclasses import dataclass


EXPECTED_USER_VERSION = 7
REQUIRED_TRIGGERS = frozenset(
    {
        "desktop_session_project_binding_immutable_guard",
        "desktop_session_project_context_owner_insert_guard",
        "desktop_session_project_context_owner_update_guard",
        "artifact_reference_gc_execution_barrier_i",
        "artifact_reference_gc_execution_barrier_u",
        "artifact_promotion_intent_gc_execution_barrier_i",
        "artifact_promotion_intent_gc_execution_barrier_u",
        "artifact_gc_execution_binding_guard_u",
        "artifact_gc_execution_metadata_guard_u",
        "artifact_gc_execution_quarantine_metadata_guard_u",
        "artifact_gc_active_reference_guard_u",
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
    "artifact_reference_gc_execution_barrier_i": (
        "create trigger artifact_reference_gc_execution_barrier_i "
        "before insert on artifact_reference "
        "when new.state='active' and exists ( select 1 from artifact_gc_batch as batch "
        "join artifact_quarantine as quarantine on quarantine.artifact_id=new.artifact_id "
        "where batch.state='executing' and ( (batch.phase='quarantine' "
        "and quarantine.gc_batch_id=batch.gc_batch_id and quarantine.state='moving') "
        "or (batch.phase='purge' and quarantine.state='quarantined' and exists ( "
        "select 1 from json_each(batch.exact_artifact_ids_json) "
        "where json_each.value=new.artifact_id )) ) ) "
        "begin select raise(abort,'artifact is under gc execution'); end"
    ),
    "artifact_reference_gc_execution_barrier_u": (
        "create trigger artifact_reference_gc_execution_barrier_u "
        "before update of artifact_id,state on artifact_reference "
        "when new.state='active' and exists ( select 1 from artifact_gc_batch as batch "
        "join artifact_quarantine as quarantine on quarantine.artifact_id=new.artifact_id "
        "where batch.state='executing' and ( (batch.phase='quarantine' "
        "and quarantine.gc_batch_id=batch.gc_batch_id and quarantine.state='moving') "
        "or (batch.phase='purge' and quarantine.state='quarantined' and exists ( "
        "select 1 from json_each(batch.exact_artifact_ids_json) "
        "where json_each.value=new.artifact_id )) ) ) "
        "begin select raise(abort,'artifact is under gc execution'); end"
    ),
    "artifact_promotion_intent_gc_execution_barrier_i": (
        "create trigger artifact_promotion_intent_gc_execution_barrier_i "
        "before insert on artifact_promotion_intent "
        "when new.state in ('staged_synced','final_present','catalog_committed','cleanup_pending') "
        "and exists ( select 1 from artifact_gc_batch as batch join artifact_quarantine as quarantine "
        "on quarantine.artifact_id=new.artifact_id where batch.state='executing' and ( "
        "(batch.phase='quarantine' and quarantine.gc_batch_id=batch.gc_batch_id and quarantine.state='moving') "
        "or (batch.phase='purge' and quarantine.state='quarantined' and exists ( "
        "select 1 from json_each(batch.exact_artifact_ids_json) where json_each.value=new.artifact_id )) ) ) "
        "begin select raise(abort,'artifact is under gc execution'); end"
    ),
    "artifact_promotion_intent_gc_execution_barrier_u": (
        "create trigger artifact_promotion_intent_gc_execution_barrier_u "
        "before update of artifact_id,state on artifact_promotion_intent "
        "when new.state in ('staged_synced','final_present','catalog_committed','cleanup_pending') "
        "and exists ( select 1 from artifact_gc_batch as batch join artifact_quarantine as quarantine "
        "on quarantine.artifact_id=new.artifact_id where batch.state='executing' and ( "
        "(batch.phase='quarantine' and quarantine.gc_batch_id=batch.gc_batch_id and quarantine.state='moving') "
        "or (batch.phase='purge' and quarantine.state='quarantined' and exists ( "
        "select 1 from json_each(batch.exact_artifact_ids_json) where json_each.value=new.artifact_id )) ) ) "
        "begin select raise(abort,'artifact is under gc execution'); end"
    ),
    "artifact_gc_execution_binding_guard_u": (
        "create trigger artifact_gc_execution_binding_guard_u "
        "before update of phase,scope_owner_id,plan_artifact_id, "
        "reachability_fingerprint,exact_artifact_ids_hash,exact_artifact_ids_json, "
        "open_intent_ids_json,confirmation_nonce,confirmation_hash,created_at,expires_at "
        "on artifact_gc_batch when old.state='executing' "
        "begin select raise(abort,'gc batch binding is immutable during execution'); end"
    ),
    "artifact_gc_execution_metadata_guard_u": (
        "create trigger artifact_gc_execution_metadata_guard_u "
        "before update on artifact when exists ( select 1 from artifact_gc_batch as batch "
        "where batch.state='executing' and exists ( select 1 from json_each(batch.exact_artifact_ids_json) "
        "where json_each.value=old.artifact_id ) ) and ( new.artifact_id is not old.artifact_id "
        "or new.sha256 is not old.sha256 or new.byte_size is not old.byte_size "
        "or new.media_type is not old.media_type or new.semantic_role is not old.semantic_role "
        "or new.storage_key is not old.storage_key or new.safe_format_id is not old.safe_format_id "
        "or new.schema_fingerprint is not old.schema_fingerprint or new.created_at is not old.created_at "
        "or new.published_at is not old.published_at ) "
        "begin select raise(abort,'artifact metadata is immutable during gc execution'); end"
    ),
    "artifact_gc_execution_quarantine_metadata_guard_u": (
        "create trigger artifact_gc_execution_quarantine_metadata_guard_u "
        "before update on artifact_quarantine when exists ( select 1 from artifact_gc_batch as batch "
        "where batch.state='executing' and ( batch.gc_batch_id=old.gc_batch_id or ( batch.phase='purge' "
        "and exists ( select 1 from json_each(batch.exact_artifact_ids_json) "
        "where json_each.value=old.artifact_id ) ) ) ) and ( new.artifact_id is not old.artifact_id "
        "or new.gc_batch_id is not old.gc_batch_id "
        "or new.quarantine_storage_key is not old.quarantine_storage_key "
        "or new.original_storage_key is not old.original_storage_key "
        "or new.quarantined_at is not old.quarantined_at "
        "or new.purge_not_before is not old.purge_not_before ) "
        "begin select raise(abort,'gc quarantine metadata is immutable during execution'); end"
    ),
    "artifact_gc_active_reference_guard_u": (
        "create trigger artifact_gc_active_reference_guard_u "
        "before update of state on artifact "
        "when new.state in ('quarantined','deleted') and exists ( "
        "select 1 from artifact_reference where artifact_id=new.artifact_id "
        "and state='active' ) "
        "begin select raise(abort,'reachable artifact cannot leave published state'); end"
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
        "artifact_gc_batch",
        "artifact_gc_request",
        "artifact_gc_receipt",
        "artifact_promotion_intent",
        "artifact_quarantine",
        "artifact_storage_error",
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

_EXPECTED_COLUMN_SHAPES = {
    "artifact_promotion_intent": (
        ("promotion_intent_id", "TEXT", 0, None, 1),
        ("artifact_id", "TEXT", 1, None, 0),
        ("expected_sha256", "TEXT", 1, None, 0),
        ("expected_byte_size", "INTEGER", 1, None, 0),
        ("staging_token", "TEXT", 1, None, 0),
        ("staging_key", "TEXT", 1, None, 0),
        ("final_storage_key", "TEXT", 1, None, 0),
        ("state", "TEXT", 1, None, 0),
        ("state_version", "INTEGER", 1, None, 0),
        ("descriptor_json", "TEXT", 1, None, 0),
        ("references_json", "TEXT", 1, None, 0),
        ("created_at", "TEXT", 1, None, 0),
        ("updated_at", "TEXT", 1, None, 0),
        ("finalized_at", "TEXT", 0, None, 0),
        ("last_error_code", "TEXT", 0, None, 0),
        ("last_error_detail_artifact_id", "TEXT", 0, None, 0),
    ),
    "artifact_storage_error": (
        ("storage_error_id", "TEXT", 0, None, 1),
        ("promotion_intent_id", "TEXT", 0, None, 0),
        ("artifact_id", "TEXT", 0, None, 0),
        ("phase", "TEXT", 1, None, 0),
        ("error_code", "TEXT", 1, None, 0),
        ("observed_state_json", "TEXT", 1, None, 0),
        ("created_at", "TEXT", 1, None, 0),
        ("resolved_at", "TEXT", 0, None, 0),
    ),
    "artifact_gc_batch": (
        ("gc_batch_id", "TEXT", 0, None, 1),
        ("phase", "TEXT", 1, None, 0),
        ("scope_owner_id", "TEXT", 1, None, 0),
        ("plan_artifact_id", "TEXT", 1, None, 0),
        ("reachability_fingerprint", "TEXT", 1, None, 0),
        ("exact_artifact_ids_hash", "TEXT", 1, None, 0),
        ("exact_artifact_ids_json", "TEXT", 1, None, 0),
        ("open_intent_ids_json", "TEXT", 1, None, 0),
        ("confirmation_nonce", "TEXT", 0, None, 0),
        ("confirmation_hash", "TEXT", 0, None, 0),
        ("state", "TEXT", 1, None, 0),
        ("created_at", "TEXT", 1, None, 0),
        ("expires_at", "TEXT", 1, None, 0),
        ("confirmed_at", "TEXT", 0, None, 0),
        ("completed_at", "TEXT", 0, None, 0),
    ),
    "artifact_gc_request": (
        ("request_scope_key", "TEXT", 0, None, 1),
        ("operation_id", "TEXT", 1, None, 0),
        ("scope_owner_id", "TEXT", 1, None, 0),
        ("canonical_request_hash", "TEXT", 1, None, 0),
        ("phase", "TEXT", 1, None, 0),
        ("plan_json", "TEXT", 1, None, 0),
        ("reachable_artifact_count", "INTEGER", 1, None, 0),
        ("plan_artifact_id", "TEXT", 0, None, 0),
        ("gc_batch_id", "TEXT", 0, None, 0),
        ("state", "TEXT", 1, None, 0),
        ("outcome_json", "TEXT", 0, None, 0),
        ("created_at", "TEXT", 1, None, 0),
        ("updated_at", "TEXT", 1, None, 0),
    ),
    "artifact_quarantine": (
        ("artifact_id", "TEXT", 1, None, 1),
        ("gc_batch_id", "TEXT", 1, None, 2),
        ("quarantine_storage_key", "TEXT", 1, None, 0),
        ("original_storage_key", "TEXT", 1, None, 0),
        ("quarantined_at", "TEXT", 1, None, 0),
        ("purge_not_before", "TEXT", 1, None, 0),
        ("state", "TEXT", 1, None, 0),
    ),
    "artifact_gc_receipt": (
        ("receipt_id", "TEXT", 0, None, 1),
        ("gc_batch_id", "TEXT", 1, None, 0),
        ("result", "TEXT", 1, None, 0),
        ("exact_artifact_ids_hash", "TEXT", 1, None, 0),
        ("exact_bytes", "INTEGER", 1, None, 0),
        ("reclaimed_bytes", "INTEGER", 1, None, 0),
        ("created_at", "TEXT", 1, None, 0),
        ("details_json", "TEXT", 1, None, 0),
    ),
    "catalog_upgrade_receipt": (
        ("operation_id", "TEXT", 0, None, 1),
        ("source_catalog_path_fingerprint", "TEXT", 1, None, 0),
        ("source_catalog_sha256", "TEXT", 1, None, 0),
        ("source_schema_prefix_json", "TEXT", 1, None, 0),
        ("target_schema_prefix_json", "TEXT", 1, None, 0),
        ("backup_path_fingerprint", "TEXT", 0, None, 0),
        ("backup_sha256", "TEXT", 0, None, 0),
        ("staged_sha256_before_replace", "TEXT", 1, None, 0),
        ("final_catalog_sha256", "TEXT", 1, None, 0),
        ("integrity_check", "TEXT", 1, None, 0),
        ("foreign_key_check", "TEXT", 1, None, 0),
        ("replacement_mode", "TEXT", 1, None, 0),
        ("started_at", "TEXT", 1, None, 0),
        ("committed_at", "TEXT", 1, None, 0),
        ("recovery_action", "TEXT", 1, None, 0),
        ("result", "TEXT", 1, None, 0),
        ("error_code", "TEXT", 0, None, 0),
    ),
}


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
    for name in (
        "artifact_reference_gc_execution_barrier_i",
        "artifact_reference_gc_execution_barrier_u",
        "artifact_promotion_intent_gc_execution_barrier_i",
        "artifact_promotion_intent_gc_execution_barrier_u",
        "artifact_gc_execution_binding_guard_u",
        "artifact_gc_execution_metadata_guard_u",
        "artifact_gc_execution_quarantine_metadata_guard_u",
        "artifact_gc_active_reference_guard_u",
    ):
        _require_trigger_shape(
            connection,
            name,
            "Artifact GC execution guard shape is not canonical",
        )


def _validate_required_column_shapes(connection: sqlite3.Connection) -> None:
    for table_name, expected in _EXPECTED_COLUMN_SHAPES.items():
        quoted_table_name = '"' + table_name.replace('"', '""') + '"'
        actual = tuple(
            (
                str(row[1]),
                str(row[2]).upper(),
                int(row[3]),
                None if row[4] is None else str(row[4]),
                int(row[5]),
            )
            for row in connection.execute(
                f"PRAGMA table_info({quoted_table_name})"
            )
        )
        if actual != expected:
            raise SchemaValidationError(
                f"{table_name} column shape is not the admitted catalog upgrade receipt schema"
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

    lifecycle_tables = {
        "artifact_promotion_intent",
        "artifact_storage_error",
        "artifact_gc_batch",
        "artifact_gc_request",
        "artifact_quarantine",
        "artifact_gc_receipt",
    }
    for table_row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ):
        table = str(table_row[0])
        if table == "artifact" or table in lifecycle_tables:
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
    _validate_required_column_shapes(connection)
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
        "0007_artifact_promotion_gc",
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
