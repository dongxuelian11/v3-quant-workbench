from __future__ import annotations

from datetime import datetime

from v3_backend.domain.backtest_runtime import (
    BacktestRunResult,
    BacktestRunSpec,
    DeterministicAshareBacktestEngine,
)
from v3_backend.domain.portfolio_construction import (
    DeterministicPortfolioConstruction,
    PortfolioConstructionResult,
    PortfolioConstructionSpecVersion,
)
from v3_backend.domain.risk_runtime import (
    RiskPolicySetVersion,
    RiskRuntimeResult,
    RiskStateInput,
    apply_risk,
)
from v3_backend.domain.strategies import (
    PortfolioIntent,
    StrategyDefinitionVersion,
    StrategyEvaluationBindingVersion,
)
from v3_backend.domain.weights import RuntimeIdentity, TargetWeightVector

from .contracts import (
    PortfolioRiskAgentDraft,
    PortfolioRiskDraftKind,
    UserConfirmation,
)


class PortfolioRiskApplicationError(ValueError):
    pass


def _confirmed(
    draft: PortfolioRiskAgentDraft,
    confirmation: UserConfirmation,
    expected: PortfolioRiskDraftKind,
) -> None:
    if draft.draft_kind is not expected:
        raise PortfolioRiskApplicationError("confirmation action does not match draft kind")
    if confirmation.action != expected.value:
        raise PortfolioRiskApplicationError("confirmation action does not match application command")
    if confirmation.draft_sha256 != draft.deterministic_sha256:
        raise PortfolioRiskApplicationError("user confirmation must bind the exact draft hash")
    if confirmation.agent_issued:
        raise PortfolioRiskApplicationError("Agent-issued confirmation is forbidden")


def apply_confirmed_portfolio_construct(
    *,
    draft: PortfolioRiskAgentDraft,
    confirmation: UserConfirmation,
    intent: PortfolioIntent,
    definition: StrategyDefinitionVersion,
    binding: StrategyEvaluationBindingVersion,
    construction_spec: PortfolioConstructionSpecVersion,
    runtime_identity: RuntimeIdentity,
    base_currency: str,
    as_of: datetime,
    decision_time: datetime,
    rebalance_time: datetime,
    valid_until: datetime,
) -> PortfolioConstructionResult:
    """User-confirmed construction through the exact H canonical owner.

    No optimizer candidate is ever passed; V0 construction admits none.
    """

    _confirmed(draft, confirmation, PortfolioRiskDraftKind.PORTFOLIO_CONSTRUCT)
    payload = draft.payload
    if payload.action != "PORTFOLIO_CONSTRUCT":
        raise PortfolioRiskApplicationError("typed portfolio construct payload required")
    if not isinstance(construction_spec, PortfolioConstructionSpecVersion):
        raise PortfolioRiskApplicationError("application requires the exact PortfolioConstructionSpecVersion")
    if construction_spec.portfolio_construction_spec_version_id != payload.requested_construction_spec_version_id:
        raise PortfolioRiskApplicationError("application construction spec mismatch")
    if intent.portfolio_intent_id != payload.context.portfolio_intent_id:
        raise PortfolioRiskApplicationError("application PortfolioIntent mismatch")
    return DeterministicPortfolioConstruction().construct(
        intent=intent,
        definition=definition,
        binding=binding,
        construction_spec=construction_spec,
        runtime_identity=runtime_identity,
        base_currency=base_currency,
        as_of=as_of,
        decision_time=decision_time,
        rebalance_time=rebalance_time,
        valid_until=valid_until,
    )


def apply_confirmed_risk_apply(
    *,
    draft: PortfolioRiskAgentDraft,
    confirmation: UserConfirmation,
    source_target: TargetWeightVector,
    policy_set: RiskPolicySetVersion,
    runtime_identity: RuntimeIdentity,
    state_inputs: tuple[RiskStateInput, ...] = (),
) -> RiskRuntimeResult:
    """User-confirmed risk application through the exact I canonical owner.

    No external solver candidate is ever passed; canonical Risk V0 output only.
    """

    _confirmed(draft, confirmation, PortfolioRiskDraftKind.RISK_APPLY)
    payload = draft.payload
    if payload.action != "RISK_APPLY":
        raise PortfolioRiskApplicationError("typed risk apply payload required")
    if not isinstance(source_target, TargetWeightVector):
        raise PortfolioRiskApplicationError("application requires the exact TargetWeightVector")
    if source_target.target_weight_vector_id != payload.source_target_weight_vector_id:
        raise PortfolioRiskApplicationError("application source TargetWeightVector mismatch")
    if not isinstance(policy_set, RiskPolicySetVersion):
        raise PortfolioRiskApplicationError("application requires the exact RiskPolicySetVersion")
    if policy_set.risk_policy_set_version_id != payload.requested_risk_policy_set_version_id:
        raise PortfolioRiskApplicationError("application risk policy set mismatch")
    return apply_risk(
        source_target=source_target,
        policy_set=policy_set,
        runtime_identity=runtime_identity,
        state_inputs=state_inputs,
    )


def apply_confirmed_backtest_run(
    *,
    draft: PortfolioRiskAgentDraft,
    confirmation: UserConfirmation,
    spec: BacktestRunSpec,
) -> BacktestRunResult:
    """User-confirmed A-share backtest through the exact J canonical owner."""

    _confirmed(draft, confirmation, PortfolioRiskDraftKind.BACKTEST_RUN)
    payload = draft.payload
    if payload.action != "BACKTEST_RUN":
        raise PortfolioRiskApplicationError("typed backtest run payload required")
    if not isinstance(spec, BacktestRunSpec):
        raise PortfolioRiskApplicationError("application requires the exact BacktestRunSpec")
    if payload.risk_adjusted_weight_vector_id != payload.context.risk_adjusted_weight_vector_id:
        raise PortfolioRiskApplicationError("backtest draft context is not exactly bound")
    if not spec.schedule:
        raise PortfolioRiskApplicationError("application backtest spec requires a schedule")
    scheduled_ids = {item.vector.risk_adjusted_weight_vector_id for item in spec.schedule}
    if payload.risk_adjusted_weight_vector_id not in scheduled_ids:
        raise PortfolioRiskApplicationError("application schedule does not include the exact RiskAdjustedWeightVector")
    if spec.cost_policy.policy_id != payload.requested_cost_policy_id:
        raise PortfolioRiskApplicationError("application CostPolicy mismatch")
    if spec.engine_version != payload.engine_version:
        raise PortfolioRiskApplicationError("application engine version mismatch")
    if spec.rule_profile.profile_id != payload.requested_rule_profile_id:
        raise PortfolioRiskApplicationError("application A-share rule profile mismatch")
    if spec.execution_timing_profile.profile_id != payload.requested_execution_timing_profile_id:
        raise PortfolioRiskApplicationError("application execution timing profile mismatch")
    return DeterministicAshareBacktestEngine().run(spec)


__all__ = [
    "PortfolioRiskApplicationError",
    "apply_confirmed_backtest_run",
    "apply_confirmed_portfolio_construct",
    "apply_confirmed_risk_apply",
]
