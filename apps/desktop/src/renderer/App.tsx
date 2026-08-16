import React, { useEffect, useState } from "react";
import { Command } from "cmdk";
import type { LabId } from "../../../../packages/contracts/src/index";
import { useWorkbench } from "./store";
import { Workbench } from "./components/Workbench";
import { Icon, StatusSurface, TruthMark, type IconName } from "./components/PresentationSystem";
import { AgentWorkspace } from "./components/AgentWorkspace";
import { ResearchSessionNavigator } from "./components/ResearchSessionNavigator";
import { WindowControls } from "./components/WindowControls";
import { ProductRuntimeStatusChip } from "./components/ProductRuntimeStatusChip";
import {
  applyRound3ConnectionState,
  applyRound3EvidenceEvent,
  initialRound3AgentWorkspaceState
} from "./round3Evidence";

type WorkspaceSurface = "agent" | LabId;

const labs: { id: LabId; zh: string; icon: IconName }[] = [
  { id: "research", zh: "研究", icon: "research" },
  { id: "strategy", zh: "策略", icon: "strategy" },
  { id: "model", zh: "模型", icon: "model" },
  { id: "backtest", zh: "回测", icon: "backtest" },
  { id: "result", zh: "结果", icon: "result" }
];

const labContext: Record<LabId, { object: string; phase: string }> = {
  research: { object: "12 月动量 / 600519.SH", phase: "证据研究" },
  strategy: { object: "策略草案 · StrategyDraft / demo-v8", phase: "构建与审阅" },
  model: { object: "试验 · Study S-014 / LightGBM", phase: "训练工作流" },
  backtest: { object: "BT-DEMO-021", phase: "执行复盘" },
  result: { object: "回测结果分析 · BacktestResultAnalytics / PRE_ALPHA", phase: "确定性绩效分析" }
};

export function App() {
  const s = useWorkbench();
  const [palette, setPalette] = useState(false);
  const [surface, setSurface] = useState<WorkspaceSurface>("agent");
  const [agentState, setAgentState] = useState(initialRound3AgentWorkspaceState);
  const [activeSessionId, setActiveSessionId] = useState(agentState.data.sessions[0].sessionViewId);

  useEffect(() => { void s.hydrate(); }, []);
  useEffect(() => {
    const bridge = window.v3BackendRuntime;
    let stopped = false;
    let healthAttempts = 0;
    let healthTimer: ReturnType<typeof setTimeout> | undefined;
    const stopConnection = bridge.onConnectionState((state) => setAgentState((current) => applyRound3ConnectionState(current, state)));
    const stopEvidence = bridge.onEvidenceEvent((event) => setAgentState((current) => applyRound3EvidenceEvent(current, event)));
    void bridge.getEvidenceSnapshot().then((event) => {
      if (event) setAgentState((current) => applyRound3EvidenceEvent(current, event));
    }).catch(() => undefined);
    const syncHealth = (): void => {
      healthAttempts += 1;
      void bridge.getHealth().then((health) => {
        const state = health.state;
        if (!stopped && typeof state === "string" && ["STOPPED", "STARTING", "HANDSHAKING", "REPLAYING", "READY", "DISCONNECTED", "CRASH_LOOP", "SHUTTING_DOWN"].includes(state)) {
          setAgentState((current) => applyRound3ConnectionState(current, state as Parameters<typeof applyRound3ConnectionState>[1]));
        }
      }).catch(() => {
        if (!stopped && healthAttempts < 40) healthTimer = setTimeout(syncHealth, 250);
      });
    };
    syncHealth();
    return () => { stopped = true; if (healthTimer) clearTimeout(healthTimer); stopConnection(); stopEvidence(); };
  }, []);
  useEffect(() => {
    if (!agentState.data.sessions.some((session) => session.sessionViewId === activeSessionId)) {
      setActiveSessionId(agentState.data.sessions[0].sessionViewId);
    }
  }, [activeSessionId, agentState.data.sessions]);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((value) => !value);
      }
      if ((event.ctrlKey || event.metaKey) && event.key === "0") {
        event.preventDefault();
        setSurface("agent");
      }
      if ((event.ctrlKey || event.metaKey) && /^[1-5]$/.test(event.key)) {
        event.preventDefault();
        const lab = labs[Number(event.key) - 1].id;
        s.setLab(lab);
        setSurface(lab);
      }
    };
    document.addEventListener("keydown", listener);
    return () => document.removeEventListener("keydown", listener);
  }, [s.setLab]);

  if (!s.hydrated) return <StatusSurface state="loading" title="正在恢复研究会话" detail="载入 ProjectContext、布局与草案状态…"/>;

  const active = labs.find((lab) => lab.id === s.activeLab) ?? labs[0];
  const context = labContext[s.activeLab];
  const activeSession = agentState.data.sessions.find((session) => session.sessionViewId === activeSessionId) ?? agentState.data.sessions[0];
  const openLab = (lab: LabId) => { s.setLab(lab); setSurface(lab); };

  return <div className={`app-shell inspector-${surface !== "agent" && s.inspectorOpen ? "open" : "closed"}`} data-testid="app-shell" data-default-surface={surface}>
    <aside className="global-rail" aria-label="V3 智能体与实验室导航">
      <div className="rail-brand" aria-label="V3 精密量化研究工作台"><span>V3</span><i/></div>
      <nav><button
        data-surface="agent"
        className={surface === "agent" ? "active" : ""}
        onClick={() => setSurface("agent")}
        aria-current={surface === "agent" ? "page" : undefined}
        title="智能体工作区 · Ctrl+0"
      ><Icon name="pulse"/><span>智能体</span><kbd>0</kbd></button>{labs.map((lab, index) => <button
        key={lab.id}
        data-lab={lab.id}
        className={surface === lab.id ? "active" : ""}
        onClick={() => openLab(lab.id)}
        aria-current={surface === lab.id ? "page" : undefined}
        title={`${lab.zh}实验室 · Ctrl+${index + 1}`}
      ><Icon name={lab.icon}/><span>{lab.zh}</span><kbd>{index + 1}</kbd></button>)}</nav>
      <div className="rail-utilities">
        <button onClick={() => setPalette(true)} aria-label="打开命令面板" aria-haspopup="dialog"><Icon name="command"/></button>
        {surface !== "agent" && <button onClick={s.toggleBottom} aria-label="打开任务与日志" aria-pressed={s.bottomOpen}><Icon name="operations"/></button>}
        <span className="rail-avatar" aria-label="当前用户 LM">LM</span>
      </div>
    </aside>

    <header className="context-bar" onDoubleClick={(event) => { if ((event.target as HTMLElement).closest("button")) return; void window.v3Desktop.windowControl("toggle-maximize"); }}>
      <div className="context-breadcrumb">{surface === "agent" ? <><span>智能体工作区</span><Icon name="chevron" size={13}/><b>{activeSession.title}</b><small>证据优先研究</small></> : <><span>{active.zh}实验室</span><Icon name="chevron" size={13}/><b>{context.object}</b><small>{context.phase}</small></>}</div>
      <button className="context-search" onClick={() => setPalette(true)} aria-haspopup="dialog" aria-expanded={palette}><Icon name="command" size={15}/><span>跳转、打开视图或执行命令</span><kbd>Ctrl K</kbd></button>
      <div className="context-runtime">{surface === "agent" ? <span className="boundary-chip">{agentState.boundary.label}</span> : <TruthMark compact/>}<ProductRuntimeStatusChip/><span><i/>{s.runtime}</span></div>
      <WindowControls />
    </header>

    <aside className="context-sidebar" aria-label="项目与研究资产" data-nav-width>
      {surface === "agent" ? <ResearchSessionNavigator sessions={agentState.data.sessions} boundary={agentState.boundary} activeSessionId={activeSessionId} onSelect={setActiveSessionId}/> : <>
        <div className="sidebar-project">
          <span className="sidebar-icon"><Icon name="project"/></span>
          <div><small>当前项目</small><b>动量研究</b><span>2026 Q2 · 本地 · LOCAL</span></div>
          <button aria-label="项目操作"><Icon name="more" size={16}/></button>
        </div>
        <div className="sidebar-section-head"><span>工作对象</span><button aria-label="新增资产" onClick={() => s.select("新增资产 · BACKEND_UNWIRED")}><Icon name="add" size={15}/></button></div>
        <AssetGroup mark="D" title="数据" items={["中国 A 股日线复权 · 开发数据", "因子面板 v12 · 开发数据"]} onSelect={s.select}/>
        <AssetGroup mark="U" title="股票池 · Universe" items={["中国大盘股 @v12", "导入观察列表 @v3"]} onSelect={s.select}/>
        <AssetGroup mark="R" title="研究案例" items={["12 月动量", "IC 衰减分析", "覆盖率诊断"]} onSelect={s.select}/>
        <AssetGroup mark="V" title="版本与运行" items={["策略草案 · StrategyDraft v8", "试验 · Study S-014", "模型版本 · ModelVersion lgbm-v4"]} onSelect={s.select}/>
        <div className="sidebar-foot"><TruthMark detail="确定性数据提供器"/><span>可用时间 · 15:05 CST</span></div>
      </>}
    </aside>

    <main className="workspace">{surface === "agent" ? <AgentWorkspace session={activeSession} data={agentState.data} boundary={agentState.boundary} connectionState={agentState.connectionState} onOpenLab={openLab}/> : <Workbench/>}</main>

    {surface !== "agent" && s.inspectorOpen && <aside className="inspector" aria-label="上下文检查器" data-testid="inspector" data-inspector-width>
      <div className="inspector-head"><div><Icon name="inspector" size={15}/><span>{s.inspectorEvidence.eyebrow}</span></div><button onClick={s.toggleInspector} aria-label="关闭检查器"><Icon name="close" size={15}/></button></div>
      <div className="inspector-identity"><small>已选上下文</small><h2>{s.inspectorEvidence.title}</h2><p>{s.inspectorEvidence.summary}</p><TruthMark detail="来源可追溯"/></div>
      <section className="inspector-section"><h3>上下文事实</h3><dl>{s.inspectorEvidence.facts.map((fact) => <React.Fragment key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></React.Fragment>)}</dl></section>
      <section className="inspector-section"><h3>交互链路</h3><code>{s.inspectorEvidence.trace}</code></section>
      <section className="inspector-section"><h3>来源与守卫</h3><p>{s.inspectorEvidence.provenance}</p><p>可用时间 · available-time / 生效时间 · effective-time 约束保留；无后端金融计算。</p></section>
    </aside>}

    {surface !== "agent" && <section className={`operations ${s.bottomOpen ? "open" : "closed"}`} aria-label="任务、日志与输出">
      <header><div><Icon name="operations" size={16}/><span>任务与日志</span><small>仅在需要时显示</small></div><button data-action="operations-toggle" onClick={s.toggleBottom} aria-label="关闭任务与日志" aria-expanded={s.bottomOpen} aria-controls="operations-drawer"><Icon name="close" size={15}/></button></header>
      {s.bottomOpen && <div id="operations-drawer" className="operations-drawer" data-major-panel>
        <div><small>会话</small><b>工作区已就绪</b><span>项目上下文 · ProjectContext 已恢复</span></div>
        <div><small>布局</small><b>停靠布局持久化</b><span>{s.savedAt ? `保存于 ${new Date(s.savedAt).toLocaleTimeString("zh-CN")}` : "等待保存"}</span></div>
        <div><small>真值边界</small><b>演示数据 · 后端尚未接线</b><span>不构成投资或交易建议</span></div>
      </div>}
    </section>}

    {palette && <div className="palette-backdrop" onMouseDown={() => setPalette(false)} role="presentation">
      <Command className="command-palette" onMouseDown={(event) => event.stopPropagation()} onKeyDown={(event) => { if (event.key === "Escape") setPalette(false); }} label="命令面板" role="dialog" aria-modal="true">
        <div className="palette-head"><Icon name="command"/><Command.Input autoFocus placeholder="输入命令、实验室或工作对象…"/><kbd>ESC</kbd></div>
        <Command.List><Command.Empty>无匹配命令</Command.Empty>
          <Command.Group heading="智能体优先入口"><Command.Item onSelect={() => { setSurface("agent"); setPalette(false); }}><Icon name="pulse"/><span>打开智能体工作区<small>研究会话 · 证据 · 时间线</small></span><kbd>Ctrl 0</kbd></Command.Item></Command.Group>
          <Command.Group heading="专业实验室">{labs.map((lab, index) => <Command.Item key={lab.id} onSelect={() => { openLab(lab.id); setPalette(false); }}><Icon name={lab.icon}/><span>打开{lab.zh}实验室<small>专业研究工作台</small></span><kbd>Ctrl {index + 1}</kbd></Command.Item>)}</Command.Group>
          <Command.Group heading="工作区">
            {surface !== "agent" && <Command.Item onSelect={() => { s.toggleInspector(); setPalette(false); }}><Icon name="inspector"/><span>切换上下文检查器<small>查看当前对象、来源与守卫</small></span></Command.Item>}
            {surface !== "agent" && <Command.Item onSelect={() => { s.toggleBottom(); setPalette(false); }}><Icon name="operations"/><span>切换任务与日志抽屉<small>查看会话、布局与真值状态</small></span></Command.Item>}
            <Command.Item onSelect={() => { void s.save(); setPalette(false); }}><Icon name="focus"/><span>保存当前工作区<small>持久化布局与本地状态</small></span></Command.Item>
            <Command.Item onSelect={() => { void s.reset(); setPalette(false); }}><Icon name="pulse"/><span>重置当前工作区<small>恢复默认布局与状态</small></span></Command.Item>
          </Command.Group>
        </Command.List>
      </Command>
    </div>}
  </div>;
}

function AssetGroup({ mark, title, items, onSelect }: { mark: string; title: string; items: string[]; onSelect: (item: string) => void }) {
  return <div className="asset-group"><div className="asset-group-title"><Icon name="chevron" size={12}/><span>{title}</span></div>{items.map((item) => <button key={item} title={`${title} / ${item}`} onClick={() => onSelect(`${title} / ${item}`)}><i>{mark}</i><span>{item}</span></button>)}</div>;
}
