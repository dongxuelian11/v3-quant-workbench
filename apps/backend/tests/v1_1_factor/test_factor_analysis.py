from __future__ import annotations

import math
import statistics
import unittest
from datetime import date, timedelta

from v3_backend.domain.factors import PanelInputRow, PanelValueRow
from v3_backend.domain.factors.analysis import (
    FactorAnalysisService,
    FactorAnalysisSpecV1,
    MetricStatus,
)


_PARTITION_HASH = "a" * 64
_PARTITION_ID = "art_sha256_" + _PARTITION_HASH
_FACTOR_ID = "fdv_sha256_" + "b" * 64


def _pearson(left: list[float], right: list[float]) -> float:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left)
        * sum((y - right_mean) ** 2 for y in right)
    )
    return numerator / denominator


def _cross_section_fixture():
    instruments = tuple(f"ins_cn_sse_{600000 + index:06d}" for index in range(20))
    sessions = tuple(date(2025, 1, 1) + timedelta(days=index) for index in range(30))
    market_rows: list[PanelInputRow] = []
    factor_rows: list[PanelValueRow] = []
    for day_index, session in enumerate(sessions):
        for instrument_index, instrument in enumerate(instruments):
            close = 100.0 + instrument_index * 3.0 + day_index * (instrument_index + 1) * 0.2
            market_rows.append(
                PanelInputRow(
                    session_date=session,
                    instrument_id=instrument,
                    features={"close": close},
                    missing_reasons={},
                    source_partition_artifact_id=_PARTITION_ID,
                    source_partition_sha256=_PARTITION_HASH,
                )
            )
            if day_index == 0:
                factor = 1.0
            elif day_index == 1 and instrument_index >= 18:
                factor = None
            elif day_index == 2:
                factor = float(instrument_index // 3)
            else:
                factor = instrument_index + day_index / 1000.0
            factor_rows.append(
                PanelValueRow(
                    session_date=session,
                    instrument_id=instrument,
                    value=factor,
                    missing_reason=None if factor is not None else "SOURCE_VALUE_MISSING",
                    factor_definition_version_id=_FACTOR_ID,
                    source_partition_artifact_id=_PARTITION_ID,
                    source_partition_sha256=_PARTITION_HASH,
                )
            )
    return instruments, sessions, tuple(market_rows), tuple(factor_rows)


class FactorAnalysisAcceptanceTests(unittest.TestCase):
    def test_single_symbol_reports_insufficient_sample_without_numeric_cross_section(self) -> None:
        instrument = "ins_cn_sse_600519"
        sessions = tuple(date(2025, 1, 1) + timedelta(days=index) for index in range(10))
        market = tuple(
            PanelInputRow(
                session,
                instrument,
                {"close": 100.0 + index},
                {},
                _PARTITION_ID,
                _PARTITION_HASH,
            )
            for index, session in enumerate(sessions)
        )
        factor = tuple(
            PanelValueRow(
                session,
                instrument,
                float(index),
                None,
                _FACTOR_ID,
                _PARTITION_ID,
                _PARTITION_HASH,
            )
            for index, session in enumerate(sessions)
        )
        result = FactorAnalysisService().analyze(
            snapshot_id="snp_sha256_" + "c" * 64,
            universe_version_id="unv_sha256_" + "d" * 64,
            membership=(instrument,),
            factor_rows=factor,
            market_rows=market,
            spec=FactorAnalysisSpecV1(),
        )
        self.assertTrue(result.daily_results)
        self.assertTrue(
            all(item.status is MetricStatus.INSUFFICIENT_SAMPLE for item in result.daily_results)
        )
        self.assertTrue(all(item.ic.value is None and item.rank_ic.value is None for item in result.daily_results))
        self.assertTrue(all(item.quantile_returns is None for item in result.daily_results))
        self.assertIs(result.aggregate.ic_mean.status, MetricStatus.INSUFFICIENT_SAMPLE)
        self.assertEqual(result.aggregate.ic_mean.reason, "CROSS_SECTION_REQUIRES_AT_LEAST_20_INSTRUMENTS")

    def test_daily_cross_section_and_aggregate_match_independent_reference(self) -> None:
        instruments, sessions, market, factor = _cross_section_fixture()
        result = FactorAnalysisService().analyze(
            snapshot_id="snp_sha256_" + "c" * 64,
            universe_version_id="unv_sha256_" + "d" * 64,
            membership=instruments,
            factor_rows=factor,
            market_rows=market,
            spec=FactorAnalysisSpecV1(),
        )
        self.assertEqual(len(result.daily_results), 25)
        self.assertIs(result.daily_results[0].status, MetricStatus.NOT_AVAILABLE)
        self.assertEqual(result.daily_results[0].reason, "CONSTANT_INPUT")
        self.assertIs(result.daily_results[1].status, MetricStatus.INSUFFICIENT_SAMPLE)
        self.assertEqual(result.daily_results[1].sample_size, 18)

        tied = result.daily_results[2]
        self.assertIs(tied.status, MetricStatus.AVAILABLE)
        self.assertIn("TIE_SPLIT_BY_STABLE_ID", tied.diagnostics)
        self.assertIs(tied.turnover.status, MetricStatus.NOT_AVAILABLE)
        self.assertEqual(tied.turnover.reason, "NO_PRIOR_PORTFOLIO")
        self.assertIs(result.daily_results[3].turnover.status, MetricStatus.AVAILABLE)

        target = result.daily_results[3]
        formation = sessions[3]
        label = sessions[8]
        factor_values = [float(index) + 0.003 for index in range(20)]
        closes = {
            (row.instrument_id, row.session_date): float(row.features["close"])
            for row in market
        }
        returns = [
            closes[(instrument, label)] / closes[(instrument, formation)] - 1.0
            for instrument in instruments
        ]
        self.assertAlmostEqual(target.ic.value, _pearson(factor_values, returns), places=14)
        self.assertAlmostEqual(target.rank_ic.value, 1.0, places=14)
        expected_quantiles = tuple(
            statistics.fmean(returns[start : start + 4])
            for start in range(0, 20, 4)
        )
        self.assertEqual(len(target.quantile_returns or ()), 5)
        for observed, expected in zip(target.quantile_returns or (), expected_quantiles, strict=True):
            self.assertAlmostEqual(observed, expected, places=14)
        self.assertAlmostEqual(
            target.long_short_spread or 0.0,
            expected_quantiles[-1] - expected_quantiles[0],
            places=14,
        )

        available_ics = [
            item.ic.value for item in result.daily_results
            if item.status is MetricStatus.AVAILABLE and item.ic.value is not None
        ]
        self.assertEqual(len(available_ics), 23)
        self.assertIs(result.aggregate.ic_mean.status, MetricStatus.AVAILABLE)
        self.assertAlmostEqual(result.aggregate.ic_mean.value, statistics.fmean(available_ics), places=14)
        self.assertAlmostEqual(result.aggregate.ic_std.value, statistics.pstdev(available_ics), places=14)
        self.assertAlmostEqual(
            result.aggregate.icir.value,
            statistics.fmean(available_ics) / statistics.pstdev(available_ics),
            places=14,
        )
        self.assertTrue(result.factor_analysis_result_id.startswith("far_sha256_"))


if __name__ == "__main__":
    unittest.main()
