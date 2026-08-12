from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal

from v3_backend.agents.contracts import AgentProvenance, PermissionLevel
from v3_backend.agents.permissions import decide_permission
from v3_backend.domain.backtest_runtime import BacktestRunResult, CostPolicyVersion
from v3_backend.domain.portfolio_construction import (
    PortfolioConstructionSpecVersion,
)
from v3_backend.domain.result_analytics import BacktestResultAnalytics
from v3_backend.domain.reviewer_integration import ResearchReviewReport
from v3_backend.domain.risk_runtime import RiskDecisionReport, RiskPolicySetVersion
from v3_backend.domain.strategies import (
    PortfolioIntent,
    StrategyDefinitionVersion,
    StrategyEvaluationBindingVersion,
)
from v3_backend.domain.weights import (
    PortfolioIntentSource,
    ReferenceKind,
    RiskAdjustedWeightVector,
    TargetWeightVector,
    UnresolvedExactReference,
)

from .contracts import (
    AnalyticsMetricEvidence,
    BacktestDiagnosticSummary,
    BacktestResultEvidenceView,
    BacktestRunDraftPayload,
    ComparisonStatus,
    CostPolicyEvidenceView,
    MetricDelta,
    PortfolioConstructDraftPayload,
    PortfolioIntentEvidenceView,
    PortfolioIntentItemEvidence,
    PortfolioRiskAgentDraft,
    PortfolioRiskDraftKind,
    PortfolioRiskProposal,
    PortfolioRiskScenarioContext,
    ResultAnalyticsEvidenceView,
    ResultCompareDraftPayload,
    ReviewRunDraftPayload,
    ReviewerEvidenceView,
    RiskAdjustedEvidenceView,
    RiskApplyDraftPayload,
    RiskPolicyEvidence,
    RiskPolicySetEvidenceView,
    RiskStageSummary,
    ScenarioComparison,
    ScenarioEvidenceBundle,
    ScenarioEvidenceExplanation,
    TargetWeightEvidenceRow,
    TargetWeightEvidenceView,
)


class PortfolioRiskAgentBindingError(ValueError):
    pass


def _binding(condition: bool, message: str) -> None:
    if not condition:
        raise PortfolioRiskAgentBindingError(message)


def _truth_wire(admission: object) -> tuple[str, str]:
    wire = admission.to_wire()
    return str(wire["canonical_truth_state"]), str(wire["canonical_admission_state"])


def _draft(*, kind: PortfolioRiskDraftKind, payload: object, provenance: AgentProvenance) -> PortfolioRiskAgentDraft:
    return PortfolioRiskAgentDraft(
        draft_kind=kind,
        payload=payload,
        permission_decision=decide_permission(PermissionLevel.L1_DRAFT),
        provenance=provenance,
    )


def read_portfolio_intent(
    *,
    intent: PortfolioIntent,
    source: PortfolioIntentSource,
    binding: StrategyEvaluationBindingVersion,
    base_currency: str,
) -> PortfolioIntentEvidenceView:
    if not isinstance(intent, PortfolioIntent):
        raise TypeError("intent must be the canonical PortfolioIntent object")
    if not isinstance(source, PortfolioIntentSource):
        raise TypeError("source must be the canonical PortfolioIntentSource object")
    if not isinstance(binding, StrategyEvaluationBindingVersion):
        raise TypeError("binding must be the canonical StrategyEvaluationBindingVersion object")
    _binding(source.portfolio_intent_id == intent.portfolio_intent_id, "PortfolioIntentSource does not bind the exact PortfolioIntent")
    _binding(source.strategy_definition_version_id == intent.strategy_definition_version_id, "strategy definition identity mismatch")
    _binding(source.strategy_evaluation_binding_version_id == intent.strategy_evaluation_binding_version_id, "evaluation binding identity mismatch")
    _binding(source.strategy_evaluation_binding_version_id == binding.strategy_evaluation_binding_version_id, "binding identity mismatch")
    truth, admission = _truth_wire(source.truth_admission)
    return PortfolioIntentEvidenceView(
        portfolio_intent_id=intent.portfolio_intent_id,
        portfolio_intent_content_sha256=source.portfolio_intent_content_sha256,
        strategy_definition_version_id=intent.strategy_definition_version_id,
        strategy_evaluation_binding_version_id=intent.strategy_evaluation_binding_version_id,
        universe_version_id=source.universe_version_id,
        universe_membership_artifact_id=source.membership_artifact_id,
        selection_artifact_id=intent.source_selection_artifact_id,
        signal_artifact_id=intent.source_signal_artifact_id,
        exposure_mode=intent.exposure_mode,
        cash_policy=intent.cash_policy,
        rebalance_intent=intent.rebalance_intent,
        items=tuple(
            PortfolioIntentItemEvidence(
                instrument_id=item.instrument_id,
                desired_exposure=str(item.desired_exposure),
                source_score=str(item.source_score) if item.source_score is not None else None,
                source_node_path=tuple(item.source_node_path) if item.source_node_path is not None else None,
            )
            for item in intent.items
        ),
        constraint_keys=tuple(sorted(intent.constraints)),
        knowledge_cutoff=binding.knowledge_cutoff,
        base_currency=base_currency,
        truth_admission=truth,
        admission_state=admission,
    )


def build_scenario_context(
    *,
    intent: PortfolioIntent,
    definition: StrategyDefinitionVersion,
    binding: StrategyEvaluationBindingVersion,
    construction_spec: UnresolvedExactReference,
    cost_policy: CostPolicyVersion,
    rule_profile_id: str,
    execution_timing_profile_id: str,
    risk_policy_set: RiskPolicySetVersion,
    base_currency: str,
    source_target: TargetWeightVector | None = None,
    risk_adjusted: RiskAdjustedWeightVector | None = None,
    as_of: datetime | None = None,
    decision_time: datetime | None = None,
    rebalance_time: datetime | None = None,
    valid_until: datetime | None = None,
) -> PortfolioRiskScenarioContext:
    source = PortfolioIntentSource.create(intent=intent, definition=definition, binding=binding)
    if not isinstance(construction_spec, UnresolvedExactReference):
        raise TypeError("construction_spec must be the exact UnresolvedExactReference")
    _binding(construction_spec.reference_kind is ReferenceKind.CONSTRUCTION_SPEC, "construction spec reference kind must be CONSTRUCTION_SPEC")
    if not isinstance(cost_policy, CostPolicyVersion):
        raise TypeError("cost_policy must be the canonical CostPolicyVersion object")
    cost_policy.assert_canonical()
    if not isinstance(risk_policy_set, RiskPolicySetVersion):
        raise TypeError("risk_policy_set must be the canonical RiskPolicySetVersion object")
    risk_policy_set.assert_canonical()
    policies = risk_policy_set.policies
    _binding(len(policies) >= 1, "risk policy set must contain at least one policy")
    backends = {policy.backend for policy in policies}
    code_versions = {policy.code_version for policy in policies}
    runtime_profiles = {policy.runtime_profile_id for policy in policies}
    _binding(len(backends) == 1 and len(code_versions) == 1 and len(runtime_profiles) == 1, "risk policy set must share one exact backend/code/runtime identity")
    risk_code_version = next(iter(code_versions))
    risk_runtime_profile_id = next(iter(runtime_profiles))
    if source_target is not None:
        if not isinstance(source_target, TargetWeightVector):
            raise TypeError("source_target must be the canonical TargetWeightVector object")
        source_target.assert_canonical()
        _binding(source_target.source.portfolio_intent_id == intent.portfolio_intent_id, "target vector does not bind the exact PortfolioIntent")
        _binding(risk_code_version == source_target.runtime_identity.code_version, "risk policy set code version does not bind the exact target runtime")
        _binding(risk_runtime_profile_id == source_target.runtime_identity.runtime_profile_id, "risk policy set runtime profile does not bind the exact target runtime")
        as_of = source_target.as_of
        decision_time = source_target.decision_time
        rebalance_time = source_target.rebalance_time
        valid_until = source_target.valid_until
        base_currency = source_target.base_currency
    for name, value in (("as_of", as_of), ("decision_time", decision_time), ("rebalance_time", rebalance_time), ("valid_until", valid_until)):
        _binding(isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None, f"{name} must be timezone-aware")
    if source_target is None:
        _binding(binding.period.start <= as_of <= binding.period.end, "as_of must be inside the exact StrategyEvaluationBinding period")
        _binding(binding.period.start <= decision_time <= binding.period.end, "decision_time must be inside the exact StrategyEvaluationBinding period")
        _binding(as_of <= binding.knowledge_cutoff, "as_of must not exceed the exact knowledge cutoff")
        _binding(decision_time <= binding.knowledge_cutoff, "decision_time must not exceed the exact knowledge cutoff")
    if risk_adjusted is not None:
        if not isinstance(risk_adjusted, RiskAdjustedWeightVector):
            raise TypeError("risk_adjusted must be the canonical RiskAdjustedWeightVector object")
        risk_adjusted.assert_canonical()
        _binding(risk_adjusted.source_target is not None, "risk-adjusted vector must bind its exact source target")
        _binding(source_target is not None and risk_adjusted.source_target.target_weight_vector_id == source_target.target_weight_vector_id, "risk-adjusted vector does not bind the exact source TargetWeightVector")
    truth, admission = _truth_wire(source.truth_admission)
    return PortfolioRiskScenarioContext(
        portfolio_intent_id=intent.portfolio_intent_id,
        portfolio_intent_content_sha256=source.portfolio_intent_content_sha256,
        strategy_definition_version_id=definition.strategy_definition_version_id,
        strategy_evaluation_binding_version_id=binding.strategy_evaluation_binding_version_id,
        universe_version_id=source.universe_version_id,
        universe_membership_artifact_id=source.membership_artifact_id,
        selection_artifact_id=intent.source_selection_artifact_id,
        signal_artifact_id=intent.source_signal_artifact_id,
        snapshot_id=binding.snapshot.snapshot_id,
        calendar_version_id=binding.calendar.calendar_version_id,
        knowledge_cutoff=binding.knowledge_cutoff,
        base_currency=base_currency,
        as_of=as_of,
        decision_time=decision_time,
        rebalance_time=rebalance_time,
        valid_until=valid_until,
        construction_spec_version_id=construction_spec.source_id,
        construction_spec_content_sha256=construction_spec.content_sha256,
        cost_policy_id=cost_policy.policy_id,
        cost_policy_content_sha256=cost_policy.content_sha256,
        rule_profile_id=rule_profile_id,
        execution_timing_profile_id=execution_timing_profile_id,
        risk_policy_set_version_id=risk_policy_set.risk_policy_set_version_id,
        risk_policy_set_content_sha256=risk_policy_set.content_sha256,
        risk_backend=next(iter(backends)),
        risk_code_version=risk_code_version,
        risk_runtime_profile_id=risk_runtime_profile_id,
        source_target_weight_vector_id=source_target.target_weight_vector_id if source_target is not None else None,
        source_target_weight_vector_content_sha256=source_target.content_sha256 if source_target is not None else None,
        risk_adjusted_weight_vector_id=risk_adjusted.risk_adjusted_weight_vector_id if risk_adjusted is not None else None,
        risk_adjusted_weight_vector_content_sha256=risk_adjusted.content_sha256 if risk_adjusted is not None else None,
        truth_admission=truth,
        admission_state=admission,
    )


def read_target_weight_evidence(target: TargetWeightVector) -> TargetWeightEvidenceView:
    if not isinstance(target, TargetWeightVector):
        raise TypeError("target must be the canonical TargetWeightVector object")
    target.assert_canonical()
    truth, _ = _truth_wire(target.truth_admission)
    return TargetWeightEvidenceView(
        target_weight_vector_id=target.target_weight_vector_id,
        content_sha256=target.content_sha256,
        publisher_service=target.publisher_service,
        base_currency=target.base_currency,
        as_of=target.as_of,
        decision_time=target.decision_time,
        rebalance_time=target.rebalance_time,
        valid_until=target.valid_until,
        cash_weight=target.cash_weight,
        rows=tuple(TargetWeightEvidenceRow(instrument_id=row.instrument_id, target_weight=row.target_weight) for row in target.rows),
        evidence_refs=tuple(reference.source_id for reference in target.evidence_refs),
        truth_admission=truth,
    )


def read_risk_policy_set(policy_set: RiskPolicySetVersion) -> RiskPolicySetEvidenceView:
    if not isinstance(policy_set, RiskPolicySetVersion):
        raise TypeError("policy_set must be the canonical RiskPolicySetVersion object")
    policy_set.assert_canonical()
    first = policy_set.policies[0]
    truth, _ = _truth_wire(policy_set.truth_admission)
    return RiskPolicySetEvidenceView(
        risk_policy_set_version_id=policy_set.risk_policy_set_version_id,
        content_sha256=policy_set.content_sha256,
        backend=first.backend,
        code_version=first.code_version,
        runtime_profile_id=first.runtime_profile_id,
        policies=tuple(
            RiskPolicyEvidence(
                policy_id=policy.policy_id,
                policy_type=policy.policy_type.value,
                mode=policy.mode.value,
                parameters=tuple((key, str(value)) for key, value in policy.parameters),
                risk_model_requirement=policy.risk_model_requirement.value,
                residual_cash_rule=policy.residual_cash_rule.value,
                failure_behavior=policy.failure_behavior.value,
            )
            for policy in policy_set.policies
        ),
        truth_admission=truth,
    )


def read_risk_adjusted_evidence(
    adjusted: RiskAdjustedWeightVector,
    decision_report: RiskDecisionReport | None = None,
) -> RiskAdjustedEvidenceView:
    if not isinstance(adjusted, RiskAdjustedWeightVector):
        raise TypeError("adjusted must be the canonical RiskAdjustedWeightVector object")
    adjusted.assert_canonical()
    stages: tuple[RiskStageSummary, ...] = ()
    if decision_report is not None:
        if not isinstance(decision_report, RiskDecisionReport):
            raise TypeError("decision_report must be the canonical RiskDecisionReport object")
        decision_report.assert_canonical()
        _binding(decision_report.source_target_weight_vector_id == adjusted.risk_application.source_target_weight_vector_id, "risk decision report does not bind the exact source target")
        stages = tuple(
            RiskStageSummary(
                stage_order=stage.stage_index,
                policy_id=stage.policy_id,
                status=stage.status.value,
                reason=stage.reason,
            )
            for stage in decision_report.stages
        )
    truth, _ = _truth_wire(adjusted.truth_admission)
    return RiskAdjustedEvidenceView(
        risk_adjusted_weight_vector_id=adjusted.risk_adjusted_weight_vector_id,
        content_sha256=adjusted.content_sha256,
        source_target_weight_vector_id=adjusted.risk_application.source_target_weight_vector_id,
        source_target_content_sha256=adjusted.risk_application.source_target_content_sha256,
        decision=adjusted.risk_application.decision.value,
        decision_reason=adjusted.risk_application.decision_reason.value,
        cash_weight=adjusted.cash_weight,
        rows=tuple(TargetWeightEvidenceRow(instrument_id=row.instrument_id, target_weight=row.target_weight) for row in adjusted.rows),
        stage_summaries=stages,
        truth_admission=truth,
    )


def read_cost_policy(cost: CostPolicyVersion) -> CostPolicyEvidenceView:
    if not isinstance(cost, CostPolicyVersion):
        raise TypeError("cost must be the canonical CostPolicyVersion object")
    cost.assert_canonical()
    truth, _ = _truth_wire(cost.truth_admission)
    return CostPolicyEvidenceView(
        policy_id=cost.policy_id,
        content_sha256=cost.content_sha256,
        policy_name=cost.policy_name,
        effective_from=cost.effective_from.isoformat(),
        effective_to=cost.effective_to.isoformat() if cost.effective_to is not None else None,
        commission_rate=cost.commission_rate,
        minimum_commission=cost.minimum_commission,
        stamp_duty_sell_rate=cost.stamp_duty_sell_rate,
        market_rule_count=len(cost.market_rules),
        currency_scale=cost.currency_scale,
        truth_admission=truth,
    )


def read_backtest_result(result: BacktestRunResult, engine_version: str | None = None) -> BacktestResultEvidenceView:
    if not isinstance(result, BacktestRunResult):
        raise TypeError("result must be the canonical BacktestRunResult object")
    if not result.nav:
        raise PortfolioRiskAgentBindingError("backtest result requires at least one NAV point")
    diagnostic_counts = Counter(diagnostic.code.value for diagnostic in result.diagnostics)
    truth, _ = _truth_wire(result.truth_admission)
    final = result.nav[-1]
    initial_cash = ""
    for entry in result.cash_ledger:
        if entry.kind.value == "INITIAL_CASH":
            initial_cash = entry.amount
            break
    return BacktestResultEvidenceView(
        result_id=result.result_id,
        content_sha256=result.content_sha256,
        run_spec_id=result.run_spec_id,
        engine_version=engine_version,
        initial_cash=initial_cash,
        session_count=len(result.nav),
        order_count=len(result.orders),
        fill_count=len(result.fills),
        diagnostic_summary=tuple(
            BacktestDiagnosticSummary(code=code, count=count) for code, count in sorted(diagnostic_counts.items())
        ),
        final_cash=final.cash,
        final_nav=final.nav,
        final_holdings_count=len(result.holdings),
        nav_points=tuple((row.session_date.isoformat(), row.nav) for row in result.nav),
        truth_admission=truth,
    )


def read_result_analytics(analytics: BacktestResultAnalytics) -> ResultAnalyticsEvidenceView:
    if not isinstance(analytics, BacktestResultAnalytics):
        raise TypeError("analytics must be the canonical BacktestResultAnalytics object")

    def project(name: str, metric: object) -> AnalyticsMetricEvidence:
        status = metric.status.value
        if status == "AVAILABLE":
            return AnalyticsMetricEvidence(name=name, status="AVAILABLE", value=str(metric.value))
        return AnalyticsMetricEvidence(name=name, status=status, reason=metric.reason)

    turnover_metric = analytics.turnover.turnover
    truth, _ = _truth_wire(analytics.truth_admission)
    return ResultAnalyticsEvidenceView(
        analytics_id=analytics.analytics_id,
        content_sha256=analytics.content_sha256,
        source_result_id=analytics.source_result_id,
        source_result_content_sha256=analytics.source_result_content_sha256,
        analytics_policy_id=analytics.analytics_policy_id,
        analytics_policy_content_sha256=analytics.analytics_policy_content_sha256,
        benchmark_series_id=analytics.benchmark_series_id,
        metrics=(
            project("total_return", analytics.total_return),
            project("annualized_return", analytics.annualized_return),
            project("annualized_volatility", analytics.annualized_volatility),
            project("max_drawdown", analytics.max_drawdown),
            project("sharpe", analytics.sharpe),
            project("sortino", analytics.sortino),
        ),
        turnover=AnalyticsMetricEvidence(
            name="turnover",
            status="AVAILABLE" if turnover_metric.status.value == "AVAILABLE" else turnover_metric.status.value,
            value=str(turnover_metric.value) if turnover_metric.status.value == "AVAILABLE" else None,
            reason=turnover_metric.reason if turnover_metric.status.value != "AVAILABLE" else None,
        ),
        fill_count=analytics.costs.fill_count,
        total_fees=analytics.costs.total_fees,
        truth_admission=truth,
    )


def read_reviewer_report(report: ResearchReviewReport) -> ReviewerEvidenceView:
    if not isinstance(report, ResearchReviewReport):
        raise TypeError("report must be the canonical ResearchReviewReport object")
    truth_ceiling = report.truth_ceiling.to_wire()
    ceiling = str(truth_ceiling.get("canonical_truth_state", "UNKNOWN_CEILING"))
    return ReviewerEvidenceView(
        review_report_id=report.review_report_id,
        rule_set_id=report.rule_set_id,
        rule_set_content_sha256=report.rule_set_content_sha256,
        session_id=report.session_id,
        target_ref_count=len(report.target_refs),
        overall_status=report.overall_status.value,
        checked_rules=report.coverage.checked_rules,
        findings=tuple((finding.kind.value, finding.severity.value, finding.summary) for finding in report.findings),
        truth_ceiling=ceiling,
    )


def build_scenario_bundle(
    *,
    intent: PortfolioIntentEvidenceView,
    construction_spec: UnresolvedExactReference,
    risk_policy_set: RiskPolicySetEvidenceView,
    cost_policy: CostPolicyEvidenceView,
    target: TargetWeightEvidenceView | None = None,
    risk_adjusted: RiskAdjustedEvidenceView | None = None,
    backtest: BacktestResultEvidenceView | None = None,
    analytics: ResultAnalyticsEvidenceView | None = None,
    reviewer_reports: tuple[ReviewerEvidenceView, ...] = (),
) -> ScenarioEvidenceBundle:
    if not isinstance(construction_spec, UnresolvedExactReference):
        raise TypeError("construction_spec must be the exact UnresolvedExactReference")
    _binding(construction_spec.reference_kind is ReferenceKind.CONSTRUCTION_SPEC, "construction spec reference kind must be CONSTRUCTION_SPEC")
    if target is not None and risk_adjusted is not None:
        _binding(risk_adjusted.source_target_weight_vector_id == target.target_weight_vector_id, "bundle risk-adjusted evidence must bind the exact target vector")
    if backtest is not None and risk_adjusted is not None:
        _binding(backtest is not None and risk_adjusted.risk_adjusted_weight_vector_id is not None, "bundle backtest evidence requires an exact risk-adjusted vector")
    if analytics is not None and backtest is not None:
        _binding(analytics.source_result_id == backtest.result_id, "bundle analytics must bind the exact backtest result")
    return ScenarioEvidenceBundle(
        intent=intent,
        construction_spec_version_id=construction_spec.source_id,
        construction_spec_content_sha256=construction_spec.content_sha256,
        risk_policy_set=risk_policy_set,
        cost_policy=cost_policy,
        target=target,
        risk_adjusted=risk_adjusted,
        backtest=backtest,
        analytics=analytics,
        reviewer_reports=reviewer_reports,
    )


def draft_portfolio_construct(
    *,
    context: PortfolioRiskScenarioContext,
    provenance: AgentProvenance,
) -> PortfolioRiskAgentDraft:
    payload = PortfolioConstructDraftPayload(
        context=context,
        requested_construction_spec_version_id=context.construction_spec_version_id,
        requested_cost_policy_id=context.cost_policy_id,
        evidence_refs=(context.construction_spec_version_id, context.cost_policy_id, context.portfolio_intent_id),
    )
    return _draft(kind=PortfolioRiskDraftKind.PORTFOLIO_CONSTRUCT, payload=payload, provenance=provenance)


def draft_risk_apply(
    *,
    context: PortfolioRiskScenarioContext,
    source_target: TargetWeightVector,
    provenance: AgentProvenance,
) -> PortfolioRiskAgentDraft:
    if not isinstance(source_target, TargetWeightVector):
        raise TypeError("source_target must be the canonical TargetWeightVector object")
    source_target.assert_canonical()
    _binding(context.source_target_weight_vector_id == source_target.target_weight_vector_id, "context does not bind the exact source TargetWeightVector")
    payload = RiskApplyDraftPayload(
        context=context,
        source_target_weight_vector_id=source_target.target_weight_vector_id,
        source_target_weight_vector_content_sha256=source_target.content_sha256,
        requested_risk_policy_set_version_id=context.risk_policy_set_version_id,
        risk_backend=context.risk_backend,
        risk_code_version=context.risk_code_version,
        risk_runtime_profile_id=context.risk_runtime_profile_id,
        evidence_refs=(source_target.target_weight_vector_id, context.risk_policy_set_version_id),
    )
    return _draft(kind=PortfolioRiskDraftKind.RISK_APPLY, payload=payload, provenance=provenance)


def draft_backtest_run(
    *,
    context: PortfolioRiskScenarioContext,
    risk_adjusted: RiskAdjustedWeightVector,
    initial_cash: str,
    engine_version: str,
    provenance: AgentProvenance,
) -> PortfolioRiskAgentDraft:
    if not isinstance(risk_adjusted, RiskAdjustedWeightVector):
        raise TypeError("risk_adjusted must be the canonical RiskAdjustedWeightVector object")
    risk_adjusted.assert_canonical()
    _binding(context.risk_adjusted_weight_vector_id == risk_adjusted.risk_adjusted_weight_vector_id, "context does not bind the exact RiskAdjustedWeightVector")
    payload = BacktestRunDraftPayload(
        context=context,
        risk_adjusted_weight_vector_id=risk_adjusted.risk_adjusted_weight_vector_id,
        risk_adjusted_weight_vector_content_sha256=risk_adjusted.content_sha256,
        effective_at=risk_adjusted.source_target.rebalance_time,
        initial_cash=initial_cash,
        requested_cost_policy_id=context.cost_policy_id,
        requested_rule_profile_id=context.rule_profile_id,
        requested_execution_timing_profile_id=context.execution_timing_profile_id,
        engine_version=engine_version,
        evidence_refs=(risk_adjusted.risk_adjusted_weight_vector_id, context.cost_policy_id),
    )
    return _draft(kind=PortfolioRiskDraftKind.BACKTEST_RUN, payload=payload, provenance=provenance)


def draft_result_compare(
    *,
    left: ResultAnalyticsEvidenceView,
    right: ResultAnalyticsEvidenceView,
    objective_metric: str | None,
    objective_direction: str | None,
    provenance: AgentProvenance,
) -> PortfolioRiskAgentDraft:
    payload = ResultCompareDraftPayload(
        left_analytics_id=left.analytics_id,
        right_analytics_id=right.analytics_id,
        objective_metric=objective_metric,
        objective_direction=objective_direction,
        evidence_refs=(left.analytics_id, right.analytics_id),
    )
    return _draft(kind=PortfolioRiskDraftKind.RESULT_COMPARE, payload=payload, provenance=provenance)


def draft_review_run(
    *,
    target_refs: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    rule_set_id: str,
    provenance: AgentProvenance,
) -> PortfolioRiskAgentDraft:
    payload = ReviewRunDraftPayload(
        target_refs=tuple(target_refs),
        evidence_refs=tuple(evidence_refs),
        requested_rule_set_id=rule_set_id,
    )
    return _draft(kind=PortfolioRiskDraftKind.REVIEW_RUN, payload=payload, provenance=provenance)


def build_portfolio_risk_proposal(
    *,
    research_goal: str,
    context: PortfolioRiskScenarioContext,
    action_drafts: tuple[PortfolioRiskAgentDraft, ...],
    next_action_proposals: tuple[str, ...] = (),
    agent_rationale: str | None = None,
) -> PortfolioRiskProposal:
    return PortfolioRiskProposal(
        research_goal=research_goal,
        agent_rationale=agent_rationale,
        exact_context=context,
        action_drafts=action_drafts,
        next_action_proposals=tuple(next_action_proposals),
    )


_METRIC_ORDER = (
    "total_return",
    "annualized_return",
    "annualized_volatility",
    "max_drawdown",
    "sharpe",
    "sortino",
)


def _metric_map(view: ResultAnalyticsEvidenceView) -> dict[str, AnalyticsMetricEvidence]:
    result = {metric.name: metric for metric in view.metrics}
    result["turnover"] = view.turnover
    return result


def compare_scenarios(
    left: ScenarioEvidenceBundle,
    right: ScenarioEvidenceBundle,
    *,
    objective_metric: str | None = None,
    objective_direction: str | None = None,
) -> ScenarioComparison:
    if not isinstance(left, ScenarioEvidenceBundle) or not isinstance(right, ScenarioEvidenceBundle):
        raise TypeError("comparison requires exact ScenarioEvidenceBundle objects")
    left_key = dict(left.comparison_context_key)
    right_key = dict(right.comparison_context_key)
    mismatches: tuple[str, ...] = ()
    if left_key != right_key:
        mismatches = tuple(
            sorted(
                name
                for name in left_key
                if left_key[name] != right_key.get(name)
            )
        )
        return ScenarioComparison(
            status=ComparisonStatus.INCOMPARABLE_CONTEXT,
            left_analytics_id=left.analytics.analytics_id if left.analytics is not None else "NOT_AVAILABLE",
            right_analytics_id=right.analytics.analytics_id if right.analytics is not None else "NOT_AVAILABLE",
            context_mismatches=mismatches,
        )
    if left.analytics is None or right.analytics is None:
        return ScenarioComparison(
            status=ComparisonStatus.INCOMPARABLE_CONTEXT,
            left_analytics_id=left.analytics.analytics_id if left.analytics is not None else "NOT_AVAILABLE",
            right_analytics_id=right.analytics.analytics_id if right.analytics is not None else "NOT_AVAILABLE",
            context_mismatches=("analytics",),
        )
    left_metrics = _metric_map(left.analytics)
    right_metrics = _metric_map(right.analytics)
    deltas: list[MetricDelta] = []
    for name in (*_METRIC_ORDER, "turnover"):
        left_metric = left_metrics[name]
        right_metric = right_metrics[name]
        if left_metric.status == "AVAILABLE" and right_metric.status == "AVAILABLE":
            left_value = Decimal(left_metric.value)
            right_value = Decimal(right_metric.value)
            deltas.append(
                MetricDelta(
                    name=name,
                    status="AVAILABLE",
                    left_value=str(left_value),
                    right_value=str(right_value),
                    delta_right_minus_left=str(right_value - left_value),
                )
            )
        else:
            status = "NOT_AVAILABLE" if left_metric.status == "NOT_AVAILABLE" or right_metric.status == "NOT_AVAILABLE" else "INSUFFICIENT_SAMPLE"
            deltas.append(MetricDelta(name=name, status=status))
    ranking: str | None = None
    if objective_metric is not None and objective_direction is not None:
        delta = next((item for item in deltas if item.name == objective_metric), None)
        if delta is not None and delta.status == "AVAILABLE":
            difference = Decimal(delta.delta_right_minus_left)
            if difference == 0:
                ranking = "TIE"
            elif objective_direction == "MAXIMIZE":
                ranking = "RIGHT" if difference > 0 else "LEFT"
            else:
                ranking = "LEFT" if difference > 0 else "RIGHT"
    return ScenarioComparison(
        status=ComparisonStatus.COMPARABLE,
        left_analytics_id=left.analytics.analytics_id,
        right_analytics_id=right.analytics.analytics_id,
        metric_deltas=tuple(deltas),
        objective_metric=objective_metric,
        objective_direction=objective_direction,
        ranking=ranking,
    )


def explain_scenario(
    *,
    bundle: ScenarioEvidenceBundle,
    next_action_proposals: tuple[str, ...] = (),
) -> ScenarioEvidenceExplanation:
    if not isinstance(bundle, ScenarioEvidenceBundle):
        raise TypeError("explanation requires an exact ScenarioEvidenceBundle")
    missing: list[str] = []
    for name, value in (
        ("target", bundle.target),
        ("risk_adjusted", bundle.risk_adjusted),
        ("backtest", bundle.backtest),
        ("analytics", bundle.analytics),
    ):
        if value is None:
            missing.append(name)
    cited: list[str] = [bundle.intent.portfolio_intent_id, bundle.construction_spec_version_id, bundle.risk_policy_set.risk_policy_set_version_id, bundle.cost_policy.policy_id]
    if bundle.target is not None:
        cited.append(bundle.target.target_weight_vector_id)
    if bundle.risk_adjusted is not None:
        cited.append(bundle.risk_adjusted.risk_adjusted_weight_vector_id)
    if bundle.backtest is not None:
        cited.append(bundle.backtest.result_id)
    if bundle.analytics is not None:
        cited.append(bundle.analytics.analytics_id)
    for report in bundle.reviewer_reports:
        cited.append(report.review_report_id)

    constraint_statements: list[str] = []
    weight_change_statements: list[str] = []
    risk_diagnostic_statements: list[str] = []
    if bundle.risk_adjusted is not None:
        if bundle.risk_adjusted.stage_summaries:
            for stage in bundle.risk_adjusted.stage_summaries:
                statement = f"stage {stage.stage_order} {stage.policy_id} {stage.status}: {stage.reason}"
                risk_diagnostic_statements.append(statement)
                if stage.status in ("ADJUSTED", "REJECTED"):
                    constraint_statements.append(statement)
        if bundle.target is not None:
            target_rows = {row.instrument_id: Decimal(row.target_weight) for row in bundle.target.rows}
            adjusted_rows = {row.instrument_id: Decimal(row.target_weight) for row in bundle.risk_adjusted.rows}
            for instrument_id in sorted(set(target_rows) | set(adjusted_rows)):
                before = target_rows.get(instrument_id)
                after = adjusted_rows.get(instrument_id)
                if before != after:
                    weight_change_statements.append(f"{instrument_id}: {before} -> {after}")
            if bundle.target.cash_weight != bundle.risk_adjusted.cash_weight:
                weight_change_statements.append(f"cash: {bundle.target.cash_weight} -> {bundle.risk_adjusted.cash_weight}")
        weight_change_statements.append(f"decision: {bundle.risk_adjusted.decision} ({bundle.risk_adjusted.decision_reason})")

    cost_statements: list[str] = [
        f"CostPolicy {bundle.cost_policy.policy_name} {bundle.cost_policy.policy_id} commission={bundle.cost_policy.commission_rate} stamp_duty_sell={bundle.cost_policy.stamp_duty_sell_rate}",
    ]
    analytics_statements: list[str] = []
    if bundle.analytics is not None:
        for metric in (*bundle.analytics.metrics, bundle.analytics.turnover):
            if metric.status == "AVAILABLE":
                analytics_statements.append(f"{metric.name}: {metric.value}")
            else:
                analytics_statements.append(f"{metric.name}: {metric.status}" + (f" ({metric.reason})" if metric.reason else ""))
        cost_statements.append(f"fills={bundle.analytics.fill_count} total_fees={bundle.analytics.total_fees}")

    reviewer_statements: list[str] = []
    for report in bundle.reviewer_reports:
        for kind, severity, summary in report.findings:
            reviewer_statements.append(f"{report.review_report_id} {kind} {severity}: {summary}")
        if not report.findings:
            reviewer_statements.append(f"{report.review_report_id}: {report.overall_status}, no findings")

    return ScenarioEvidenceExplanation(
        status="EVIDENCE_BOUND" if not missing else "EVIDENCE_MISSING",
        summary=(
            "explanation is bound to the exact cited scenario evidence"
            if not missing
            else "explanation is incomplete; referenced evidence links are missing"
        ),
        constraint_statements=tuple(constraint_statements),
        weight_change_statements=tuple(weight_change_statements),
        risk_diagnostic_statements=tuple(risk_diagnostic_statements),
        cost_statements=tuple(cost_statements),
        analytics_statements=tuple(analytics_statements),
        reviewer_statements=tuple(reviewer_statements),
        missing_evidence=tuple(missing),
        next_action_proposals=tuple(next_action_proposals),
        cited_evidence_refs=tuple(cited),
    )
