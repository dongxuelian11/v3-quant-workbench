"""Immutable artifact descriptors, references, and stream-ticket shapes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .exceptions import DescriptorConflict, InvalidArtifactIdentity
from .identity import artifact_id_from_sha256, storage_key_for_artifact_id, validate_sha256


_REFERENCE_ID_RE = re.compile(r"arf_[0-9A-HJKMNP-TV-Z]{26}")


def _require_aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _wire_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    artifact_id: str
    sha256: str
    byte_size: int
    media_type: str
    role: str
    created_at: datetime
    published_at: datetime
    provenance_entity_id: str
    safe_format_id: str | None = None
    schema_fingerprint: str | None = None
    semantic_fingerprint: str | None = None
    state: str = "PUBLISHED"

    def __post_init__(self) -> None:
        validate_sha256(self.sha256)
        if self.artifact_id != artifact_id_from_sha256(self.sha256):
            raise InvalidArtifactIdentity("artifact_id and sha256 must identify the same bytes")
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool) or self.byte_size < 0:
            raise ValueError("byte_size must be a non-negative integer")
        if not isinstance(self.media_type, str) or "/" not in self.media_type:
            raise ValueError("media_type must be a MIME type")
        if not self.role or not isinstance(self.role, str):
            raise ValueError("role must not be empty")
        if not self.provenance_entity_id or not isinstance(self.provenance_entity_id, str):
            raise ValueError("provenance_entity_id must not be empty")
        if self.state != "PUBLISHED":
            raise ValueError("a durable descriptor must be PUBLISHED")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.published_at, "published_at")
        if self.published_at < self.created_at:
            raise ValueError("published_at cannot precede created_at")
        for name in ("safe_format_id", "schema_fingerprint", "semantic_fingerprint"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be non-empty when present")

    @property
    def storage_key(self) -> str:
        return storage_key_for_artifact_id(self.artifact_id)

    def to_wire(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "role": self.role,
            "created_at": _wire_time(self.created_at),
            "published_at": _wire_time(self.published_at),
            "provenance_entity_id": self.provenance_entity_id,
            "state": self.state,
        }
        for name in ("safe_format_id", "schema_fingerprint", "semantic_fingerprint"):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        return result

    def to_artifact_ref(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "role": self.role,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
        }
        if self.schema_fingerprint is not None:
            result["schema_fingerprint"] = self.schema_fingerprint
        return result


def ensure_descriptor_immutable(existing: ArtifactDescriptor, candidate: ArtifactDescriptor) -> None:
    """Reject a metadata rewrite for an already-published byte identity."""

    if existing.artifact_id != candidate.artifact_id:
        return
    immutable_fields = (
        "sha256",
        "byte_size",
        "media_type",
        "role",
        "created_at",
        "provenance_entity_id",
        "safe_format_id",
        "schema_fingerprint",
        "semantic_fingerprint",
    )
    changed = [field for field in immutable_fields if getattr(existing, field) != getattr(candidate, field)]
    if changed:
        raise DescriptorConflict("published descriptor is immutable; changed: " + ", ".join(changed))


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    reference_id: str
    owner_id: str
    artifact_id: str
    role: str
    created_at: datetime
    state: str = "ACTIVE"
    released_at: datetime | None = None

    def __post_init__(self) -> None:
        if _REFERENCE_ID_RE.fullmatch(self.reference_id) is None:
            raise ValueError("reference_id must be a canonical arf_ ULID")
        if not self.owner_id:
            raise ValueError("owner_id must not be empty")
        from .identity import sha256_from_artifact_id

        sha256_from_artifact_id(self.artifact_id)
        if not self.role:
            raise ValueError("role must not be empty")
        _require_aware(self.created_at, "created_at")
        if self.state not in {"ACTIVE", "RELEASED"}:
            raise ValueError("reference state must be ACTIVE or RELEASED")
        if self.state == "ACTIVE" and self.released_at is not None:
            raise ValueError("active reference cannot have released_at")
        if self.state == "RELEASED":
            if self.released_at is None:
                raise ValueError("released reference requires released_at")
            _require_aware(self.released_at, "released_at")
            if self.released_at < self.created_at:
                raise ValueError("released_at cannot precede created_at")


@dataclass(frozen=True, slots=True)
class StreamTicketDescriptor:
    """Runtime-owned ticket data contract; this module never issues tickets."""

    ticket_id: str
    artifact_id: str
    project_id: str
    session_id: str
    expires_at: datetime
    range_start: int | None = None
    range_end_exclusive: int | None = None
    mode: str = "STREAM_TICKET"

    def __post_init__(self) -> None:
        from .identity import sha256_from_artifact_id

        sha256_from_artifact_id(self.artifact_id)
        if self.mode != "STREAM_TICKET" or not self.ticket_id:
            raise ValueError("stream ticket mode and ticket_id are required")
        if not self.project_id or not self.session_id:
            raise ValueError("stream ticket scope requires project_id and session_id")
        _require_aware(self.expires_at, "expires_at")
        if (self.range_start is None) != (self.range_end_exclusive is None):
            raise ValueError("byte range requires both bounds")
        if self.range_start is not None:
            if self.range_start < 0 or self.range_end_exclusive <= self.range_start:
                raise ValueError("invalid byte range")

    def to_access_wire(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "ticket_id": self.ticket_id,
            "expires_at": _wire_time(self.expires_at),
        }
