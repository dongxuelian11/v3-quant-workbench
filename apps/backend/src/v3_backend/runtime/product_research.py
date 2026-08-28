"""Bounded Product Entry composition for executable free-data research.

This module is deliberately a composition boundary.  It admits one canonical
provider profile, resolves actual provider bytes, normalizes those bytes through
the existing Data Truth adapter, and then calls the existing Strategy,
Portfolio, Risk, and CoreResearchPipeline owners.  It never accepts market
observations or any other numeric market truth from the Product Entry caller.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol
from zoneinfo import ZoneInfo

from v3_backend.adapters.market_data.akshare import (
    AkshareAShareEodAdapter,
    ProviderAcquisitionError,
)
from v3_backend.adapters.sqlite.artifact_publication import SQLiteArtifactPublicationPort
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.portfolio_risk_owner import SQLitePortfolioRiskPolicyOwner
from v3_backend.adapters.sqlite.repositories import (
    SQLiteRepositoryRegistry,
    SQLiteTableRepository,
)
from v3_backend.adapters.sqlite.risk_application import SQLiteRiskApplicationRepository
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.errors import CapabilityUnavailableError
from v3_backend.domain.artifacts.identity import artifact_id_for_bytes
from v3_backend.domain.artifacts.model import ArtifactDescriptor, ArtifactReference
from v3_backend.domain.artifacts.publication import ArtifactPublication
from v3_backend.domain.backtest_runtime import (
    AshareTradingRuleProfileVersion,
    Board,
    BoardTradingRule,
    ExecutionTimingProfileVersion,
    cn_a_share_2023_08_28_cost_policy,
)
from v3_backend.domain.data_truth import (
    ConnectorDataCapability,
    PersistedProviderAdmission,
    ProviderAdapterRegistry,
    ProviderCanonicalAdmissionUnavailable,
    ProviderExecutionBinding,
    ProviderPolicyMismatch,
    ProviderRuntimeConfig,
    RevisionSemantics,
)
from v3_backend.domain.data_truth.capabilities import (
    FIELD_CAPABILITY_POLICY_ROLE,
    FIELD_CAPABILITY_POLICY_SCHEMA_FINGERPRINT,
    FieldCapabilityPolicy,
)
from v3_backend.domain.data_truth.provider_ingestion import (
    ResearchDataSnapshot,
    normalize_a_share_eod,
)
from v3_backend.domain.datasets import (
    DatasetBinding,
    DatasetVersion,
    FeatureSetVersion,
    LabelSpec,
    SplitSpec,
)
from v3_backend.domain.factors import (
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FactorEvaluation,
    FactorEvaluationContext,
    FeatureMaterialization,
    FeatureNode,
    UnresolvedIdUpstreamTruthBinding,
    default_operator_registry,
)
from v3_backend.domain.portfolio_construction import (
    CanonicalPortfolioOwnerService,
    ConstructionMethod,
    PortfolioConstructionSpecVersion,
)
from v3_backend.domain.research_pipeline import (
    CoreResearchPipelineService,
    ResearchBarObservation,
    ResearchExecutionAssumptionProfile,
    ResearchPipelineRequest,
    ResearchSessionObservation,
    RESEARCH_BACKTEST_RESULT_ROLE,
)
from v3_backend.domain.research_pipeline.runtime import RESEARCH_BACKTEST_RESULT_SCHEMA_FINGERPRINT
from v3_backend.domain.risk_runtime import (
    CanonicalRiskApplicationService,
    CanonicalRiskPolicyAuthoringService,
    MaxSingleNamePolicyInput,
)
from v3_backend.domain.strategies import (
    BindingInputRef,
    BindingSlot,
    BoundInputReference,
    CanonicalOwnerArtifactReference,
    EvaluationPeriod,
    ExactCalendarReference,
    ExactSnapshotReference,
    ExactUniverseReference,
    FormalStrategyEvaluationRequest,
    FormalStrategyEvaluationService,
    FormalStrategyInputRequest,
    NodeOutputRef,
    PortCardinality,
    PortSpec,
    PortValueType,
    StrategyCompiler,
    StrategyIr,
    StrategyNode,
    StrategyEvaluationBindingVersion,
    SCORE_PAYLOAD_ROLE,
    SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
    default_component_registry,
    encode_score_payload_for_universe,
)
from v3_backend.domain.weights import RuntimeIdentity
from v3_backend.errors.exceptions import (
    ConflictError,
    InvalidArgumentError,
    TruthPreconditionFailedError,
)
from v3_backend.migrations import apply_migrations
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256
from v3_backend.repositories.unit_of_work import TransactionMode

from .product_runtime import (
    PRODUCT_CODE_VERSION,
    RUN_LEDGER_MANIFEST_REFERENCE_ROLE,
    RUN_RESULT_REFERENCE_ROLE,
    ProductRuntime,
    ProductResearchSubmission,
    _NoopPublishCallbacks,
    _canonical_request_hash,
    _accept_outcome_json,
    catalog_row,
    classify_execution_error,
    mint_v3_id,
    wire_time,
)


PRODUCT_RESEARCH_OPERATION = "ProductEntryService.v1.submitResearch"
RESEARCH_PROFILE_ID = "RESEARCH_FREE_DATA_V1"
RESEARCH_STRATEGY_PROFILE_ID = "RESEARCH_CLOSE_RANK_TOP1_V1"
RESEARCH_PROVIDER_ID = "pvd_akshare_eastmoney_a_share_eod_v1"
RESEARCH_CONNECTOR_VERSION_ID = "cov_akshare_eod_research_v1"
RESEARCH_CONNECTOR_ID = "con_akshare_eod_research_v1"
RESEARCH_DATASET = "CN_A_SHARE_EOD"
RESEARCH_FREQUENCY = "P1D"
RESEARCH_ADMISSION_PROFILE_ID = "PRODUCT_RESEARCH_FREE_DATA_V1"
RESEARCH_ENVIRONMENT_PROFILE_ID = "v3.product-research-admission/1.0.0"
RESEARCH_CONTEXT_KIND = "PRODUCT_RESEARCH_CONTEXT"
RESEARCH_CONTEXT_SCHEMA_VERSION = "v3.product-research-context/1.0.0"
RESEARCH_LINEAGE_ROLE = "RESEARCH_PIPELINE_LINEAGE"
RESEARCH_SOURCE_REFERENCE_ROLE = "PRODUCT_RESEARCH_SOURCE"
RESEARCH_RAW_CAPTURE_ROLE = "DATA_TRUTH_RAW_CAPTURE"
RESEARCH_CALENDAR_ROLE = "DATA_TRUTH_CALENDAR"
RESEARCH_PARTITION_ROLE = "DATA_TRUTH_SNAPSHOT_PARTITION"
RESEARCH_MEMBERSHIP_ROLE = "UNIVERSE_MEMBERSHIP"
RESEARCH_STRATEGY_PROFILE_ROLE = "RESEARCH_STRATEGY_PROFILE"
RESEARCH_FEATURE_OUTPUT_ROLE = "FEATURE_MATERIALIZATION"
RESEARCH_DATASET_PROFILE_ROLE = "RESEARCH_DATASET_PROFILE"
RESEARCH_LINEAGE_SCHEMA_VERSION = "v3.product-research-lineage/1.0.0"
RESEARCH_MATURITY = "PRODUCT_CONNECTED_CANDIDATE"
RESEARCH_TRUTH_ADMISSION = {"truth": "NOT_FORMAL", "admission": "PRE_ALPHA"}
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class ProductResearchError(RuntimeError):
    """The bounded Product Runtime research composition failed closed."""


def _research_accept_outcome(
    task_id: str,
    run_id: str,
    *,
    operation_receipt_id: str | None = None,
    event_cursor: int | None = None,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "task_id": task_id,
        "run_id": run_id,
        "accepted_state": "QUEUED",
        "maturity": RESEARCH_MATURITY,
        "research_profile_id": RESEARCH_PROFILE_ID,
        "strategy_profile_id": RESEARCH_STRATEGY_PROFILE_ID,
        "research_classification": ["RESEARCH_ONLY", "APPROXIMATE"],
        "truth_admission": dict(RESEARCH_TRUTH_ADMISSION),
    }
    if operation_receipt_id is not None:
        outcome["operation_receipt_id"] = operation_receipt_id
    if event_cursor is not None:
        outcome["event_cursor"] = event_cursor
    return outcome


class ResearchProviderFactory(Protocol):
    def __call__(self, config: ProviderRuntimeConfig) -> Any: ...


_PROVIDER_ADMISSION_QUERY = """
SELECT capability.provider_id, capability.connector_version_id,
       capability.policy_artifact_id, connector.state AS connector_state,
       version.state AS version_state, authority.declared_state,
       admission.state AS admission_state
FROM connector_data_capability AS capability
JOIN connector_version AS version
  ON version.connector_version_id=capability.connector_version_id
JOIN connector AS connector ON connector.connector_id=version.connector_id
LEFT JOIN connector_capability AS authority
  ON authority.connector_version_id=capability.connector_version_id
 AND authority.capability_code=capability.capability_code
LEFT JOIN connector_admission AS admission
  ON admission.connector_version_id=capability.connector_version_id
 AND admission.admission_profile_id=?
 AND admission.environment_profile_id=?
WHERE capability.connector_version_id=?
  AND capability.provider_id=?
  AND capability.logical_dataset=?
  AND capability.frequency=?
"""
_POLICY_REFERENCE_QUERY = """
SELECT policy_artifact_id
FROM connector_data_capability
WHERE connector_version_id=? AND provider_id=?
  AND logical_dataset=? AND frequency=?
"""


class _PersistedAdmissionResolver:
    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def _lookup(self, config: ProviderRuntimeConfig) -> Any:
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            row = connection.execute(
                _PROVIDER_ADMISSION_QUERY,
                (
                    RESEARCH_ADMISSION_PROFILE_ID,
                    RESEARCH_ENVIRONMENT_PROFILE_ID,
                    config.connector_version_id,
                    config.provider_id,
                    RESEARCH_DATASET,
                    RESEARCH_FREQUENCY,
                ),
            ).fetchone()
        finally:
            connection.close()
        return row

    def resolve(self, config: ProviderRuntimeConfig) -> PersistedProviderAdmission | None:
        row = self._lookup(config)
        return None if row is None else _admission_from_row(row)


def _admission_from_row(row: Any) -> PersistedProviderAdmission:
    admitted = all(
        str(status_value) == expected_status
        for status_value, expected_status in (
            (row[3], "REGISTERED"),
            (row[4], "ADMITTED"),
            (row[5], "DECLARED"),
            (row[6], "PASSED"),
        )
    )
    return PersistedProviderAdmission(
        provider_id=str(row[0]),
        connector_version_id=str(row[1]),
        policy_artifact_id=str(row[2]),
        admitted=admitted,
    )


class _PersistedPolicyResolver:
    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def _lookup(self, admission: PersistedProviderAdmission) -> Any:
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            row = connection.execute(
                _POLICY_REFERENCE_QUERY,
                (
                    admission.connector_version_id,
                    admission.provider_id,
                    RESEARCH_DATASET,
                    RESEARCH_FREQUENCY,
                ),
            ).fetchone()
        finally:
            connection.close()
        return row

    def _load_policy(self, admission: PersistedProviderAdmission) -> FieldCapabilityPolicy:
        payload = self.product.read_verified_bytes(admission.policy_artifact_id)
        if hashlib.sha256(payload).hexdigest() != admission.policy_artifact_id.removeprefix(
            "art_sha256_"
        ):
            raise ProviderPolicyMismatch("persisted Data Truth policy bytes changed")
        try:
            return FieldCapabilityPolicy.from_canonical_bytes(payload)
        except (TypeError, ValueError) as error:
            raise ProviderPolicyMismatch("persisted Data Truth policy is not canonical") from error

    @staticmethod
    def _validate_policy(
        policy: FieldCapabilityPolicy,
        admission: PersistedProviderAdmission,
    ) -> None:
        if (
            policy.provider_id != admission.provider_id
            or policy.connector_version_id != admission.connector_version_id
            or policy.policy_artifact_id != admission.policy_artifact_id
        ):
            raise ProviderPolicyMismatch("persisted Data Truth policy does not match admission")

    def resolve(self, admission: PersistedProviderAdmission) -> FieldCapabilityPolicy:
        row = self._lookup(admission)
        if row is None or str(row[0]) != admission.policy_artifact_id:
            raise ProviderPolicyMismatch("persisted Data Truth policy reference is unavailable")
        policy = self._load_policy(admission)
        self._validate_policy(policy, admission)
        return policy


_RESEARCH_SOURCE_FIELDS = frozenset(
    {
        "provider_id",
        "connector_version_id",
        "logical_dataset",
        "frequency",
        "symbol",
        "start_date",
        "end_date",
    }
)


def _source_fields(source: Mapping[str, Any]) -> dict[str, str]:
    if set(source) != _RESEARCH_SOURCE_FIELDS:
        raise InvalidArgumentError(
            "research source intent must be closed",
            details={"unknown_or_missing": sorted(set(source) ^ _RESEARCH_SOURCE_FIELDS)},
        )
    return {key: str(source[key]) for key in _RESEARCH_SOURCE_FIELDS}


def _validate_source_identity(source_fields: Mapping[str, str]) -> None:
    if source_fields["provider_id"] != RESEARCH_PROVIDER_ID:
        raise TruthPreconditionFailedError("research provider is not admitted for this Product Entry")
    if source_fields["connector_version_id"] != RESEARCH_CONNECTOR_VERSION_ID:
        raise TruthPreconditionFailedError("research ConnectorVersion is not admitted")
    if (
        source_fields["logical_dataset"] != RESEARCH_DATASET
        or source_fields["frequency"] != RESEARCH_FREQUENCY
    ):
        raise InvalidArgumentError("research source dataset/frequency is not admitted")
    if len(source_fields["symbol"]) != 6 or not source_fields["symbol"].isdigit():
        raise InvalidArgumentError("research symbol must be six ASCII digits")


def _source_date(source_fields: Mapping[str, str], name: str) -> date:
    wire_date = source_fields[name]
    if len(wire_date) != 8 or not wire_date.isdigit():
        raise InvalidArgumentError(f"{name} must use YYYYMMDD")
    try:
        return date.fromisoformat(f"{wire_date[:4]}-{wire_date[4:6]}-{wire_date[6:8]}")
    except ValueError:
        raise InvalidArgumentError(f"{name} must use YYYYMMDD") from None


def _require_exact_source(source: Mapping[str, Any]) -> dict[str, str]:
    source_fields = _source_fields(source)
    _validate_source_identity(source_fields)
    start = _source_date(source_fields, "start_date")
    end = _source_date(source_fields, "end_date")
    if end < start or (end - start).days > 31:
        raise InvalidArgumentError("research source date range must be 0..31 days")
    return source_fields


def _provider_descriptor_wire(descriptor: Any) -> dict[str, Any]:
    return {
        "provider_id": descriptor.provider_id,
        "stable_name": descriptor.stable_name,
        "display_name": descriptor.stable_name,
        "source_authority": descriptor.source_authority,
        "metadata_json": {"metadata_hash": descriptor.metadata_hash},
        "descriptor_hash": descriptor.metadata_hash,
        "state": "REGISTERED",
        "created_at": wire_time(datetime.now(timezone.utc)),
    }


def _insert_idempotent(
    connection,
    table_name: str,
    identity_column: str,
    row: Mapping[str, Any],
) -> None:
    existing = connection.execute(
        f'SELECT * FROM "{table_name}" WHERE "{identity_column}"=?',
        (row[identity_column],),
    ).fetchone()
    if existing is not None:
        _validate_idempotent_row(existing, row, table_name)
        return
    _insert_new_row(connection, table_name, row)


def _validate_idempotent_row(
    existing: Any,
    row: Mapping[str, Any],
    table_name: str,
) -> None:
    existing_wire = {key: existing[key] for key in existing.keys()}
    for key, expected_value in row.items():
        if existing_wire.get(key) != expected_value:
            raise ConflictError(f"canonical {table_name} row conflicts with the admitted source")


def _insert_new_row(connection, table_name: str, row: Mapping[str, Any]) -> None:
    columns = tuple(row)
    connection.execute(
        f'INSERT INTO "{table_name}" ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
        tuple(row[column] for column in columns),
    )


def _ensure_project_reference(product: ProductRuntime, project_id: str, artifact_id: str, role: str) -> None:
    connection = connect_catalog(product.database_path)
    try:
        row = connection.execute(
            "SELECT 1 FROM artifact_reference WHERE owner_type='Project' AND owner_id=? AND role=? AND artifact_id=?",
            (project_id, role, artifact_id),
        ).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO artifact_reference(
                    artifact_reference_id, owner_type, owner_id, role,
                    artifact_id, state, created_at
                ) VALUES(?,?,?,?,?,'ACTIVE',?)
                """,
                (mint_v3_id("arf_"), project_id, role, artifact_id, wire_time(datetime.now(timezone.utc))),
            )
            connection.commit()
    finally:
        connection.close()


@dataclass(frozen=True)
class _ArtifactWrite:
    project_id: str
    payload: bytes
    role: str
    schema_fingerprint: str
    provenance: str


def _lookup_artifact(product: ProductRuntime, artifact_id: str) -> Mapping[str, Any] | None:
    connection = connect_catalog(product.database_path, read_only=True)
    try:
        return catalog_row(
            connection,
            "SELECT artifact_id,sha256,byte_size,semantic_role,schema_fingerprint,state FROM artifact WHERE artifact_id=?",
            (artifact_id,),
        )
    finally:
        connection.close()


def _verify_existing_artifact(
    product: ProductRuntime,
    write: _ArtifactWrite,
    artifact_id: str,
    existing: Mapping[str, Any],
) -> None:
    expected_sha = artifact_id.removeprefix("art_sha256_")
    metadata_matches = (
        existing["sha256"] == expected_sha
        and int(existing["byte_size"]) == len(write.payload)
        and existing["semantic_role"] == write.role
        and existing["schema_fingerprint"] == write.schema_fingerprint
        and existing["state"] == "PUBLISHED"
    )
    if not metadata_matches:
        raise ProductResearchError("published Artifact metadata conflicts with actual source bytes")
    if product.read_verified_bytes(artifact_id) != write.payload:
        raise ProductResearchError("published Artifact bytes do not match the source capture")
    _ensure_project_reference(product, write.project_id, artifact_id, write.role)


def _publish_artifact(product: ProductRuntime, write: _ArtifactWrite, artifact_id: str) -> None:
    published = product.execution._publish_artifact_batch(
        payloads=((write.provenance, write.payload, write.role, write.schema_fingerprint),),
        references=((write.project_id, write.role, 0),),
    )[0]
    if published.descriptor.artifact_id != artifact_id:
        raise ProductResearchError("Artifact publication changed the source identity")


def _ensure_artifact(
    product: ProductRuntime,
    write: _ArtifactWrite,
) -> str:
    expected_id = artifact_id_for_bytes(write.payload)
    existing = _lookup_artifact(product, expected_id)
    if existing is not None:
        _verify_existing_artifact(product, write, expected_id, existing)
        return expected_id
    _publish_artifact(product, write, expected_id)
    return expected_id


def _matching_provider_capabilities(adapter: Any) -> tuple[Any, ...]:
    return tuple(
        capability
        for capability in adapter.capabilities()
        if capability.connector_version_id == RESEARCH_CONNECTOR_VERSION_ID
        and capability.provider_id == RESEARCH_PROVIDER_ID
        and capability.capability_code == RESEARCH_DATASET
    )


def _validate_provider_parts(
    descriptor: Any,
    policy: FieldCapabilityPolicy,
    capabilities: tuple[Any, ...],
) -> None:
    if descriptor.provider_id != RESEARCH_PROVIDER_ID:
        raise ProviderCanonicalAdmissionUnavailable(
            "provider descriptor is outside the admitted Product Entry profile"
        )
    expected_policy_id = "art_sha256_" + hashlib.sha256(
        policy.artifact_bytes
    ).hexdigest()
    if policy.policy_artifact_id != expected_policy_id:
        raise ProviderPolicyMismatch("provider policy identity is not byte-derived")
    if len(capabilities) != 1 or capabilities[0].policy_artifact_id != policy.policy_artifact_id:
        raise ProviderCanonicalAdmissionUnavailable(
            "provider does not declare the exact admitted capability"
        )


def _admitted_provider_parts(adapter: Any) -> tuple[Any, FieldCapabilityPolicy]:
    descriptor = adapter.descriptor()
    policy = adapter.field_capability_policy()
    _validate_provider_parts(descriptor, policy, _matching_provider_capabilities(adapter))
    return descriptor, policy


def _provider_runtime_config() -> ProviderRuntimeConfig:
    return ProviderRuntimeConfig(
        provider_id=RESEARCH_PROVIDER_ID,
        connector_version_id=RESEARCH_CONNECTOR_VERSION_ID,
        runtime_profile_id=RESEARCH_PROFILE_ID,
    )


def _register_provider_admission(
    product: ProductRuntime,
    *,
    descriptor: Any,
    policy: FieldCapabilityPolicy,
) -> None:
    now = wire_time(datetime.now(timezone.utc))
    connection = connect_catalog(product.database_path)
    try:
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        uow.begin()
        registry = SQLiteRepositoryRegistry(uow)
        _register_provider_rows(registry, descriptor, policy, now)
        uow.commit()
    finally:
        if uow.active:
            uow.rollback()
        connection.close()


def _register_provider_rows(
    registry: SQLiteRepositoryRegistry,
    descriptor: Any,
    policy: FieldCapabilityPolicy,
    now: str,
) -> None:
    provider_row = _provider_descriptor_wire(descriptor)
    existing_provider = registry.data_truth.table("provider_descriptor").get(descriptor.provider_id)
    if existing_provider is not None:
        # Provider descriptors are append-only. Reusing the persisted creation
        # time makes repeated admission idempotent while the repository still
        # rejects any change to the canonical descriptor fields.
        provider_row["created_at"] = existing_provider["created_at"]
    registry.data_truth.register_provider(provider_row)
    _register_connector_rows(registry, policy, now)
    _register_connector_capability(registry, policy)
    _register_connector_admission(registry, policy, now)
    _register_connector_extension(registry, policy, now)


def _register_connector_extension(
    registry: SQLiteRepositoryRegistry,
    policy: FieldCapabilityPolicy,
    now: str,
) -> None:
    extension_row = {
        "connector_version_id": RESEARCH_CONNECTOR_VERSION_ID,
        "capability_code": RESEARCH_DATASET,
        "provider_id": RESEARCH_PROVIDER_ID,
        "logical_dataset": RESEARCH_DATASET,
        "frequency": RESEARCH_FREQUENCY,
        "revision_semantics": RevisionSemantics.UNKNOWN.value,
        "provenance_required": 1,
        "policy_artifact_id": policy.policy_artifact_id,
        "declared_at": now,
    }
    existing_extension = registry.data_truth.table("connector_data_capability").get(
        {"connector_version_id": RESEARCH_CONNECTOR_VERSION_ID, "capability_code": RESEARCH_DATASET}
    )
    if existing_extension is not None:
        extension_row["declared_at"] = existing_extension["declared_at"]
    registry.data_truth.declare_connector_capability_extension(extension_row)


def _connector_row(now: str) -> dict[str, Any]:
    return {
        "connector_id": RESEARCH_CONNECTOR_ID,
        "stable_name": "v3-product-research-akshare-eod",
        "publisher": "V3",
        "state": "REGISTERED",
        "created_at": now,
    }


def _connector_version_row(policy: FieldCapabilityPolicy, now: str) -> dict[str, Any]:
    return {
        "connector_version_id": RESEARCH_CONNECTOR_VERSION_ID,
        "connector_id": RESEARCH_CONNECTOR_ID,
        "semantic_version": "1.0.0",
        "bundle_artifact_id": policy.policy_artifact_id,
        "bundle_sha256": policy.policy_artifact_id.removeprefix("art_sha256_"),
        "entrypoint": "v3.product-research.akshare-eod",
        "declared_manifest_json": {
            "provider_id": RESEARCH_PROVIDER_ID,
            "logical_dataset": RESEARCH_DATASET,
            "profile_id": RESEARCH_PROFILE_ID,
        },
        "network_policy": "DECLARED_ALLOWLIST",
        "state": "ADMITTED",
        "created_at": now,
    }


def _register_connector_rows(
    registry: SQLiteRepositoryRegistry,
    policy: FieldCapabilityPolicy,
    now: str,
) -> None:
    connector_repository = registry.connector.table("connector")
    connector_row = _connector_row(now)
    existing_connector = connector_repository.get(RESEARCH_CONNECTOR_ID)
    if existing_connector is not None:
        connector_row["created_at"] = existing_connector["created_at"]
    connector_repository.add_new(connector_row, idempotent=True)

    version_repository = registry.connector.table("connector_version")
    version_row = _connector_version_row(policy, now)
    existing_version = version_repository.get(RESEARCH_CONNECTOR_VERSION_ID)
    if existing_version is not None:
        version_row["created_at"] = existing_version["created_at"]
    version_repository.add_new(version_row, idempotent=True)


def _connector_capability_row(policy: FieldCapabilityPolicy) -> dict[str, Any]:
    return {
        "connector_version_id": RESEARCH_CONNECTOR_VERSION_ID,
        "capability_code": RESEARCH_DATASET,
        "declared_state": "DECLARED",
        "admitted_truth_state": "DEMO",
        "limitation_json": {
            "profile_id": RESEARCH_PROFILE_ID,
            "available_time": "UNKNOWN",
            "revision": "UNKNOWN",
            "formal_market_state": "DEFERRED",
        },
        "evidence_artifact_id": policy.policy_artifact_id,
    }


def _register_connector_capability(
    registry: SQLiteRepositoryRegistry,
    policy: FieldCapabilityPolicy,
) -> None:
    registry.connector.table("connector_capability").add_new(
        _connector_capability_row(policy), idempotent=True
    )


def _connector_admission_row(policy: FieldCapabilityPolicy, now: str) -> dict[str, Any]:
    return {
        "connector_admission_id": mint_v3_id("cad_"),
        "connector_version_id": RESEARCH_CONNECTOR_VERSION_ID,
        "admission_profile_id": RESEARCH_ADMISSION_PROFILE_ID,
        "environment_profile_id": RESEARCH_ENVIRONMENT_PROFILE_ID,
        "task_id": None,
        "state": "PASSED",
        "report_artifact_id": policy.policy_artifact_id,
        "started_at": now,
        "finished_at": now,
    }


def _register_connector_admission(
    registry: SQLiteRepositoryRegistry,
    policy: FieldCapabilityPolicy,
    now: str,
) -> None:
    admission_repository = registry.connector.table("connector_admission")
    existing_admission = admission_repository.list_page(
        {
            "connector_version_id": RESEARCH_CONNECTOR_VERSION_ID,
            "admission_profile_id": RESEARCH_ADMISSION_PROFILE_ID,
            "environment_profile_id": RESEARCH_ENVIRONMENT_PROFILE_ID,
        },
        limit=2,
    )
    if existing_admission:
        return
    admission_repository.add_new(_connector_admission_row(policy, now))


def _ensure_provider_admission(
    product: ProductRuntime,
    *,
    project_id: str,
    adapter: Any,
) -> tuple[ProviderAdapterRegistry, ProviderRuntimeConfig]:
    descriptor, policy = _admitted_provider_parts(adapter)
    _ensure_artifact(
        product,
        _ArtifactWrite(
            project_id=project_id,
            payload=policy.artifact_bytes,
            role=FIELD_CAPABILITY_POLICY_ROLE,
            schema_fingerprint=FIELD_CAPABILITY_POLICY_SCHEMA_FINGERPRINT,
            provenance="prv_product_research_capability_policy",
        ),
    )
    _register_provider_admission(product, descriptor=descriptor, policy=policy)
    config = _provider_runtime_config()
    return ProviderAdapterRegistry({RESEARCH_PROVIDER_ID: lambda _config: adapter}), config


def _raw_capture_wire_fields(submission: Any, acquired_at: datetime) -> dict[str, Any]:
    return {
        "raw_capture_id": submission.envelope.raw_capture_id,
        "connector_version_id": submission.envelope.connector_version_id,
        "provider_dataset": submission.envelope.provider_dataset,
        "request_fingerprint": str(submission.source_metadata.get("request_fingerprint", "")),
        "effective_range_start": _wire_optional_time(submission.envelope.effective_range_start),
        "effective_range_end": _wire_optional_time(submission.envelope.effective_range_end),
        "available_time": None,
        "provider_revision_id": submission.envelope.provider_revision_id,
        "captured_at": wire_time(acquired_at),
        "ingested_at": wire_time(submission.envelope.ingested_at),
        "artifact_id": submission.envelope.artifact_id,
        "content_hash": submission.envelope.content_hash,
        "state": "CAPTURED",
    }


def _raw_capture_row(submission: Any, metadata_json: Mapping[str, Any]) -> dict[str, Any]:
    acquired_at = submission.source_metadata.get("acquired_at")
    if not isinstance(acquired_at, datetime):
        raise ProductResearchError("provider capture omitted acquisition time evidence")
    raw_row = _raw_capture_wire_fields(submission, acquired_at)
    if len(raw_row["request_fingerprint"]) != 64:
        raise ProductResearchError("provider capture request fingerprint is unavailable")
    raw_row["source_metadata_json"] = metadata_json
    return raw_row


def _wire_optional_time(moment: datetime | None) -> str | None:
    return None if moment is None else wire_time(moment)


def _persist_raw_capture_row(
    product: ProductRuntime,
    submission: Any,
    raw_row: Mapping[str, Any],
) -> None:
    connection = connect_catalog(product.database_path)
    try:
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        uow.begin()
        registry = SQLiteRepositoryRegistry(uow)
        existing = registry.data_truth.table("raw_capture").get(
            submission.envelope.raw_capture_id
        )
        _ensure_raw_capture_state(registry, submission, raw_row, existing)
        uow.commit()
    finally:
        if uow.active:
            uow.rollback()
        connection.close()


def _ensure_raw_capture_state(
    registry: SQLiteRepositoryRegistry,
    submission: Any,
    raw_row: Mapping[str, Any],
    existing: Mapping[str, Any] | None,
) -> None:
    if existing is None:
        registry.data_truth.submit_raw_capture(
            {**raw_row, "provider_id": submission.envelope.provider_id, "provenance_complete": 0}
        )
        registry.data_truth.accept_raw_capture(submission.envelope.raw_capture_id)
        return
    _validate_raw_capture_identity(existing, raw_row)
    if existing["state"] == "CAPTURED":
        registry.data_truth.accept_raw_capture(submission.envelope.raw_capture_id)
    elif existing["state"] != "ACCEPTED":
        raise ProductResearchError("persisted Raw Capture is not accepted")


def _validate_raw_capture_identity(
    existing: Mapping[str, Any],
    raw_row: Mapping[str, Any],
) -> None:
    identity_fields = ("connector_version_id", "provider_dataset", "artifact_id", "content_hash")
    if any(existing.get(name) != raw_row[name] for name in identity_fields):
        raise ProductResearchError("persisted Raw Capture identity conflicts with actual bytes")


def _validated_raw_payload(submission: Any) -> tuple[Mapping[str, Any], bytes]:
    raw_payload = submission.source_metadata.get("raw_payload")
    if not isinstance(raw_payload, Mapping):
        raise ProductResearchError("provider submission did not carry canonical raw payload bytes")
    raw_bytes = canonical_json_bytes(raw_payload)
    expected_sha = hashlib.sha256(raw_bytes).hexdigest()
    if expected_sha != submission.envelope.content_hash:
        raise ProductResearchError("provider raw payload hash does not match its capture envelope")
    if submission.envelope.artifact_id != "art_sha256_" + expected_sha:
        raise ProductResearchError("provider raw payload Artifact identity is not canonical")
    return raw_payload, raw_bytes


def _raw_capture_artifact_write(
    project_id: str,
    submission: Any,
    raw_payload: Mapping[str, Any],
    raw_bytes: bytes,
) -> _ArtifactWrite:
    return _ArtifactWrite(
        project_id=project_id,
        payload=raw_bytes,
        role=RESEARCH_RAW_CAPTURE_ROLE,
        schema_fingerprint=canonical_sha256({"schema": raw_payload.get("schema_id")}),
        provenance="prv_product_research_raw_capture_" + submission.envelope.raw_capture_id,
    )


def _persist_raw_capture(
    product: ProductRuntime,
    *,
    project_id: str,
    submission: Any,
) -> str:
    raw_payload, raw_bytes = _validated_raw_payload(submission)
    _ensure_artifact(product, _raw_capture_artifact_write(project_id, submission, raw_payload, raw_bytes))
    metadata_json = json.loads(canonical_json_bytes(submission.source_metadata).decode("utf-8"))
    raw_row = _raw_capture_row(submission, metadata_json)
    _persist_raw_capture_row(product, submission, raw_row)
    return submission.envelope.raw_capture_id


def _board(exchange: str) -> Board:
    return {
        "SSE": Board.SSE_MAIN,
        "SZSE": Board.SZSE_MAIN,
        "BSE": Board.BSE,
    }[exchange]


@dataclass(frozen=True)
class _SnapshotArtifacts:
    calendar_artifact_id: str
    partition_artifact_id: str
    calendar_sha: str
    session_dates: tuple[date, ...]
    first_time: datetime
    last_time: datetime


@dataclass(frozen=True)
class _SnapshotRequest:
    project_id: str
    snapshot: ResearchDataSnapshot
    raw_capture_id: str
    raw_artifact_id: str


@dataclass(frozen=True)
class _SnapshotWrite:
    snapshot: ResearchDataSnapshot
    raw_capture_id: str
    raw_artifact_id: str
    artifacts: _SnapshotArtifacts
    now: str


def _snapshot_time_range(snapshot: ResearchDataSnapshot) -> tuple[datetime, datetime]:
    return (
        min(record.event_time for record in snapshot.records),
        max(record.event_time for record in snapshot.records),
    )


def _calendar_artifact(product: ProductRuntime, request: _SnapshotRequest, session_dates: tuple[date, ...]) -> str:
    payload = canonical_json_bytes(
        {
            "profile_id": RESEARCH_PROFILE_ID,
            "snapshot_id": request.snapshot.snapshot_id,
            "session_dates": [session_date.isoformat() for session_date in session_dates],
            "semantics": "observed provider dates; not formal trading-calendar truth",
        }
    )
    return _ensure_artifact(
        product,
        _ArtifactWrite(
            project_id=request.project_id,
            payload=payload,
            role=RESEARCH_CALENDAR_ROLE,
            schema_fingerprint=canonical_sha256({"schema": "research-calendar-v1"}),
            provenance="prv_product_research_calendar_" + request.snapshot.snapshot_id,
        ),
    )


def _partition_artifact(product: ProductRuntime, request: _SnapshotRequest) -> str:
    payload = canonical_json_bytes(
        {
            "snapshot_id": request.snapshot.snapshot_id,
            "raw_capture_id": request.raw_capture_id,
            "records": len(request.snapshot.records),
        }
    )
    return _ensure_artifact(
        product,
        _ArtifactWrite(
            project_id=request.project_id,
            payload=payload,
            role=RESEARCH_PARTITION_ROLE,
            schema_fingerprint=canonical_sha256({"schema": "research-partition-v1"}),
            provenance="prv_product_research_partition_" + request.snapshot.snapshot_id,
        ),
    )


def _build_snapshot_artifacts(
    product: ProductRuntime,
    request: _SnapshotRequest,
) -> _SnapshotArtifacts:
    if not request.snapshot.records:
        raise ProductResearchError("provider source produced no usable records")
    session_dates = tuple(sorted({record.session_date for record in request.snapshot.records}))
    first_time, last_time = _snapshot_time_range(request.snapshot)
    calendar_artifact_id = _calendar_artifact(product, request, session_dates)
    partition_artifact_id = _partition_artifact(product, request)
    return _SnapshotArtifacts(
        calendar_artifact_id=calendar_artifact_id,
        partition_artifact_id=partition_artifact_id,
        calendar_sha=calendar_artifact_id.removeprefix("art_sha256_"),
        session_dates=session_dates,
        first_time=first_time,
        last_time=last_time,
    )


def _snapshot_header_row(write: _SnapshotWrite) -> dict[str, Any]:
    return {
        "snapshot_id": write.snapshot.snapshot_id,
        "connector_version_id": RESEARCH_CONNECTOR_VERSION_ID,
        "parent_snapshot_id": None,
        "manifest_artifact_id": write.raw_artifact_id,
        "content_hash": write.snapshot.records[0].content_hash,
        "normalization_spec_version": write.snapshot.normalization_version,
        "truth_profile_id": RESEARCH_PROFILE_ID,
        "min_effective_time": wire_time(write.artifacts.first_time),
        "max_effective_time": wire_time(write.artifacts.last_time),
        "max_available_time": None,
        "state": "CANDIDATE",
        "created_at": write.now,
        "validated_at": None,
        "published_at": None,
    }


def _add_snapshot_header(registry: SQLiteRepositoryRegistry, write: _SnapshotWrite) -> None:
    registry.snapshot.table("data_snapshot").add_new(
        _snapshot_header_row(write),
        idempotent=True,
    )
    registry.data_truth.link_snapshot_source(
        {
            "snapshot_id": write.snapshot.snapshot_id,
            "raw_capture_id": write.raw_capture_id,
            "logical_dataset": RESEARCH_DATASET,
            "linked_at": write.now,
        }
    )


def _calendar_version_row(write: _SnapshotWrite, calendar_version_id: str) -> dict[str, Any]:
    return {
        "calendar_version_id": calendar_version_id,
        "market": "CN_A_SHARE",
        "timezone": "Asia/Shanghai",
        "source_artifact_id": write.artifacts.calendar_artifact_id,
        "content_hash": write.artifacts.calendar_sha,
        "state": "PUBLISHED",
        "published_at": write.now,
    }


def _trading_session_id(write: _SnapshotWrite, session_date: date) -> str:
    return "trs_sha256_" + canonical_sha256(
        {"calendar": write.artifacts.calendar_sha, "session_date": session_date.isoformat()}
    )


def _trading_session_row(
    write: _SnapshotWrite,
    calendar_version_id: str,
    ordinal: int,
    session_date: date,
) -> dict[str, Any]:
    open_time = datetime.combine(session_date, time(9, 30), tzinfo=_SHANGHAI)
    close_time = datetime.combine(session_date, time(15, 0), tzinfo=_SHANGHAI)
    return {
        "trading_session_id": _trading_session_id(write, session_date),
        "calendar_version_id": calendar_version_id,
        "session_date": session_date.isoformat(),
        "is_trading_day": 1,
        "session_ordinal": ordinal,
        "open_time": wire_time(open_time),
        "close_time": wire_time(close_time),
        "available_time": write.now,
        "evidence_artifact_id": write.artifacts.calendar_artifact_id,
    }


def _add_snapshot_calendar(registry: SQLiteRepositoryRegistry, write: _SnapshotWrite) -> None:
    calendar_version_id = "tcv_sha256_" + write.artifacts.calendar_sha
    registry.data_truth.table("trading_calendar_version").add_new(
        _calendar_version_row(write, calendar_version_id),
        idempotent=True,
    )
    for ordinal, session_date in enumerate(write.artifacts.session_dates):
        registry.data_truth.table("trading_session").add_new(
            _trading_session_row(write, calendar_version_id, ordinal, session_date),
            idempotent=True,
        )
    registry.data_truth.link_snapshot_calendar(
        {
            "snapshot_id": write.snapshot.snapshot_id,
            "calendar_version_id": calendar_version_id,
            "linked_at": write.now,
        }
    )


def _snapshot_partition_row(write: _SnapshotWrite) -> dict[str, Any]:
    return {
        "snapshot_id": write.snapshot.snapshot_id,
        "logical_dataset": RESEARCH_DATASET,
        "partition_key": write.snapshot.records[0].symbol,
        "parquet_artifact_id": write.artifacts.partition_artifact_id,
        "row_count": len(write.snapshot.records),
        "schema_fingerprint": canonical_sha256({"schema": "research-eod-v1"}),
        "min_effective_time": wire_time(write.artifacts.first_time),
        "max_effective_time": wire_time(write.artifacts.last_time),
        "max_available_time": None,
    }


def _add_snapshot_partition(uow: SQLiteUnitOfWork, write: _SnapshotWrite) -> None:
    SQLiteTableRepository(uow, "snapshot_partition").add_new(
        _snapshot_partition_row(write),
        idempotent=True,
    )


def _snapshot_validation_profile(now: str) -> dict[str, Any]:
    return {
        "validation_profile_id": "svp_product_research_free_data_v1",
        "admission_state": "PRE_ALPHA",
        "description": "Research-only provider snapshot; missing PIT/revision semantics remain deferred",
        "created_at": now,
    }


def _snapshot_validation_binding(snapshot: ResearchDataSnapshot, now: str) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "validation_profile_id": "svp_product_research_free_data_v1",
        "bound_at": now,
    }


def _add_snapshot_validation(connection, write: _SnapshotWrite) -> None:
    _insert_idempotent(
        connection,
        "snapshot_validation_profile",
        "validation_profile_id",
        _snapshot_validation_profile(write.now),
    )
    _insert_idempotent(
        connection,
        "snapshot_validation_binding",
        "snapshot_id",
        _snapshot_validation_binding(write.snapshot, write.now),
    )


def _publish_snapshot(connection, write: _SnapshotWrite) -> None:
    state = connection.execute(
        "SELECT state FROM data_snapshot WHERE snapshot_id=?", (write.snapshot.snapshot_id,)
    ).fetchone()[0]
    if state == "CANDIDATE":
        connection.execute(
            "UPDATE data_snapshot SET state='PUBLISHED',published_at=? WHERE snapshot_id=? AND state='CANDIDATE'",
            (write.now, write.snapshot.snapshot_id),
        )
    elif state != "PUBLISHED":
        raise ProductResearchError("research snapshot is not in a publishable state")


def _persist_snapshot_catalog(product: ProductRuntime, write: _SnapshotWrite) -> None:
    connection = connect_catalog(product.database_path)
    try:
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        uow.begin()
        registry = SQLiteRepositoryRegistry(uow)
        _add_snapshot_header(registry, write)
        _add_snapshot_calendar(registry, write)
        _add_snapshot_partition(uow, write)
        _add_snapshot_validation(connection, write)
        _publish_snapshot(connection, write)
        uow.commit()
    finally:
        if uow.active:
            uow.rollback()
        connection.close()


def _ensure_snapshot(product: ProductRuntime, request: _SnapshotRequest) -> str:
    artifacts = _build_snapshot_artifacts(product, request)
    _persist_snapshot_catalog(
        product,
        _SnapshotWrite(
            snapshot=request.snapshot,
            raw_capture_id=request.raw_capture_id,
            raw_artifact_id=request.raw_artifact_id,
            artifacts=artifacts,
            now=wire_time(datetime.now(timezone.utc)),
        ),
    )
    return artifacts.calendar_artifact_id


def _score_port() -> PortSpec:
    from v3_backend.domain.strategies import MissingSemantics

    return PortSpec(
        value_type=PortValueType.SCORE_MAP,
        cardinality=PortCardinality.CROSS_SECTION,
        time_basis="BOUND_DECISION_TIME",
        universe_basis="BOUND_UNIVERSE_MEMBERSHIP",
        missing_semantics=MissingSemantics.EXPLICIT,
    )


def _strategy_input_node() -> StrategyNode:
    return StrategyNode(
        "input.scores", "v3.strategy.input.bound_scores", "1.0.0",
        {"artifact": BindingInputRef("scores")}, {}, {"profile_id": RESEARCH_STRATEGY_PROFILE_ID},
    )


def _strategy_gate_node() -> StrategyNode:
    return StrategyNode(
        "gate.nonnegative", "v3.strategy.condition.minimum", "1.0.0",
        {"scores": NodeOutputRef("input.scores", "scores")},
        {"threshold": "0", "inclusive": True}, {},
    )


def _strategy_rank_node() -> StrategyNode:
    return StrategyNode(
        "rank.primary", "v3.strategy.rank.score", "1.0.0",
        {"scores": NodeOutputRef("input.scores", "scores"), "eligible": NodeOutputRef("gate.nonnegative", "eligible")},
        {"descending": True, "missing_policy": "EXCLUDE"}, {},
    )


def _strategy_selection_node() -> StrategyNode:
    return StrategyNode(
        "select.top1", "v3.strategy.select.top_n", "1.0.0",
        {"ranked": NodeOutputRef("rank.primary", "ranked")}, {"count": 1}, {},
    )


def _strategy_signal_node() -> StrategyNode:
    return StrategyNode(
        "output.signal", "v3.strategy.output.signal", "1.0.0",
        {"scores": NodeOutputRef("input.scores", "scores")}, {"signal_kind": "SCORE"}, {},
    )


def _strategy_output_nodes() -> tuple[StrategyNode, StrategyNode]:
    selection = StrategyNode(
        "output.selection", "v3.strategy.output.selection", "1.0.0",
        {"selection": NodeOutputRef("select.top1", "selection")}, {}, {},
    )
    intent = StrategyNode(
        "output.intent", "v3.strategy.output.portfolio_intent", "1.0.0",
        {"scores": NodeOutputRef("input.scores", "scores"), "selection": NodeOutputRef("select.top1", "selection")},
        {"gross_exposure": "1", "exposure_mode": "ABSOLUTE_DESIRED_EXPOSURE", "cash_policy": "RESIDUAL", "rebalance_intent": "AT_BOUND_DECISION_TIME"},
        {},
    )
    return selection, intent


def _research_strategy_definition() -> StrategyIr:
    selection, intent = _strategy_output_nodes()
    nodes = (_strategy_input_node(), _strategy_gate_node(), _strategy_rank_node(), _strategy_selection_node(), _strategy_signal_node(), selection, intent)
    ir = StrategyIr(
        required_bindings=(BindingSlot("scores", "PREDICTION_SIGNAL", _score_port()),),
        nodes=nodes,
        outputs={
            "signal": NodeOutputRef("output.signal", "artifact"),
            "selection": NodeOutputRef("output.selection", "artifact"),
            "portfolio_intent": NodeOutputRef("output.intent", "artifact"),
        },
        projection_metadata={"profile_id": RESEARCH_STRATEGY_PROFILE_ID},
    )
    return StrategyCompiler(default_component_registry()).compile(ir)


def _research_rule_profile(first_date: date) -> AshareTradingRuleProfileVersion:
    return AshareTradingRuleProfileVersion.create(
        profile_name="RESEARCH_FREE_DATA_CN_A_SHARE_RULES_V1",
        effective_from=first_date,
        effective_to=None,
        settlement_days=1,
        board_rules=(
            BoardTradingRule(Board.SSE_MAIN, 100, 100, "0.10", "0.10"),
            BoardTradingRule(Board.SSE_STAR, 200, 1, "0.20", "0.20"),
            BoardTradingRule(Board.SZSE_MAIN, 100, 100, "0.10", "0.10"),
            BoardTradingRule(Board.SZSE_CHINEXT, 100, 100, "0.20", "0.20"),
            BoardTradingRule(Board.BSE, 100, 1, "0.30", "0.30"),
        ),
        truth_admission=PRE_ALPHA_CEILING,
    )


def _research_timing_profile(first_date: date) -> ExecutionTimingProfileVersion:
    return ExecutionTimingProfileVersion.create(
        profile_name="RESEARCH_FREE_DATA_RAW_OPEN_V1",
        effective_from=first_date,
        effective_to=None,
        market_timezone="Asia/Shanghai",
        raw_open_eligibility_cutoff_local_time="09:15:00",
        raw_open_execution_local_time="09:25:00",
        truth_admission=PRE_ALPHA_CEILING,
    )


@dataclass(frozen=True)
class _StrategyBuildContext:
    product: ProductRuntime
    project_id: str
    snapshot: ResearchDataSnapshot
    raw_artifact_id: str
    calendar_artifact_id: str
    decision_time: datetime
    records: tuple[Any, ...] = ()
    instrument_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _StrategyUniverse:
    definition: dict[str, Any]
    definition_sha: str
    membership_artifact_id: str
    universe_version_id: str
    snapshot_ref: ExactSnapshotReference
    universe_ref: ExactUniverseReference
    calendar_ref: ExactCalendarReference


@dataclass(frozen=True)
class _StrategyFeatures:
    factor_definition: FactorDefinitionVersion
    materialization: FeatureMaterialization
    evaluation: FactorEvaluation
    dataset: DatasetVersion
    label: LabelSpec
    split: SplitSpec
    dataset_profile_artifact_id: str


@dataclass(frozen=True)
class _DatasetBuild:
    feature_set: FeatureSetVersion
    evaluation: FactorEvaluation
    label: LabelSpec
    split: SplitSpec
    binding: DatasetBinding
    profile_artifact_id: str


@dataclass(frozen=True)
class _StrategyFeatureBuild:
    source_parts: _SourceCloseParts
    dataset: DatasetVersion
    label: LabelSpec
    split: SplitSpec
    profile_artifact_id: str


@dataclass(frozen=True)
class _StrategyOwner:
    definition: StrategyIr
    binding: StrategyEvaluationBindingVersion
    signal_id: str
    score_sha: str
    score_artifact_id: str
    profile_artifact_id: str


@dataclass(frozen=True)
class _StrategyOwnerBuild:
    definition: StrategyIr
    binding: StrategyEvaluationBindingVersion
    signal_id: str
    score_sha: str
    score_artifact_id: str
    profile_artifact_id: str


@dataclass(frozen=True)
class _StrategyBindingBuild:
    context: _StrategyBuildContext
    universe: _StrategyUniverse
    features: _StrategyFeatures
    definition: StrategyIr
    owner_reference: CanonicalOwnerArtifactReference


def _validated_strategy_context(context: _StrategyBuildContext) -> _StrategyBuildContext:
    records = tuple(
        sorted(context.snapshot.records, key=lambda record: (record.session_date, record.instrument_id))
    )
    if any(record.close is None or record.open is None for record in records):
        raise ProductResearchError(
            "Research Free Data requires actual open/close bytes for every observed row"
        )
    instrument_ids = tuple(sorted({record.instrument_id for record in records}))
    if len(instrument_ids) != 1:
        raise ProductResearchError(
            "the bounded Product Entry profile admits exactly one provider symbol"
        )
    return replace(context, records=records, instrument_ids=instrument_ids)


def _universe_definition(context: _StrategyBuildContext) -> dict[str, Any]:
    return {
        "profile_id": RESEARCH_PROFILE_ID,
        "snapshot_id": context.snapshot.snapshot_id,
        "instrument_ids": list(context.instrument_ids),
        "role": "OBSERVED_PROVIDER_SYMBOLS_ONLY",
    }


def _universe_references(
    context: _StrategyBuildContext,
    definition_sha: str,
    membership_artifact_id: str,
    universe_version_id: str,
) -> tuple[ExactSnapshotReference, ExactUniverseReference, ExactCalendarReference]:
    truth = PRE_ALPHA_CEILING
    calendar_sha = context.calendar_artifact_id.removeprefix("art_sha256_")
    return (
        ExactSnapshotReference(context.snapshot.snapshot_id, context.records[0].content_hash, truth),
        ExactUniverseReference(
            universe_version_id,
            definition_sha,
            membership_artifact_id,
            membership_artifact_id.removeprefix("art_sha256_"),
            context.instrument_ids,
            truth,
        ),
        ExactCalendarReference("tcv_sha256_" + calendar_sha, calendar_sha, "Asia/Shanghai", truth),
    )


def _universe_membership_artifact(
    context: _StrategyBuildContext,
    universe_definition: Mapping[str, Any],
) -> str:
    return _ensure_artifact(
        context.product,
        _ArtifactWrite(
            project_id=context.project_id,
            payload=canonical_json_bytes(universe_definition),
            role=RESEARCH_MEMBERSHIP_ROLE,
            schema_fingerprint=canonical_sha256({"schema": "research-membership-v1"}),
            provenance="prv_product_research_membership_" + context.snapshot.snapshot_id,
        ),
    )


def _build_strategy_universe(context: _StrategyBuildContext) -> _StrategyUniverse:
    universe_definition = _universe_definition(context)
    definition_sha = canonical_sha256(universe_definition)
    membership_artifact_id = _universe_membership_artifact(context, universe_definition)
    universe_version_id = "unv_sha256_" + canonical_sha256(
        {"snapshot_id": context.snapshot.snapshot_id, "membership_artifact_id": membership_artifact_id}
    )
    snapshot_ref, universe_ref, calendar_ref = _universe_references(
        context, definition_sha, membership_artifact_id, universe_version_id
    )
    return _StrategyUniverse(
        definition=universe_definition,
        definition_sha=definition_sha,
        membership_artifact_id=membership_artifact_id,
        universe_version_id=universe_version_id,
        snapshot_ref=snapshot_ref,
        universe_ref=universe_ref,
        calendar_ref=calendar_ref,
    )


@dataclass(frozen=True)
class _SourceCloseParts:
    definition: FactorDefinitionVersion
    materialization: FeatureMaterialization
    evaluation: FactorEvaluation
    context: FactorEvaluationContext


def _source_close_definition() -> FactorDefinitionVersion:
    return FactorDefinitionVersion.create(
        "research_source_close", FeatureNode("close", "eod.close/1.0.0"), default_operator_registry()
    )


def _source_close_context(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
) -> FactorEvaluationContext:
    evaluator_version = DeterministicReferenceEvaluator(default_operator_registry()).evaluator_version
    return FactorEvaluationContext(
        snapshot_id=context.snapshot.snapshot_id,
        universe_version_id=universe.universe_version_id,
        snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
            context.snapshot.snapshot_id, PRE_ALPHA_CEILING
        ),
        universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
            universe.universe_version_id, PRE_ALPHA_CEILING
        ),
        knowledge_cutoff=context.decision_time,
        calendar_version_id=universe.calendar_ref.calendar_version_id,
        schema_version_id="schema.research-eod/v1",
        environment_fingerprint="v3.product-research/1.0.0:" + sys.version.split()[0],
        evaluator_version=evaluator_version,
    )


def _source_close_evaluation(
    definition: FactorDefinitionVersion,
    context: _StrategyBuildContext,
) -> Any:
    return DeterministicReferenceEvaluator(default_operator_registry()).evaluate(
        definition, {"close": (float(context.records[0].close),)}
    )


def _publish_feature_output(context: _StrategyBuildContext, factor_result: Any) -> str:
    feature_output_artifact_id = _ensure_artifact(
        context.product,
        _ArtifactWrite(
            project_id=context.project_id,
            payload=canonical_json_bytes({"values": list(factor_result.values)}),
            role=RESEARCH_FEATURE_OUTPUT_ROLE,
            schema_fingerprint=canonical_sha256({"schema": "factor-values-v1"}),
            provenance="prv_product_research_feature_output_" + context.snapshot.snapshot_id,
        ),
    )
    return feature_output_artifact_id


def _source_close_outputs(
    context: _StrategyBuildContext,
    factor_definition: FactorDefinitionVersion,
    factor_context: FactorEvaluationContext,
    factor_result: Any,
) -> tuple[FeatureMaterialization, FactorEvaluation]:
    feature_output_artifact_id = _publish_feature_output(context, factor_result)
    materialization = FeatureMaterialization.create(
        factor_definition, factor_result, factor_context, context.raw_artifact_id, PRE_ALPHA_CEILING
    )
    if materialization.output_artifact_id != feature_output_artifact_id:
        raise ProductResearchError("internal source projection Artifact identity drifted")
    evaluation = FactorEvaluation.create(
        factor_definition, materialization, context.raw_artifact_id, PRE_ALPHA_CEILING
    )
    return materialization, evaluation


def _evaluate_source_close(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
) -> _SourceCloseParts:
    factor_definition = _source_close_definition()
    factor_context = _source_close_context(context, universe)
    factor_result = _source_close_evaluation(factor_definition, context)
    materialization, evaluation = _source_close_outputs(
        context, factor_definition, factor_context, factor_result
    )
    return _SourceCloseParts(factor_definition, materialization, evaluation, factor_context)


def _dataset_binding(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
    factor_context: FactorEvaluationContext,
) -> DatasetBinding:
    return DatasetBinding(
        snapshot_id=context.snapshot.snapshot_id,
        universe_version_id=universe.universe_version_id,
        snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
            context.snapshot.snapshot_id, PRE_ALPHA_CEILING
        ),
        universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
            universe.universe_version_id, PRE_ALPHA_CEILING
        ),
        knowledge_cutoff=context.decision_time,
        calendar_version_id=universe.calendar_ref.calendar_version_id,
        schema_version_id=factor_context.schema_version_id,
        environment_fingerprint=factor_context.environment_fingerprint,
        evaluator_version=factor_context.evaluator_version,
    )


def _dataset_profile_artifact(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
    feature_set: FeatureSetVersion,
) -> str:
    payload = _dataset_profile_payload(context, universe, feature_set)
    return _ensure_artifact(
        context.product,
        _ArtifactWrite(
            project_id=context.project_id,
            payload=payload,
            role=RESEARCH_DATASET_PROFILE_ROLE,
            schema_fingerprint=canonical_sha256({"schema": "research-dataset-profile-v1"}),
            provenance="prv_product_research_dataset_profile_" + context.snapshot.snapshot_id,
        ),
    )


def _dataset_profile_payload(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
    feature_set: FeatureSetVersion,
) -> bytes:
    return canonical_json_bytes(
        {
            "profile_id": RESEARCH_PROFILE_ID,
            "snapshot_id": context.snapshot.snapshot_id,
            "universe_version_id": universe.universe_version_id,
            "feature_set_version_id": feature_set.feature_set_version_id,
        }
    )


def _dataset_label_and_split() -> tuple[LabelSpec, SplitSpec]:
    label = LabelSpec.create("next_return", "close", 1, 0)
    split = SplitSpec.create(
        train_start=0,
        train_end=0,
        validation_start=2,
        validation_end=2,
        test_start=4,
        test_end=4,
        purge_observations=0,
        embargo_observations=0,
    )
    return label, split


def _dataset_version(build: _DatasetBuild) -> DatasetVersion:
    return DatasetVersion.create(
        feature_set=build.feature_set,
        evaluations=(build.evaluation,),
        label_spec=build.label,
        split_spec=build.split,
        binding=build.binding,
        dataset_artifact_id=build.profile_artifact_id,
        provenance_artifact_id=build.profile_artifact_id,
        proposed_state=PRE_ALPHA_CEILING,
    )


def _strategy_dataset_build(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
    source_parts: _SourceCloseParts,
) -> tuple[DatasetVersion, LabelSpec, SplitSpec, str]:
    feature_set = FeatureSetVersion.create((source_parts.evaluation,), context.raw_artifact_id)
    binding = _dataset_binding(context, universe, source_parts.context)
    profile_artifact_id = _dataset_profile_artifact(context, universe, feature_set)
    label, split = _dataset_label_and_split()
    dataset = _dataset_version(
        _DatasetBuild(feature_set, source_parts.evaluation, label, split, binding, profile_artifact_id)
    )
    return dataset, label, split, profile_artifact_id


def _build_strategy_features(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
) -> _StrategyFeatures:
    source_parts = _evaluate_source_close(context, universe)
    dataset, label, split, profile_artifact_id = _strategy_dataset_build(
        context, universe, source_parts
    )
    return _strategy_features_result(
        _StrategyFeatureBuild(
            source_parts,
            dataset,
            label,
            split,
            profile_artifact_id,
        )
    )


def _strategy_features_result(build: _StrategyFeatureBuild) -> _StrategyFeatures:
    return _StrategyFeatures(
        factor_definition=build.source_parts.definition,
        materialization=build.source_parts.materialization,
        evaluation=build.source_parts.evaluation,
        dataset=build.dataset,
        label=build.label,
        split=build.split,
        dataset_profile_artifact_id=build.profile_artifact_id,
    )


def _strategy_binding(build: _StrategyBindingBuild) -> StrategyEvaluationBindingVersion:
    context = build.context
    return StrategyEvaluationBindingVersion.create(
        definition=build.definition,
        dataset=build.features.dataset,
        factor_evaluations=(build.features.evaluation,),
        feature_materializations=(build.features.materialization,),
        snapshot=build.universe.snapshot_ref,
        universe=build.universe.universe_ref,
        period=EvaluationPeriod(
            context.decision_time - timedelta(hours=1), context.decision_time
        ),
        knowledge_cutoff=context.decision_time,
        calendar=build.universe.calendar_ref,
        compiler_version=build.definition.compiler_version,
        runtime_profile_id=build.definition.runtime_profile_id,
        environment_fingerprint=build.features.dataset.binding.environment_fingerprint,
        input_references=(BoundInputReference.from_canonical_owner("scores", build.owner_reference),),
        canonical_owner_references=(build.owner_reference,),
    )


def _publish_score_owner(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
    definition: StrategyIr,
) -> tuple[str, str]:
    score_payload = _score_payload(context, universe, definition)
    score_sha = hashlib.sha256(score_payload).hexdigest()
    return _publish_score_artifact(context, score_payload, score_sha)


def _score_payload(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
    definition: StrategyIr,
) -> bytes:
    return encode_score_payload_for_universe(
        definition=definition,
        universe=universe.universe_ref,
        binding_key="scores",
        decision_time=context.decision_time,
        values=(str(context.records[0].close),),
    )


def _publish_score_artifact(
    context: _StrategyBuildContext,
    score_payload: bytes,
    score_sha: str,
) -> tuple[str, str]:
    score_artifact_id = _ensure_artifact(
        context.product,
        _ArtifactWrite(
            project_id=context.project_id,
            payload=score_payload,
            role=SCORE_PAYLOAD_ROLE,
            schema_fingerprint=SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
            provenance="prv_product_research_score_payload_" + context.snapshot.snapshot_id,
        ),
    )
    return score_artifact_id, score_sha


def _signal_id(features: _StrategyFeatures, score_artifact_id: str) -> str:
    return "sgv_sha256_" + canonical_sha256(
        {
            "profile_id": RESEARCH_STRATEGY_PROFILE_ID,
            "dataset_version_id": features.dataset.dataset_version_id,
            "score_artifact_id": score_artifact_id,
        }
    )


def _signal_owner_reference(
    signal_id: str,
    score_sha: str,
    score_artifact_id: str,
) -> CanonicalOwnerArtifactReference:
    return CanonicalOwnerArtifactReference(
        artifact_type="PREDICTION_SIGNAL",
        owner_namespace="PREDICTION_SIGNAL_VERSION",
        owner_id=signal_id,
        owner_version=score_sha,
        payload_role=SCORE_PAYLOAD_ROLE,
        artifact_id=score_artifact_id,
        content_sha256=score_sha,
    )


def _strategy_profile_payload(
    context: _StrategyBuildContext,
    definition: StrategyIr,
    binding: StrategyEvaluationBindingVersion,
    score_artifact_id: str,
) -> bytes:
    return canonical_json_bytes(
        {
            "profile_id": RESEARCH_STRATEGY_PROFILE_ID,
            "definition": definition.to_wire(),
            "binding": binding.to_wire(),
            "source_snapshot_id": context.snapshot.snapshot_id,
            "score_artifact_id": score_artifact_id,
            "truth_admission": PRE_ALPHA_CEILING.to_wire(),
        }
    )


def _strategy_profile_artifact(
    context: _StrategyBuildContext,
    definition: StrategyIr,
    binding: StrategyEvaluationBindingVersion,
    score_artifact_id: str,
) -> str:
    profile_artifact_id = _ensure_artifact(
        context.product,
        _ArtifactWrite(
            project_id=context.project_id,
            payload=_strategy_profile_payload(context, definition, binding, score_artifact_id),
            role=RESEARCH_STRATEGY_PROFILE_ROLE,
            schema_fingerprint=canonical_sha256({"schema": "research-strategy-profile-v1"}),
            provenance="prv_product_research_strategy_profile_" + context.snapshot.snapshot_id,
        ),
    )
    return profile_artifact_id


def _build_strategy_owner(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
    features: _StrategyFeatures,
) -> _StrategyOwner:
    definition = _research_strategy_definition()
    score_artifact_id, score_sha = _publish_score_owner(context, universe, definition)
    signal_id = _signal_id(features, score_artifact_id)
    owner_reference = _signal_owner_reference(signal_id, score_sha, score_artifact_id)
    binding = _strategy_binding(
        _StrategyBindingBuild(context, universe, features, definition, owner_reference)
    )
    profile_artifact_id = _strategy_profile_artifact(context, definition, binding, score_artifact_id)
    return _strategy_owner_result(
        _StrategyOwnerBuild(
            definition, binding, signal_id, score_sha, score_artifact_id, profile_artifact_id
        )
    )


def _strategy_owner_result(build: _StrategyOwnerBuild) -> _StrategyOwner:
    return _StrategyOwner(
        definition=build.definition,
        binding=build.binding,
        signal_id=build.signal_id,
        score_sha=build.score_sha,
        score_artifact_id=build.score_artifact_id,
        profile_artifact_id=build.profile_artifact_id,
    )


@dataclass(frozen=True)
class _StrategyPersistence:
    context: _StrategyBuildContext
    universe: _StrategyUniverse
    features: _StrategyFeatures
    owner: _StrategyOwner


def _universe_definition_row(build: _StrategyPersistence, now: str) -> dict[str, Any]:
    universe = build.universe
    return {
        "universe_definition_id": "und_sha256_" + universe.definition_sha,
        "project_id": build.context.project_id,
        "constructor_kind": "WATCHLIST",
        "definition_json": universe.definition,
        "canonical_hash": universe.definition_sha,
        "state": "PUBLISHED",
        "created_at": now,
    }


def _universe_version_row(build: _StrategyPersistence, now: str) -> dict[str, Any]:
    context, universe = build.context, build.universe
    return {
        "universe_version_id": universe.universe_version_id,
        "universe_definition_id": "und_sha256_" + universe.definition_sha,
        "snapshot_id": context.snapshot.snapshot_id,
        "industry_taxonomy_version_id": None,
        "knowledge_cutoff": wire_time(context.decision_time),
        "membership_artifact_id": universe.membership_artifact_id,
        "audit_artifact_id": universe.membership_artifact_id,
        "content_hash": canonical_sha256(universe.definition),
        "state": "PUBLISHED",
        "published_at": now,
    }


def _persist_universe_rows(
    registry: SQLiteRepositoryRegistry,
    build: _StrategyPersistence,
    now: str,
) -> None:
    registry.universe.table("universe_definition").add_new(
        _universe_definition_row(build, now), idempotent=True
    )
    registry.universe.table("universe_version").add_new(
        _universe_version_row(build, now), idempotent=True
    )


def _dataset_spec_id(dataset: DatasetVersion) -> str:
    return "dss_sha256_" + canonical_sha256(dataset.binding.to_wire())


def _dataset_spec_wire(features: _StrategyFeatures) -> dict[str, Any]:
    return {
        "profile_id": RESEARCH_PROFILE_ID,
        "label": features.label.to_wire(),
        "split": features.split.to_wire(),
    }


def _dataset_spec_row(
    build: _StrategyPersistence,
    dataset_spec_id: str,
    now: str,
) -> dict[str, Any]:
    features = build.features
    return {
        "dataset_spec_id": dataset_spec_id,
        "project_id": build.context.project_id,
        "spec_json": _dataset_spec_wire(features),
        "canonical_hash": dataset_spec_id.removeprefix("dss_sha256_"),
        "split_kind": "CHRONOLOGICAL",
        "purge_duration": None,
        "embargo_duration": None,
        "preprocessing_fit_scope": "TRAIN_ONLY",
        "state": "VALIDATED",
        "validation_artifact_id": features.dataset_profile_artifact_id,
        "created_at": now,
    }


def _dataset_version_row(build: _StrategyPersistence, dataset_spec_id: str, now: str) -> dict[str, Any]:
    context, universe, features = build.context, build.universe, build.features
    return {
        "dataset_version_id": features.dataset.dataset_version_id,
        "dataset_spec_id": dataset_spec_id,
        "snapshot_id": context.snapshot.snapshot_id,
        "universe_version_id": universe.universe_version_id,
        "manifest_artifact_id": features.dataset_profile_artifact_id,
        "leakage_audit_artifact_id": features.dataset_profile_artifact_id,
        "content_hash": features.dataset.dataset_version_id.removeprefix("dsv_sha256_"),
        "state": "PUBLISHED",
        "published_at": now,
    }


def _persist_dataset_rows(
    registry: SQLiteRepositoryRegistry,
    build: _StrategyPersistence,
    now: str,
) -> None:
    dataset_spec_id = _dataset_spec_id(build.features.dataset)
    registry.dataset.table("dataset_spec").add_new(
        _dataset_spec_row(build, dataset_spec_id, now),
        idempotent=True,
    )
    registry.dataset.table("dataset_version").add_new(
        _dataset_version_row(build, dataset_spec_id, now),
        idempotent=True,
    )


def _model_ids(build: _StrategyPersistence) -> tuple[str, str]:
    model_spec_id = "mds_sha256_" + canonical_sha256(
        {"profile_id": RESEARCH_STRATEGY_PROFILE_ID, "project_id": build.context.project_id}
    )
    model_version_id = "mdv_sha256_" + canonical_sha256(
        {"model_spec_id": model_spec_id, "dataset_version_id": build.features.dataset.dataset_version_id}
    )
    return model_spec_id, model_version_id


def _model_spec_row(
    build: _StrategyPersistence,
    model_spec_id: str,
    now: str,
) -> dict[str, Any]:
    return {
        "model_spec_id": model_spec_id,
        "project_id": build.context.project_id,
        "model_family": "LINEAR",
        "spec_json": {"profile_id": RESEARCH_STRATEGY_PROFILE_ID, "projection": "normalized_eod.close"},
        "environment_profile_id": RESEARCH_ENVIRONMENT_PROFILE_ID,
        "canonical_hash": model_spec_id.removeprefix("mds_sha256_"),
        "state": "VALIDATED",
        "created_at": now,
    }


def _model_version_row(
    build: _StrategyPersistence,
    model_spec_id: str,
    model_version_id: str,
    now: str,
) -> dict[str, Any]:
    owner = build.owner
    return {
        "model_version_id": model_version_id,
        "model_spec_id": model_spec_id,
        "dataset_version_id": build.features.dataset.dataset_version_id,
        "run_id": "rpresearch_sha256_" + canonical_sha256({"profile": owner.profile_artifact_id}),
        "model_artifact_id": owner.profile_artifact_id,
        "metrics_artifact_id": owner.profile_artifact_id,
        "model_card_artifact_id": None,
        "content_hash": owner.profile_artifact_id.removeprefix("art_sha256_"),
        "safe_format_id": "canonical-json-v1",
        "state": "PUBLISHED",
        "published_at": now,
    }


def _prediction_signal_row(
    build: _StrategyPersistence,
    model_version_id: str,
    now: str,
) -> dict[str, Any]:
    owner = build.owner
    return {
        "prediction_signal_version_id": owner.signal_id,
        "model_version_id": model_version_id,
        "dataset_version_id": build.features.dataset.dataset_version_id,
        "signal_artifact_id": owner.score_artifact_id,
        "content_hash": owner.score_sha,
        "state": "PUBLISHED",
        "published_at": now,
    }


def _persist_model_rows(
    registry: SQLiteRepositoryRegistry,
    build: _StrategyPersistence,
    now: str,
) -> None:
    model_spec_id, model_version_id = _model_ids(build)
    registry.model.table("model_spec").add_new(
        _model_spec_row(build, model_spec_id, now), idempotent=True
    )
    registry.model.table("model_version").add_new(
        _model_version_row(build, model_spec_id, model_version_id, now),
        idempotent=True,
    )
    registry.model.table("prediction_signal_version").add_new(
        _prediction_signal_row(build, model_version_id, now),
        idempotent=True,
    )


def _persist_strategy_records(build: _StrategyPersistence) -> None:
    now = wire_time(datetime.now(timezone.utc))
    connection = connect_catalog(build.context.product.database_path)
    try:
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        uow.begin()
        registry = SQLiteRepositoryRegistry(uow)
        _persist_universe_rows(registry, build, now)
        _persist_dataset_rows(registry, build, now)
        _persist_model_rows(registry, build, now)
        uow.commit()
    finally:
        if uow.active:
            uow.rollback()
        connection.close()


def _build_strategy_request(
    context: _StrategyBuildContext,
    owner: _StrategyOwner,
) -> FormalStrategyEvaluationRequest:
    return FormalStrategyEvaluationRequest(
        definition=owner.definition,
        binding=owner.binding,
        inputs=(
            FormalStrategyInputRequest(
                binding_key="scores",
                owner_namespace="PREDICTION_SIGNAL_VERSION",
                owner_id=owner.signal_id,
                owner_version=owner.score_sha,
                payload_role=SCORE_PAYLOAD_ROLE,
                decision_time=context.decision_time,
                max_bytes=64 * 1024,
            ),
        ),
    )


def _build_strategy_observations(
    records: tuple[Any, ...],
) -> tuple[ResearchSessionObservation, ...]:
    bars_by_date: dict[date, list[ResearchBarObservation]] = defaultdict(list)
    for record in records:
        bars_by_date[record.session_date].append(_research_bar(record))
    return tuple(
        ResearchSessionObservation(
            session_date=session_date,
            is_open=True,
            bars=tuple(sorted(bars, key=lambda bar: bar.instrument_id)),
        )
        for session_date, bars in sorted(bars_by_date.items())
    )


def _research_bar(record: Any) -> ResearchBarObservation:
    return ResearchBarObservation(
        instrument_id=record.instrument_id,
        board=_board(record.exchange),
        raw_open=format(record.open, "f"),
        raw_close=format(record.close, "f"),
    )


def _strategy_reference_ids(
    context: _StrategyBuildContext,
    universe: _StrategyUniverse,
    features: _StrategyFeatures,
    owner: _StrategyOwner,
) -> dict[str, str]:
    return {
        "universe_version_id": universe.universe_version_id,
        "membership_artifact_id": universe.membership_artifact_id,
        "score_artifact_id": owner.score_artifact_id,
        "strategy_profile_artifact_id": owner.profile_artifact_id,
        "dataset_version_id": features.dataset.dataset_version_id,
        "signal_id": owner.signal_id,
        "calendar_artifact_id": context.calendar_artifact_id,
    }


def _ensure_strategy_records(
    context: _StrategyBuildContext,
) -> tuple[FormalStrategyEvaluationRequest, tuple[ResearchSessionObservation, ...], dict[str, str]]:
    validated_context = _validated_strategy_context(context)
    universe = _build_strategy_universe(validated_context)
    features = _build_strategy_features(validated_context, universe)
    owner = _build_strategy_owner(validated_context, universe, features)
    _persist_strategy_records(_StrategyPersistence(validated_context, universe, features, owner))
    return (
        _build_strategy_request(validated_context, owner),
        _build_strategy_observations(validated_context.records),
        _strategy_reference_ids(validated_context, universe, features, owner),
    )


@dataclass(frozen=True)
class _PipelinePublication:
    artifact_id: str
    payload: bytes
    provenance_entity_id: str
    owner_id: str


def _register_pipeline_result_artifact(
    product: ProductRuntime,
    publication: _PipelinePublication,
) -> None:
    """Register the CoreResearchPipeline publication in the product catalog.

    CoreResearchPipelineService owns the byte publication, while Product Runtime
    owns the durable Project/Run/Result references.  The two stores are joined
    only after the exact bytes and content identity are re-verified here.
    """
    published_at = datetime.now(timezone.utc)
    descriptor = _pipeline_result_descriptor(publication, published_at)
    _persist_pipeline_result_reference(product, descriptor, publication.owner_id, published_at)


def _persist_pipeline_result_reference(
    product: ProductRuntime,
    descriptor: ArtifactDescriptor,
    owner_id: str,
    published_at: datetime,
) -> None:
    connection = connect_catalog(product.database_path)
    try:
        uow = SQLiteUnitOfWork(
            connection, TransactionMode.PUBLISH, publish_callbacks=_NoopPublishCallbacks()
        )
        uow.begin()
        _publish_pipeline_result_reference(uow, descriptor, owner_id, published_at)
        uow.commit()
    finally:
        if uow.active:
            uow.rollback()
        connection.close()


def _pipeline_result_descriptor(
    publication: _PipelinePublication,
    published_at: datetime,
) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        artifact_id=publication.artifact_id,
        sha256=publication.artifact_id.removeprefix("art_sha256_"),
        byte_size=len(publication.payload),
        media_type="application/json",
        role=RESEARCH_BACKTEST_RESULT_ROLE,
        created_at=published_at,
        published_at=published_at,
        provenance_entity_id=publication.provenance_entity_id,
        safe_format_id="canonical-json-v1",
        schema_fingerprint=RESEARCH_BACKTEST_RESULT_SCHEMA_FINGERPRINT,
        semantic_fingerprint=RESEARCH_PROFILE_ID,
    )


def _publish_pipeline_result_reference(
    uow: SQLiteUnitOfWork,
    descriptor: ArtifactDescriptor,
    owner_id: str,
    published_at: datetime,
) -> None:
    SQLiteArtifactPublicationPort(uow).publish(
        ArtifactPublication(
            descriptor,
            (
                ArtifactReference(
                    reference_id=mint_v3_id("arf_"),
                    owner_id=owner_id,
                    artifact_id=descriptor.artifact_id,
                    role=RUN_RESULT_REFERENCE_ROLE,
                    created_at=published_at,
                ),
            ),
        )
    )


@dataclass(frozen=True)
class _ResearchResultArtifacts:
    pipeline_run_id: str
    result_artifact_id: str
    result_artifact_sha256: str
    lineage_artifact_id: str
    lineage_hash: str


@dataclass(frozen=True)
class _LineageWrite:
    run_id: str
    pipeline_result: Any
    result_artifact_id: str
    source: Mapping[str, Any]
    source_refs: Mapping[str, Any]


def _verified_pipeline_artifact(
    product: ProductRuntime,
    pipeline_result: Any,
) -> tuple[str, bytes]:
    if pipeline_result.result_artifact_id is None or pipeline_result.run_id is None:
        raise ProductResearchError("CoreResearchPipelineService returned no canonical result Artifact")
    result_artifact_id = str(pipeline_result.result_artifact_id)
    result_bytes = product.read_verified_bytes(result_artifact_id)
    if hashlib.sha256(result_bytes).hexdigest() != result_artifact_id.removeprefix("art_sha256_"):
        raise ProductResearchError("CoreResearchPipeline result Artifact failed byte/hash verification")
    return result_artifact_id, result_bytes


def _lineage_payload(write: _LineageWrite) -> bytes:
    pipeline_result = write.pipeline_result
    lineage_payload = canonical_json_bytes(
        {
            "schema_version": RESEARCH_LINEAGE_SCHEMA_VERSION,
            "product_operation_id": PRODUCT_RESEARCH_OPERATION,
            "product_task_run_id": write.run_id,
            "core_pipeline_run_id": str(pipeline_result.run_id),
            "core_pipeline_run_receipt_id": str(pipeline_result.run_receipt_id),
            "result_artifact_id": write.result_artifact_id,
            "result_artifact_sha256": write.result_artifact_id.removeprefix("art_sha256_"),
            "source": dict(write.source),
            "source_refs": dict(write.source_refs),
            "research_profile_id": RESEARCH_PROFILE_ID,
            "research_classification": ["RESEARCH_ONLY", "APPROXIMATE"],
            "truth_admission": PRE_ALPHA_CEILING.to_wire(),
        }
    )
    return lineage_payload


def _publish_research_lineage(product: ProductRuntime, write: _LineageWrite) -> str:
    lineage_payload = _lineage_payload(write)
    lineage_artifact = product.execution._publish_artifact_batch(
        payloads=(
            (
                "prv_product_research_lineage_" + write.run_id,
                lineage_payload,
                RESEARCH_LINEAGE_ROLE,
                RESEARCH_LINEAGE_SCHEMA_VERSION,
            ),
        ),
        references=((write.run_id, RUN_LEDGER_MANIFEST_REFERENCE_ROLE, 0),),
    )[0]
    return lineage_artifact.descriptor.artifact_id


@dataclass(frozen=True)
class _ResearchResultWrite:
    project_id: str
    run_id: str
    artifacts: _ResearchResultArtifacts


def _research_result_row(result_id: str, write: _ResearchResultWrite, now: str) -> dict[str, Any]:
    return {
        "result_id": result_id,
        "project_id": write.project_id,
        "backtest_run_id": write.run_id,
        "ledger_manifest_artifact_id": write.artifacts.lineage_artifact_id,
        "reconciliation_artifact_id": None,
        "state": "PENDING_RECONCILIATION",
        "invalid_reason_code": None,
        "lineage_hash": write.artifacts.lineage_hash,
        "created_at": now,
    }


def _persist_research_result(product: ProductRuntime, write: _ResearchResultWrite) -> str:
    result_id = mint_v3_id("res_")
    now = wire_time(datetime.now(timezone.utc))
    connection = connect_catalog(product.database_path)
    try:
        uow = SQLiteUnitOfWork(
            connection, TransactionMode.PUBLISH, publish_callbacks=_NoopPublishCallbacks()
        )
        uow.begin()
        SQLiteRepositoryRegistry(uow).result.publish_result(
            _research_result_row(result_id, write, now)
        )
        uow.commit()
    finally:
        if uow.active:
            uow.rollback()
        connection.close()
    return result_id


@dataclass(frozen=True)
class _ResearchResultRequest:
    project_id: str
    run_id: str
    pipeline_result: Any
    source: Mapping[str, Any]
    source_refs: Mapping[str, Any]


def _research_result_artifacts(
    request: _ResearchResultRequest,
    result_artifact_id: str,
    lineage_artifact_id: str,
) -> _ResearchResultArtifacts:
    return _ResearchResultArtifacts(
        pipeline_run_id=str(request.pipeline_result.run_id),
        result_artifact_id=result_artifact_id,
        result_artifact_sha256=result_artifact_id.removeprefix("art_sha256_"),
        lineage_artifact_id=lineage_artifact_id,
        lineage_hash=canonical_sha256(
            {
                "product_run_id": request.run_id,
                "core_pipeline_run_id": request.pipeline_result.run_id,
                "result_artifact_id": result_artifact_id,
                "lineage_artifact_id": lineage_artifact_id,
            }
        ),
    )


def _research_result_wire(
    result_id: str,
    artifacts: _ResearchResultArtifacts,
    source_refs: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "result_id": result_id,
        "result_artifact_id": artifacts.result_artifact_id,
        "result_artifact_sha256": artifacts.result_artifact_sha256,
        "lineage_artifact_id": artifacts.lineage_artifact_id,
        "pipeline_run_id": artifacts.pipeline_run_id,
        "source_refs": dict(source_refs),
        "maturity": RESEARCH_MATURITY,
        "research_classification": ["RESEARCH_ONLY", "APPROXIMATE"],
    }


def _publish_research_result_artifacts(
    product: ProductRuntime,
    request: _ResearchResultRequest,
    result_artifact_id: str,
    result_bytes: bytes,
) -> str:
    _register_pipeline_result_artifact(
        product,
        _PipelinePublication(
            artifact_id=result_artifact_id,
            payload=result_bytes,
            provenance_entity_id=str(request.pipeline_result.run_receipt_id),
            owner_id=request.run_id,
        ),
    )
    return _publish_research_lineage(product, _lineage_write(request, result_artifact_id))


def _lineage_write(
    request: _ResearchResultRequest,
    result_artifact_id: str,
) -> _LineageWrite:
    return _LineageWrite(
        request.run_id,
        request.pipeline_result,
        result_artifact_id,
        request.source,
        request.source_refs,
    )


def _research_result(
    product: ProductRuntime,
    request: _ResearchResultRequest,
) -> dict[str, Any]:
    result_artifact_id, result_bytes = _verified_pipeline_artifact(
        product, request.pipeline_result
    )
    lineage_artifact_id = _publish_research_result_artifacts(
        product, request, result_artifact_id, result_bytes
    )
    result_artifacts = _research_result_artifacts(
        request, result_artifact_id, lineage_artifact_id
    )
    result_id = _persist_research_result(
        product, _ResearchResultWrite(request.project_id, request.run_id, result_artifacts)
    )
    return _research_result_wire(result_id, result_artifacts, request.source_refs)


@dataclass(frozen=True)
class _PreparedResearchRequest:
    project_id: str
    project_context_revision_id: str
    source_intent: dict[str, str]
    semantic: dict[str, Any]
    request_hash: str
    scope: str
    execution_deadline_at: str | None


@dataclass(frozen=True)
class _ResearchCapture:
    strategy_request: FormalStrategyEvaluationRequest
    observations: tuple[ResearchSessionObservation, ...]
    source_refs: dict[str, Any]
    raw_capture_id: str
    raw_artifact_id: str
    snapshot: ResearchDataSnapshot
    decision_time: datetime


@dataclass(frozen=True)
class _SourceSnapshotCapture:
    raw_capture_id: str
    raw_artifact_id: str
    snapshot: ResearchDataSnapshot
    calendar_artifact_id: str
    decision_time: datetime


@dataclass(frozen=True)
class _ResearchExecution:
    request: _PreparedResearchRequest
    capture: _ResearchCapture
    pipeline_request: ResearchPipelineRequest
    policy_owner: SQLitePortfolioRiskPolicyOwner
    risk_repository: SQLiteRiskApplicationRepository
    context_wire: dict[str, Any]


@dataclass(frozen=True)
class _ExecutionComponents:
    pipeline_request: ResearchPipelineRequest
    policy_owner: SQLitePortfolioRiskPolicyOwner
    risk_repository: SQLiteRiskApplicationRepository


@dataclass(frozen=True)
class _PipelineBuild:
    request: _PreparedResearchRequest
    capture: _ResearchCapture
    runtime_identity: RuntimeIdentity
    risk_policy_set_version_id: str
    published_at: datetime


@dataclass(frozen=True)
class _TaskHandles:
    task: Any
    run: Any
    attempt: Any


def _construction_spec(runtime_identity: RuntimeIdentity) -> PortfolioConstructionSpecVersion:
    return PortfolioConstructionSpecVersion.create(
        method=ConstructionMethod.EQUAL_WEIGHT_SELECTED,
        method_version="1.0.0",
        target_cash_weight="0.1",
        max_instrument_weight="0.9",
        runtime_identity=runtime_identity,
    )


def _pipeline_identity_parameters(build: _PipelineBuild) -> dict[str, Any]:
    return {
        "project_id": build.request.project_id,
        "project_context_revision_id": build.request.project_context_revision_id,
        "strategy_request": build.capture.strategy_request,
        "construction_spec": _construction_spec(build.runtime_identity),
        "risk_policy_set_version_id": build.risk_policy_set_version_id,
        "runtime_identity": build.runtime_identity,
    }


def _pipeline_timing_parameters(build: _PipelineBuild) -> dict[str, Any]:
    decision_time = build.capture.decision_time
    return {
        "base_currency": "CNY",
        "as_of": decision_time,
        "decision_time": decision_time,
        "rebalance_time": decision_time + timedelta(hours=1),
        "valid_until": decision_time + timedelta(days=1),
        "published_at": build.published_at,
    }


def _pipeline_data_parameters(build: _PipelineBuild) -> dict[str, Any]:
    first_date = build.capture.observations[0].session_date
    return {
        "assumption_profile": ResearchExecutionAssumptionProfile.free_data_v1(),
        "observations": build.capture.observations,
        "initial_cash": "100000",
        "initial_holdings": (),
        "rule_profile": _research_rule_profile(first_date),
        "cost_policy": cn_a_share_2023_08_28_cost_policy(
            commission_rate="0.0003", minimum_commission="5"
        ),
        "execution_timing_profile": _research_timing_profile(first_date),
    }


def _build_pipeline_request(build: _PipelineBuild) -> ResearchPipelineRequest:
    request_parameters = {
        **_pipeline_identity_parameters(build),
        **_pipeline_timing_parameters(build),
        **_pipeline_data_parameters(build),
    }
    return ResearchPipelineRequest(**request_parameters)


def _research_runtime_identity() -> RuntimeIdentity:
    return RuntimeIdentity(
        code_version=PRODUCT_CODE_VERSION,
        runtime_profile_id="v3.product-research/1.0.0",
        environment_fingerprint="cpython-" + sys.version.split()[0],
    )


def _execution_policy_inputs(
    request: _PreparedResearchRequest,
    policy_owner: SQLitePortfolioRiskPolicyOwner,
) -> tuple[RuntimeIdentity, str, datetime]:
    runtime_identity = _research_runtime_identity()
    published_at = datetime.now(timezone.utc)
    risk_policy_set_version_id = _author_research_risk_policy(
        request, policy_owner, runtime_identity, published_at
    )
    return runtime_identity, risk_policy_set_version_id, published_at


def _author_research_risk_policy(
    request: _PreparedResearchRequest,
    policy_owner: SQLitePortfolioRiskPolicyOwner,
    runtime_identity: RuntimeIdentity,
    published_at: datetime,
) -> str:
    policy_result = CanonicalRiskPolicyAuthoringService(policy_owner).author_and_publish(
        project_id=request.project_id,
        project_context_revision_id=request.project_context_revision_id,
        definitions=(MaxSingleNamePolicyInput("0.9"),),
        runtime_identity=runtime_identity,
        published_at=published_at,
    )
    return policy_result.policy_set.risk_policy_set_version_id


def _require_pipeline_success(pipeline_result: Any) -> None:
    if not pipeline_result.succeeded:
        raise ProductResearchError(
            f"CoreResearchPipelineService failed at {pipeline_result.failed_stage}: {pipeline_result.error_message}"
        )


def _research_result_request(
    execution: _ResearchExecution,
    run_id: str,
    pipeline_result: Any,
) -> _ResearchResultRequest:
    return _ResearchResultRequest(
        project_id=execution.request.project_id,
        run_id=run_id,
        pipeline_result=pipeline_result,
        source=execution.request.source_intent,
        source_refs=execution.capture.source_refs,
    )


def _provider_capture_request(request: _PreparedResearchRequest) -> dict[str, Any]:
    return {
        "symbol": request.source_intent["symbol"],
        "period": "daily",
        "start_date": request.source_intent["start_date"],
        "end_date": request.source_intent["end_date"],
        "adjust": "",
        "timeout": None,
    }


def _persist_source_snapshot(
    product: ProductRuntime,
    request: _PreparedResearchRequest,
    submission: Any,
) -> _SourceSnapshotCapture:
    raw_capture_id = _persist_raw_capture(
        product, project_id=request.project_id, submission=submission
    )
    snapshot = normalize_a_share_eod(submission, proposed_state=PRE_ALPHA_CEILING)
    raw_artifact_id = submission.envelope.artifact_id
    calendar_artifact_id = _ensure_snapshot(
        product,
        _SnapshotRequest(request.project_id, snapshot, raw_capture_id, raw_artifact_id),
    )
    decision_time = min(record.event_time for record in snapshot.records)
    return _SourceSnapshotCapture(
        raw_capture_id, raw_artifact_id, snapshot, calendar_artifact_id, decision_time
    )


def _build_research_capture(
    product: ProductRuntime,
    request: _PreparedResearchRequest,
    source_capture: _SourceSnapshotCapture,
) -> _ResearchCapture:
    strategy_context = _strategy_context_for_capture(product, request, source_capture)
    strategy_request, observations, strategy_refs = _ensure_strategy_records(strategy_context)
    return _ResearchCapture(
        strategy_request=strategy_request,
        observations=observations,
        source_refs=_capture_source_refs(source_capture, strategy_refs),
        raw_capture_id=source_capture.raw_capture_id,
        raw_artifact_id=source_capture.raw_artifact_id,
        snapshot=source_capture.snapshot,
        decision_time=source_capture.decision_time,
    )


def _strategy_context_for_capture(
    product: ProductRuntime,
    request: _PreparedResearchRequest,
    source_capture: _SourceSnapshotCapture,
) -> _StrategyBuildContext:
    return _StrategyBuildContext(
        product=product,
        project_id=request.project_id,
        snapshot=source_capture.snapshot,
        raw_artifact_id=source_capture.raw_artifact_id,
        calendar_artifact_id=source_capture.calendar_artifact_id,
        decision_time=source_capture.decision_time,
    )


def _capture_source_refs(
    source_capture: _SourceSnapshotCapture,
    strategy_refs: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "provider_id": RESEARCH_PROVIDER_ID,
        "connector_version_id": RESEARCH_CONNECTOR_VERSION_ID,
        "raw_capture_id": source_capture.raw_capture_id,
        "raw_artifact_id": source_capture.raw_artifact_id,
        "snapshot_id": source_capture.snapshot.snapshot_id,
        **strategy_refs,
    }


def _research_context_wire(
    request: _PreparedResearchRequest,
    capture: _ResearchCapture,
) -> dict[str, Any]:
    return {
        "schema_version": RESEARCH_CONTEXT_SCHEMA_VERSION,
        "context_kind": RESEARCH_CONTEXT_KIND,
        "project_id": request.project_id,
        "project_context_revision_id": request.project_context_revision_id,
        "research_profile_id": RESEARCH_PROFILE_ID,
        "strategy_profile_id": RESEARCH_STRATEGY_PROFILE_ID,
        "source_intent": request.source_intent,
        "source_refs": capture.source_refs,
        "core_pipeline_run_id": None,
        "core_pipeline_run_receipt_id": None,
        "assumption_profile_id": RESEARCH_PROFILE_ID,
        "research_classification": ["RESEARCH_ONLY", "APPROXIMATE"],
        "truth_admission": PRE_ALPHA_CEILING.to_wire(),
    }


def _queued_research_context_wire(request: _PreparedResearchRequest) -> dict[str, Any]:
    """Durable acceptance intent; actual source refs exist only after child capture."""
    return {
        "schema_version": RESEARCH_CONTEXT_SCHEMA_VERSION,
        "context_kind": RESEARCH_CONTEXT_KIND,
        "project_id": request.project_id,
        "project_context_revision_id": request.project_context_revision_id,
        "research_profile_id": RESEARCH_PROFILE_ID,
        "strategy_profile_id": RESEARCH_STRATEGY_PROFILE_ID,
        "source_intent": request.source_intent,
        "source_refs": {},
        "core_pipeline_run_id": None,
        "core_pipeline_run_receipt_id": None,
        "assumption_profile_id": RESEARCH_PROFILE_ID,
        "research_classification": ["RESEARCH_ONLY", "APPROXIMATE"],
        "truth_admission": PRE_ALPHA_CEILING.to_wire(),
        "execution_state": "QUEUED_BEFORE_PROVIDER_CAPTURE",
    }


def _research_semantic(
    intent: ProductResearchSubmission,
    source_intent: dict[str, str],
) -> dict[str, Any]:
    return {
        "project_id": intent.project_id,
        "project_context_revision_id": intent.project_context_revision_id,
        "research_profile_id": intent.research_profile_id,
        "strategy_profile_id": intent.strategy_profile_id,
        "source": source_intent,
    }


class ProductResearchService:
    """One project-bound Product Entry research operation."""

    def __init__(
        self,
        product: ProductRuntime,
        *,
        provider_factory: ResearchProviderFactory | None = None,
    ) -> None:
        self.product = product
        if provider_factory is None:
            self._provider_factory: ResearchProviderFactory = lambda config: AkshareAShareEodAdapter(
                connector_version_id=config.connector_version_id
            )
        else:
            self._provider_factory = provider_factory

    def _validate_intent(self, intent: ProductResearchSubmission) -> dict[str, str]:
        self.product.require_project_context_ownership(
            intent.project_id, intent.project_context_revision_id
        )
        if intent.research_profile_id != RESEARCH_PROFILE_ID:
            raise InvalidArgumentError("only RESEARCH_FREE_DATA_V1 is admitted")
        if intent.strategy_profile_id != RESEARCH_STRATEGY_PROFILE_ID:
            raise InvalidArgumentError("only the bounded Product Runtime strategy profile is admitted")
        if not isinstance(intent.idempotency_key, str) or not intent.idempotency_key.strip():
            raise InvalidArgumentError("idempotency_key is required")
        return _require_exact_source(intent.source)

    def _prepare_request(self, intent: ProductResearchSubmission) -> _PreparedResearchRequest:
        source_intent = self._validate_intent(intent)
        semantic = _research_semantic(intent, source_intent)
        request_hash = _canonical_request_hash(PRODUCT_RESEARCH_OPERATION, semantic)
        scope = self.product.idempotency.scope_key(
            PRODUCT_RESEARCH_OPERATION, intent.project_id, intent.idempotency_key
        )
        return _PreparedResearchRequest(
            project_id=intent.project_id,
            project_context_revision_id=intent.project_context_revision_id,
            source_intent=source_intent,
            semantic=semantic,
            request_hash=request_hash,
            scope=scope,
            execution_deadline_at=intent.execution_deadline_at,
        )

    def _replay_if_known(self, request: _PreparedResearchRequest) -> dict[str, Any] | None:
        existing = self.product.idempotency.lookup(
            self.product, request.scope, request.request_hash
        )
        if existing is None:
            return None
        task_id = str(existing["task_id"])
        return _research_accept_outcome(
            task_id,
            str(existing["run_id"]),
            operation_receipt_id=self.product.execution.operation_receipt_id_for_task(task_id),
        )

    def _capture_provider_submission(self, request: _PreparedResearchRequest) -> Any:
        adapter = self._provider_factory(_provider_runtime_config())
        registry, config = _ensure_provider_admission(
            self.product, project_id=request.project_id, adapter=adapter
        )
        binding: ProviderExecutionBinding = registry.bind(
            config,
            _PersistedAdmissionResolver(self.product),
            _PersistedPolicyResolver(self.product),
        )
        try:
            return binding.capture(_provider_capture_request(request))
        except ProviderAcquisitionError as error:
            raise CapabilityUnavailableError(
                "PROVIDER_ACQUISITION_UNAVAILABLE: free A-share source acquisition failed; retry later",
                details={
                    "reason_code": "PROVIDER_ACQUISITION_UNAVAILABLE",
                    "provider_id": RESEARCH_PROVIDER_ID,
                    "connector_version_id": RESEARCH_CONNECTOR_VERSION_ID,
                    "fallback_used": False,
                    "canonical_chain_created": False,
                },
            ) from error

    def _capture_source(self, request: _PreparedResearchRequest) -> _ResearchCapture:
        submission = self._capture_provider_submission(request)
        source_capture = _persist_source_snapshot(self.product, request, submission)
        return _build_research_capture(self.product, request, source_capture)

    def _execution_components(
        self,
        request: _PreparedResearchRequest,
        capture: _ResearchCapture,
    ) -> _ExecutionComponents:
        policy_owner = SQLitePortfolioRiskPolicyOwner(
            self.product.database_path, self.product.artifact_root
        )
        risk_repository = SQLiteRiskApplicationRepository(
            self.product.database_path, self.product.artifact_root
        )
        runtime_identity, risk_policy_set_version_id, published_at = _execution_policy_inputs(
            request, policy_owner
        )
        pipeline_request = _build_pipeline_request(
            _PipelineBuild(
                request, capture, runtime_identity, risk_policy_set_version_id, published_at
            )
        )
        return _ExecutionComponents(pipeline_request, policy_owner, risk_repository)

    def _build_execution(
        self,
        request: _PreparedResearchRequest,
        capture: _ResearchCapture,
    ) -> _ResearchExecution:
        components = self._execution_components(request, capture)
        return _ResearchExecution(
            request=request,
            capture=capture,
            pipeline_request=components.pipeline_request,
            policy_owner=components.policy_owner,
            risk_repository=components.risk_repository,
            context_wire=_research_context_wire(request, capture),
        )

    def _accept_task(
        self,
        execution: _ResearchExecution,
    ) -> tuple[Any, Any, Any]:
        context_artifact_id = self.product.execution._persist_context_artifact(
            execution.context_wire,
            provenance="prv_product_research_context_" + execution.request.request_hash,
            deadline_at=execution.request.execution_deadline_at,
        )
        return self.product.execution._create_task(
            operation_id=PRODUCT_RESEARCH_OPERATION,
            project_id=execution.request.project_id,
            project_context_revision_id=execution.request.project_context_revision_id,
            normalized_input_hash=canonical_sha256(execution.request.semantic),
            context_artifact_id=context_artifact_id,
            canonical_input={
                "semantic_request": dict(execution.request.semantic),
                "request_hash": execution.request.request_hash,
                "scope": execution.request.scope,
            },
            idempotency=(
                execution.request.scope,
                execution.request.request_hash,
                _accept_outcome_json,
            ),
            execution_deadline_at=execution.request.execution_deadline_at,
        )

    def _accept_request(
        self,
        request: _PreparedResearchRequest,
        *,
        inline_worker: bool = False,
    ) -> _TaskHandles:
        context_artifact_id = self.product.execution._persist_context_artifact(
            _queued_research_context_wire(request),
            provenance="prv_product_research_intent_" + request.request_hash,
            deadline_at=request.execution_deadline_at,
        )
        return _TaskHandles(
            *self.product.execution._create_task(
                operation_id=PRODUCT_RESEARCH_OPERATION,
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                normalized_input_hash=canonical_sha256(request.semantic),
                context_artifact_id=context_artifact_id,
                canonical_input={
                    "semantic_request": dict(request.semantic),
                    "request_hash": request.request_hash,
                    "scope": request.scope,
                },
                idempotency=(request.scope, request.request_hash, _accept_outcome_json),
                execution_deadline_at=request.execution_deadline_at,
                inline_worker=inline_worker,
            )
        )

    def _execute_accepted_inline(
        self,
        request: _PreparedResearchRequest,
        handles: _TaskHandles,
    ) -> dict[str, Any]:
        try:
            self.product.execution._transition_to_running(
                handles.task,
                handles.run,
                handles.attempt,
            )
        except Exception as error:
            self.product.execution._finish_failure(
                handles.task,
                handles.run,
                handles.attempt,
                error=error,
                category=classify_execution_error(error),
            )
            raise
        return self.execute_accepted(request, handles)

    def _build_core_pipeline(
        self,
        execution: _ResearchExecution,
        repositories: SQLiteRepositoryRegistry,
    ) -> CoreResearchPipelineService:
        return CoreResearchPipelineService(
            strategy=FormalStrategyEvaluationService(
                repositories=repositories,
                byte_reader=self.product.artifact_store,
            ),
            portfolio=CanonicalPortfolioOwnerService(execution.policy_owner),
            risk=CanonicalRiskApplicationService(execution.risk_repository),
            adjusted_weight_owner=execution.risk_repository,
            result_artifact_store=self.product.artifact_store,
        )

    def _run_core_pipeline(self, execution: _ResearchExecution) -> Any:
        connection = connect_catalog(self.product.database_path, read_only=True)
        read_uow = SQLiteUnitOfWork(connection, TransactionMode.READ_ONLY)
        read_uow.begin()
        try:
            repositories = SQLiteRepositoryRegistry(read_uow)
            return self._build_core_pipeline(execution, repositories).run(
                execution.pipeline_request
            )
        finally:
            if read_uow.active:
                read_uow.rollback()
            connection.close()

    def _run_pipeline_and_publish(
        self,
        execution: _ResearchExecution,
        handles: _TaskHandles,
    ) -> dict[str, Any]:
        event_cursor = self.product.latest_event_sequence(execution.request.project_id)
        pipeline_result = self._run_core_pipeline(execution)
        _require_pipeline_success(pipeline_result)
        outputs = _research_result(
            self.product,
            _research_result_request(execution, handles.run.run_id, pipeline_result),
        )
        task_outputs = {
            role: str(outputs[role])
            for role in (
                "result_id",
                "result_artifact_id",
                "result_artifact_sha256",
                "lineage_artifact_id",
                "pipeline_run_id",
                "maturity",
            )
        }
        self.product.execution._finish_success(
            handles.task, handles.run, handles.attempt, outputs=task_outputs
        )
        return _research_accept_outcome(
            handles.task.task_id,
            handles.run.run_id,
            operation_receipt_id=self.product.execution.operation_receipt_id_for_task(
                handles.task.task_id
            ),
            event_cursor=event_cursor,
        )

    def _execute_task(
        self,
        execution: _ResearchExecution,
        handles: _TaskHandles,
    ) -> dict[str, Any]:
        try:
            self.product.execution._transition_to_running(
                handles.task,
                handles.run,
                handles.attempt,
            )
            return self._run_pipeline_and_publish(execution, handles)
        except Exception as error:
            self.product.execution._finish_failure(
                handles.task,
                handles.run,
                handles.attempt,
                error=error,
                category=classify_execution_error(error),
            )
            raise

    def execute_accepted(
        self,
        request: _PreparedResearchRequest,
        handles: _TaskHandles,
    ) -> dict[str, Any]:
        try:
            capture = self._capture_source(request)
            execution = self._build_execution(request, capture)
            return self._run_pipeline_and_publish(execution, handles)
        except Exception as error:
            self.product.execution._finish_failure(
                handles.task,
                handles.run,
                handles.attempt,
                error=error,
                category=classify_execution_error(error),
            )
            raise

    def submit(self, submission: ProductResearchSubmission) -> dict[str, Any]:
        request = self._prepare_request(submission)
        replay = self._replay_if_known(request)
        if replay is not None:
            return replay
        if self.product.research_workers is not None:
            workers = self.product.research_workers
            reservation = workers.reserve_capacity()
            handles: _TaskHandles | None = None
            try:
                handles = self._accept_request(request)
                workers.start(
                    request,
                    handles,
                    reservation_token=reservation,
                )
            except Exception as error:
                workers.release_capacity(reservation)
                if handles is not None and not getattr(
                    error, "defer_task_finalization", False
                ):
                    self.product.execution._finish_failure(
                        handles.task,
                        handles.run,
                        handles.attempt,
                        error=error,
                        category=classify_execution_error(error),
                    )
                raise
            return _research_accept_outcome(
                handles.task.task_id,
                handles.run.run_id,
                operation_receipt_id=self.product.execution.operation_receipt_id_for_task(
                    handles.task.task_id
                ),
                event_cursor=self.product.latest_event_sequence(request.project_id),
            )
        handles = self._accept_request(request, inline_worker=True)
        return self._execute_accepted_inline(request, handles)


__all__ = [
    "PRODUCT_RESEARCH_OPERATION",
    "RESEARCH_CONNECTOR_VERSION_ID",
    "RESEARCH_DATASET",
    "RESEARCH_MATURITY",
    "RESEARCH_PROFILE_ID",
    "RESEARCH_PROVIDER_ID",
    "RESEARCH_STRATEGY_PROFILE_ID",
    "ProductResearchError",
    "ProductResearchService",
]
