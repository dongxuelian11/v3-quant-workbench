import React, { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { buildResultChartSeries, RESULT_LAB_ANALYTICS_V0, type AnalyticsMetricView } from "../resultAnalyticsViewModel";
import "./ResultAnalyticsPanel.css";

const tabs = ["Overview", "Period Returns", "Trading & Cost", "Benchmark", "Policy & Identity"] as const;
type ResultTab = typeof tabs[number];

const percent = (metric: AnalyticsMetricView, digits = 2): string => metric.status === "AVAILABLE" && metric.value !== null ? `${(Number(metric.value) * 100).toFixed(digits)}%` : metric.status;
const number = (metric: AnalyticsMetricView, digits = 3): string => metric.status === "AVAILABLE" && metric.value !== null ? Number(metric.value).toFixed(digits) : metric.status;
const money = (value: string): string => new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));

function ResultAnalyticsChart() {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current, undefined, { renderer: "canvas" });
    const series = buildResultChartSeries(RESULT_LAB_ANALYTICS_V0);
    chart.setOption({
      animation: false,
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", backgroundColor: "#111722", borderColor: "#364052", textStyle: { color: "#E7EBF3", fontSize: 11 } },
      legend: { top: 8, right: 12, textStyle: { color: "#8B93A7", fontSize: 10 }, data: ["NAV", "Cumulative return", "Relative performance", "Drawdown"] },
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
        { name: "Relative performance", type: "line", yAxisIndex: 1, data: series.relativePerformancePercent, symbol: "none", lineStyle: { width: 1.1, color: "#E4B567", type: "dashed" } },
        { name: "Drawdown", type: "line", xAxisIndex: 1, yAxisIndex: 2, data: series.drawdownPercent, symbol: "none", lineStyle: { width: 1.2, color: "#F07676" }, areaStyle: { color: "rgba(240,118,118,.12)" } }
      ]
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, []);
  return <div ref={host} className="result-analytics-chart" role="img" aria-label="由 Result Analytics 实际序列驱动的 NAV、累计收益、相对净值与回撤图" data-testid="result-analytics-chart" data-analytics-id={RESULT_LAB_ANALYTICS_V0.analyticsId}/>;
}

function KpiStrip() {
  const a = RESULT_LAB_ANALYTICS_V0;
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

function Overview() {
  const a = RESULT_LAB_ANALYTICS_V0;
  return <div className="result-overview"><KpiStrip/><div className="result-analysis-plane"><ResultAnalyticsChart/><aside className="result-facts"><header><small>DRAWDOWN EPISODE</small><b>{percent(a.metrics.maxDrawdown)}</b></header><dl><dt>Peak</dt><dd>{a.drawdownEpisode.peakDate}</dd><dt>Trough</dt><dd>{a.drawdownEpisode.troughDate}</dd><dt>Recovery</dt><dd>{a.drawdownEpisode.recoveryDate}</dd><dt>Duration</dt><dd>{a.drawdownEpisode.durationSessions} sessions</dd><dt>Status</dt><dd className="ok">{a.drawdownEpisode.recoveryStatus}</dd></dl><header><small>BENCHMARK BINDING</small><b>{a.benchmark.name}</b></header><dl><dt>Total return</dt><dd>{percent(a.benchmark.totalReturn)}</dd><dt>Tracking diff.</dt><dd>{percent(a.benchmark.trackingDifference)}</dd><dt>Tracking error</dt><dd>{percent(a.benchmark.trackingError)}</dd></dl></aside></div></div>;
}

function ReturnTable({ title, rows }: { title: string; rows: readonly { periodLabel: string; startDate: string; endDate: string; periodReturn: string }[] }) {
  return <section className="result-ledger-table"><header><small>PERIOD RETURN</small><h2>{title}</h2></header><div className="result-table-head"><span>Period</span><span>Start session</span><span>End session</span><span>Return</span></div>{rows.map((row) => <div className="result-table-row" key={row.periodLabel}><b>{row.periodLabel}</b><span>{row.startDate}</span><span>{row.endDate}</span><strong className={Number(row.periodReturn) >= 0 ? "positive" : "negative"}>{(Number(row.periodReturn) * 100).toFixed(3)}%</strong></div>)}</section>;
}

function PeriodReturns() {
  const a = RESULT_LAB_ANALYTICS_V0;
  return <div className="result-split-ledgers"><ReturnTable title="Monthly returns" rows={a.monthlyReturns}/><ReturnTable title="Yearly returns" rows={a.yearlyReturns}/></div>;
}

function TradingCost() {
  const { costs, turnover } = RESULT_LAB_ANALYTICS_V0;
  return <div className="result-trading-ledger"><section><header><small>EXACT FILLS / FEE LEDGER</small><h2>Observed trading and cost</h2></header><dl className="result-dense-dl"><dt>Fill count</dt><dd>{costs.fillCount}</dd><dt>Buy notional</dt><dd>¥ {money(costs.buyTradedNotional)}</dd><dt>Sell notional</dt><dd>¥ {money(costs.sellTradedNotional)}</dd><dt>Gross traded notional</dt><dd>¥ {money(costs.grossTradedNotional)}</dd><dt>Total fees</dt><dd>¥ {money(costs.totalFees)}</dd><dt>Fee / traded notional</dt><dd>{percent(costs.feeOverTradedNotional, 3)}</dd><dt>Observed fee load / start NAV</dt><dd>{percent(costs.observedFeeLoadOverStartNav, 4)}</dd></dl></section><section><header><small>FEE BREAKDOWN</small><h2>Reconciled components</h2></header><dl className="result-dense-dl"><dt>Commission</dt><dd>¥ {money(costs.commission)}</dd><dt>Stamp duty</dt><dd>¥ {money(costs.stampDuty)}</dd><dt>Transfer fee</dt><dd>¥ {money(costs.transferFee)}</dd><dt>Exchange fee</dt><dd>¥ {money(costs.exchangeFee)}</dd></dl><div className="result-warning"><b>Counterfactual no-cost rerun</b><span>NOT AVAILABLE</span><code>COUNTERFACTUAL_NO_COST_RERUN_NOT_AVAILABLE</code><p>No pre-cost return field exists; fees are not added back to NAV.</p></div></section><section><header><small>TURNOVER POLICY</small><h2>Deterministic denominator</h2></header><dl className="result-dense-dl"><dt>Gross traded notional</dt><dd>¥ {money(costs.grossTradedNotional)}</dd><dt>Average daily NAV</dt><dd>¥ {money(turnover.averageDailyNav)}</dd><dt>Turnover</dt><dd>{percent(turnover.turnover, 3)}</dd></dl><code className="result-policy-code">{RESULT_LAB_ANALYTICS_V0.policy.turnoverConvention}</code></section></div>;
}

function BenchmarkPanel() {
  const benchmark = RESULT_LAB_ANALYTICS_V0.benchmark;
  return <div className="result-benchmark"><header><div><small>OPTIONAL EXACT BENCHMARK</small><h2>{benchmark.name}</h2></div><span className="result-available">{benchmark.status}</span></header><div className="result-benchmark-kpis"><span><small>Benchmark return</small><b>{percent(benchmark.totalReturn)}</b></span><span><small>Tracking difference</small><b>{percent(benchmark.trackingDifference)}</b></span><span><small>Tracking error</small><b>{percent(benchmark.trackingError)}</b></span><span><small>Alpha / Beta</small><b>{benchmark.alpha.status}</b></span></div><div className="result-table-head benchmark"><span>Session</span><span>Relative NAV</span><span>Session excess return</span></div>{benchmark.relativeReturns.map((row) => <div className="result-table-row benchmark" key={row.sessionDate}><b>{row.sessionDate}</b><span>{Number(row.relativeNav).toFixed(6)}</span><span>{row.sessionExcessReturn.value === null ? row.sessionExcessReturn.reason : `${(Number(row.sessionExcessReturn.value) * 100).toFixed(4)}%`}</span></div>)}<footer><code>{benchmark.seriesId}</code><code>{benchmark.contentSha256}</code><p>No symbol download and no default index. Date alignment is exact.</p></footer></div>;
}

function PolicyIdentity() {
  const a = RESULT_LAB_ANALYTICS_V0;
  return <div className="result-identity-grid"><section><header><small>EXACT BINDINGS</small><h2>Result → Policy → Benchmark → Analytics</h2></header><dl className="result-identity-list"><dt>Source Result ID</dt><dd><code>{a.sourceResult.resultId}</code></dd><dt>Source content SHA-256</dt><dd><code>{a.sourceResult.contentSha256}</code></dd><dt>Policy ID</dt><dd><code>{a.policy.policyId}</code></dd><dt>Policy content SHA-256</dt><dd><code>{a.policy.contentSha256}</code></dd><dt>Benchmark ID</dt><dd><code>{a.benchmark.seriesId}</code></dd><dt>Benchmark content SHA-256</dt><dd><code>{a.benchmark.contentSha256}</code></dd><dt>Analytics ID</dt><dd><code>{a.analyticsId}</code></dd><dt>Analytics content SHA-256</dt><dd><code>{a.contentSha256}</code></dd></dl></section><section><header><small>ANALYTICS POLICY</small><h2>{a.policy.profileName}</h2></header><dl className="result-dense-dl"><dt>Annualization sessions</dt><dd>{a.policy.annualizationSessions}</dd><dt>Volatility ddof</dt><dd>{a.policy.volatilityDdoF}</dd><dt>Risk-free</dt><dd>{a.policy.riskFreePolicy}</dd><dt>Sortino target</dt><dd>{a.policy.sortinoTarget}</dd><dt>Numeric precision</dt><dd>{a.policy.numericPrecision} decimals</dd><dt>Truth</dt><dd>{a.truthAdmission.canonicalTruthState}</dd><dt>Admission</dt><dd>{a.truthAdmission.canonicalAdmissionState}</dd><dt>Fixture boundary</dt><dd>{a.fixtureBoundary}</dd></dl></section></div>;
}

export function ResultPanel() {
  const [tab, setTab] = useState<ResultTab>("Overview");
  const a = RESULT_LAB_ANALYTICS_V0;
  return <section className="panel-page result-workspace result-analytics-lab" data-testid="result-surface" data-primary-panel="result-review" data-major-panel data-result-id={a.sourceResult.resultId} data-result-analytics-id={a.analyticsId} data-policy-id={a.policy.policyId} data-benchmark-id={a.benchmark.seriesId}>
    <header className="analysis-header result-analytics-header"><div className="analysis-title"><small>BACKTEST RESULT ANALYTICS / V0</small><h1>Deterministic Result Lab</h1><p><span className="result-boundary">{a.truthAdmission.canonicalTruthState} · {a.truthAdmission.canonicalAdmissionState}</span><span>exact result / policy / benchmark binding</span></p></div><div className="result-hero-metric"><small>TOTAL RETURN</small><b>{percent(a.metrics.totalReturn)}</b><span>{percent(a.benchmark.trackingDifference)} tracking difference</span></div><div className="analysis-actions"><button onClick={() => setTab("Policy & Identity")}>Policy / Identity</button></div></header>
    <div className="analysis-contextline"><code>{a.sourceResult.resultId}</code><span>{a.policy.profileName} · {a.policy.annualizationSessions} sessions</span><span>{a.policy.riskFreePolicy}</span><span>{a.benchmark.name}</span></div>
    <div className="mini-tabs" role="tablist" aria-label="Result Analytics 专业视图">{tabs.map((item) => <button role="tab" aria-selected={tab === item} data-result-tab={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item}>{item}</button>)}</div>
    <div className="result-primary result-analytics-primary primary-canvas" data-primary-canvas>{tab === "Overview" ? <Overview/> : tab === "Period Returns" ? <PeriodReturns/> : tab === "Trading & Cost" ? <TradingCost/> : tab === "Benchmark" ? <BenchmarkPanel/> : <PolicyIdentity/>}</div>
  </section>;
}
