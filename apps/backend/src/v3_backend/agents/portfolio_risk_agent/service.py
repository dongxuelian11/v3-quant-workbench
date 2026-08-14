from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal

from v3_backend.agents.contracts import AgentProvenance, PermissionLevel, deterministic_json
from v3_backend.agents.permissions import decide_permission
from v3_backend.domain.backtest_runtime import (
    BacktestRunResult,
    BacktestRunSpec,
    CostPolicyVersion,
)
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
    RuntimeIdentity,
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
    ReviewerTargetEvidence,
    RiskAdjustedEvidenceView,
    RiskApplyDraftPayload,
    RiskPolicyEvidence,
    RiskPolicySetEvidenceView,
    RiskStageSummary,
    ScenarioComparison,
    ScenarioComparisonInvariant,
    ScenarioEvidenceBundle,
    ScenarioEvidenceExplanation,
    TargetWeightEvidenceRow,
    TargetWeightEvidenceView,
    comparison_invariant_content,
    comparison_invariant_identity,
)
from .trusted import ResolvedScenarioEvidenceBundle, ScenarioResolutionRequest


_VALUATION_MODE = "RAW_EOD_CLOSE_FAIL_CLOSED"


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
        _binding(decision_report.risk_policy_set_version_id == adjusted.risk_application.risk_policy_set.source_id, "risk decision report does not bind the exact RiskPolicySetVersion")
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


def read_backtest_result(
    result: BacktestRunResult,
    spec: BacktestRunSpec | None = None,
    bound_risk_adjusted_weight_vector_id: str | None = None,
) -> BacktestResultEvidenceView:
    if not isinstance(result, BacktestRunResult):
        raise TypeError("result must be the canonical BacktestRunResult object")
    if not result.nav:
        raise PortfolioRiskAgentBindingError("backtest result requires at least one NAV point")
    if spec is not None:
        if not isinstance(spec, BacktestRunSpec):
            raise TypeError("spec must be the canonical BacktestRunSpec object")
        _binding(spec.run_spec_id == result.run_spec_id, "backtest spec does not bind the exact BacktestRunResult")
    diagnostic_counts = Counter(diagnostic.code.value for diagnostic in result.diagnostics)
    truth, _ = _truth_wire(result.truth_admission)
    final = result.nav[-1]
    initial_cash = ""
    for entry in result.cash_ledger:
        if entry.kind.value == "INITIAL_CASH":
            initial_cash = entry.amount
            break
    scheduled_ids: tuple[str, ...] = ()
    if spec is not None:
        scheduled_ids = tuple(
            item.vector.risk_adjusted_weight_vector_id for item in spec.schedule
        )
    return BacktestResultEvidenceView(
        result_id=result.result_id,
        content_sha256=result.content_sha256,
        run_spec_id=result.run_spec_id,
        run_spec_content_sha256=spec.content_sha256 if spec is not None else None,
        engine_version=spec.engine_version if spec is not None else None,
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
        scheduled_risk_adjusted_vector_ids=scheduled_ids,
        bound_risk_adjusted_weight_vector_id=bound_risk_adjusted_weight_vector_id,
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
        target_refs=tuple(
            ReviewerTargetEvidence(
                object_kind=ref.object_kind,
                object_id=ref.object_id,
                content_sha256=ref.content_sha256,
            )
            for ref in report.target_refs
        ),
        overall_status=report.overall_status.value,
        checked_rules=report.coverage.checked_rules,
        findings=tuple((finding.kind.value, finding.severity.value, finding.summary) for finding in report.findings),
        truth_ceiling=ceiling,
    )


def _derive_comparison_invariant(
    *,
    intent: PortfolioIntent,
    source: PortfolioIntentSource,
    binding: StrategyEvaluationBindingVersion,
    base_currency: str,
    backtest_spec: BacktestRunSpec,
    analytics: BacktestResultAnalytics,
) -> ScenarioComparisonInvariant:
    """Resolver-owned derivation of the exact comparison invariant (R-D).

    Derived only from canonical owner objects: the exact BacktestRunSpec and
    its pinned canonical inputs, the PortfolioIntent identity/content, the
    universe, knowledge cutoff/as-of context, base currency, analytics policy
    and benchmark context.  Treatment dimensions (construction spec, risk
    policy set, cost policy) are intentionally not part of the invariant.
    """

    sessions = backtest_spec.sessions
    dimensions = {
        "portfolio_intent_id": intent.portfolio_intent_id,
        "portfolio_intent_content_sha256": source.portfolio_intent_content_sha256,
        "universe_version_id": source.universe_version_id,
        "universe_membership_artifact_id": source.membership_artifact_id,
        "knowledge_cutoff": binding.knowledge_cutoff,
        "snapshot_id": binding.snapshot.snapshot_id,
        "calendar_version_id": binding.calendar.calendar_version_id,
        "base_currency": base_currency,
        "analytics_policy_id": analytics.analytics_policy_id,
        "analytics_policy_content_sha256": analytics.analytics_policy_content_sha256,
        "benchmark_series_id": analytics.benchmark_series_id,
        "initial_cash": backtest_spec.initial_cash,
        "initial_holdings": tuple(
            (item.instrument_id, item.quantity, item.acquired_on.isoformat())
            for item in backtest_spec.initial_holdings
        ),
        "instruments": tuple(
            (item.instrument_id, item.board.value) for item in backtest_spec.instruments
        ),
        "session_dates": tuple(session.session_date.isoformat() for session in sessions),
        "session_market_state_inputs": deterministic_json(
            [
                [session.session_date.isoformat(), [state.to_wire() for state in session.states]]
                for session in sessions
            ]
        ),
        "corporate_action_events": deterministic_json(
            [
                [session.session_date.isoformat(), [action.to_wire() for action in session.corporate_actions]]
                for session in sessions
            ]
        ),
        "exact_input_references": deterministic_json(
            [reference.to_wire() for reference in backtest_spec.exact_references]
        ),
        "rule_profile_id": backtest_spec.rule_profile.profile_id,
        "rule_profile_content_sha256": backtest_spec.rule_profile.content_sha256,
        "execution_timing_profile_id": backtest_spec.execution_timing_profile.profile_id,
        "execution_timing_profile_content_sha256": backtest_spec.execution_timing_profile.content_sha256,
        "execution_convention": backtest_spec.execution_timing_profile.execution_convention,
        "runtime_identity": deterministic_json(backtest_spec.runtime_identity.to_wire()),
        "engine_version": backtest_spec.engine_version,
        "valuation_mode": _VALUATION_MODE,
    }
    return ScenarioComparisonInvariant(
        invariant_id=comparison_invariant_identity(**dimensions),
        **dimensions,
    )


def resolve_scenario_evidence(
    *,
    intent: PortfolioIntent,
    source: PortfolioIntentSource,
    binding: StrategyEvaluationBindingVersion,
    construction_spec: UnresolvedExactReference,
    risk_policy_set: RiskPolicySetVersion,
    cost_policy: CostPolicyVersion,
    base_currency: str,
    target: TargetWeightVector | None = None,
    risk_adjusted: RiskAdjustedWeightVector | None = None,
    decision_report: RiskDecisionReport | None = None,
    backtest_result: BacktestRunResult | None = None,
    backtest_spec: BacktestRunSpec | None = None,
    analytics: BacktestResultAnalytics | None = None,
    reviewer_reports: tuple[ResearchReviewReport, ...] = (),
) -> ResolvedScenarioEvidenceBundle:
    """System-owned scenario evidence resolver over canonical owner objects.

    Only actual canonical owner objects are accepted; arbitrary prebuilt
    evidence projections are never proof.  The returned
    `ResolvedScenarioEvidenceBundle` is an intermediate value: trusted entry
    points perform this resolution at the trusted consumer boundary and never
    accept caller-supplied resolved bundles as proof of provenance.  Links
    that the current owners cannot prove are listed in `binding_gaps` and
    never become EVIDENCE_BOUND; such bundles also carry no comparison
    invariant.
    """

    if not isinstance(intent, PortfolioIntent):
        raise TypeError("intent must be the canonical PortfolioIntent object")
    if not isinstance(source, PortfolioIntentSource):
        raise TypeError("source must be the canonical PortfolioIntentSource object")
    if not isinstance(binding, StrategyEvaluationBindingVersion):
        raise TypeError("binding must be the canonical StrategyEvaluationBindingVersion object")
    _binding(source.portfolio_intent_id == intent.portfolio_intent_id, "source does not bind the exact PortfolioIntent")
    if not isinstance(construction_spec, UnresolvedExactReference):
        raise TypeError("construction_spec must be the exact UnresolvedExactReference")
    _binding(construction_spec.reference_kind is ReferenceKind.CONSTRUCTION_SPEC, "construction spec reference kind must be CONSTRUCTION_SPEC")
    if not isinstance(risk_policy_set, RiskPolicySetVersion):
        raise TypeError("risk_policy_set must be the canonical RiskPolicySetVersion object")
    risk_policy_set.assert_canonical()
    if not isinstance(cost_policy, CostPolicyVersion):
        raise TypeError("cost_policy must be the canonical CostPolicyVersion object")
    cost_policy.assert_canonical()

    intent_view = read_portfolio_intent(intent=intent, source=source, binding=binding, base_currency=base_currency)
    policy_view = read_risk_policy_set(risk_policy_set)
    cost_view = read_cost_policy(cost_policy)
    target_view: TargetWeightEvidenceView | None = None
    adjusted_view: RiskAdjustedEvidenceView | None = None
    result_view: BacktestResultEvidenceView | None = None
    analytics_view: ResultAnalyticsEvidenceView | None = None
    reviewer_views: tuple[ReviewerEvidenceView, ...] = ()
    gaps: list[str] = []

    if target is not None:
        if not isinstance(target, TargetWeightVector):
            raise TypeError("target must be the canonical TargetWeightVector object")
        target.assert_canonical()
        _binding(target.source.portfolio_intent_id == intent.portfolio_intent_id, "target does not bind the exact PortfolioIntent")
        _binding(target.construction_spec.source_id == construction_spec.source_id, "target does not bind the exact construction spec")
        _binding(target.construction_spec.content_sha256 == construction_spec.content_sha256, "target does not bind the exact construction spec content hash")
        target_view = read_target_weight_evidence(target)

    if risk_adjusted is not None:
        if not isinstance(risk_adjusted, RiskAdjustedWeightVector):
            raise TypeError("risk_adjusted must be the canonical RiskAdjustedWeightVector object")
        risk_adjusted.assert_canonical()
        _binding(target is not None, "risk-adjusted evidence requires the exact target vector")
        _binding(risk_adjusted.source_target.target_weight_vector_id == target.target_weight_vector_id, "risk-adjusted does not bind the exact target vector")
        _binding(risk_adjusted.source_target.content_sha256 == target.content_sha256, "risk-adjusted does not bind the exact target content hash")
        _binding(risk_adjusted.risk_application.risk_policy_set.source_id == risk_policy_set.risk_policy_set_version_id, "risk-adjusted does not bind the exact RiskPolicySetVersion")
        _binding(risk_adjusted.risk_application.risk_policy_set.content_sha256 == risk_policy_set.content_sha256, "risk-adjusted does not bind the exact policy set content hash")
        adjusted_view = read_risk_adjusted_evidence(risk_adjusted, decision_report)

    if decision_report is not None:
        if not isinstance(decision_report, RiskDecisionReport):
            raise TypeError("decision_report must be the canonical RiskDecisionReport object")
        _binding(decision_report.risk_policy_set_version_id == risk_policy_set.risk_policy_set_version_id, "risk decision report does not bind the exact scenario RiskPolicySetVersion")
        _binding(decision_report.risk_policy_set_content_sha256 == risk_policy_set.content_sha256, "risk decision report does not bind the exact scenario RiskPolicySetVersion content hash")

    if backtest_result is not None:
        if not isinstance(backtest_result, BacktestRunResult):
            raise TypeError("backtest_result must be the canonical BacktestRunResult object")
        _binding(risk_adjusted is not None, "backtest evidence requires the exact risk-adjusted vector")
        if backtest_spec is None:
            gaps.append("backtest_to_risk_adjusted")
        else:
            if not isinstance(backtest_spec, BacktestRunSpec):
                raise TypeError("backtest_spec must be the canonical BacktestRunSpec object")
            _binding(backtest_spec.run_spec_id == backtest_result.run_spec_id, "backtest spec does not bind the exact BacktestRunResult")
            _binding(backtest_spec.cost_policy.policy_id == cost_policy.policy_id, "backtest spec CostPolicy does not bind the exact scenario CostPolicy")
            _binding(backtest_spec.cost_policy.content_sha256 == cost_policy.content_sha256, "backtest spec CostPolicy content hash does not bind the exact scenario CostPolicy")
            scheduled_ids = tuple(item.vector.risk_adjusted_weight_vector_id for item in backtest_spec.schedule)
            _binding(risk_adjusted.risk_adjusted_weight_vector_id in scheduled_ids, "backtest spec schedule does not include the exact RiskAdjustedWeightVector")
        result_view = read_backtest_result(
            backtest_result,
            spec=backtest_spec,
            bound_risk_adjusted_weight_vector_id=risk_adjusted.risk_adjusted_weight_vector_id if backtest_spec is not None else None,
        )

    if analytics is not None:
        if not isinstance(analytics, BacktestResultAnalytics):
            raise TypeError("analytics must be the canonical BacktestResultAnalytics object")
        _binding(backtest_result is not None, "analytics evidence requires the exact backtest result")
        _binding(analytics.source_result_id == backtest_result.result_id, "analytics does not bind the exact BacktestRunResult")
        _binding(analytics.source_result_content_sha256 == backtest_result.content_sha256, "analytics does not bind the exact result content hash")
        analytics_view = read_result_analytics(analytics)

    reviewer_views = ()
    for report in reviewer_reports:
        if not isinstance(report, ResearchReviewReport):
            raise TypeError("reviewer_reports must contain canonical ResearchReviewReport objects")
        view = read_reviewer_report(report)
        if backtest_result is not None:
            matches = any(
                ref.object_id == backtest_result.result_id and ref.content_sha256 == backtest_result.content_sha256
                for ref in view.target_refs
            )
            _binding(matches, "reviewer report does not target the exact scenario BacktestRunResult")
        reviewer_views = (*reviewer_views, view)

    payload = ScenarioEvidenceBundle(
        intent=intent_view,
        construction_spec_version_id=construction_spec.source_id,
        construction_spec_content_sha256=construction_spec.content_sha256,
        risk_policy_set=policy_view,
        cost_policy=cost_view,
        target=target_view,
        risk_adjusted=adjusted_view,
        backtest=result_view,
        analytics=analytics_view,
        reviewer_reports=reviewer_views,
        binding_gaps=tuple(gaps),
    )

    comparison_invariant: ScenarioComparisonInvariant | None = None
    if not gaps and backtest_spec is not None and backtest_result is not None and analytics is not None:
        comparison_invariant = _derive_comparison_invariant(
            intent=intent,
            source=source,
            binding=binding,
            base_currency=base_currency,
            backtest_spec=backtest_spec,
            analytics=analytics,
        )

    return ResolvedScenarioEvidenceBundle(payload, comparison_invariant)


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
    policy_set: RiskPolicySetVersion,
    runtime_identity: RuntimeIdentity,
    provenance: AgentProvenance,
) -> PortfolioRiskAgentDraft:
    if not isinstance(source_target, TargetWeightVector):
        raise TypeError("source_target must be the canonical TargetWeightVector object")
    source_target.assert_canonical()
    if not isinstance(policy_set, RiskPolicySetVersion):
        raise TypeError("policy_set must be the canonical RiskPolicySetVersion object")
    policy_set.assert_canonical()
    if not isinstance(runtime_identity, RuntimeIdentity):
        raise TypeError("runtime_identity must be the exact W0 RuntimeIdentity")
    _binding(context.source_target_weight_vector_id == source_target.target_weight_vector_id, "context does not bind the exact source TargetWeightVector")
    _binding(context.risk_policy_set_version_id == policy_set.risk_policy_set_version_id, "context does not bind the exact RiskPolicySetVersion")
    _binding(context.risk_policy_set_content_sha256 == policy_set.content_sha256, "context does not bind the exact policy set content hash")
    payload = RiskApplyDraftPayload(
        context=context,
        source_target_weight_vector_id=source_target.target_weight_vector_id,
        source_target_weight_vector_content_sha256=source_target.content_sha256,
        requested_risk_policy_set_version_id=policy_set.risk_policy_set_version_id,
        requested_risk_policy_set_content_sha256=policy_set.content_sha256,
        risk_backend=context.risk_backend,
        risk_code_version=context.risk_code_version,
        risk_runtime_profile_id=context.risk_runtime_profile_id,
        runtime_code_version=runtime_identity.code_version,
        runtime_profile_id=runtime_identity.runtime_profile_id,
        runtime_environment_fingerprint=runtime_identity.environment_fingerprint,
        evidence_refs=(source_target.target_weight_vector_id, policy_set.risk_policy_set_version_id),
    )
    return _draft(kind=PortfolioRiskDraftKind.RISK_APPLY, payload=payload, provenance=provenance)


def draft_backtest_run(
    *,
    context: PortfolioRiskScenarioContext,
    risk_adjusted: RiskAdjustedWeightVector,
    spec: BacktestRunSpec,
    provenance: AgentProvenance,
) -> PortfolioRiskAgentDraft:
    if not isinstance(risk_adjusted, RiskAdjustedWeightVector):
        raise TypeError("risk_adjusted must be the canonical RiskAdjustedWeightVector object")
    risk_adjusted.assert_canonical()
    if not isinstance(spec, BacktestRunSpec):
        raise TypeError("spec must be the canonical BacktestRunSpec object")
    _binding(context.risk_adjusted_weight_vector_id == risk_adjusted.risk_adjusted_weight_vector_id, "context does not bind the exact RiskAdjustedWeightVector")
    _binding(context.cost_policy_id == spec.cost_policy.policy_id, "context CostPolicy does not bind the exact BacktestRunSpec")
    _binding(context.rule_profile_id == spec.rule_profile.profile_id, "context rule profile does not bind the exact BacktestRunSpec")
    _binding(context.execution_timing_profile_id == spec.execution_timing_profile.profile_id, "context timing profile does not bind the exact BacktestRunSpec")
    scheduled_ids = tuple(item.vector.risk_adjusted_weight_vector_id for item in spec.schedule)
    _binding(risk_adjusted.risk_adjusted_weight_vector_id in scheduled_ids, "BacktestRunSpec schedule does not include the exact RiskAdjustedWeightVector")
    payload = BacktestRunDraftPayload(
        context=context,
        risk_adjusted_weight_vector_id=risk_adjusted.risk_adjusted_weight_vector_id,
        risk_adjusted_weight_vector_content_sha256=risk_adjusted.content_sha256,
        effective_at=risk_adjusted.source_target.rebalance_time,
        initial_cash=spec.initial_cash,
        requested_cost_policy_id=spec.cost_policy.policy_id,
        requested_rule_profile_id=spec.rule_profile.profile_id,
        requested_execution_timing_profile_id=spec.execution_timing_profile.profile_id,
        engine_version=spec.engine_version,
        backtest_run_spec_id=spec.run_spec_id,
        backtest_run_spec_content_sha256=spec.content_sha256,
        evidence_refs=(risk_adjusted.risk_adjusted_weight_vector_id, spec.run_spec_id),
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


_INVARIANT_DIMENSION_NAMES = (
    "portfolio_intent_id",
    "portfolio_intent_content_sha256",
    "universe_version_id",
    "universe_membership_artifact_id",
    "knowledge_cutoff",
    "snapshot_id",
    "calendar_version_id",
    "base_currency",
    "analytics_policy_id",
    "analytics_policy_content_sha256",
    "benchmark_series_id",
    "initial_cash",
    "initial_holdings",
    "instruments",
    "session_dates",
    "session_market_state_inputs",
    "corporate_action_events",
    "exact_input_references",
    "rule_profile_id",
    "rule_profile_content_sha256",
    "execution_timing_profile_id",
    "execution_timing_profile_content_sha256",
    "execution_convention",
    "runtime_identity",
    "engine_version",
    "valuation_mode",
)


def _invariant_mismatch_names(
    left: ScenarioComparisonInvariant,
    right: ScenarioComparisonInvariant,
) -> tuple[str, ...]:
    mismatches = tuple(
        name
        for name in _INVARIANT_DIMENSION_NAMES
        if getattr(left, name) != getattr(right, name)
    )
    if not mismatches and left.invariant_id != right.invariant_id:
        mismatches = ("comparison_invariant",)
    return mismatches


def _compare_resolved_scenarios(
    left: ResolvedScenarioEvidenceBundle,
    right: ResolvedScenarioEvidenceBundle,
    *,
    objective_metric: str | None = None,
    objective_direction: str | None = None,
) -> ScenarioComparison:
    """Internal deterministic comparison over resolver-produced resolved values.

    Internal helper; trusted entry points resolve canonical requests through
    `resolve_scenario_evidence` and pass the results here.  Order of
    authority: resolved evidence -> exact comparison invariant -> invariant
    equality -> disclosed treatment differences -> metrics/ranking.  Metrics
    never override invariant mismatch, and evidence-binding gaps always fail
    closed.
    """

    if type(left) is not ResolvedScenarioEvidenceBundle or type(right) is not ResolvedScenarioEvidenceBundle:
        raise TypeError("comparison requires internally resolved scenario evidence")
    left_payload = left.payload
    right_payload = right.payload

    left_analytics_id = left_payload.analytics.analytics_id if left_payload.analytics is not None else "NOT_AVAILABLE"
    right_analytics_id = right_payload.analytics.analytics_id if right_payload.analytics is not None else "NOT_AVAILABLE"

    gaps = tuple(sorted(set(left_payload.binding_gaps) | set(right_payload.binding_gaps)))
    if gaps:
        return ScenarioComparison(
            status=ComparisonStatus.INCOMPARABLE_CONTEXT,
            left_analytics_id=left_analytics_id,
            right_analytics_id=right_analytics_id,
            context_mismatches=("EVIDENCE_BINDING_UNAVAILABLE", *gaps),
        )
    if left_payload.analytics is None or right_payload.analytics is None:
        return ScenarioComparison(
            status=ComparisonStatus.INCOMPARABLE_CONTEXT,
            left_analytics_id=left_analytics_id,
            right_analytics_id=right_analytics_id,
            context_mismatches=("analytics",),
        )
    if left.comparison_invariant is None or right.comparison_invariant is None:
        return ScenarioComparison(
            status=ComparisonStatus.INCOMPARABLE_CONTEXT,
            left_analytics_id=left_analytics_id,
            right_analytics_id=right_analytics_id,
            context_mismatches=("comparison_invariant",),
        )
    left_invariant = left.comparison_invariant
    right_invariant = right.comparison_invariant
    if left_invariant.invariant_id != right_invariant.invariant_id:
        return ScenarioComparison(
            status=ComparisonStatus.INCOMPARABLE_CONTEXT,
            left_analytics_id=left_analytics_id,
            right_analytics_id=right_analytics_id,
            context_mismatches=_invariant_mismatch_names(left_invariant, right_invariant),
        )
    treatment_left = dict(left_payload.treatment_context_key)
    treatment_right = dict(right_payload.treatment_context_key)
    scenario_differences = tuple(
        sorted(name for name in treatment_left if treatment_left[name] != treatment_right.get(name))
    )
    left_metrics = _metric_map(left_payload.analytics)
    right_metrics = _metric_map(right_payload.analytics)
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
        left_analytics_id=left_payload.analytics.analytics_id,
        right_analytics_id=right_payload.analytics.analytics_id,
        scenario_differences=scenario_differences,
        metric_deltas=tuple(deltas),
        objective_metric=objective_metric,
        objective_direction=objective_direction,
        ranking=ranking,
    )


def compare_scenarios(
    *,
    left: ScenarioResolutionRequest,
    right: ScenarioResolutionRequest,
    objective_metric: str | None = None,
    objective_direction: str | None = None,
) -> ScenarioComparison:
    """Trusted scenario comparison over canonical resolution requests.

    Canonical resolution happens at this trusted consumer boundary: both
    requests are resolved through `resolve_scenario_evidence` before any
    comparison.  Caller-supplied resolved bundles are not accepted and there
    is no provenance shortcut (no token, no flag, no hash check).
    """

    if type(left) is not ScenarioResolutionRequest or type(right) is not ScenarioResolutionRequest:
        raise TypeError(
            "scenario comparison requires exact ScenarioResolutionRequest inputs "
            "(canonical owner objects); caller-supplied resolved evidence is not authority"
        )
    return _compare_resolved_scenarios(
        resolve_scenario_evidence(**left.to_kwargs()),
        resolve_scenario_evidence(**right.to_kwargs()),
        objective_metric=objective_metric,
        objective_direction=objective_direction,
    )


def _explain_resolved_scenario(
    *,
    bundle: ResolvedScenarioEvidenceBundle,
    next_action_proposals: tuple[str, ...] = (),
) -> ScenarioEvidenceExplanation:
    if type(bundle) is not ResolvedScenarioEvidenceBundle:
        raise TypeError("explanation requires internally resolved scenario evidence")
    payload = bundle.payload
    missing: list[str] = []
    for name, value in (
        ("target", payload.target),
        ("risk_adjusted", payload.risk_adjusted),
        ("backtest", payload.backtest),
        ("analytics", payload.analytics),
    ):
        if value is None:
            missing.append(name)
    cited: list[str] = [payload.intent.portfolio_intent_id, payload.construction_spec_version_id, payload.risk_policy_set.risk_policy_set_version_id, payload.cost_policy.policy_id]
    if payload.target is not None:
        cited.append(payload.target.target_weight_vector_id)
    if payload.risk_adjusted is not None:
        cited.append(payload.risk_adjusted.risk_adjusted_weight_vector_id)
    if payload.backtest is not None:
        cited.append(payload.backtest.result_id)
    if payload.analytics is not None:
        cited.append(payload.analytics.analytics_id)
    for report in payload.reviewer_reports:
        cited.append(report.review_report_id)

    if payload.binding_gaps:
        status = "EVIDENCE_BINDING_UNAVAILABLE"
    elif missing:
        status = "EVIDENCE_MISSING"
    else:
        status = "EVIDENCE_BOUND"

    constraint_statements: list[str] = []
    weight_change_statements: list[str] = []
    risk_diagnostic_statements: list[str] = []
    if payload.risk_adjusted is not None:
        if payload.risk_adjusted.stage_summaries:
            for stage in payload.risk_adjusted.stage_summaries:
                statement = f"stage {stage.stage_order} {stage.policy_id} {stage.status}: {stage.reason}"
                risk_diagnostic_statements.append(statement)
                if stage.status in ("ADJUSTED", "REJECTED"):
                    constraint_statements.append(statement)
        if payload.target is not None:
            target_rows = {row.instrument_id: Decimal(row.target_weight) for row in payload.target.rows}
            adjusted_rows = {row.instrument_id: Decimal(row.target_weight) for row in payload.risk_adjusted.rows}
            for instrument_id in sorted(set(target_rows) | set(adjusted_rows)):
                before = target_rows.get(instrument_id)
                after = adjusted_rows.get(instrument_id)
                if before != after:
                    weight_change_statements.append(f"{instrument_id}: {before} -> {after}")
            if payload.target.cash_weight != payload.risk_adjusted.cash_weight:
                weight_change_statements.append(f"cash: {payload.target.cash_weight} -> {payload.risk_adjusted.cash_weight}")
        weight_change_statements.append(f"decision: {payload.risk_adjusted.decision} ({payload.risk_adjusted.decision_reason})")

    cost_statements: list[str] = [
        f"CostPolicy {payload.cost_policy.policy_name} {payload.cost_policy.policy_id} commission={payload.cost_policy.commission_rate} stamp_duty_sell={payload.cost_policy.stamp_duty_sell_rate}",
    ]
    analytics_statements: list[str] = []
    if payload.analytics is not None:
        for metric in (*payload.analytics.metrics, payload.analytics.turnover):
            if metric.status == "AVAILABLE":
                analytics_statements.append(f"{metric.name}: {metric.value}")
            else:
                analytics_statements.append(f"{metric.name}: {metric.status}" + (f" ({metric.reason})" if metric.reason else ""))
        cost_statements.append(f"fills={payload.analytics.fill_count} total_fees={payload.analytics.total_fees}")

    reviewer_statements: list[str] = []
    for report in payload.reviewer_reports:
        for kind, severity, summary in report.findings:
            reviewer_statements.append(f"{report.review_report_id} {kind} {severity}: {summary}")
        if not report.findings:
            reviewer_statements.append(f"{report.review_report_id}: {report.overall_status}, no findings")

    return ScenarioEvidenceExplanation(
        status=status,
        summary=(
            "explanation is bound to the exact cited scenario evidence"
            if status == "EVIDENCE_BOUND"
            else (
                "explanation is incomplete; canonical owner links could not be proven"
                if status == "EVIDENCE_BINDING_UNAVAILABLE"
                else "explanation is incomplete; referenced evidence links are missing"
            )
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


def explain_scenario(
    *,
    request: ScenarioResolutionRequest,
    next_action_proposals: tuple[str, ...] = (),
) -> ScenarioEvidenceExplanation:
    """Trusted scenario explanation over a canonical resolution request.

    Canonical resolution happens at this trusted consumer boundary before
    any explanation is produced.  Caller-supplied resolved bundles are not
    accepted; there is no provenance shortcut.
    """

    if type(request) is not ScenarioResolutionRequest:
        raise TypeError(
            "scenario explanation requires an exact ScenarioResolutionRequest input "
            "(canonical owner objects); caller-supplied resolved evidence is not authority"
        )
    return _explain_resolved_scenario(
        bundle=resolve_scenario_evidence(**request.to_kwargs()),
        next_action_proposals=next_action_proposals,
    )
