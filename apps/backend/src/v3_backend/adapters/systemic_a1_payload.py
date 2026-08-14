"""Thin A1 adapters over canonical owner objects, P1, and the Artifact Store."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import json
from typing import Protocol
from v3_backend.domain.artifacts.model import ArtifactDescriptor
from v3_backend.domain.data_truth.formal import CanonicalSnapshotRepository
from v3_backend.domain.datasets.formal import (
    DATASET_ARTIFACT_ROLE,
    FEATURE_VALUES_PAYLOAD_ROLE,
    LABEL_PAYLOAD_ROLE,
    LABEL_SOURCE_PAYLOAD_ROLE,
    CanonicalLabelPayloadRepository,
    CanonicalHistoricalLabelSource,
    FormalFeatureMaterializationRepository,
    FormalDatasetRepository,
    feature_output_context_identity,
    formal_dataset_context_identity,
    label_source_payload_context_identity,
)
from v3_backend.domain.factors.formal import (
    FACTOR_INPUT_PAYLOAD_ROLE,
    CanonicalJsonArtifactPublisher,
    FactorPayloadContextRepository,
    FactorInputPayload,
    factor_payload_context_identity,
)
from v3_backend.domain.payload_authority import CanonicalPayloadBinding, PayloadResolutionRequest
from v3_backend.provenance.canonical_hash import canonical_json_bytes


_CANONICAL_JSON_ARTIFACT_ROLE = "PARQUET_DATASET_MANIFEST"


class LabelPayloadContextRepository(Protocol):
    def get_label_context(self, context_identity: str): ...


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
        label_contexts: LabelPayloadContextRepository | None = None,
        datasets: FormalDatasetRepository | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._factor_contexts = factor_contexts
        self._materializations = materializations
        self._label_payloads = label_payloads
        self._label_contexts = label_contexts
        self._datasets = datasets

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
        if request.owner_namespace == "v3.data_truth.snapshot" and request.payload_role == LABEL_SOURCE_PAYLOAD_ROLE:
            owner = self._snapshots.get_snapshot(request.owner_id)
            if owner is None or request.owner_version != owner.snapshot_id or self._label_contexts is None:
                return None
            context = self._label_contexts.get_label_context(request.context_identity)
            if context is None:
                return None
            snapshot, universe, label_spec = context
            exact_context = label_source_payload_context_identity(
                snapshot=snapshot, universe=universe, label_spec=label_spec
            )
            if snapshot != owner or request.context_identity != exact_context:
                return None
            return CanonicalPayloadBinding(
                owner_namespace=request.owner_namespace,
                owner_id=owner.snapshot_id,
                owner_version=owner.snapshot_id,
                payload_role=LABEL_SOURCE_PAYLOAD_ROLE,
                artifact_id=owner.payload_artifact_id,
                expected_sha256=owner.payload_sha256,
                expected_byte_size=owner.payload_byte_size,
                context_identity=exact_context,
                binding_version=self.binding_version,
                schema_fingerprint=owner.schema_fingerprint,
                semantic_fingerprint=label_spec.label_spec_id,
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
            owner = self._label_payloads.get_label_payload(request.owner_id, request.context_identity)
            if owner is None or request.owner_version != owner.label_payload_id or request.context_identity != owner.context_identity:
                return None
            return CanonicalPayloadBinding(
                owner_namespace=request.owner_namespace,
                owner_id=owner.label_spec_id,
                owner_version=owner.label_payload_id,
                payload_role=LABEL_PAYLOAD_ROLE,
                artifact_id=owner.artifact_id,
                expected_sha256=owner.sha256,
                expected_byte_size=owner.byte_size,
                context_identity=owner.context_identity,
                binding_version=self.binding_version,
                schema_fingerprint=owner.schema_fingerprint,
                semantic_fingerprint=owner.label_spec_id,
                provenance_reference_id=owner.source_receipt.receipt_identity,
            )
        if request.owner_namespace == "v3.datasets.formal" and request.payload_role == DATASET_ARTIFACT_ROLE:
            if self._datasets is None:
                return None
            owner = self._datasets.get_dataset(request.owner_id)
            if owner is None or request.owner_version != owner.dataset_version_id:
                return None
            exact_context = formal_dataset_context_identity(owner)
            if request.context_identity != exact_context:
                return None
            descriptor = owner.dataset_descriptor
            return CanonicalPayloadBinding(
                owner_namespace=request.owner_namespace,
                owner_id=owner.dataset_version_id,
                owner_version=owner.dataset_version_id,
                payload_role=DATASET_ARTIFACT_ROLE,
                artifact_id=descriptor.artifact_id,
                expected_sha256=descriptor.sha256,
                expected_byte_size=descriptor.byte_size,
                context_identity=exact_context,
                binding_version=self.binding_version,
                schema_fingerprint=owner.dataset_schema_fingerprint,
                semantic_fingerprint=owner.label_payload_id,
                provenance_reference_id=owner.label_receipt.receipt_identity,
            )
        if request.owner_namespace == "v3.datasets" and request.payload_role == DATASET_ARTIFACT_ROLE:
            return self._resolve_dataset(request)
        return None

    def _resolve_dataset(self, request: PayloadResolutionRequest) -> CanonicalPayloadBinding | None:
        if self._datasets is None:
            return None
        owner = self._datasets.get_dataset(request.owner_id)
        if (
            owner is None
            or request.owner_version != owner.dataset_version_id
            or request.context_identity != owner.dataset_version_id
        ):
            return None
        descriptor = owner.dataset_descriptor
        return CanonicalPayloadBinding(
            owner_namespace=request.owner_namespace,
            owner_id=owner.dataset_version_id,
            owner_version=owner.dataset_version_id,
            payload_role=DATASET_ARTIFACT_ROLE,
            artifact_id=descriptor.artifact_id,
            expected_sha256=descriptor.sha256,
            expected_byte_size=descriptor.byte_size,
            context_identity=owner.dataset_version_id,
            binding_version=self.binding_version,
            schema_fingerprint=owner.dataset_schema_fingerprint,
            semantic_fingerprint=owner.split_spec_id,
            provenance_reference_id=owner.label_receipt.receipt_identity,
        )


class FileSystemCanonicalJsonArtifactPublisher(CanonicalJsonArtifactPublisher):
    """Publishes through the existing Artifact Store; no alternate byte store."""

    def __init__(self, store, *, descriptor_sink=None) -> None:
        self._store = store
        self._descriptor_sink = descriptor_sink

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
            "CANONICAL_OWNER_RECORD",
            "ALPHA_RESEARCH_METRICS",
            "ALPHA_RESEARCH_REVIEW",
            "ALPHA_RESEARCH_RUN",
            "ALPHA_RESEARCH_RESULT",
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
        if self._descriptor_sink is not None:
            self._descriptor_sink.register_descriptor(result.descriptor)
        return result.descriptor


class A1CanonicalHistoricalLabelSource(CanonicalHistoricalLabelSource):
    """Resolves source values through P1 and reuses the accepted Factor decoder."""

    def __init__(self, *, payload_resolver) -> None:
        self._resolver = payload_resolver

    def resolve_label_source(self, *, snapshot, universe, label_spec, max_bytes):
        context = label_source_payload_context_identity(
            snapshot=snapshot, universe=universe, label_spec=label_spec
        )
        result = self._resolver.resolve(
            PayloadResolutionRequest(
                owner_namespace="v3.data_truth.snapshot",
                owner_id=snapshot.snapshot_id,
                owner_version=snapshot.snapshot_id,
                payload_role=LABEL_SOURCE_PAYLOAD_ROLE,
                context_identity=context,
                max_bytes=max_bytes,
            )
        )
        decoded = FactorInputPayload.decode_verified_source_field(
            result.verified_payload.payload,
            snapshot=snapshot,
            universe=universe,
            source_field=label_spec.source_field,
        )
        raw = json.loads(result.verified_payload.payload.decode("utf-8"))
        field = next(
            (value for value in raw["fields"] if value.get("name") == label_spec.source_field),
            None,
        )
        if field is None:
            raise ValueError("verified canonical historical payload lacks LabelSpec source_field")
        raw_values = field.get("values")
        if not isinstance(raw_values, list) or len(raw_values) != len(decoded.instrument_ids) * len(decoded.observation_ids):
            raise ValueError("verified canonical historical Label source shape differs")
        return (
            decoded.instrument_ids,
            decoded.observation_ids,
            tuple(None if value is None else Decimal(value) for value in raw_values),
            result.receipt,
        )


__all__ = [
    "A1CanonicalPayloadBindingResolver",
    "A1CanonicalHistoricalLabelSource",
    "FileSystemCanonicalJsonArtifactPublisher",
]
