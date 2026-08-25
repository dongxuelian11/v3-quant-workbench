import React, { useMemo, useState } from "react";
import type { ProductResultMetricView } from "../../../../../packages/contracts/src/index";
import { useProductRuntime } from "../productRuntimeStore";

function metricText(metric: ProductResultMetricView): string {
  return metric.status === "AVAILABLE" ? metric.value ?? "NOT_AVAILABLE" : `${metric.status} · ${metric.reason}`;
}

function SeriesChart({ values, label }: { values: readonly Readonly<{ sessionDate: string; value: string | null }>[]; label: string }) {
  const points = useMemo(() => {
    const available = values.map((row) => row.value === null ? null : Number(row.value));
    const finite = available.filter((value): value is number => value !== null && Number.isFinite(value));
    if (finite.length < 2) return "";
    const minimum = Math.min(...finite);
    const maximum = Math.max(...finite);
    const span = maximum === minimum ? 1 : maximum - minimum;
    return available.map((value, index) => {
      const x = available.length === 1 ? 0 : index * 100 / (available.length - 1);
      const y = value === null ? 50 : 96 - (value - minimum) * 88 / span;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(" ");
  }, [values]);
  return <figure className="product-result-chart" aria-label={label}>
    <figcaption>{label}</figcaption>
    {points.length === 0 ? <p>NOT_AVAILABLE · 样本不足</p> : <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img"><title>{label}时间序列，共 {values.length} 个观测</title><polyline points={points} /></svg>}
    <div><span>{values[0]?.sessionDate ?? "—"}</span><span>{values.at(-1)?.sessionDate ?? "—"}</span></div>
  </figure>;
}

export function ProductResultsWorkspace() {
  const home = useProductRuntime((state) => state.dataHome);
  const details = useProductRuntime((state) => state.latestProductResult);
  const readbackError = useProductRuntime((state) => state.latestProductResultError);
  const load = useProductRuntime((state) => state.loadLatestProductResult);
  const [exportState, setExportState] = useState<string | null>(null);
  const exportArtifact = async (artifactId: string, suggestedName: string) => {
    setExportState("正在选择导出位置…");
    try {
      const outcome = await window.v3ProductRuntime.exportArtifact({ artifactId, suggestedName });
      setExportState(outcome.state === "NOT_RUN" ? "NOT_RUN · 用户取消" : `${outcome.state} · ${outcome.byteSize} 字节 · ${outcome.sha256}`);
    } catch (error) {
      setExportState(error instanceof Error ? error.message : String(error));
    }
  };

  if (home?.backtestState !== "AVAILABLE" || home.backtest === null) {
    return <main className="product-c3-workspace" data-product-page="results">
      <header className="product-c3-heading"><div><small>VALID RESULT ONLY</small><h1>结果</h1><p>当前项目没有可打开的 VALID Result。PENDING/INVALID 不会混入结果页。</p></div></header>
      <section className="product-result-empty"><strong>NOT_AVAILABLE</strong><span>{home?.backtestUnavailableReason ?? "NO_VALID_BACKTEST"}</span></section>
    </main>;
  }
  if (details === null) {
    return <main className="product-c3-workspace" data-product-page="results">
      <header className="product-c3-heading"><div><small>VALID RESULT · ARTIFACT READBACK</small><h1>结果</h1><p>Home 已指向 VALID Result，但图表与表格 Artifact 尚未完成严格重建。</p></div></header>
      <section className="product-result-empty"><strong>DEGRADED</strong><span>{readbackError ?? "RESULT_ARTIFACT_READBACK_REQUIRED"}</span><button type="button" onClick={() => { void load(); }}>重新读取 canonical artifacts</button></section>
    </main>;
  }

  const metricEntries: readonly [string, ProductResultMetricView][] = [
    ["总收益", details.metrics.totalReturn], ["年化收益", details.metrics.annualizedReturn],
    ["年化波动", details.metrics.annualizedVolatility], ["最大回撤", details.metrics.maxDrawdown],
    ["Sharpe", details.metrics.sharpe], ["Sortino", details.metrics.sortino], ["Calmar", details.metrics.calmar],
    ["换手率", details.costSummary.turnover], ["峰值单一持仓", details.concentration.peakSinglePositionWeight],
    ["平均持仓数", details.concentration.averageHeldInstrumentCount]
  ];
  return <main className="product-c3-workspace" data-product-page="results">
    <header className="product-c3-heading">
      <div><small>VALID · PRODUCT_CONNECTED</small><h1>结果</h1><p>{details.engineVersion} · {details.truth} / {details.admission}</p></div>
      <div className="product-c3-badges"><span>VALID</span><span>{details.assumptionMode}</span><span>RESEARCH_ONLY</span></div>
    </header>
    <section className="product-result-metrics" aria-label="回测指标">
      {metricEntries.map(([label, metric]) => <div key={label}><span>{label}</span><strong>{metricText(metric)}</strong></div>)}
      <div><span>总费用</span><strong>{details.costSummary.totalFees}</strong></div>
      <div><span>总成交额</span><strong>{details.costSummary.grossTradedNotional}</strong></div>
      <div><span>基准 · Benchmark</span><strong>{details.benchmarkStatus}</strong></div>
    </section>
    <section className="product-result-charts">
      <SeriesChart label="净值" values={details.navSeries.map((row) => ({ sessionDate: row.sessionDate, value: row.nav }))} />
      <SeriesChart label="回撤" values={details.drawdownSeries.map((row) => ({ sessionDate: row.sessionDate, value: row.drawdown.value }))} />
      <SeriesChart label="总敞口" values={details.exposureSeries.map((row) => ({ sessionDate: row.sessionDate, value: row.grossExposure.value }))} />
    </section>
    <section className="product-result-tables">
      <details open><summary>订单 · {details.orders.rowCount}{details.orders.truncated ? `（前 ${details.orders.preview.length} 行）` : ""}</summary><div className="product-result-table-scroll"><table><thead><tr><th>日期</th><th>标的</th><th>方向</th><th>请求数量</th><th>原始限价</th><th>Order ID</th></tr></thead><tbody>{details.orders.preview.map((row) => <tr key={row.orderId}><td>{row.sessionDate}</td><td>{row.instrumentId}</td><td>{row.side}</td><td>{row.requestedQuantity}</td><td>{row.rawLimitPrice}</td><td>{row.orderId}</td></tr>)}</tbody></table></div></details>
      <details open><summary>成交 · {details.fills.rowCount}{details.fills.truncated ? `（前 ${details.fills.preview.length} 行）` : ""}</summary><div className="product-result-table-scroll"><table><thead><tr><th>日期</th><th>标的</th><th>方向</th><th>数量</th><th>执行价</th><th>费用</th></tr></thead><tbody>{details.fills.preview.map((row) => <tr key={row.fillId}><td>{row.sessionDate}</td><td>{row.instrumentId}</td><td>{row.side}</td><td>{row.quantity}</td><td>{row.executionPrice ?? row.rawPrice}</td><td>{row.totalFees}</td></tr>)}</tbody></table></div></details>
      <details><summary>费用 · {details.fills.rowCount}{details.fills.truncated ? `（前 ${details.fills.preview.length} 行）` : ""}</summary><div className="product-result-table-scroll"><table><thead><tr><th>Fill ID</th><th>佣金</th><th>印花税</th><th>过户费</th><th>交易费</th><th>合计</th></tr></thead><tbody>{details.fills.preview.map((row) => <tr key={`cost:${row.fillId}`}><td>{row.fillId}</td><td>{row.commission}</td><td>{row.stampDuty}</td><td>{row.transferFee}</td><td>{row.exchangeFee}</td><td>{row.totalFees}</td></tr>)}</tbody></table></div></details>
      <details><summary>持仓快照 · {details.holdings.rowCount}</summary><div className="product-result-table-scroll"><table><thead><tr><th>日期</th><th>标的</th><th>持仓</th><th>可卖</th><th>市值</th></tr></thead><tbody>{details.holdings.preview.map((row) => <tr key={`${row.sessionDate}:${row.instrumentId}`}><td>{row.sessionDate}</td><td>{row.instrumentId}</td><td>{row.quantity}</td><td>{row.sellableQuantity}</td><td>{row.marketValue}</td></tr>)}</tbody></table></div></details>
      <details><summary>执行诊断 · {details.diagnostics.rowCount}</summary><div className="product-result-table-scroll"><table><thead><tr><th>代码</th><th>请求 / 可用 / 成交 / 未成交</th><th>说明</th></tr></thead><tbody>{details.diagnostics.preview.map((row, index) => <tr key={`${row.orderId}:${row.code}:${index}`}><td>{row.code}</td><td>{row.requestedQuantity} / {row.eligibleQuantity ?? "—"} / {row.filledQuantity} / {row.unfilledQuantity ?? "—"}</td><td>{row.detail}</td></tr>)}</tbody></table></div></details>
      <details><summary>月度 / 年度收益 · {details.periodReturns.monthly.length + details.periodReturns.yearly.length}</summary><div className="product-result-table-scroll"><table><thead><tr><th>周期</th><th>起始</th><th>结束</th><th>收益</th></tr></thead><tbody>{[...details.periodReturns.monthly, ...details.periodReturns.yearly].map((row) => <tr key={`${row.periodLabel}:${row.startDate}`}><td>{row.periodLabel}</td><td>{row.startDate}</td><td>{row.endDate}</td><td>{metricText(row.periodReturn)}</td></tr>)}</tbody></table></div></details>
    </section>
    <section className="product-result-lineage"><h2>结果谱系 · Lineage</h2><dl>{Object.entries(details.lineage).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl></section>
    <section className="product-result-export" aria-label="结果导出"><button type="button" onClick={() => { void exportArtifact(details.exports.summaryJsonArtifactId, "v3-result-summary.json"); }}>导出摘要 JSON</button><button type="button" onClick={() => { void exportArtifact(details.exports.ordersCsvArtifactId, "v3-orders.csv"); }}>导出订单 CSV</button><button type="button" onClick={() => { void exportArtifact(details.exports.fillsCsvArtifactId, "v3-fills.csv"); }}>导出成交 CSV</button><button type="button" onClick={() => { void exportArtifact(details.exports.analyticsJsonArtifactId, "v3-analytics.json"); }}>导出分析 JSON</button>{exportState !== null && <span aria-live="polite">{exportState}</span>}</section>
  </main>;
}
