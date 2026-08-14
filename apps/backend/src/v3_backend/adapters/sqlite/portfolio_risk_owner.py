"""SQLite and Artifact implementation of the corrected Portfolio/RiskPolicy owners."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.adapters.artifact_store.filesystem import PublicationResult, StagingReceipt
from v3_backend.domain.artifacts.model import ArtifactReference
from v3_backend.domain.artifacts.publication import ArtifactPublication
from v3_backend.domain.payload_authority import (
    CanonicalPayloadBinding,
    PayloadResolutionRequest,
)
from v3_backend.domain.portfolio_construction.model import PortfolioConstructionResult
from v3_backend.domain.portfolio_construction.owner import (
    TARGET_WEIGHT_OWNER_NAMESPACE,
    TARGET_WEIGHT_PAYLOAD_ROLE,
    TARGET_WEIGHT_SERIALIZATION_VERSION,
    TargetWeightOwnerAuthorityError,
    TargetWeightOwnerPublication,
)
from v3_backend.domain.risk_runtime.authoring import (
    RISK_POLICY_OWNER_NAMESPACE,
    RISK_POLICY_PAYLOAD_ROLE,
    RISK_POLICY_SERIALIZATION_VERSION,
    RiskPolicyOwnerAuthorityError,
    RiskPolicySetOwnerPublication,
)
from v3_backend.domain.risk_runtime.model import (
    RiskModelRequirement,
    RiskPolicySetVersion,
)
from v3_backend.domain.weights import RuntimeIdentity
from v3_backend.errors.exceptions import ConflictError
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256
from v3_backend.repositories.unit_of_work import TransactionMode

from .artifact_publication import SQLiteArtifactPublicationPort
from .connection import SQLiteConfig, connect_catalog
from .repositories import SQLiteRepositoryRegistry
from .unit_of_work import SQLiteUnitOfWork


OWNER_BINDING_VERSION = "v3.sqlite-portfolio-riskpolicy-owner-binding/1.0.0"
_TARGET_CREATED_BY = "v3.canonical-portfolio-owner-service/1.0.0"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _wire_time(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("canonical owner timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("persisted canonical owner timestamp is not timezone-aware")
    return parsed


def _reference_id(owner_type: str, owner_id: str, role: str, artifact_id: str) -> str:
    value = int(canonical_sha256([owner_type, owner_id, role, artifact_id]), 16) >> 128
    encoded = ""
    for _ in range(26):
        encoded = _CROCKFORD[value & 31] + encoded
        value >>= 5
    return "arf_" + encoded


def _schema_fingerprint(schema_version: str, serialization_version: str) -> str:
    return "sch_sha256_" + canonical_sha256(
        {
            "schema_version": schema_version,
            "serialization_version": serialization_version,
            "encoding": "canonical-json",
        }
    )


def _owner_context_identity(
    *, project_id: str, project_context_revision_id: str, canonical_hash: str
) -> str:
    return canonical_sha256(
        {
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "project_context_canonical_hash": canonical_hash,
        }
    )


@dataclass(frozen=True, slots=True)
class _ArtifactPlan:
    owner_type: str
    owner_id: str
    role: str
    schema_version: str
    serialization_version: str
    payload: bytes


class _OwnerPublishCallbacks:
    """Reuse the existing PUBLISH UoW compensation contract for one owner payload."""

    def __init__(
        self,
        *,
        store: FileSystemArtifactStore,
        database_path: Path,
        plan: _ArtifactPlan,
        published_at: datetime,
    ) -> None:
        self.store = store
        self.database_path = database_path
        self.plan = plan
        self.published_at = published_at
        self.stage: StagingReceipt = store.stage_bytes(plan.payload)
        self.result: PublicationResult | None = None

    def verify_staged(self) -> None:
        if self.stage.sha256 != hashlib.sha256(self.plan.payload).hexdigest():
            raise ValueError("staged canonical owner payload hash mismatch")
        if self.stage.byte_size != len(self.plan.payload):
            raise ValueError("staged canonical owner payload size mismatch")

    def publish_staged(self) -> None:
        try:
            self.result = self.store.publish(
                self.stage.staging_token,
                expected_sha256=self.stage.sha256,
                expected_byte_size=self.stage.byte_size,
                media_type="application/json",
                role=self.plan.role,
                provenance_entity_id=self.plan.owner_id,
                schema_fingerprint=_schema_fingerprint(
                    self.plan.schema_version, self.plan.serialization_version
                ),
                semantic_fingerprint=self.plan.owner_id,
                published_at=self.published_at,
            )
        except Exception:
            observed_now = datetime.now(timezone.utc)
            self.store.discard_staging(
                self.stage.staging_token,
                not_newer_than=observed_now,
                now=observed_now,
            )
            raise

    def compensate_unreferenced_staging(self) -> None:
        if self.result is None or self.result.deduplicated:
            return
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            reachable = connection.execute(
                """
                SELECT 1 FROM artifact_reference
                WHERE artifact_id=? AND state='ACTIVE' LIMIT 1
                """,
                (self.result.descriptor.artifact_id,),
            ).fetchone()
        finally:
            connection.close()
        if reachable is None:
            self.store.delete_published_bytes(self.result.descriptor.artifact_id)

    def notify_committed(self) -> None:
        return None


class SQLitePortfolioRiskPolicyOwner:
    """One adapter over the existing Catalog, Artifact Store and P1 extension seam."""

    def __init__(self, database_path: str | Path, artifact_root: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.store = FileSystemArtifactStore(artifact_root)

    def _connection(self, *, read_only: bool = False):
        return connect_catalog(SQLiteConfig(self.database_path, read_only=read_only))

    def _require_context(
        self,
        registry: SQLiteRepositoryRegistry,
        *,
        project_id: str,
        project_context_revision_id: str,
    ) -> str:
        project = registry.project.table("project").get(project_id)
        revision = registry.project.table("project_context_revision").get(
            project_context_revision_id
        )
        if (
            project is None
            or project["state"] != "ACTIVE"
            or revision is None
            or revision["project_id"] != project_id
        ):
            raise ValueError("canonical owner requires an exact active Project/ProjectContext")
        return _owner_context_identity(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            canonical_hash=str(revision["canonical_hash"]),
        )

    def _publish_constructed_target(
        self,
        construction: PortfolioConstructionResult,
        *,
        project_id: str,
        project_context_revision_id: str,
        published_at: datetime,
    ) -> TargetWeightOwnerPublication:
        if not isinstance(construction, PortfolioConstructionResult):
            raise TypeError("trusted owner accepts only PortfolioConstructionResult")
        target = construction.target
        target.assert_canonical()
        payload = canonical_json_bytes(target.to_wire())
        plan = _ArtifactPlan(
            "TargetWeightVector",
            target.target_weight_vector_id,
            TARGET_WEIGHT_PAYLOAD_ROLE,
            target.schema_version,
            TARGET_WEIGHT_SERIALIZATION_VERSION,
            payload,
        )
        existing = self._load_publication(
            "target_weight_vector_publication", target.target_weight_vector_id
        )
        if existing is not None:
            stable = self._require_same_target(
                existing, target, project_id, project_context_revision_id
            )
            self._validate_existing_payload(
                stable, payload, TARGET_WEIGHT_PAYLOAD_ROLE
            )
            return self._target_publication_from_row(stable)
        callbacks = _OwnerPublishCallbacks(
            store=self.store,
            database_path=self.database_path,
            plan=plan,
            published_at=published_at,
        )
        connection = self._connection()
        try:
            with SQLiteUnitOfWork(
                connection,
                TransactionMode.PUBLISH,
                publish_callbacks=callbacks,
            ) as unit:
                assert callbacks.result is not None
                registry = SQLiteRepositoryRegistry(unit)
                context_identity = self._require_context(
                    registry,
                    project_id=project_id,
                    project_context_revision_id=project_context_revision_id,
                )
                descriptor = callbacks.result.descriptor
                reference = ArtifactReference(
                    reference_id=_reference_id(
                        plan.owner_type, plan.owner_id, plan.role, descriptor.artifact_id
                    ),
                    owner_id=plan.owner_id,
                    artifact_id=descriptor.artifact_id,
                    role=plan.role,
                    created_at=descriptor.created_at,
                )
                SQLiteArtifactPublicationPort(unit).publish(
                    ArtifactPublication(descriptor, (reference,))
                )
                row = {
                    "target_weight_vector_id": target.target_weight_vector_id,
                    "content_sha256": target.content_sha256,
                    "project_id": project_id,
                    "project_context_revision_id": project_context_revision_id,
                    "context_identity": context_identity,
                    "portfolio_intent_id": target.source.portfolio_intent_id,
                    "portfolio_intent_content_sha256": target.source.portfolio_intent_content_sha256,
                    "portfolio_intent_provenance_sha256": target.source.portfolio_intent_provenance_sha256,
                    "source_reference_sha256": target.source.source_reference_sha256,
                    "source_owner_receipt_resolution": target.source.owner_receipt_resolution,
                    "construction_spec_id": target.construction_spec.source_id,
                    "construction_spec_content_sha256": target.construction_spec.content_sha256,
                    "universe_version_id": target.source.universe_version_id,
                    "membership_artifact_id": target.source.membership_artifact_id,
                    "membership_sha256": target.source.membership_sha256,
                    "artifact_id": descriptor.artifact_id,
                    "artifact_reference_id": reference.reference_id,
                    "artifact_sha256": descriptor.sha256,
                    "byte_size": descriptor.byte_size,
                    "schema_version": target.schema_version,
                    "serialization_version": TARGET_WEIGHT_SERIALIZATION_VERSION,
                    "canonical_truth_state": target.truth_admission.truth.value,
                    "canonical_admission_state": target.truth_admission.admission.value,
                    "created_by": _TARGET_CREATED_BY,
                    "published_at": _wire_time(published_at),
                }
                registry.portfolio.table("target_weight_vector_publication").add_new(row)
        except ConflictError as error:
            existing = self._load_publication(
                "target_weight_vector_publication", target.target_weight_vector_id
            )
            if existing is None:
                raise TargetWeightOwnerAuthorityError(
                    "TargetWeight canonical identity/content conflict"
                ) from error
            stable = self._require_same_target(
                existing, target, project_id, project_context_revision_id
            )
            self._validate_existing_payload(stable, payload, TARGET_WEIGHT_PAYLOAD_ROLE)
            return self._target_publication_from_row(stable)
        finally:
            connection.close()
        row = self._load_publication(
            "target_weight_vector_publication", target.target_weight_vector_id
        )
        assert row is not None
        return self._target_publication_from_row(row)

    def _publish_authored_policy_set(
        self,
        policy_set: RiskPolicySetVersion,
        *,
        project_id: str,
        project_context_revision_id: str,
        runtime_identity: RuntimeIdentity,
        authoring_service_version: str,
        published_at: datetime,
    ) -> RiskPolicySetOwnerPublication:
        policy_set.assert_canonical()
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be RuntimeIdentity")
        if any(
            policy.risk_model_requirement is not RiskModelRequirement.NOT_REQUIRED
            for policy in policy_set.policies
        ):
            raise RiskPolicyOwnerAuthorityError("RiskModel requirement must remain NOT_REQUIRED")
        first = policy_set.policies[0]
        if (
            first.code_version != runtime_identity.code_version
            or first.runtime_profile_id != runtime_identity.runtime_profile_id
        ):
            raise RiskPolicyOwnerAuthorityError(
                "authored policy runtime does not match publication runtime"
            )
        payload = canonical_json_bytes(policy_set.to_wire())
        plan = _ArtifactPlan(
            "RiskPolicySetVersion",
            policy_set.risk_policy_set_version_id,
            RISK_POLICY_PAYLOAD_ROLE,
            policy_set.schema_version,
            RISK_POLICY_SERIALIZATION_VERSION,
            payload,
        )
        existing = self._load_publication(
            "risk_policy_set_publication", policy_set.risk_policy_set_version_id
        )
        if existing is not None:
            stable = self._require_same_policy(
                existing,
                policy_set,
                project_id,
                project_context_revision_id,
                runtime_identity,
                authoring_service_version,
            )
            self._validate_existing_payload(stable, payload, RISK_POLICY_PAYLOAD_ROLE)
            return self._risk_publication_from_row(stable)
        callbacks = _OwnerPublishCallbacks(
            store=self.store,
            database_path=self.database_path,
            plan=plan,
            published_at=published_at,
        )
        connection = self._connection()
        try:
            with SQLiteUnitOfWork(
                connection,
                TransactionMode.PUBLISH,
                publish_callbacks=callbacks,
            ) as unit:
                assert callbacks.result is not None
                registry = SQLiteRepositoryRegistry(unit)
                context_identity = self._require_context(
                    registry,
                    project_id=project_id,
                    project_context_revision_id=project_context_revision_id,
                )
                descriptor = callbacks.result.descriptor
                reference = ArtifactReference(
                    reference_id=_reference_id(
                        plan.owner_type, plan.owner_id, plan.role, descriptor.artifact_id
                    ),
                    owner_id=plan.owner_id,
                    artifact_id=descriptor.artifact_id,
                    role=plan.role,
                    created_at=descriptor.created_at,
                )
                SQLiteArtifactPublicationPort(unit).publish(
                    ArtifactPublication(descriptor, (reference,))
                )
                row = {
                    "risk_policy_set_version_id": policy_set.risk_policy_set_version_id,
                    "content_sha256": policy_set.content_sha256,
                    "project_id": project_id,
                    "project_context_revision_id": project_context_revision_id,
                    "context_identity": context_identity,
                    "artifact_id": descriptor.artifact_id,
                    "artifact_reference_id": reference.reference_id,
                    "artifact_sha256": descriptor.sha256,
                    "byte_size": descriptor.byte_size,
                    "schema_version": policy_set.schema_version,
                    "serialization_version": RISK_POLICY_SERIALIZATION_VERSION,
                    "authoring_service_version": authoring_service_version,
                    "code_version": first.code_version,
                    "runtime_profile_id": first.runtime_profile_id,
                    "environment_fingerprint": runtime_identity.environment_fingerprint,
                    "backend": first.backend,
                    "risk_model_requirement": RiskModelRequirement.NOT_REQUIRED.value,
                    "canonical_truth_state": policy_set.truth_admission.truth.value,
                    "canonical_admission_state": policy_set.truth_admission.admission.value,
                    "created_by": authoring_service_version,
                    "published_at": _wire_time(published_at),
                }
                registry.risk.table("risk_policy_set_publication").add_new(row)
        except ConflictError as error:
            existing = self._load_publication(
                "risk_policy_set_publication", policy_set.risk_policy_set_version_id
            )
            if existing is None:
                raise RiskPolicyOwnerAuthorityError(
                    "RiskPolicySetVersion canonical identity/content conflict"
                ) from error
            stable = self._require_same_policy(
                existing,
                policy_set,
                project_id,
                project_context_revision_id,
                runtime_identity,
                authoring_service_version,
            )
            self._validate_existing_payload(stable, payload, RISK_POLICY_PAYLOAD_ROLE)
            return self._risk_publication_from_row(stable)
        finally:
            connection.close()
        row = self._load_publication(
            "risk_policy_set_publication", policy_set.risk_policy_set_version_id
        )
        assert row is not None
        return self._risk_publication_from_row(row)

    def resolve(self, request: PayloadResolutionRequest) -> CanonicalPayloadBinding | None:
        if not isinstance(request, PayloadResolutionRequest):
            raise TypeError("owner resolution requires PayloadResolutionRequest")
        if (
            request.owner_namespace == TARGET_WEIGHT_OWNER_NAMESPACE
            and request.payload_role == TARGET_WEIGHT_PAYLOAD_ROLE
        ):
            table = "target_weight_vector_publication"
            identity_column = "target_weight_vector_id"
        elif (
            request.owner_namespace == RISK_POLICY_OWNER_NAMESPACE
            and request.payload_role == RISK_POLICY_PAYLOAD_ROLE
        ):
            table = "risk_policy_set_publication"
            identity_column = "risk_policy_set_version_id"
        else:
            return None
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                f"""
                SELECT owner.*,artifact.state AS artifact_state,
                       artifact.sha256 AS catalog_sha256,
                       artifact.byte_size AS catalog_byte_size,
                       artifact.schema_fingerprint AS catalog_schema_fingerprint,
                       reference.owner_type AS reference_owner_type,
                       reference.owner_id AS reference_owner_id,
                       reference.role AS reference_role,
                       reference.artifact_id AS reference_artifact_id,
                       reference.state AS reference_state,
                       revision.project_id AS revision_project_id,
                       revision.canonical_hash AS revision_canonical_hash,
                       project.state AS project_state
                FROM {table} AS owner
                JOIN artifact ON artifact.artifact_id=owner.artifact_id
                JOIN artifact_reference AS reference
                  ON reference.artifact_reference_id=owner.artifact_reference_id
                JOIN project_context_revision AS revision
                  ON revision.project_context_revision_id=owner.project_context_revision_id
                JOIN project ON project.project_id=owner.project_id
                WHERE owner.{identity_column}=?
                """,
                (request.owner_id,),
            ).fetchone()
            if row is None:
                return None
            record = {key: row[key] for key in row.keys()}
        finally:
            connection.close()
        expected_owner_type = (
            "TargetWeightVector"
            if table == "target_weight_vector_publication"
            else "RiskPolicySetVersion"
        )
        if (
            record[identity_column] != request.owner_id
            or record["content_sha256"] != request.owner_version
            or record["context_identity"] != request.context_identity
            or record["artifact_state"] != "PUBLISHED"
            or record["catalog_sha256"] != record["artifact_sha256"]
            or record["catalog_byte_size"] != record["byte_size"]
            or record["reference_owner_type"] != expected_owner_type
            or record["reference_owner_id"] != request.owner_id
            or record["reference_role"] != request.payload_role
            or record["reference_artifact_id"] != record["artifact_id"]
            or record["reference_state"] != "ACTIVE"
            or record["revision_project_id"] != record["project_id"]
            or record["project_state"] != "ACTIVE"
            or _owner_context_identity(
                project_id=str(record["project_id"]),
                project_context_revision_id=str(record["project_context_revision_id"]),
                canonical_hash=str(record["revision_canonical_hash"]),
            )
            != record["context_identity"]
        ):
            return None
        return CanonicalPayloadBinding(
            owner_namespace=request.owner_namespace,
            owner_id=request.owner_id,
            owner_version=request.owner_version,
            payload_role=request.payload_role,
            artifact_id=str(record["artifact_id"]),
            expected_sha256=str(record["artifact_sha256"]),
            expected_byte_size=int(record["byte_size"]),
            context_identity=request.context_identity,
            binding_version=OWNER_BINDING_VERSION,
            schema_fingerprint=(
                None
                if record["catalog_schema_fingerprint"] is None
                else str(record["catalog_schema_fingerprint"])
            ),
            semantic_fingerprint=str(record["content_sha256"]),
            provenance_reference_id=request.owner_id,
        )

    def _load_publication(self, table: str, identity: str):
        identity_columns = {
            "target_weight_vector_publication": "target_weight_vector_id",
            "risk_policy_set_publication": "risk_policy_set_version_id",
        }
        try:
            identity_column = identity_columns[table]
        except KeyError as error:
            raise ValueError(f"unsupported owner publication table: {table}") from error
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {identity_column}=?",
                (identity,),
            ).fetchone()
            return None if row is None else {key: row[key] for key in row.keys()}
        finally:
            connection.close()

    def _validate_existing_payload(self, row, expected_payload: bytes, role: str) -> None:
        expected_sha256 = hashlib.sha256(expected_payload).hexdigest()
        if (
            row.get("artifact_sha256") != expected_sha256
            or row.get("byte_size") != len(expected_payload)
        ):
            raise ValueError("persisted canonical owner payload metadata conflicts")
        connection = self._connection(read_only=True)
        try:
            artifact = connection.execute(
                """
                SELECT sha256,byte_size,semantic_role,state
                FROM artifact WHERE artifact_id=?
                """,
                (row["artifact_id"],),
            ).fetchone()
        finally:
            connection.close()
        if artifact is None or tuple(artifact) != (
            expected_sha256,
            len(expected_payload),
            role,
            "PUBLISHED",
        ):
            raise ValueError("persisted canonical owner Artifact metadata conflicts")
        observed = self.store.read_bytes(str(row["artifact_id"]), max_bytes=len(expected_payload))
        if observed != expected_payload:
            raise ValueError("persisted canonical owner bytes conflict")

    @staticmethod
    def _require_same_target(row, target, project_id, project_context_revision_id):
        expected = {
            "content_sha256": target.content_sha256,
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "portfolio_intent_id": target.source.portfolio_intent_id,
            "portfolio_intent_content_sha256": target.source.portfolio_intent_content_sha256,
            "portfolio_intent_provenance_sha256": target.source.portfolio_intent_provenance_sha256,
            "source_reference_sha256": target.source.source_reference_sha256,
            "source_owner_receipt_resolution": target.source.owner_receipt_resolution,
            "construction_spec_id": target.construction_spec.source_id,
            "construction_spec_content_sha256": target.construction_spec.content_sha256,
            "universe_version_id": target.source.universe_version_id,
            "membership_artifact_id": target.source.membership_artifact_id,
            "membership_sha256": target.source.membership_sha256,
            "schema_version": target.schema_version,
            "serialization_version": TARGET_WEIGHT_SERIALIZATION_VERSION,
            "canonical_truth_state": target.truth_admission.truth.value,
            "canonical_admission_state": target.truth_admission.admission.value,
            "created_by": _TARGET_CREATED_BY,
        }
        if any(row.get(key) != value for key, value in expected.items()):
            raise TargetWeightOwnerAuthorityError(
                "same TargetWeight canonical identity has conflicting content/context"
            )
        return row

    @staticmethod
    def _require_same_policy(
        row,
        policy_set,
        project_id,
        project_context_revision_id,
        runtime_identity,
        authoring_service_version,
    ):
        first = policy_set.policies[0]
        expected = {
            "content_sha256": policy_set.content_sha256,
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "schema_version": policy_set.schema_version,
            "serialization_version": RISK_POLICY_SERIALIZATION_VERSION,
            "authoring_service_version": authoring_service_version,
            "code_version": first.code_version,
            "runtime_profile_id": first.runtime_profile_id,
            "environment_fingerprint": runtime_identity.environment_fingerprint,
            "backend": first.backend,
            "risk_model_requirement": RiskModelRequirement.NOT_REQUIRED.value,
            "canonical_truth_state": policy_set.truth_admission.truth.value,
            "canonical_admission_state": policy_set.truth_admission.admission.value,
            "created_by": authoring_service_version,
        }
        if any(row.get(key) != value for key, value in expected.items()):
            raise RiskPolicyOwnerAuthorityError(
                "same RiskPolicySetVersion canonical identity has conflicting content/context"
            )
        return row

    @staticmethod
    def _target_publication_from_row(row) -> TargetWeightOwnerPublication:
        return TargetWeightOwnerPublication(
            target_weight_vector_id=str(row["target_weight_vector_id"]),
            content_sha256=str(row["content_sha256"]),
            project_id=str(row["project_id"]),
            project_context_revision_id=str(row["project_context_revision_id"]),
            context_identity=str(row["context_identity"]),
            artifact_id=str(row["artifact_id"]),
            artifact_sha256=str(row["artifact_sha256"]),
            byte_size=int(row["byte_size"]),
            schema_version=str(row["schema_version"]),
            serialization_version=str(row["serialization_version"]),
            canonical_truth_state=str(row["canonical_truth_state"]),
            canonical_admission_state=str(row["canonical_admission_state"]),
            published_at=_parse_time(str(row["published_at"])),
        )

    @staticmethod
    def _risk_publication_from_row(row) -> RiskPolicySetOwnerPublication:
        return RiskPolicySetOwnerPublication(
            risk_policy_set_version_id=str(row["risk_policy_set_version_id"]),
            content_sha256=str(row["content_sha256"]),
            project_id=str(row["project_id"]),
            project_context_revision_id=str(row["project_context_revision_id"]),
            context_identity=str(row["context_identity"]),
            artifact_id=str(row["artifact_id"]),
            artifact_sha256=str(row["artifact_sha256"]),
            byte_size=int(row["byte_size"]),
            schema_version=str(row["schema_version"]),
            serialization_version=str(row["serialization_version"]),
            risk_model_requirement=str(row["risk_model_requirement"]),
            canonical_truth_state=str(row["canonical_truth_state"]),
            canonical_admission_state=str(row["canonical_admission_state"]),
            published_at=_parse_time(str(row["published_at"])),
        )


__all__ = ["OWNER_BINDING_VERSION", "SQLitePortfolioRiskPolicyOwner"]
