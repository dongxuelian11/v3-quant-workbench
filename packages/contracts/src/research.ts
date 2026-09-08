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
export type JobKind = "data.update" | "data.import" | "factor.analyze" | "backtest.run" | "model.train" | "optimize.run" | "selection.run";
export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
export interface JobSpec { projectId?: string; strategyId?: string; kind: JobKind; name?: string; parameters: JsonObject; }
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
  spec: JobSpec;
}
export interface Experiment {
  id: string;
  projectId?: string;
  strategyId?: string;
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
export interface FactorDefinition { id: string; name: string; family: string; description: string; expression?: string; }
/** Saved user holdings; generating a selection never changes this snapshot. */
export interface PositionRow { symbol: string; quantity: number; sellableQuantity: number; costPrice?: number; }
export interface Positions { asOfDate: string; cash: number; rows: PositionRow[]; updatedAt?: string; }
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
export type WorkspacePanelKind = "today" | "strategy" | "factors" | "model" | "experiment" | "compare" | "market" | "screener" | "stock" | "selection" | "positions" | "data" | "universe";
export interface ResearchObjectRef {
  kind: WorkspacePanelKind;
  projectId?: string;
  strategyId?: string;
  experimentId?: string;
  symbol?: string;
  title?: string;
}
export interface WorkspacePanel extends ResearchObjectRef {
  id: string;
  title: string;
  experimentRefs?: ResearchObjectRef[];
  linkGroup?: string;
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
  theme: "light" | "dark";
  density: "comfortable" | "compact";
  sidebarWidth: number;
  aiWidth: number;
  windows: WorkspaceWindow[];
  presets: Record<string, WorkspaceWindow[]>;
  activeConversationId?: string;
  tablePreferences?: JsonObject;
}
export interface WorkspaceWindowBridge {
  current(): Promise<{ id: string; main: boolean; state?: WorkspaceWindow }>;
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
  asOfDate: string;
  summary: Record<string, number | null>;
  indices: JsonObject[];
  industries: JsonObject[];
  breadth: JsonObject[];
  coverage: DataCoverage[];
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
export interface Watchlist { id: string; name: string; symbols: string[]; updatedAt?: string; }
export interface SavedScreener { id: string; name: string; query: MarketQuery; updatedAt?: string; }
export interface ResearchConversation { id: string; name: string; context: ResearchObjectRef[]; state: JsonObject; createdAt: string; updatedAt: string; }
export type PortfolioMethod = "equal" | "score" | "risk_parity" | "mean_variance";
export interface FilePickerOptions { purpose?: "research" | "positions" | "membership"; }
export interface ResearchBridge {
  request<T = unknown>(method: string, params?: object): Promise<T>;
  onEvent(listener: (event: JobEvent) => void): () => void;
  chooseDirectory(): Promise<string | null>;
  chooseFiles(options?: FilePickerOptions): Promise<string[]>;
  exportFile(request: { suggestedName: string; content?: string; dataUrl?: string; sourcePath?: string; html?: string; format: "csv" | "xlsx" | "png" | "pdf" }): Promise<string | null>;
  workspace?: WorkspaceWindowBridge;
}
declare global { interface Window { v3Research?: ResearchBridge; } }
