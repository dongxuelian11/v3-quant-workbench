"""Authority-backed field capability policy for provider-neutral market data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from ...provenance.canonical_hash import canonical_json_bytes, canonical_sha256
from ..payload_authority.model import PayloadResolutionRequest
from ..payload_authority.service import CanonicalPayloadResolver
from .model import RevisionSemantics


FIELD_CAPABILITY_POLICY_CONTRACT = "v3.data-truth-field-capability-policy/1.0.0"
FIELD_CAPABILITY_POLICY_ROLE = "DATA_TRUTH_CAPABILITY_POLICY"
FIELD_CAPABILITY_POLICY_SCHEMA_FINGERPRINT = canonical_sha256(
    {
        "contract": FIELD_CAPABILITY_POLICY_CONTRACT,
        "wire": "canonical-json-v1",
    }
)


class MarketDataFieldCode(str, Enum):
    OHLC = "OHLC"
    VOLUME = "VOLUME"
    AMOUNT = "AMOUNT"
    TRADING_CALENDAR = "TRADING_CALENDAR"
    TRADING_SESSION = "TRADING_SESSION"
    TRADING_STATUS = "TRADING_STATUS"
    SUSPENSION_STATUS = "SUSPENSION_STATUS"
    TRADABILITY = "TRADABILITY"
    SECURITY_TYPE = "SECURITY_TYPE"
    BOARD = "BOARD"
    LISTING_STATUS = "LISTING_STATUS"
    DELISTING_STATUS = "DELISTING_STATUS"
    ST_OR_RESTRICTED_STATUS = "ST_OR_RESTRICTED_STATUS"
    PRICE_LIMIT_RULE_INPUTS = "PRICE_LIMIT_RULE_INPUTS"
    NO_PRICE_LIMIT_SESSION_INPUTS = "NO_PRICE_LIMIT_SESSION_INPUTS"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    ADJUSTMENT_FACTOR = "ADJUSTMENT_FACTOR"
    UNIVERSE_MEMBERSHIP = "UNIVERSE_MEMBERSHIP"
    AVAILABLE_TIME = "AVAILABLE_TIME"
    REVISION_ID = "REVISION_ID"
    REVISION_SEMANTICS = "REVISION_SEMANTICS"
    PIT_VISIBILITY = "PIT_VISIBILITY"


class FieldCapabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class AvailableTimeSemantics(str, Enum):
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    NOT_PROVIDED = "NOT_PROVIDED"
    UNKNOWN = "UNKNOWN"


class SourceCostClass(str, Enum):
    FREE = "FREE"
    PAID = "PAID"
    LOCAL_LICENSED = "LOCAL_LICENSED"
    UNKNOWN = "UNKNOWN"


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class FieldCapability:
    field_code: MarketDataFieldCode
    state: FieldCapabilityState
    source_field_semantic: str | None
    available_time_semantics: AvailableTimeSemantics
    revision_semantics: RevisionSemantics
    provenance_required: bool
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.field_code, MarketDataFieldCode):
            object.__setattr__(self, "field_code", MarketDataFieldCode(self.field_code))
        if not isinstance(self.state, FieldCapabilityState):
            object.__setattr__(self, "state", FieldCapabilityState(self.state))
        if not isinstance(self.available_time_semantics, AvailableTimeSemantics):
            object.__setattr__(
                self,
                "available_time_semantics",
                AvailableTimeSemantics(self.available_time_semantics),
            )
        if not isinstance(self.revision_semantics, RevisionSemantics):
            object.__setattr__(
                self, "revision_semantics", RevisionSemantics(self.revision_semantics)
            )
        if not isinstance(self.provenance_required, bool):
            raise TypeError("provenance_required must be bool")
        if self.source_field_semantic is not None:
            _text(self.source_field_semantic, "source_field_semantic")
        if self.reason_code is not None:
            _text(self.reason_code, "reason_code")
        if self.state in {FieldCapabilityState.AVAILABLE, FieldCapabilityState.PARTIAL}:
            if self.source_field_semantic is None:
                raise ValueError("available/partial field capability requires source semantics")
        elif self.reason_code is None:
            raise ValueError("unavailable/unknown field capability requires a reason code")

    def to_wire(self) -> dict[str, object]:
        return {
            "field_code": self.field_code.value,
            "state": self.state.value,
            "source_field_semantic": self.source_field_semantic,
            "available_time_semantics": self.available_time_semantics.value,
            "revision_semantics": self.revision_semantics.value,
            "provenance_required": self.provenance_required,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_wire(cls, wire: Mapping[str, object]) -> FieldCapability:
        expected = {
            "field_code",
            "state",
            "source_field_semantic",
            "available_time_semantics",
            "revision_semantics",
            "provenance_required",
            "reason_code",
        }
        if set(wire) != expected:
            raise ValueError("field capability wire keys are not closed")
        return cls(
            field_code=MarketDataFieldCode(str(wire["field_code"])),
            state=FieldCapabilityState(str(wire["state"])),
            source_field_semantic=(
                None
                if wire["source_field_semantic"] is None
                else str(wire["source_field_semantic"])
            ),
            available_time_semantics=AvailableTimeSemantics(
                str(wire["available_time_semantics"])
            ),
            revision_semantics=RevisionSemantics(str(wire["revision_semantics"])),
            provenance_required=wire["provenance_required"],
            reason_code=None if wire["reason_code"] is None else str(wire["reason_code"]),
        )


@dataclass(frozen=True, slots=True)
class FieldCapabilityPolicy:
    policy_version: str
    connector_version_id: str
    provider_id: str
    logical_dataset: str
    frequency: str
    normalization_contract_version: str
    source_cost_class: SourceCostClass
    fields: tuple[FieldCapability, ...]
    contract_version: str = FIELD_CAPABILITY_POLICY_CONTRACT

    def __post_init__(self) -> None:
        for field in (
            "policy_version",
            "connector_version_id",
            "provider_id",
            "logical_dataset",
            "frequency",
            "normalization_contract_version",
            "contract_version",
        ):
            _text(getattr(self, field), field)
        if not self.connector_version_id.startswith("cov_"):
            raise ValueError("field policy must bind an exact ConnectorVersion")
        if not self.provider_id.startswith("pvd_"):
            raise ValueError("field policy must bind an exact provider descriptor")
        if self.contract_version != FIELD_CAPABILITY_POLICY_CONTRACT:
            raise ValueError("unsupported field capability policy contract")
        if not isinstance(self.source_cost_class, SourceCostClass):
            object.__setattr__(
                self, "source_cost_class", SourceCostClass(self.source_cost_class)
            )
        ordered = tuple(sorted(self.fields, key=lambda item: item.field_code.value))
        if not ordered or any(not isinstance(item, FieldCapability) for item in ordered):
            raise ValueError("field policy requires typed field capabilities")
        codes = tuple(item.field_code for item in ordered)
        if len(codes) != len(set(codes)):
            raise ValueError("field capability codes must be unique")
        object.__setattr__(self, "fields", ordered)

    def capability(self, field_code: MarketDataFieldCode) -> FieldCapability | None:
        code = field_code if isinstance(field_code, MarketDataFieldCode) else MarketDataFieldCode(field_code)
        return next((item for item in self.fields if item.field_code is code), None)

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "policy_version": self.policy_version,
            "connector_version_id": self.connector_version_id,
            "provider_id": self.provider_id,
            "logical_dataset": self.logical_dataset,
            "frequency": self.frequency,
            "normalization_contract_version": self.normalization_contract_version,
            "source_cost_class": self.source_cost_class.value,
            "fields": tuple(item.to_wire() for item in self.fields),
        }

    @property
    def policy_identity(self) -> str:
        return "fcp_sha256_" + canonical_sha256(self.to_wire())

    @property
    def artifact_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def policy_artifact_id(self) -> str:
        return "art_sha256_" + canonical_sha256(self.to_wire())

    @classmethod
    def from_wire(cls, wire: Mapping[str, object]) -> FieldCapabilityPolicy:
        expected = {
            "contract_version",
            "policy_version",
            "connector_version_id",
            "provider_id",
            "logical_dataset",
            "frequency",
            "normalization_contract_version",
            "source_cost_class",
            "fields",
        }
        if set(wire) != expected:
            raise ValueError("field capability policy wire keys are not closed")
        observed = wire["fields"]
        if not isinstance(observed, list):
            raise ValueError("field capability policy fields must be an array")
        if any(not isinstance(item, Mapping) for item in observed):
            raise ValueError("field capability policy fields must be objects")
        return cls(
            contract_version=str(wire["contract_version"]),
            policy_version=str(wire["policy_version"]),
            connector_version_id=str(wire["connector_version_id"]),
            provider_id=str(wire["provider_id"]),
            logical_dataset=str(wire["logical_dataset"]),
            frequency=str(wire["frequency"]),
            normalization_contract_version=str(wire["normalization_contract_version"]),
            source_cost_class=SourceCostClass(str(wire["source_cost_class"])),
            fields=tuple(FieldCapability.from_wire(item) for item in observed),
        )

    @classmethod
    def from_canonical_bytes(cls, payload: bytes) -> FieldCapabilityPolicy:
        if not isinstance(payload, bytes):
            raise TypeError("field capability policy payload must be bytes")
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("field capability policy is not valid UTF-8 JSON") from error
        if not isinstance(parsed, Mapping):
            raise ValueError("field capability policy must be a JSON object")
        if canonical_json_bytes(parsed) != payload:
            raise ValueError("field capability policy bytes are not canonical JSON")
        policy = cls.from_wire(parsed)
        if policy.artifact_bytes != payload:
            raise ValueError("decoded field capability policy is not byte-stable")
        return policy


def resolve_field_capability_policy(
    resolver: CanonicalPayloadResolver,
    request: PayloadResolutionRequest,
) -> FieldCapabilityPolicy:
    """Resolve actual policy bytes through P1; verified-looking objects are not inputs."""

    if request.payload_role != FIELD_CAPABILITY_POLICY_ROLE:
        raise ValueError("capability policy resolution requires the exact policy role")
    result = resolver.resolve(request)
    verified = result.verified_payload
    if verified.schema_fingerprint != FIELD_CAPABILITY_POLICY_SCHEMA_FINGERPRINT:
        raise ValueError("capability policy schema fingerprint is unavailable or mismatched")
    policy = FieldCapabilityPolicy.from_canonical_bytes(verified.payload)
    if policy.policy_artifact_id != verified.artifact_id:
        raise ValueError("capability policy bytes do not match the resolved Artifact identity")
    return policy


def require_complete_field_code_declaration(
    policy: FieldCapabilityPolicy,
    field_codes: Iterable[MarketDataFieldCode] = tuple(MarketDataFieldCode),
) -> None:
    missing = sorted(
        code.value for code in field_codes if policy.capability(code) is None
    )
    if missing:
        raise ValueError("field capability policy omits: " + ",".join(missing))
