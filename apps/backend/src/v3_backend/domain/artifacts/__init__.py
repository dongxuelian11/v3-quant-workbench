"""Content-addressed artifact domain primitives."""

from .exceptions import (
    ArtifactCollision,
    ArtifactError,
    CapabilityUnavailable,
    DescriptorConflict,
    FormatRejected,
    GarbageCollectionSafetyError,
    IntegrityMismatch,
    InvalidArtifactIdentity,
    StagingNotFound,
)
from .identity import (
    artifact_id_for_bytes,
    artifact_id_from_sha256,
    sha256_from_artifact_id,
    storage_key_for_artifact_id,
    storage_key_for_sha256,
)
from .model import (
    ArtifactDescriptor,
    ArtifactReference,
    StreamTicketDescriptor,
    ensure_descriptor_immutable,
)

__all__ = (
    "ArtifactCollision",
    "ArtifactDescriptor",
    "ArtifactError",
    "ArtifactReference",
    "CapabilityUnavailable",
    "DescriptorConflict",
    "FormatRejected",
    "GarbageCollectionSafetyError",
    "IntegrityMismatch",
    "InvalidArtifactIdentity",
    "StagingNotFound",
    "StreamTicketDescriptor",
    "artifact_id_for_bytes",
    "artifact_id_from_sha256",
    "ensure_descriptor_immutable",
    "sha256_from_artifact_id",
    "storage_key_for_artifact_id",
    "storage_key_for_sha256",
)
