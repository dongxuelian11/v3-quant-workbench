import React, { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import type { UniverseMode } from "../../../../../packages/contracts/src/index";
import { researchBars, researchEvents, symbols, universeModes } from "../demo";
import { useWorkbench } from "../store";
import { Icon, MetricRail, PaneHeading, TruthMark } from "./PresentationSystem";

export function ResearchChartPanel() {
  const host = useRef<HTMLDivElement>(null);
  const focusContext = useWorkbench((state) => state.focusContext);
  const [universeOpen, setUniverseOpen] = useState(false);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current, undefined, { renderer: "canvas" });
    const dates = researchBars.map((point) => point.date);
    chart.setOption({
      animation: false,
      backgroundColor: "#10131C",
      textStyle: { fontFamily: "Segoe UI, Microsoft YaHei UI, Microsoft YaHei, sans-serif" },
      tooltip: { trigger: "axis", axisPointer: { type: "cross", lineStyle: { color: "#C6CAD8" } }, backgroundColor: "#1A1D2B", borderColor: "#343A4D", textStyle: { color: "#E4E7F0", fontSize: 11 } },
      axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
      legend: { top: 12, left: 54, data: ["价格", "动量均线", "基准"], textStyle: { color: "#8B90A7", fontSize: 11 }, itemWidth: 18, itemHeight: 8 },
      grid: [
        { left: 58, right: 22, top: 48, height: "62%" },
        { left: 58, right: 22, top: "76%", height: "13%" }
      ],
      xAxis: [
        { type: "category", data: dates, boundaryGap: true, axisLine: { lineStyle: { color: "#343A4D" } }, axisLabel: { color: "#8B90A7", fontSize: 11 }, axisTick: { show: false }, splitLine: { show: false }, min: "dataMin", max: "dataMax" },
        { type: "category", gridIndex: 1, data: dates, boundaryGap: true, axisLine: { lineStyle: { color: "#343A4D" } }, axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false }, min: "dataMin", max: "dataMax" }
      ],
      yAxis: [
        { scale: true, axisLine: { show: false }, axisLabel: { color: "#8B90A7", fontSize: 11 }, splitLine: { lineStyle: { color: "#242938" } }, splitNumber: 5 },
        { scale: true, gridIndex: 1, axisLine: { show: false }, axisLabel: { color: "#6F7488", fontSize: 11 }, splitLine: { show: false }, splitNumber: 2 }
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], start: 12, end: 100 },
        { type: "slider", xAxisIndex: [0, 1], bottom: 5, height: 15, borderColor: "#262B3A", backgroundColor: "#141721", fillerColor: "rgba(79,195,247,.16)", handleStyle: { color: "#4FC3F7" }, textStyle: { color: "#8B90A7", fontSize: 9 } }
      ],
      brush: { toolbox: ["rect", "clear"], xAxisIndex: 0, brushStyle: { borderColor: "#4FC3F7", color: "rgba(79,195,247,.12)" } },
      series: [
        {
          name: "价格", type: "candlestick", data: researchBars.map((point) => [point.open, point.close, point.low, point.high]),
          itemStyle: { color: "#FF6B6B", color0: "#3CCB7F", borderColor: "#FF6B6B", borderColor0: "#3CCB7F" }
        },
        {
          name: "动量均线", type: "line", showSymbol: false, smooth: true, lineStyle: { color: "#4FC3F7", width: 1.8 }, data: researchBars.map((point) => point.value)
        },
        {
          name: "基准", type: "line", showSymbol: false, lineStyle: { color: "#FFB74D", width: 1, type: "dashed", opacity: .8 }, data: researchBars.map((point) => point.benchmark)
        },
        {
          name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1,
          itemStyle: { color: (params: { dataIndex: number }) => researchBars[params.dataIndex].close >= researchBars[params.dataIndex].open ? "rgba(255,107,107,.55)" : "rgba(60,203,127,.55)" },
          data: researchBars.map((point) => point.volume)
        }
      ]
    });
    chart.on("click", (params) => {
      const point = researchBars[params.dataIndex ?? 0];
      if (!point) return;
      focusContext({
        kind: "research-point", eyebrow: "价格 / 成交量证据", title: `${point.date} · ${point.close.toLocaleString("zh-CN")}`,
        summary: "图表点选已同步到价格、成交量、可用时间与来源证据。",
        facts: [
          { label: "OHLC", value: `${point.open} / ${point.high} / ${point.low} / ${point.close}` },
          { label: "成交量", value: `${point.volume}M` },
          { label: "生效时间", value: `${point.date}-28 15:00 CST` },
          { label: "可用时间", value: `${point.date}-28 15:05 CST` }
        ],
        provenance: "中国日线复权 · 开发数据 / hash demo:74c2…9f1a",
        trace: "chart.point.selected → research.case.updated → chart/ledger interpreted → inspector.explained"
      });
    });
    chart.on("brushSelected", (...args: unknown[]) => {
      const params = args[0] as { batch?: { areas?: unknown[] }[] };
      const selectedAreas = params.batch?.reduce((count, batch) => count + (batch.areas?.length ?? 0), 0) ?? 0;
      if (selectedAreas === 0) return;
      focusContext({
        kind: "research-event", eyebrow: "框选研究窗口", title: "框选区间 · 18 期样本",
        summary: "所选区间已映射到事件、相对强弱、因子覆盖与证据链。",
        facts: [{ label: "窗口", value: "2025-01 → 2026-06" }, { label: "样本", value: "18 期" }, { label: "覆盖率", value: "96.8%" }],
        provenance: "确定性前端开发数据提供器 · DeterministicFrontendDemoProvider/v1",
        trace: "chart.brush.selected → window.updated → overlays/analytics interpreted → inspector.explained"
      });
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [focusContext]);

  const inspectEvent = (event: typeof researchEvents[number]) => {
    setSelectedEventId(event.id);
    focusContext({
      kind: "research-event", eyebrow: "事件 / 账本证据", title: `${event.label} · ${event.date}`,
      summary: `${event.detail}。事件选择已联动主图、研究案例与来源证据。`,
      facts: [
        { label: "事件 ID", value: event.id }, { label: "可用时间", value: `${event.available} CST` },
        { label: "生效期间", value: event.date }, { label: "研究案例", value: "动量研究 / 2026 Q2" }
      ],
      provenance: "EventLedger/demo-v4 · content hash demo:5a91…ce20",
      trace: "event.selected → research.session.updated → chart/event interpreted → inspector.explained → evidence.trace.ready"
    }, `${event.label} / ${event.id}`);
  };

  return <section className="panel-page research-workspace" data-primary-panel="research-chart" data-major-panel>
    <header className="research-context">
      <div className="instrument"><small>研究案例 · 中国 A 股 / 600519.SH</small><h1>贵州茅台 <span>1,562.40</span><em>+1.28%</em></h1><p>12 月动量 · 2023-01 → 2026-06</p></div>
      <div className="context-facts"><span><small>股票池 · Universe</small>中国大盘股 @v12</span><span><small>可用时间</small>2026-06-30 15:05 CST</span><TruthMark detail="来源可追溯"/></div>
      <div className="research-actions"><div className="context-tools" aria-label="研究上下文工具"><button data-action="research-universe" aria-pressed={universeOpen} onClick={() => { setUniverseOpen(!universeOpen); setAnalyticsOpen(false); }}>股票池</button><button data-action="research-analytics" aria-pressed={analyticsOpen} onClick={() => { setAnalyticsOpen(!analyticsOpen); setUniverseOpen(false); }}>分析</button></div><button className={running ? "danger" : "primary"} aria-pressed={running} onClick={() => setRunning(!running)}><Icon name={running ? "close" : "pulse"} size={14}/>{running ? "停止" : "运行研究"}</button></div>
    </header>
    <div className="research-stage">
      <MetricRail className="research-metrics" items={[
        { label: "区间收益", value: "+28.42%", tone: "positive" },
        { label: "相对基准", value: "+11.36%", tone: "positive" },
        { label: "IC 均值", value: "0.071" },
        { label: "最大回撤", value: "-8.31%", tone: "negative" }
      ]}/>
      <div className="chart-mode-line"><b role="status" aria-live="polite">{running ? "开发研究运行中" : "覆盖率 96.8% · 研究就绪"}</b></div>
      <div ref={host} className="echart primary-canvas" data-testid="research-echart" data-primary-canvas />
    </div>
    <div className="event-ledger" aria-label="研究事件带">
      <b>事件 / 账本</b>{researchEvents.map((event) => <button key={event.id} data-research-event={event.id} className={selectedEventId === event.id ? "selected" : ""} aria-pressed={selectedEventId === event.id} onClick={() => inspectEvent(event)}><time>{event.date}</time><span>{event.label}</span><small>{event.detail}</small></button>)}
    </div>
    {analyticsOpen && <div className="context-drawer analytics-drawer" role="region" aria-label="二级分析" data-testid="research-analytics-drawer" data-major-panel><PaneHeading eyebrow="二级分析" title="因子诊断与事件证据" actions={<button onClick={() => setAnalyticsOpen(false)} aria-label="关闭二级分析"><Icon name="close" size={15}/></button>}/><ResearchAnalyticsContent /></div>}
    {universeOpen && <div className="context-drawer universe-drawer" role="region" aria-label="股票池构建器" data-testid="universe-drawer" data-major-panel><PaneHeading eyebrow="聚焦工作流" title="股票池构建器 · Universe" actions={<button data-action="universe-close" onClick={() => setUniverseOpen(false)} aria-label="关闭股票池构建器"><Icon name="close" size={15}/></button>}/><UniverseBuilderContent /></div>}
  </section>;
}

export function UniverseBuilderPanel() {
  return <section className="panel-page standalone-secondary" data-testid="universe-builder" data-major-panel><UniverseBuilderContent /></section>;
}

function UniverseBuilderContent() {
  const mode = useWorkbench((state) => state.selectedUniverseMode);
  const choose = useWorkbench((state) => state.setUniverseMode);
  const focusContext = useWorkbench((state) => state.focusContext);
  const [actionReceipt, setActionReceipt] = useState("Universe 草案就绪");
  const current = universeModes.find((item) => item.id === mode) ?? universeModes[0];

  return <div className="universe-workflow">
    <div className="constructor-list"><h3>九类构造器</h3>{universeModes.map((item, index) => <button key={item.id} className={mode === item.id ? "active" : ""} data-universe-mode={item.id} onClick={() => choose(item.id)}><i>{String(index + 1).padStart(2, "0")}</i><span><b>{item.name}</b><small>{item.detail}</small></span></button>)}</div>
    <div className="constructor-config">
      <div className="section-head"><div><small>股票池构造器 · Universe</small><h2>{current.name}</h2></div><span className="version">UniverseVersion/demo-v13</span></div>
      <Config mode={mode} />
      <div className="preview-head"><b>版本化预览</b><span>5,184 → 1,842 · 截止时间 · as-of 2026-06-30</span></div>
      <div className="symbol-grid"><div className="grid-head"><span>代码</span><span>名称</span><span>变动</span><span>因子分位</span></div>{symbols.map((row) => <button key={row[0]} className={row[0] === "INVALID-X" ? "unresolved" : ""} onClick={() => focusContext({ kind: "universe", eyebrow: "标的池成员 · UNIVERSE MEMBER", title: `${row[0]} · ${row[1]}`, summary: "证券已从 Universe 预览映射到研究案例与来源证据。", facts: [{ label: "变动", value: row[2] }, { label: "因子分位", value: row[3] }, { label: "截止时间 · As-of", value: "2026-06-30" }], provenance: "UniverseVersion/demo-v13", trace: "universe.member.selected → research.case.updated → inspector.explained" })}>{row.map((cell) => <span key={cell}>{cell}</span>)}</button>)}</div>
      {mode === "csv-tsv-import" && <div className="import-preview"><div><b>CSV/TSV 导入解析预览</b><small>显式保留未解析行，不静默纳入 Universe。</small></div><label className="file-button">选择 CSV/TSV<input type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" /></label><span className="warn">未解析：INVALID-X</span></div>}
      <div className="actions"><span className="action-receipt" role="status" aria-live="polite">{actionReceipt}</span><button onClick={() => setActionReceipt("UniverseVersion/demo-v13 已保存到前端开发会话")}>保存为新版本</button><button className="primary" onClick={() => setActionReceipt("UniverseVersion/demo-v13 已应用到项目上下文 · ProjectContext")}>应用到项目上下文</button></div>
    </div>
  </div>;
}

function Config({ mode }: { mode: UniverseMode }) {
  if (mode === "nested-condition") return <div className="condition-tree"><b>AND</b><div>市值 ≥ 100 亿</div><div><b>OR</b><span>ROE ≥ 12%</span><span>动量前 20%</span></div><button>＋ 添加条件组</button></div>;
  if (mode === "factor-top-bottom") return <div className="form-grid"><label>因子<select><option>12 月动量</option><option>质量组合</option></select></label><label>方向<select><option>头部 N</option><option>尾部 N</option></select></label><label>数量 N<input type="number" defaultValue="50" /></label></div>;
  if (mode === "custom-symbols") return <div className="token-input"><span>600519.SH ×</span><span>300750.SZ ×</span><input aria-label="添加证券代码" placeholder="输入代码后回车" /></div>;
  if (mode === "saved-reference") return <div className="form-grid"><label>引用版本<select><option>UniverseVersion/demo-v12</option><option>UniverseVersion/demo-v11</option></select></label><label>截止时间 · As-of<input type="date" defaultValue="2026-06-30" /></label></div>;
  return <div className="form-grid"><label>市场 / 分类<select><option>沪深 A 股</option><option>沪深300</option><option>中信一级 / 电子</option><option>AI 基础设施</option></select></label><label>截止时间 · As-of<input type="date" defaultValue="2026-06-30" /></label><label>停牌处理<select><option>保留并标记</option><option>排除</option></select></label></div>;
}

export function ResearchAnalyticsPanel() {
  return <section className="panel-page standalone-secondary analytics-page" data-major-panel><ResearchAnalyticsContent /></section>;
}

function ResearchAnalyticsContent() {
  const [tab, setTab] = useState("分组收益");
  const tabs = ["分组收益", "IC / 衰减", "覆盖率", "相关性", "事件元数据"];
  const copy: Record<string, string> = {
    "分组收益": "Q5 − Q1 年化差值 +8.4%，样本与主图所选研究区间一致。",
    "IC / 衰减": "IC(1D) 0.071 → IC(20D) 0.028；衰减曲线来自固定开发序列。",
    "覆盖率": "当前覆盖率 96.8%；缺失值使用中性灰并保留来源标记。",
    "相关性": "与质量混合因子相关系数 0.23；事件窗口已对齐。",
    "事件元数据": "rebalance / earnings-window / ledger 三类证据可回溯。"
  };
  return <div className="analytics-workflow">
    <div className="mini-tabs">{tabs.map((item) => <button className={item === tab ? "active" : ""} onClick={() => setTab(item)} key={item}>{item}</button>)}</div>
    <div className="analytics-content"><div className="histogram" aria-label="因子分布直方图">{[34,48,69,92,110,126,118,94,61,42,29].map((height, index) => <i key={index} style={{ height }} />)}</div><div className="analytics-notes"><span className="truth-line"><i /> 开发数据</span><h3>{tab}</h3><p>{copy[tab]}</p><dl><dt>相关性 ID</dt><dd>demo-corr-2026q2</dd><dt>可用时间</dt><dd>2026-06-30 15:05 CST</dd><dt>来源</dt><dd>确定性前端开发数据提供器 · DeterministicFrontendDemoProvider/v1</dd></dl></div></div>
  </div>;
}
