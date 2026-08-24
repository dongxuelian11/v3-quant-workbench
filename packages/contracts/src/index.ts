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
  runtimeMeta: { storeSchemaVersion: 2 },
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

export interface ProductPageRequest {
  /** Opaque owner-issued keyset cursor; callers must not parse or mint it. */
  readonly cursor?: string;
  readonly pageSize?: number;
}

export interface ProductTaskPageRequest extends ProductPageRequest {
  readonly filter?: ProductTaskListFilter;
}

export interface ProductTasksListView {
  readonly tasks: readonly ProductTaskView[];
  readonly hasMore: boolean;
  readonly nextCursor: string | null;
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
  readonly taskId: string;
  readonly projectSequence: number;
  readonly eventType: string;
  readonly occurredAt: string;
  /** Canonical result identity recorded by the durable TASK_SUCCEEDED event. */
  readonly resultId: string | null;
  readonly progress: ProductTaskProgressView | null;
}

export type ProductTaskProgressPhase =
  | "ACQUIRING"
  | "VALIDATING"
  | "COMPUTING"
  | "PUBLISHING"
  | "RECONCILING";

export interface ProductTaskProgressView {
  readonly phase: ProductTaskProgressPhase;
  readonly completedUnits: number;
  readonly totalUnits: number;
  readonly workUnit: string;
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

export interface ArtifactStreamBytesView {
  readonly artifactId: string;
  readonly sha256: string;
  readonly byteSize: number;
  readonly bytes: Uint8Array;
}

/** Renderer intent only; Electron main owns the native destination capability. */
export interface ProductArtifactExportIntent {
  readonly artifactId: string;
  readonly suggestedName: string;
}

/** Cancellation is literal NOT_RUN and never creates a backend Task. */
export type ProductArtifactExportOutcomeView =
  | { readonly state: "NOT_RUN" }
  | {
      readonly state: "COMPLETED";
      readonly taskId: string;
      readonly runId: string;
      readonly artifactId: string;
      readonly manifestArtifactId: string;
      readonly displayName: string;
      readonly sha256: string;
      readonly byteSize: number;
      readonly completedAt: string;
    };

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
  readonly nextCursor: string | null;
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
  readonly nextCursor: string | null;
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

/** Renderer-visible native selection: deliberately excludes every path. */
export interface LocalDataSourceSelectionView {
  readonly displayName: string;
  readonly byteSize: number;
  readonly mediaType: "text/csv" | "application/vnd.apache.parquet";
  readonly capabilityToken: string;
}

/** Explicit user-supplied local-data semantics plus a one-use main capability. */
export interface ProductLocalDataImportIntent {
  readonly capabilityToken: string;
  readonly volumeUnit: "SHARES" | "HANDS";
  readonly amountUnit: "CNY";
  readonly timezone: "Asia/Shanghai";
  readonly adjustment: "UNADJUSTED";
}

export interface ProductLocalDataImportOutcomeView {
  readonly taskId: string;
  readonly runId: string;
  readonly acceptedState: "QUEUED";
  readonly maturity: "PRODUCT_CONNECTED";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly checkpointResume: "UNAVAILABLE";
  readonly retry: "NEW_ATTEMPT_SAME_RUN_FROM_START";
  readonly sourceArtifactId: string;
  readonly eventCursor?: number;
}

export interface ProductFactorStudyIntent {
  readonly formulaSource: string;
  readonly analysisOutputName: string;
}

export interface ProductFactorStudyOutcomeView {
  readonly taskId: string;
  readonly runId: string;
  readonly acceptedState: "QUEUED";
  readonly maturity: "PRODUCT_CONNECTED";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly checkpointResume: "UNAVAILABLE";
  readonly retry: "NEW_ATTEMPT_SAME_RUN_FROM_START";
  readonly formulaDocumentVersionId: string;
  readonly analysisOutputName: string;
  readonly eventCursor?: number;
}

export interface ProductFactorMetricView {
  readonly status: "AVAILABLE" | "INSUFFICIENT_SAMPLE" | "NOT_AVAILABLE";
  readonly value: number | null;
  readonly reason: string | null;
}

export interface ProductFactorDailyAnalysisView {
  readonly sessionDate: string;
  readonly labelSessionDate: string;
  readonly status: "AVAILABLE" | "INSUFFICIENT_SAMPLE" | "NOT_AVAILABLE";
  readonly reason: string | null;
  readonly universeSize: number;
  readonly sampleSize: number;
  readonly coverage: number;
  readonly missingRate: number;
  readonly ic: ProductFactorMetricView;
  readonly rankIc: ProductFactorMetricView;
  readonly quantileReturns: readonly number[] | null;
  readonly longShortSpread: number | null;
  readonly turnover: ProductFactorMetricView;
  readonly diagnostics: readonly string[];
  readonly excludedReasonCounts: readonly Readonly<{ reason: string; count: number }>[];
}

export interface ProductFactorSummaryView {
  readonly schemaVersion: "v3.project-factor-summary/1.0.0";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly snapshotId: string;
  readonly universeVersionId: string;
  readonly sourceManifestArtifactId: string;
  readonly sourceManifestSha256: string;
  readonly formulaDocumentVersionId: string;
  readonly formulaDocumentArtifactId: string;
  readonly analysisOutputName: string;
  readonly analysisArtifactId: string;
  readonly outputs: readonly Readonly<{
    name: string;
    factorDefinitionVersionId: string;
    factorDefinitionArtifactId: string;
    materializationId: string;
    materializationArtifactId: string;
    outputType: "FLOAT_SERIES" | "BOOLEAN_SERIES";
    rowCount: number;
  }>[];
  readonly visualPreview: readonly Readonly<{
    sessionDate: string;
    instrumentId: string;
    open: number | null;
    high: number | null;
    low: number | null;
    close: number | null;
    volumeShares: number | null;
    amountCny: number | null;
    series: Readonly<Record<string, number | boolean | null>>;
  }>[];
  readonly analysis: Readonly<{
    factorAnalysisResultId: string;
    spec: Readonly<{
      forwardReturnHorizonSessions: 5;
      quantiles: 5;
      minimumInstrumentsPerDate: 20;
      minimumValidIcDates: 20;
      formationPrice: "RAW_CLOSE";
      labelPrice: "RAW_CLOSE";
      signalAvailability: "AFTER_SESSION_CLOSE";
    }>;
    aggregate: Readonly<{
      validDates: number;
      icMean: ProductFactorMetricView;
      icStd: ProductFactorMetricView;
      icir: ProductFactorMetricView;
      rankIcMean: ProductFactorMetricView;
      rankIcStd: ProductFactorMetricView;
      rankIcir: ProductFactorMetricView;
      yearlyDistribution: readonly Readonly<{
        year: number;
        validDates: number;
        icMean: ProductFactorMetricView;
        icStd: ProductFactorMetricView;
        icir: ProductFactorMetricView;
      }>[];
    }>;
    dailyResults: readonly ProductFactorDailyAnalysisView[];
  }>;
}

export interface ProductDataReadModelView {
  readonly schemaVersion: "v3.product-data-read-model/1.0.0";
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly displayName: string;
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly sourceType: "LOCAL_USER_SUPPLIED";
  readonly pitState: "PIT_UNPROVABLE";
  readonly mediaType: "text/csv" | "application/vnd.apache.parquet";
  readonly rowCount: number;
  readonly instrumentCount: number;
  readonly dateCoverageStart: string;
  readonly dateCoverageEnd: string;
  readonly partitionCount: number;
  readonly universeRole: "USER_DEFINED_STATIC";
  readonly qualityStatus: "PASS";
  readonly validationProfileId: "svp_local_user_supplied_v1";
  readonly capabilityReasons: Readonly<{
    pit: "PIT_UNPROVABLE";
    revision: "PROVIDER_REVISION_UNKNOWN";
    calendar: "OBSERVED_LOCAL_ROWS_NOT_FORMAL_TRADING_CALENDAR";
    status: "SOURCE_COLUMN_ABSENT_OR_NULL_WHEN_NOT_PROVIDED";
  }>;
  readonly volumeUnit: "SHARES";
  readonly amountUnit: "CNY";
  readonly adjustment: "UNADJUSTED";
  readonly rawCaptureId: string;
  readonly rawContentHash: string;
  readonly snapshotId: string;
  readonly normalizedPayloadHash: string;
  readonly universeVersionId: string;
  readonly importedAt: string;
  readonly rawArtifactId: string;
}

export type ProductStrategyPositionSizing =
  | "SINGLE_ASSET_FULL_WEIGHT"
  | "EQUAL_WEIGHT_ACTIVE_SIGNALS";

export type ProductResearchAssumptionMode =
  | "RESEARCH_APPROXIMATE"
  | "STRICT_FAIL_CLOSED";

export interface ProductResearchAssumptionProfileView {
  readonly mode: ProductResearchAssumptionMode;
  readonly assumptionProfileId: string;
}

export interface ProductStrategyProfileRefsView {
  readonly costPolicyVersionId: string;
  readonly executionPolicyVersionId: string;
  readonly riskPolicySetVersionId: string;
  readonly assumptionProfileId: string;
}

export interface ProductStrategyAuthoringProfileView {
  readonly schemaVersion: "v3.product-strategy-authoring-profile/1.0.0";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly positionSizingOptions: readonly ProductStrategyPositionSizing[];
  readonly maxPositionsMin: 1;
  readonly maxPositionsMax: 20;
  readonly grossExposureMin: "0";
  readonly grossExposureMax: "1";
  readonly rebalance: "NEXT_OPEN_AFTER_SIGNAL";
  readonly profileRefs: ProductStrategyProfileRefsView;
  readonly assumptionProfiles: readonly ProductResearchAssumptionProfileView[];
}

export interface ProductStrategySummaryView {
  readonly schemaVersion: "v3.project-strategy-summary/1.0.0";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly snapshotId: string;
  readonly universeVersionId: string;
  readonly researchStrategySpecId: string;
  readonly strategyVersionId: string;
  readonly entrySignalFactorVersionId: string;
  readonly exitSignalFactorVersionId: string;
  readonly profileRefs: ProductStrategyProfileRefsView;
  readonly transitionCount: number;
  readonly decisionChainCount: number;
}

export interface ProductBacktestSummaryView {
  readonly schemaVersion: "v3.project-backtest-summary/1.0.0";
  readonly maturity: "PRODUCT_CONNECTED";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly researchBacktestRequestId: string;
  readonly researchStrategySpecId: string;
  readonly snapshotId: string;
  readonly universeVersionId: string;
  readonly runId: string;
  readonly runSpecId: string;
  readonly resultId: string;
  readonly backtestResultId: string;
  readonly resultArtifactId: string;
  readonly analyticsId: string;
  readonly analyticsArtifactId: string;
  readonly summaryExportArtifactId: string;
  readonly ordersExportArtifactId: string;
  readonly fillsExportArtifactId: string;
  readonly resultLineageId: string;
  readonly lineageArtifactId: string;
  readonly resultState: "VALID";
  readonly engineVersion: string;
  readonly orderCount: number;
  readonly fillCount: number;
  readonly diagnosticCount: number;
  readonly firstFillSessionDate: string | null;
  readonly firstEffectiveSessionDate: string | null;
  readonly assumptionMode: ProductResearchAssumptionMode;
}

export interface ProductBacktestPolicyCoverageView {
  readonly schemaVersion: "v3.product-backtest-policy-coverage/1.0.0";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly coverageStart: string;
  readonly coverageEnd: string | null;
  readonly ruleProfileId: string;
  readonly costPolicyId: string;
  readonly executionTimingProfileId: string;
  readonly commissionRate: string;
  readonly minimumCommissionCny: string;
  readonly stampDutySellRate: string;
  readonly resourceEstimate: Readonly<{
    resourceClass: "PRODUCT_BACKTEST_CPU";
    cpuSlots: 1;
    memoryLimitBytes: 1073741824;
    scratchLimitBytes: 1073741824;
    checkpointResume: "UNAVAILABLE";
  }>;
}

export interface ProductResearchStrategyIntent {
  readonly entrySignalFactorVersionId: string;
  readonly exitSignalFactorVersionId: string;
  readonly positionSizing: ProductStrategyPositionSizing;
  readonly maxPositions: number;
  readonly grossExposure: string;
  readonly initialCash: string;
  readonly assumptionProfileId: string;
}

export interface ProductResearchStrategyOutcomeView {
  readonly taskId: string;
  readonly runId: string;
  readonly acceptedState: "QUEUED";
  readonly maturity: "PRODUCT_CONNECTED";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly checkpointResume: "UNAVAILABLE";
  readonly retry: "NEW_ATTEMPT_SAME_RUN_FROM_START";
  readonly researchStrategySpecId: string;
  readonly eventCursor?: number;
}

export interface ProductResearchStrategyPreviewView {
  readonly schemaVersion: "v3.product-strategy-preview/1.0.0";
  readonly maturity: "PRODUCT_CONNECTED";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly snapshotId: string;
  readonly universeVersionId: string;
  readonly researchStrategySpecId: string;
  readonly strategyDefinitionVersionId: string;
  readonly entrySignalFactorVersionId: string;
  readonly exitSignalFactorVersionId: string;
  readonly profileRefs: ProductStrategyProfileRefsView;
  readonly assumptionMode: ProductResearchAssumptionMode;
  readonly transitionCount: number;
  readonly plannedDecisionChainCount: number;
  readonly sideEffects: "NONE";
}

export interface ProductResearchBacktestIntent {
  readonly sessionStart: string;
  readonly sessionEnd: string;
  readonly slippageBps: string;
  readonly dailyVolumeParticipationRate: string;
}

export interface ProductResearchBacktestOutcomeView {
  readonly taskId: string;
  readonly runId: string;
  readonly acceptedState: "QUEUED";
  readonly maturity: "PRODUCT_CONNECTED";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly checkpointResume: "UNAVAILABLE";
  readonly retry: "NEW_ATTEMPT_SAME_RUN_FROM_START";
  readonly researchBacktestRequestId: string;
  readonly eventCursor?: number;
}

export interface ProductResearchBacktestPreviewView {
  readonly schemaVersion: "v3.product-backtest-preflight/1.0.0";
  readonly maturity: "PRODUCT_CONNECTED";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly status: "PASS";
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly researchStrategySpecId: string;
  readonly researchBacktestRequestId: string;
  readonly snapshotId: string;
  readonly universeVersionId: string;
  readonly sessionStart: string;
  readonly sessionEnd: string;
  readonly slippageBps: string;
  readonly dailyVolumeParticipationRate: string;
  readonly commissionRate: string;
  readonly minimumCommissionCny: string;
  readonly stampDutySellRate: string;
  readonly assumptionMode: ProductResearchAssumptionMode;
  readonly policyRefs: Readonly<{
    ruleProfileId: string;
    costPolicyId: string;
    executionTimingProfileId: string;
    riskPolicySetVersionId: string;
  }>;
  readonly resourceEstimate: ProductBacktestPolicyCoverageView["resourceEstimate"];
  readonly sideEffects: "NONE";
}

export interface ProductResultMetricView {
  readonly status: "AVAILABLE" | "INSUFFICIENT_SAMPLE" | "NOT_AVAILABLE";
  readonly value: string | null;
  readonly reason: string | null;
}

export interface ProductResultOrderRowView {
  readonly orderId: string;
  readonly sessionDate: string;
  readonly instrumentId: string;
  readonly side: "BUY" | "SELL";
  readonly requestedQuantity: number;
  readonly rawLimitPrice: string;
}

export interface ProductResultFillRowView {
  readonly fillId: string;
  readonly orderId: string;
  readonly sessionDate: string;
  readonly instrumentId: string;
  readonly side: "BUY" | "SELL";
  readonly quantity: number;
  readonly rawPrice: string;
  readonly executionPrice: string | null;
  readonly consideration: string;
  readonly commission: string;
  readonly stampDuty: string;
  readonly transferFee: string;
  readonly exchangeFee: string;
  readonly totalFees: string;
  readonly participationCap: number | null;
  readonly slippageBps: string | null;
}

export interface ProductResultDiagnosticRowView {
  readonly orderId: string;
  readonly code: string;
  readonly requestedQuantity: number;
  readonly eligibleQuantity: number | null;
  readonly filledQuantity: number;
  readonly unfilledQuantity: number | null;
  readonly participationCap: number | null;
  readonly detail: string;
}

export interface ProductResultHoldingRowView {
  readonly sessionDate: string;
  readonly instrumentId: string;
  readonly quantity: number;
  readonly sellableQuantity: number;
  readonly rawClose: string;
  readonly marketValue: string;
}

export interface ProductResultTablePreview<T> {
  readonly rowCount: number;
  readonly preview: readonly T[];
  readonly truncated: boolean;
  readonly sourceArtifactId: string;
}

export interface ProductLatestResultDetailsView {
  readonly schemaVersion: "v3.product-result-details/1.0.0";
  readonly maturity: "PRODUCT_CONNECTED";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly resultState: "VALID";
  readonly resultId: string;
  readonly backtestResultId: string;
  readonly analyticsId: string;
  readonly resultLineageId: string;
  readonly runId: string;
  readonly runSpecId: string;
  readonly engineVersion: string;
  readonly assumptionMode: ProductResearchAssumptionMode;
  readonly metrics: Readonly<{
    startNav: ProductResultMetricView;
    endNav: ProductResultMetricView;
    totalReturn: ProductResultMetricView;
    annualizedReturn: ProductResultMetricView;
    annualizedVolatility: ProductResultMetricView;
    maxDrawdown: ProductResultMetricView;
    sharpe: ProductResultMetricView;
    sortino: ProductResultMetricView;
    calmar: ProductResultMetricView;
  }>;
  readonly navSeries: readonly Readonly<{
    sessionDate: string;
    nav: string;
    sessionReturn: ProductResultMetricView;
    cumulativeReturn: ProductResultMetricView;
  }>[];
  readonly drawdownSeries: readonly Readonly<{ sessionDate: string; drawdown: ProductResultMetricView }>[];
  readonly exposureSeries: readonly Readonly<{
    sessionDate: string;
    grossExposure: ProductResultMetricView;
    netExposure: ProductResultMetricView;
    heldInstrumentCount: number;
  }>[];
  readonly periodReturns: Readonly<{
    monthly: readonly Readonly<{
      periodLabel: string;
      startDate: string;
      endDate: string;
      periodReturn: ProductResultMetricView;
    }>[];
    yearly: readonly Readonly<{
      periodLabel: string;
      startDate: string;
      endDate: string;
      periodReturn: ProductResultMetricView;
    }>[];
  }>;
  readonly costSummary: Readonly<{
    fillCount: number;
    grossTradedNotional: string;
    totalFees: string;
    turnover: ProductResultMetricView;
  }>;
  readonly concentration: Readonly<{
    peakSinglePositionWeight: ProductResultMetricView;
    peakSessionDate: string | null;
    peakInstrumentId: string | null;
    averageHeldInstrumentCount: ProductResultMetricView;
    maximumHeldInstrumentCount: number;
  }>;
  readonly benchmarkStatus: "AVAILABLE" | "BENCHMARK_NOT_AVAILABLE";
  readonly orders: ProductResultTablePreview<ProductResultOrderRowView>;
  readonly fills: ProductResultTablePreview<ProductResultFillRowView>;
  readonly diagnostics: ProductResultTablePreview<ProductResultDiagnosticRowView>;
  readonly holdings: ProductResultTablePreview<ProductResultHoldingRowView>;
  readonly lineage: Readonly<{
    rawCaptureId: string;
    rawArtifactId: string;
    snapshotId: string;
    universeVersionId: string;
    entryFactorVersionId: string;
    exitFactorVersionId: string;
    researchStrategySpecId: string;
    strategyVersionId: string;
    riskPolicySetVersionId: string;
    runSpecArtifactId: string;
    resultArtifactId: string;
    analyticsArtifactId: string;
    lineageArtifactId: string;
  }>;
  readonly exports: Readonly<{
    summaryJsonArtifactId: string;
    ordersCsvArtifactId: string;
    fillsCsvArtifactId: string;
    analyticsJsonArtifactId: string;
  }>;
}

export interface ProductProjectHomeView {
  readonly readModelVersion: "v3.project-home/1.1";
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly maturity: "PRODUCT_CONNECTED";
  readonly truth: "NOT_FORMAL";
  readonly admission: "PRE_ALPHA";
  readonly localImportState: "AVAILABLE";
  readonly dataState: "EMPTY" | "AVAILABLE" | "UNAVAILABLE";
  readonly dataUnavailableReason: "NONE" | "NO_SNAPSHOT" | "DATA_READ_MODEL_NOT_AVAILABLE";
  readonly data: ProductDataReadModelView | null;
  readonly factorState: "EMPTY" | "AVAILABLE" | "UNAVAILABLE";
  readonly factorUnavailableReason: "NONE" | "NO_SNAPSHOT" | "NO_FACTOR_STUDY" | "FACTOR_READ_MODEL_NOT_AVAILABLE";
  readonly factor: ProductFactorSummaryView | null;
  readonly strategyAuthoringProfile: ProductStrategyAuthoringProfileView;
  readonly backtestPolicyCoverage: ProductBacktestPolicyCoverageView;
  readonly strategyState: "EMPTY" | "AVAILABLE" | "UNAVAILABLE";
  readonly strategyUnavailableReason: "NONE" | "NO_FACTOR_STUDY" | "NO_RESEARCH_STRATEGY" | "STRATEGY_READ_MODEL_NOT_AVAILABLE";
  readonly strategy: ProductStrategySummaryView | null;
  readonly backtestState: "EMPTY" | "AVAILABLE" | "UNAVAILABLE";
  readonly backtestUnavailableReason: "NONE" | "NO_RESEARCH_STRATEGY" | "NO_VALID_BACKTEST" | "BACKTEST_READ_MODEL_NOT_AVAILABLE";
  readonly backtest: ProductBacktestSummaryView | null;
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
  /** Project-scoped, summary-only readback; never contains raw bytes or paths. */
  getProjectHome(): Promise<ProductProjectHomeView>;
  restoreSession(): Promise<SessionRestoreView>;
  connectExistingProject(request: ConnectExistingProjectRequest): Promise<ProjectContextView>;
  listTasks(request?: ProductTaskPageRequest): Promise<ProductTasksListView>;
  getTask(taskId: string): Promise<ProductTaskView>;
  /** Retry one persisted, retry-admitted Product research Backtest from immutable Run inputs. */
  retryResearchBacktest(taskId: string): Promise<ProductTaskView>;
  getTaskEvents(afterSequence: number, limit: number): Promise<ProductTaskEventsView>;
  getResult(resultId: string): Promise<ProductResultView>;
  getArtifactDescriptor(artifactId: string): Promise<ArtifactDescriptorView>;
  openArtifactStream(artifactId: string): Promise<ArtifactStreamTicketView>;
  readArtifactBytes(artifactId: string): Promise<ArtifactStreamBytesView>;
  exportArtifact(request: ProductArtifactExportIntent): Promise<ProductArtifactExportOutcomeView>;
  submitExistingBacktestRunSpec(runSpecId: string): Promise<BacktestSubmitOutcomeView>;
  /** Projectless clean-start entry: backend mints all canonical identities. */
  createProject(request: CreateProjectRequest): Promise<ProjectCreatedView>;
  listProjects(request?: ProductPageRequest): Promise<ProjectsListView>;
  /** Durable run-spec discovery with actual-artifact verification. */
  listBacktestRunSpecs(request?: ProductPageRequest): Promise<RunSpecsListView>;
  /**
   * Target-authority reuse: the Electron main process owns the file chooser and
   * reads the selected V3 research package; the renderer never receives or
   * controls raw filesystem paths. The target must already own and verify the
   * package's source authority. Null = user cancelled the chooser.
   */
  importResearchPackage(): Promise<ImportResearchPackageOutcomeView | null>;
  /** Native chooser result; null means cancellation and creates no Task. */
  chooseLocalDataSource(): Promise<LocalDataSourceSelectionView | null>;
  /** Transfer through backend staging, then submit only the immutable raw ref. */
  importLocalDataset(request: ProductLocalDataImportIntent): Promise<ProductLocalDataImportOutcomeView>;
  /** Queue a real backend Factor study; renderer supplies no data/owner IDs or values. */
  submitFactorStudy(request: ProductFactorStudyIntent): Promise<ProductFactorStudyOutcomeView>;
  /** Resolve exact Factor/Profile refs from fresh Home and queue Strategy publication. */
  previewResearchStrategy(request: ProductResearchStrategyIntent): Promise<ProductResearchStrategyPreviewView>;
  /** Publish only after the renderer has shown a matching side-effect-free preview. */
  publishResearchStrategy(request: ProductResearchStrategyIntent): Promise<ProductResearchStrategyOutcomeView>;
  /** Resolve the latest exact Strategy from fresh Home and queue a research Backtest. */
  previewResearchBacktest(request: ProductResearchBacktestIntent): Promise<ProductResearchBacktestPreviewView>;
  submitResearchBacktest(request: ProductResearchBacktestIntent): Promise<ProductResearchBacktestOutcomeView>;
  /** Rebuild bounded charts/tables/lineage from the latest VALID canonical artifacts. */
  getLatestProductResultDetails(): Promise<ProductLatestResultDetailsView>;
  /**
   * Product-connected, research-only source admission. The renderer supplies
   * only symbol/date intent; provider refs and the transport envelope are
   * owned by Electron main and no numeric market truth is accepted here.
   */
  submitResearch(request: ProductResearchSubmitIntent): Promise<ProductResearchSubmitOutcomeView>;
}
