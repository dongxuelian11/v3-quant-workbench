from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar

from v3_backend.contracts.common.truth_admission import (
    PRE_ALPHA_CEILING,
    TruthAdmissionState,
    meet_pair,
)
from v3_backend.domain.weights import (
    ReferenceKind,
    RiskAdjustedWeightRow,
    RuntimeIdentity,
    TargetWeightRow,
    TargetWeightVector,
    UnresolvedExactReference,
    normalize_weight_decimal,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


RISK_POLICY_SCHEMA_VERSION = "v3.risk-policy-definition/1.0.0"
RISK_POLICY_SET_SCHEMA_VERSION = "v3.risk-policy-set-version/1.0.0"
RISK_STAGE_REPORT_SCHEMA_VERSION = "v3.risk-stage-report/1.0.0"
RISK_DECISION_REPORT_SCHEMA_VERSION = "v3.risk-decision-report/1.0.0"


class RiskRuntimeError(ValueError):
    """Base error for deterministic Risk V0 contract violations."""


class ExternalSolverAuthorityError(RiskRuntimeError):
    """Raised when an external candidate attempts to publish canonical output."""


class PolicyMode(StrEnum):
    VALIDATE = "VALIDATE"
    CLIP = "CLIP"
    SCALE = "SCALE"
    PROJECT = "PROJECT"
    FREEZE = "FREEZE"
    REPLACE = "REPLACE"
    PASS_THROUGH = "PASS_THROUGH"


class PolicyType(StrEnum):
    PASS_THROUGH = "PASS_THROUGH"
    MAX_SINGLE_NAME = "MAX_SINGLE_NAME"
    GROSS_NET_EXPOSURE_VALIDATE = "GROSS_NET_EXPOSURE_VALIDATE"


class FailureBehavior(StrEnum):
    REJECT = "REJECT"


class ResidualCashRule(StrEnum):
    PRESERVE = "PRESERVE"
    ADD_REDUCTION_TO_CASH = "ADD_REDUCTION_TO_CASH"


class RiskModelRequirement(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"


class PitRequirement(StrEnum):
    TARGET_ONLY = "TARGET_ONLY"
    AS_OF_NOT_AFTER_TARGET_DECISION = "AS_OF_NOT_AFTER_TARGET_DECISION"


class StageStatus(StrEnum):
    PASSED = "PASSED"
    ADJUSTED = "ADJUSTED"
    REJECTED = "REJECTED"


class DecisionStatus(StrEnum):
    PASS_THROUGH = "PASS_THROUGH"
    ADJUSTED = "ADJUSTED"
    REJECTED = "REJECTED"


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RiskRuntimeError(f"{name} must be non-empty without edge whitespace")


def _wire_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decimal(value: str) -> Decimal:
    return Decimal(value)


def _canonical_parameters(
    parameters: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    for key, value in parameters:
        _require_text(key, "policy parameter name")
        normalized.append((key, normalize_weight_decimal(value, key)))
    ordered = tuple(sorted(normalized))
    if len({key for key, _ in ordered}) != len(ordered):
        raise RiskRuntimeError("policy parameter names must be unique")
    return ordered


@dataclass(frozen=True, slots=True)
class RiskStateRequirement:
    input_key: str
    reference_kind: ReferenceKind
    pit_requirement: PitRequirement = PitRequirement.AS_OF_NOT_AFTER_TARGET_DECISION

    def __post_init__(self) -> None:
        _require_text(self.input_key, "risk state input_key")
        if self.reference_kind not in {ReferenceKind.RISK_STATE, ReferenceKind.RISK_MODEL}:
            raise RiskRuntimeError("risk state requirements allow only RISK_STATE or RISK_MODEL")
        if not isinstance(self.pit_requirement, PitRequirement):
            raise TypeError("pit_requirement must be PitRequirement")

    def to_wire(self) -> dict[str, str]:
        return {
            "input_key": self.input_key,
            "reference_kind": self.reference_kind.value,
            "pit_requirement": self.pit_requirement.value,
        }


@dataclass(frozen=True, slots=True)
class RiskStateInput:
    input_key: str
    reference: UnresolvedExactReference
    as_of: datetime

    def __post_init__(self) -> None:
        _require_text(self.input_key, "risk state input_key")
        if not isinstance(self.reference, UnresolvedExactReference):
            raise TypeError("risk state reference must be UnresolvedExactReference")
        if self.reference.reference_kind not in {
            ReferenceKind.RISK_STATE,
            ReferenceKind.RISK_MODEL,
        }:
            raise RiskRuntimeError("risk state inputs allow only RISK_STATE or RISK_MODEL refs")
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise RiskRuntimeError("risk state as_of must be timezone-aware")

    def to_wire(self) -> dict[str, object]:
        return {
            "input_key": self.input_key,
            "reference": self.reference.to_wire(),
            "as_of": _wire_time(self.as_of),
        }


@dataclass(frozen=True, slots=True)
class RiskPolicyDefinition:
    policy_id: str
    content_sha256: str
    policy_type: PolicyType
    policy_version: str
    mode: PolicyMode
    parameters: tuple[tuple[str, str], ...]
    required_state_inputs: tuple[RiskStateRequirement, ...]
    failure_behavior: FailureBehavior
    residual_cash_rule: ResidualCashRule
    risk_model_requirement: RiskModelRequirement
    code_version: str
    runtime_profile_id: str
    backend: str
    truth_requirement: str
    pit_requirement: PitRequirement
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = RISK_POLICY_SCHEMA_VERSION

    @classmethod
    def pass_through(
        cls,
        *,
        code_version: str,
        runtime_profile_id: str,
        backend: str = "v3-native-decimal",
        policy_version: str = "1.0.0",
        truth_admission: TruthAdmissionState = PRE_ALPHA_CEILING,
    ) -> RiskPolicyDefinition:
        return cls._create(
            policy_type=PolicyType.PASS_THROUGH,
            policy_version=policy_version,
            mode=PolicyMode.PASS_THROUGH,
            parameters=(),
            required_state_inputs=(),
            residual_cash_rule=ResidualCashRule.PRESERVE,
            risk_model_requirement=RiskModelRequirement.NOT_REQUIRED,
            code_version=code_version,
            runtime_profile_id=runtime_profile_id,
            backend=backend,
            truth_requirement="PRESERVE_UPSTREAM_TRUTH_CEILING",
            pit_requirement=PitRequirement.TARGET_ONLY,
            truth_admission=truth_admission,
        )

    @classmethod
    def max_single_name(
        cls,
        *,
        max_weight: str,
        code_version: str,
        runtime_profile_id: str,
        backend: str = "v3-native-decimal",
        policy_version: str = "1.0.0",
        required_state_inputs: tuple[RiskStateRequirement, ...] = (),
        truth_admission: TruthAdmissionState = PRE_ALPHA_CEILING,
    ) -> RiskPolicyDefinition:
        return cls._create(
            policy_type=PolicyType.MAX_SINGLE_NAME,
            policy_version=policy_version,
            mode=PolicyMode.CLIP,
            parameters=(("max_weight", max_weight),),
            required_state_inputs=required_state_inputs,
            residual_cash_rule=ResidualCashRule.ADD_REDUCTION_TO_CASH,
            risk_model_requirement=RiskModelRequirement.NOT_REQUIRED,
            code_version=code_version,
            runtime_profile_id=runtime_profile_id,
            backend=backend,
            truth_requirement="PRESERVE_UPSTREAM_TRUTH_CEILING",
            pit_requirement=PitRequirement.AS_OF_NOT_AFTER_TARGET_DECISION,
            truth_admission=truth_admission,
        )

    @classmethod
    def gross_net_exposure_validate(
        cls,
        *,
        max_gross: str,
        min_net: str,
        max_net: str,
        code_version: str,
        runtime_profile_id: str,
        backend: str = "v3-native-decimal",
        policy_version: str = "1.0.0",
        required_state_inputs: tuple[RiskStateRequirement, ...] = (),
        truth_admission: TruthAdmissionState = PRE_ALPHA_CEILING,
    ) -> RiskPolicyDefinition:
        return cls._create(
            policy_type=PolicyType.GROSS_NET_EXPOSURE_VALIDATE,
            policy_version=policy_version,
            mode=PolicyMode.VALIDATE,
            parameters=(
                ("max_gross", max_gross),
                ("min_net", min_net),
                ("max_net", max_net),
            ),
            required_state_inputs=required_state_inputs,
            residual_cash_rule=ResidualCashRule.PRESERVE,
            risk_model_requirement=RiskModelRequirement.NOT_REQUIRED,
            code_version=code_version,
            runtime_profile_id=runtime_profile_id,
            backend=backend,
            truth_requirement="PRESERVE_UPSTREAM_TRUTH_CEILING",
            pit_requirement=PitRequirement.AS_OF_NOT_AFTER_TARGET_DECISION,
            truth_admission=truth_admission,
        )

    @classmethod
    def _create(
        cls,
        *,
        policy_type: PolicyType,
        policy_version: str,
        mode: PolicyMode,
        parameters: tuple[tuple[str, str], ...],
        required_state_inputs: tuple[RiskStateRequirement, ...],
        residual_cash_rule: ResidualCashRule,
        risk_model_requirement: RiskModelRequirement,
        code_version: str,
        runtime_profile_id: str,
        backend: str,
        truth_requirement: str,
        pit_requirement: PitRequirement,
        truth_admission: TruthAdmissionState,
    ) -> RiskPolicyDefinition:
        if not isinstance(policy_type, PolicyType) or not isinstance(mode, PolicyMode):
            raise TypeError("policy_type/mode must use Risk V0 enums")
        for name, value in (
            ("policy_version", policy_version),
            ("code_version", code_version),
            ("runtime_profile_id", runtime_profile_id),
            ("backend", backend),
            ("truth_requirement", truth_requirement),
        ):
            _require_text(value, name)
        if not isinstance(residual_cash_rule, ResidualCashRule):
            raise TypeError("residual_cash_rule must be ResidualCashRule")
        if not isinstance(risk_model_requirement, RiskModelRequirement):
            raise TypeError("risk_model_requirement must be RiskModelRequirement")
        if not isinstance(pit_requirement, PitRequirement):
            raise TypeError("pit_requirement must be PitRequirement")
        if not isinstance(truth_admission, TruthAdmissionState):
            raise TypeError("truth_admission must be TruthAdmissionState")
        ordered_requirements = tuple(sorted(required_state_inputs, key=lambda value: value.input_key))
        if any(not isinstance(value, RiskStateRequirement) for value in ordered_requirements):
            raise TypeError("required_state_inputs must contain RiskStateRequirement")
        if len({value.input_key for value in ordered_requirements}) != len(ordered_requirements):
            raise RiskRuntimeError("required risk state input keys must be unique")
        canonical_parameters = _canonical_parameters(parameters)
        cls._validate_algebra(
            policy_type,
            mode,
            canonical_parameters,
            residual_cash_rule,
            risk_model_requirement,
        )
        bounded_truth = meet_pair(truth_admission, PRE_ALPHA_CEILING)
        payload = cls._payload(
            policy_type=policy_type,
            policy_version=policy_version,
            mode=mode,
            parameters=canonical_parameters,
            required_state_inputs=ordered_requirements,
            failure_behavior=FailureBehavior.REJECT,
            residual_cash_rule=residual_cash_rule,
            risk_model_requirement=risk_model_requirement,
            code_version=code_version,
            runtime_profile_id=runtime_profile_id,
            backend=backend,
            truth_requirement=truth_requirement,
            pit_requirement=pit_requirement,
            truth_admission=bounded_truth,
        )
        digest = canonical_sha256(payload)
        return cls(
            policy_id="rpd_sha256_" + digest,
            content_sha256=digest,
            policy_type=policy_type,
            policy_version=policy_version,
            mode=mode,
            parameters=canonical_parameters,
            required_state_inputs=ordered_requirements,
            failure_behavior=FailureBehavior.REJECT,
            residual_cash_rule=residual_cash_rule,
            risk_model_requirement=risk_model_requirement,
            code_version=code_version,
            runtime_profile_id=runtime_profile_id,
            backend=backend,
            truth_requirement=truth_requirement,
            pit_requirement=pit_requirement,
            truth_admission=bounded_truth,
        )

    @staticmethod
    def _validate_algebra(
        policy_type: PolicyType,
        mode: PolicyMode,
        parameters: tuple[tuple[str, str], ...],
        residual_cash_rule: ResidualCashRule,
        risk_model_requirement: RiskModelRequirement,
    ) -> None:
        values = dict(parameters)
        if policy_type is PolicyType.PASS_THROUGH:
            if mode is not PolicyMode.PASS_THROUGH or parameters:
                raise RiskRuntimeError("PASS_THROUGH has no parameters and requires PASS_THROUGH mode")
            if residual_cash_rule is not ResidualCashRule.PRESERVE:
                raise RiskRuntimeError("PASS_THROUGH must preserve cash")
        elif policy_type is PolicyType.MAX_SINGLE_NAME:
            if mode is not PolicyMode.CLIP or set(values) != {"max_weight"}:
                raise RiskRuntimeError("MAX_SINGLE_NAME requires CLIP and exact max_weight")
            if not Decimal(0) < _decimal(values["max_weight"]) <= Decimal(1):
                raise RiskRuntimeError("max_weight must be in (0, 1]")
            if residual_cash_rule is not ResidualCashRule.ADD_REDUCTION_TO_CASH:
                raise RiskRuntimeError("MAX_SINGLE_NAME requires ADD_REDUCTION_TO_CASH")
        elif policy_type is PolicyType.GROSS_NET_EXPOSURE_VALIDATE:
            if mode is not PolicyMode.VALIDATE or set(values) != {
                "max_gross",
                "min_net",
                "max_net",
            }:
                raise RiskRuntimeError(
                    "GROSS_NET_EXPOSURE_VALIDATE requires exact gross/net limits"
                )
            max_gross = _decimal(values["max_gross"])
            min_net = _decimal(values["min_net"])
            max_net = _decimal(values["max_net"])
            if not Decimal(0) <= min_net <= max_net <= Decimal(1):
                raise RiskRuntimeError("net limits must satisfy 0 <= min_net <= max_net <= 1")
            if not Decimal(0) <= max_gross <= Decimal(1):
                raise RiskRuntimeError("max_gross must be in [0, 1]")
            if residual_cash_rule is not ResidualCashRule.PRESERVE:
                raise RiskRuntimeError("GROSS_NET_EXPOSURE_VALIDATE must preserve cash")
        if risk_model_requirement is RiskModelRequirement.REQUIRED:
            raise RiskRuntimeError("Risk V0 built-in policies do not admit a RiskModel")

    @classmethod
    def _payload(
        cls,
        **values: object,
    ) -> dict[str, object]:
        required = values["required_state_inputs"]
        truth = values["truth_admission"]
        assert isinstance(required, tuple)
        assert isinstance(truth, TruthAdmissionState)
        return {
            "schema_version": cls.schema_version,
            "policy_type": values["policy_type"].value,
            "policy_version": values["policy_version"],
            "mode": values["mode"].value,
            "parameters": [list(value) for value in values["parameters"]],
            "required_state_inputs": [value.to_wire() for value in required],
            "failure_behavior": values["failure_behavior"].value,
            "residual_cash_rule": values["residual_cash_rule"].value,
            "risk_model_requirement": values["risk_model_requirement"].value,
            "code_version": values["code_version"],
            "runtime_profile_id": values["runtime_profile_id"],
            "backend": values["backend"],
            "truth_requirement": values["truth_requirement"],
            "pit_requirement": values["pit_requirement"].value,
            "truth_admission": truth.to_wire(),
        }

    def to_wire(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "content_sha256": self.content_sha256,
            **self._payload(
                policy_type=self.policy_type,
                policy_version=self.policy_version,
                mode=self.mode,
                parameters=self.parameters,
                required_state_inputs=self.required_state_inputs,
                failure_behavior=self.failure_behavior,
                residual_cash_rule=self.residual_cash_rule,
                risk_model_requirement=self.risk_model_requirement,
                code_version=self.code_version,
                runtime_profile_id=self.runtime_profile_id,
                backend=self.backend,
                truth_requirement=self.truth_requirement,
                pit_requirement=self.pit_requirement,
                truth_admission=self.truth_admission,
            ),
        }

    def assert_canonical(self) -> None:
        if canonical_sha256({key: value for key, value in self.to_wire().items() if key not in {"policy_id", "content_sha256"}}) != self.content_sha256:
            raise RiskRuntimeError("RiskPolicyDefinition content identity mismatch")
        if self.policy_id != "rpd_sha256_" + self.content_sha256:
            raise RiskRuntimeError("RiskPolicyDefinition ID mismatch")


@dataclass(frozen=True, slots=True)
class RiskPolicySetVersion:
    risk_policy_set_version_id: str
    content_sha256: str
    policies: tuple[RiskPolicyDefinition, ...]
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = RISK_POLICY_SET_SCHEMA_VERSION

    @classmethod
    def create(cls, policies: tuple[RiskPolicyDefinition, ...]) -> RiskPolicySetVersion:
        if not policies or any(not isinstance(value, RiskPolicyDefinition) for value in policies):
            raise RiskRuntimeError("RiskPolicySetVersion requires ordered policies")
        for policy in policies:
            policy.assert_canonical()
        if len({value.policy_id for value in policies}) != len(policies):
            raise RiskRuntimeError("RiskPolicySetVersion policy IDs must be unique")
        runtime_keys = {
            (value.code_version, value.runtime_profile_id, value.backend) for value in policies
        }
        if len(runtime_keys) != 1:
            raise RiskRuntimeError("all policies in a set must use one exact runtime/backend")
        has_transform = any(value.mode is PolicyMode.CLIP for value in policies)
        has_explicit_pass = any(value.mode is PolicyMode.PASS_THROUGH for value in policies)
        if not has_transform and not has_explicit_pass:
            raise RiskRuntimeError(
                "a non-transforming policy set requires explicit PASS_THROUGH"
            )
        truth = policies[0].truth_admission
        for policy in policies[1:]:
            truth = meet_pair(truth, policy.truth_admission)
        payload = cls._payload(policies, truth)
        digest = canonical_sha256(payload)
        return cls("rpsv_sha256_" + digest, digest, policies, truth)

    @classmethod
    def _payload(
        cls,
        policies: tuple[RiskPolicyDefinition, ...],
        truth_admission: TruthAdmissionState,
    ) -> dict[str, object]:
        return {
            "schema_version": cls.schema_version,
            "ordered_policies": [value.to_wire() for value in policies],
            "truth_admission": truth_admission.to_wire(),
        }

    def to_wire(self) -> dict[str, object]:
        return {
            "risk_policy_set_version_id": self.risk_policy_set_version_id,
            "content_sha256": self.content_sha256,
            **self._payload(self.policies, self.truth_admission),
        }

    def assert_canonical(self) -> None:
        rebuilt = type(self).create(self.policies)
        if rebuilt != self:
            raise RiskRuntimeError("RiskPolicySetVersion identity mismatch")

    def as_w0_reference(self) -> UnresolvedExactReference:
        self.assert_canonical()
        return UnresolvedExactReference(
            ReferenceKind.RISK_POLICY_SET,
            self.risk_policy_set_version_id,
            self.content_sha256,
            self.truth_admission,
        )


@dataclass(frozen=True, slots=True)
class ExposureValues:
    gross_exposure: str
    net_exposure: str
    cash_weight: str
    max_single_name: str

    def to_wire(self) -> dict[str, str]:
        return {
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "cash_weight": self.cash_weight,
            "max_single_name": self.max_single_name,
        }


def vector_content_sha256(
    rows: tuple[TargetWeightRow, ...], cash_weight: str
) -> str:
    return canonical_sha256(
        {
            "cash_weight": cash_weight,
            "rows": [value.to_wire() for value in rows],
        }
    )


def exposure_values(
    rows: tuple[TargetWeightRow, ...], cash_weight: str
) -> ExposureValues:
    weights = tuple(_decimal(value.target_weight) for value in rows)
    gross = sum((abs(value) for value in weights), Decimal(0))
    net = sum(weights, Decimal(0))
    maximum = max(weights, default=Decimal(0))
    return ExposureValues(
        gross_exposure=normalize_weight_decimal(str(gross), "gross_exposure"),
        net_exposure=normalize_weight_decimal(str(net), "net_exposure"),
        cash_weight=normalize_weight_decimal(cash_weight, "cash_weight"),
        max_single_name=normalize_weight_decimal(str(maximum), "max_single_name"),
    )


@dataclass(frozen=True, slots=True)
class RiskStageReport:
    risk_stage_report_id: str
    content_sha256: str
    stage_index: int
    policy_id: str
    policy_type: PolicyType
    input_vector_sha256: str
    output_vector_sha256: str
    input_rows: tuple[RiskAdjustedWeightRow, ...]
    output_rows: tuple[RiskAdjustedWeightRow, ...]
    before: ExposureValues
    after: ExposureValues
    limits: tuple[tuple[str, str], ...]
    reason: str
    status: StageStatus
    residual_cash_handling: ResidualCashRule
    required_state_refs: tuple[RiskStateInput, ...]
    external_solver_evidence: str

    schema_version: ClassVar[str] = RISK_STAGE_REPORT_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        stage_index: int,
        policy: RiskPolicyDefinition,
        input_rows: tuple[RiskAdjustedWeightRow, ...],
        input_cash: str,
        output_rows: tuple[RiskAdjustedWeightRow, ...],
        output_cash: str,
        reason: str,
        status: StageStatus,
        required_state_refs: tuple[RiskStateInput, ...],
    ) -> RiskStageReport:
        if (
            not isinstance(stage_index, int)
            or isinstance(stage_index, bool)
            or stage_index < 1
        ):
            raise RiskRuntimeError("stage_index must be a positive integer")
        policy.assert_canonical()
        if not isinstance(status, StageStatus):
            raise TypeError("status must be StageStatus")
        if any(not isinstance(value, TargetWeightRow) for value in (*input_rows, *output_rows)):
            raise TypeError("risk stage rows must use the W0 weight row type")
        if any(not isinstance(value, RiskStateInput) for value in required_state_refs):
            raise TypeError("required_state_refs must contain RiskStateInput")
        _require_text(reason, "risk stage reason")
        payload = cls._payload(
            stage_index=stage_index,
            policy_id=policy.policy_id,
            policy_type=policy.policy_type,
            input_vector_sha256=vector_content_sha256(input_rows, input_cash),
            output_vector_sha256=vector_content_sha256(output_rows, output_cash),
            input_rows=input_rows,
            output_rows=output_rows,
            before=exposure_values(input_rows, input_cash),
            after=exposure_values(output_rows, output_cash),
            limits=policy.parameters,
            reason=reason,
            status=status,
            residual_cash_handling=policy.residual_cash_rule,
            required_state_refs=required_state_refs,
            external_solver_evidence="NOT_USED_V0",
        )
        digest = canonical_sha256(payload)
        return cls(
            risk_stage_report_id="rsr_sha256_" + digest,
            content_sha256=digest,
            stage_index=stage_index,
            policy_id=policy.policy_id,
            policy_type=policy.policy_type,
            input_vector_sha256=vector_content_sha256(input_rows, input_cash),
            output_vector_sha256=vector_content_sha256(output_rows, output_cash),
            input_rows=input_rows,
            output_rows=output_rows,
            before=exposure_values(input_rows, input_cash),
            after=exposure_values(output_rows, output_cash),
            limits=policy.parameters,
            reason=reason,
            status=status,
            residual_cash_handling=policy.residual_cash_rule,
            required_state_refs=required_state_refs,
            external_solver_evidence="NOT_USED_V0",
        )

    @classmethod
    def _payload(cls, **values: object) -> dict[str, object]:
        input_rows = values["input_rows"]
        output_rows = values["output_rows"]
        before = values["before"]
        after = values["after"]
        state_refs = values["required_state_refs"]
        assert isinstance(input_rows, tuple) and isinstance(output_rows, tuple)
        assert isinstance(before, ExposureValues) and isinstance(after, ExposureValues)
        assert isinstance(state_refs, tuple)
        return {
            "schema_version": cls.schema_version,
            "stage_index": values["stage_index"],
            "policy_id": values["policy_id"],
            "policy_type": values["policy_type"].value,
            "input_vector_sha256": values["input_vector_sha256"],
            "output_vector_sha256": values["output_vector_sha256"],
            "input_rows": [value.to_wire() for value in input_rows],
            "output_rows": [value.to_wire() for value in output_rows],
            "before": before.to_wire(),
            "after": after.to_wire(),
            "limits": [list(value) for value in values["limits"]],
            "reason": values["reason"],
            "status": values["status"].value,
            "residual_cash_handling": values["residual_cash_handling"].value,
            "required_state_refs": [value.to_wire() for value in state_refs],
            "external_solver_evidence": values["external_solver_evidence"],
        }

    def to_wire(self) -> dict[str, object]:
        return {
            "risk_stage_report_id": self.risk_stage_report_id,
            "content_sha256": self.content_sha256,
            **self._payload(
                stage_index=self.stage_index,
                policy_id=self.policy_id,
                policy_type=self.policy_type,
                input_vector_sha256=self.input_vector_sha256,
                output_vector_sha256=self.output_vector_sha256,
                input_rows=self.input_rows,
                output_rows=self.output_rows,
                before=self.before,
                after=self.after,
                limits=self.limits,
                reason=self.reason,
                status=self.status,
                residual_cash_handling=self.residual_cash_handling,
                required_state_refs=self.required_state_refs,
                external_solver_evidence=self.external_solver_evidence,
            ),
        }

    def assert_canonical(self) -> None:
        payload = {
            key: value
            for key, value in self.to_wire().items()
            if key not in {"risk_stage_report_id", "content_sha256"}
        }
        if canonical_sha256(payload) != self.content_sha256:
            raise RiskRuntimeError("RiskStageReport content identity mismatch")
        if self.risk_stage_report_id != "rsr_sha256_" + self.content_sha256:
            raise RiskRuntimeError("RiskStageReport ID mismatch")


@dataclass(frozen=True, slots=True)
class RiskDecisionReport:
    risk_decision_report_id: str
    content_sha256: str
    source_target_weight_vector_id: str
    source_target_content_sha256: str
    risk_policy_set_version_id: str
    risk_policy_set_content_sha256: str
    decision: DecisionStatus
    stages: tuple[RiskStageReport, ...]
    final_rows: tuple[RiskAdjustedWeightRow, ...]
    final_cash_weight: str
    final_vector_sha256: str
    rejection_reason: str | None
    state_inputs: tuple[RiskStateInput, ...]
    runtime_identity: RuntimeIdentity
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = RISK_DECISION_REPORT_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        source_target: TargetWeightVector,
        policy_set: RiskPolicySetVersion,
        decision: DecisionStatus,
        stages: tuple[RiskStageReport, ...],
        final_rows: tuple[RiskAdjustedWeightRow, ...],
        final_cash_weight: str,
        rejection_reason: str | None,
        state_inputs: tuple[RiskStateInput, ...],
        runtime_identity: RuntimeIdentity,
    ) -> RiskDecisionReport:
        source_target.assert_canonical()
        policy_set.assert_canonical()
        if not isinstance(decision, DecisionStatus):
            raise TypeError("decision must be DecisionStatus")
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be the W0 RuntimeIdentity")
        if not stages or len(stages) > len(policy_set.policies):
            raise RiskRuntimeError("decision report requires a bounded non-empty stage prefix")
        if any(not isinstance(value, RiskStageReport) for value in stages):
            raise TypeError("stages must contain RiskStageReport")
        if any(not isinstance(value, RiskStateInput) for value in state_inputs):
            raise TypeError("state_inputs must contain RiskStateInput")
        for index, stage in enumerate(stages, start=1):
            stage.assert_canonical()
            policy = policy_set.policies[index - 1]
            if (
                stage.stage_index != index
                or stage.policy_id != policy.policy_id
                or stage.policy_type is not policy.policy_type
            ):
                raise RiskRuntimeError("decision report stages must match the ordered policy set")
        if stages[0].input_vector_sha256 != vector_content_sha256(
            source_target.rows, source_target.cash_weight
        ):
            raise RiskRuntimeError("decision report first stage must bind the source target")
        for previous, current in zip(stages, stages[1:]):
            if previous.output_vector_sha256 != current.input_vector_sha256:
                raise RiskRuntimeError("decision report stage vector chain is broken")
        if (
            final_rows != stages[-1].output_rows
            or final_cash_weight != stages[-1].after.cash_weight
        ):
            raise RiskRuntimeError("decision report final vector must match the last stage")
        rejected = tuple(value for value in stages if value.status is StageStatus.REJECTED)
        adjusted = tuple(value for value in stages if value.status is StageStatus.ADJUSTED)
        if decision is DecisionStatus.REJECTED:
            if rejection_reason is None or rejected != (stages[-1],):
                raise RiskRuntimeError("REJECTED report requires one terminal rejected stage")
        elif rejection_reason is not None or rejected:
            raise RiskRuntimeError("successful report cannot carry rejection evidence")
        elif decision is DecisionStatus.ADJUSTED and not adjusted:
            raise RiskRuntimeError("ADJUSTED report requires an adjusted stage")
        elif decision is DecisionStatus.PASS_THROUGH and adjusted:
            raise RiskRuntimeError("PASS_THROUGH report cannot contain an adjusted stage")
        truth = meet_pair(source_target.truth_admission, policy_set.truth_admission)
        for state in state_inputs:
            truth = meet_pair(truth, state.reference.truth_admission)
        payload = cls._payload(
            source_target_weight_vector_id=source_target.target_weight_vector_id,
            source_target_content_sha256=source_target.content_sha256,
            risk_policy_set_version_id=policy_set.risk_policy_set_version_id,
            risk_policy_set_content_sha256=policy_set.content_sha256,
            decision=decision,
            stages=stages,
            final_rows=final_rows,
            final_cash_weight=final_cash_weight,
            final_vector_sha256=vector_content_sha256(final_rows, final_cash_weight),
            rejection_reason=rejection_reason,
            state_inputs=state_inputs,
            runtime_identity=runtime_identity,
            truth_admission=truth,
        )
        digest = canonical_sha256(payload)
        return cls(
            risk_decision_report_id="rdr_sha256_" + digest,
            content_sha256=digest,
            source_target_weight_vector_id=source_target.target_weight_vector_id,
            source_target_content_sha256=source_target.content_sha256,
            risk_policy_set_version_id=policy_set.risk_policy_set_version_id,
            risk_policy_set_content_sha256=policy_set.content_sha256,
            decision=decision,
            stages=stages,
            final_rows=final_rows,
            final_cash_weight=final_cash_weight,
            final_vector_sha256=vector_content_sha256(final_rows, final_cash_weight),
            rejection_reason=rejection_reason,
            state_inputs=state_inputs,
            runtime_identity=runtime_identity,
            truth_admission=truth,
        )

    @classmethod
    def _payload(cls, **values: object) -> dict[str, object]:
        stages = values["stages"]
        final_rows = values["final_rows"]
        state_inputs = values["state_inputs"]
        runtime = values["runtime_identity"]
        truth = values["truth_admission"]
        assert isinstance(stages, tuple) and isinstance(final_rows, tuple)
        assert isinstance(state_inputs, tuple) and isinstance(runtime, RuntimeIdentity)
        assert isinstance(truth, TruthAdmissionState)
        return {
            "schema_version": cls.schema_version,
            "source_target_weight_vector_id": values["source_target_weight_vector_id"],
            "source_target_content_sha256": values["source_target_content_sha256"],
            "risk_policy_set_version_id": values["risk_policy_set_version_id"],
            "risk_policy_set_content_sha256": values["risk_policy_set_content_sha256"],
            "decision": values["decision"].value,
            "stages": [value.to_wire() for value in stages],
            "final_rows": [value.to_wire() for value in final_rows],
            "final_cash_weight": values["final_cash_weight"],
            "final_vector_sha256": values["final_vector_sha256"],
            "rejection_reason": values["rejection_reason"],
            "state_inputs": [value.to_wire() for value in state_inputs],
            "runtime_identity": runtime.to_wire(),
            "truth_admission": truth.to_wire(),
        }

    def to_wire(self) -> dict[str, object]:
        return {
            "risk_decision_report_id": self.risk_decision_report_id,
            "content_sha256": self.content_sha256,
            **self._payload(
                source_target_weight_vector_id=self.source_target_weight_vector_id,
                source_target_content_sha256=self.source_target_content_sha256,
                risk_policy_set_version_id=self.risk_policy_set_version_id,
                risk_policy_set_content_sha256=self.risk_policy_set_content_sha256,
                decision=self.decision,
                stages=self.stages,
                final_rows=self.final_rows,
                final_cash_weight=self.final_cash_weight,
                final_vector_sha256=self.final_vector_sha256,
                rejection_reason=self.rejection_reason,
                state_inputs=self.state_inputs,
                runtime_identity=self.runtime_identity,
                truth_admission=self.truth_admission,
            ),
        }

    def assert_canonical(self) -> None:
        for stage in self.stages:
            stage.assert_canonical()
        payload = {
            key: value
            for key, value in self.to_wire().items()
            if key not in {"risk_decision_report_id", "content_sha256"}
        }
        if canonical_sha256(payload) != self.content_sha256:
            raise RiskRuntimeError("RiskDecisionReport content identity mismatch")
        if self.risk_decision_report_id != "rdr_sha256_" + self.content_sha256:
            raise RiskRuntimeError("RiskDecisionReport ID mismatch")

    def as_w0_reference(self) -> UnresolvedExactReference:
        self.assert_canonical()
        return UnresolvedExactReference(
            ReferenceKind.RISK_EVIDENCE,
            self.risk_decision_report_id,
            self.content_sha256,
            self.truth_admission,
        )


class RiskPolicyRejected(RiskRuntimeError):
    def __init__(self, report: RiskDecisionReport) -> None:
        self.report = report
        super().__init__(report.rejection_reason or "RISK_POLICY_REJECTED")


__all__ = [
    "DecisionStatus",
    "ExposureValues",
    "ExternalSolverAuthorityError",
    "FailureBehavior",
    "PitRequirement",
    "PolicyMode",
    "PolicyType",
    "ResidualCashRule",
    "RiskDecisionReport",
    "RiskModelRequirement",
    "RiskPolicyDefinition",
    "RiskPolicyRejected",
    "RiskPolicySetVersion",
    "RiskRuntimeError",
    "RiskStageReport",
    "RiskStateInput",
    "RiskStateRequirement",
    "StageStatus",
    "exposure_values",
    "vector_content_sha256",
]
