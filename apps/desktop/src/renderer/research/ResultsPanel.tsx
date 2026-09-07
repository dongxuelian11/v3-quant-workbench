import React, { useEffect, useMemo, useState } from "react";
import type { ExperimentDetails, JsonObject, ResearchTable } from "../../../../../packages/contracts/src/research";
import { errorText, request, useResearch } from "./state";
import { DataTable, Empty, Heading, Plot, valueText, fieldLabel, tableLabel, tradeDirection } from "./ui";
import { PriceChart, type TradeMarker } from "./PriceChart";
import { PagedExperimentTable, type TablePage } from "./PagedTable";

import { object } from "./configuration";

const escapeHtml = (s: string) => s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
function tradeFromRow(row: JsonObject): TradeMarker | null {
  const date = row.date ?? row.trade_date, price = row.price ?? row.execution_price ?? row.trade_price, side = tradeDirection(row.side ?? row.direction);
  if (typeof date !== "string" || typeof price !== "number" || !Number.isFinite(price) || typeof side !== "string") return null;
  return { date, price, ...(typeof row.adjustedPrice === "number" && Number.isFinite(row.adjustedPrice) ? { adjustedPrice: row.adjustedPrice } : {}), side };
}
function artifactTableName(detail: ExperimentDetails, name: string) {
  return detail.experiment.artifacts.find(a => a.name === name || a.name.replace(/\.[^.]+$/, "") === name)?.name ?? name;
}
export function ResultsPanel() {
  const s = useResearch(); const id = s.selectedExperiment || s.experiments[0]?.id || "";
  const [detail, setDetail] = useState<ExperimentDetails | null>(null); const [loading, setLoading] = useState(false);
  const [comparison, setComparison] = useState<ExperimentDetails[]>([]); const [selected, setSelected] = useState<string[]>([]);
  const [tab, setTab] = useState("overall"); const [name, setName] = useState("");
  const [replay, setReplay] = useState<{ symbol: string; date?: string; trade?: TradeMarker } | null>(null);
  useEffect(() => { let active = true; setDetail(null); setReplay(null); if (!id) return; setLoading(true); void s.act(async () => { const d = await request<ExperimentDetails>("experiments.get", { projectId: s.project!.id, experimentId: id }); if (active) { setDetail(d); setName(d.experiment.name); } }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [id, s.project!.id, s.revision]);
  const exportResult = (format: "csv" | "xlsx" | "pdf") => void s.act(async () => {
    if (!detail) return;
    if (format !== "pdf") {
      const result = await request<{ path: string }>("exports.create", { projectId: s.project!.id, experimentId: id, format });
      const path = await window.v3Research!.exportFile({ format, sourcePath: result.path, suggestedName: `${detail.experiment.name}.${format}` });
      if (path) s.setNotice(`已导出：${path}`);
    } else {
      const tableHtml = detail.tables.map(t => `<h2>${escapeHtml(t.name)}</h2><table><thead><tr>${t.columns.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead><tbody>${t.rows.map(r => `<tr>${t.columns.map(c => `<td>${escapeHtml(valueText(r[c]))}</td>`).join("")}</tr>`).join("")}</tbody></table>`).join("");
      const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>body{font:13px "Microsoft YaHei",sans-serif;color:#263536;padding:32px}table{border-collapse:collapse;font-size:10px;width:100%}td,th{border-bottom:1px solid #ddd;padding:5px;text-align:left}pre{white-space:pre-wrap}h1{color:#267774}</style><h1>${escapeHtml(detail.experiment.name)}</h1><p>${escapeHtml(s.project!.name)} · ${escapeHtml(detail.experiment.createdAt)}</p><p>${escapeHtml(detail.experiment.summary)}</p><h2>指标</h2><pre>${escapeHtml(JSON.stringify(detail.experiment.metrics, null, 2))}</pre><h2>参数</h2><pre>${escapeHtml(JSON.stringify(detail.experiment.parameters, null, 2))}</pre>${tableHtml}<p>研究报告 · 表格为返回的预览行，完整数据请导出 CSV / Excel。</p></html>`;
      const path = await window.v3Research!.exportFile({ format, html, suggestedName: `${detail.experiment.name}.pdf` }); if (path) s.setNotice(`已导出：${path}`);
    }
  });
  const onRow = (row: JsonObject) => { const symbol = row.symbol ?? row.instrument ?? row.code; const date = row.date ?? row.trade_date; const trade = tradeFromRow(row); if (typeof symbol === "string") setReplay({ symbol, date: typeof date === "string" ? date : undefined, ...(trade ? { trade } : {}) }); };
  const tradeMarkers = detail?.tables.filter(t => /trade|交易/i.test(t.name)).flatMap(t => t.rows.filter(r => (r.symbol ?? r.instrument ?? r.code) === replay?.symbol).flatMap(r => { const trade = tradeFromRow(r); return trade ? [trade] : []; })) ?? [];
  return <div className="r-page"><Heading title="实验与结果" description="整体表现、横向比较，以及交易与持仓回放。结果仅来自已保存的实验。" /><div className="r-results-layout"><aside className="r-runs">{s.experiments.map(e => <div key={e.id} className={id === e.id ? "active" : ""}><input type="checkbox" aria-label={`比较 ${e.name}`} checked={selected.includes(e.id)} onChange={() => setSelected(ids => ids.includes(e.id) ? ids.filter(x => x !== e.id) : [...ids, e.id])} /><button onClick={() => { s.setSelectedExperiment(e.id); setTab("overall"); }}><strong>{e.starred ? "★ " : ""}{e.name}</strong><small>{new Date(e.createdAt).toLocaleDateString("zh-CN")}</small></button></div>)}<button disabled={selected.length < 2} onClick={() => void s.act(async () => { setComparison(await request<ExperimentDetails[]>("experiments.compare", { projectId: s.project!.id, experimentIds: selected })); setTab("compare"); })}>比较已选（{selected.length}）</button></aside><section className="r-result-content">{loading ? <Empty title="正在读取实验…" /> : !detail ? <Empty title="还没有实验结果">运行因子分析、回测或模型训练后，在这里查看真实结果。</Empty> : <><div className="r-toolbar"><input aria-label="实验名称" value={name} onChange={e => setName(e.target.value)} /><button disabled={!name.trim()} onClick={() => void s.act(async () => { await request("experiments.update", { projectId: s.project!.id, experimentId: id, name: name.trim() }); await s.refresh(); })}>重命名</button><button onClick={() => void s.act(async () => { await request("experiments.update", { projectId: s.project!.id, experimentId: id, starred: !detail.experiment.starred }); await s.refresh(); })}>{detail.experiment.starred ? "取消收藏" : "收藏"}</button><button className="r-danger" onClick={() => { if (window.confirm(`删除实验“${detail.experiment.name}”？`)) void s.act(async () => { await request("experiments.delete", { projectId: s.project!.id, experimentId: id }); s.setSelectedExperiment(""); setComparison([]); setSelected(ids => ids.filter(x => x !== id)); await s.refresh(); }); }}>删除</button></div><nav className="r-subtabs" aria-label="结果视图">{[["overall", "整体表现"], ["tables", "交易与持仓"], ["compare", "实验比较"], ["parameters", "参数与输出"]].map(([key, label]) => <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>)}</nav><p>{detail.experiment.summary}</p><UnavailableFactors details={detail.details} />
      {tab === "overall" && (detail.experiment.kind === "factor.analyze" ? <FactorResults key={detail.experiment.id} detail={detail} /> : <><Metrics metrics={detail.experiment.metrics} /><SeriesPlot details={[detail]} /><ExtendedResults detail={detail} />{detail.tables.filter(t => /ic|quantile|group|correlation|turnover/i.test(t.name)).map(t => <AnalysisTable key={t.name} table={t} />)}</>)}
      {tab === "tables" && <>{detail.tables.length ? detail.tables.map(t => <PagedExperimentTable key={`${id}-${t.name}`} experimentId={id} table={artifactTableName(detail, t.name)} onRow={onRow} />) : <Empty title="这个实验没有返回表格" />}{replay && <PriceChart symbol={replay.symbol} focusDate={replay.date} trades={tradeMarkers} experimentId={id} tradeTable={detail.tables.find(t => /trade|交易/i.test(t.name)) ? artifactTableName(detail, detail.tables.find(t => /trade|交易/i.test(t.name))!.name) : undefined} />}</>}
      {tab === "compare" && (comparison.length ? <><DataTable table={{ name: "实验指标比较", columns: ["实验", ...new Set(comparison.flatMap(d => Object.keys(d.experiment.metrics)))], rows: comparison.map(d => ({ 实验: d.experiment.name, ...d.experiment.metrics })) }} /><SeriesPlot details={comparison} /><p className="r-note">请核对数据日期、股票池和参数差异后解释比较结果。</p></> : <Empty title="选择两个或更多实验进行比较" />)}
      {tab === "parameters" && <><ApplyBest detail={detail} /><h3>输入参数</h3><pre>{JSON.stringify(detail.experiment.parameters, null, 2)}</pre><h3>详细信息</h3><pre>{JSON.stringify(detail.details, null, 2)}</pre><DataTable table={{ name: "输出文件", columns: ["name", "type", "path"], rows: detail.experiment.artifacts.map(a => ({ ...a })) }} /><button onClick={() => void s.act(() => s.submit(detail.experiment.kind, detail.experiment.parameters, `${detail.experiment.name} · 重跑`))}>使用这些参数重跑</button></>}
      <div className="r-toolbar"><button onClick={() => exportResult("csv")}>导出 CSV</button><button onClick={() => exportResult("xlsx")}>导出 Excel</button><button onClick={() => exportResult("pdf")}>导出 PDF 报告</button></div></>}</section></div></div>;
}
function FactorResults({ detail }: { detail: ExperimentDetails }) {
  const s = useResearch();
  const [selected, setSelected] = useState("");
  const [loaded, setLoaded] = useState<{ selection: string; tables: ResearchTable[] } | null>(null);
  const [failure, setFailure] = useState("");
  const names = new Map(s.factors.map(f => [f.id, f.name]));
  const custom = detail.experiment.parameters.customFactors;
  if (Array.isArray(custom)) for (const f of custom) {
    if (f && typeof f === "object" && !Array.isArray(f) && typeof f.id === "string" && typeof f.name === "string") names.set(f.id, f.name);
  }
  const factors = Array.isArray(detail.details.factors) ? detail.details.factors.flatMap(f =>
    f && typeof f === "object" && !Array.isArray(f) && typeof f.factor === "string"
      ? [{ id: f.factor, samples: typeof f.samples === "number" ? f.samples : null }] : []) : [];
  const periods = [...new Set(factors.flatMap(f => Object.keys(detail.experiment.metrics).filter(k => k.startsWith(`${f.id}:`)).map(k => k.slice(f.id.length + 1))))];
  const summary: ResearchTable = {
    name: "批量因子汇总", columns: ["因子", "样本数", ...periods],
    rows: factors.map(f => ({ factorId: f.id, 因子: names.get(f.id) ?? f.id, 样本数: f.samples,
      ...Object.fromEntries(periods.map(p => [p, detail.experiment.metrics[`${f.id}:${p}`] ?? null])) }))
  };
  useEffect(() => {
    let active = true;
    setLoaded(null); setFailure("");
    const tableNames = selected ? detail.experiment.artifacts.filter(a => a.name.startsWith(`${selected}_`)).map(a => a.name) : ["factor_correlation"];
    async function loadTable(name: string): Promise<ResearchTable | null> {
      const artifact = detail.experiment.artifacts.find(a => a.name === name);
      if (!artifact) throw new Error(`缺少分析表：${name}`);
      let offset = 0;
      const rows: JsonObject[] = [];
      let columns: string[] = [];
      while (active) {
        const page = await request<TablePage>("experiments.table", { projectId: detail.experiment.projectId, experimentId: detail.experiment.id, table: artifact.name, offset, limit: 500 });
        if (!active) return null;
        columns = page.columns;
        rows.push(...page.rows); offset += page.rows.length;
        if (offset >= page.total) return { name, columns, rows };
        if (!page.rows.length) throw new Error(`分析表 ${name} 未返回剩余记录。`);
      }
      return null;
    }
    void Promise.all(tableNames.map(loadTable)).then(tables => {
      if (active) setLoaded({ selection: selected, tables: tables.filter((t): t is ResearchTable => t !== null) });
    }).catch(e => { if (active) setFailure(errorText(e)); });
    return () => { active = false; };
  }, [detail, selected]);
  const select = (id: string) => { setLoaded(null); setFailure(""); setSelected(id); };
  return <section><div className="r-toolbar"><label htmlFor={`factor-result-${detail.experiment.id}`}>查看因子</label><select id={`factor-result-${detail.experiment.id}`} value={selected} onChange={e => select(e.target.value)}><option value="">汇总 · 全部因子</option>{factors.map(f => <option key={f.id} value={f.id}>{names.get(f.id) ?? f.id}</option>)}</select></div>
    {!selected && <DataTable table={summary} onRow={row => { if (typeof row.factorId === "string") select(row.factorId); }} />}
    {failure ? <p role="alert" className="r-note">{failure}</p> : !loaded || loaded.selection !== selected ? <p role="status">正在读取完整分析表…</p> : loaded.tables.map(table => selected
      ? <SingleFactorTable key={table.name} table={table} factorName={names.get(selected) ?? selected} />
      : <AnalysisTable key={table.name} table={table} />)}
  </section>;
}
function SingleFactorTable({ table, factorName }: { table: ResearchTable; factorName: string }) {
  const grouped = table.name.endsWith("_quantile_returns");
  const suffix = table.name.toLowerCase();
  const title = `${factorName} · ${grouped ? "分组收益" : /rank.*ic/.test(suffix) ? "Rank IC" : /icir/.test(suffix) ? "ICIR" : /decay/.test(suffix) ? "因子衰减" : /stability/.test(suffix) ? "分期稳定性" : /cumulative/.test(suffix) ? "累计分组表现" : /turnover/.test(suffix) ? "换手率" : suffix.endsWith("_ic") ? "Pearson IC" : table.name}`;
  const axis = grouped ? "factor_quantile" : table.columns.find(c => /date|datetime|time/i.test(c)) ?? table.columns[0];
  const numeric = table.columns.filter(c => c !== axis && table.rows.some(row => typeof row[c] === "number"));
  return <section><p className="r-note">{title} · 完整分析表 {table.rows.length} 行</p>{table.rows.length > 0 && numeric.length > 0 && <Plot title={title} option={{ tooltip: { trigger: "axis" }, legend: { type: "scroll" }, grid: { left: 64, right: 24, top: 45, bottom: 65 }, xAxis: { type: "category", data: table.rows.map(row => valueText(row[axis], axis)) }, yAxis: { type: "value", scale: true }, dataZoom: grouped ? [] : [{ type: "inside" }, { type: "slider", height: 18 }], series: numeric.map(column => ({ name: column, type: grouped ? "bar" : "line", showSymbol: false, connectNulls: false, data: table.rows.map(row => typeof row[column] === "number" ? row[column] : null) })) }} />}<DataTable table={{ ...table, name: title }} /></section>;
}
function UnavailableFactors({ details }: { details: JsonObject }) {
  const entries = details.unavailableFactors;
  if (!Array.isArray(entries) || !entries.length) return null;
  return <details><summary>有 {entries.length} 个因子未能分析，其他结果可继续查看</summary>{entries.map((entry, index) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return null;
    return <p className="r-note" key={index}><strong>{valueText(entry.factor)}</strong>：{valueText(entry.reason)}</p>;
  })}</details>;
}
function Metrics({ metrics }: { metrics: Record<string, number | null> }) { return <div className="r-metrics">{Object.entries(metrics).map(([key, value]) => <div key={key}><span>{fieldLabel(key)}</span><strong>{value == null ? "—" : Number.isFinite(value) ? value.toLocaleString("zh-CN", { maximumFractionDigits: 5 }) : "不可用"}</strong></div>)}</div>; }
function SeriesPlot({ details }: { details: ExperimentDetails[] }) {
  const s = useResearch();
  const series = details.flatMap(d => d.series.map(ser => ({ name: details.length > 1 ? `${d.experiment.name} · ${ser.name}` : ser.name, type: "line" as const, showSymbol: false, connectNulls: false, data: ser.points.map(p => [p.date, p.value]) })));
  if (!series.length) return <Empty title="没有可绘制的时间序列">可继续查看表格和参数。</Empty>;
  return <Plot title="结果走势" option={{ tooltip: { trigger: "axis" }, legend: { type: "scroll" }, grid: { left: 64, right: 24, top: 45, bottom: 60 }, xAxis: { type: "time" }, yAxis: { type: "value", scale: true }, dataZoom: [{ type: "inside" }, { type: "slider", height: 18 }], series }} onImage={url => void s.act(async () => { const path = await window.v3Research!.exportFile({ format: "png", dataUrl: url, suggestedName: "研究结果.png" }); if (path) s.setNotice(`已导出：${path}`); })} />;
}
function AnalysisTable({ table }: { table: ResearchTable }) {
  const numeric = useMemo(() => table.columns.filter(c => table.rows.some(r => typeof r[c] === "number")), [table]);
  const label = table.columns.find(c => !numeric.includes(c)) ?? table.columns[0];
  if (/correlation/i.test(table.name) && numeric.length && table.rows.length) return <><DataTable table={table} /><Plot title="因子相关性" option={{ tooltip: { position: "top" }, grid: { top: 20, left: 90, right: 30, bottom: 90 }, xAxis: { type: "category", data: numeric }, yAxis: { type: "category", data: table.rows.map(r => valueText(r[label])) }, visualMap: { min: -1, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#b97468", "#f8f7ef", "#287775"] } }, series: [{ type: "heatmap", data: table.rows.flatMap((r, y) => numeric.flatMap((c, x) => typeof r[c] === "number" ? [[x, y, r[c]]] : [])), label: { show: true } }] }} /></>;
  return <><DataTable table={table} />{numeric.length > 0 && table.rows.length > 0 && <Plot title={tableLabel(table.name)} option={{ tooltip: { trigger: "axis" }, legend: { type: "scroll" }, grid: { left: 64, right: 24, top: 45, bottom: 50 }, xAxis: { type: "category", data: table.rows.map(r => valueText(r[label])) }, yAxis: { type: "value" }, series: numeric.map(c => ({ name: fieldLabel(c, table.name), type: /ic|turnover|benchmark|excess|drawdown/i.test(table.name) ? "line" : "bar", data: table.rows.map(r => typeof r[c] === "number" ? r[c] : null) })) }} />}</>;
}

function ApplyBest({ detail }: { detail: ExperimentDetails }) {
  const s = useResearch(); const best = object(detail.details.bestParameters);
  if (detail.experiment.kind !== "optimize.run" || !Object.keys(best).length) return null;
  return <section><h3>寻优选出的参数</h3><pre>{JSON.stringify(best, null, 2)}</pre><button onClick={() => void s.act(async () => {
    const target = detail.experiment.parameters.target === "model" ? "model" : "backtest";
    const config = structuredClone(object(detail.experiment.parameters.baseParameters));
    for (const [path, value] of Object.entries(best)) {
      const keys = path.split(".");
      if (keys.some(k => !k || ["__proto__", "prototype", "constructor"].includes(k))) throw new Error("最佳参数包含不支持的字段。");
      let cursor = config;
      for (const key of keys.slice(0, -1)) { cursor[key] = { ...object(cursor[key]) }; cursor = cursor[key] as JsonObject; }
      cursor[keys[keys.length - 1]] = value;
    }
    await s.save({ settings: { ...s.project!.settings, [target]: config } });
    if (Array.isArray(config.factorIds)) s.setSelectedFactors(config.factorIds.filter((v): v is string => typeof v === "string"));
    s.setPage(target); s.setNotice("最佳参数已应用，请核对独立测试区间后运行。");
  })}>应用最佳参数到配置</button><p className="r-note">应用不会自动运行实验。验证集用于选参，测试集用于独立评价。</p></section>;
}
function ExtendedResults({ detail }: { detail: ExperimentDetails }) {
  const tables = detail.tables.filter(t => /benchmark|excess|drawdown|monthly|industry|risk|contribution|trial|window|constraint|unfilled/i.test(t.name));
  return <><ApplyBest detail={detail} />{detail.details.executable === false && <p role="status">当前组合不可执行：{valueText(detail.details.conflicts)}</p>}{tables.map(table => <CompleteAnalysis key={`${detail.experiment.id}-${table.name}`} detail={detail} name={table.name} />)}</>;
}
function CompleteAnalysis({ detail, name }: { detail: ExperimentDetails; name: string }) {
  const [table, setTable] = useState<ResearchTable | null>(null); const [error, setError] = useState("");
  useEffect(() => { let active = true; setTable(null); setError(""); void (async () => {
    let offset = 0; const rows: JsonObject[] = [];
    while (active) {
      const page = await request<TablePage>("experiments.table", { projectId: detail.experiment.projectId, experimentId: detail.experiment.id, table: artifactTableName(detail, name), offset, limit: 500 });
      if (!active) return;
      rows.push(...page.rows); offset += page.rows.length;
      if (offset >= page.total) { setTable({ name, columns: page.columns, rows }); return; }
      if (!page.rows.length) throw new Error("结果表未返回剩余行。");
    }
  })().catch(e => { if (active) setError(errorText(e)); }); return () => { active = false; }; }, [detail, name]);
  return <section>{error ? <p role="alert">{error}</p> : table ? <AnalysisTable table={table} /> : <p role="status">正在读取 {tableLabel(name)}…</p>}</section>;
}
