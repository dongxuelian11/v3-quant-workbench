
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from v3_backend.provenance.canonical_hash import canonical_sha256

from .dto import validate_schema
from .ids import validate_v3_id


_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class ProvenanceRelationship(str, Enum):
    GENERATED_FROM = "GENERATED_FROM"
    USED = "USED"
    DERIVED_FROM = "DERIVED_FROM"


@dataclass(frozen=True)
class ProvenanceRecordV1:
    entity_id: str
    subject_id: str
    subject_fingerprint: str
    request_actor: str
    project_context_revision_id: str
    operation_id: str
    contract_version: str
    input_object_ids: tuple[str, ...]
    input_content_hashes: tuple[str, ...]
    environment_profile_id: str
    code_version: str
    recorded_at: str

    def __post_init__(self) -> None:
        validate_v3_id(self.entity_id, "ProvenanceEntity")
        validate_v3_id(self.subject_id)
        validate_v3_id(self.project_context_revision_id, "ProjectContextRevision")
        for item in self.input_object_ids:
            validate_v3_id(item)
        for path, value in (("subject_fingerprint", self.subject_fingerprint), *[("input_content_hashes", item) for item in self.input_content_hashes]):
            if _SHA256_RE.fullmatch(value) is None:
                raise ValueError(f"{path} must be lowercase SHA-256")
        if not self.operation_id or not self.contract_version or not self.request_actor:
            raise ValueError("operation_id, contract_version and request_actor are required")
        validate_schema(self.recorded_at, {"type": "string", "format": "date-time"}, "$.recorded_at")

    def to_wire(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "subject_id": self.subject_id,
            "subject_fingerprint": self.subject_fingerprint,
            "request_actor": self.request_actor,
            "project_context_revision_id": self.project_context_revision_id,
            "operation_id": self.operation_id,
            "contract_version": self.contract_version,
            "input_object_ids": list(self.input_object_ids),
            "input_content_hashes": list(self.input_content_hashes),
            "environment_profile_id": self.environment_profile_id,
            "code_version": self.code_version,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True)
class ProvenanceEdgeV1:
    edge_id: str
    source_entity_id: str
    target_entity_id: str
    relationship: ProvenanceRelationship
    ordinal: int = 0

    def __post_init__(self) -> None:
        validate_v3_id(self.edge_id, "ProvenanceEdge")
        validate_v3_id(self.source_entity_id, "ProvenanceEntity")
        validate_v3_id(self.target_entity_id, "ProvenanceEntity")
        if not isinstance(self.relationship, ProvenanceRelationship):
            object.__setattr__(self, "relationship", ProvenanceRelationship(self.relationship))
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")

    @property
    def canonical_sort_key(self) -> tuple[str, str, str, int, str]:
        return (
            self.source_entity_id,
            self.relationship.value,
            self.target_entity_id,
            self.ordinal,
            self.edge_id,
        )

    @property
    def canonical_fingerprint(self) -> str:
        return canonical_sha256(self.to_wire())

    def to_wire(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_entity_id": self.source_entity_id,
            "target_entity_id": self.target_entity_id,
            "relationship": self.relationship.value,
            "ordinal": self.ordinal,
        }


def sort_provenance_edges(edges: tuple[ProvenanceEdgeV1, ...] | list[ProvenanceEdgeV1]) -> tuple[ProvenanceEdgeV1, ...]:
    return tuple(sorted(edges, key=lambda edge: edge.canonical_sort_key))
