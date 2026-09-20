/** Small shared boundary for the open-source research application. */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface UniverseConfig {
  name: string;
  symbols: string[];
  source: "manual" | "csi300" | "csi500" | "all";
  excludeST: boolean;
  minListingDays: number;
  query?: MarketQuery;
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
export type JobKind = "data.update" | "data.import" | "factor.analyze" | "backtest.run" | "model.train" | "optimize.run" | "selection.run" | "rdagent.run" | "simulation.advance" | "reports.import" | "reports.ocr" | "reports.refresh";
export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
export interface JobSpec { projectId?: string; strategyId?: string; candidateId?: string; kind: JobKind; name?: string; parameters: JsonObject; }
export interface JobEvent {
  id: string;
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
export interface ExperimentDetails {
  experiment: Experiment;
  tables: ResearchTable[];
  series: { name: string; points: { date: string; value: number | null }[] }[];
  details: JsonObject;
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
/** A paper account; advancing it never changes the user's actual holdings. */
export interface SimulationAccount {
  id: string;
  name: string;
  projectId: string;
  strategyId: string;
  startDate: string;
  capital: number;
  nav: number;
  cash: number;
  asOfDate: string | null;
  status: "ready" | "paused" | "blocked";
  paused: boolean;
  revision: number;
  unresolved: { date: string | null; message: string } | null;
  pendingDecision: JsonObject | null;
  state: JsonObject;
  modelState?: JsonObject | null;
  createdAt: string;
  updatedAt: string;
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
  chartDefaults?: JsonObject;
  theme: "light" | "dark";
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
  rightPanel?: "ai" | "parameters";
  closedProjectIds?: string[];
  conversationViews?: Record<string, { draft: string; scrollTop: number; atBottom: boolean }>;
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
export interface MarketOverview {
  asOfDate: string | null;
  summary: Record<string, number | null>;
  indices: JsonObject[];
  industries: JsonObject[];
  concepts?: JsonObject[];
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
  createdAt: string;
  updatedAt: string;
}
export interface ReproductionRun {
  runId: string;
  planId: string;
  revision: number;
  status: "running" | "completed" | "failed" | "cancelled" | "interrupted";
  steps: { stepId: string; jobId?: string; experimentId?: string; status: "pending" | JobStatus }[];
  message?: string;
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
export interface FilePickerOptions { purpose?: "research" | "positions" | "membership" | "report" | "quote"; }
export interface ResearchBridge {
  desktop: {
    windowState(): Promise<{ maximized: boolean }>;
    windowControl(action: "minimize" | "toggle-maximize" | "close"): Promise<{ maximized: boolean }>;
    onWindowStateChanged(listener: (state: { maximized: boolean }) => void): () => void;
  };
  request<T = unknown>(method: string, params?: object): Promise<T>;
  onEvent(listener: (event: JobEvent) => void): () => void;
  chooseDirectory(options?: { purpose?: "project" | "tdx" }): Promise<string | null>;
  chooseFiles(options?: FilePickerOptions): Promise<string[]>;
  readReportDocument(reportId: string): Promise<Uint8Array>;
  openExternal(url: string): Promise<void>;
  exportFile(request: { suggestedName: string; content?: string; dataUrl?: string; sourcePath?: string; html?: string; format: "csv" | "xlsx" | "png" | "pdf" }): Promise<string | null>;
  workspace?: WorkspaceWindowBridge;
}
declare global { interface Window { v3Research?: ResearchBridge; } }
