from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from track_f_strategy_runtime.helpers import build_runtime_fixture
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
    UserConfirmation,
    apply_confirmed_backtest_run,
    apply_confirmed_portfolio_construct,
    apply_confirmed_risk_apply,
    build_portfolio_risk_proposal,
    build_scenario_bundle,
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
)
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
    ValidationState,
)
from v3_backend.domain.backtest_runtime import (
    BacktestRunSpec,
    Board,
    CostPolicyVersion,
    DailyMarketState,
    DeterministicAshareBacktestEngine,
    ExactInputReference,
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
from v3_backend.domain.strategies import DeterministicStrategyEvaluator
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
ENGINE_VERSION = "v3.a_share_daily_eod_engine/0.2.0"


def sha(character: str) -> str:
    return character * 64


def provenance(task: str = "round5-r/1") -> AgentProvenance:
    return AgentProvenance(
        agent_kind=AgentKind.RESEARCH,
        sdk_version="2.27.0",
        model_name="deterministic-test-model",
        provider_name="test-provider",
        prompt_version=task,
        instruction_version="round5-r/1",
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
        # CN-window vector chain for the J engine
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
        self.backtest_result = self._run_backtest()

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

    def _run_backtest(self):
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
        )
        sessions = tuple(
            MarketSession(
                day,
                True,
                tuple(
                    DailyMarketState(instrument_id, "10", "10")
                    for instrument_id in self.source.universe_instrument_ids
                ),
                (),
            )
            for day in (DAY1, DAY2)
        )
        spec = BacktestRunSpec.create(
            initial_cash="100000",
            initial_holdings=(),
            instruments=tuple(
                InstrumentDefinition(
                    instrument_id,
                    Board.SZSE_MAIN if instrument_id.endswith(".SZ") else Board.SSE_MAIN,
                )
                for instrument_id in self.source.universe_instrument_ids
            ),
            sessions=sessions,
            schedule=(ScheduledWeights(self.cn_adjusted.source_target.rebalance_time, self.cn_adjusted),),
            rule_profile=self.rule_profile,
            cost_policy=self.cost_policy,
            execution_timing_profile=self.timing_profile,
            exact_references=refs,
            runtime_identity=self.runtime_identity,
        )
        return DeterministicAshareBacktestEngine().run(spec)

    def _backtest_spec(self) -> BacktestRunSpec:
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
        )
        return BacktestRunSpec.create(
            initial_cash="100000",
            initial_holdings=(),
            instruments=tuple(
                InstrumentDefinition(
                    instrument_id,
                    Board.SZSE_MAIN if instrument_id.endswith(".SZ") else Board.SSE_MAIN,
                )
                for instrument_id in self.source.universe_instrument_ids
            ),
            sessions=tuple(
                MarketSession(
                    day,
                    True,
                    tuple(
                        DailyMarketState(instrument_id, "10", "10")
                        for instrument_id in self.source.universe_instrument_ids
                    ),
                    (),
                )
                for day in (DAY1, DAY2)
            ),
            schedule=(ScheduledWeights(self.cn_adjusted.source_target.rebalance_time, self.cn_adjusted),),
            rule_profile=self.rule_profile,
            cost_policy=self.cost_policy,
            execution_timing_profile=self.timing_profile,
            exact_references=refs,
            runtime_identity=self.runtime_identity,
        )

    def _backtest_spec_with_state(self, instrument_id: str, **overrides) -> BacktestRunSpec:
        sessions = tuple(
            MarketSession(
                day,
                True,
                tuple(
                    DailyMarketState(
                        name,
                        "10",
                        "10",
                        **({"suspended": True} if name == instrument_id else {}),
                    )
                    for name in self.source.universe_instrument_ids
                ),
                (),
            )
            for day in (DAY1, DAY2)
        )
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
        )
        return BacktestRunSpec.create(
            initial_cash="100000",
            initial_holdings=(),
            instruments=tuple(
                InstrumentDefinition(
                    name,
                    Board.SZSE_MAIN if name.endswith(".SZ") else Board.SSE_MAIN,
                )
                for name in self.source.universe_instrument_ids
            ),
            sessions=sessions,
            schedule=(ScheduledWeights(self.cn_adjusted.source_target.rebalance_time, self.cn_adjusted),),
            rule_profile=self.rule_profile,
            cost_policy=self.cost_policy,
            execution_timing_profile=self.timing_profile,
            exact_references=refs,
            runtime_identity=self.runtime_identity,
        )

    def analytics(self):
        return DeterministicResultAnalyticsEngine().analyze(
            self.backtest_result,
            SourceResultBinding(self.backtest_result.result_id, self.backtest_result.content_sha256),
            ResultAnalyticsPolicyVersion.a_share_daily_research_v0(),
        )

    def review_scope(self):
        result_digest = self.backtest_result.content_sha256
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

    def bundle(self, *, cost_policy: CostPolicyVersion | None = None, policy_set: RiskPolicySetVersion | None = None, analytics=None, reviewer_reports=()):
        intent_view = read_portfolio_intent(
            intent=self.intent,
            source=self.source,
            binding=self.fixture.binding,
            base_currency="CNY",
        )
        policy_view = read_risk_policy_set(policy_set or self.policy_set)
        cost_view = read_cost_policy(cost_policy or self.cost_policy)
        target_view = read_target_weight_evidence(self.cn_target)
        adjusted_view = read_risk_adjusted_evidence(self.cn_adjusted, self.cn_risk.decision_report)
        result_view = read_backtest_result(self.backtest_result, engine_version=ENGINE_VERSION)
        analytics_view = read_result_analytics(analytics) if analytics is not None else None
        return build_scenario_bundle(
            intent=intent_view,
            construction_spec=self.construction_spec.to_reference(),
            risk_policy_set=policy_view,
            cost_policy=cost_view,
            target=target_view,
            risk_adjusted=adjusted_view,
            backtest=result_view,
            analytics=analytics_view,
            reviewer_reports=reviewer_reports,
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
        self.assertEqual(draft.draft_kind, PortfolioRiskDraftKind.PORTFOLIO_CONSTRUCT)

    def test_02_exact_portfolio_intent_required(self):
        with self.assertRaises(TypeError):
            read_portfolio_intent(
                intent="not-a-PortfolioIntent",
                source=self.source,
                binding=self.fixture.binding,
                base_currency="CNY",
            )
        fake = self.intent.__class__  # type: ignore[assignment]
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
        self.assertIsNotNone(fake)

    def test_03_exact_risk_policy_set_required_for_risk(self):
        context = self.context(source_target=self.target)
        with self.assertRaises(TypeError):
            draft_risk_apply(context=context, source_target="not-a-vector", provenance=provenance())
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
        draft = draft_risk_apply(context=context, source_target=self.target, provenance=provenance())
        confirmation = self.confirmation(draft, "RISK_APPLY")
        with self.assertRaises(PortfolioRiskApplicationError):
            apply_confirmed_risk_apply(
                draft=draft,
                confirmation=confirmation,
                source_target=self.target,
                policy_set=mismatched,
                runtime_identity=other_runtime,
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
        draft = draft_risk_apply(context=context, source_target=self.target, provenance=provenance())
        confirmation = self.confirmation(draft, "RISK_APPLY")
        with self.assertRaises(PortfolioRiskApplicationError):
            apply_confirmed_risk_apply(
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
                risk_backend=context.risk_backend,
                risk_code_version=context.risk_code_version,
                risk_runtime_profile_id=context.risk_runtime_profile_id,
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
            risk_backend=context.risk_backend,
            risk_code_version=context.risk_code_version,
            risk_runtime_profile_id=context.risk_runtime_profile_id,
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
        for name in tools.visible_tool_names:
            self.assertNotIn("risk_adjusted_weight_vector", name.replace("get_risk_adjusted_evidence", ""))
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
        explanation = explain_scenario(bundle=self.bundle(cost_policy=other_cost))
        self.assertTrue(any("OTHER_COST" in statement for statement in explanation.cost_statements))
        self.assertIn(other_cost.policy_id, explanation.cited_evidence_refs)

    def test_11_backtest_draft_exact_inputs(self):
        context = self.context(source_target=self.cn_target, risk_adjusted=self.cn_adjusted)
        draft = draft_backtest_run(
            context=context,
            risk_adjusted=self.cn_adjusted,
            initial_cash="100000",
            engine_version=ENGINE_VERSION,
            provenance=provenance(),
        )
        self.assertEqual(draft.payload.risk_adjusted_weight_vector_id, self.cn_adjusted.risk_adjusted_weight_vector_id)
        self.assertEqual(draft.payload.effective_at, self.cn_rebalance)
        self.assertEqual(draft.payload.requested_cost_policy_id, self.cost_policy.policy_id)
        self.assertEqual(draft.payload.requested_rule_profile_id, self.rule_profile.profile_id)
        self.assertEqual(draft.payload.requested_execution_timing_profile_id, self.timing_profile.profile_id)
        with self.assertRaises(PortfolioRiskAgentBindingError):
            draft_backtest_run(
                context=self.context(source_target=self.cn_target),
                risk_adjusted=self.cn_adjusted,
                initial_cash="100000",
                engine_version=ENGINE_VERSION,
                provenance=provenance(),
            )
        bad_context = self.context(source_target=self.cn_target, risk_adjusted=self.cn_adjusted)
        bad_draft = draft_backtest_run(
            context=bad_context,
            risk_adjusted=self.cn_adjusted,
            initial_cash="100000",
            engine_version="v3.a_share_daily_eod_engine/9.9.9",
            provenance=provenance(),
        )
        confirmation = self.confirmation(bad_draft, "BACKTEST_RUN")
        with self.assertRaises(PortfolioRiskApplicationError):
            apply_confirmed_backtest_run(draft=bad_draft, confirmation=confirmation, spec=self._backtest_spec())

    def test_12_comparison_context_exact(self):
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
        right = self.bundle(analytics=self.analytics(), cost_policy=other_cost)
        comparison = compare_scenarios(left, right, objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(comparison.status, ComparisonStatus.INCOMPARABLE_CONTEXT)
        self.assertIn("cost_policy_id", comparison.context_mismatches)
        self.assertIsNone(comparison.ranking)
        self.assertEqual(comparison.metric_deltas, ())
        same = compare_scenarios(left, self.bundle(analytics=self.analytics()), objective_metric="total_return", objective_direction="MAXIMIZE")
        self.assertEqual(same.status, ComparisonStatus.COMPARABLE)
        self.assertTrue(all(delta.status == "AVAILABLE" for delta in same.metric_deltas if delta.name == "total_return"))
        self.assertIsNotNone(same.ranking)

    def test_13_different_cost_policy_visible(self):
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
        self.assertEqual(other_view.commission_rate, "0.001")
        comparison = compare_scenarios(self.bundle(analytics=self.analytics()), self.bundle(analytics=self.analytics(), cost_policy=other_cost))
        self.assertIn("cost_policy_id", comparison.context_mismatches)

    def test_14_reviewer_evidence_exact_bound(self):
        report = review_research_scope(self.review_scope())
        view = read_reviewer_report(report)
        self.assertEqual(view.rule_set_id, report.rule_set_id)
        self.assertEqual(view.session_id, SESSION)
        self.assertEqual(view.target_ref_count, len(report.target_refs))
        draft = draft_review_run(
            target_refs=(self.backtest_result.result_id,),
            evidence_refs=(self.backtest_result.result_id, self.cost_policy.policy_id),
            rule_set_id=view.rule_set_id,
            provenance=provenance(),
        )
        self.assertEqual(draft.draft_kind, PortfolioRiskDraftKind.REVIEW_RUN)
        self.assertGreaterEqual(len(draft.payload.target_refs), 1)
        explanation = explain_scenario(bundle=self.bundle(analytics=self.analytics(), reviewer_reports=(view,)))
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
        with self.assertRaises(PortfolioRiskApplicationError):
            apply_confirmed_portfolio_construct(
                draft=draft,
                confirmation=UserConfirmation(
                    action="PORTFOLIO_CONSTRUCT",
                    draft_sha256="c" * 64,
                    confirmed_by="human-researcher-1",
                    confirmed_at=datetime(2026, 1, 5, 16, 0, tzinfo=timezone.utc),
                ),
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
            initial_cash="100000",
            engine_version=ENGINE_VERSION,
            provenance=provenance(),
        )
        confirmation = self.confirmation(draft, "BACKTEST_RUN")
        result = apply_confirmed_backtest_run(draft=draft, confirmation=confirmation, spec=self._backtest_spec())
        self.assertEqual(result.result_id, self.backtest_result.result_id)
        suspended = self._backtest_spec_with_state("000001.SZ", suspended=True)
        suspended_result = DeterministicAshareBacktestEngine().run(suspended)
        codes = {diagnostic.code.value for diagnostic in suspended_result.diagnostics}
        self.assertIn("SUSPENDED", codes)
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
        draft = draft_portfolio_construct(context=self.context(source_target=self.target), provenance=provenance())
        self.assertEqual(draft.payload.action, "PORTFOLIO_CONSTRUCT")
        from v3_backend.agents.portfolio_risk_agent import PortfolioRiskAgentDraft

        with self.assertRaises(ValidationError):
            PortfolioRiskAgentDraft.model_validate({**draft.model_dump(), "publish_authority": True})


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
                if candidate.get("task") in ("PORTFOLIO_CONSTRUCT_PROPOSAL", "RISK_APPLY_PROPOSAL", "BACKTEST_RUN_PROPOSAL"):
                    request = candidate
    if request is None:
        raise AssertionError("R structured request unavailable")
    if not has_return:
        return ModelResponse(parts=[ToolCallPart("get_portfolio_intent", {"portfolio_intent_id": request["portfolio_intent_id"]})])
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"rationale": "Exact PortfolioIntent supports a bounded scenario draft.", "next_action_proposals": ["review the exact construction draft before applying it"], "evidence_claims": ["ignored model-authored evidence claim"]})])


def proposal_without_tool(_messages: list[object], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"rationale": "Unsafe no-tool proposal.", "next_action_proposals": []})])


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

    def read_tools(self):
        return PortfolioRiskReadTools(
            intents=(read_portfolio_intent(intent=self.intent, source=self.source, binding=self.fixture.binding, base_currency="CNY"),),
            targets=(read_target_weight_evidence(self.target),),
            policy_sets=(read_risk_policy_set(self.policy_set),),
            adjusted=(read_risk_adjusted_evidence(self.adjusted, self.risk_result.decision_report),),
            cost_policies=(read_cost_policy(self.cost_policy),),
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

    def test_worker_risk_and_backtest_proposals(self):
        risk_context = self.context(source_target=self.target)
        risk_proposal = self.worker(proposal_model).run_risk_proposal(research_goal="clip", context=risk_context, source_target=self.target)
        self.assertEqual(risk_proposal.action_drafts[0].draft_kind, PortfolioRiskDraftKind.RISK_APPLY)
        backtest_context = self.context(source_target=self.cn_target, risk_adjusted=self.cn_adjusted)
        backtest_proposal = self.worker(proposal_model).run_backtest_proposal(
            research_goal="eod backtest",
            context=backtest_context,
            risk_adjusted=self.cn_adjusted,
            initial_cash="100000",
            engine_version=ENGINE_VERSION,
        )
        self.assertEqual(backtest_proposal.action_drafts[0].draft_kind, PortfolioRiskDraftKind.BACKTEST_RUN)
        self.assertEqual(backtest_proposal.action_drafts[0].payload.engine_version, ENGINE_VERSION)

    def test_read_tools_fail_closed_on_unknown_identity(self):
        tools = self.read_tools()
        tools.begin((("get_portfolio_intent", self.intent.portfolio_intent_id),))
        with self.assertRaises(PortfolioRiskAgentToolError):
            tools.get_target_weight_evidence(self.target.target_weight_vector_id)
        with self.assertRaises(PortfolioRiskAgentToolError):
            tools.get_portfolio_intent("unknown-intent")

    def test_user_confirmation_seam_end_to_end(self):
        context = self.context(source_target=self.target)
        construct_draft = draft_portfolio_construct(context=context, provenance=provenance())
        result = apply_confirmed_portfolio_construct(
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
        self.assertEqual(result.target.target_weight_vector_id, self.target.target_weight_vector_id)
        risk_draft = draft_risk_apply(context=self.context(source_target=self.target), source_target=self.target, provenance=provenance())
        risk_result = apply_confirmed_risk_apply(
            draft=risk_draft,
            confirmation=self.confirmation(risk_draft, "RISK_APPLY"),
            source_target=self.target,
            policy_set=self.policy_set,
            runtime_identity=self.runtime_identity,
        )
        self.assertEqual(risk_result.adjusted_weights.risk_adjusted_weight_vector_id, self.adjusted.risk_adjusted_weight_vector_id)
        backtest_draft = draft_backtest_run(
            context=self.context(source_target=self.cn_target, risk_adjusted=self.cn_adjusted),
            risk_adjusted=self.cn_adjusted,
            initial_cash="100000",
            engine_version=ENGINE_VERSION,
            provenance=provenance(),
        )
        backtest_result = apply_confirmed_backtest_run(
            draft=backtest_draft,
            confirmation=self.confirmation(backtest_draft, "BACKTEST_RUN"),
            spec=self._backtest_spec(),
        )
        self.assertEqual(backtest_result.result_id, self.backtest_result.result_id)

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
        self.assertEqual(draft.payload.left_analytics_id, view.analytics_id)
        report = review_research_scope(self.review_scope())
        reviewer_view = read_reviewer_report(report)
        explanation = explain_scenario(
            bundle=self.bundle(analytics=analytics, reviewer_reports=(reviewer_view,)),
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
