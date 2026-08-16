import React, { useCallback, useRef, useState } from "react";
import { DockviewReact, type DockviewApi, type DockviewReadyEvent } from "dockview-react";
import { ResearchChartPanel, ResearchAnalyticsPanel, UniverseBuilderPanel } from "./ResearchPanels";
import { StrategyDraftPanel, StrategyReviewPanel } from "./StrategyPanels";
import { ModelRunsPanel, ModelStudyPanel, ModelVersionPanel, ModelWorkflowPanel } from "./ModelPanels";
import { BacktestPanel } from "./BacktestResultPanels";
import { ResultPanel } from "./ResultAnalyticsPanel";
import { useWorkbench } from "../store";
import { Icon } from "./PresentationSystem";
import { FactorWorkbench } from "./FactorWorkbench";

const LAYOUT_CONTRACT = "precision-workbench-v3";

const components = {
  researchChart: ResearchChartPanel,
  researchAnalytics: ResearchAnalyticsPanel,
  universeBuilder: UniverseBuilderPanel,
  strategyDraft: StrategyDraftPanel,
  strategyReview: StrategyReviewPanel,
  modelWorkflow: ModelWorkflowPanel,
  modelRuns: ModelRunsPanel,
  modelStudy: ModelStudyPanel,
  modelVersion: ModelVersionPanel,
  backtest: BacktestPanel,
  result: ResultPanel
};

const defaults = {
  research: ["research-chart", "研究 · 价格与证据", "researchChart"],
  strategy: ["strategy-draft", "策略草案 · StrategyDraft", "strategyDraft"],
  model: ["model-workflow", "模型 · 分阶段工作流", "modelWorkflow"],
  backtest: ["backtest-surface", "回测 · 执行复盘", "backtest"],
  result: ["result-surface", "结果 · 绩效分析", "result"]
} as const;

const questions = {
  research: "这只证券发生了什么，哪些证据能够证明？",
  strategy: "如何把研究假设变成可审阅、可交接的策略草案？",
  model: "哪个数据、模型与试验链路支持当前信号版本？",
  backtest: "这个实验在何种约束下产生了怎样的执行结果？",
  result: "结果表现如何，风险、归因与 lineage 是否一致？"
} as const;

export function Workbench() {
  const activeLab = useWorkbench((state) => state.activeLab);
  const layouts = useWorkbench((state) => state.dockLayouts);
  const saveDockLayout = useWorkbench((state) => state.saveDockLayout);
  const toggleInspector = useWorkbench((state) => state.toggleInspector);
  const toggleBottom = useWorkbench((state) => state.toggleBottom);
  const inspectorOpen = useWorkbench((state) => state.inspectorOpen);
  const bottomOpen = useWorkbench((state) => state.bottomOpen);
  const agentEvidenceMode = useWorkbench((state) => state.agentEvidenceMode);
  const [researchSurface, setResearchSurface] = useState<"canvas" | "factors">("canvas");
  const apiRef = useRef<DockviewApi | null>(null);

  const createDefault = useCallback((api: DockviewApi) => {
    api.clear();
    const panel = defaults[activeLab];
    api.addPanel({ id: panel[0], title: panel[1], component: panel[2] });
    window.localStorage.setItem("v3-layout-contract", LAYOUT_CONTRACT);
  }, [activeLab]);

  const onReady = useCallback((event: DockviewReadyEvent) => {
    apiRef.current = event.api;
    const saved = layouts[activeLab];
    const layoutContract = window.localStorage.getItem("v3-layout-contract");
    try {
      if (saved && layoutContract === LAYOUT_CONTRACT) event.api.fromJSON(saved as Parameters<DockviewApi["fromJSON"]>[0]);
      else createDefault(event.api);
    } catch {
      createDefault(event.api);
    }
    event.api.onDidLayoutChange(() => { void saveDockLayout(activeLab, event.api.toJSON()); });
  }, [activeLab, layouts, createDefault, saveDockLayout]);

  const createResearchPreset = () => {
    const api = apiRef.current;
    if (!api || activeLab !== "research") return;
    api.clear();
    const chart = api.addPanel({ id: "research-chart", title: "研究 · 价格与证据", component: "researchChart" });
    api.addPanel({ id: "research-analytics", title: "二级分析", component: "researchAnalytics", position: { referencePanel: "research-chart", direction: "below" } });
    api.addPanel({ id: "universe-builder", title: "股票池构建器 · Universe", component: "universeBuilder", position: { referencePanel: "research-analytics" } });
    window.setTimeout(() => chart.api.group.api.setSize({ height: Math.round(api.height * .68) }), 0);
  };

  const split = () => {
    const api = apiRef.current;
    if (!api) return;
    const id = `${activeLab}-secondary-${Date.now()}`;
    const component = activeLab === "research" ? "researchAnalytics" : activeLab === "strategy" ? "strategyReview" : activeLab === "model" ? "modelVersion" : activeLab;
    api.addPanel({ id, title: "上下文分析", component, position: { direction: "right" } });
  };

  const activateFirst = () => apiRef.current?.panels[0]?.api.setActive();
  const closeActive = () => apiRef.current?.activePanel?.api.close();
  const restore = () => {
    const api = apiRef.current;
    const saved = layouts[activeLab];
    if (api && saved) api.fromJSON(saved as Parameters<DockviewApi["fromJSON"]>[0]);
  };
  const reset = () => { if (apiRef.current) createDefault(apiRef.current); };

  return <div className="workbench-frame" data-lab-workbench={activeLab}>
    <div className="workbench-contextbar">
      <div className="workbench-question"><small>{activeLab === "research" ? "研究" : activeLab === "strategy" ? "策略" : activeLab === "model" ? "模型" : activeLab === "backtest" ? "回测" : "结果"}</small><span>{questions[activeLab]}</span></div>
      <div className="workbench-actions">
        {activeLab === "research" && <div className="research-surface-switch" role="group" aria-label="研究实验室视图"><button className={researchSurface === "canvas" ? "active" : ""} onClick={() => setResearchSurface("canvas")}>研究画布</button><button data-action="factor-library-open" className={researchSurface === "factors" ? "active" : ""} onClick={() => setResearchSurface("factors")}>因子库</button></div>}
        {activeLab === "research" && <button data-action="dock-preset" onClick={createResearchPreset} title="应用研究多面板预设"><Icon name="research" size={14}/><span>研究布局</span></button>}
        <button data-action="inspector-toggle" onClick={toggleInspector} aria-pressed={inspectorOpen} title="切换上下文检查器"><Icon name="inspector" size={14}/><span>检查器</span></button>
        <button data-action="operations-open" onClick={toggleBottom} aria-pressed={bottomOpen} title="切换任务与日志"><Icon name="operations" size={14}/><span>任务</span></button>
        <details className="dock-menu"><summary aria-label="工作区布局操作"><Icon name="more" size={16}/></summary><div>
          <small>布局操作</small>
          <button data-action="dock-activate" onClick={activateFirst}>激活首面板</button>
          <button data-action="dock-split" onClick={split}>分屏 / 停靠</button>
          <button data-action="dock-close" onClick={closeActive}>关闭活动面板</button>
          <button data-action="dock-restore" onClick={restore}>恢复已存布局</button>
          <button data-action="dock-reset" onClick={reset}>恢复默认布局</button>
        </div></details>
      </div>
    </div>
    <div className="dock-host">{activeLab === "research" && researchSurface === "factors" ? <FactorWorkbench fixtureMode={agentEvidenceMode === "DEVELOPMENT_INTEGRATION_FIXTURE"}/> : <DockviewReact key={activeLab} className="dockview-theme-abyss" components={components} onReady={onReady} />}</div>
  </div>;
}
