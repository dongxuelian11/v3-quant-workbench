"""Deterministic field resolution and Research/Formal capability gates."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping

from ...contracts.common.truth_admission import (
    NOT_FORMAL_CEILING,
    PRE_ALPHA_CEILING,
    TruthAdmissionState,
)
from ...provenance.canonical_hash import canonical_json_bytes, canonical_sha256
from ..payload_authority.model import PayloadResolutionRequest
from ..payload_authority.service import CanonicalPayloadResolver
from .capabilities import (
    FieldCapabilityPolicy,
    FieldCapabilityState,
    MarketDataFieldCode,
)
from .model import RevisionSemantics


SOURCE_RESOLUTION_POLICY_CONTRACT = "v3.data-truth-source-resolution-policy/1.0.0"
CAPABILITY_PROFILE_CONTRACT = "v3.data-truth-capability-profile/1.0.0"
SOURCE_AUTHORITY_EVIDENCE_CONTRACT = "v3.data-truth-source-authority-evidence/1.0.0"
SOURCE_AUTHORITY_EVIDENCE_ROLE = "DATA_TRUTH_SOURCE_AUTHORITY_EVIDENCE"
SOURCE_AUTHORITY_EVIDENCE_SCHEMA_FINGERPRINT = canonical_sha256(
    {
        "contract": SOURCE_AUTHORITY_EVIDENCE_CONTRACT,
        "wire": "canonical-json-v1",
    }
)


class FieldValueKind(str, Enum):
    DIRECT = "DIRECT"
    DERIVED = "DERIVED"
    MISSING = "MISSING"
    UNAVAILABLE = "UNAVAILABLE"


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    MISSING = "MISSING"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class ConflictMode(str, Enum):
    RETAIN_AND_SELECT = "RETAIN_AND_SELECT"
    FAIL_CLOSED = "FAIL_CLOSED"
    AUTHORITATIVE_EVIDENCE = "AUTHORITATIVE_EVIDENCE"


class CapabilityTarget(str, Enum):
    RESEARCH = "RESEARCH"
    FORMAL_MARKET_STATE = "FORMAL_MARKET_STATE"


class CapabilityAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"


@dataclass(frozen=True, slots=True)
class SourceAuthorityEvidence:
    """Canonical bytes naming the exact provider allowed to resolve one conflict."""

    resolution_policy_version: str
    field_code: MarketDataFieldCode
    authoritative_provider_id: str
    authoritative_connector_version_id: str
    logical_dataset: str
    contract_version: str = SOURCE_AUTHORITY_EVIDENCE_CONTRACT

    def __post_init__(self) -> None:
        if self.contract_version != SOURCE_AUTHORITY_EVIDENCE_CONTRACT:
            raise ValueError("unsupported source authority evidence contract")
        if not self.resolution_policy_version:
            raise ValueError("source authority evidence requires policy version")
        if not isinstance(self.field_code, MarketDataFieldCode):
            object.__setattr__(self, "field_code", MarketDataFieldCode(self.field_code))
        if not self.authoritative_provider_id.startswith("pvd_"):
            raise ValueError("source authority evidence requires canonical provider")
        if not self.authoritative_connector_version_id.startswith("cov_"):
            raise ValueError("source authority evidence requires exact ConnectorVersion")
        if not self.logical_dataset:
            raise ValueError("source authority evidence requires logical dataset")

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "resolution_policy_version": self.resolution_policy_version,
            "field_code": self.field_code.value,
            "authoritative_provider_id": self.authoritative_provider_id,
            "authoritative_connector_version_id": self.authoritative_connector_version_id,
            "logical_dataset": self.logical_dataset,
        }

    @property
    def artifact_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_id(self) -> str:
        return "art_sha256_" + canonical_sha256(self.to_wire())

    @classmethod
    def from_canonical_bytes(cls, payload: bytes) -> SourceAuthorityEvidence:
        if not isinstance(payload, bytes):
            raise TypeError("source authority evidence payload must be bytes")
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("source authority evidence is not valid UTF-8 JSON") from error
        if not isinstance(parsed, Mapping) or set(parsed) != {
            "contract_version",
            "resolution_policy_version",
            "field_code",
            "authoritative_provider_id",
            "authoritative_connector_version_id",
            "logical_dataset",
        }:
            raise ValueError("source authority evidence wire is not closed")
        if canonical_json_bytes(parsed) != payload:
            raise ValueError("source authority evidence bytes are not canonical JSON")
        evidence = cls(
            contract_version=str(parsed["contract_version"]),
            resolution_policy_version=str(parsed["resolution_policy_version"]),
            field_code=MarketDataFieldCode(str(parsed["field_code"])),
            authoritative_provider_id=str(parsed["authoritative_provider_id"]),
            authoritative_connector_version_id=str(
                parsed["authoritative_connector_version_id"]
            ),
            logical_dataset=str(parsed["logical_dataset"]),
        )
        if evidence.artifact_bytes != payload:
            raise ValueError("source authority evidence is not byte-stable")
        return evidence


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _wire_value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, tuple):
        return tuple(_wire_value(item) for item in value)
    if isinstance(value, list):
        return tuple(_wire_value(item) for item in value)
    if isinstance(value, Mapping):
        return {str(key): _wire_value(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    provider_id: str
    connector_version_id: str
    logical_dataset: str
    raw_capture_id: str
    artifact_id: str
    content_hash: str
    source_field_semantic: str
    effective_time: datetime
    available_time: datetime | None
    revision_id: str | None
    revision_semantics: RevisionSemantics
    acquired_at: datetime
    value_kind: FieldValueKind
    selection_policy_id: str | None = None
    authority_evidence_artifact_id: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "provider_id",
            "connector_version_id",
            "logical_dataset",
            "raw_capture_id",
            "artifact_id",
            "content_hash",
            "source_field_semantic",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field} must be a non-empty string")
        if not self.provider_id.startswith("pvd_"):
            raise ValueError("field provenance provider_id is not canonical")
        if not self.connector_version_id.startswith("cov_"):
            raise ValueError("field provenance connector_version_id is not canonical")
        if not self.raw_capture_id.startswith("raw_"):
            raise ValueError("field provenance raw_capture_id is not canonical")
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("field provenance content_hash must be lowercase SHA-256")
        if self.artifact_id != "art_sha256_" + self.content_hash:
            raise ValueError("field provenance Artifact identity must match content hash")
        if not isinstance(self.revision_semantics, RevisionSemantics):
            object.__setattr__(
                self, "revision_semantics", RevisionSemantics(self.revision_semantics)
            )
        if not isinstance(self.value_kind, FieldValueKind):
            object.__setattr__(self, "value_kind", FieldValueKind(self.value_kind))
        _aware(self.effective_time, "effective_time")
        _aware(self.acquired_at, "acquired_at")
        if self.available_time is not None:
            _aware(self.available_time, "available_time")
        for field in (
            "revision_id",
            "selection_policy_id",
            "authority_evidence_artifact_id",
        ):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{field} must be null or a non-empty string")

    def to_wire(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "connector_version_id": self.connector_version_id,
            "logical_dataset": self.logical_dataset,
            "raw_capture_id": self.raw_capture_id,
            "artifact_id": self.artifact_id,
            "content_hash": self.content_hash,
            "source_field_semantic": self.source_field_semantic,
            "effective_time": self.effective_time,
            "available_time": self.available_time,
            "revision_id": self.revision_id,
            "revision_semantics": self.revision_semantics.value,
            "acquired_at": self.acquired_at,
            "value_kind": self.value_kind.value,
            "selection_policy_id": self.selection_policy_id,
            "authority_evidence_artifact_id": self.authority_evidence_artifact_id,
        }

    @property
    def provenance_identity(self) -> str:
        return "fpv_sha256_" + canonical_sha256(self.to_wire())


@dataclass(frozen=True, slots=True)
class FieldCandidate:
    field_code: MarketDataFieldCode
    value: object | None
    capability_state: FieldCapabilityState
    provenance: FieldProvenance
    eligible: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.field_code, MarketDataFieldCode):
            object.__setattr__(self, "field_code", MarketDataFieldCode(self.field_code))
        if not isinstance(self.capability_state, FieldCapabilityState):
            object.__setattr__(
                self, "capability_state", FieldCapabilityState(self.capability_state)
            )
        if not isinstance(self.provenance, FieldProvenance):
            raise TypeError("candidate provenance must be FieldProvenance")
        if not isinstance(self.eligible, bool):
            raise TypeError("candidate eligible must be bool")
        if self.provenance.value_kind in {FieldValueKind.MISSING, FieldValueKind.UNAVAILABLE}:
            if self.value is not None:
                raise ValueError("missing/unavailable field candidate cannot carry a value")
        elif self.value is None:
            raise ValueError("direct/derived field candidate requires a value")

    @property
    def value_identity(self) -> str | None:
        return None if self.value is None else canonical_sha256(_wire_value(self.value))


@dataclass(frozen=True, slots=True)
class FieldSourceRule:
    field_code: MarketDataFieldCode
    ordered_provider_ids: tuple[str, ...]
    material: bool
    conflict_mode: ConflictMode
    authoritative_provider_id: str | None = None
    authority_evidence_artifact_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.field_code, MarketDataFieldCode):
            object.__setattr__(self, "field_code", MarketDataFieldCode(self.field_code))
        if not isinstance(self.conflict_mode, ConflictMode):
            object.__setattr__(self, "conflict_mode", ConflictMode(self.conflict_mode))
        if not self.ordered_provider_ids or len(self.ordered_provider_ids) != len(
            set(self.ordered_provider_ids)
        ):
            raise ValueError("field source rule requires unique ordered providers")
        if any(not item.startswith("pvd_") for item in self.ordered_provider_ids):
            raise ValueError("field source rule provider IDs must be canonical")
        if self.conflict_mode is ConflictMode.AUTHORITATIVE_EVIDENCE:
            if (
                self.authoritative_provider_id not in self.ordered_provider_ids
                or not self.authority_evidence_artifact_id
            ):
                raise ValueError(
                    "authoritative conflict resolution requires provider and evidence Artifact"
                )
        elif self.authoritative_provider_id is not None or self.authority_evidence_artifact_id is not None:
            raise ValueError("authority evidence is valid only for authoritative conflict mode")

    def to_wire(self) -> dict[str, object]:
        return {
            "field_code": self.field_code.value,
            "ordered_provider_ids": self.ordered_provider_ids,
            "material": self.material,
            "conflict_mode": self.conflict_mode.value,
            "authoritative_provider_id": self.authoritative_provider_id,
            "authority_evidence_artifact_id": self.authority_evidence_artifact_id,
        }


@dataclass(frozen=True, slots=True)
class SourceResolutionPolicy:
    policy_version: str
    target: CapabilityTarget
    field_rules: tuple[FieldSourceRule, ...]
    contract_version: str = SOURCE_RESOLUTION_POLICY_CONTRACT

    def __post_init__(self) -> None:
        if not self.policy_version:
            raise ValueError("resolution policy version is required")
        if self.contract_version != SOURCE_RESOLUTION_POLICY_CONTRACT:
            raise ValueError("unsupported source resolution policy contract")
        if not isinstance(self.target, CapabilityTarget):
            object.__setattr__(self, "target", CapabilityTarget(self.target))
        ordered = tuple(sorted(self.field_rules, key=lambda item: item.field_code.value))
        codes = tuple(item.field_code for item in ordered)
        if not ordered or len(codes) != len(set(codes)):
            raise ValueError("resolution policy requires unique field rules")
        object.__setattr__(self, "field_rules", ordered)

    def rule(self, field_code: MarketDataFieldCode) -> FieldSourceRule | None:
        code = field_code if isinstance(field_code, MarketDataFieldCode) else MarketDataFieldCode(field_code)
        return next((item for item in self.field_rules if item.field_code is code), None)

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "policy_version": self.policy_version,
            "target": self.target.value,
            "field_rules": tuple(item.to_wire() for item in self.field_rules),
        }

    @property
    def policy_identity(self) -> str:
        return "srp_sha256_" + canonical_sha256(self.to_wire())


@dataclass(frozen=True, slots=True)
class FieldResolution:
    field_code: MarketDataFieldCode
    status: ResolutionStatus
    value: object | None
    selected_provenance: FieldProvenance | None
    conflict_provenance: tuple[FieldProvenance, ...]
    reason_codes: tuple[str, ...]


def resolve_field(
    field_code: MarketDataFieldCode,
    candidates: tuple[FieldCandidate, ...],
    policy: SourceResolutionPolicy,
    *,
    authority_resolver: CanonicalPayloadResolver | None = None,
    authority_request: PayloadResolutionRequest | None = None,
) -> FieldResolution:
    code = field_code if isinstance(field_code, MarketDataFieldCode) else MarketDataFieldCode(field_code)
    rule = policy.rule(code)
    if rule is None:
        return FieldResolution(
            code,
            ResolutionStatus.NOT_AVAILABLE,
            None,
            None,
            (),
            ("SOURCE_RESOLUTION_RULE_UNAVAILABLE",),
        )
    if any(item.field_code is not code for item in candidates):
        raise ValueError("field resolver candidates must share the requested field code")
    provider_rank = {provider_id: index for index, provider_id in enumerate(rule.ordered_provider_ids)}
    allowed_states = (
        {FieldCapabilityState.AVAILABLE, FieldCapabilityState.PARTIAL}
        if policy.target is CapabilityTarget.RESEARCH
        else {FieldCapabilityState.AVAILABLE}
    )
    eligible = tuple(
        sorted(
            (
                item
                for item in candidates
                if item.eligible
                and item.provenance.provider_id in provider_rank
                and item.capability_state in allowed_states
                and item.provenance.value_kind in {FieldValueKind.DIRECT, FieldValueKind.DERIVED}
            ),
            key=lambda item: (
                provider_rank[item.provenance.provider_id],
                item.provenance.provenance_identity,
            ),
        )
    )
    if not eligible:
        status = (
            ResolutionStatus.MISSING
            if policy.target is CapabilityTarget.RESEARCH
            else ResolutionStatus.NOT_AVAILABLE
        )
        return FieldResolution(
            code,
            status,
            None,
            None,
            (),
            ("NO_ELIGIBLE_PROVIDER_FIELD",),
        )

    identities = {item.value_identity for item in eligible}
    conflicts = tuple(item.provenance for item in eligible) if len(identities) > 1 else ()
    selected = eligible[0]
    if conflicts and policy.target is CapabilityTarget.FORMAL_MARKET_STATE and rule.material:
        if rule.conflict_mode is ConflictMode.AUTHORITATIVE_EVIDENCE:
            authoritative = tuple(
                item
                for item in eligible
                if item.provenance.provider_id == rule.authoritative_provider_id
            )
            if (
                len(authoritative) != 1
                or authority_resolver is None
                or authority_request is None
                or authority_request.payload_role != SOURCE_AUTHORITY_EVIDENCE_ROLE
            ):
                return FieldResolution(
                    code,
                    ResolutionStatus.NOT_AVAILABLE,
                    None,
                    None,
                    conflicts,
                    ("MATERIAL_SOURCE_CONFLICT_UNRESOLVED",),
                )
            resolved_evidence = authority_resolver.resolve(authority_request)
            verified = resolved_evidence.verified_payload
            if (
                verified.schema_fingerprint
                != SOURCE_AUTHORITY_EVIDENCE_SCHEMA_FINGERPRINT
                or verified.artifact_id != rule.authority_evidence_artifact_id
            ):
                return FieldResolution(
                    code,
                    ResolutionStatus.NOT_AVAILABLE,
                    None,
                    None,
                    conflicts,
                    ("MATERIAL_SOURCE_AUTHORITY_EVIDENCE_MISMATCH",),
                )
            evidence = SourceAuthorityEvidence.from_canonical_bytes(verified.payload)
            authoritative_candidate = authoritative[0]
            if (
                evidence.artifact_id != verified.artifact_id
                or evidence.resolution_policy_version != policy.policy_version
                or evidence.field_code is not code
                or evidence.authoritative_provider_id
                != authoritative_candidate.provenance.provider_id
                or evidence.authoritative_connector_version_id
                != authoritative_candidate.provenance.connector_version_id
                or evidence.logical_dataset
                != authoritative_candidate.provenance.logical_dataset
            ):
                return FieldResolution(
                    code,
                    ResolutionStatus.NOT_AVAILABLE,
                    None,
                    None,
                    conflicts,
                    ("MATERIAL_SOURCE_AUTHORITY_EVIDENCE_MISMATCH",),
                )
            selected = authoritative_candidate
        else:
            return FieldResolution(
                code,
                ResolutionStatus.NOT_AVAILABLE,
                None,
                None,
                conflicts,
                ("MATERIAL_SOURCE_CONFLICT_UNRESOLVED",),
            )

    selected_provenance = replace(
        selected.provenance,
        selection_policy_id=policy.policy_identity,
        authority_evidence_artifact_id=(
            rule.authority_evidence_artifact_id
            if conflicts and rule.conflict_mode is ConflictMode.AUTHORITATIVE_EVIDENCE
            else selected.provenance.authority_evidence_artifact_id
        ),
    )
    reasons = ("SOURCE_CONFLICT_RETAINED",) if conflicts else ("EXPLICIT_PROVIDER_PRIORITY",)
    return FieldResolution(
        code,
        ResolutionStatus.RESOLVED,
        selected.value,
        selected_provenance,
        conflicts,
        reasons,
    )


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    field_code: MarketDataFieldCode
    allowed_states: tuple[FieldCapabilityState, ...]
    require_available_time: bool
    require_revision_id: bool
    require_known_revision_semantics: bool
    require_provenance: bool

    def __post_init__(self) -> None:
        if not isinstance(self.field_code, MarketDataFieldCode):
            object.__setattr__(self, "field_code", MarketDataFieldCode(self.field_code))
        states = tuple(sorted(set(self.allowed_states), key=lambda item: item.value))
        if not states or any(not isinstance(item, FieldCapabilityState) for item in states):
            raise ValueError("capability requirement requires typed allowed states")
        object.__setattr__(self, "allowed_states", states)

    def to_wire(self) -> dict[str, object]:
        return {
            "field_code": self.field_code.value,
            "allowed_states": tuple(item.value for item in self.allowed_states),
            "require_available_time": self.require_available_time,
            "require_revision_id": self.require_revision_id,
            "require_known_revision_semantics": self.require_known_revision_semantics,
            "require_provenance": self.require_provenance,
        }


@dataclass(frozen=True, slots=True)
class MarketDataCapabilityProfile:
    profile_version: str
    target: CapabilityTarget
    resolution_policy: SourceResolutionPolicy
    requirements: tuple[CapabilityRequirement, ...]
    contract_version: str = CAPABILITY_PROFILE_CONTRACT

    def __post_init__(self) -> None:
        if not self.profile_version:
            raise ValueError("capability profile version is required")
        if self.contract_version != CAPABILITY_PROFILE_CONTRACT:
            raise ValueError("unsupported capability profile contract")
        if not isinstance(self.target, CapabilityTarget):
            object.__setattr__(self, "target", CapabilityTarget(self.target))
        if self.resolution_policy.target is not self.target:
            raise ValueError("capability profile target must match resolution policy target")
        ordered = tuple(sorted(self.requirements, key=lambda item: item.field_code.value))
        codes = tuple(item.field_code for item in ordered)
        if not ordered or len(codes) != len(set(codes)):
            raise ValueError("capability profile requires unique field requirements")
        object.__setattr__(self, "requirements", ordered)

    @property
    def profile_identity(self) -> str:
        return "mcp_sha256_" + canonical_sha256(
            {
                "contract_version": self.contract_version,
                "profile_version": self.profile_version,
                "target": self.target.value,
                "resolution_policy_id": self.resolution_policy.policy_identity,
                "requirements": tuple(item.to_wire() for item in self.requirements),
            }
        )


@dataclass(frozen=True, slots=True)
class CapabilityEvaluation:
    profile_identity: str
    target: CapabilityTarget
    availability: CapabilityAvailability
    missing_fields: tuple[MarketDataFieldCode, ...]
    reason_codes: tuple[str, ...]
    capability_report: tuple[tuple[MarketDataFieldCode, str], ...]
    truth_ceiling: TruthAdmissionState


def evaluate_capability_profile(
    profile: MarketDataCapabilityProfile,
    resolutions: Mapping[MarketDataFieldCode, FieldResolution],
    provider_policies: Mapping[str, FieldCapabilityPolicy],
) -> CapabilityEvaluation:
    blocking_missing: set[MarketDataFieldCode] = set()
    reasons: set[str] = set()
    report: list[tuple[MarketDataFieldCode, str]] = []
    for requirement in profile.requirements:
        resolution = resolutions.get(requirement.field_code)
        if (
            resolution is None
            or resolution.status is not ResolutionStatus.RESOLVED
            or resolution.selected_provenance is None
        ):
            blocking_missing.add(requirement.field_code)
            reasons.add(f"{requirement.field_code.value}_NOT_RESOLVED")
            report.append((requirement.field_code, "NOT_RESOLVED"))
            continue
        provenance = resolution.selected_provenance
        policy = provider_policies.get(provenance.provider_id)
        capability = None if policy is None else policy.capability(requirement.field_code)
        if capability is None or capability.state not in requirement.allowed_states:
            blocking_missing.add(requirement.field_code)
            reasons.add(f"{requirement.field_code.value}_CAPABILITY_INELIGIBLE")
            report.append((requirement.field_code, "CAPABILITY_INELIGIBLE"))
            continue
        failures: list[str] = []
        if requirement.require_available_time and provenance.available_time is None:
            failures.append("AVAILABLE_TIME_UNAVAILABLE")
        if requirement.require_revision_id and provenance.revision_id is None:
            failures.append("REVISION_ID_UNAVAILABLE")
        if (
            requirement.require_known_revision_semantics
            and provenance.revision_semantics is RevisionSemantics.UNKNOWN
        ):
            failures.append("REVISION_SEMANTICS_UNKNOWN")
        if requirement.require_provenance and not provenance.raw_capture_id:
            failures.append("PROVENANCE_UNAVAILABLE")
        if failures:
            blocking_missing.add(requirement.field_code)
            reasons.update(f"{requirement.field_code.value}_{item}" for item in failures)
            report.append((requirement.field_code, "+".join(failures)))
        else:
            report.append((requirement.field_code, capability.state.value))

    reported_missing = set(blocking_missing)
    reported_codes = {item[0] for item in report}
    for code in MarketDataFieldCode:
        capabilities = tuple(
            capability
            for policy in provider_policies.values()
            if (capability := policy.capability(code)) is not None
        )
        if (
            not capabilities
            or all(
                item.state
                in {FieldCapabilityState.UNAVAILABLE, FieldCapabilityState.UNKNOWN}
                for item in capabilities
            )
        ):
            reported_missing.add(code)
            states = (
                "UNDECLARED"
                if not capabilities
                else "+".join(sorted({item.state.value for item in capabilities}))
            )
            reasons.add(f"{code.value}_EXPLICIT_GAP_{states}")
            if code not in reported_codes:
                report.append((code, f"EXPLICIT_GAP_{states}"))
    availability = (
        CapabilityAvailability.NOT_AVAILABLE
        if blocking_missing
        else CapabilityAvailability.AVAILABLE
    )
    ceiling = (
        PRE_ALPHA_CEILING
        if profile.target is CapabilityTarget.RESEARCH
        else NOT_FORMAL_CEILING
    )
    if availability is CapabilityAvailability.AVAILABLE and profile.target is CapabilityTarget.FORMAL_MARKET_STATE:
        reasons.add("CAPABILITY_GATE_DOES_NOT_MINT_CANONICAL_TRUTH")
    return CapabilityEvaluation(
        profile_identity=profile.profile_identity,
        target=profile.target,
        availability=availability,
        missing_fields=tuple(sorted(reported_missing, key=lambda item: item.value)),
        reason_codes=tuple(sorted(reasons)),
        capability_report=tuple(sorted(report, key=lambda item: item[0].value)),
        truth_ceiling=ceiling,
    )


class FormalMarketStateUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StrictFormalMarketStateGate:
    profile: MarketDataCapabilityProfile

    def __post_init__(self) -> None:
        if self.profile.target is not CapabilityTarget.FORMAL_MARKET_STATE:
            raise ValueError("strict formal gate requires a FORMAL_MARKET_STATE profile")

    def evaluate(
        self,
        resolutions: Mapping[MarketDataFieldCode, FieldResolution],
        provider_policies: Mapping[str, FieldCapabilityPolicy],
    ) -> CapabilityEvaluation:
        return evaluate_capability_profile(self.profile, resolutions, provider_policies)

    def require_available(
        self,
        resolutions: Mapping[MarketDataFieldCode, FieldResolution],
        provider_policies: Mapping[str, FieldCapabilityPolicy],
    ) -> CapabilityEvaluation:
        evaluation = self.evaluate(resolutions, provider_policies)
        if evaluation.availability is not CapabilityAvailability.AVAILABLE:
            raise FormalMarketStateUnavailable(
                "FORMAL_MARKET_STATE_NOT_AVAILABLE:" + ",".join(evaluation.reason_codes)
            )
        return evaluation


FORMAL_MARKET_STATE_FIELDS = (
    MarketDataFieldCode.OHLC,
    MarketDataFieldCode.VOLUME,
    MarketDataFieldCode.TRADING_CALENDAR,
    MarketDataFieldCode.TRADING_SESSION,
    MarketDataFieldCode.TRADING_STATUS,
    MarketDataFieldCode.SUSPENSION_STATUS,
    MarketDataFieldCode.TRADABILITY,
    MarketDataFieldCode.SECURITY_TYPE,
    MarketDataFieldCode.BOARD,
    MarketDataFieldCode.LISTING_STATUS,
    MarketDataFieldCode.DELISTING_STATUS,
    MarketDataFieldCode.ST_OR_RESTRICTED_STATUS,
    MarketDataFieldCode.PRICE_LIMIT_RULE_INPUTS,
    MarketDataFieldCode.NO_PRICE_LIMIT_SESSION_INPUTS,
    MarketDataFieldCode.CORPORATE_ACTION,
    MarketDataFieldCode.ADJUSTMENT_FACTOR,
    MarketDataFieldCode.UNIVERSE_MEMBERSHIP,
    MarketDataFieldCode.AVAILABLE_TIME,
    MarketDataFieldCode.REVISION_ID,
    MarketDataFieldCode.REVISION_SEMANTICS,
    MarketDataFieldCode.PIT_VISIBILITY,
)


def research_requirements() -> tuple[CapabilityRequirement, ...]:
    return tuple(
        CapabilityRequirement(
            field_code=code,
            allowed_states=(FieldCapabilityState.AVAILABLE, FieldCapabilityState.PARTIAL),
            require_available_time=False,
            require_revision_id=False,
            require_known_revision_semantics=False,
            require_provenance=True,
        )
        for code in (
            MarketDataFieldCode.OHLC,
            MarketDataFieldCode.VOLUME,
            MarketDataFieldCode.AMOUNT,
        )
    )


def formal_market_state_requirements() -> tuple[CapabilityRequirement, ...]:
    return tuple(
        CapabilityRequirement(
            field_code=code,
            allowed_states=(FieldCapabilityState.AVAILABLE,),
            require_available_time=True,
            require_revision_id=True,
            require_known_revision_semantics=True,
            require_provenance=True,
        )
        for code in FORMAL_MARKET_STATE_FIELDS
    )
