"""Publish field capability policy bytes through the accepted Artifact Store."""

from __future__ import annotations

import hashlib
from datetime import datetime

from ...domain.data_truth.capabilities import (
    FIELD_CAPABILITY_POLICY_ROLE,
    FIELD_CAPABILITY_POLICY_SCHEMA_FINGERPRINT,
    FieldCapabilityPolicy,
)
from ...domain.data_truth.resolution import (
    SOURCE_AUTHORITY_EVIDENCE_ROLE,
    SOURCE_AUTHORITY_EVIDENCE_SCHEMA_FINGERPRINT,
    SourceAuthorityEvidence,
)
from ..artifact_store.filesystem import FileSystemArtifactStore, PublicationResult


def publish_field_capability_policy(
    store: FileSystemArtifactStore,
    policy: FieldCapabilityPolicy,
    *,
    provenance_entity_id: str,
    published_at: datetime,
) -> PublicationResult:
    """Persist exact canonical policy bytes; Catalog binding remains existing authority."""

    payload = policy.artifact_bytes
    digest = hashlib.sha256(payload).hexdigest()
    if policy.policy_artifact_id != "art_sha256_" + digest:
        raise ValueError("field capability policy identity is not byte-derived")
    staged = store.stage_bytes(payload)
    return store.publish(
        staged.staging_token,
        expected_sha256=digest,
        expected_byte_size=len(payload),
        media_type="application/json",
        role=FIELD_CAPABILITY_POLICY_ROLE,
        provenance_entity_id=provenance_entity_id,
        schema_fingerprint=FIELD_CAPABILITY_POLICY_SCHEMA_FINGERPRINT,
        semantic_fingerprint=policy.policy_identity,
        published_at=published_at,
    )


def publish_source_authority_evidence(
    store: FileSystemArtifactStore,
    evidence: SourceAuthorityEvidence,
    *,
    provenance_entity_id: str,
    published_at: datetime,
) -> PublicationResult:
    """Persist the exact bytes later resolved inside the formal conflict boundary."""

    payload = evidence.artifact_bytes
    digest = hashlib.sha256(payload).hexdigest()
    if evidence.artifact_id != "art_sha256_" + digest:
        raise ValueError("source authority evidence identity is not byte-derived")
    staged = store.stage_bytes(payload)
    return store.publish(
        staged.staging_token,
        expected_sha256=digest,
        expected_byte_size=len(payload),
        media_type="application/json",
        role=SOURCE_AUTHORITY_EVIDENCE_ROLE,
        provenance_entity_id=provenance_entity_id,
        schema_fingerprint=SOURCE_AUTHORITY_EVIDENCE_SCHEMA_FINGERPRINT,
        semantic_fingerprint=evidence.artifact_id,
        published_at=published_at,
    )
