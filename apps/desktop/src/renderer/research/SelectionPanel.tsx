import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ExperimentDetails, JobEvent, JsonObject, Positions, SelectionPositionsSource } from "../../../../../packages/contracts/src/research";
import { request, useResearch } from "./state";
import { DataTable, Empty, Field, Heading, valueText } from "./ui";
import { completeModel, completeStrategy, object } from "./configuration";
import { SelectionPositionsSourceEditor } from "./SelectionPositionsSourceEditor";
import { useWorkspace } from "./workspace";
import { PagedExperimentTable } from "./PagedTable";
import { readScope } from "./readCancellation";

export function SelectionPanel() {
  const s = useResearch(); const p = s.project!; const w = useWorkspace();
  const [positionsSource, setPositionsSource] = useState<SelectionPositionsSource>({ kind: "none" });
  const submissionLock = useRef(false);
  const savePositions = useRef<(() => Promise<void>) | null>(null);
  const configured = object(p.settings.selection);
  const usingSimulation = positionsSource.kind === "simulation";
  const [strategy, setStrategy] = useState(() => completeStrategy(p.settings, Object.keys(object(configured.strategy)).length ? object(configured.strategy) : object(p.settings.backtest)));
  const [model, setModel] = useState(() => completeModel(p.settings, Object.keys(object(configured.model)).length ? object(configured.model) : object(p.settings.model)));
  const [source, setSource] = useState(String(configured.dataSource ?? "baostock"));
  const [update, setUpdate] = useState(configured.updateData !== false);
  const [researchDate, setResearchDate] = useState("");
  const [financials, setFinancials] = useState(configured.financials !== false);
  const [configurationOpen, setConfigurationOpen] = useState(configured.enabled !== true);
  const [changed, setChanged] = useState(false);
  const [strategyChoice, setStrategyChoice] = useState("project");
  const [modelChoice, setModelChoice] = useState("project");
  const [result, setResult] = useState<ExperimentDetails | null>(null);
  const [contributionSymbol, setContributionSymbol] = useState("");
  const [view, setView] = useState("candidates");
  const [chosen, setChosen] = useState("");
  const [busy, setBusy] = useState(false);
  const [accountJob, setAccountJob] = useState<JobEvent | null>(null);
  const [sharedResult, setSharedResult] = useState<ExperimentDetails | null>(null);
  const [sharedResultError, setSharedResultError] = useState("");
  const [sharedView, setSharedView] = useState("candidates");
  const [sharedRetry, setSharedRetry] = useState(0);
  const sharedLoad = useRef("");
  useEffect(() => { setAccountJob(null); setSharedResult(null); setSharedResultError(""); setSharedView("candidates"); sharedLoad.current = ""; }, [positionsSource.kind, positionsSource.kind === "simulation" ? positionsSource.accountId : "", positionsSource.kind === "simulation" ? positionsSource.projectId : ""]);
  useEffect(() => {
    if (!accountJob) return;
    const saved = s.jobs.find(job => job.id === accountJob.id);
    if (saved && saved !== accountJob) setAccountJob(saved);
    const unsubscribe = window.v3Research?.onEvent(event => { if ("id" in event && event.id === accountJob.id && "kind" in event && event.kind === "selection.run") setAccountJob(event as JobEvent); });
    return () => unsubscribe?.();
  }, [accountJob?.id]);
  useEffect(() => {
    if (!accountJob || accountJob.status !== "completed" || !accountJob.experimentId) return;
    const key = `${accountJob.id}:${accountJob.experimentId}`;
    if (sharedLoad.current === key) return;
    sharedLoad.current = key; let active = true; const reads = readScope(); setSharedResult(null); setSharedResultError("");
    void reads.request<ExperimentDetails>("experiments.get", { experimentId: accountJob.experimentId }).then(detail => { if (active) setSharedResult(detail); }).catch(error => { if (active) { sharedLoad.current = ""; setSharedResultError(error instanceof Error ? error.message : String(error)); } });
    return () => { active = false; reads.cancel(); };
  }, [accountJob?.id, accountJob?.status, accountJob?.experimentId, sharedRetry]);
  const runs = s.experiments.filter(e => e.kind === "selection.run");
  const resultId = chosen || runs[0]?.id;
  useEffect(() => {
    let active = true; setResult(null); setContributionSymbol("");
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
    <div className="r-toolbar"><span className="r-tag">{configured.enabled === true ? "方案已启用" : "尚未启用方案"}</span>{changed && <span>编辑中的方案尚未启用</span>}<span>{usingSimulation?"自由策略（本次不使用）":"策略"}：{({ single_factor: "单因子排序", multi_factor: "多因子加权", model_score: "模型评分" } as Record<string, string>)[String(object(configured.strategy).template)] ?? "未配置"}</span><button disabled={busy || (!usingSimulation && (configured.enabled !== true || changed))} onClick={() => { if(submissionLock.current)return;submissionLock.current=true;setBusy(true); void s.act(async () => { if (!savePositions.current) throw new Error("持仓仍在加载。"); await savePositions.current(); if(usingSimulation){const job=await request<JobEvent>("jobs.submit",{spec:{kind:"selection.run",name:"账户固定版本研究",parameters:{positionsSource,updateData:update,...(researchDate?{date:researchDate}:{})}}});setAccountJob(job);setSharedResult(null);setSharedResultError("");sharedLoad.current="";s.setNotice("账户固定版本研究已提交，账户未推进。");}else await s.submit("selection.run", { ...object(p.settings.selection), positionsSource: { ...positionsSource }, ...(researchDate?{date:researchDate}:{}) }); }).finally(() => {submissionLock.current=false;setBusy(false);}); }}>更新并生成清单</button><span>数据日期：{valueText(result?.details.dataDate)}</span><span>模型更新时间：{result?.details.modelUpdatedAt ? new Date(String(result.details.modelUpdatedAt)).toLocaleString("zh-CN") : "—"}</span></div>
    <fieldset disabled={busy || usingSimulation}><legend>自由策略与模型（模拟账户研究不使用）</legend><details open={configurationOpen} onToggle={e => setConfigurationOpen(e.currentTarget.open)}><summary>策略与模型方案</summary><div className="r-form-grid"><Field label="策略方案"><select value={strategyChoice} disabled={busy} onChange={e => void choose("strategy", e.target.value)}><option value="project">项目已保存策略</option>{s.experiments.filter(e => e.kind === "backtest.run").map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></Field><Field label="模型方案"><select value={modelChoice} disabled={busy} onChange={e => void choose("model", e.target.value)}><option value="project">项目已保存模型设置</option>{s.experiments.filter(e => e.kind === "model.train").map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></Field><Field label="数据源"><select value={source} onChange={e => { setSource(e.target.value); setChanged(true); }}><option value="baostock">BaoStock</option><option value="akshare">AKShare</option></select></Field><label className="r-check"><input type="checkbox" checked={update} onChange={e => { setUpdate(e.target.checked); setChanged(true); }} />生成前增量更新</label><label className="r-check"><input type="checkbox" checked={financials} onChange={e => { setFinancials(e.target.checked); setChanged(true); }} />更新财务数据</label></div>
    <details><summary>查看将启用的方案参数</summary><h3>策略</h3><pre>{JSON.stringify(strategy, null, 2)}</pre><h3>模型 · 每月首次运行时按需重训</h3><pre>{JSON.stringify(model, null, 2)}</pre></details>
    <div className="r-toolbar"><button className="r-primary" disabled={busy} onClick={() => void s.act(async () => { await s.save({ settings: { ...p.settings, selection: snapshot() } }); setChanged(false); setConfigurationOpen(false); s.setNotice("已明确启用所选策略与模型方案"); })}>启用这组方案</button><button onClick={() => s.setPage("strategy")}>编辑策略</button><button onClick={() => s.setPage("model")}>编辑模型</button>{configured.enabled === true && <button onClick={() => void s.act(() => s.save({ settings: { ...p.settings, selection: { ...configured, enabled: false } } }))}>停用方案</button>}</div>
    </details></fieldset><SelectionPositionsSourceEditor value={positionsSource} onChange={value => { setPositionsSource(value); setAccountJob(null); setSharedResult(null); setSharedResultError(""); }} saveRef={savePositions} disabled={busy} />
    <div className="r-form-grid"><Field label="研究日期（留空使用最近完整交易日）"><input aria-label="每日选股研究日期" type="date" value={researchDate} onChange={e => setResearchDate(e.target.value)} /></Field>{usingSimulation && <label className="r-check"><input type="checkbox" checked={update} disabled={busy} onChange={e => setUpdate(e.target.checked)} />生成前更新数据</label>}</div>
    {usingSimulation && accountJob && <section className="simulation-card"><div className="r-toolbar"><h2>账户固定版本研究任务</h2><span>{accountJob.status === "queued" ? "排队中" : accountJob.status === "running" ? `运行中 · ${accountJob.progress}%` : accountJob.status === "completed" ? "已完成" : accountJob.status === "failed" ? "失败" : accountJob.status === "cancelled" ? "已取消" : "已中断"}</span>{["queued", "running"].includes(accountJob.status) && <button disabled={busy} onClick={() => { setBusy(true); void request("jobs.cancel", { jobId: accountJob.id }).then(() => s.setNotice("已请求停止账户研究任务")).catch(error => setSharedResultError(error instanceof Error ? error.message : String(error))).finally(() => setBusy(false)); }}>停止任务</button>}</div><p>{accountJob.message}</p>{accountJob.status === "completed" && !accountJob.experimentId && <p role="status">任务完成但尚未登记可读实验。{accountJob.registrationPending ? "实验登记仍在处理中。" : "暂时没有可打开的实验结果。"}</p>}{["failed", "cancelled", "interrupted"].includes(accountJob.status) && <p role="alert">{accountJob.message}</p>}{sharedResultError && <p role="alert">共享实验读取失败：{sharedResultError} <button onClick={() => setSharedRetry(value => value + 1)}>重试读取</button></p>}{accountJob.experimentId && !sharedResult && !sharedResultError && <p role="status">正在读取全局实验 {accountJob.experimentId}…</p>}{sharedResult && <><div className="r-toolbar"><strong>{sharedResult.experiment.name} · 全局共享实验</strong><button onClick={() => w.open({ kind: "experiment", title: sharedResult.experiment.name, experimentId: sharedResult.experiment.id })}>打开共享实验详情与导出</button></div><p>{sharedResult.experiment.summary}</p>{sharedResult.details.executable === false && <p role="status">当前结果不可执行：{valueText(sharedResult.details.conflicts)}</p>}<nav className="r-subtabs" aria-label="账户研究结果表">{["candidates", "target_weights", "rebalance"].filter(table => sharedResult.tables.some(item => item.name === table)).map(table => <button key={table} className={sharedView === table ? "active" : ""} onClick={() => setSharedView(table)}>{table === "candidates" ? "候选股票" : table === "target_weights" ? "目标组合" : "净调仓"}</button>)}</nav>{sharedResult.tables.some(item => item.name === sharedView) ? <><DataTable table={sharedResult.tables.find(item => item.name === sharedView)!} /><p className="r-note">上表是实验详情返回的只读预览；点击“打开共享实验详情与导出”查看完整分页结果。</p></> : <Empty title="此实验没有该表" />}</>}</section>}
    <section><div className="r-toolbar"><h2>选股结果</h2><select aria-label="选股实验" value={resultId ?? ""} onChange={e => setChosen(e.target.value)}>{runs.map(e => <option key={e.id} value={e.id}>{e.name} · {new Date(e.createdAt).toLocaleString("zh-CN")}</option>)}</select>{result && <button onClick={() => { s.setSelectedExperiment(result.experiment.id); s.setPage("results"); }}>查看实验与导出 →</button>}</div>
      {result ? <><p>{result.experiment.summary}</p>{result.details.executable === false && <div className="r-conflicts" role="status"><strong>当前清单不可执行</strong><p>{valueText(result.details.conflicts)}</p></div>}<nav className="r-subtabs" aria-label="选股结果视图">{[["candidates", "候选股票"], ["target_weights", "目标组合"], ["rebalance", "调仓清单"]].map(([id, label]) => <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>{label}</button>)}</nav><PagedExperimentTable key={`${result.experiment.id}-${view}`} experimentId={result.experiment.id} table={view} onRow={view === "candidates" ? row => { if (typeof row.symbol === "string") setContributionSymbol(row.symbol); } : undefined} />{view === "candidates" && <><p className="r-note">点击候选证券查看因子贡献。</p>{contributionSymbol && <section><div className="r-toolbar"><h3>{contributionSymbol} · 因子贡献</h3><button onClick={() => setContributionSymbol("")}>关闭详情</button></div>{result.experiment.artifacts.some(a => a.name === "factor_contributions") ? <PagedExperimentTable key={`${result.experiment.id}-${contributionSymbol}`} experimentId={result.experiment.id} table="factor_contributions" initialSymbol={contributionSymbol} /> : <p className="r-note">该实验未保存因子贡献表。</p>}</section>}</>}<p className="r-note">数量与金额为估算，不能调整的原因保留在清单中。实际交易后请自行更新持仓。</p></> : <Empty title="还没有选股结果">启用方案即可生成候选研究；如需账户相关清单，再明确选择实际持仓或模拟账户。</Empty>}
    </section></div>;
}

export function PositionsEditor({ saveRef, defaultExpanded = false }: { defaultExpanded?: boolean; saveRef: React.RefObject<(() => Promise<void>) | null> }) {
  const s = useResearch(); const id = s.project?.id;
  const [editorOpen, setEditorOpen] = useState(true);
  const [legacyProject, setLegacyProject] = useState("");
  const [positions, setPositions] = useState<Positions | null>(null);
  const [dirty, setDirty] = useState(false); const [busy, setBusy] = useState(false);
  useEffect(() => { let active = true; void s.act(async () => { const data = await request<Positions>("positions.get", { projectId: id }); if (active) { setPositions(data); setEditorOpen(defaultExpanded || !data.updatedAt); } }); return () => { active = false; }; }, [id]);
  useLayoutEffect(() => {
  const saveCurrentPositions = async () => {
    if (busy || !positions) throw new Error("请等待持仓读取或导入完成。");
    if (!dirty) return;
    if (!positions.asOfDate || !Number.isFinite(positions.cash) || positions.cash < 0 || positions.rows.some(r => !r.symbol.trim() || !Number.isInteger(r.quantity) || !Number.isInteger(r.sellableQuantity) || r.quantity < 0 || r.sellableQuantity < 0 || r.sellableQuantity > r.quantity)) throw new Error("请检查持仓日期、证券、现金和可卖数量。");
    setPositions(await request<Positions>("positions.save", { projectId: id, positions })); setDirty(false);
  };
  saveRef.current = saveCurrentPositions;
  return () => { if (saveRef.current === saveCurrentPositions) saveRef.current = null; };
  }, [busy, positions, dirty, id, saveRef]);
  const change = (next: Positions) => { setPositions(next); setDirty(true); };
  return <details open={editorOpen} onToggle={e => setEditorOpen(e.currentTarget.open)}><summary>实际持仓与可用现金 {dirty ? "· 未保存" : ""}</summary>{positions && <><div className="r-form-grid"><Field label="持仓日期"><input type="date" value={positions.asOfDate} onChange={e => change({ ...positions, asOfDate: e.target.value })} /></Field><Field label="可用现金（元）"><input type="number" min={0} value={positions.cash} onChange={e => change({ ...positions, cash: Number(e.target.value) })} /></Field></div><div className="r-table-scroll"><table><thead><tr><th>证券</th><th>实际股数</th><th>可卖股数</th><th>成本价（可选）</th><th>操作</th></tr></thead><tbody>{positions.rows.map((row, index) => <tr key={index}><td><input aria-label={`第${index + 1}行证券`} value={row.symbol} onChange={e => change({ ...positions, rows: positions.rows.map((r, i) => i === index ? { ...r, symbol: e.target.value } : r) })} /></td>{(["quantity", "sellableQuantity", "costPrice"] as const).map(key => <td key={key}><input aria-label={`第${index + 1}行${key}`} type="number" min={0} value={row[key] ?? ""} onChange={e => change({ ...positions, rows: positions.rows.map((r, i) => i === index ? { ...r, [key]: e.target.value === "" && key === "costPrice" ? undefined : Number(e.target.value) } : r) })} /></td>)}<td><button onClick={() => change({ ...positions, rows: positions.rows.filter((_, i) => i !== index) })}>移除</button></td></tr>)}</tbody></table></div><div className="r-toolbar"><button onClick={() => change({ ...positions, rows: [...positions.rows, { symbol: "", quantity: 0, sellableQuantity: 0 }] })}>添加持仓</button><button disabled={busy} onClick={() => { setBusy(true); void s.act(async () => { if (!positions.asOfDate || positions.cash < 0 || positions.rows.some(r => !r.symbol.trim() || r.quantity < 0 || r.sellableQuantity < 0 || r.sellableQuantity > r.quantity)) throw new Error("请检查持仓日期、证券、现金和可卖数量。"); setPositions(await request<Positions>("positions.save", { projectId: id, positions })); setDirty(false); s.setNotice("实际持仓已保存"); }).finally(() => setBusy(false)); }}>保存实际持仓</button></div></>}<button disabled={busy} onClick={() => { setBusy(true); void s.act(async () => { const files = await window.v3Research!.chooseFiles({ purpose: "positions" }); if (!files.length) return; if (files.length !== 1) throw new Error("请一次选择一个持仓文件。"); const imported = await request<Positions>("positions.import", { projectId: id, path: files[0] }); setPositions(imported); setDirty(false); s.setNotice("持仓文件已导入"); }).finally(() => setBusy(false)); }}>导入持仓 CSV / Excel</button>{!id && <div className="r-toolbar"><select aria-label="旧项目持仓" value={legacyProject} onChange={e => setLegacyProject(e.target.value)}><option value="">选择旧项目持仓</option>{s.projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><button disabled={!legacyProject || busy} onClick={() => void s.act(async () => { const old = await request<Positions>("positions.get", { projectId: legacyProject }); setPositions(old); setDirty(true); setEditorOpen(true); s.setNotice("旧项目持仓已载入编辑区，请核对后保存到全局账户"); })}>载入旧项目持仓</button></div>}<p className="r-note">导入列：证券代码、持仓数量、可卖数量、成本价（可选）、可用资金、日期。每行一只证券；日期使用 YYYY-MM-DD，数量以股为单位。</p></details>;
}
