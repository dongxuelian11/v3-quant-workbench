import React, { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { buildResultChartSeries, RESULT_ANALYTICS_DEVELOPMENT_STATE, RESULT_ANALYTICS_PRODUCTION_DEFAULT, type AnalyticsMetricView, type ResultAnalyticsSurfaceState, type ResultAnalyticsView } from "../resultAnalyticsViewModel";
import "./ResultAnalyticsPanel.css";

const tabs = ["Overview", "Period Returns", "Trading & Cost", "Benchmark", "Policy & Identity"] as const;
type ResultTab = typeof tabs[number];

const metricLabel = (metric: AnalyticsMetricView, formatter: (value: number) => string): string => metric.status === "AVAILABLE" && metric.value !== null ? formatter(Number(metric.value)) : `${metric.status} · ${metric.reason}`;
const percent = (metric: AnalyticsMetricView, digits = 2): string => metricLabel(metric, (value) => `${(value * 100).toFixed(digits)}%`);
const number = (metric: AnalyticsMetricView, digits = 3): string => metricLabel(metric, (value) => value.toFixed(digits));
const money = (value: string): string => new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));

function ResultAnalyticsChart({ analytics }: { analytics: ResultAnalyticsView }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current, undefined, { renderer: "canvas" });
    const series = buildResultChartSeries(analytics);
    const relativeSeries = series.relativePerformancePercent === null ? [] : [{ name: "Relative performance", type: "line", yAxisIndex: 1, data: series.relativePerformancePercent, symbol: "none", lineStyle: { width: 1.1, color: "#E4B567", type: "dashed" } }];
    chart.setOption({
      animation: false,
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", backgroundColor: "#111722", borderColor: "#364052", textStyle: { color: "#E7EBF3", fontSize: 11 } },
      legend: { top: 8, right: 12, textStyle: { color: "#8B93A7", fontSize: 10 }, data: ["NAV", "Cumulative return", ...(series.relativePerformancePercent === null ? [] : ["Relative performance"]), "Drawdown"] },
      grid: [{ left: 58, right: 55, top: 42, height: "53%" }, { left: 58, right: 55, top: "73%", height: "16%" }],
      xAxis: [
        { type: "category", data: series.dates, boundaryGap: false, axisLine: { lineStyle: { color: "#343A4D" } }, axisLabel: { color: "#80889B", fontSize: 10 }, axisTick: { show: false } },
        { type: "category", gridIndex: 1, data: series.dates, boundaryGap: false, axisLine: { lineStyle: { color: "#343A4D" } }, axisLabel: { color: "#80889B", fontSize: 10 }, axisTick: { show: false } }
      ],
      yAxis: [
        { type: "value", scale: true, axisLabel: { color: "#80889B", fontSize: 10 }, splitLine: { lineStyle: { color: "#232A38" } } },
        { type: "value", position: "right", axisLabel: { color: "#80889B", fontSize: 10, formatter: "{value}%" }, splitLine: { show: false } },
        { type: "value", gridIndex: 1, max: 0, axisLabel: { color: "#80889B", fontSize: 10, formatter: "{value}%" }, splitLine: { lineStyle: { color: "#232A38" } } }
      ],
      series: [
        { name: "NAV", type: "line", data: series.nav, symbol: "none", lineStyle: { width: 2, color: "#53C7F0" }, areaStyle: { color: "rgba(83,199,240,.08)" } },
        { name: "Cumulative return", type: "line", yAxisIndex: 1, data: series.cumulativeReturnPercent, symbol: "none", lineStyle: { width: 1.2, color: "#86D5A5" } },
        ...relativeSeries,
        { name: "Drawdown", type: "line", xAxisIndex: 1, yAxisIndex: 2, data: series.drawdownPercent, symbol: "none", lineStyle: { width: 1.2, color: "#F07676" }, areaStyle: { color: "rgba(240,118,118,.12)" } }
      ]
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [analytics]);
  return <div ref={host} className="result-analytics-chart" role="img" aria-label="由 Result Analytics 实际序列驱动的 NAV、累计收益、可选相对净值与回撤图" data-testid="result-analytics-chart" data-analytics-id={analytics.analyticsId}/>;
}

function KpiStrip({ analytics: a }: { analytics: ResultAnalyticsView }) {
  const items = [
    ["Total return", percent(a.metrics.totalReturn), "positive"],
    ["Annualized", percent(a.metrics.annualizedReturn), "positive"],
    ["Volatility", percent(a.metrics.annualizedVolatility), "neutral"],
    ["Max drawdown", percent(a.metrics.maxDrawdown), "negative"],
    ["Sharpe", number(a.metrics.sharpe), "neutral"],
    ["Turnover", percent(a.turnover.turnover), "neutral"]
  ] as const;
  return <div className="result-kpi-strip" aria-label="Result Analytics KPI">{items.map(([label, value, tone]) => <div key={label}><small>{label}</small><strong className={tone}>{value}</strong></div>)}</div>;
}

function Overview({ analytics: a }: { analytics: ResultAnalyticsView }) {
  const episode = a.drawdownEpisode;
  return <div className="result-overview"><KpiStrip analytics={a}/><div className="result-analysis-plane"><ResultAnalyticsChart analytics={a}/><aside className="result-facts"><header><small>DRAWDOWN EPISODE</small><b>{percent(a.metrics.maxDrawdown)}</b></header>{episode ? <dl><dt>Peak</dt><dd>{episode.peakDate}</dd><dt>Trough</dt><dd>{episode.troughDate}</dd><dt>Recovery</dt><dd>{episode.recoveryDate ?? "—"}</dd><dt>Duration</dt><dd>{episode.durationSessions} sessions</dd><dt>Status</dt><dd className={episode.recoveryStatus === "RECOVERED" ? "ok" : "warning"}>{episode.recoveryStatus}</dd></dl> : <p className="result-empty-detail">NO NEGATIVE DRAWDOWN EPISODE</p>}<header><small>BENCHMARK BINDING</small><b>{a.benchmark.name ?? "Benchmark not available"}</b></header><dl><dt>Total return</dt><dd>{percent(a.benchmark.totalReturn)}</dd><dt>Tracking diff.</dt><dd>{percent(a.benchmark.trackingDifference)}</dd><dt>Tracking error</dt><dd>{percent(a.benchmark.trackingError)}</dd></dl></aside></div></div>;
}

function ReturnTable({ title, rows }: { title: string; rows: ResultAnalyticsView["monthlyReturns"] }) {
  return <section className="result-ledger-table"><header><small>PERIOD RETURN</small><h2>{title}</h2></header><div className="result-table-head"><span>Period</span><span>Start session</span><span>End session</span><span>Return</span></div>{rows.map((row) => <div className="result-table-row" key={row.periodLabel}><b>{row.periodLabel}</b><span>{row.startDate}</span><span>{row.endDate}</span><strong className={row.periodReturn.status === "AVAILABLE" && Number(row.periodReturn.value) >= 0 ? "positive" : "negative"}>{percent(row.periodReturn, 3)}</strong></div>)}</section>;
}

function PeriodReturns({ analytics: a }: { analytics: ResultAnalyticsView }) {
  return <div className="result-split-ledgers"><ReturnTable title="Monthly returns" rows={a.monthlyReturns}/><ReturnTable title="Yearly returns" rows={a.yearlyReturns}/></div>;
}

function TradingCost({ analytics }: { analytics: ResultAnalyticsView }) {
  const { costs, turnover } = analytics;
  return <div className="result-trading-ledger"><section><header><small>EXACT FILLS / FEE LEDGER</small><h2>Observed trading and cost</h2></header><dl className="result-dense-dl"><dt>Fill count</dt><dd>{costs.fillCount}</dd><dt>Buy notional</dt><dd>¥ {money(costs.buyTradedNotional)}</dd><dt>Sell notional</dt><dd>¥ {money(costs.sellTradedNotional)}</dd><dt>Gross traded notional</dt><dd>¥ {money(costs.grossTradedNotional)}</dd><dt>Total fees</dt><dd>¥ {money(costs.totalFees)}</dd><dt>Fee / traded notional</dt><dd>{percent(costs.feeOverTradedNotional, 3)}</dd><dt>Observed fee load / start NAV</dt><dd>{percent(costs.observedFeeLoadOverStartNav, 4)}</dd></dl></section><section><header><small>FEE BREAKDOWN</small><h2>Reconciled components</h2></header><dl className="result-dense-dl"><dt>Commission</dt><dd>¥ {money(costs.commission)}</dd><dt>Stamp duty</dt><dd>¥ {money(costs.stampDuty)}</dd><dt>Transfer fee</dt><dd>¥ {money(costs.transferFee)}</dd><dt>Exchange fee</dt><dd>¥ {money(costs.exchangeFee)}</dd></dl><div className="result-warning"><b>Counterfactual no-cost rerun</b><span>NOT AVAILABLE</span><code>COUNTERFACTUAL_NO_COST_RERUN_NOT_AVAILABLE</code><p>No pre-cost return field exists; fees are not added back to NAV.</p></div></section><section><header><small>TURNOVER POLICY</small><h2>Deterministic denominator</h2></header><dl className="result-dense-dl"><dt>Gross traded notional</dt><dd>¥ {money(costs.grossTradedNotional)}</dd><dt>Average daily NAV</dt><dd>¥ {money(turnover.averageDailyNav)}</dd><dt>Turnover</dt><dd>{percent(turnover.turnover, 3)}</dd></dl><code className="result-policy-code">{analytics.policy.turnoverConvention}</code></section></div>;
}

function BenchmarkPanel({ analytics }: { analytics: ResultAnalyticsView }) {
  const benchmark = analytics.benchmark;
  return <div className="result-benchmark"><header><div><small>OPTIONAL EXACT BENCHMARK</small><h2>{benchmark.name ?? "Benchmark not available"}</h2></div><span className={benchmark.status === "AVAILABLE" ? "result-available" : "result-unavailable"}>{benchmark.status}</span></header>{benchmark.status === "BENCHMARK_NOT_AVAILABLE" ? <div className="result-empty-detail"><b>BENCHMARK NOT AVAILABLE</b><p>No default index was substituted. Relative-performance series is omitted.</p><code>{benchmark.trackingDifference.reason}</code></div> : <><div className="result-benchmark-kpis"><span><small>Benchmark return</small><b>{percent(benchmark.totalReturn)}</b></span><span><small>Tracking difference</small><b>{percent(benchmark.trackingDifference)}</b></span><span><small>Tracking error</small><b>{percent(benchmark.trackingError)}</b></span><span><small>Alpha / Beta</small><b>{number(benchmark.alpha)}</b></span></div><div className="result-table-head benchmark"><span>Session</span><span>Relative NAV</span><span>Session excess return</span></div>{benchmark.relativeReturns.map((row) => <div className="result-table-row benchmark" key={row.sessionDate}><b>{row.sessionDate}</b><span>{number(row.relativeNav, 6)}</span><span>{percent(row.sessionExcessReturn, 4)}</span></div>)}<footer><code>{benchmark.seriesId}</code><code>{benchmark.contentSha256}</code><p>No symbol download and no default index. Date alignment is exact.</p></footer></>}</div>;
}

function PolicyIdentity({ analytics: a }: { analytics: ResultAnalyticsView }) {
  return <div className="result-identity-grid"><section><header><small>EXACT BINDINGS</small><h2>Result → Policy → Benchmark → Analytics</h2></header><dl className="result-identity-list"><dt>Source Result ID</dt><dd><code>{a.sourceResult.resultId}</code></dd><dt>Source content SHA-256</dt><dd><code>{a.sourceResult.contentSha256}</code></dd><dt>Policy ID</dt><dd><code>{a.policy.policyId}</code></dd><dt>Policy content SHA-256</dt><dd><code>{a.policy.contentSha256}</code></dd><dt>Benchmark ID</dt><dd><code>{a.benchmark.seriesId ?? "BENCHMARK_NOT_AVAILABLE"}</code></dd><dt>Benchmark content SHA-256</dt><dd><code>{a.benchmark.contentSha256 ?? "BENCHMARK_NOT_AVAILABLE"}</code></dd><dt>Analytics ID</dt><dd><code>{a.analyticsId}</code></dd><dt>Analytics content SHA-256</dt><dd><code>{a.contentSha256}</code></dd></dl></section><section><header><small>ANALYTICS POLICY</small><h2>{a.policy.profileName}</h2></header><dl className="result-dense-dl"><dt>Annualization sessions</dt><dd>{a.policy.annualizationSessions}</dd><dt>Volatility ddof</dt><dd>{a.policy.volatilityDdoF}</dd><dt>Risk-free</dt><dd>{a.policy.riskFreePolicy}</dd><dt>Sortino target</dt><dd>{a.policy.sortinoTarget}</dd><dt>Numeric precision</dt><dd>{a.policy.numericPrecision} decimals</dd><dt>Rounding</dt><dd>{a.policy.numericRounding}</dd><dt>Truth</dt><dd>{a.truthAdmission.canonicalTruthState}</dd><dt>Admission</dt><dd>{a.truthAdmission.canonicalAdmissionState}</dd><dt>Fixture boundary</dt><dd>{a.fixtureBoundary}</dd></dl></section></div>;
}

function defaultSurfaceState(): ResultAnalyticsSurfaceState {
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).get("resultAnalyticsFixture") === "development" ? RESULT_ANALYTICS_DEVELOPMENT_STATE : RESULT_ANALYTICS_PRODUCTION_DEFAULT;
}

export function ResultPanelView({ surfaceState }: { surfaceState: ResultAnalyticsSurfaceState }) {
  const [tab, setTab] = useState<ResultTab>("Overview");
  const state = surfaceState;
  if (state.analytics === null) return <section className="panel-page result-workspace result-analytics-lab result-empty" data-testid="result-surface" data-primary-panel="result-review" data-major-panel data-result-boundary={state.boundary}><header className="analysis-header result-analytics-header"><div className="analysis-title"><small>BACKTEST RESULT ANALYTICS / V0</small><h1>Deterministic Result Lab</h1><p><span className="result-source-boundary">{state.boundary}</span></p></div></header><div className="result-empty-state"><small>RESULT AUTHORITY</small><h2>{state.reason}</h2><p>No canonical BacktestResultAnalytics source is connected to this production entry. Development fixtures are never substituted silently.</p></div></section>;
  const a = state.analytics;
  return <section className="panel-page result-workspace result-analytics-lab" data-testid="result-surface" data-primary-panel="result-review" data-major-panel data-result-id={a.sourceResult.resultId} data-result-analytics-id={a.analyticsId} data-policy-id={a.policy.policyId} data-benchmark-id={a.benchmark.seriesId}>
    <header className="analysis-header result-analytics-header"><div className="analysis-title"><small>BACKTEST RESULT ANALYTICS / V0</small><h1>Deterministic Result Lab</h1><p><span className="result-source-boundary">DEVELOPMENT / INTEGRATION FIXTURE</span><span className="result-boundary">{a.truthAdmission.canonicalTruthState} · {a.truthAdmission.canonicalAdmissionState}</span><span>exact result / policy / optional benchmark binding</span></p></div><div className="result-hero-metric"><small>TOTAL RETURN</small><b>{percent(a.metrics.totalReturn)}</b><span>{percent(a.benchmark.trackingDifference)} tracking difference</span></div><div className="analysis-actions"><button onClick={() => setTab("Policy & Identity")}>Policy / Identity</button></div></header>
    <div className="analysis-contextline"><code>{a.sourceResult.resultId}</code><span>{a.policy.profileName} · {a.policy.annualizationSessions} sessions</span><span>{a.policy.riskFreePolicy}</span><span>{a.benchmark.name}</span></div>
    <div className="mini-tabs" role="tablist" aria-label="Result Analytics 专业视图">{tabs.map((item) => <button role="tab" aria-selected={tab === item} data-result-tab={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item}>{item}</button>)}</div>
    <div className="result-primary result-analytics-primary primary-canvas" data-primary-canvas>{tab === "Overview" ? <Overview analytics={a}/> : tab === "Period Returns" ? <PeriodReturns analytics={a}/> : tab === "Trading & Cost" ? <TradingCost analytics={a}/> : tab === "Benchmark" ? <BenchmarkPanel analytics={a}/> : <PolicyIdentity analytics={a}/>}</div>
  </section>;
}

export function ResultPanel() {
  return <ResultPanelView surfaceState={defaultSurfaceState()}/>;
}
