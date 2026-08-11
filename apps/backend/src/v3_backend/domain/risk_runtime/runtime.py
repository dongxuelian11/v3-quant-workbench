from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from v3_backend.domain.weights import (
    RiskAdjustedWeightVector,
    RiskApplicationReceipt,
    RiskDecision,
    RiskDecisionReason,
    RiskStageEvidence,
    RuntimeIdentity,
    TargetWeightRow,
    TargetWeightVector,
    normalize_weight_decimal,
)

from .model import (
    DecisionStatus,
    ExternalSolverAuthorityError,
    PitRequirement,
    PolicyType,
    RISK_V0_BACKEND,
    RiskDecisionReport,
    RiskPolicyDefinition,
    RiskPolicyRejected,
    RiskPolicySetVersion,
    RiskRuntimeError,
    RiskStageReport,
    RiskStateInput,
    StageStatus,
    exposure_values,
)


@dataclass(frozen=True, slots=True)
class RiskRuntimeResult:
    policy_set: RiskPolicySetVersion
    decision_report: RiskDecisionReport
    application_receipt: RiskApplicationReceipt
    adjusted_weights: RiskAdjustedWeightVector


def _canonical_state_inputs(
    values: tuple[RiskStateInput, ...],
) -> tuple[RiskStateInput, ...]:
    if any(not isinstance(value, RiskStateInput) for value in values):
        raise TypeError("state_inputs must contain RiskStateInput")
    ordered = tuple(sorted(values, key=lambda value: value.input_key))
    if len({value.input_key for value in ordered}) != len(ordered):
        raise RiskRuntimeError("risk state input keys must be unique")
    reference_keys = tuple(
        (value.reference.reference_kind, value.reference.source_id) for value in ordered
    )
    if len(set(reference_keys)) != len(reference_keys):
        raise RiskRuntimeError("risk state exact references must be unique")
    return ordered


def _policy_state_inputs(
    *,
    policy: RiskPolicyDefinition,
    available: dict[str, RiskStateInput],
    source_target: TargetWeightVector,
) -> tuple[tuple[RiskStateInput, ...], str | None]:
    selected: list[RiskStateInput] = []
    for requirement in policy.required_state_inputs:
        observed = available.get(requirement.input_key)
        if observed is None:
            return (), "MISSING_REQUIRED_RISK_STATE:" + requirement.input_key
        if observed.reference.reference_kind is not requirement.reference_kind:
            return (), "RISK_STATE_KIND_MISMATCH:" + requirement.input_key
        if (
            requirement.pit_requirement
            is PitRequirement.AS_OF_NOT_AFTER_TARGET_DECISION
            and observed.as_of > source_target.decision_time
        ):
            return (), "RISK_STATE_PIT_VIOLATION:" + requirement.input_key
        selected.append(observed)
    return tuple(selected), None


def _rejected_report(
    *,
    source_target: TargetWeightVector,
    policy_set: RiskPolicySetVersion,
    stages: tuple[RiskStageReport, ...],
    rows: tuple[TargetWeightRow, ...],
    cash_weight: str,
    reason: str,
    state_inputs: tuple[RiskStateInput, ...],
    runtime_identity: RuntimeIdentity,
) -> RiskDecisionReport:
    return RiskDecisionReport.create(
        source_target=source_target,
        policy_set=policy_set,
        decision=DecisionStatus.REJECTED,
        stages=stages,
        final_rows=rows,
        final_cash_weight=cash_weight,
        rejection_reason=reason,
        state_inputs=state_inputs,
        runtime_identity=runtime_identity,
    )


def _execute_stage(
    *,
    stage_index: int,
    policy: RiskPolicyDefinition,
    rows: tuple[TargetWeightRow, ...],
    cash_weight: str,
    stage_state_inputs: tuple[RiskStateInput, ...],
) -> tuple[tuple[TargetWeightRow, ...], str, RiskStageReport, bool]:
    output_rows = rows
    output_cash = cash_weight
    changed = False
    status = StageStatus.PASSED

    if policy.policy_type is PolicyType.PASS_THROUGH:
        reason = "NO_ADDITIONAL_RISK_TRANSFORM"
    elif policy.policy_type is PolicyType.MAX_SINGLE_NAME:
        limit = Decimal(dict(policy.parameters)["max_weight"])
        residual = Decimal(0)
        clipped: list[TargetWeightRow] = []
        for row in rows:
            before = Decimal(row.target_weight)
            after = min(before, limit)
            residual += before - after
            clipped.append(TargetWeightRow(row.instrument_id, str(after)))
        output_rows = tuple(clipped)
        if residual:
            output_cash = normalize_weight_decimal(
                str(Decimal(cash_weight) + residual),
                "cash_weight",
            )
            changed = True
            status = StageStatus.ADJUSTED
            reason = "MAX_SINGLE_NAME_CLIPPED"
        else:
            reason = "WITHIN_MAX_SINGLE_NAME"
    elif policy.policy_type is PolicyType.GROSS_NET_EXPOSURE_VALIDATE:
        limits = {key: Decimal(value) for key, value in policy.parameters}
        exposure = exposure_values(rows, cash_weight)
        gross = Decimal(exposure.gross_exposure)
        net = Decimal(exposure.net_exposure)
        if gross > limits["max_gross"]:
            reason = "GROSS_EXPOSURE_LIMIT_EXCEEDED"
            status = StageStatus.REJECTED
        elif net < limits["min_net"]:
            reason = "NET_EXPOSURE_BELOW_MINIMUM"
            status = StageStatus.REJECTED
        elif net > limits["max_net"]:
            reason = "NET_EXPOSURE_ABOVE_MAXIMUM"
            status = StageStatus.REJECTED
        else:
            reason = "GROSS_NET_EXPOSURE_VALIDATED"
    else:
        raise RiskRuntimeError("unsupported Risk V0 policy type")

    report = RiskStageReport.create(
        stage_index=stage_index,
        policy=policy,
        input_rows=rows,
        input_cash=cash_weight,
        output_rows=output_rows,
        output_cash=output_cash,
        reason=reason,
        status=status,
        required_state_refs=stage_state_inputs,
    )
    return output_rows, output_cash, report, changed


def apply_risk(
    *,
    source_target: TargetWeightVector,
    policy_set: RiskPolicySetVersion,
    runtime_identity: RuntimeIdentity,
    state_inputs: tuple[RiskStateInput, ...] = (),
    external_solver_candidate: object | None = None,
) -> RiskRuntimeResult:
    """Apply ordered Risk V0 policies and publish only through the W0 seam."""

    if external_solver_candidate is not None:
        raise ExternalSolverAuthorityError(
            "external solver candidates cannot assign canonical Risk V0 output"
        )
    if not isinstance(source_target, TargetWeightVector):
        raise TypeError("source_target must be the canonical W0 TargetWeightVector object")
    source_target.assert_canonical()
    if not isinstance(policy_set, RiskPolicySetVersion):
        raise TypeError("policy_set must be RiskPolicySetVersion")
    policy_set.assert_canonical()
    if not isinstance(runtime_identity, RuntimeIdentity):
        raise TypeError("runtime_identity must be the W0 RuntimeIdentity")
    for policy in policy_set.policies:
        if policy.backend != RISK_V0_BACKEND:
            raise RiskRuntimeError(
                f"policy set is not executable by Risk V0 backend {RISK_V0_BACKEND}"
            )
        if (
            policy.code_version != runtime_identity.code_version
            or policy.runtime_profile_id != runtime_identity.runtime_profile_id
        ):
            raise RiskRuntimeError("policy set and runtime identity must match exactly")

    ordered_state_inputs = _canonical_state_inputs(state_inputs)
    available = {value.input_key: value for value in ordered_state_inputs}
    required_keys = {
        requirement.input_key
        for policy in policy_set.policies
        for requirement in policy.required_state_inputs
    }
    unexpected = set(available) - required_keys
    if unexpected:
        raise RiskRuntimeError(
            "undeclared risk state inputs are forbidden: " + ",".join(sorted(unexpected))
        )

    rows = source_target.rows
    cash_weight = source_target.cash_weight
    stage_reports: list[RiskStageReport] = []
    transformed = False

    for stage_index, policy in enumerate(policy_set.policies, start=1):
        selected_state, state_error = _policy_state_inputs(
            policy=policy,
            available=available,
            source_target=source_target,
        )
        if state_error is not None:
            rejected_stage = RiskStageReport.create(
                stage_index=stage_index,
                policy=policy,
                input_rows=rows,
                input_cash=cash_weight,
                output_rows=rows,
                output_cash=cash_weight,
                reason=state_error,
                status=StageStatus.REJECTED,
                required_state_refs=(),
            )
            stage_reports.append(rejected_stage)
            raise RiskPolicyRejected(
                _rejected_report(
                    source_target=source_target,
                    policy_set=policy_set,
                    stages=tuple(stage_reports),
                    rows=rows,
                    cash_weight=cash_weight,
                    reason=state_error,
                    state_inputs=ordered_state_inputs,
                    runtime_identity=runtime_identity,
                )
            )

        rows, cash_weight, stage_report, changed = _execute_stage(
            stage_index=stage_index,
            policy=policy,
            rows=rows,
            cash_weight=cash_weight,
            stage_state_inputs=selected_state,
        )
        stage_reports.append(stage_report)
        transformed = transformed or changed
        if stage_report.status is StageStatus.REJECTED:
            raise RiskPolicyRejected(
                _rejected_report(
                    source_target=source_target,
                    policy_set=policy_set,
                    stages=tuple(stage_reports),
                    rows=rows,
                    cash_weight=cash_weight,
                    reason=stage_report.reason,
                    state_inputs=ordered_state_inputs,
                    runtime_identity=runtime_identity,
                )
            )

    decision = DecisionStatus.ADJUSTED if transformed else DecisionStatus.PASS_THROUGH
    report = RiskDecisionReport.create(
        source_target=source_target,
        policy_set=policy_set,
        decision=decision,
        stages=tuple(stage_reports),
        final_rows=rows,
        final_cash_weight=cash_weight,
        rejection_reason=None,
        state_inputs=ordered_state_inputs,
        runtime_identity=runtime_identity,
    )
    application = RiskApplicationReceipt.create(
        source_target=source_target,
        risk_policy_set=policy_set.as_w0_reference(),
        decision=(
            RiskDecision.ADJUSTED if transformed else RiskDecision.PASS_THROUGH
        ),
        decision_reason=(
            RiskDecisionReason.POLICY_TRANSFORM_APPLIED
            if transformed
            else RiskDecisionReason.NO_ADDITIONAL_RISK_TRANSFORM
        ),
        stages=tuple(
            RiskStageEvidence(
                value.stage_index,
                value.risk_stage_report_id,
                value.policy_id,
                value.content_sha256,
            )
            for value in stage_reports
        ),
        supporting_refs=(
            report.as_w0_reference(),
            *(value.reference for value in ordered_state_inputs),
        ),
        runtime_identity=runtime_identity,
    )
    adjusted = RiskAdjustedWeightVector.create(
        source_target=source_target,
        risk_application=application,
        runtime_identity=runtime_identity,
        cash_weight=cash_weight,
        rows=rows,
    )
    return RiskRuntimeResult(
        policy_set=policy_set,
        decision_report=report,
        application_receipt=application,
        adjusted_weights=adjusted,
    )


__all__ = ["RiskRuntimeResult", "apply_risk"]
