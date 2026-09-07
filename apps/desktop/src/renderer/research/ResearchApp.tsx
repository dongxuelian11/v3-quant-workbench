import React, { useEffect, useRef, useState } from "react";
import { DockviewReact, type DockviewApi, type DockviewReadyEvent, type IDockviewPanelProps } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import type { ProjectConfig } from "../../../../../packages/contracts/src/research";
import { ResearchContext, pages, request, useResearch, useResearchState, type Page } from "./state";
import { DataPanel, FactorPanel, Overview, UniversePanel } from "./ResearchPanels";
import { ModelPanel, StrategyPanel } from "./RunPanels";
import { ResultsPanel } from "./ResultsPanel";
import { PriceChart } from "./PriceChart";
import { AiPanel } from "./AiPanel";
import { Empty, Field } from "./ui";
import { WindowControls } from "../components/WindowControls";

const panels = { research: ({ params }: IDockviewPanelProps<{ page: Page }>) => {
  const s = useResearch();
  switch (params.page) {
    case "overview": return <Overview />; case "data": return <DataPanel />; case "universe": return <UniversePanel />;
    case "factors": return <FactorPanel />; case "strategy": return <StrategyPanel key={JSON.stringify(s.project?.settings.backtest)} />; case "model": return <ModelPanel key={JSON.stringify(s.project?.settings.model)} />;
    case "backtest": return <StrategyPanel run key={JSON.stringify(s.project?.settings.backtest)} />; case "results": return <ResultsPanel />; case "chart": return <div className="r-page"><PriceChart /></div>;
  }
} };
export function ResearchApp() { const state = useResearchState(); return <ResearchContext.Provider value={state}><Shell /></ResearchContext.Provider>; }
function Shell() {
  const s = useResearch(); const [creating, setCreating] = useState(false); const [settings, setSettings] = useState(false);
  const [aiVisible, setAiVisible] = useState(true); const [jobsVisible, setJobsVisible] = useState(false);
  const [left, setLeft] = useState(208); const [right, setRight] = useState(310); const [bottom, setBottom] = useState(170);
  const api = useRef<DockviewApi | null>(null); const layoutTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dimensions = useRef({ left, right, bottom }); dimensions.current = { left, right, bottom };
  const stateRef = useRef(s); stateRef.current = s;
  useEffect(() => { const l = s.project?.layout; if (l) { setLeft(Number(l.sidebarWidth) || 208); setRight(Number(l.aiWidth) || 310); setBottom(Number(l.taskHeight) || 170); } return () => { if (layoutTimer.current) clearTimeout(layoutTimer.current); }; }, [s.project?.id]);
  function persistLayout() {
    if (layoutTimer.current) clearTimeout(layoutTimer.current);
    const projectId = stateRef.current.project?.id;
    layoutTimer.current = setTimeout(() => { const current = stateRef.current; if (!projectId || current.project?.id !== projectId || !api.current) return; const d = dimensions.current;
      void current.act(() => current.save({ layout: { dock: JSON.parse(JSON.stringify(api.current!.toJSON())), sidebarWidth: d.left, aiWidth: d.right, taskHeight: d.bottom } }));
    }, 650);
  }
  function openPanel(page: Page, dock = api.current) { if (!dock) return; const panel = dock.getPanel(page); if (panel) panel.api.setActive(); else dock.addPanel({ id: page, component: "research", title: pages[page], params: { page } }); }
  const ready = (event: DockviewReadyEvent) => {
    api.current = event.api; const saved = s.project?.layout?.dock;
    if (saved) { try { event.api.fromJSON(saved as unknown as ReturnType<DockviewApi["toJSON"]>); } catch { s.setNotice("保存的窗格布局无法恢复，已打开默认概览。"); } }
    openPanel("overview", event.api); event.api.onDidLayoutChange(persistLayout);
    event.api.onDidActivePanelChange(event => { const page = event.panel?.params?.page as Page | undefined; if (page && page in pages) stateRef.current.setPage(page); });
  };
  useEffect(() => { if (s.project) openPanel(s.page); }, [s.page, s.project?.id]);
  const resize = (kind: "left" | "right" | "bottom", e: React.PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId); const startX = e.clientX, startY = e.clientY, start = dimensions.current;
    e.currentTarget.onpointermove = event => {
      if (kind === "left") setLeft(Math.max(160, Math.min(320, start.left + event.clientX - startX)));
      if (kind === "right") setRight(Math.max(250, Math.min(500, start.right - event.clientX + startX)));
      if (kind === "bottom") setBottom(Math.max(100, Math.min(360, start.bottom - event.clientY + startY)));
    };
    e.currentTarget.onpointerup = () => { e.currentTarget.onpointermove = null; persistLayout(); };
  };
  const activeJobs = s.jobs.filter(j => ["queued", "running"].includes(j.status));
  return <div className="r-app" data-testid="research-app" style={{ "--r-sidebar": `${left}px`, "--r-ai": `${right}px`, "--r-tasks": `${bottom}px` } as React.CSSProperties}>
    <header className="r-titlebar"><div className="r-brand"><strong>V3</strong><span>研究工作台</span></div><span className="r-project-title">{s.project?.name ?? "你的下一次研究，从这里开始"}</span><div className="r-title-actions"><button onClick={() => setAiVisible(v => !v)}>{aiVisible ? "收起助手" : "打开助手"}</button>{window.v3Desktop && <WindowControls />}</div></header>
    {s.error && <div className="r-banner error" role="alert"><span>{s.error}</span><button onClick={() => s.setError("")} aria-label="关闭错误消息">×</button></div>}{s.notice && <div className="r-banner" role="status"><span>{s.notice}</span><button onClick={() => s.setNotice("")} aria-label="关闭提示">×</button></div>}
    <div className="r-body"><aside className="r-sidebar"><h2>研究项目</h2><div className="r-project-list">{s.projects.map(p => <button className={p.id === s.project?.id ? "active" : ""} key={p.id} onClick={() => void s.act(() => s.open(p.path))}><Folder /><span>{p.name}</span></button>)}</div><button className="r-sidebar-action" disabled={!window.v3Research} onClick={() => setCreating(true)}><span>＋</span> 新建项目</button><button className="r-sidebar-action" disabled={!window.v3Research} onClick={() => void s.act(async () => { const path = await window.v3Research!.chooseDirectory(); if (path) await s.open(path); })}><Folder /> 打开项目</button><hr /><h2>个人库</h2><button disabled={!s.project} onClick={() => s.setPage("universe")}>股票池模板</button><button disabled={!s.project} onClick={() => s.setPage("strategy")}>策略模板</button><div className="r-sidebar-foot"><button onClick={() => { setSettings(true); setAiVisible(true); }}>设置</button><small>本地研究 · 日线</small></div></aside><div className="r-resize" role="separator" aria-label="调整项目栏宽度" aria-orientation="vertical" onPointerDown={e => resize("left", e)} />
      <main className="r-main">{s.project ? <><nav className="r-pages" aria-label="研究导航">{Object.entries(pages).map(([page, label]) => <button key={page} className={s.page === page ? "active" : ""} onClick={() => { s.setPage(page as Page); openPanel(page as Page); }}>{label}</button>)}<button className="r-layout-reset" title="恢复默认窗格" onClick={() => { api.current?.clear(); openPanel("overview"); s.setPage("overview"); }}>重置布局</button></nav><div className="r-dock"><DockviewReact key={s.project.id} className="dockview-theme-light" components={panels} onReady={ready} /></div></> : <div className="r-welcome"><span className="r-eyebrow">V3 · QUANTITATIVE RESEARCH</span><h1>把一个想法，<br />变成可复盘的研究。</h1><p>数据、因子、模型与实验，<br />在自己的项目中有序展开。</p><div className="r-toolbar"><button className="r-primary" disabled={!window.v3Research} onClick={() => setCreating(true)}>创建第一个项目 →</button><button disabled={!window.v3Research} onClick={() => void s.act(async () => { const path = await window.v3Research!.chooseDirectory(); if (path) await s.open(path); })}>打开已有项目</button></div>{!window.v3Research && <p className="r-note">研究服务未连接<br />请从桌面应用打开，连接本地研究服务。</p>}<div className="r-welcome-steps"><span>01 数据准备</span><span>02 因子与模型</span><span>03 实验与复盘</span></div></div>}</main>
      {<><div style={aiVisible ? undefined : { display: "none" }} className="r-resize" role="separator" aria-label="调整助手宽度" aria-orientation="vertical" onPointerDown={e => resize("right", e)} /><AiPanel hidden={!aiVisible} key={s.project?.id ?? "empty"} settingsOpen={settings} closeSettings={() => setSettings(false)} /></>}
    </div><footer className="r-taskbar"><button onClick={() => setJobsVisible(v => !v)} aria-expanded={jobsVisible}>任务 <span>{activeJobs.length ? `${activeJobs.length} 项进行中` : "暂无运行中的任务"}</span><span>{jobsVisible ? "⌄" : "⌃"}</span></button>{jobsVisible && <><div className="r-resize horizontal" role="separator" aria-label="调整任务区高度" onPointerDown={e => resize("bottom", e)} /><Jobs /></>}</footer>{creating && <CreateProject close={() => setCreating(false)} />}
  </div>;
}
function Folder() { return <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></svg>; }
function CreateProject({ close }: { close: () => void }) {
  const s = useResearch(); const [name, setName] = useState(""); const [path, setPath] = useState(""); const [objective, setObjective] = useState(""); const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null); useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="r-dialog" onCancel={close}><form onSubmit={e => { e.preventDefault(); setBusy(true); void s.act(async () => { const p = await request<ProjectConfig>("projects.create", { path, name: name.trim(), objective: objective.trim() }); await s.open(p.path); close(); }).finally(() => setBusy(false)); }}><h2>新建研究项目</h2><p>项目文件、数据与实验保存在你选择的文件夹。</p><Field label="项目名称"><input required autoFocus value={name} onChange={e => setName(e.target.value)} /></Field><Field label="项目文件夹"><div className="r-toolbar"><input required value={path} onChange={e => setPath(e.target.value)} /><button type="button" onClick={() => void s.act(async () => { const chosen = await window.v3Research!.chooseDirectory(); if (chosen) setPath(chosen); })}>选择文件夹</button></div></Field><Field label="研究目标"><textarea rows={4} value={objective} onChange={e => setObjective(e.target.value)} placeholder="想验证怎样的投资假设？" /></Field><div className="r-toolbar"><button type="button" onClick={close}>取消</button><button className="r-primary" disabled={busy || !name.trim() || !path.trim()} type="submit">{busy ? "创建中…" : "创建项目"}</button></div></form></dialog>;
}
function Jobs() {
  const s = useResearch(); const labels = { queued: "排队中", running: "运行中", completed: "已完成", failed: "失败", cancelled: "已取消", interrupted: "已中断" };
  return <div className="r-jobs">{s.jobs.length ? s.jobs.map(j => <div className="r-job" key={j.id}><strong>{j.name}</strong><span>{labels[j.status]}</span><progress max={1} value={Math.max(0, Math.min(1, j.progress))} aria-label={`${j.name}进度`} /><span title={j.message}>{j.message}</span>{["queued", "running"].includes(j.status) ? <button onClick={() => void s.act(async () => { await request("jobs.cancel", { jobId: j.id }); await s.refresh(); })}>取消</button> : <button onClick={() => void s.act(() => s.submit(j.spec.kind, j.spec.parameters, j.name))}>重跑</button>}{j.experimentId && <button onClick={() => { s.setSelectedExperiment(j.experimentId!); s.setPage("results"); }}>查看结果</button>}</div>) : <Empty title="还没有任务记录" />}</div>;
}


