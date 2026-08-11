from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Mapping

from v3_backend.contracts.common.truth_admission import (
    PRE_ALPHA_CEILING,
    TruthAdmissionState,
)
from v3_backend.domain.weights import (
    AbsentMemberPolicy,
    ExposureProfile,
    ReferenceKind,
    RuntimeIdentity,
    TargetWeightRow,
    TargetWeightVector,
    UnresolvedExactReference,
    WEIGHT_BUDGET_TOLERANCE,
    WEIGHT_DECIMAL_PLACES,
    normalize_weight_decimal,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


CONSTRUCTION_SPEC_SCHEMA_VERSION = "v3.portfolio-construction-spec/1.1.0"
CONSTRUCTION_DIAGNOSTICS_SCHEMA_VERSION = (
    "v3.portfolio-construction-diagnostics/1.1.0"
)
CONSTRUCTION_PROVENANCE_SCHEMA_VERSION = (
    "v3.portfolio-construction-provenance/1.1.0"
)
OPTIMIZER_CANDIDATE_SCHEMA_VERSION = "v3.portfolio-optimizer-candidate/1.0.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ConstructionMethod(StrEnum):
    EQUAL_WEIGHT_SELECTED = "EQUAL_WEIGHT_SELECTED"
    NORMALIZED_DESIRED_EXPOSURE = "NORMALIZED_DESIRED_EXPOSURE"


class IntentExposureMode(StrEnum):
    ABSOLUTE_DESIRED_EXPOSURE = "ABSOLUTE_DESIRED_EXPOSURE"
    RELATIVE_DESIRED_EXPOSURE = "RELATIVE_DESIRED_EXPOSURE"


class IntentCashPolicy(StrEnum):
    RESIDUAL = "RESIDUAL"


class IntentRebalancePolicy(StrEnum):
    AT_BOUND_DECISION_TIME = "AT_BOUND_DECISION_TIME"


class IntentConstraintNormalization(StrEnum):
    EQUAL_DESIRED_EXPOSURE = "EQUAL_DESIRED_EXPOSURE"
    RELATIVE_DESIRED_EXPOSURE = "RELATIVE_DESIRED_EXPOSURE"


class DesiredExposureMagnitudePolicy(StrEnum):
    NOT_PRESERVED = "INTENT_DESIRED_EXPOSURE_MAGNITUDES_NOT_PRESERVED"
    RELATIVE_INPUTS = "INTENT_DESIRED_EXPOSURES_INTERPRETED_AS_RELATIVE_INPUTS"


class SelectionTransform(StrEnum):
    REWEIGHTED_EQUAL = "SELECTION_MEMBERSHIP_REWEIGHTED_EQUAL"
    NORMALIZED_TO_BUDGET = (
        "RELATIVE_DESIRED_EXPOSURES_NORMALIZED_TO_PINNED_INVESTED_BUDGET"
    )


class IntentSemanticAdmissionStatus(StrEnum):
    PASSED = "PASSED_CLOSED_PORTFOLIO_INTENT_SEMANTICS_V1"


class TimingValidationStatus(StrEnum):
    PASSED = "PASSED_EXACT_BINDING_PERIOD_AND_KNOWLEDGE_CUTOFF_V1"


class ConstraintCheckStatus(StrEnum):
    PASSED = "PASSED"


class ConstructionRejectionReason(StrEnum):
    INVALID_PORTFOLIO_INTENT = "INVALID_PORTFOLIO_INTENT"
    SPEC_RUNTIME_MISMATCH = "SPEC_RUNTIME_MISMATCH"
    EXPOSURE_MODE_MISMATCH = "EXPOSURE_MODE_MISMATCH"
    CASH_POLICY_MISMATCH = "CASH_POLICY_MISMATCH"
    REBALANCE_INTENT_MISMATCH = "REBALANCE_INTENT_MISMATCH"
    UNSUPPORTED_INTENT_CONSTRAINT = "UNSUPPORTED_INTENT_CONSTRAINT"
    INTENT_CONSTRAINT_MISMATCH = "INTENT_CONSTRAINT_MISMATCH"
    DESIRED_EXPOSURE_SEMANTICS_MISMATCH = (
        "DESIRED_EXPOSURE_SEMANTICS_MISMATCH"
    )
    INVALID_TARGET_TIMING = "INVALID_TARGET_TIMING"
    AS_OF_OUTSIDE_BINDING_PERIOD = "AS_OF_OUTSIDE_BINDING_PERIOD"
    DECISION_TIME_OUTSIDE_BINDING_PERIOD = (
        "DECISION_TIME_OUTSIDE_BINDING_PERIOD"
    )
    AS_OF_AFTER_KNOWLEDGE_CUTOFF = "AS_OF_AFTER_KNOWLEDGE_CUTOFF"
    DECISION_TIME_AFTER_KNOWLEDGE_CUTOFF = (
        "DECISION_TIME_AFTER_KNOWLEDGE_CUTOFF"
    )
    DUPLICATE_INSTRUMENT = "DUPLICATE_INSTRUMENT"
    OUTSIDE_EXACT_UNIVERSE = "OUTSIDE_EXACT_UNIVERSE"
    INVALID_DESIRED_EXPOSURE = "INVALID_DESIRED_EXPOSURE"
    EMPTY_SELECTION_INFEASIBLE = "EMPTY_SELECTION_INFEASIBLE"
    ZERO_DESIRED_EXPOSURE_TOTAL = "ZERO_DESIRED_EXPOSURE_TOTAL"
    INSTRUMENT_WEIGHT_BOUND = "INSTRUMENT_WEIGHT_BOUND"
    GROSS_EXPOSURE_BOUND = "GROSS_EXPOSURE_BOUND"
    NET_EXPOSURE_BOUND = "NET_EXPOSURE_BOUND"
    OPTIMIZER_NOT_CONFIGURED = "OPTIMIZER_NOT_CONFIGURED"


class PortfolioConstructionRejected(ValueError):
    def __init__(self, reason: ConstructionRejectionReason, detail: str) -> None:
        if not isinstance(reason, ConstructionRejectionReason):
            raise TypeError("reason must be ConstructionRejectionReason")
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty without edge whitespace")


def _wire_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("decimal evidence must be finite")
    if value.is_zero():
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _wire_time(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timing evidence must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _method_intent_semantics(
    method: ConstructionMethod,
) -> tuple[
    IntentExposureMode,
    IntentConstraintNormalization,
    DesiredExposureMagnitudePolicy,
    SelectionTransform,
]:
    if method is ConstructionMethod.EQUAL_WEIGHT_SELECTED:
        return (
            IntentExposureMode.ABSOLUTE_DESIRED_EXPOSURE,
            IntentConstraintNormalization.EQUAL_DESIRED_EXPOSURE,
            DesiredExposureMagnitudePolicy.NOT_PRESERVED,
            SelectionTransform.REWEIGHTED_EQUAL,
        )
    return (
        IntentExposureMode.RELATIVE_DESIRED_EXPOSURE,
        IntentConstraintNormalization.RELATIVE_DESIRED_EXPOSURE,
        DesiredExposureMagnitudePolicy.RELATIVE_INPUTS,
        SelectionTransform.NORMALIZED_TO_BUDGET,
    )


@dataclass(frozen=True, slots=True)
class PortfolioConstructionSpecVersion:
    portfolio_construction_spec_version_id: str
    content_sha256: str
    method: ConstructionMethod
    method_version: str
    exposure_profile: ExposureProfile
    intent_semantic_policy_version: str
    intent_constraint_policy_version: str
    accepted_intent_exposure_mode: IntentExposureMode
    accepted_intent_cash_policy: IntentCashPolicy
    accepted_intent_rebalance_intent: IntentRebalancePolicy
    accepted_intent_constraint_normalization: IntentConstraintNormalization
    desired_exposure_magnitude_policy: DesiredExposureMagnitudePolicy
    selection_transform: SelectionTransform
    required_proposal_only: bool
    required_portfolio_service: bool
    unknown_constraint_policy: str
    cash_policy: str
    target_cash_weight: str
    min_instrument_weight: str
    max_instrument_weight: str
    max_gross_exposure: str
    max_net_exposure: str
    selection_normalization_rule: str
    tie_break_rule: str
    rounding_rule: str
    residual_allocation_rule: str
    absent_member_policy: AbsentMemberPolicy
    decimal_places: int
    tolerance: str
    optimizer_backend: str
    optimizer_version: str
    optimizer_settings: Mapping[str, object]
    diagnostics_policy: str
    runtime_identity: RuntimeIdentity
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = CONSTRUCTION_SPEC_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        method: ConstructionMethod,
        method_version: str,
        target_cash_weight: str,
        min_instrument_weight: str = "0",
        max_instrument_weight: str = "1",
        max_gross_exposure: str = "1",
        max_net_exposure: str = "1",
        runtime_identity: RuntimeIdentity,
        optimizer_settings: Mapping[str, object] | None = None,
    ) -> PortfolioConstructionSpecVersion:
        if not isinstance(method, ConstructionMethod):
            raise TypeError("method must be ConstructionMethod")
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be RuntimeIdentity")
        _require_text(method_version, "method_version")
        (
            accepted_intent_exposure_mode,
            accepted_intent_constraint_normalization,
            desired_exposure_magnitude_policy,
            selection_transform,
        ) = _method_intent_semantics(method)
        accepted_intent_cash_policy = IntentCashPolicy.RESIDUAL
        accepted_intent_rebalance_intent = (
            IntentRebalancePolicy.AT_BOUND_DECISION_TIME
        )
        cash = normalize_weight_decimal(target_cash_weight, "target_cash_weight")
        minimum = normalize_weight_decimal(
            min_instrument_weight, "min_instrument_weight"
        )
        maximum = normalize_weight_decimal(
            max_instrument_weight, "max_instrument_weight"
        )
        gross = normalize_weight_decimal(max_gross_exposure, "max_gross_exposure")
        net = normalize_weight_decimal(max_net_exposure, "max_net_exposure")
        decimal_values = {
            "target_cash_weight": Decimal(cash),
            "min_instrument_weight": Decimal(minimum),
            "max_instrument_weight": Decimal(maximum),
            "max_gross_exposure": Decimal(gross),
            "max_net_exposure": Decimal(net),
        }
        if any(value < 0 for value in decimal_values.values()):
            raise ValueError("construction spec weights and exposure bounds must be non-negative")
        if decimal_values["target_cash_weight"] > 1:
            raise ValueError("target_cash_weight must not exceed one")
        if decimal_values["min_instrument_weight"] > decimal_values["max_instrument_weight"]:
            raise ValueError("min_instrument_weight must not exceed max_instrument_weight")
        normalized_settings = dict(optimizer_settings or {})
        payload = cls._payload(
            method=method,
            method_version=method_version,
            intent_semantic_policy_version="v3.portfolio-intent-admission/1.0.0",
            intent_constraint_policy_version=(
                "v3.portfolio-intent-constraint-policy/1.0.0"
            ),
            accepted_intent_exposure_mode=accepted_intent_exposure_mode,
            accepted_intent_cash_policy=accepted_intent_cash_policy,
            accepted_intent_rebalance_intent=accepted_intent_rebalance_intent,
            accepted_intent_constraint_normalization=(
                accepted_intent_constraint_normalization
            ),
            desired_exposure_magnitude_policy=desired_exposure_magnitude_policy,
            selection_transform=selection_transform,
            target_cash_weight=cash,
            min_instrument_weight=minimum,
            max_instrument_weight=maximum,
            max_gross_exposure=gross,
            max_net_exposure=net,
            optimizer_settings=normalized_settings,
            runtime_identity=runtime_identity,
            truth_admission=PRE_ALPHA_CEILING,
        )
        digest = canonical_sha256(payload)
        return cls(
            portfolio_construction_spec_version_id="pcsv_sha256_" + digest,
            content_sha256=digest,
            method=method,
            method_version=method_version,
            exposure_profile=ExposureProfile.LONG_ONLY_UNLEVERED,
            intent_semantic_policy_version="v3.portfolio-intent-admission/1.0.0",
            intent_constraint_policy_version=(
                "v3.portfolio-intent-constraint-policy/1.0.0"
            ),
            accepted_intent_exposure_mode=accepted_intent_exposure_mode,
            accepted_intent_cash_policy=accepted_intent_cash_policy,
            accepted_intent_rebalance_intent=accepted_intent_rebalance_intent,
            accepted_intent_constraint_normalization=(
                accepted_intent_constraint_normalization
            ),
            desired_exposure_magnitude_policy=desired_exposure_magnitude_policy,
            selection_transform=selection_transform,
            required_proposal_only=True,
            required_portfolio_service=True,
            unknown_constraint_policy="REJECT_UNSUPPORTED_INTENT_CONSTRAINT",
            cash_policy="PINNED_EXPLICIT_CASH_WITH_INVESTED_RESIDUAL",
            target_cash_weight=cash,
            min_instrument_weight=minimum,
            max_instrument_weight=maximum,
            max_gross_exposure=gross,
            max_net_exposure=net,
            selection_normalization_rule=(
                "SELECTED_MEMBERS_EQUAL_WEIGHT"
                if method is ConstructionMethod.EQUAL_WEIGHT_SELECTED
                else "NONNEGATIVE_DESIRED_EXPOSURE_PROPORTIONAL"
            ),
            tie_break_rule="CANONICAL_INSTRUMENT_ID_ASCENDING",
            rounding_rule="DECIMAL_FLOOR_TO_12_PLACES",
            residual_allocation_rule=(
                "LARGEST_REMAINDER_THEN_CANONICAL_INSTRUMENT_ID"
            ),
            absent_member_policy=AbsentMemberPolicy.ZERO,
            decimal_places=WEIGHT_DECIMAL_PLACES,
            tolerance=normalize_weight_decimal(
                str(WEIGHT_BUDGET_TOLERANCE), "tolerance"
            ),
            optimizer_backend="NONE_V3_NATIVE_DECIMAL_BASELINE",
            optimizer_version="NOT_APPLICABLE",
            optimizer_settings=MappingProxyType(normalized_settings),
            diagnostics_policy="IMMUTABLE_TYPED_SUCCESS_OR_TYPED_REJECTION_V1",
            runtime_identity=runtime_identity,
            truth_admission=PRE_ALPHA_CEILING,
        )

    @classmethod
    def _payload(
        cls,
        *,
        method: ConstructionMethod,
        method_version: str,
        intent_semantic_policy_version: str,
        intent_constraint_policy_version: str,
        accepted_intent_exposure_mode: IntentExposureMode,
        accepted_intent_cash_policy: IntentCashPolicy,
        accepted_intent_rebalance_intent: IntentRebalancePolicy,
        accepted_intent_constraint_normalization: IntentConstraintNormalization,
        desired_exposure_magnitude_policy: DesiredExposureMagnitudePolicy,
        selection_transform: SelectionTransform,
        target_cash_weight: str,
        min_instrument_weight: str,
        max_instrument_weight: str,
        max_gross_exposure: str,
        max_net_exposure: str,
        optimizer_settings: Mapping[str, object],
        runtime_identity: RuntimeIdentity,
        truth_admission: TruthAdmissionState,
    ) -> dict[str, object]:
        return {
            "schema_version": cls.schema_version,
            "method": method.value,
            "method_version": method_version,
            "exposure_profile": ExposureProfile.LONG_ONLY_UNLEVERED.value,
            "intent_semantic_policy_version": intent_semantic_policy_version,
            "intent_constraint_policy_version": intent_constraint_policy_version,
            "accepted_intent_exposure_mode": accepted_intent_exposure_mode.value,
            "accepted_intent_cash_policy": accepted_intent_cash_policy.value,
            "accepted_intent_rebalance_intent": accepted_intent_rebalance_intent.value,
            "accepted_intent_constraint_normalization": (
                accepted_intent_constraint_normalization.value
            ),
            "desired_exposure_magnitude_policy": (
                desired_exposure_magnitude_policy.value
            ),
            "selection_transform": selection_transform.value,
            "required_proposal_only": True,
            "required_portfolio_service": True,
            "unknown_constraint_policy": "REJECT_UNSUPPORTED_INTENT_CONSTRAINT",
            "cash_policy": "PINNED_EXPLICIT_CASH_WITH_INVESTED_RESIDUAL",
            "target_cash_weight": target_cash_weight,
            "min_instrument_weight": min_instrument_weight,
            "max_instrument_weight": max_instrument_weight,
            "max_gross_exposure": max_gross_exposure,
            "max_net_exposure": max_net_exposure,
            "selection_normalization_rule": (
                "SELECTED_MEMBERS_EQUAL_WEIGHT"
                if method is ConstructionMethod.EQUAL_WEIGHT_SELECTED
                else "NONNEGATIVE_DESIRED_EXPOSURE_PROPORTIONAL"
            ),
            "tie_break_rule": "CANONICAL_INSTRUMENT_ID_ASCENDING",
            "rounding_rule": "DECIMAL_FLOOR_TO_12_PLACES",
            "residual_allocation_rule": (
                "LARGEST_REMAINDER_THEN_CANONICAL_INSTRUMENT_ID"
            ),
            "absent_member_policy": AbsentMemberPolicy.ZERO.value,
            "decimal_places": WEIGHT_DECIMAL_PLACES,
            "tolerance": normalize_weight_decimal(
                str(WEIGHT_BUDGET_TOLERANCE), "tolerance"
            ),
            "optimizer_backend": "NONE_V3_NATIVE_DECIMAL_BASELINE",
            "optimizer_version": "NOT_APPLICABLE",
            "optimizer_settings": dict(optimizer_settings),
            "diagnostics_policy": "IMMUTABLE_TYPED_SUCCESS_OR_TYPED_REJECTION_V1",
            "runtime_identity": runtime_identity.to_wire(),
            "truth_admission": truth_admission.to_wire(),
        }

    def assert_canonical(self) -> None:
        if not isinstance(self.method, ConstructionMethod):
            raise ValueError("PortfolioConstructionSpecVersion method is not closed")
        (
            expected_exposure_mode,
            expected_constraint_normalization,
            expected_magnitude_policy,
            expected_selection_transform,
        ) = _method_intent_semantics(self.method)
        expected_normalization = (
            "SELECTED_MEMBERS_EQUAL_WEIGHT"
            if self.method is ConstructionMethod.EQUAL_WEIGHT_SELECTED
            else "NONNEGATIVE_DESIRED_EXPOSURE_PROPORTIONAL"
        )
        fixed_fields_match = (
            self.exposure_profile is ExposureProfile.LONG_ONLY_UNLEVERED
            and self.intent_semantic_policy_version
            == "v3.portfolio-intent-admission/1.0.0"
            and self.intent_constraint_policy_version
            == "v3.portfolio-intent-constraint-policy/1.0.0"
            and self.accepted_intent_exposure_mode is expected_exposure_mode
            and self.accepted_intent_cash_policy is IntentCashPolicy.RESIDUAL
            and self.accepted_intent_rebalance_intent
            is IntentRebalancePolicy.AT_BOUND_DECISION_TIME
            and self.accepted_intent_constraint_normalization
            is expected_constraint_normalization
            and self.desired_exposure_magnitude_policy is expected_magnitude_policy
            and self.selection_transform is expected_selection_transform
            and self.required_proposal_only is True
            and self.required_portfolio_service is True
            and self.unknown_constraint_policy
            == "REJECT_UNSUPPORTED_INTENT_CONSTRAINT"
            and self.cash_policy == "PINNED_EXPLICIT_CASH_WITH_INVESTED_RESIDUAL"
            and self.selection_normalization_rule == expected_normalization
            and self.tie_break_rule == "CANONICAL_INSTRUMENT_ID_ASCENDING"
            and self.rounding_rule == "DECIMAL_FLOOR_TO_12_PLACES"
            and self.residual_allocation_rule
            == "LARGEST_REMAINDER_THEN_CANONICAL_INSTRUMENT_ID"
            and self.absent_member_policy is AbsentMemberPolicy.ZERO
            and self.decimal_places == WEIGHT_DECIMAL_PLACES
            and self.tolerance
            == normalize_weight_decimal(str(WEIGHT_BUDGET_TOLERANCE), "tolerance")
            and self.optimizer_backend == "NONE_V3_NATIVE_DECIMAL_BASELINE"
            and self.optimizer_version == "NOT_APPLICABLE"
            and self.diagnostics_policy
            == "IMMUTABLE_TYPED_SUCCESS_OR_TYPED_REJECTION_V1"
            and self.truth_admission == PRE_ALPHA_CEILING
        )
        if not fixed_fields_match:
            raise ValueError("PortfolioConstructionSpecVersion fixed V0 policy mismatch")
        payload = self._payload(
            method=self.method,
            method_version=self.method_version,
            intent_semantic_policy_version=self.intent_semantic_policy_version,
            intent_constraint_policy_version=self.intent_constraint_policy_version,
            accepted_intent_exposure_mode=self.accepted_intent_exposure_mode,
            accepted_intent_cash_policy=self.accepted_intent_cash_policy,
            accepted_intent_rebalance_intent=self.accepted_intent_rebalance_intent,
            accepted_intent_constraint_normalization=(
                self.accepted_intent_constraint_normalization
            ),
            desired_exposure_magnitude_policy=(
                self.desired_exposure_magnitude_policy
            ),
            selection_transform=self.selection_transform,
            target_cash_weight=self.target_cash_weight,
            min_instrument_weight=self.min_instrument_weight,
            max_instrument_weight=self.max_instrument_weight,
            max_gross_exposure=self.max_gross_exposure,
            max_net_exposure=self.max_net_exposure,
            optimizer_settings=self.optimizer_settings,
            runtime_identity=self.runtime_identity,
            truth_admission=self.truth_admission,
        )
        digest = canonical_sha256(payload)
        if self.content_sha256 != digest:
            raise ValueError("PortfolioConstructionSpecVersion content hash mismatch")
        if self.portfolio_construction_spec_version_id != "pcsv_sha256_" + digest:
            raise ValueError("PortfolioConstructionSpecVersion identity mismatch")

    def to_wire(self) -> dict[str, object]:
        self.assert_canonical()
        return {
            "portfolio_construction_spec_version_id": self.portfolio_construction_spec_version_id,
            "content_sha256": self.content_sha256,
            **self._payload(
                method=self.method,
                method_version=self.method_version,
                intent_semantic_policy_version=self.intent_semantic_policy_version,
                intent_constraint_policy_version=self.intent_constraint_policy_version,
                accepted_intent_exposure_mode=self.accepted_intent_exposure_mode,
                accepted_intent_cash_policy=self.accepted_intent_cash_policy,
                accepted_intent_rebalance_intent=(
                    self.accepted_intent_rebalance_intent
                ),
                accepted_intent_constraint_normalization=(
                    self.accepted_intent_constraint_normalization
                ),
                desired_exposure_magnitude_policy=(
                    self.desired_exposure_magnitude_policy
                ),
                selection_transform=self.selection_transform,
                target_cash_weight=self.target_cash_weight,
                min_instrument_weight=self.min_instrument_weight,
                max_instrument_weight=self.max_instrument_weight,
                max_gross_exposure=self.max_gross_exposure,
                max_net_exposure=self.max_net_exposure,
                optimizer_settings=self.optimizer_settings,
                runtime_identity=self.runtime_identity,
                truth_admission=self.truth_admission,
            ),
        }

    def to_reference(self) -> UnresolvedExactReference:
        self.assert_canonical()
        return UnresolvedExactReference(
            ReferenceKind.CONSTRUCTION_SPEC,
            self.portfolio_construction_spec_version_id,
            self.content_sha256,
            self.truth_admission,
        )


@dataclass(frozen=True, slots=True)
class OptimizerCandidate:
    optimizer_candidate_id: str
    content_sha256: str
    backend: str
    backend_version: str
    objective: str
    constraints_sha256: str
    tolerance: str
    status: str
    seed: str | None
    rows: tuple[TargetWeightRow, ...]

    schema_version: ClassVar[str] = OPTIMIZER_CANDIDATE_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        backend: str,
        backend_version: str,
        objective: str,
        constraints_sha256: str,
        tolerance: str,
        status: str,
        seed: str | None,
        rows: tuple[TargetWeightRow, ...],
    ) -> OptimizerCandidate:
        for name, value in (
            ("backend", backend),
            ("backend_version", backend_version),
            ("objective", objective),
            ("constraints_sha256", constraints_sha256),
            ("status", status),
        ):
            _require_text(value, name)
        if _SHA256.fullmatch(constraints_sha256) is None:
            raise ValueError("constraints_sha256 must be a lowercase full SHA-256")
        canonical_tolerance = normalize_weight_decimal(tolerance, "tolerance")
        ordered_rows = tuple(sorted(rows, key=lambda value: value.instrument_id))
        payload = {
            "schema_version": cls.schema_version,
            "backend": backend,
            "backend_version": backend_version,
            "objective": objective,
            "constraints_sha256": constraints_sha256,
            "tolerance": canonical_tolerance,
            "status": status,
            "seed": seed,
            "rows": [value.to_wire() for value in ordered_rows],
        }
        digest = canonical_sha256(payload)
        return cls(
            optimizer_candidate_id="opc_sha256_" + digest,
            content_sha256=digest,
            backend=backend,
            backend_version=backend_version,
            objective=objective,
            constraints_sha256=constraints_sha256,
            tolerance=canonical_tolerance,
            status=status,
            seed=seed,
            rows=ordered_rows,
        )

    def to_wire(self) -> dict[str, object]:
        payload = {
            "schema_version": self.schema_version,
            "backend": self.backend,
            "backend_version": self.backend_version,
            "objective": self.objective,
            "constraints_sha256": self.constraints_sha256,
            "tolerance": self.tolerance,
            "status": self.status,
            "seed": self.seed,
            "rows": [value.to_wire() for value in self.rows],
        }
        digest = canonical_sha256(payload)
        if self.content_sha256 != digest or self.optimizer_candidate_id != "opc_sha256_" + digest:
            raise ValueError("OptimizerCandidate identity/content mismatch")
        return {
            "optimizer_candidate_id": self.optimizer_candidate_id,
            "content_sha256": self.content_sha256,
            **payload,
        }


@dataclass(frozen=True, slots=True)
class ConstraintCheck:
    name: str
    status: ConstraintCheckStatus
    observed: str
    limit: str

    def __post_init__(self) -> None:
        _require_text(self.name, "constraint check name")
        if not isinstance(self.status, ConstraintCheckStatus):
            raise TypeError("status must be ConstraintCheckStatus")
        _require_text(self.observed, "constraint observed")
        _require_text(self.limit, "constraint limit")

    def to_wire(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status.value,
            "observed": self.observed,
            "limit": self.limit,
        }


@dataclass(frozen=True, slots=True)
class PortfolioConstructionDiagnostics:
    diagnostics_id: str
    content_sha256: str
    selected_count: int
    excluded_count: int
    cash_weight: str
    gross_exposure: str
    net_exposure: str
    normalization_input_total: str
    rounding_residual_allocated: str
    portfolio_intent_id: str
    strategy_evaluation_binding_version_id: str
    source_reference_sha256: str
    method: ConstructionMethod
    intent_semantic_admission_status: IntentSemanticAdmissionStatus
    intent_exposure_mode: IntentExposureMode
    intent_cash_policy: IntentCashPolicy
    intent_rebalance_intent: IntentRebalancePolicy
    intent_constraint_normalization: IntentConstraintNormalization
    desired_exposure_magnitude_policy: DesiredExposureMagnitudePolicy
    selection_transform: SelectionTransform
    as_of: str
    decision_time: str
    rebalance_time: str
    valid_until: str
    binding_period_start: str
    binding_period_end: str
    binding_knowledge_cutoff: str
    timing_validation_status: TimingValidationStatus
    constraint_checks: tuple[ConstraintCheck, ...]
    infeasibility_reason: None
    optimizer_evidence: None
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = CONSTRUCTION_DIAGNOSTICS_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        selected_count: int,
        excluded_count: int,
        cash_weight: Decimal,
        gross_exposure: Decimal,
        net_exposure: Decimal,
        normalization_input_total: Decimal,
        rounding_residual_allocated: Decimal,
        portfolio_intent_id: str,
        strategy_evaluation_binding_version_id: str,
        source_reference_sha256: str,
        method: ConstructionMethod,
        intent_exposure_mode: IntentExposureMode,
        intent_cash_policy: IntentCashPolicy,
        intent_rebalance_intent: IntentRebalancePolicy,
        intent_constraint_normalization: IntentConstraintNormalization,
        desired_exposure_magnitude_policy: DesiredExposureMagnitudePolicy,
        selection_transform: SelectionTransform,
        as_of: datetime,
        decision_time: datetime,
        rebalance_time: datetime,
        valid_until: datetime,
        binding_period_start: datetime,
        binding_period_end: datetime,
        binding_knowledge_cutoff: datetime,
        constraint_checks: tuple[ConstraintCheck, ...],
    ) -> PortfolioConstructionDiagnostics:
        if selected_count < 0 or excluded_count < 0:
            raise ValueError("diagnostic counts must be non-negative")
        payload = {
            "schema_version": cls.schema_version,
            "selected_count": selected_count,
            "excluded_count": excluded_count,
            "cash_weight": _wire_decimal(cash_weight),
            "gross_exposure": _wire_decimal(gross_exposure),
            "net_exposure": _wire_decimal(net_exposure),
            "normalization_input_total": _wire_decimal(normalization_input_total),
            "rounding_residual_allocated": _wire_decimal(rounding_residual_allocated),
            "portfolio_intent_id": portfolio_intent_id,
            "strategy_evaluation_binding_version_id": strategy_evaluation_binding_version_id,
            "source_reference_sha256": source_reference_sha256,
            "method": method.value,
            "intent_semantic_admission_status": (
                IntentSemanticAdmissionStatus.PASSED.value
            ),
            "intent_exposure_mode": intent_exposure_mode.value,
            "intent_cash_policy": intent_cash_policy.value,
            "intent_rebalance_intent": intent_rebalance_intent.value,
            "intent_constraint_normalization": intent_constraint_normalization.value,
            "desired_exposure_magnitude_policy": (
                desired_exposure_magnitude_policy.value
            ),
            "selection_transform": selection_transform.value,
            "as_of": _wire_time(as_of),
            "decision_time": _wire_time(decision_time),
            "rebalance_time": _wire_time(rebalance_time),
            "valid_until": _wire_time(valid_until),
            "binding_period_start": _wire_time(binding_period_start),
            "binding_period_end": _wire_time(binding_period_end),
            "binding_knowledge_cutoff": _wire_time(binding_knowledge_cutoff),
            "timing_validation_status": TimingValidationStatus.PASSED.value,
            "constraint_checks": [value.to_wire() for value in constraint_checks],
            "infeasibility_reason": None,
            "optimizer_evidence": None,
            "truth_admission": PRE_ALPHA_CEILING.to_wire(),
        }
        digest = canonical_sha256(payload)
        return cls(
            diagnostics_id="pcdiag_sha256_" + digest,
            content_sha256=digest,
            selected_count=selected_count,
            excluded_count=excluded_count,
            cash_weight=_wire_decimal(cash_weight),
            gross_exposure=_wire_decimal(gross_exposure),
            net_exposure=_wire_decimal(net_exposure),
            normalization_input_total=_wire_decimal(normalization_input_total),
            rounding_residual_allocated=_wire_decimal(rounding_residual_allocated),
            portfolio_intent_id=portfolio_intent_id,
            strategy_evaluation_binding_version_id=strategy_evaluation_binding_version_id,
            source_reference_sha256=source_reference_sha256,
            method=method,
            intent_semantic_admission_status=IntentSemanticAdmissionStatus.PASSED,
            intent_exposure_mode=intent_exposure_mode,
            intent_cash_policy=intent_cash_policy,
            intent_rebalance_intent=intent_rebalance_intent,
            intent_constraint_normalization=intent_constraint_normalization,
            desired_exposure_magnitude_policy=desired_exposure_magnitude_policy,
            selection_transform=selection_transform,
            as_of=_wire_time(as_of),
            decision_time=_wire_time(decision_time),
            rebalance_time=_wire_time(rebalance_time),
            valid_until=_wire_time(valid_until),
            binding_period_start=_wire_time(binding_period_start),
            binding_period_end=_wire_time(binding_period_end),
            binding_knowledge_cutoff=_wire_time(binding_knowledge_cutoff),
            timing_validation_status=TimingValidationStatus.PASSED,
            constraint_checks=constraint_checks,
            infeasibility_reason=None,
            optimizer_evidence=None,
            truth_admission=PRE_ALPHA_CEILING,
        )

    def to_wire(self) -> dict[str, object]:
        payload = {
            "schema_version": self.schema_version,
            "selected_count": self.selected_count,
            "excluded_count": self.excluded_count,
            "cash_weight": self.cash_weight,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "normalization_input_total": self.normalization_input_total,
            "rounding_residual_allocated": self.rounding_residual_allocated,
            "portfolio_intent_id": self.portfolio_intent_id,
            "strategy_evaluation_binding_version_id": self.strategy_evaluation_binding_version_id,
            "source_reference_sha256": self.source_reference_sha256,
            "method": self.method.value,
            "intent_semantic_admission_status": (
                self.intent_semantic_admission_status.value
            ),
            "intent_exposure_mode": self.intent_exposure_mode.value,
            "intent_cash_policy": self.intent_cash_policy.value,
            "intent_rebalance_intent": self.intent_rebalance_intent.value,
            "intent_constraint_normalization": (
                self.intent_constraint_normalization.value
            ),
            "desired_exposure_magnitude_policy": (
                self.desired_exposure_magnitude_policy.value
            ),
            "selection_transform": self.selection_transform.value,
            "as_of": self.as_of,
            "decision_time": self.decision_time,
            "rebalance_time": self.rebalance_time,
            "valid_until": self.valid_until,
            "binding_period_start": self.binding_period_start,
            "binding_period_end": self.binding_period_end,
            "binding_knowledge_cutoff": self.binding_knowledge_cutoff,
            "timing_validation_status": self.timing_validation_status.value,
            "constraint_checks": [value.to_wire() for value in self.constraint_checks],
            "infeasibility_reason": self.infeasibility_reason,
            "optimizer_evidence": self.optimizer_evidence,
            "truth_admission": self.truth_admission.to_wire(),
        }
        digest = canonical_sha256(payload)
        if self.content_sha256 != digest or self.diagnostics_id != "pcdiag_sha256_" + digest:
            raise ValueError("PortfolioConstructionDiagnostics identity/content mismatch")
        return {
            "diagnostics_id": self.diagnostics_id,
            "content_sha256": self.content_sha256,
            **payload,
        }

    def to_reference(self) -> UnresolvedExactReference:
        self.to_wire()
        return UnresolvedExactReference(
            ReferenceKind.DIAGNOSTICS,
            self.diagnostics_id,
            self.content_sha256,
            self.truth_admission,
        )


@dataclass(frozen=True, slots=True)
class PortfolioConstructionProvenance:
    provenance_id: str
    content_sha256: str
    source_reference_sha256: str
    construction_spec_version_id: str
    diagnostics_id: str
    candidate_rows_sha256: str
    cash_weight: str
    as_of: str
    decision_time: str
    rebalance_time: str
    valid_until: str
    binding_period_start: str
    binding_period_end: str
    binding_knowledge_cutoff: str
    rebalance_intent: IntentRebalancePolicy
    timing_validation_status: TimingValidationStatus
    optimizer_candidate_sha256: None
    runtime_identity: RuntimeIdentity
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = CONSTRUCTION_PROVENANCE_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        source_reference_sha256: str,
        construction_spec_version_id: str,
        diagnostics_id: str,
        rows: tuple[TargetWeightRow, ...],
        cash_weight: str,
        as_of: datetime,
        decision_time: datetime,
        rebalance_time: datetime,
        valid_until: datetime,
        binding_period_start: datetime,
        binding_period_end: datetime,
        binding_knowledge_cutoff: datetime,
        rebalance_intent: IntentRebalancePolicy,
        runtime_identity: RuntimeIdentity,
    ) -> PortfolioConstructionProvenance:
        canonical_cash = normalize_weight_decimal(cash_weight, "cash_weight")
        rows_sha256 = canonical_sha256([value.to_wire() for value in rows])
        payload = {
            "schema_version": cls.schema_version,
            "source_reference_sha256": source_reference_sha256,
            "construction_spec_version_id": construction_spec_version_id,
            "diagnostics_id": diagnostics_id,
            "candidate_rows_sha256": rows_sha256,
            "cash_weight": canonical_cash,
            "as_of": _wire_time(as_of),
            "decision_time": _wire_time(decision_time),
            "rebalance_time": _wire_time(rebalance_time),
            "valid_until": _wire_time(valid_until),
            "binding_period_start": _wire_time(binding_period_start),
            "binding_period_end": _wire_time(binding_period_end),
            "binding_knowledge_cutoff": _wire_time(binding_knowledge_cutoff),
            "rebalance_intent": rebalance_intent.value,
            "timing_validation_status": TimingValidationStatus.PASSED.value,
            "optimizer_candidate_sha256": None,
            "runtime_identity": runtime_identity.to_wire(),
            "truth_admission": PRE_ALPHA_CEILING.to_wire(),
        }
        digest = canonical_sha256(payload)
        return cls(
            provenance_id="pcprov_sha256_" + digest,
            content_sha256=digest,
            source_reference_sha256=source_reference_sha256,
            construction_spec_version_id=construction_spec_version_id,
            diagnostics_id=diagnostics_id,
            candidate_rows_sha256=rows_sha256,
            cash_weight=canonical_cash,
            as_of=_wire_time(as_of),
            decision_time=_wire_time(decision_time),
            rebalance_time=_wire_time(rebalance_time),
            valid_until=_wire_time(valid_until),
            binding_period_start=_wire_time(binding_period_start),
            binding_period_end=_wire_time(binding_period_end),
            binding_knowledge_cutoff=_wire_time(binding_knowledge_cutoff),
            rebalance_intent=rebalance_intent,
            timing_validation_status=TimingValidationStatus.PASSED,
            optimizer_candidate_sha256=None,
            runtime_identity=runtime_identity,
            truth_admission=PRE_ALPHA_CEILING,
        )

    def to_wire(self) -> dict[str, object]:
        payload = {
            "schema_version": self.schema_version,
            "source_reference_sha256": self.source_reference_sha256,
            "construction_spec_version_id": self.construction_spec_version_id,
            "diagnostics_id": self.diagnostics_id,
            "candidate_rows_sha256": self.candidate_rows_sha256,
            "cash_weight": self.cash_weight,
            "as_of": self.as_of,
            "decision_time": self.decision_time,
            "rebalance_time": self.rebalance_time,
            "valid_until": self.valid_until,
            "binding_period_start": self.binding_period_start,
            "binding_period_end": self.binding_period_end,
            "binding_knowledge_cutoff": self.binding_knowledge_cutoff,
            "rebalance_intent": self.rebalance_intent.value,
            "timing_validation_status": self.timing_validation_status.value,
            "optimizer_candidate_sha256": self.optimizer_candidate_sha256,
            "runtime_identity": self.runtime_identity.to_wire(),
            "truth_admission": self.truth_admission.to_wire(),
        }
        digest = canonical_sha256(payload)
        if self.content_sha256 != digest or self.provenance_id != "pcprov_sha256_" + digest:
            raise ValueError("PortfolioConstructionProvenance identity/content mismatch")
        return {
            "provenance_id": self.provenance_id,
            "content_sha256": self.content_sha256,
            **payload,
        }

    def to_reference(self) -> UnresolvedExactReference:
        self.to_wire()
        return UnresolvedExactReference(
            ReferenceKind.PROVENANCE,
            self.provenance_id,
            self.content_sha256,
            self.truth_admission,
        )


@dataclass(frozen=True, slots=True)
class PortfolioConstructionResult:
    target: TargetWeightVector
    diagnostics: PortfolioConstructionDiagnostics
    provenance: PortfolioConstructionProvenance


__all__ = [
    "ConstructionMethod",
    "ConstructionRejectionReason",
    "ConstraintCheck",
    "ConstraintCheckStatus",
    "DesiredExposureMagnitudePolicy",
    "IntentCashPolicy",
    "IntentConstraintNormalization",
    "IntentExposureMode",
    "IntentRebalancePolicy",
    "IntentSemanticAdmissionStatus",
    "OptimizerCandidate",
    "PortfolioConstructionDiagnostics",
    "PortfolioConstructionProvenance",
    "PortfolioConstructionRejected",
    "PortfolioConstructionResult",
    "PortfolioConstructionSpecVersion",
    "SelectionTransform",
    "TimingValidationStatus",
]
