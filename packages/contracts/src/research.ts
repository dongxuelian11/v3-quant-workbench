/** Small shared boundary for the open-source research application. */
export interface DataSourceSettings {
  daily: "baostock" | "akshare" | "file";
  financials: "baostock" | "file";
  boards: "akshare" | "file";
  intraday: "akshare" | "file";
  microcap: "tdx" | "file";
  quoteFallback: boolean;
}
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };
export interface MembershipVersion {
  membershipRef: { poolId: string; version: string; source: string };
  observedAt?: string | null;
  rows: number;
  symbols: number;
  startDate: string | null;
  endDate: string | null;
}

export interface UniverseConfig {
  name: string;
  symbols: string[];
  source: "manual" | "csi300" | "csi500" | "all";
  excludeST: boolean;
  minListingDays: number;
  query?: MarketQuery;
  membershipRef?: { poolId: string; version: string; source: string };
}
export interface ProjectConfig {
  id: string;
  name: string;
  path: string;
  objective: string;
  createdAt: string;
  updatedAt: string;
  universe: UniverseConfig;
  startDate: string;
  endDate: string;
  layout?: JsonObject;
  settings: JsonObject;
}
export type JobKind = "data.update" | "data.import" | "factor.analyze" | "backtest.run" | "model.train" | "optimize.run" | "selection.run" | "screener.run" | "rdagent.run" | "simulation.advance" | "reports.import" | "reports.ocr" | "reports.refresh";
export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
export interface ComputeSettings { profile: "interactive" | "balanced" | "compute"; maxConcurrentJobs?: number; threadsPerJob?: number; }
export interface EffectiveResources extends ComputeSettings { maxConcurrentJobs: number; threadsPerJob: number; availableCpus: number; requested: ComputeSettings; qlibKernels: number; optunaParallelTrials: number; limitations: string[]; }
export interface JobSpec { projectId?: string; strategyId?: string; candidateId?: string; inputExperimentId?: string; effectiveResources?: EffectiveResources; kind: JobKind; name?: string; parameters: JsonObject; }
export interface JobEvent {
  id: string;
  /** Queue priority exposed to the UI; absent on older task records. */
  priority?: number;
  projectId?: string;
  strategyId?: string;
  kind: JobKind;
  name: string;
  status: JobStatus;
  progress: number;
  message: string;
  createdAt: string;
  updatedAt: string;
  experimentId?: string;
  resultAvailable?: boolean;
  registrationPending?: boolean;
  registrationError?: string;
  effectiveResources?: EffectiveResources;
  preparation?: JsonObject;
  spec: JobSpec;
}
/** Conversation activity is routed separately from persisted calculation jobs. */
export interface ResearchAIEvent {
  kind: "ai.execution";
  id: string;
  conversationId: string;
  projectId?: string | null;
  status: "running" | "paused" | "completed" | "failed" | "cancelled";
  message?: string;
}
export interface ReproductionEvent {
  kind: "reproduction.execution";
  id: string;
  planId: string;
  projectId: string;
  status: ReproductionRun["status"];
  message?: string;
}
export type ResearchServiceEvent = JobEvent | ResearchAIEvent | ReproductionEvent;
export interface Experiment {
  inputSnapshot?: { version: 1; path: string; status: string; [key: string]: JsonValue };
  id: string;
  projectId?: string;
  strategyId?: string;
  candidateId?: string;
  candidateRevision?: number;
  reproduction?: { planId: string; revision: number; reportId: string; variant: ReproductionVariant };
  kind: JobKind;
  name: string;
  starred: boolean;
  createdAt: string;
  parameters: JsonObject;
  metrics: Record<string, number | null>;
  artifacts: { name: string; path: string; type: string }[];
  summary: string;
}
export interface ResearchTable { name: string; columns: string[]; rows: JsonObject[]; fieldLabels?: Record<string, string>; }
export interface ExperimentAnalysis extends ResearchTable {
  total: number;
  returned: number;
  aggregation: { method: "complete" | "preview" | "minmax"; sampled: boolean; sourceRows: number };
  calendarSource?: "experiment_processing_sessions" | "unavailable" | null;
  message?: string;
}
export interface ExperimentDetails {
  experiment: Experiment;
  tables: ResearchTable[];
  series: { name: string; points: { date: string; value: number | null }[] }[];
  details: JsonObject;
}
/** Saved observations from declarative backtest rules; dates refer to the signal session. */
export interface RuleDiagnosticCondition {
  conditionIndex: number;
  field: JsonValue;
  op: JsonValue;
  threshold: JsonValue;
  thresholdState?: "present" | "missing" | "positive_infinity" | "negative_infinity";
  value: JsonValue;
  valueState: "present" | "missing" | "positive_infinity" | "negative_infinity" | "not_evaluated";
  conditionState: "true" | "false" | "unknown" | "not_evaluated";
}
export interface RuleDiagnosticRow {
  date: string;
  executionDate: string;
  symbol: string;
  ruleIndex: number;
  ruleId: string;
  action: "entry" | "add" | "reduce" | "exit";
  ruleState: "matched" | "not_matched" | "unknown" | "skipped";
  skipReason: "not_held" | "already_held" | "exit_priority" | null;
  beforeWeight: number;
  targetWeight: number;
  conditionsJson: string;
  constraintReasonsJson: string;
  orderId: string | null;
  orderState: "no_order" | "filled" | "partial" | "rejected";
  requestedQuantity: number;
  filledQuantity: number;
  orderReasonsJson: string;
}
export interface RuleDiagnosticsCapability {
  version: 1;
  status: "available" | "not_applicable";
  artifact: "rule_diagnostics" | null;
  rowCount: number;
  scope: "declarative_backtest_rules";
  dateBasis: "signal_date";
}
/** Comparison describes saved experiments without recomputing or ranking them. */
export interface ExperimentRef { projectId: string | null; experimentId: string; }
export interface ExperimentChange {
  field: string;
  label: string;
  before: JsonValue;
  after: JsonValue;
  beforeKnown: boolean;
  afterKnown: boolean;
}
export interface ComparisonInputSummary {
  snapshotStatus: "available" | "missing" | "unavailable";
  sourceExperimentId: string | null;
  recordedVersionAvailable: boolean;
  coverage: JsonObject | null;
}
export interface ExperimentComparison {
  version: 1;
  baselineRef: ExperimentRef;
  ref: ExperimentRef;
  configurationChanges: ExperimentChange[];
  rangeChanges: ExperimentChange[];
  inputEvidence: {
    status: "same_recorded_version" | "different_recorded_version" | "unknown";
    basis: "snapshot_reference" | "recorded_source_version" | "insufficient";
    message: string;
    baseline: ComparisonInputSummary;
    current: ComparisonInputSummary;
  };
  comparability: {
    status: "comparable" | "controlled_change" | "incomparable" | "unknown";
    reasons: { code: string; field: string | null; message: string }[];
  };
}
export interface PreviousExperimentComparison {
  currentRef: ExperimentRef;
  previousRef: ExperimentRef | null;
  comparison: ExperimentComparison | null;
}
export interface FactorDefinition {
  id: string;
  name: string;
  family: string;
  description: string;
  expression?: string;
  source?: "parquet";
  dataPath?: string;
  codePath?: string;
}
/** Saved user holdings; generating a selection never changes this snapshot. */
export interface PositionRow { symbol: string; quantity: number; sellableQuantity: number; costPrice?: number; }
export interface Positions { asOfDate: string; cash: number; rows: PositionRow[]; updatedAt?: string; }
/** Omitted/null projectId addresses shared storage; explicit IDs address legacy storage only. */
export interface SimulationAccountRef { accountId: string; projectId?: string | null; }
export type SimulationBindingSource = { kind: "dailyPlan"; dailyPlanId: string } | { kind: "strategy"; projectId: string; strategyId: string };
export interface SimulationBindingVersion { id: string; sourceVersion: string | null; createdAt: string; snapshot: JsonObject; }
export interface SimulationBinding {
  id: string; source: SimulationBindingSource; name: string; allocation: number;
  allowNewEntries: boolean; currentVersionId: string; versions: SimulationBindingVersion[];
}
export interface SimulationOwnership {
  id: string; symbol: string; bindingId: string | null; entryVersionId: string | null;
  management: "rules" | "manual"; quantity: number; sellableQuantity: number;
  pendingQuantity: number; costBasis: number | null;
}
export interface SimulationCashFlow {
  id: string; accountId: string; date: string; direction: "deposit" | "withdraw";
  amount: number; navBefore: number; navAfter: number; unitNav: number;
  unitsBefore: number; unitsAfter: number; effectivePhase: "before_start" | "after_close";
  createdAt: string; note?: string;
}
export type SelectionPositionsSource = { kind: "none" } | { kind: "actual" } | ({ kind: "simulation" } & SimulationAccountRef);
/** Saved version 1 accounts may lack version 2 fields; absence is not a zero or empty history. */
export interface SimulationAccount {
  id: string; name: string; projectId: string | null; strategyId: string | null;
  startDate: string; capital: number; nav: number; cash: number;
  asOfDate: string | null; status: "ready" | "paused" | "blocked"; paused: boolean;
  revision: number; unresolved: { date: string | null; message: string } | null;
  pendingDecision: JsonObject | null; state: JsonObject; modelState?: JsonObject | null;
  createdAt: string; updatedAt: string; schemaVersion?: 1 | 2;
  origin?: SimulationAccountRef & { revision: number; asOfDate: string | null };
  branchOf?: SimulationAccountRef & { date: string; revision: number };
  bindings?: SimulationBinding[]; ownership?: SimulationOwnership[];
  netContributions?: number; unitNav?: number | null; units?: number | null;
  valuationStatus?: "known" | "unavailable";
}
export interface SimulationMutation extends SimulationAccountRef { expectedRevision: number; }
export interface SimulationBindingSave extends SimulationMutation {
  bindingId?: string; source?: SimulationBindingSource; allocation?: number; allowNewEntries?: boolean;
}
export interface SimulationBindingPreview extends SimulationAccountRef { bindingId?: string; source?: SimulationBindingSource; }
export interface SimulationBindingPreviewResult { source: SimulationBindingSource; sourceVersion: string; snapshot: JsonObject; }
export interface SimulationBindingAdopt extends SimulationMutation { bindingId: string; expectedSourceVersion: string; }
/** Effective at the current settled close, or immediately before startDate if unstarted. */
export interface SimulationCashFlowCreate extends SimulationMutation {
  requestId: string; direction: "deposit" | "withdraw"; amount: number; note?: string;
}
/** Includes fromDate close; the branch continues AFTER that completed day. */
export interface SimulationBranchCreate extends SimulationMutation { fromDate: string; name: string; requestId: string; }
export interface SimulationLegacyImport { source: SimulationAccountRef; expectedRevision: number; name?: string; requestId: string; }
export interface SimulationAdvance extends SimulationMutation { endDate: string; }
export interface SimulationAccountExport extends SimulationMutation { format: "csv" | "xlsx"; table?: string; }
export interface SimulationAccountCurve {
  rows: { date: string; unitNav: number | null; nav: number | null }[];
  total: number;
}
export interface StrategyConfig {
  id: string;
  projectId: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  universe: UniverseConfig;
  settings: JsonObject;
  enabled: boolean;
  allocation: number;
  active?: { universe: UniverseConfig; settings: JsonObject; updatedAt: string };
}
export type WorkspacePanelKind = "today" | "strategy" | "factors" | "model" | "experiment" | "compare" | "market" | "quote" | "screener" | "stock" | "selection" | "positions" | "data" | "universe" | "candidate" | "simulation" | "reports" | "report" | "reproduction";
export interface ResearchObjectRef {
  kind: WorkspacePanelKind;
  projectId?: string;
  strategyId?: string;
  experimentId?: string;
  symbol?: string;
  instrument?: QuoteInstrument;
  title?: string;
  view?: string;
  date?: string;
  dateRange?: { start?: string; end?: string };
  factorId?: string;
  tradeId?: string;
  modelWindowId?: string;
  candidateId?: string;
  accountId?: string;
  reportId?: string;
  reproductionId?: string;
  page?: number;
  analysis?: JsonObject;
}
export interface WorkspacePanel extends ResearchObjectRef {
  id: string;
  title: string;
  experimentRefs?: ResearchObjectRef[];
  linkGroup?: string;
  chartViews?: ChartViewState[];
  quoteList?: { visible: boolean; width: number; kind: QuoteInstrument['kind']; categories: Partial<Record<QuoteInstrument['kind'], { query: string; offset: number; watchlistId: string }>> };
}
export interface WorkspaceWindow {
  id: string;
  main?: boolean;
  maximized?: boolean;
  bounds?: { x?: number; y?: number; width: number; height: number };
  dock?: JsonObject;
  panels: WorkspacePanel[];
  activePanelId?: string;
}
export interface WorkspaceState {
  navigation?: { order?: string[]; hidden?: string[]; pinned?: string[] };
  chartDefaults?: JsonObject;
  theme: "light" | "dark" | "system";
  zoomFactor?: number;
  readingFontSize?: number;
  shortcuts?: Partial<Record<"commandSearch" | "settings" | "sidebar" | "assistant" | "quoteList", string>>;
  layoutPresets?: Record<string, { sidebarVisible?: boolean; aiVisible?: boolean; sidebarWidth?: number; aiWidth?: number; density?: "comfortable" | "compact"; rightPanel?: "ai" | "parameters" | "jobs"; layout?: "single" | "columns" | "rows" }>;
  density: "comfortable" | "compact";
  sidebarWidth: number;
  aiWidth: number;
  windows: WorkspaceWindow[];
  presets: Record<string, WorkspaceWindow[]>;
  /** Legacy preference. Cold starts never select this conversation automatically. */
  activeConversationId?: string;
  tablePreferences?: JsonObject;
  sidebarVisible?: boolean;
  aiVisible?: boolean;
  rightPanel?: "ai" | "parameters" | "jobs";
  closedProjectIds?: string[];
  conversationViews?: Record<string, { draft: string; scrollTop: number; atBottom: boolean }>;
}
export interface ResearchPreset {
  id: string;
  name: string;
  category: "factorProcessing" | "costs" | "portfolio" | "validation";
  value: JsonObject;
  revision: number;
  createdAt: string;
  updatedAt: string;
}
export interface WorkspaceWindowBridge {
  current(): Promise<{ id: string; main: boolean; state?: WorkspaceWindow; visible?: boolean; minimized?: boolean }>;
  detach(panel: WorkspacePanel, bounds?: WorkspaceWindow["bounds"]): Promise<{ windowId: string }>;
  update(state: WorkspaceWindow): Promise<void>;
  attach(panels: WorkspacePanel[], targetWindowId?: string): Promise<void>;
  restore(windows: WorkspaceWindow[]): Promise<void>;
  onPanels(listener: (panels: WorkspacePanel[]) => void): () => void;
  onChanged(listener: (change: { method: string; params?: JsonObject }) => void): () => void;
  broadcast(change: { method: string; params?: JsonObject }): void;
}
export interface ScreenFilter { field: string; operator: "gt" | "gte" | "lt" | "lte" | "eq" | "ne" | "contains" | "in"; value: JsonValue; }
export interface MarketQuery {
  date?: string;
  projectId?: string;
  symbols?: string[];
  watchlistId?: string;
  filters?: ScreenFilter[];
  match?: "all" | "any";
  search?: string;
  sortBy?: string;
  descending?: boolean;
  offset?: number;
  limit?: number;
}
export interface DataCoverage {
  dataset: string;
  label: string;
  source: string;
  startDate?: string;
  endDate?: string;
  symbols?: number;
  rows?: number;
  status: "available" | "partial" | "missing";
  message?: string;
  estimated?: boolean;
}
export interface MarketTable extends ResearchTable {
  total: number;
  offset: number;
  limit: number;
  asOfDate: string;
  coverage: DataCoverage[];
  fieldLabels?: Record<string, string>;
}
export type MarketStrengthRow = JsonObject & {
  strengthChangeRatio?: number | null;
  strengthDays?: 1 | 5 | 20;
  strengthStartDate?: string | null;
  strengthEndDate?: string | null;
  strengthStatus?: "ready" | "missing" | "partial" | "unsupported";
  strengthMessage?: string;
  strengthSource?: string;
}
export interface MarketOverview {
  asOfDate: string | null;
  summary: Record<string, number | null>;
  indices: MarketStrengthRow[];
  industries: MarketStrengthRow[];
  concepts?: MarketStrengthRow[];
  strength?: { days: 1 | 5 | 20; asOfDate: string | null; calendarSource: string; covered: number; total: number; message: string };
  breadth: JsonObject[];
  coverage: DataCoverage[];
  source?: string;
  updatedAt?: string | null;
  stale?: boolean;
  status?: "ready" | "missing" | "empty" | "source_error";
  errors?: Record<string, string>;
}
export interface StockPanorama {
  symbol: string;
  name: string;
  asOfDate: string;
  profile: JsonObject;
  metrics: JsonObject;
  financials: ResearchTable;
  factors: ResearchTable;
  flow: ResearchTable;
  chips: ResearchTable;
  events: ResearchTable;
  seats: ResearchTable;
  coverage: DataCoverage[];
  notes: string;
}
export type QuoteInstrumentKind = "stock" | "index" | "industry" | "concept";
/** A type and venue-qualified symbol distinguish SH000001 from SZ000001 and BK boards. */
export interface QuoteInstrument { kind: QuoteInstrumentKind; symbol: string; name?: string; source?: string; }
export interface QuoteCatalog {
  items: QuoteInstrument[];
  total: number;
  updatedAt: string | null;
  needsRefresh: boolean;
  source?: string;
  message?: string;
  status?: "ready" | "missing" | "empty" | "source_error";
  errors?: Partial<Record<QuoteInstrumentKind, string>>;
}
export interface QuoteBar {
  date: string; open: number | null; high: number | null; low: number | null; close: number; volume: number | null;
  amount?: number | null; turnover?: number | null; factor?: number | null;
  rawOpen?: number | null; rawHigh?: number | null; rawLow?: number | null; rawClose?: number | null;
  timestamp?: number;
  complete?: boolean;
  previousClose?: number | null;
  averagePrice?: number | null;
  averagePriceSource?: "provider" | "session_vwap" | "unavailable";
  source?: string;
  periodStart?: string;
  periodEnd?: string;
  sessions?: number;
}
export type IntradayPeriod = "intraday" | "1m" | "5m" | "15m" | "30m" | "60m";
export type ChartPeriod = "day" | "week" | "month" | "trading_days" | IntradayPeriod;
/** Per-chart state travels with its document when moved between native windows. */
export interface ChartViewState {
  id: string;
  instrument: QuoteInstrument;
  period: ChartPeriod;
  tradingDays?: number;
  anchorDate?: string;
  indicators?: JsonObject;
  preferences?: JsonObject;
  formulaView?: JsonObject;
  fixed?: boolean;
  linkGroup?: string;
}
export interface QuoteCoverage {
  startDate: string | null; endDate: string | null; rows: number; updatedAt: string | null;
  source: string; priceUnit: string; volumeUnit: string; amountUnit: string;
}
export interface QuoteStatus {
  instrument: QuoteInstrument;
  historyAvailable?: boolean;
  hasMore?: boolean;
  bars: QuoteBar[];
  coverage: QuoteCoverage;
  message?: string;
  period?: IntradayPeriod;
  availablePeriods?: IntradayPeriod[];
  status?: "ready" | "missing" | "empty" | "source_error" | "unsupported";
  timezone?: "Asia/Shanghai";
  tradingDays?: number;
  anchorDate?: string;
  averagePriceSource?: "provider" | "session_vwap" | "unavailable";
  averagePriceMessage?: string;
}
export interface QuoteMembers {
  status?: "ready" | "missing" | "source_error";
  stale?: boolean;
  updatedAt?: string | null;
  instrument: QuoteInstrument;
  asOfDate: string | null;
  rows: JsonObject[];
  total: number;
  offset: number;
  limit: number;
  source: string;
  message?: string;
}
export interface Watchlist {
  id: string; name: string; symbols: string[]; updatedAt?: string;
  /** Stock symbols remain compatible with existing screeners. Other instruments are separate. */
  instruments?: QuoteInstrument[];
  asOfDate?: string;
  source?: string;
}
export interface ResearchAssetRef {
  snapshotOwner?: "shared";
  id: string; kind: "factor" | "strategy" | "model"; name: string; projectId?: string;
  projectName?: string; revision: string; snapshot: JsonObject; experimentId?: string;
  available: boolean; reason?: string;
}
export interface ScreenerCondition {
  id: string; field: string;
  operator: "gt" | "gte" | "lt" | "lte" | "eq" | "ne" | "between" | "rank_top" | "rank_bottom" | "cross_up" | "cross_down" | "contains" | "in";
  value?: JsonValue; upper?: number; compareField?: string; window?: number;
  occurrence?: "current" | "all" | "any";
}
export interface ScreenerConditionGroup { id: string; match: "all" | "any"; children: (ScreenerCondition | ScreenerConditionGroup)[]; }
export interface ScreenerPlan {
  id: string; name: string; mode: "conditions" | "factors" | "strategy"; version: number;
  universe: UniverseConfig; date?: string; dataProjectId?: string;
  conditions: ScreenerConditionGroup; preconditions?: ScreenerConditionGroup;
  factors: { id: string; direction: 1 | -1; weight: number }[];
  assets: ResearchAssetRef[]; rankingReference: "base" | "prefilter"; limit?: number;
  favorite?: boolean; archived?: boolean; updatedAt?: string; lastUsedAt?: string;
}
export interface ScreenerWorkspace { activePlanId?: string; draft?: ScreenerPlan; lastExperimentId?: string; view?: "screen" | "watchlist"; conditionsCollapsed?: boolean; detailHeight?: number; }
export interface DailyResearchPlan {
  id: string; name: string; planId: string; planVersion: number; planSnapshot: ScreenerPlan;
  allocation: number; enabled: boolean; updatedAt: string;
  latestVersion?: number; sourceChanged?: boolean; sourceUnavailable?: boolean;
}
/** Scope coverage on asOfDate, measured in unique securities, not historical rows. */
export interface ScreenerCoverage {
  asOfDate: string;
  expectedSymbols: number | null;
  observedSymbols: number;
  eligibilityUnknown: number;
  denominatorStatus: "known" | "partial_query_inputs" | "partial_unspecified_manual_pool" | "missing_membership" | "partial_observed_market" | "unknown";
}
export interface ScreenerResult extends ResearchTable {
  experimentId: string; asOfDate: string; status: "complete" | "preview";
  total: number; offset: number; limit: number; counts: { scope: number; valid: number; included: number; missing: number };
  /** Absent for legacy results; never infer full coverage from counts.scope. */
  coverage?: ScreenerCoverage;
  configChanged: boolean; message?: string; diff?: JsonObject;
}
export interface SavedScreener { id: string; name: string; query: MarketQuery; updatedAt?: string; }
export interface ResearchConversation {
  id: string; name: string;
  /** null is global; absent is unclassified legacy history. */
  projectId?: string | null;
  context: ResearchObjectRef[]; state: JsonObject; createdAt: string; updatedAt: string;
}
/** Source facts and extraction status are separate from AI interpretations. */
export interface ResearchReport {
  id: string;
  title: string;
  institution?: string;
  authors?: string[];
  symbols: string[];
  publishedAt?: string | null;
  collectedAt: string;
  source: string;
  url?: string;
  pdfUrl?: string;
  documentAvailable: boolean;
  pageCount?: number;
  extractionStatus: "pending" | "ready" | "needs_ocr" | "failed";
  message?: string;
}
export interface ReportPage {
  page: number;
  text: string;
  method: "text" | "ocr" | "unavailable";
}
export interface ReportCitation {
  reportId: string;
  page: number;
  excerpt?: string;
}
export interface ReportSubscription {
  id: string;
  name: string;
  enabled: boolean;
  query: { keyword?: string; institution?: string; symbol?: string; startDate: string; endDate?: string };
  lastCheckedAt?: string | null;
  lastSuccessfulDate?: string | null;
  message?: string;
}
export type ReproductionVariant = "original" | "adapted" | "post_publication" | "execution";
export interface ReproductionStep {
  id: string;
  name: string;
  variant: ReproductionVariant;
  spec: JobSpec;
  dependsOn: string[];
  differences: string[];
  citations: ReportCitation[];
}
export interface ReproductionPlan {
  id: string;
  reportId: string;
  projectId: string;
  strategyId?: string;
  name: string;
  revision: number;
  objective: string;
  missingConditions: string[];
  steps: ReproductionStep[];
  plannedWork?: ResearchWorkCounts;
  createdAt: string;
  updatedAt: string;
}
export interface ResearchWorkCounts { trials: number; trainingTasks: number; backtestTasks: number; rollingTasks: number; }
export interface ReproductionRun {
  runId: string;
  planId: string;
  revision: number;
  status: "running" | "completed" | "failed" | "cancelled" | "interrupted";
  steps: { stepId: string; jobId?: string; experimentId?: string; status: "pending" | JobStatus }[];
  message?: string;
  budget?: { trialLimit: number; reserved: ResearchWorkCounts; planned: ResearchWorkCounts; message: string };
}
export interface ResearchUIBlock {
  id: string;
  language: "openui";
  content: string;
  state?: JsonObject;
  projectId?: string | null;
  reportId?: string;
  reproductionId?: string;
  reproductionRevision?: number;
  experimentIds?: string[];
}
export interface ProjectSummary {
  projectId: string;
  revision: number;
  updatedAt: string | null;
  cleared: boolean;
  goals: string[];
  userDecisions: string[];
  experimentFindings: { experimentId: string; date: string; conclusion: string; conversationId?: string }[];
  hypotheses: string[];
  unresolved: string[];
  notes: string;
  sourceConversationIds?: string[];
}
export interface ResearchCandidate {
  id: string;
  projectId: string;
  strategyId?: string;
  kind: "factor" | "model" | "strategy";
  name: string;
  description?: string;
  changeSummary?: string;
  spec: JobSpec;
  revision: number;
  sourceConversationId?: string;
  parentId?: string;
  experiments: { projectId: string; experimentId: string; revision: number }[];
  adoptedAt?: string;
  adoptedRevision?: number;
  createdAt: string;
  updatedAt: string;
}
export interface ResearchCandidateCode {
  candidateId: string;
  revision: number;
  factorId?: string | null;
  language: "python";
  path: string;
  content: string;
}
export type PortfolioMethod = "equal" | "score" | "risk_parity" | "mean_variance";
export interface FilePickerOptions { purpose?: "research" | "positions" | "membership" | "report" | "quote" | "settings"; }
/** Unique per read/export request. Cancellation is cooperative, including queued reads. */
export interface ReadCancellation { readId: string; }
/** A request was signalled; a result already committed can still complete successfully. */
export interface ReadCancellationResult { requested: boolean; }
export interface ResearchBridge {
  desktop: {
    windowState(): Promise<{ maximized: boolean }>;
    windowControl(action: "minimize" | "toggle-maximize" | "close"): Promise<{ maximized: boolean }>;
    onWindowStateChanged(listener: (state: { maximized: boolean }) => void): () => void;
  };
  request<T = unknown>(method: string, params?: object): Promise<T>;
  onEvent(listener: (event: JobEvent) => void): () => void;
  chooseDirectory(options?: { purpose?: "project" | "tdx" | "data" | "projectDefault" }): Promise<string | null>;
  chooseFiles(options?: FilePickerOptions): Promise<string[]>;
  readReportDocument(reportId: string): Promise<Uint8Array>;
  openExternal(url: string): Promise<void>;
  exportFile(request: { suggestedName: string; content?: string; dataUrl?: string; sourcePath?: string; html?: string; format: "csv" | "xlsx" | "png" | "pdf" | "json" }): Promise<string | null>;
  workspace?: WorkspaceWindowBridge;
}
export interface LocalAssistantAction {
  kind: "navigation" | "filter_patch" | "run" | "search" | "clarify" | "handoff";
  namespace: "market" | "screeners" | "dailyPlans" | "positions" | "research";
  objectIds: string[];
  screen?: "overview" | "screeners" | "daily" | "positions" | "research";
  query?: string;
  conditions?: ScreenerConditionGroup;
  question?: string;
  message: string;
}
export interface LocalAssistantInterpretation {
  status: "proposed" | "needs_clarification" | "unsupported" | "unavailable";
  action: LocalAssistantAction | null;
  model: string;
  executed: false;
  elapsedMs: number;
  message?: string;
}
export interface LocalAssistantApplied {
  kind: "navigation" | "search" | "handoff" | "clarify" | "draft" | "jobs";
  screen?: LocalAssistantAction["screen"];
  objectIds?: string[];
  query?: string;
  message?: string;
  draft?: ScreenerPlan;
  previousDraft?: ScreenerPlan;
  jobs?: JobEvent[];
}
declare global { interface Window { v3Research?: ResearchBridge; } }
