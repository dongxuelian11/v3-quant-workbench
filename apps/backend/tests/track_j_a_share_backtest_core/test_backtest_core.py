from __future__ import annotations

import dataclasses
import inspect
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from round3_w0_weight_seam.test_weight_seam import WeightSeamFixture, sha
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.backtest_runtime import (
    AshareTradingRuleProfileVersion,
    BacktestContractError,
    BacktestRunSpec,
    Board,
    BoardTradingRule,
    CorporateAction,
    CorporateActionType,
    CostPolicyVersion,
    DailyMarketState,
    DeterministicAshareBacktestEngine,
    DiagnosticCode,
    ExactInputReference,
    ExecutionTimingProfileVersion,
    ExpiredScheduledWeightsError,
    InitialHolding,
    InstrumentDefinition,
    MarketSession,
    MarketCostRule,
    ScheduledWeights,
    Side,
    UnsupportedCorporateActionError,
    cn_a_share_2023_08_28_cost_policy,
    cn_a_share_2026_07_06_execution_timing_profile,
    cn_a_share_2026_07_06_rule_profile,
)
from v3_backend.domain.weights import RiskAdjustedWeightVector, TargetWeightRow, TargetWeightVector


DAY1 = date(2026, 7, 7)
DAY2 = date(2026, 7, 8)
CN = ZoneInfo("Asia/Shanghai")


class BacktestCoreGoldenTests(WeightSeamFixture):
    def risk_vector(
        self,
        rows=(TargetWeightRow("000001.SZ", "0.9"),),
        cash="0.1",
        *,
        rebalance_at=None,
        valid_until=None,
    ):
        rebalance_at = rebalance_at or datetime(2026, 7, 7, 8, 0, tzinfo=CN)
        valid_until = valid_until or datetime(2026, 7, 8, 15, 0, tzinfo=CN)
        target = TargetWeightVector.create(
            source=self.source,
            construction_spec=self.construction,
            evidence_refs=self.evidence,
            runtime_identity=self.runtime,
            base_currency="CNY",
            as_of=rebalance_at - timedelta(hours=1),
            decision_time=rebalance_at - timedelta(minutes=30),
            rebalance_time=rebalance_at,
            valid_until=valid_until,
            cash_weight=cash,
            rows=tuple(rows),
        )
        return RiskAdjustedWeightVector.create(
            source_target=target,
            risk_application=self.risk_receipt(target),
            runtime_identity=self.runtime,
            cash_weight=cash,
            rows=tuple(rows),
        )

    @staticmethod
    def state(
        instrument_id,
        price="10",
        close=None,
        **overrides,
    ):
        return DailyMarketState(
            instrument_id,
            price,
            price if close is None else close,
            **overrides,
        )

    def session(self, day=DAY1, *, closed=False, actions=(), overrides=None):
        overrides = overrides or {}
        states = tuple(
            self.state(instrument_id, **overrides.get(instrument_id, {}))
            for instrument_id in self.source.universe_instrument_ids
        )
        return MarketSession(day, not closed, states, tuple(actions))

    @staticmethod
    def market_rules(*, bse_rate="0.000125", effective_from=date(2023, 8, 28), effective_to=None):
        exchange_rates = {
            Board.SSE_MAIN: "0.0000341",
            Board.SSE_STAR: "0.0000341",
            Board.SZSE_MAIN: "0.0000341",
            Board.SZSE_CHINEXT: "0.0000341",
            Board.BSE: bse_rate,
        }
        return tuple(
            MarketCostRule(board, effective_from, effective_to, "0.00001", rate, f"OFFICIAL_{board.value}_{effective_from.isoformat()}")
            for board, rate in exchange_rates.items()
        )

    @classmethod
    def cost(cls, *, commission="0.0003", minimum="5", stamp="0.0005", market_rules=None, effective_from=date(2023, 8, 28), effective_to=None):
        return CostPolicyVersion.create(
            policy_name=f"TEST_COST_{commission}_{minimum}_{stamp}",
            effective_from=effective_from,
            effective_to=effective_to,
            commission_rate=commission,
            minimum_commission=minimum,
            stamp_duty_sell_rate=stamp,
            market_rules=tuple(market_rules or cls.market_rules()),
        )

    def spec(
        self,
        *,
        vectors=None,
        sessions=None,
        initial_cash="100000",
        initial_holdings=(),
        cost=None,
        rules=None,
        timing=None,
        board_overrides=None,
    ):
        vectors = vectors or (self.risk_vector(),)
        normalized_vectors = tuple(item[1] if isinstance(item, tuple) else item for item in vectors)
        schedule = tuple(ScheduledWeights(vector.source_target.rebalance_time, vector) for vector in normalized_vectors)
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
            initial_cash=initial_cash,
            initial_holdings=tuple(initial_holdings),
            instruments=tuple(
                InstrumentDefinition(
                    instrument_id,
                    (board_overrides or {}).get(instrument_id, Board.SZSE_MAIN if instrument_id.endswith(".SZ") else Board.SSE_MAIN),
                )
                for instrument_id in self.source.universe_instrument_ids
            ),
            sessions=tuple(sessions or (self.session(),)),
            schedule=schedule,
            rule_profile=rules or cn_a_share_2026_07_06_rule_profile(),
            cost_policy=cost or self.cost(),
            execution_timing_profile=timing or cn_a_share_2026_07_06_execution_timing_profile(),
            exact_references=refs,
            runtime_identity=self.runtime,
        )

    def run_engine(self, **kwargs):
        return DeterministicAshareBacktestEngine().run(self.spec(**kwargs))

    def test_01_simple_buy_hold_uses_canonical_w0_and_raw_price(self):
        vector = self.risk_vector((TargetWeightRow("000001.SZ", "0.5"),), "0.5")
        result = self.run_engine(vectors=((DAY1, vector),))
        self.assertEqual(len(result.fills), 1)
        self.assertIs(result.fills[0].side, Side.BUY)
        self.assertEqual(result.fills[0].raw_price, "10")
        self.assertEqual(result.target_quantity_vectors[0].source_weight_vector_id, vector.risk_adjusted_weight_vector_id)
        self.assertEqual(result.nav[-1].nav, "99982.79")

    def test_02_same_day_sell_is_rejected_by_t_plus_one(self):
        cash = self.risk_vector((), "1")
        result = self.run_engine(
            vectors=(cash,),
            initial_cash="0",
            initial_holdings=(InitialHolding("000001.SZ", 100, DAY1),),
        )
        self.assertEqual(result.fills, ())
        self.assertIn(DiagnosticCode.NO_SELLABLE_QUANTITY, {item.code for item in result.diagnostics})

    def test_03_next_day_sell_is_allowed(self):
        cash_day1 = self.risk_vector((), "1")
        cash_day2 = self.risk_vector((), "1", rebalance_at=datetime(2026, 7, 7, 10, 0, tzinfo=CN))
        result = self.run_engine(
            vectors=(cash_day1, cash_day2),
            sessions=(self.session(DAY1), self.session(DAY2)),
            initial_cash="0",
            initial_holdings=(InitialHolding("000001.SZ", 100, DAY1),),
        )
        self.assertEqual([fill.side for fill in result.fills], [Side.SELL])

    def test_04_lot_rounding_and_odd_lot_liquidation(self):
        vector = self.risk_vector((TargetWeightRow("000001.SZ", "0.0123"),), "0.9877")
        result = self.run_engine(vectors=((DAY1, vector),))
        self.assertEqual(result.target_quantity_vectors[0].rows[0].target_quantity, 100)
        self.assertEqual(result.target_quantity_vectors[0].rows[0].unrounded_quantity, 123)
        self.assertEqual(result.target_quantity_vectors[0].rows[0].planning_code, "LOT_ROUNDED_RESIDUAL")
        odd = self.run_engine(
            vectors=((DAY1, self.risk_vector((), "1")),),
            initial_cash="0",
            initial_holdings=(InitialHolding("000001.SZ", 150, DAY1 - timedelta(days=1)),),
        )
        self.assertEqual(odd.fills[0].quantity, 150)

    def test_05_closed_calendar_and_suspension_produce_no_fill(self):
        closed = self.run_engine(sessions=(self.session(closed=True),))
        self.assertEqual(closed.orders, ())
        suspended = self.run_engine(
            sessions=(self.session(overrides={"000001.SZ": {"suspended": True}}),)
        )
        self.assertEqual(suspended.fills, ())
        self.assertEqual(suspended.diagnostics[0].code, DiagnosticCode.SUSPENDED)

    def test_06_limit_up_buy_is_blocked_but_explicit_no_limit_session_allows(self):
        blocked = self.run_engine(sessions=(self.session(overrides={"000001.SZ": {"at_limit_up_open": True}}),))
        self.assertEqual(blocked.fills, ())
        self.assertEqual(blocked.diagnostics[0].code, DiagnosticCode.LIMIT_UP_BUY_BLOCKED)
        allowed = self.run_engine(sessions=(self.session(overrides={"000001.SZ": {"at_limit_up_open": True, "no_price_limit_session": True}}),))
        self.assertEqual(len(allowed.fills), 1)

    def test_07_limit_down_sell_is_blocked(self):
        result = self.run_engine(
            vectors=((DAY1, self.risk_vector((), "1")),),
            initial_cash="0",
            initial_holdings=(InitialHolding("000001.SZ", 100, DAY1 - timedelta(days=1)),),
            sessions=(self.session(overrides={"000001.SZ": {"at_limit_down_open": True}}),),
        )
        self.assertEqual(result.fills, ())
        self.assertEqual(result.diagnostics[0].code, DiagnosticCode.LIMIT_DOWN_SELL_BLOCKED)

    def test_08_fees_tax_cash_and_ledgers_reconcile(self):
        buy = self.risk_vector((TargetWeightRow("000001.SZ", "0.5"),), "0.5")
        cash = self.risk_vector((), "1", rebalance_at=datetime(2026, 7, 7, 10, 0, tzinfo=CN))
        result = self.run_engine(vectors=(buy, cash), sessions=(self.session(DAY1), self.session(DAY2)))
        self.assertEqual(result.fills[0].costs.stamp_duty, "0")
        self.assertGreater(Decimal(result.fills[1].costs.stamp_duty), 0)
        self.assertEqual(Decimal(result.cash_ledger[-1].balance_after), Decimal(result.nav[-1].cash))
        self.assertEqual(sum(entry.quantity_delta for entry in result.position_ledger), 0)

    def test_09_insufficient_cash_has_explicit_residual_diagnostic(self):
        fully_invested = self.risk_vector((TargetWeightRow("000001.SZ", "1"),), "0")
        result = self.run_engine(initial_cash="1000", vectors=((DAY1, fully_invested),))
        self.assertEqual(result.fills, ())
        self.assertIn(result.diagnostics[0].code, {DiagnosticCode.PARTIAL_CASH, DiagnosticCode.BELOW_BUY_LOT})
        self.assertEqual(result.diagnostics[0].filled_quantity, 0)

    def test_10_restricted_and_nontradable_are_explicit_inputs(self):
        restricted = self.run_engine(sessions=(self.session(overrides={"000001.SZ": {"buy_restricted": True, "restricted_security": True}}),))
        self.assertEqual(restricted.diagnostics[0].code, DiagnosticCode.BUY_RESTRICTED)
        nontradable = self.run_engine(sessions=(self.session(overrides={"000001.SZ": {"tradable": False}}),))
        self.assertEqual(nontradable.diagnostics[0].code, DiagnosticCode.NOT_TRADABLE)

    def test_11_supported_cash_and_bonus_corporate_actions_are_separate(self):
        actions = (
            CorporateAction("div-1", "000001.SZ", DAY1, CorporateActionType.CASH_DIVIDEND, cash_per_share="0.1"),
            CorporateAction("split-1", "000001.SZ", DAY1, CorporateActionType.BONUS_OR_SPLIT, ratio_numerator=2),
        )
        result = self.run_engine(
            vectors=((DAY1, self.risk_vector((), "1")),),
            initial_cash="0",
            initial_holdings=(InitialHolding("000001.SZ", 100, DAY1 - timedelta(days=1)),),
            sessions=(self.session(actions=actions),),
        )
        dividend = next(entry for entry in result.cash_ledger if entry.reference_id == "div-1")
        self.assertEqual(dividend.amount, "10")
        self.assertEqual(result.fills[0].quantity, 200)

    def test_12_unsupported_corporate_action_fails_closed(self):
        action = CorporateAction("rights-1", "000001.SZ", DAY1, CorporateActionType.RIGHTS_ISSUE)
        with self.assertRaisesRegex(UnsupportedCorporateActionError, "NOT_SUPPORTED"):
            self.run_engine(sessions=(self.session(actions=(action,)),))

    def test_13_deterministic_rerun_has_identical_wire_and_ids(self):
        spec = self.spec()
        first = DeterministicAshareBacktestEngine().run(spec)
        second = DeterministicAshareBacktestEngine().run(spec)
        self.assertEqual(first, second)
        self.assertEqual(first.to_wire(), second.to_wire())

    def test_14_rule_profile_version_changes_run_and_result_identity(self):
        base = cn_a_share_2026_07_06_rule_profile()
        altered_rules = tuple(
            BoardTradingRule(item.board, item.buy_minimum_quantity, 50 if item.board is Board.SZSE_MAIN else item.buy_quantity_step, item.normal_price_limit_rate, item.restricted_price_limit_rate, item.price_tick, item.sell_odd_lot_in_one_order)
            for item in base.board_rules
        )
        altered = AshareTradingRuleProfileVersion.create(profile_name="TEST_ALTERNATE_LOT_V1", effective_from=DAY1, effective_to=None, settlement_days=1, board_rules=altered_rules)
        first_spec = self.spec(rules=base)
        second_spec = self.spec(rules=altered)
        self.assertNotEqual(first_spec.run_spec_id, second_spec.run_spec_id)
        self.assertNotEqual(DeterministicAshareBacktestEngine().run(first_spec).result_id, DeterministicAshareBacktestEngine().run(second_spec).result_id)

    def test_15_cost_policy_changes_cash_and_identity(self):
        zero = self.cost(commission="0", minimum="0", stamp="0")
        charged = self.cost()
        zero_spec = self.spec(cost=zero)
        charged_spec = self.spec(cost=charged)
        zero_result = DeterministicAshareBacktestEngine().run(zero_spec)
        charged_result = DeterministicAshareBacktestEngine().run(charged_spec)
        self.assertNotEqual(zero_spec.run_spec_id, charged_spec.run_spec_id)
        self.assertGreater(Decimal(zero_result.nav[-1].nav), Decimal(charged_result.nav[-1].nav))

    def test_16_pre_alpha_truth_is_propagated_and_never_promoted(self):
        spec = self.spec()
        result = DeterministicAshareBacktestEngine().run(spec)
        self.assertEqual(spec.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(result.truth_admission, PRE_ALPHA_CEILING)

    def test_17_w0_vector_is_immutable_and_missing_close_fails_closed(self):
        vector = self.risk_vector()
        before = vector.to_wire()
        DeterministicAshareBacktestEngine().run(self.spec(vectors=((DAY1, vector),)))
        self.assertEqual(vector.to_wire(), before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            vector.cash_weight = "1"
        session = self.session(overrides={"000001.SZ": {"close": None}})
        # Explicit None is normally converted by the helper; construct the missing value directly.
        states = tuple(DailyMarketState(x.instrument_id, x.raw_open, None if x.instrument_id == "000001.SZ" else x.raw_close) for x in session.states)
        with self.assertRaisesRegex(BacktestContractError, "missing close"):
            self.run_engine(sessions=(MarketSession(DAY1, True, states),))

    def test_18_no_live_broker_or_network_capability(self):
        import v3_backend.domain.backtest_runtime.engine as engine_module
        import v3_backend.domain.backtest_runtime.model as model_module

        source = inspect.getsource(engine_module) + inspect.getsource(model_module)
        for forbidden in ("import socket", "import requests", "broker_connection", "live_trading", "paper_trading"):
            self.assertNotIn(forbidden, source.lower())

    def test_19_before_open_is_eligible_for_same_session_raw_open(self):
        vector = self.risk_vector(rebalance_at=datetime(2026, 7, 7, 9, 14, 59, tzinfo=CN))
        result = self.run_engine(vectors=(vector,))
        self.assertEqual(result.target_quantity_vectors[0].session_date, DAY1)
        self.assertEqual(result.target_quantity_vectors[0].source_weight_vector_id, vector.risk_adjusted_weight_vector_id)

    def test_20_after_open_information_waits_for_next_open(self):
        vector = self.risk_vector(rebalance_at=datetime(2026, 7, 7, 15, 0, tzinfo=CN))
        result = self.run_engine(vectors=(vector,), sessions=(self.session(DAY1), self.session(DAY2)))
        self.assertEqual(tuple(item.session_date for item in result.target_quantity_vectors), (DAY2,))
        self.assertEqual(tuple(fill.session_date for fill in result.fills), (DAY2,))

    def test_21_exactly_at_eligibility_cutoff_waits_for_next_open(self):
        vector = self.risk_vector(rebalance_at=datetime(2026, 7, 7, 9, 15, tzinfo=CN))
        result = self.run_engine(vectors=(vector,), sessions=(self.session(DAY1), self.session(DAY2)))
        self.assertEqual(tuple(item.session_date for item in result.target_quantity_vectors), (DAY2,))

    def test_22_schedule_must_exactly_bind_w0_target_rebalance_time(self):
        vector = self.risk_vector()
        with self.assertRaisesRegex(BacktestContractError, "exactly equal"):
            ScheduledWeights(vector.source_target.rebalance_time + timedelta(seconds=1), vector)

    def test_23_expired_vector_fails_at_raw_open_execution_timestamp(self):
        vector = self.risk_vector(valid_until=datetime(2026, 7, 7, 9, 20, tzinfo=CN))
        with self.assertRaisesRegex(ExpiredScheduledWeightsError, "expires"):
            self.run_engine(vectors=(vector,))
        boundary = self.risk_vector(valid_until=datetime(2026, 7, 7, 9, 25, tzinfo=CN))
        self.assertEqual(len(self.run_engine(vectors=(boundary,)).target_quantity_vectors), 1)

    def test_24_closed_session_does_not_consume_eligible_vector(self):
        vector = self.risk_vector()
        result = self.run_engine(vectors=(vector,), sessions=(self.session(DAY1, closed=True), self.session(DAY2)))
        self.assertEqual(tuple(item.session_date for item in result.target_quantity_vectors), (DAY2,))

    def test_25_latest_eligible_vector_wins_once_per_session_open(self):
        older = self.risk_vector((TargetWeightRow("000001.SZ", "0.2"),), "0.8", rebalance_at=datetime(2026, 7, 7, 7, 0, tzinfo=CN))
        latest = self.risk_vector((TargetWeightRow("000001.SZ", "0.5"),), "0.5", rebalance_at=datetime(2026, 7, 7, 8, 0, tzinfo=CN))
        result = self.run_engine(vectors=(older, latest))
        self.assertEqual(len(result.target_quantity_vectors), 1)
        self.assertEqual(result.target_quantity_vectors[0].source_weight_vector_id, latest.risk_adjusted_weight_vector_id)

    def test_26_w0_timestamp_and_timing_profile_are_run_identity_inputs(self):
        first = self.risk_vector(rebalance_at=datetime(2026, 7, 7, 8, 0, tzinfo=CN))
        second = self.risk_vector(rebalance_at=datetime(2026, 7, 7, 8, 1, tzinfo=CN))
        first_spec = self.spec(vectors=(first,))
        second_spec = self.spec(vectors=(second,))
        self.assertNotEqual(first_spec.run_spec_id, second_spec.run_spec_id)
        self.assertNotEqual(
            DeterministicAshareBacktestEngine().run(first_spec).result_id,
            DeterministicAshareBacktestEngine().run(second_spec).result_id,
        )
        altered_timing = ExecutionTimingProfileVersion.create(
            profile_name="TEST_RAW_OPEN_0910_V1",
            effective_from=date(2026, 7, 6),
            effective_to=None,
            market_timezone="Asia/Shanghai",
            raw_open_eligibility_cutoff_local_time="09:10:00",
            raw_open_execution_local_time="09:25:00",
        )
        altered_spec = self.spec(vectors=(first,), timing=altered_timing)
        self.assertNotEqual(first_spec.run_spec_id, altered_spec.run_spec_id)
        self.assertNotEqual(
            DeterministicAshareBacktestEngine().run(first_spec).result_id,
            DeterministicAshareBacktestEngine().run(altered_spec).result_id,
        )

    def test_27_market_scoped_official_rates_distinguish_sse_szse_and_bse(self):
        policy = cn_a_share_2023_08_28_cost_policy(commission_rate="0", minimum_commission="0")
        sse = policy.calculate(Board.SSE_MAIN, Side.BUY, Decimal("100000"), DAY1)
        szse = policy.calculate(Board.SZSE_MAIN, Side.BUY, Decimal("100000"), DAY1)
        bse = policy.calculate(Board.BSE, Side.BUY, Decimal("100000"), DAY1)
        self.assertEqual((sse.transfer_fee, sse.exchange_fee), ("1", "3.41"))
        self.assertEqual((szse.transfer_fee, szse.exchange_fee), ("1", "3.41"))
        self.assertEqual((bse.transfer_fee, bse.exchange_fee), ("1", "12.5"))

    def test_28_mixed_sse_bse_run_uses_each_instruments_board_rule(self):
        rows = (TargetWeightRow("000001.SZ", "0.4"), TargetWeightRow("000002.SZ", "0.4"))
        vector = self.risk_vector(rows, "0.2")
        result = self.run_engine(
            vectors=(vector,),
            cost=self.cost(commission="0", minimum="0", stamp="0"),
            board_overrides={"000001.SZ": Board.SSE_MAIN, "000002.SZ": Board.BSE},
        )
        costs = {fill.instrument_id: fill.costs.exchange_fee for fill in result.fills}
        self.assertEqual(costs["000001.SZ"], "1.36")
        self.assertEqual(costs["000002.SZ"], "5")

    def test_29_missing_or_overlapping_market_cost_rule_fails_closed(self):
        missing = tuple(rule for rule in self.market_rules() if rule.board is not Board.SZSE_MAIN)
        with self.assertRaisesRegex(BacktestContractError, "exactly one rule"):
            self.spec(cost=self.cost(market_rules=missing))
        overlap = self.market_rules() + (
            MarketCostRule(Board.SZSE_MAIN, date(2026, 1, 1), None, "0.00001", "0.0000341", "OVERLAP_TEST"),
        )
        with self.assertRaisesRegex(BacktestContractError, "found 2"):
            self.spec(cost=self.cost(market_rules=overlap))

    def test_30_market_cost_effective_period_is_identity_and_cross_boundary_input(self):
        bounded = self.cost(market_rules=self.market_rules(effective_to=DAY1), effective_to=DAY1)
        unbounded = self.cost()
        self.assertNotEqual(bounded.policy_id, unbounded.policy_id)
        old_rules = self.market_rules(bse_rate="0.000125", effective_from=date(2023, 8, 28), effective_to=DAY1)
        new_rules = self.market_rules(bse_rate="0.0002", effective_from=DAY2, effective_to=None)
        cross = self.cost(market_rules=old_rules + new_rules)
        self.assertEqual(cross.calculate(Board.BSE, Side.BUY, Decimal("100000"), DAY1).exchange_fee, "12.5")
        self.assertEqual(cross.calculate(Board.BSE, Side.BUY, Decimal("100000"), DAY2).exchange_fee, "20")

    def test_31_fee_ledger_carries_exact_breakdown_and_financial_conventions(self):
        result = self.run_engine()
        fee_entry = next(entry for entry in result.cash_ledger if entry.kind.value == "FEE")
        self.assertEqual(fee_entry.cost_breakdown, result.fills[0].costs)
        minimum = self.cost().calculate(Board.SZSE_MAIN, Side.BUY, Decimal("100"), DAY1)
        self.assertEqual(minimum.commission, "5")
        buy = self.cost().calculate(Board.SZSE_MAIN, Side.BUY, Decimal("100000"), DAY1)
        sell = self.cost().calculate(Board.SZSE_MAIN, Side.SELL, Decimal("100000"), DAY1)
        self.assertEqual(buy.stamp_duty, "0")
        self.assertEqual(sell.stamp_duty, "50")


if __name__ == "__main__":
    unittest.main()
