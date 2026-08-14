"""Artifact Store adapter for the bounded Model research pipeline."""

from __future__ import annotations

from collections.abc import Mapping

from v3_backend.domain.artifacts.model import ArtifactDescriptor
from v3_backend.domain.models.model import SafeLinearModelArtifact
from v3_backend.domain.models.pipeline import ModelArtifactPublication
from v3_backend.provenance.canonical_hash import canonical_json_bytes


MODEL_PIPELINE_RECORD_ROLE = "MODEL_PIPELINE_RECORD"
MODEL_SAFE_LINEAR_ROLE = "MODEL_SAFE_LINEAR"


class FileSystemModelPipelineArtifactPublisher:
    """Publishes Model outputs through the existing content-addressed store."""

    def __init__(self, store) -> None:
        self._store = store

    def publish_record(
        self,
        payload: Mapping[str, object],
        publication: ModelArtifactPublication,
    ) -> ArtifactDescriptor:
        return self._publish(
            canonical_json_bytes(payload),
            media_type="application/json",
            role=MODEL_PIPELINE_RECORD_ROLE,
            publication=publication,
        )

    def publish_safe_model(
        self,
        artifact: SafeLinearModelArtifact,
        publication: ModelArtifactPublication,
    ) -> ArtifactDescriptor:
        descriptor = self._publish(
            artifact.to_bytes(),
            media_type=artifact.media_type,
            role=MODEL_SAFE_LINEAR_ROLE,
            publication=publication,
        )
        if descriptor.artifact_id != artifact.artifact_id:
            raise ValueError("published safe model bytes differ from ModelVersion artifact")
        return descriptor

    def _publish(
        self,
        payload: bytes,
        *,
        media_type: str,
        role: str,
        publication: ModelArtifactPublication,
    ) -> ArtifactDescriptor:
        staged = self._store.stage_bytes(payload)
        return self._store.publish(
            staged.staging_token,
            expected_sha256=staged.sha256,
            expected_byte_size=staged.byte_size,
            media_type=media_type,
            role=role,
            provenance_entity_id=publication.provenance_entity_id,
            schema_fingerprint=publication.schema_fingerprint,
            semantic_fingerprint=publication.semantic_fingerprint,
        ).descriptor


__all__ = [
    "FileSystemModelPipelineArtifactPublisher",
    "MODEL_PIPELINE_RECORD_ROLE",
    "MODEL_SAFE_LINEAR_ROLE",
]
