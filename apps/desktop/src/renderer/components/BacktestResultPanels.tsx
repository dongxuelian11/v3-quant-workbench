import React, { useState } from "react";
import { DEMO_TRUTH } from "../../../../../packages/contracts/src/index";
import { useWorkbench } from "../store";
import { Icon, MetricRail, TruthMark } from "./PresentationSystem";

const backtestTabs = ["Review", "Run Matrix", "Holdings", "Orders / Fills", "Attribution"] as const;

function TruthStatus() {
  return <span data-truth-classification={DEMO_TRUTH.wave3} title={DEMO_TRUTH.wave3}><TruthMark detail="非正式金融输出"/></span>;
}

export function BacktestPanel() {
  const [tab, setTab] = useState<typeof backtestTabs[number]>("Review");
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [queue, setQueue] = useState("paused");
  const [queueNotice, setQueueNotice] = useState("开发队列已暂停");
  const focusContext = useWorkbench((state) => state.focusContext);
  const updateQueue = (next: string) => { setQueue(next); setQueueNotice(`开发队列状态 · ${queueStateLabel(next)}`); };
  return <section className="panel-page backtest-workspace" data-testid="backtest-surface" data-primary-panel="backtest-review" data-major-panel>
    <header className="analysis-header"><div className="analysis-title"><small>回测实验 · BT-DEMO-021</small><h1>风险平价 · 执行复盘</h1><p><TruthStatus/><span>可用时间 2026-06-30 18:45 CST</span></p></div><div className="experiment-trail"><span><small>交接</small>demo-v8</span><Icon name="chevron" size={13}/><span><small>场景</small>每月 · 2023—2026</span><Icon name="chevron" size={13}/><span><small>队列</small><b className={queue === "running" ? "ok" : "warn"}>{queueStateLabel(queue)}</b></span></div><div className="analysis-actions"><button data-action="backtest-scenario" aria-pressed={scenarioOpen} onClick={() => setScenarioOpen(!scenarioOpen)}>场景设置</button><button className={queue === "running" ? "" : "primary"} onClick={() => updateQueue("running")} disabled={queue === "running"}><Icon name="pulse" size={14}/>{queue === "running" ? "运行中" : "运行开发回测"}</button></div></header>
    <div className="analysis-contextline"><span>基准 · 沪深300 · 开发数据</span><span>成本 · 8 bps</span><span>行业中性 · ±5%</span><span className="action-receipt" role="status" aria-live="polite">{queueNotice}</span></div>
    <div className="mini-tabs" role="tablist" aria-label="回测分析视图">{backtestTabs.map((item) => <button role="tab" aria-selected={tab === item} data-backtest-tab={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item}>{backtestTabLabel(item)}</button>)}</div>
    <div className="backtest-primary primary-canvas" data-primary-canvas>{tab === "Review" ? <BacktestReview queue={queue} setQueue={updateQueue} onRun={() => focusContext({ kind: "backtest", eyebrow: "回测运行 · BACKTEST RUN", title: "BT-DEMO-021 · 风险平价", summary: "运行选择已映射到权益、回撤、成交与约束证据。", facts: [{ label: "收益率", value: "+26.84%" }, { label: "回撤", value: "-8.31%" }, { label: "换手率", value: "38.4%" }], provenance: "回测确定性开发数据提供方", trace: "backtest.run.selected → execution.review.updated → inspector.explained" })} /> : tab === "Run Matrix" ? <RunMatrix queue={queue} onRun={(id) => focusContext({ kind: "backtest", eyebrow: "运行矩阵", title: id, summary: "批量运行已关联场景、状态与约束检查。", facts: [{ label: "队列", value: queueStateLabel(queue) }, { label: "场景", value: "风险平价" }], provenance: "回测确定性开发数据提供方", trace: "run.matrix.selected → scenario.context.updated → inspector.explained" })} /> : <ExecutionTable tab={tab} />}</div>
    {scenarioOpen && <div className="context-drawer scenario-drawer" role="region" aria-label="回测场景设置" data-major-panel><div className="drawer-head"><div><small>场景 / 实验</small><b>回测场景设置</b></div><button onClick={() => setScenarioOpen(false)} aria-label="关闭场景设置">×</button></div><div className="scenario-form"><label>开始<input type="date" defaultValue="2023-01-01"/></label><label>结束<input type="date" defaultValue="2026-06-30"/></label><label>调仓<select><option>每月 · Monthly</option><option>每周 · Weekly</option></select></label><label>组合构建<select><option>风险平价 · Risk parity</option><option>等权 · Equal weight</option></select></label><label>最大单股权重<input type="number" defaultValue="4"/></label><label>交易成本 (bps)<input type="number" defaultValue="8"/></label><label>约束<select><option>行业中性 ±5%</option><option>无行业约束</option></select></label><div className="dimension-line"><b>批量维度</b><span>2 个标的池</span><span>3 种调仓</span><span>2 档成本</span><span>12 个运行</span></div><button className="primary" onClick={() => { setQueueNotice("场景参数已应用到前端开发会话"); setScenarioOpen(false); }}>应用场景</button></div></div>}
  </section>;
}

function BacktestReview({ queue, setQueue, onRun }: { queue: string; setQueue: (next: string) => void; onRun: () => void }) {
  return <div className="review-layout"><div className="performance-canvas"><MetricRail items={[{ label: "开发收益率", value: "+26.84%", tone: "positive" }, { label: "回撤", value: "-8.31%", tone: "negative" }, { label: "夏普比率", value: "1.42" }, { label: "换手率", value: "38.4%" }]}/><PerformanceChart /></div><aside className="run-evidence"><div className="section-head"><div><small>执行上下文</small><h2>BT-DEMO-021</h2></div><button onClick={onRun}><Icon name="inspector" size={14}/>证据</button></div><dl><dt>策略 · Strategy</dt><dd>StrategyDraft/demo-v8</dd><dt>信号 · Signal</dt><dd>PredictionSignalVersion/demo-alpha-v3</dd><dt>委托 / 成交</dt><dd>1,284 / 1,279</dd><dt>约束</dt><dd><span className="warn">换手率 38.4%</span></dd></dl><div className="constraint-list"><span className="ok">✓ 总敞口</span><span className="ok">✓ 行业偏离</span><span className="warn">! 换手阈值</span></div><div className="queue-actions">{queue === "running" ? <button onClick={() => setQueue("paused")}>Ⅱ 暂停</button> : <button onClick={() => setQueue("running")}>↻ 继续</button>}<button onClick={() => setQueue("cancelled")} className="danger" disabled={queue === "cancelled"}>× 取消</button></div></aside></div>;
}

function RunMatrix({ queue, onRun }: { queue: string; onRun: (id: string) => void }) {
  return <div className="run-matrix"><div className="section-head"><div><small>运行矩阵 / 队列</small><h2>12 个开发运行</h2></div><span className={`state ${queue}`}>{queueStateLabel(queue)}</span></div>{["BT-DEMO-021", "BT-DEMO-022", "BT-DEMO-023", "BT-DEMO-024", "BT-DEMO-025"].map((id, index) => <button className="matrix-row" key={id} onClick={() => onRun(id)}><b>{id}</b><span>{index === 0 ? "风险平价" : "等权"}</span><span>每月</span><progress max="100" value={queue === "running" ? 32 + index * 12 : index === 0 ? 100 : 58 - index * 7}/><small>{queue === "running" ? "运行中 · RUNNING" : index === 0 ? "已完成 · COMPLETE" : "已暂停 · PAUSED"}</small></button>)}</div>;
}

function PerformanceChart({ detailed = false }: { detailed?: boolean }) {
  return <div className={`performance-chart ${detailed ? "detailed" : ""}`} aria-label="权益、基准与回撤图"><svg viewBox="0 0 900 320" preserveAspectRatio="none"><defs><linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#4FC3F7" stopOpacity=".2"/><stop offset="1" stopColor="#4FC3F7" stopOpacity="0"/></linearGradient></defs><g className="grid-lines"><path d="M0 55 H900 M0 110 H900 M0 165 H900 M0 220 H900"/></g><path className="area" d="M0 238 C80 220 115 235 170 188 S260 172 310 158 S400 175 455 122 S560 140 620 95 S720 112 780 68 S850 88 900 42 L900 252 L0 252Z"/><path className="equity-line" d="M0 238 C80 220 115 235 170 188 S260 172 310 158 S400 175 455 122 S560 140 620 95 S720 112 780 68 S850 88 900 42"/><path className="benchmark-line" d="M0 242 C120 225 180 214 260 196 S420 186 500 160 S650 148 720 116 S840 104 900 82"/><path className="drawdown-line" d="M0 282 C110 286 155 266 230 288 S360 270 420 296 S550 262 660 286 S790 266 900 290"/></svg><div className="axis-years"><span>2023</span><span>2024</span><span>2025</span><span>2026</span></div></div>;
}

function ExecutionTable({ tab }: { tab: string }) {
  const [selectedRow, setSelectedRow] = useState<string | null>(null);
  const rows = tab.includes("Holding") || tab.includes("Position") ? [["600519.SH", "贵州茅台", "3.8%", "+1.28%", "Momentum"], ["300750.SZ", "宁德时代", "3.6%", "+2.43%", "Quality"], ["601318.SH", "中国平安", "3.4%", "+0.74%", "Value"]] : tab.includes("Order") ? [["ORD-1021", "600519.SH", "BUY 120", "FILLED", "09:31:02"], ["ORD-1022", "300750.SZ", "SELL 80", "PARTIAL", "10:04:18"], ["TRD-8821", "601318.SH", "BUY 300", "FILLED", "10:41:37"]] : [["Industry deviation", "3.1%", "≤5%", "PASS", "constraint"], ["Single weight", "3.8%", "≤4%", "PASS", "constraint"], ["Turnover", "38.4%", "≤35%", "WARN", "execution"]];
  return <div className="execution-table"><div className="section-head"><div><small>辅助证据</small><h2>{backtestTabLabel(tab)}</h2></div><span className="action-receipt" role="status" aria-live="polite">{selectedRow ? `${selectedRow} 已选中` : "选择一行查看上下文"}</span><TruthStatus/></div><div className="table-head"><span>标识</span><span>上下文</span><span>数值</span><span>状态</span><span>来源</span></div>{rows.map((row) => <button key={row[0]} className={selectedRow === row[0] ? "selected" : ""} aria-pressed={selectedRow === row[0]} onClick={() => setSelectedRow(row[0])}>{row.map((cell) => <span key={cell}>{cell}</span>)}</button>)}</div>;
}

function backtestTabLabel(value: string): string {
  return ({ Review: "复盘", "Run Matrix": "运行矩阵", Holdings: "持仓", "Orders / Fills": "委托 / 成交", Attribution: "归因" } as Record<string, string>)[value] ?? value;
}

function queueStateLabel(value: string): string {
  return ({ running: "运行中 · RUNNING", paused: "已暂停 · PAUSED", cancelled: "已取消 · CANCELLED" } as Record<string, string>)[value] ?? value;
}
