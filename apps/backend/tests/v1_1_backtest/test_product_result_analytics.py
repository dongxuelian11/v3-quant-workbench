from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.backtest_runtime import (
    BacktestRunResult,
    DailyNav,
    HoldingSnapshot,
)
from v3_backend.domain.result_analytics import (
    BenchmarkStatus,
    DeterministicResultAnalyticsEngine,
    MetricStatus,
    ResultAnalyticsPolicyVersion,
    SourceResultBinding,
)


def _policy() -> ResultAnalyticsPolicyVersion:
    base = ResultAnalyticsPolicyVersion.a_share_daily_research_v0()
    values = {
        key: value
        for key, value in base._payload().items()
        if key != "schema_version"
    }
    values.update(
        profile_name="EXPLICIT_RESEARCH_ANALYTICS_V0",
        annualization_sessions=2,
    )
    return ResultAnalyticsPolicyVersion.create(**values)


def _result(
    nav_rows: tuple[DailyNav, ...],
    holdings: tuple[HoldingSnapshot, ...],
) -> BacktestRunResult:
    spec = SimpleNamespace(
        run_spec_id="btrs_product_analytics_fixture",
        truth_admission=PRE_ALPHA_CEILING,
    )
    return BacktestRunResult.create(
        spec,
        (),
        (),
        (),
        (),
        (),
        (),
        holdings,
        nav_rows,
    )


class ProductResultAnalyticsV11Tests(unittest.TestCase):
    def test_acc_c3_11_calmar_exposure_concentration_and_benchmark_states(self) -> None:
        dates = (date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 8))
        result = _result(
            (
                DailyNav(dates[0], "50", "50", "100"),
                DailyNav(dates[1], "20", "100", "120"),
                DailyNav(dates[2], "0", "90", "90"),
            ),
            (
                HoldingSnapshot(dates[0], "600519.SS", 5, 5, "10", "50"),
                HoldingSnapshot(dates[1], "600519.SS", 6, 6, "10", "60"),
                HoldingSnapshot(dates[1], "000001.SZ", 4, 4, "10", "40"),
                HoldingSnapshot(dates[2], "600519.SS", 9, 9, "10", "90"),
            ),
        )
        analytics = DeterministicResultAnalyticsEngine().analyze_product_v1_1(
            result,
            SourceResultBinding(result.result_id, result.content_sha256),
            _policy(),
        )

        self.assertEqual(analytics.calmar.status, MetricStatus.AVAILABLE)
        self.assertEqual(Decimal(analytics.calmar.value), Decimal("-0.4"))
        self.assertEqual(
            [Decimal(row.gross_exposure.value) for row in analytics.exposure_series],
            [Decimal("0.5"), Decimal("0.833333333333"), Decimal("1")],
        )
        self.assertEqual(
            [row.net_exposure.value for row in analytics.exposure_series],
            [row.gross_exposure.value for row in analytics.exposure_series],
        )
        self.assertEqual(
            [row.held_instrument_count for row in analytics.exposure_series],
            [1, 2, 1],
        )
        self.assertEqual(
            analytics.concentration.peak_single_position_weight.value, "1"
        )
        self.assertEqual(analytics.concentration.peak_session_date, dates[2])
        self.assertEqual(
            analytics.concentration.peak_instrument_id, "600519.SS"
        )
        self.assertEqual(
            analytics.concentration.average_held_instrument_count.value,
            "1.333333333333",
        )
        self.assertEqual(analytics.concentration.maximum_held_instrument_count, 2)
        self.assertEqual(
            analytics.core.benchmark.status,
            BenchmarkStatus.BENCHMARK_NOT_AVAILABLE,
        )
        self.assertEqual(analytics.source_result_id, result.result_id)
        self.assertEqual(
            analytics.source_result_content_sha256, result.content_sha256
        )
        self.assertEqual(analytics.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(analytics.analytics_id, "bra_sha256_" + analytics.content_sha256)

    def test_acc_c3_11_zero_drawdown_and_no_positions_are_explicit(self) -> None:
        dates = (date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 8))
        result = _result(
            tuple(DailyNav(day, "100", "0", "100") for day in dates),
            (),
        )
        analytics = DeterministicResultAnalyticsEngine().analyze_product_v1_1(
            result,
            SourceResultBinding(result.result_id, result.content_sha256),
            _policy(),
        )
        self.assertEqual(analytics.calmar.status, MetricStatus.NOT_AVAILABLE)
        self.assertEqual(analytics.calmar.reason, "ZERO_DRAWDOWN")
        self.assertEqual(
            analytics.concentration.peak_single_position_weight.status,
            MetricStatus.NOT_AVAILABLE,
        )
        self.assertEqual(
            analytics.concentration.peak_single_position_weight.reason,
            "NO_POSITIONS",
        )
        self.assertEqual(
            [row.gross_exposure.value for row in analytics.exposure_series],
            ["0", "0", "0"],
        )


if __name__ == "__main__":
    unittest.main()
