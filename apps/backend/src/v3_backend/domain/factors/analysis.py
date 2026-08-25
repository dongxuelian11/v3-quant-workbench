"""Deterministic V1.1 cross-sectional Factor analysis."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from v3_backend.provenance.canonical_hash import canonical_sha256

from .evaluator import PanelInputRow, PanelValueRow


class FactorAnalysisError(ValueError):
    pass


class MetricStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"


@dataclass(frozen=True, slots=True)
class MetricValue:
    status: MetricStatus
    value: float | None
    reason: str | None = None

    def to_wire(self) -> dict[str, object]:
        return {"status": self.status.value, "value": self.value, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class FactorAnalysisSpecV1:
    forward_return_horizon_sessions: int = 5
    quantiles: int = 5
    minimum_instruments_per_date: int = 20
    minimum_valid_ic_dates: int = 20
    formation_price: str = "RAW_CLOSE"
    label_price: str = "RAW_CLOSE"
    signal_availability: str = "AFTER_SESSION_CLOSE"

    def __post_init__(self) -> None:
        expected = (5, 5, 20, 20, "RAW_CLOSE", "RAW_CLOSE", "AFTER_SESSION_CLOSE")
        observed = (
            self.forward_return_horizon_sessions,
            self.quantiles,
            self.minimum_instruments_per_date,
            self.minimum_valid_ic_dates,
            self.formation_price,
            self.label_price,
            self.signal_availability,
        )
        if observed != expected:
            raise FactorAnalysisError("FactorAnalysisSpecV1 semantics are fixed for comparability")

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": "v3.factor-analysis-spec/1.0.0",
            "forward_return_horizon_sessions": self.forward_return_horizon_sessions,
            "quantiles": self.quantiles,
            "minimum_instruments_per_date": self.minimum_instruments_per_date,
            "minimum_valid_ic_dates": self.minimum_valid_ic_dates,
            "formation_price": self.formation_price,
            "label_price": self.label_price,
            "signal_availability": self.signal_availability,
        }


@dataclass(frozen=True, slots=True)
class DailyFactorAnalysis:
    session_date: date
    label_session_date: date
    status: MetricStatus
    reason: str | None
    universe_size: int
    sample_size: int
    coverage: float
    missing_rate: float
    ic: MetricValue
    rank_ic: MetricValue
    quantile_returns: tuple[float, ...] | None
    long_short_spread: float | None
    turnover: MetricValue
    diagnostics: tuple[str, ...]
    excluded_reason_counts: tuple[tuple[str, int], ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "label_session_date": self.label_session_date.isoformat(),
            "status": self.status.value,
            "reason": self.reason,
            "universe_size": self.universe_size,
            "sample_size": self.sample_size,
            "coverage": self.coverage,
            "missing_rate": self.missing_rate,
            "ic": self.ic.to_wire(),
            "rank_ic": self.rank_ic.to_wire(),
            "quantile_returns": self.quantile_returns,
            "long_short_spread": self.long_short_spread,
            "turnover": self.turnover.to_wire(),
            "diagnostics": self.diagnostics,
            "excluded_reason_counts": self.excluded_reason_counts,
        }


@dataclass(frozen=True, slots=True)
class YearlyFactorAnalysis:
    year: int
    valid_dates: int
    ic_mean: MetricValue
    ic_std: MetricValue
    icir: MetricValue

    def to_wire(self) -> dict[str, object]:
        return {
            "year": self.year,
            "valid_dates": self.valid_dates,
            "ic_mean": self.ic_mean.to_wire(),
            "ic_std": self.ic_std.to_wire(),
            "icir": self.icir.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class AggregateFactorAnalysis:
    valid_dates: int
    ic_mean: MetricValue
    ic_std: MetricValue
    icir: MetricValue
    rank_ic_mean: MetricValue
    rank_ic_std: MetricValue
    rank_icir: MetricValue
    yearly_distribution: tuple[YearlyFactorAnalysis, ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "valid_dates": self.valid_dates,
            "ic_mean": self.ic_mean.to_wire(),
            "ic_std": self.ic_std.to_wire(),
            "icir": self.icir.to_wire(),
            "rank_ic_mean": self.rank_ic_mean.to_wire(),
            "rank_ic_std": self.rank_ic_std.to_wire(),
            "rank_icir": self.rank_icir.to_wire(),
            "yearly_distribution": tuple(value.to_wire() for value in self.yearly_distribution),
        }


@dataclass(frozen=True, slots=True)
class FactorAnalysisResult:
    factor_analysis_result_id: str
    snapshot_id: str
    universe_version_id: str
    factor_definition_version_id: str
    spec: FactorAnalysisSpecV1
    daily_results: tuple[DailyFactorAnalysis, ...]
    aggregate: AggregateFactorAnalysis
    truth: str = "NOT_FORMAL"
    admission: str = "PRE_ALPHA"

    def to_wire(self) -> dict[str, object]:
        return {
            "factor_analysis_result_id": self.factor_analysis_result_id,
            "snapshot_id": self.snapshot_id,
            "universe_version_id": self.universe_version_id,
            "factor_definition_version_id": self.factor_definition_version_id,
            "spec": self.spec.to_wire(),
            "daily_results": tuple(value.to_wire() for value in self.daily_results),
            "aggregate": self.aggregate.to_wire(),
            "truth": self.truth,
            "admission": self.admission,
        }


def _pearson(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left)
        * sum((y - right_mean) ** 2 for y in right)
    )
    if denominator == 0:
        raise FactorAnalysisError("CONSTANT_INPUT")
    value = numerator / denominator
    if not math.isfinite(value):
        raise FactorAnalysisError("correlation is non-finite")
    return value


def _average_ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    ordered = sorted(range(len(values)), key=lambda index: (values[index], index))
    output = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[cursor]]:
            end += 1
        average = (cursor + end - 1) / 2.0
        for position in range(cursor, end):
            output[ordered[position]] = average
        cursor = end
    return tuple(output)


def _aggregate(values: tuple[float, ...], minimum: int, insufficient_reason: str) -> tuple[MetricValue, MetricValue, MetricValue]:
    if len(values) < minimum:
        missing = MetricValue(MetricStatus.INSUFFICIENT_SAMPLE, None, insufficient_reason)
        return missing, missing, missing
    mean = statistics.fmean(values)
    standard_deviation = statistics.pstdev(values)
    mean_metric = MetricValue(MetricStatus.AVAILABLE, mean)
    std_metric = MetricValue(MetricStatus.AVAILABLE, standard_deviation)
    if standard_deviation == 0:
        icir = MetricValue(MetricStatus.NOT_AVAILABLE, None, "ZERO_VARIANCE")
    else:
        icir = MetricValue(MetricStatus.AVAILABLE, mean / standard_deviation)
    return mean_metric, std_metric, icir


class FactorAnalysisService:
    service_version = "v3-factor-analysis/1.0.0"

    def analyze(
        self,
        *,
        snapshot_id: str,
        universe_version_id: str,
        membership: tuple[str, ...],
        factor_rows: tuple[PanelValueRow, ...],
        market_rows: tuple[PanelInputRow, ...],
        spec: FactorAnalysisSpecV1,
    ) -> FactorAnalysisResult:
        if not membership or membership != tuple(sorted(set(membership))):
            raise FactorAnalysisError("membership must be a non-empty sorted exact Universe")
        if not factor_rows or not market_rows:
            raise FactorAnalysisError("Factor analysis requires factor and market rows")
        factor_ids = {row.factor_definition_version_id for row in factor_rows}
        if len(factor_ids) != 1:
            raise FactorAnalysisError("factor rows must bind one FactorDefinitionVersion")
        factor_id = next(iter(factor_ids))
        factor_by_key = self._factor_index(factor_rows)
        market_by_key = self._market_index(market_rows)
        sessions = tuple(sorted({row.session_date for row in market_rows}))
        horizon = spec.forward_return_horizon_sessions
        if len(sessions) <= horizon:
            raise FactorAnalysisError("Factor analysis has no evaluable forward-return session")

        previous_top: frozenset[str] | None = None
        daily: list[DailyFactorAnalysis] = []
        for position, formation_date in enumerate(sessions[:-horizon]):
            label_date = sessions[position + horizon]
            factors: list[float] = []
            returns: list[float] = []
            instruments: list[str] = []
            excluded: dict[str, int] = {}
            for instrument in membership:
                factor = factor_by_key.get((formation_date, instrument))
                formation = market_by_key.get((formation_date, instrument))
                label = market_by_key.get((label_date, instrument))
                reason: str | None = None
                if factor is None or factor.value is None:
                    reason = "FACTOR_MISSING"
                elif isinstance(factor.value, bool):
                    raise FactorAnalysisError("FactorAnalysisSpecV1 requires a numeric factor")
                elif formation is None or formation.features.get("close") is None:
                    reason = "FORMATION_PRICE_MISSING"
                elif label is None or label.features.get("close") is None:
                    reason = "LABEL_PRICE_MISSING"
                elif (
                    factor.source_partition_artifact_id != formation.source_partition_artifact_id
                    or factor.source_partition_sha256 != formation.source_partition_sha256
                ):
                    raise FactorAnalysisError("factor/source Snapshot partition binding mismatch")
                if reason is not None:
                    excluded[reason] = excluded.get(reason, 0) + 1
                    continue
                formation_close = formation.features["close"]
                label_close = label.features["close"]
                if (
                    isinstance(formation_close, bool)
                    or isinstance(label_close, bool)
                    or not isinstance(formation_close, (int, float))
                    or not isinstance(label_close, (int, float))
                    or not math.isfinite(float(formation_close))
                    or not math.isfinite(float(label_close))
                    or float(formation_close) <= 0
                    or float(label_close) <= 0
                ):
                    excluded["PRICE_INVALID"] = excluded.get("PRICE_INVALID", 0) + 1
                    continue
                factors.append(float(factor.value))
                returns.append(float(label_close) / float(formation_close) - 1.0)
                instruments.append(instrument)

            sample_size = len(factors)
            coverage = sample_size / len(membership)
            missing_rate = 1.0 - coverage
            unavailable_turnover = MetricValue(
                MetricStatus.NOT_AVAILABLE, None, "NO_PRIOR_PORTFOLIO"
            )
            common = {
                "session_date": formation_date,
                "label_session_date": label_date,
                "universe_size": len(membership),
                "sample_size": sample_size,
                "coverage": coverage,
                "missing_rate": missing_rate,
                "excluded_reason_counts": tuple(sorted(excluded.items())),
            }
            if sample_size < spec.minimum_instruments_per_date:
                reason = "CROSS_SECTION_REQUIRES_AT_LEAST_20_INSTRUMENTS"
                missing = MetricValue(MetricStatus.INSUFFICIENT_SAMPLE, None, reason)
                daily.append(
                    DailyFactorAnalysis(
                        status=MetricStatus.INSUFFICIENT_SAMPLE,
                        reason=reason,
                        ic=missing,
                        rank_ic=missing,
                        quantile_returns=None,
                        long_short_spread=None,
                        turnover=unavailable_turnover,
                        diagnostics=(),
                        **common,
                    )
                )
                continue
            factor_values = tuple(factors)
            return_values = tuple(returns)
            if len(set(factor_values)) == 1 or len(set(return_values)) == 1:
                reason = "CONSTANT_INPUT"
                missing = MetricValue(MetricStatus.NOT_AVAILABLE, None, reason)
                daily.append(
                    DailyFactorAnalysis(
                        status=MetricStatus.NOT_AVAILABLE,
                        reason=reason,
                        ic=missing,
                        rank_ic=missing,
                        quantile_returns=None,
                        long_short_spread=None,
                        turnover=unavailable_turnover,
                        diagnostics=(),
                        **common,
                    )
                )
                continue

            ic = _pearson(factor_values, return_values)
            rank_ic = _pearson(_average_ranks(factor_values), _average_ranks(return_values))
            ordered = sorted(
                range(sample_size),
                key=lambda index: (factor_values[index], instruments[index]),
            )
            base, remainder = divmod(sample_size, spec.quantiles)
            buckets: list[tuple[int, ...]] = []
            cursor = 0
            boundaries: list[int] = []
            for bucket_index in range(spec.quantiles):
                size = base + (1 if bucket_index < remainder else 0)
                bucket = tuple(ordered[cursor : cursor + size])
                buckets.append(bucket)
                cursor += size
                if cursor < sample_size:
                    boundaries.append(cursor)
            diagnostics = (
                ("TIE_SPLIT_BY_STABLE_ID",)
                if any(
                    factor_values[ordered[boundary - 1]] == factor_values[ordered[boundary]]
                    for boundary in boundaries
                )
                else ()
            )
            quantile_returns = tuple(
                statistics.fmean(return_values[index] for index in bucket)
                for bucket in buckets
            )
            top = frozenset(instruments[index] for index in buckets[-1])
            if previous_top is None:
                turnover = unavailable_turnover
            else:
                denominator = max(len(previous_top), len(top))
                turnover = MetricValue(
                    MetricStatus.AVAILABLE,
                    0.0 if denominator == 0 else 1.0 - len(previous_top & top) / denominator,
                )
            previous_top = top
            daily.append(
                DailyFactorAnalysis(
                    status=MetricStatus.AVAILABLE,
                    reason=None,
                    ic=MetricValue(MetricStatus.AVAILABLE, ic),
                    rank_ic=MetricValue(MetricStatus.AVAILABLE, rank_ic),
                    quantile_returns=quantile_returns,
                    long_short_spread=quantile_returns[-1] - quantile_returns[0],
                    turnover=turnover,
                    diagnostics=diagnostics,
                    **common,
                )
            )

        available = tuple(item for item in daily if item.status is MetricStatus.AVAILABLE)
        ic_values = tuple(float(item.ic.value) for item in available if item.ic.value is not None)
        rank_values = tuple(
            float(item.rank_ic.value) for item in available if item.rank_ic.value is not None
        )
        insufficient_reason = (
            "CROSS_SECTION_REQUIRES_AT_LEAST_20_INSTRUMENTS"
            if len(membership) < spec.minimum_instruments_per_date
            else "VALID_IC_DATES_REQUIRE_AT_LEAST_20"
        )
        ic_mean, ic_std, icir = _aggregate(
            ic_values, spec.minimum_valid_ic_dates, insufficient_reason
        )
        rank_mean, rank_std, rank_icir = _aggregate(
            rank_values, spec.minimum_valid_ic_dates, insufficient_reason
        )
        yearly: list[YearlyFactorAnalysis] = []
        for year in sorted({item.session_date.year for item in daily}):
            year_values = tuple(
                float(item.ic.value)
                for item in available
                if item.session_date.year == year and item.ic.value is not None
            )
            year_mean, year_std, year_icir = _aggregate(
                year_values,
                spec.minimum_valid_ic_dates,
                "YEAR_REQUIRES_AT_LEAST_20_VALID_IC_DATES",
            )
            yearly.append(
                YearlyFactorAnalysis(year, len(year_values), year_mean, year_std, year_icir)
            )
        aggregate = AggregateFactorAnalysis(
            len(available),
            ic_mean,
            ic_std,
            icir,
            rank_mean,
            rank_std,
            rank_icir,
            tuple(yearly),
        )
        identity_payload = {
            "service_version": self.service_version,
            "snapshot_id": snapshot_id,
            "universe_version_id": universe_version_id,
            "factor_definition_version_id": factor_id,
            "membership": membership,
            "spec": spec.to_wire(),
            "daily_results": tuple(value.to_wire() for value in daily),
            "aggregate": aggregate.to_wire(),
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
        }
        return FactorAnalysisResult(
            "far_sha256_" + canonical_sha256(identity_payload),
            snapshot_id,
            universe_version_id,
            factor_id,
            spec,
            tuple(daily),
            aggregate,
        )

    @staticmethod
    def _factor_index(rows: tuple[PanelValueRow, ...]) -> dict[tuple[date, str], PanelValueRow]:
        indexed = {(row.session_date, row.instrument_id): row for row in rows}
        if len(indexed) != len(rows):
            raise FactorAnalysisError("factor rows contain duplicate date/instrument keys")
        return indexed

    @staticmethod
    def _market_index(rows: tuple[PanelInputRow, ...]) -> dict[tuple[date, str], PanelInputRow]:
        indexed = {(row.session_date, row.instrument_id): row for row in rows}
        if len(indexed) != len(rows):
            raise FactorAnalysisError("market rows contain duplicate date/instrument keys")
        return indexed


__all__ = (
    "AggregateFactorAnalysis",
    "DailyFactorAnalysis",
    "FactorAnalysisError",
    "FactorAnalysisResult",
    "FactorAnalysisService",
    "FactorAnalysisSpecV1",
    "MetricStatus",
    "MetricValue",
    "YearlyFactorAnalysis",
)
