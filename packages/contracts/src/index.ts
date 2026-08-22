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
  /** Runtime-owned: exact command id -> binding evidence for fail-closed idempotency. */
  executedCommands?: Record<string, { name: string; issuedAt: string }>;
  /** Runtime-owned: durable project event cursors keyed by projectId. */
  projectEventCursors?: Record<string, number>;
  /** Runtime-owned: monotonically increasing persistence revision. */
  persistenceRevision?: number;
  /** Runtime-owned: store schema marker for forward compatibility checks. */
  runtimeMeta?: { storeSchemaVersion: number };
}

export const WORKSPACE_USER_FIELDS = [
  "activeLab", "inspectorOpen", "bottomOpen", "activeProject", "selectedAsset",
  "selectedUniverseMode", "dockLayouts", "strategy", "model"
] as const;

export const WORKSPACE_RUNTIME_FIELDS = [
  "executedCommandIds", "commandExecutionCount", "executedCommands",
  "projectEventCursors", "persistenceRevision", "runtimeMeta", "savedAt"
] as const;

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

export class CommandConflictError extends Error {
  readonly code = "COMMAND_ID_CONFLICT";
  readonly commandId: string;
  readonly previousName: string;
  readonly nextName: string;
  constructor(commandId: string, previousName: string, nextName: string) {
    super(`command id ${commandId} is already bound to ${previousName}; refusing conflicting ${nextName}`);
    this.name = "CommandConflictError";
    this.commandId = commandId;
    this.previousName = previousName;
    this.nextName = nextName;
  }
}

export function applyCommandExactlyOnce(current: PersistedWorkspace, command: DesktopCommandEnvelope): { state: PersistedWorkspace; receipt: CommandReceipt } {
  const previous = current.commandExecutionCount[command.id] ?? 0;
  const bound = current.executedCommands?.[command.id];
  if (bound) {
    if (bound.name !== command.name) throw new CommandConflictError(command.id, bound.name, command.name);
    return { state: structuredClone(current), receipt: { id: command.id, accepted: false, duplicate: true, executionCount: previous } };
  }
  if (current.executedCommandIds.includes(command.id)) {
    return { state: structuredClone(current), receipt: { id: command.id, accepted: false, duplicate: true, executionCount: previous } };
  }
  const state = structuredClone(current);
  // V1 keeps the full durable command ledger; long-term retention/epoch
  // compaction is deferred to V1.1. No slice-based eviction may re-execute.
  state.executedCommandIds = [...state.executedCommandIds, command.id];
  state.executedCommands = { ...(state.executedCommands ?? {}), [command.id]: { name: command.name, issuedAt: command.issuedAt } };
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
  windowState(): Promise<{ maximized: boolean }>;
  onWindowStateChanged(listener: (state: { maximized: boolean }) => void): () => void;
  windowControl(action: "minimize" | "toggle-maximize" | "close"): Promise<{ maximized: boolean }>;
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
  executedCommands: {},
  projectEventCursors: {},
  persistenceRevision: 0,
  runtimeMeta: { storeSchemaVersion: 1 },
  savedAt: null
};

export const DEMO_TRUTH = {
  classification: "DEMO" as const,
  label: "DEMO / NOT FORMAL FINANCIAL OUTPUT",
  provenance: "DeterministicFrontendDemoProvider/v1",
  wave3: "RECOVERED_FROM_PRODUCT_DESIGN_NOT_PRIOR_WAVE3_ACCEPTANCE"
};

// ---------------------------------------------------------------------------
// Desktop product runtime bridge DTOs (runtime-owned canonical views).
// These types mirror the frozen B3 read models that the Electron main process
// admits through closed adapters; the renderer never sees raw backend payloads
// or transport envelope fields.
// ---------------------------------------------------------------------------

export type ProductTruthState = "FORMAL" | "DEMO" | "UNAVAILABLE";

export type ProductBackendState =
  | "STOPPED" | "STARTING" | "HANDSHAKING" | "REPLAYING"
  | "READY" | "RECONNECTING" | "DISCONNECTED" | "CRASH_LOOP" | "SHUTTING_DOWN";

export type ProductBindingState =
  | "NO_CANONICAL_PROJECT_BOUND"
  | "PROJECT_BOUND"
  | "BINDING_STALE";

export interface ProductBindingRefs {
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly sessionId: string;
}

export interface ProductCapabilityView {
  readonly code: string;
  readonly truth_state: ProductTruthState;
  readonly reason_code?: string;
}

export interface ProductStatusView {
  readonly productVersion: string;
  readonly backendState: ProductBackendState;
  readonly bindingState: ProductBindingState;
  readonly boundProject: ProductBindingRefs | null;
  readonly capabilities: readonly ProductCapabilityView[];
  readonly buildManifestId: string | null;
  readonly buildIdentityState: "CLEAN" | "DIRTY" | "UNAVAILABLE";
}

export interface ProductContextFieldsView {
  readonly name?: string;
  readonly description?: string;
}

export interface ProjectContextView {
  readonly readModelVersion: "v3.project-context/1.0";
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly revisionNo: number;
  readonly canonicalHash: string;
  readonly contextFields: ProductContextFieldsView;
  readonly createdAt: string;
  readonly createdBy: string;
}

export interface SessionRestoreView {
  readonly readModelVersion: "v3.session-restore/1.0";
  readonly sessionRowId: string;
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly state: string;
  readonly openedAt: string;
}

export interface ProductTaskAttemptView {
  readonly attemptId: string | null;
  readonly ordinal: number;
  readonly state: string;
  readonly errorCategory: string | null;
}

export interface ProductTaskListFilter {
  readonly service?: "ProductEntryService";
  readonly state?: "SUCCEEDED";
}

export interface ProductTaskView {
  readonly readModelVersion: "v3.task/1.0";
  readonly taskId: string;
  readonly projectId: string;
  readonly operationId: string;
  readonly state: string;
  readonly stateVersion: number;
  readonly runId: string;
  /** Direct canonical Task -> Result relation; null is an explicit no-result state. */
  readonly resultId: string | null;
  readonly attempt: ProductTaskAttemptView;
  readonly outputs: Readonly<Record<string, string>>;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly terminalAt: string | null;
}

export interface ProductTaskEventView {
  readonly eventId: string;
  readonly projectSequence: number;
  readonly eventType: string;
  readonly occurredAt: string;
  /** Canonical result identity recorded by the durable TASK_SUCCEEDED event. */
  readonly resultId: string | null;
}

export interface ProductTaskEventsView {
  readonly items: readonly ProductTaskEventView[];
  readonly highWatermark: number;
}

export interface ProductResultView {
  readonly readModelVersion: "v3.result/1.0";
  readonly resultId: string;
  readonly projectId: string;
  readonly backtestRunId: string;
  readonly codeVersion: string | null;
  readonly buildManifestId: string | null;
  readonly state: string;
  readonly ledgerManifestArtifactId: string;
  readonly reconciliationArtifactId: string | null;
  readonly resultArtifact: ArtifactDescriptorView | null;
}

export interface ArtifactDescriptorView {
  readonly artifactId: string;
  readonly sha256: string;
  readonly byteSize: number;
  readonly mediaType: string;
  readonly role: string;
  readonly createdAt: string;
}

export interface ArtifactStreamTicketView {
  readonly mode: "STREAM_TICKET";
  readonly ticketId: string;
  readonly artifactId: string;
}

export interface BacktestSubmitOutcomeView {
  readonly taskId: string;
  readonly runId: string;
  readonly acceptedState: "QUEUED";
  readonly idempotentReplay: boolean;
}

export interface ProductBridgeErrorView {
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly operationId?: string;
}

export interface ConnectExistingProjectRequest {
  readonly projectId: string;
  readonly projectContextRevisionId: string;
}

export interface CreateProjectRequest {
  readonly displayName: string;
  readonly notes?: string;
}

/** Backend-minted clean-start project creation outcome (control protocol). */
export interface ProjectCreatedView {
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly displayName: string;
  readonly createdAt: string;
}

export interface ProjectListItemView {
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly displayName: string;
  readonly createdAt: string;
}

export interface ProjectsListView {
  readonly projects: readonly ProjectListItemView[];
  readonly hasMore: boolean;
}

export interface RunSpecEntryView {
  readonly runSpecId: string | null;
  readonly artifactId: string;
  readonly contentSha256: string | null;
  readonly projectContextRevisionId: string | null;
  readonly engineVersion: string | null;
  readonly createdAt: string | null;
  readonly executionAdapterVersionId: string | null;
  readonly status: "EXECUTABLE" | "UNAVAILABLE";
  readonly diagnostic: string | null;
}

export interface RunSpecsListView {
  readonly specs: readonly RunSpecEntryView[];
  readonly hasMore: boolean;
  readonly nextAfterArtifactId: string | null;
}

/** Target-canonical-authority research package reuse outcome. */
export interface ImportResearchPackageOutcomeView {
  readonly runSpecId: string;
  readonly runSpecArtifactId: string;
  readonly contextArtifactId: string;
  readonly alreadyImported: boolean;
  readonly sourceProjectId: string;
  readonly importedAt: string;
}

/** Closed Product Entry source intent; the main process supplies provider refs. */
export interface ProductResearchSubmitIntent {
  readonly symbol: string;
  readonly startDate: string;
  readonly endDate: string;
}

export interface ProductResearchSubmitOutcomeView {
  readonly truthState: "DEMO";
  readonly taskId: string;
  readonly runId: string;
  readonly acceptedState: "QUEUED";
  readonly idempotentReplay: boolean;
  readonly maturity: "PRODUCT_CONNECTED_CANDIDATE";
  readonly researchProfileId: "RESEARCH_FREE_DATA_V1";
  readonly strategyProfileId: "RESEARCH_CLOSE_RANK_TOP1_V1";
  readonly researchClassification: readonly ["RESEARCH_ONLY", "APPROXIMATE"];
  readonly truthAdmission: {
    readonly truth: "NOT_FORMAL";
    readonly admission: "PRE_ALPHA";
  };
  readonly eventCursor?: number;
}

/**
 * Narrow typed product bridge exposed to the renderer. There is deliberately
 * no generic request(operationId, payload) member: every method maps to one
 * admitted frozen operation and the Electron main process owns the transport
 * envelope (request_id, project binding, idempotency intent).
 */
export interface V3ProductRuntimeBridge {
  getProductStatus(): Promise<ProductStatusView>;
  getCapabilities(): Promise<readonly ProductCapabilityView[]>;
  getBoundProject(): Promise<ProductBindingRefs | null>;
  getProjectContext(): Promise<ProjectContextView>;
  restoreSession(): Promise<SessionRestoreView>;
  connectExistingProject(request: ConnectExistingProjectRequest): Promise<ProjectContextView>;
  listTasks(filter?: ProductTaskListFilter): Promise<readonly ProductTaskView[]>;
  getTask(taskId: string): Promise<ProductTaskView>;
  getTaskEvents(afterSequence: number, limit: number): Promise<ProductTaskEventsView>;
  getResult(resultId: string): Promise<ProductResultView>;
  getArtifactDescriptor(artifactId: string): Promise<ArtifactDescriptorView>;
  openArtifactStream(artifactId: string): Promise<ArtifactStreamTicketView>;
  submitExistingBacktestRunSpec(runSpecId: string): Promise<BacktestSubmitOutcomeView>;
  /** Projectless clean-start entry: backend mints all canonical identities. */
  createProject(request: CreateProjectRequest): Promise<ProjectCreatedView>;
  listProjects(): Promise<ProjectsListView>;
  /** Durable run-spec discovery with actual-artifact verification. */
  listBacktestRunSpecs(): Promise<RunSpecsListView>;
  /**
   * Target-authority reuse: the Electron main process owns the file chooser and
   * reads the selected V3 research package; the renderer never receives or
   * controls raw filesystem paths. The target must already own and verify the
   * package's source authority. Null = user cancelled the chooser.
   */
  importResearchPackage(): Promise<ImportResearchPackageOutcomeView | null>;
  /**
   * Product-connected, research-only source admission. The renderer supplies
   * only symbol/date intent; provider refs and the transport envelope are
   * owned by Electron main and no numeric market truth is accepted here.
   */
  submitResearch(request: ProductResearchSubmitIntent): Promise<ProductResearchSubmitOutcomeView>;
}
