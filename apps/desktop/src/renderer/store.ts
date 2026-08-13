import { create } from "zustand";
import { DEFAULT_WORKSPACE, type LabId, type ModelFamily, type PersistedWorkspace, type StrategyMode, type UniverseMode } from "../../../../packages/contracts/src/index";

declare global { interface Window { v3Desktop: import("../../../../packages/contracts/src/index").DesktopBridge } }

export type EvidenceFact = { label: string; value: string };
export type InspectorEvidence = {
  kind: "research-event" | "research-point" | "universe" | "strategy-node" | "strategy-review" | "model-run" | "backtest" | "result" | "general";
  eyebrow: string;
  title: string;
  summary: string;
  facts: EvidenceFact[];
  provenance: string;
  trace: string;
};

const DEFAULT_EVIDENCE: InspectorEvidence = {
  kind: "general",
  eyebrow: "RESEARCH CASE CONTEXT",
  title: "Momentum 12M",
  summary: "同一研究案例中的图表、事件、版本与证据上下文。",
  facts: [
    { label: "Project", value: "Momentum Research / 2026 Q2" },
    { label: "Dataset", value: "CN Daily Adjusted · Demo" },
    { label: "Available time", value: "2026-06-30 15:05 CST" }
  ],
  provenance: "DeterministicFrontendDemoProvider/v1",
  trace: "context.loaded → panel.interpreted → inspector.ready"
};

type Store = PersistedWorkspace & {
  hydrated: boolean;
  inspectorTitle: string;
  inspectorEvidence: InspectorEvidence;
  runtime: string;
  agentEvidenceMode: "LIVE_READ_ONLY" | "DEVELOPMENT_INTEGRATION_FIXTURE";
  hydrate(): Promise<void>;
  setLab(lab: LabId): void;
  select(title: string): void;
  focusContext(evidence: InspectorEvidence, asset?: string): void;
  toggleInspector(): void;
  toggleBottom(): void;
  setUniverseMode(mode: UniverseMode): void;
  setStrategyMode(mode: StrategyMode): void;
  setStrategyCode(code: string): void;
  selectNode(id: string, title: string): void;
  reviewHunk(id: string, decision: "accept" | "reject"): void;
  validateStrategy(): void;
  createHandoff(): void;
  setModelFamily(family: ModelFamily): void;
  setModelState(state: PersistedWorkspace["model"]["studyState"]): void;
  toggleRun(id: string): void;
  saveDockLayout(lab: LabId, layout: unknown): Promise<void>;
  save(): Promise<void>;
  reset(): Promise<void>;
};

const persisted = (state: Store): PersistedWorkspace => ({
  activeLab: state.activeLab, inspectorOpen: state.inspectorOpen, bottomOpen: state.bottomOpen,
  activeProject: state.activeProject, selectedAsset: state.selectedAsset, selectedUniverseMode: state.selectedUniverseMode,
  dockLayouts: state.dockLayouts, strategy: state.strategy, model: state.model,
  executedCommandIds: state.executedCommandIds, commandExecutionCount: state.commandExecutionCount, savedAt: state.savedAt
});

let saveTimer: number | undefined;
function laterSave(get: () => Store): void {
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => { void window.v3Desktop.saveWorkspace(persisted(get())); }, 180);
}

export const useWorkbench = create<Store>((set, get) => ({
  ...structuredClone(DEFAULT_WORKSPACE), hydrated: false, inspectorTitle: DEFAULT_EVIDENCE.title, inspectorEvidence: DEFAULT_EVIDENCE, runtime: "Electron", agentEvidenceMode: "LIVE_READ_ONLY",
  hydrate: async () => {
    const loaded = await window.v3Desktop.loadWorkspace();
    const info = await window.v3Desktop.runtimeInfo();
    set({ ...loaded, hydrated: true, runtime: `Electron ${info.electron}`, agentEvidenceMode: info.agentEvidenceMode, inspectorEvidence: DEFAULT_EVIDENCE, inspectorTitle: DEFAULT_EVIDENCE.title });
  },
  setLab: (activeLab) => {
    set({ activeLab, inspectorOpen: false, bottomOpen: false, inspectorTitle: `${activeLab[0].toUpperCase()}${activeLab.slice(1)} Context` });
    laterSave(get);
  },
  select: (inspectorTitle) => {
    set({ inspectorTitle, selectedAsset: inspectorTitle, inspectorEvidence: { ...DEFAULT_EVIDENCE, title: inspectorTitle, trace: "asset.selected → context.updated → inspector.ready" } });
    laterSave(get);
  },
  focusContext: (inspectorEvidence, asset) => {
    set({ inspectorEvidence, inspectorTitle: inspectorEvidence.title, selectedAsset: asset ?? inspectorEvidence.title, inspectorOpen: true });
    laterSave(get);
  },
  toggleInspector: () => { set((s) => ({ inspectorOpen: !s.inspectorOpen })); laterSave(get); },
  toggleBottom: () => { set((s) => ({ bottomOpen: !s.bottomOpen })); laterSave(get); },
  setUniverseMode: (selectedUniverseMode) => {
    set({ selectedUniverseMode, inspectorTitle: `Universe · ${selectedUniverseMode}`, inspectorEvidence: { ...DEFAULT_EVIDENCE, kind: "universe", eyebrow: "UNIVERSE CONSTRUCTOR", title: `Universe · ${selectedUniverseMode}`, trace: "universe.mode.selected → preview.rebuilt → provenance.guarded" } });
    laterSave(get);
  },
  setStrategyMode: (mode) => { set((s) => ({ strategy: { ...s.strategy, mode } })); laterSave(get); },
  setStrategyCode: (code) => { set((s) => ({ strategy: { ...s.strategy, code, version: s.strategy.version + 1 } })); laterSave(get); },
  selectNode: (id, title) => {
    set((s) => ({
      inspectorOpen: true,
      inspectorTitle: title,
      inspectorEvidence: {
        kind: "strategy-node", eyebrow: "STRATEGY NODE", title,
        summary: "节点选择已映射到 StrategyDraft、代码符号与验证上下文。",
        facts: [{ label: "Node ID", value: id }, { label: "Draft", value: `StrategyDraft/demo-v${s.strategy.version}` }, { label: "Validation", value: s.strategy.validation }],
        provenance: "StrategyDraft deterministic demo state", trace: "strategy.node.selected → draft.context.updated → inspector.explained"
      },
      strategy: { ...s.strategy, selectedNodeId: id }
    }));
    laterSave(get);
  },
  reviewHunk: (id, decision) => {
    set((s) => ({
      inspectorEvidence: {
        kind: "strategy-review", eyebrow: "PROPOSAL REVIEW", title: `Hunk ${id} · ${decision}`,
        summary: "提案决策仅更新当前 StrategyDraft 的审阅状态，不生成正式金融输出。",
        facts: [{ label: "Decision", value: decision.toUpperCase() }, { label: "Draft", value: `demo-v${s.strategy.version}` }],
        provenance: "Deterministic proposal fixture", trace: "proposal.hunk.reviewed → draft.review.updated → inspector.explained"
      },
      strategy: {
        ...s.strategy,
        acceptedHunks: decision === "accept" ? [...new Set([...s.strategy.acceptedHunks, id])] : s.strategy.acceptedHunks.filter((x) => x !== id),
        rejectedHunks: decision === "reject" ? [...new Set([...s.strategy.rejectedHunks, id])] : s.strategy.rejectedHunks.filter((x) => x !== id)
      }
    }));
    laterSave(get);
  },
  validateStrategy: () => { set((s) => ({ strategy: { ...s.strategy, validation: s.strategy.code.includes("Universe.ref") ? "valid" : "invalid" } })); laterSave(get); },
  createHandoff: () => { set((s) => ({ strategy: { ...s.strategy, handoffId: `BacktestHandoffDraft/demo-v${s.strategy.version}` } })); laterSave(get); },
  setModelFamily: (family) => {
    set((s) => ({
      model: { ...s.model, family }, inspectorTitle: `模型族 · ${family}`,
      inspectorEvidence: { ...DEFAULT_EVIDENCE, kind: "model-run", eyebrow: "MODEL CONFIGURATION", title: `模型族 · ${family}`, summary: "模型族选择已应用于当前 Demo 运行配置。", trace: "model.family.selected → run.config.updated → provenance.guarded" }
    }));
    laterSave(get);
  },
  setModelState: (studyState) => { set((s) => ({ model: { ...s.model, studyState, checkpoint: studyState === "checkpointed" ? s.model.checkpoint + 1 : s.model.checkpoint } })); laterSave(get); },
  toggleRun: (id) => {
    set((s) => ({
      model: { ...s.model, selectedRunIds: s.model.selectedRunIds.includes(id) ? s.model.selectedRunIds.filter((x) => x !== id) : [...s.model.selectedRunIds, id] },
      inspectorTitle: `Run · ${id}`,
      inspectorEvidence: { ...DEFAULT_EVIDENCE, kind: "model-run", eyebrow: "MODEL RUN", title: `Run · ${id}`, summary: "运行选择已同步到比较与诊断上下文。", trace: "model.run.selected → comparison.updated → inspector.ready" }
    }));
    laterSave(get);
  },
  saveDockLayout: async (lab, layout) => { set((s) => ({ dockLayouts: { ...s.dockLayouts, [lab]: layout } })); await get().save(); },
  save: async () => { const saved = await window.v3Desktop.saveWorkspace(persisted(get())); set({ savedAt: saved.savedAt }); },
  reset: async () => {
    const next = await window.v3Desktop.resetWorkspace();
    set({ ...next, inspectorTitle: DEFAULT_EVIDENCE.title, inspectorEvidence: DEFAULT_EVIDENCE });
  }
}));
