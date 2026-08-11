from __future__ import annotations

import dataclasses
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.backtest_runtime import (
    BacktestRunResult,
    CashLedgerEntry,
    CostBreakdown,
    DailyNav,
    Fill,
    LedgerKind,
    Side,
)
from v3_backend.domain.result_analytics import (
    BacktestResultAnalytics,
    BenchmarkObservation,
    BenchmarkSeriesVersion,
    BenchmarkStatus,
    DeterministicResultAnalyticsEngine,
    MetricStatus,
    ResultAnalyticsError,
    ResultAnalyticsPolicyVersion,
    SourceResultBinding,
    UnsupportedResultAnalyticsPolicy,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


def d(day: int, month: int = 1, year: int = 2026) -> date:
    return date(year, month, day)


def make_result(
    nav_values: tuple[str, ...],
    *,
    dates: tuple[date, ...] | None = None,
    fills: tuple[Fill, ...] = (),
    cash_ledger: tuple[CashLedgerEntry, ...] = (),
    truth=PRE_ALPHA_CEILING,
) -> BacktestRunResult:
    observed_dates = dates or tuple(d(index + 1) for index in range(len(nav_values)))
    nav = tuple(
        DailyNav(session_date, value, "0", value)
        for session_date, value in zip(observed_dates, nav_values, strict=True)
    )
    spec = SimpleNamespace(run_spec_id="btrs_fixture", truth_admission=truth)
    return BacktestRunResult.create(
        spec,
        (),
        (),
        fills,
        (),
        cash_ledger,
        (),
        (),
        nav,
    )


def binding(result: BacktestRunResult) -> SourceResultBinding:
    return SourceResultBinding(result.result_id, result.content_sha256)


def benchmark(
    dates: tuple[date, ...],
    values: tuple[str, ...],
    *,
    truth=PRE_ALPHA_CEILING,
) -> BenchmarkSeriesVersion:
    return BenchmarkSeriesVersion.create(
        name="EXACT_RESEARCH_BENCHMARK_V0",
        rows=tuple(
            BenchmarkObservation(session_date, value)
            for session_date, value in zip(dates, values, strict=True)
        ),
        source_provenance_refs=("fixture://benchmark/exact-v0",),
        alignment_policy="EXACT_SESSION_DATE_MATCH",
        truth_admission=truth,
    )


class ResultAnalyticsV0Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DeterministicResultAnalyticsEngine()
        self.policy = ResultAnalyticsPolicyVersion.a_share_daily_research_v0()

    def analyze(self, result: BacktestRunResult, reference=None):
        return self.engine.analyze(result, binding(result), self.policy, reference)

    def test_01_deterministic_return_series_and_identity(self):
        result = make_result(("100", "110", "99", "118.8"))
        first = self.analyze(result)
        second = self.analyze(result)
        self.assertEqual(first, second)
        self.assertEqual(first.analytics_id, "bra_sha256_" + first.content_sha256)
        self.assertEqual(
            [row.session_return.value for row in first.return_series],
            [None, "0.1", "-0.1", "0.2"],
        )
        self.assertEqual(first.return_series[0].session_return.status, MetricStatus.NOT_AVAILABLE)

    def test_02_total_and_annualized_return_bind_explicit_policy(self):
        result = make_result(("100", "110", "99", "118.8"))
        analytics = self.analyze(result)
        self.assertEqual(analytics.total_return.value, "0.188")
        expected = (Decimal("1.188") ** (Decimal(252) / Decimal(3))) - 1
        self.assertAlmostEqual(
            Decimal(analytics.annualized_return.value), expected, places=10
        )
        self.assertEqual(analytics.analytics_policy_id, self.policy.policy_id)
        self.assertEqual(self.policy.annualization_sessions, 252)

    def test_03_policy_change_changes_policy_and_analytics_identity(self):
        result = make_result(("100", "101", "102"))
        changed = ResultAnalyticsPolicyVersion.create(
            **{
                key: value
                for key, value in self.policy._payload().items()
                if key != "schema_version"
            }
            | {
                "profile_name": "EXPLICIT_RESEARCH_ANALYTICS_V0",
                "annualization_sessions": 250,
            }
        )
        first = self.analyze(result)
        second = self.engine.analyze(result, binding(result), changed)
        self.assertNotEqual(self.policy.policy_id, changed.policy_id)
        self.assertNotEqual(first.analytics_id, second.analytics_id)

    def test_04_volatility_uses_ddof_one(self):
        result = make_result(("100", "110", "99"))
        analytics = self.analyze(result)
        expected = Decimal("0.02").sqrt() * Decimal(252).sqrt()
        self.assertAlmostEqual(
            Decimal(analytics.annualized_volatility.value), expected, places=10
        )

    def test_05_max_drawdown_has_exact_peak_trough_and_recovery(self):
        dates = (d(1), d(2), d(3), d(4), d(5))
        result = make_result(("100", "120", "90", "110", "121"), dates=dates)
        analytics = self.analyze(result)
        self.assertEqual(analytics.max_drawdown.value, "-0.25")
        self.assertEqual(analytics.drawdown_episode.peak_date, d(2))
        self.assertEqual(analytics.drawdown_episode.trough_date, d(3))
        self.assertEqual(analytics.drawdown_episode.recovery_date, d(5))
        self.assertEqual(analytics.drawdown_episode.duration_sessions, 3)

    def test_06_unrecovered_drawdown_is_typed(self):
        result = make_result(("100", "120", "90", "110"))
        episode = self.analyze(result).drawdown_episode
        self.assertEqual(episode.recovery_date, None)
        self.assertEqual(episode.recovery_status.value, "UNRECOVERED")

    def test_07_sharpe_uses_zero_risk_free_assumption(self):
        result = make_result(("100", "110", "99", "108.9"))
        analytics = self.analyze(result)
        returns = (Decimal("0.1"), Decimal("-0.1"), Decimal("0.1"))
        mean = sum(returns) / Decimal(3)
        stddev = (
            sum((value - mean) ** 2 for value in returns) / Decimal(2)
        ).sqrt()
        expected = mean / stddev * Decimal(252).sqrt()
        self.assertAlmostEqual(Decimal(analytics.sharpe.value), expected, places=10)
        self.assertEqual(self.policy.risk_free_policy, "ZERO_RISK_FREE_ASSUMPTION")
        self.assertEqual(self.policy.risk_free_annual_rate, "0")

    def test_08_sortino_uses_explicit_zero_target(self):
        result = make_result(("100", "110", "99", "108.9"))
        analytics = self.analyze(result)
        returns = (Decimal("0.1"), Decimal("-0.1"), Decimal("0.1"))
        downside = (Decimal("0.01") / Decimal(3)).sqrt()
        expected = (sum(returns) / Decimal(3)) / downside * Decimal(252).sqrt()
        self.assertAlmostEqual(Decimal(analytics.sortino.value), expected, places=10)

    def test_09_insufficient_samples_and_zero_variance_are_not_nan(self):
        one = self.analyze(make_result(("100",)))
        self.assertEqual(one.annualized_return.status, MetricStatus.INSUFFICIENT_SAMPLE)
        self.assertEqual(one.annualized_volatility.status, MetricStatus.INSUFFICIENT_SAMPLE)
        self.assertEqual(one.sharpe.status, MetricStatus.INSUFFICIENT_SAMPLE)
        flat = self.analyze(make_result(("100", "100", "100")))
        self.assertEqual(flat.annualized_volatility.value, "0")
        self.assertEqual(flat.sharpe.status, MetricStatus.NOT_AVAILABLE)
        self.assertEqual(flat.sharpe.reason, "ZERO_VARIANCE")
        self.assertEqual(flat.sortino.reason, "ZERO_DOWNSIDE_DEVIATION")

    def test_10_monthly_and_yearly_returns_use_previous_period_end(self):
        dates = (d(30, 1), d(31, 1), d(1, 2), d(28, 2), d(2, 1, 2027))
        result = make_result(("100", "110", "121", "99", "108.9"), dates=dates)
        analytics = self.analyze(result)
        self.assertEqual(
            [(row.period_label, row.period_return.value) for row in analytics.monthly_returns],
            [("2026-01", "0.1"), ("2026-02", "-0.1"), ("2027-01", "0.1")],
        )
        self.assertEqual(
            [(row.period_label, row.period_return.value) for row in analytics.yearly_returns],
            [("2026", "-0.01"), ("2027", "0.1")],
        )

    def test_11_turnover_and_12_fee_aggregation_reconcile_exact_ledgers(self):
        costs = CostBreakdown("1", "2", "3", "4")
        fill = Fill(
            "fill-1", "order-1", d(1), "000001.SZ", Side.BUY, 100, "10", "1000", costs
        )
        ledger = (
            CashLedgerEntry(0, d(1), LedgerKind.BUY, "-1000", "8990", "fill-1"),
            CashLedgerEntry(1, d(1), LedgerKind.FEE, "-10", "8980", "fill-1", costs),
        )
        analytics = self.analyze(
            make_result(("10000", "12000"), fills=(fill,), cash_ledger=ledger)
        )
        self.assertEqual(analytics.costs.gross_traded_notional, "1000")
        self.assertEqual(analytics.costs.total_fees, "10")
        self.assertEqual(analytics.costs.commission, "1")
        self.assertEqual(analytics.costs.stamp_duty, "2")
        self.assertEqual(analytics.costs.transfer_fee, "3")
        self.assertEqual(analytics.costs.exchange_fee, "4")
        self.assertEqual(analytics.turnover.average_daily_nav, "11000")
        self.assertEqual(analytics.turnover.turnover.value, "0.090909090909")

    def test_13_no_fake_pre_cost_return(self):
        analytics = self.analyze(make_result(("100", "101")))
        self.assertNotIn("pre_cost_return", analytics.costs.to_wire())
        self.assertIn("observed_fee_load_over_start_nav", analytics.costs.to_wire())

    def test_14_absent_benchmark_is_truthful(self):
        analytics = self.analyze(make_result(("100", "101", "102")))
        self.assertEqual(
            analytics.benchmark.status, BenchmarkStatus.BENCHMARK_NOT_AVAILABLE
        )
        self.assertEqual(
            analytics.benchmark.tracking_error.reason, "BENCHMARK_NOT_AVAILABLE"
        )

    def test_15_exact_benchmark_alignment_and_metrics(self):
        dates = (d(1), d(2), d(3))
        result = make_result(("100", "110", "121"), dates=dates)
        reference = benchmark(dates, ("100", "105", "110.25"))
        analytics = self.analyze(result, reference)
        self.assertEqual(analytics.benchmark.status, BenchmarkStatus.AVAILABLE)
        self.assertEqual(analytics.benchmark.aligned_benchmark_total_return.value, "0.1025")
        self.assertEqual(analytics.benchmark.tracking_difference.value, "0.1075")
        self.assertEqual(
            [row.relative_nav.value for row in analytics.benchmark.relative_returns],
            ["1", "1.047619047619", "1.097505668934"],
        )
        self.assertEqual(analytics.benchmark.alpha.reason, "OUTSIDE_V0_CLOSED_FORMULA")

    def test_16_benchmark_date_mismatch_rejects(self):
        result = make_result(("100", "101"), dates=(d(1), d(2)))
        reference = benchmark((d(1), d(3)), ("100", "101"))
        with self.assertRaisesRegex(ResultAnalyticsError, "exactly match"):
            self.analyze(result, reference)

    def test_17_source_binding_and_canonical_hash_mismatch_reject(self):
        result = make_result(("100", "101"))
        with self.assertRaisesRegex(ResultAnalyticsError, "binding mismatch"):
            self.engine.analyze(
                result,
                SourceResultBinding(result.result_id, "0" * 64),
                self.policy,
            )
        altered = dataclasses.replace(result, content_sha256="1" * 64)
        with self.assertRaisesRegex(ResultAnalyticsError, "identity/content mismatch"):
            self.engine.analyze(altered, binding(altered), self.policy)

    def test_18_benchmark_change_changes_analytics_identity(self):
        dates = (d(1), d(2), d(3))
        result = make_result(("100", "101", "102"), dates=dates)
        first = self.analyze(result, benchmark(dates, ("100", "100", "100")))
        second = self.analyze(result, benchmark(dates, ("100", "101", "102")))
        self.assertNotEqual(first.analytics_id, second.analytics_id)

    def test_19_truth_is_not_upgraded(self):
        dates = (d(1), d(2))
        formal_result = make_result(
            ("100", "101"), dates=dates, truth=FORMAL_ADMITTED_CEILING
        )
        analytics = self.analyze(
            formal_result,
            benchmark(dates, ("100", "101"), truth=PRE_ALPHA_CEILING),
        )
        self.assertEqual(analytics.truth_admission, PRE_ALPHA_CEILING)

    def test_20_nonfinite_and_fee_ledger_mismatch_reject(self):
        with self.assertRaisesRegex(ResultAnalyticsError, "finite"):
            self.analyze(make_result(("100", "NaN")))
        costs = CostBreakdown("1", "0", "0", "0")
        fill = Fill(
            "fill-1", "order-1", d(1), "000001.SZ", Side.SELL, 10, "10", "100", costs
        )
        mismatched = (
            CashLedgerEntry(0, d(1), LedgerKind.SELL, "100", "100", "fill-1"),
            CashLedgerEntry(1, d(1), LedgerKind.FEE, "-2", "98", "fill-1", costs),
        )
        with self.assertRaisesRegex(ResultAnalyticsError, "reconciliation mismatch"):
            self.analyze(
                make_result(("100", "101"), fills=(fill,), cash_ledger=mismatched)
            )

    def test_21_frozen_profile_and_unsupported_conventions_fail_closed(self):
        base = {
            key: value
            for key, value in self.policy._payload().items()
            if key != "schema_version"
        }
        mutations = (
            {"annualization_sessions": 250},
            {"return_convention": "LOG_RETURN"},
            {"risk_free_policy": "NONZERO_MARKET_RATE", "risk_free_annual_rate": "0.05"},
            {"drawdown_convention": "END_TO_END"},
            {"turnover_convention": "HALF_GROSS"},
            {"period_return_convention": "PERIOD_START_TO_END"},
            {"missing_data_policy": "DROP_MISSING"},
            {"numeric_rounding": "ROUND_DOWN"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                UnsupportedResultAnalyticsPolicy,
                "UNSUPPORTED_RESULT_ANALYTICS_POLICY",
            ):
                ResultAnalyticsPolicyVersion.create(**(base | mutation))

    def test_22_direct_hash_consistent_malformed_policy_rejects(self):
        malformed = dataclasses.replace(self.policy, return_convention="LOG_RETURN")
        digest = canonical_sha256(malformed._payload())
        malformed = dataclasses.replace(
            malformed, content_sha256=digest, policy_id="rap_sha256_" + digest
        )
        with self.assertRaisesRegex(
            UnsupportedResultAnalyticsPolicy, "UNSUPPORTED_RESULT_ANALYTICS_POLICY"
        ):
            malformed.assert_canonical()
        with self.assertRaises(UnsupportedResultAnalyticsPolicy):
            self.engine.analyze(make_result(("100", "101")), binding(make_result(("100", "101"))), malformed)

    def test_23_explicit_numeric_profile_changes_execution_consistently(self):
        base = {
            key: value
            for key, value in self.policy._payload().items()
            if key != "schema_version"
        }
        custom = ResultAnalyticsPolicyVersion.create(
            **(base | {"profile_name": "EXPLICIT_RESEARCH_ANALYTICS_V0", "annualization_sessions": 250})
        )
        result = make_result(("100", "101", "102"))
        canonical = self.analyze(result)
        changed = self.engine.analyze(result, binding(result), custom)
        self.assertNotEqual(canonical.analytics_id, changed.analytics_id)
        self.assertNotEqual(canonical.annualized_return.value, changed.annualized_return.value)

    def test_24_benchmark_semantics_revalidated_by_assert_canonical(self):
        dates = (d(1), d(2))
        valid = benchmark(dates, ("100", "101"))
        valid.assert_canonical()
        for mutation in (
            {"source_provenance_refs": ()},
            {"alignment_policy": "FORWARD_FILL"},
            {"rows": tuple(reversed(valid.rows))},
            {"truth_admission": FORMAL_ADMITTED_CEILING},
        ):
            malformed = dataclasses.replace(valid, **mutation)
            digest = canonical_sha256(malformed._payload())
            malformed = dataclasses.replace(
                malformed,
                content_sha256=digest,
                benchmark_series_id="bmsv_sha256_" + digest,
            )
            with self.subTest(mutation=mutation), self.assertRaises(ResultAnalyticsError):
                malformed.assert_canonical()

    def test_25_analytics_is_engine_owned_and_exactly_recomputable(self):
        result = make_result(("100", "101", "102"))
        analytics = self.analyze(result)
        self.assertFalse(hasattr(BacktestResultAnalytics, "create"))
        analytics.assert_canonical()
        self.engine.assert_output(result, binding(result), self.policy, None, analytics)

    @staticmethod
    def _self_consistent_analytics(
        analytics: BacktestResultAnalytics, **changes
    ) -> BacktestResultAnalytics:
        changed = dataclasses.replace(analytics, **changes)
        values = {
            field: getattr(changed, field)
            for field in changed.__dataclass_fields__
            if field not in {"analytics_id", "content_sha256", "schema_version"}
        }
        digest = canonical_sha256(BacktestResultAnalytics._payload_from_values(values))
        return dataclasses.replace(
            changed, analytics_id="bra_sha256_" + digest, content_sha256=digest
        )

    def test_26_canonical_hash_does_not_replace_engine_output_authority(self):
        result = make_result(("100", "101", "102"))
        analytics = self.analyze(result)
        wrong_id = dataclasses.replace(analytics, content_sha256="0" * 64)
        with self.assertRaisesRegex(ResultAnalyticsError, "identity/content mismatch"):
            wrong_id.assert_canonical()
        fabricated = self._self_consistent_analytics(
            analytics, total_return=analytics.total_return.available("9")
        )
        fabricated.assert_canonical()
        with self.assertRaisesRegex(ResultAnalyticsError, "deterministic recomputation"):
            self.engine.assert_output(result, binding(result), self.policy, None, fabricated)

    def test_27_fabricated_cost_turnover_and_truth_fail_recomputation(self):
        result = make_result(("100", "101", "102"))
        analytics = self.analyze(result)
        fabricated_cost = self._self_consistent_analytics(
            analytics,
            costs=dataclasses.replace(analytics.costs, total_fees="99"),
            turnover=dataclasses.replace(
                analytics.turnover, average_daily_nav="999"
            ),
        )
        fabricated_cost.assert_canonical()
        with self.assertRaisesRegex(ResultAnalyticsError, "deterministic recomputation"):
            self.engine.assert_output(result, binding(result), self.policy, None, fabricated_cost)
        fabricated_truth = self._self_consistent_analytics(
            analytics, truth_admission=FORMAL_ADMITTED_CEILING
        )
        fabricated_truth.assert_canonical()
        with self.assertRaisesRegex(ResultAnalyticsError, "deterministic recomputation"):
            self.engine.assert_output(result, binding(result), self.policy, None, fabricated_truth)

    def test_28_source_result_change_changes_analytics_identity(self):
        first = make_result(("100", "101", "102"))
        second = make_result(("100", "101", "103"))
        self.assertNotEqual(self.analyze(first).analytics_id, self.analyze(second).analytics_id)


if __name__ == "__main__":
    unittest.main()
