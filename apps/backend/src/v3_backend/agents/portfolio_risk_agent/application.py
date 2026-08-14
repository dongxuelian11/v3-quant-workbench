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


USER_EXECUTION_AUTHORITY_NOT_AVAILABLE = "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE"


class PortfolioRiskApplicationError(ValueError):
    pass


class UserExecutionAuthorityNotAvailable(PortfolioRiskApplicationError):
    """Production user-execution authority does not exist on current main."""


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


def _authority_fail_closed() -> None:
    raise UserExecutionAuthorityNotAvailable(
        USER_EXECUTION_AUTHORITY_NOT_AVAILABLE
        + ": no canonical user-action/approval authority exists on current main; "
        + "production R execution is NOT_AVAILABLE / NOT_RUN; R does not mint a second approval authority"
    )


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
    """User-confirmed construction seam.

    Production execution is NOT_AVAILABLE: current main has no canonical
    user-action/approval authority, and a caller-shaped UserConfirmation is not
    authority. The seam fails closed before any owner invocation.
    """

    _authority_fail_closed()


def apply_confirmed_risk_apply(
    *,
    draft: PortfolioRiskAgentDraft,
    confirmation: UserConfirmation,
    source_target: TargetWeightVector,
    policy_set: RiskPolicySetVersion,
    runtime_identity: RuntimeIdentity,
    state_inputs: tuple[RiskStateInput, ...] = (),
) -> RiskRuntimeResult:
    """User-confirmed risk application seam. Fails closed: no user-execution authority on current main."""

    _authority_fail_closed()


def apply_confirmed_backtest_run(
    *,
    draft: PortfolioRiskAgentDraft,
    confirmation: UserConfirmation,
    spec: BacktestRunSpec,
) -> BacktestRunResult:
    """User-confirmed A-share backtest seam. Fails closed: no user-execution authority on current main."""

    _authority_fail_closed()


def verify_portfolio_construct_binding(
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
) -> None:
    """Exact confirmation binding checks for the future user-execution seam.

    Canonical owner validation remains necessary but is not a substitute for
    confirmation binding. This verifier is the R execution-input binding model;
    it is exercised directly by tests until a canonical user-action authority
    exists on main.
    """

    _confirmed(draft, confirmation, PortfolioRiskDraftKind.PORTFOLIO_CONSTRUCT)
    payload = draft.payload
    if payload.action != "PORTFOLIO_CONSTRUCT":
        raise PortfolioRiskApplicationError("typed portfolio construct payload required")
    context = payload.context
    if not isinstance(construction_spec, PortfolioConstructionSpecVersion):
        raise PortfolioRiskApplicationError("verification requires the exact PortfolioConstructionSpecVersion")
    if construction_spec.portfolio_construction_spec_version_id != payload.requested_construction_spec_version_id:
        raise PortfolioRiskApplicationError("construction spec id mismatch after confirmation")
    if construction_spec.content_sha256 != context.construction_spec_content_sha256:
        raise PortfolioRiskApplicationError("construction spec content hash mismatch after confirmation")
    if intent.portfolio_intent_id != context.portfolio_intent_id:
        raise PortfolioRiskApplicationError("PortfolioIntent mismatch after confirmation")
    if definition.strategy_definition_version_id != context.strategy_definition_version_id:
        raise PortfolioRiskApplicationError("StrategyDefinitionVersion mismatch after confirmation")
    if binding.strategy_evaluation_binding_version_id != context.strategy_evaluation_binding_version_id:
        raise PortfolioRiskApplicationError("StrategyEvaluationBindingVersion mismatch after confirmation")
    if base_currency != context.base_currency:
        raise PortfolioRiskApplicationError("base_currency mismatch after confirmation")
    if as_of != context.as_of:
        raise PortfolioRiskApplicationError("as_of mismatch after confirmation")
    if decision_time != context.decision_time:
        raise PortfolioRiskApplicationError("decision_time mismatch after confirmation")
    if rebalance_time != context.rebalance_time:
        raise PortfolioRiskApplicationError("rebalance_time mismatch after confirmation")
    if valid_until != context.valid_until:
        raise PortfolioRiskApplicationError("valid_until mismatch after confirmation")
    if not isinstance(runtime_identity, RuntimeIdentity):
        raise PortfolioRiskApplicationError("verification requires the exact W0 RuntimeIdentity")
    if runtime_identity != construction_spec.runtime_identity:
        raise PortfolioRiskApplicationError("runtime identity does not bind the exact construction spec")


def verify_risk_apply_binding(
    *,
    draft: PortfolioRiskAgentDraft,
    confirmation: UserConfirmation,
    source_target: TargetWeightVector,
    policy_set: RiskPolicySetVersion,
    runtime_identity: RuntimeIdentity,
    state_inputs: tuple[RiskStateInput, ...] = (),
) -> None:
    """Exact confirmation binding checks for the future risk-execution seam.

    Route A (bounded V0): no state-input execution in R; `state_inputs` must be
    empty. PIT/state-input validation remains delegated to the canonical Risk
    runtime whenever a future authority admits execution.
    """

    _confirmed(draft, confirmation, PortfolioRiskDraftKind.RISK_APPLY)
    payload = draft.payload
    if payload.action != "RISK_APPLY":
        raise PortfolioRiskApplicationError("typed risk apply payload required")
    if state_inputs:
        raise PortfolioRiskApplicationError("unbound risk state inputs are rejected at the R user-execution seam (Route A: state_inputs must be empty)")
    if not isinstance(source_target, TargetWeightVector):
        raise PortfolioRiskApplicationError("verification requires the exact TargetWeightVector")
    if source_target.target_weight_vector_id != payload.source_target_weight_vector_id:
        raise PortfolioRiskApplicationError("source target id mismatch after confirmation")
    if source_target.content_sha256 != payload.source_target_weight_vector_content_sha256:
        raise PortfolioRiskApplicationError("source target content hash mismatch after confirmation")
    if not isinstance(policy_set, RiskPolicySetVersion):
        raise PortfolioRiskApplicationError("verification requires the exact RiskPolicySetVersion")
    if policy_set.risk_policy_set_version_id != payload.requested_risk_policy_set_version_id:
        raise PortfolioRiskApplicationError("risk policy set id mismatch after confirmation")
    if policy_set.content_sha256 != payload.requested_risk_policy_set_content_sha256:
        raise PortfolioRiskApplicationError("risk policy set content hash mismatch after confirmation")
    first = policy_set.policies[0]
    if (first.backend, first.code_version, first.runtime_profile_id) != (
        payload.risk_backend,
        payload.risk_code_version,
        payload.risk_runtime_profile_id,
    ):
        raise PortfolioRiskApplicationError("risk backend/code/runtime triple mismatch after confirmation")
    if not isinstance(runtime_identity, RuntimeIdentity):
        raise PortfolioRiskApplicationError("verification requires the exact W0 RuntimeIdentity")
    if (runtime_identity.code_version, runtime_identity.runtime_profile_id, runtime_identity.environment_fingerprint) != (
        payload.runtime_code_version,
        payload.runtime_profile_id,
        payload.runtime_environment_fingerprint,
    ):
        raise PortfolioRiskApplicationError("runtime identity mismatch after confirmation")


def verify_backtest_binding(
    *,
    draft: PortfolioRiskAgentDraft,
    confirmation: UserConfirmation,
    spec: BacktestRunSpec,
) -> None:
    """Exact confirmation binding checks for the future backtest-execution seam.

    The confirmed draft binds an exact content-addressed BacktestRunSpec
    identity (id + content hash), which covers every execution-changing input
    (sessions, instruments, exact references, schedule). No weak partial hash
    is invented.
    """

    _confirmed(draft, confirmation, PortfolioRiskDraftKind.BACKTEST_RUN)
    payload = draft.payload
    if payload.action != "BACKTEST_RUN":
        raise PortfolioRiskApplicationError("typed backtest run payload required")
    if not isinstance(spec, BacktestRunSpec):
        raise PortfolioRiskApplicationError("verification requires the exact BacktestRunSpec")
    if spec.run_spec_id != payload.backtest_run_spec_id:
        raise PortfolioRiskApplicationError("BacktestRunSpec id mismatch after confirmation")
    if spec.content_sha256 != payload.backtest_run_spec_content_sha256:
        raise PortfolioRiskApplicationError("BacktestRunSpec content hash mismatch after confirmation")
    if spec.initial_cash != payload.initial_cash:
        raise PortfolioRiskApplicationError("initial_cash mismatch after confirmation")
    if spec.engine_version != payload.engine_version:
        raise PortfolioRiskApplicationError("engine version mismatch after confirmation")
    if spec.cost_policy.policy_id != payload.requested_cost_policy_id:
        raise PortfolioRiskApplicationError("CostPolicy mismatch after confirmation")
    if spec.rule_profile.profile_id != payload.requested_rule_profile_id:
        raise PortfolioRiskApplicationError("A-share rule profile mismatch after confirmation")
    if spec.execution_timing_profile.profile_id != payload.requested_execution_timing_profile_id:
        raise PortfolioRiskApplicationError("execution timing profile mismatch after confirmation")
    scheduled = {item.vector.risk_adjusted_weight_vector_id: item for item in spec.schedule}
    if payload.risk_adjusted_weight_vector_id not in scheduled:
        raise PortfolioRiskApplicationError("schedule does not include the exact RiskAdjustedWeightVector")
    bound = scheduled[payload.risk_adjusted_weight_vector_id]
    if bound.effective_at != payload.effective_at:
        raise PortfolioRiskApplicationError("scheduled effective time mismatch after confirmation")
    if bound.vector.content_sha256 != payload.risk_adjusted_weight_vector_content_sha256:
        raise PortfolioRiskApplicationError("scheduled vector content hash mismatch after confirmation")


__all__ = [
    "PortfolioRiskApplicationError",
    "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE",
    "UserExecutionAuthorityNotAvailable",
    "apply_confirmed_backtest_run",
    "apply_confirmed_portfolio_construct",
    "apply_confirmed_risk_apply",
    "verify_backtest_binding",
    "verify_portfolio_construct_binding",
    "verify_risk_apply_binding",
]
