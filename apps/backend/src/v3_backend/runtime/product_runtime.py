"""B3 product runtime composition root.

Composes the durable product substrate behind thin ASL facades:

    durable catalog (SQLite, migrations 0001-0004)
    + content-addressed artifact store (filesystem bytes + catalog descriptors)
    + durable Task/Run/Attempt/event persistence
    + accepted canonical owners (strategy / portfolio / risk / backtest engine)

and executes the canonical research execution path:

    persisted canonical BacktestRunSpec (btrs_sha256_ content identity)
        -> deterministic A-share engine
        -> durable Task lifecycle + events
        -> durable Result record + content-addressed Result/Ledger artifacts

Every numeric stage remains owned by its existing accepted owner.  This module
adds composition, durable adapters and ASL facades only; it never re-implements
strategy, weight, risk or NAV computation and never accepts caller numeric
truth through the frozen ASL surface.
"""

from __future__ import annotations

import hashlib
import base64
import binascii
import json
import os
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from v3_backend.adapters.artifact_store import FileSystemArtifactStore, StagingReceipt
from v3_backend.adapters.sqlite.artifact_publication import (
    ArtifactPublicationCoordinator,
    PreparedArtifactPublication,
    SQLiteArtifactPublicationPort,
)
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.repositories import (
    SQLiteRepositoryRegistry,
    SQLiteTaskRepository,
)
from v3_backend.adapters.sqlite.task_persistence import (
    SQLiteTaskPersistence,
    SQLiteTaskUnitOfWork,
)
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.artifacts.identity import sha256_from_artifact_id
from v3_backend.domain.artifacts.exceptions import (
    ArtifactCollision,
    IntegrityMismatch,
    StagingNotFound,
)
from v3_backend.domain.artifacts.model import ArtifactDescriptor, ArtifactReference
from v3_backend.domain.artifacts.policy import (
    ADMITTED,
    FormatRule,
    SafeFormatPolicy,
)
from v3_backend.domain.artifacts.publication import ArtifactPublication
from v3_backend.domain.backtest_runtime import (
    AshareTradingRuleProfileVersion,
    BacktestRunResult,
    BacktestRunSpec,
    Board,
    BoardTradingRule,
    CorporateAction,
    CorporateActionType,
    DailyMarketState,
    DeterministicAshareBacktestEngine,
    ExactInputReference,
    ExecutionTimingProfileVersion,
    InitialHolding,
    InstrumentDefinition,
    MarketSession,
    ScheduledWeights,
    cn_a_share_2023_08_28_cost_policy,
)
from v3_backend.domain.tasks.entities import (
    ATTEMPT_TERMINAL_STATES,
    AttemptState,
    Run,
    RunIdentity,
    RunState,
    Task,
    TaskAttempt,
    TASK_TERMINAL_STATES,
    TaskState,
)
from v3_backend.domain.tasks.events import PendingTaskEvent
from v3_backend.domain.tasks.retry_policy import ErrorCategory, RetryPolicy
from v3_backend.domain.tasks.state_machine import (
    TaskTransitionContext,
    ImpossibleTransition,
    transition_attempt,
    transition_run,
    transition_task,
)

from v3_backend.domain.weights import RuntimeIdentity
from v3_backend.errors.exceptions import (
    ArtifactNotPublishedError,
    CapabilityUnavailableError,
    ConflictError,
    IdempotencyConflictError,
    InvalidArgumentError,
    NotFoundError,
    ResourceRejectedError,
    TruthPreconditionFailedError,
    V3ContractError,
)
from v3_backend.migrations.upgrade import require_current_catalog, upgrade_catalog
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256
from v3_backend.repositories.unit_of_work import TransactionMode

from .composition_root import Capability, RuntimePorts
from .build_manifest import BUILD_MANIFEST, BUILD_MANIFEST_ID
from v3_backend.control_plane.progress_persistence import (
    DispatchStateConflict,
    ProgressPersistence,
    RuntimeResolutionConflict,
    compatibility_hash_for_context,
)

if TYPE_CHECKING:
    from .product_workers import ProductResearchWorkerConfig

PRODUCT_RUNTIME_VERSION = "v3.product-runtime/1.0.0"
PRODUCT_BACKEND_VERSION_FLAVOR = "product"
CATALOG_FILENAME = "catalog.sqlite3"
ARTIFACT_DIRNAME = "artifacts"
MIGRATION_APPLICATION_VERSION = "v3-product-runtime-composition"

# Frozen execution adapter identity: the only admitted engine for the product path.
ADMITTED_EXECUTION_ADAPTER_VERSION_ID = "v3.a_share_daily_eod_engine/0.2.0"
FORMAL_BACKTEST_UNAVAILABLE_REASON = "FORMAL_EXECUTION_CONTRACT_NOT_CLOSED"
INLINE_WORKER_KIND = "PRODUCT_INLINE_V1"
INLINE_ENVIRONMENT_PROFILE_ID = "v3.product-inline-executor/1.0.0"
PRODUCT_CODE_VERSION = BUILD_MANIFEST.code_version
_CANONICAL_UTC_DEADLINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)

# Product artifact roles (product composition policy; bounded and explicit).
BACKTEST_RUN_SPEC_ROLE = "BACKTEST_RUN_SPEC"
PRODUCT_EXECUTION_CONTEXT_ROLE = "PRODUCT_EXECUTION_CONTEXT"
BACKTEST_RUN_RESULT_ROLE = "BACKTEST_RUN_RESULT"
LEDGER_MANIFEST_ROLE = "LEDGER_MANIFEST"
EXPORT_MANIFEST_ROLE = "EXPORT_MANIFEST"
EXPERIMENT_EXPANSION_MANIFEST_ROLE = "EXPERIMENT_EXPANSION_MANIFEST"

EXECUTION_CONTEXT_SCHEMA_VERSION = "v3.product-execution-context/1.0.0"
RESEARCH_RUN_CONTEXT_KIND = "RESEARCH_RUN_CONTEXT"
EXPORT_CONTEXT_KIND = "EXPORT_CONTEXT"
EXPERIMENT_EXPANSION_CONTEXT_KIND = "EXPERIMENT_EXPANSION_CONTEXT"

EXPORT_PROFILES = ("LIGHT_REVIEW", "FULL_REPRODUCTION")
DEFAULT_EXPORT_PROFILE = "LIGHT_REVIEW"
DEFAULT_RETENTION_PROFILE = "default"
MAX_EXPERIMENT_CELLS = 64
MAX_RECONCILIATION_BATCH = 128

# Durable artifact-reference roles owned by a Project (assembly) / Run (execution).
PROJECT_SPEC_REFERENCE_ROLE = "RESEARCH_RUN_SPEC"
PROJECT_SPEC_CONTEXT_REFERENCE_ROLE = "RESEARCH_RUN_CONTEXT"
RUN_CONTEXT_REFERENCE_ROLE = "EXECUTION_CONTEXT"
RUN_RESULT_REFERENCE_ROLE = "BACKTEST_RUN_RESULT"
RUN_LEDGER_MANIFEST_REFERENCE_ROLE = "LEDGER_MANIFEST"
RUN_EXPORT_MANIFEST_REFERENCE_ROLE = "EXPORT_MANIFEST"

_TASK_EVENT_VERSION = "1.0.0"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def mint_v3_id(prefix: str) -> str:
    """Mint a frozen-pattern V3 identity (prefix + 26 Crockford base32 chars)."""
    if not prefix.endswith("_"):
        raise ValueError("id prefix must end with '_'")
    value = int.from_bytes(uuid.uuid4().bytes, "big") << 2
    chars = "".join(_CROCKFORD[(value >> (5 * shift)) & 0x1F] for shift in range(25, -1, -1))
    return prefix + chars


def mint_uuid7() -> str:
    """Mint a canonical UUIDv7 for ASL request/session identities."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    raw = bytearray(uuid.uuid4().bytes)
    raw[0] = (now_ms >> 40) & 0xFF
    raw[1] = (now_ms >> 32) & 0xFF
    raw[2] = (now_ms >> 24) & 0xFF
    raw[3] = (now_ms >> 16) & 0xFF
    raw[4] = (now_ms >> 8) & 0xFF
    raw[5] = now_ms & 0xFF
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("product timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_product_storage_root(explicit: str | None = None) -> Path:
    """Explicit arg/env test root first; production local app-data root otherwise."""
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("V3_PRODUCT_STORAGE_ROOT")
    if env:
        return Path(env).resolve()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "v3-quant-workbench" / "product"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "v3-quant-workbench" / "product"
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "v3-quant-workbench" / "product"


def product_artifact_policy() -> SafeFormatPolicy:
    """Bounded product publication policy with explicit JSON validators per role."""
    from v3_backend.domain.data_truth.capabilities import (
        FIELD_CAPABILITY_POLICY_ROLE,
    )
    from v3_backend.domain.research_pipeline import RESEARCH_BACKTEST_RESULT_ROLE
    from v3_backend.domain.strategies import SCORE_PAYLOAD_ROLE

    rules = (
        FormatRule(
            "LOCAL_DATA_RAW_FILE",
            "text/csv",
            ADMITTED,
            "utf8-text-v1",
            "bounded user-supplied CSV bytes retained as immutable source evidence",
        ),
        FormatRule(
            "LOCAL_DATA_RAW_FILE",
            "application/vnd.apache.parquet",
            ADMITTED,
            "flat-parquet-v1",
            "bounded flat primitive Parquet bytes retained as immutable source evidence",
        ),
        FormatRule(
            SCORE_PAYLOAD_ROLE,
            "application/json",
            ADMITTED,
            "canonical-json-v1",
            "bounded development score fixture resolved through P1 bytes",
        ),
        FormatRule(
            RESEARCH_BACKTEST_RESULT_ROLE,
            "application/json",
            ADMITTED,
            "canonical-json-v1",
            "PRE_ALPHA research result envelope with explicit assumptions",
        ),
        FormatRule(
            FIELD_CAPABILITY_POLICY_ROLE,
            "application/json",
            ADMITTED,
            "canonical-json-v1",
            "provider capability policy resolved from persisted Data Truth bytes",
        ),
        FormatRule(
            "FEATURE_MATERIALIZATION",
            "application/json",
            ADMITTED,
            "canonical-finite-json-v1",
            "research-only derived feature values with finite numeric wire values",
        ),
        *(
            FormatRule(
                role,
                "application/json",
                ADMITTED,
                "canonical-finite-json-v1",
                f"V1.1 Factor artifact with finite research numeric values: {role}",
            )
            for role in (
                "FACTOR_FORMULA_DOCUMENT",
                "FACTOR_DEFINITION",
                "FACTOR_MATERIALIZATION_PARTITION",
                "FACTOR_MATERIALIZATION",
                "FACTOR_ANALYSIS",
                "PRODUCT_FACTOR_STUDY_READ_MODEL",
            )
        ),
    )
    product_roles = (
        BACKTEST_RUN_SPEC_ROLE,
        PRODUCT_EXECUTION_CONTEXT_ROLE,
        BACKTEST_RUN_RESULT_ROLE,
        LEDGER_MANIFEST_ROLE,
        EXPORT_MANIFEST_ROLE,
        EXPERIMENT_EXPANSION_MANIFEST_ROLE,
        "DATA_TRUTH_RAW_CAPTURE",
        "DATA_TRUTH_CALENDAR",
        "DATA_TRUTH_SNAPSHOT_PARTITION",
        "DATA_TRUTH_SNAPSHOT_MANIFEST",
        "DATA_TRUTH_CORPORATE_ACTION_SET",
        "UNIVERSE_MEMBERSHIP",
        "RESEARCH_STRATEGY_PROFILE",
        "RESEARCH_DATASET_PROFILE",
        "RESEARCH_PIPELINE_LINEAGE",
        "LOCAL_DATA_CONNECTOR_MANIFEST",
        "LOCAL_DATA_SCHEMA_MAPPING",
        "LOCAL_DATA_NORMALIZATION_RECEIPT",
        "LOCAL_DATA_UNIVERSE_AUDIT",
        "LOCAL_DATA_IMPORT_READ_MODEL",
        "PRODUCT_RESEARCH_STRATEGY_SPEC",
        "PRODUCT_STRATEGY_DEFINITION",
        "PRODUCT_STRATEGY_VALIDATION",
        "PRODUCT_STRATEGY_STATE_MATERIALIZATION",
        "PRODUCT_STRATEGY_READ_MODEL",
        "PRODUCT_STRATEGY_DECISION_INPUT",
        "PRODUCT_STRATEGY_DECISION_DATASET",
        "PRODUCT_STRATEGY_SIGNAL",
        "PRODUCT_STRATEGY_SELECTION",
        "PRODUCT_STRATEGY_PORTFOLIO_INTENT",
        "PRODUCT_RESEARCH_EXECUTION_INPUTS",
        "PRODUCT_RESEARCH_ASSUMPTION_RECEIPT",
        "PRODUCT_RESEARCH_RESULT_RECONCILIATION",
        "PRODUCT_RESULT_ANALYTICS",
        "PRODUCT_RESULT_LINEAGE",
        "PRODUCT_RESULT_EXPORT_SUMMARY_JSON",
        "PRODUCT_RESEARCH_BACKTEST_READ_MODEL",
        "GC_PLAN",
    )
    return SafeFormatPolicy(
        rules
        + tuple(
            FormatRule(
                role,
                "application/json",
                ADMITTED,
                "canonical-json-v1",
                f"product runtime {role} canonical JSON payload",
            )
            for role in product_roles
        )
        + tuple(
            FormatRule(
                role,
                "text/csv",
                ADMITTED,
                "utf8-text-v1",
                f"product runtime {role} deterministic UTF-8 CSV payload",
            )
            for role in (
                "PRODUCT_RESULT_EXPORT_ORDERS_CSV",
                "PRODUCT_RESULT_EXPORT_FILLS_CSV",
            )
        )
    )


class ProductArtifactBatch:
    """PUBLISH UoW callbacks for a bounded batch of staged product artifacts."""

    def __init__(
        self,
        *,
        store: FileSystemArtifactStore,
        payloads: tuple[tuple[Any, ...], ...],
        published_at: datetime,
        coordinator: ArtifactPublicationCoordinator | None = None,
    ) -> None:
        """payloads: provenance, bytes, role, schema fingerprint, optional MIME."""
        self.store = store
        self.coordinator = coordinator or ArtifactPublicationCoordinator(
            store.root.parent / CATALOG_FILENAME, store
        )
        normalized_payloads: list[tuple[Any, ...]] = []
        for item in payloads:
            if len(item) not in {4, 5}:
                raise V3ContractError("product artifact payload tuple is invalid")
            provenance_entity_id, payload, role, schema_fingerprint = item[:4]
            media_type = item[4] if len(item) == 5 else "application/json"
            if (
                not isinstance(provenance_entity_id, str)
                or not provenance_entity_id
                or not isinstance(payload, bytes)
                or not isinstance(role, str)
                or not role
                or not isinstance(schema_fingerprint, str)
                or not schema_fingerprint
                or not isinstance(media_type, str)
                or not media_type
            ):
                raise V3ContractError("product artifact payload fields are invalid")
            normalized_payloads.append(item)
        self.payloads = tuple(normalized_payloads)
        self.published_at = published_at
        stages = tuple(store.stage_bytes(item[1]) for item in self.payloads)
        self.stages: tuple[Any, ...] = stages
        self.results: list[Any] = []
        self.prepared: tuple[PreparedArtifactPublication, ...] = ()
        self.active_references: tuple[tuple[ArtifactReference, ...], ...] = ()

    def prepare_intents(
        self, references: tuple[tuple[str, str, int], ...]
    ) -> None:
        prepared: list[PreparedArtifactPublication] = []
        active_by_index: list[tuple[ArtifactReference, ...]] = []
        for index, (item, stage) in enumerate(zip(self.payloads, self.stages, strict=True)):
            provenance_entity_id, _, role, schema_fingerprint = item[:4]
            media_type = item[4] if len(item) == 5 else "application/json"
            active_references = tuple(
                ArtifactReference(
                    reference_id=mint_v3_id("arf_"),
                    owner_id=owner_id,
                    artifact_id="art_sha256_" + stage.sha256,
                    role=reference_role,
                    created_at=self.published_at,
                    state="ACTIVE",
                )
                for owner_id, reference_role, artifact_index in references
                if artifact_index == index
            )
            prepared_item = self.coordinator.prepare(
                stage,
                media_type=media_type,
                role=role,
                provenance_entity_id=provenance_entity_id,
                schema_fingerprint=schema_fingerprint,
                semantic_fingerprint=stage.sha256,
                published_at=self.published_at,
                active_references=active_references,
            )
            prepared.append(prepared_item)
            active_by_index.append(
                prepared_item.active_references or active_references
            )
        self.prepared = tuple(prepared)
        self.active_references = tuple(active_by_index)

    def verify_staged(self) -> None:
        for item, stage in zip(self.payloads, self.stages, strict=True):
            payload = item[1]
            if stage.sha256 != hashlib.sha256(payload).hexdigest():
                raise V3ContractError("staged product artifact hash mismatch")
            if stage.byte_size != len(payload):
                raise V3ContractError("staged product artifact size mismatch")

    def publish_staged(self) -> None:
        if len(self.prepared) != len(self.payloads):
            raise V3ContractError("artifact promotion intents were not prepared")
        self.results = []
        for item, prepared in zip(self.payloads, self.prepared, strict=True):
            provenance_entity_id, _, role, schema_fingerprint = item[:4]
            media_type = item[4] if len(item) == 5 else "application/json"
            self.results.append(
                self.coordinator.promote(
                    prepared,
                    media_type=media_type,
                    role=role,
                    provenance_entity_id=provenance_entity_id,
                    schema_fingerprint=schema_fingerprint,
                    semantic_fingerprint=prepared.staging.sha256,
                    published_at=self.published_at,
                )
            )

    def compensate_unreferenced_staging(self) -> None:
        failures: list[Exception] = []
        for prepared in self.prepared:
            try:
                self.coordinator.note_callback_failure(
                    prepared, RuntimeError("Catalog publication did not commit")
                )
            except Exception as exc:
                failures.append(exc)
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise ExceptionGroup("Artifact publication compensation failed", failures)

    def notify_committed(self) -> None:
        failures: list[Exception] = []
        for prepared in self.prepared:
            try:
                self.coordinator.finalize(prepared)
            except Exception as exc:
                try:
                    self.coordinator.note_callback_failure(prepared, exc)
                except Exception as record_error:
                    failures.append(record_error)
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise ExceptionGroup("Artifact publication commit notification failed", failures)


class ProductStagedArtifact:
    """PUBLISH callbacks for one already-streamed product artifact."""

    def __init__(
        self,
        *,
        store: FileSystemArtifactStore,
        staging: StagingReceipt,
        provenance_entity_id: str,
        role: str,
        media_type: str,
        schema_fingerprint: str,
        published_at: datetime,
        coordinator: ArtifactPublicationCoordinator | None = None,
    ) -> None:
        self.store = store
        self.coordinator = coordinator or ArtifactPublicationCoordinator(
            store.root.parent / CATALOG_FILENAME, store
        )
        self.staging = staging
        self.provenance_entity_id = provenance_entity_id
        self.role = role
        self.media_type = media_type
        self.schema_fingerprint = schema_fingerprint
        self.published_at = published_at
        self.result: Any | None = None
        self.prepared: PreparedArtifactPublication | None = None
        self.active_references: tuple[ArtifactReference, ...] = ()

    def prepare_intent(self, references: tuple[tuple[str, str], ...]) -> None:
        active_references = tuple(
            ArtifactReference(
                reference_id=mint_v3_id("arf_"),
                owner_id=owner_id,
                artifact_id="art_sha256_" + self.staging.sha256,
                role=reference_role,
                created_at=self.published_at,
                state="ACTIVE",
            )
            for owner_id, reference_role in references
        )
        self.prepared = self.coordinator.prepare(
            self.staging,
            media_type=self.media_type,
            role=self.role,
            provenance_entity_id=self.provenance_entity_id,
            schema_fingerprint=self.schema_fingerprint,
            semantic_fingerprint=self.staging.sha256,
            published_at=self.published_at,
            active_references=active_references,
        )
        self.active_references = self.prepared.active_references or active_references

    def verify_staged(self) -> None:
        digest = hashlib.sha256()
        byte_size = 0
        with self.store.open_staged(self.staging.staging_token) as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                byte_size += len(chunk)
        if digest.hexdigest() != self.staging.sha256 or byte_size != self.staging.byte_size:
            raise V3ContractError("pre-staged product artifact identity changed")

    def publish_staged(self) -> None:
        if self.prepared is None:
            raise V3ContractError("artifact promotion intent was not prepared")
        self.result = self.coordinator.promote(
            self.prepared,
            media_type=self.media_type,
            role=self.role,
            provenance_entity_id=self.provenance_entity_id,
            schema_fingerprint=self.schema_fingerprint,
            semantic_fingerprint=self.staging.sha256,
            published_at=self.published_at,
        )

    def compensate_unreferenced_staging(self) -> None:
        if self.prepared is not None:
            self.coordinator.note_callback_failure(
                self.prepared, RuntimeError("Catalog publication did not commit")
            )

    def notify_committed(self) -> None:
        if self.prepared is None:
            return
        try:
            self.coordinator.finalize(self.prepared)
        except Exception as exc:
            self.coordinator.note_callback_failure(self.prepared, exc)


def catalog_rows(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def catalog_row(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    row = connection.execute(sql, params).fetchone()
    return None if row is None else dict(row)


def _require_existing_artifact_descriptor(
    connection: sqlite3.Connection,
    descriptor: ArtifactDescriptor,
) -> None:
    existing = catalog_row(
        connection,
        "SELECT * FROM artifact WHERE artifact_id=?",
        (descriptor.artifact_id,),
    )
    expected = {
        "sha256": descriptor.sha256,
        "byte_size": descriptor.byte_size,
        "media_type": descriptor.media_type,
        "semantic_role": descriptor.role,
        "storage_key": descriptor.storage_key,
        "safe_format_id": descriptor.safe_format_id,
        "schema_fingerprint": descriptor.schema_fingerprint,
        "state": "PUBLISHED",
    }
    if existing is None or any(existing.get(key) != value for key, value in expected.items()):
        raise V3ContractError("existing published Artifact metadata conflicts with exact bytes")


class ProductEventReplay:
    """Durable project-bound event replay port for the Runtime Core."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._project_id: str | None = None

    def bind_project(self, project_id: str) -> None:
        if project_id is None:
            return
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            exists = catalog_row(
                connection, "SELECT project_id FROM project WHERE project_id=?", (project_id,)
            )
        finally:
            connection.close()
        if exists is None:
            raise V3ContractError(f"supervisor project is unknown to the product catalog: {project_id}")
        self._project_id = project_id

    def replay(self, after_sequence: int, limit: int) -> list[dict[str, Any]]:
        if self._project_id is None:
            return []
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            rows = catalog_rows(
                connection,
                """
                SELECT task_event_id, project_id, project_sequence, event_type,
                       occurred_at, payload_json
                FROM task_event
                WHERE project_id=? AND project_sequence>? AND project_sequence<=?
                ORDER BY project_sequence
                """,
                (self._project_id, after_sequence, after_sequence + limit),
            )
        finally:
            connection.close()
        return [
            {
                "event_id": str(row["task_event_id"]),
                "project_id": str(row["project_id"]),
                "project_sequence": int(row["project_sequence"]),
                "event_type": str(row["event_type"]),
                "occurred_at": str(row["occurred_at"]),
                "body": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def high_watermark(self) -> int:
        if self._project_id is None:
            return 0
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            value = connection.execute(
                "SELECT COALESCE(MAX(project_sequence),0) FROM task_event WHERE project_id=?",
                (self._project_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        return int(value)


def _canonical_request_hash(operation_id: str, semantic: Mapping[str, Any]) -> str:
    return canonical_sha256({"operation_id": operation_id, "semantic_request": dict(semantic)})


def classify_execution_error(error: Exception) -> ErrorCategory:
    if isinstance(error, V3ContractError):
        return ErrorCategory.INVALID_ARGUMENT
    if isinstance(error, (ValueError, TypeError)):
        return ErrorCategory.INVALID_ARGUMENT
    if isinstance(error, (OSError, sqlite3.OperationalError)):
        return ErrorCategory.TRANSIENT_IO
    return ErrorCategory.INTERNAL_ERROR


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    task_id: str
    run_id: str
    event_cursor: int | None


@dataclass(frozen=True, slots=True)
class ProductResearchSubmission:
    project_id: str
    project_context_revision_id: str
    research_profile_id: str
    strategy_profile_id: str
    source: Mapping[str, Any]
    idempotency_key: str
    execution_deadline_at: str | None = None


@dataclass(frozen=True, slots=True)
class _QueuedWorkerLaunch:
    """Prepared Product request and its single worker-owner profile."""

    prepared_request: Any
    operation_id: str
    work_kind: str
    resource_class: str


def _rule_profile_params(profile: AshareTradingRuleProfileVersion) -> dict[str, Any]:
    return {
        "profile_name": profile.profile_name,
        "effective_from": profile.effective_from.isoformat(),
        "effective_to": None if profile.effective_to is None else profile.effective_to.isoformat(),
        "settlement_days": profile.settlement_days,
        "board_rules": [
            {
                "board": rule.board.value,
                "buy_minimum_quantity": rule.buy_minimum_quantity,
                "buy_quantity_step": rule.buy_quantity_step,
                "normal_price_limit_rate": rule.normal_price_limit_rate,
                "restricted_price_limit_rate": rule.restricted_price_limit_rate,
                "price_tick": rule.price_tick,
                "sell_odd_lot_in_one_order": rule.sell_odd_lot_in_one_order,
            }
            for rule in profile.board_rules
        ],
    }


def _rebuild_rule_profile(params: Mapping[str, Any]) -> AshareTradingRuleProfileVersion:
    return AshareTradingRuleProfileVersion.create(
        profile_name=str(params["profile_name"]),
        effective_from=datetime.fromisoformat(str(params["effective_from"])).date(),
        effective_to=(
            None if params.get("effective_to") is None else datetime.fromisoformat(str(params["effective_to"])).date()
        ),
        settlement_days=int(params["settlement_days"]),
        board_rules=tuple(
            BoardTradingRule(
                board=Board(str(rule["board"])),
                buy_minimum_quantity=int(rule["buy_minimum_quantity"]),
                buy_quantity_step=int(rule["buy_quantity_step"]),
                normal_price_limit_rate=str(rule["normal_price_limit_rate"]),
                restricted_price_limit_rate=str(rule["restricted_price_limit_rate"]),
                price_tick=str(rule.get("price_tick", "0.01")),
                sell_odd_lot_in_one_order=bool(rule.get("sell_odd_lot_in_one_order", True)),
            )
            for rule in params["board_rules"]
        ),
        truth_admission=PRE_ALPHA_CEILING,
    )


def _timing_profile_params(profile: ExecutionTimingProfileVersion) -> dict[str, Any]:
    return {
        "profile_name": profile.profile_name,
        "effective_from": profile.effective_from.isoformat(),
        "effective_to": None if profile.effective_to is None else profile.effective_to.isoformat(),
        "market_timezone": profile.market_timezone,
        "raw_open_eligibility_cutoff_local_time": profile.raw_open_eligibility_cutoff_local_time,
        "raw_open_execution_local_time": profile.raw_open_execution_local_time,
    }


def _rebuild_timing_profile(params: Mapping[str, Any]) -> ExecutionTimingProfileVersion:
    return ExecutionTimingProfileVersion.create(
        profile_name=str(params["profile_name"]),
        effective_from=datetime.fromisoformat(str(params["effective_from"])).date(),
        effective_to=(
            None if params.get("effective_to") is None else datetime.fromisoformat(str(params["effective_to"])).date()
        ),
        market_timezone=str(params["market_timezone"]),
        raw_open_eligibility_cutoff_local_time=str(params["raw_open_eligibility_cutoff_local_time"]),
        raw_open_execution_local_time=str(params["raw_open_execution_local_time"]),
        truth_admission=PRE_ALPHA_CEILING,
    )


def _cost_policy_params(policy) -> dict[str, Any]:
    return {
        "commission_rate": policy.commission_rate,
        "minimum_commission": policy.minimum_commission,
    }


class ResearchRunSpecCodec:
    """Persist and deterministically reconstruct a canonical BacktestRunSpec.

    Reconstruction goes exclusively through public canonical constructors
    (profile `create()` factories, the durable Risk owner's
    `require_adjusted_weight_vector`) and is proven by exact content-hash
    equality with the registered `run_spec_id` digest.  Any mismatch fails
    closed before the numeric engine runs.
    """

    def __init__(self, product: "ProductRuntime") -> None:
        self.product = product

    def persist(
        self,
        *,
        spec: BacktestRunSpec,
        rule_profile: AshareTradingRuleProfileVersion,
        cost_policy,
        timing_profile: ExecutionTimingProfileVersion,
        project_id: str,
        project_context_revision_id: str,
        published_at: datetime,
    ) -> tuple[str, str]:
        """Persist spec wire + execution context artifacts; return (run_spec_id, context_artifact_id)."""
        spec_wire = spec.to_wire()
        spec_payload = canonical_json_bytes(spec_wire)
        if spec_wire.get("run_spec_id") != spec.run_spec_id or spec_wire.get("content_sha256") != spec.content_sha256:
            raise V3ContractError("persisted BacktestRunSpec wire identity mismatch")
        context = {
            "schema_version": EXECUTION_CONTEXT_SCHEMA_VERSION,
            "context_kind": RESEARCH_RUN_CONTEXT_KIND,
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "run_spec_id": spec.run_spec_id,
            "run_spec_content_sha256": spec.content_sha256,
            "engine_version": spec.engine_version,
            "rule_profile": _rule_profile_params(rule_profile),
            "cost_policy": _cost_policy_params(cost_policy),
            "execution_timing_profile": _timing_profile_params(timing_profile),
            "published_at": wire_time(published_at),
        }
        context_payload = canonical_json_bytes(context)
        batch = ProductArtifactBatch(
            store=self.product.artifact_store,
            payloads=(
                ("prv_product_run_spec_" + spec.run_spec_id, spec_payload, BACKTEST_RUN_SPEC_ROLE, spec.schema_version),
                (
                    "prv_product_execution_context_" + spec.run_spec_id,
                    context_payload,
                    PRODUCT_EXECUTION_CONTEXT_ROLE,
                    EXECUTION_CONTEXT_SCHEMA_VERSION,
                ),
            ),
            published_at=published_at,
            coordinator=self.product.artifact_publication,
        )
        batch.prepare_intents(
            (
                (project_id, PROJECT_SPEC_REFERENCE_ROLE, 0),
                (project_id, PROJECT_SPEC_CONTEXT_REFERENCE_ROLE, 1),
            )
        )
        connection = connect_catalog(self.product.database_path)
        uow = SQLiteUnitOfWork(
            connection, TransactionMode.PUBLISH, publish_callbacks=batch
        )
        try:
            uow.begin()
            port = SQLiteArtifactPublicationPort(uow)
            spec_result = batch.results[0]
            context_result = batch.results[1]
            port.publish(
                ArtifactPublication(
                    descriptor=spec_result.descriptor,
                    active_references=batch.active_references[0],
                ),
                promotion_intent_id=batch.prepared[0].promotion_intent_id,
            )
            port.publish(
                ArtifactPublication(
                    descriptor=context_result.descriptor,
                    active_references=batch.active_references[1],
                ),
                promotion_intent_id=batch.prepared[1].promotion_intent_id,
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        return spec.run_spec_id, context_result.descriptor.artifact_id

    def resolve_reference(self, project_id: str, role: str) -> list[dict[str, Any]]:
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            rows = catalog_rows(
                connection,
                """
                SELECT owner_id, role, artifact_id FROM artifact_reference
                WHERE owner_id=? AND role=? AND state='ACTIVE'
                """,
                (project_id, role),
            )
        finally:
            connection.close()
        return rows

    def reconstruct(
        self, *, project_id: str, run_spec_id: str
    ) -> tuple[BacktestRunSpec, str]:
        """Reconstruct the canonical spec object; returns (spec, context_artifact_id)."""
        spec_rows = self.resolve_reference(project_id, PROJECT_SPEC_REFERENCE_ROLE)
        context_rows = self.resolve_reference(project_id, PROJECT_SPEC_CONTEXT_REFERENCE_ROLE)
        spec_wire = None
        context_wire = None
        context_artifact_id = None
        for row in context_rows:
            payload = self._read_verified(row["artifact_id"])
            candidate = json.loads(payload.decode("utf-8"))
            if candidate.get("context_kind") == RESEARCH_RUN_CONTEXT_KIND and candidate.get("run_spec_id") == run_spec_id:
                context_wire = candidate
                context_artifact_id = str(row["artifact_id"])
                break
        if context_wire is None:
            raise NotFoundError(f"no durable execution context for run spec: {run_spec_id}")
        for row in spec_rows:
            candidate = self._read_verified(row["artifact_id"])
            wire = json.loads(candidate.decode("utf-8"))
            if wire.get("run_spec_id") == run_spec_id:
                spec_wire = wire
                break
        if spec_wire is None:
            raise NotFoundError(f"no durable BacktestRunSpec wire for: {run_spec_id}")
        return self._rebuild(spec_wire, context_wire), context_artifact_id

    def _read_verified(self, artifact_id: str) -> bytes:
        payload = self.product.read_verified_bytes(artifact_id)
        return payload

    def _rebuild(self, spec_wire: Mapping[str, Any], context: Mapping[str, Any]) -> BacktestRunSpec:
        if spec_wire.get("content_sha256") != context.get("run_spec_content_sha256"):
            raise TruthPreconditionFailedError("execution context and spec content identity diverge")
        run_spec_id = str(spec_wire["run_spec_id"])
        if not isinstance(run_spec_id, str) or not run_spec_id.startswith("btrs_sha256_"):
            raise TruthPreconditionFailedError("run spec identity is not canonical")
        expected_digest = run_spec_id.removeprefix("btrs_sha256_")
        rule_profile = _rebuild_rule_profile(context["rule_profile"])
        if spec_wire.get("rule_profile_id") != rule_profile.profile_id or spec_wire.get(
            "rule_profile_sha256"
        ) != rule_profile.content_sha256:
            raise TruthPreconditionFailedError("rule profile reconstruction mismatch")
        timing_profile = _rebuild_timing_profile(context["execution_timing_profile"])
        if spec_wire.get("execution_timing_profile_id") != timing_profile.profile_id or spec_wire.get(
            "execution_timing_profile_sha256"
        ) != timing_profile.content_sha256:
            raise TruthPreconditionFailedError("execution timing profile reconstruction mismatch")
        cost_policy = cn_a_share_2023_08_28_cost_policy(
            commission_rate=str(context["cost_policy"]["commission_rate"]),
            minimum_commission=str(context["cost_policy"]["minimum_commission"]),
        )
        if spec_wire.get("cost_policy_id") != cost_policy.policy_id or spec_wire.get(
            "cost_policy_sha256"
        ) != cost_policy.content_sha256:
            raise TruthPreconditionFailedError("cost policy reconstruction mismatch")
        engine_version = str(spec_wire["engine_version"])
        if engine_version != ADMITTED_EXECUTION_ADAPTER_VERSION_ID:
            raise TruthPreconditionFailedError(
                f"engine version is not the admitted product adapter: {engine_version}"
            )

        instruments = tuple(
            InstrumentDefinition(str(item["instrument_id"]), Board(str(item["board"])))
            for item in spec_wire["instruments"]
        )
        sessions = tuple(self._rebuild_session(item) for item in spec_wire["sessions"])
        schedule = tuple(self._rebuild_schedule(item) for item in spec_wire["schedule"])
        exact_references = tuple(
            ExactInputReference(
                str(item["reference_kind"]),
                str(item["source_id"]),
                str(item["content_sha256"]),
                PRE_ALPHA_CEILING,
            )
            for item in spec_wire["exact_references"]
        )
        runtime_wire = spec_wire["runtime_identity"]
        runtime_identity = RuntimeIdentity(
            code_version=str(runtime_wire["code_version"]),
            runtime_profile_id=str(runtime_wire["runtime_profile_id"]),
            environment_fingerprint=str(runtime_wire["environment_fingerprint"]),
        )
        spec = BacktestRunSpec.create(
            initial_cash=str(spec_wire["initial_cash"]),
            initial_holdings=tuple(
                InitialHolding(
                    str(item["instrument_id"]),
                    int(item["quantity"]),
                    datetime.fromisoformat(str(item["acquired_on"])).date(),
                )
                for item in spec_wire["initial_holdings"]
            ),
            instruments=instruments,
            sessions=sessions,
            schedule=schedule,
            rule_profile=rule_profile,
            cost_policy=cost_policy,
            execution_timing_profile=timing_profile,
            exact_references=exact_references,
            runtime_identity=runtime_identity,
            engine_version=engine_version,
        )
        if spec.run_spec_id != run_spec_id or spec.content_sha256 != expected_digest:
            raise TruthPreconditionFailedError("reconstructed BacktestRunSpec identity mismatch")
        return spec

    @staticmethod
    def _rebuild_session(wire: Mapping[str, Any]) -> MarketSession:
        return MarketSession(
            session_date=datetime.fromisoformat(str(wire["session_date"])).date(),
            is_open=bool(wire["is_open"]),
            states=tuple(
                DailyMarketState(
                    instrument_id=str(item["instrument_id"]),
                    raw_open=str(item["raw_open"]),
                    raw_close=None if item.get("raw_close") is None else str(item["raw_close"]),
                    suspended=bool(item.get("suspended", False)),
                    tradable=bool(item.get("tradable", True)),
                    buy_restricted=bool(item.get("buy_restricted", False)),
                    restricted_security=bool(item.get("restricted_security", False)),
                    at_limit_up_open=bool(item.get("at_limit_up_open", False)),
                    at_limit_down_open=bool(item.get("at_limit_down_open", False)),
                    no_price_limit_session=bool(item.get("no_price_limit_session", False)),
                )
                for item in wire["states"]
            ),
            corporate_actions=tuple(
                CorporateAction(
                    action_id=str(item["action_id"]),
                    instrument_id=str(item["instrument_id"]),
                    ex_date=datetime.fromisoformat(str(item["ex_date"])).date(),
                    action_type=CorporateActionType(str(item["action_type"])),
                    cash_per_share=str(item.get("cash_per_share", "0")),
                    ratio_numerator=int(item.get("ratio_numerator", 1)),
                    ratio_denominator=int(item.get("ratio_denominator", 1)),
                )
                for item in wire.get("corporate_actions", ())
            ),
        )

    def _rebuild_schedule(self, wire: Mapping[str, Any]) -> ScheduledWeights:
        rawv_id = str(wire["risk_adjusted_weight_vector_id"])
        from v3_backend.adapters.sqlite.risk_application import SQLiteRiskApplicationRepository

        repository = SQLiteRiskApplicationRepository(
            self.product.database_path, self.product.artifact_root
        )
        vector = repository.require_adjusted_weight_vector(rawv_id)
        if vector.content_sha256 != str(wire.get("content_sha256")):
            raise TruthPreconditionFailedError("Risk owner vector content diverges from spec schedule")
        return ScheduledWeights(datetime.fromisoformat(str(wire["effective_at"])), vector)


@dataclass(frozen=True, slots=True)
class DurableIdempotency:
    """Durable per-operation idempotency over the frozen idempotency_record table."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def scope_key(operation_id: str, project_id: str, idempotency_key: str) -> str:
        return f"{operation_id}|{project_id}|{idempotency_key}"

    def check_or_record(
        self,
        *,
        unit: "SQLiteTaskUnitOfWork",
        operation_id: str,
        project_id: str,
        idempotency_key: str,
        canonical_request_hash: str,
        outcome_kind: str,
        outcome: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Return the previously recorded outcome, or record a new one.

        Same key + different canonical request fails closed with
        IDEMPOTENCY_CONFLICT; same key + same request returns the original
        recorded outcome; a brand-new key records atomically with the unit.
        """
        repository: SQLiteTaskRepository = unit.registry.task
        key = self.scope_key(operation_id, project_id, idempotency_key)
        existing = repository.get_idempotency(key)
        if existing is not None:
            if str(existing["canonical_request_hash"]) != canonical_request_hash:
                raise IdempotencyConflictError(
                    "idempotency_key reuse with a different canonical request"
                )
            return json.loads(str(existing["outcome_json"]))
        repository.record_idempotency(
            {
                "scope_key": key,
                "operation_id": operation_id,
                "project_id": project_id,
                "canonical_request_hash": canonical_request_hash,
                "outcome_kind": outcome_kind,
                "outcome_json": json.dumps(dict(outcome), separators=(",", ":"), sort_keys=True),
                "created_at": wire_time(datetime.now(timezone.utc)),
                "expires_at": None,
            }
        )
        return None

    def lookup(
        self, product: "ProductRuntime", scope_key: str, canonical_request_hash: str
    ) -> dict[str, Any] | None:
        connection = connect_catalog(product.database_path, read_only=True)
        try:
            row = catalog_row(
                connection,
                "SELECT canonical_request_hash, outcome_json FROM idempotency_record WHERE scope_key=?",
                (scope_key,),
            )
        finally:
            connection.close()
        if row is None:
            return None
        if str(row["canonical_request_hash"]) != canonical_request_hash:
            raise IdempotencyConflictError(
                "idempotency_key reuse with a different canonical request"
            )
        return json.loads(str(row["outcome_json"]))


def _accept_outcome_json(
    task_id: str,
    run_id: str,
    operation_receipt_id: str | None = None,
) -> str:
    outcome: dict[str, str] = {"task_id": task_id, "run_id": run_id}
    if operation_receipt_id is not None:
        outcome["operation_receipt_id"] = operation_receipt_id
    return json.dumps(outcome, separators=(",", ":"), sort_keys=True)


class ProductExecution:
    """Product executor over the durable Task owner.

    Every mutation is durable through SQLiteTaskPersistence
    before and after engine execution; the Run's durable EXECUTION_CONTEXT
    artifact reference makes retry re-execution deterministic and
    restart-safe.  Failure transitions are persisted with an ErrorCategory
    classification.
    """

    def __init__(self, product: "ProductRuntime") -> None:
        self.product = product
        self.engine = DeterministicAshareBacktestEngine()
        self.retry_policy = RetryPolicy()

    def operation_receipt_id_for_task(self, task_id: str) -> str | None:
        """Return the durable receipt bound to a newly accepted Task, if any."""

        try:
            return self.product.progress_persistence.receipt_for_task(task_id).operation_receipt_id
        except KeyError:
            # Legacy Tasks without an execution deadline predate PR03
            # receipts and may legitimately replay without one.  A deadline
            # Task, however, has a receipt as part of its accepted side
            # effect.  Do not let a Catalog gap turn that task into a replay
            # response that cannot be queried for its finality.
            connection = self.product._connection(read_only=True)
            try:
                row = connection.execute(
                    """
                    SELECT t.execution_deadline_at,a.execution_deadline_at
                    FROM task AS t
                    LEFT JOIN run AS r
                      ON r.task_id=t.task_id
                     AND r.run_no=(
                        SELECT MAX(latest_run.run_no)
                        FROM run AS latest_run
                        WHERE latest_run.task_id=t.task_id
                     )
                    LEFT JOIN task_attempt AS a
                      ON a.run_id=r.run_id
                     AND a.attempt_no=(
                        SELECT MAX(latest_attempt.attempt_no)
                        FROM task_attempt AS latest_attempt
                        WHERE latest_attempt.run_id=r.run_id
                     )
                    WHERE t.task_id=?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()
            if row is not None and (row[0] is not None or row[1] is not None):
                raise self.product._runtime_context_corrupt(
                    "deadline-bound Task is missing its durable operation receipt"
                )
            return None

    @staticmethod
    def _parse_execution_deadline(value: str) -> datetime:
        if (
            not isinstance(value, str)
            or len(value) > 64
            or _CANONICAL_UTC_DEADLINE.fullmatch(value) is None
        ):
            raise InvalidArgumentError("execution deadline must be bounded RFC3339 UTC")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as error:
            raise InvalidArgumentError(
                "execution deadline must be bounded RFC3339 UTC"
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise InvalidArgumentError("execution deadline must include UTC")
        return parsed.astimezone(timezone.utc)

    def _assert_deadline_before_side_effect(self, deadline_at: str | None = None) -> None:
        """Apply the request-owned absolute deadline at a Catalog boundary."""

        if deadline_at is None:
            from .request_router import current_request_deadline_at

            deadline_at = current_request_deadline_at()
        if deadline_at is None:
            deadline_at = getattr(self.product, "_active_control_deadline_at", None)
        if deadline_at is None:
            return
        if datetime.now(timezone.utc) >= self._parse_execution_deadline(deadline_at):
            raise ResourceRejectedError(
                "operation deadline expired before irreversible side effect",
                details={"reason_code": "DEADLINE_EXCEEDED_PRE_COMMIT"},
            )

    def _record_progress(
        self,
        task: Task,
        run: Run,
        attempt: TaskAttempt,
        *,
        phase: str,
        completed_units: int,
        total_units: int,
        work_unit: str,
    ) -> None:
        allowed = {"ACQUIRING", "VALIDATING", "COMPUTING", "PUBLISHING", "RECONCILING"}
        if phase not in allowed:
            raise ValueError("Task progress phase is not admitted")
        if (
            not isinstance(completed_units, int)
            or isinstance(completed_units, bool)
            or not isinstance(total_units, int)
            or isinstance(total_units, bool)
            or total_units < 1
            or completed_units < 0
            or completed_units > total_units
            or not isinstance(work_unit, str)
            or not work_unit
            or len(work_unit) > 128
        ):
            raise ValueError("Task progress work units are invalid")
        current_task = self.product.task_persistence.read_task(task.task_id)
        if current_task.project_id != task.project_id or current_task.state in TASK_TERMINAL_STATES:
            raise ImpossibleTransition("terminal or cross-project Task cannot record progress")
        self.product.progress_persistence.record_progress(
            attempt.attempt_id,
            phase=phase,
            completed_units=completed_units,
            total_units=total_units,
            work_unit=work_unit,
        )

    # -- durable task phases ------------------------------------------------

    def _create_task(
        self,
        *,
        operation_id: str,
        project_id: str,
        project_context_revision_id: str,
        normalized_input_hash: str,
        context_artifact_id: str | None,
        idempotency: tuple[str, str, str] | None = None,
        is_batch: bool = False,
        execution_deadline_at: str | None = None,
        inline_worker: bool = True,
        service_contract_version: str = "1.0.0",
        canonical_input: Mapping[str, Any] | None = None,
    ) -> tuple[Task, Run, TaskAttempt]:
        if self.product._shutdown_prepared or self.product._shutdown_committed:
            raise ConflictError("runtime is shutting down and no new Task may be accepted")
        self._assert_deadline_before_side_effect(execution_deadline_at)
        run_id = mint_v3_id("run_")
        task = Task(
            task_id=mint_v3_id("tsk_"),
            project_id=project_id,
            operation_id=operation_id,
            active_run_id=run_id,
            state=TaskState.QUEUED,
            state_version=0,
            execution_epoch=0,
            is_batch=is_batch,
            child_task_ids=(),
        )
        run = Run(
            run_id=run_id,
            task_id=task.task_id,
            identity=RunIdentity(
                project_context_revision_id=project_context_revision_id,
                normalized_input_hash=normalized_input_hash,
                code_version=PRODUCT_CODE_VERSION,
                environment_profile=INLINE_ENVIRONMENT_PROFILE_ID,
                service_contract_version=service_contract_version,
            ),
            state=RunState.SEALED,
            state_version=0,
        )
        attempt = TaskAttempt(
            attempt_id=mint_v3_id("att_"),
            task_id=task.task_id,
            run_id=run_id,
            ordinal=1,
            state=AttemptState.QUEUED,
            state_version=0,
            lease_id=mint_v3_id("lea_") if inline_worker else None,
            resume_checkpoint_artifact_id=None,
            terminal_error_category=None,
        )
        operation_receipt_id: str | None = None
        correlation_id: str | None = None
        receipt_deadline: datetime | None = None
        if execution_deadline_at is not None:
            receipt_deadline = self._parse_execution_deadline(execution_deadline_at)
            from .request_router import current_request_correlation_id

            correlation_id = current_request_correlation_id() or f"local:{run_id}"
            operation_receipt_id = mint_v3_id("opr_")
        now = wire_time(datetime.now(timezone.utc))
        with self.product.task_persistence.begin() as unit:
            unit.add_task(task)
            unit.add_run(run, canonical_input=canonical_input)
            unit.add_attempt(attempt)
            if self.product.runtime_generation_id is not None:
                cursor = unit.connection.execute(
                    "UPDATE task_attempt SET runtime_generation_id=? WHERE attempt_id=?",
                    (self.product.runtime_generation_id, attempt.attempt_id),
                )
                if cursor.rowcount != 1:
                    raise ConflictError("Attempt runtime generation could not be persisted")
            if execution_deadline_at is not None:
                unit.connection.execute(
                    "UPDATE task SET execution_deadline_at=? WHERE task_id=?",
                    (execution_deadline_at, task.task_id),
                )
                unit.connection.execute(
                    "UPDATE task_attempt SET execution_deadline_at=? WHERE attempt_id=?",
                    (execution_deadline_at, attempt.attempt_id),
                )
            if (
                operation_receipt_id is not None
                and correlation_id is not None
                and receipt_deadline is not None
            ):
                self.product.progress_persistence.create_receipt_in_transaction(
                    unit.connection,
                    operation_receipt_id=operation_receipt_id,
                    correlation_id=correlation_id,
                    operation_id=operation_id,
                    project_id=project_id,
                    deadline_at=receipt_deadline,
                    runtime_generation_id=self.product.runtime_generation_id,
                    task_id=task.task_id,
                    run_id=run_id,
                    attempt_id=attempt.attempt_id,
                )
            if inline_worker:
                worker_id = mint_v3_id("wrk_")
                unit.connection.execute(
                    """
                    INSERT INTO worker(worker_id, worker_kind, process_id, environment_profile_id,
                                       state, started_at)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (worker_id, INLINE_WORKER_KIND, os.getpid(), INLINE_ENVIRONMENT_PROFILE_ID, "BUSY", now),
                )
                unit.connection.execute(
                    """
                    INSERT INTO worker_lease(lease_id, attempt_id, worker_id, cpu_slots,
                                             memory_limit_bytes, scratch_limit_bytes, state,
                                             granted_at, expires_at)
                    VALUES(?,?,?,1,1073741824,1073741824,'GRANTED',?,?)
                    """,
                    (
                        attempt.lease_id,
                        attempt.attempt_id,
                        worker_id,
                        now,
                        wire_time(datetime.now(timezone.utc) + timedelta(hours=1)),
                    ),
                )
            if context_artifact_id is not None:
                unit.connection.execute(
                    """
                    INSERT INTO artifact_reference(artifact_reference_id, owner_type, owner_id,
                                                   role, artifact_id, state, created_at)
                    VALUES(?,'Run',?,?,?,'ACTIVE',?)
                    """,
                    (mint_v3_id("arf_"), run_id, RUN_CONTEXT_REFERENCE_ROLE, context_artifact_id, now),
                )
            unit.append_event(
                PendingTaskEvent(
                    event_id=mint_v3_id("tev_"),
                    event_version=_TASK_EVENT_VERSION,
                    project_id=project_id,
                    task_id=task.task_id,
                    event_type="TASK_QUEUED",
                    occurred_at=datetime.now(timezone.utc),
                    payload={"operation_id": operation_id},
                    run_id=run_id,
                    attempt_id=None,
                )
            )
            if idempotency is not None:
                scope_key, request_hash, outcome_factory = idempotency
                unit.registry.task.record_idempotency(
                    {
                        "scope_key": scope_key,
                        "operation_id": operation_id,
                        "project_id": project_id,
                        "canonical_request_hash": request_hash,
                        "outcome_kind": "TASK_ACCEPTED",
                        "outcome_json": outcome_factory(
                            task.task_id, run_id, operation_receipt_id
                        ),
                        "created_at": now,
                        "expires_at": None,
                    }
                )
            self._assert_deadline_before_side_effect(execution_deadline_at)
            unit.commit()
        return task, run, attempt

    def _transition_to_running(
        self, task: Task, run: Run, attempt: TaskAttempt, *, run_transition: bool = True
    ) -> None:
        self._assert_deadline_before_side_effect()
        with self.product.task_persistence.begin() as unit:
            current_task = unit.require_task(task.task_id)
            current_run = unit.require_run(run.run_id)
            current_attempt = unit.require_attempt(attempt.attempt_id)
            deadline_row = unit.connection.execute(
                "SELECT execution_deadline_at FROM task_attempt WHERE attempt_id=?",
                (current_attempt.attempt_id,),
            ).fetchone()
            deadline_at = None if deadline_row is None else deadline_row[0]
            if deadline_at is not None:
                self._assert_deadline_before_side_effect(str(deadline_at))
            # The inline compatibility path still uses the PR03 durable
            # admission boundary.  Keep queue control, receipt state and the
            # aggregate transition in one Catalog transaction so a failed
            # start cannot leave a visible RUNNING Task with a HOLD receipt or
            # a stale dispatch control row.
            self.product.progress_persistence.mark_dispatched_in_transaction(
                unit.connection,
                current_task.task_id,
                user_confirmed_at=datetime.now(timezone.utc),
            )
            self.product.progress_persistence.mark_receipt_running_in_transaction(
                unit.connection,
                current_attempt.attempt_id,
            )
            current_task.state = transition_task(
                current_task.state,
                "ATTEMPT_STARTED",
                TaskTransitionContext(active_lease_persisted=True),
            )
            if run_transition:
                current_run.state = transition_run(current_run.state, "ATTEMPT_ACTIVATED")
            for event, expected in (
                ("LEASE_GRANTED", AttemptState.LEASED),
                ("WORKER_DISPATCHED", AttemptState.STARTING),
                ("WORKER_ACKNOWLEDGED", AttemptState.RUNNING),
            ):
                current_attempt.state = transition_attempt(current_attempt.state, event)
                if current_attempt.state is not expected:
                    raise ImpossibleTransition(f"attempt transition produced {current_attempt.state}")
            unit.save_task(current_task, expected_version=current_task.state_version)
            if run_transition:
                unit.save_run(current_run, expected_version=current_run.state_version)
            unit.save_attempt(current_attempt, expected_version=current_attempt.state_version)
            unit.append_event(
                PendingTaskEvent(
                    event_id=mint_v3_id("tev_"),
                    event_version=_TASK_EVENT_VERSION,
                    project_id=current_task.project_id,
                    task_id=current_task.task_id,
                    event_type="TASK_STARTED",
                    occurred_at=datetime.now(timezone.utc),
                    payload={"state": current_task.state.value},
                    run_id=current_run.run_id,
                    attempt_id=current_attempt.attempt_id,
                )
            )
            if deadline_at is not None:
                self._assert_deadline_before_side_effect(str(deadline_at))
            unit.commit()

    @staticmethod
    def _stop_worker_for_attempt(unit: SQLiteTaskUnitOfWork, attempt_id: str, now: str) -> None:
        """Close the per-task inline worker without creating a second registry."""
        unit.connection.execute(
            """
            UPDATE worker
            SET state='STOPPED', stopped_at=?
            WHERE worker_id IN (
                SELECT worker_id FROM worker_lease WHERE attempt_id=?
            )
              AND state IN ('STARTING','IDLE','BUSY','DRAINING')
            """,
            (now, attempt_id),
        )

    def _finish_success(
        self,
        task: Task,
        run: Run,
        attempt: TaskAttempt,
        outputs: Mapping[str, str],
        *,
        run_transition: bool = True,
        artifact_outputs: tuple[tuple[str, int, str], ...] = (),
    ) -> None:
        self._assert_deadline_before_side_effect()
        with self.product.task_persistence.begin() as unit:
            current_task = unit.require_task(task.task_id)
            current_run = unit.require_run(run.run_id)
            current_attempt = unit.require_attempt(attempt.attempt_id)
            deadline_row = unit.connection.execute(
                "SELECT execution_deadline_at FROM task_attempt WHERE attempt_id=?",
                (current_attempt.attempt_id,),
            ).fetchone()
            if deadline_row is not None and deadline_row[0] is not None:
                self._assert_deadline_before_side_effect(str(deadline_row[0]))
            # The terminal progress record is part of the same Catalog UoW as
            # Attempt/Task/receipt finality.  A second connection here would
            # permit a durable SUCCEEDED Task with a missing or late PUBLISHED
            # record when the worker exits between the two writes.
            self.product.progress_persistence.record_progress_in_transaction(
                unit.connection,
                current_attempt.attempt_id,
                phase="PUBLISHED",
                completed_units=3,
                total_units=3,
                work_unit="pipeline_phases",
                counters={"canonical_terminal": 1},
                occurred_at=datetime.now(timezone.utc),
            )
            # Progress is also an attempt-scoped TaskEvent, and the frozen
            # SQLite adapter derives Attempt.state_version from that event
            # stream.  Re-read after the append so the terminal CAS includes
            # the final progress event rather than using a stale version.
            current_attempt = unit.require_attempt(current_attempt.attempt_id)
            current_attempt.state = transition_attempt(current_attempt.state, "ATTEMPT_SUCCEEDED")
            unit.save_attempt(current_attempt, expected_version=current_attempt.state_version)
            if run_transition:
                current_run.state = transition_run(
                    current_run.state, "TASK_TERMINAL_NO_ACTIVE_ATTEMPT", no_active_attempt=True
                )
                unit.save_run(current_run, expected_version=current_run.state_version)
            current_task.state = transition_task(
                current_task.state,
                "ALL_REQUIRED_ARTIFACTS_PUBLISHED",
                TaskTransitionContext(successful_attempt=True, publication_committed=True),
            )
            unit.save_task(current_task, expected_version=current_task.state_version)
            completed_at = wire_time(datetime.now(timezone.utc))
            for output_role, ordinal, artifact_id in artifact_outputs:
                unit.connection.execute(
                    """
                    INSERT INTO task_output(
                      task_id,output_role,ordinal,artifact_id,created_at
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        current_task.task_id,
                        output_role,
                        ordinal,
                        artifact_id,
                        completed_at,
                    ),
                )
            unit.append_event(
                PendingTaskEvent(
                    event_id=mint_v3_id("tev_"),
                    event_version=_TASK_EVENT_VERSION,
                    project_id=current_task.project_id,
                    task_id=current_task.task_id,
                    event_type="TASK_SUCCEEDED",
                    occurred_at=datetime.now(timezone.utc),
                    payload={"outputs": dict(outputs)},
                    run_id=current_run.run_id,
                    attempt_id=current_attempt.attempt_id,
                )
            )
            unit.connection.execute(
                """
                UPDATE worker_lease SET state='RELEASED', released_at=?
                WHERE attempt_id=? AND state IN ('GRANTED','RENEWED')
                """,
                (wire_time(datetime.now(timezone.utc)), current_attempt.attempt_id),
            )
            self._stop_worker_for_attempt(
                unit, current_attempt.attempt_id, wire_time(datetime.now(timezone.utc))
            )
            committed_receipt = self.product.progress_persistence.finalize_receipt_in_transaction(
                unit.connection,
                attempt_id=current_attempt.attempt_id,
                success=True,
                outcome={"task_id": current_task.task_id, **dict(outputs)},
                commit_boundary_at=datetime.now(timezone.utc),
                complete=False,
            )
            if deadline_row is not None and deadline_row[0] is not None:
                self._assert_deadline_before_side_effect(str(deadline_row[0]))
            unit.commit()
            if committed_receipt is not None:
                self.product.progress_persistence.complete_receipt(
                    committed_receipt.operation_receipt_id
                )

    def _finish_failure(
        self,
        task: Task,
        run: Run,
        attempt: TaskAttempt,
        *,
        error: BaseException,
        category: ErrorCategory,
        run_transition: bool = True,
    ) -> None:
        reason_code: str | None = None
        if isinstance(error, V3ContractError):
            candidate = error.details.get("reason_code")
            if isinstance(candidate, str) and 1 <= len(candidate) <= 128:
                reason_code = candidate
        if reason_code is None:
            candidate = getattr(error, "reason_code", None)
            if isinstance(candidate, str) and 1 <= len(candidate) <= 128:
                reason_code = candidate
        with self.product.task_persistence.begin() as unit:
            current_task = unit.require_task(task.task_id)
            current_run = unit.require_run(run.run_id)
            current_attempt = unit.require_attempt(attempt.attempt_id)
            if current_task.state in TASK_TERMINAL_STATES:
                return
            if current_attempt.state in ATTEMPT_TERMINAL_STATES:
                if current_attempt.state is not AttemptState.FAILED:
                    raise ImpossibleTransition(
                        "failure finalization cannot overwrite a non-failed terminal Attempt"
                    )
                if current_attempt.terminal_error_category is None:
                    current_attempt.terminal_error_category = category.value
                    unit.save_attempt(
                        current_attempt,
                        expected_version=current_attempt.state_version,
                    )
            else:
                current_attempt.terminal_error_category = category.value
                current_attempt.state = transition_attempt(
                    current_attempt.state,
                    "ATTEMPT_FAILED",
                )
                unit.save_attempt(
                    current_attempt,
                    expected_version=current_attempt.state_version,
                )
            if run_transition and current_run.state is not RunState.TERMINAL:
                current_run.state = transition_run(
                    current_run.state, "TASK_TERMINAL_NO_ACTIVE_ATTEMPT", no_active_attempt=True
                )
                unit.save_run(current_run, expected_version=current_run.state_version)
            current_task.state = transition_task(
                current_task.state,
                "ATTEMPT_FAILED_NO_RETRY",
                TaskTransitionContext(error_persisted=True),
            )
            unit.save_task(current_task, expected_version=current_task.state_version)
            failure_payload: dict[str, Any] = {
                "error_type": type(error).__name__,
                "error_message": str(error)[:2048],
                "error_category": category.value,
            }
            if reason_code is not None:
                failure_payload["reason_code"] = reason_code
            unit.append_event(
                PendingTaskEvent(
                    event_id=mint_v3_id("tev_"),
                    event_version=_TASK_EVENT_VERSION,
                    project_id=current_task.project_id,
                    task_id=current_task.task_id,
                    event_type="TASK_FAILED",
                    occurred_at=datetime.now(timezone.utc),
                    payload=failure_payload,
                    run_id=current_run.run_id,
                    attempt_id=current_attempt.attempt_id,
                )
            )
            unit.connection.execute(
                """
                UPDATE worker_lease SET state='RELEASED', released_at=?
                WHERE attempt_id=? AND state IN ('GRANTED','RENEWED')
                """,
                (wire_time(datetime.now(timezone.utc)), current_attempt.attempt_id),
            )
            self._stop_worker_for_attempt(
                unit, current_attempt.attempt_id, wire_time(datetime.now(timezone.utc))
            )
            self.product.progress_persistence.finalize_receipt_in_transaction(
                unit.connection,
                attempt_id=current_attempt.attempt_id,
                success=False,
                error_code=reason_code or category.value,
            )
            unit.commit()

    def _latest_sequence(self, project_id: str) -> int:
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            value = connection.execute(
                "SELECT COALESCE(MAX(project_sequence),0) FROM task_event WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        return int(value)

    # -- publication helpers -------------------------------------------------

    def _publish_artifact_batch(
        self,
        *,
        payloads: tuple[tuple[Any, ...], ...],
        references: tuple[tuple[str, str, str], ...],
        deadline_at: str | None = None,
    ) -> list[Any]:
        """references: (owner_id, role, artifact_index)."""
        self._assert_deadline_before_side_effect(deadline_at)
        published_at = datetime.now(timezone.utc)
        batch = ProductArtifactBatch(
            store=self.product.artifact_store,
            payloads=payloads,
            published_at=published_at,
            coordinator=self.product.artifact_publication,
        )
        batch.prepare_intents(references)
        self._assert_deadline_before_side_effect(deadline_at)
        connection = connect_catalog(self.product.database_path)
        uow = SQLiteUnitOfWork(connection, TransactionMode.PUBLISH, publish_callbacks=batch)
        results: list[Any] = []
        try:
            uow.begin()
            port = SQLiteArtifactPublicationPort(uow)
            for index, item in enumerate(payloads):
                descriptor = batch.results[index].descriptor
                port.publish(
                    ArtifactPublication(
                        descriptor=descriptor,
                        active_references=batch.active_references[index],
                    ),
                    promotion_intent_id=batch.prepared[index].promotion_intent_id,
                )
                results.append(batch.results[index])
            self._assert_deadline_before_side_effect(deadline_at)
            uow.commit()
            return results
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    def _publish_staged_artifact(
        self,
        *,
        staging: StagingReceipt,
        provenance_entity_id: str,
        role: str,
        media_type: str,
        schema_fingerprint: str,
        references: tuple[tuple[str, str], ...],
    ) -> Any:
        """Publish one bounded stream through the canonical Artifact/Catalog owner."""

        self._assert_deadline_before_side_effect()
        published_at = datetime.now(timezone.utc)
        callbacks = ProductStagedArtifact(
            store=self.product.artifact_store,
            staging=staging,
            provenance_entity_id=provenance_entity_id,
            role=role,
            media_type=media_type,
            schema_fingerprint=schema_fingerprint,
            published_at=published_at,
            coordinator=self.product.artifact_publication,
        )
        callbacks.prepare_intent(references)
        self._assert_deadline_before_side_effect()
        connection = connect_catalog(self.product.database_path)
        uow = SQLiteUnitOfWork(connection, TransactionMode.PUBLISH, publish_callbacks=callbacks)
        try:
            uow.begin()
            if callbacks.result is None:
                raise V3ContractError("pre-staged product artifact publication produced no result")
            descriptor = callbacks.result.descriptor
            SQLiteArtifactPublicationPort(uow).publish(
                ArtifactPublication(
                    descriptor=descriptor,
                    active_references=callbacks.active_references,
                ),
                promotion_intent_id=callbacks.prepared.promotion_intent_id,
            )
            self._assert_deadline_before_side_effect()
            uow.commit()
            return callbacks.result
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    def _publish_backtest_outputs(
        self, *, project_id: str, run_id: str, result: BacktestRunResult
    ) -> dict[str, Any]:
        """Publish the canonical result artifact + ledger manifest + durable Result row."""
        result_payload = canonical_json_bytes(result.to_wire())
        manifest_wire = {
            "schema_version": "v3.ledger-manifest/1.0.0",
            "backtest_result_id": result.result_id,
            "backtest_result_sha256": result.content_sha256,
            "run_spec_id": result.run_spec_id,
            "ledger_digests": {
                "cash_ledger": canonical_sha256([row.to_wire() for row in result.cash_ledger]),
                "position_ledger": canonical_sha256([row.to_wire() for row in result.position_ledger]),
                "orders": canonical_sha256([row.to_wire() for row in result.orders]),
                "fills": canonical_sha256([row.to_wire() for row in result.fills]),
                "holdings": canonical_sha256([row.to_wire() for row in result.holdings]),
                "nav": canonical_sha256([row.to_wire() for row in result.nav]),
            },
        }
        manifest_payload = canonical_json_bytes(manifest_wire)
        published = self._publish_artifact_batch(
            payloads=(
                (
                    "prv_backtest_run_result_" + result.result_id,
                    result_payload,
                    BACKTEST_RUN_RESULT_ROLE,
                    result.schema_version,
                ),
                (
                    "prv_ledger_manifest_" + result.result_id,
                    manifest_payload,
                    LEDGER_MANIFEST_ROLE,
                    "v3.ledger-manifest/1.0.0",
                ),
            ),
            references=(
                (run_id, RUN_RESULT_REFERENCE_ROLE, 0),
                (run_id, RUN_LEDGER_MANIFEST_REFERENCE_ROLE, 1),
            ),
        )
        result_publication = published[0]
        manifest_publication = published[1]
        result_id = mint_v3_id("res_")
        lineage_hash = canonical_sha256(
            {
                "run_id": run_id,
                "backtest_result_id": result.result_id,
                "result_artifact_id": result_publication.descriptor.artifact_id,
                "ledger_manifest_artifact_id": manifest_publication.descriptor.artifact_id,
            }
        )
        now = wire_time(datetime.now(timezone.utc))
        connection = connect_catalog(self.product.database_path)
        uow = SQLiteUnitOfWork(connection, TransactionMode.PUBLISH, publish_callbacks=_NoopPublishCallbacks())
        try:
            uow.begin()
            SQLiteRepositoryRegistry(uow).result.publish_result(
                {
                    "result_id": result_id,
                    "project_id": project_id,
                    "backtest_run_id": run_id,
                    "ledger_manifest_artifact_id": manifest_publication.descriptor.artifact_id,
                    "reconciliation_artifact_id": None,
                    "state": "PENDING_RECONCILIATION",
                    "invalid_reason_code": None,
                    "lineage_hash": lineage_hash,
                    "created_at": now,
                }
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        return {
            "result_id": result_id,
            "result_artifact_id": result_publication.descriptor.artifact_id,
            "result_artifact_sha256": result_publication.descriptor.sha256,
            "ledger_manifest_artifact_id": manifest_publication.descriptor.artifact_id,
            "backtest_result_id": result.result_id,
        }

    # -- golden execution ------------------------------------------------------

    def submit_backtest(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        run_spec_id: str,
        execution_adapter_version_id: str,
        idempotency_key: str,
    ) -> ExecutionOutcome:
        self.product.require_project_context_ownership(project_id, project_context_revision_id)
        if execution_adapter_version_id != ADMITTED_EXECUTION_ADAPTER_VERSION_ID:
            raise TruthPreconditionFailedError(
                f"execution adapter is not admitted: {execution_adapter_version_id}"
            )
        operation_id = "BacktestService.v1.submitBacktest"
        semantic = {
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "run_spec_id": run_spec_id,
            "execution_adapter_version_id": execution_adapter_version_id,
        }
        scope = DurableIdempotency.scope_key(operation_id, project_id, idempotency_key)
        request_hash = _canonical_request_hash(operation_id, semantic)
        existing = DurableIdempotency().lookup(self.product, scope, request_hash)
        if existing is not None:
            return ExecutionOutcome(
                str(existing["task_id"]), str(existing["run_id"]), None
            )
        spec, context_artifact_id = self.product.spec_codec.reconstruct(
            project_id=project_id, run_spec_id=run_spec_id
        )
        context_wire = json.loads(
            self.product.read_verified_bytes(context_artifact_id).decode("utf-8")
        )
        if context_wire.get("project_context_revision_id") != project_context_revision_id:
            raise TruthPreconditionFailedError(
                "run spec context is bound to a different project context revision"
            )
        normalized_input_hash = canonical_sha256(
            {"run_spec_id": run_spec_id, "execution_adapter_version_id": execution_adapter_version_id}
        )
        task, run, attempt = self._create_task(
            operation_id=operation_id,
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            normalized_input_hash=normalized_input_hash,
            context_artifact_id=context_artifact_id,
            idempotency=(scope, request_hash, _accept_outcome_json),
        )
        try:
            self._transition_to_running(task, run, attempt)
            event_cursor = self._latest_sequence(project_id)
            result = self.engine.run(spec)
        except Exception as error:
            self._finish_failure(
                task, run, attempt, error=error, category=classify_execution_error(error)
            )
            return ExecutionOutcome(task.task_id, run.run_id, self._latest_sequence(project_id))
        try:
            outputs = self._publish_backtest_outputs(
                project_id=project_id, run_id=run.run_id, result=result
            )
            self._finish_success(task, run, attempt, outputs=outputs)
        except Exception as error:
            self._finish_failure(
                task, run, attempt, error=error, category=classify_execution_error(error)
            )
        return ExecutionOutcome(task.task_id, run.run_id, event_cursor)

    def submit_research(self, submission: ProductResearchSubmission) -> dict[str, Any]:
        """Execute the one bounded Product Entry research composition."""
        return self.product.research.submit(submission)

    def export_artifacts(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        artifact_ids: tuple[str, ...],
        export_profile_id: str,
        destination_token: str,
        idempotency_key: str,
    ) -> ExecutionOutcome:
        self.product.require_project_context_ownership(project_id, project_context_revision_id)
        if export_profile_id not in EXPORT_PROFILES:
            raise InvalidArgumentError(f"unknown export profile: {export_profile_id}")
        if len(artifact_ids) != 1:
            raise InvalidArgumentError("V1.1 native export requires exactly one Artifact")
        if (
            not destination_token.startswith("edc_")
            or len(destination_token) < 16
            or len(destination_token) > 128
        ):
            raise InvalidArgumentError("destination_token is not an admitted Electron capability")
        for artifact_id in artifact_ids:
            self.product.require_project_reachable_artifact(project_id, artifact_id)
        operation_id = "ArtifactService.v1.exportArtifact"
        semantic = {
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "artifact_ids": list(artifact_ids),
            "export_profile_id": export_profile_id,
            "destination_token": destination_token,
        }
        scope = DurableIdempotency.scope_key(operation_id, project_id, idempotency_key)
        request_hash = _canonical_request_hash(operation_id, semantic)
        existing = DurableIdempotency().lookup(self.product, scope, request_hash)
        if existing is not None:
            return ExecutionOutcome(str(existing["task_id"]), str(existing["run_id"]), None)
        normalized_input_hash = canonical_sha256(
            {"artifact_ids": list(artifact_ids), "export_profile_id": export_profile_id}
        )
        context_artifact_id = self._persist_context_artifact(
            {
                "schema_version": EXECUTION_CONTEXT_SCHEMA_VERSION,
                "context_kind": EXPORT_CONTEXT_KIND,
                "project_id": project_id,
                "project_context_revision_id": project_context_revision_id,
                "artifact_ids": list(artifact_ids),
                "export_profile_id": export_profile_id,
                "destination_token": destination_token,
            },
            provenance="prv_product_export_context",
        )
        task, run, attempt = self._create_task(
            operation_id=operation_id,
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            normalized_input_hash=normalized_input_hash,
            context_artifact_id=context_artifact_id,
            idempotency=(scope, request_hash, _accept_outcome_json),
        )
        self._transition_to_running(task, run, attempt)
        event_cursor = self._latest_sequence(project_id)
        return ExecutionOutcome(task.task_id, run.run_id, event_cursor)

    def complete_artifact_export(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        task_id: str,
        destination_token: str,
        display_name: str,
        artifact_id: str,
        sha256: str,
        byte_size: int,
        completed_at: str,
    ) -> dict[str, Any]:
        """Finalize an export only after Electron attests an exact native write."""

        self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
            raise InvalidArgumentError("export byte_size must be a non-negative integer")
        if (
            not display_name
            or len(display_name) > 255
            or "/" in display_name
            or "\\" in display_name
            or display_name in {".", ".."}
        ):
            raise InvalidArgumentError("export display_name is invalid")
        if not completed_at.endswith("Z"):
            raise InvalidArgumentError("completed_at must be RFC3339 UTC")
        try:
            completed = datetime.fromisoformat(completed_at[:-1] + "+00:00")
        except ValueError as exc:
            raise InvalidArgumentError("completed_at must be RFC3339 UTC") from exc
        task = self.product.task_persistence.read_task(task_id)
        if task.project_id != project_id or task.operation_id != "ArtifactService.v1.exportArtifact":
            raise TruthPreconditionFailedError("export Task does not belong to this project/operation")
        if task.state is not TaskState.RUNNING:
            raise ConflictError("export Task is not awaiting native completion")
        run = self._read_run(task.active_run_id)
        attempt = self.product.task_persistence.latest_attempt(task_id)
        context_wire = json.loads(
            self.product.read_verified_bytes(
                self._run_context_artifact(run.run_id)
            ).decode("utf-8")
        )
        if (
            context_wire.get("context_kind") != EXPORT_CONTEXT_KIND
            or context_wire.get("project_id") != project_id
            or context_wire.get("project_context_revision_id")
            != project_context_revision_id
            or context_wire.get("destination_token") != destination_token
            or context_wire.get("artifact_ids") != [artifact_id]
        ):
            raise TruthPreconditionFailedError("native export receipt does not match its durable context")
        descriptor = self.product.require_project_reachable_artifact(
            project_id, artifact_id
        )
        if (
            str(descriptor["sha256"]) != sha256
            or int(descriptor["byte_size"]) != byte_size
            or artifact_id != f"art_sha256_{sha256}"
        ):
            raise TruthPreconditionFailedError("native export receipt does not match Artifact identity")
        # Re-read through the verified Artifact handle at finalization time; a
        # desktop receipt cannot replace canonical payload integrity.
        payload = self.product.read_verified_bytes(artifact_id)
        if len(payload) != byte_size or hashlib.sha256(payload).hexdigest() != sha256:
            raise TruthPreconditionFailedError("native export source bytes changed before finalization")
        manifest_wire = {
            "schema_version": "v3.export-manifest/1.0.0",
            "export_profile_id": context_wire["export_profile_id"],
            "display_name": display_name,
            "completed_at": wire_time(completed),
            "artifacts": [
                {
                    "artifact_id": artifact_id,
                    "sha256": sha256,
                    "byte_size": byte_size,
                }
            ],
        }
        output = self._publish_artifact_batch(
            payloads=(
                (
                    "prv_product_export_manifest",
                    canonical_json_bytes(manifest_wire),
                    EXPORT_MANIFEST_ROLE,
                    "v3.export-manifest/1.0.0",
                ),
            ),
            references=((run.run_id, RUN_EXPORT_MANIFEST_REFERENCE_ROLE, 0),),
        )[0]
        self._finish_success(
            task,
            run,
            attempt,
            outputs={
                "artifact_id": output.descriptor.artifact_id,
                "artifact_sha256": output.descriptor.sha256,
            },
        )
        return {
            "kind": "artifactExport.completed",
            "task_id": task_id,
            "manifest_artifact_id": output.descriptor.artifact_id,
        }

    def fail_artifact_export(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        task_id: str,
        destination_token: str,
        reason_code: str,
    ) -> dict[str, Any]:
        self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        if not reason_code or len(reason_code) > 128:
            raise InvalidArgumentError("export failure reason_code is invalid")
        task = self.product.task_persistence.read_task(task_id)
        if task.project_id != project_id or task.operation_id != "ArtifactService.v1.exportArtifact":
            raise TruthPreconditionFailedError("export Task does not belong to this project/operation")
        if task.state is not TaskState.RUNNING:
            raise ConflictError("export Task is not awaiting native completion")
        run = self._read_run(task.active_run_id)
        attempt = self.product.task_persistence.latest_attempt(task_id)
        context_wire = json.loads(
            self.product.read_verified_bytes(
                self._run_context_artifact(run.run_id)
            ).decode("utf-8")
        )
        if (
            context_wire.get("context_kind") != EXPORT_CONTEXT_KIND
            or context_wire.get("project_id") != project_id
            or context_wire.get("project_context_revision_id")
            != project_context_revision_id
            or context_wire.get("destination_token") != destination_token
        ):
            raise TruthPreconditionFailedError("native export failure does not match its durable context")
        self._finish_failure(
            task,
            run,
            attempt,
            error=V3ContractError(reason_code),
            category=ErrorCategory.INTERNAL_ERROR,
        )
        return {"kind": "artifactExport.failed", "task_id": task_id}

    def _persist_context_artifact(
        self,
        wire: Mapping[str, Any],
        *,
        provenance: str,
        deadline_at: str | None = None,
    ) -> str:
        self._assert_deadline_before_side_effect(deadline_at)
        payload = canonical_json_bytes(wire)
        published = self._publish_artifact_batch(
            payloads=(
                (provenance, payload, PRODUCT_EXECUTION_CONTEXT_ROLE, EXECUTION_CONTEXT_SCHEMA_VERSION),
            ),
            references=((str(wire["project_id"]), PROJECT_SPEC_CONTEXT_REFERENCE_ROLE, 0),),
            deadline_at=deadline_at,
        )
        return published[0].descriptor.artifact_id

    def expand_experiment(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        experiment_id: str,
        idempotency_key: str,
    ) -> ExecutionOutcome:
        self.product.require_project_context_ownership(project_id, project_context_revision_id)
        experiment = self.product.require_experiment(experiment_id)
        if str(experiment["project_id"]) != project_id:
            raise NotFoundError(f"experiment does not belong to project: {experiment_id}")
        if str(experiment["state"]) != "DRAFT":
            raise ConflictError("experiment is not in DRAFT state")
        spec = json.loads(str(experiment["experiment_spec_json"]))
        cells = list(spec.get("cells", ()))
        if not cells or len(cells) > MAX_EXPERIMENT_CELLS:
            raise InvalidArgumentError("experiment matrix must have 1..64 cells")
        operation_id = "BacktestService.v1.expandExperiment"
        semantic = {
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "experiment_id": experiment_id,
        }
        scope = DurableIdempotency.scope_key(operation_id, project_id, idempotency_key)
        request_hash = _canonical_request_hash(operation_id, semantic)
        existing = DurableIdempotency().lookup(self.product, scope, request_hash)
        if existing is not None:
            return ExecutionOutcome(str(existing["task_id"]), str(existing["run_id"]), None)
        normalized_input_hash = canonical_sha256({"experiment_id": experiment_id})
        context_artifact_id = self._persist_context_artifact(
            {
                "schema_version": EXECUTION_CONTEXT_SCHEMA_VERSION,
                "context_kind": EXPERIMENT_EXPANSION_CONTEXT_KIND,
                "project_id": project_id,
                "project_context_revision_id": project_context_revision_id,
                "experiment_id": experiment_id,
            },
            provenance="prv_product_experiment_expansion_context",
        )
        task, run, attempt = self._create_task(
            operation_id=operation_id,
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            normalized_input_hash=normalized_input_hash,
            context_artifact_id=context_artifact_id,
            is_batch=True,
            idempotency=(scope, request_hash, _accept_outcome_json),
        )
        self._transition_to_running(task, run, attempt)
        event_cursor = self._latest_sequence(project_id)
        try:
            child_ids: list[str] = []
            child_failed = False
            for cell in cells:
                cell_spec_id = str(cell["run_spec_id"])
                child = self.submit_backtest(
                    project_id=project_id,
                    project_context_revision_id=project_context_revision_id,
                    run_spec_id=cell_spec_id,
                    execution_adapter_version_id=str(cell["execution_adapter_version_id"]),
                    idempotency_key=f"{idempotency_key}:cell:{cell_spec_id}",
                )
                child_ids.append(child.task_id)
                with self.product.task_persistence.begin() as unit:
                    unit.connection.execute(
                        """
                        INSERT INTO task_dependency(task_id, depends_on_task_id, required_terminal_state)
                        VALUES(?,?,?)
                        """,
                        (task.task_id, child.task_id, "SUCCEEDED"),
                    )
                    unit.commit()
                child_state = self.product.task_persistence.read_task(child.task_id).state
                if child_state is not TaskState.SUCCEEDED:
                    child_failed = True
            manifest_wire = {
                "schema_version": "v3.experiment-expansion-manifest/1.0.0",
                "experiment_id": experiment_id,
                "parent_task_id": task.task_id,
                "child_task_ids": child_ids,
            }
            manifest_payload = canonical_json_bytes(manifest_wire)
            outputs = self._publish_artifact_batch(
                payloads=(
                    (
                        "prv_product_experiment_expansion_manifest",
                        manifest_payload,
                        EXPERIMENT_EXPANSION_MANIFEST_ROLE,
                        "v3.experiment-expansion-manifest/1.0.0",
                    ),
                ),
                references=((run.run_id, RUN_EXPORT_MANIFEST_REFERENCE_ROLE, 0),),
            )[0]
            now = wire_time(datetime.now(timezone.utc))
            connection = connect_catalog(self.product.database_path)
            cursor = connection.execute(
                """
                UPDATE experiment SET state='EXPANDED', expansion_manifest_artifact_id=?, updated_at=?
                WHERE experiment_id=? AND state='DRAFT'
                """,
                (outputs.descriptor.artifact_id, now, experiment_id),
            )
            connection.commit()
            connection.close()
            if cursor.rowcount != 1:
                raise ConflictError("experiment matrix was already expanded")
            if child_failed:
                with self.product.task_persistence.begin() as unit:
                    current_task = unit.require_task(task.task_id)
                    current_run = unit.require_run(run.run_id)
                    current_attempt = unit.require_attempt(attempt.attempt_id)
                    current_task.state = transition_task(
                        current_task.state,
                        "CHILDREN_TERMINAL_MIXED",
                        TaskTransitionContext(is_batch=True),
                    )
                    unit.save_task(current_task, expected_version=current_task.state_version)
                    current_attempt.state = transition_attempt(current_attempt.state, "ATTEMPT_SUCCEEDED")
                    unit.save_attempt(current_attempt, expected_version=current_attempt.state_version)
                    current_run.state = transition_run(
                        current_run.state, "TASK_TERMINAL_NO_ACTIVE_ATTEMPT", no_active_attempt=True
                    )
                    unit.save_run(current_run, expected_version=current_run.state_version)
                    unit.append_event(
                        PendingTaskEvent(
                            event_id=mint_v3_id("tev_"),
                            event_version=_TASK_EVENT_VERSION,
                            project_id=project_id,
                            task_id=task.task_id,
                            event_type="TASK_PARTIAL",
                            occurred_at=datetime.now(timezone.utc),
                            payload={"outputs": {"manifest_artifact_id": outputs.descriptor.artifact_id}, "child_task_ids": child_ids},
                            run_id=run.run_id,
                            attempt_id=attempt.attempt_id,
                        )
                    )
                    unit.commit()
            else:
                self._finish_success(
                    task,
                    run,
                    attempt,
                    # Child identity is owned by task_dependency and the
                    # content-addressed expansion manifest. TASK_SUCCEEDED
                    # outputs remain a scalar role-to-value read model.
                    outputs={"manifest_artifact_id": outputs.descriptor.artifact_id},
                )
        except Exception as error:
            self._finish_failure(
                task, run, attempt, error=error, category=classify_execution_error(error)
            )
        return ExecutionOutcome(task.task_id, run.run_id, event_cursor)

    def retry_failed_task(
        self, *, task_id: str, failed_attempt_id: str, expected_state_version: int
    ) -> str:
        """Re-execute a FAILED product Task through its durable execution context.

        Frozen attempt rule: retry always creates a new TaskAttempt on the same
        immutable Run; the Run remains TERMINAL and is not re-transitioned.
        """
        task = self.product.task_persistence.read_task(task_id)
        if task.operation_id == "ProductEntryService.v1.submitResearchBacktest":
            return self.product.backtest.retry_failed_task(
                task_id=task_id,
                failed_attempt_id=failed_attempt_id,
                expected_state_version=expected_state_version,
            )
        if task.state is not TaskState.FAILED and task.state is not TaskState.PARTIAL:
            raise ConflictError("Task is not in a retryable state")
        if task.state_version != expected_state_version:
            raise ConflictError("Task state version is stale")
        latest = self.product.task_persistence.latest_attempt(task_id)
        if latest.attempt_id != failed_attempt_id or latest.state is not AttemptState.FAILED:
            raise InvalidArgumentError("failed_attempt_id is not the latest failed Attempt")
        if latest.terminal_error_category is None:
            raise InvalidArgumentError("failed Attempt carries no error classification")
        persisted_category = latest.terminal_error_category
        category_aliases = {
            "RESOURCE_EXHAUSTED_MEMORY": ErrorCategory.WORKER_OOM,
            "RESOURCE_EXHAUSTED_SCRATCH": ErrorCategory.WORKER_LOST,
        }
        if persisted_category in category_aliases:
            category = category_aliases[persisted_category]
        else:
            try:
                category = ErrorCategory(persisted_category)
            except ValueError as error:
                raise ConflictError(
                    f"retry not admitted: unknown persisted failure category {persisted_category}"
                ) from error
        decision = self.retry_policy.decide(category, prior_attempt_count=latest.ordinal)
        if not decision.allowed:
            raise ConflictError(f"retry not admitted: {decision.reason}")
        run_id = task.active_run_id
        run = self._read_run(run_id)
        context_artifact_id = self._run_context_artifact(run_id)
        context_wire = json.loads(
            self.product.read_verified_bytes(context_artifact_id).decode("utf-8")
        )
        kind = context_wire.get("context_kind")
        prior_receipt = None
        try:
            prior_receipt = self.product.progress_persistence.receipt_for_attempt(
                failed_attempt_id
            )
        except KeyError:
            pass
        if prior_receipt is not None:
            self._assert_deadline_before_side_effect(
                wire_time(prior_receipt.deadline_at)
            )
        with self.product.task_persistence.begin() as unit:
            current_task = unit.require_task(task_id)
            current_task.state = transition_task(
                current_task.state,
                "RETRY_SCHEDULED",
                TaskTransitionContext(retry_epoch=True),
            )
            unit.save_task(current_task, expected_version=current_task.state_version)
            attempt = TaskAttempt(
                attempt_id=mint_v3_id("att_"),
                task_id=task_id,
                run_id=run_id,
                ordinal=latest.ordinal + 1,
                state=AttemptState.QUEUED,
                state_version=0,
                lease_id=mint_v3_id("lea_"),
                resume_checkpoint_artifact_id=None,
                terminal_error_category=None,
            )
            unit.add_attempt(attempt)
            lineage = unit.connection.execute(
                """
                UPDATE task_attempt
                SET retry_of_attempt_id=?
                WHERE attempt_id=? AND retry_of_attempt_id IS NULL
                """,
                (failed_attempt_id, attempt.attempt_id),
            )
            if lineage.rowcount != 1:
                raise ConflictError("retry Attempt lineage could not be persisted")
            if self.product.runtime_generation_id is not None:
                generation_cursor = unit.connection.execute(
                    """
                    UPDATE task_attempt
                    SET runtime_generation_id=?
                    WHERE attempt_id=? AND runtime_generation_id IS NULL
                    """,
                    (self.product.runtime_generation_id, attempt.attempt_id),
                )
                if generation_cursor.rowcount != 1:
                    raise ConflictError("retry Attempt runtime generation could not be persisted")
            if prior_receipt is not None:
                self.product.progress_persistence.create_receipt_in_transaction(
                    unit.connection,
                    operation_receipt_id=mint_v3_id("opr_"),
                    correlation_id=f"retry:{attempt.attempt_id}",
                    operation_id=prior_receipt.operation_id,
                    project_id=current_task.project_id,
                    deadline_at=prior_receipt.deadline_at,
                    runtime_generation_id=self.product.runtime_generation_id,
                    task_id=task_id,
                    run_id=run_id,
                    attempt_id=attempt.attempt_id,
                )
            now = wire_time(datetime.now(timezone.utc))
            worker_id = mint_v3_id("wrk_")
            unit.connection.execute(
                """
                INSERT INTO worker(worker_id, worker_kind, process_id, environment_profile_id,
                                   state, started_at)
                VALUES(?,?,?,?,?,?)
                """,
                (worker_id, INLINE_WORKER_KIND, os.getpid(), INLINE_ENVIRONMENT_PROFILE_ID, "BUSY", now),
            )
            unit.connection.execute(
                """
                INSERT INTO worker_lease(lease_id, attempt_id, worker_id, cpu_slots,
                                         memory_limit_bytes, scratch_limit_bytes, state,
                                         granted_at, expires_at)
                VALUES(?,?,?,1,1073741824,1073741824,'GRANTED',?,?)
                """,
                (
                    attempt.lease_id,
                    attempt.attempt_id,
                    worker_id,
                    now,
                    wire_time(datetime.now(timezone.utc) + timedelta(hours=1)),
                ),
            )
            unit.append_event(
                PendingTaskEvent(
                    event_id=mint_v3_id("tev_"),
                    event_version=_TASK_EVENT_VERSION,
                    project_id=current_task.project_id,
                    task_id=task_id,
                    event_type="TASK_QUEUED",
                    occurred_at=datetime.now(timezone.utc),
                    payload={"operation_id": current_task.operation_id, "retry_of_attempt": failed_attempt_id},
                    run_id=run_id,
                    attempt_id=attempt.attempt_id,
                )
            )
            unit.commit()
        self._transition_to_running(task, run, attempt, run_transition=False)
        if kind == RESEARCH_RUN_CONTEXT_KIND:
            spec, _ = self.product.spec_codec.reconstruct(
                project_id=context_wire["project_id"], run_spec_id=context_wire["run_spec_id"]
            )
            try:
                result = self.engine.run(spec)
                outputs = self._publish_backtest_outputs(
                    project_id=context_wire["project_id"], run_id=run_id, result=result
                )
                self._finish_success(task, run, attempt, outputs=outputs, run_transition=False)
            except Exception as error:
                self._finish_failure(
                    task, run, attempt, error=error, category=classify_execution_error(error),
                    run_transition=False,
                )
        elif kind == EXPORT_CONTEXT_KIND:
            # A retry creates a fresh Attempt but cannot replay OS destination
            # authority. It waits for a new Electron native completion/failure
            # receipt and never recreates a success manifest by itself.
            return task_id
        else:
            self._finish_failure(
                task, run, attempt,
                error=InvalidArgumentError(f"unsupported execution context kind: {kind}"),
                category=ErrorCategory.INVALID_ARGUMENT,
                run_transition=False,
            )
        return task_id

    def _read_run(self, run_id: str) -> Run:
        with self.product.task_persistence.begin() as unit:
            run = unit.require_run(run_id)
            unit.commit()
            return run

    def _run_context_artifact(self, run_id: str) -> str:
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            row = catalog_row(
                connection,
                """
                SELECT artifact_id FROM artifact_reference
                WHERE owner_id=? AND role=? AND state='ACTIVE' LIMIT 1
                """,
                (run_id, RUN_CONTEXT_REFERENCE_ROLE),
            )
        finally:
            connection.close()
        if row is None:
            raise NotFoundError(f"Run has no durable execution context: {run_id}")
        return str(row["artifact_id"])


class _NoopPublishCallbacks:
    """PUBLISH UoW callbacks when the batch has no staged bytes to publish."""

    def verify_staged(self) -> None:
        return None

    def publish_staged(self) -> None:
        return None

    def compensate_unreferenced_staging(self) -> None:
        return None

    def notify_committed(self) -> None:
        return None


class ProductRuntime:
    """Durable product composition root behind the ASL facades."""

    def __init__(
        self,
        storage_root: str | Path,
        *,
        research_provider_factory=None,
        research_worker_config: ProductResearchWorkerConfig | None = None,
        reconcile_on_start: bool = True,
    ) -> None:
        self._initialize_storage_paths(storage_root)
        upgrade_catalog(
            self.database_path,
            application_version=MIGRATION_APPLICATION_VERSION,
            backup_dir=self.storage_root / "backups",
        )
        self._initialize_services(
            research_provider_factory,
            research_worker_config,
            reconcile_on_start,
        )

    @classmethod
    def for_worker(
        cls,
        storage_root: str | Path,
        *,
        research_provider_factory=None,
        execution_deadline_at: str | None = None,
        correlation_id: str | None = None,
    ) -> "ProductRuntime":
        """Open the parent's live Catalog without acquiring upgrade ownership."""

        product = cls.__new__(cls)
        product._initialize_storage_paths(storage_root)
        require_current_catalog(product.database_path)
        product._initialize_services(research_provider_factory, None, False)
        product._active_control_deadline_at = execution_deadline_at
        product._active_control_correlation_id = correlation_id
        return product

    def _initialize_storage_paths(self, storage_root: str | Path) -> None:
        self.storage_root = Path(storage_root).resolve()
        self.database_path = self.storage_root / CATALOG_FILENAME
        self.artifact_root = self.storage_root / ARTIFACT_DIRNAME
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _initialize_services(
        self,
        research_provider_factory,
        research_worker_config: ProductResearchWorkerConfig | None,
        reconcile_on_start: bool,
    ) -> None:
        self.artifact_store = FileSystemArtifactStore(
            self.artifact_root, policy=product_artifact_policy()
        )
        self.artifact_publication = ArtifactPublicationCoordinator(
            self.database_path, self.artifact_store
        )
        self.task_persistence = SQLiteTaskPersistence(self.database_path)
        self.progress_persistence = ProgressPersistence(
            self.database_path,
            identity_new=mint_v3_id,
        )
        self.event_replay = ProductEventReplay(self.database_path)
        self.spec_codec = ResearchRunSpecCodec(self)
        self.idempotency = DurableIdempotency()
        self._shutdown_prepared = False
        self._shutdown_committed = False
        self._cancellation_lock = RLock()
        self._active_control_deadline_at: str | None = None
        self._active_control_correlation_id: str | None = None
        self.runtime_generation_id: str | None = None
        if reconcile_on_start:
            self.runtime_generation_id = mint_v3_id("rgen_")
            self.progress_persistence.create_generation(
                self.runtime_generation_id,
                process_identity_hash=hashlib.sha256(
                    f"pid:{os.getpid()}:generation:{self.runtime_generation_id}".encode("utf-8")
                ).hexdigest(),
            )
        self.execution = ProductExecution(self)
        self._initialize_worker_manager(research_worker_config)
        self._initialize_domain_services(research_provider_factory)
        if reconcile_on_start:
            self._reconcile_startup_state()
        else:
            self._record_unreconciled_startup()

    def _initialize_worker_manager(
        self,
        research_worker_config: ProductResearchWorkerConfig | None,
    ) -> None:
        if research_worker_config is not None:
            from .product_workers import ProductResearchWorkerManager

            self.product_workers = ProductResearchWorkerManager(
                self,
                research_worker_config,
            )
        else:
            self.product_workers = None
        # Compatibility alias for the already accepted 1.0 research path.  The
        # manager is now shared by additive Product Entry work kinds rather than
        # creating a second Task/Worker state machine.
        self.research_workers = self.product_workers

    def _initialize_domain_services(self, research_provider_factory) -> None:
        from .product_research import ProductResearchService
        from .product_data import ProductDataService
        from .product_factor import ProductFactorStudyService
        from .product_strategy import ProductStrategyService
        from .product_backtest import ProductResearchBacktestService
        from .product_results import ProductResultService
        from .local_data_transfer import ProductLocalDataTransferService

        self.research = ProductResearchService(
            self,
            provider_factory=research_provider_factory,
        )
        self.data = ProductDataService(self)
        self.factor = ProductFactorStudyService(self)
        self.strategy = ProductStrategyService(self)
        self.backtest = ProductResearchBacktestService(self)
        self.results = ProductResultService(self)
        self.local_data_transfers = ProductLocalDataTransferService(self)

    def _reconcile_startup_state(self) -> None:
        gc_summary = self.artifact_publication.reconcile_gc()
        # GC restore has a durable RESTORED intent while its final bytes may
        # already exist under a still-QUARANTINED Catalog row.  Resolve that
        # boundary before the generic orphan scan can classify the final as
        # unadmitted bytes.
        artifact_summary = self.artifact_publication.reconcile()
        # Publication recovery owns a cataloged Result before generic
        # worker-loss reconciliation is allowed to fail its Task.
        from .product_publication import ProductBacktestPublication

        publication_summary = ProductBacktestPublication(self).recover_pending()
        worker_summary = self._reconcile_execution_state()
        self.reconciliation_summary = {
            **artifact_summary,
            **gc_summary,
            **worker_summary,
            **publication_summary,
        }

    def _record_unreconciled_startup(self) -> None:
        self.reconciliation_summary = {
            "active_leases_revoked": 0,
            "expired_leases_reconciled": 0,
            "attempts_lost": 0,
            "attempts_cancelled_after_restart": 0,
            "tasks_failed": 0,
            "tasks_cancelled_after_restart": 0,
            "receipts_completed_after_restart": 0,
            "workers_stopped": 0,
            "publication_intents_seen": 0,
            "publication_finalized": 0,
            "publication_failed": 0,
            "promotion_intents_seen": 0,
            "promotion_finalized": 0,
            "promotion_failed": 0,
            "promotion_bytes_unavailable": 0,
            "promotion_next_cursor": None,
            "published_artifacts_seen": 0,
            "published_artifacts_repaired": 0,
            "published_artifacts_unavailable": 0,
            "published_artifact_next_cursor": None,
            "published_artifact_scan_blocked": False,
            "orphan_stages_seen": 0,
            "orphan_stages_quarantined": 0,
            "orphan_stages_failed": 0,
            "orphan_stage_next_cursor": None,
            "orphan_stage_scan_blocked": False,
            "orphan_promoting_bytes_seen": 0,
            "orphan_promoting_bytes_isolated": 0,
            "orphan_promoting_bytes_failed": 0,
            "orphan_promoting_next_cursor": None,
            "orphan_promoting_scan_blocked": False,
            "orphan_final_bytes_seen": 0,
            "orphan_final_bytes_isolated": 0,
            "orphan_final_bytes_failed": 0,
            "orphan_final_next_cursor": None,
            "orphan_final_scan_blocked": False,
            "gc_batches_seen": 0,
            "gc_batches_completed": 0,
            "gc_batches_failed": 0,
            "gc_restores_seen": 0,
            "gc_restores_completed": 0,
            "gc_restores_failed": 0,
        }

    # -- catalog access ------------------------------------------------------

    def _connection(self, *, read_only: bool = False) -> sqlite3.Connection:
        return connect_catalog(self.database_path, read_only=read_only)

    def require_project(self, project_id: str) -> dict[str, Any]:
        connection = self._connection(read_only=True)
        try:
            row = catalog_row(connection, "SELECT * FROM project WHERE project_id=?", (project_id,))
        finally:
            connection.close()
        if row is None:
            raise NotFoundError(f"unknown project: {project_id}")
        if str(row["state"]) != "ACTIVE":
            raise ConflictError(f"project is not ACTIVE: {project_id}")
        return row

    def require_context_revision(self, project_context_revision_id: str) -> dict[str, Any]:
        connection = self._connection(read_only=True)
        try:
            row = catalog_row(
                connection,
                "SELECT * FROM project_context_revision WHERE project_context_revision_id=?",
                (project_context_revision_id,),
            )
        finally:
            connection.close()
        if row is None:
            raise NotFoundError(f"unknown project context revision: {project_context_revision_id}")
        return row

    def require_project_context_ownership(self, project_id: str, project_context_revision_id: str) -> dict[str, Any]:
        """Fail closed when the context revision is missing or belongs elsewhere."""
        self.require_project(project_id)
        revision = self.require_context_revision(project_context_revision_id)
        if str(revision["project_id"]) != project_id:
            raise TruthPreconditionFailedError(
                "project context revision does not belong to the request project"
            )
        return revision

    def current_revision(self, project_id: str) -> dict[str, Any]:
        connection = self._connection(read_only=True)
        try:
            row = catalog_row(
                connection,
                """
                SELECT * FROM project_context_revision
                WHERE project_id=? ORDER BY revision_no DESC LIMIT 1
                """,
                (project_id,),
            )
        finally:
            connection.close()
        if row is None:
            raise NotFoundError(f"project has no context revision: {project_id}")
        return row

    def _require_current_project_context(
        self, project_id: str, project_context_revision_id: str
    ) -> dict[str, Any]:
        context = self.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        current = self.current_revision(project_id)
        if str(current["project_context_revision_id"]) != project_context_revision_id:
            raise ConflictError(
                "TaskControl requires the current project context revision"
            )
        return context

    def _read_task_bundle(self, task_id: str) -> tuple[Task, Run, TaskAttempt]:
        try:
            with self.task_persistence.begin() as unit:
                task = unit.require_task(task_id)
                run = unit.require_run(task.active_run_id)
                attempt_row = unit.connection.execute(
                    """
                    SELECT attempt_id
                    FROM task_attempt
                    WHERE run_id=?
                    ORDER BY attempt_no DESC
                    LIMIT 1
                    """,
                    (run.run_id,),
                ).fetchone()
                if attempt_row is None:
                    raise KeyError(f"no Attempt for Task: {task_id}")
                attempt = unit.require_attempt(str(attempt_row[0]))
                unit.commit()
                return task, run, attempt
        except KeyError as error:
            raise NotFoundError(f"unknown Task: {task_id}") from error

    @staticmethod
    def _runtime_context_corrupt(message: str) -> TruthPreconditionFailedError:
        return TruthPreconditionFailedError(
            message,
            details={"reason_code": "RUN_CONTEXT_CORRUPT"},
        )

    def _validate_queued_execution_context(
        self,
        *,
        task: Task,
        run: Run,
        attempt: TaskAttempt,
        context: Mapping[str, object],
    ) -> tuple[dict[str, Any], str | None]:
        """Validate the immutable Run input before any start-side mutation."""

        expected = {
            "task_id": task.task_id,
            "run_id": run.run_id,
            "attempt_id": attempt.attempt_id,
            "operation_id": task.operation_id,
            "input_hash": run.identity.normalized_input_hash,
            "code_version": run.identity.code_version,
            "environment_profile": run.identity.environment_profile,
        }
        if any(context.get(name) != value for name, value in expected.items()):
            raise self._runtime_context_corrupt(
                "immutable Task/Run/Attempt execution context drifted"
            )
        canonical_input = context.get("canonical_input")
        if not isinstance(canonical_input, dict):
            raise self._runtime_context_corrupt(
                "durable Run canonical input is not an object"
            )
        semantic = canonical_input.get("semantic_request")
        request_hash = canonical_input.get("request_hash")
        scope = canonical_input.get("scope")
        if not isinstance(semantic, dict):
            raise self._runtime_context_corrupt(
                "durable Run semantic request is absent"
            )
        if (
            semantic.get("project_id") != task.project_id
            or semantic.get("project_context_revision_id")
            != run.identity.project_context_revision_id
        ):
            raise self._runtime_context_corrupt(
                "durable Run semantic request is not bound to its Task project"
            )
        if (
            not isinstance(request_hash, str)
            or len(request_hash) != 64
            or request_hash != request_hash.lower()
            or any(char not in "0123456789abcdef" for char in request_hash)
        ):
            raise self._runtime_context_corrupt(
                "durable Run request hash is invalid"
            )
        if not isinstance(scope, str) or not scope or len(scope) > 512:
            raise self._runtime_context_corrupt(
                "durable Run request scope is invalid"
            )
        try:
            semantic_hash = canonical_sha256(semantic)
            expected_request_hash = _canonical_request_hash(
                task.operation_id, semantic
            )
        except (TypeError, ValueError) as error:
            raise self._runtime_context_corrupt(
                "durable Run semantic request is not canonical JSON"
            ) from error
        if semantic_hash != run.identity.normalized_input_hash:
            raise self._runtime_context_corrupt(
                "durable Run semantic input hash does not match Run identity"
            )
        if request_hash != expected_request_hash:
            raise self._runtime_context_corrupt(
                "durable Run request hash does not match its operation and input"
            )
        if canonical_input.get("normalized_input_hash") != run.identity.normalized_input_hash:
            raise self._runtime_context_corrupt(
                "durable canonical input normalized hash drifted"
            )
        if canonical_input.get("service_contract_version") != run.identity.service_contract_version:
            raise self._runtime_context_corrupt(
                "durable canonical input contract version drifted"
            )
        task_deadline = context.get("task_deadline_at")
        attempt_deadline = context.get("attempt_deadline_at")
        if task_deadline is not None and not isinstance(task_deadline, str):
            raise self._runtime_context_corrupt("Task deadline is not text")
        if attempt_deadline is not None and not isinstance(attempt_deadline, str):
            raise self._runtime_context_corrupt("Attempt deadline is not text")
        if task_deadline is not None and attempt_deadline is not None and task_deadline != attempt_deadline:
            raise self._runtime_context_corrupt(
                "Task and Attempt deadlines differ"
            )
        deadline = attempt_deadline or task_deadline
        if deadline is not None:
            try:
                self.execution._parse_execution_deadline(deadline)
            except (TypeError, ValueError, InvalidArgumentError) as error:
                raise self._runtime_context_corrupt(
                    "durable execution deadline is not canonical"
                ) from error
        generation = context.get("runtime_generation_id")
        if generation is not None and not isinstance(generation, str):
            raise self._runtime_context_corrupt(
                "Attempt runtime generation identity is invalid"
            )
        return dict(semantic), deadline

    @staticmethod
    def _bind_rebuilt_request(
        prepared: Any,
        *,
        semantic: Mapping[str, Any],
        request_hash: str,
        scope: str,
        execution_deadline_at: str | None,
    ) -> Any:
        if (
            getattr(prepared, "semantic", None) != dict(semantic)
            or getattr(prepared, "request_hash", None) != request_hash
        ):
            raise TruthPreconditionFailedError(
                "rebuilt Product request does not match immutable Run input",
                details={"reason_code": "RUN_CONTEXT_CORRUPT"},
            )
        return replace(
            prepared,
            scope=scope,
            execution_deadline_at=execution_deadline_at,
        )

    def _rebuild_queued_worker_launch(
        self,
        *,
        operation_id: str,
        semantic: dict[str, Any],
        request_hash: str,
        scope: str,
        execution_deadline_at: str | None,
    ) -> _QueuedWorkerLaunch:
        """Rebuild a typed worker request from the immutable Run semantic input."""

        workers = self.product_workers
        profile_for_operation = getattr(workers, "profile_for_operation", None)
        if not callable(profile_for_operation):
            raise CapabilityUnavailableError(
                "Product worker profile resolver is unavailable",
                details={"reason_code": "PRODUCT_WORKER_PROFILE_NOT_AVAILABLE"},
            )
        try:
            work_kind, resource_class = profile_for_operation(operation_id)
        except KeyError as error:
            raise CapabilityUnavailableError(
                "Task operation has no admitted Product worker profile",
                details={
                    "reason_code": "PRODUCT_OPERATION_NOT_DISPATCHABLE",
                    "operation_id": operation_id,
                },
            ) from error
        synthetic_key = "__task_control_rebuild_" + request_hash
        try:
            if operation_id == "ProductEntryService.v1.submitResearch":
                from .product_research import ProductResearchSubmission

                source = semantic["source"]
                prepared = self.research._prepare_request(
                    ProductResearchSubmission(
                        project_id=semantic["project_id"],
                        project_context_revision_id=semantic[
                            "project_context_revision_id"
                        ],
                        research_profile_id=semantic["research_profile_id"],
                        strategy_profile_id=semantic["strategy_profile_id"],
                        source=source,
                        idempotency_key=synthetic_key,
                        execution_deadline_at=execution_deadline_at,
                    )
                )
            elif operation_id == "ProductEntryService.v1.importLocalDataset":
                from .product_data import ProductLocalDataSubmission

                prepared = self.data._prepare_submission(
                    ProductLocalDataSubmission(
                        project_id=semantic["project_id"],
                        project_context_revision_id=semantic[
                            "project_context_revision_id"
                        ],
                        source=semantic["source"],
                        idempotency_key=synthetic_key,
                        execution_deadline_at=execution_deadline_at,
                    )
                )
            elif operation_id == "ProductEntryService.v1.submitFactorStudy":
                from .product_factor import ProductFactorStudySubmission

                prepared = self.factor._prepare_submission(
                    ProductFactorStudySubmission(
                        project_id=semantic["project_id"],
                        project_context_revision_id=semantic[
                            "project_context_revision_id"
                        ],
                        formula_source=semantic["formula_source"],
                        analysis_output_name=semantic["analysis_output_name"],
                        idempotency_key=synthetic_key,
                        execution_deadline_at=execution_deadline_at,
                    )
                )
            elif operation_id == "ProductEntryService.v1.publishResearchStrategy":
                from .product_strategy import ProductStrategySubmission

                spec = semantic["spec"]
                prepared = self.strategy._prepare_submission(
                    ProductStrategySubmission(
                        project_id=semantic["project_id"],
                        project_context_revision_id=semantic[
                            "project_context_revision_id"
                        ],
                        universe_version_id=spec["universe_version_id"],
                        entry_signal_factor_version_id=spec[
                            "entry_signal_factor_version_id"
                        ],
                        exit_signal_factor_version_id=spec[
                            "exit_signal_factor_version_id"
                        ],
                        position_sizing=spec["position_sizing"],
                        max_positions=spec["max_positions"],
                        gross_exposure=spec["gross_exposure"],
                        rebalance=spec["rebalance"],
                        cost_policy_version_id=spec["cost_policy_version_id"],
                        execution_policy_version_id=spec[
                            "execution_policy_version_id"
                        ],
                        risk_policy_set_version_id=spec[
                            "risk_policy_set_version_id"
                        ],
                        initial_cash=spec["initial_cash"],
                        assumption_profile_id=spec["assumption_profile_id"],
                        idempotency_key=synthetic_key,
                        execution_deadline_at=execution_deadline_at,
                    )
                )
            elif operation_id == "ProductEntryService.v1.submitResearchBacktest":
                from .product_backtest import ProductResearchBacktestSubmission

                prepared = self.backtest._prepare_submission(
                    ProductResearchBacktestSubmission(
                        project_id=semantic["project_id"],
                        project_context_revision_id=semantic[
                            "project_context_revision_id"
                        ],
                        research_strategy_spec_id=semantic[
                            "research_strategy_spec_id"
                        ],
                        session_start=date.fromisoformat(semantic["session_start"]),
                        session_end=date.fromisoformat(semantic["session_end"]),
                        slippage_bps=semantic["slippage_bps"],
                        daily_volume_participation_rate=semantic[
                            "daily_volume_participation_rate"
                        ],
                        idempotency_key=synthetic_key,
                        execution_deadline_at=execution_deadline_at,
                    )
                )
            elif operation_id == "ResultService.v1.reconcileLedger":
                from .product_results import ResultReconcileSubmission

                prepared = self.results._prepare(
                    operation_id=operation_id,
                    work_kind=work_kind,
                    resource_class=resource_class,
                    project_id=semantic["project_id"],
                    project_context_revision_id=semantic[
                        "project_context_revision_id"
                    ],
                    backtest_run_id=semantic["backtest_run_id"],
                    idempotency_key=synthetic_key,
                    semantic_tail={
                        "ledger_manifest_artifact_id": semantic[
                            "ledger_manifest_artifact_id"
                        ],
                        "reconciliation_profile_id": semantic[
                            "reconciliation_profile_id"
                        ],
                    },
                    execution_deadline_at=execution_deadline_at,
                )
            elif operation_id == "ResultService.v1.finalizeResult":
                from .product_results import ResultFinalizeSubmission

                prepared = self.results._prepare(
                    operation_id=operation_id,
                    work_kind=work_kind,
                    resource_class=resource_class,
                    project_id=semantic["project_id"],
                    project_context_revision_id=semantic[
                        "project_context_revision_id"
                    ],
                    backtest_run_id=semantic["backtest_run_id"],
                    idempotency_key=synthetic_key,
                    semantic_tail={
                        "reconciliation_artifact_id": semantic[
                            "reconciliation_artifact_id"
                        ],
                        "analytics_spec": semantic["analytics_spec"],
                    },
                    execution_deadline_at=execution_deadline_at,
                )
            else:
                raise CapabilityUnavailableError(
                    "Task operation has no typed Product rebuild path",
                    details={
                        "reason_code": "PRODUCT_OPERATION_NOT_DISPATCHABLE",
                        "operation_id": operation_id,
                    },
                )
        except (KeyError, TypeError, ValueError, V3ContractError) as error:
            raise self._runtime_context_corrupt(
                "durable Product semantic request cannot be rebuilt"
            ) from error
        prepared = self._bind_rebuilt_request(
            prepared,
            semantic=semantic,
            request_hash=request_hash,
            scope=scope,
            execution_deadline_at=execution_deadline_at,
        )
        return _QueuedWorkerLaunch(
            prepared_request=prepared,
            operation_id=operation_id,
            work_kind=work_kind,
            resource_class=resource_class,
        )

    def read_operation_receipt(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        operation_receipt_id: str,
    ) -> dict[str, Any]:
        """Return a bounded read model from the durable receipt owner."""

        self.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        try:
            receipt = self.progress_persistence.receipt(operation_receipt_id)
        except KeyError as error:
            raise NotFoundError(
                f"unknown operation receipt: {operation_receipt_id}"
            ) from error
        if receipt.project_id != project_id:
            raise NotFoundError("operation receipt is not owned by the request project")
        if receipt.task_id is not None and receipt.run_id is None:
            raise self._runtime_context_corrupt(
                "operation receipt has a Task without a Run"
            )
        if receipt.attempt_id is not None and receipt.run_id is None:
            raise self._runtime_context_corrupt(
                "operation receipt has an Attempt without a Run"
            )
        if receipt.run_id is not None or receipt.attempt_id is not None:
            connection = self._connection(read_only=True)
            try:
                binding = None
                if receipt.run_id is not None:
                    binding = connection.execute(
                        """
                        SELECT t.project_id,t.operation_id,r.task_id,
                               r.project_context_revision_id
                        FROM run AS r
                        JOIN task AS t ON t.task_id=r.task_id
                        WHERE r.run_id=?
                        """,
                        (receipt.run_id,),
                    ).fetchone()
                attempt_binding = None
                if receipt.attempt_id is not None:
                    attempt_binding = connection.execute(
                        """
                        SELECT a.run_id,r.task_id,a.runtime_generation_id
                        FROM task_attempt AS a
                        JOIN run AS r ON r.run_id=a.run_id
                        WHERE a.attempt_id=?
                        """,
                        (receipt.attempt_id,),
                    ).fetchone()
            finally:
                connection.close()
            if (
                binding is None
                or str(binding[0]) != project_id
                or str(binding[1]) != receipt.operation_id
                or str(binding[3]) != project_context_revision_id
                or (
                    receipt.task_id is not None
                    and str(binding[2]) != receipt.task_id
                )
                or (
                    receipt.attempt_id is not None
                    and (
                        attempt_binding is None
                        or str(attempt_binding[0]) != receipt.run_id
                        or (
                            receipt.task_id is not None
                            and str(attempt_binding[1]) != receipt.task_id
                        )
                        or (
                            None
                            if attempt_binding[2] is None
                            else str(attempt_binding[2])
                        )
                        != receipt.runtime_generation_id
                    )
                )
            ):
                raise self._runtime_context_corrupt(
                    "operation receipt binding does not match its Task/Run/Attempt"
                )
        outcome: dict[str, Any] | None = None
        if receipt.outcome_json is not None:
            if len(receipt.outcome_json.encode("utf-8")) > 65_536:
                raise self._runtime_context_corrupt(
                    "operation receipt outcome exceeds the read-model bound"
                )
            try:
                decoded = json.loads(receipt.outcome_json)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise self._runtime_context_corrupt(
                    "operation receipt outcome is not valid JSON"
                ) from error
            if not isinstance(decoded, dict):
                raise self._runtime_context_corrupt(
                    "operation receipt outcome must be an object"
                )
            outcome = decoded
        if receipt.outcome_artifact_id is not None:
            self.require_project_reachable_artifact(
                project_id, receipt.outcome_artifact_id
            )
        return {
            "read_model_version": "v3.operation-receipt/1.0",
            "operation_receipt_id": receipt.operation_receipt_id,
            "correlation_id": receipt.correlation_id,
            "operation_id": receipt.operation_id,
            "project_id": receipt.project_id,
            "task_id": receipt.task_id,
            "run_id": receipt.run_id,
            "attempt_id": receipt.attempt_id,
            "deadline_at": wire_time(receipt.deadline_at),
            "runtime_generation_id": receipt.runtime_generation_id,
            "state": receipt.state,
            "commit_boundary_at": (
                None
                if receipt.commit_boundary_at is None
                else wire_time(receipt.commit_boundary_at)
            ),
            "outcome": outcome,
            "outcome_artifact_id": receipt.outcome_artifact_id,
            "error_code": receipt.error_code,
            "created_at": wire_time(receipt.created_at),
            "updated_at": wire_time(receipt.updated_at),
            "terminal_at": (
                None if receipt.terminal_at is None else wire_time(receipt.terminal_at)
            ),
            "state_version": receipt.state_version,
        }

    @staticmethod
    def _decode_queue_cursor(
        cursor: str | None,
        *,
        project_id: str,
        states: tuple[str, ...],
    ) -> tuple[str, str] | None:
        if cursor is None:
            return None
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
            raise InvalidArgumentError("queue cursor must be a bounded opaque string")
        try:
            padding = "=" * (-len(cursor) % 4)
            decoded = json.loads(
                base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
            )
        except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidArgumentError("queue cursor is malformed") from error
        expected_keys = {
            "v",
            "project_id",
            "states",
            "updated_at",
            "task_id",
            "sort",
        }
        if not isinstance(decoded, dict) or set(decoded) != expected_keys:
            raise InvalidArgumentError("queue cursor shape is invalid")
        if (
            decoded["v"] != 1
            or decoded["project_id"] != project_id
            or decoded["states"] != list(states)
            or decoded["sort"] != "updated_at_asc_task_id_asc"
            or not isinstance(decoded["updated_at"], str)
            or not isinstance(decoded["task_id"], str)
            or not decoded["task_id"]
        ):
            raise InvalidArgumentError(
                "queue cursor does not match the current project/filter/sort scope"
            )
        try:
            parsed = datetime.fromisoformat(
                decoded["updated_at"].replace("Z", "+00:00")
            )
        except ValueError as error:
            raise InvalidArgumentError("queue cursor timestamp is invalid") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise InvalidArgumentError("queue cursor timestamp must include UTC")
        if len(decoded["task_id"]) > 128:
            raise InvalidArgumentError("queue cursor task identity is too long")
        return decoded["updated_at"], decoded["task_id"]

    @staticmethod
    def _encode_queue_cursor(
        *,
        project_id: str,
        states: tuple[str, ...],
        updated_at: str,
        task_id: str,
    ) -> str:
        cursor_wire = {
            "v": 1,
            "project_id": project_id,
            "states": list(states),
            "updated_at": updated_at,
            "task_id": task_id,
            "sort": "updated_at_asc_task_id_asc",
        }
        return base64.urlsafe_b64encode(
            json.dumps(
                cursor_wire,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).decode("ascii").rstrip("=")

    def list_queue(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        states: tuple[str, ...],
        page_size: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        """Read a bounded queue page without loading Task payloads or history."""

        self._require_current_project_context(
            project_id, project_context_revision_id
        )
        if (
            not states
            or len(set(states)) != len(states)
            or any(state not in {"HOLD", "READY", "DISPATCHED", "TERMINAL"} for state in states)
        ):
            raise InvalidArgumentError("queue state filter is invalid")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 200
        ):
            raise InvalidArgumentError("queue page_size must be between 1 and 200")
        normalized_states = tuple(sorted(states))
        after = self._decode_queue_cursor(
            cursor, project_id=project_id, states=normalized_states
        )
        rows = self.progress_persistence.list_dispatch_controls_page(
            project_id,
            states=normalized_states,
            page_size=page_size,
            after=after,
        )
        truncated = len(rows) > page_size
        page_rows = rows[:page_size]
        items: list[dict[str, Any]] = []
        for row in page_rows:
            progress = None
            if row["progress_sequence"] is not None:
                progress = {
                    "sequence": int(row["progress_sequence"]),
                    "phase": str(row["progress_phase"]),
                    "completed_units": int(row["progress_completed_units"]),
                    "total_units": int(row["progress_total_units"]),
                    "work_unit": str(row["progress_work_unit"]),
                    "occurred_at": str(row["progress_occurred_at"]),
                }
            items.append(
                {
                    "task_id": str(row["task_id"]),
                    "operation_id": str(row["operation_id"]),
                    "task_state": str(row["task_state"]),
                    "task_state_version": int(row["task_state_version"]),
                    "dispatch_state": str(row["dispatch_state"]),
                    "dispatch_state_version": int(row["dispatch_state_version"]),
                    "hold_reason": (
                        None
                        if row["hold_reason"] is None
                        else str(row["hold_reason"])
                    ),
                    "user_confirmed_at": (
                        None
                        if row["user_confirmed_at"] is None
                        else str(row["user_confirmed_at"])
                    ),
                    "run_id": None if row["run_id"] is None else str(row["run_id"]),
                    "attempt_id": (
                        None
                        if row["attempt_id"] is None
                        else str(row["attempt_id"])
                    ),
                    "attempt_state": (
                        None
                        if row["attempt_state"] is None
                        else str(row["attempt_state"])
                    ),
                    "execution_deadline_at": (
                        None
                        if row["execution_deadline_at"] is None
                        else str(row["execution_deadline_at"])
                    ),
                    "progress": progress,
                    "updated_at": str(row["dispatch_updated_at"]),
                }
            )
        next_cursor = None
        if truncated and page_rows:
            last = page_rows[-1]
            next_cursor = self._encode_queue_cursor(
                project_id=project_id,
                states=normalized_states,
                updated_at=str(last["dispatch_updated_at"]),
                task_id=str(last["task_id"]),
            )
        return {
            "read_model_version": "v3.task-queue-page/1.0",
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "states": list(normalized_states),
            "items": items,
            "page_size": page_size,
            "truncated": truncated,
            "has_more": truncated,
            "next_cursor": next_cursor,
        }

    def start_queued_task(
        self,
        *,
        task_id: str,
        project_id: str,
        project_context_revision_id: str,
        expected_state_version: int,
        expected_dispatch_state_version: int,
    ) -> Task:
        """Explicitly admit one restart-safe queued Task to its worker owner."""

        self._require_current_project_context(
            project_id, project_context_revision_id
        )
        if (
            isinstance(expected_state_version, bool)
            or not isinstance(expected_state_version, int)
            or expected_state_version < 0
            or isinstance(expected_dispatch_state_version, bool)
            or not isinstance(expected_dispatch_state_version, int)
            or expected_dispatch_state_version < 0
        ):
            raise InvalidArgumentError("TaskControl state versions are invalid")
        workers = self.product_workers
        if workers is None:
            raise CapabilityUnavailableError(
                "isolated Product worker is unavailable",
                details={"reason_code": "PRODUCT_WORKER_NOT_AVAILABLE"},
            )
        task, run, attempt = self._read_task_bundle(task_id)
        if task.project_id != project_id:
            raise TruthPreconditionFailedError(
                "task belongs to a different project"
            )
        if task.state is not TaskState.QUEUED:
            raise ConflictError("only a QUEUED Task may be explicitly started")
        if task.state_version != expected_state_version:
            raise ConflictError("Task state version is stale")
        try:
            dispatch = self.progress_persistence.dispatch_control(task_id)
        except KeyError as error:
            raise TruthPreconditionFailedError(
                "Task has no durable dispatch control row"
            ) from error
        if dispatch.state != "HOLD":
            raise ConflictError(
                f"Task dispatch control is not HOLD: {dispatch.state}"
            )
        if dispatch.state_version != expected_dispatch_state_version:
            raise ConflictError("dispatch state version is stale")
        try:
            context = self.progress_persistence.execution_context_for_attempt(
                attempt.attempt_id
            )
        except RuntimeResolutionConflict as error:
            raise self._runtime_context_corrupt(
                "durable Task execution context cannot be read"
            ) from error
        semantic, deadline = self._validate_queued_execution_context(
            task=task,
            run=run,
            attempt=attempt,
            context=context,
        )
        self.execution._assert_deadline_before_side_effect(deadline)
        launch = self._rebuild_queued_worker_launch(
            operation_id=task.operation_id,
            semantic=semantic,
            request_hash=str(context["canonical_input"]["request_hash"]),
            scope=str(context["canonical_input"]["scope"]),
            execution_deadline_at=deadline,
        )
        self.execution._assert_deadline_before_side_effect(deadline)
        if not isinstance(self.runtime_generation_id, str) or not self.runtime_generation_id:
            raise CapabilityUnavailableError(
                "runtime generation is unavailable for queued start",
                details={"reason_code": "RUNTIME_GENERATION_NOT_AVAILABLE"},
            )
        reservation = workers.reserve_capacity()
        handles = SimpleNamespace(task=task, run=run, attempt=attempt)
        admission_committed = False
        try:
            confirmation_at = datetime.now(timezone.utc)
            with self.task_persistence.begin() as unit:
                current_task = unit.require_task(task_id)
                current_run = unit.require_run(current_task.active_run_id)
                current_attempt_row = unit.connection.execute(
                    """
                    SELECT attempt_id
                    FROM task_attempt
                    WHERE run_id=?
                    ORDER BY attempt_no DESC
                    LIMIT 1
                    """,
                    (current_run.run_id,),
                ).fetchone()
                if current_attempt_row is None:
                    raise ConflictError("Task has no current Attempt")
                current_attempt = unit.require_attempt(str(current_attempt_row[0]))
                if (
                    current_task.project_id != project_id
                    or current_task.state is not TaskState.QUEUED
                    or current_task.state_version != expected_state_version
                    or current_run.run_id != run.run_id
                    or current_attempt.attempt_id != attempt.attempt_id
                    or current_attempt.state is not AttemptState.QUEUED
                ):
                    raise ConflictError("Task changed while it was being started")
                try:
                    rebound = self.progress_persistence.rebind_queued_attempt_generation_in_transaction(
                        unit.connection,
                        attempt.attempt_id,
                        runtime_generation_id=self.runtime_generation_id,
                    )
                    ready = self.progress_persistence.transition_dispatch_in_transaction(
                        unit.connection,
                        task_id,
                        expected_state="HOLD",
                        new_state="READY",
                        expected_state_version=expected_dispatch_state_version,
                        user_confirmed_at=confirmation_at,
                    )
                except (DispatchStateConflict, RuntimeResolutionConflict) as error:
                    raise ConflictError(
                        "Task dispatch admission changed while it was being started"
                    ) from error
                unit.append_event(
                    PendingTaskEvent(
                        event_id=mint_v3_id("tev_"),
                        event_version=_TASK_EVENT_VERSION,
                        project_id=project_id,
                        task_id=task_id,
                        event_type="TASK_DISPATCH_READY",
                        occurred_at=confirmation_at,
                        payload={
                            "dispatch_state": ready.state,
                            "dispatch_state_version": ready.state_version,
                            "user_confirmed_at": wire_time(confirmation_at),
                        },
                        run_id=run.run_id,
                        attempt_id=attempt.attempt_id,
                    )
                )
                if rebound.previous_runtime_generation_id != rebound.runtime_generation_id:
                    unit.append_event(
                        PendingTaskEvent(
                            event_id=mint_v3_id("tev_"),
                            event_version=_TASK_EVENT_VERSION,
                            project_id=project_id,
                            task_id=task_id,
                            event_type="TASK_EXECUTION_GENERATION_REBOUND",
                            occurred_at=confirmation_at,
                            payload={
                                "attempt_id": attempt.attempt_id,
                                "previous_runtime_generation_id": rebound.previous_runtime_generation_id,
                                "runtime_generation_id": rebound.runtime_generation_id,
                                "receipt_rebound": rebound.receipt_rebound,
                            },
                            run_id=run.run_id,
                            attempt_id=attempt.attempt_id,
                        )
                    )
                unit.commit()
                admission_committed = True
        except Exception:
            workers.release_capacity(reservation)
            raise
        try:
            workers.start(
                launch.prepared_request,
                handles,
                reservation_token=reservation,
                operation_id=launch.operation_id,
                work_kind=launch.work_kind,
                resource_class=launch.resource_class,
            )
        except Exception as error:
            workers.release_capacity(reservation)
            if admission_committed and not getattr(
                error, "defer_task_finalization", False
            ):
                self.execution._finish_failure(
                    task,
                    run,
                    attempt,
                    error=error,
                    category=classify_execution_error(error),
                )
            raise
        return self.task_persistence.read_task(task_id)

    def resume_from_checkpoint(
        self,
        *,
        task_id: str,
        project_id: str,
        project_context_revision_id: str,
        checkpoint_artifact_id: str,
        compatibility_hash: str,
        expected_state_version: int,
    ) -> None:
        """Expose the explicit PR03 boundary until a domain safe point exists."""

        self._require_current_project_context(
            project_id, project_context_revision_id
        )
        task, _, _ = self._read_task_bundle(task_id)
        if task.project_id != project_id:
            raise TruthPreconditionFailedError(
                "task belongs to a different project"
            )
        if task.state_version != expected_state_version:
            raise ConflictError("Task state version is stale")
        # Product worker profiles deliberately remain non-resumable in PR03;
        # the input identities are accepted by the contract but must not be
        # mistaken for authority when no verified checkpoint owner exists.
        raise CapabilityUnavailableError(
            "Product checkpoint resume is not available for this operation",
            details={
                "reason_code": "PRODUCT_CHECKPOINT_RESUME_NOT_AVAILABLE",
                "checkpoint_resume": "NOT_AVAILABLE",
                "checkpoint_artifact_id": checkpoint_artifact_id,
                "compatibility_hash": compatibility_hash,
            },
        )

    def read_verified_bytes(self, artifact_id: str) -> bytes:
        """Read content-addressed bytes, applying Catalog authority when registered.

        CoreResearchPipelineService publishes its result bytes through the
        provider-neutral store and Product Runtime registers the exact result
        immediately after re-reading it.  That deliberately narrow
        pre-registration window must still be hash-verified, but it cannot use
        a Catalog row that does not exist yet.  All product-visible reads go
        through ``require_published_artifact`` or a reachability check first.
        """
        connection = self._connection(read_only=True)
        try:
            row = catalog_row(
                connection,
                "SELECT * FROM artifact WHERE artifact_id=?",
                (artifact_id,),
            )
        finally:
            connection.close()
        if row is None:
            try:
                with self.artifact_store.open_verified(artifact_id) as handle:
                    return handle.read()
            except StagingNotFound as exc:
                raise NotFoundError(f"unknown artifact: {artifact_id}") from exc
        row = self.require_published_artifact(artifact_id)
        with self.artifact_store.open_verified(
            artifact_id,
            expected_sha256=str(row["sha256"]),
            expected_byte_size=int(row["byte_size"]),
        ) as handle:
            return handle.read()

    def require_published_artifact_metadata(self, artifact_id: str) -> dict[str, Any]:
        """Return durable publication metadata without reading filesystem bytes.

        This is an admission-only operation for asynchronous work.  It proves
        that the Catalog has a PUBLISHED descriptor, but it deliberately does
        not prove that the current filesystem bytes are still available or
        content-addressed.  A worker must call ``require_published_artifact``
        (or an equivalent verified read) before parsing or computing from the
        payload.
        """
        connection = self._connection(read_only=True)
        try:
            row = catalog_row(connection, "SELECT * FROM artifact WHERE artifact_id=?", (artifact_id,))
        finally:
            connection.close()
        if row is None:
            raise NotFoundError(f"unknown artifact: {artifact_id}")
        if str(row["state"]) != "PUBLISHED":
            raise ArtifactNotPublishedError(f"artifact is not published: {artifact_id}")
        return row

    def require_published_artifact(self, artifact_id: str) -> dict[str, Any]:
        """Require a published Catalog row and currently verified final bytes."""
        row = self.require_published_artifact_metadata(artifact_id)
        connection = self._connection(read_only=True)
        try:
            storage_error = connection.execute(
                """
                SELECT error_code FROM artifact_storage_error
                WHERE artifact_id=? AND resolved_at IS NULL
                  AND error_code IN(
                    'PUBLISHED_BYTES_UNAVAILABLE',
                    'ARTIFACT_CONTENT_ADDRESS_COLLISION_OR_CORRUPTION'
                  )
                ORDER BY created_at DESC LIMIT 1
                """,
                (artifact_id,),
            ).fetchone()
        finally:
            connection.close()
        if storage_error is not None:
            raise ArtifactNotPublishedError(
                f"artifact requires storage reconciliation: {artifact_id}",
                details={"reason_code": str(storage_error[0])},
            )
        try:
            self.artifact_store.verify_final_bytes(
                artifact_id, expected_byte_size=int(row["byte_size"])
            )
        except StagingNotFound as exc:
            raise ArtifactNotPublishedError(
                f"published Artifact bytes are not available: {artifact_id}",
                details={"reason_code": "PUBLISHED_BYTES_UNAVAILABLE"},
            ) from exc
        except (ArtifactCollision, IntegrityMismatch) as exc:
            raise ArtifactNotPublishedError(
                f"published Artifact bytes failed content-address verification: {artifact_id}",
                details={
                    "reason_code": "ARTIFACT_CONTENT_ADDRESS_COLLISION_OR_CORRUPTION",
                },
            ) from exc
        except Exception as exc:
            raise ArtifactNotPublishedError(
                f"published Artifact bytes are not verifiably available: {artifact_id}",
                details={
                    "reason_code": "ARTIFACT_PROMOTION_RECONCILIATION_REQUIRED",
                    "error": str(exc),
                },
            ) from exc
        return row

    def require_project_reachable_artifact(
        self, project_id: str, artifact_id: str
    ) -> dict[str, Any]:
        """Require active reachability from the named Product project."""

        self.require_project(project_id)
        descriptor = self.require_published_artifact(artifact_id)
        connection = self._connection(read_only=True)
        try:
            reachable = connection.execute(
                """
                SELECT 1
                FROM artifact_reference AS ar
                WHERE ar.artifact_id=? AND ar.state='ACTIVE' AND (
                  (ar.owner_type='Project' AND ar.owner_id=?)
                  OR (ar.owner_type='Task' AND ar.owner_id IN (
                    SELECT task_id FROM task WHERE project_id=?
                  ))
                  OR (ar.owner_type='Run' AND ar.owner_id IN (
                    SELECT r.run_id FROM run AS r
                    JOIN task AS t ON t.task_id=r.task_id
                    WHERE t.project_id=?
                  ))
                  OR (ar.owner_type='TaskAttempt' AND ar.owner_id IN (
                    SELECT a.attempt_id FROM task_attempt AS a
                    JOIN run AS r ON r.run_id=a.run_id
                    JOIN task AS t ON t.task_id=r.task_id
                    WHERE t.project_id=?
                  ))
                  OR (ar.owner_type='Result' AND ar.owner_id IN (
                    SELECT result_id FROM result WHERE project_id=?
                  ))
                )
                LIMIT 1
                """,
                (
                    artifact_id,
                    project_id,
                    project_id,
                    project_id,
                    project_id,
                    project_id,
                ),
            ).fetchone()
        finally:
            connection.close()
        if reachable is None:
            raise TruthPreconditionFailedError(
                "Artifact is not reachable from the request project"
            )
        return descriptor

    def require_experiment(self, experiment_id: str) -> dict[str, Any]:
        connection = self._connection(read_only=True)
        try:
            row = catalog_row(
                connection, "SELECT * FROM experiment WHERE experiment_id=?", (experiment_id,)
            )
        finally:
            connection.close()
        if row is None:
            raise NotFoundError(f"unknown experiment: {experiment_id}")
        return row

    def require_result(self, result_id: str) -> dict[str, Any]:
        connection = self._connection(read_only=True)
        try:
            row = catalog_row(connection, "SELECT * FROM result WHERE result_id=?", (result_id,))
        finally:
            connection.close()
        if row is None:
            raise NotFoundError(f"unknown result: {result_id}")
        return row

    def references(self, owner_id: str, role: str | None = None) -> list[dict[str, Any]]:
        connection = self._connection(read_only=True)
        try:
            if role is None:
                rows = catalog_rows(
                    connection,
                    """
                    SELECT owner_id, role, artifact_id FROM artifact_reference
                    WHERE owner_id=? AND state='ACTIVE' ORDER BY role, artifact_id
                    """,
                    (owner_id,),
                )
            else:
                rows = catalog_rows(
                    connection,
                    """
                    SELECT owner_id, role, artifact_id FROM artifact_reference
                    WHERE owner_id=? AND role=? AND state='ACTIVE' ORDER BY artifact_id
                    """,
                    (owner_id, role),
                )
        finally:
            connection.close()
        return rows

    def latest_event_sequence(self, project_id: str) -> int:
        connection = self._connection(read_only=True)
        try:
            value = connection.execute(
                "SELECT COALESCE(MAX(project_sequence),0) FROM task_event WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        return int(value)

    def session_row(self, session_id: str) -> dict[str, Any] | None:
        connection = self._connection(read_only=True)
        try:
            return catalog_row(
                connection, "SELECT * FROM desktop_session WHERE session_id=?", (session_id,)
            )
        finally:
            connection.close()

    # -- capabilities ----------------------------------------------------------

    def capabilities(self) -> tuple[Capability, ...]:
        from v3_backend.contracts.registry import SERVICE_CONTRACTS

        bound_services = {
            "ProjectSessionService",
            "ArtifactService",
            "ProductEntryService",
        }
        capabilities: list[Capability] = []
        for service in sorted(SERVICE_CONTRACTS):
            if service in bound_services:
                capabilities.append(Capability(code=service, truth_state="FORMAL"))
            elif service == "BacktestService":
                capabilities.append(
                    Capability(
                        code=service,
                        truth_state="UNAVAILABLE",
                        reason_code=FORMAL_BACKTEST_UNAVAILABLE_REASON,
                    )
                )
            elif service in {"ResultService", "TaskService"}:
                capabilities.append(
                    Capability(
                        code=service,
                        truth_state="UNAVAILABLE",
                        reason_code="PRODUCT_OPERATION_SET_INCOMPLETE",
                    )
                )
            else:
                capabilities.append(
                    Capability(
                        code=service,
                        truth_state="UNAVAILABLE",
                        reason_code="ASL_FACADE_NOT_BOUND",
                    )
                )
        return tuple(capabilities)

    # -- runtime seam -----------------------------------------------------------

    def reconcile_supervisor(self, accepted) -> None:
        self.reconciliation_summary = self._reconcile_execution_state()
        if accepted.project_id is not None:
            self.event_replay.bind_project(accepted.project_id)

    def cancel_research_task(
        self,
        task_id: str,
        *,
        project_id: str | None = None,
        expected_state_version: int | None = None,
        reason: str,
    ) -> bool:
        """Serialize cancellation with Product worker admission when available."""

        workers = self.research_workers
        with_admission_lock = getattr(workers, "with_admission_lock", None)
        if callable(with_admission_lock):
            return bool(
                with_admission_lock(
                    lambda: self._cancel_research_task_impl(
                        task_id,
                        project_id=project_id,
                        expected_state_version=expected_state_version,
                        reason=reason,
                        allow_queued_without_child=True,
                    )
                )
            )
        return self._cancel_research_task_impl(
            task_id,
            project_id=project_id,
            expected_state_version=expected_state_version,
            reason=reason,
            allow_queued_without_child=False,
        )

    def _cancel_research_task_impl(
        self,
        task_id: str,
        *,
        project_id: str | None = None,
        expected_state_version: int | None = None,
        reason: str,
        allow_queued_without_child: bool,
    ) -> bool:
        """Cancel one isolated research process and durably fence its terminal state.

        The first transaction records intent.  The operating-system child is
        then cooperatively signalled and escalated by the worker owner.  Only a
        confirmed exit permits the second transaction to publish CANCELLED.
        """
        with self._cancellation_lock:
            task = self.task_persistence.read_task(task_id)
            if project_id is not None and task.project_id != project_id:
                raise TruthPreconditionFailedError("task belongs to a different project")
            if task.state in TASK_TERMINAL_STATES:
                if expected_state_version is None:
                    return False
                raise ConflictError("terminal Task cannot be cancelled")
            if (
                expected_state_version is not None
                and task.state_version != expected_state_version
            ):
                raise ConflictError("Task state version is stale")

            with self.task_persistence.begin() as unit:
                current_task = unit.require_task(task_id)
                attempt_row = unit.connection.execute(
                    """
                    SELECT a.attempt_id FROM task_attempt AS a
                    JOIN run AS r ON r.run_id=a.run_id
                    WHERE r.task_id=? ORDER BY a.attempt_no DESC LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                if attempt_row is None:
                    raise ConflictError("Task has no cancellable Attempt")
                attempt_id = str(attempt_row[0])
                if current_task.state is not TaskState.CANCEL_REQUESTED:
                    current_task.state = transition_task(
                        current_task.state,
                        "CANCEL_REQUESTED",
                        TaskTransitionContext(),
                    )
                    unit.save_task(current_task, expected_version=current_task.state_version)
                    unit.append_event(
                        PendingTaskEvent(
                            event_id=mint_v3_id("tev_"),
                            event_version=_TASK_EVENT_VERSION,
                            project_id=current_task.project_id,
                            task_id=task_id,
                            event_type="TASK_CANCEL_REQUESTED",
                            occurred_at=datetime.now(timezone.utc),
                            payload={"reason": reason},
                            run_id=current_task.active_run_id,
                            attempt_id=attempt_id,
                        )
                    )
                unit.commit()

            workers = self.research_workers
            confirmed_exit = workers is not None and workers.cancel(task_id)
            if not confirmed_exit:
                # The listener may have removed the slot after the child had
                # already written ATTEMPT_CANCELLED. Read back before turning
                # an idempotent cancellation race into a false conflict.
                latest = self.task_persistence.latest_attempt(task_id)
                if latest.state is not AttemptState.CANCELLED:
                    latest_task = self.task_persistence.read_task(task_id)
                    if latest_task.state is TaskState.CANCELLED:
                        return True
                    if latest_task.state in TASK_TERMINAL_STATES:
                        return False
                    if not (
                        latest_task.state is TaskState.CANCEL_REQUESTED
                        and latest.state in {
                            AttemptState.FAILED,
                            AttemptState.CANCELLED,
                            AttemptState.LOST,
                        }
                    ) and not (
                        allow_queued_without_child
                        and latest_task.state is TaskState.CANCEL_REQUESTED
                        and latest.state is AttemptState.QUEUED
                    ):
                        raise ConflictError("Task child process exit could not be confirmed")

            with self.task_persistence.begin() as unit:
                current_task = unit.require_task(task_id)
                current_attempt = unit.require_attempt(attempt_id)
                if current_task.state in TASK_TERMINAL_STATES:
                    return current_task.state is TaskState.CANCELLED
                if current_attempt.state not in ATTEMPT_TERMINAL_STATES:
                    current_attempt.state = transition_attempt(
                        current_attempt.state, "ATTEMPT_CANCELLED"
                    )
                    unit.save_attempt(
                        current_attempt, expected_version=current_attempt.state_version
                    )
                elif current_attempt.state not in {
                    AttemptState.CANCELLED,
                    AttemptState.FAILED,
                    AttemptState.LOST,
                }:
                    # A success/failure/lost result won the race; never
                    # overwrite an independently owned terminal Attempt.
                    return False
                current_run = unit.require_run(current_task.active_run_id)
                if current_run.state is not RunState.TERMINAL:
                    current_run.state = transition_run(
                        current_run.state,
                        "TASK_TERMINAL_NO_ACTIVE_ATTEMPT",
                        no_active_attempt=True,
                    )
                    unit.save_run(current_run, expected_version=current_run.state_version)
                if current_task.state is TaskState.CANCEL_REQUESTED:
                    current_task.state = transition_task(
                        current_task.state,
                        "WORKER_CANCELLED_OR_TERMINATED",
                        TaskTransitionContext(cleanup_complete=True),
                    )
                    unit.save_task(current_task, expected_version=current_task.state_version)
                    unit.append_event(
                        PendingTaskEvent(
                            event_id=mint_v3_id("tev_"),
                            event_version=_TASK_EVENT_VERSION,
                            project_id=current_task.project_id,
                            task_id=task_id,
                            event_type="TASK_CANCELLED",
                            occurred_at=datetime.now(timezone.utc),
                            payload={"reason": reason},
                            run_id=current_task.active_run_id,
                            attempt_id=current_attempt.attempt_id,
                        )
                    )
                now = wire_time(datetime.now(timezone.utc))
                unit.connection.execute(
                    """
                    UPDATE worker_lease SET state='REVOKED', released_at=?
                    WHERE attempt_id=? AND state IN ('GRANTED','RENEWED')
                    """,
                    (now, current_attempt.attempt_id),
                )
                self.execution._stop_worker_for_attempt(
                    unit, current_attempt.attempt_id, now
                )
                self.progress_persistence.abort_receipt_in_transaction(
                    unit.connection,
                    attempt_id=current_attempt.attempt_id,
                    error_code="EXECUTION_CANCELLED_PRE_COMMIT",
                )
                unit.commit()
            return True

    def _compatible_restart_checkpoint(
        self, connection: sqlite3.Connection, *, attempt_id: str, run_id: str
    ) -> str | None:
        """Return a checkpoint only after metadata and final bytes re-verify."""

        # A failed/tampered newest checkpoint must not hide an older valid
        # one, so page backwards by the stable (created_at, checkpoint_id)
        # ordering instead of applying a LIMIT that changes recovery truth.
        after: tuple[str, str] | None = None
        while True:
            if after is None:
                rows = connection.execute(
                    """
                    SELECT c.artifact_id,c.input_hash,c.code_version,c.environment_profile_id,
                           c.compatibility_hash,ar.state,ar.sha256,ar.byte_size,
                           r.input_hash,r.code_version,r.environment_profile_id,
                           r.operation_id,r.operation_schema_version,
                           r.resource_policy_version,r.resolved_resource_hash,
                           r.compatibility_hash,c.created_at,c.checkpoint_id
                    FROM checkpoint AS c
                    JOIN artifact AS ar ON ar.artifact_id=c.artifact_id
                    JOIN run AS r ON r.run_id=?
                    WHERE c.attempt_id=?
                    ORDER BY c.created_at DESC,c.checkpoint_id DESC
                    LIMIT ?
                    """,
                    (run_id, attempt_id, MAX_RECONCILIATION_BATCH),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT c.artifact_id,c.input_hash,c.code_version,c.environment_profile_id,
                           c.compatibility_hash,ar.state,ar.sha256,ar.byte_size,
                           r.input_hash,r.code_version,r.environment_profile_id,
                           r.operation_id,r.operation_schema_version,
                           r.resource_policy_version,r.resolved_resource_hash,
                           r.compatibility_hash,c.created_at,c.checkpoint_id
                    FROM checkpoint AS c
                    JOIN artifact AS ar ON ar.artifact_id=c.artifact_id
                    JOIN run AS r ON r.run_id=?
                    WHERE c.attempt_id=?
                      AND (
                        c.created_at < ?
                        OR (c.created_at=? AND c.checkpoint_id < ?)
                      )
                    ORDER BY c.created_at DESC,c.checkpoint_id DESC
                    LIMIT ?
                    """,
                    (
                        run_id,
                        attempt_id,
                        after[0],
                        after[0],
                        after[1],
                        MAX_RECONCILIATION_BATCH,
                    ),
                ).fetchall()
            if not rows:
                break
            for row in rows:
                if str(row[5]) != "PUBLISHED":
                    continue
                if any(
                    str(row[index]) != str(row[other])
                    for index, other in (
                        (1, 8),
                        (2, 9),
                        (3, 10),
                    )
                ):
                    continue
                resolved_hash = str(row[14])
                if resolved_hash == "0" * 64:
                    continue
                try:
                    expected_compatibility = compatibility_hash_for_context(
                        input_hash=str(row[8]),
                        code_version=str(row[9]),
                        environment_profile=str(row[10]),
                        operation_id=str(row[11]),
                        operation_schema_version=str(row[12]),
                        resource_policy_version=str(row[13]),
                        resolved_resource_hash=resolved_hash,
                    )
                except (TypeError, ValueError):
                    continue
                if (
                    str(row[4]) != expected_compatibility
                    or str(row[15]) != expected_compatibility
                    or str(row[6]) != str(row[0]).removeprefix("art_sha256_")
                    or int(row[7]) < 0
                ):
                    continue
                verifier = getattr(self.artifact_store, "verify_final_bytes", None)
                if not callable(verifier):
                    continue
                try:
                    observed_sha, observed_size = verifier(
                        str(row[0]), expected_byte_size=int(row[7])
                    )
                except Exception:
                    continue
                if observed_sha == str(row[6]) and observed_size == int(row[7]):
                    return str(row[0])
            last = rows[-1]
            after = (str(last[16]), str(last[17]))
        return None

    def _reconcile_execution_state(self) -> dict[str, int]:
        """Reconcile live execution rows without inventing restart recovery.

        Inline workers are compatibility-only and fail on restart. Isolated
        workers are also never auto-spawned: a verified checkpoint can leave a
        Task PAUSED, otherwise the Task fails with explicit worker-loss truth.
        Queued/paused rows are always returned to a user-visible HOLD.
        """

        terminal_tasks = {item.value for item in TASK_TERMINAL_STATES}
        terminal_attempts = {item.value for item in ATTEMPT_TERMINAL_STATES}
        isolated_worker_kind = "PRODUCT_RESEARCH_PROCESS_V1"
        now_dt = datetime.now(timezone.utc)
        now = wire_time(now_dt)
        counts: dict[str, int] = {
            "active_leases_revoked": 0,
            "expired_leases_reconciled": 0,
            "attempts_lost": 0,
            "attempts_cancelled_after_restart": 0,
            "tasks_failed": 0,
            "tasks_cancelled_after_restart": 0,
            "tasks_paused": 0,
            "checkpoint_candidates": 0,
            "dispatch_holds_after_restart": 0,
            "workers_stopped": 0,
            "receipts_completed_after_restart": 0,
        }
        with self.task_persistence.begin() as unit:
            # Reconciliation must drain the complete durable set, but never
            # materialize an unbounded number of leases in one Python list.
            # The ordered keyset also remains correct while each yielded row
            # is moved out of the GRANTED/RENEWED/EXPIRED source set.
            def active_lease_rows():
                after: tuple[str, int, str] | None = None
                while True:
                    if after is None:
                        rows = unit.connection.execute(
                            """
                            SELECT l.lease_id,l.attempt_id,l.worker_id,l.state AS lease_state,
                                   a.attempt_no AS attempt_no,
                                   a.state AS attempt_state,a.runtime_generation_id,
                                   r.task_id,r.run_id,r.state AS run_state,
                                   t.project_id,t.state AS task_state,w.worker_kind,
                                   w.state AS worker_state
                            FROM worker_lease AS l
                            JOIN task_attempt AS a ON a.attempt_id=l.attempt_id
                            JOIN run AS r ON r.run_id=a.run_id
                            JOIN task AS t ON t.task_id=r.task_id
                            JOIN worker AS w ON w.worker_id=l.worker_id
                            WHERE l.state IN ('GRANTED','RENEWED','EXPIRED')
                            ORDER BY t.task_id,a.attempt_no,l.lease_id
                            LIMIT ?
                            """,
                            (MAX_RECONCILIATION_BATCH,),
                        ).fetchall()
                    else:
                        rows = unit.connection.execute(
                            """
                            SELECT l.lease_id,l.attempt_id,l.worker_id,l.state AS lease_state,
                                   a.attempt_no AS attempt_no,
                                   a.state AS attempt_state,a.runtime_generation_id,
                                   r.task_id,r.run_id,r.state AS run_state,
                                   t.project_id,t.state AS task_state,w.worker_kind,
                                   w.state AS worker_state
                            FROM worker_lease AS l
                            JOIN task_attempt AS a ON a.attempt_id=l.attempt_id
                            JOIN run AS r ON r.run_id=a.run_id
                            JOIN task AS t ON t.task_id=r.task_id
                            JOIN worker AS w ON w.worker_id=l.worker_id
                            WHERE l.state IN ('GRANTED','RENEWED','EXPIRED')
                              AND (
                                t.task_id > ?
                                OR (t.task_id=? AND a.attempt_no > ?)
                                OR (t.task_id=? AND a.attempt_no=? AND l.lease_id > ?)
                              )
                            ORDER BY t.task_id,a.attempt_no,l.lease_id
                            LIMIT ?
                            """,
                            (
                                after[0],
                                after[0],
                                after[1],
                                after[0],
                                after[1],
                                after[2],
                                MAX_RECONCILIATION_BATCH,
                            ),
                        ).fetchall()
                    if not rows:
                        return
                    yield from rows
                    last = rows[-1]
                    after = (
                        str(last["task_id"]),
                        int(last["attempt_no"]),
                        str(last["lease_id"]),
                    )

            def append_event(
                row: Any,
                event_type: str,
                payload: dict[str, object],
                *,
                attempt_id: str | None = None,
            ) -> None:
                unit.append_event(
                    PendingTaskEvent(
                        event_id=mint_v3_id("tev_"),
                        event_version=_TASK_EVENT_VERSION,
                        project_id=str(row["project_id"]),
                        task_id=str(row["task_id"]),
                        event_type=event_type,
                        occurred_at=now_dt,
                        payload=payload,
                        run_id=str(row["run_id"]),
                        attempt_id=attempt_id,
                    )
                )

            def hold_task(row: Any) -> None:
                task_id = str(row["task_id"])
                control = unit.connection.execute(
                    "SELECT state,hold_reason,user_confirmed_at FROM task_dispatch_control WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                changed = control is None or (
                    str(control[0]) != "HOLD"
                    or str(control[1]) != "HOLD_AFTER_RESTART"
                    or control[2] is not None
                )
                if control is None:
                    unit.connection.execute(
                        """
                        INSERT INTO task_dispatch_control(
                          task_id,state,hold_reason,user_confirmed_at,state_version,updated_at
                        ) VALUES(?,'HOLD','HOLD_AFTER_RESTART',NULL,0,?)
                        """,
                        (task_id, now),
                    )
                elif changed:
                    unit.connection.execute(
                        """
                        UPDATE task_dispatch_control
                        SET state='HOLD',hold_reason='HOLD_AFTER_RESTART',
                            user_confirmed_at=NULL,state_version=state_version+1,updated_at=?
                        WHERE task_id=?
                        """,
                        (now, task_id),
                    )
                if changed:
                    counts["dispatch_holds_after_restart"] += 1
                    append_event(
                        row,
                        "TASK_DISPATCH_HELD",
                        {"reason_code": "HOLD_AFTER_RESTART"},
                    )

            def terminalize_dispatch(task_id: str) -> None:
                unit.connection.execute(
                    """
                    UPDATE task_dispatch_control
                    SET state='TERMINAL',hold_reason=NULL,user_confirmed_at=NULL,
                        state_version=state_version+1,updated_at=?
                    WHERE task_id=? AND state<>'TERMINAL'
                    """,
                    (now, task_id),
                )

            def finalize_restart_cancellation(row: Any) -> None:
                """Complete a persisted cancel intent after restart recovery.

                Cancellation intent is durable before the OS signal is sent.
                If the process dies, or the runtime crashes after the signal,
                the next generation must not reinterpret that intent as a
                worker failure or leave the Task in CANCEL_REQUESTED forever.
                A COMMITTED receipt remains an explicit commit boundary and
                therefore stops this reconciliation rather than being
                overwritten by cancellation.
                """

                task_id = str(row["task_id"])
                current_task = unit.require_task(task_id)
                if current_task.state is not TaskState.CANCEL_REQUESTED:
                    return
                attempt_id = str(row["attempt_id"])
                current_attempt = unit.require_attempt(attempt_id)
                if current_attempt.state is AttemptState.SUCCEEDED:
                    raise ConflictError(
                        "cancelled Task has a successful Attempt"
                    )
                receipt = self.progress_persistence.abort_receipt_in_transaction(
                    unit.connection,
                    attempt_id=attempt_id,
                    error_code="EXECUTION_CANCELLED_PRE_COMMIT",
                )
                if receipt is not None and receipt.state in {"COMMITTED", "SUCCEEDED"}:
                    raise ConflictError(
                        "cancelled Task has a committed operation receipt"
                    )
                if current_attempt.state not in terminal_attempts:
                    unit.connection.execute(
                        """
                        UPDATE task_attempt
                        SET state='CANCELLED',
                            error_code='EXECUTION_CANCELLED_PRE_COMMIT',
                            interruption_reason=COALESCE(interruption_reason,?),
                            finished_at=?
                        WHERE attempt_id=?
                          AND state NOT IN ('SUCCEEDED','FAILED','CANCELLED','LOST')
                        """,
                        ("RUNTIME_RESTART_CANCELLATION", now, attempt_id),
                    )
                    counts["attempts_cancelled_after_restart"] += 1
                    append_event(
                        row,
                        "ATTEMPT_TERMINAL",
                        {
                            "state": "CANCELLED",
                            "error_category": "EXECUTION_CANCELLED_PRE_COMMIT",
                            "reason_code": "RUNTIME_RESTART_CANCELLATION",
                        },
                        attempt_id=attempt_id,
                    )
                current_run = unit.require_run(current_task.active_run_id)
                if current_run.state is not RunState.TERMINAL:
                    current_run.state = transition_run(
                        current_run.state,
                        "TASK_TERMINAL_NO_ACTIVE_ATTEMPT",
                        no_active_attempt=True,
                    )
                    unit.save_run(current_run, expected_version=current_run.state_version)
                current_task.state = transition_task(
                    current_task.state,
                    "WORKER_CANCELLED_OR_TERMINATED",
                    TaskTransitionContext(cleanup_complete=True),
                )
                unit.save_task(current_task, expected_version=current_task.state_version)
                append_event(
                    row,
                    "TASK_CANCELLED",
                    {
                        "reason_code": "RUNTIME_RESTART_CANCELLATION",
                        "error_category": "EXECUTION_CANCELLED_PRE_COMMIT",
                    },
                    attempt_id=attempt_id,
                )
                terminalize_dispatch(task_id)
                counts["tasks_cancelled_after_restart"] += 1

            for row in active_lease_rows():
                task_id = str(row["task_id"])
                attempt_id = str(row["attempt_id"])
                task_is_terminal = str(row["task_state"]) in terminal_tasks
                prior_lease_state = str(row["lease_state"])
                lease_is_active = prior_lease_state in {"GRANTED", "RENEWED"}
                isolated = str(row["worker_kind"]) == isolated_worker_kind
                if lease_is_active:
                    lease_state = "RELEASED" if task_is_terminal else "REVOKED"
                    counts["active_leases_revoked"] += 1
                else:
                    lease_state = "EXPIRED"
                    counts["expired_leases_reconciled"] += 1
                unit.connection.execute(
                    """
                    UPDATE worker_lease SET state=?,released_at=?
                    WHERE lease_id=? AND state IN ('GRANTED','RENEWED','EXPIRED')
                    """,
                    (lease_state, now, str(row["lease_id"])),
                )
                worker_state = "STOPPED" if task_is_terminal else "LOST"
                worker_cursor = unit.connection.execute(
                    """
                    UPDATE worker SET state=?,stopped_at=?
                    WHERE worker_id=? AND state IN ('STARTING','IDLE','BUSY','DRAINING')
                    """,
                    (worker_state, now, str(row["worker_id"])),
                )
                counts["workers_stopped"] += worker_cursor.rowcount
                if str(row["attempt_state"]) not in terminal_attempts:
                    attempt_cursor = unit.connection.execute(
                        """
                        UPDATE task_attempt
                        SET state='LOST',error_code='WORKER_LOST',
                            interruption_reason=COALESCE(interruption_reason,?),finished_at=?
                        WHERE attempt_id=? AND state NOT IN ('SUCCEEDED','FAILED','CANCELLED','LOST')
                        """,
                        ("RUNTIME_RESTART_RECONCILIATION", now, attempt_id),
                    )
                    if attempt_cursor.rowcount == 1:
                        counts["attempts_lost"] += 1
                        append_event(
                            row,
                            "ATTEMPT_TERMINAL",
                            {
                                "state": "LOST",
                                "error_category": "WORKER_LOST",
                                "reason_code": "RUNTIME_RESTART_RECONCILIATION",
                            },
                            attempt_id=attempt_id,
                        )
                if str(row["task_state"]) == "CANCEL_REQUESTED":
                    finalize_restart_cancellation(row)
                    continue
                if task_is_terminal:
                    # A terminal Task is already the semantic owner of the
                    # outcome, but its dispatch control row must not remain
                    # DISPATCHED after a crash between task finality and
                    # control cleanup.  Close that queue state before
                    # skipping the worker-loss branch.
                    terminalize_dispatch(task_id)
                    continue
                # Multiple stale leases can point at one Task.  Re-read the
                # durable Task state after the lease/Attempt cleanup so a
                # later row cannot repeat terminalization or checkpoint
                # finality.  This avoids a cross-table-size in-memory set.
                current_task = unit.require_task(task_id)
                if current_task.state in TASK_TERMINAL_STATES:
                    terminalize_dispatch(task_id)
                    continue
                if current_task.state is TaskState.PAUSED:
                    hold_task(row)
                    continue
                checkpoint_id = (
                    self._compatible_restart_checkpoint(
                        unit.connection, attempt_id=attempt_id, run_id=str(row["run_id"])
                    )
                    if isolated
                    else None
                )
                if checkpoint_id is not None:
                    counts["checkpoint_candidates"] += 1
                    cursor = unit.connection.execute(
                        """
                        UPDATE task
                        SET state='PAUSED',state_version=state_version+1,
                            updated_at=?,terminal_at=NULL
                        WHERE task_id=? AND state NOT IN ('SUCCEEDED','FAILED','CANCELLED','PARTIAL','PAUSED')
                        """,
                        (now, task_id),
                    )
                    if cursor.rowcount == 1:
                        counts["tasks_paused"] += 1
                        append_event(
                            row,
                            "TASK_PAUSED",
                            {
                                "reason_code": "RUNTIME_RESTART_RECONCILIATION",
                                "checkpoint_artifact_id": checkpoint_id,
                            },
                            attempt_id=attempt_id,
                        )
                    hold_task(row)
                    try:
                        self.progress_persistence.finalize_receipt_in_transaction(
                            unit.connection,
                            attempt_id=attempt_id,
                            success=False,
                            error_code="WORKER_LOST",
                        )
                    except Exception:
                        # A receipt may already be terminal because another
                        # observer won the restart race.  The paused Task and
                        # verified checkpoint remain the canonical recovery
                        # view; never rewrite them for a stale receipt error.
                        pass
                else:
                    cursor = unit.connection.execute(
                        """
                        UPDATE task
                        SET state='FAILED',state_version=state_version+1,
                            updated_at=?,terminal_at=?
                        WHERE task_id=? AND state NOT IN ('SUCCEEDED','FAILED','CANCELLED','PARTIAL')
                        """,
                        (now, now, task_id),
                    )
                    if cursor.rowcount == 1:
                        counts["tasks_failed"] += 1
                        unit.connection.execute(
                            """
                            UPDATE run SET state='TERMINAL',terminal_at=?
                            WHERE run_id=? AND state IN ('SEALED','ACTIVE')
                            """,
                            (now, str(row["run_id"])),
                        )
                        append_event(
                            row,
                            "TASK_FAILED",
                            {
                                "error_type": "RuntimeRestartReconciliation",
                                "error_message": (
                                    "worker execution was interrupted by runtime restart; "
                                    "no verified checkpoint was available"
                                ),
                                "error_category": "WORKER_LOST",
                                "reason_code": "RUNTIME_RESTART_RECONCILIATION",
                                "checkpoint_resume": "NOT_AVAILABLE",
                            },
                            attempt_id=attempt_id,
                        )
                        try:
                            self.progress_persistence.finalize_receipt_in_transaction(
                                unit.connection,
                                attempt_id=attempt_id,
                                success=False,
                                error_code="WORKER_LOST",
                            )
                        except Exception:
                            # A receipt conflict must not rewrite a terminal
                            # Task; the durable task/error event remains truth.
                            pass
                    terminalize_dispatch(task_id)

            # A queue row may have no live lease at all. Rehydrate it as a
            # HOLD, including a PAUSED task that was left by an earlier run.
            # These scans are keyset-paged as well: holding a row changes its
            # control record, not the source Task state, so a LIMIT-only loop
            # would repeatedly read the same page forever.
            def queued_task_rows():
                after = ""
                while True:
                    rows = unit.connection.execute(
                        """
                        SELECT t.task_id,t.project_id,t.state,r.run_id
                        FROM task AS t
                        JOIN run AS r
                          ON r.task_id=t.task_id
                         AND r.run_no=(SELECT MAX(run_no) FROM run WHERE task_id=t.task_id)
                        WHERE t.state IN ('QUEUED','PAUSED','PAUSE_REQUESTED')
                          AND NOT EXISTS (
                            SELECT 1
                            FROM task_attempt AS a
                            JOIN worker_lease AS l ON l.attempt_id=a.attempt_id
                            WHERE a.run_id=r.run_id AND l.state IN ('GRANTED','RENEWED','EXPIRED')
                          )
                          AND t.task_id>?
                        ORDER BY t.task_id
                        LIMIT ?
                        """,
                        (after, MAX_RECONCILIATION_BATCH),
                    ).fetchall()
                    if not rows:
                        return
                    yield from rows
                    after = str(rows[-1]["task_id"])

            def cancel_requested_rows():
                after = ""
                while True:
                    rows = unit.connection.execute(
                        """
                        SELECT t.task_id,t.project_id,t.state AS task_state,
                               r.run_id,r.state AS run_state,
                               a.attempt_id,a.state AS attempt_state
                        FROM task AS t
                        JOIN run AS r
                          ON r.task_id=t.task_id
                         AND r.run_no=(SELECT MAX(run_no) FROM run WHERE task_id=t.task_id)
                        JOIN task_attempt AS a
                          ON a.run_id=r.run_id
                         AND a.attempt_no=(SELECT MAX(attempt_no) FROM task_attempt WHERE run_id=r.run_id)
                        WHERE t.state='CANCEL_REQUESTED'
                          AND NOT EXISTS (
                            SELECT 1
                            FROM task_attempt AS active_attempt
                            JOIN worker_lease AS l ON l.attempt_id=active_attempt.attempt_id
                            WHERE active_attempt.run_id=r.run_id
                              AND l.state IN ('GRANTED','RENEWED','EXPIRED')
                          )
                          AND t.task_id>?
                        ORDER BY t.task_id
                        LIMIT ?
                        """,
                        (after, MAX_RECONCILIATION_BATCH),
                    ).fetchall()
                    if not rows:
                        return
                    yield from rows
                    after = str(rows[-1]["task_id"])

            for row in cancel_requested_rows():
                finalize_restart_cancellation(row)
            for row in queued_task_rows():
                hold_task(row)
            stopped = unit.connection.execute(
                """
                UPDATE worker SET state='STOPPED',stopped_at=?
                WHERE state IN ('STARTING','IDLE','BUSY','DRAINING')
                  AND worker_id IN (
                    SELECT l.worker_id
                    FROM worker_lease AS l
                    JOIN task_attempt AS a ON a.attempt_id=l.attempt_id
                    JOIN run AS r ON r.run_id=a.run_id
                    JOIN task AS t ON t.task_id=r.task_id
                    WHERE l.state='RELEASED'
                      AND t.state IN ('SUCCEEDED','FAILED','CANCELLED','PARTIAL')
                  )
                """,
                (now,),
            )
            counts["workers_stopped"] += stopped.rowcount
            # _finish_success writes Task/Attempt finality and the receipt's
            # COMMITTED boundary in one transaction, then closes the receipt
            # in a second idempotent step.  A crash between those steps must
            # be repaired from the successful durable owner on the next
            # startup; never infer success from a COMMITTED receipt alone.
            def committed_success_rows():
                after = ""
                while True:
                    rows = unit.connection.execute(
                        """
                        SELECT o.operation_receipt_id
                        FROM control_operation_receipt AS o
                        JOIN task AS t ON t.task_id=o.task_id
                        JOIN task_attempt AS a ON a.attempt_id=o.attempt_id
                        WHERE o.state='COMMITTED'
                          AND t.state='SUCCEEDED'
                          AND a.state='SUCCEEDED'
                          AND o.operation_receipt_id>?
                        ORDER BY o.operation_receipt_id
                        LIMIT ?
                        """,
                        (after, MAX_RECONCILIATION_BATCH),
                    ).fetchall()
                    if not rows:
                        return
                    yield from rows
                    after = str(rows[-1]["operation_receipt_id"])

            for receipt_row in committed_success_rows():
                self.progress_persistence.complete_receipt_in_transaction(
                    unit.connection,
                    str(receipt_row[0]),
                    updated_at=now_dt,
                )
                counts["receipts_completed_after_restart"] += 1
            unit.commit()
        return counts

    def prepare_shutdown(self, deadline: str | None) -> dict[str, str]:
        # The session has already stopped accepting commands, but the
        # shutdown owner still must validate and enforce its absolute control
        # deadline before closing resources or mutating the Catalog.  An
        # expired/invalid request must not leave a half-prepared runtime.
        if deadline is not None:
            self.execution._parse_execution_deadline(deadline)
            self.execution._assert_deadline_before_side_effect(deadline)
        self._shutdown_prepared = True
        self.execution._assert_deadline_before_side_effect(deadline)
        self.local_data_transfers.close()
        if self.research_workers is not None:
            for task_id in self.research_workers.task_ids():
                self.execution._assert_deadline_before_side_effect(deadline)
                task = self.task_persistence.read_task(task_id)
                if task.state in TASK_TERMINAL_STATES:
                    self.execution._assert_deadline_before_side_effect(deadline)
                    if not self.research_workers.confirm_terminal_exit(task_id):
                        raise ConflictError(
                            "shutdown cannot confirm terminal research child exit"
                        )
                else:
                    self.execution._assert_deadline_before_side_effect(deadline)
                    self.cancel_research_task(
                        task_id,
                        reason="RUNTIME_SHUTDOWN",
                    )
            if self.research_workers.has_live_processes():
                raise ConflictError("shutdown cannot confirm all research child exits")
        self.execution._assert_deadline_before_side_effect(deadline)
        self.reconciliation_summary = self._reconcile_execution_state()
        if self.runtime_generation_id is not None:
            self.execution._assert_deadline_before_side_effect(deadline)
            self.progress_persistence.close_generation(self.runtime_generation_id)
        return {
            "execution_mode": (
                "ISOLATED_PRODUCT_PROCESS"
                if self.research_workers is not None
                else "SYNCHRONOUS_IN_PROCESS"
            ),
            "active_task_policy": (
                "CANCEL_AND_CONFIRM_EXIT_BEFORE_SHUTDOWN"
                if self.research_workers is not None
                else "DRAIN_BEFORE_SHUTDOWN"
            ),
            "checkpoint_resume": "UNAVAILABLE",
            "shutdown_truth": "PROCESS_EXIT_CONFIRMED_NO_CHECKPOINT",
        }

    def commit_shutdown(self) -> None:
        if self.research_workers is not None and self.research_workers.has_live_processes():
            raise ConflictError("runtime shutdown commit requires zero live research children")
        self._shutdown_committed = True


def build_product_runtime(
    storage_root: str | Path | None = None,
    *,
    research_provider_factory=None,
    research_worker_config: ProductResearchWorkerConfig | None = None,
) -> ProductRuntime:
    return ProductRuntime(
        resolve_product_storage_root(None if storage_root is None else str(storage_root)),
        research_provider_factory=research_provider_factory,
        research_worker_config=research_worker_config,
    )


def build_product_ports(
    storage_root: str | Path | None = None,
    *,
    research_provider_factory=None,
    research_provider_mode: str | None = None,
) -> RuntimePorts:
    """Normal production RuntimePorts: real facades over durable product stores."""
    from .product_entry import handle_product_entry_control
    from .product_facades import ArtifactFacade, build_product_facades
    from .product_workers import ProductResearchWorkerConfig

    product = build_product_runtime(
        storage_root,
        research_provider_factory=research_provider_factory,
        research_worker_config=ProductResearchWorkerConfig(
            provider_mode=research_provider_mode,
        ),
    )
    handlers: dict[str, Any] = {}
    facades = build_product_facades(product)
    artifact_facade = next(
        facade for facade in facades if isinstance(facade, ArtifactFacade)
    )
    for facade in facades:
        handlers.update(facade.handlers())
    return RuntimePorts(
        operation_handlers=handlers,
        capabilities=product.capabilities(),
        event_replay=product.event_replay,
        startup_reconcile=product.reconcile_supervisor,
        prepare_shutdown=product.prepare_shutdown,
        commit_shutdown=product.commit_shutdown,
        product_entry_control=(
            lambda kind, message: handle_product_entry_control(product, kind, message)
        ),
        local_data_control=product.local_data_transfers.handle,
        artifact_stream_control=artifact_facade.handle_stream_control,
        artifact_export_control=artifact_facade.handle_export_control,
    )


__all__ = [
    "ADMITTED_EXECUTION_ADAPTER_VERSION_ID",
    "FORMAL_BACKTEST_UNAVAILABLE_REASON",
    "BACKTEST_RUN_RESULT_ROLE",
    "BACKTEST_RUN_SPEC_ROLE",
    "DEFAULT_RETENTION_PROFILE",
    "EXPORT_MANIFEST_ROLE",
    "LEDGER_MANIFEST_ROLE",
    "PRODUCT_EXECUTION_CONTEXT_ROLE",
    "PRODUCT_RUNTIME_VERSION",
    "ProductRuntime",
    "build_product_ports",
    "build_product_runtime",
    "mint_v3_id",
    "mint_uuid7",
    "product_artifact_policy",
    "resolve_product_storage_root",
]
