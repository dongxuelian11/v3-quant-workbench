import React, { useMemo, useState } from "react";
import type { ProductFactorSummaryView } from "../../../../../packages/contracts/src/index";
import { useProductRuntime } from "../productRuntimeStore";

const GOLDEN_FORMULA = `MJ:=AMOUNT/VOL/100;
MA5:=MA(MJ,5);
MA20:=MA(MJ,20);
MA60:=MA(MJ,60);
GOLDEN_CROSS:CROSS(MA20,MA60) AND MA5>MA20;
DEATH_CROSS:CROSS(MA60,MA20) AND MA5<MA20;`;

type ResearchTab = "values" | "ic" | "quantiles" | "diagnostics" | "lineage";

function numeric(value: number | boolean | null): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function linePath(values: readonly (number | null)[], minimum: number, maximum: number): string {
  const range = maximum - minimum || 1;
  const width = Math.max(1, values.length - 1);
  let open = false;
  return values.map((value, index) => {
    if (value === null) { open = false; return ""; }
    const x = 28 + index / width * 944;
    const y = 316 - (value - minimum) / range * 270;
    const command = open ? "L" : "M";
    open = true;
    return `${command}${x.toFixed(2)},${y.toFixed(2)}`;
  }).filter(Boolean).join(" ");
}

function FactorChart({ factor }: { factor: ProductFactorSummaryView }) {
  const rows = useMemo(() => {
    const first = factor.visualPreview[0]?.instrumentId;
    return factor.visualPreview.filter((row) => row.instrumentId === first).slice(-180);
  }, [factor]);
  const numericValues = rows.flatMap((row) => [
    row.low, row.high, numeric(row.series.MA5 ?? null), numeric(row.series.MA20 ?? null), numeric(row.series.MA60 ?? null)
  ]).filter((value): value is number => value !== null);
  if (rows.length === 0 || numericValues.length === 0) {
    return <div className="factor-chart-empty">UNAVAILABLE · 没有可绘制的 canonical 序列</div>;
  }
  const minimum = Math.min(...numericValues);
  const maximum = Math.max(...numericValues);
  const width = Math.max(1, rows.length - 1);
  const y = (value: number) => 316 - (value - minimum) / (maximum - minimum || 1) * 270;
  return <figure className="factor-chart" aria-label="同一 Snapshot 的价格、均线与信号">
    <svg viewBox="0 0 1000 350" role="img">
      <title>{rows[0]?.instrumentId} 价格、MA5/20/60 与交叉信号</title>
      <g className="chart-grid">{[0, 1, 2, 3, 4].map((index) => <line key={index} x1="28" x2="972" y1={46 + index * 67.5} y2={46 + index * 67.5} />)}</g>
      <g className="chart-candles">{rows.map((row, index) => {
        if (row.open === null || row.high === null || row.low === null || row.close === null) return null;
        const x = 28 + index / width * 944;
        const rise = row.close >= row.open;
        return <g key={`${row.sessionDate}:${row.instrumentId}`} className={rise ? "rise" : "fall"}>
          <line x1={x} x2={x} y1={y(row.high)} y2={y(row.low)} />
          <rect x={x - 2.2} y={Math.min(y(row.open), y(row.close))} width="4.4" height={Math.max(1, Math.abs(y(row.open) - y(row.close)))} />
        </g>;
      })}</g>
      <path className="factor-line ma5" d={linePath(rows.map((row) => numeric(row.series.MA5 ?? null)), minimum, maximum)} />
      <path className="factor-line ma20" d={linePath(rows.map((row) => numeric(row.series.MA20 ?? null)), minimum, maximum)} />
      <path className="factor-line ma60" d={linePath(rows.map((row) => numeric(row.series.MA60 ?? null)), minimum, maximum)} />
      <g className="signal-markers">{rows.map((row, index) => {
        if (row.close === null) return null;
        const x = 28 + index / width * 944;
        if (row.series.GOLDEN_CROSS === true) return <path key={`g:${row.sessionDate}`} className="golden" d={`M${x},${y(row.close) - 13} l-6,-9 h12 z`} />;
        if (row.series.DEATH_CROSS === true) return <path key={`d:${row.sessionDate}`} className="death" d={`M${x},${y(row.close) + 13} l-6,9 h12 z`} />;
        return null;
      })}</g>
    </svg>
    <figcaption>
      <span>{rows[0]?.instrumentId}</span><span>MA5</span><span>MA20</span><span>MA60</span><span>▲ 金叉</span><span>▼ 死叉</span>
    </figcaption>
  </figure>;
}

export function ProductFactorWorkspace() {
  const home = useProductRuntime((state) => state.dataHome);
  const busy = useProductRuntime((state) => state.entryBusy);
  const accepted = useProductRuntime((state) => state.factorStudy);
  const task = useProductRuntime((state) => state.factorTask);
  const submit = useProductRuntime((state) => state.submitFactorStudy);
  const error = useProductRuntime((state) => state.errorMessage);
  const [source, setSource] = useState(GOLDEN_FORMULA);
  const [analysisOutputName, setAnalysisOutputName] = useState("MJ");
  const [tab, setTab] = useState<ResearchTab>("values");
  const factor = home?.factor ?? null;
  const connected = typeof window.v3ProductRuntime?.submitFactorStudy === "function"
    && typeof window.v3ProductRuntime?.getProjectHome === "function";
  const busyState = accepted === null
    ? "LOADING"
    : task === null || task.state === "QUEUED"
      ? "QUEUED"
      : task.state === "SUCCEEDED"
        ? "PERSISTING"
        : task.state === "FAILED" || task.state === "CANCELLED"
          ? "ERROR"
          : "RUNNING";
  const state = !connected
    ? "DISCONNECTED"
    : error !== null
      ? "ERROR"
      : busy
        ? busyState
        : factor !== null
          ? factor.analysis.aggregate.icMean.status === "INSUFFICIENT_SAMPLE"
            ? "INSUFFICIENT_SAMPLE"
            : "SUCCESS"
          : home?.dataState === "AVAILABLE" ? home.factorState : "UNAVAILABLE";
  const aggregate = factor?.analysis.aggregate ?? null;

  return <main className="product-factor-workspace" data-product-page="research">
    <header className="factor-heading">
      <div>
        <small>FACTOR RESEARCH · PRE_ALPHA / NOT_FORMAL</small>
        <h1>研究</h1>
        <p>{home?.data?.displayName ?? "尚无 Snapshot"} · {home?.data?.instrumentCount ?? 0} 个标的 · {factor?.analysisOutputName ?? analysisOutputName}</p>
      </div>
      <span className={`truth-state truth-state-${state.toLowerCase()}`} aria-live="polite">{state}</span>
    </header>

    <section className="factor-authoring" aria-label="TDX 因子定义">
      <label><span>TDX 公式</span><textarea value={source} disabled={busy} onChange={(event) => setSource(event.target.value)} spellCheck={false} /></label>
      <div>
        <label><span>分析输出</span><input value={analysisOutputName} disabled={busy} onChange={(event) => setAnalysisOutputName(event.target.value)} /></label>
        <button type="button" disabled={busy || home?.dataState !== "AVAILABLE" || source.trim().length === 0} onClick={() => void submit({ formulaSource: source, analysisOutputName })}>
          {busy ? "正在计算并持久化…" : "运行因子研究"}
        </button>
        <small>创建 durable Task 后，由 backend 解析、校验、物化和分析。</small>
      </div>
    </section>

    {error !== null && <p className="factor-error" role="alert">{error}</p>}
    {factor === null
      ? <section className="factor-empty"><strong>{home?.factorUnavailableReason ?? "NO_SNAPSHOT"}</strong><p>导入真实 CSV / Parquet 后可运行；这里不会显示 fixture 或硬编码信号。</p></section>
      : <>
        <FactorChart factor={factor} />
        <nav className="factor-tabs" aria-label="因子研究详情">
          {(["values", "ic", "quantiles", "diagnostics", "lineage"] as const).map((name) => <button key={name} aria-current={tab === name ? "page" : undefined} onClick={() => setTab(name)}>{({ values: "因子值", ic: "IC 序列", quantiles: "五分位收益", diagnostics: "诊断", lineage: "血缘" })[name]}</button>)}
        </nav>
        <section className="factor-detail" data-factor-tab={tab}>
          {tab === "values" && <div className="factor-table"><div className="factor-row head"><span>日期</span><span>标的</span><span>MJ</span><span>MA5</span><span>MA20</span><span>MA60</span><span>信号</span></div>{factor.visualPreview.slice(-100).map((row) => <div className="factor-row" key={`${row.sessionDate}:${row.instrumentId}`}><span>{row.sessionDate}</span><span>{row.instrumentId}</span><span>{String(row.series.MJ ?? "—")}</span><span>{String(row.series.MA5 ?? "—")}</span><span>{String(row.series.MA20 ?? "—")}</span><span>{String(row.series.MA60 ?? "—")}</span><span>{row.series.GOLDEN_CROSS === true ? "金叉" : row.series.DEATH_CROSS === true ? "死叉" : "—"}</span></div>)}</div>}
          {tab === "ic" && <div className="analysis-list"><p className="analysis-boundary">{aggregate?.icMean.status} · {aggregate?.icMean.reason ?? "可用"}</p>{factor.analysis.dailyResults.map((row) => <div key={row.sessionDate}><time>{row.sessionDate}</time><span>IC {row.ic.value ?? row.ic.status}</span><span>RankIC {row.rankIc.value ?? row.rankIc.status}</span><span>覆盖率 {(row.coverage * 100).toFixed(1)}%</span></div>)}</div>}
          {tab === "quantiles" && <div className="analysis-list"><p className="analysis-boundary">单标的不会伪造横截面数值。</p>{factor.analysis.dailyResults.map((row) => <div key={row.sessionDate}><time>{row.sessionDate}</time><span>{row.quantileReturns === null ? row.status : row.quantileReturns.map((value) => value.toFixed(4)).join(" / ")}</span><span>Long-short {row.longShortSpread ?? "—"}</span></div>)}</div>}
          {tab === "diagnostics" && <div className="diagnostic-pane"><strong>{aggregate?.icMean.status}</strong><p>{aggregate?.icMean.reason ?? "统计样本满足当前规范"}</p><dl><div><dt>有效日期</dt><dd>{aggregate?.validDates}</dd></div><div><dt>ICIR</dt><dd>{aggregate?.icir.value ?? aggregate?.icir.status}</dd></div><div><dt>RankICIR</dt><dd>{aggregate?.rankIcir.value ?? aggregate?.rankIcir.status}</dd></div>{aggregate?.yearlyDistribution.map((year) => <div key={year.year}><dt>{year.year} 年</dt><dd>{year.validDates} 日 · IC {year.icMean.value ?? year.icMean.status} · ICIR {year.icir.value ?? year.icir.status}</dd></div>)}</dl></div>}
          {tab === "lineage" && <dl className="factor-lineage"><div><dt>Snapshot</dt><dd>{factor.snapshotId}</dd></div><div><dt>Universe</dt><dd>{factor.universeVersionId}</dd></div><div><dt>FormulaDocument</dt><dd>{factor.formulaDocumentVersionId}</dd></div><div><dt>Source manifest</dt><dd>{factor.sourceManifestArtifactId}</dd></div><div><dt>Source SHA-256</dt><dd>{factor.sourceManifestSha256}</dd></div><div><dt>Analysis Artifact</dt><dd>{factor.analysisArtifactId}</dd></div>{factor.outputs.map((output) => <div key={output.name}><dt>{output.name}</dt><dd>{output.factorDefinitionVersionId} · {output.materializationId}</dd></div>)}</dl>}
        </section>
      </>}
  </main>;
}
