import React, { useEffect, useState } from "react";
import { Command } from "cmdk";
import type { LabId } from "../../../../packages/contracts/src/index";
import { useWorkbench } from "./store";
import { Workbench } from "./components/Workbench";

const labs: { id: LabId; zh: string; en: string; icon: string }[] = [
  { id: "research", zh: "研究", en: "Research", icon: "⌁" }, { id: "strategy", zh: "策略", en: "Strategy", icon: "◇" },
  { id: "model", zh: "模型", en: "Model", icon: "✦" }, { id: "backtest", zh: "回测", en: "Backtest", icon: "▥" },
  { id: "result", zh: "结果", en: "Result", icon: "◉" }
];

export function App() {
  const s = useWorkbench();
  const [palette, setPalette] = useState(false);
  useEffect(() => { void s.hydrate(); }, []);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setPalette((v) => !v); } };
    document.addEventListener("keydown", listener); return () => document.removeEventListener("keydown", listener);
  }, []);
  if (!s.hydrated) return <div className="loading">正在恢复持久化工作区…</div>;
  return <div className="app-shell" data-testid="app-shell">
    <header className="top-nav">
      <div className="brand"><span className="brand-mark">V3</span><div><b>量化研究工作台</b><small>FR-1 CAPABILITY CANDIDATE</small></div></div>
      <nav aria-label="五实验室主导航">{labs.map((lab, i) => <button key={lab.id} data-lab={lab.id} className={s.activeLab === lab.id ? "active" : ""} onClick={() => s.setLab(lab.id)}><span>{lab.icon}</span><b>{lab.zh}</b><small>{lab.en}</small><kbd>⌘{i + 1}</kbd></button>)}</nav>
      <div className="top-tools"><span className="runtime">● {s.runtime}</span><button onClick={() => setPalette(true)}>⌘ 命令</button><button className="avatar">LM</button></div>
    </header>
    <aside className="asset-tree" aria-label="项目与研究资产树">
      <div className="tree-heading"><span>项目资产</span><button>＋</button></div>
      <div className="project-row"><span>▾</span><b>Momentum Research</b><small>LOCAL</small></div>
      <Tree title="数据源" items={["CN Daily Adjusted · Demo", "Factor Panel v12 · Demo"]} onSelect={s.select} />
      <Tree title="Universe" items={["CN Large Cap @v12", "Imported Watchlist @v3"]} onSelect={s.select} />
      <Tree title="研究" items={["Momentum 12M", "IC Decay Analysis", "Coverage Diagnostics"]} onSelect={s.select} />
      <Tree title="策略与模型" items={["StrategyDraft v8", "Study S-014", "ModelVersion lgbm-v4"]} onSelect={s.select} />
      <div className="tree-truth"><b>DEMO PROVIDER</b><span>所有数值均为确定性演示</span><small>NOT FORMAL FINANCIAL OUTPUT</small></div>
    </aside>
    <main className="workspace"><Workbench /></main>
    {s.inspectorOpen && <aside className="inspector" data-testid="inspector"><div className="inspector-head"><span>上下文检查器</span><button onClick={s.toggleInspector}>×</button></div><h2>{s.inspectorTitle}</h2><p className="truth-chip">DEMO · 可追溯</p><dl><dt>项目</dt><dd>{s.activeProject}</dd><dt>选中资产</dt><dd>{s.selectedAsset ?? "无"}</dd><dt>数据真值</dt><dd>DeterministicFrontendDemoProvider/v1</dd><dt>正式输出</dt><dd className="warn">禁止</dd></dl><div className="audit-box"><b>诊断 / Truth / Provenance</b><p>当前界面恢复产品交互能力，不包含后端计算，不构成投资或交易建议。</p></div></aside>}
    <section className={`operations ${s.bottomOpen ? "open" : "closed"}`}><button onClick={s.toggleBottom}>{s.bottomOpen ? "⌄" : "⌃"} 任务 / 日志 / 输出</button>{s.bottomOpen && <div><span className="ok">● WORKSPACE READY</span><span>ProjectContext 已恢复</span><span>布局持久化已启用</span><span className="demo">DEMO / NOT FORMAL FINANCIAL OUTPUT</span></div>}</section>
    {palette && <div className="palette-backdrop" onMouseDown={() => setPalette(false)}><Command className="command-palette" onMouseDown={(e) => e.stopPropagation()} label="命令面板"><Command.Input autoFocus placeholder="输入命令或跳转实验室…" /><Command.List><Command.Empty>无匹配命令</Command.Empty>{labs.map((lab) => <Command.Item key={lab.id} onSelect={() => { s.setLab(lab.id); setPalette(false); }}>打开 {lab.zh}实验室 <small>{lab.en}</small></Command.Item>)}<Command.Item onSelect={() => { void s.save(); setPalette(false); }}>保存当前工作区</Command.Item><Command.Item onSelect={() => { void s.reset(); setPalette(false); }}>重置当前工作区</Command.Item></Command.List></Command></div>}
  </div>;
}

function Tree({ title, items, onSelect }: { title: string; items: string[]; onSelect: (x: string) => void }) {
  return <div className="tree-group"><b>▾ {title}</b>{items.map((item) => <button key={item} onClick={() => onSelect(`${title} / ${item}`)}><span>{title === "Universe" ? "◎" : "▧"}</span>{item}</button>)}</div>;
}
