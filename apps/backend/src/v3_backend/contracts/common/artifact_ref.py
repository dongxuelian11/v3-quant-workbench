
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .dto import ContractValidationError, validate_schema
from .ids import validate_v3_id


_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _closed(value: Mapping[str, Any], allowed: set[str], required: set[str], path: str) -> None:
    if not isinstance(value, Mapping):
        raise ContractValidationError(path, "expected object")
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise ContractValidationError(path, "missing required fields: " + ", ".join(missing))
    if unknown:
        raise ContractValidationError(path, "unknown fields: " + ", ".join(unknown))


@dataclass(frozen=True)
class ArtifactAccessV1:
    ticket_id: str
    expires_at: str
    mode: str = "STREAM_TICKET"

    def __post_init__(self) -> None:
        if self.mode != "STREAM_TICKET":
            raise ContractValidationError("$.access.mode", "mode must be STREAM_TICKET")
        if not self.ticket_id:
            raise ContractValidationError("$.access.ticket_id", "ticket_id must not be empty")
        validate_schema(self.expires_at, {"type": "string", "format": "date-time"}, "$.access.expires_at")

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> "ArtifactAccessV1":
        _closed(value, {"mode", "ticket_id", "expires_at"}, {"mode", "ticket_id", "expires_at"}, "$.access")
        return cls(mode=value["mode"], ticket_id=value["ticket_id"], expires_at=value["expires_at"])

    def to_wire(self) -> dict[str, str]:
        return {"mode": self.mode, "ticket_id": self.ticket_id, "expires_at": self.expires_at}


@dataclass(frozen=True)
class ArtifactRefV1:
    artifact_id: str
    role: str
    media_type: str
    byte_size: int
    sha256: str
    schema_fingerprint: str | None = None
    access: ArtifactAccessV1 | None = None

    def __post_init__(self) -> None:
        validate_v3_id(self.artifact_id, "Artifact")
        if not isinstance(self.role, str) or not self.role:
            raise ContractValidationError("$.role", "role must not be empty")
        if not isinstance(self.media_type, str) or "/" not in self.media_type:
            raise ContractValidationError("$.media_type", "media_type must be a MIME type")
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool) or self.byte_size < 0:
            raise ContractValidationError("$.byte_size", "byte_size must be a non-negative integer")
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise ContractValidationError("$.sha256", "sha256 must be lowercase hexadecimal")
        if self.artifact_id != "art_sha256_" + self.sha256:
            raise ContractValidationError("$.artifact_id", "artifact_id and sha256 must identify the same bytes")
        if self.schema_fingerprint is not None and not self.schema_fingerprint:
            raise ContractValidationError("$.schema_fingerprint", "schema_fingerprint must not be empty")

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> "ArtifactRefV1":
        allowed = {"artifact_id", "role", "media_type", "byte_size", "sha256", "schema_fingerprint", "access"}
        required = {"artifact_id", "role", "media_type", "byte_size", "sha256"}
        _closed(value, allowed, required, "$")
        access = ArtifactAccessV1.from_wire(value["access"]) if "access" in value else None
        return cls(
            artifact_id=value["artifact_id"],
            role=value["role"],
            media_type=value["media_type"],
            byte_size=value["byte_size"],
            sha256=value["sha256"],
            schema_fingerprint=value.get("schema_fingerprint"),
            access=access,
        )

    def to_wire(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "role": self.role,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
        }
        if self.schema_fingerprint is not None:
            value["schema_fingerprint"] = self.schema_fingerprint
        if self.access is not None:
            value["access"] = self.access.to_wire()
        return value
