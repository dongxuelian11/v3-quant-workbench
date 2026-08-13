import React, { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { buildResultChartSeries, RESULT_ANALYTICS_DEVELOPMENT_STATE, RESULT_ANALYTICS_PRODUCTION_DEFAULT, type AnalyticsMetricView, type ResultAnalyticsSurfaceState, type ResultAnalyticsView } from "../resultAnalyticsViewModel";
import "./ResultAnalyticsPanel.css";

const tabs = ["Overview", "Period Returns", "Trading & Cost", "Benchmark", "Policy & Identity"] as const;
type ResultTab = typeof tabs[number];

const metricLabel = (metric: AnalyticsMetricView, formatter: (value: number) => string): string => metric.status === "AVAILABLE" && metric.value !== null ? formatter(Number(metric.value)) : `${availabilityLabel(metric.status)} · ${metric.reason}`;
const percent = (metric: AnalyticsMetricView, digits = 2): string => metricLabel(metric, (value) => `${(value * 100).toFixed(digits)}%`);
const number = (metric: AnalyticsMetricView, digits = 3): string => metricLabel(metric, (value) => value.toFixed(digits));
const money = (value: string): string => new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));

function ResultAnalyticsChart({ analytics }: { analytics: ResultAnalyticsView }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current, undefined, { renderer: "canvas" });
    const series = buildResultChartSeries(analytics);
    const relativeSeries = series.relativePerformancePercent === null ? [] : [{ name: "相对表现", type: "line", yAxisIndex: 1, data: series.relativePerformancePercent, symbol: "none", lineStyle: { width: 1.1, color: "#E4B567", type: "dashed" } }];
    chart.setOption({
      animation: false,
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", backgroundColor: "#111722", borderColor: "#364052", textStyle: { color: "#E7EBF3", fontSize: 11 } },
      legend: { top: 8, right: 12, textStyle: { color: "#8B93A7", fontSize: 10 }, data: ["净值 · NAV", "累计收益", ...(series.relativePerformancePercent === null ? [] : ["相对表现"]), "回撤"] },
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
        { name: "净值 · NAV", type: "line", data: series.nav, symbol: "none", lineStyle: { width: 2, color: "#53C7F0" }, areaStyle: { color: "rgba(83,199,240,.08)" } },
        { name: "累计收益", type: "line", yAxisIndex: 1, data: series.cumulativeReturnPercent, symbol: "none", lineStyle: { width: 1.2, color: "#86D5A5" } },
        ...relativeSeries,
        { name: "回撤", type: "line", xAxisIndex: 1, yAxisIndex: 2, data: series.drawdownPercent, symbol: "none", lineStyle: { width: 1.2, color: "#F07676" }, areaStyle: { color: "rgba(240,118,118,.12)" } }
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
    ["总收益率", percent(a.metrics.totalReturn), "positive"],
    ["年化收益率", percent(a.metrics.annualizedReturn), "positive"],
    ["年化波动率", percent(a.metrics.annualizedVolatility), "neutral"],
    ["最大回撤", percent(a.metrics.maxDrawdown), "negative"],
    ["夏普比率", number(a.metrics.sharpe), "neutral"],
    ["换手率", percent(a.turnover.turnover), "neutral"]
  ] as const;
  return <div className="result-kpi-strip" aria-label="Result Analytics KPI">{items.map(([label, value, tone]) => <div key={label}><small>{label}</small><strong className={tone}>{value}</strong></div>)}</div>;
}

function Overview({ analytics: a }: { analytics: ResultAnalyticsView }) {
  const episode = a.drawdownEpisode;
  return <div className="result-overview"><KpiStrip analytics={a}/><div className="result-analysis-plane"><ResultAnalyticsChart analytics={a}/><aside className="result-facts"><header><small>回撤区间</small><b>{percent(a.metrics.maxDrawdown)}</b></header>{episode ? <dl><dt>峰值</dt><dd>{episode.peakDate}</dd><dt>谷值</dt><dd>{episode.troughDate}</dd><dt>恢复</dt><dd>{episode.recoveryDate ?? "—"}</dd><dt>持续时间</dt><dd>{episode.durationSessions} 个交易日</dd><dt>状态</dt><dd className={episode.recoveryStatus === "RECOVERED" ? "ok" : "warning"}>{recoveryLabel(episode.recoveryStatus)}</dd></dl> : <p className="result-empty-detail">没有负回撤区间</p>}<header><small>基准绑定</small><b>{a.benchmark.name ?? "基准不可用"}</b></header><dl><dt>总收益率</dt><dd>{percent(a.benchmark.totalReturn)}</dd><dt>跟踪差异</dt><dd>{percent(a.benchmark.trackingDifference)}</dd><dt>跟踪误差</dt><dd>{percent(a.benchmark.trackingError)}</dd></dl></aside></div></div>;
}

function ReturnTable({ title, rows }: { title: string; rows: ResultAnalyticsView["monthlyReturns"] }) {
  return <section className="result-ledger-table"><header><small>区间收益</small><h2>{title}</h2></header><div className="result-table-head"><span>区间</span><span>起始交易日</span><span>结束交易日</span><span>收益率</span></div>{rows.map((row) => <div className="result-table-row" key={row.periodLabel}><b>{row.periodLabel}</b><span>{row.startDate}</span><span>{row.endDate}</span><strong className={row.periodReturn.status === "AVAILABLE" && Number(row.periodReturn.value) >= 0 ? "positive" : "negative"}>{percent(row.periodReturn, 3)}</strong></div>)}</section>;
}

function PeriodReturns({ analytics: a }: { analytics: ResultAnalyticsView }) {
  return <div className="result-split-ledgers"><ReturnTable title="月度收益" rows={a.monthlyReturns}/><ReturnTable title="年度收益" rows={a.yearlyReturns}/></div>;
}

function TradingCost({ analytics }: { analytics: ResultAnalyticsView }) {
  const { costs, turnover } = analytics;
  return <div className="result-trading-ledger"><section><header><small>精确成交 / 费用账本</small><h2>已观测交易与成本</h2></header><dl className="result-dense-dl"><dt>成交笔数</dt><dd>{costs.fillCount}</dd><dt>买入名义金额</dt><dd>¥ {money(costs.buyTradedNotional)}</dd><dt>卖出名义金额</dt><dd>¥ {money(costs.sellTradedNotional)}</dd><dt>总成交名义金额</dt><dd>¥ {money(costs.grossTradedNotional)}</dd><dt>总费用</dt><dd>¥ {money(costs.totalFees)}</dd><dt>费用 / 成交名义金额</dt><dd>{percent(costs.feeOverTradedNotional, 3)}</dd><dt>观测费用负载 / 起始净值</dt><dd>{percent(costs.observedFeeLoadOverStartNav, 4)}</dd></dl></section><section><header><small>费用分解</small><h2>已对账组成</h2></header><dl className="result-dense-dl"><dt>佣金</dt><dd>¥ {money(costs.commission)}</dd><dt>印花税</dt><dd>¥ {money(costs.stampDuty)}</dd><dt>过户费</dt><dd>¥ {money(costs.transferFee)}</dd><dt>交易所费用</dt><dd>¥ {money(costs.exchangeFee)}</dd></dl><div className="result-warning"><b>反事实无成本重跑</b><span>不可用 · NOT_AVAILABLE</span><code>COUNTERFACTUAL_NO_COST_RERUN_NOT_AVAILABLE</code><p>不存在成本前收益字段；不会将费用加回净值 · NAV。</p></div></section><section><header><small>换手率策略</small><h2>确定性分母</h2></header><dl className="result-dense-dl"><dt>总成交名义金额</dt><dd>¥ {money(costs.grossTradedNotional)}</dd><dt>平均每日净值 · NAV</dt><dd>¥ {money(turnover.averageDailyNav)}</dd><dt>换手率</dt><dd>{percent(turnover.turnover, 3)}</dd></dl><code className="result-policy-code">{analytics.policy.turnoverConvention}</code></section></div>;
}

function BenchmarkPanel({ analytics }: { analytics: ResultAnalyticsView }) {
  const benchmark = analytics.benchmark;
  return <div className="result-benchmark"><header><div><small>可选精确基准</small><h2>{benchmark.name ?? "基准不可用"}</h2></div><span className={benchmark.status === "AVAILABLE" ? "result-available" : "result-unavailable"}>{availabilityLabel(benchmark.status)}</span></header>{benchmark.status === "BENCHMARK_NOT_AVAILABLE" ? <div className="result-empty-detail"><b>基准不可用 · BENCHMARK_NOT_AVAILABLE</b><p>没有替换默认指数；相对表现序列已省略。</p><code>{benchmark.trackingDifference.reason}</code></div> : <><div className="result-benchmark-kpis"><span><small>基准收益率</small><b>{percent(benchmark.totalReturn)}</b></span><span><small>跟踪差异</small><b>{percent(benchmark.trackingDifference)}</b></span><span><small>跟踪误差</small><b>{percent(benchmark.trackingError)}</b></span><span><small>阿尔法 / 贝塔</small><b>{number(benchmark.alpha)}</b></span></div><div className="result-table-head benchmark"><span>交易日</span><span>相对净值 · NAV</span><span>单日超额收益</span></div>{benchmark.relativeReturns.map((row) => <div className="result-table-row benchmark" key={row.sessionDate}><b>{row.sessionDate}</b><span>{number(row.relativeNav, 6)}</span><span>{percent(row.sessionExcessReturn, 4)}</span></div>)}<footer><code>{benchmark.seriesId}</code><code>{benchmark.contentSha256}</code><p>不下载标的，也不替换默认指数；日期严格对齐。</p></footer></>}</div>;
}

function PolicyIdentity({ analytics: a }: { analytics: ResultAnalyticsView }) {
  return <div className="result-identity-grid"><section><header><small>精确绑定</small><h2>结果 → 策略 → 基准 → 分析</h2></header><dl className="result-identity-list"><dt>来源结果 ID</dt><dd><code>{a.sourceResult.resultId}</code></dd><dt>来源内容 SHA-256</dt><dd><code>{a.sourceResult.contentSha256}</code></dd><dt>策略 ID</dt><dd><code>{a.policy.policyId}</code></dd><dt>策略内容 SHA-256</dt><dd><code>{a.policy.contentSha256}</code></dd><dt>基准 ID</dt><dd><code>{a.benchmark.seriesId ?? "BENCHMARK_NOT_AVAILABLE"}</code></dd><dt>基准内容 SHA-256</dt><dd><code>{a.benchmark.contentSha256 ?? "BENCHMARK_NOT_AVAILABLE"}</code></dd><dt>分析 ID</dt><dd><code>{a.analyticsId}</code></dd><dt>分析内容 SHA-256</dt><dd><code>{a.contentSha256}</code></dd></dl></section><section><header><small>分析策略</small><h2>{a.policy.profileName}</h2></header><dl className="result-dense-dl"><dt>年化交易日数</dt><dd>{a.policy.annualizationSessions}</dd><dt>波动率 ddof</dt><dd>{a.policy.volatilityDdoF}</dd><dt>无风险策略</dt><dd>{a.policy.riskFreePolicy}</dd><dt>索提诺目标</dt><dd>{a.policy.sortinoTarget}</dd><dt>数值精度</dt><dd>{a.policy.numericPrecision} 位小数</dd><dt>舍入</dt><dd>{a.policy.numericRounding}</dd><dt>真值状态</dt><dd>{a.truthAdmission.canonicalTruthState}</dd><dt>准入状态</dt><dd>{a.truthAdmission.canonicalAdmissionState}</dd><dt>开发数据边界</dt><dd>{a.fixtureBoundary}</dd></dl></section></div>;
}

function defaultSurfaceState(): ResultAnalyticsSurfaceState {
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).get("resultAnalyticsFixture") === "development" ? RESULT_ANALYTICS_DEVELOPMENT_STATE : RESULT_ANALYTICS_PRODUCTION_DEFAULT;
}

export function ResultPanelView({ surfaceState }: { surfaceState: ResultAnalyticsSurfaceState }) {
  const [tab, setTab] = useState<ResultTab>("Overview");
  const state = surfaceState;
  if (state.analytics === null) return <section className="panel-page result-workspace result-analytics-lab result-empty" data-testid="result-surface" data-primary-panel="result-review" data-major-panel data-result-boundary={state.boundary}><header className="analysis-header result-analytics-header"><div className="analysis-title"><small>回测结果分析 / V0</small><h1>确定性结果实验室</h1><p><span className="result-source-boundary">{state.boundary}</span></p></div></header><div className="result-empty-state"><small>结果权威边界</small><h2>{reasonLabel(state.reason)}</h2><p>此生产入口尚未接入规范 BacktestResultAnalytics 来源。绝不静默替换开发数据。</p></div></section>;
  const a = state.analytics;
  return <section className="panel-page result-workspace result-analytics-lab" data-testid="result-surface" data-primary-panel="result-review" data-major-panel data-result-id={a.sourceResult.resultId} data-result-analytics-id={a.analyticsId} data-policy-id={a.policy.policyId} data-benchmark-id={a.benchmark.seriesId}>
    <header className="analysis-header result-analytics-header"><div className="analysis-title"><small>回测结果分析 / V0</small><h1>确定性结果实验室</h1><p><span className="result-source-boundary">开发集成数据 · DEVELOPMENT_INTEGRATION_FIXTURE</span><span className="result-boundary">{a.truthAdmission.canonicalTruthState} · {a.truthAdmission.canonicalAdmissionState}</span><span>精确结果 / 策略 / 可选基准绑定</span></p></div><div className="result-hero-metric"><small>总收益率</small><b>{percent(a.metrics.totalReturn)}</b><span>跟踪差异 {percent(a.benchmark.trackingDifference)}</span></div><div className="analysis-actions"><button onClick={() => setTab("Policy & Identity")}>策略 / 标识</button></div></header>
    <div className="analysis-contextline"><code>{a.sourceResult.resultId}</code><span>{a.policy.profileName} · {a.policy.annualizationSessions} 个交易日</span><span>{a.policy.riskFreePolicy}</span><span>{a.benchmark.name}</span></div>
    <div className="mini-tabs" role="tablist" aria-label="结果分析专业视图">{tabs.map((item) => <button role="tab" aria-selected={tab === item} data-result-tab={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item}>{resultTabLabel(item)}</button>)}</div>
    <div className="result-primary result-analytics-primary primary-canvas" data-primary-canvas>{tab === "Overview" ? <Overview analytics={a}/> : tab === "Period Returns" ? <PeriodReturns analytics={a}/> : tab === "Trading & Cost" ? <TradingCost analytics={a}/> : tab === "Benchmark" ? <BenchmarkPanel analytics={a}/> : <PolicyIdentity analytics={a}/>}</div>
  </section>;
}

export function ResultPanel() {
  return <ResultPanelView surfaceState={defaultSurfaceState()}/>;
}

function resultTabLabel(value: string): string {
  return ({ Overview: "概览", "Period Returns": "区间收益", "Trading & Cost": "交易与成本", Benchmark: "基准", "Policy & Identity": "策略与标识" } as Record<string, string>)[value] ?? value;
}

function availabilityLabel(value: string): string {
  return ({ AVAILABLE: "可用 · AVAILABLE", NOT_AVAILABLE: "不可用 · NOT_AVAILABLE", BENCHMARK_NOT_AVAILABLE: "基准不可用 · BENCHMARK_NOT_AVAILABLE" } as Record<string, string>)[value] ?? value;
}

function recoveryLabel(value: string): string {
  return ({ RECOVERED: "已恢复 · RECOVERED", UNRECOVERED: "未恢复 · UNRECOVERED" } as Record<string, string>)[value] ?? value;
}

function reasonLabel(value: string): string {
  return value === "RESULT_ANALYTICS_NOT_CONNECTED" ? "结果分析尚未接入 · RESULT_ANALYTICS_NOT_CONNECTED" : value;
}
