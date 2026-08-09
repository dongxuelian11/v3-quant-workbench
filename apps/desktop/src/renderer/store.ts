import { create } from "zustand";
import { DEFAULT_WORKSPACE, type LabId, type ModelFamily, type PersistedWorkspace, type StrategyMode, type UniverseMode } from "../../../../packages/contracts/src/index";

declare global { interface Window { v3Desktop: import("../../../../packages/contracts/src/index").DesktopBridge } }

type Store = PersistedWorkspace & {
  hydrated: boolean;
  inspectorTitle: string;
  runtime: string;
  hydrate(): Promise<void>;
  setLab(lab: LabId): void;
  select(title: string): void;
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
  ...structuredClone(DEFAULT_WORKSPACE), hydrated: false, inspectorTitle: "Momentum 12M", runtime: "Electron",
  hydrate: async () => { const loaded = await window.v3Desktop.loadWorkspace(); const info = await window.v3Desktop.runtimeInfo(); set({ ...loaded, hydrated: true, runtime: `Electron ${info.electron}` }); },
  setLab: (activeLab) => { set({ activeLab, inspectorTitle: `${activeLab[0].toUpperCase()}${activeLab.slice(1)} Context` }); laterSave(get); },
  select: (inspectorTitle) => { set({ inspectorTitle, selectedAsset: inspectorTitle }); laterSave(get); },
  toggleInspector: () => { set((s) => ({ inspectorOpen: !s.inspectorOpen })); laterSave(get); },
  toggleBottom: () => { set((s) => ({ bottomOpen: !s.bottomOpen })); laterSave(get); },
  setUniverseMode: (selectedUniverseMode) => { set({ selectedUniverseMode, inspectorTitle: `Universe · ${selectedUniverseMode}` }); laterSave(get); },
  setStrategyMode: (mode) => { set((s) => ({ strategy: { ...s.strategy, mode } })); laterSave(get); },
  setStrategyCode: (code) => { set((s) => ({ strategy: { ...s.strategy, code, version: s.strategy.version + 1 } })); laterSave(get); },
  selectNode: (id, inspectorTitle) => { set((s) => ({ inspectorTitle, strategy: { ...s.strategy, selectedNodeId: id } })); laterSave(get); },
  reviewHunk: (id, decision) => { set((s) => ({ strategy: { ...s.strategy, acceptedHunks: decision === "accept" ? [...new Set([...s.strategy.acceptedHunks, id])] : s.strategy.acceptedHunks.filter((x) => x !== id), rejectedHunks: decision === "reject" ? [...new Set([...s.strategy.rejectedHunks, id])] : s.strategy.rejectedHunks.filter((x) => x !== id) } })); laterSave(get); },
  validateStrategy: () => { set((s) => ({ strategy: { ...s.strategy, validation: s.strategy.code.includes("Universe.ref") ? "valid" : "invalid" } })); laterSave(get); },
  createHandoff: () => { set((s) => ({ strategy: { ...s.strategy, handoffId: `BacktestHandoffDraft/demo-v${s.strategy.version}` } })); laterSave(get); },
  setModelFamily: (family) => { set((s) => ({ model: { ...s.model, family }, inspectorTitle: `模型族 · ${family}` })); laterSave(get); },
  setModelState: (studyState) => { set((s) => ({ model: { ...s.model, studyState, checkpoint: studyState === "checkpointed" ? s.model.checkpoint + 1 : s.model.checkpoint } })); laterSave(get); },
  toggleRun: (id) => { set((s) => ({ model: { ...s.model, selectedRunIds: s.model.selectedRunIds.includes(id) ? s.model.selectedRunIds.filter((x) => x !== id) : [...s.model.selectedRunIds, id] }, inspectorTitle: `Run · ${id}` })); laterSave(get); },
  saveDockLayout: async (lab, layout) => { set((s) => ({ dockLayouts: { ...s.dockLayouts, [lab]: layout } })); await get().save(); },
  save: async () => { const saved = await window.v3Desktop.saveWorkspace(persisted(get())); set({ savedAt: saved.savedAt }); },
  reset: async () => { const next = await window.v3Desktop.resetWorkspace(); set({ ...next, inspectorTitle: "Momentum 12M" }); }
}));
