from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from v3_backend.agents.contracts import ProposalBoundary, StrictAgentModel, deterministic_json


ExactId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
CanonicalWireText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=65536)]
Sha256Exact = Annotated[str, StringConstraints(strict=True, pattern=r"[0-9a-f]{64}")]
ExactMetricName = Literal[
    "total_return",
    "annualized_return",
    "annualized_volatility",
    "max_drawdown",
    "sharpe",
    "sortino",
    "turnover",
]
ExactObjectiveDirection = Literal["MINIMIZE", "MAXIMIZE"]


def _nested_tuples(value: object) -> object:
    """Recursively convert JSON lists to tuples for strict nested tuple fields."""

    if isinstance(value, list):
        return tuple(_nested_tuples(item) for item in value)
    return value


class PortfolioRiskDraftKind(StrEnum):
    PORTFOLIO_CONSTRUCT = "PORTFOLIO_CONSTRUCT"
    RISK_APPLY = "RISK_APPLY"
    BACKTEST_RUN = "BACKTEST_RUN"
    RESULT_COMPARE = "RESULT_COMPARE"
    REVIEW_RUN = "REVIEW_RUN"


class PortfolioRiskScenarioContext(StrictAgentModel):
    """Exact caller-supplied canonical bindings for one portfolio/risk scenario.

    R never allocates any of these identities; every field must come from an
    existing canonical object supplied by the caller/application.
    """

    portfolio_intent_id: ExactId
    portfolio_intent_content_sha256: Sha256Exact
    strategy_definition_version_id: ExactId
    strategy_evaluation_binding_version_id: ExactId
    universe_version_id: ExactId
    universe_membership_artifact_id: ExactId
    selection_artifact_id: ExactId
    signal_artifact_id: ExactId | None = None
    snapshot_id: ExactId
    calendar_version_id: ExactId
    knowledge_cutoff: datetime
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    as_of: datetime
    decision_time: datetime
    rebalance_time: datetime
    valid_until: datetime
    construction_spec_version_id: ExactId
    construction_spec_content_sha256: Sha256Exact
    cost_policy_id: ExactId
    cost_policy_content_sha256: Sha256Exact
    rule_profile_id: ExactId
    execution_timing_profile_id: ExactId
    risk_policy_set_version_id: ExactId
    risk_policy_set_content_sha256: Sha256Exact
    risk_backend: ExactId
    risk_code_version: ExactId
    risk_runtime_profile_id: ExactId
    source_target_weight_vector_id: ExactId | None = None
    source_target_weight_vector_content_sha256: Sha256Exact | None = None
    risk_adjusted_weight_vector_id: ExactId | None = None
    risk_adjusted_weight_vector_content_sha256: Sha256Exact | None = None
    truth_admission: ExactId
    admission_state: ExactId

    @field_validator(
        "knowledge_cutoff", "as_of", "decision_time", "rebalance_time", "valid_until",
        mode="after",
    )
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scenario context timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def exact_target_ordering(self) -> "PortfolioRiskScenarioContext":
        if not self.as_of <= self.decision_time <= self.rebalance_time <= self.valid_until:
            raise ValueError("scenario timing must satisfy as_of <= decision_time <= rebalance_time <= valid_until")
        if (self.source_target_weight_vector_id is None) != (self.source_target_weight_vector_content_sha256 is None):
            raise ValueError("source target vector identity requires exact id and content hash")
        if (self.risk_adjusted_weight_vector_id is None) != (self.risk_adjusted_weight_vector_content_sha256 is None):
            raise ValueError("risk-adjusted vector identity requires exact id and content hash")
        if self.risk_adjusted_weight_vector_id is not None and self.source_target_weight_vector_id is None:
            raise ValueError("a risk-adjusted vector requires its exact source target vector")
        return self


class PortfolioConstructDraftPayload(StrictAgentModel):
    action: Literal["PORTFOLIO_CONSTRUCT"] = "PORTFOLIO_CONSTRUCT"
    context: PortfolioRiskScenarioContext
    requested_construction_spec_version_id: ExactId
    requested_cost_policy_id: ExactId
    expected_output_kind: Literal["TARGET_WEIGHT_VECTOR"] = "TARGET_WEIGHT_VECTOR"
    evidence_refs: tuple[ExactId, ...] = Field(min_length=1)
    user_confirmation_required: Literal[True] = True
    agent_execution_allowed: Literal[False] = False

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def bind_requested_spec(self) -> "PortfolioConstructDraftPayload":
        if self.requested_construction_spec_version_id != self.context.construction_spec_version_id:
            raise ValueError("portfolio construct draft must bind the exact construction spec")
        if self.requested_cost_policy_id != self.context.cost_policy_id:
            raise ValueError("portfolio construct draft must bind the exact CostPolicy")
        return self


class RiskApplyDraftPayload(StrictAgentModel):
    action: Literal["RISK_APPLY"] = "RISK_APPLY"
    context: PortfolioRiskScenarioContext
    source_target_weight_vector_id: ExactId
    source_target_weight_vector_content_sha256: Sha256Exact
    requested_risk_policy_set_version_id: ExactId
    requested_risk_policy_set_content_sha256: Sha256Exact
    risk_backend: ExactId
    risk_code_version: ExactId
    risk_runtime_profile_id: ExactId
    runtime_code_version: ExactId
    runtime_profile_id: ExactId
    runtime_environment_fingerprint: ExactId
    expected_output_kind: Literal["RISK_ADJUSTED_WEIGHT_VECTOR"] = "RISK_ADJUSTED_WEIGHT_VECTOR"
    evidence_refs: tuple[ExactId, ...] = Field(min_length=1)
    user_confirmation_required: Literal[True] = True
    agent_execution_allowed: Literal[False] = False

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def bind_exact_risk_authority(self) -> "RiskApplyDraftPayload":
        if self.source_target_weight_vector_id != self.context.source_target_weight_vector_id:
            raise ValueError("risk apply draft must bind the exact source TargetWeightVector")
        if self.source_target_weight_vector_content_sha256 != self.context.source_target_weight_vector_content_sha256:
            raise ValueError("risk apply draft must bind the exact source target content hash")
        if self.requested_risk_policy_set_version_id != self.context.risk_policy_set_version_id:
            raise ValueError("risk apply draft must bind the exact RiskPolicySetVersion")
        if self.requested_risk_policy_set_content_sha256 != self.context.risk_policy_set_content_sha256:
            raise ValueError("risk apply draft must bind the exact RiskPolicySetVersion content hash")
        if (self.risk_backend, self.risk_code_version, self.risk_runtime_profile_id) != (
            self.context.risk_backend,
            self.context.risk_code_version,
            self.context.risk_runtime_profile_id,
        ):
            raise ValueError("risk apply draft must bind the exact risk backend/code/runtime triple")
        return self


class BacktestRunDraftPayload(StrictAgentModel):
    action: Literal["BACKTEST_RUN"] = "BACKTEST_RUN"
    context: PortfolioRiskScenarioContext
    risk_adjusted_weight_vector_id: ExactId
    risk_adjusted_weight_vector_content_sha256: Sha256Exact
    effective_at: datetime
    initial_cash: str = Field(pattern=r"^\d+(\.\d+)?$")
    requested_cost_policy_id: ExactId
    requested_rule_profile_id: ExactId
    requested_execution_timing_profile_id: ExactId
    engine_version: ExactId
    backtest_run_spec_id: ExactId
    backtest_run_spec_content_sha256: Sha256Exact
    expected_output_kind: Literal["BACKTEST_RUN_RESULT"] = "BACKTEST_RUN_RESULT"
    evidence_refs: tuple[ExactId, ...] = Field(min_length=1)
    user_confirmation_required: Literal[True] = True
    agent_execution_allowed: Literal[False] = False

    @field_validator("effective_at", mode="after")
    @classmethod
    def effective_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("backtest effective_at must be timezone-aware")
        return value

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def bind_exact_backtest_inputs(self) -> "BacktestRunDraftPayload":
        if self.risk_adjusted_weight_vector_id != self.context.risk_adjusted_weight_vector_id:
            raise ValueError("backtest draft must bind the exact RiskAdjustedWeightVector")
        if self.risk_adjusted_weight_vector_content_sha256 != self.context.risk_adjusted_weight_vector_content_sha256:
            raise ValueError("backtest draft must bind the exact risk-adjusted content hash")
        if self.effective_at != self.context.rebalance_time:
            raise ValueError("backtest effective_at must equal the exact W0 rebalance_time")
        if self.requested_cost_policy_id != self.context.cost_policy_id:
            raise ValueError("backtest draft must bind the exact CostPolicy")
        if self.requested_rule_profile_id != self.context.rule_profile_id:
            raise ValueError("backtest draft must bind the exact A-share trading rule profile")
        if self.requested_execution_timing_profile_id != self.context.execution_timing_profile_id:
            raise ValueError("backtest draft must bind the exact execution timing profile")
        return self


class ResultCompareDraftPayload(StrictAgentModel):
    action: Literal["RESULT_COMPARE"] = "RESULT_COMPARE"
    left_analytics_id: ExactId
    right_analytics_id: ExactId
    objective_metric: ExactMetricName | None = None
    objective_direction: ExactObjectiveDirection | None = None
    evidence_refs: tuple[ExactId, ...] = Field(min_length=2)
    agent_execution_allowed: Literal[False] = False

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def complete_objective(self) -> "ResultCompareDraftPayload":
        flags = (self.objective_metric is None, self.objective_direction is None)
        if len(set(flags)) != 1:
            raise ValueError("comparison draft objective requires metric and direction together")
        return self


class ReviewRunDraftPayload(StrictAgentModel):
    action: Literal["REVIEW_RUN"] = "REVIEW_RUN"
    target_refs: tuple[ExactId, ...] = Field(min_length=1)
    evidence_refs: tuple[ExactId, ...] = Field(min_length=1)
    requested_rule_set_id: ExactId
    agent_execution_allowed: Literal[False] = False

    @field_validator("target_refs", "evidence_refs", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class PortfolioRiskAgentDraft(ProposalBoundary):
    proposal_type: Literal["PORTFOLIO_RISK_AGENT_DRAFT"] = "PORTFOLIO_RISK_AGENT_DRAFT"
    draft_kind: PortfolioRiskDraftKind
    payload: (
        PortfolioConstructDraftPayload
        | RiskApplyDraftPayload
        | BacktestRunDraftPayload
        | ResultCompareDraftPayload
        | ReviewRunDraftPayload
    ) = Field(discriminator="action")


class PortfolioRiskProposal(StrictAgentModel):
    research_goal: str
    agent_rationale: str | None = None
    exact_context: PortfolioRiskScenarioContext
    action_drafts: tuple[PortfolioRiskAgentDraft, ...] = Field(min_length=1, max_length=16)
    next_action_proposals: tuple[str, ...] = ()
    authority_status: Literal["NON_CANONICAL"] = "NON_CANONICAL"
    lifecycle_state: Literal["DRAFT"] = "DRAFT"
    agent_execution_allowed: Literal[False] = False

    @field_validator("action_drafts", "next_action_proposals", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def bind_every_action_to_context(self) -> "PortfolioRiskProposal":
        for draft in self.action_drafts:
            payload = draft.payload
            bound = getattr(payload, "context", None)
            if bound is not None and bound.portfolio_intent_id != self.exact_context.portfolio_intent_id:
                raise ValueError("proposal action must bind the exact PortfolioIntent context")
        return self


class PortfolioRiskNarrative(StrictAgentModel):
    rationale: str
    next_action_proposals: tuple[str, ...] = Field(default=(), max_length=16)
    evidence_claims: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("next_action_proposals", "evidence_claims", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class PortfolioIntentItemEvidence(StrictAgentModel):
    instrument_id: ExactId
    desired_exposure: str
    source_score: str | None = None
    source_node_path: tuple[str, ...] | None = None


class PortfolioIntentEvidenceView(StrictAgentModel):
    portfolio_intent_id: ExactId
    portfolio_intent_content_sha256: Sha256Exact
    strategy_definition_version_id: ExactId
    strategy_evaluation_binding_version_id: ExactId
    universe_version_id: ExactId
    universe_membership_artifact_id: ExactId
    selection_artifact_id: ExactId
    signal_artifact_id: ExactId | None = None
    exposure_mode: ExactId
    cash_policy: ExactId
    rebalance_intent: ExactId
    items: tuple[PortfolioIntentItemEvidence, ...] = Field(min_length=1)
    constraint_keys: tuple[ExactId, ...]
    knowledge_cutoff: datetime
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    truth_admission: ExactId
    admission_state: ExactId

    @field_validator("items", "constraint_keys", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class TargetWeightEvidenceRow(StrictAgentModel):
    instrument_id: ExactId
    target_weight: str


class TargetWeightEvidenceView(StrictAgentModel):
    target_weight_vector_id: ExactId
    content_sha256: Sha256Exact
    publisher_service: ExactId
    exposure_profile: Literal["LONG_ONLY_UNLEVERED"] = "LONG_ONLY_UNLEVERED"
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    as_of: datetime
    decision_time: datetime
    rebalance_time: datetime
    valid_until: datetime
    cash_weight: str
    rows: tuple[TargetWeightEvidenceRow, ...]
    evidence_refs: tuple[ExactId, ...] = Field(min_length=1)
    truth_admission: ExactId

    @field_validator("rows", "evidence_refs", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class RiskPolicyEvidence(StrictAgentModel):
    policy_id: ExactId
    policy_type: ExactId
    mode: ExactId
    parameters: tuple[tuple[ExactId, str], ...] = ()
    risk_model_requirement: ExactId
    residual_cash_rule: ExactId
    failure_behavior: ExactId

    @field_validator("parameters", mode="before")
    @classmethod
    def parameter_tuples(cls, value: object) -> object:
        return tuple(tuple(item) for item in value) if isinstance(value, list) else value


class RiskPolicySetEvidenceView(StrictAgentModel):
    risk_policy_set_version_id: ExactId
    content_sha256: Sha256Exact
    backend: ExactId
    code_version: ExactId
    runtime_profile_id: ExactId
    policies: tuple[RiskPolicyEvidence, ...] = Field(min_length=1)
    truth_admission: ExactId

    @field_validator("policies", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class RiskStageSummary(StrictAgentModel):
    stage_order: int = Field(ge=1)
    policy_id: ExactId
    status: ExactId
    reason: ExactId


class RiskAdjustedEvidenceView(StrictAgentModel):
    risk_adjusted_weight_vector_id: ExactId
    content_sha256: Sha256Exact
    source_target_weight_vector_id: ExactId
    source_target_content_sha256: Sha256Exact
    decision: ExactId
    decision_reason: ExactId
    cash_weight: str
    rows: tuple[TargetWeightEvidenceRow, ...]
    stage_summaries: tuple[RiskStageSummary, ...] = ()
    truth_admission: ExactId

    @field_validator("rows", "stage_summaries", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class CostPolicyEvidenceView(StrictAgentModel):
    policy_id: ExactId
    content_sha256: Sha256Exact
    policy_name: ExactId
    effective_from: str
    effective_to: str | None = None
    commission_rate: str
    minimum_commission: str
    stamp_duty_sell_rate: str
    market_rule_count: int = Field(ge=0)
    currency_scale: int = Field(ge=0)
    truth_admission: ExactId


class BacktestDiagnosticSummary(StrictAgentModel):
    code: ExactId
    count: int = Field(ge=0)


class BacktestResultEvidenceView(StrictAgentModel):
    result_id: ExactId
    content_sha256: Sha256Exact
    run_spec_id: ExactId
    run_spec_content_sha256: Sha256Exact | None = None
    engine_version: ExactId | None = None
    initial_cash: str
    session_count: int = Field(ge=1)
    order_count: int = Field(ge=0)
    fill_count: int = Field(ge=0)
    diagnostic_summary: tuple[BacktestDiagnosticSummary, ...] = ()
    final_cash: str
    final_nav: str
    final_holdings_count: int = Field(ge=0)
    nav_points: tuple[tuple[str, str], ...] = Field(min_length=1)
    scheduled_risk_adjusted_vector_ids: tuple[ExactId, ...] = ()
    bound_risk_adjusted_weight_vector_id: ExactId | None = None
    truth_admission: ExactId

    @field_validator("diagnostic_summary", "nav_points", "scheduled_risk_adjusted_vector_ids", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return _nested_tuples(value)


class AnalyticsMetricEvidence(StrictAgentModel):
    name: ExactMetricName
    status: Literal["AVAILABLE", "NOT_AVAILABLE", "INSUFFICIENT_SAMPLE"]
    value: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def require_exact_available_evidence(self) -> "AnalyticsMetricEvidence":
        if self.status == "AVAILABLE" and self.value is None:
            raise ValueError("available analytics metric requires an exact value")
        if self.status != "AVAILABLE" and self.value is not None:
            raise ValueError("missing/insufficient metric cannot carry a value")
        return self


class ResultAnalyticsEvidenceView(StrictAgentModel):
    analytics_id: ExactId
    content_sha256: Sha256Exact
    source_result_id: ExactId
    source_result_content_sha256: Sha256Exact
    analytics_policy_id: ExactId
    analytics_policy_content_sha256: Sha256Exact
    benchmark_series_id: ExactId | None = None
    metrics: tuple[AnalyticsMetricEvidence, ...] = Field(min_length=1)
    turnover: AnalyticsMetricEvidence
    fill_count: int = Field(ge=0)
    total_fees: str | None = None
    truth_admission: ExactId

    @field_validator("metrics", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReviewerTargetEvidence(StrictAgentModel):
    object_kind: ExactId
    object_id: ExactId
    content_sha256: Sha256Exact


class ReviewerEvidenceView(StrictAgentModel):
    review_report_id: ExactId
    rule_set_id: ExactId
    rule_set_content_sha256: Sha256Exact
    session_id: ExactId
    target_refs: tuple[ReviewerTargetEvidence, ...] = Field(min_length=1)
    overall_status: ExactId
    checked_rules: int = Field(ge=0)
    findings: tuple[tuple[ExactId, ExactId, str], ...] = ()
    truth_ceiling: ExactId

    @field_validator("target_refs", "findings", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return _nested_tuples(value)


class ScenarioEvidenceBundle(StrictAgentModel):
    """Untrusted evidence projection DTO for one scenario.

    This model is a public, plainly constructible data view intended for
    rendering/serialization only.  It carries no authority: a deterministic
    hash, `binding_gaps == ()`, copied ids/hashes or ordinary JSON
    deserialization cannot confer trusted status.  Trusted R consumers accept
    only `ResolvedScenarioEvidenceBundle` instances produced by
    `resolve_scenario_evidence` over canonical owner objects.

    Chain invariant: intent -> target -> risk-adjusted -> backtest -> analytics.
    `binding_gaps` lists links the current canonical owners could not prove;
    a bundle with gaps is never EVIDENCE_BOUND.
    """

    intent: PortfolioIntentEvidenceView
    construction_spec_version_id: ExactId
    construction_spec_content_sha256: Sha256Exact
    risk_policy_set: RiskPolicySetEvidenceView
    cost_policy: CostPolicyEvidenceView
    target: TargetWeightEvidenceView | None = None
    risk_adjusted: RiskAdjustedEvidenceView | None = None
    backtest: BacktestResultEvidenceView | None = None
    analytics: ResultAnalyticsEvidenceView | None = None
    reviewer_reports: tuple[ReviewerEvidenceView, ...] = ()
    binding_gaps: tuple[ExactId, ...] = ()

    @field_validator("reviewer_reports", "binding_gaps", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def chain_ordering(self) -> "ScenarioEvidenceBundle":
        if self.risk_adjusted is not None and self.target is None:
            raise ValueError("risk-adjusted evidence requires the exact target vector view")
        if self.backtest is not None and self.risk_adjusted is None:
            raise ValueError("backtest evidence requires the exact risk-adjusted view")
        if self.analytics is not None and self.backtest is None:
            raise ValueError("analytics evidence requires the exact backtest view")
        return self

    @property
    def treatment_context_key(self) -> tuple[tuple[str, str], ...]:
        return (
            ("construction_spec_version_id", self.construction_spec_version_id),
            ("risk_policy_set_version_id", self.risk_policy_set.risk_policy_set_version_id),
            ("cost_policy_id", self.cost_policy.policy_id),
        )


def comparison_invariant_content(
    *,
    portfolio_intent_id: ExactId,
    portfolio_intent_content_sha256: Sha256Exact,
    universe_version_id: ExactId,
    universe_membership_artifact_id: ExactId,
    knowledge_cutoff: datetime,
    snapshot_id: ExactId,
    calendar_version_id: ExactId,
    base_currency: str,
    analytics_policy_id: ExactId,
    analytics_policy_content_sha256: Sha256Exact,
    benchmark_series_id: ExactId | None,
    initial_cash: str,
    initial_holdings: tuple[tuple[ExactId, int, str], ...],
    instruments: tuple[tuple[ExactId, str], ...],
    session_dates: tuple[str, ...],
    session_market_state_inputs: str,
    corporate_action_events: str,
    exact_input_references: str,
    rule_profile_id: ExactId,
    rule_profile_content_sha256: Sha256Exact,
    execution_timing_profile_id: ExactId,
    execution_timing_profile_content_sha256: Sha256Exact,
    execution_convention: ExactId,
    runtime_identity: str,
    engine_version: ExactId,
    valuation_mode: str,
) -> dict[str, object]:
    """Exact non-treatment dimensions used for the deterministic invariant identity."""

    return {
        "portfolio_intent_id": portfolio_intent_id,
        "portfolio_intent_content_sha256": portfolio_intent_content_sha256,
        "universe_version_id": universe_version_id,
        "universe_membership_artifact_id": universe_membership_artifact_id,
        "knowledge_cutoff": knowledge_cutoff.isoformat(),
        "snapshot_id": snapshot_id,
        "calendar_version_id": calendar_version_id,
        "base_currency": base_currency,
        "analytics_policy_id": analytics_policy_id,
        "analytics_policy_content_sha256": analytics_policy_content_sha256,
        "benchmark_series_id": benchmark_series_id,
        "initial_cash": initial_cash,
        "initial_holdings": [list(item) for item in initial_holdings],
        "instruments": [list(item) for item in instruments],
        "session_dates": list(session_dates),
        "session_market_state_inputs": session_market_state_inputs,
        "corporate_action_events": corporate_action_events,
        "exact_input_references": exact_input_references,
        "rule_profile_id": rule_profile_id,
        "rule_profile_content_sha256": rule_profile_content_sha256,
        "execution_timing_profile_id": execution_timing_profile_id,
        "execution_timing_profile_content_sha256": execution_timing_profile_content_sha256,
        "execution_convention": execution_convention,
        "runtime_identity": runtime_identity,
        "engine_version": engine_version,
        "valuation_mode": valuation_mode,
    }


def comparison_invariant_identity(**dimensions: object) -> str:
    """Deterministic content hash over the exact non-treatment dimensions."""

    return hashlib.sha256(deterministic_json(comparison_invariant_content(**dimensions)).encode("utf-8")).hexdigest()


class ScenarioComparisonInvariant(StrictAgentModel):
    """Resolver-derived deterministic comparison invariant (R-D).

    Derived exclusively by the system resolver from canonical scenario and
    backtest evidence — especially the exact BacktestRunSpec and its pinned
    canonical inputs.  Callers cannot claim comparison equivalence: the
    `invariant_id` is the content hash of every non-treatment execution and
    evaluation dimension below, recomputed and verified on construction.

    Treatment dimensions (construction spec, risk policy set, cost policy) are
    deliberately absent so that disclosed experimental treatments remain
    comparable under exact invariant equality.
    """

    invariant_id: Sha256Exact
    portfolio_intent_id: ExactId
    portfolio_intent_content_sha256: Sha256Exact
    universe_version_id: ExactId
    universe_membership_artifact_id: ExactId
    knowledge_cutoff: datetime
    snapshot_id: ExactId
    calendar_version_id: ExactId
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    analytics_policy_id: ExactId
    analytics_policy_content_sha256: Sha256Exact
    benchmark_series_id: ExactId | None = None
    initial_cash: str
    initial_holdings: tuple[tuple[ExactId, int, str], ...] = ()
    instruments: tuple[tuple[ExactId, str], ...] = Field(min_length=1)
    session_dates: tuple[str, ...] = Field(min_length=1)
    session_market_state_inputs: CanonicalWireText
    corporate_action_events: CanonicalWireText
    exact_input_references: CanonicalWireText
    rule_profile_id: ExactId
    rule_profile_content_sha256: Sha256Exact
    execution_timing_profile_id: ExactId
    execution_timing_profile_content_sha256: Sha256Exact
    execution_convention: ExactId
    runtime_identity: CanonicalWireText
    engine_version: ExactId
    valuation_mode: Literal["RAW_EOD_CLOSE_FAIL_CLOSED"] = "RAW_EOD_CLOSE_FAIL_CLOSED"

    @field_validator("knowledge_cutoff", mode="after")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("comparison invariant knowledge_cutoff must be timezone-aware")
        return value

    @field_validator("initial_holdings", "instruments", "session_dates", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(tuple(item) if isinstance(item, list) else item for item in value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def exact_invariant_identity(self) -> "ScenarioComparisonInvariant":
        expected = comparison_invariant_identity(
            portfolio_intent_id=self.portfolio_intent_id,
            portfolio_intent_content_sha256=self.portfolio_intent_content_sha256,
            universe_version_id=self.universe_version_id,
            universe_membership_artifact_id=self.universe_membership_artifact_id,
            knowledge_cutoff=self.knowledge_cutoff,
            snapshot_id=self.snapshot_id,
            calendar_version_id=self.calendar_version_id,
            base_currency=self.base_currency,
            analytics_policy_id=self.analytics_policy_id,
            analytics_policy_content_sha256=self.analytics_policy_content_sha256,
            benchmark_series_id=self.benchmark_series_id,
            initial_cash=self.initial_cash,
            initial_holdings=self.initial_holdings,
            instruments=self.instruments,
            session_dates=self.session_dates,
            session_market_state_inputs=self.session_market_state_inputs,
            corporate_action_events=self.corporate_action_events,
            exact_input_references=self.exact_input_references,
            rule_profile_id=self.rule_profile_id,
            rule_profile_content_sha256=self.rule_profile_content_sha256,
            execution_timing_profile_id=self.execution_timing_profile_id,
            execution_timing_profile_content_sha256=self.execution_timing_profile_content_sha256,
            execution_convention=self.execution_convention,
            runtime_identity=self.runtime_identity,
            engine_version=self.engine_version,
            valuation_mode=self.valuation_mode,
        )
        if self.invariant_id != expected:
            raise ValueError("scenario comparison invariant id must be the exact content hash of its dimensions")
        return self


class ComparisonStatus(StrEnum):
    COMPARABLE = "COMPARABLE"
    INCOMPARABLE_CONTEXT = "INCOMPARABLE_CONTEXT"


class MetricDelta(StrictAgentModel):
    name: ExactMetricName
    status: Literal["AVAILABLE", "NOT_AVAILABLE", "INSUFFICIENT_SAMPLE"]
    left_value: str | None = None
    right_value: str | None = None
    delta_right_minus_left: str | None = None

    @model_validator(mode="after")
    def bind_values_to_status(self) -> "MetricDelta":
        values = (self.left_value, self.right_value, self.delta_right_minus_left)
        if self.status == "AVAILABLE" and any(value is None for value in values):
            raise ValueError("available metric delta requires both values and the delta")
        if self.status != "AVAILABLE" and any(value is not None for value in values):
            raise ValueError("missing metric delta cannot carry values")
        return self


class ScenarioComparison(StrictAgentModel):
    status: ComparisonStatus
    left_analytics_id: ExactId
    right_analytics_id: ExactId
    context_mismatches: tuple[ExactId, ...] = ()
    scenario_differences: tuple[ExactId, ...] = ()
    metric_deltas: tuple[MetricDelta, ...] = ()
    objective_metric: ExactMetricName | None = None
    objective_direction: ExactObjectiveDirection | None = None
    ranking: Literal["LEFT", "RIGHT", "TIE"] | None = None

    @field_validator("context_mismatches", "scenario_differences", "metric_deltas", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def prohibit_incomparable_ranking(self) -> "ScenarioComparison":
        if self.status is ComparisonStatus.INCOMPARABLE_CONTEXT:
            if self.metric_deltas or self.ranking or self.scenario_differences:
                raise ValueError("incomparable contexts cannot carry deltas, differences or a ranking")
        if self.ranking is not None and (self.objective_metric is None or self.objective_direction is None):
            raise ValueError("ranking requires an exact objective metric and direction")
        return self


class ScenarioEvidenceExplanation(StrictAgentModel):
    status: Literal["EVIDENCE_BOUND", "EVIDENCE_MISSING", "EVIDENCE_BINDING_UNAVAILABLE"]
    summary: str
    constraint_statements: tuple[str, ...] = ()
    weight_change_statements: tuple[str, ...] = ()
    risk_diagnostic_statements: tuple[str, ...] = ()
    cost_statements: tuple[str, ...] = ()
    analytics_statements: tuple[str, ...] = ()
    reviewer_statements: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    next_action_proposals: tuple[str, ...] = ()
    cited_evidence_refs: tuple[ExactId, ...] = ()
    invented_exposure: Literal[False] = False
    invented_covariance: Literal[False] = False
    invented_analytics: Literal[False] = False
    invented_causality: Literal[False] = False
    invented_optimization: Literal[False] = False

    @field_validator(
        "constraint_statements", "weight_change_statements", "risk_diagnostic_statements",
        "cost_statements", "analytics_statements", "reviewer_statements",
        "missing_evidence", "next_action_proposals", "cited_evidence_refs", mode="before",
    )
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class UserConfirmation(StrictAgentModel):
    confirmation_type: Literal["USER_CONFIRMATION"] = "USER_CONFIRMATION"
    action: Literal["PORTFOLIO_CONSTRUCT", "RISK_APPLY", "BACKTEST_RUN"]
    draft_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    confirmed_by: ExactId
    confirmed_at: datetime
    agent_issued: Literal[False] = False

    @field_validator("confirmed_at", mode="after")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("user confirmation timestamp must be timezone-aware")
        return value
