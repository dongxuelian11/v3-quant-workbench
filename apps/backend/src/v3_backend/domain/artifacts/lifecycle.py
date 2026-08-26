"""Durable state vocabulary for Artifact promotion and two-phase GC.

The filesystem and Catalog are separate durability domains.  These value
objects keep the transition vocabulary and confirmation fingerprints stable so
adapters cannot silently invent a weaker state machine.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from v3_backend.provenance.canonical_hash import canonical_json_bytes

from .exceptions import GarbageCollectionSafetyError
from .identity import sha256_from_artifact_id


PROMOTION_STATES = (
    "STAGED_SYNCED",
    "FINAL_PRESENT",
    "CATALOG_COMMITTED",
    "CLEANUP_PENDING",
    "FINALIZED",
    "FAILED",
)
PROMOTION_TERMINAL_STATES = frozenset({"FINALIZED", "FAILED"})
PROMOTION_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "STAGED_SYNCED": frozenset({"FINAL_PRESENT", "FAILED"}),
    "FINAL_PRESENT": frozenset({"CATALOG_COMMITTED", "FAILED"}),
    "CATALOG_COMMITTED": frozenset({"CLEANUP_PENDING", "FINALIZED", "FAILED"}),
    "CLEANUP_PENDING": frozenset({"FINALIZED", "FAILED"}),
    "FINALIZED": frozenset(),
    "FAILED": frozenset(),
}

GC_BATCH_STATES = (
    "PLANNED",
    "CONFIRMED",
    "EXECUTING",
    "COMPLETED",
    "STALE",
    "FAILED",
)
GC_BATCH_TERMINAL_STATES = frozenset({"COMPLETED", "STALE", "FAILED"})
GC_BATCH_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "PLANNED": frozenset({"CONFIRMED", "STALE"}),
    "CONFIRMED": frozenset({"EXECUTING", "STALE"}),
    "EXECUTING": frozenset({"COMPLETED", "FAILED"}),
    "COMPLETED": frozenset(),
    "STALE": frozenset(),
    "FAILED": frozenset(),
}


def exact_artifact_ids_hash(artifact_ids: tuple[str, ...] | list[str]) -> str:
    """Hash the sorted, unique Artifact IDs that a destructive action covers."""

    normalized = tuple(sorted(str(value) for value in artifact_ids))
    if len(set(normalized)) != len(normalized):
        raise GarbageCollectionSafetyError("exact Artifact ID set contains duplicates")
    for artifact_id in normalized:
        sha256_from_artifact_id(artifact_id)
    return hashlib.sha256(canonical_json_bytes(list(normalized))).hexdigest()


def gc_confirmation_hash(
    *, plan_artifact_id: str, exact_ids_hash: str, confirmation_nonce: str
) -> str:
    """Derive the short-lived confirmation proof from exact user inputs."""

    sha256_from_artifact_id(plan_artifact_id)
    if not isinstance(exact_ids_hash, str) or len(exact_ids_hash) != 64:
        raise GarbageCollectionSafetyError("GC confirmation requires an exact ID-set hash")
    if not isinstance(confirmation_nonce, str) or not confirmation_nonce:
        raise GarbageCollectionSafetyError("GC confirmation requires a nonce")
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "plan_artifact_id": plan_artifact_id,
                "exact_artifact_ids_hash": exact_ids_hash,
                "confirmation_nonce": confirmation_nonce,
            }
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ArtifactPromotionIntent:
    promotion_intent_id: str
    artifact_id: str
    expected_sha256: str
    expected_byte_size: int
    staging_token: str
    staging_key: str
    final_storage_key: str
    state: str = "STAGED_SYNCED"
    state_version: int = 1

    def __post_init__(self) -> None:
        sha256_from_artifact_id(self.artifact_id)
        if self.artifact_id != "art_sha256_" + self.expected_sha256:
            raise ValueError("promotion intent Artifact ID does not match expected SHA-256")
        if not isinstance(self.expected_byte_size, int) or isinstance(self.expected_byte_size, bool):
            raise ValueError("promotion intent byte size must be an integer")
        if self.expected_byte_size < 0:
            raise ValueError("promotion intent byte size cannot be negative")
        if self.state not in PROMOTION_STATES:
            raise ValueError("unknown Artifact promotion state")
        if not isinstance(self.state_version, int) or isinstance(self.state_version, bool):
            raise ValueError("promotion intent state_version must be an integer")
        if self.state_version < 1:
            raise ValueError("promotion intent state_version must be positive")

    def transition(self, target_state: str) -> "ArtifactPromotionIntent":
        if target_state not in PROMOTION_STATES:
            raise ValueError("unknown Artifact promotion state")
        if target_state == self.state:
            return self
        if target_state not in PROMOTION_TRANSITIONS[self.state]:
            raise ValueError(f"invalid Artifact promotion transition: {self.state}->{target_state}")
        return ArtifactPromotionIntent(
            promotion_intent_id=self.promotion_intent_id,
            artifact_id=self.artifact_id,
            expected_sha256=self.expected_sha256,
            expected_byte_size=self.expected_byte_size,
            staging_token=self.staging_token,
            staging_key=self.staging_key,
            final_storage_key=self.final_storage_key,
            state=target_state,
            state_version=self.state_version + 1,
        )
