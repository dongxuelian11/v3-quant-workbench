from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from v3_backend.domain.data_truth.model import (
    CapabilityTruthState,
    ConnectorCapabilityResolution,
    RevisionSemantics,
    UniverseResolution,
)
from v3_backend.domain.data_truth.pit import PitCapabilityUnavailable
from v3_backend.errors.exceptions import (
    ArtifactNotPublishedError,
    ConflictError,
    InvalidArgumentError,
    NotFoundError,
)
from v3_backend.provenance.canonical_hash import canonical_json
from v3_backend.repositories.unit_of_work import TransactionMode

from .unit_of_work import SQLiteUnitOfWork


MAX_JSON_BYTES = 64 * 1024
MAX_INLINE_NUMERIC_ITEMS = 256
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")

_REPOSITORY_TABLES: dict[str, frozenset[str]] = {
    "project": frozenset({"project", "project_context_revision", "desktop_session"}),
    "connector": frozenset(
        {"connector", "connector_version", "connector_capability", "connector_admission", "credential_reference"}
    ),
    "instrument": frozenset({"instrument", "instrument_revision", "instrument_alias"}),
    "snapshot": frozenset(
        {
            "data_snapshot",
            "raw_capture",
            "snapshot_partition",
            "snapshot_validation",
            "snapshot_validation_profile",
            "snapshot_validation_requirement",
            "snapshot_validation_binding",
            "industry_taxonomy_version",
            "industry_membership",
        }
    ),
    "universe": frozenset({"universe_definition", "universe_version"}),
    "factor": frozenset({"factor_definition", "factor_version"}),
    "dataset": frozenset({"dataset_spec", "dataset_version"}),
    "strategy": frozenset({"strategy_draft", "strategy_version"}),
    "model": frozenset({"model_spec", "model_version", "prediction_signal_version"}),
    "study": frozenset({"study", "trial", "checkpoint"}),
    "portfolio": frozenset(
        {
            "portfolio_construction_spec",
            "portfolio_version",
            "target_weight_vector_publication",
        }
    ),
    "risk": frozenset(
        {"risk_model_spec", "risk_model_version", "risk_policy_set_publication"}
    ),
    "optimization": frozenset({"constraint_set_version", "optimization_problem", "optimization_solution"}),
    "backtest": frozenset({"experiment", "backtest_run_spec"}),
    "result": frozenset({"result", "result_component"}),
    "task": frozenset({"task", "run", "task_attempt", "task_dependency", "task_event", "idempotency_record"}),
    "artifact": frozenset({"artifact", "artifact_reference"}),
    "provenance": frozenset({"provenance_entity", "provenance_edge"}),
    "data_truth": frozenset(
        {
            "provider_descriptor",
            "connector_data_capability",
            "raw_capture",
            "raw_capture_truth_descriptor",
            "trading_calendar_version",
            "trading_session",
            "snapshot_raw_capture",
            "snapshot_calendar",
            "corporate_action",
            "adjustment_factor_version",
            "universe_membership_interval",
        }
    ),
}
_IMMUTABLE_TABLES = frozenset(
    {
        "project_context_revision",
        "connector_version",
        "instrument_revision",
        "instrument_alias",
        "raw_capture",
        "snapshot_partition",
        "snapshot_validation",
        "industry_taxonomy_version",
        "industry_membership",
        "factor_version",
        "constraint_set_version",
        "backtest_run_spec",
        "task_dependency",
        "task_event",
        "idempotency_record",
        "checkpoint",
        "result_component",
        "provenance_entity",
        "provenance_edge",
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
        "target_weight_vector_publication",
        "risk_policy_set_publication",
    }
)


def _row_dict(row: sqlite3.Row | Sequence[Any], columns: Sequence[str] | None = None) -> dict[str, Any]:
    if isinstance(row, sqlite3.Row):
        return {key: row[key] for key in row.keys()}
    if columns is None:
        raise TypeError("columns are required for tuple rows")
    return dict(zip(columns, row, strict=True))


def _parse_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidArgumentError("PIT timestamps must be timezone-aware")
    return parsed


def _count_numeric_array_items(value: Any) -> int:
    if isinstance(value, list):
        if value and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
            return len(value)
        return sum(_count_numeric_array_items(item) for item in value)
    if isinstance(value, Mapping):
        return sum(_count_numeric_array_items(item) for item in value.values())
    return 0


def canonical_bounded_json(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise InvalidArgumentError("JSON metadata is not valid") from exc
    if _count_numeric_array_items(value) > MAX_INLINE_NUMERIC_ITEMS:
        raise InvalidArgumentError(
            "variable-length numerical payload must be stored as an ArtifactRef",
            details={"max_inline_numeric_items": MAX_INLINE_NUMERIC_ITEMS},
        )
    text = canonical_json(value)
    size = len(text.encode("utf-8"))
    if size > MAX_JSON_BYTES:
        raise InvalidArgumentError(
            "Catalog JSON metadata exceeds the 64 KiB limit",
            details={"max_bytes": MAX_JSON_BYTES, "actual_bytes": size},
        )
    return text


class SQLiteTableRepository:
    def __init__(self, unit_of_work: SQLiteUnitOfWork, table_name: str) -> None:
        if _IDENTIFIER.fullmatch(table_name) is None:
            raise ValueError(f"invalid table name: {table_name!r}")
        self.uow = unit_of_work
        self.connection = unit_of_work.connection
        self.table_name = table_name
        table_exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        ).fetchone()
        if table_exists is None:
            raise ValueError(f"unknown Catalog table: {table_name}")
        info = tuple(self.connection.execute(f'PRAGMA table_info("{table_name}")'))
        self.columns = tuple(str(row[1]) for row in info)
        self.primary_key = tuple(
            str(row[1]) for row in sorted((row for row in info if int(row[5]) > 0), key=lambda row: int(row[5]))
        )
        self.version_column = "row_version" if "row_version" in self.columns else (
            "state_version" if "state_version" in self.columns else None
        )
        self.order_columns = (
            ("created_at", self.primary_key[0])
            if "created_at" in self.columns and len(self.primary_key) == 1
            else self.primary_key
        )

    def _assert_active(self, *, write: bool = False) -> None:
        if not self.uow.active:
            raise RuntimeError("repository access requires an active UnitOfWork")
        if write and self.uow.mode is TransactionMode.READ_ONLY:
            raise RuntimeError("writes are forbidden in READ_ONLY mode")

    def _identity_clause(self, identity: str | Mapping[str, Any]) -> tuple[str, tuple[Any, ...]]:
        if isinstance(identity, Mapping):
            if set(identity) != set(self.primary_key):
                raise ValueError(f"identity must provide composite key {self.primary_key!r}")
            return (
                " AND ".join(f'"{column}"=?' for column in self.primary_key),
                tuple(identity[column] for column in self.primary_key),
            )
        if len(self.primary_key) != 1:
            raise ValueError(f"{self.table_name} uses a composite primary key")
        return f'"{self.primary_key[0]}"=?', (identity,)

    def _normalize(self, row: Mapping[str, Any]) -> dict[str, Any]:
        unknown = set(row) - set(self.columns)
        if unknown:
            raise InvalidArgumentError(
                f"unknown fields for {self.table_name}",
                details={"fields": sorted(unknown)},
            )
        normalized = dict(row)
        for column, value in tuple(normalized.items()):
            if column.endswith("_json") and value is not None:
                normalized[column] = canonical_bounded_json(value)
            if isinstance(value, (bytes, bytearray, memoryview)):
                raise InvalidArgumentError("binary payloads are forbidden in the Control Catalog")
        return normalized

    def get(self, identity: str | Mapping[str, Any]) -> dict[str, Any] | None:
        self._assert_active()
        clause, parameters = self._identity_clause(identity)
        row = self.connection.execute(
            f'SELECT * FROM "{self.table_name}" WHERE {clause}', parameters
        ).fetchone()
        return None if row is None else _row_dict(row, self.columns)

    def require(self, identity: str | Mapping[str, Any]) -> dict[str, Any]:
        row = self.get(identity)
        if row is None:
            raise NotFoundError(
                f"{self.table_name} not found", details={"identity": dict(identity) if isinstance(identity, Mapping) else identity}
            )
        return row

    def add_new(
        self, aggregate: Mapping[str, Any], *, idempotent: bool = False
    ) -> dict[str, Any]:
        self._assert_active(write=True)
        row = self._normalize(aggregate)
        if not row:
            raise InvalidArgumentError("cannot insert an empty aggregate")
        columns = tuple(row)
        sql = (
            f'INSERT INTO "{self.table_name}" ('
            + ",".join(f'"{column}"' for column in columns)
            + ") VALUES ("
            + ",".join("?" for _ in columns)
            + ")"
        )
        try:
            self.connection.execute(sql, tuple(row[column] for column in columns))
        except sqlite3.IntegrityError as exc:
            if idempotent and self.primary_key and all(column in row for column in self.primary_key):
                identity = {column: row[column] for column in self.primary_key}
                existing = self.get(identity)
                if existing is not None and all(existing.get(key) == value for key, value in row.items()):
                    return existing
            raise ConflictError(
                f"cannot insert {self.table_name}", details={"sqlite_error": str(exc)}
            ) from exc
        identity = {column: row[column] for column in self.primary_key}
        return self.require(identity)

    def save(
        self,
        identity: str | Mapping[str, Any],
        changes: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        self._assert_active(write=True)
        if self.table_name in _IMMUTABLE_TABLES:
            raise ConflictError(f"{self.table_name} is append-only")
        if self.version_column is None:
            raise ConflictError(f"{self.table_name} has no optimistic version column")
        normalized = self._normalize(changes)
        for primary in self.primary_key:
            if primary in normalized:
                raise InvalidArgumentError("primary key mutation is forbidden")
        normalized.pop(self.version_column, None)
        if not normalized:
            raise InvalidArgumentError("save requires at least one changed field")
        clause, identity_values = self._identity_clause(identity)
        assignments = ",".join(f'"{column}"=?' for column in normalized)
        sql = (
            f'UPDATE "{self.table_name}" SET {assignments},'
            f'"{self.version_column}"="{self.version_column}"+1 '
            f'WHERE {clause} AND "{self.version_column}"=?'
        )
        cursor = self.connection.execute(
            sql,
            tuple(normalized.values()) + identity_values + (expected_version,),
        )
        if cursor.rowcount != 1:
            if self.get(identity) is None:
                raise NotFoundError(f"{self.table_name} not found")
            raise ConflictError(
                "optimistic concurrency conflict",
                details={"expected_version": expected_version},
            )
        return self.require(identity)

    def list_page(
        self,
        filters: Mapping[str, Any] | None = None,
        *,
        cursor: Sequence[Any] | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        self._assert_active()
        if not 1 <= limit <= 1_000:
            raise InvalidArgumentError("limit must be between 1 and 1000")
        filters = dict(filters or {})
        if set(filters) - set(self.columns):
            raise InvalidArgumentError("filter contains an unknown column")
        clauses = [f'"{column}"=?' for column in filters]
        parameters: list[Any] = list(filters.values())
        if cursor is not None:
            if not self.order_columns or len(cursor) != len(self.order_columns):
                raise InvalidArgumentError("invalid keyset cursor")
            tuple_columns = ",".join(f'"{column}"' for column in self.order_columns)
            clauses.append(f"({tuple_columns}) > ({','.join('?' for _ in cursor)})")
            parameters.extend(cursor)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        order = ",".join(f'"{column}"' for column in self.order_columns) or "rowid"
        rows = self.connection.execute(
            f'SELECT * FROM "{self.table_name}"{where} ORDER BY {order} LIMIT ?',
            tuple(parameters) + (limit,),
        ).fetchall()
        return tuple(_row_dict(row, self.columns) for row in rows)


class SQLiteDomainRepository:
    def __init__(self, unit_of_work: SQLiteUnitOfWork, domain: str) -> None:
        self.uow = unit_of_work
        try:
            self.allowed_tables = _REPOSITORY_TABLES[domain]
        except KeyError as exc:
            raise ValueError(f"unknown repository domain: {domain}") from exc

    def table(self, table_name: str) -> SQLiteTableRepository:
        if table_name not in self.allowed_tables:
            raise ValueError(f"{table_name} is outside this repository boundary")
        return SQLiteTableRepository(self.uow, table_name)

    def publish_version(
        self,
        table_name: str,
        aggregate: Mapping[str, Any],
        *,
        provenance_entities: Sequence[Mapping[str, Any]] = (),
        provenance_edges: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        repository = self.table(table_name)
        if "state" in repository.columns and aggregate.get("state") != "PUBLISHED":
            raise InvalidArgumentError("publish_version requires state=PUBLISHED")
        published = repository.add_new(aggregate, idempotent=True)
        provenance = SQLiteProvenanceRepository(self.uow)
        for entity in provenance_entities:
            provenance.record_entity_once(entity)
        for edge in provenance_edges:
            provenance.record_edge_once(edge)
        return published


class SQLiteProjectRepository(SQLiteDomainRepository):
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "project")

    def get(self, project_id: str) -> dict[str, Any] | None:
        return self.table("project").get(project_id)

    def require(self, project_id: str) -> dict[str, Any]:
        return self.table("project").require(project_id)

    def add_new(self, aggregate: Mapping[str, Any], *, idempotent: bool = False) -> dict[str, Any]:
        return self.table("project").add_new(aggregate, idempotent=idempotent)

    def save(
        self, project_id: str, changes: Mapping[str, Any], *, expected_version: int
    ) -> dict[str, Any]:
        return self.table("project").save(project_id, changes, expected_version=expected_version)

    def get_current_revision(self, project_id: str) -> dict[str, Any] | None:
        self.table("project_context_revision")._assert_active()
        row = self.uow.connection.execute(
            """
            SELECT * FROM project_context_revision
            WHERE project_id=? ORDER BY revision_no DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        return None if row is None else _row_dict(row)

    def append_revision(
        self, revision: Mapping[str, Any], *, base_revision_id: str | None
    ) -> dict[str, Any]:
        current = self.get_current_revision(str(revision["project_id"]))
        if current is None:
            if base_revision_id is not None:
                raise ConflictError("first ProjectContext revision must have no base")
            expected_no = 1
            expected_parent = None
        else:
            if current["project_context_revision_id"] != base_revision_id:
                raise ConflictError("ProjectContext base revision is stale")
            expected_no = int(current["revision_no"]) + 1
            expected_parent = base_revision_id
        if int(revision.get("revision_no", expected_no)) != expected_no:
            raise ConflictError("ProjectContext revision number is not append-only")
        row = dict(revision)
        row["revision_no"] = expected_no
        row["parent_revision_id"] = expected_parent
        return self.table("project_context_revision").add_new(row)


class SQLiteInstrumentRepository(SQLiteDomainRepository):
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "instrument")

    def add_alias(self, alias: Mapping[str, Any]) -> dict[str, Any]:
        repository = self.table("instrument_alias")
        repository._assert_active(write=True)
        start = str(alias["effective_from"])
        end = alias.get("effective_to")
        overlap = self.uow.connection.execute(
            """
            SELECT instrument_alias_id FROM instrument_alias
            WHERE connector_version_id=? AND provider_code=?
              AND (effective_to IS NULL OR effective_to > ?)
              AND (? IS NULL OR effective_from < ?)
            LIMIT 1
            """,
            (
                alias["connector_version_id"],
                alias["provider_code"],
                start,
                end,
                end,
            ),
        ).fetchone()
        if overlap is not None:
            raise ConflictError("provider alias interval overlaps an existing alias")
        return repository.add_new(alias)

    def resolve_alias(
        self, connector_version_id: str, provider_code: str, as_of: str
    ) -> dict[str, Any] | None:
        repository = self.table("instrument_alias")
        repository._assert_active()
        rows = self.uow.connection.execute(
            """
            SELECT * FROM instrument_alias
            WHERE connector_version_id=? AND provider_code=?
              AND effective_from<=?
              AND (effective_to IS NULL OR ?<effective_to)
            ORDER BY effective_from DESC
            """,
            (connector_version_id, provider_code, as_of, as_of),
        ).fetchall()
        if len(rows) > 1:
            raise ConflictError("ambiguous provider alias resolution")
        return None if not rows else _row_dict(rows[0])


class SQLiteConnectorRepository(SQLiteDomainRepository):
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "connector")

    def list_versions(self, connector_id: str) -> tuple[dict[str, Any], ...]:
        return self.table("connector_version").list_page(
            {"connector_id": connector_id}, limit=1_000
        )

    def record_admission(self, admission: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("connector_admission").add_new(admission, idempotent=True)

    def set_capability_state(self, capability: Mapping[str, Any]) -> dict[str, Any]:
        # Capability evidence is version-scoped. Changed evidence/state is a conflict,
        # never an in-place rewrite of the admission decision.
        return self.table("connector_capability").add_new(capability, idempotent=True)

    def resolve_credential_reference(self, connector_id: str) -> dict[str, Any] | None:
        rows = self.table("credential_reference").list_page(
            {"connector_id": connector_id, "state": "ACTIVE"}, limit=2
        )
        if len(rows) > 1:
            raise ConflictError("multiple ACTIVE credential references for one Connector")
        return None if not rows else rows[0]


class SQLiteSnapshotRepository(SQLiteDomainRepository):
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "snapshot")

    def create_candidate(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        if snapshot.get("state") != "CANDIDATE":
            raise InvalidArgumentError("create_candidate requires state=CANDIDATE")
        return self.table("data_snapshot").add_new(snapshot)

    def record_validation(self, validation: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("snapshot_validation").add_new(validation, idempotent=True)

    def mark_validated(
        self,
        snapshot_id: str,
        *,
        validation_profile_id: str,
        validated_at: str,
    ) -> dict[str, Any]:
        repository = self.table("data_snapshot")
        repository._assert_active(write=True)
        profile = self.uow.connection.execute(
            """
            SELECT admission_state FROM snapshot_validation_profile
            WHERE validation_profile_id=?
            """,
            (validation_profile_id,),
        ).fetchone()
        if profile is None:
            raise ConflictError("Snapshot validation profile is not registered")
        requirement_count = int(
            self.uow.connection.execute(
                """
                SELECT COUNT(*) FROM snapshot_validation_requirement
                WHERE validation_profile_id=?
                """,
                (validation_profile_id,),
            ).fetchone()[0]
        )
        if requirement_count == 0:
            raise ConflictError("Snapshot validation profile has no required checks")
        incomplete = self.uow.connection.execute(
            """
            SELECT requirement.check_code
            FROM snapshot_validation_requirement AS requirement
            LEFT JOIN snapshot_validation AS result
              ON result.snapshot_id=?
             AND result.validation_profile_id=requirement.validation_profile_id
             AND result.check_code=requirement.check_code
            WHERE requirement.validation_profile_id=?
              AND (
                result.snapshot_validation_id IS NULL
                OR result.state<>requirement.required_state
                OR result.severity<>requirement.severity
              )
            LIMIT 1
            """,
            (snapshot_id, validation_profile_id),
        ).fetchone()
        if incomplete is not None:
            raise ConflictError(
                f"Snapshot validation requirement is incomplete: {incomplete[0]}"
            )
        self.table("snapshot_validation_binding").add_new(
            {
                "snapshot_id": snapshot_id,
                "validation_profile_id": validation_profile_id,
                "bound_at": validated_at,
            },
            idempotent=True,
        )
        cursor = self.uow.connection.execute(
            """
            UPDATE data_snapshot SET state='VALIDATED', validated_at=?
            WHERE snapshot_id=? AND state='CANDIDATE'
            """,
            (validated_at, snapshot_id),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Snapshot is not CANDIDATE")
        return repository.require(snapshot_id)

    def publish_validated(
        self,
        snapshot_id: str,
        *,
        manifest_artifact_id: str,
        content_hash: str,
        published_at: str,
    ) -> dict[str, Any]:
        repository = self.table("data_snapshot")
        repository._assert_active(write=True)
        self._assert_strict_pit_admitted(snapshot_id)
        failed = self.uow.connection.execute(
            """
            SELECT 1 FROM snapshot_validation
            WHERE snapshot_id=? AND state='FAIL' AND severity='BLOCKING' LIMIT 1
            """,
            (snapshot_id,),
        ).fetchone()
        if failed is not None:
            raise ConflictError("Snapshot has a non-PASSED validation")
        manifest = self.uow.connection.execute(
            "SELECT sha256,state FROM artifact WHERE artifact_id=?",
            (manifest_artifact_id,),
        ).fetchone()
        if (
            manifest is None
            or str(manifest[1]) != "PUBLISHED"
            or str(manifest[0]) != content_hash
            or manifest_artifact_id != "art_sha256_" + content_hash
        ):
            raise ArtifactNotPublishedError(
                "Snapshot manifest must be PUBLISHED and content-address the snapshot"
            )
        cursor = self.uow.connection.execute(
            """
            UPDATE data_snapshot
            SET state='PUBLISHED', manifest_artifact_id=?, content_hash=?, published_at=?
            WHERE snapshot_id=? AND state='VALIDATED'
            """,
            (manifest_artifact_id, content_hash, published_at, snapshot_id),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Snapshot is not VALIDATED")
        return repository.require(snapshot_id)

    def _assert_strict_pit_admitted(self, snapshot_id: str) -> None:
        snapshot = self.uow.connection.execute(
            """
            SELECT connector_version_id,truth_profile_id
            FROM data_snapshot WHERE snapshot_id=?
            """,
            (snapshot_id,),
        ).fetchone()
        if snapshot is None:
            raise ConflictError("Snapshot does not exist")
        if str(snapshot[1]) != "STRICT_PIT":
            return

        connector_version_id = str(snapshot[0])
        sources = self.uow.connection.execute(
            """
            SELECT source.logical_dataset,capture.connector_version_id,
                   truth.provider_id,truth.provider_available_time,
                   truth.provenance_complete,policy.provider_id
            FROM snapshot_raw_capture AS source
            JOIN raw_capture AS capture
              ON capture.raw_capture_id=source.raw_capture_id
            LEFT JOIN raw_capture_truth_descriptor AS truth
              ON truth.raw_capture_id=source.raw_capture_id
            LEFT JOIN connector_data_capability AS policy
              ON policy.connector_version_id=?
             AND policy.capability_code=source.logical_dataset
            WHERE source.snapshot_id=?
            """,
            (connector_version_id, snapshot_id),
        ).fetchall()
        if not sources:
            raise PitCapabilityUnavailable("RAW_CAPTURE_SOURCE_UNAVAILABLE")

        capability_repository = SQLiteDataTruthRepository(self.uow)
        for source in sources:
            logical_dataset = str(source[0])
            if str(source[1]) != connector_version_id:
                raise PitCapabilityUnavailable("WRONG_CONNECTOR_VERSION")
            resolution = capability_repository.resolve_connector_capability(
                connector_version_id, logical_dataset
            )
            if resolution.truth_state is not CapabilityTruthState.FORMAL:
                raise PitCapabilityUnavailable(resolution.reason_code)
            if source[2] is None or source[3] is None:
                raise PitCapabilityUnavailable("PROVIDER_AVAILABLE_TIME_UNAVAILABLE")
            if int(source[4]) != 1:
                raise PitCapabilityUnavailable("PROVENANCE_INCOMPLETE")
            if source[5] is None or str(source[5]) != str(source[2]):
                raise PitCapabilityUnavailable("PROVIDER_PROVENANCE_MISMATCH")

        missing_partition_time = self.uow.connection.execute(
            """
            SELECT 1 FROM snapshot_partition
            WHERE snapshot_id=? AND max_available_time IS NULL LIMIT 1
            """,
            (snapshot_id,),
        ).fetchone()
        if missing_partition_time is not None:
            raise PitCapabilityUnavailable("PARTITION_AVAILABLE_TIME_UNAVAILABLE")

        missing_calendar_time = self.uow.connection.execute(
            """
            SELECT 1 FROM snapshot_calendar AS binding
            JOIN trading_session AS session
              ON session.calendar_version_id=binding.calendar_version_id
            WHERE binding.snapshot_id=? AND session.available_time IS NULL LIMIT 1
            """,
            (snapshot_id,),
        ).fetchone()
        if missing_calendar_time is not None:
            raise PitCapabilityUnavailable("CALENDAR_AVAILABLE_TIME_UNAVAILABLE")

    def list_upgrade_candidates(
        self, connector_version_id: str, *, after_published_at: str
    ) -> tuple[dict[str, Any], ...]:
        repository = self.table("data_snapshot")
        repository._assert_active()
        rows = self.uow.connection.execute(
            """
            SELECT * FROM data_snapshot
            WHERE connector_version_id=? AND state='PUBLISHED' AND published_at>?
            ORDER BY published_at,snapshot_id
            """,
            (connector_version_id, after_published_at),
        ).fetchall()
        return tuple(_row_dict(row) for row in rows)


class SQLiteDataTruthRepository(SQLiteDomainRepository):
    """Bounded Data Truth extension of the canonical Catalog registry."""

    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "data_truth")

    def register_provider(self, descriptor: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("provider_descriptor").add_new(descriptor, idempotent=True)

    def declare_connector_capability_extension(
        self, capability: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Attach Data Truth policy to the exact canonical capability authority."""
        return self.table("connector_data_capability").add_new(
            capability, idempotent=True
        )

    def resolve_connector_capability(
        self, connector_version_id: str, capability_code: str
    ) -> ConnectorCapabilityResolution:
        self.table("connector_data_capability")._assert_active()
        row = self.uow.connection.execute(
            """
            SELECT authority.declared_state,authority.admitted_truth_state,
                   policy.revision_semantics,version.state
            FROM connector_capability AS authority
            JOIN connector_version AS version
              ON version.connector_version_id=authority.connector_version_id
            LEFT JOIN connector_data_capability AS policy
              ON policy.connector_version_id=authority.connector_version_id
             AND policy.capability_code=authority.capability_code
            WHERE authority.connector_version_id=? AND authority.capability_code=?
            """,
            (connector_version_id, capability_code),
        ).fetchone()
        if row is None:
            return ConnectorCapabilityResolution(
                connector_version_id,
                capability_code,
                CapabilityTruthState.UNAVAILABLE,
                "CAPABILITY_NOT_DECLARED_FOR_CONNECTOR_VERSION",
            )
        if (
            str(row[0]) != "DECLARED"
            or str(row[1]) == "UNAVAILABLE"
            or str(row[3]) != "ADMITTED"
        ):
            return ConnectorCapabilityResolution(
                connector_version_id,
                capability_code,
                CapabilityTruthState.UNAVAILABLE,
                "CAPABILITY_AUTHORITY_UNAVAILABLE",
            )
        if row[2] is None:
            return ConnectorCapabilityResolution(
                connector_version_id,
                capability_code,
                CapabilityTruthState.UNAVAILABLE,
                "DATA_TRUTH_POLICY_UNAVAILABLE",
            )
        semantics = RevisionSemantics(str(row[2]))
        if semantics is RevisionSemantics.UNKNOWN:
            return ConnectorCapabilityResolution(
                connector_version_id,
                capability_code,
                CapabilityTruthState.UNAVAILABLE,
                "REVISION_SEMANTICS_UNKNOWN",
                semantics,
            )
        return ConnectorCapabilityResolution(
            connector_version_id,
            capability_code,
            CapabilityTruthState(str(row[1])),
            "EXACT_CONNECTOR_VERSION_ADMITTED",
            semantics,
        )

    def submit_raw_capture(self, capture: Mapping[str, Any]) -> dict[str, Any]:
        if capture.get("state") != "CAPTURED":
            raise InvalidArgumentError("connector submission requires state=CAPTURED")
        if capture.get("provider_id") is None or capture.get("source_metadata_json") is None:
            raise InvalidArgumentError("Raw Capture requires provider and source metadata")
        content_hash = str(capture.get("content_hash", ""))
        if capture.get("artifact_id") != "art_sha256_" + content_hash:
            raise InvalidArgumentError("Raw Capture Artifact identity must match content_hash")
        row = dict(capture)
        provider_id = str(row.pop("provider_id"))
        source_metadata = row.pop("source_metadata_json")
        provenance_complete = row.pop("provenance_complete", None)
        if provenance_complete not in {0, 1, False, True}:
            raise InvalidArgumentError(
                "Raw Capture requires explicit provenance_complete truth"
            )
        provider_available_time = row.get("available_time")
        recorded = self.table("raw_capture").add_new(row, idempotent=True)
        self.table("raw_capture_truth_descriptor").add_new(
            {
                "raw_capture_id": recorded["raw_capture_id"],
                "provider_id": provider_id,
                "source_metadata_json": source_metadata,
                "provider_available_time": provider_available_time,
                "provenance_complete": int(bool(provenance_complete)),
            },
            idempotent=True,
        )
        return recorded

    def accept_raw_capture(self, raw_capture_id: str) -> dict[str, Any]:
        repository = self.table("raw_capture")
        repository._assert_active(write=True)
        cursor = self.uow.connection.execute(
            "UPDATE raw_capture SET state='ACCEPTED' WHERE raw_capture_id=? AND state='CAPTURED'",
            (raw_capture_id,),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Raw Capture is not CAPTURED")
        return repository.require(raw_capture_id)

    def publish_calendar(self, calendar: Mapping[str, Any]) -> dict[str, Any]:
        if calendar.get("state") != "PUBLISHED":
            raise InvalidArgumentError("Trading Calendar version must be PUBLISHED")
        return self.table("trading_calendar_version").add_new(calendar, idempotent=True)

    def add_session(self, session: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("trading_session").add_new(session, idempotent=True)

    def link_snapshot_source(self, source: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("snapshot_raw_capture").add_new(source, idempotent=True)

    def link_snapshot_calendar(self, binding: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("snapshot_calendar").add_new(binding, idempotent=True)

    def add_membership_interval(self, membership: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("universe_membership_interval").add_new(membership)

    def publish_universe_version(
        self,
        universe_version_id: str,
        *,
        membership_artifact_id: str,
        audit_artifact_id: str,
        content_hash: str,
        published_at: str,
    ) -> dict[str, Any]:
        repository = SQLiteTableRepository(self.uow, "universe_version")
        repository._assert_active(write=True)
        for artifact_id in (membership_artifact_id, audit_artifact_id):
            artifact = self.uow.connection.execute(
                "SELECT state FROM artifact WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
            if artifact is None or str(artifact[0]) != "PUBLISHED":
                raise ArtifactNotPublishedError("Universe version requires PUBLISHED Artifacts")
        cursor = self.uow.connection.execute(
            """
            UPDATE universe_version
            SET membership_artifact_id=?,audit_artifact_id=?,content_hash=?,state='PUBLISHED',published_at=?
            WHERE universe_version_id=? AND state='BUILDING'
            """,
            (
                membership_artifact_id,
                audit_artifact_id,
                content_hash,
                published_at,
                universe_version_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ConflictError("UniverseVersion is not BUILDING")
        return repository.require(universe_version_id)

    def resolve_members_as_of(
        self,
        universe_version_id: str,
        *,
        as_of: str,
        decision_time: str,
        strict: bool = True,
    ) -> UniverseResolution:
        repository = self.table("universe_membership_interval")
        repository._assert_active()
        version = self.uow.connection.execute(
            """
            SELECT universe.snapshot_id,universe.knowledge_cutoff,universe.state,
                   snapshot.state
            FROM universe_version AS universe
            LEFT JOIN data_snapshot AS snapshot
              ON snapshot.snapshot_id=universe.snapshot_id
            WHERE universe.universe_version_id=?
            """,
            (universe_version_id,),
        ).fetchone()
        if (
            version is None
            or str(version[2]) != "PUBLISHED"
            or str(version[3]) != "PUBLISHED"
        ):
            raise PitCapabilityUnavailable("UniverseVersion is unavailable or unpublished")

        decision = _parse_instant(decision_time)
        cutoff = _parse_instant(str(version[1]))
        if decision > cutoff:
            raise PitCapabilityUnavailable(
                "decision_time exceeds UniverseVersion knowledge_cutoff"
            )
        visibility_ceiling = min(decision, cutoff).isoformat()
        missing = self.uow.connection.execute(
            """
            SELECT 1 FROM universe_membership_interval
            WHERE universe_version_id=? AND effective_from<=?
              AND (effective_to IS NULL OR ?<effective_to)
              AND available_time IS NULL LIMIT 1
            """,
            (universe_version_id, as_of, as_of),
        ).fetchone()
        if strict and missing is not None:
            raise PitCapabilityUnavailable("Universe membership available_time is unavailable")
        rows = self.uow.connection.execute(
            """
            SELECT membership.* FROM universe_membership_interval AS membership
            JOIN instrument ON instrument.instrument_id=membership.instrument_id
            WHERE membership.universe_version_id=?
              AND membership.effective_from<=?
              AND (membership.effective_to IS NULL OR ?<membership.effective_to)
              AND membership.available_time IS NOT NULL
              AND datetime(membership.available_time)<=datetime(?)
              AND instrument.listing_date<=?
              AND (instrument.delisting_date IS NULL OR ?<=instrument.delisting_date)
            ORDER BY membership.membership_fact_id,datetime(membership.available_time) DESC,membership.revision_id
            """,
            (universe_version_id, as_of, as_of, visibility_ceiling, as_of, as_of),
        ).fetchall()
        by_fact: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            mapped = _row_dict(row)
            by_fact.setdefault(str(mapped["membership_fact_id"]), []).append(mapped)

        by_instrument: dict[str, list[dict[str, Any]]] = {}
        selected_revisions: list[dict[str, object]] = []
        for fact_id, revisions in by_fact.items():
            latest_time = max(
                _parse_instant(str(item["available_time"])) for item in revisions
            )
            latest = [
                item
                for item in revisions
                if _parse_instant(str(item["available_time"])) == latest_time
            ]
            if len(latest) != 1:
                raise PitCapabilityUnavailable(
                    f"ambiguous Universe revision for {fact_id}"
                )
            selected = latest[0]
            selected_revisions.append(
                {
                    "membership_fact_id": fact_id,
                    "instrument_id": str(selected["instrument_id"]),
                    "revision_id": str(selected["revision_id"]),
                    "available_time": str(selected["available_time"]),
                    "provenance_artifact_id": str(
                        selected["provenance_artifact_id"]
                    ),
                }
            )
            if selected["membership_state"] == "EXCLUDED":
                continue
            by_instrument.setdefault(str(selected["instrument_id"]), []).append(selected)

        ambiguous = [key for key, facts in by_instrument.items() if len(facts) != 1]
        if ambiguous:
            raise PitCapabilityUnavailable(
                f"ambiguous active Universe facts for {','.join(sorted(ambiguous))}"
            )
        members = tuple(by_instrument[key][0] for key in sorted(by_instrument))
        return UniverseResolution(
            members=members,
            audit={
                "universe_version_id": universe_version_id,
                "snapshot_id": str(version[0]),
                "knowledge_cutoff": str(version[1]),
                "as_of": as_of,
                "decision_time": decision_time,
                "visibility_ceiling": visibility_ceiling,
                "selected_revisions": tuple(
                    sorted(
                        selected_revisions,
                        key=lambda item: str(item["membership_fact_id"]),
                    )
                ),
            },
        )

    def resolve_instrument_revision_as_of(
        self, instrument_id: str, *, as_of: str, decision_time: str
    ) -> dict[str, Any] | None:
        self.table("raw_capture")._assert_active()
        _parse_instant(decision_time)
        rows = self.uow.connection.execute(
            """
            SELECT * FROM instrument_revision
            WHERE instrument_id=? AND effective_from<=?
              AND (effective_to IS NULL OR ?<effective_to)
              AND datetime(available_time)<=datetime(?)
            ORDER BY effective_from,effective_to,datetime(available_time) DESC,revision_no DESC
            """,
            (instrument_id, as_of, as_of, decision_time),
        ).fetchall()
        by_fact: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
        for row in rows:
            mapped = _row_dict(row)
            key = (str(mapped["effective_from"]), mapped["effective_to"])
            by_fact.setdefault(key, []).append(mapped)
        selected: list[dict[str, Any]] = []
        for revisions in by_fact.values():
            latest_time = max(
                _parse_instant(str(item["available_time"])) for item in revisions
            )
            latest = [
                item
                for item in revisions
                if _parse_instant(str(item["available_time"])) == latest_time
            ]
            if len(latest) != 1:
                raise PitCapabilityUnavailable("ambiguous Instrument revision availability")
            selected.append(latest[0])
        if len(selected) > 1:
            raise PitCapabilityUnavailable("ambiguous Instrument effective facts")
        return None if not selected else selected[0]

    def record_corporate_action(self, action: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("corporate_action").add_new(action, idempotent=True)

    def publish_adjustment_factors(self, version: Mapping[str, Any]) -> dict[str, Any]:
        if version.get("state") != "PUBLISHED":
            raise InvalidArgumentError("Adjustment Factor version must be PUBLISHED")
        return self.table("adjustment_factor_version").add_new(version, idempotent=True)


class SQLiteStudyRepository(SQLiteDomainRepository):
    _TERMINAL = frozenset({"PRUNED", "COMPLETED", "FAILED", "CANCELLED"})

    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "study")

    def reserve_trial_batch(
        self, trials: Sequence[Mapping[str, Any]]
    ) -> tuple[dict[str, Any], ...]:
        repository = self.table("trial")
        return tuple(repository.add_new(trial, idempotent=True) for trial in trials)

    def append_trial_state(
        self,
        trial_id: str,
        *,
        from_state: str,
        to_state: str,
        finished_at: str | None = None,
        objective_summary: Mapping[str, Any] | None = None,
        metrics_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        repository = self.table("trial")
        repository._assert_active(write=True)
        if from_state in self._TERMINAL:
            raise ConflictError("terminal Trial cannot transition")
        objective_json = (
            None if objective_summary is None else canonical_bounded_json(objective_summary)
        )
        cursor = self.uow.connection.execute(
            """
            UPDATE trial
            SET state=?, finished_at=?, objective_summary_json=COALESCE(?,objective_summary_json),
                metrics_artifact_id=COALESCE(?,metrics_artifact_id)
            WHERE trial_id=? AND state=?
            """,
            (to_state, finished_at, objective_json, metrics_artifact_id, trial_id, from_state),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Trial state compare-and-swap failed")
        return repository.require(trial_id)

    def load_resume_checkpoint(self, attempt_id: str) -> dict[str, Any] | None:
        repository = self.table("checkpoint")
        repository._assert_active()
        row = self.uow.connection.execute(
            "SELECT * FROM checkpoint WHERE attempt_id=? ORDER BY ordinal DESC LIMIT 1",
            (attempt_id,),
        ).fetchone()
        return None if row is None else _row_dict(row)


class SQLiteTaskRepository(SQLiteDomainRepository):
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "task")

    def create_task_and_run(
        self, task: Mapping[str, Any], run: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if run.get("task_id") != task.get("task_id"):
            raise ConflictError("Run must belong to the newly created Task")
        task_row = self.table("task").add_new(task)
        run_row = self.table("run").add_new(run)
        return task_row, run_row

    def create_attempt(self, attempt: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("task_attempt").add_new(attempt)

    def append_event(
        self, event: Mapping[str, Any], *, expected_stream_sequence: int
    ) -> dict[str, Any]:
        repository = self.table("task_event")
        repository._assert_active(write=True)
        current = int(
            self.uow.connection.execute(
                "SELECT COALESCE(MAX(project_sequence),0) FROM task_event WHERE project_id=?",
                (event["project_id"],),
            ).fetchone()[0]
        )
        if current != expected_stream_sequence:
            raise ConflictError(
                "event stream sequence conflict",
                details={"expected": expected_stream_sequence, "observed": current},
            )
        row = dict(event)
        row["project_sequence"] = current + 1
        return repository.add_new(row)

    def list_replay(
        self, project_id: str, *, after_sequence: int = 0, limit: int = 1_000
    ) -> tuple[dict[str, Any], ...]:
        repository = self.table("task_event")
        repository._assert_active()
        if not 1 <= limit <= 10_000:
            raise InvalidArgumentError("replay limit must be between 1 and 10000")
        rows = self.uow.connection.execute(
            """
            SELECT * FROM task_event
            WHERE project_id=? AND project_sequence>?
            ORDER BY project_sequence LIMIT ?
            """,
            (project_id, after_sequence, limit),
        ).fetchall()
        return tuple(_row_dict(row) for row in rows)

    def record_idempotency(self, outcome: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("idempotency_record").add_new(outcome, idempotent=True)

    def get_idempotency(self, scope_key: str) -> dict[str, Any] | None:
        return self.table("idempotency_record").get(scope_key)


class SQLiteArtifactRepository(SQLiteDomainRepository):
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "artifact")

    def declare_staged(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        if artifact.get("state") != "STAGED":
            raise InvalidArgumentError("declare_staged requires state=STAGED")
        return self.table("artifact").add_new(artifact, idempotent=True)

    def publish_verified(
        self, artifact_id: str, *, sha256: str, published_at: str
    ) -> dict[str, Any]:
        repository = self.table("artifact")
        repository._assert_active(write=True)
        if artifact_id != "art_sha256_" + sha256:
            raise InvalidArgumentError("Artifact ID does not match verified SHA-256")
        cursor = self.uow.connection.execute(
            """
            UPDATE artifact SET state='PUBLISHED', published_at=?
            WHERE artifact_id=? AND sha256=? AND state='STAGED'
            """,
            (published_at, artifact_id, sha256),
        )
        if cursor.rowcount != 1:
            existing = repository.get(artifact_id)
            if (
                existing is not None
                and existing["state"] == "PUBLISHED"
                and existing["sha256"] == sha256
            ):
                return existing
            raise ArtifactNotPublishedError("staged Artifact verification or state precondition failed")
        return repository.require(artifact_id)

    def add_reference(self, reference: Mapping[str, Any]) -> dict[str, Any]:
        artifact = self.table("artifact").get(str(reference["artifact_id"]))
        if artifact is None or artifact["state"] != "PUBLISHED":
            raise ArtifactNotPublishedError("Artifact reference target is not PUBLISHED")
        if reference.get("state") != "ACTIVE":
            raise InvalidArgumentError("new Artifact references must be ACTIVE")
        return self.table("artifact_reference").add_new(reference, idempotent=True)

    def bind_artifact(
        self,
        *,
        artifact_reference_id: str,
        owner_type: str,
        owner_id: str,
        role: str,
        artifact_id: str,
        created_at: str,
    ) -> dict[str, Any]:
        return self.add_reference(
            {
                "artifact_reference_id": artifact_reference_id,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "role": role,
                "artifact_id": artifact_id,
                "state": "ACTIVE",
                "created_at": created_at,
            }
        )

    def release_reference(self, reference_id: str, *, released_at: str) -> dict[str, Any]:
        repository = self.table("artifact_reference")
        repository._assert_active(write=True)
        cursor = self.uow.connection.execute(
            """
            UPDATE artifact_reference SET state='RELEASED', released_at=?
            WHERE artifact_reference_id=? AND state='ACTIVE'
            """,
            (released_at, reference_id),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Artifact reference is not ACTIVE")
        return repository.require(reference_id)

    def reachable_set(self) -> frozenset[str]:
        repository = self.table("artifact_reference")
        repository._assert_active()
        return frozenset(
            str(row[0])
            for row in self.uow.connection.execute(
                "SELECT DISTINCT artifact_id FROM artifact_reference WHERE state='ACTIVE'"
            )
        )

    def mark_deleted(
        self, artifact_id: str, *, deleted_at: str, confirmed_gc_plan_artifact_id: str
    ) -> dict[str, Any]:
        repository = self.table("artifact")
        repository._assert_active(write=True)
        if not confirmed_gc_plan_artifact_id.startswith("art_sha256_"):
            raise InvalidArgumentError("a confirmed GC plan Artifact ID is required")
        gc_plan = repository.get(confirmed_gc_plan_artifact_id)
        if gc_plan is None or gc_plan["state"] != "PUBLISHED":
            raise ArtifactNotPublishedError("confirmed GC plan Artifact is not PUBLISHED")
        active = self.uow.connection.execute(
            "SELECT 1 FROM artifact_reference WHERE artifact_id=? AND state='ACTIVE' LIMIT 1",
            (artifact_id,),
        ).fetchone()
        if active is not None:
            raise ConflictError("reachable Artifact cannot be marked DELETED")
        cursor = self.uow.connection.execute(
            """
            UPDATE artifact SET state='DELETED', deleted_at=?
            WHERE artifact_id=? AND state IN ('PUBLISHED','QUARANTINED')
            """,
            (deleted_at, artifact_id),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Artifact is not deletable")
        return repository.require(artifact_id)


class SQLiteProvenanceRepository(SQLiteDomainRepository):
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "provenance")

    def record_entity_once(self, entity: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("provenance_entity").add_new(entity, idempotent=True)

    def record_edge_once(self, edge: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("provenance_edge").add_new(edge, idempotent=True)

    def walk_ancestors(self, entity_id: str) -> tuple[dict[str, Any], ...]:
        repository = self.table("provenance_edge")
        repository._assert_active()
        rows = self.uow.connection.execute(
            """
            WITH RECURSIVE ancestors(entity_id, depth) AS (
              SELECT from_entity_id, 1 FROM provenance_edge WHERE to_entity_id=?
              UNION
              SELECT edge.from_entity_id, ancestors.depth+1
              FROM provenance_edge AS edge
              JOIN ancestors ON edge.to_entity_id=ancestors.entity_id
              WHERE ancestors.depth < 100
            )
            SELECT entity.*, MIN(ancestors.depth) AS depth
            FROM ancestors JOIN provenance_entity AS entity
              ON entity.provenance_entity_id=ancestors.entity_id
            GROUP BY entity.provenance_entity_id
            ORDER BY depth, entity.provenance_entity_id
            """,
            (entity_id,),
        ).fetchall()
        return tuple(_row_dict(row) for row in rows)


class SQLiteOptimizationRepository(SQLiteDomainRepository):
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "optimization")

    def publish_solution(
        self,
        solution: Mapping[str, Any],
        *,
        residual_validation_passed: bool | None = None,
    ) -> dict[str, Any]:
        status = solution.get("status")
        weights = solution.get("weights_artifact_id")
        residual = solution.get("residual_validation_artifact_id")
        if status == "OPTIMAL":
            if weights is None or residual is None or residual_validation_passed is not True:
                raise InvalidArgumentError(
                    "OPTIMAL solution requires weights and independently PASSED residual validation"
                )
        elif weights is not None:
            raise InvalidArgumentError("non-OPTIMAL solution cannot bind weights")
        return self.table("optimization_solution").add_new(solution, idempotent=True)

    def publish_problem(self, problem: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("optimization_problem").add_new(problem, idempotent=True)


class SQLiteBacktestRepository(SQLiteDomainRepository):
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "backtest")

    def expand_matrix_once(
        self, experiment_id: str, *, expansion_manifest_artifact_id: str, updated_at: str
    ) -> dict[str, Any]:
        repository = self.table("experiment")
        repository._assert_active(write=True)
        cursor = self.uow.connection.execute(
            """
            UPDATE experiment
            SET state='EXPANDED', expansion_manifest_artifact_id=?, updated_at=?
            WHERE experiment_id=? AND state='DRAFT' AND expansion_manifest_artifact_id IS NULL
            """,
            (expansion_manifest_artifact_id, updated_at, experiment_id),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Experiment matrix was already expanded or is not DRAFT")
        return repository.require(experiment_id)

    def bind_child_task(
        self, task_id: str, child_task_id: str, *, required_terminal_state: str = "SUCCEEDED"
    ) -> dict[str, Any]:
        return SQLiteTableRepository(self.uow, "task_dependency").add_new(
            {
                "task_id": task_id,
                "depends_on_task_id": child_task_id,
                "required_terminal_state": required_terminal_state,
            },
            idempotent=True,
        )

    def publish_run_spec(self, run_spec: Mapping[str, Any]) -> dict[str, Any]:
        return self.table("backtest_run_spec").add_new(run_spec, idempotent=True)


class SQLiteResultRepository(SQLiteDomainRepository):
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        super().__init__(unit_of_work, "result")

    def publish_result(
        self,
        result: Mapping[str, Any],
        *,
        reconciliation_passed: bool | None = None,
    ) -> dict[str, Any]:
        if result.get("state") == "VALID" and (
            result.get("reconciliation_artifact_id") is None
            or reconciliation_passed is not True
        ):
            raise InvalidArgumentError("VALID Result requires independently PASSED reconciliation")
        return self.table("result").add_new(result, idempotent=True)

    def record_reconciliation(
        self,
        result_id: str,
        *,
        reconciliation_artifact_id: str,
        reconciliation_passed: bool,
        state: str,
        finalized_at: str,
        invalid_reason_code: str | None = None,
    ) -> dict[str, Any]:
        if state not in {"VALID", "INVALID"}:
            raise InvalidArgumentError("reconciliation must finalize Result as VALID or INVALID")
        if state == "VALID" and not reconciliation_passed:
            raise InvalidArgumentError("VALID Result requires independently PASSED reconciliation")
        repository = self.table("result")
        repository._assert_active(write=True)
        cursor = self.uow.connection.execute(
            """
            UPDATE result
            SET reconciliation_artifact_id=?, state=?, finalized_at=?, invalid_reason_code=?
            WHERE result_id=? AND state='PENDING_RECONCILIATION'
            """,
            (
                reconciliation_artifact_id,
                state,
                finalized_at,
                invalid_reason_code,
                result_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Result is not pending reconciliation")
        return repository.require(result_id)


class SQLiteRepositoryRegistry:
    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        self.project = SQLiteProjectRepository(unit_of_work)
        self.connector = SQLiteConnectorRepository(unit_of_work)
        self.instrument = SQLiteInstrumentRepository(unit_of_work)
        self.snapshot = SQLiteSnapshotRepository(unit_of_work)
        self.universe = SQLiteDomainRepository(unit_of_work, "universe")
        self.factor = SQLiteDomainRepository(unit_of_work, "factor")
        self.dataset = SQLiteDomainRepository(unit_of_work, "dataset")
        self.strategy = SQLiteDomainRepository(unit_of_work, "strategy")
        self.model = SQLiteDomainRepository(unit_of_work, "model")
        self.study = SQLiteStudyRepository(unit_of_work)
        self.portfolio = SQLiteDomainRepository(unit_of_work, "portfolio")
        self.risk = SQLiteDomainRepository(unit_of_work, "risk")
        self.optimization = SQLiteOptimizationRepository(unit_of_work)
        self.backtest = SQLiteBacktestRepository(unit_of_work)
        self.result = SQLiteResultRepository(unit_of_work)
        self.task = SQLiteTaskRepository(unit_of_work)
        self.artifact = SQLiteArtifactRepository(unit_of_work)
        self.provenance = SQLiteProvenanceRepository(unit_of_work)
        self.data_truth = SQLiteDataTruthRepository(unit_of_work)
