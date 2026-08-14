"""Immutable contracts for canonical payload resolution and its evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from v3_backend.domain.artifacts.identity import validate_sha256
from v3_backend.provenance.canonical_hash import canonical_sha256

from .exceptions import PayloadArtifactIdMismatch, PayloadReadBoundExceeded


REQUEST_CONTRACT_VERSION = "v3.payload-resolution-request/1.0.0"
BINDING_CONTRACT_VERSION = "v3.canonical-payload-binding/1.0.0"
RESOLVER_CONTRACT_VERSION = "v3.canonical-payload-resolver/1.0.0"
VERIFIED_RESULT_STATUS = "VERIFIED"


def _require_text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")


def _require_optional_text(value: object, field: str) -> None:
    if value is not None:
        _require_text(value, field)


def _content_identity(prefix: str, payload: dict[str, Any]) -> str:
    return prefix + canonical_sha256(payload)


@dataclass(frozen=True, slots=True)
class PayloadResolutionRequest:
    """Untrusted intent only; it deliberately has no raw-payload field."""

    owner_namespace: str
    owner_id: str
    owner_version: str
    payload_role: str
    context_identity: str
    max_bytes: int
    contract_version: str = REQUEST_CONTRACT_VERSION

    def __post_init__(self) -> None:
        for field in (
            "owner_namespace",
            "owner_id",
            "owner_version",
            "payload_role",
            "context_identity",
            "contract_version",
        ):
            _require_text(getattr(self, field), field)
        if (
            not isinstance(self.max_bytes, int)
            or isinstance(self.max_bytes, bool)
            or self.max_bytes <= 0
        ):
            raise PayloadReadBoundExceeded("max_bytes must be a positive non-boolean integer")

    def to_identity_wire(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "owner_namespace": self.owner_namespace,
            "owner_id": self.owner_id,
            "owner_version": self.owner_version,
            "payload_role": self.payload_role,
            "context_identity": self.context_identity,
            "max_bytes": self.max_bytes,
        }

    @property
    def request_identity(self) -> str:
        return _content_identity("prq_sha256_", self.to_identity_wire())


@dataclass(frozen=True, slots=True)
class CanonicalPayloadBinding:
    """A canonical-owner statement obtained through an injected trusted port.

    Constructing this value does not establish authority. The service must obtain it
    from ``CanonicalPayloadBindingResolver`` and validate it against the request.
    """

    owner_namespace: str
    owner_id: str
    owner_version: str
    payload_role: str
    artifact_id: str
    expected_sha256: str
    expected_byte_size: int
    context_identity: str
    binding_version: str
    schema_fingerprint: str | None = None
    semantic_fingerprint: str | None = None
    provenance_reference_id: str | None = None
    contract_version: str = BINDING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        for field in (
            "owner_namespace",
            "owner_id",
            "owner_version",
            "payload_role",
            "artifact_id",
            "context_identity",
            "binding_version",
            "contract_version",
        ):
            _require_text(getattr(self, field), field)
        try:
            validate_sha256(self.expected_sha256)
        except (TypeError, ValueError) as exc:
            raise PayloadArtifactIdMismatch("expected_sha256 is not canonical SHA-256") from exc
        if (
            not isinstance(self.expected_byte_size, int)
            or isinstance(self.expected_byte_size, bool)
            or self.expected_byte_size < 0
        ):
            raise ValueError("expected_byte_size must be a non-negative non-boolean integer")
        for field in (
            "schema_fingerprint",
            "semantic_fingerprint",
            "provenance_reference_id",
        ):
            _require_optional_text(getattr(self, field), field)

    def to_identity_wire(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "binding_version": self.binding_version,
            "owner_namespace": self.owner_namespace,
            "owner_id": self.owner_id,
            "owner_version": self.owner_version,
            "payload_role": self.payload_role,
            "artifact_id": self.artifact_id,
            "expected_sha256": self.expected_sha256,
            "expected_byte_size": self.expected_byte_size,
            "schema_fingerprint": self.schema_fingerprint,
            "semantic_fingerprint": self.semantic_fingerprint,
            "context_identity": self.context_identity,
            "provenance_reference_id": self.provenance_reference_id,
        }

    @property
    def binding_identity(self) -> str:
        return _content_identity("cpb_sha256_", self.to_identity_wire())


@dataclass(frozen=True, slots=True)
class VerifiedPayload:
    """Bytes verified during one resolver execution; object possession is not authority."""

    request_identity: str
    binding_identity: str
    artifact_id: str
    actual_sha256: str
    actual_byte_size: int
    context_identity: str
    payload: bytes
    schema_fingerprint: str | None = None
    semantic_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "request_identity",
            "binding_identity",
            "artifact_id",
            "context_identity",
        ):
            _require_text(getattr(self, field), field)
        validate_sha256(self.actual_sha256)
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be bytes")
        if (
            not isinstance(self.actual_byte_size, int)
            or isinstance(self.actual_byte_size, bool)
            or self.actual_byte_size != len(self.payload)
        ):
            raise ValueError("actual_byte_size must equal the payload byte length")
        for field in ("schema_fingerprint", "semantic_fingerprint"):
            _require_optional_text(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class PayloadResolutionReceipt:
    """Deterministic evidence of resolution, never execution authorization."""

    request_identity: str
    binding_identity: str
    artifact_id: str
    actual_sha256: str
    actual_byte_size: int
    context_identity: str
    resolver_contract_version: str = RESOLVER_CONTRACT_VERSION
    result_status: str = VERIFIED_RESULT_STATUS
    schema_fingerprint: str | None = None
    semantic_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "request_identity",
            "binding_identity",
            "artifact_id",
            "context_identity",
            "resolver_contract_version",
        ):
            _require_text(getattr(self, field), field)
        validate_sha256(self.actual_sha256)
        if (
            not isinstance(self.actual_byte_size, int)
            or isinstance(self.actual_byte_size, bool)
            or self.actual_byte_size < 0
        ):
            raise ValueError("actual_byte_size must be a non-negative non-boolean integer")
        if self.result_status != VERIFIED_RESULT_STATUS:
            raise ValueError(f"result_status must be {VERIFIED_RESULT_STATUS}")
        for field in ("schema_fingerprint", "semantic_fingerprint"):
            _require_optional_text(getattr(self, field), field)

    def to_identity_wire(self) -> dict[str, Any]:
        return {
            "resolver_contract_version": self.resolver_contract_version,
            "result_status": self.result_status,
            "request_identity": self.request_identity,
            "binding_identity": self.binding_identity,
            "artifact_id": self.artifact_id,
            "actual_sha256": self.actual_sha256,
            "actual_byte_size": self.actual_byte_size,
            "schema_fingerprint": self.schema_fingerprint,
            "semantic_fingerprint": self.semantic_fingerprint,
            "context_identity": self.context_identity,
        }

    @property
    def receipt_identity(self) -> str:
        return _content_identity("prr_sha256_", self.to_identity_wire())


@dataclass(frozen=True, slots=True)
class PayloadResolutionResult:
    verified_payload: VerifiedPayload
    receipt: PayloadResolutionReceipt

    def __post_init__(self) -> None:
        if self.verified_payload.request_identity != self.receipt.request_identity:
            raise ValueError("verified payload and receipt request identities differ")
        if self.verified_payload.binding_identity != self.receipt.binding_identity:
            raise ValueError("verified payload and receipt binding identities differ")
