from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import ClassVar

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
    TruthAdmissionState,
    UpstreamRequirement,
    is_at_most,
    meet_pair,
    propagate_downstream_ceiling,
)
from v3_backend.domain.strategies import (
    PortfolioIntent,
    StrategyDefinitionVersion,
    StrategyEvaluationBindingVersion,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


TARGET_WEIGHT_SCHEMA_VERSION = "v3.target-weight-vector/1.0.0"
RISK_ADJUSTED_WEIGHT_SCHEMA_VERSION = "v3.risk_adjusted_weight_vector/1.0.0"
RISK_APPLICATION_SCHEMA_VERSION = "v3.risk_application_receipt/1.0.0"
WEIGHT_DECIMAL_PLACES = 12
WEIGHT_BUDGET_TOLERANCE = Decimal("0.000000000001")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_NON_EXACT = {"latest", "current", "unresolved", "auto", "default"}
_PORTFOLIO_PUBLISHER = "PortfolioService/Portfolio Construction"
_RISK_PUBLISHER = "Risk"
_UNRESOLVED_OWNER = "UNRESOLVED_CALLER_ASSERTED"


class WeightContractError(ValueError):
    """Raised when the shared canonical weight seam fails closed."""


class TargetKind(StrEnum):
    ABSOLUTE_COMPLETE = "ABSOLUTE_COMPLETE"


class WeightBasis(StrEnum):
    NAV = "NAV"


class ExposureProfile(StrEnum):
    LONG_ONLY_UNLEVERED = "LONG_ONLY_UNLEVERED"


class AbsentMemberPolicy(StrEnum):
    ZERO = "ZERO"


class ReferenceKind(StrEnum):
    CONSTRUCTION_SPEC = "CONSTRUCTION_SPEC"
    DIAGNOSTICS = "DIAGNOSTICS"
    PROVENANCE = "PROVENANCE"
    RISK_POLICY_SET = "RISK_POLICY_SET"
    RISK_MODEL = "RISK_MODEL"
    RISK_STATE = "RISK_STATE"
    RISK_EVIDENCE = "RISK_EVIDENCE"


class RiskDecision(StrEnum):
    PASS_THROUGH = "PASS_THROUGH"
    ADJUSTED = "ADJUSTED"


class RiskDecisionReason(StrEnum):
    NO_ADDITIONAL_RISK_TRANSFORM = "NO_ADDITIONAL_RISK_TRANSFORM"
    POLICY_TRANSFORM_APPLIED = "POLICY_TRANSFORM_APPLIED"


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise WeightContractError(f"{name} must be non-empty without edge whitespace")


def _require_exact_text(value: str, name: str) -> None:
    _require_text(value, name)
    lowered = value.lower()
    if lowered in _NON_EXACT or lowered.startswith("latest:"):
        raise WeightContractError(f"{name} must be exact; mutable aliases are forbidden")


def _require_sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise WeightContractError(f"{name} must be a lowercase full SHA-256")


def _require_aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WeightContractError(f"{name} must be timezone-aware")


def _wire_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_weight_decimal(value: object, name: str = "weight") -> str:
    """Normalize an exact decimal string without rounding or accepting negative zero."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise WeightContractError(f"{name} must be a decimal string")
    try:
        decimal = Decimal(value)
    except InvalidOperation as error:
        raise WeightContractError(f"{name} must be a finite decimal string") from error
    if not decimal.is_finite():
        raise WeightContractError(f"{name} must be a finite decimal string")
    if decimal.is_zero() and decimal.as_tuple().sign:
        raise WeightContractError(f"{name} must not be negative zero")
    if decimal.is_zero():
        return "0"
    normalized = decimal.normalize()
    fractional_places = max(-normalized.as_tuple().exponent, 0)
    if fractional_places > WEIGHT_DECIMAL_PLACES:
        raise WeightContractError(
            f"{name} exceeds the pinned {WEIGHT_DECIMAL_PLACES}-place precision"
        )
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _decimal(value: str) -> Decimal:
    return Decimal(value)


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    code_version: str
    runtime_profile_id: str
    environment_fingerprint: str

    def __post_init__(self) -> None:
        _require_exact_text(self.code_version, "code_version")
        _require_exact_text(self.runtime_profile_id, "runtime_profile_id")
        _require_exact_text(self.environment_fingerprint, "environment_fingerprint")

    def to_wire(self) -> dict[str, str]:
        return {
            "code_version": self.code_version,
            "runtime_profile_id": self.runtime_profile_id,
            "environment_fingerprint": self.environment_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class UnresolvedExactReference:
    """Exact bytes/ID without an external canonical owner receipt.

    A caller cannot promote this reference to FORMAL_ADMITTED merely by supplying an
    ID, hash, and formal-looking truth state. Until an owner resolver exists, the
    reference is explicitly capped at PRE_ALPHA.
    """

    reference_kind: ReferenceKind
    source_id: str
    content_sha256: str
    truth_admission: TruthAdmissionState
    owner_receipt_resolution: str = _UNRESOLVED_OWNER

    def __post_init__(self) -> None:
        if not isinstance(self.reference_kind, ReferenceKind):
            raise TypeError("reference_kind must be ReferenceKind")
        _require_exact_text(self.source_id, "source_id")
        _require_sha256(self.content_sha256, "content_sha256")
        if not isinstance(self.truth_admission, TruthAdmissionState):
            raise TypeError("truth_admission must be TruthAdmissionState")
        if self.owner_receipt_resolution != _UNRESOLVED_OWNER:
            raise WeightContractError("external owner receipt resolution is not caller-selectable")
        object.__setattr__(
            self,
            "truth_admission",
            meet_pair(self.truth_admission, PRE_ALPHA_CEILING),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "reference_kind": self.reference_kind.value,
            "source_id": self.source_id,
            "content_sha256": self.content_sha256,
            "owner_receipt_resolution": self.owner_receipt_resolution,
            "truth_admission": self.truth_admission.to_wire(),
        }


def _assert_canonical_definition(definition: StrategyDefinitionVersion) -> str:
    if not isinstance(definition, StrategyDefinitionVersion):
        raise TypeError("definition must be StrategyDefinitionVersion")
    wire = definition.to_wire()
    canonical_ir_sha256 = canonical_sha256(wire["canonical_ir"])
    if definition.canonical_ir_sha256 != canonical_ir_sha256:
        raise WeightContractError("PortfolioIntent StrategyDefinitionVersion IR hash mismatch")
    identity_payload = {
        "canonical_ir_sha256": canonical_ir_sha256,
        "canonical_ir": wire["canonical_ir"],
        "component_registry_version": definition.component_registry_version,
        "compiler_version": definition.compiler_version,
        "runtime_profile_id": definition.runtime_profile_id,
        "custom_dependency_refs": list(definition.custom_dependency_refs),
    }
    expected = "sdv_sha256_" + canonical_sha256(identity_payload)
    if definition.strategy_definition_version_id != expected:
        raise WeightContractError("PortfolioIntent StrategyDefinitionVersion identity mismatch")
    return canonical_sha256(wire)


def _assert_canonical_binding(binding: StrategyEvaluationBindingVersion) -> str:
    if not isinstance(binding, StrategyEvaluationBindingVersion):
        raise TypeError("binding must be StrategyEvaluationBindingVersion")
    wire = binding.to_wire()
    payload = {
        key: value
        for key, value in wire.items()
        if key != "strategy_evaluation_binding_version_id"
    }
    expected = "sebv_sha256_" + canonical_sha256(payload)
    if binding.strategy_evaluation_binding_version_id != expected:
        raise WeightContractError("PortfolioIntent StrategyEvaluationBindingVersion identity mismatch")
    return canonical_sha256(wire)


def _intent_identity_payload(intent: PortfolioIntent) -> dict[str, object]:
    wire = intent.to_wire()
    payload = {
        key: value
        for key, value in wire.items()
        if key
        not in {
            "artifact_type",
            "portfolio_intent_id",
            # FormalStrategyEvaluationService records this closed mint boundary
            # after computing the PortfolioIntent identity.  It is provenance
            # metadata, not part of the already-minted content identity.
            "formal_execution_contract_version",
        }
    }
    return payload


@dataclass(frozen=True, slots=True)
class PortfolioIntentSource:
    portfolio_intent_id: str
    portfolio_intent_content_sha256: str
    portfolio_intent_provenance_sha256: str
    strategy_definition_version_id: str
    strategy_definition_content_sha256: str
    strategy_evaluation_binding_version_id: str
    strategy_evaluation_binding_content_sha256: str
    universe_version_id: str
    universe_definition_sha256: str
    membership_artifact_id: str
    membership_sha256: str
    universe_instrument_ids: tuple[str, ...]
    source_reference_sha256: str
    truth_admission: TruthAdmissionState
    owner_receipt_resolution: str = _UNRESOLVED_OWNER

    @classmethod
    def create(
        cls,
        *,
        intent: PortfolioIntent,
        definition: StrategyDefinitionVersion,
        binding: StrategyEvaluationBindingVersion,
    ) -> PortfolioIntentSource:
        if not isinstance(intent, PortfolioIntent):
            raise TypeError("intent must be the current-main PortfolioIntent type")
        definition_sha256 = _assert_canonical_definition(definition)
        binding_sha256 = _assert_canonical_binding(binding)
        if binding.strategy_definition_version_id != definition.strategy_definition_version_id:
            raise WeightContractError("PortfolioIntent definition/binding mismatch")
        if intent.strategy_definition_version_id != definition.strategy_definition_version_id:
            raise WeightContractError("PortfolioIntent StrategyDefinitionVersion mismatch")
        if (
            intent.strategy_evaluation_binding_version_id
            != binding.strategy_evaluation_binding_version_id
        ):
            raise WeightContractError("PortfolioIntent evaluation binding mismatch")
        observed_inputs = tuple(
            (value.binding_key, value.artifact_id, value.content_sha256)
            for value in intent.input_artifacts
        )
        expected_inputs = tuple(
            (value.binding_key, value.artifact_id, value.content_sha256)
            for value in binding.input_references
        )
        if observed_inputs != expected_inputs:
            raise WeightContractError("PortfolioIntent exact input evidence mismatch")
        if not is_at_most(intent.truth_admission, definition.truth_admission):
            raise WeightContractError("PortfolioIntent truth exceeds StrategyDefinitionVersion")
        if not is_at_most(intent.truth_admission, binding.truth_admission):
            raise WeightContractError("PortfolioIntent truth exceeds evaluation binding")

        payload = _intent_identity_payload(intent)
        content_sha256 = canonical_sha256(payload)
        if intent.portfolio_intent_id != "pint_sha256_" + content_sha256:
            raise WeightContractError("PortfolioIntent is not a canonical exact source object")
        provenance = {
            "strategy_definition_version_id": intent.strategy_definition_version_id,
            "strategy_evaluation_binding_version_id": intent.strategy_evaluation_binding_version_id,
            "source_signal_artifact_id": intent.source_signal_artifact_id,
            "source_selection_artifact_id": intent.source_selection_artifact_id,
            "source_signal_provenance_sha256": intent.source_signal_provenance_sha256,
            "source_selection_provenance_sha256": intent.source_selection_provenance_sha256,
            "input_artifacts": [value.to_wire() for value in intent.input_artifacts],
            "publisher_boundary": "PORTFOLIO_SERVICE_IS_SOLE_TARGET_WEIGHT_VECTOR_PUBLISHER",
        }
        if intent.provenance_sha256 != canonical_sha256(provenance):
            raise WeightContractError("PortfolioIntent provenance mismatch")

        source_payload = {
            "portfolio_intent_id": intent.portfolio_intent_id,
            "portfolio_intent_content_sha256": content_sha256,
            "portfolio_intent_provenance_sha256": intent.provenance_sha256,
            "strategy_definition_version_id": definition.strategy_definition_version_id,
            "strategy_definition_content_sha256": definition_sha256,
            "strategy_evaluation_binding_version_id": binding.strategy_evaluation_binding_version_id,
            "strategy_evaluation_binding_content_sha256": binding_sha256,
            "universe_version_id": binding.universe.universe_version_id,
            "universe_definition_sha256": binding.universe.definition_sha256,
            "membership_artifact_id": binding.universe.membership_artifact_id,
            "membership_sha256": binding.universe.membership_sha256,
            "universe_instrument_ids": list(binding.universe.instrument_ids),
            "owner_receipt_resolution": _UNRESOLVED_OWNER,
        }
        return cls(
            portfolio_intent_id=intent.portfolio_intent_id,
            portfolio_intent_content_sha256=content_sha256,
            portfolio_intent_provenance_sha256=intent.provenance_sha256,
            strategy_definition_version_id=definition.strategy_definition_version_id,
            strategy_definition_content_sha256=definition_sha256,
            strategy_evaluation_binding_version_id=binding.strategy_evaluation_binding_version_id,
            strategy_evaluation_binding_content_sha256=binding_sha256,
            universe_version_id=binding.universe.universe_version_id,
            universe_definition_sha256=binding.universe.definition_sha256,
            membership_artifact_id=binding.universe.membership_artifact_id,
            membership_sha256=binding.universe.membership_sha256,
            universe_instrument_ids=binding.universe.instrument_ids,
            source_reference_sha256=canonical_sha256(source_payload),
            truth_admission=meet_pair(intent.truth_admission, PRE_ALPHA_CEILING),
        )

    def _reference_payload(self) -> dict[str, object]:
        return {
            "portfolio_intent_id": self.portfolio_intent_id,
            "portfolio_intent_content_sha256": self.portfolio_intent_content_sha256,
            "portfolio_intent_provenance_sha256": self.portfolio_intent_provenance_sha256,
            "strategy_definition_version_id": self.strategy_definition_version_id,
            "strategy_definition_content_sha256": self.strategy_definition_content_sha256,
            "strategy_evaluation_binding_version_id": self.strategy_evaluation_binding_version_id,
            "strategy_evaluation_binding_content_sha256": self.strategy_evaluation_binding_content_sha256,
            "universe_version_id": self.universe_version_id,
            "universe_definition_sha256": self.universe_definition_sha256,
            "membership_artifact_id": self.membership_artifact_id,
            "membership_sha256": self.membership_sha256,
            "universe_instrument_ids": list(self.universe_instrument_ids),
            "owner_receipt_resolution": self.owner_receipt_resolution,
        }

    def assert_canonical(self) -> None:
        for name in (
            "portfolio_intent_content_sha256",
            "portfolio_intent_provenance_sha256",
            "strategy_definition_content_sha256",
            "strategy_evaluation_binding_content_sha256",
            "universe_definition_sha256",
            "membership_sha256",
            "source_reference_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        if self.portfolio_intent_id != "pint_sha256_" + self.portfolio_intent_content_sha256:
            raise WeightContractError("PortfolioIntent source ID/content hash mismatch")
        if not self.strategy_definition_version_id.startswith("sdv_sha256_"):
            raise WeightContractError("PortfolioIntent StrategyDefinitionVersion ID is not canonical")
        if not self.strategy_evaluation_binding_version_id.startswith("sebv_sha256_"):
            raise WeightContractError("PortfolioIntent evaluation binding ID is not canonical")
        if self.membership_artifact_id != "art_sha256_" + self.membership_sha256:
            raise WeightContractError("PortfolioIntent membership artifact/hash mismatch")
        if self.owner_receipt_resolution != _UNRESOLVED_OWNER:
            raise WeightContractError("PortfolioIntent owner receipt is not canonical")
        ordered = tuple(sorted(self.universe_instrument_ids))
        if not ordered or ordered != self.universe_instrument_ids or len(ordered) != len(set(ordered)):
            raise WeightContractError("PortfolioIntent universe membership is not canonical")
        if canonical_sha256(self._reference_payload()) != self.source_reference_sha256:
            raise WeightContractError("PortfolioIntent source reference hash mismatch")
        if not is_at_most(self.truth_admission, PRE_ALPHA_CEILING):
            raise WeightContractError("unresolved PortfolioIntent owner cannot exceed PRE_ALPHA")

    def to_wire(self) -> dict[str, object]:
        self.assert_canonical()
        return {
            **self._reference_payload(),
            "source_reference_sha256": self.source_reference_sha256,
            "truth_admission": self.truth_admission.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class TargetWeightRow:
    instrument_id: str
    target_weight: str

    def __post_init__(self) -> None:
        _require_text(self.instrument_id, "instrument_id")
        object.__setattr__(
            self,
            "target_weight",
            normalize_weight_decimal(self.target_weight, "target_weight"),
        )

    def to_wire(self) -> dict[str, str]:
        return {
            "instrument_id": self.instrument_id,
            "target_weight": self.target_weight,
        }


RiskAdjustedWeightRow = TargetWeightRow


def _canonical_rows(
    rows: tuple[TargetWeightRow, ...],
    universe_instrument_ids: tuple[str, ...],
) -> tuple[TargetWeightRow, ...]:
    if any(not isinstance(value, TargetWeightRow) for value in rows):
        raise TypeError("rows must contain only TargetWeightRow values")
    ordered = tuple(sorted(rows, key=lambda value: value.instrument_id))
    instrument_ids = tuple(value.instrument_id for value in ordered)
    if len(instrument_ids) != len(set(instrument_ids)):
        raise WeightContractError("weight rows must be unique by instrument_id")
    if not set(instrument_ids).issubset(universe_instrument_ids):
        raise WeightContractError("weight row instrument is outside exact universe membership")
    if any(_decimal(value.target_weight).is_zero() for value in ordered):
        raise WeightContractError(
            "explicit zero weight rows are forbidden; AbsentMemberPolicy.ZERO is canonical"
        )
    return ordered


def _validate_long_only_budget(rows: tuple[TargetWeightRow, ...], cash_weight: str) -> None:
    weights = tuple(_decimal(value.target_weight) for value in rows)
    cash = _decimal(cash_weight)
    if any(value < 0 for value in weights) or cash < 0:
        raise WeightContractError("LONG_ONLY_UNLEVERED weights and cash must be non-negative")
    total = sum(weights, Decimal(0)) + cash
    if abs(total - Decimal(1)) > WEIGHT_BUDGET_TOLERANCE:
        raise WeightContractError(
            "LONG_ONLY_UNLEVERED weights plus cash must equal one within the pinned tolerance"
        )


def _canonical_references(
    references: tuple[UnresolvedExactReference, ...],
) -> tuple[UnresolvedExactReference, ...]:
    if any(not isinstance(value, UnresolvedExactReference) for value in references):
        raise TypeError("references must contain only UnresolvedExactReference values")
    ordered = tuple(sorted(references, key=lambda value: (value.reference_kind.value, value.source_id)))
    keys = tuple((value.reference_kind, value.source_id) for value in ordered)
    if len(keys) != len(set(keys)):
        raise WeightContractError("exact reference kind/source pairs must be unique")
    return ordered


@dataclass(frozen=True, slots=True)
class TargetWeightVector:
    target_weight_vector_id: str
    content_sha256: str
    source: PortfolioIntentSource
    construction_spec: UnresolvedExactReference
    evidence_refs: tuple[UnresolvedExactReference, ...]
    runtime_identity: RuntimeIdentity
    base_currency: str
    as_of: datetime
    decision_time: datetime
    rebalance_time: datetime
    valid_until: datetime
    cash_weight: str
    rows: tuple[TargetWeightRow, ...]
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = TARGET_WEIGHT_SCHEMA_VERSION
    publisher_service: ClassVar[str] = _PORTFOLIO_PUBLISHER
    target_kind: ClassVar[TargetKind] = TargetKind.ABSOLUTE_COMPLETE
    weight_basis: ClassVar[WeightBasis] = WeightBasis.NAV
    exposure_profile: ClassVar[ExposureProfile] = ExposureProfile.LONG_ONLY_UNLEVERED
    absent_member_policy: ClassVar[AbsentMemberPolicy] = AbsentMemberPolicy.ZERO

    @classmethod
    def create(
        cls,
        *,
        source: PortfolioIntentSource,
        construction_spec: UnresolvedExactReference,
        evidence_refs: tuple[UnresolvedExactReference, ...],
        runtime_identity: RuntimeIdentity,
        base_currency: str,
        as_of: datetime,
        decision_time: datetime,
        rebalance_time: datetime,
        valid_until: datetime,
        cash_weight: str,
        rows: tuple[TargetWeightRow, ...],
    ) -> TargetWeightVector:
        if not isinstance(source, PortfolioIntentSource):
            raise TypeError("source must be PortfolioIntentSource")
        source.assert_canonical()
        if (
            not isinstance(construction_spec, UnresolvedExactReference)
            or construction_spec.reference_kind is not ReferenceKind.CONSTRUCTION_SPEC
        ):
            raise WeightContractError("construction_spec must be an exact CONSTRUCTION_SPEC reference")
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be RuntimeIdentity")
        if not isinstance(base_currency, str) or _CURRENCY.fullmatch(base_currency) is None:
            raise WeightContractError("base_currency must be an uppercase three-letter code")
        for name, value in (
            ("as_of", as_of),
            ("decision_time", decision_time),
            ("rebalance_time", rebalance_time),
            ("valid_until", valid_until),
        ):
            _require_aware(value, name)
        if not as_of <= decision_time <= rebalance_time <= valid_until:
            raise WeightContractError(
                "target times must satisfy as_of <= decision_time <= rebalance_time <= valid_until"
            )
        ordered_rows = _canonical_rows(rows, source.universe_instrument_ids)
        canonical_cash = normalize_weight_decimal(cash_weight, "cash_weight")
        _validate_long_only_budget(ordered_rows, canonical_cash)
        ordered_evidence = _canonical_references(evidence_refs)
        allowed_evidence_kinds = {
            ReferenceKind.DIAGNOSTICS,
            ReferenceKind.PROVENANCE,
        }
        evidence_kinds = {value.reference_kind for value in ordered_evidence}
        if not evidence_kinds.issubset(allowed_evidence_kinds):
            raise WeightContractError(
                "TargetWeightVector evidence_refs allow only DIAGNOSTICS and PROVENANCE"
            )
        if not allowed_evidence_kinds.issubset(evidence_kinds):
            raise WeightContractError(
                "TargetWeightVector requires exact DIAGNOSTICS and PROVENANCE evidence refs"
            )
        truth = propagate_downstream_ceiling(
            FORMAL_ADMITTED_CEILING,
            (
                UpstreamRequirement("portfolio_intent:" + source.portfolio_intent_id, source.truth_admission),
                UpstreamRequirement(
                    "construction_spec:" + construction_spec.source_id,
                    construction_spec.truth_admission,
                ),
                *(
                    UpstreamRequirement(
                        f"evidence:{value.reference_kind.value}:{value.source_id}",
                        value.truth_admission,
                    )
                    for value in ordered_evidence
                ),
            ),
        )
        payload = cls._payload(
            source=source,
            construction_spec=construction_spec,
            evidence_refs=ordered_evidence,
            runtime_identity=runtime_identity,
            base_currency=base_currency,
            as_of=as_of,
            decision_time=decision_time,
            rebalance_time=rebalance_time,
            valid_until=valid_until,
            cash_weight=canonical_cash,
            rows=ordered_rows,
            truth_admission=truth,
        )
        digest = canonical_sha256(payload)
        return cls(
            target_weight_vector_id="twv_sha256_" + digest,
            content_sha256=digest,
            source=source,
            construction_spec=construction_spec,
            evidence_refs=ordered_evidence,
            runtime_identity=runtime_identity,
            base_currency=base_currency,
            as_of=as_of,
            decision_time=decision_time,
            rebalance_time=rebalance_time,
            valid_until=valid_until,
            cash_weight=canonical_cash,
            rows=ordered_rows,
            truth_admission=truth,
        )

    @classmethod
    def _payload(
        cls,
        *,
        source: PortfolioIntentSource,
        construction_spec: UnresolvedExactReference,
        evidence_refs: tuple[UnresolvedExactReference, ...],
        runtime_identity: RuntimeIdentity,
        base_currency: str,
        as_of: datetime,
        decision_time: datetime,
        rebalance_time: datetime,
        valid_until: datetime,
        cash_weight: str,
        rows: tuple[TargetWeightRow, ...],
        truth_admission: TruthAdmissionState,
    ) -> dict[str, object]:
        return {
            "schema_version": cls.schema_version,
            "publisher_service": cls.publisher_service,
            "target_kind": cls.target_kind.value,
            "weight_basis": cls.weight_basis.value,
            "exposure_profile": cls.exposure_profile.value,
            "base_currency": base_currency,
            "as_of": _wire_time(as_of),
            "decision_time": _wire_time(decision_time),
            "rebalance_time": _wire_time(rebalance_time),
            "valid_until": _wire_time(valid_until),
            "source": source.to_wire(),
            "universe_version_id": source.universe_version_id,
            "membership_artifact_id": source.membership_artifact_id,
            "membership_sha256": source.membership_sha256,
            "construction_spec": construction_spec.to_wire(),
            "cash_weight": cash_weight,
            "rows": [value.to_wire() for value in rows],
            "absent_member_policy": cls.absent_member_policy.value,
            "evidence_refs": [value.to_wire() for value in evidence_refs],
            "runtime_identity": runtime_identity.to_wire(),
            "truth_admission": truth_admission.to_wire(),
        }

    def assert_canonical(self) -> None:
        rebuilt = type(self).create(
            source=self.source,
            construction_spec=self.construction_spec,
            evidence_refs=self.evidence_refs,
            runtime_identity=self.runtime_identity,
            base_currency=self.base_currency,
            as_of=self.as_of,
            decision_time=self.decision_time,
            rebalance_time=self.rebalance_time,
            valid_until=self.valid_until,
            cash_weight=self.cash_weight,
            rows=self.rows,
        )
        if rebuilt != self:
            raise WeightContractError("TargetWeightVector ID/content/provenance mismatch")

    def to_wire(self) -> dict[str, object]:
        self.assert_canonical()
        return {
            "artifact_type": "TargetWeightVector",
            "target_weight_vector_id": self.target_weight_vector_id,
            "content_sha256": self.content_sha256,
            **self._payload(
                source=self.source,
                construction_spec=self.construction_spec,
                evidence_refs=self.evidence_refs,
                runtime_identity=self.runtime_identity,
                base_currency=self.base_currency,
                as_of=self.as_of,
                decision_time=self.decision_time,
                rebalance_time=self.rebalance_time,
                valid_until=self.valid_until,
                cash_weight=self.cash_weight,
                rows=self.rows,
                truth_admission=self.truth_admission,
            ),
        }


@dataclass(frozen=True, slots=True)
class RiskStageEvidence:
    stage_order: int
    stage_id: str
    policy_id: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.stage_order, int) or isinstance(self.stage_order, bool) or self.stage_order < 1:
            raise WeightContractError("stage_order must be a positive integer")
        _require_exact_text(self.stage_id, "stage_id")
        _require_exact_text(self.policy_id, "policy_id")
        _require_sha256(self.evidence_sha256, "evidence_sha256")

    def to_wire(self) -> dict[str, object]:
        return {
            "stage_order": self.stage_order,
            "stage_id": self.stage_id,
            "policy_id": self.policy_id,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class RiskApplicationReceipt:
    risk_application_receipt_id: str
    content_sha256: str
    source_target: TargetWeightVector
    source_target_weight_vector_id: str
    source_target_content_sha256: str
    risk_policy_set: UnresolvedExactReference
    decision: RiskDecision
    decision_reason: RiskDecisionReason
    stages: tuple[RiskStageEvidence, ...]
    ordered_stage_evidence_sha256: str
    supporting_refs: tuple[UnresolvedExactReference, ...]
    runtime_identity: RuntimeIdentity
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = RISK_APPLICATION_SCHEMA_VERSION
    publisher_service: ClassVar[str] = _RISK_PUBLISHER

    @classmethod
    def create(
        cls,
        *,
        source_target: TargetWeightVector,
        risk_policy_set: UnresolvedExactReference,
        decision: RiskDecision,
        decision_reason: RiskDecisionReason,
        stages: tuple[RiskStageEvidence, ...],
        supporting_refs: tuple[UnresolvedExactReference, ...],
        runtime_identity: RuntimeIdentity,
    ) -> RiskApplicationReceipt:
        if not isinstance(source_target, TargetWeightVector):
            raise TypeError("source_target must be TargetWeightVector")
        source_target.assert_canonical()
        if (
            not isinstance(risk_policy_set, UnresolvedExactReference)
            or risk_policy_set.reference_kind is not ReferenceKind.RISK_POLICY_SET
        ):
            raise WeightContractError("risk_policy_set must be an exact RISK_POLICY_SET reference")
        if not isinstance(decision, RiskDecision):
            raise TypeError("decision must be RiskDecision")
        if not isinstance(decision_reason, RiskDecisionReason):
            raise TypeError("decision_reason must be RiskDecisionReason")
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be RuntimeIdentity")
        if decision is RiskDecision.PASS_THROUGH:
            if decision_reason is not RiskDecisionReason.NO_ADDITIONAL_RISK_TRANSFORM:
                raise WeightContractError("PASS_THROUGH requires NO_ADDITIONAL_RISK_TRANSFORM")
        elif decision_reason is not RiskDecisionReason.POLICY_TRANSFORM_APPLIED:
            raise WeightContractError("ADJUSTED requires POLICY_TRANSFORM_APPLIED")
        if not stages or any(not isinstance(value, RiskStageEvidence) for value in stages):
            raise WeightContractError("risk application requires ordered stage evidence")
        if tuple(value.stage_order for value in stages) != tuple(range(1, len(stages) + 1)):
            raise WeightContractError("risk stage order must be contiguous and already canonical")
        if len({value.stage_id for value in stages}) != len(stages):
            raise WeightContractError("risk stage IDs must be unique")
        ordered_refs = _canonical_references(supporting_refs)
        allowed_supporting_kinds = {
            ReferenceKind.RISK_MODEL,
            ReferenceKind.RISK_STATE,
            ReferenceKind.RISK_EVIDENCE,
            ReferenceKind.PROVENANCE,
        }
        if any(
            value.reference_kind not in allowed_supporting_kinds
            for value in ordered_refs
        ):
            raise WeightContractError(
                "RiskApplicationReceipt supporting_refs allow only "
                "RISK_MODEL, RISK_STATE, RISK_EVIDENCE, and PROVENANCE"
            )
        stage_digest = canonical_sha256([value.to_wire() for value in stages])
        truth = propagate_downstream_ceiling(
            FORMAL_ADMITTED_CEILING,
            (
                UpstreamRequirement(
                    "source_target:" + source_target.target_weight_vector_id,
                    source_target.truth_admission,
                ),
                UpstreamRequirement(
                    "risk_policy_set:" + risk_policy_set.source_id,
                    risk_policy_set.truth_admission,
                ),
                *(
                    UpstreamRequirement(
                        f"risk_support:{value.reference_kind.value}:{value.source_id}",
                        value.truth_admission,
                    )
                    for value in ordered_refs
                ),
            ),
        )
        payload = cls._payload(
            source_target_weight_vector_id=source_target.target_weight_vector_id,
            source_target_content_sha256=source_target.content_sha256,
            risk_policy_set=risk_policy_set,
            decision=decision,
            decision_reason=decision_reason,
            stages=stages,
            ordered_stage_evidence_sha256=stage_digest,
            supporting_refs=ordered_refs,
            runtime_identity=runtime_identity,
            truth_admission=truth,
        )
        digest = canonical_sha256(payload)
        return cls(
            risk_application_receipt_id="rar_sha256_" + digest,
            content_sha256=digest,
            source_target=source_target,
            source_target_weight_vector_id=source_target.target_weight_vector_id,
            source_target_content_sha256=source_target.content_sha256,
            risk_policy_set=risk_policy_set,
            decision=decision,
            decision_reason=decision_reason,
            stages=stages,
            ordered_stage_evidence_sha256=stage_digest,
            supporting_refs=ordered_refs,
            runtime_identity=runtime_identity,
            truth_admission=truth,
        )

    @classmethod
    def _payload(
        cls,
        *,
        source_target_weight_vector_id: str,
        source_target_content_sha256: str,
        risk_policy_set: UnresolvedExactReference,
        decision: RiskDecision,
        decision_reason: RiskDecisionReason,
        stages: tuple[RiskStageEvidence, ...],
        ordered_stage_evidence_sha256: str,
        supporting_refs: tuple[UnresolvedExactReference, ...],
        runtime_identity: RuntimeIdentity,
        truth_admission: TruthAdmissionState,
    ) -> dict[str, object]:
        return {
            "schema_version": cls.schema_version,
            "publisher_service": cls.publisher_service,
            "source_target_weight_vector_id": source_target_weight_vector_id,
            "source_target_content_sha256": source_target_content_sha256,
            "risk_policy_set": risk_policy_set.to_wire(),
            "decision": decision.value,
            "decision_reason": decision_reason.value,
            "stages": [value.to_wire() for value in stages],
            "ordered_stage_evidence_sha256": ordered_stage_evidence_sha256,
            "supporting_refs": [value.to_wire() for value in supporting_refs],
            "runtime_identity": runtime_identity.to_wire(),
            "truth_admission": truth_admission.to_wire(),
        }

    def assert_canonical(self) -> None:
        rebuilt = type(self).create(
            source_target=self.source_target,
            risk_policy_set=self.risk_policy_set,
            decision=self.decision,
            decision_reason=self.decision_reason,
            stages=self.stages,
            supporting_refs=self.supporting_refs,
            runtime_identity=self.runtime_identity,
        )
        if rebuilt != self:
            raise WeightContractError("RiskApplicationReceipt ID/content/provenance mismatch")

    def to_wire(self) -> dict[str, object]:
        self.assert_canonical()
        return {
            "artifact_type": "RiskApplicationReceipt",
            "risk_application_receipt_id": self.risk_application_receipt_id,
            "content_sha256": self.content_sha256,
            **self._payload(
                source_target_weight_vector_id=self.source_target_weight_vector_id,
                source_target_content_sha256=self.source_target_content_sha256,
                risk_policy_set=self.risk_policy_set,
                decision=self.decision,
                decision_reason=self.decision_reason,
                stages=self.stages,
                ordered_stage_evidence_sha256=self.ordered_stage_evidence_sha256,
                supporting_refs=self.supporting_refs,
                runtime_identity=self.runtime_identity,
                truth_admission=self.truth_admission,
            ),
        }


@dataclass(frozen=True, slots=True)
class RiskAdjustedWeightVector:
    risk_adjusted_weight_vector_id: str
    content_sha256: str
    source_target: TargetWeightVector
    risk_application: RiskApplicationReceipt
    runtime_identity: RuntimeIdentity
    cash_weight: str
    rows: tuple[RiskAdjustedWeightRow, ...]
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = RISK_ADJUSTED_WEIGHT_SCHEMA_VERSION
    publisher_service: ClassVar[str] = _RISK_PUBLISHER

    @classmethod
    def create(
        cls,
        *,
        source_target: TargetWeightVector,
        risk_application: RiskApplicationReceipt,
        runtime_identity: RuntimeIdentity,
        cash_weight: str,
        rows: tuple[RiskAdjustedWeightRow, ...],
    ) -> RiskAdjustedWeightVector:
        if not isinstance(source_target, TargetWeightVector):
            raise TypeError("source_target must be TargetWeightVector")
        source_target.assert_canonical()
        if not isinstance(risk_application, RiskApplicationReceipt):
            raise TypeError("risk_application must be RiskApplicationReceipt")
        risk_application.assert_canonical()
        if (
            risk_application.source_target_weight_vector_id
            != source_target.target_weight_vector_id
            or risk_application.source_target_content_sha256
            != source_target.content_sha256
        ):
            raise WeightContractError(
                "RiskApplicationReceipt exact source TargetWeightVector binding mismatch"
            )
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be RuntimeIdentity")
        ordered_rows = _canonical_rows(rows, source_target.source.universe_instrument_ids)
        canonical_cash = normalize_weight_decimal(cash_weight, "cash_weight")
        _validate_long_only_budget(ordered_rows, canonical_cash)
        if risk_application.decision is RiskDecision.PASS_THROUGH:
            if ordered_rows != source_target.rows or canonical_cash != source_target.cash_weight:
                raise WeightContractError(
                    "PASS_THROUGH rows and cash must be semantically equal to the source target"
                )
        truth = propagate_downstream_ceiling(
            FORMAL_ADMITTED_CEILING,
            (
                UpstreamRequirement(
                    "source_target:" + source_target.target_weight_vector_id,
                    source_target.truth_admission,
                ),
                UpstreamRequirement(
                    "risk_application:" + risk_application.risk_application_receipt_id,
                    risk_application.truth_admission,
                ),
            ),
        )
        if not is_at_most(truth, source_target.truth_admission):
            raise WeightContractError("RiskAdjustedWeightVector cannot promote source truth")
        payload = cls._payload(
            source_target=source_target,
            risk_application=risk_application,
            runtime_identity=runtime_identity,
            cash_weight=canonical_cash,
            rows=ordered_rows,
            truth_admission=truth,
        )
        digest = canonical_sha256(payload)
        return cls(
            risk_adjusted_weight_vector_id="rawv_sha256_" + digest,
            content_sha256=digest,
            source_target=source_target,
            risk_application=risk_application,
            runtime_identity=runtime_identity,
            cash_weight=canonical_cash,
            rows=ordered_rows,
            truth_admission=truth,
        )

    @classmethod
    def _payload(
        cls,
        *,
        source_target: TargetWeightVector,
        risk_application: RiskApplicationReceipt,
        runtime_identity: RuntimeIdentity,
        cash_weight: str,
        rows: tuple[RiskAdjustedWeightRow, ...],
        truth_admission: TruthAdmissionState,
    ) -> dict[str, object]:
        return {
            "schema_version": cls.schema_version,
            "publisher_service": cls.publisher_service,
            "source_target_weight_vector_id": source_target.target_weight_vector_id,
            "source_target_content_sha256": source_target.content_sha256,
            "risk_application_receipt_id": risk_application.risk_application_receipt_id,
            "risk_application_content_sha256": risk_application.content_sha256,
            "risk_decision": risk_application.decision.value,
            "risk_decision_reason": risk_application.decision_reason.value,
            "ordered_stage_evidence_sha256": risk_application.ordered_stage_evidence_sha256,
            "target_kind": source_target.target_kind.value,
            "weight_basis": source_target.weight_basis.value,
            "exposure_profile": source_target.exposure_profile.value,
            "base_currency": source_target.base_currency,
            "cash_weight": cash_weight,
            "rows": [value.to_wire() for value in rows],
            "absent_member_policy": source_target.absent_member_policy.value,
            "runtime_identity": runtime_identity.to_wire(),
            "truth_admission": truth_admission.to_wire(),
        }

    def assert_canonical(self) -> None:
        rebuilt = type(self).create(
            source_target=self.source_target,
            risk_application=self.risk_application,
            runtime_identity=self.runtime_identity,
            cash_weight=self.cash_weight,
            rows=self.rows,
        )
        if rebuilt != self:
            raise WeightContractError("RiskAdjustedWeightVector ID/content/provenance mismatch")

    def to_wire(self) -> dict[str, object]:
        self.assert_canonical()
        return {
            "artifact_type": "RiskAdjustedWeightVector",
            "risk_adjusted_weight_vector_id": self.risk_adjusted_weight_vector_id,
            "content_sha256": self.content_sha256,
            **self._payload(
                source_target=self.source_target,
                risk_application=self.risk_application,
                runtime_identity=self.runtime_identity,
                cash_weight=self.cash_weight,
                rows=self.rows,
                truth_admission=self.truth_admission,
            ),
        }


__all__ = [
    "AbsentMemberPolicy",
    "ExposureProfile",
    "PortfolioIntentSource",
    "ReferenceKind",
    "RiskAdjustedWeightRow",
    "RiskAdjustedWeightVector",
    "RiskApplicationReceipt",
    "RiskDecision",
    "RiskDecisionReason",
    "RiskStageEvidence",
    "RuntimeIdentity",
    "TargetKind",
    "TargetWeightRow",
    "TargetWeightVector",
    "UnresolvedExactReference",
    "WEIGHT_BUDGET_TOLERANCE",
    "WEIGHT_DECIMAL_PLACES",
    "WeightBasis",
    "WeightContractError",
    "normalize_weight_decimal",
]
