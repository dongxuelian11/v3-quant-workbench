from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from track_f_strategy_runtime.helpers import build_runtime_fixture, rebuild_binding
from v3_backend.agents.contracts import AgentKind, AgentProvenance, PermissionLevel
from v3_backend.agents.permissions import decide_permission
from v3_backend.agents.portfolio_risk_agent import (
    ComparisonStatus,
    PortfolioRiskAgentBindingError,
    PortfolioRiskAgentToolError,
    PortfolioRiskAgentWorker,
    PortfolioRiskApplicationError,
    PortfolioRiskDraftKind,
    PortfolioRiskReadTools,
    ResolvedScenarioEvidenceBundle,
    ScenarioComparisonInvariant,
    ScenarioEvidenceBundle,
    USER_EXECUTION_AUTHORITY_NOT_AVAILABLE,
    UserConfirmation,
    UserExecutionAuthorityNotAvailable,
    apply_confirmed_backtest_run,
    apply_confirmed_portfolio_construct,
    apply_confirmed_risk_apply,
    build_portfolio_risk_proposal,
    build_scenario_context,
    compare_scenarios,
    draft_backtest_run,
    draft_portfolio_construct,
    draft_result_compare,
    draft_review_run,
    draft_risk_apply,
    explain_scenario,
    read_backtest_result,
    read_cost_policy,
    read_portfolio_intent,
    read_result_analytics,
    read_reviewer_report,
    read_risk_adjusted_evidence,
    read_risk_policy_set,
    read_target_weight_evidence,
    resolve_scenario_evidence,
    verify_backtest_binding,
    verify_portfolio_construct_binding,
    verify_risk_apply_binding,
)
from v3_backend.agents.portfolio_risk_agent.contracts import comparison_invariant_identity
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
    ValidationState,
)
from v3_backend.domain.backtest_runtime import (
    AshareTradingRuleProfileVersion,
    BacktestRunSpec,
    Board,
    BoardTradingRule,
    CostPolicyVersion,
    DailyMarketState,
    DeterministicAshareBacktestEngine,
    ExactInputReference,
    ExecutionTimingProfileVersion,
    InitialHolding,
    InstrumentDefinition,
    MarketCostRule,
    MarketSession,
    ScheduledWeights,
    Side,
    cn_a_share_2026_07_06_execution_timing_profile,
    cn_a_share_2026_07_06_rule_profile,
)
from v3_backend.domain.portfolio_construction import (
    ConstructionMethod,
    DeterministicPortfolioConstruction,
    PortfolioConstructionSpecVersion,
)
from v3_backend.domain.result_analytics import (
    BenchmarkObservation,
    BenchmarkSeriesVersion,
    DeterministicResultAnalyticsEngine,
    ResultAnalyticsPolicyVersion,
    SourceResultBinding,
)
from v3_backend.domain.reviewer_integration import (
    ResearchReviewScope,
    ReviewEvidenceRecord,
    ReviewEvidenceRef,
    review_research_scope,
)
from v3_backend.domain.risk_runtime import (
    ExternalSolverAuthorityError,
    RiskPolicyDefinition,
    RiskPolicySetVersion,
    RiskStateInput,
    apply_risk,
)
from v3_backend.domain.strategies import (
    DeterministicStrategyEvaluator,
    ExactUniverseReference,
)
from v3_backend.domain.weights import (
    PortfolioIntentSource,
    ReferenceKind,
    RiskAdjustedWeightVector,
    RuntimeIdentity,
    TargetWeightRow,
    TargetWeightVector,
    UnresolvedExactReference,
)

CN = ZoneInfo("Asia/Shanghai")
DAY1 = date(2026, 7, 7)
DAY2 = date(2026, 7, 8)
SESSION = "research-session-round5-r-001"


def sha(character: str) -> str:
    return character * 64


def provenance(task: str = "round5-r/1") -> AgentProvenance:
    return AgentProvenance(
        agent_kind=AgentKind.RESEARCH,
        sdk_version="2.27.0",
        model_name="deterministic-test-model",
        provider_name="test-provider",
        prompt_version=task,
        instruction_version="round5-r/1.1",
        input_sha256="b" * 64,
    )


class PortfolioRiskAgentFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_runtime_fixture()
        self.evaluation = DeterministicStrategyEvaluator().evaluate(
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            inputs=(self.fixture.runtime_input,),
        )
        assert self.evaluation.portfolio_intent is not None
        self.intent = self.evaluation.portfolio_intent
        self.source = PortfolioIntentSource.create(
            intent=self.intent,
            definition=self.fixture.definition,
            binding=self.fixture.binding,
        )
        self.runtime_identity = RuntimeIdentity(
            code_version="git:round5-r-test",
            runtime_profile_id="v3.portfolio-risk-agent/1.0.0",
            environment_fingerprint="cpython-3.14.5-linux-x64",
        )
        self.as_of = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
        self.decision_time = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
        self.rebalance_time = datetime(2026, 1, 6, 1, 30, tzinfo=timezone.utc)
        self.valid_until = datetime(2026, 1, 6, 7, 0, tzinfo=timezone.utc)
        self.construction_spec = PortfolioConstructionSpecVersion.create(
            method=ConstructionMethod.EQUAL_WEIGHT_SELECTED,
            method_version="1.0.0",
            target_cash_weight="0.1",
            max_instrument_weight="1",
            runtime_identity=self.runtime_identity,
        )
        self.construction = DeterministicPortfolioConstruction().construct(
            intent=self.intent,
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec,
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.as_of,
            decision_time=self.decision_time,
            rebalance_time=self.rebalance_time,
            valid_until=self.valid_until,
        )
        self.target = self.construction.target
        self.policy_set = RiskPolicySetVersion.create(
            (
                RiskPolicyDefinition.pass_through(
                    code_version=self.runtime_identity.code_version,
                    runtime_profile_id=self.runtime_identity.runtime_profile_id,
                ),
                RiskPolicyDefinition.max_single_name(
                    max_weight="0.45",
                    code_version=self.runtime_identity.code_version,
                    runtime_profile_id=self.runtime_identity.runtime_profile_id,
                ),
            )
        )
        self.risk_result = apply_risk(
            source_target=self.target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
        )
        self.adjusted = self.risk_result.adjusted_weights
        self.cost_policy = CostPolicyVersion.create(
            policy_name="TEST_COST_ROUND5_R",
            effective_from=date(2023, 8, 28),
            effective_to=None,
            commission_rate="0.0003",
            minimum_commission="5",
            stamp_duty_sell_rate="0.0005",
            market_rules=tuple(
                MarketCostRule(board, date(2023, 8, 28), None, "0.00001", "0.0000341", f"OFFICIAL_{board.value}")
                for board in Board
            ),
        )
        self.rule_profile = cn_a_share_2026_07_06_rule_profile()
        self.timing_profile = cn_a_share_2026_07_06_execution_timing_profile()
        self.cn_rebalance = datetime(2026, 7, 7, 8, 0, tzinfo=CN)
        self.cn_valid_until = datetime(2026, 7, 8, 15, 0, tzinfo=CN)
        self.cn_target = TargetWeightVector.create(
            source=self.source,
            construction_spec=self.construction_spec.to_reference(),
            evidence_refs=(
                self.construction.diagnostics.to_reference(),
                self.construction.provenance.to_reference(),
            ),
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.cn_rebalance - timedelta(hours=1),
            decision_time=self.cn_rebalance - timedelta(minutes=30),
            rebalance_time=self.cn_rebalance,
            valid_until=self.cn_valid_until,
            cash_weight="0.1",
            rows=(
                TargetWeightRow("000001.SZ", "0.5"),
                TargetWeightRow("000002.SZ", "0.4"),
            ),
        )
        self.cn_risk = apply_risk(
            source_target=self.cn_target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
        )
        self.cn_adjusted = self.cn_risk.adjusted_weights
        self.backtest_spec = self._build_backtest_spec(self.cn_adjusted, self.cost_policy)
        self.backtest_result = DeterministicAshareBacktestEngine().run(self.backtest_spec)

    def context(self, *, source_target: TargetWeightVector | None = None, risk_adjusted: RiskAdjustedWeightVector | None = None) -> object:
        return build_scenario_context(
            intent=self.intent,
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec.to_reference(),
            cost_policy=self.cost_policy,
            rule_profile_id=self.rule_profile.profile_id,
            execution_timing_profile_id=self.timing_profile.profile_id,
            risk_policy_set=self.policy_set,
            base_currency="CNY",
            source_target=source_target,
            risk_adjusted=risk_adjusted,
        )

    def _build_backtest_spec(
        self,
        vector: RiskAdjustedWeightVector,
        cost: CostPolicyVersion,
        *,
        initial_cash: str = "100000",
        initial_holdings: tuple[InitialHolding, ...] = (),
        sessions: tuple[MarketSession, ...] | None = None,
        state_overrides: dict[str, dict[str, object]] | None = None,
        reference_overrides: dict[str, str] | None = None,
        rule_profile: AshareTradingRuleProfileVersion | None = None,
        timing_profile: ExecutionTimingProfileVersion | None = None,
        runtime_identity: RuntimeIdentity | None = None,
        engine_version: str = "v3.a_share_daily_eod_engine/0.2.0",
        source: PortfolioIntentSource | None = None,
    ) -> BacktestRunSpec:
        source = source or self.source
        refs = tuple(
            ExactInputReference(kind, kind.lower() + "-v1", sha(character), PRE_ALPHA_CEILING)
            for kind, character in (
                ("SNAPSHOT", "9"),
                ("MARKET_DATA", "a"),
                ("TRADING_CALENDAR", "b"),
                ("UNIVERSE", "c"),
                ("CORPORATE_ACTIONS", "d"),
                ("OFFICIAL_TRADING_HOURS", "e"),
                ("OFFICIAL_COST_RULES", "f"),
            )
            if (reference_overrides or {}).get(kind) is None
        ) + tuple(
            ExactInputReference(kind, kind.lower() + "-v2", sha(character), PRE_ALPHA_CEILING)
            for kind, character in (reference_overrides or {}).items()
        )
        if sessions is None:
            sessions = tuple(
                MarketSession(
                    day,
                    True,
                    tuple(
                        self._state_for(instrument_id, state_overrides)
                        for instrument_id in source.universe_instrument_ids
                    ),
                    (),
                )
                for day in (DAY1, DAY2)
            )
        return BacktestRunSpec.create(
            initial_cash=initial_cash,
            initial_holdings=initial_holdings,
            instruments=tuple(
                InstrumentDefinition(
                    instrument_id,
                    Board.SZSE_MAIN if instrument_id.endswith(".SZ") else Board.SSE_MAIN,
                )
                for instrument_id in source.universe_instrument_ids
            ),
            sessions=sessions,
            schedule=(ScheduledWeights(vector.source_target.rebalance_time, vector),),
            rule_profile=rule_profile or self.rule_profile,
            cost_policy=cost,
            execution_timing_profile=timing_profile or self.timing_profile,
            exact_references=refs,
            runtime_identity=runtime_identity or self.runtime_identity,
            engine_version=engine_version,
        )

    @staticmethod
    def _state_for(instrument_id: str, state_overrides: dict[str, dict[str, object]] | None) -> DailyMarketState:
        overrides = dict((state_overrides or {}).get(instrument_id, {}))
        raw_open = str(overrides.pop("raw_open", "10"))
        raw_close = str(overrides.pop("raw_close", "10"))
        return DailyMarketState(instrument_id, raw_open, raw_close, **overrides)

    def analytics_for(
        self,
        result,
        policy: ResultAnalyticsPolicyVersion | None = None,
        benchmark: BenchmarkSeriesVersion | None = None,
    ) -> object:
        return DeterministicResultAnalyticsEngine().analyze(
            result,
            SourceResultBinding(result.result_id, result.content_sha256),
            policy or ResultAnalyticsPolicyVersion.a_share_daily_research_v0(),
            benchmark=benchmark,
        )

    def analytics(self):
        return self.analytics_for(self.backtest_result)

    def review_scope(self, result=None, *, target_digest_override: str | None = None):
        result = result or self.backtest_result
        result_digest = target_digest_override or result.content_sha256
        result_ref = ReviewEvidenceRef(SESSION, "BacktestRunResult", "btrr_sha256_" + result_digest, result_digest)
        spec_ref = ReviewEvidenceRef(SESSION, "BacktestRunSpec", "btrs_sha256_" + sha("7"), sha("7"))
        records = (
            ReviewEvidenceRecord(
                spec_ref,
                ValidationState.PASSED,
                FORMAL_ADMITTED_CEILING,
                (),
                (),
                (),
            ),
            ReviewEvidenceRecord(
                result_ref,
                ValidationState.PASSED,
                FORMAL_ADMITTED_CEILING,
                (spec_ref,),
                (),
                (),
            ),
        )
        return ResearchReviewScope.create(
            session_id=SESSION,
            target_refs=(result_ref,),
            evidence_records=records,
        )

    def bundle(
        self,
        *,
        analytics=None,
        reviewer_reports=(),
        cost_policy: CostPolicyVersion | None = None,
        policy_set: RiskPolicySetVersion | None = None,
        target: TargetWeightVector | None = None,
        risk_adjusted: RiskAdjustedWeightVector | None = None,
        decision_report=None,
        backtest_result=None,
        backtest_spec: BacktestRunSpec | None = None,
        with_backtest_spec: bool = True,
        construction_spec: UnresolvedExactReference | None = None,
        base_currency: str = "CNY",
    ):
        return resolve_scenario_evidence(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            construction_spec=construction_spec or self.construction_spec.to_reference(),
            risk_policy_set=policy_set or self.policy_set,
            cost_policy=cost_policy or self.cost_policy,
            base_currency=base_currency,
            target=target or self.cn_target,
            risk_adjusted=risk_adjusted or self.cn_adjusted,
            decision_report=decision_report if decision_report is not None else self.cn_risk.decision_report,
            backtest_result=backtest_result or self.backtest_result,
            backtest_spec=backtest_spec if backtest_spec is not None else (self.backtest_spec if with_backtest_spec else None),
            analytics=analytics,
            reviewer_reports=reviewer_reports,
        )

    def _alternate_chain_bundle(
        self,
        *,
        universe_id: str = "universe-2",
        universe_instruments: tuple[str, ...] | None = None,
    ) -> ResolvedScenarioEvidenceBundle:
        """Full canonical chain over an alternate universe (same definition)."""

        if universe_instruments is None:
            other_fixture = build_runtime_fixture(universe_id=universe_id)
            definition = other_fixture.definition
            other_binding = other_fixture.binding
            runtime_input = other_fixture.runtime_input
        else:
            other_fixture = build_runtime_fixture(
                factor_values=(3.0, 3.0, 2.0),
                runtime_values={
                    "000001.SZ": "3",
                    "000002.SZ": "3.0",
                    "000003.SZ": "2",
                },
            )
            definition = other_fixture.definition
            other_binding = rebuild_binding(
                other_fixture,
                universe=ExactUniverseReference(
                    "universe-1",
                    sha("2"),
                    "art_sha256_" + sha("f"),
                    sha("f"),
                    universe_instruments,
                    PRE_ALPHA_CEILING,
                ),
            )
            runtime_input = other_fixture.runtime_input
        evaluation = DeterministicStrategyEvaluator().evaluate(
            definition=definition,
            binding=other_binding,
            inputs=(runtime_input,),
        )
        other_intent = evaluation.portfolio_intent
        other_source = PortfolioIntentSource.create(
            intent=other_intent,
            definition=definition,
            binding=other_binding,
        )
        other_construction = DeterministicPortfolioConstruction().construct(
            intent=other_intent,
            definition=definition,
            binding=other_binding,
            construction_spec=self.construction_spec,
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.as_of,
            decision_time=self.decision_time,
            rebalance_time=self.rebalance_time,
            valid_until=self.valid_until,
        )
        other_target = TargetWeightVector.create(
            source=other_source,
            construction_spec=self.construction_spec.to_reference(),
            evidence_refs=(
                other_construction.diagnostics.to_reference(),
                other_construction.provenance.to_reference(),
            ),
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.cn_rebalance - timedelta(hours=1),
            decision_time=self.cn_rebalance - timedelta(minutes=30),
            rebalance_time=self.cn_rebalance,
            valid_until=self.cn_valid_until,
            cash_weight="0.1",
            rows=(
                TargetWeightRow("000001.SZ", "0.5"),
                TargetWeightRow("000002.SZ", "0.4"),
            ),
        )
        other_risk = apply_risk(
            source_target=other_target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
        )
        other_adjusted = other_risk.adjusted_weights
        other_spec = self._build_backtest_spec(other_adjusted, self.cost_policy, source=other_source)
        other_result = DeterministicAshareBacktestEngine().run(other_spec)
        return resolve_scenario_evidence(
            intent=other_intent,
            source=other_source,
            binding=other_binding,
            construction_spec=self.construction_spec.to_reference(),
            risk_policy_set=self.policy_set,
            cost_policy=self.cost_policy,
            base_currency="CNY",
            target=other_target,
            risk_adjusted=other_adjusted,
            decision_report=other_risk.decision_report,
            backtest_result=other_result,
            backtest_spec=other_spec,
            analytics=self.analytics_for(other_result),
        )

    def confirmation(self, draft, action: str) -> UserConfirmation:
        return UserConfirmation(
            action=action,
            draft_sha256=draft.deterministic_sha256,
            confirmed_by="human-researcher-1",
            confirmed_at=datetime(2026, 1, 5, 16, 0, tzinfo=timezone.utc),
        )


class PortfolioRiskAgentContractTests(PortfolioRiskAgentFixture):
    def test_01_proposal_is_non_canonical_draft(self):
        context = self.context(source_target=self.target)
        draft = draft_portfolio_construct(context=context, provenance=provenance())
        self.assertEqual(
            (draft.authority_status, draft.lifecycle_state, draft.canonical_identity, draft.publish_authority),
            ("NON_CANONICAL", "DRAFT", None, False),
        )
        self.assertEqual(draft.payload.agent_execution_allowed, False)
        self.assertEqual(draft.payload.user_confirmation_required, True)
        proposal = build_portfolio_risk_proposal(
            research_goal="bound baseline",
            context=context,
            action_drafts=(draft,),
        )
        self.assertEqual(
            (proposal.authority_status, proposal.lifecycle_state, proposal.agent_execution_allowed),
            ("NON_CANONICAL", "DRAFT", False),
        )

    def test_02_exact_portfolio_intent_required(self):
        with self.assertRaises(TypeError):
            read_portfolio_intent(
                intent="not-a-PortfolioIntent",
                source=self.source,
                binding=self.fixture.binding,
                base_currency="CNY",
            )
        with self.assertRaises(PortfolioRiskAgentBindingError):
            build_scenario_context(
                intent=self.intent,
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec.to_reference(),
                cost_policy=self.cost_policy,
                rule_profile_id=self.rule_profile.profile_id,
                execution_timing_profile_id=self.timing_profile.profile_id,
                risk_policy_set=self.policy_set,
                base_currency="CNY",
            )

    def test_03_exact_risk_policy_set_required_for_risk(self):
        other_runtime = RuntimeIdentity(
            code_version="git:different",
            runtime_profile_id="v3.risk-runtime/9.9.9",
            environment_fingerprint="cpython-3.14.5-linux-x64",
        )
        mismatched = RiskPolicySetVersion.create(
            (
                RiskPolicyDefinition.pass_through(
                    code_version=other_runtime.code_version,
                    runtime_profile_id=other_runtime.runtime_profile_id,
                ),
            )
        )
        with self.assertRaises(PortfolioRiskAgentBindingError):
            build_scenario_context(
                intent=self.intent,
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec.to_reference(),
                cost_policy=self.cost_policy,
                rule_profile_id=self.rule_profile.profile_id,
                execution_timing_profile_id=self.timing_profile.profile_id,
                risk_policy_set=mismatched,
                base_currency="CNY",
                source_target=self.target,
            )
        context = self.context(source_target=self.target)
        with self.assertRaises(PortfolioRiskAgentBindingError):
            draft_risk_apply(
                context=context,
                source_target=self.target,
                policy_set=mismatched,
                runtime_identity=other_runtime,
                provenance=provenance(),
            )

    def test_04_stale_or_wrong_risk_model_rejected(self):
        stale_runtime = RuntimeIdentity(
            code_version="git:stale-code",
            runtime_profile_id="v3.risk-runtime/0.1.0",
            environment_fingerprint="cpython-3.14.5-linux-x64",
        )
        stale_policy = RiskPolicySetVersion.create(
            (
                RiskPolicyDefinition.pass_through(
                    code_version=stale_runtime.code_version,
                    runtime_profile_id=stale_runtime.runtime_profile_id,
                ),
            )
        )
        with self.assertRaises(PortfolioRiskAgentBindingError):
            build_scenario_context(
                intent=self.intent,
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec.to_reference(),
                cost_policy=self.cost_policy,
                rule_profile_id=self.rule_profile.profile_id,
                execution_timing_profile_id=self.timing_profile.profile_id,
                risk_policy_set=stale_policy,
                base_currency="CNY",
                source_target=self.target,
            )
        context = self.context(source_target=self.target)
        draft = draft_risk_apply(
            context=context,
            source_target=self.target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
            provenance=provenance(),
        )
        confirmation = self.confirmation(draft, "RISK_APPLY")
        with self.assertRaises(PortfolioRiskApplicationError):
            verify_risk_apply_binding(
                draft=draft,
                confirmation=confirmation,
                source_target=self.target,
                policy_set=stale_policy,
                runtime_identity=stale_runtime,
            )

    def test_05_unsupported_constraint_rejected(self):
        context = self.context(source_target=self.target)
        from v3_backend.agents.portfolio_risk_agent.contracts import RiskApplyDraftPayload

        with self.assertRaises(ValidationError):
            RiskApplyDraftPayload(
                context=context,
                source_target_weight_vector_id=context.source_target_weight_vector_id,
                source_target_weight_vector_content_sha256=context.source_target_weight_vector_content_sha256,
                requested_risk_policy_set_version_id=context.risk_policy_set_version_id,
                requested_risk_policy_set_content_sha256=context.risk_policy_set_content_sha256,
                risk_backend=context.risk_backend,
                risk_code_version=context.risk_code_version,
                risk_runtime_profile_id=context.risk_runtime_profile_id,
                runtime_code_version=self.runtime_identity.code_version,
                runtime_profile_id=self.runtime_identity.runtime_profile_id,
                runtime_environment_fingerprint=self.runtime_identity.environment_fingerprint,
                evidence_refs=("r1",),
                sector_exposure_bound="0.2",
            )
        with self.assertRaises(ValidationError):
            from v3_backend.agents.portfolio_risk_agent.contracts import PortfolioRiskScenarioContext

            PortfolioRiskScenarioContext(
                **{
                    **context.model_dump(),
                    "turnover_budget": "0.5",
                }
            )

    def test_06_leverage_or_short_not_silently_enabled(self):
        context = self.context(source_target=self.target)
        from v3_backend.agents.portfolio_risk_agent.contracts import RiskApplyDraftPayload

        payload_kwargs = dict(
            context=context,
            source_target_weight_vector_id=context.source_target_weight_vector_id,
            source_target_weight_vector_content_sha256=context.source_target_weight_vector_content_sha256,
            requested_risk_policy_set_version_id=context.risk_policy_set_version_id,
            requested_risk_policy_set_content_sha256=context.risk_policy_set_content_sha256,
            risk_backend=context.risk_backend,
            risk_code_version=context.risk_code_version,
            risk_runtime_profile_id=context.risk_runtime_profile_id,
            runtime_code_version=self.runtime_identity.code_version,
            runtime_profile_id=self.runtime_identity.runtime_profile_id,
            runtime_environment_fingerprint=self.runtime_identity.environment_fingerprint,
            evidence_refs=("r1",),
        )
        with self.assertRaises(ValidationError):
            RiskApplyDraftPayload(**payload_kwargs, allow_short=True)
        with self.assertRaises(ValidationError):
            RiskApplyDraftPayload(**payload_kwargs, leverage_ratio="1.5")
        self.assertEqual(self.target.exposure_profile.value, "LONG_ONLY_UNLEVERED")
        for row in self.adjusted.rows:
            self.assertGreaterEqual(Decimal(row.target_weight), Decimal(0))

    def test_07_scenario_identity_deterministic(self):
        first = self.context(source_target=self.target)
        second = self.context(source_target=self.target)
        draft_a = draft_portfolio_construct(context=first, provenance=provenance("t/1"))
        draft_b = draft_portfolio_construct(context=second, provenance=provenance("t/1"))
        self.assertEqual(draft_a.deterministic_sha256, draft_b.deterministic_sha256)
        self.assertEqual(draft_a.to_deterministic_json(), draft_b.to_deterministic_json())
        self.assertNotEqual(draft_a.deterministic_sha256, draft_portfolio_construct(context=second, provenance=provenance("t/2")).deterministic_sha256)

    def test_08_agent_cannot_mint_target_weight_vector(self):
        draft = draft_portfolio_construct(context=self.context(source_target=self.target), provenance=provenance())
        self.assertIsInstance(draft.payload.context.portfolio_intent_id, str)
        from v3_backend.agents.portfolio_risk_agent.contracts import PortfolioConstructDraftPayload

        with self.assertRaises(ValidationError):
            PortfolioConstructDraftPayload(
                context=draft.payload.context,
                requested_construction_spec_version_id=draft.payload.requested_construction_spec_version_id,
                requested_cost_policy_id=draft.payload.requested_cost_policy_id,
                evidence_refs=("r1",),
                target_weight_rows=("000001.SZ", "0.5"),
            )
        tools = PortfolioRiskReadTools(
            intents=(
                read_portfolio_intent(
                    intent=self.intent,
                    source=self.source,
                    binding=self.fixture.binding,
                    base_currency="CNY",
                ),
            )
        )
        self.assertNotIn("mint_target_weight_vector", tools.visible_tool_names)
        self.assertNotIn("construct", tools.visible_tool_names)

    def test_09_agent_cannot_mint_risk_adjusted_vector(self):
        tools = PortfolioRiskReadTools(
            adjusted=(read_risk_adjusted_evidence(self.adjusted, self.risk_result.decision_report),)
        )
        self.assertNotIn("apply_risk", tools.visible_tool_names)
        self.assertNotIn("mint", tools.visible_tool_names)
        view = read_risk_adjusted_evidence(self.adjusted, self.risk_result.decision_report)
        self.assertTrue(view.risk_adjusted_weight_vector_id.startswith("rawv_sha256_"))

    def test_10_agent_cannot_change_cost_policy_by_prose(self):
        context = self.context(source_target=self.target)
        draft = draft_portfolio_construct(context=context, provenance=provenance())
        self.assertEqual(draft.payload.requested_cost_policy_id, self.cost_policy.policy_id)
        other_cost = CostPolicyVersion.create(
            policy_name="OTHER_COST",
            effective_from=date(2023, 8, 28),
            effective_to=None,
            commission_rate="0.001",
            minimum_commission="1",
            stamp_duty_sell_rate="0.001",
            market_rules=self.cost_policy.market_rules,
        )
        from v3_backend.agents.portfolio_risk_agent.contracts import PortfolioConstructDraftPayload

        with self.assertRaises(ValidationError):
            PortfolioConstructDraftPayload(
                context=context,
                requested_construction_spec_version_id=context.construction_spec_version_id,
                requested_cost_policy_id=other_cost.policy_id,
                evidence_refs=("r1",),
            )
        spec2 = self._build_backtest_spec(self.cn_adjusted, other_cost)
        result2 = DeterministicAshareBacktestEngine().run(spec2)
        bundle2 = resolve_scenario_evidence(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec.to_reference(),
            risk_policy_set=self.policy_set,
            cost_policy=other_cost,
            base_currency="CNY",
            target=self.cn_target,
            risk_adjusted=self.cn_adjusted,
            decision_report=self.cn_risk.decision_report,
            backtest_result=result2,
            backtest_spec=spec2,
            analytics=self.analytics_for(result2),
        )
        explanation = explain_scenario(bundle=bundle2)
        self.assertTrue(any("OTHER_COST" in statement for statement in explanation.cost_statements))
        self.assertIn(other_cost.policy_id, explanation.cited_evidence_refs)

    def test_11_backtest_draft_exact_inputs(self):
        context = self.context(source_target=self.cn_target, risk_adjusted=self.cn_adjusted)
        draft = draft_backtest_run(
            context=context,
            risk_adjusted=self.cn_adjusted,
            spec=self.backtest_spec,
            provenance=provenance(),
        )
        self.assertEqual(draft.payload.risk_adjusted_weight_vector_id, self.cn_adjusted.risk_adjusted_weight_vector_id)
        self.assertEqual(draft.payload.effective_at, self.cn_rebalance)
        self.assertEqual(draft.payload.backtest_run_spec_id, self.backtest_spec.run_spec_id)
        self.assertEqual(draft.payload.backtest_run_spec_content_sha256, self.backtest_spec.content_sha256)
        self.assertEqual(draft.payload.initial_cash, "100000")
        with self.assertRaises(PortfolioRiskAgentBindingError):
            draft_backtest_run(
                context=self.context(source_target=self.cn_target),
                risk_adjusted=self.cn_adjusted,
                spec=self.backtest_spec,
                provenance=provenance(),
            )
        bad_spec = self._build_backtest_spec(self.cn_adjusted, self.cost_policy, initial_cash="200000")
        with self.assertRaises(PortfolioRiskApplicationError):
            verify_backtest_binding(
                draft=draft,
                confirmation=self.confirmation(draft, "BACKTEST_RUN"),
                spec=bad_spec,
            )

    def test_12_comparison_invariant_context_exact(self):
        left = self.bundle(analytics=self.analytics())
        other_bundle = self._alternate_chain_bundle(universe_id="universe-2")
        self.assertIsInstance(left, ResolvedScenarioEvidenceBundle)
        self.assertIsInstance(other_bundle, ResolvedScenarioEvidenceBundle)
        self.assertIsNotNone(left.comparison_invariant)
        self.assertIsNotNone(other_bundle.comparison_invariant)
        self.assertNotEqual(
            left.comparison_invariant.invariant_id,
            other_bundle.comparison_invariant.invariant_id,
        )
        comparison = compare_scenarios(left, other_bundle, objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(comparison.status, ComparisonStatus.INCOMPARABLE_CONTEXT)
        self.assertIn("universe_version_id", comparison.context_mismatches)
        self.assertIsNone(comparison.ranking)
        self.assertEqual(comparison.metric_deltas, ())
        same = compare_scenarios(left, self.bundle(analytics=self.analytics()), objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(same.status, ComparisonStatus.COMPARABLE)
        self.assertTrue(all(delta.status == "AVAILABLE" for delta in same.metric_deltas if delta.name == "total_return"))
        self.assertEqual(same.ranking, "TIE")

    def test_13_different_cost_policy_is_visible_treatment_difference(self):
        other_cost = CostPolicyVersion.create(
            policy_name="OTHER_COST",
            effective_from=date(2023, 8, 28),
            effective_to=None,
            commission_rate="0.001",
            minimum_commission="1",
            stamp_duty_sell_rate="0.001",
            market_rules=self.cost_policy.market_rules,
        )
        base_view = read_cost_policy(self.cost_policy)
        other_view = read_cost_policy(other_cost)
        self.assertNotEqual(base_view.policy_id, other_view.policy_id)
        self.assertNotEqual(base_view.commission_rate, other_view.commission_rate)
        spec2 = self._build_backtest_spec(self.cn_adjusted, other_cost)
        result2 = DeterministicAshareBacktestEngine().run(spec2)
        left = self.bundle(analytics=self.analytics())
        right = resolve_scenario_evidence(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec.to_reference(),
            risk_policy_set=self.policy_set,
            cost_policy=other_cost,
            base_currency="CNY",
            target=self.cn_target,
            risk_adjusted=self.cn_adjusted,
            decision_report=self.cn_risk.decision_report,
            backtest_result=result2,
            backtest_spec=spec2,
            analytics=self.analytics_for(result2),
        )
        comparison = compare_scenarios(left, right, objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(comparison.status, ComparisonStatus.COMPARABLE)
        self.assertEqual(comparison.scenario_differences, ("cost_policy_id",))
        self.assertTrue(any(delta.name == "total_return" and delta.status == "AVAILABLE" for delta in comparison.metric_deltas))

    def test_14_reviewer_evidence_exact_bound(self):
        report = review_research_scope(self.review_scope())
        view = read_reviewer_report(report)
        self.assertEqual(view.rule_set_id, report.rule_set_id)
        self.assertEqual(view.session_id, SESSION)
        self.assertTrue(any(ref.object_id == self.backtest_result.result_id for ref in view.target_refs))
        draft = draft_review_run(
            target_refs=(self.backtest_result.result_id,),
            evidence_refs=(self.backtest_result.result_id, self.cost_policy.policy_id),
            rule_set_id=view.rule_set_id,
            provenance=provenance(),
        )
        self.assertEqual(draft.draft_kind, PortfolioRiskDraftKind.REVIEW_RUN)
        reviewer_view = read_reviewer_report(report)
        explanation = explain_scenario(bundle=self.bundle(analytics=self.analytics(), reviewer_reports=(report,)))
        self.assertEqual(explanation.status, "EVIDENCE_BOUND")
        self.assertIn(view.review_report_id, explanation.cited_evidence_refs)

    def test_15_missing_analytics_not_run_not_available(self):
        explanation = explain_scenario(bundle=self.bundle())
        self.assertEqual(explanation.status, "EVIDENCE_MISSING")
        self.assertIn("analytics", explanation.missing_evidence)
        comparison = compare_scenarios(self.bundle(), self.bundle())
        self.assertEqual(comparison.status, ComparisonStatus.INCOMPARABLE_CONTEXT)
        self.assertIn("analytics", comparison.context_mismatches)
        analytics = self.analytics()
        view = read_result_analytics(analytics)
        unavailable = [metric for metric in (*view.metrics, view.turnover) if metric.status != "AVAILABLE"]
        for metric in unavailable:
            self.assertIsNone(metric.value)

    def test_16_explicit_user_command_not_exposed_as_agent_l2(self):
        decision = decide_permission(PermissionLevel.L2_EXECUTE)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "V0_L2_EXECUTE_DENIED")
        tools = PortfolioRiskReadTools()
        for name in tools.visible_tool_names:
            self.assertNotIn("confirm", name)
            self.assertNotIn("apply", name)
            self.assertNotIn("execute", name)
        context = self.context(source_target=self.target)
        draft = draft_portfolio_construct(context=context, provenance=provenance())
        with self.assertRaises(ValidationError):
            UserConfirmation(
                action="PORTFOLIO_CONSTRUCT",
                draft_sha256=draft.deterministic_sha256,
                confirmed_by="ai-agent",
                confirmed_at=datetime(2026, 1, 5, 16, 0, tzinfo=timezone.utc),
                agent_issued=True,
            )

    def test_17_l2_l3_remain_denied(self):
        for level, reason in (
            (PermissionLevel.L2_EXECUTE, "V0_L2_EXECUTE_DENIED"),
            (PermissionLevel.L3_PUBLISH, "V0_L3_PUBLISH_DENIED"),
        ):
            decision = decide_permission(level)
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.reason, reason)

    def test_18_no_second_optimizer_or_risk_authority(self):
        from v3_backend.domain.portfolio_construction import PortfolioConstructionRejected

        candidate = object()
        with self.assertRaises(PortfolioConstructionRejected):
            DeterministicPortfolioConstruction().construct(
                intent=self.intent,
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec,
                runtime_identity=self.runtime_identity,
                base_currency="CNY",
                as_of=self.as_of,
                decision_time=self.decision_time,
                rebalance_time=self.rebalance_time,
                valid_until=self.valid_until,
                optimizer_candidate=candidate,
            )
        with self.assertRaises(ExternalSolverAuthorityError):
            apply_risk(
                source_target=self.target,
                policy_set=self.policy_set,
                runtime_identity=self.runtime_identity,
                external_solver_candidate=candidate,
            )
        view = read_risk_policy_set(self.policy_set)
        self.assertEqual(view.backend, "v3-native-decimal")

    def test_19_a_share_constraints_preserved(self):
        draft = draft_backtest_run(
            context=self.context(source_target=self.cn_target, risk_adjusted=self.cn_adjusted),
            risk_adjusted=self.cn_adjusted,
            spec=self.backtest_spec,
            provenance=provenance(),
        )
        confirmation = self.confirmation(draft, "BACKTEST_RUN")
        verify_backtest_binding(draft=draft, confirmation=confirmation, spec=self.backtest_spec)
        suspended_spec = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            state_overrides={"000001.SZ": {"suspended": True}},
        )
        suspended_result = DeterministicAshareBacktestEngine().run(suspended_spec)
        codes = {diagnostic.code.value for diagnostic in suspended_result.diagnostics}
        self.assertIn("SUSPENDED", codes)
        with self.assertRaises(PortfolioRiskApplicationError):
            verify_backtest_binding(draft=draft, confirmation=confirmation, spec=suspended_spec)
        explanation = explain_scenario(bundle=self.bundle(analytics=self.analytics()))
        for statement in explanation.analytics_statements + explanation.weight_change_statements:
            self.assertNotIn("short", statement.lower())
            self.assertNotIn("leverage", statement.lower())

    def test_20_research_loop_complete_remains_not_available(self):
        from v3_backend.domain.agent_research_loop.model import ResearchActionState

        self.assertEqual(ResearchActionState.NOT_RUN.value, "NOT_RUN")
        proposal = build_portfolio_risk_proposal(
            research_goal="no completion",
            context=self.context(source_target=self.target),
            action_drafts=(draft_portfolio_construct(context=self.context(source_target=self.target), provenance=provenance()),),
        )
        self.assertEqual(proposal.agent_execution_allowed, False)
        self.assertEqual(proposal.lifecycle_state, "DRAFT")
        from v3_backend.agents.portfolio_risk_agent import PortfolioRiskAgentDraft

        draft = draft_portfolio_construct(context=self.context(source_target=self.target), provenance=provenance())
        with self.assertRaises(ValidationError):
            PortfolioRiskAgentDraft.model_validate({**draft.model_dump(), "publish_authority": True})


class PortfolioRiskCorrectionAuthorityTests(PortfolioRiskAgentFixture):
    """Finding R-A: UserConfirmation is not user authority."""

    def test_corr_01_caller_confirmation_cannot_authorize_production_execution(self):
        construct_draft = draft_portfolio_construct(context=self.context(source_target=self.target), provenance=provenance())
        with self.assertRaises(UserExecutionAuthorityNotAvailable) as caught:
            apply_confirmed_portfolio_construct(
                draft=construct_draft,
                confirmation=self.confirmation(construct_draft, "PORTFOLIO_CONSTRUCT"),
                intent=self.intent,
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec,
                runtime_identity=self.runtime_identity,
                base_currency="CNY",
                as_of=self.as_of,
                decision_time=self.decision_time,
                rebalance_time=self.rebalance_time,
                valid_until=self.valid_until,
            )
        self.assertIn(USER_EXECUTION_AUTHORITY_NOT_AVAILABLE, str(caught.exception))

    def test_corr_02_fake_confirmed_by_cannot_elevate_authority(self):
        risk_draft = draft_risk_apply(
            context=self.context(source_target=self.target),
            source_target=self.target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
            provenance=provenance(),
        )
        confirmation = UserConfirmation(
            action="RISK_APPLY",
            draft_sha256=risk_draft.deterministic_sha256,
            confirmed_by="human-researcher-1",
            confirmed_at=datetime(2026, 1, 5, 16, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(confirmation.agent_issued)
        with self.assertRaises(UserExecutionAuthorityNotAvailable):
            apply_confirmed_risk_apply(
                draft=risk_draft,
                confirmation=confirmation,
                source_target=self.target,
                policy_set=self.policy_set,
                runtime_identity=self.runtime_identity,
            )

    def test_corr_03_all_three_apply_commands_fail_closed(self):
        construct_draft = draft_portfolio_construct(context=self.context(source_target=self.target), provenance=provenance())
        risk_draft = draft_risk_apply(
            context=self.context(source_target=self.target),
            source_target=self.target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
            provenance=provenance(),
        )
        backtest_draft = draft_backtest_run(
            context=self.context(source_target=self.cn_target, risk_adjusted=self.cn_adjusted),
            risk_adjusted=self.cn_adjusted,
            spec=self.backtest_spec,
            provenance=provenance(),
        )
        with self.assertRaises(UserExecutionAuthorityNotAvailable):
            apply_confirmed_portfolio_construct(
                draft=construct_draft,
                confirmation=self.confirmation(construct_draft, "PORTFOLIO_CONSTRUCT"),
                intent=self.intent,
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec,
                runtime_identity=self.runtime_identity,
                base_currency="CNY",
                as_of=self.as_of,
                decision_time=self.decision_time,
                rebalance_time=self.rebalance_time,
                valid_until=self.valid_until,
            )
        with self.assertRaises(UserExecutionAuthorityNotAvailable):
            apply_confirmed_risk_apply(
                draft=risk_draft,
                confirmation=self.confirmation(risk_draft, "RISK_APPLY"),
                source_target=self.target,
                policy_set=self.policy_set,
                runtime_identity=self.runtime_identity,
            )
        with self.assertRaises(UserExecutionAuthorityNotAvailable):
            apply_confirmed_backtest_run(
                draft=backtest_draft,
                confirmation=self.confirmation(backtest_draft, "BACKTEST_RUN"),
                spec=self.backtest_spec,
            )

    def test_corr_04_l2_l3_remain_denied(self):
        self.assertFalse(decide_permission(PermissionLevel.L2_EXECUTE).allowed)
        self.assertFalse(decide_permission(PermissionLevel.L3_PUBLISH).allowed)

    def test_corr_05_agent_tool_inventory_has_zero_confirm_apply_execute(self):
        tools = PortfolioRiskReadTools()
        for name in tools.visible_tool_names:
            for forbidden in ("confirm", "apply", "execute", "construct", "publish"):
                self.assertNotIn(forbidden, name)


class PortfolioRiskCorrectionConstructBindingTests(PortfolioRiskAgentFixture):
    """Finding R-B (3.1): exact portfolio construct binding."""

    def _draft(self):
        return draft_portfolio_construct(context=self.context(source_target=self.target), provenance=provenance())

    def _verify(self, draft, **overrides):
        kwargs = dict(
            draft=draft,
            confirmation=self.confirmation(draft, "PORTFOLIO_CONSTRUCT"),
            intent=self.intent,
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec,
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.as_of,
            decision_time=self.decision_time,
            rebalance_time=self.rebalance_time,
            valid_until=self.valid_until,
        )
        kwargs.update(overrides)
        verify_portfolio_construct_binding(**kwargs)

    def test_corr_06_changed_base_currency_reject(self):
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), base_currency="USD")

    def test_corr_07_changed_as_of_reject(self):
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), as_of=self.as_of + timedelta(minutes=1))

    def test_corr_08_changed_decision_time_reject(self):
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), decision_time=self.decision_time + timedelta(minutes=1))

    def test_corr_09_changed_rebalance_time_reject(self):
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), rebalance_time=self.rebalance_time + timedelta(minutes=1))

    def test_corr_10_changed_valid_until_reject(self):
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), valid_until=self.valid_until + timedelta(minutes=1))

    def test_corr_11_wrong_construction_spec_reject(self):
        other_spec = PortfolioConstructionSpecVersion.create(
            method=ConstructionMethod.EQUAL_WEIGHT_SELECTED,
            method_version="1.0.0",
            target_cash_weight="0.2",
            max_instrument_weight="1",
            runtime_identity=self.runtime_identity,
        )
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), construction_spec=other_spec)

    def test_corr_11b_exact_construct_binding_pass(self):
        self._verify(self._draft())


class PortfolioRiskCorrectionRiskBindingTests(PortfolioRiskAgentFixture):
    """Finding R-B (3.2): exact risk apply binding, Route A."""

    def _draft(self):
        return draft_risk_apply(
            context=self.context(source_target=self.target),
            source_target=self.target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
            provenance=provenance(),
        )

    def _verify(self, draft, **overrides):
        kwargs = dict(
            draft=draft,
            confirmation=self.confirmation(draft, "RISK_APPLY"),
            source_target=self.target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
            state_inputs=(),
        )
        kwargs.update(overrides)
        verify_risk_apply_binding(**kwargs)

    def _draft_with(self, **updates):
        draft = self._draft()
        from v3_backend.agents.portfolio_risk_agent import PortfolioRiskAgentDraft

        payload = draft.payload.model_dump()
        payload.update(updates)
        return PortfolioRiskAgentDraft(
            draft_kind=draft.draft_kind,
            payload=payload,
            permission_decision=draft.permission_decision,
            provenance=draft.provenance,
        )

    def test_corr_12_wrong_target_content_reject(self):
        import dataclasses

        tampered_target = dataclasses.replace(self.target, content_sha256=sha("e"))
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), source_target=tampered_target)

    def test_corr_13_wrong_policy_content_reject(self):
        import dataclasses

        tampered_policy = dataclasses.replace(self.policy_set, content_sha256=sha("e"))
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), policy_set=tampered_policy)

    def test_corr_14_wrong_runtime_identity_reject(self):
        tampered = self._draft_with(runtime_code_version="git:other")
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(tampered)
        other_runtime = RuntimeIdentity(
            code_version="git:other",
            runtime_profile_id=self.runtime_identity.runtime_profile_id,
            environment_fingerprint=self.runtime_identity.environment_fingerprint,
        )
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), runtime_identity=other_runtime)

    def test_corr_15_unbound_state_inputs_reject(self):
        state_input = RiskStateInput(
            "state-1",
            UnresolvedExactReference(ReferenceKind.RISK_STATE, "state-1", sha("8"), PRE_ALPHA_CEILING),
            self.decision_time,
        )
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), state_inputs=(state_input,))

    def test_corr_16_pit_owner_validation_stays_with_canonical_risk_runtime(self):
        self._verify(self._draft())
        with self.assertRaises(UserExecutionAuthorityNotAvailable):
            apply_confirmed_risk_apply(
                draft=self._draft(),
                confirmation=self.confirmation(self._draft(), "RISK_APPLY"),
                source_target=self.target,
                policy_set=self.policy_set,
                runtime_identity=self.runtime_identity,
            )


class PortfolioRiskCorrectionBacktestBindingTests(PortfolioRiskAgentFixture):
    """Finding R-B (3.3): exact content-addressed BacktestRunSpec binding."""

    def _draft(self):
        return draft_backtest_run(
            context=self.context(source_target=self.cn_target, risk_adjusted=self.cn_adjusted),
            risk_adjusted=self.cn_adjusted,
            spec=self.backtest_spec,
            provenance=provenance(),
        )

    def _verify(self, draft, **overrides):
        kwargs = dict(
            draft=draft,
            confirmation=self.confirmation(draft, "BACKTEST_RUN"),
            spec=self.backtest_spec,
        )
        kwargs.update(overrides)
        verify_backtest_binding(**kwargs)

    def _draft_with(self, **updates):
        draft = self._draft()
        from v3_backend.agents.portfolio_risk_agent import PortfolioRiskAgentDraft

        payload = draft.payload.model_dump()
        payload.update(updates)
        return PortfolioRiskAgentDraft(
            draft_kind=draft.draft_kind,
            payload=payload,
            permission_decision=draft.permission_decision,
            provenance=draft.provenance,
        )

    def test_corr_17_changed_initial_cash_reject(self):
        tampered = self._draft_with(initial_cash="200000")
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(tampered)

    def test_corr_18_changed_scheduled_effective_time_reject(self):
        from v3_backend.domain.backtest_runtime import ScheduledWeights

        item = self.backtest_spec.schedule[0]
        tampered_item = object.__new__(ScheduledWeights)
        object.__setattr__(tampered_item, "effective_at", item.effective_at + timedelta(minutes=1))
        object.__setattr__(tampered_item, "vector", item.vector)
        raw_spec = object.__new__(BacktestRunSpec)
        for field_name in (
            "run_spec_id",
            "content_sha256",
            "initial_cash",
            "initial_holdings",
            "instruments",
            "sessions",
            "rule_profile",
            "cost_policy",
            "execution_timing_profile",
            "exact_references",
            "runtime_identity",
            "engine_version",
            "truth_admission",
        ):
            object.__setattr__(raw_spec, field_name, getattr(self.backtest_spec, field_name))
        object.__setattr__(raw_spec, "schedule", (tampered_item,))
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), spec=raw_spec)

    def test_corr_19_unrelated_vector_spec_reject(self):
        unrelated_spec = self._build_backtest_spec(self.adjusted, self.cost_policy)
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), spec=unrelated_spec)

    def test_corr_20_different_market_sessions_reject_via_content_hash(self):
        changed_spec = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            state_overrides={"000002.SZ": {"raw_open": "11"}},
        )
        with self.assertRaises(PortfolioRiskApplicationError):
            self._verify(self._draft(), spec=changed_spec)

    def test_corr_21_production_execution_not_available_without_authority(self):
        with self.assertRaises(UserExecutionAuthorityNotAvailable):
            apply_confirmed_backtest_run(
                draft=self._draft(),
                confirmation=self.confirmation(self._draft(), "BACKTEST_RUN"),
                spec=self.backtest_spec,
            )

    def test_corr_21b_exact_backtest_binding_pass(self):
        self._verify(self._draft())


class PortfolioRiskCorrectionEvidenceResolverTests(PortfolioRiskAgentFixture):
    """Finding R-C: system-owned scenario evidence resolver."""

    def test_corr_22_fabricated_projection_cannot_become_evidence_bound(self):
        from v3_backend.agents.portfolio_risk_agent import BacktestResultEvidenceView

        fabricated = BacktestResultEvidenceView(
            result_id="btrr_sha256_" + sha("1"),
            content_sha256=sha("1"),
            run_spec_id="btrs_sha256_" + sha("2"),
            initial_cash="0",
            session_count=1,
            order_count=0,
            fill_count=0,
            final_cash="0",
            final_nav="0",
            final_holdings_count=0,
            nav_points=(("2026-07-07", "0"),),
            truth_admission="PRE_ALPHA",
        )
        self.assertIsInstance(fabricated, BacktestResultEvidenceView)
        with self.assertRaises(TypeError):
            resolve_scenario_evidence(
                intent=self.intent,
                source=self.source,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec.to_reference(),
                risk_policy_set=self.policy_set,
                cost_policy=self.cost_policy,
                base_currency="CNY",
                target=self.cn_target,
                risk_adjusted=self.cn_adjusted,
                backtest_result=fabricated,
                backtest_spec=self.backtest_spec,
            )

    def test_corr_23_unrelated_target_reject(self):
        other_target = TargetWeightVector.create(
            source=self.source,
            construction_spec=self.construction_spec.to_reference(),
            evidence_refs=(
                self.construction.diagnostics.to_reference(),
                self.construction.provenance.to_reference(),
            ),
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.cn_rebalance - timedelta(hours=1),
            decision_time=self.cn_rebalance - timedelta(minutes=30),
            rebalance_time=self.cn_rebalance + timedelta(days=1),
            valid_until=self.cn_valid_until + timedelta(days=1),
            cash_weight="0.5",
            rows=(TargetWeightRow("000001.SZ", "0.5"),),
        )
        with self.assertRaises(PortfolioRiskAgentBindingError):
            resolve_scenario_evidence(
                intent=self.intent,
                source=self.source,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec.to_reference(),
                risk_policy_set=self.policy_set,
                cost_policy=self.cost_policy,
                base_currency="CNY",
                target=other_target,
                risk_adjusted=self.cn_adjusted,
            )

    def test_corr_24_unrelated_backtest_result_reject(self):
        other_spec = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            state_overrides={"000001.SZ": {"suspended": True}},
        )
        other_result = DeterministicAshareBacktestEngine().run(other_spec)
        with self.assertRaises(PortfolioRiskAgentBindingError):
            resolve_scenario_evidence(
                intent=self.intent,
                source=self.source,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec.to_reference(),
                risk_policy_set=self.policy_set,
                cost_policy=self.cost_policy,
                base_currency="CNY",
                target=self.cn_target,
                risk_adjusted=self.cn_adjusted,
                backtest_result=other_result,
                backtest_spec=self.backtest_spec,
            )

    def test_corr_25_analytics_from_another_result_reject(self):
        other_spec = self._build_backtest_spec(self.cn_adjusted, self.cost_policy, initial_cash="300000")
        other_result = DeterministicAshareBacktestEngine().run(other_spec)
        other_analytics = self.analytics_for(other_result)
        with self.assertRaises(PortfolioRiskAgentBindingError):
            self.bundle(analytics=other_analytics)

    def test_corr_26_unrelated_reviewer_report_reject(self):
        other_spec = self._build_backtest_spec(self.cn_adjusted, self.cost_policy, initial_cash="300000")
        other_result = DeterministicAshareBacktestEngine().run(other_spec)
        other_report = review_research_scope(self.review_scope(result=other_result))
        with self.assertRaises(PortfolioRiskAgentBindingError):
            self.bundle(analytics=self.analytics(), reviewer_reports=(other_report,))

    def test_corr_27_missing_owner_link_marks_binding_unavailable(self):
        bundle = self.bundle(analytics=self.analytics(), with_backtest_spec=False)
        self.assertIn("backtest_to_risk_adjusted", bundle.binding_gaps)
        explanation = explain_scenario(bundle=bundle)
        self.assertEqual(explanation.status, "EVIDENCE_BINDING_UNAVAILABLE")

    def test_corr_28_exact_canonical_chain_passes(self):
        report = review_research_scope(self.review_scope())
        bundle = self.bundle(analytics=self.analytics(), reviewer_reports=(report,))
        self.assertEqual(bundle.binding_gaps, ())
        explanation = explain_scenario(bundle=bundle)
        self.assertEqual(explanation.status, "EVIDENCE_BOUND")
        view = bundle.backtest
        self.assertEqual(view.run_spec_id, self.backtest_spec.run_spec_id)
        self.assertIn(self.cn_adjusted.risk_adjusted_weight_vector_id, view.scheduled_risk_adjusted_vector_ids)
        self.assertEqual(view.bound_risk_adjusted_weight_vector_id, self.cn_adjusted.risk_adjusted_weight_vector_id)


def proposal_model(messages: list[object], info: AgentInfo) -> ModelResponse:
    request = None
    has_return = False
    for message in messages:
        for part in getattr(message, "parts", ()):
            if isinstance(part, ToolReturnPart):
                has_return = True
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                try:
                    candidate = json.loads(part.content)
                except json.JSONDecodeError:
                    continue
                if candidate.get("task") in ("PORTFOLIO_CONSTRUCT_PROPOSAL", "RISK_APPLY_PROPOSAL", "BACKTEST_RUN_PROPOSAL", "RESULT_COMPARE_PROPOSAL"):
                    request = candidate
    if request is None:
        raise AssertionError("R structured request unavailable")
    if not has_return:
        if request.get("task") == "RESULT_COMPARE_PROPOSAL":
            return ModelResponse(parts=[ToolCallPart("compare_scenarios", {"comparison_key": request.get("comparison_key", "")})])
        return ModelResponse(parts=[ToolCallPart("get_portfolio_intent", {"portfolio_intent_id": request["portfolio_intent_id"]})])
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"rationale": "Exact evidence supports a bounded scenario draft.", "next_action_proposals": ["review the exact draft before any future execution"], "evidence_claims": ["ignored model-authored evidence claim"]})])


def proposal_without_tool(_messages: list[object], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"rationale": "Unsafe no-tool proposal.", "next_action_proposals": []})])


def compare_model_without_tool(_messages: list[object], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"rationale": "Unsafe no-evidence compare.", "next_action_proposals": []})])


class PortfolioRiskAgentWorkerTests(PortfolioRiskAgentFixture):
    def worker(self, model, read_tools=None):
        return PortfolioRiskAgentWorker(
            model=FunctionModel(model),
            permission=PermissionLevel.L1_DRAFT,
            model_name="deterministic-test-model",
            provider_name="test-provider",
            prompt_version="round5-r/1",
            read_tools=read_tools or self.read_tools(),
        )

    def read_tools(self, bundles=()):
        return PortfolioRiskReadTools(
            intents=(read_portfolio_intent(intent=self.intent, source=self.source, binding=self.fixture.binding, base_currency="CNY"),),
            targets=(read_target_weight_evidence(self.target),),
            policy_sets=(read_risk_policy_set(self.policy_set),),
            adjusted=(
                read_risk_adjusted_evidence(self.adjusted, self.risk_result.decision_report),
                read_risk_adjusted_evidence(self.cn_adjusted, self.cn_risk.decision_report),
            ),
            cost_policies=(read_cost_policy(self.cost_policy),),
            bundles=tuple(bundles),
        )

    def test_worker_construct_proposal_requires_exact_evidence(self):
        context = self.context(source_target=self.target)
        proposal = self.worker(proposal_model).run_construct_proposal(research_goal="baseline", context=context)
        self.assertEqual(proposal.authority_status, "NON_CANONICAL")
        self.assertEqual(proposal.lifecycle_state, "DRAFT")
        self.assertEqual(len(proposal.action_drafts), 1)
        self.assertEqual(proposal.action_drafts[0].draft_kind, PortfolioRiskDraftKind.PORTFOLIO_CONSTRUCT)

    def test_worker_proposal_without_tool_fails_closed(self):
        from v3_backend.agents.pydantic_worker import AgentOutputRejected

        context = self.context(source_target=self.target)
        with self.assertRaises(AgentOutputRejected):
            self.worker(proposal_without_tool).run_construct_proposal(research_goal="unsafe", context=context)

    def test_worker_risk_proposal_exposes_exact_evidence(self):
        risk_context = self.context(source_target=self.target)
        risk_proposal = self.worker(proposal_model).run_risk_proposal(
            research_goal="clip",
            context=risk_context,
            source_target=self.target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
        )
        self.assertEqual(risk_proposal.action_drafts[0].draft_kind, PortfolioRiskDraftKind.RISK_APPLY)
        payload = risk_proposal.action_drafts[0].payload
        self.assertEqual(payload.requested_risk_policy_set_content_sha256, self.policy_set.content_sha256)
        self.assertEqual(payload.runtime_code_version, self.runtime_identity.code_version)

    def test_worker_backtest_proposal_exposes_exact_evidence(self):
        backtest_context = self.context(source_target=self.cn_target, risk_adjusted=self.cn_adjusted)
        backtest_proposal = self.worker(proposal_model).run_backtest_proposal(
            research_goal="eod backtest",
            context=backtest_context,
            risk_adjusted=self.cn_adjusted,
            spec=self.backtest_spec,
        )
        self.assertEqual(backtest_proposal.action_drafts[0].draft_kind, PortfolioRiskDraftKind.BACKTEST_RUN)
        payload = backtest_proposal.action_drafts[0].payload
        self.assertEqual(payload.backtest_run_spec_id, self.backtest_spec.run_spec_id)
        self.assertEqual(payload.engine_version, self.backtest_spec.engine_version)

    def test_worker_compare_proposal_consumes_exact_comparison_evidence(self):
        from v3_backend.agents.pydantic_worker import AgentOutputRejected

        other_cost = CostPolicyVersion.create(
            policy_name="OTHER_COST",
            effective_from=date(2023, 8, 28),
            effective_to=None,
            commission_rate="0.001",
            minimum_commission="1",
            stamp_duty_sell_rate="0.001",
            market_rules=self.cost_policy.market_rules,
        )
        spec2 = self._build_backtest_spec(self.cn_adjusted, other_cost)
        result2 = DeterministicAshareBacktestEngine().run(spec2)
        left = self.bundle(analytics=self.analytics())
        right = resolve_scenario_evidence(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec.to_reference(),
            risk_policy_set=self.policy_set,
            cost_policy=other_cost,
            base_currency="CNY",
            target=self.cn_target,
            risk_adjusted=self.cn_adjusted,
            decision_report=self.cn_risk.decision_report,
            backtest_result=result2,
            backtest_spec=spec2,
            analytics=self.analytics_for(result2),
        )
        tools = self.read_tools(bundles=(left, right))
        narrative = self.worker(proposal_model, read_tools=tools).run_compare_proposal(
            research_goal="compare",
            left=left,
            right=right,
            objective_metric="total_return",
            objective_direction="MAXIMIZE",
        )
        self.assertIsNotNone(narrative.rationale)
        tools.begin(())
        with self.assertRaises(AgentOutputRejected):
            self.worker(compare_model_without_tool, read_tools=tools).run_compare_proposal(
                research_goal="unsafe compare",
                left=left,
                right=right,
            )

    def test_compare_worker_requires_bundle_evidence(self):
        from v3_backend.agents.pydantic_worker import AgentOutputRejected

        left = self.bundle(analytics=self.analytics())
        other_cost = CostPolicyVersion.create(
            policy_name="OTHER_COST",
            effective_from=date(2023, 8, 28),
            effective_to=None,
            commission_rate="0.001",
            minimum_commission="1",
            stamp_duty_sell_rate="0.001",
            market_rules=self.cost_policy.market_rules,
        )
        spec2 = self._build_backtest_spec(self.cn_adjusted, other_cost)
        result2 = DeterministicAshareBacktestEngine().run(spec2)
        right = resolve_scenario_evidence(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec.to_reference(),
            risk_policy_set=self.policy_set,
            cost_policy=other_cost,
            base_currency="CNY",
            target=self.cn_target,
            risk_adjusted=self.cn_adjusted,
            decision_report=self.cn_risk.decision_report,
            backtest_result=result2,
            backtest_spec=spec2,
            analytics=self.analytics_for(result2),
        )
        empty_tools = PortfolioRiskReadTools()
        with self.assertRaises(AgentOutputRejected):
            self.worker(proposal_model, read_tools=empty_tools).run_compare_proposal(
                research_goal="compare",
                left=left,
                right=right,
            )

    def test_read_tools_fail_closed_on_unknown_identity(self):
        tools = self.read_tools()
        tools.begin((("get_portfolio_intent", self.intent.portfolio_intent_id),))
        with self.assertRaises(PortfolioRiskAgentToolError):
            tools.get_target_weight_evidence(self.target.target_weight_vector_id)
        with self.assertRaises(PortfolioRiskAgentToolError):
            tools.get_portfolio_intent("unknown-intent")

    def test_user_confirmation_seam_fails_closed_and_binding_verifiers_pass(self):
        context = self.context(source_target=self.target)
        construct_draft = draft_portfolio_construct(context=context, provenance=provenance())
        verify_portfolio_construct_binding(
            draft=construct_draft,
            confirmation=self.confirmation(construct_draft, "PORTFOLIO_CONSTRUCT"),
            intent=self.intent,
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec,
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.as_of,
            decision_time=self.decision_time,
            rebalance_time=self.rebalance_time,
            valid_until=self.valid_until,
        )
        risk_draft = draft_risk_apply(
            context=context,
            source_target=self.target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
            provenance=provenance(),
        )
        verify_risk_apply_binding(
            draft=risk_draft,
            confirmation=self.confirmation(risk_draft, "RISK_APPLY"),
            source_target=self.target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
            state_inputs=(),
        )
        backtest_draft = draft_backtest_run(
            context=self.context(source_target=self.cn_target, risk_adjusted=self.cn_adjusted),
            risk_adjusted=self.cn_adjusted,
            spec=self.backtest_spec,
            provenance=provenance(),
        )
        verify_backtest_binding(
            draft=backtest_draft,
            confirmation=self.confirmation(backtest_draft, "BACKTEST_RUN"),
            spec=self.backtest_spec,
        )

    def test_compare_drafts_and_explanation_flow(self):
        analytics = self.analytics()
        view = read_result_analytics(analytics)
        draft = draft_result_compare(
            left=view,
            right=view,
            objective_metric="total_return",
            objective_direction="MAXIMIZE",
            provenance=provenance(),
        )
        self.assertEqual(draft.draft_kind, PortfolioRiskDraftKind.RESULT_COMPARE)
        report = review_research_scope(self.review_scope())
        reviewer_view = read_reviewer_report(report)
        explanation = explain_scenario(
            bundle=self.bundle(analytics=analytics, reviewer_reports=(report,)),
            next_action_proposals=("PROPOSAL: raise max single-name clip",),
        )
        self.assertEqual(explanation.status, "EVIDENCE_BOUND")
        self.assertTrue(explanation.analytics_statements)
        self.assertTrue(explanation.reviewer_statements)
        self.assertFalse(explanation.invented_analytics)
        self.assertFalse(explanation.invented_exposure)
        self.assertFalse(explanation.invented_covariance)
        self.assertFalse(explanation.invented_causality)
        self.assertFalse(explanation.invented_optimization)
        comparison = compare_scenarios(
            self.bundle(analytics=analytics),
            self.bundle(analytics=analytics),
            objective_metric="total_return",
            objective_direction="MAXIMIZE",
        )
        self.assertEqual(comparison.status, ComparisonStatus.COMPARABLE)
        self.assertEqual(comparison.ranking, "TIE")


class PortfolioRiskCorrectionCompareTests(PortfolioRiskAgentFixture):
    """Finding R-D: evidence-grounded scenario comparison semantics."""

    def _risk_variant_bundle(self):
        variant_set = RiskPolicySetVersion.create(
            (
                RiskPolicyDefinition.pass_through(
                    code_version=self.runtime_identity.code_version,
                    runtime_profile_id=self.runtime_identity.runtime_profile_id,
                ),
            )
        )
        variant_risk = apply_risk(
            source_target=self.cn_target,
            policy_set=variant_set,
            runtime_identity=self.runtime_identity,
        )
        variant_adjusted = variant_risk.adjusted_weights
        variant_spec = self._build_backtest_spec(variant_adjusted, self.cost_policy)
        variant_result = DeterministicAshareBacktestEngine().run(variant_spec)
        return resolve_scenario_evidence(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec.to_reference(),
            risk_policy_set=variant_set,
            cost_policy=self.cost_policy,
            base_currency="CNY",
            target=self.cn_target,
            risk_adjusted=variant_adjusted,
            decision_report=variant_risk.decision_report,
            backtest_result=variant_result,
            backtest_spec=variant_spec,
            analytics=self.analytics_for(variant_result),
        )

    def test_corr_31_different_universe_or_cutoff_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        other_bundle = self._alternate_chain_bundle(universe_id="universe-2")
        self.assertIsInstance(other_bundle, ResolvedScenarioEvidenceBundle)
        comparison = compare_scenarios(left, other_bundle)
        self.assertEqual(comparison.status, ComparisonStatus.INCOMPARABLE_CONTEXT)
        self.assertIn("universe_version_id", comparison.context_mismatches)
        self.assertEqual(comparison.scenario_differences, ())
        self.assertIsNone(comparison.ranking)

    def test_corr_32_different_risk_policy_is_comparable_treatment_difference(self):
        left = self.bundle(analytics=self.analytics())
        right = self._risk_variant_bundle()
        comparison = compare_scenarios(left, right)
        self.assertEqual(comparison.status, ComparisonStatus.COMPARABLE)
        self.assertEqual(comparison.scenario_differences, ("risk_policy_set_version_id",))

    def test_corr_33_different_cost_policy_is_comparable_treatment_difference(self):
        other_cost = CostPolicyVersion.create(
            policy_name="OTHER_COST",
            effective_from=date(2023, 8, 28),
            effective_to=None,
            commission_rate="0.001",
            minimum_commission="1",
            stamp_duty_sell_rate="0.001",
            market_rules=self.cost_policy.market_rules,
        )
        spec2 = self._build_backtest_spec(self.cn_adjusted, other_cost)
        result2 = DeterministicAshareBacktestEngine().run(spec2)
        left = self.bundle(analytics=self.analytics())
        right = resolve_scenario_evidence(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec.to_reference(),
            risk_policy_set=self.policy_set,
            cost_policy=other_cost,
            base_currency="CNY",
            target=self.cn_target,
            risk_adjusted=self.cn_adjusted,
            decision_report=self.cn_risk.decision_report,
            backtest_result=result2,
            backtest_spec=spec2,
            analytics=self.analytics_for(result2),
        )
        comparison = compare_scenarios(left, right)
        self.assertEqual(comparison.status, ComparisonStatus.COMPARABLE)
        self.assertEqual(comparison.scenario_differences, ("cost_policy_id",))

    def test_corr_34_treatment_differences_returned_explicitly(self):
        left = self.bundle(analytics=self.analytics())
        right = self._risk_variant_bundle()
        comparison = compare_scenarios(left, right, objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(comparison.scenario_differences, ("risk_policy_set_version_id",))
        self.assertNotIn("portfolio_intent_id", comparison.scenario_differences)
        self.assertNotIn("universe_version_id", comparison.scenario_differences)

    def test_corr_35_ranking_only_with_available_objective_and_exact_invariant(self):
        left = self.bundle(analytics=self.analytics())
        right = self.bundle(analytics=self.analytics())
        ranked = compare_scenarios(left, right, objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(ranked.status, ComparisonStatus.COMPARABLE)
        self.assertEqual(ranked.ranking, "TIE")
        unranked = compare_scenarios(left, right, objective_metric="sharpe", objective_direction="MAXIMIZE")
        sharpe_delta = next(delta for delta in unranked.metric_deltas if delta.name == "sharpe")
        if sharpe_delta.status != "AVAILABLE":
            self.assertIsNone(unranked.ranking)
        else:
            self.assertIsNotNone(unranked.ranking)


class PortfolioRiskFinalClosureRCTests(PortfolioRiskAgentFixture):
    """R-C final closure: resolver trust boundary is not bypassable."""

    def _manual_bundle(self) -> ScenarioEvidenceBundle:
        intent_view = read_portfolio_intent(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            base_currency="CNY",
        )
        reference = self.construction_spec.to_reference()
        return ScenarioEvidenceBundle(
            intent=intent_view,
            construction_spec_version_id=reference.source_id,
            construction_spec_content_sha256=reference.content_sha256,
            risk_policy_set=read_risk_policy_set(self.policy_set),
            cost_policy=read_cost_policy(self.cost_policy),
        )

    def test_final_rc_01_manual_dto_cannot_become_trusted(self):
        trusted = self.bundle(analytics=self.analytics())
        manual = self._manual_bundle()
        self.assertIsInstance(manual, ScenarioEvidenceBundle)
        self.assertNotIsInstance(manual, ResolvedScenarioEvidenceBundle)
        with self.assertRaises(TypeError):
            ResolvedScenarioEvidenceBundle(manual, None, object())
        with self.assertRaises(TypeError):
            ResolvedScenarioEvidenceBundle(manual, None, None)
        with self.assertRaises(TypeError):
            compare_scenarios(trusted, manual)
        with self.assertRaises(TypeError):
            compare_scenarios(manual, trusted)
        with self.assertRaises(TypeError):
            explain_scenario(bundle=manual)

    def test_final_rc_02_empty_binding_gaps_cannot_confer_trust(self):
        manual = self._manual_bundle()
        self.assertEqual(manual.binding_gaps, ())
        with self.assertRaises(TypeError):
            explain_scenario(bundle=manual)
        with self.assertRaises(TypeError):
            compare_scenarios(manual, manual)

    def test_final_rc_03_matching_deterministic_sha_cannot_confer_trust(self):
        trusted = self.bundle(analytics=self.analytics())
        copied = trusted.payload.model_copy()
        self.assertEqual(copied.deterministic_sha256, trusted.payload.deterministic_sha256)
        deserialized = None
        try:
            deserialized = ScenarioEvidenceBundle.model_validate_json(
                json.dumps(trusted.payload.model_dump(mode="json"))
            )
        except ValidationError:
            deserialized = None
        for fabricated in (copied, deserialized):
            if fabricated is None:
                continue
            with self.assertRaises(TypeError):
                compare_scenarios(trusted, fabricated)
            with self.assertRaises(TypeError):
                explain_scenario(bundle=fabricated)

    def test_final_rc_04_manual_bundle_cannot_enter_read_tools(self):
        manual = self._manual_bundle()
        with self.assertRaises(TypeError):
            PortfolioRiskReadTools(bundles=(manual,))
        trusted = self.bundle(analytics=self.analytics())
        tools = PortfolioRiskReadTools(bundles=(trusted,))
        self.assertTrue(tools.has("get_scenario_bundle", trusted.deterministic_sha256))
        self.assertFalse(tools.has("get_scenario_bundle", manual.deterministic_sha256))
        tools.begin((("get_scenario_bundle", trusted.deterministic_sha256),))
        fetched = tools.get_scenario_bundle(trusted.deterministic_sha256)
        self.assertIsInstance(fetched, ResolvedScenarioEvidenceBundle)
        self.assertEqual(fetched.deterministic_sha256, trusted.deterministic_sha256)

    def test_final_rc_05_manual_bundle_cannot_enter_compare_worker(self):
        trusted = self.bundle(analytics=self.analytics())
        manual = self._manual_bundle()
        worker = PortfolioRiskAgentWorker(
            model=FunctionModel(proposal_model),
            permission=PermissionLevel.L1_DRAFT,
            model_name="deterministic-test-model",
            provider_name="test-provider",
            prompt_version="round5-r/1",
            read_tools=PortfolioRiskReadTools(bundles=(trusted,)),
        )
        with self.assertRaises(TypeError):
            worker.run_compare_proposal(research_goal="unsafe", left=trusted, right=manual)
        with self.assertRaises(TypeError):
            worker.run_compare_proposal(research_goal="unsafe", left=manual, right=trusted)

    def test_final_rc_06_unrelated_reviewer_report_rejected(self):
        other_spec = self._build_backtest_spec(self.cn_adjusted, self.cost_policy, initial_cash="300000")
        other_result = DeterministicAshareBacktestEngine().run(other_spec)
        other_report = review_research_scope(self.review_scope(result=other_result))
        with self.assertRaises(PortfolioRiskAgentBindingError):
            self.bundle(analytics=self.analytics(), reviewer_reports=(other_report,))

    def test_final_rc_07_reviewer_report_wrong_result_identity_rejected(self):
        report = review_research_scope(self.review_scope(target_digest_override=sha("7")))
        with self.assertRaises(PortfolioRiskAgentBindingError):
            self.bundle(analytics=self.analytics(), reviewer_reports=(report,))

    def test_final_rc_08_broken_cost_policy_spec_relation_fails(self):
        other_cost = CostPolicyVersion.create(
            policy_name="OTHER_COST",
            effective_from=date(2023, 8, 28),
            effective_to=None,
            commission_rate="0.001",
            minimum_commission="1",
            stamp_duty_sell_rate="0.001",
            market_rules=self.cost_policy.market_rules,
        )
        broken_spec = self._build_backtest_spec(self.cn_adjusted, other_cost)
        broken_result = DeterministicAshareBacktestEngine().run(broken_spec)
        with self.assertRaises(PortfolioRiskAgentBindingError):
            resolve_scenario_evidence(
                intent=self.intent,
                source=self.source,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec.to_reference(),
                risk_policy_set=self.policy_set,
                cost_policy=self.cost_policy,
                base_currency="CNY",
                target=self.cn_target,
                risk_adjusted=self.cn_adjusted,
                decision_report=self.cn_risk.decision_report,
                backtest_result=broken_result,
                backtest_spec=broken_spec,
                analytics=self.analytics_for(broken_result),
            )

    def test_final_rc_09_broken_decision_report_policy_set_relation_fails(self):
        variant_set = RiskPolicySetVersion.create(
            (
                RiskPolicyDefinition.pass_through(
                    code_version=self.runtime_identity.code_version,
                    runtime_profile_id=self.runtime_identity.runtime_profile_id,
                ),
            )
        )
        variant_risk = apply_risk(
            source_target=self.cn_target,
            policy_set=variant_set,
            runtime_identity=self.runtime_identity,
        )
        with self.assertRaises(PortfolioRiskAgentBindingError):
            resolve_scenario_evidence(
                intent=self.intent,
                source=self.source,
                binding=self.fixture.binding,
                construction_spec=self.construction_spec.to_reference(),
                risk_policy_set=self.policy_set,
                cost_policy=self.cost_policy,
                base_currency="CNY",
                target=self.cn_target,
                risk_adjusted=self.cn_adjusted,
                decision_report=variant_risk.decision_report,
                backtest_result=self.backtest_result,
                backtest_spec=self.backtest_spec,
                analytics=self.analytics(),
            )

    def test_final_rc_10_full_valid_canonical_chain_resolves_trusted(self):
        report = review_research_scope(self.review_scope())
        bundle = self.bundle(analytics=self.analytics(), reviewer_reports=(report,))
        self.assertIsInstance(bundle, ResolvedScenarioEvidenceBundle)
        self.assertEqual(bundle.binding_gaps, ())
        self.assertIsInstance(bundle.comparison_invariant, ScenarioComparisonInvariant)
        self.assertEqual(
            bundle.comparison_invariant.invariant_id,
            comparison_invariant_identity(**{
                name: getattr(bundle.comparison_invariant, name)
                for name in (
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
            }),
        )
        tampered = bundle.comparison_invariant.model_dump(mode="json")
        tampered["initial_cash"] = "999999"
        with self.assertRaises(ValidationError):
            ScenarioComparisonInvariant.model_validate(tampered)
        explanation = explain_scenario(bundle=bundle)
        self.assertEqual(explanation.status, "EVIDENCE_BOUND")
        view = bundle.backtest
        self.assertEqual(view.run_spec_id, self.backtest_spec.run_spec_id)


class PortfolioRiskFinalClosureRDTests(PortfolioRiskAgentFixture):
    """R-D final closure: comparison invariant covers the full execution/evaluation context."""

    def _assert_incomparable(self, left, right, dimension):
        comparison = compare_scenarios(left, right, objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(comparison.status, ComparisonStatus.INCOMPARABLE_CONTEXT)
        self.assertIn(dimension, comparison.context_mismatches)
        self.assertIsNone(comparison.ranking)
        self.assertEqual(comparison.metric_deltas, ())
        self.assertEqual(comparison.scenario_differences, ())

    def _bundle_with_spec(self, spec, *, result=None, analytics=None):
        result = result if result is not None else DeterministicAshareBacktestEngine().run(spec)
        return self.bundle(
            backtest_result=result,
            backtest_spec=spec,
            analytics=analytics if analytics is not None else self.analytics_for(result),
        )

    def test_final_rd_01_different_initial_cash_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        spec2 = self._build_backtest_spec(self.cn_adjusted, self.cost_policy, initial_cash="300000")
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "initial_cash")

    def test_final_rd_02_different_initial_holdings_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        spec2 = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            initial_holdings=(InitialHolding("000001.SZ", 100, DAY1),),
        )
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "initial_holdings")

    def test_final_rd_03_different_instruments_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        right = self._alternate_chain_bundle(
            universe_id="universe-3",
            universe_instruments=("000001.SZ", "000002.SZ", "000003.SZ"),
        )
        self._assert_incomparable(left, right, "instruments")

    def test_final_rd_04_different_session_range_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        sessions = (
            MarketSession(
                DAY1,
                True,
                tuple(
                    self._state_for(instrument_id, None)
                    for instrument_id in self.source.universe_instrument_ids
                ),
                (),
            ),
        )
        spec2 = self._build_backtest_spec(self.cn_adjusted, self.cost_policy, sessions=sessions)
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "session_dates")

    def test_final_rd_05_same_dates_different_market_state_inputs_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        spec2 = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            state_overrides={"000001.SZ": {"raw_close": "10.5"}},
        )
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "session_market_state_inputs")

    def test_final_rd_06_different_data_snapshot_refs_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        spec2 = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            reference_overrides={"SNAPSHOT": "9", "MARKET_DATA": "a"},
        )
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "exact_input_references")

    def test_final_rd_07_different_calendar_session_refs_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        spec2 = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            reference_overrides={"TRADING_CALENDAR": "b"},
        )
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "exact_input_references")

    def test_final_rd_08_different_corporate_action_refs_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        spec2 = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            reference_overrides={"CORPORATE_ACTIONS": "d"},
        )
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "exact_input_references")

    def test_final_rd_09_different_a_share_rule_profile_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        other_rule = AshareTradingRuleProfileVersion.create(
            profile_name="OTHER_A_SHARE_RULE_PROFILE",
            effective_from=date(2026, 7, 6),
            effective_to=None,
            settlement_days=1,
            board_rules=self.rule_profile.board_rules,
        )
        spec2 = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            rule_profile=other_rule,
        )
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "rule_profile_id")

    def test_final_rd_10_different_execution_timing_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        other_timing = ExecutionTimingProfileVersion.create(
            profile_name="OTHER_EXECUTION_TIMING_PROFILE",
            effective_from=date(2026, 7, 6),
            effective_to=None,
            market_timezone="Asia/Shanghai",
            raw_open_eligibility_cutoff_local_time="09:15:00",
            raw_open_execution_local_time="09:26:00",
        )
        spec2 = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            timing_profile=other_timing,
        )
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "execution_timing_profile_id")

    def test_final_rd_11_different_runtime_identity_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        other_runtime = RuntimeIdentity(
            code_version="git:round5-r-test",
            runtime_profile_id="v3.portfolio-risk-agent/1.0.0",
            environment_fingerprint="other-environment-fingerprint",
        )
        spec2 = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            runtime_identity=other_runtime,
        )
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "runtime_identity")

    def test_final_rd_12_different_engine_version_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        spec2 = self._build_backtest_spec(
            self.cn_adjusted,
            self.cost_policy,
            engine_version="v3.a_share_daily_eod_engine/9.9.9",
        )
        right = self._bundle_with_spec(spec2)
        self._assert_incomparable(left, right, "engine_version")

    def test_final_rd_13_different_analytics_policy_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        other_policy = ResultAnalyticsPolicyVersion.create(
            profile_name="EXPLICIT_RESEARCH_ANALYTICS_V0",
            return_convention="SIMPLE_NAV_RETURN",
            annualization_sessions=365,
            volatility_ddof=1,
            risk_free_policy="ZERO_RISK_FREE_ASSUMPTION",
            risk_free_annual_rate="0",
            sortino_target="0",
            drawdown_convention="RUNNING_PEAK_TO_NAV",
            turnover_convention="GROSS_TRADED_NOTIONAL_OVER_ARITHMETIC_MEAN_DAILY_NAV",
            period_return_convention="PERIOD_END_OVER_PREVIOUS_PERIOD_END",
            missing_data_policy="FAIL_CLOSED_EXACT_SESSIONS",
            numeric_precision=12,
            numeric_rounding="ROUND_HALF_EVEN",
        )
        analytics2 = self.analytics_for(self.backtest_result, policy=other_policy)
        right = self.bundle(analytics=analytics2)
        self._assert_incomparable(left, right, "analytics_policy_id")

    def test_final_rd_14_different_benchmark_context_incomparable(self):
        left = self.bundle(analytics=self.analytics())
        benchmark2 = BenchmarkSeriesVersion.create(
            name="OTHER_BENCHMARK_SERIES",
            rows=(
                BenchmarkObservation(DAY1, "100"),
                BenchmarkObservation(DAY2, "101"),
            ),
            source_provenance_refs=(sha("e"),),
            alignment_policy="EXACT_SESSION_DATE_MATCH",
            truth_admission=PRE_ALPHA_CEILING,
        )
        analytics2 = self.analytics_for(self.backtest_result, benchmark=benchmark2)
        right = self.bundle(analytics=analytics2)
        self._assert_incomparable(left, right, "benchmark_series_id")

    def test_final_rd_15_different_construction_spec_comparable_treatment(self):
        left = self.bundle(analytics=self.analytics())
        other_spec = PortfolioConstructionSpecVersion.create(
            method=ConstructionMethod.EQUAL_WEIGHT_SELECTED,
            method_version="1.0.0",
            target_cash_weight="0.2",
            max_instrument_weight="1",
            runtime_identity=self.runtime_identity,
        )
        other_construction = DeterministicPortfolioConstruction().construct(
            intent=self.intent,
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            construction_spec=other_spec,
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.as_of,
            decision_time=self.decision_time,
            rebalance_time=self.rebalance_time,
            valid_until=self.valid_until,
        )
        other_target = TargetWeightVector.create(
            source=self.source,
            construction_spec=other_spec.to_reference(),
            evidence_refs=(
                other_construction.diagnostics.to_reference(),
                other_construction.provenance.to_reference(),
            ),
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.cn_rebalance - timedelta(hours=1),
            decision_time=self.cn_rebalance - timedelta(minutes=30),
            rebalance_time=self.cn_rebalance,
            valid_until=self.cn_valid_until,
            cash_weight="0.2",
            rows=(
                TargetWeightRow("000001.SZ", "0.4"),
                TargetWeightRow("000002.SZ", "0.4"),
            ),
        )
        other_risk = apply_risk(
            source_target=other_target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
        )
        other_adjusted = other_risk.adjusted_weights
        spec2 = self._build_backtest_spec(other_adjusted, self.cost_policy)
        result2 = DeterministicAshareBacktestEngine().run(spec2)
        right = resolve_scenario_evidence(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            construction_spec=other_spec.to_reference(),
            risk_policy_set=self.policy_set,
            cost_policy=self.cost_policy,
            base_currency="CNY",
            target=other_target,
            risk_adjusted=other_adjusted,
            decision_report=other_risk.decision_report,
            backtest_result=result2,
            backtest_spec=spec2,
            analytics=self.analytics_for(result2),
        )
        self.assertEqual(left.comparison_invariant.invariant_id, right.comparison_invariant.invariant_id)
        comparison = compare_scenarios(left, right, objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(comparison.status, ComparisonStatus.COMPARABLE)
        self.assertIn("construction_spec_version_id", comparison.scenario_differences)
        self.assertNotIn("portfolio_intent_id", comparison.scenario_differences)

    def test_final_rd_16_different_risk_policy_set_comparable_treatment(self):
        left = self.bundle(analytics=self.analytics())
        variant_set = RiskPolicySetVersion.create(
            (
                RiskPolicyDefinition.pass_through(
                    code_version=self.runtime_identity.code_version,
                    runtime_profile_id=self.runtime_identity.runtime_profile_id,
                ),
            )
        )
        variant_risk = apply_risk(
            source_target=self.cn_target,
            policy_set=variant_set,
            runtime_identity=self.runtime_identity,
        )
        variant_adjusted = variant_risk.adjusted_weights
        variant_spec = self._build_backtest_spec(variant_adjusted, self.cost_policy)
        variant_result = DeterministicAshareBacktestEngine().run(variant_spec)
        right = resolve_scenario_evidence(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec.to_reference(),
            risk_policy_set=variant_set,
            cost_policy=self.cost_policy,
            base_currency="CNY",
            target=self.cn_target,
            risk_adjusted=variant_adjusted,
            decision_report=variant_risk.decision_report,
            backtest_result=variant_result,
            backtest_spec=variant_spec,
            analytics=self.analytics_for(variant_result),
        )
        self.assertEqual(left.comparison_invariant.invariant_id, right.comparison_invariant.invariant_id)
        comparison = compare_scenarios(left, right, objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(comparison.status, ComparisonStatus.COMPARABLE)
        self.assertIn("risk_policy_set_version_id", comparison.scenario_differences)

    def test_final_rd_17_different_cost_policy_comparable_treatment(self):
        left = self.bundle(analytics=self.analytics())
        other_cost = CostPolicyVersion.create(
            policy_name="OTHER_COST",
            effective_from=date(2023, 8, 28),
            effective_to=None,
            commission_rate="0.001",
            minimum_commission="1",
            stamp_duty_sell_rate="0.001",
            market_rules=self.cost_policy.market_rules,
        )
        spec2 = self._build_backtest_spec(self.cn_adjusted, other_cost)
        result2 = DeterministicAshareBacktestEngine().run(spec2)
        right = resolve_scenario_evidence(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            construction_spec=self.construction_spec.to_reference(),
            risk_policy_set=self.policy_set,
            cost_policy=other_cost,
            base_currency="CNY",
            target=self.cn_target,
            risk_adjusted=self.cn_adjusted,
            decision_report=self.cn_risk.decision_report,
            backtest_result=result2,
            backtest_spec=spec2,
            analytics=self.analytics_for(result2),
        )
        self.assertEqual(left.comparison_invariant.invariant_id, right.comparison_invariant.invariant_id)
        comparison = compare_scenarios(left, right, objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(comparison.status, ComparisonStatus.COMPARABLE)
        self.assertIn("cost_policy_id", comparison.scenario_differences)
