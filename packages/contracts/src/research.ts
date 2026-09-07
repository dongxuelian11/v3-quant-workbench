/** Small shared boundary for the open-source research application. */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface UniverseConfig {
  name: string;
  symbols: string[];
  source: "manual" | "csi300" | "csi500" | "all";
  excludeST: boolean;
  minListingDays: number;
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
export type JobKind = "data.update" | "data.import" | "factor.analyze" | "backtest.run" | "model.train" | "optimize.run";
export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
export interface JobSpec { projectId: string; kind: JobKind; name?: string; parameters: JsonObject; }
export interface JobEvent {
  id: string;
  projectId: string;
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
  projectId: string;
  kind: JobKind;
  name: string;
  starred: boolean;
  createdAt: string;
  parameters: JsonObject;
  metrics: Record<string, number | null>;
  artifacts: { name: string; path: string; type: string }[];
  summary: string;
}
export interface ResearchTable { name: string; columns: string[]; rows: JsonObject[]; }
export interface ExperimentDetails {
  experiment: Experiment;
  tables: ResearchTable[];
  series: { name: string; points: { date: string; value: number | null }[] }[];
  details: JsonObject;
}
export interface FactorDefinition { id: string; name: string; family: string; description: string; expression?: string; }
export interface ResearchBridge {
  request<T = unknown>(method: string, params?: object): Promise<T>;
  onEvent(listener: (event: JobEvent) => void): () => void;
  chooseDirectory(): Promise<string | null>;
  chooseFiles(): Promise<string[]>;
  exportFile(request: { suggestedName: string; content?: string; dataUrl?: string; sourcePath?: string; html?: string; format: "csv" | "xlsx" | "png" | "pdf" }): Promise<string | null>;
}
declare global { interface Window { v3Research?: ResearchBridge; } }
