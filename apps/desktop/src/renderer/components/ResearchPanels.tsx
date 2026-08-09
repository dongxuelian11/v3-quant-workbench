import React, { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { DEMO_TRUTH } from "../../../../../packages/contracts/src/index";
import { researchSeries, symbols, universeModes } from "../demo";
import { useWorkbench } from "../store";

export function ResearchChartPanel() {
  const host = useRef<HTMLDivElement>(null); const select = useWorkbench((s) => s.select); const [running, setRunning] = useState(false);
  useEffect(() => {
    if (!host.current) return; const chart = echarts.init(host.current);
    chart.setOption({ animation: false, backgroundColor: "transparent", tooltip: { trigger: "axis", axisPointer: { type: "cross" } }, legend: { data: ["Momentum Composite", "Benchmark"], textStyle: { color: "#93a9b9" } }, grid: { left: 54, right: 28, top: 48, bottom: 62 }, xAxis: { type: "category", data: researchSeries.map((x) => x.date), axisLabel: { color: "#71899b" }, axisPointer: { show: true } }, yAxis: { type: "value", axisLabel: { color: "#71899b" }, splitLine: { lineStyle: { color: "#182b39" } } }, dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 15 }], brush: { toolbox: ["rect", "clear"], xAxisIndex: 0 }, series: [{ name: "Momentum Composite", type: "line", smooth: true, showSymbol: false, lineStyle: { color: "#37d9d0", width: 2 }, areaStyle: { color: "rgba(55,217,208,.12)" }, data: researchSeries.map((x) => x.value) }, { name: "Benchmark", type: "line", showSymbol: false, lineStyle: { color: "#f0b65f", width: 1.5, type: "dashed" }, data: researchSeries.map((x) => x.benchmark) }] });
    chart.on("click", (p) => select(`图表选择 · ${String(p.name)} · ${String(p.value)}`)); chart.on("brushSelected", () => select("Brush 区间选择 · 研究样本 18 期"));
    const resize = () => chart.resize(); window.addEventListener("resize", resize); return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [select]);
  return <section className="panel-page research-chart-page"><div className="panel-controls"><label>数据源 <select defaultValue="demo"><option value="demo">CN Daily Adjusted · Demo</option><option>Factor Panel v12 · Demo</option></select></label><label>Universe <select defaultValue="large"><option value="large">CN Large Cap @v12</option><option>All Shares @v31</option></select></label><button className={running ? "danger" : "primary"} onClick={() => setRunning(!running)}>{running ? "■ 停止研究" : "▶ 运行研究"}</button><span className="truth-chip">{DEMO_TRUTH.label}</span></div><div className="metric-strip"><Metric k="区间收益" v="+28.42%"/><Metric k="Benchmark" v="+17.06%"/><Metric k="IC Mean" v="0.071"/><Metric k="Coverage" v="96.8%"/></div><div ref={host} className="echart" data-testid="research-echart"/><small className="hint">滚轮缩放 · 拖拽 dataZoom · 工具箱 Brush · 点击数据点联动 Inspector</small></section>;
}

function Metric({ k, v }: { k: string; v: string }) { return <div><small>{k}</small><b>{v}</b></div>; }

export function UniverseBuilderPanel() {
  const mode = useWorkbench((s) => s.selectedUniverseMode); const choose = useWorkbench((s) => s.setUniverseMode); const select = useWorkbench((s) => s.select);
  return <section className="panel-page universe-page" data-testid="universe-builder"><div className="universe-layout"><div className="constructor-list"><h3>九类构造器</h3>{universeModes.map((item, i) => <button key={item.id} className={mode === item.id ? "active" : ""} data-universe-mode={item.id} onClick={() => choose(item.id)}><i>{i + 1}</i><span><b>{item.name}</b><small>{item.detail}</small></span></button>)}</div><div className="constructor-config"><div className="section-head"><div><small>UNIVERSE CONSTRUCTOR</small><h2>{universeModes.find((x) => x.id === mode)?.name}</h2></div><span className="version">UniverseVersion/demo-v13</span></div><Config mode={mode}/><div className="preview-head"><b>版本化预览</b><span>5,184 → 1,842 · as-of 2026-06-30</span></div><div className="symbol-grid"><div className="grid-head"><span>代码</span><span>名称</span><span>变动</span><span>因子分位</span></div>{symbols.map((row) => <button key={row[0]} className={row[0] === "INVALID-X" ? "unresolved" : ""} onClick={() => select(`Universe 证券 · ${row[0]} ${row[1]}`)}>{row.map((cell) => <span key={cell}>{cell}</span>)}</button>)}</div>{mode === "csv-tsv-import" && <div className="import-preview"><b>CSV/TSV 导入解析预览</b><label className="file-button">选择 CSV/TSV<input type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" /></label><span className="warn">未解析：INVALID-X · 将不会静默纳入</span></div>}<div className="actions"><button>保存为新版本</button><button className="primary">应用到 ProjectContext</button></div></div></div></section>;
}

function Config({ mode }: { mode: string }) {
  if (mode === "nested-condition") return <div className="condition-tree"><b>AND</b><div>市值 ≥ 100 亿</div><div><b>OR</b><span>ROE ≥ 12%</span><span>Momentum Top 20%</span></div><button>＋ 添加条件组</button></div>;
  if (mode === "factor-top-bottom") return <div className="form-grid"><label>因子<select><option>Momentum 12M</option><option>Quality Blend</option></select></label><label>方向<select><option>Top N</option><option>Bottom N</option></select></label><label>N<input type="number" defaultValue="50" /></label></div>;
  if (mode === "custom-symbols") return <div className="token-input"><span>600519.SH ×</span><span>300750.SZ ×</span><input aria-label="添加证券代码" placeholder="输入代码后回车" /></div>;
  if (mode === "saved-reference") return <div className="form-grid"><label>引用版本<select><option>UniverseVersion/demo-v12</option><option>UniverseVersion/demo-v11</option></select></label><label>As-of<input type="date" defaultValue="2026-06-30" /></label></div>;
  return <div className="form-grid"><label>市场/分类<select><option>沪深 A 股</option><option>沪深300</option><option>中信一级 / 电子</option><option>AI 基础设施</option></select></label><label>As-of<input type="date" defaultValue="2026-06-30" /></label><label>停牌处理<select><option>保留并标记</option><option>排除</option></select></label></div>;
}

export function ResearchAnalyticsPanel() {
  const [tab, setTab] = useState("分布"); const tabs = ["分布", "覆盖率", "IC / 衰减", "分组收益", "相关性", "事件元数据"];
  return <section className="panel-page analytics-page"><div className="mini-tabs">{tabs.map((x) => <button className={x === tab ? "active" : ""} onClick={() => setTab(x)} key={x}>{x}</button>)}</div><div className="analytics-content"><div className="histogram">{[34,48,69,92,110,126,118,94,61,42,29].map((h, i) => <i key={i} style={{height:h}}/> )}</div><div className="analytics-notes"><span className="truth-chip">DEMO</span><h3>{tab}</h3><p>{tab === "IC / 衰减" ? "IC(1D) 0.071 → IC(20D) 0.028，衰减曲线来自固定演示序列。" : tab === "分组收益" ? "Q5 − Q1 年化差值 +8.4%，仅演示分组交互。" : tab === "相关性" ? "与 Quality Blend 相关系数 0.23；事件窗口已标注。" : "选择区间与 Research 主图、Universe Grid、Inspector 双向联动。"}</p><dl><dt>Correlation ID</dt><dd>demo-corr-2026q2</dd><dt>Event metadata</dt><dd>rebalance / earnings-window</dd><dt>Provenance</dt><dd>DeterministicFrontendDemoProvider/v1</dd></dl></div></div></section>;
}
