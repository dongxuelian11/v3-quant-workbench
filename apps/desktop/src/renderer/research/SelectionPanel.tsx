import React, { useEffect, useRef, useState } from "react";
import type { ExperimentDetails, JsonObject, Positions } from "../../../../../packages/contracts/src/research";
import { request, useResearch } from "./state";
import { Empty, Field, Heading, valueText } from "./ui";
import { completeModel, completeStrategy, object } from "./configuration";
import { PagedExperimentTable } from "./PagedTable";

export function SelectionPanel() {
  const s = useResearch(); const p = s.project!;
  const savePositions = useRef<(() => Promise<void>) | null>(null);
  const configured = object(p.settings.selection);
  const [strategy, setStrategy] = useState(() => completeStrategy(p.settings, Object.keys(object(configured.strategy)).length ? object(configured.strategy) : object(p.settings.backtest)));
  const [model, setModel] = useState(() => completeModel(p.settings, Object.keys(object(configured.model)).length ? object(configured.model) : object(p.settings.model)));
  const [source, setSource] = useState(String(configured.dataSource ?? "baostock"));
  const [update, setUpdate] = useState(configured.updateData !== false);
  const [financials, setFinancials] = useState(configured.financials !== false);
  const [configurationOpen, setConfigurationOpen] = useState(configured.enabled !== true);
  const [changed, setChanged] = useState(false);
  const [strategyChoice, setStrategyChoice] = useState("project");
  const [modelChoice, setModelChoice] = useState("project");
  const [result, setResult] = useState<ExperimentDetails | null>(null);
  const [view, setView] = useState("candidates");
  const [chosen, setChosen] = useState("");
  const [busy, setBusy] = useState(false);
  const runs = s.experiments.filter(e => e.kind === "selection.run");
  const resultId = chosen || runs[0]?.id;
  useEffect(() => {
    let active = true; setResult(null);
    if (resultId) void s.act(async () => { const next = await request<ExperimentDetails>("experiments.get", { projectId: p.id, experimentId: resultId }); if (active) setResult(next); });
    return () => { active = false; };
  }, [resultId, p.id, s.revision]);
  const snapshot = (): JsonObject => ({ enabled: true, strategy, model, retrain: "monthly", dataSource: source, updateData: update, financials });
  async function choose(kind: "strategy" | "model", id: string) {
    setBusy(true);
    await s.act(async () => {
      const params = id === "project" ? object(p.settings[kind === "strategy" ? "backtest" : "model"])
        : (await request<ExperimentDetails>("experiments.get", { projectId: p.id, experimentId: id })).experiment.parameters;
      if (kind === "strategy") { setStrategy(completeStrategy(p.settings, params)); setStrategyChoice(id); }
      else { setModel(completeModel(p.settings, params)); setModelChoice(id); }
      setChanged(true);
    }); setBusy(false);
  }
  return <div className="r-page"><Heading title="每日选股" description="从已确认方案生成候选、目标组合和调仓清单。清单不会改变实际持仓。" />
    <div className="r-toolbar"><span className="r-tag">{configured.enabled === true ? "方案已启用" : "尚未启用方案"}</span>{changed && <span>编辑中的方案尚未启用</span>}<span>策略：{({ single_factor: "单因子排序", multi_factor: "多因子加权", model_score: "模型评分" } as Record<string, string>)[String(object(configured.strategy).template)] ?? "未配置"}</span><button disabled={configured.enabled !== true || busy || changed} onClick={() => { setBusy(true); void s.act(async () => { if (!savePositions.current) throw new Error("持仓仍在加载。"); await savePositions.current(); await s.submit("selection.run", object(p.settings.selection)); }).finally(() => setBusy(false)); }}>更新并生成清单</button><span>数据日期：{valueText(result?.details.dataDate)}</span><span>模型更新时间：{valueText(result?.details.modelUpdatedAt)}</span></div>
    <details open={configurationOpen} onToggle={e => setConfigurationOpen(e.currentTarget.open)}><summary>策略与模型方案</summary><div className="r-form-grid"><Field label="策略方案"><select value={strategyChoice} disabled={busy} onChange={e => void choose("strategy", e.target.value)}><option value="project">项目已保存策略</option>{s.experiments.filter(e => e.kind === "backtest.run").map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></Field><Field label="模型方案"><select value={modelChoice} disabled={busy} onChange={e => void choose("model", e.target.value)}><option value="project">项目已保存模型设置</option>{s.experiments.filter(e => e.kind === "model.train").map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></Field><Field label="数据源"><select value={source} onChange={e => { setSource(e.target.value); setChanged(true); }}><option value="baostock">BaoStock</option><option value="akshare">AKShare</option></select></Field><label className="r-check"><input type="checkbox" checked={update} onChange={e => { setUpdate(e.target.checked); setChanged(true); }} />生成前增量更新</label><label className="r-check"><input type="checkbox" checked={financials} onChange={e => { setFinancials(e.target.checked); setChanged(true); }} />更新财务数据</label></div>
    <details><summary>查看将启用的方案参数</summary><h3>策略</h3><pre>{JSON.stringify(strategy, null, 2)}</pre><h3>模型 · 每月首次运行时按需重训</h3><pre>{JSON.stringify(model, null, 2)}</pre></details>
    <div className="r-toolbar"><button className="r-primary" disabled={busy} onClick={() => void s.act(async () => { await s.save({ settings: { ...p.settings, selection: snapshot() } }); setChanged(false); setConfigurationOpen(false); s.setNotice("已明确启用所选策略与模型方案"); })}>启用这组方案</button><button onClick={() => s.setPage("strategy")}>编辑策略</button><button onClick={() => s.setPage("model")}>编辑模型</button>{configured.enabled === true && <button onClick={() => void s.act(() => s.save({ settings: { ...p.settings, selection: { ...configured, enabled: false } } }))}>停用方案</button>}</div>
    </details><PositionsEditor saveRef={savePositions} />
    <section><div className="r-toolbar"><h2>选股结果</h2><select aria-label="选股实验" value={resultId ?? ""} onChange={e => setChosen(e.target.value)}>{runs.map(e => <option key={e.id} value={e.id}>{e.name} · {new Date(e.createdAt).toLocaleString("zh-CN")}</option>)}</select>{result && <button onClick={() => { s.setSelectedExperiment(result.experiment.id); s.setPage("results"); }}>查看实验与导出 →</button>}</div>
      {result ? <><p>{result.experiment.summary}</p>{result.details.executable === false && <div className="r-conflicts" role="status"><strong>当前清单不可执行</strong><p>{valueText(result.details.conflicts)}</p></div>}<nav className="r-subtabs" aria-label="选股结果视图">{[["candidates", "候选股票"], ["target_weights", "目标组合"], ["rebalance", "调仓清单"]].map(([id, label]) => <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>{label}</button>)}</nav><PagedExperimentTable key={`${result.experiment.id}-${view}`} experimentId={result.experiment.id} table={view} /><p className="r-note">数量与金额为估算，不能调整的原因保留在清单中。实际交易后请自行更新持仓。</p></> : <Empty title="还没有选股结果">启用方案、保存实际持仓和现金后，生成第一份清单。</Empty>}
    </section></div>;
}

function PositionsEditor({ saveRef }: { saveRef: React.RefObject<(() => Promise<void>) | null> }) {
  const s = useResearch(); const id = s.project!.id;
  const [editorOpen, setEditorOpen] = useState(true);
  const [positions, setPositions] = useState<Positions | null>(null);
  const [dirty, setDirty] = useState(false); const [busy, setBusy] = useState(false);
  useEffect(() => { let active = true; void s.act(async () => { const data = await request<Positions>("positions.get", { projectId: id }); if (active) { setPositions(data); setEditorOpen(!data.updatedAt); } }); return () => { active = false; }; }, [id]);
  saveRef.current = async () => {
    if (busy || !positions) throw new Error("请等待持仓读取或导入完成。");
    if (!dirty) return;
    if (!positions.asOfDate || !Number.isFinite(positions.cash) || positions.cash < 0 || positions.rows.some(r => !r.symbol.trim() || !Number.isInteger(r.quantity) || !Number.isInteger(r.sellableQuantity) || r.quantity < 0 || r.sellableQuantity < 0 || r.sellableQuantity > r.quantity)) throw new Error("请检查持仓日期、证券、现金和可卖数量。");
    setPositions(await request<Positions>("positions.save", { projectId: id, positions })); setDirty(false);
  };
  const change = (next: Positions) => { setPositions(next); setDirty(true); };
  return <details open={editorOpen} onToggle={e => setEditorOpen(e.currentTarget.open)}><summary>实际持仓与可用现金 {dirty ? "· 未保存" : ""}</summary>{positions && <><div className="r-form-grid"><Field label="持仓日期"><input type="date" value={positions.asOfDate} onChange={e => change({ ...positions, asOfDate: e.target.value })} /></Field><Field label="可用现金（元）"><input type="number" min={0} value={positions.cash} onChange={e => change({ ...positions, cash: Number(e.target.value) })} /></Field></div><div className="r-table-scroll"><table><thead><tr><th>证券</th><th>实际股数</th><th>可卖股数</th><th>成本价（可选）</th><th>操作</th></tr></thead><tbody>{positions.rows.map((row, index) => <tr key={index}><td><input aria-label={`第${index + 1}行证券`} value={row.symbol} onChange={e => change({ ...positions, rows: positions.rows.map((r, i) => i === index ? { ...r, symbol: e.target.value } : r) })} /></td>{(["quantity", "sellableQuantity", "costPrice"] as const).map(key => <td key={key}><input aria-label={`第${index + 1}行${key}`} type="number" min={0} value={row[key] ?? ""} onChange={e => change({ ...positions, rows: positions.rows.map((r, i) => i === index ? { ...r, [key]: e.target.value === "" && key === "costPrice" ? undefined : Number(e.target.value) } : r) })} /></td>)}<td><button onClick={() => change({ ...positions, rows: positions.rows.filter((_, i) => i !== index) })}>移除</button></td></tr>)}</tbody></table></div><div className="r-toolbar"><button onClick={() => change({ ...positions, rows: [...positions.rows, { symbol: "", quantity: 0, sellableQuantity: 0 }] })}>添加持仓</button><button disabled={busy} onClick={() => { setBusy(true); void s.act(async () => { if (!positions.asOfDate || positions.cash < 0 || positions.rows.some(r => !r.symbol.trim() || r.quantity < 0 || r.sellableQuantity < 0 || r.sellableQuantity > r.quantity)) throw new Error("请检查持仓日期、证券、现金和可卖数量。"); setPositions(await request<Positions>("positions.save", { projectId: id, positions })); setDirty(false); s.setNotice("实际持仓已保存"); }).finally(() => setBusy(false)); }}>保存实际持仓</button></div></>}<button disabled={busy} onClick={() => { setBusy(true); void s.act(async () => { const files = await window.v3Research!.chooseFiles({ purpose: "positions" }); if (!files.length) return; if (files.length !== 1) throw new Error("请一次选择一个持仓文件。"); const imported = await request<Positions>("positions.import", { projectId: id, path: files[0] }); setPositions(imported); setDirty(false); s.setNotice("持仓文件已导入"); }).finally(() => setBusy(false)); }}>导入持仓 CSV / Excel</button><p className="r-note">导入列：证券代码、持仓数量、可卖数量、成本价（可选）、可用资金、日期。每行一只证券；日期使用 YYYY-MM-DD，数量以股为单位。</p></details>;
}
