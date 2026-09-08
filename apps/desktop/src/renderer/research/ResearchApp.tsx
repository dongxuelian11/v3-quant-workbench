import React, { useEffect, useRef, useState } from "react";
import { DockviewReact, type DockviewApi, type DockviewReadyEvent, type IDockviewPanelProps } from "dockview-react";
import type { ProjectConfig, StrategyConfig, WorkspacePanel, WorkspaceState, WorkspaceWindow } from "../../../../../packages/contracts/src/research";
import { ResearchContext, request, useResearch, useResearchState, jobTitle } from "./state";
import { DataPanel, FactorPanel, UniversePanel } from "./ResearchPanels";
import { ModelPanel, StrategyHome, StrategyPanel } from "./RunPanels";
import { ResultsPanel } from "./ResultsPanel";
import { TodayPanel, MarketPanel, StockPanel, GlobalSelection, DataCenter, ComparePanel } from "./WorkspacePanels";
import { PositionsEditor } from "./SelectionPanel";
import { ConversationPanel } from "./ConversationPanel";
import { Empty, Field, requestText, TextPromptHost } from "./ui";
import { ObjectScope, WorkspaceContext, useWorkspace, flushDrafts } from "./workspace";
import { WindowControls } from "../components/WindowControls";
const defaults: WorkspaceState = { theme: "light", density: "comfortable", sidebarWidth: 210, aiWidth: 330, windows: [], presets: {} };
const panels = { research: ({ params }: IDockviewPanelProps<WorkspacePanel>) => <ObjectScope panel={params}><Panel panel={params} /></ObjectScope> };
function Panel({ panel }: { panel: WorkspacePanel }) {
  const w = useWorkspace(); const s = useResearch(); const saveRef = useRef<(() => Promise<void>) | null>(null);
  let content: React.ReactNode;
  switch (panel.kind) {
    case "today": content = <TodayPanel />; break;
    case "market": case "screener": content = <MarketPanel screening={panel.kind === "screener"} />; break;
    case "stock": content = <StockPanel panel={panel} />; break;
    case "selection": content = <GlobalSelection />; break;
    case "positions": content = <div className="r-page"><h1>实际持仓</h1><p className="r-note">全局实际账户。选股清单不会修改这里的持仓。</p><PositionsEditor saveRef={saveRef} defaultExpanded /></div>; break;
    case "data": content = panel.projectId ? <DataPanel /> : <DataCenter />; break;
    case "compare": content = <ComparePanel refs={panel.experimentRefs ?? []} panelId={panel.id} />; break;
    case "experiment": content = <ResultsPanel />; break;
    case "universe": content = <UniversePanel key={s.configurationVersions.universe ?? 0} />; break;
    case "factors": content = <FactorPanel key={s.configurationVersions.factors ?? 0} />; break;
    case "model": content = <ModelPanel key={s.configurationVersions.model ?? 0} />; break;
    case "strategy": content = panel.view === "backtest" || panel.view === "optimize" ? <StrategyPanel key={s.configurationVersions.strategy ?? 0} run optimize={panel.view === "optimize"} /> : <StrategyHome panel={panel} />; break;
  }
  const strategy = w.strategies.find(x => x.id === panel.strategyId && x.projectId === panel.projectId);
  return <div className="r-object-panel" style={{ containerType: "inline-size", containerName: "object" }}>{strategy && panel.kind !== "experiment" && <div className="r-objectbar r-objectbar-compact">
    <strong title={strategy.name}>{strategy.name}</strong><span className="r-draft-status">草稿自动保存</span>
    <details className="r-object-menu"><summary>策略操作</summary><div>
      <button onClick={() => void s.act(async () => { await flushDrafts(); await request("strategies.activate", { projectId: strategy.projectId, strategyId: strategy.id, enabled: true, allocation: strategy.allocation }); await w.reload(); s.setNotice("当前已保存草稿已应用到每日选股"); })}>应用到每日选股</button>
      <button onClick={() => w.open({ kind: "universe", title: `${strategy.name} · 股票池`, projectId: strategy.projectId, strategyId: strategy.id })}>编辑股票池</button>
      <button onClick={() => void s.act(async () => { const name = await requestText("策略名称", strategy.name); if (name?.trim()) { await flushDrafts(); await request("strategies.save", { projectId: strategy.projectId, strategy: { id: strategy.id, name: name.trim() } }); await w.reload(); } })}>重命名策略</button>
      {strategy.enabled && <button onClick={() => void s.act(async () => { await request("strategies.activate", { projectId: strategy.projectId, strategyId: strategy.id, enabled: false }); await w.reload(); })}>停用每日选股</button>}
    </div></details>
  </div>}{content}</div>;
}
function ResearchLinks({projectId,strategyId,name}:{projectId:string;strategyId?:string;name:string}) {
 const w=useWorkspace();const entries=[['factors','因子研究',undefined],['strategy','策略回测','backtest'],['model','模型训练',undefined],['strategy','参数寻优','optimize'],['experiment','实验结果',undefined]] as const;
 return <div className="r-research-links">{entries.map(([kind,title,view])=><button key={title} className={w.active?.kind===kind&&w.active?.projectId===projectId&&w.active?.strategyId===strategyId&&w.active?.view===view?'active':''} onClick={()=>w.open({kind,view,title:`${name} · ${title}`,projectId,strategyId})}>{title}</button>)}</div>;
}
function StrategyTree({strategy,defaultExpanded}:{strategy:StrategyConfig;defaultExpanded:boolean}) {
 const w=useWorkspace();const [expanded,setExpanded]=useState(defaultExpanded);
 useEffect(()=>setExpanded(defaultExpanded),[defaultExpanded]);
 return <details className="r-strategy-tree" open={expanded} onToggle={e=>setExpanded(e.currentTarget.open)}><summary><span className={`r-status-dot ${strategy.enabled?'enabled':''}`}/>{strategy.name}</summary><button className={w.active?.kind==='strategy'&&w.active?.projectId===strategy.projectId&&w.active?.strategyId===strategy.id&&!w.active?.view?'active':''} onClick={()=>w.open({kind:'strategy',title:strategy.name,projectId:strategy.projectId,strategyId:strategy.id})}>配置摘要</button><ResearchLinks projectId={strategy.projectId} strategyId={strategy.id} name={strategy.name}/></details>;
}
export function ResearchApp() { const state = useResearchState(); return <ResearchContext.Provider value={state}><Shell /></ResearchContext.Provider>; }
function Shell() {
  const s = useResearch(); const latest = useRef(s); latest.current = s;
  const [creating, setCreating] = useState(false); const [settings, setSettings] = useState(false); const [jobsVisible, setJobsVisible] = useState(false);
  const [preferences, setPreferences] = useState(defaults); const prefRef = useRef(preferences); prefRef.current = preferences;
  const [windowInfo, setWindowInfo] = useState<{ id: string; main: boolean; state?: WorkspaceWindow } | null>(null);
  const infoRef = useRef(windowInfo); infoRef.current = windowInfo;
  const [strategies, setStrategies] = useState<StrategyConfig[]>([]); const [active, setActive] = useState<WorkspacePanel>(); const [bottom, setBottom] = useState(180); const [groupCount, setGroupCount] = useState(1);
  const api = useRef<DockviewApi | null>(null); const timer = useRef<ReturnType<typeof setTimeout> | null>(null); const restoring = useRef(false); const dockReady = useRef(false);
  const cancelSave = () => { if (timer.current) clearTimeout(timer.current); timer.current = null; };
  const reload = async () => { setStrategies(await request<StrategyConfig[]>("strategies.list")); await latest.current.refreshProjects(); };
  async function savePreferences(patch: Partial<WorkspaceState>) { const next = { ...prefRef.current, ...patch }; prefRef.current = next; setPreferences(next); await request("workspace.save", { state: patch }); window.v3Research?.workspace?.broadcast({ method: "workspace.preferences" }); }
  function snapshot(): WorkspaceWindow { const info = infoRef.current!; return { ...info.state, id: info.id, main: info.main, dock: JSON.parse(JSON.stringify(api.current!.toJSON())), panels: api.current!.panels.map(p => p.params as WorkspacePanel), activePanelId: api.current!.activePanel?.id }; }
  async function persistNow() { if (!api.current || !infoRef.current || restoring.current) return; cancelSave(); const state = snapshot(); if (window.v3Research?.workspace) await window.v3Research.workspace.update(state); else await request("workspace.save", { state: { windows: [state] } }); }
  function persist() { if (restoring.current) return; cancelSave(); timer.current = setTimeout(() => void latest.current.act(persistNow), 450); }
  function open(panel: Omit<WorkspacePanel, "id"> & { id?: string }, split?: "right" | "below") {
    const dock = api.current; if (!dock) return;
    let id = panel.id ?? [panel.kind, panel.projectId, panel.strategyId, panel.view, panel.experimentId, panel.symbol, panel.kind === "compare" ? crypto.randomUUID() : ""].filter(Boolean).join(":");
    const existing = dock.getPanel(id);
    if (!panel.id && panel.kind === "experiment") {
      const matching = dock.panels.find(p => p.params?.kind === "experiment" && p.params.projectId === panel.projectId && p.params.strategyId === panel.strategyId && p.params.experimentId === panel.experimentId);
      if (matching) { matching.api.setActive(); return; }
      if (existing) id = `${id}:${crypto.randomUUID()}`;
    } else if (existing) { existing.api.setActive(); return; }
    dock.addPanel({ id, component: "research", title: panel.title, params: { ...panel, id }, ...(split && dock.activePanel ? { position: { referencePanel: dock.activePanel.id, direction: split } } : {}) });
  }
  function restore(state?: WorkspaceWindow) {
    if (!api.current) return; restoring.current = true; cancelSave(); api.current.clear();
    let restored = false;
    if (state?.dock) try { api.current.fromJSON(state.dock as unknown as ReturnType<DockviewApi["toJSON"]>); restored = true; } catch { latest.current.setNotice("保存的分屏布局无法读取，已按工作对象恢复。"); }
    if (!restored) for (const panel of state?.panels ?? []) open(panel);
    if (!api.current.panels.length && infoRef.current?.main) open({ kind: "today", title: "今日工作台" });
    if (state?.activePanelId) api.current.getPanel(state.activePanelId)?.api.setActive(); restoring.current = false;
  }
  useEffect(() => { let alive = true; void s.act(async () => {
    const [saved, info] = await Promise.all([request<WorkspaceState>("workspace.get"), window.v3Research?.workspace?.current() ?? Promise.resolve<{ id: string; main: boolean; state?: WorkspaceWindow }>({ id: "main", main: true })]);
    if (!alive) return; const next = { ...defaults, ...saved }; prefRef.current = next; setPreferences(next); const current = { ...info, state: info.state ?? next.windows.find(w => w.id === info.id) }; infoRef.current = current; setWindowInfo(current); await reload();
  }); return () => { alive = false; cancelSave(); }; }, []);
  useEffect(() => { document.documentElement.dataset.theme = preferences.theme; document.documentElement.dataset.density = preferences.density; }, [preferences.theme, preferences.density]);
  useEffect(() => { const bridge = window.v3Research?.workspace; if (!bridge) return;
    const offPanels = bridge.onPanels(incoming => { cancelSave(); for (const panel of incoming) open(panel); void latest.current.act(persistNow); });
    const offChanged = bridge.onChanged(change => { if (change.method === "workspace.layout") void latest.current.act(async () => { const info = await bridge.current(); infoRef.current = info; setWindowInfo(info); restore(info.state); }); else if (change.method === "workspace.preferences") void latest.current.act(async () => { const next = await request<WorkspaceState>("workspace.get"); prefRef.current = { ...defaults, ...next }; setPreferences(prefRef.current); }); else if (change.method === "stock.link") { const symbol = String(change.params?.symbol ?? ""); if (symbol) window.dispatchEvent(new CustomEvent("v3-stock-link", { detail: symbol })); } else if (change.method.startsWith("strategies")) void latest.current.act(reload); });
    return () => { offPanels(); offChanged(); };
  }, []);
  function ready(event: DockviewReadyEvent) { api.current = event.api; dockReady.current = true; restore(infoRef.current?.state); setActive(event.api.activePanel?.params as WorkspacePanel | undefined); setGroupCount(event.api.groups.length); event.api.onDidLayoutChange(() => { setGroupCount(event.api.groups.length); persist(); }); event.api.onDidActivePanelChange(e => setActive(e.panel?.params as WorkspacePanel | undefined));
    event.api.onWillDragPanel(event => { const id = event.panel.id; const target = event.nativeEvent.target; if (!(event.nativeEvent instanceof DragEvent) || !(target instanceof HTMLElement)) return; target.addEventListener("dragend", event => { const drag = event as DragEvent; if (drag.dataTransfer?.dropEffect === "none" && (drag.clientX < 0 || drag.clientY < 0 || drag.clientX > window.innerWidth || drag.clientY > window.innerHeight)) void latest.current.act(() => detach(id, { x: drag.screenX - 120, y: drag.screenY - 30, width: 1200, height: 850 })); }, { once: true }); }); }

  async function detach(id?: string, bounds?: WorkspaceWindow["bounds"]) { const panel = id ? api.current?.getPanel(id) : api.current?.activePanel; if (!panel || !window.v3Research?.workspace) return; cancelSave(); await flushDrafts(); await window.v3Research.workspace.detach(panel.params as WorkspacePanel, bounds ?? { width: 1200, height: 850 }); panel.api.close(); cancelSave(); await persistNow(); }
  async function singleWorkspace() {
    const dock = api.current; const activePanel = dock?.activePanel; if (!dock || !activePanel) return;
    await flushDrafts();
    if (dock.hasMaximizedGroup()) dock.exitMaximizedGroup();
    const group = activePanel.group;
    for (const panel of [...dock.panels]) if (panel.group !== group) panel.api.moveTo({ group });
    activePanel.api.setActive(); await persistNow();
  }
  async function attach() { if (!api.current || !window.v3Research?.workspace) return; cancelSave(); await flushDrafts(); const moved = api.current.panels.map(p => p.params as WorkspacePanel); restoring.current = true; try { await window.v3Research.workspace.attach(moved); } catch (error) { restoring.current = false; throw error; } }
  function linkStock(symbol: string) { window.dispatchEvent(new CustomEvent("v3-stock-link", { detail: symbol })); window.v3Research?.workspace?.broadcast({ method: "stock.link", params: { symbol } }); }
  async function preset(name: string) { cancelSave(); if (prefRef.current.presets[name]) { const windows = prefRef.current.presets[name]; await window.v3Research?.workspace?.restore(windows); restore(windows.find(w => w.id === infoRef.current?.id)); return; }
    restoring.current = true; api.current?.clear();
    if (name === "市场") { open({ kind: "market", title: "市场概况" }); open({ kind: "stock", title: "联动个股", id: "stock:linked" }, "right"); }
    else if (name === "选股") { open({ kind: "selection", title: "每日选股" }); open({ kind: "positions", title: "实际持仓" }, "below"); }
    else if (name === "比较") open({ kind: "compare", title: "实验比较" });
    else { const st = strategies[0]; open(st ? { kind: "strategy", title: st.name, projectId: st.projectId, strategyId: st.id } : { kind: "today", title: "今日工作台" }); }
    restoring.current = false; await persistNow();
  }
  const resize = (kind: "sidebarWidth" | "aiWidth" | "bottom", e: React.PointerEvent<HTMLDivElement>) => { const element = e.currentTarget; element.setPointerCapture(e.pointerId); const x = e.clientX, y = e.clientY, initial = kind === "bottom" ? bottom : prefRef.current[kind]; element.onpointermove = v => { const value = Math.max(kind === "bottom" ? 100 : kind === "aiWidth" ? 280 : 170, Math.min(kind === "bottom" ? 420 : kind === "aiWidth" ? 700 : 380, initial + (kind === "bottom" ? y - v.clientY : kind === "aiWidth" ? x - v.clientX : v.clientX - x))); if (kind === "bottom") setBottom(value); else { prefRef.current = { ...prefRef.current, [kind]: value }; setPreferences(prefRef.current); } }; element.onpointerup = () => { element.onpointermove = null; element.onpointerup = null; if (kind !== "bottom") void s.act(() => savePreferences({ [kind]: prefRef.current[kind] })); }; };
  const activeJobs = s.jobs.filter(j => ["queued", "running"].includes(j.status));
  return <WorkspaceContext.Provider value={{ open, updatePanel: (id, patch) => { const panel = api.current?.getPanel(id); if (panel) { panel.api.updateParameters({ ...panel.params, ...patch }); if (patch.title) panel.api.setTitle(patch.title); if (api.current?.activePanel?.id === id) setActive(panel.params as WorkspacePanel); persist(); } }, strategies, reload, active, preferences, savePreferences, linkStock }}><div className="r-app" data-testid="research-app" style={{ "--r-sidebar": `${preferences.sidebarWidth}px`, "--r-ai": `${preferences.aiWidth}px`, "--r-tasks": `${bottom}px` } as React.CSSProperties}>
    <header className="r-titlebar"><div className="r-brand"><strong>V3</strong><span>研究工作台</span></div><span className="r-project-title">{windowInfo?.main ? "本地研究 · A 股日线" : "独立工作窗口"}</span><div className="r-title-actions"><button onClick={() => void s.act(() => savePreferences({ theme: preferences.theme === "light" ? "dark" : "light" }))}>{preferences.theme === "light" ? "深色" : "浅色"}</button><button onClick={() => void s.act(() => savePreferences({ density: preferences.density === "compact" ? "comfortable" : "compact" }))}>{preferences.density === "compact" ? "标准行高" : "密集行高"}</button>{window.v3Desktop && <WindowControls />}</div></header>
    {s.error && <div className="r-banner error" role="alert"><span>{s.error}</span><button onClick={() => s.setError("")} aria-label="关闭错误">×</button></div>}{s.notice && <div className="r-banner" role="status"><span>{s.notice}</span><button onClick={() => s.setNotice("")} aria-label="关闭提示">×</button></div>}
    <div className="r-body">{windowInfo?.main && <><aside className="r-sidebar"><nav aria-label="全局导航">{([["today","今日工作台"],["market","市场概况"],["screener","筛选与自选"],["selection","每日选股"],["positions","实际持仓"],["data","数据中心"]] as const).map(([kind,title]) => <button key={kind} className={active?.kind === kind ? "active" : ""} onClick={() => open({ kind, title })}>{title}</button>)}</nav><hr /><div className="r-toolbar"><h2>研究项目</h2><button aria-label="新建项目" onClick={() => setCreating(true)}>＋</button></div><div className="r-project-tree">{!s.projects.length&&<div className="r-research-empty"><p>因子研究、策略回测、模型训练与参数寻优保存在研究项目中。</p><button onClick={()=>setCreating(true)}>创建研究项目</button><p>已有项目？使用下方“打开项目文件夹”继续研究和查看实验。</p></div>}{s.projects.map(p => <details key={p.id} open><summary>{p.name}</summary>{strategies.filter(st => st.projectId === p.id).map(st => <StrategyTree key={st.id} strategy={st} defaultExpanded={active?.strategyId?active.strategyId===st.id&&active.projectId===st.projectId:strategies[0]?.id===st.id&&strategies[0]?.projectId===st.projectId}/>)}{!strategies.some(st=>st.projectId===p.id)&&<ResearchLinks projectId={p.id} name={p.name}/>}<button className="r-muted" onClick={() => void s.act(async () => { const name = await requestText("新策略名称"); if (!name?.trim()) return; const st = await request<StrategyConfig>("strategies.create", { projectId: p.id, name: name.trim() }); await reload(); open({ kind: "strategy", title: st.name, projectId: p.id, strategyId: st.id }); })}>＋ 新策略</button><button onClick={() => open({ kind: "data", projectId: p.id, title: `${p.name} · 数据` })}>项目数据</button></details>)}</div><button className="r-sidebar-action" onClick={() => void s.act(async () => { const path = await window.v3Research!.chooseDirectory(); if (path) { await s.open(path); await reload(); } })}>打开项目文件夹</button><div className="r-sidebar-foot"><button onClick={() => setSettings(true)}>设置</button><small>数据与实验保存在本地</small></div></aside><div className="r-resize" role="separator" aria-label="调整导航宽度" onPointerDown={e => resize("sidebarWidth", e)} /></>}
    <main className="r-main"><div className="r-workspace-toolbar">{groupCount > 1 && <button className="r-primary" title="保留所有标签，合并为一个宽工作区" onClick={() => void s.act(singleWorkspace)}>合并分屏</button>}<select aria-label="切换工作区预设" value="" onChange={e => void s.act(() => preset(e.target.value))}><option value="" disabled>工作区布局</option>{[...new Set(["研究","比较","市场","选股",...Object.keys(preferences.presets)])].map(name => <option key={name}>{name}</option>)}</select><button onClick={() => void s.act(async () => { const name = await requestText("保存工作区名称"); if (!name?.trim()) return; await persistNow(); const state = await request<WorkspaceState>("workspace.get"); await savePreferences({ presets: { ...state.presets, [name.trim()]: state.windows } }); })}>保存布局</button><span className="r-spacer" /><button disabled={!active} title="复制当前对象并在右侧分屏" onClick={() => active && open({ ...active, id: crypto.randomUUID() }, "right")}>右侧分屏</button><button disabled={!active || !window.v3Research?.workspace} title="将当前标签拖出为独立 Windows 窗口，可移至第二屏" onClick={() => void s.act(() => detach())}>拖出到窗口 ↗</button>{windowInfo && !windowInfo.main && <button onClick={() => void s.act(attach)}>全部移回主窗口</button>}</div><div className="r-dock">{windowInfo ? <DockviewReact className={`dockview-theme-${preferences.theme}`} components={panels} onReady={ready} /> : <Empty title="正在恢复工作区…" />}</div></main>
    {windowInfo?.main && <><div className="r-resize" role="separator" aria-label="调整 AI 宽度" onPointerDown={e => resize("aiWidth", e)} /><ConversationPanel settingsOpen={settings} closeSettings={() => setSettings(false)} /></>}</div>
    <footer className="r-taskbar"><button onClick={() => setJobsVisible(v => !v)} aria-expanded={jobsVisible}>任务 <span>{activeJobs.length ? `${activeJobs.length} 项进行中` : "无运行任务"}</span><span>{jobsVisible ? "收起" : "展开"}</span></button>{jobsVisible && <><div className="r-resize horizontal" onPointerDown={e => resize("bottom", e)} /><Jobs /></>}</footer>{creating && <CreateProject close={() => { setCreating(false); void s.act(reload); }} />}</div><TextPromptHost /></WorkspaceContext.Provider>;
}

function CreateProject({ close }: { close: () => void }) {
  const s = useResearch(); const [name, setName] = useState(""); const [path, setPath] = useState(""); const [objective, setObjective] = useState(""); const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null); useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="r-dialog" onCancel={close}><form onSubmit={e => { e.preventDefault(); setBusy(true); void s.act(async () => { const p = await request<ProjectConfig>("projects.create", { path, name: name.trim(), objective: objective.trim() }); await s.open(p.path); close(); }).finally(() => setBusy(false)); }}><h2>新建研究项目</h2><p>项目文件、数据与实验保存在你选择的文件夹。</p><Field label="项目名称"><input required autoFocus value={name} onChange={e => setName(e.target.value)} /></Field><Field label="项目文件夹"><div className="r-toolbar"><input required value={path} onChange={e => setPath(e.target.value)} /><button type="button" onClick={() => void s.act(async () => { const chosen = await window.v3Research!.chooseDirectory(); if (chosen) setPath(chosen); })}>选择文件夹</button></div></Field><Field label="研究目标"><textarea rows={4} value={objective} onChange={e => setObjective(e.target.value)} placeholder="想验证怎样的投资假设？" /></Field><div className="r-toolbar"><button type="button" onClick={close}>取消</button><button className="r-primary" disabled={busy || !name.trim() || !path.trim()} type="submit">{busy ? "创建中…" : "创建项目"}</button></div></form></dialog>;
}
function Jobs() {
  const s = useResearch(); const w = useWorkspace(); const labels = { queued: "排队中", running: "运行中", completed: "已完成", failed: "失败", cancelled: "已取消", interrupted: "已中断" };
  return <div className="r-jobs">{s.jobs.length ? s.jobs.map(j => <div className="r-job" key={j.id}><strong>{jobTitle(j.kind, j.name)}</strong><span>{labels[j.status]}</span><progress max={1} value={Math.max(0, Math.min(1, j.progress))} aria-label={`${jobTitle(j.kind, j.name)}进度`} /><span title={j.message}>{j.message}</span>{["queued", "running"].includes(j.status) ? <button onClick={() => void s.act(async () => { await request("jobs.cancel", { jobId: j.id }); await s.refresh(); })}>取消</button> : <button onClick={() => void s.act(() => request("jobs.submit", { spec: j.spec }))}>重跑</button>}{j.experimentId && <button onClick={() => { w.open({ kind: "experiment", title: jobTitle(j.kind, j.name), projectId: j.projectId, strategyId: j.strategyId, experimentId: j.experimentId }); }}>查看结果</button>}</div>) : <Empty title="还没有任务记录" />}</div>;
}
