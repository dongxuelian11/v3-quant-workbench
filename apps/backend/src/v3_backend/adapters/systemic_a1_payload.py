"""Thin A1 adapters over canonical owner objects, P1, and the Artifact Store."""

from __future__ import annotations

from collections.abc import Mapping
from v3_backend.domain.artifacts.model import ArtifactDescriptor
from v3_backend.domain.data_truth.formal import CanonicalSnapshotRepository
from v3_backend.domain.datasets.formal import (
    FEATURE_VALUES_PAYLOAD_ROLE,
    LABEL_PAYLOAD_ROLE,
    CanonicalLabelPayloadRepository,
    FormalFeatureMaterializationRepository,
    feature_output_context_identity,
)
from v3_backend.domain.factors.formal import (
    FACTOR_INPUT_PAYLOAD_ROLE,
    CanonicalJsonArtifactPublisher,
    FactorPayloadContextRepository,
    factor_payload_context_identity,
)
from v3_backend.domain.payload_authority import CanonicalPayloadBinding, PayloadResolutionRequest
from v3_backend.provenance.canonical_hash import canonical_json_bytes


_CANONICAL_JSON_ARTIFACT_ROLE = "PARQUET_DATASET_MANIFEST"


class A1CanonicalPayloadBindingResolver:
    """Owner-specific binding adapter; P1 remains the only byte verifier."""

    binding_version = "v3.systemic-a1-owner-binding/1.0.0"

    def __init__(
        self,
        *,
        snapshots: CanonicalSnapshotRepository,
        factor_contexts: FactorPayloadContextRepository,
        materializations: FormalFeatureMaterializationRepository,
        label_payloads: CanonicalLabelPayloadRepository,
    ) -> None:
        self._snapshots = snapshots
        self._factor_contexts = factor_contexts
        self._materializations = materializations
        self._label_payloads = label_payloads

    def resolve(self, request: PayloadResolutionRequest) -> CanonicalPayloadBinding | None:
        if request.owner_namespace == "v3.data_truth.snapshot" and request.payload_role == FACTOR_INPUT_PAYLOAD_ROLE:
            owner = self._snapshots.get_snapshot(request.owner_id)
            if owner is None or request.owner_version != owner.snapshot_id:
                return None
            context = self._factor_contexts.get_factor_context(request.context_identity)
            if context is None:
                return None
            snapshot, universe, definition = context
            exact_context = factor_payload_context_identity(snapshot=snapshot, universe=universe, definition=definition)
            if snapshot != owner or request.context_identity != exact_context:
                return None
            return CanonicalPayloadBinding(
                owner_namespace=request.owner_namespace,
                owner_id=owner.snapshot_id,
                owner_version=owner.snapshot_id,
                payload_role=FACTOR_INPUT_PAYLOAD_ROLE,
                artifact_id=owner.payload_artifact_id,
                expected_sha256=owner.payload_sha256,
                expected_byte_size=owner.payload_byte_size,
                context_identity=exact_context,
                binding_version=self.binding_version,
                schema_fingerprint=owner.schema_fingerprint,
                semantic_fingerprint=owner.source_data_truth_id,
                provenance_reference_id=owner.snapshot_id,
            )
        if request.owner_namespace == "v3.factors.materialization" and request.payload_role == FEATURE_VALUES_PAYLOAD_ROLE:
            owner = self._materializations.get_materialization(request.owner_id)
            if owner is None or request.owner_version != owner.feature_materialization_id:
                return None
            if request.context_identity != feature_output_context_identity(owner):
                return None
            descriptor = owner.output_descriptor
            return CanonicalPayloadBinding(
                owner_namespace=request.owner_namespace,
                owner_id=owner.feature_materialization_id,
                owner_version=owner.feature_materialization_id,
                payload_role=FEATURE_VALUES_PAYLOAD_ROLE,
                artifact_id=descriptor.artifact_id,
                expected_sha256=descriptor.sha256,
                expected_byte_size=descriptor.byte_size,
                context_identity=request.context_identity,
                binding_version=self.binding_version,
                schema_fingerprint=owner.output_schema_fingerprint,
                semantic_fingerprint=owner.factor_definition_version_id,
                provenance_reference_id=owner.input_receipt.receipt_identity,
            )
        if request.owner_namespace == "v3.data_truth.labels" and request.payload_role == LABEL_PAYLOAD_ROLE:
            owner = self._label_payloads.get_label_payload(request.owner_id)
            if owner is None or request.owner_version != owner.label_spec_id or request.context_identity != owner.context_identity:
                return None
            return CanonicalPayloadBinding(
                owner_namespace=request.owner_namespace,
                owner_id=owner.label_spec_id,
                owner_version=owner.label_spec_id,
                payload_role=LABEL_PAYLOAD_ROLE,
                artifact_id=owner.artifact_id,
                expected_sha256=owner.sha256,
                expected_byte_size=owner.byte_size,
                context_identity=owner.context_identity,
                binding_version=self.binding_version,
                schema_fingerprint=owner.schema_fingerprint,
                semantic_fingerprint=owner.label_spec_id,
                provenance_reference_id=owner.artifact_id,
            )
        return None


class FileSystemCanonicalJsonArtifactPublisher(CanonicalJsonArtifactPublisher):
    """Publishes through the existing Artifact Store; no alternate byte store."""

    def __init__(self, store) -> None:
        self._store = store

    def publish_canonical_json(
        self,
        payload: Mapping[str, object],
        *,
        semantic_role: str,
        provenance_entity_id: str,
        schema_fingerprint: str,
    ) -> ArtifactDescriptor:
        if semantic_role not in {
            "FACTOR_INPUT",
            "FEATURE_MATERIALIZATION",
            "DATASET_LABELS",
            "DATASET_SAMPLES",
        }:
            raise ValueError("A1 canonical JSON publisher received an unsupported semantic role")
        encoded = canonical_json_bytes(payload)
        staged = self._store.stage_bytes(encoded)
        result = self._store.publish(
            staged.staging_token,
            expected_sha256=staged.sha256,
            expected_byte_size=staged.byte_size,
            media_type="application/json",
            role=_CANONICAL_JSON_ARTIFACT_ROLE,
            provenance_entity_id=provenance_entity_id,
            schema_fingerprint=schema_fingerprint,
            semantic_fingerprint=f"{semantic_role}:{provenance_entity_id}",
        )
        return result.descriptor


__all__ = [
    "A1CanonicalPayloadBindingResolver",
    "FileSystemCanonicalJsonArtifactPublisher",
]
