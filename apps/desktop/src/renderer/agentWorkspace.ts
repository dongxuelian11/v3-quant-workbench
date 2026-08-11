import type { LabId } from "../../../../packages/contracts/src/index";

export const AGENT_WORKSPACE_BOUNDARY = Object.freeze({
  mode: "DEMO_DEVELOPMENT_ONLY" as const,
  label: "DEMO / DEVELOPMENT_ONLY",
  source: "CURRENT_MAIN_VIEW_MODEL" as const,
  transport: "WS_E_FRONTEND_ENTRYPOINT_UNWIRED" as const,
  authority: "READ_ONLY_VIEW_MODEL" as const
});

export const PERMISSION_SURFACE = Object.freeze([
  { level: "L0_READ", allowed: true, label: "Read evidence" },
  { level: "L1_DRAFT", allowed: true, label: "Create non-canonical draft" },
  { level: "L2_EXECUTE", allowed: false, label: "Execute unavailable" },
  { level: "L3_PUBLISH", allowed: false, label: "Publish unavailable" }
] as const);

export type AgentRole = "RESEARCH" | "DATA" | "REVIEWER";
export type SessionStatus = "DRAFT" | "PENDING" | "BLOCKED";
export type CanonicalTruthState = "UNKNOWN" | "NOT_FORMAL" | "FORMAL";
export type CanonicalAdmissionState = "UNKNOWN" | "PRE_ALPHA" | "FORMAL_ADMITTED";
export type ValidationState = "NOT_RUN" | "FAILED" | "PASSED";
export type TimelineState = "DRAFT" | "READ" | "PENDING" | "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "BLOCKED" | "NOT_RUN" | "PASSED" | "PRE_ALPHA";
export type EvidenceKind = "Truth / Admission" | "DatasetVersion" | "FactorEvaluation" | "Experiment Run" | "Experiment Attempt" | "RewardVector" | "ModelVersion" | "PredictionArtifact" | "StrategyDefinition" | "SignalArtifact" | "PortfolioIntent" | "Reviewer Findings";

export interface ResearchSessionView {
  sessionViewId: string;
  title: string;
  goal: string;
  status: SessionStatus;
  linkedExperimentRunId: string | null;
  linkedTaskId: string | null;
  lastEvidenceUpdate: string;
  evidenceIds: string[];
}

export interface AgentStatementView {
  id: string;
  role: AgentRole;
  type: "RESEARCH_DRAFT" | "DATA_REVIEW_FINDINGS" | "REVIEWER_FINDINGS";
  authorityStatus: "NON_CANONICAL";
  lifecycleState: "DRAFT";
  permission: "L1_DRAFT";
  title: string;
  body: string;
  evidenceIds: string[];
}

export interface EvidenceView {
  kind: EvidenceKind;
  objectId: string;
  title: string;
  summary: string;
  canonicalTruthState: CanonicalTruthState;
  canonicalAdmissionState: CanonicalAdmissionState;
  validationState: ValidationState;
  provenanceRefs: string[];
  reviewerFinding: string | null;
  facts: { label: string; value: string }[];
  openInLab: LabId;
  artifactId: string | null;
}

export interface TimelineEntryView {
  id: string;
  authority: "AGENT" | "PLAN" | "TASK" | "TOOL" | "EXPERIMENT" | "EVIDENCE" | "REVIEWER" | "VALIDATION" | "ADMISSION";
  state: TimelineState;
  title: string;
  detail: string;
  objectId: string | null;
  at: string;
}

export type RendererKey = "table" | "metric" | "text" | "details" | "chart" | "backtest-result";
export type ArtifactPayload =
  | { renderer: "table"; columns: string[]; rows: string[][] }
  | { renderer: "metric"; metrics: { label: string; value: string }[] }
  | { renderer: "text"; text: string }
  | { renderer: "details"; entries: { label: string; value: string }[] }
  | { renderer: "chart"; availability: "FUTURE_SLOT"; reason: string }
  | { renderer: "backtest-result"; availability: "FUTURE_SLOT"; reason: string };

export interface ArtifactView {
  artifactId: string;
  title: string;
  mediaType: string;
  provenanceRef: string;
  payload: ArtifactPayload;
}

export const ARTIFACT_RENDERER_REGISTRY = Object.freeze({
  table: { availability: "AVAILABLE", label: "Table" },
  metric: { availability: "AVAILABLE", label: "Metrics" },
  text: { availability: "AVAILABLE", label: "Text" },
  details: { availability: "AVAILABLE", label: "Structured details" },
  chart: { availability: "FUTURE_SLOT", label: "Chart" },
  "backtest-result": { availability: "FUTURE_SLOT", label: "Backtest / Result" }
} as const);

export function getRendererDefinition(renderer: string) {
  if (!Object.prototype.hasOwnProperty.call(ARTIFACT_RENDERER_REGISTRY, renderer)) throw new TypeError(`unknown artifact renderer: ${renderer}`);
  return ARTIFACT_RENDERER_REGISTRY[renderer as RendererKey];
}

export function assertSafeArtifactOutput(value: unknown): asserts value is ArtifactPayload {
  if (value === null || Array.isArray(value) || typeof value !== "object") throw new TypeError("artifact output must be an object");
  const envelope = value as Record<string, unknown>;
  if (typeof envelope.renderer !== "string") throw new TypeError("artifact renderer must be a string");
  getRendererDefinition(envelope.renderer);
  for (const forbidden of ["html", "jsx", "script", "javascript", "code"]) if (forbidden in envelope) throw new TypeError(`artifact output forbids ${forbidden}`);
  if (envelope.renderer === "table" && (!Array.isArray(envelope.columns) || !Array.isArray(envelope.rows))) throw new TypeError("table renderer requires columns and rows");
  if (envelope.renderer === "metric" && !Array.isArray(envelope.metrics)) throw new TypeError("metric renderer requires metrics");
  if (envelope.renderer === "text" && typeof envelope.text !== "string") throw new TypeError("text renderer requires text");
  if (envelope.renderer === "details" && !Array.isArray(envelope.entries)) throw new TypeError("details renderer requires entries");
  if ((envelope.renderer === "chart" || envelope.renderer === "backtest-result") && envelope.availability !== "FUTURE_SLOT") throw new TypeError("future renderer cannot claim current availability");
}

export function statusTone(state: TimelineState | SessionStatus): "success" | "danger" | "warning" | "neutral" | "draft" {
  if (state === "SUCCEEDED" || state === "PASSED") return "success";
  if (state === "FAILED" || state === "BLOCKED") return "danger";
  if (state === "RUNNING" || state === "PRE_ALPHA") return "warning";
  if (state === "DRAFT") return "draft";
  return "neutral";
}

export const FUTURE_EXTENSION_SLOTS = Object.freeze([
  { object: "TargetWeightVector", status: "NOT_CONNECTED", owner: "FUTURE_MAIN_CONTRACT" },
  { object: "RiskAdjustedWeightVector", status: "NOT_CONNECTED", owner: "FUTURE_MAIN_CONTRACT" },
  { object: "BacktestRunResult", status: "NOT_CONNECTED", owner: "FUTURE_MAIN_CONTRACT" }
] as const);
