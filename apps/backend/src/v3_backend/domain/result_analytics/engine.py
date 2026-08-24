from __future__ import annotations

from collections import OrderedDict
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from v3_backend.contracts.common.truth_admission import meet_pair
from v3_backend.domain.backtest_runtime import BacktestRunResult, LedgerKind, Side
from v3_backend.provenance.canonical_hash import canonical_sha256

from .model import (
    AnalyticsMetric,
    BacktestResultAnalytics,
    BenchmarkAnalytics,
    BenchmarkSeriesVersion,
    BenchmarkStatus,
    CostAnalytics,
    DrawdownEpisode,
    DrawdownRecoveryStatus,
    DrawdownSeriesRow,
    ExposureSeriesRow,
    MetricStatus,
    PeriodReturnRow,
    PositionConcentrationSummary,
    ProductBacktestResultAnalytics,
    RelativeReturnRow,
    ResultAnalyticsError,
    ResultAnalyticsPolicyVersion,
    ReturnSeriesRow,
    SourceResultBinding,
    TurnoverAnalytics,
    _create_backtest_result_analytics,
    _create_product_backtest_result_analytics,
    exact_decimal_text,
)


class DeterministicResultAnalyticsEngine:
    product_engine_version = "v3.result_analytics_engine/1.1.0"

    def analyze(
        self,
        result: BacktestRunResult,
        source_binding: SourceResultBinding,
        policy: ResultAnalyticsPolicyVersion,
        benchmark: BenchmarkSeriesVersion | None = None,
    ) -> BacktestResultAnalytics:
        if not isinstance(result, BacktestRunResult):
            raise TypeError("result must be BacktestRunResult")
        if not isinstance(source_binding, SourceResultBinding):
            raise TypeError("source_binding must be SourceResultBinding")
        if not isinstance(policy, ResultAnalyticsPolicyVersion):
            raise TypeError("policy must be ResultAnalyticsPolicyVersion")
        if benchmark is not None and not isinstance(benchmark, BenchmarkSeriesVersion):
            raise TypeError("benchmark must be BenchmarkSeriesVersion or None")
        self._assert_result(result, source_binding)
        policy.assert_canonical()
        policy.assert_execution_compatible()
        if benchmark is not None:
            benchmark.assert_canonical()

        nav_rows = tuple(result.nav)
        if not nav_rows:
            raise ResultAnalyticsError("result requires at least one NAV observation")
        dates = tuple(row.session_date for row in nav_rows)
        if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
            raise ResultAnalyticsError("NAV dates must be unique and increasing")
        nav = tuple(self._decimal(row.nav, "NAV", positive=True) for row in nav_rows)
        start_nav = nav[0]
        end_nav = nav[-1]
        returns = tuple(nav[index] / nav[index - 1] - 1 for index in range(1, len(nav)))

        return_series = tuple(
            ReturnSeriesRow(
                row.session_date,
                self._format(value, policy),
                AnalyticsMetric.not_available("NO_PRIOR_SESSION")
                if index == 0
                else self._metric(returns[index - 1], policy),
                self._metric(value / start_nav - 1, policy),
            )
            for index, (row, value) in enumerate(zip(nav_rows, nav, strict=True))
        )
        total_return = end_nav / start_nav - 1
        annualized_return = (
            self._metric(
                self._power(
                    end_nav / start_nav,
                    Decimal(policy.annualization_sessions) / Decimal(len(returns)),
                )
                - 1,
                policy,
            )
            if returns
            else AnalyticsMetric.insufficient_sample("REQUIRES_ONE_SESSION_RETURN")
        )
        volatility, sharpe = self._volatility_and_sharpe(returns, policy)
        sortino = self._sortino(returns, policy)
        drawdowns, max_drawdown, episode = self._drawdown(dates, nav, policy)
        monthly = self._period_returns(dates, nav, "MONTHLY", policy)
        yearly = self._period_returns(dates, nav, "YEARLY", policy)
        costs, turnover = self._cost_and_turnover(result, nav, policy)
        benchmark_analytics = self._benchmark(
            dates, nav, returns, total_return, benchmark, policy
        )
        truth = (
            result.truth_admission
            if benchmark is None
            else meet_pair(result.truth_admission, benchmark.truth_admission)
        )
        return _create_backtest_result_analytics(
            source_result_id=result.result_id,
            source_result_content_sha256=result.content_sha256,
            analytics_policy_id=policy.policy_id,
            analytics_policy_content_sha256=policy.content_sha256,
            benchmark_series_id=benchmark.benchmark_series_id if benchmark else None,
            benchmark_content_sha256=benchmark.content_sha256 if benchmark else None,
            start_nav=self._metric(start_nav, policy),
            end_nav=self._metric(end_nav, policy),
            total_return=self._metric(total_return, policy),
            annualized_return=annualized_return,
            annualized_volatility=volatility,
            max_drawdown=max_drawdown,
            sharpe=sharpe,
            sortino=sortino,
            return_series=return_series,
            drawdown_series=drawdowns,
            drawdown_episode=episode,
            monthly_returns=monthly,
            yearly_returns=yearly,
            costs=costs,
            turnover=turnover,
            benchmark=benchmark_analytics,
            truth_admission=truth,
        )

    def analyze_product_v1_1(
        self,
        result: BacktestRunResult,
        source_binding: SourceResultBinding,
        policy: ResultAnalyticsPolicyVersion,
        benchmark: BenchmarkSeriesVersion | None = None,
    ) -> ProductBacktestResultAnalytics:
        """Derive the additive V1.1 product projection without changing V0 IDs."""

        core = self.analyze(result, source_binding, policy, benchmark)
        calmar = self._calmar(core, policy)
        exposure_series, concentration = self._exposure_and_concentration(
            result, policy
        )
        return _create_product_backtest_result_analytics(
            engine_version=self.product_engine_version,
            core=core,
            calmar=calmar,
            exposure_series=exposure_series,
            concentration=concentration,
            order_count=len(result.orders),
            fill_count=len(result.fills),
            diagnostic_count=len(result.diagnostics),
            truth_admission=core.truth_admission,
        )

    def _calmar(
        self,
        core: BacktestResultAnalytics,
        policy: ResultAnalyticsPolicyVersion,
    ) -> AnalyticsMetric:
        if core.annualized_return.status is not MetricStatus.AVAILABLE:
            return core.annualized_return
        if core.max_drawdown.status is not MetricStatus.AVAILABLE:
            return core.max_drawdown
        drawdown = abs(Decimal(core.max_drawdown.value))
        if drawdown == 0:
            return AnalyticsMetric.not_available("ZERO_DRAWDOWN")
        return self._metric(Decimal(core.annualized_return.value) / drawdown, policy)

    def _exposure_and_concentration(
        self,
        result: BacktestRunResult,
        policy: ResultAnalyticsPolicyVersion,
    ) -> tuple[tuple[ExposureSeriesRow, ...], PositionConcentrationSummary]:
        nav_by_date = {row.session_date: row for row in result.nav}
        holdings_by_date: dict[date, list[tuple[str, Decimal]]] = {
            session_date: [] for session_date in nav_by_date
        }
        seen: set[tuple[date, str]] = set()
        for holding in result.holdings:
            key = (holding.session_date, holding.instrument_id)
            if key in seen or holding.session_date not in nav_by_date:
                raise ResultAnalyticsError("holding rows must be unique and NAV-bound")
            seen.add(key)
            raw_close = self._decimal(holding.raw_close, "holding raw_close", positive=True)
            market_value = self._decimal(
                holding.market_value, "holding market_value", non_negative=True
            )
            if holding.quantity <= 0 or market_value != raw_close * holding.quantity:
                raise ResultAnalyticsError("holding quantity/value is inconsistent")
            holdings_by_date[holding.session_date].append(
                (holding.instrument_id, market_value)
            )

        exposure_rows: list[ExposureSeriesRow] = []
        peak: tuple[Decimal, date, str] | None = None
        counts: list[int] = []
        for nav_row in result.nav:
            nav = self._decimal(nav_row.nav, "NAV", positive=True)
            expected_holdings = self._decimal(
                nav_row.holdings_value, "NAV holdings_value", non_negative=True
            )
            rows = sorted(holdings_by_date[nav_row.session_date])
            observed_holdings = sum((value for _, value in rows), Decimal(0))
            if observed_holdings != expected_holdings:
                raise ResultAnalyticsError("holding values do not reconcile to daily NAV")
            gross = sum((abs(value) for _, value in rows), Decimal(0)) / nav
            net = observed_holdings / nav
            counts.append(len(rows))
            exposure_rows.append(
                ExposureSeriesRow(
                    nav_row.session_date,
                    self._metric(gross, policy),
                    self._metric(net, policy),
                    len(rows),
                )
            )
            for instrument_id, value in rows:
                candidate = (value / nav, nav_row.session_date, instrument_id)
                if peak is None or candidate[0] > peak[0]:
                    peak = candidate

        concentration = PositionConcentrationSummary(
            peak_single_position_weight=(
                AnalyticsMetric.not_available("NO_POSITIONS")
                if peak is None
                else self._metric(peak[0], policy)
            ),
            peak_session_date=None if peak is None else peak[1],
            peak_instrument_id=None if peak is None else peak[2],
            average_held_instrument_count=self._metric(
                Decimal(sum(counts)) / Decimal(len(counts)), policy
            ),
            maximum_held_instrument_count=max(counts, default=0),
        )
        return tuple(exposure_rows), concentration

    def assert_output(
        self,
        result: BacktestRunResult,
        source_binding: SourceResultBinding,
        policy: ResultAnalyticsPolicyVersion,
        benchmark: BenchmarkSeriesVersion | None,
        analytics: BacktestResultAnalytics,
    ) -> None:
        if type(analytics) is not BacktestResultAnalytics:
            raise TypeError("analytics must be BacktestResultAnalytics")
        analytics.assert_canonical()
        recomputed = self.analyze(result, source_binding, policy, benchmark)
        if analytics != recomputed or analytics.to_wire() != recomputed.to_wire():
            raise ResultAnalyticsError(
                "analytics output does not exactly match deterministic recomputation"
            )

    @staticmethod
    def _assert_result(
        result: BacktestRunResult, source_binding: SourceResultBinding
    ) -> None:
        if (
            result.result_id != source_binding.result_id
            or result.content_sha256 != source_binding.content_sha256
        ):
            raise ResultAnalyticsError("source result/hash binding mismatch")
        wire = result.to_wire()
        if set(wire) != {
            "artifact_type",
            "result_id",
            "content_sha256",
            "run_spec_id",
            "target_quantity_vectors",
            "orders",
            "fills",
            "diagnostics",
            "cash_ledger",
            "position_ledger",
            "holdings",
            "nav",
            "truth_admission",
        }:
            raise ResultAnalyticsError("source result wire shape mismatch")
        payload = {
            "schema_version": result.schema_version,
            **{
                key: value
                for key, value in wire.items()
                if key not in {"artifact_type", "result_id", "content_sha256"}
            },
        }
        digest = canonical_sha256(payload)
        if (
            result.content_sha256 != digest
            or result.result_id != "btrr_sha256_" + digest
        ):
            raise ResultAnalyticsError("source result identity/content mismatch")

    @staticmethod
    def _decimal(
        value: str | Decimal,
        name: str,
        *,
        positive: bool = False,
        non_negative: bool = False,
    ) -> Decimal:
        return Decimal(
            exact_decimal_text(
                value,
                name,
                positive=positive,
                non_negative=non_negative,
            )
        )

    @staticmethod
    def _format(value: Decimal, policy: ResultAnalyticsPolicyVersion) -> str:
        if not value.is_finite():
            raise ResultAnalyticsError("computed metric must be finite")
        quantum = Decimal(1).scaleb(-policy.numeric_precision)
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_HALF_EVEN
            quantized = value.quantize(quantum)
        return exact_decimal_text(quantized, "computed metric")

    def _metric(
        self, value: Decimal, policy: ResultAnalyticsPolicyVersion
    ) -> AnalyticsMetric:
        return AnalyticsMetric.available(self._format(value, policy))

    @staticmethod
    def _sqrt(value: Decimal) -> Decimal:
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_HALF_EVEN
            return value.sqrt(context=context)

    @staticmethod
    def _power(base: Decimal, exponent: Decimal) -> Decimal:
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_HALF_EVEN
            return context.power(base, exponent)

    def _sample_stddev(
        self, values: tuple[Decimal, ...], ddof: int
    ) -> Decimal | None:
        if len(values) <= ddof:
            return None
        mean = sum(values, Decimal(0)) / Decimal(len(values))
        variance = sum((value - mean) ** 2 for value in values) / Decimal(
            len(values) - ddof
        )
        return self._sqrt(variance)

    def _volatility_and_sharpe(
        self,
        returns: tuple[Decimal, ...],
        policy: ResultAnalyticsPolicyVersion,
    ) -> tuple[AnalyticsMetric, AnalyticsMetric]:
        standard_deviation = self._sample_stddev(returns, policy.volatility_ddof)
        if standard_deviation is None:
            insufficient = AnalyticsMetric.insufficient_sample(
                "REQUIRES_DDOF_PLUS_ONE_SESSION_RETURNS"
            )
            return insufficient, insufficient
        annual_root = self._sqrt(Decimal(policy.annualization_sessions))
        volatility = self._metric(standard_deviation * annual_root, policy)
        if standard_deviation == 0:
            return volatility, AnalyticsMetric.not_available("ZERO_VARIANCE")
        mean = sum(returns, Decimal(0)) / Decimal(len(returns))
        return volatility, self._metric(mean / standard_deviation * annual_root, policy)

    def _sortino(
        self,
        returns: tuple[Decimal, ...],
        policy: ResultAnalyticsPolicyVersion,
    ) -> AnalyticsMetric:
        if not returns:
            return AnalyticsMetric.insufficient_sample("REQUIRES_ONE_SESSION_RETURN")
        target = Decimal(policy.sortino_target)
        differences = tuple(value - target for value in returns)
        downside = self._sqrt(
            sum(min(value, Decimal(0)) ** 2 for value in differences)
            / Decimal(len(differences))
        )
        if downside == 0:
            return AnalyticsMetric.not_available("ZERO_DOWNSIDE_DEVIATION")
        mean = sum(differences, Decimal(0)) / Decimal(len(differences))
        return self._metric(
            mean / downside * self._sqrt(Decimal(policy.annualization_sessions)),
            policy,
        )

    def _drawdown(
        self,
        dates: tuple[date, ...],
        nav: tuple[Decimal, ...],
        policy: ResultAnalyticsPolicyVersion,
    ) -> tuple[
        tuple[DrawdownSeriesRow, ...], AnalyticsMetric, DrawdownEpisode | None
    ]:
        peak_value = nav[0]
        peak_index = 0
        peak_indices: list[int] = []
        values: list[Decimal] = []
        for index, value in enumerate(nav):
            if value >= peak_value:
                peak_value = value
                peak_index = index
            peak_indices.append(peak_index)
            values.append(value / peak_value - 1)
        minimum = min(values)
        series = tuple(
            DrawdownSeriesRow(session_date, self._metric(value, policy))
            for session_date, value in zip(dates, values, strict=True)
        )
        metric = self._metric(minimum, policy)
        if minimum == 0:
            return series, metric, None
        trough_index = values.index(minimum)
        selected_peak_index = peak_indices[trough_index]
        selected_peak_value = nav[selected_peak_index]
        recovery_index = next(
            (
                index
                for index in range(trough_index + 1, len(nav))
                if nav[index] >= selected_peak_value
            ),
            None,
        )
        duration_end = recovery_index if recovery_index is not None else len(nav) - 1
        episode = DrawdownEpisode(
            peak_date=dates[selected_peak_index],
            trough_date=dates[trough_index],
            recovery_date=dates[recovery_index] if recovery_index is not None else None,
            duration_sessions=duration_end - selected_peak_index,
            recovery_status=(
                DrawdownRecoveryStatus.RECOVERED
                if recovery_index is not None
                else DrawdownRecoveryStatus.UNRECOVERED
            ),
            max_drawdown=metric,
        )
        return series, metric, episode

    def _period_returns(
        self,
        dates: tuple[date, ...],
        nav: tuple[Decimal, ...],
        kind: str,
        policy: ResultAnalyticsPolicyVersion,
    ) -> tuple[PeriodReturnRow, ...]:
        grouped: OrderedDict[str, list[int]] = OrderedDict()
        for index, session_date in enumerate(dates):
            label = (
                f"{session_date.year:04d}-{session_date.month:02d}"
                if kind == "MONTHLY"
                else f"{session_date.year:04d}"
            )
            grouped.setdefault(label, []).append(index)
        rows: list[PeriodReturnRow] = []
        prior_end: Decimal | None = None
        for label, indices in grouped.items():
            start_index = indices[0]
            end_index = indices[-1]
            base = nav[start_index] if prior_end is None else prior_end
            rows.append(
                PeriodReturnRow(
                    kind,
                    label,
                    dates[start_index],
                    dates[end_index],
                    self._metric(nav[end_index] / base - 1, policy),
                )
            )
            prior_end = nav[end_index]
        return tuple(rows)

    def _cost_and_turnover(
        self,
        result: BacktestRunResult,
        nav: tuple[Decimal, ...],
        policy: ResultAnalyticsPolicyVersion,
    ) -> tuple[CostAnalytics, TurnoverAnalytics]:
        fill_ids = tuple(fill.fill_id for fill in result.fills)
        if len(fill_ids) != len(set(fill_ids)):
            raise ResultAnalyticsError("fill IDs must be unique")
        fee_entries = tuple(
            entry for entry in result.cash_ledger if entry.kind is LedgerKind.FEE
        )
        if any(entry.reference_id not in set(fill_ids) for entry in fee_entries):
            raise ResultAnalyticsError("orphan fee-ledger entry")

        buy = Decimal(0)
        sell = Decimal(0)
        commission = Decimal(0)
        stamp = Decimal(0)
        transfer = Decimal(0)
        exchange = Decimal(0)
        for fill in result.fills:
            consideration = self._decimal(
                fill.consideration, "fill consideration", non_negative=True
            )
            execution_price = self._decimal(
                fill.execution_price or fill.raw_price,
                "fill execution price",
                positive=True,
            )
            if (
                fill.quantity <= 0
                or consideration != execution_price * Decimal(fill.quantity)
            ):
                raise ResultAnalyticsError("fill consideration/quantity/price mismatch")
            trade_kind = LedgerKind.BUY if fill.side is Side.BUY else LedgerKind.SELL
            trade_entries = tuple(
                entry
                for entry in result.cash_ledger
                if entry.kind is trade_kind and entry.reference_id == fill.fill_id
            )
            if len(trade_entries) != 1:
                raise ResultAnalyticsError("fill must have exactly one trade-ledger entry")
            expected_amount = -consideration if fill.side is Side.BUY else consideration
            if self._decimal(trade_entries[0].amount, "trade ledger amount") != expected_amount:
                raise ResultAnalyticsError("fill/trade-ledger amount mismatch")

            costs = fill.costs
            components = tuple(
                self._decimal(value, "fee component", non_negative=True)
                for value in (
                    costs.commission,
                    costs.stamp_duty,
                    costs.transfer_fee,
                    costs.exchange_fee,
                )
            )
            total = sum(components, Decimal(0))
            matching_fees = tuple(
                entry for entry in fee_entries if entry.reference_id == fill.fill_id
            )
            if total == 0:
                if matching_fees:
                    raise ResultAnalyticsError("zero-cost fill must not have a fee entry")
            else:
                if len(matching_fees) != 1:
                    raise ResultAnalyticsError(
                        "non-zero fill cost requires exactly one fee entry"
                    )
                fee = matching_fees[0]
                if fee.cost_breakdown is None:
                    raise ResultAnalyticsError("fee entry requires cost breakdown")
                fee_components = tuple(
                    self._decimal(value, "fee ledger component", non_negative=True)
                    for value in (
                        fee.cost_breakdown.commission,
                        fee.cost_breakdown.stamp_duty,
                        fee.cost_breakdown.transfer_fee,
                        fee.cost_breakdown.exchange_fee,
                    )
                )
                if fee_components != components or self._decimal(
                    fee.amount, "fee ledger amount"
                ) != -total:
                    raise ResultAnalyticsError("fill/fee-ledger reconciliation mismatch")
            if fill.side is Side.BUY:
                buy += consideration
            else:
                sell += consideration
            commission += components[0]
            stamp += components[1]
            transfer += components[2]
            exchange += components[3]

        gross = buy + sell
        total_fees = commission + stamp + transfer + exchange
        average_nav = sum(nav, Decimal(0)) / Decimal(len(nav))
        costs = CostAnalytics(
            fill_count=len(result.fills),
            buy_traded_notional=self._format(buy, policy),
            sell_traded_notional=self._format(sell, policy),
            gross_traded_notional=self._format(gross, policy),
            commission=self._format(commission, policy),
            stamp_duty=self._format(stamp, policy),
            transfer_fee=self._format(transfer, policy),
            exchange_fee=self._format(exchange, policy),
            total_fees=self._format(total_fees, policy),
            fee_over_traded_notional=(
                self._metric(total_fees / gross, policy)
                if gross > 0
                else AnalyticsMetric.not_available("NO_TRADES")
            ),
            observed_fee_load_over_start_nav=self._metric(
                total_fees / nav[0], policy
            ),
        )
        turnover = TurnoverAnalytics(
            convention=policy.turnover_convention,
            gross_traded_notional=self._format(gross, policy),
            average_daily_nav=self._format(average_nav, policy),
            turnover=self._metric(gross / average_nav, policy),
        )
        return costs, turnover

    def _benchmark(
        self,
        dates: tuple[date, ...],
        nav: tuple[Decimal, ...],
        returns: tuple[Decimal, ...],
        strategy_total_return: Decimal,
        benchmark: BenchmarkSeriesVersion | None,
        policy: ResultAnalyticsPolicyVersion,
    ) -> BenchmarkAnalytics:
        outside_v0 = AnalyticsMetric.not_available("OUTSIDE_V0_CLOSED_FORMULA")
        if benchmark is None:
            unavailable = AnalyticsMetric.not_available("BENCHMARK_NOT_AVAILABLE")
            return BenchmarkAnalytics(
                status=BenchmarkStatus.BENCHMARK_NOT_AVAILABLE,
                benchmark_series_id=None,
                benchmark_content_sha256=None,
                benchmark_name=None,
                aligned_benchmark_total_return=unavailable,
                relative_returns=(),
                tracking_difference=unavailable,
                tracking_error=unavailable,
                alpha=outside_v0,
                beta=outside_v0,
            )
        if benchmark.alignment_policy != "EXACT_SESSION_DATE_MATCH":
            raise ResultAnalyticsError("unsupported benchmark alignment policy")
        benchmark_dates = tuple(row.session_date for row in benchmark.rows)
        if benchmark_dates != dates:
            raise ResultAnalyticsError("benchmark dates must exactly match result NAV dates")
        values = tuple(
            self._decimal(row.value, "benchmark value", positive=True)
            for row in benchmark.rows
        )
        benchmark_returns = tuple(
            values[index] / values[index - 1] - 1
            for index in range(1, len(values))
        )
        benchmark_total = values[-1] / values[0] - 1
        excess = tuple(
            strategy - reference
            for strategy, reference in zip(returns, benchmark_returns, strict=True)
        )
        relative_rows = tuple(
            RelativeReturnRow(
                session_date,
                self._metric(
                    (strategy_value / nav[0]) / (reference_value / values[0]),
                    policy,
                ),
                AnalyticsMetric.not_available("NO_PRIOR_SESSION")
                if index == 0
                else self._metric(excess[index - 1], policy),
            )
            for index, (session_date, strategy_value, reference_value) in enumerate(
                zip(dates, nav, values, strict=True)
            )
        )
        tracking_stddev = self._sample_stddev(excess, policy.volatility_ddof)
        tracking_error = (
            AnalyticsMetric.insufficient_sample(
                "REQUIRES_DDOF_PLUS_ONE_EXCESS_RETURNS"
            )
            if tracking_stddev is None
            else self._metric(
                tracking_stddev
                * self._sqrt(Decimal(policy.annualization_sessions)),
                policy,
            )
        )
        return BenchmarkAnalytics(
            status=BenchmarkStatus.AVAILABLE,
            benchmark_series_id=benchmark.benchmark_series_id,
            benchmark_content_sha256=benchmark.content_sha256,
            benchmark_name=benchmark.name,
            aligned_benchmark_total_return=self._metric(benchmark_total, policy),
            relative_returns=relative_rows,
            tracking_difference=self._metric(
                strategy_total_return - benchmark_total, policy
            ),
            tracking_error=tracking_error,
            alpha=outside_v0,
            beta=outside_v0,
        )


__all__ = ["DeterministicResultAnalyticsEngine"]
