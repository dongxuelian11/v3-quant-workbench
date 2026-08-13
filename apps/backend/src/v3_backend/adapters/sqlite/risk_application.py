"""SQLite/Artifact implementation of the canonical Risk application owner."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.adapters.artifact_store.filesystem import (
    FileSystemArtifactStore,
    PublicationResult,
    StagingReceipt,
)
from v3_backend.domain.artifacts.model import ArtifactReference
from v3_backend.domain.artifacts.publication import ArtifactPublication
from v3_backend.domain.payload_authority import (
    CanonicalPayloadBinding,
    CanonicalPayloadResolver,
    PayloadResolutionRequest,
    PayloadBindingUnavailable,
)
from v3_backend.domain.risk_runtime.application import (
    CanonicalRiskApplicationPublication,
    CanonicalRiskApplicationRequest,
    RiskApplicationAuthorityError,
)
from v3_backend.domain.risk_runtime.codec import (
    canonical_policy_set_bytes,
    risk_policy_set_from_bytes,
)
from v3_backend.domain.risk_runtime.model import RiskPolicySetVersion
from v3_backend.domain.risk_runtime.runtime import apply_risk
from v3_backend.domain.weights import (
    RiskAdjustedWeightVector,
    RiskApplicationReceipt,
    TargetWeightVector,
    RuntimeIdentity,
)
from v3_backend.domain.weights.codec import (
    MAX_WEIGHT_ARTIFACT_BYTES,
    canonical_weight_bytes,
    risk_adjusted_weight_vector_from_bytes,
    risk_application_receipt_from_bytes,
    target_weight_vector_from_bytes,
)
from v3_backend.provenance.canonical_hash import canonical_sha256
from v3_backend.repositories.unit_of_work import TransactionMode

from .artifact_publication import SQLiteArtifactPublicationPort
from .connection import SQLiteConfig, connect_catalog
from .repositories import SQLiteRepositoryRegistry
from .unit_of_work import SQLiteUnitOfWork


BINDING_VERSION = "v3.sqlite-risk-application-owner/1.0.0"
TARGET_NAMESPACE = "v3.portfolio.target-weight-vector"
RECEIPT_NAMESPACE = "v3.risk.application-receipt"
ADJUSTED_NAMESPACE = "v3.risk.adjusted-weight-vector"
TARGET_ROLE = "TARGET_WEIGHT_VECTOR"
RECEIPT_ROLE = "RISK_APPLICATION_RECEIPT"
ADJUSTED_ROLE = "RISK_ADJUSTED_WEIGHT_VECTOR"


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RiskApplicationAuthorityError("publication time must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _reference_id(owner_id: str, role: str) -> str:
    digest = hashlib.sha256(f"{owner_id}\0{role}".encode("utf-8")).hexdigest()
    return "arf_" + digest[:26].upper()


def _provenance_id(subject_type: str, subject_id: str, digest: str) -> str:
    return "prv_" + canonical_sha256(
        {"subject_type": subject_type, "subject_id": subject_id, "canonical_hash": digest}
    )


def _edge_id(from_id: str, relation: str, to_id: str) -> str:
    return "pre_" + canonical_sha256(
        {"from_entity_id": from_id, "relation": relation, "to_entity_id": to_id}
    )


def _truth_columns(value) -> dict[str, str]:
    return {
        "truth_state": value.truth.value,
        "admission_state": value.admission.value,
    }


@dataclass(frozen=True, slots=True)
class _ArtifactPlan:
    owner_id: str
    role: str
    schema_version: str
    payload: bytes
    provenance_entity_id: str


class _BatchPublishCallbacks:
    """Existing PUBLISH UoW callback contract for a bounded artifact batch."""

    def __init__(
        self,
        *,
        store: FileSystemArtifactStore,
        database_path: Path,
        plans: tuple[_ArtifactPlan, ...],
        published_at: datetime,
    ) -> None:
        self.store = store
        self.database_path = database_path
        self.plans = plans
        self.published_at = published_at
        self.stages: tuple[StagingReceipt, ...] = tuple(
            store.stage_bytes(plan.payload) for plan in plans
        )
        self.results: tuple[PublicationResult, ...] = ()

    def verify_staged(self) -> None:
        for plan, stage in zip(self.plans, self.stages, strict=True):
            if stage.sha256 != hashlib.sha256(plan.payload).hexdigest():
                raise RiskApplicationAuthorityError("staged Artifact hash mismatch")
            if stage.byte_size != len(plan.payload):
                raise RiskApplicationAuthorityError("staged Artifact size mismatch")

    def publish_staged(self) -> None:
        published: list[PublicationResult] = []
        try:
            for plan, stage in zip(self.plans, self.stages, strict=True):
                published.append(
                    self.store.publish(
                        stage.staging_token,
                        expected_sha256=stage.sha256,
                        expected_byte_size=stage.byte_size,
                        media_type="application/json",
                        role=plan.role,
                        provenance_entity_id=plan.provenance_entity_id,
                        schema_fingerprint=plan.schema_version,
                        semantic_fingerprint=plan.schema_version,
                        published_at=self.published_at,
                    )
                )
        except Exception:
            self.results = tuple(published)
            self.compensate_unreferenced_staging()
            observed_now = datetime.now(timezone.utc)
            for stage in self.stages[len(published) :]:
                self.store.discard_staging(
                    stage.staging_token,
                    not_newer_than=observed_now,
                    now=observed_now,
                )
            raise
        else:
            self.results = tuple(published)

    def compensate_unreferenced_staging(self) -> None:
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            for result in self.results:
                if result.deduplicated:
                    continue
                reachable = connection.execute(
                    "SELECT 1 FROM artifact_reference WHERE artifact_id=? AND state='ACTIVE' LIMIT 1",
                    (result.descriptor.artifact_id,),
                ).fetchone()
                if reachable is None:
                    self.store.delete_published_bytes(result.descriptor.artifact_id)
        finally:
            connection.close()

    def notify_committed(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class ResolvedRiskAdjustedWeightVector:
    vector: RiskAdjustedWeightVector
    binding: CanonicalPayloadBinding
    source_target_weight_vector_id: str
    risk_application_receipt_id: str


class SQLiteRiskApplicationRepository:
    """Trusted owner adapter; result objects are never accepted for publication."""

    def __init__(self, database_path: str | Path, artifact_root: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.store = FileSystemArtifactStore(artifact_root)

    def _connection(self, *, read_only: bool = False) -> sqlite3.Connection:
        return connect_catalog(SQLiteConfig(self.database_path, read_only=read_only))

    @staticmethod
    def _record_entity(
        registry: SQLiteRepositoryRegistry,
        *,
        entity_id: str,
        subject_type: str,
        subject_id: str,
        subject_version: str,
        digest: str,
        code_version: str,
        environment_profile_id: str,
        actor: str,
        recorded_at: str,
    ) -> None:
        table = registry.provenance.table("provenance_entity")
        if table.get(entity_id) is not None:
            return
        registry.provenance.record_entity_once(
            {
                "provenance_entity_id": entity_id,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "subject_version": subject_version,
                "canonical_hash": digest,
                "code_version": code_version,
                "environment_profile_id": environment_profile_id,
                "actor": actor,
                "recorded_at": recorded_at,
            }
        )

    @staticmethod
    def _record_edge(
        registry: SQLiteRepositoryRegistry,
        *,
        from_id: str,
        relation: str,
        to_id: str,
        recorded_at: str,
    ) -> None:
        edge_id = _edge_id(from_id, relation, to_id)
        if registry.provenance.table("provenance_edge").get(edge_id) is not None:
            return
        registry.provenance.record_edge_once(
            {
                "provenance_edge_id": edge_id,
                "from_entity_id": from_id,
                "relation": relation,
                "to_entity_id": to_id,
                "recorded_at": recorded_at,
            }
        )

    def publish_risk_policy_set(
        self,
        policy_set: RiskPolicySetVersion,
        *,
        runtime_identity: RuntimeIdentity,
        published_at: datetime,
    ) -> RiskPolicySetVersion:
        policy_set.assert_canonical()
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be RuntimeIdentity")
        wire_time = _wire_time(published_at)
        payload = canonical_policy_set_bytes(policy_set)
        first = policy_set.policies[0]
        if (
            runtime_identity.code_version != first.code_version
            or runtime_identity.runtime_profile_id != first.runtime_profile_id
        ):
            raise RiskApplicationAuthorityError(
                "Risk policy owner runtime does not match the canonical policy set"
            )
        connection = self._connection()
        try:
            with SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL) as uow:
                registry = SQLiteRepositoryRegistry(uow)
                table = registry.risk.table("risk_policy_set_publication")
                existing = table.get(policy_set.risk_policy_set_version_id)
                row = {
                    "risk_policy_set_version_id": policy_set.risk_policy_set_version_id,
                    "content_sha256": policy_set.content_sha256,
                    "policy_json": payload.decode("utf-8"),
                    "code_version": first.code_version,
                    "runtime_profile_id": first.runtime_profile_id,
                    "environment_fingerprint": runtime_identity.environment_fingerprint,
                    "backend": first.backend,
                    **_truth_columns(policy_set.truth_admission),
                    "published_at": wire_time,
                }
                if existing is None:
                    table.add_new(row)
                elif any(existing[key] != value for key, value in row.items() if key != "published_at"):
                    raise RiskApplicationAuthorityError("Risk policy owner identity conflicts")
                entity_id = _provenance_id(
                    "RiskPolicySetVersion",
                    policy_set.risk_policy_set_version_id,
                    policy_set.content_sha256,
                )
                self._record_entity(
                    registry,
                    entity_id=entity_id,
                    subject_type="RiskPolicySetVersion",
                    subject_id=policy_set.risk_policy_set_version_id,
                    subject_version=policy_set.schema_version,
                    digest=policy_set.content_sha256,
                    code_version=first.code_version,
                    environment_profile_id=runtime_identity.runtime_profile_id,
                    actor="v3.risk-service/1.0.0",
                    recorded_at=wire_time,
                )
        finally:
            connection.close()
        return self.require_risk_policy_set(
            policy_set.risk_policy_set_version_id,
            runtime_identity=runtime_identity,
        )

    def publish_target_weight(
        self, target: TargetWeightVector, *, published_at: datetime
    ) -> TargetWeightVector:
        target.assert_canonical()
        context_identity = target.source.source_reference_sha256
        try:
            existing = self.require_target_weight(
                target.target_weight_vector_id, context_identity=context_identity
            )
        except PayloadBindingUnavailable:
            pass
        else:
            if existing != target:
                raise RiskApplicationAuthorityError("TargetWeight owner identity conflicts")
            return existing

        payload = canonical_weight_bytes(target)
        entity_id = _provenance_id(
            "TargetWeightVector", target.target_weight_vector_id, target.content_sha256
        )
        plan = _ArtifactPlan(
            target.target_weight_vector_id,
            TARGET_ROLE,
            target.schema_version,
            payload,
            entity_id,
        )
        self._publish_target(plan, target, context_identity, published_at)
        return self.require_target_weight(
            target.target_weight_vector_id, context_identity=context_identity
        )

    def _publish_target(
        self,
        plan: _ArtifactPlan,
        target: TargetWeightVector,
        context_identity: str,
        published_at: datetime,
    ) -> None:
        callbacks = _BatchPublishCallbacks(
            store=self.store,
            database_path=self.database_path,
            plans=(plan,),
            published_at=published_at,
        )
        connection = self._connection()
        wire_time = _wire_time(published_at)
        try:
            with SQLiteUnitOfWork(
                connection,
                TransactionMode.PUBLISH,
                publish_callbacks=callbacks,
            ) as uow:
                result = callbacks.results[0]
                descriptor = result.descriptor
                registry = SQLiteRepositoryRegistry(uow)
                self._record_entity(
                    registry,
                    entity_id=plan.provenance_entity_id,
                    subject_type="TargetWeightVector",
                    subject_id=target.target_weight_vector_id,
                    subject_version=target.schema_version,
                    digest=target.content_sha256,
                    code_version=target.runtime_identity.code_version,
                    environment_profile_id=target.runtime_identity.runtime_profile_id,
                    actor="v3.portfolio-service/1.0.0",
                    recorded_at=wire_time,
                )
                reference = ArtifactReference(
                    reference_id=_reference_id(target.target_weight_vector_id, TARGET_ROLE),
                    owner_id=target.target_weight_vector_id,
                    artifact_id=descriptor.artifact_id,
                    role=TARGET_ROLE,
                    created_at=descriptor.created_at,
                )
                SQLiteArtifactPublicationPort(uow).publish(
                    ArtifactPublication(descriptor, (reference,))
                )
                row = {
                    "target_weight_vector_id": target.target_weight_vector_id,
                    "content_sha256": target.content_sha256,
                    "artifact_id": descriptor.artifact_id,
                    "artifact_reference_id": reference.reference_id,
                    "artifact_sha256": descriptor.sha256,
                    "byte_size": descriptor.byte_size,
                    "schema_version": target.schema_version,
                    "context_identity": context_identity,
                    "portfolio_intent_id": target.source.portfolio_intent_id,
                    "portfolio_intent_content_sha256": target.source.portfolio_intent_content_sha256,
                    "construction_spec_id": target.construction_spec.source_id,
                    "construction_spec_content_sha256": target.construction_spec.content_sha256,
                    "universe_version_id": target.source.universe_version_id,
                    "membership_artifact_ref": target.source.membership_artifact_id,
                    "membership_sha256": target.source.membership_sha256,
                    "as_of": target.to_wire()["as_of"],
                    "decision_time": target.to_wire()["decision_time"],
                    "rebalance_time": target.to_wire()["rebalance_time"],
                    "valid_until": target.to_wire()["valid_until"],
                    "code_version": target.runtime_identity.code_version,
                    "runtime_profile_id": target.runtime_identity.runtime_profile_id,
                    "environment_fingerprint": target.runtime_identity.environment_fingerprint,
                    **_truth_columns(target.truth_admission),
                    "published_at": wire_time,
                }
                registry.portfolio.table("target_weight_vector_publication").add_new(row)
        finally:
            connection.close()

    def require_risk_policy_set(
        self,
        risk_policy_set_version_id: str,
        *,
        runtime_identity: RuntimeIdentity | None = None,
    ) -> RiskPolicySetVersion:
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                "SELECT * FROM risk_policy_set_publication WHERE risk_policy_set_version_id=?",
                (risk_policy_set_version_id,),
            ).fetchone()
            if row is None:
                raise RiskApplicationAuthorityError("canonical Risk policy owner is missing")
            policy_set = risk_policy_set_from_bytes(str(row["policy_json"]).encode("utf-8"))
            first = policy_set.policies[0]
            expected = {
                "content_sha256": policy_set.content_sha256,
                "code_version": first.code_version,
                "runtime_profile_id": first.runtime_profile_id,
                "backend": first.backend,
                **_truth_columns(policy_set.truth_admission),
            }
            if policy_set.risk_policy_set_version_id != risk_policy_set_version_id or any(
                row[key] != value for key, value in expected.items()
            ):
                raise RiskApplicationAuthorityError("canonical Risk policy owner is inconsistent")
            if runtime_identity is not None and (
                runtime_identity.code_version != row["code_version"]
                or runtime_identity.runtime_profile_id != row["runtime_profile_id"]
                or runtime_identity.environment_fingerprint
                != row["environment_fingerprint"]
            ):
                raise RiskApplicationAuthorityError(
                    "request runtime identity does not match the canonical Risk policy owner"
                )
            return policy_set
        finally:
            connection.close()

    def resolve(self, request: PayloadResolutionRequest) -> CanonicalPayloadBinding | None:
        mapping = {
            (TARGET_NAMESPACE, TARGET_ROLE, TargetWeightVector.schema_version): (
                "target_weight_vector_publication",
                "target_weight_vector_id",
            ),
            (RECEIPT_NAMESPACE, RECEIPT_ROLE, RiskApplicationReceipt.schema_version): (
                "risk_application_receipt_publication",
                "risk_application_receipt_id",
            ),
            (ADJUSTED_NAMESPACE, ADJUSTED_ROLE, RiskAdjustedWeightVector.schema_version): (
                "risk_adjusted_weight_vector_publication",
                "risk_adjusted_weight_vector_id",
            ),
        }
        selected = mapping.get(
            (request.owner_namespace, request.payload_role, request.owner_version)
        )
        if selected is None:
            return None
        table, id_column = selected
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                f'SELECT * FROM "{table}" WHERE "{id_column}"=?',
                (request.owner_id,),
            ).fetchone()
            if row is None:
                return None
            artifact = connection.execute(
                "SELECT * FROM artifact WHERE artifact_id=? AND state='PUBLISHED'",
                (row["artifact_id"],),
            ).fetchone()
            reference = connection.execute(
                "SELECT * FROM artifact_reference WHERE artifact_reference_id=? AND owner_id=? AND role=? AND artifact_id=? AND state='ACTIVE'",
                (
                    row["artifact_reference_id"],
                    request.owner_id,
                    request.payload_role,
                    row["artifact_id"],
                ),
            ).fetchone()
            if artifact is None or reference is None:
                raise RiskApplicationAuthorityError("owner Artifact is not published/reachable")
            if (
                artifact["sha256"] != row["artifact_sha256"]
                or artifact["byte_size"] != row["byte_size"]
                or artifact["semantic_role"] != request.payload_role
                or artifact["schema_fingerprint"] != row["schema_version"]
                or artifact["safe_format_id"] != "canonical-json-v1"
            ):
                raise RiskApplicationAuthorityError("owner Artifact metadata mismatch")
            return CanonicalPayloadBinding(
                owner_namespace=request.owner_namespace,
                owner_id=request.owner_id,
                owner_version=request.owner_version,
                payload_role=request.payload_role,
                artifact_id=row["artifact_id"],
                expected_sha256=row["artifact_sha256"],
                expected_byte_size=row["byte_size"],
                context_identity=row["context_identity"],
                binding_version=BINDING_VERSION,
                schema_fingerprint=row["schema_version"],
                semantic_fingerprint=row["schema_version"],
                provenance_reference_id=row["artifact_reference_id"],
            )
        finally:
            connection.close()

    def _payload(self, request: PayloadResolutionRequest) -> bytes:
        return CanonicalPayloadResolver(
            binding_resolver=self,
            byte_reader=self.store,
        ).resolve(request).verified_payload.payload

    def require_target_weight(
        self, target_weight_vector_id: str, *, context_identity: str
    ) -> TargetWeightVector:
        payload = self._payload(
            PayloadResolutionRequest(
                owner_namespace=TARGET_NAMESPACE,
                owner_id=target_weight_vector_id,
                owner_version=TargetWeightVector.schema_version,
                payload_role=TARGET_ROLE,
                context_identity=context_identity,
                max_bytes=MAX_WEIGHT_ARTIFACT_BYTES,
            )
        )
        target = target_weight_vector_from_bytes(payload)
        row = self._require_owner_row(
            "target_weight_vector_publication",
            "target_weight_vector_id",
            target_weight_vector_id,
        )
        if (
            target.target_weight_vector_id != target_weight_vector_id
            or target.content_sha256 != row["content_sha256"]
            or target.source.source_reference_sha256 != row["context_identity"]
        ):
            raise RiskApplicationAuthorityError("TargetWeight reconstruction identity mismatch")
        return target

    def _require_owner_row(self, table: str, column: str, identity: str) -> sqlite3.Row:
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                f'SELECT * FROM "{table}" WHERE "{column}"=?', (identity,)
            ).fetchone()
            if row is None:
                raise RiskApplicationAuthorityError(f"canonical owner is missing: {identity}")
            return row
        finally:
            connection.close()

    def require_risk_application_receipt(
        self, risk_application_receipt_id: str
    ) -> RiskApplicationReceipt:
        row = self._require_owner_row(
            "risk_application_receipt_publication",
            "risk_application_receipt_id",
            risk_application_receipt_id,
        )
        context = str(row["context_identity"])
        target = self.require_target_weight(
            str(row["source_target_weight_vector_id"]), context_identity=context
        )
        policy = self.require_risk_policy_set(
            str(row["risk_policy_set_version_id"]),
            runtime_identity=RuntimeIdentity(
                code_version=str(row["code_version"]),
                runtime_profile_id=str(row["runtime_profile_id"]),
                environment_fingerprint=str(row["environment_fingerprint"]),
            ),
        )
        payload = self._payload(
            PayloadResolutionRequest(
                owner_namespace=RECEIPT_NAMESPACE,
                owner_id=risk_application_receipt_id,
                owner_version=RiskApplicationReceipt.schema_version,
                payload_role=RECEIPT_ROLE,
                context_identity=context,
                max_bytes=MAX_WEIGHT_ARTIFACT_BYTES,
            )
        )
        receipt = risk_application_receipt_from_bytes(payload, source_target=target)
        if (
            receipt.risk_application_receipt_id != risk_application_receipt_id
            or receipt.content_sha256 != row["content_sha256"]
            or receipt.risk_policy_set.source_id != policy.risk_policy_set_version_id
            or receipt.risk_policy_set.content_sha256 != policy.content_sha256
            or receipt.source_target_content_sha256 != row["source_target_content_sha256"]
            or receipt.ordered_stage_evidence_sha256 != row["ordered_stage_evidence_sha256"]
        ):
            raise RiskApplicationAuthorityError("Risk receipt owner lineage mismatch")
        return receipt

    def require_adjusted_weight_vector(
        self, risk_adjusted_weight_vector_id: str
    ) -> RiskAdjustedWeightVector:
        row = self._require_owner_row(
            "risk_adjusted_weight_vector_publication",
            "risk_adjusted_weight_vector_id",
            risk_adjusted_weight_vector_id,
        )
        context = str(row["context_identity"])
        target = self.require_target_weight(
            str(row["source_target_weight_vector_id"]), context_identity=context
        )
        receipt = self.require_risk_application_receipt(
            str(row["risk_application_receipt_id"])
        )
        payload = self._payload(
            PayloadResolutionRequest(
                owner_namespace=ADJUSTED_NAMESPACE,
                owner_id=risk_adjusted_weight_vector_id,
                owner_version=RiskAdjustedWeightVector.schema_version,
                payload_role=ADJUSTED_ROLE,
                context_identity=context,
                max_bytes=MAX_WEIGHT_ARTIFACT_BYTES,
            )
        )
        vector = risk_adjusted_weight_vector_from_bytes(
            payload, source_target=target, risk_application=receipt
        )
        if (
            vector.risk_adjusted_weight_vector_id != risk_adjusted_weight_vector_id
            or vector.content_sha256 != row["content_sha256"]
            or vector.risk_application.content_sha256
            != row["risk_application_content_sha256"]
        ):
            raise RiskApplicationAuthorityError("adjusted-vector owner lineage mismatch")
        return vector

    def persist_recomputed_application(
        self,
        request: CanonicalRiskApplicationRequest,
        *,
        expected_receipt_id: str,
        expected_adjusted_id: str,
        published_at: datetime,
    ) -> CanonicalRiskApplicationPublication:
        target = self.require_target_weight(
            request.source_target_weight_vector_id,
            context_identity=request.context_identity,
        )
        if target.source.source_reference_sha256 != request.context_identity:
            raise RiskApplicationAuthorityError("target owner context mismatch")
        policy = self.require_risk_policy_set(
            request.risk_policy_set_version_id,
            runtime_identity=request.runtime_identity,
        )
        result = apply_risk(
            source_target=target,
            policy_set=policy,
            runtime_identity=request.runtime_identity,
            state_inputs=(),
        )
        receipt = result.application_receipt
        adjusted = result.adjusted_weights
        if (
            receipt.risk_application_receipt_id != expected_receipt_id
            or adjusted.risk_adjusted_weight_vector_id != expected_adjusted_id
        ):
            raise RiskApplicationAuthorityError("recomputed Risk output identity mismatch")

        try:
            existing = self.require_adjusted_weight_vector(expected_adjusted_id)
        except (PayloadBindingUnavailable, RiskApplicationAuthorityError):
            pass
        else:
            if existing != adjusted:
                raise RiskApplicationAuthorityError("adjusted-vector immutable conflict")
            return self._publication_from_rows(receipt, adjusted)

        receipt_entity = _provenance_id(
            "RiskApplicationReceipt",
            receipt.risk_application_receipt_id,
            receipt.content_sha256,
        )
        adjusted_entity = _provenance_id(
            "RiskAdjustedWeightVector",
            adjusted.risk_adjusted_weight_vector_id,
            adjusted.content_sha256,
        )
        plans = (
            _ArtifactPlan(
                receipt.risk_application_receipt_id,
                RECEIPT_ROLE,
                receipt.schema_version,
                canonical_weight_bytes(receipt),
                receipt_entity,
            ),
            _ArtifactPlan(
                adjusted.risk_adjusted_weight_vector_id,
                ADJUSTED_ROLE,
                adjusted.schema_version,
                canonical_weight_bytes(adjusted),
                adjusted_entity,
            ),
        )
        self._publish_application(
            request,
            target,
            policy,
            receipt,
            adjusted,
            plans,
            published_at,
        )
        return self._publication_from_rows(receipt, adjusted)

    def _publish_application(
        self,
        request: CanonicalRiskApplicationRequest,
        target: TargetWeightVector,
        policy: RiskPolicySetVersion,
        receipt: RiskApplicationReceipt,
        adjusted: RiskAdjustedWeightVector,
        plans: tuple[_ArtifactPlan, _ArtifactPlan],
        published_at: datetime,
    ) -> None:
        callbacks = _BatchPublishCallbacks(
            store=self.store,
            database_path=self.database_path,
            plans=plans,
            published_at=published_at,
        )
        connection = self._connection()
        wire_time = _wire_time(published_at)
        try:
            with SQLiteUnitOfWork(
                connection,
                TransactionMode.PUBLISH,
                publish_callbacks=callbacks,
            ) as uow:
                registry = SQLiteRepositoryRegistry(uow)
                target_entity = _provenance_id(
                    "TargetWeightVector", target.target_weight_vector_id, target.content_sha256
                )
                policy_entity = _provenance_id(
                    "RiskPolicySetVersion", policy.risk_policy_set_version_id, policy.content_sha256
                )
                entities = (
                    (
                        plans[0].provenance_entity_id,
                        "RiskApplicationReceipt",
                        receipt.risk_application_receipt_id,
                        receipt.schema_version,
                        receipt.content_sha256,
                    ),
                    (
                        plans[1].provenance_entity_id,
                        "RiskAdjustedWeightVector",
                        adjusted.risk_adjusted_weight_vector_id,
                        adjusted.schema_version,
                        adjusted.content_sha256,
                    ),
                )
                for entity_id, subject_type, subject_id, version, digest in entities:
                    self._record_entity(
                        registry,
                        entity_id=entity_id,
                        subject_type=subject_type,
                        subject_id=subject_id,
                        subject_version=version,
                        digest=digest,
                        code_version=request.runtime_identity.code_version,
                        environment_profile_id=request.runtime_identity.runtime_profile_id,
                        actor="v3.canonical-risk-application-service/1.0.0",
                        recorded_at=wire_time,
                    )
                self._record_edge(
                    registry,
                    from_id=target_entity,
                    relation="DERIVED_FROM",
                    to_id=plans[0].provenance_entity_id,
                    recorded_at=wire_time,
                )
                self._record_edge(
                    registry,
                    from_id=policy_entity,
                    relation="DERIVED_FROM",
                    to_id=plans[0].provenance_entity_id,
                    recorded_at=wire_time,
                )
                self._record_edge(
                    registry,
                    from_id=plans[0].provenance_entity_id,
                    relation="DERIVED_FROM",
                    to_id=plans[1].provenance_entity_id,
                    recorded_at=wire_time,
                )

                references: list[ArtifactReference] = []
                for plan, result in zip(plans, callbacks.results, strict=True):
                    reference = ArtifactReference(
                        reference_id=_reference_id(plan.owner_id, plan.role),
                        owner_id=plan.owner_id,
                        artifact_id=result.descriptor.artifact_id,
                        role=plan.role,
                        created_at=result.descriptor.created_at,
                    )
                    SQLiteArtifactPublicationPort(uow).publish(
                        ArtifactPublication(result.descriptor, (reference,))
                    )
                    references.append(reference)

                receipt_descriptor = callbacks.results[0].descriptor
                adjusted_descriptor = callbacks.results[1].descriptor
                registry.risk.table("risk_application_receipt_publication").add_new(
                    {
                        "risk_application_receipt_id": receipt.risk_application_receipt_id,
                        "content_sha256": receipt.content_sha256,
                        "artifact_id": receipt_descriptor.artifact_id,
                        "artifact_reference_id": references[0].reference_id,
                        "artifact_sha256": receipt_descriptor.sha256,
                        "byte_size": receipt_descriptor.byte_size,
                        "schema_version": receipt.schema_version,
                        "context_identity": request.context_identity,
                        "source_target_weight_vector_id": target.target_weight_vector_id,
                        "source_target_content_sha256": target.content_sha256,
                        "risk_policy_set_version_id": policy.risk_policy_set_version_id,
                        "risk_policy_set_content_sha256": policy.content_sha256,
                        "decision": receipt.decision.value,
                        "decision_reason": receipt.decision_reason.value,
                        "ordered_stage_evidence_sha256": receipt.ordered_stage_evidence_sha256,
                        "code_version": request.runtime_identity.code_version,
                        "runtime_profile_id": request.runtime_identity.runtime_profile_id,
                        "environment_fingerprint": request.runtime_identity.environment_fingerprint,
                        **_truth_columns(receipt.truth_admission),
                        "published_at": wire_time,
                    },
                    idempotent=True,
                )
                registry.risk.table("risk_adjusted_weight_vector_publication").add_new(
                    {
                        "risk_adjusted_weight_vector_id": adjusted.risk_adjusted_weight_vector_id,
                        "content_sha256": adjusted.content_sha256,
                        "artifact_id": adjusted_descriptor.artifact_id,
                        "artifact_reference_id": references[1].reference_id,
                        "artifact_sha256": adjusted_descriptor.sha256,
                        "byte_size": adjusted_descriptor.byte_size,
                        "schema_version": adjusted.schema_version,
                        "context_identity": request.context_identity,
                        "source_target_weight_vector_id": target.target_weight_vector_id,
                        "source_target_content_sha256": target.content_sha256,
                        "risk_application_receipt_id": receipt.risk_application_receipt_id,
                        "risk_application_content_sha256": receipt.content_sha256,
                        "code_version": request.runtime_identity.code_version,
                        "runtime_profile_id": request.runtime_identity.runtime_profile_id,
                        "environment_fingerprint": request.runtime_identity.environment_fingerprint,
                        **_truth_columns(adjusted.truth_admission),
                        "published_at": wire_time,
                    },
                    idempotent=True,
                )
        finally:
            connection.close()

    def _publication_from_rows(
        self,
        receipt: RiskApplicationReceipt,
        adjusted: RiskAdjustedWeightVector,
    ) -> CanonicalRiskApplicationPublication:
        receipt_row = self._require_owner_row(
            "risk_application_receipt_publication",
            "risk_application_receipt_id",
            receipt.risk_application_receipt_id,
        )
        adjusted_row = self._require_owner_row(
            "risk_adjusted_weight_vector_publication",
            "risk_adjusted_weight_vector_id",
            adjusted.risk_adjusted_weight_vector_id,
        )
        return CanonicalRiskApplicationPublication(
            source_target_weight_vector_id=receipt.source_target_weight_vector_id,
            risk_policy_set_version_id=receipt.risk_policy_set.source_id,
            risk_application_receipt_id=receipt.risk_application_receipt_id,
            risk_adjusted_weight_vector_id=adjusted.risk_adjusted_weight_vector_id,
            receipt_artifact_id=str(receipt_row["artifact_id"]),
            adjusted_artifact_id=str(adjusted_row["artifact_id"]),
            context_identity=str(adjusted_row["context_identity"]),
            truth_state=str(adjusted_row["truth_state"]),
            admission_state=str(adjusted_row["admission_state"]),
        )

    def resolve_adjusted_weight_for_downstream(
        self, risk_adjusted_weight_vector_id: str
    ) -> ResolvedRiskAdjustedWeightVector:
        row = self._require_owner_row(
            "risk_adjusted_weight_vector_publication",
            "risk_adjusted_weight_vector_id",
            risk_adjusted_weight_vector_id,
        )
        request = PayloadResolutionRequest(
            owner_namespace=ADJUSTED_NAMESPACE,
            owner_id=risk_adjusted_weight_vector_id,
            owner_version=RiskAdjustedWeightVector.schema_version,
            payload_role=ADJUSTED_ROLE,
            context_identity=str(row["context_identity"]),
            max_bytes=MAX_WEIGHT_ARTIFACT_BYTES,
        )
        binding = self.resolve(request)
        if binding is None:
            raise RiskApplicationAuthorityError("downstream owner binding is missing")
        vector = self.require_adjusted_weight_vector(risk_adjusted_weight_vector_id)
        return ResolvedRiskAdjustedWeightVector(
            vector=vector,
            binding=binding,
            source_target_weight_vector_id=str(row["source_target_weight_vector_id"]),
            risk_application_receipt_id=str(row["risk_application_receipt_id"]),
        )


__all__ = [
    "ADJUSTED_NAMESPACE",
    "ADJUSTED_ROLE",
    "BINDING_VERSION",
    "RECEIPT_NAMESPACE",
    "RECEIPT_ROLE",
    "ResolvedRiskAdjustedWeightVector",
    "SQLiteRiskApplicationRepository",
    "TARGET_NAMESPACE",
    "TARGET_ROLE",
]
