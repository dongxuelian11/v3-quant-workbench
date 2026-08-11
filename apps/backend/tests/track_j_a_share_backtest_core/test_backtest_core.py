from __future__ import annotations

import dataclasses
import inspect
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

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
    InitialHolding,
    InstrumentDefinition,
    MarketSession,
    ScheduledWeights,
    Side,
    UnsupportedCorporateActionError,
    cn_a_share_2026_07_06_rule_profile,
)
from v3_backend.domain.weights import RiskAdjustedWeightVector, TargetWeightRow


DAY1 = date(2026, 7, 7)
DAY2 = date(2026, 7, 8)


class BacktestCoreGoldenTests(WeightSeamFixture):
    def risk_vector(self, rows=(TargetWeightRow("000001.SZ", "0.9"),), cash="0.1"):
        target = self.target(rows=tuple(rows), cash_weight=cash)
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
    def cost(*, commission="0.0003", minimum="5", stamp="0.0005"):
        return CostPolicyVersion.create(
            policy_name=f"TEST_COST_{commission}_{minimum}_{stamp}",
            effective_from=date(2026, 7, 6),
            commission_rate=commission,
            minimum_commission=minimum,
            stamp_duty_sell_rate=stamp,
            transfer_fee_rate="0.00001",
            exchange_fee_rate="0.0000341",
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
    ):
        vectors = vectors or ((DAY1, self.risk_vector()),)
        schedule = tuple(
            ScheduledWeights(
                datetime.combine(day, datetime.min.time(), timezone.utc)
                + timedelta(hours=index + 1),
                vector,
            )
            for index, (day, vector) in enumerate(vectors)
        )
        refs = tuple(
            ExactInputReference(kind, kind.lower() + "-v1", sha(character), PRE_ALPHA_CEILING)
            for kind, character in (
                ("SNAPSHOT", "9"),
                ("MARKET_DATA", "a"),
                ("TRADING_CALENDAR", "b"),
                ("UNIVERSE", "c"),
                ("CORPORATE_ACTIONS", "d"),
            )
        )
        return BacktestRunSpec.create(
            initial_cash=initial_cash,
            initial_holdings=tuple(initial_holdings),
            instruments=tuple(
                InstrumentDefinition(
                    instrument_id,
                    Board.SZSE_MAIN if instrument_id.endswith(".SZ") else Board.SSE_MAIN,
                )
                for instrument_id in self.source.universe_instrument_ids
            ),
            sessions=tuple(sessions or (self.session(),)),
            schedule=schedule,
            rule_profile=rules or cn_a_share_2026_07_06_rule_profile(),
            cost_policy=cost or self.cost(),
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
        buy = self.risk_vector((TargetWeightRow("000001.SZ", "0.5"),), "0.5")
        cash = self.risk_vector((), "1")
        result = self.run_engine(vectors=((DAY1, buy), (DAY1, cash)))
        self.assertEqual([fill.side for fill in result.fills], [Side.BUY])
        self.assertIn(DiagnosticCode.NO_SELLABLE_QUANTITY, {item.code for item in result.diagnostics})

    def test_03_next_day_sell_is_allowed(self):
        buy = self.risk_vector((TargetWeightRow("000001.SZ", "0.5"),), "0.5")
        cash = self.risk_vector((), "1")
        result = self.run_engine(
            vectors=((DAY1, buy), (DAY1, cash), (DAY2, cash)),
            sessions=(self.session(DAY1), self.session(DAY2)),
        )
        self.assertEqual([fill.side for fill in result.fills], [Side.BUY, Side.SELL])

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
        cash = self.risk_vector((), "1")
        result = self.run_engine(vectors=((DAY1, buy), (DAY2, cash)), sessions=(self.session(DAY1), self.session(DAY2)))
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


if __name__ == "__main__":
    unittest.main()
