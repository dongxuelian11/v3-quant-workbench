import React, { useEffect, useRef, useState } from "react";
import { DockviewReact, type DockviewApi, type DockviewReadyEvent, type IDockviewPanelProps } from "dockview-react";
import type { ExperimentDetails, JobEvent, ProjectConfig, StrategyConfig, WorkspacePanel, WorkspaceState, WorkspaceWindow } from "../../../../../packages/contracts/src/research";
import { ResearchContext, request, useResearch, useResearchState, jobTitle } from "./state";
import { DataPanel, FactorPanel, UniversePanel } from "./ResearchPanels";
import { ModelPanel, StrategyHome, StrategyPanel } from "./RunPanels";
import { ResultsPanel } from "./ResultsPanel";
import { TodayPanel, MarketPanel, StockPanel, GlobalSelection, DataCenter, ComparePanel } from "./WorkspacePanels";
import { PositionsEditor } from "./SelectionPanel";
import { SimulationPanel } from "./SimulationPanel";
import { ReportsPanel, ReportReader } from "./ReportsPanel";
import { ReproductionPanel } from "./ReproductionPanel";
import { QuotePanel } from "./QuotePanel";
import { PreparationRecords } from "./ExperimentContext";
import { CandidatePanel } from "./CandidatePanel";
import { ScreenerPanel } from "./ScreenerPanel";
import { defaultShortcuts, matchesShortcut, shortcutTargetBlocked } from "./shortcuts";
import { orderedNavigation } from "./navigation";
import { CommandStockSearch } from './CommandStockSearch';
import { LocalCommand } from './LocalCommand';
import { SettingsDialog } from "./SettingsDialog";
import { ConversationPanel } from "./ConversationPanel";
import { Empty, Field, requestText, TextPromptHost } from "./ui";
import { ObjectScope, WorkspaceContext, useWorkspace, flushDrafts } from "./workspace";
import { WindowControls } from "../components/WindowControls";
const defaults: WorkspaceState = { sidebarVisible: true, aiVisible: true, rightPanel: "ai", theme: "light", density: "comfortable", sidebarWidth: 210, aiWidth: 330, windows: [], presets: {} };
const panels = { research: ({ params }: IDockviewPanelProps<WorkspacePanel>) => <ObjectScope panel={params}><Panel panel={params} /></ObjectScope> };
function Panel({ panel }: { panel: WorkspacePanel }) {
  const w = useWorkspace(); const s = useResearch(); const saveRef = useRef<(() => Promise<void>) | null>(null);
  let content: React.ReactNode;
  switch (panel.kind) {
    case "reports": content=<ReportsPanel/>;break;
    case "report": content=<ReportReader panel={panel}/>;break;
    case "reproduction": content=<ReproductionPanel panel={panel}/>;break;
    case "quote": content=<QuotePanel panel={panel}/>;break;
    case "candidate": content=<CandidatePanel panel={panel}/>;break;
    case "simulation": content=<SimulationPanel panel={panel}/>;break;
    case "today": content = <ResearchStart projectId={panel.projectId} />; break;
    case "market": content = <MarketPanel screening={false} />; break;
    case "screener": content = <ScreenerPanel />; break;
    case "stock": content = <StockPanel panel={panel} />; break;
    case "selection": content = <GlobalSelection />; break;
    case "positions": content = <div className="r-page"><h1>实际持仓</h1><p className="r-note">全局实际账户。选股清单不会修改这里的持仓。</p><PositionsEditor saveRef={saveRef} defaultExpanded /></div>; break;
    case "data": content = panel.projectId ? <DataPanel key={s.configurationVersions.data ?? 0} /> : <DataCenter />; break;
    case "compare": content = <ComparePanel refs={panel.experimentRefs ?? []} panelId={panel.id} />; break;
    case "experiment": content = <ResultsPanel />; break;
    case "universe": content = <UniversePanel key={s.configurationVersions.universe ?? 0} />; break;
    case "factors": content = <FactorPanel key={s.configurationVersions.factors ?? 0} />; break;
    case "model": content = <ModelPanel key={s.configurationVersions.model ?? 0} />; break;
    case "strategy": content = panel.view === "backtest" || panel.view === "optimize" ? <StrategyPanel key={s.configurationVersions.strategy ?? 0} run optimize={panel.view === "optimize"} /> : <StrategyHome panel={panel} />; break;
  }
  const strategy = w.strategies.find(x => x.id === panel.strategyId && x.projectId === panel.projectId);
  return <div className="r-object-panel" style={{ containerType: "inline-size", containerName: "object" }}>{strategy && !["experiment","candidate","simulation"].includes(panel.kind) && <div className="r-objectbar r-objectbar-compact">
    <strong title={strategy.name}>{strategy.name}</strong><span className="r-draft-status">草稿自动保存</span>
    <details className="r-object-menu"><summary>策略操作</summary><div>
      <button onClick={() => void s.act(async () => { await flushDrafts(); await request("strategies.activate", { projectId: strategy.projectId, strategyId: strategy.id, enabled: true, allocation: strategy.allocation }); await w.reload(); s.setNotice("当前已保存草稿已应用到每日选股"); })}>应用到每日选股</button>
      <button onClick={() => w.open({ kind: "universe", title: `${strategy.name} · 股票池`, projectId: strategy.projectId, strategyId: strategy.id })}>编辑股票池</button>
      <button onClick={() => void s.act(async () => { const name = await requestText("策略名称", strategy.name); if (name?.trim()) { await flushDrafts(); await request("strategies.save", { projectId: strategy.projectId, strategy: { id: strategy.id, name: name.trim() } }); await w.reload(); } })}>重命名策略</button>
      <button className="r-danger" onClick={()=>void s.act(async()=>{if(!window.confirm(`删除策略“${strategy.name}”？实验记录仍保留。`))return;await flushDrafts();await request("strategies.delete",{projectId:strategy.projectId,strategyId:strategy.id});await w.reload();})}>删除策略</button>
      {strategy.enabled && <button onClick={() => void s.act(async () => { await request("strategies.activate", { projectId: strategy.projectId, strategyId: strategy.id, enabled: false }); await w.reload(); })}>停用每日选股</button>}
    </div></details>
  </div>}{panel.projectId&&!["today","simulation","candidate"].includes(panel.kind)&&<nav className="r-module-nav" aria-label="研究模块"><details className="r-module-picker"><summary>研究入口</summary><div>{([['data','数据'],['universe','股票池'],['factors','因子'],['model','模型'],['strategy','策略'],['experiment','实验'],['quote','行情']] as const).map(([kind,title])=><button key={kind} className={panel.kind===kind?'active':''} onClick={()=>void s.act(async()=>{await flushDrafts();w.open({kind,title,projectId:panel.projectId,strategyId:panel.strategyId,experimentId:panel.experimentId,date:panel.date,symbol:panel.symbol,factorId:panel.factorId,modelWindowId:panel.modelWindowId,...(kind==='quote'&&panel.symbol?{instrument:panel.instrument??{kind:'stock' as const,symbol:panel.symbol}}:{})});})}>{title}</button>)}</div></details><span>{s.project?.name}{panel.strategyId?` · ${strategy?.name??"策略"}`:" · 项目"}</span><small>{s.project?.startDate||"开始日期未设置"} — {s.project?.endDate||"结束日期未设置"}</small></nav>}{content}</div>;
}
function StrategyTree({strategy}:{strategy:StrategyConfig;defaultExpanded:boolean}) {
 const w=useWorkspace();
 const active=w.active?.projectId===strategy.projectId&&w.active?.strategyId===strategy.id;
 return <button className={`r-strategy-item ${active?'active':''}`} title={strategy.enabled?'已启用每日选股':'研究草稿'} onClick={()=>w.open({kind:'strategy',title:strategy.name,projectId:strategy.projectId,strategyId:strategy.id})}><span className={`r-status-dot ${strategy.enabled?'enabled':''}`}/><span>{strategy.name}</span></button>;
}
export function ResearchApp() { const state = useResearchState(); return <ResearchContext.Provider value={state}><Shell /></ResearchContext.Provider>; }
function Shell() {
  const s = useResearch(); const latest = useRef(s); latest.current = s;
  useEffect(() => {
    const timers = new Map<HTMLElement, ReturnType<typeof setTimeout>>();
    const revealScroll = (event: Event) => {
      const node = event.target;
      if (!(node instanceof HTMLElement) || !node.closest(".r-app")) return;
      clearTimeout(timers.get(node)); node.dataset.scrollActive = "true";
      timers.set(node, setTimeout(() => { delete node.dataset.scrollActive; timers.delete(node); }, 900));
    };
    document.addEventListener("scroll", revealScroll, true);
    const closeMenus = (event: Event) => {
      document.querySelectorAll<HTMLDetailsElement>(".r-conversation-menu[open], .r-project-actions[open], .r-replay-menu[open], .r-chart-menu[open]").forEach(menu => {
        if (event instanceof KeyboardEvent ? event.key === "Escape" : event.target instanceof Node && !menu.contains(event.target)) menu.open = false;
      });
    };
    document.addEventListener("pointerdown", closeMenus);
    document.addEventListener("keydown", closeMenus);
    return () => { document.removeEventListener("scroll", revealScroll, true); document.removeEventListener("pointerdown", closeMenus); document.removeEventListener("keydown", closeMenus); for (const [node, timer] of timers) { clearTimeout(timer); delete node.dataset.scrollActive; } };
  }, []);
  const [toolSearch, setToolSearch] = useState<string | null>(null);
  const [creating, setCreating] = useState(false); const [settings, setSettings] = useState(false); const [settingsSection,setSettingsSection]=useState<"appearance"|"ai">("appearance");
  const [systemDark,setSystemDark]=useState(()=>window.matchMedia("(prefers-color-scheme: dark)").matches);
  const [preferences, setPreferences] = useState(defaults); const prefRef = useRef(preferences); prefRef.current = preferences;
  const [windowInfo, setWindowInfo] = useState<{ id: string; main: boolean; state?: WorkspaceWindow } | null>(null);
  const infoRef = useRef(windowInfo); infoRef.current = windowInfo;
  const [strategies, setStrategies] = useState<StrategyConfig[]>([]); const [active, setActive] = useState<WorkspacePanel>(); const [compactViewport, setCompactViewport] = useState(() => window.innerWidth <= 760); const [compactOverlay, setCompactOverlay] = useState<"sidebar" | "ai">("ai"); const [groupCount, setGroupCount] = useState(1);
  const activeRef=useRef(active);activeRef.current=active;
  const [panelTransitioning,setPanelTransitioning]=useState(false);
  const panelTransitionTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  useEffect(()=>()=>{if(panelTransitionTimer.current)clearTimeout(panelTransitionTimer.current);},[]);
  useEffect(()=>{const stop=()=>{if(panelTransitionTimer.current)clearTimeout(panelTransitionTimer.current);panelTransitionTimer.current=null;setPanelTransitioning(false);};window.addEventListener("resize",stop);return()=>window.removeEventListener("resize",stop);},[]);
  const [projectDisplay,setProjectDisplay]=useState<{id:string;overrides:Partial<WorkspaceState>}|null>(null),[displayRevision,setDisplayRevision]=useState(0),[viewDisplay,setViewDisplay]=useState<Record<string,Partial<WorkspaceState>>>({});
  const displayPreferences={...preferences,...(projectDisplay?.id===active?.projectId?projectDisplay?.overrides:{}),...(active?.id?viewDisplay[active.id]:{})};const displayRef=useRef(displayPreferences);displayRef.current=displayPreferences;const activeRightPanel=(displayPreferences.rightPanel??"ai") ;const savedSidebarVisible=displayPreferences.sidebarVisible!==false,savedRightVisible=displayPreferences.aiVisible!==false;const sidebarExpanded=savedSidebarVisible&&(!compactViewport||!savedRightVisible||compactOverlay==="sidebar");const rightExpanded=savedRightVisible&&(!compactViewport||!savedSidebarVisible||compactOverlay==="ai");useEffect(()=>{const updateCompactViewport=()=>setCompactViewport(window.innerWidth<=760);window.addEventListener("resize",updateCompactViewport);return()=>window.removeEventListener("resize",updateCompactViewport);},[]);
  useEffect(()=>{let alive=true;const projectId=active?.projectId;setProjectDisplay(null);if(projectId)void request<{overrides:Partial<WorkspaceState>}>('workspace.project.get',{projectId}).then(value=>{if(alive&&activeRef.current?.projectId===projectId)setProjectDisplay({id:projectId,overrides:value.overrides});}).catch(e=>{if(alive)latest.current.setError(String(e));});return()=>{alive=false;};},[active?.projectId,displayRevision]);
  useEffect(()=>{const changed=()=>setDisplayRevision(value=>value+1),clear=()=>{const id=activeRef.current?.id;if(id)setViewDisplay(values=>{const next={...values};delete next[id];return next;});};window.addEventListener('v3-project-display-changed',changed);window.addEventListener('v3-clear-view-display',clear);const off=window.v3Research?.workspace?.onChanged(event=>{if(event.method==='workspace.project.preferences')changed();});return()=>{window.removeEventListener('v3-project-display-changed',changed);window.removeEventListener('v3-clear-view-display',clear);off?.();};},[]);
  const dockContainer=useRef<HTMLDivElement>(null),dockResize=useRef<ResizeObserver|null>(null);
  useEffect(()=>()=>dockResize.current?.disconnect(),[]);
  const api = useRef<DockviewApi | null>(null); const timer = useRef<ReturnType<typeof setTimeout> | null>(null); const restoring = useRef(false); const dockReady = useRef(false);
  const cancelSave = () => { if (timer.current) clearTimeout(timer.current); timer.current = null; };
  const reload = async () => { setStrategies(await request<StrategyConfig[]>("strategies.list")); await latest.current.refreshProjects(); };
  async function saveGlobalPreferences(patch: Partial<WorkspaceState>) { const next = { ...prefRef.current, ...patch }; prefRef.current = next; setPreferences(next); await request("workspace.save", { state: patch }); window.v3Research?.workspace?.broadcast({ method: "workspace.preferences" }); }
  async function savePreferences(patch:Partial<WorkspaceState>){const panel=activeRef.current;if(!panel?.projectId)return saveGlobalPreferences(patch);const displayKeys=['density','readingFontSize','sidebarWidth','aiWidth','sidebarVisible','aiVisible','rightPanel'];const local=Object.fromEntries(Object.entries(patch).filter(([key])=>displayKeys.includes(key))),global=Object.fromEntries(Object.entries(patch).filter(([key])=>!displayKeys.includes(key)));if(Object.keys(local).length)setViewDisplay(values=>({...values,[panel.id]:{...values[panel.id],...local}}));if(Object.keys(global).length)await saveGlobalPreferences(global);}
   function beginPanelTransition(){if(panelTransitionTimer.current)clearTimeout(panelTransitionTimer.current);setPanelTransitioning(true);panelTransitionTimer.current=setTimeout(()=>{panelTransitionTimer.current=null;setPanelTransitioning(false);},180);}
   function endPanelTransition(){if(panelTransitionTimer.current)clearTimeout(panelTransitionTimer.current);panelTransitionTimer.current=null;setPanelTransitioning(false);}
   function togglePanel(kind:"sidebar"|"ai"){beginPanelTransition();const expanded=kind==="sidebar"?sidebarExpanded:rightExpanded,visible=kind==="sidebar"?savedSidebarVisible:savedRightVisible;if(compactViewport&&!expanded){setCompactOverlay(kind);if(!visible)void s.act(()=>savePreferences(kind==="sidebar"?{sidebarVisible:true}:{aiVisible:true}));return;}void s.act(()=>savePreferences(kind==="sidebar"?{sidebarVisible:!expanded}:{aiVisible:!expanded}));}
   const togglePanelRef=useRef(togglePanel);togglePanelRef.current=togglePanel;
   function selectRightPanel(panel:NonNullable<WorkspaceState["rightPanel"]>){void s.act(()=>savePreferences({rightPanel:panel}));}
   function openJobsPanel(){if(compactViewport)setCompactOverlay("ai");void s.act(()=>savePreferences({rightPanel:"jobs",aiVisible:true}));}

  async function openProjectDirectory() {
    const path = await window.v3Research?.chooseDirectory();
    if (!path) return;
    await s.open(path);
    const projects = await request<ProjectConfig[]>("projects.list");
    const reopened = projects.find(p => p.path.replace(/\\/g,"/").toLowerCase() === path.replace(/\\/g,"/").toLowerCase());
    if (reopened) { await savePreferences({ closedProjectIds: (prefRef.current.closedProjectIds ?? []).filter(id => id !== reopened.id) }); open({ kind: "today", projectId: reopened.id, title: reopened.name }); }
    await reload();
  }
  function snapshot(): WorkspaceWindow { const info = infoRef.current!; return { ...info.state, id: info.id, main: info.main, dock: JSON.parse(JSON.stringify(api.current!.toJSON())), panels: api.current!.panels.map(p => p.params as WorkspacePanel), activePanelId: api.current!.activePanel?.id }; }
  async function persistNow() { if (!api.current || !infoRef.current || restoring.current) return; cancelSave(); const state = snapshot(); if (window.v3Research?.workspace) await window.v3Research.workspace.update(state); else await request("workspace.save", { state: { windows: [state] } }); }
  function persist() { if (restoring.current) return; cancelSave(); timer.current = setTimeout(() => void latest.current.act(persistNow), 450); }
  function open(panel: Omit<WorkspacePanel, "id"> & { id?: string }, split?: "right" | "below") {
    const dock = api.current; if (!dock) return;
    let id = panel.id ?? [panel.kind, panel.projectId, panel.strategyId, panel.view, panel.experimentId, panel.candidateId, panel.accountId, panel.reportId, panel.reproductionId, panel.symbol, panel.instrument?.kind, panel.instrument?.symbol, panel.kind === "compare" ? crypto.randomUUID() : ""].filter(Boolean).join(":");
    const existing = dock.getPanel(id);
    if(existing && panel.kind === "quote" && !panel.instrument && !panel.id) { existing.api.setActive(); return; }
    if (!panel.id && panel.kind === "experiment") {
      const matching = dock.panels.find(p => p.params?.kind === "experiment" && p.params.projectId === panel.projectId && p.params.strategyId === panel.strategyId && p.params.experimentId === panel.experimentId);
      if (matching) { matching.api.updateParameters({ ...matching.params, ...panel, id: matching.id }); matching.api.setActive(); return; }
      if (existing) id = `${id}:${crypto.randomUUID()}`;
    } else if (existing) { existing.api.updateParameters({ ...existing.params, ...panel, id }); existing.api.setActive(); return; }
    dock.addPanel({ id, component: "research", title: panel.title, params: { ...panel, id }, ...(split && dock.activePanel ? { position: { referencePanel: dock.activePanel.id, direction: split } } : {}) });
  }
  function restore(state?: WorkspaceWindow) {
    if (!api.current) return; restoring.current = true; cancelSave(); api.current.clear();
    let restored = false;
    if (state?.dock) try { api.current.fromJSON(state.dock as unknown as ReturnType<DockviewApi["toJSON"]>); restored = true; } catch { latest.current.setNotice("保存的分屏布局无法读取，已按工作对象恢复。"); }
    if (!restored) for (const panel of state?.panels ?? []) open(panel);
    if (!api.current.panels.length && infoRef.current?.main) open({ kind: "today", title: "研究首页" });
    if (state?.activePanelId) api.current.getPanel(state.activePanelId)?.api.setActive();const container=dockContainer.current;if(container?.clientWidth&&container.clientHeight)requestAnimationFrame(()=>api.current?.layout(container.clientWidth,container.clientHeight,true)); restoring.current = false;
  }
  useEffect(() => { let alive = true; void s.act(async () => {
    const [saved, info] = await Promise.all([request<WorkspaceState>("workspace.get"), window.v3Research?.workspace?.current() ?? Promise.resolve<{ id: string; main: boolean; state?: WorkspaceWindow }>({ id: "main", main: true })]);
    if (!alive) return; const next: WorkspaceState = { ...defaults, ...saved, windows: [] }; prefRef.current = next; setPreferences(next); const current = { ...info, state: info.state }; infoRef.current = current; setWindowInfo(current); await reload();
  }); return () => { alive = false; cancelSave(); }; }, []);
  const effectiveTheme=preferences.theme==="system"?(systemDark?"dark":"light"):preferences.theme;
  useEffect(()=>{const media=window.matchMedia("(prefers-color-scheme: dark)");const changed=()=>setSystemDark(media.matches);media.addEventListener("change",changed);return()=>media.removeEventListener("change",changed);},[]);
  useEffect(() => { document.documentElement.dataset.theme = effectiveTheme; document.documentElement.dataset.density = displayPreferences.density; document.documentElement.style.setProperty("--r-reading-font",`${displayPreferences.readingFontSize??14}px`); }, [effectiveTheme, displayPreferences.density,displayPreferences.readingFontSize]);
  useEffect(()=>{void latest.current.act(()=>request("display.setZoom",{factor:preferences.zoomFactor??1}));},[preferences.zoomFactor]);
  useEffect(()=>{const resize=()=>requestAnimationFrame(()=>{const node=dockContainer.current;if(node?.clientWidth&&node.clientHeight)api.current?.layout(node.clientWidth,node.clientHeight,true);});resize();window.addEventListener("resize",resize);return()=>window.removeEventListener("resize",resize);},[preferences.zoomFactor,windowInfo?.id]);
  useEffect(() => { const bridge = window.v3Research?.workspace; if (!bridge) return;
    const offPanels = bridge.onPanels(incoming => { cancelSave(); for (const panel of incoming) open(panel); void latest.current.act(persistNow); });
    const offChanged = bridge.onChanged(change => { if (change.method === "workspace.layout") void latest.current.act(async () => { const info = await bridge.current(); infoRef.current = info; setWindowInfo(info); restore(info.state); }); else if (change.method === "workspace.preferences") void latest.current.act(async () => { const next = await request<WorkspaceState>("workspace.get"); prefRef.current = { ...defaults, ...next, activeConversationId: prefRef.current.activeConversationId }; setPreferences(prefRef.current); }); else if (change.method === "stock.link") { const symbol = String(change.params?.symbol ?? ""); if (symbol) window.dispatchEvent(new CustomEvent("v3-stock-link", { detail: symbol })); } else if(change.method==="app.updateAvailable")latest.current.setNotice(`发现新版本 ${String(change.params?.latestVersion??"")}，可在设置的通用页查看发布信息。`); else if (/^(strategies|projects|candidates|history\.memberships\.apply)/.test(change.method)) void latest.current.act(reload); });
    return () => { offPanels(); offChanged(); };
  }, []);
  useEffect(()=>{const refresh=()=>void latest.current.act(async()=>{const next=await request<WorkspaceState>("workspace.get");prefRef.current={...defaults,...next,activeConversationId:prefRef.current.activeConversationId};setPreferences(prefRef.current);window.v3Research?.workspace?.broadcast({method:"workspace.preferences"});});window.addEventListener("v3-workspace-preferences-refresh",refresh);return()=>window.removeEventListener("v3-workspace-preferences-refresh",refresh);},[]);
  function ready(event: DockviewReadyEvent) { api.current = event.api;dockResize.current?.disconnect();const resizeDock=()=>{const node=dockContainer.current;if(node&&node.clientWidth&&node.clientHeight)api.current?.layout(node.clientWidth,node.clientHeight,true);};dockResize.current=new ResizeObserver(resizeDock);if(dockContainer.current)dockResize.current.observe(dockContainer.current);requestAnimationFrame(resizeDock); dockReady.current = true; restore(infoRef.current?.state); setActive(event.api.activePanel?.params as WorkspacePanel | undefined); setGroupCount(event.api.groups.length); event.api.onDidLayoutChange(() => { setGroupCount(event.api.groups.length); persist(); }); event.api.onDidActivePanelChange(e => setActive(e.panel?.params as WorkspacePanel | undefined));
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
  function layoutPreference():NonNullable<WorkspaceState["layoutPresets"]>[string] {
    const groups=api.current?.groups??[],rectangles=groups.map(group=>group.element.getBoundingClientRect());
    const layout=groups.length<2?"single":Math.abs(rectangles[1].top-rectangles[0].top)>Math.abs(rectangles[1].left-rectangles[0].left)?"rows":"columns";
    const p=displayRef.current;return {sidebarVisible:p.sidebarVisible,aiVisible:p.aiVisible,sidebarWidth:p.sidebarWidth,aiWidth:p.aiWidth,density:p.density,rightPanel:p.rightPanel,layout};
  }
  async function preset(name: string) {
    const builtins:Record<string,NonNullable<WorkspaceState["layoutPresets"]>[string]>={研究:{layout:"single",sidebarVisible:true,aiVisible:true},比较:{layout:"columns",sidebarVisible:false,aiVisible:false},市场:{layout:"columns",sidebarVisible:false,aiVisible:false},选股:{layout:"rows",sidebarVisible:true,aiVisible:false}};
    const preference=prefRef.current.layoutPresets?.[name]??builtins[name];if(!preference)return;
    const {layout,...display}=preference;await flushDrafts();await savePreferences(display);
    const dock=api.current;if(!dock||!dock.panels.length)return;const activePanel=dock.activePanel??dock.panels[0],panels=[...dock.panels],group=activePanel.group;
    if(dock.hasMaximizedGroup())dock.exitMaximizedGroup();for(const panel of panels)if(panel.group!==group)panel.api.moveTo({group});
    if(layout&&layout!=="single"&&panels.length>1){const second=dock.addGroup({referenceGroup:group,direction:layout==="rows"?"below":"right"});for(const panel of panels.slice(Math.ceil(panels.length/2)))panel.api.moveTo({group:second});}
    activePanel.api.setActive();await persistNow();s.setNotice("已应用显示布局，现有研究标签保留。");
  }
  useEffect(()=>{const apply=(event:Event)=>void latest.current.act(()=>preset(String((event as CustomEvent).detail)));const save=()=>void latest.current.act(async()=>{const name=await requestText("保存显示布局名称");if(name?.trim())await savePreferences({layoutPresets:{...prefRef.current.layoutPresets,[name.trim()]:layoutPreference()}});});window.addEventListener("v3-apply-layout",apply);window.addEventListener("v3-save-layout",save);return()=>{window.removeEventListener("v3-apply-layout",apply);window.removeEventListener("v3-save-layout",save);};},[]);
  const resize = (kind: "sidebarWidth" | "aiWidth", e: React.PointerEvent<HTMLDivElement>) => { endPanelTransition(); const element = e.currentTarget; element.setPointerCapture(e.pointerId); const x = e.clientX, initial = displayRef.current[kind];let finalValue=initial; element.onpointermove = v => { const value = Math.max(kind === "aiWidth" ? 280 : 170, Math.min(kind === "aiWidth" ? 700 : 380, initial + (kind === "aiWidth" ? x - v.clientX : v.clientX - x))); finalValue=value;if(activeRef.current?.projectId){const id=activeRef.current.id;setViewDisplay(values=>({...values,[id]:{...values[id],[kind]:value}}));}else { prefRef.current = { ...prefRef.current, [kind]: value }; setPreferences(prefRef.current); } }; element.onpointerup = () => { element.onpointermove = null; element.onpointerup = null; void s.act(() => savePreferences({ [kind]: finalValue })); }; };

  useEffect(()=>{const openSettings=(event:Event)=>{setSettingsSection((event as CustomEvent).detail?.section==="ai"?"ai":"appearance");setSettings(true);};const key=(event:KeyboardEvent)=>{if(shortcutTargetBlocked(event))return;const keys={...defaultShortcuts,...prefRef.current.shortcuts};if(matchesShortcut(event,keys.settings)){event.preventDefault();setSettingsSection("appearance");setSettings(true);}else if(matchesShortcut(event,keys.commandSearch)){event.preventDefault();setToolSearch("");}else if(matchesShortcut(event,keys.sidebar)){event.preventDefault();togglePanelRef.current("sidebar");}else if(matchesShortcut(event,keys.assistant)){event.preventDefault();togglePanelRef.current("ai");}};window.addEventListener("v3-open-settings",openSettings);document.addEventListener("keydown",key);return()=>{window.removeEventListener("v3-open-settings",openSettings);document.removeEventListener("keydown",key);};},[]);
  const activeJobs = s.jobs.filter(j => ["queued", "running"].includes(j.status));
  return <WorkspaceContext.Provider value={{ createProject: () => setCreating(true), openProjectDirectory, open, updatePanel: (id, patch) => { const panel = api.current?.getPanel(id); if (panel) { panel.api.updateParameters({ ...panel.params, ...patch }); if (patch.title) panel.api.setTitle(patch.title); if (api.current?.activePanel?.id === id) setActive(panel.params as WorkspacePanel); persist(); } }, strategies, reload, active, preferences:displayPreferences, globalPreferences:preferences, saveGlobalPreferences, savePreferences, linkStock }}><div className="r-app" data-testid="research-app" style={{ "--r-sidebar": `${displayPreferences.sidebarWidth}px`, "--r-ai": `${displayPreferences.aiWidth}px` } as React.CSSProperties}>
    <header className="r-titlebar"><div className="r-brand"><strong>V3</strong><span>研究工作台</span></div>{windowInfo?.main && <div className="r-panel-toggles" role="group" aria-label="研究目录"><button type="button" className="r-panel-toggle" title={sidebarExpanded ? "收起研究目录" : "展开研究目录"} aria-label={sidebarExpanded ? "收起研究目录" : "展开研究目录"} aria-controls="r-sidebar-region" aria-expanded={sidebarExpanded} onClick={() => togglePanel("sidebar")}><svg className="r-panel-toggle-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><rect x="2.5" y="3" width="15" height="14" rx="1.5"/><path d="M8 3.5v13M4.5 6.3h1.5M4.5 9.5h1.5M4.5 12.7h1.5"/></svg></button></div>}<span className="r-project-title">{windowInfo?.main ? "本地研究 · A 股日线" : "独立工作窗口"}</span><div className="r-title-actions">{windowInfo?.main && <button type="button" className="r-panel-toggle" title={rightExpanded ? "收起共享右栏" : "展开共享右栏"} aria-label={rightExpanded ? "收起共享右栏" : "展开共享右栏"} aria-controls="r-right-region" aria-expanded={rightExpanded} onClick={() => togglePanel("ai")}><svg className="r-panel-toggle-icon is-mirrored" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><rect x="2.5" y="3" width="15" height="14" rx="1.5"/><path d="M8 3.5v13M4.5 6.3h1.5M4.5 9.5h1.5M4.5 12.7h1.5"/></svg></button>}<button onClick={() => void s.act(() => savePreferences({ theme: effectiveTheme === "light" ? "dark" : "light" }))}>{effectiveTheme === "light" ? "深色" : "浅色"}</button><button onClick={() => void s.act(() => savePreferences({ density: displayPreferences.density === "compact" ? "comfortable" : "compact" }))}>{displayPreferences.density === "compact" ? "标准行高" : "密集行高"}</button>{window.v3Research?.desktop && <WindowControls />}</div></header>
    {s.error && <div className="r-banner error" role="alert"><span>{s.error}</span><button onClick={() => s.setError("")} aria-label="关闭错误">×</button></div>}{s.notice && <div className="r-banner" role="status"><span>{s.notice}</span><button onClick={() => s.setNotice("")} aria-label="关闭提示">×</button></div>}
    <div className="r-body">{windowInfo?.main && <div id="r-sidebar-region" className={"r-sidebar-region" + (panelTransitioning ? " is-transitioning" : "")} data-expanded={sidebarExpanded} aria-hidden={!sidebarExpanded} inert={!sidebarExpanded}><aside className="r-sidebar"><nav aria-label="全局导航">{orderedNavigation(preferences.navigation).filter(([kind])=>!preferences.navigation?.hidden?.includes(kind)).map(([kind,title]) => <button key={kind} className={active?.kind === kind ? "active" : ""} onClick={() => open({ kind, title })}>{title}</button>)}</nav><hr /><div className="r-toolbar"><h2>研究项目</h2><button aria-label="新建项目" onClick={() => setCreating(true)}>＋</button></div><div className="r-project-tree">{!s.projects.length&&<div className="r-research-empty"><p>因子研究、策略回测、模型训练与参数寻优保存在研究项目中。</p><button onClick={()=>setCreating(true)}>创建研究项目</button><p>已有项目？使用下方“打开项目文件夹”继续研究和查看实验。</p></div>}{s.projects.filter(p => !preferences.closedProjectIds?.includes(p.id)).map(p => <details key={p.id} className="r-project-group" open><summary onClick={e=>{e.preventDefault();open({kind:"today",projectId:p.id,title:p.name});}}>{p.name}</summary><details className="r-project-actions" onClick={e=>{if((e.target as HTMLElement).closest("button"))e.currentTarget.open=false;}}><summary aria-label={`${p.name} 项目管理`} title="项目管理">⋯</summary><div><button onClick={() => void s.act(async () => { const name = await requestText("项目名称", p.name); if (name) { await request("projects.save", {project:{...p,name}}); await reload(); } })}>重命名</button><button onClick={() => void s.act(() => savePreferences({closedProjectIds:[...(preferences.closedProjectIds??[]),p.id]}))}>关闭项目</button></div></details>{strategies.filter(st => st.projectId === p.id).map(st => <StrategyTree key={`${st.projectId}:${st.id}`} strategy={st} defaultExpanded={active?.strategyId?active.strategyId===st.id&&active.projectId===st.projectId:strategies[0]?.id===st.id&&strategies[0]?.projectId===st.projectId}/>)}{!strategies.some(st=>st.projectId===p.id)&&<button onClick={()=>open({kind:"strategy",projectId:p.id,title:`${p.name} · 研究`})}>打开研究</button>}<button className="r-muted" onClick={() => void s.act(async () => { const name = await requestText("新策略名称"); if (!name?.trim()) return; const st = await request<StrategyConfig>("strategies.create", { projectId: p.id, name: name.trim() }); await reload(); open({ kind: "strategy", title: st.name, projectId: p.id, strategyId: st.id }); })}>＋ 新策略</button><button onClick={() => open({ kind: "data", projectId: p.id, title: `${p.name} · 数据` })}>项目数据</button></details>)}</div><button className="r-sidebar-action" onClick={() => void s.act(openProjectDirectory)}>打开项目文件夹</button><div className="r-sidebar-foot"><button onClick={() => { setSettingsSection("appearance");setSettings(true); }}>设置</button><small>数据与实验保存在本地</small></div></aside><div className="r-resize" role="separator" aria-label="调整导航宽度" aria-orientation="vertical" aria-valuemin={170} aria-valuemax={380} aria-valuenow={displayPreferences.sidebarWidth} onPointerDown={e => resize("sidebarWidth", e)} /></div>}
    <main className="r-main"><div className="r-workspace-toolbar"><button onClick={() => setToolSearch("")}>⌕ 打开工具</button>{groupCount > 1 && <button className="r-primary" title="保留所有标签，合并为一个宽工作区" onClick={() => void s.act(singleWorkspace)}>合并分屏</button>}<details className="r-layout-menu"><summary>布局</summary><div className="r-toolbar"><select aria-label="切换工作区预设" value="" onChange={e => void s.act(() => preset(e.target.value))}><option value="" disabled>工作区布局</option>{[...new Set(["研究","比较","市场","选股",...Object.keys(preferences.layoutPresets??{})])].map(name => <option key={name}>{name}</option>)}</select><button onClick={() => void s.act(async () => { const name = await requestText("保存工作区名称"); if (!name?.trim()) return; await savePreferences({layoutPresets:{...prefRef.current.layoutPresets,[name.trim()]:layoutPreference()}});s.setNotice("布局偏好已保存，不包含具体研究对象。"); })}>保存布局</button></div></details><span className="r-spacer" /><button disabled={!active} title="复制当前对象并在右侧分屏" onClick={() => active && open({ ...active, id: crypto.randomUUID() }, "right")}>分屏</button><button disabled={!active || !window.v3Research?.workspace} title="将当前标签拖出为独立 Windows 窗口，可移至第二屏" onClick={() => void s.act(() => detach())}>新窗口 ↗</button>{windowInfo && !windowInfo.main && <button onClick={() => void s.act(attach)}>全部移回主窗口</button>}</div><div className="r-dock" ref={dockContainer}>{windowInfo ? <DockviewReact className={`dockview-theme-${effectiveTheme}`} components={panels} onReady={ready} /> : <Empty title="正在打开研究首页…" />}</div></main>
    {windowInfo?.main && <div id="r-right-region" className={"r-right-region" + (panelTransitioning ? " is-transitioning" : "")} data-expanded={rightExpanded} aria-hidden={!rightExpanded} inert={!rightExpanded}><div className="r-resize" role="separator" aria-label="调整右栏宽度" onPointerDown={e => resize("aiWidth", e)} /><div className="r-right-content"><nav className="r-right-tabs"><button className={activeRightPanel === "ai" ? "active" : ""} onClick={() => selectRightPanel("ai")}>研究助手</button><button className={activeRightPanel === "parameters" ? "active" : ""} disabled={!active?.projectId} onClick={() => selectRightPanel("parameters")}>完整参数</button><button className={activeRightPanel === "jobs" ? "active" : ""} onClick={() => selectRightPanel("jobs")}>任务</button></nav><div className="r-right-pane" hidden={activeRightPanel !== "ai"}><ConversationPanel /></div>{displayPreferences.rightPanel === "parameters" && <div className="r-right-pane">{active?.projectId ? <ObjectScope key={`${active.projectId}:${active.strategyId}:${active.kind}`} panel={active}><ParameterPane panel={active}/></ObjectScope> : <Empty title="先选择一个研究对象" />}</div>}<div className="r-right-pane" hidden={activeRightPanel !== "jobs"}><Jobs /></div></div></div>}</div>
    <footer className="r-taskbar">{windowInfo?.main ? <button className="r-task-summary" onClick={openJobsPanel} aria-label="打开任务详情" aria-controls="r-right-region" aria-expanded={rightExpanded && activeRightPanel === "jobs"}><strong>任务</strong><span>{activeJobs.length ? activeJobs.length + " 项进行中" : "无运行任务"}</span><span>打开任务 →</span></button> : <div className="r-task-summary r-task-summary-readonly" role="status"><strong>任务</strong><span>{activeJobs.length ? activeJobs.length + " 项进行中" : "无运行任务"}</span></div>}</footer><SettingsDialog open={settings} section={settingsSection} close={()=>setSettings(false)}/>{creating && <CreateProject close={() => { setCreating(false); void s.act(reload); }} />}</div>{toolSearch !== null && <ToolPicker search={toolSearch} setSearch={setToolSearch} close={() => setToolSearch(null)} />}<TextPromptHost /></WorkspaceContext.Provider>;
}

function ResearchStart({ projectId }: { projectId?: string }) {
  const s = useResearch(), w = useWorkspace();
  const project = s.projects.find(p => p.id === projectId);
  const [continuing, setContinuing] = useState(false);
  const [copying,setCopying]=useState(false);
  if (projectId) return <div className="r-page r-project-start"><p className="r-eyebrow">研究项目</p><h1>{project?.name ?? "项目研究"}</h1><p className="r-note">{project?.objective || "从研究假设开始，选择研究起点。"}</p><div className="r-start-actions"><button onClick={()=>w.open({kind:"factors",projectId,title:"因子探索"})}><strong>因子探索</strong><span>直接研究因子与分组表现</span></button><button onClick={() => void s.act(async () => { const name = await requestText("策略验证名称"); if (!name?.trim()) return; const strategy = await request<StrategyConfig>("strategies.create", { projectId, name: name.trim() }); await w.reload(); w.open({ kind: "strategy", projectId, strategyId: strategy.id, title: strategy.name }); })}><strong>策略验证</strong><span>建立策略草稿并验证</span></button><button onClick={()=>w.open({kind:"model",projectId,title:"模型训练"})}><strong>模型训练</strong><span>配置特征与时间切分</span></button><button aria-expanded={copying} onClick={()=>setCopying(v=>!v)}><strong>复制研究</strong><span>沿用已有策略配置和原区间</span></button></div>{copying&&<section><h2>选择已有项目或策略作为起点</h2><div className="r-start-projects">{s.projects.flatMap(source=>[{projectId:source.id,id:"",name:`${source.name} · 项目配置`,startDate:source.startDate,endDate:source.endDate},...w.strategies.filter(st=>st.projectId===source.id).map(st=>({projectId:source.id,id:st.id,name:`${source.name} · ${st.name}`,startDate:String(st.settings.startDate??source.startDate??""),endDate:String(st.settings.endDate??source.endDate??"")}))]).map(source=><button key={`${source.projectId}:${source.id}`} onClick={()=>void s.act(async()=>{const name=await requestText("复制后的研究名称",`${source.name} · 副本`);if(!name?.trim())return;await flushDrafts();const copied=await request<StrategyConfig>("strategies.create",{projectId,fromProjectId:source.projectId,fromStrategyId:source.id||undefined,name:name.trim()});await w.reload();w.open({kind:"strategy",projectId,strategyId:copied.id,title:copied.name});})}><strong>{source.name}</strong><span>原区间：{source.startDate||"未设置"} — {source.endDate||"未设置"}</span></button>)}</div><p className="r-note">复制配置与原研究区间，副本未启用；原项目和实验保留。</p></section>}<div className="r-toolbar"><button onClick={() => w.open({ kind: "data", projectId, title: "项目数据" })}>项目数据与研究区间</button><button onClick={()=>w.open({kind:"universe",projectId,title:"项目股票池"})}>股票池</button><button onClick={() => w.open({ kind: "experiment", projectId, title: "项目实验" })}>查看实验</button></div><h2>继续研究策略</h2><div className="r-start-projects">{w.strategies.filter(st => st.projectId === projectId).map(st => <button key={st.id} onClick={() => w.open({ kind: "strategy", projectId, strategyId: st.id, title: st.name })}><strong>{st.name}</strong><span>{st.enabled ? "每日选股已启用" : "研究草稿"}</span></button>)}</div></div>;
  return <div className="r-page r-research-start"><p className="r-eyebrow">V3 · A 股日线研究</p><h1>今天，从哪里开始？</h1><p className="r-note">查看行情，或带着一个问题进入研究。</p><div className="r-start-actions"><button className="r-primary" onClick={() => w.open({ kind: "quote", title: "查看行情" })}><strong>查看行情</strong><span>股票、指数与板块</span></button><button onClick={() => setContinuing(v => !v)}><strong>继续项目</strong><span>选择已有研究</span></button><button onClick={w.createProject}><strong>新建研究</strong><span>建立新的研究项目</span></button><button onClick={() => void s.act(w.openProjectDirectory)}><strong>打开项目</strong><span>从本地文件夹打开</span></button></div>{continuing && <section><h2>历史项目</h2><div className="r-start-projects">{s.projects.map(p => <button key={p.id} onClick={() => w.open({ kind: "today", projectId: p.id, title: p.name })}><strong>{p.name}</strong><span>{p.objective || p.path}</span></button>)}</div>{!s.projects.length && <p className="r-note">还没有历史项目。可以新建研究，或打开已有项目文件夹。</p>}</section>}</div>;
}
function CreateProject({ close }: { close: () => void }) {
  const w = useWorkspace(); const s = useResearch(); const [name, setName] = useState(""); const [path, setPath] = useState(""); const [objective, setObjective] = useState(""); const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null); useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="r-dialog" onCancel={close}><form onSubmit={e => { e.preventDefault(); setBusy(true); void s.act(async () => { const p = await request<ProjectConfig>("projects.create", { path, name: name.trim(), objective: objective.trim() }); await s.open(p.path); w.open({kind:"today",projectId:p.id,title:p.name}); close(); }).finally(() => setBusy(false)); }}><h2>新建研究项目</h2><p>项目文件、数据与实验保存在你选择的文件夹。</p><Field label="项目名称"><input required autoFocus value={name} onChange={e => setName(e.target.value)} /></Field><Field label="项目文件夹"><div className="r-toolbar"><input required value={path} onChange={e => setPath(e.target.value)} /><button type="button" onClick={() => void s.act(async () => { const chosen = await window.v3Research!.chooseDirectory(); if (chosen) setPath(chosen); })}>选择文件夹</button></div></Field><Field label="研究目标"><textarea rows={4} value={objective} onChange={e => setObjective(e.target.value)} placeholder="想验证怎样的投资假设？" /></Field><div className="r-toolbar"><button type="button" onClick={close}>取消</button><button className="r-primary" disabled={busy || !name.trim() || !path.trim()} type="submit">{busy ? "创建中…" : "创建项目"}</button></div></form></dialog>;
}
function Jobs() {
 const s=useResearch(),w=useWorkspace();const [status,setStatus]=useState(""),[projectId,setProjectId]=useState("");const [offset,setOffset]=useState(0),[history,setHistory]=useState<JobEvent[]>([]),[selected,setSelected]=useState<string[]>([]),[busy,setBusy]=useState(false);const limit=30;const [historyOpen,setHistoryOpen]=useState(false);const [allHistory,setAllHistory]=useState(false);
 const labels:Record<string,string>={queued:"排队中",running:"运行中",completed:"已完成",failed:"失败",cancelled:"已取消",interrupted:"已中断"};
 const ended=["completed","failed","cancelled","interrupted"];
 const reload=async()=>{const rows=await request<JobEvent[]>("jobs.list",{...(status?{status}:{statuses:ended}),...(projectId?{projectId}:{}),offset,limit,allHistory});setHistory(rows);setSelected([]);if(!rows.length&&offset>0)setOffset(Math.max(0,offset-limit));};
 useEffect(()=>{void s.act(reload);},[status,projectId,offset,allHistory,s.revision]);
 async function clear(all=false){setBusy(true);await s.act(async()=>{const result=await request<{removedIds:string[];skippedIds:string[]}>("jobs.clear",all?{statuses:status?[status]:ended,...(projectId?{projectId}:{})}:{jobIds:selected});await s.refresh();await reload();s.setNotice(`已清理 ${result.removedIds.length} 条任务记录${result.skippedIds.length?`，跳过 ${result.skippedIds.length} 条`:""}；实验结果保留。`);});setBusy(false);}
 const recover=async(jobId:string)=>{if(busy)return;setBusy(true);try{await s.act(async()=>{await request("jobs.recoverResult",{jobId});await s.refresh();await reload();s.setNotice("已恢复结果登记，未提交新的计算。");});}finally{setBusy(false);}};
 const render=(j:JobEvent)=><div className="r-job" key={j.id}>{ended.includes(j.status)&&<input disabled={j.registrationPending} type="checkbox" aria-label={`选择任务${j.name}`} checked={selected.includes(j.id)} onChange={()=>setSelected(v=>v.includes(j.id)?v.filter(id=>id!==j.id):[...v,j.id])}/>}<strong>{jobTitle(j.kind,j.name)}</strong><span>{labels[j.status]}</span>{j.status==='queued'&&<select aria-label={`${j.name}等待优先级`} value={String((j as JobEvent&{priority?:number}).priority??0)} onChange={event=>{const priority=Number(event.target.value);void s.act(async()=>{await request('jobs.priority',{jobId:j.id,priority});await s.refresh();});}}><option value={-1}>优先处理</option><option value={0}>正常</option><option value={1}>稍后</option>{![-1,0,1].includes((j as JobEvent&{priority?:number}).priority??0)&&<option value={(j as JobEvent&{priority?:number}).priority}>自定义优先级</option>}</select>}<progress max={1} value={Math.max(0,Math.min(1,j.progress))}/><span title={j.message}>{j.message}</span>{j.registrationPending?<button disabled={busy} onClick={()=>void recover(j.id)}>恢复结果登记</button>:!ended.includes(j.status)?<button onClick={()=>void s.act(async()=>{await request("jobs.cancel",{jobId:j.id});await s.refresh();})}>取消</button>:<button onClick={()=>void s.act(()=>request("jobs.submit",{spec:j.spec}))}>重跑</button>}{j.experimentId&&(j.resultAvailable===false?<span className="r-muted">实验已删除</span>:<button onClick={()=>w.open({kind:"experiment",title:jobTitle(j.kind,j.name),projectId:j.projectId,strategyId:j.strategyId,experimentId:j.experimentId})}>查看结果</button>)}{ended.includes(j.status)&&<button disabled={busy||j.registrationPending} onClick={()=>void s.act(async()=>{await request("jobs.clear",{jobIds:[j.id]});await s.refresh();await reload();})}>清理</button>}{j.preparation&&<PreparationRecords preparation={j.preparation} projectId={j.projectId} strategyId={j.strategyId}/>}</div>;
 const active=s.jobs.filter(j=>!ended.includes(j.status)&&(!projectId||j.projectId===projectId));
 return <div className="r-jobs">
    <div className="r-toolbar r-jobs-filters">
      <select aria-label="任务历史范围" value={allHistory?"all":"recent"} onChange={e=>{setAllHistory(e.target.value==="all");setOffset(0);}}><option value="recent">最近 30 天</option><option value="all">全部历史</option></select>
      <select aria-label="任务状态" value={status} onChange={e=>{setStatus(e.target.value);setOffset(0);}}><option value="">全部已结束</option>{ended.map(k=><option key={k} value={k}>{labels[k]}</option>)}</select>
      <select aria-label="任务项目" value={projectId} onChange={e=>{setProjectId(e.target.value);setOffset(0);}}><option value="">所有项目</option>{s.projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select>
    </div>
    {active.length>0&&<><h3>进行中</h3>{active.map(render)}</>}
    {(history.length>0||offset>0)&&<div className="r-toolbar r-jobs-pagination" role="group" aria-label="历史任务分页">
      <button disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-limit))}>上一页</button>
      <span>第 {Math.floor(offset/limit)+1} 页</span>
      <button disabled={history.length<limit} onClick={()=>setOffset(offset+limit)}>下一页</button>
    </div>}
    {history.length ? <details open={historyOpen} onToggle={event=>setHistoryOpen(event.currentTarget.open)}>
      <summary>历史记录 · {history.length} 条当前页</summary>{history.map(render)}
    </details> : <Empty title="此筛选下没有历史任务" />}
    <details className="r-jobs-management">
      <summary>管理历史</summary>
      <div className="r-jobs-management-actions">
        <button disabled={busy||!selected.length} onClick={()=>void clear()}>清理所选（{selected.length}）</button>
        <button disabled={busy||!history.length} onClick={()=>void clear(true)}>清理全部匹配历史（含 30 天前）</button>
      </div>
    </details>
  </div>;
}

function ToolPicker({search,setSearch,close}:{search:string;setSearch:(value:string)=>void;close:()=>void}) {
 const s=useResearch(),w=useWorkspace();const dialog=useRef<HTMLDialogElement>(null);
 const [target,setTarget]=useState(w.active?.projectId ? `${w.active.projectId}:${w.active.strategyId??""}` : "");
 useEffect(()=>{dialog.current?.showModal();},[]);
 const [projectId,strategyId]=target.split(":");
 const entries=[{kind:"reports",title:"研报库"},{kind:"reproduction",title:"研报复现",scoped:true},{kind:"quote",title:"查看行情"},{kind:"data",title:"项目数据",scoped:true},{kind:"universe",title:"股票池",scoped:true},{kind:"factors",title:"因子研究",scoped:true},{kind:"model",title:"模型训练",scoped:true},{kind:"strategy",title:"策略配置",scoped:true},{kind:"strategy",view:"backtest",title:"策略回测",scoped:true},{kind:"strategy",view:"optimize",title:"参数寻优",scoped:true},{kind:"experiment",title:"实验结果",scoped:true},{kind:"candidate",title:"研究候选",scoped:true},{kind:"simulation",title:"日线模拟账户"},{kind:"compare",title:"实验比较"},{kind:"market",title:"市场概况"},{kind:"screener",title:"筛选与自选"},{kind:"selection",title:"每日选股"},{kind:"positions",title:"实际持仓"}] as const;
 return <dialog ref={dialog} className="r-dialog r-tool-picker" onCancel={close}><div className="r-toolbar"><h2>打开工具</h2><button onClick={close}>关闭</button></div><input autoFocus aria-label="搜索工具" placeholder="搜索因子、模型、回测、持仓…" value={search} onChange={e=>setSearch(e.target.value)}/><select aria-label="工具的研究对象" value={target} onChange={e=>setTarget(e.target.value)}><option value="">选择研究对象</option>{s.projects.map(p=><optgroup key={p.id} label={p.name}><option value={`${p.id}:`}>{p.name} · 项目默认配置</option>{w.strategies.filter(st=>st.projectId===p.id).map(st=><option key={st.id} value={`${p.id}:${st.id}`}>{p.name} · {st.name}</option>)}</optgroup>)}</select><CommandStockSearch query={search} close={close}/><LocalCommand text={search} onSearch={setSearch} close={close}/><div className="r-tool-list">{entries.filter(e=>e.title.includes(search.trim())).map(e=><button disabled={"scoped" in e&&!projectId} key={e.title} onClick={()=>{w.open({kind:e.kind,title:e.title,...("view" in e?{view:e.view}:{}),...("scoped" in e?{projectId,strategyId:strategyId||undefined}:{})});close();}}>{e.title}<span>打开 →</span></button>)}</div></dialog>;
}

function ParameterPane({panel}:{panel:WorkspacePanel}) {
 const s=useResearch();const [detail,setDetail]=useState<ExperimentDetails|null>(null);
 useEffect(()=>{if(panel.kind==='experiment'&&panel.experimentId)void s.act(async()=>setDetail(await request<ExperimentDetails>('experiments.get',{projectId:panel.projectId,experimentId:panel.experimentId})));},[panel.experimentId,panel.projectId]);
 if(['reports','report','reproduction'].includes(panel.kind))return <div className="r-page"><h2>研报研究</h2><p>原文条件、引用和复现参数在中间页面核对与保存。</p></div>;
 if(panel.kind==='simulation')return <div className="r-page"><h2>模拟账户</h2><p>推进参数和账户状态在中间账户页查看。绑定采用固定版本；采用新版本后，旧持仓仍按入场版本管理。</p></div>;
 if(panel.kind==='candidate')return <div className="r-page"><h2>独立候选参数</h2><p>在中间候选页编辑与保存参数，并检查版本实验。点击采用后才更新策略草稿。</p></div>;
 if(panel.kind==='experiment')return <div className="r-page"><h2>本次实验参数</h2><p className="r-note">保存的运行快照。要调整下一次研究，请打开对应策略草稿。</p>{detail?<pre>{JSON.stringify(detail.experiment.parameters,null,2)}</pre>:<p>正在读取实验…</p>}</div>;
 return panel.kind==='factors'?<FactorPanel/>:panel.kind==='model'?<ModelPanel/>:panel.kind==='universe'?<UniversePanel/>:<StrategyPanel/>;
}
