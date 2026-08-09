import React, { useCallback, useRef } from "react";
import { DockviewReact, type DockviewApi, type DockviewReadyEvent } from "dockview-react";
import { ResearchChartPanel, ResearchAnalyticsPanel, UniverseBuilderPanel } from "./ResearchPanels";
import { StrategyDraftPanel, StrategyReviewPanel } from "./StrategyPanels";
import { ModelRunsPanel, ModelStudyPanel, ModelVersionPanel } from "./ModelPanels";
import { BacktestPanel, ResultPanel } from "./BacktestResultPanels";
import { useWorkbench } from "../store";

const components = {
  researchChart: ResearchChartPanel, researchAnalytics: ResearchAnalyticsPanel, universeBuilder: UniverseBuilderPanel,
  strategyDraft: StrategyDraftPanel, strategyReview: StrategyReviewPanel,
  modelRuns: ModelRunsPanel, modelStudy: ModelStudyPanel, modelVersion: ModelVersionPanel,
  backtest: BacktestPanel, result: ResultPanel
};

const defaults = {
  research: [["research-chart", "研究图表", "researchChart"], ["universe-builder", "Universe Builder", "universeBuilder"], ["research-analytics", "研究分析", "researchAnalytics"]],
  strategy: [["strategy-draft", "StrategyDraft · Visual / Code / Split", "strategyDraft"], ["strategy-review", "Proposal Diff · Hunk Review", "strategyReview"]],
  model: [["model-runs", "Run / Dataset / SplitPlan", "modelRuns"], ["model-study", "Study / Trial / HPO", "modelStudy"], ["model-version", "ModelVersion / Signal", "modelVersion"]],
  backtest: [["backtest-surface", "Backtest Lab · Demo", "backtest"]],
  result: [["result-surface", "Result Lab · Demo", "result"]]
} as const;

export function Workbench() {
  const activeLab = useWorkbench((s) => s.activeLab);
  const layouts = useWorkbench((s) => s.dockLayouts);
  const saveDockLayout = useWorkbench((s) => s.saveDockLayout);
  const toggleInspector = useWorkbench((s) => s.toggleInspector);
  const apiRef = useRef<DockviewApi | null>(null);

  const createDefault = useCallback((api: DockviewApi) => {
    api.clear(); const defs = defaults[activeLab];
    const first = defs[0]; api.addPanel({ id: first[0], title: first[1], component: first[2] });
    defs.slice(1).forEach((item, index) => api.addPanel({ id: item[0], title: item[1], component: item[2], position: { referencePanel: first[0], direction: index === 0 ? "right" : "below" } }));
  }, [activeLab]);

  const onReady = useCallback((event: DockviewReadyEvent) => {
    apiRef.current = event.api;
    const saved = layouts[activeLab];
    try { if (saved) event.api.fromJSON(saved as Parameters<DockviewApi["fromJSON"]>[0]); else createDefault(event.api); } catch { createDefault(event.api); }
    event.api.onDidLayoutChange(() => { void saveDockLayout(activeLab, event.api.toJSON()); });
  }, [activeLab, layouts, createDefault, saveDockLayout]);

  const split = () => {
    const api = apiRef.current; if (!api) return;
    const id = `${activeLab}-notes-${Date.now()}`;
    api.addPanel({ id, title: "临时诊断", component: activeLab === "research" ? "researchAnalytics" : activeLab === "strategy" ? "strategyReview" : activeLab === "model" ? "modelVersion" : activeLab, position: { direction: "right" } });
  };
  const activateFirst = () => apiRef.current?.panels[0]?.api.setActive();
  const closeActive = () => apiRef.current?.activePanel?.api.close();
  const restore = () => { const api = apiRef.current; const saved = layouts[activeLab]; if (api && saved) api.fromJSON(saved as Parameters<DockviewApi["fromJSON"]>[0]); };
  const reset = () => { if (apiRef.current) createDefault(apiRef.current); };

  return <div className="workbench-frame" data-lab-workbench={activeLab}>
    <div className="workbench-toolbar"><div><b>{activeLab.toUpperCase()} LAB</b><span>Dockview 工作区 · 独立布局</span></div><div><button data-action="dock-activate" onClick={activateFirst}>激活</button><button data-action="dock-split" onClick={split}>分屏/停靠</button><button data-action="dock-close" onClick={closeActive}>关闭活动面板</button><button data-action="dock-restore" onClick={restore}>恢复</button><button data-action="dock-reset" onClick={reset}>重置</button><button onClick={toggleInspector}>检查器</button></div></div>
    <div className="dock-host"><DockviewReact key={activeLab} className="dockview-theme-abyss" components={components} onReady={onReady} /></div>
  </div>;
}
