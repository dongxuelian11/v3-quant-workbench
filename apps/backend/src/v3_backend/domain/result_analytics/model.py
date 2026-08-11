from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import ClassVar

from v3_backend.contracts.common.truth_admission import TruthAdmissionState
from v3_backend.provenance.canonical_hash import canonical_sha256


class ResultAnalyticsError(ValueError):
    pass


class MetricStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


class BenchmarkStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BENCHMARK_NOT_AVAILABLE = "BENCHMARK_NOT_AVAILABLE"


class DrawdownRecoveryStatus(str, Enum):
    RECOVERED = "RECOVERED"
    UNRECOVERED = "UNRECOVERED"


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ResultAnalyticsError(f"{name} must be exact non-empty text")
    return value


def _sha(value: str, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ResultAnalyticsError(f"{name} must be a lowercase sha256")
    return value


def exact_decimal_text(
    value: str | Decimal,
    name: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> str:
    try:
        observed = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError) as error:
        raise ResultAnalyticsError(f"{name} must be an exact decimal") from error
    if not observed.is_finite():
        raise ResultAnalyticsError(f"{name} must be finite")
    if positive and observed <= 0:
        raise ResultAnalyticsError(f"{name} must be positive")
    if non_negative and observed < 0:
        raise ResultAnalyticsError(f"{name} must be non-negative")
    if observed == 0:
        return "0"
    normalized = format(observed.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


@dataclass(frozen=True, slots=True)
class AnalyticsMetric:
    status: MetricStatus
    value: str | None
    reason: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, MetricStatus):
            raise TypeError("status must be MetricStatus")
        if self.status is MetricStatus.AVAILABLE:
            if self.value is None or self.reason is not None:
                raise ResultAnalyticsError(
                    "AVAILABLE metric requires value and forbids reason"
                )
            object.__setattr__(self, "value", exact_decimal_text(self.value, "metric"))
        else:
            if self.value is not None or self.reason is None:
                raise ResultAnalyticsError(
                    "unavailable metric forbids value and requires reason"
                )
            _text(self.reason, "metric reason")

    @classmethod
    def available(cls, value: str) -> AnalyticsMetric:
        return cls(MetricStatus.AVAILABLE, value, None)

    @classmethod
    def not_available(cls, reason: str) -> AnalyticsMetric:
        return cls(MetricStatus.NOT_AVAILABLE, None, reason)

    @classmethod
    def insufficient_sample(cls, reason: str) -> AnalyticsMetric:
        return cls(MetricStatus.INSUFFICIENT_SAMPLE, None, reason)

    def to_wire(self) -> dict[str, str | None]:
        return {
            "status": self.status.value,
            "value": self.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ResultAnalyticsPolicyVersion:
    policy_id: str
    content_sha256: str
    profile_name: str
    return_convention: str
    annualization_sessions: int
    volatility_ddof: int
    risk_free_policy: str
    risk_free_annual_rate: str
    sortino_target: str
    drawdown_convention: str
    turnover_convention: str
    period_return_convention: str
    missing_data_policy: str
    numeric_precision: int
    numeric_rounding: str

    schema_version: ClassVar[str] = "v3.result_analytics_policy/1.0.0"

    @classmethod
    def create(
        cls,
        *,
        profile_name: str,
        return_convention: str,
        annualization_sessions: int,
        volatility_ddof: int,
        risk_free_policy: str,
        risk_free_annual_rate: str,
        sortino_target: str,
        drawdown_convention: str,
        turnover_convention: str,
        period_return_convention: str,
        missing_data_policy: str,
        numeric_precision: int,
        numeric_rounding: str,
    ) -> ResultAnalyticsPolicyVersion:
        for name, value in (
            ("profile_name", profile_name),
            ("return_convention", return_convention),
            ("risk_free_policy", risk_free_policy),
            ("drawdown_convention", drawdown_convention),
            ("turnover_convention", turnover_convention),
            ("period_return_convention", period_return_convention),
            ("missing_data_policy", missing_data_policy),
            ("numeric_rounding", numeric_rounding),
        ):
            _text(value, name)
        if annualization_sessions <= 0:
            raise ResultAnalyticsError("annualization_sessions must be positive")
        if volatility_ddof < 0:
            raise ResultAnalyticsError("volatility_ddof must be non-negative")
        if numeric_precision < 1 or numeric_precision > 28:
            raise ResultAnalyticsError("numeric_precision must be between 1 and 28")
        risk_free = exact_decimal_text(risk_free_annual_rate, "risk_free_annual_rate")
        target = exact_decimal_text(sortino_target, "sortino_target")
        if risk_free_policy == "ZERO_RISK_FREE_ASSUMPTION" and risk_free != "0":
            raise ResultAnalyticsError("zero-risk-free policy requires exact zero rate")
        payload = {
            "schema_version": cls.schema_version,
            "profile_name": profile_name,
            "return_convention": return_convention,
            "annualization_sessions": annualization_sessions,
            "volatility_ddof": volatility_ddof,
            "risk_free_policy": risk_free_policy,
            "risk_free_annual_rate": risk_free,
            "sortino_target": target,
            "drawdown_convention": drawdown_convention,
            "turnover_convention": turnover_convention,
            "period_return_convention": period_return_convention,
            "missing_data_policy": missing_data_policy,
            "numeric_precision": numeric_precision,
            "numeric_rounding": numeric_rounding,
        }
        digest = canonical_sha256(payload)
        return cls(
            "rap_sha256_" + digest,
            digest,
            profile_name,
            return_convention,
            annualization_sessions,
            volatility_ddof,
            risk_free_policy,
            risk_free,
            target,
            drawdown_convention,
            turnover_convention,
            period_return_convention,
            missing_data_policy,
            numeric_precision,
            numeric_rounding,
        )

    @classmethod
    def a_share_daily_research_v0(cls) -> ResultAnalyticsPolicyVersion:
        return cls.create(
            profile_name="A_SHARE_DAILY_RESEARCH_V0",
            return_convention="SIMPLE_NAV_RETURN",
            annualization_sessions=252,
            volatility_ddof=1,
            risk_free_policy="ZERO_RISK_FREE_ASSUMPTION",
            risk_free_annual_rate="0",
            sortino_target="0",
            drawdown_convention="RUNNING_PEAK_TO_NAV",
            turnover_convention=(
                "GROSS_TRADED_NOTIONAL_OVER_ARITHMETIC_MEAN_DAILY_NAV"
            ),
            period_return_convention="PERIOD_END_OVER_PREVIOUS_PERIOD_END",
            missing_data_policy="FAIL_CLOSED_EXACT_SESSIONS",
            numeric_precision=12,
            numeric_rounding="ROUND_HALF_EVEN",
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile_name": self.profile_name,
            "return_convention": self.return_convention,
            "annualization_sessions": self.annualization_sessions,
            "volatility_ddof": self.volatility_ddof,
            "risk_free_policy": self.risk_free_policy,
            "risk_free_annual_rate": self.risk_free_annual_rate,
            "sortino_target": self.sortino_target,
            "drawdown_convention": self.drawdown_convention,
            "turnover_convention": self.turnover_convention,
            "period_return_convention": self.period_return_convention,
            "missing_data_policy": self.missing_data_policy,
            "numeric_precision": self.numeric_precision,
            "numeric_rounding": self.numeric_rounding,
        }

    def assert_canonical(self) -> None:
        digest = canonical_sha256(self._payload())
        if self.content_sha256 != digest or self.policy_id != "rap_sha256_" + digest:
            raise ResultAnalyticsError("analytics policy identity/content mismatch")

    def to_wire(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "content_sha256": self.content_sha256,
            **self._payload(),
        }


@dataclass(frozen=True, slots=True)
class SourceResultBinding:
    result_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        _text(self.result_id, "result_id")
        _sha(self.content_sha256, "content_sha256")

    def to_wire(self) -> dict[str, str]:
        return {
            "result_id": self.result_id,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkObservation:
    session_date: date
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.session_date, date):
            raise TypeError("session_date must be date")
        object.__setattr__(
            self,
            "value",
            exact_decimal_text(self.value, "benchmark value", positive=True),
        )

    def to_wire(self) -> dict[str, str]:
        return {"session_date": self.session_date.isoformat(), "value": self.value}


@dataclass(frozen=True, slots=True)
class BenchmarkSeriesVersion:
    benchmark_series_id: str
    content_sha256: str
    name: str
    rows: tuple[BenchmarkObservation, ...]
    source_provenance_refs: tuple[str, ...]
    alignment_policy: str
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = "v3.benchmark_series/1.0.0"

    @classmethod
    def create(
        cls,
        *,
        name: str,
        rows: tuple[BenchmarkObservation, ...],
        source_provenance_refs: tuple[str, ...],
        alignment_policy: str,
        truth_admission: TruthAdmissionState,
    ) -> BenchmarkSeriesVersion:
        _text(name, "benchmark name")
        _text(alignment_policy, "alignment_policy")
        if not rows or any(not isinstance(row, BenchmarkObservation) for row in rows):
            raise ResultAnalyticsError("benchmark rows must be non-empty observations")
        dates = tuple(row.session_date for row in rows)
        if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
            raise ResultAnalyticsError("benchmark dates must be unique and increasing")
        if not source_provenance_refs:
            raise ResultAnalyticsError("benchmark requires provenance references")
        for reference in source_provenance_refs:
            _text(reference, "benchmark provenance reference")
        if not isinstance(truth_admission, TruthAdmissionState):
            raise TypeError("truth_admission must be TruthAdmissionState")
        payload = {
            "schema_version": cls.schema_version,
            "name": name,
            "rows": [row.to_wire() for row in rows],
            "source_provenance_refs": list(source_provenance_refs),
            "alignment_policy": alignment_policy,
            "truth_admission": truth_admission.to_wire(),
        }
        digest = canonical_sha256(payload)
        return cls(
            "bmsv_sha256_" + digest,
            digest,
            name,
            rows,
            source_provenance_refs,
            alignment_policy,
            truth_admission,
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "rows": [row.to_wire() for row in self.rows],
            "source_provenance_refs": list(self.source_provenance_refs),
            "alignment_policy": self.alignment_policy,
            "truth_admission": self.truth_admission.to_wire(),
        }

    def assert_canonical(self) -> None:
        digest = canonical_sha256(self._payload())
        if (
            self.content_sha256 != digest
            or self.benchmark_series_id != "bmsv_sha256_" + digest
        ):
            raise ResultAnalyticsError("benchmark identity/content mismatch")

    def to_wire(self) -> dict[str, object]:
        return {
            "benchmark_series_id": self.benchmark_series_id,
            "content_sha256": self.content_sha256,
            **self._payload(),
        }


@dataclass(frozen=True, slots=True)
class ReturnSeriesRow:
    session_date: date
    nav: str
    session_return: AnalyticsMetric
    cumulative_return: AnalyticsMetric

    def to_wire(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "nav": self.nav,
            "session_return": self.session_return.to_wire(),
            "cumulative_return": self.cumulative_return.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class DrawdownSeriesRow:
    session_date: date
    drawdown: AnalyticsMetric

    def to_wire(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "drawdown": self.drawdown.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class DrawdownEpisode:
    peak_date: date
    trough_date: date
    recovery_date: date | None
    duration_sessions: int
    recovery_status: DrawdownRecoveryStatus
    max_drawdown: AnalyticsMetric

    def to_wire(self) -> dict[str, object]:
        return {
            "peak_date": self.peak_date.isoformat(),
            "trough_date": self.trough_date.isoformat(),
            "recovery_date": self.recovery_date.isoformat()
            if self.recovery_date
            else None,
            "duration_sessions": self.duration_sessions,
            "recovery_status": self.recovery_status.value,
            "max_drawdown": self.max_drawdown.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class PeriodReturnRow:
    period_kind: str
    period_label: str
    start_date: date
    end_date: date
    period_return: AnalyticsMetric

    def to_wire(self) -> dict[str, object]:
        return {
            "period_kind": self.period_kind,
            "period_label": self.period_label,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "period_return": self.period_return.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class CostAnalytics:
    fill_count: int
    buy_traded_notional: str
    sell_traded_notional: str
    gross_traded_notional: str
    commission: str
    stamp_duty: str
    transfer_fee: str
    exchange_fee: str
    total_fees: str
    fee_over_traded_notional: AnalyticsMetric
    observed_fee_load_over_start_nav: AnalyticsMetric

    def to_wire(self) -> dict[str, object]:
        return {
            "fill_count": self.fill_count,
            "buy_traded_notional": self.buy_traded_notional,
            "sell_traded_notional": self.sell_traded_notional,
            "gross_traded_notional": self.gross_traded_notional,
            "fee_breakdown": {
                "commission": self.commission,
                "stamp_duty": self.stamp_duty,
                "transfer_fee": self.transfer_fee,
                "exchange_fee": self.exchange_fee,
            },
            "total_fees": self.total_fees,
            "fee_over_traded_notional": self.fee_over_traded_notional.to_wire(),
            "observed_fee_load_over_start_nav": (
                self.observed_fee_load_over_start_nav.to_wire()
            ),
        }


@dataclass(frozen=True, slots=True)
class TurnoverAnalytics:
    convention: str
    gross_traded_notional: str
    average_daily_nav: str
    turnover: AnalyticsMetric

    def to_wire(self) -> dict[str, object]:
        return {
            "convention": self.convention,
            "gross_traded_notional": self.gross_traded_notional,
            "average_daily_nav": self.average_daily_nav,
            "turnover": self.turnover.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class RelativeReturnRow:
    session_date: date
    relative_nav: AnalyticsMetric
    session_excess_return: AnalyticsMetric

    def to_wire(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "relative_nav": self.relative_nav.to_wire(),
            "session_excess_return": self.session_excess_return.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkAnalytics:
    status: BenchmarkStatus
    benchmark_series_id: str | None
    benchmark_content_sha256: str | None
    benchmark_name: str | None
    aligned_benchmark_total_return: AnalyticsMetric
    relative_returns: tuple[RelativeReturnRow, ...]
    tracking_difference: AnalyticsMetric
    tracking_error: AnalyticsMetric
    alpha: AnalyticsMetric
    beta: AnalyticsMetric

    def to_wire(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "benchmark_series_id": self.benchmark_series_id,
            "benchmark_content_sha256": self.benchmark_content_sha256,
            "benchmark_name": self.benchmark_name,
            "aligned_benchmark_total_return": (
                self.aligned_benchmark_total_return.to_wire()
            ),
            "relative_returns": [row.to_wire() for row in self.relative_returns],
            "tracking_difference": self.tracking_difference.to_wire(),
            "tracking_error": self.tracking_error.to_wire(),
            "alpha": self.alpha.to_wire(),
            "beta": self.beta.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class BacktestResultAnalytics:
    analytics_id: str
    content_sha256: str
    source_result_id: str
    source_result_content_sha256: str
    analytics_policy_id: str
    analytics_policy_content_sha256: str
    benchmark_series_id: str | None
    benchmark_content_sha256: str | None
    start_nav: AnalyticsMetric
    end_nav: AnalyticsMetric
    total_return: AnalyticsMetric
    annualized_return: AnalyticsMetric
    annualized_volatility: AnalyticsMetric
    max_drawdown: AnalyticsMetric
    sharpe: AnalyticsMetric
    sortino: AnalyticsMetric
    return_series: tuple[ReturnSeriesRow, ...]
    drawdown_series: tuple[DrawdownSeriesRow, ...]
    drawdown_episode: DrawdownEpisode | None
    monthly_returns: tuple[PeriodReturnRow, ...]
    yearly_returns: tuple[PeriodReturnRow, ...]
    costs: CostAnalytics
    turnover: TurnoverAnalytics
    benchmark: BenchmarkAnalytics
    truth_admission: TruthAdmissionState

    schema_version: ClassVar[str] = "v3.backtest_result_analytics/1.0.0"

    @classmethod
    def create(cls, **values: object) -> BacktestResultAnalytics:
        payload = cls._payload_from_values(values)
        digest = canonical_sha256(payload)
        return cls(
            analytics_id="bra_sha256_" + digest,
            content_sha256=digest,
            **values,
        )

    @classmethod
    def _payload_from_values(cls, values: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": cls.schema_version,
            "source_result": {
                "result_id": values["source_result_id"],
                "content_sha256": values["source_result_content_sha256"],
            },
            "analytics_policy": {
                "policy_id": values["analytics_policy_id"],
                "content_sha256": values["analytics_policy_content_sha256"],
            },
            "benchmark_binding": (
                {
                    "benchmark_series_id": values["benchmark_series_id"],
                    "content_sha256": values["benchmark_content_sha256"],
                }
                if values["benchmark_series_id"] is not None
                else None
            ),
            "metrics": {
                name: values[name].to_wire()
                for name in (
                    "start_nav",
                    "end_nav",
                    "total_return",
                    "annualized_return",
                    "annualized_volatility",
                    "max_drawdown",
                    "sharpe",
                    "sortino",
                )
            },
            "return_series": [row.to_wire() for row in values["return_series"]],
            "drawdown_series": [
                row.to_wire() for row in values["drawdown_series"]
            ],
            "drawdown_episode": values["drawdown_episode"].to_wire()
            if values["drawdown_episode"]
            else None,
            "monthly_returns": [
                row.to_wire() for row in values["monthly_returns"]
            ],
            "yearly_returns": [row.to_wire() for row in values["yearly_returns"]],
            "costs": values["costs"].to_wire(),
            "turnover": values["turnover"].to_wire(),
            "benchmark": values["benchmark"].to_wire(),
            "truth_admission": values["truth_admission"].to_wire(),
        }

    def to_wire(self) -> dict[str, object]:
        values = {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
            if field not in {"analytics_id", "content_sha256", "schema_version"}
        }
        return {
            "artifact_type": "BacktestResultAnalytics",
            "analytics_id": self.analytics_id,
            "content_sha256": self.content_sha256,
            **self._payload_from_values(values),
        }


__all__ = [
    "AnalyticsMetric",
    "BacktestResultAnalytics",
    "BenchmarkAnalytics",
    "BenchmarkObservation",
    "BenchmarkSeriesVersion",
    "BenchmarkStatus",
    "CostAnalytics",
    "DrawdownEpisode",
    "DrawdownRecoveryStatus",
    "DrawdownSeriesRow",
    "MetricStatus",
    "PeriodReturnRow",
    "RelativeReturnRow",
    "ResultAnalyticsError",
    "ResultAnalyticsPolicyVersion",
    "ReturnSeriesRow",
    "SourceResultBinding",
    "TurnoverAnalytics",
    "exact_decimal_text",
]
