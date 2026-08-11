export const LAB_IDS = ["research", "strategy", "model", "backtest", "result"] as const;
export type LabId = (typeof LAB_IDS)[number];

export type TruthClass = "DEMO" | "FORMAL" | "UNAVAILABLE";
export type ModelFamily = "LightGBM" | "XGBoost" | "CatBoost" | "sklearn-linear" | "sklearn-tree-ensemble" | "PyTorch-deep" | "custom-plugin";
export type StudyState = "ready" | "running" | "paused" | "cancelled" | "checkpointed" | "completed";
export type StrategyMode = "visual" | "code" | "split";
export type UniverseMode = "all-shares" | "index" | "industry" | "concept" | "custom-symbols" | "nested-condition" | "factor-top-bottom" | "saved-reference" | "csv-tsv-import";

export interface StrategyDraft {
  id: string;
  version: number;
  mode: StrategyMode;
  code: string;
  acceptedHunks: string[];
  rejectedHunks: string[];
  selectedNodeId: string | null;
  validation: "not-run" | "valid" | "invalid";
  handoffId: string | null;
}

export interface ModelState {
  family: ModelFamily;
  datasetVersion: string;
  label: string;
  splitPlan: "chronological" | "rolling" | "expanding" | "purge-embargo" | "walk-forward";
  selectedRunIds: string[];
  studyState: StudyState;
  checkpoint: number;
  modelVersion: string | null;
  predictionSignalVersion: string | null;
}

export interface PersistedWorkspace {
  activeLab: LabId;
  inspectorOpen: boolean;
  bottomOpen: boolean;
  activeProject: string;
  selectedAsset: string | null;
  selectedUniverseMode: UniverseMode;
  dockLayouts: Partial<Record<LabId, unknown>>;
  strategy: StrategyDraft;
  model: ModelState;
  executedCommandIds: string[];
  commandExecutionCount: Record<string, number>;
  savedAt: string | null;
}

export interface DesktopCommandEnvelope {
  id: string;
  name: "workspace.save" | "workspace.reset" | "study.resume" | "study.pause" | "study.cancel" | "study.checkpoint" | "strategy.validate" | "strategy.handoff";
  issuedAt: string;
}

export interface CommandReceipt {
  id: string;
  accepted: boolean;
  duplicate: boolean;
  executionCount: number;
}

export function applyCommandExactlyOnce(current: PersistedWorkspace, command: DesktopCommandEnvelope): { state: PersistedWorkspace; receipt: CommandReceipt } {
  const previous = current.commandExecutionCount[command.id] ?? 0;
  if (current.executedCommandIds.includes(command.id)) return { state: structuredClone(current), receipt: { id: command.id, accepted: false, duplicate: true, executionCount: previous } };
  const state = structuredClone(current);
  state.executedCommandIds = [...state.executedCommandIds.slice(-199), command.id];
  state.commandExecutionCount = { ...state.commandExecutionCount, [command.id]: previous + 1 };
  if (command.name === "study.resume") state.model.studyState = "running";
  if (command.name === "study.pause") state.model.studyState = "paused";
  if (command.name === "study.cancel") state.model.studyState = "cancelled";
  if (command.name === "study.checkpoint") { state.model.studyState = "checkpointed"; state.model.checkpoint += 1; }
  return { state, receipt: { id: command.id, accepted: true, duplicate: false, executionCount: 1 } };
}

export interface DesktopBridge {
  loadWorkspace(): Promise<PersistedWorkspace>;
  saveWorkspace(state: PersistedWorkspace): Promise<PersistedWorkspace>;
  resetWorkspace(): Promise<PersistedWorkspace>;
  executeCommand(command: DesktopCommandEnvelope): Promise<CommandReceipt>;
  runtimeInfo(): Promise<{ electron: string; platform: string; storePath: string; agentEvidenceMode: "LIVE_READ_ONLY" | "DEVELOPMENT_INTEGRATION_FIXTURE" }>;
}

export const DEFAULT_STRATEGY_CODE = `# V3 StrategyDraft · DEMO / NOT FORMAL FINANCIAL OUTPUT
universe = Universe.ref("CN-LARGE-CAP@v12")
signal = rank(momentum_12m) * 0.65 + rank(quality) * 0.35
portfolio = top_n(signal, 50).equal_weight()
rebalance(portfolio, frequency="monthly")`;

export const DEFAULT_WORKSPACE: PersistedWorkspace = {
  activeLab: "research",
  inspectorOpen: false,
  bottomOpen: false,
  activeProject: "Momentum Research / 2026 Q2",
  selectedAsset: "因子 / Momentum 12M",
  selectedUniverseMode: "all-shares",
  dockLayouts: {},
  strategy: {
    id: "strategy-draft-demo-001",
    version: 8,
    mode: "visual",
    code: DEFAULT_STRATEGY_CODE,
    acceptedHunks: [],
    rejectedHunks: [],
    selectedNodeId: "factor-momentum",
    validation: "not-run",
    handoffId: null
  },
  model: {
    family: "LightGBM",
    datasetVersion: "DatasetVersion/demo-cn-factor-v12",
    label: "next_20d_excess_return",
    splitPlan: "walk-forward",
    selectedRunIds: ["RUN-018"],
    studyState: "checkpointed",
    checkpoint: 18,
    modelVersion: "ModelVersion/demo-lgbm-v4",
    predictionSignalVersion: "PredictionSignalVersion/demo-alpha-v3"
  },
  executedCommandIds: [],
  commandExecutionCount: {},
  savedAt: null
};

export const DEMO_TRUTH = {
  classification: "DEMO" as const,
  label: "DEMO / NOT FORMAL FINANCIAL OUTPUT",
  provenance: "DeterministicFrontendDemoProvider/v1",
  wave3: "RECOVERED_FROM_PRODUCT_DESIGN_NOT_PRIOR_WAVE3_ACCEPTANCE"
};
