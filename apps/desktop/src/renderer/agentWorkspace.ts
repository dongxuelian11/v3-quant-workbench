import type { LabId } from "../../../../packages/contracts/src/index";

export const AGENT_WORKSPACE_BOUNDARY = Object.freeze({
  mode: "LIVE_READ_ONLY" as const,
  label: "LIVE READ-ONLY",
  source: "CURRENT_MAIN_CANONICAL_PROJECTION" as const,
  transport: "WS_E_READ_ONLY_CONNECTED" as const,
  authority: "READ_ONLY_VIEW_MODEL" as const
});

export const DEVELOPMENT_INTEGRATION_BOUNDARY = Object.freeze({
  mode: "DEVELOPMENT_INTEGRATION_FIXTURE" as const,
  label: "DEVELOPMENT / INTEGRATION FIXTURE",
  source: "ACTUAL_CANONICAL_H_I_J_TEST_CHAIN" as const,
  transport: "WS_E_READ_ONLY_CONNECTED" as const,
  authority: "READ_ONLY_VIEW_MODEL" as const
});

export interface AgentWorkspaceBoundary {
  readonly mode: "LIVE_READ_ONLY" | "LIVE_READ_ONLY_NO_EVIDENCE" | "BACKEND_DISCONNECTED" | "DEVELOPMENT_INTEGRATION_FIXTURE";
  readonly label: string;
  readonly source: string;
  readonly transport: string;
  readonly authority: "READ_ONLY_VIEW_MODEL";
}

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
export type EvidenceKind = "Truth / Admission" | "DatasetVersion" | "FactorEvaluation" | "Experiment Run" | "Experiment Attempt" | "RewardVector" | "ModelVersion" | "PredictionArtifact" | "StrategyDefinition" | "SignalArtifact" | "PortfolioIntent" | "TargetWeightVector" | "RiskAdjustedWeightVector" | "RiskDecisionReport" | "BacktestRunSpec" | "BacktestRunResult" | "Reviewer Findings";

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
  sessionViewId: string;
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
  sessionViewId: string;
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
  | { renderer: "backtest-result"; availability: "FUTURE_SLOT"; reason: string }
  | {
      renderer: "backtest-result";
      resultId: string;
      runSpecId: string;
      nav: { columns: readonly ["Session date", "NAV"]; rows: readonly (readonly [string, string])[] };
      fillCount: number;
      diagnosticCount: number;
      cashLedgerSummary: string;
      feeLedgerSummary: string;
    };

export interface ArtifactView {
  artifactId: string;
  title: string;
  mediaType: string;
  provenanceRef: string;
  payload: ArtifactPayload;
}

export interface AgentWorkspaceFixture {
  sessions: readonly ResearchSessionView[];
  statements: readonly AgentStatementView[];
  timeline: readonly TimelineEntryView[];
  evidence: readonly EvidenceView[];
  artifacts: readonly ArtifactView[];
}

export interface AgentWorkspaceSessionScope {
  statements: AgentStatementView[];
  timeline: TimelineEntryView[];
  evidence: EvidenceView[];
}

export interface AgentWorkspaceData {
  sessions: readonly ResearchSessionView[];
  statements: readonly AgentStatementView[];
  timeline: readonly TimelineEntryView[];
  evidence: readonly EvidenceView[];
  artifacts: readonly ArtifactView[];
}

export function deriveAgentWorkspaceSessionScope(
  session: ResearchSessionView,
  statements: readonly AgentStatementView[],
  timeline: readonly TimelineEntryView[],
  evidence: readonly EvidenceView[]
): AgentWorkspaceSessionScope {
  const evidenceById = new Map(evidence.map((item) => [item.objectId, item]));
  return {
    statements: statements.filter((item) => item.sessionViewId === session.sessionViewId),
    timeline: timeline.filter((item) => item.sessionViewId === session.sessionViewId),
    evidence: session.evidenceIds.map((objectId) => evidenceById.get(objectId)).filter((item): item is EvidenceView => item !== undefined)
  };
}

export function resolveSessionEvidenceSelection(
  sessionEvidence: readonly EvidenceView[],
  currentObjectId: string | null,
  requestedObjectId?: string
): EvidenceView | null {
  const current = sessionEvidence.find((item) => item.objectId === currentObjectId) ?? null;
  if (requestedObjectId !== undefined) return sessionEvidence.find((item) => item.objectId === requestedObjectId) ?? current;
  return current ?? sessionEvidence[0] ?? null;
}

export function resolveSessionArtifact(selectedEvidence: EvidenceView | null, artifacts: readonly ArtifactView[]): ArtifactView | null {
  if (!selectedEvidence?.artifactId) return null;
  return artifacts.find((item) => item.artifactId === selectedEvidence.artifactId) ?? null;
}

export function validateAgentWorkspaceFixture(fixture: AgentWorkspaceFixture): true {
  assertUnique(fixture.sessions.map((item) => item.sessionViewId), "sessionViewId");
  assertUnique(fixture.statements.map((item) => item.id), "statement id");
  assertUnique(fixture.timeline.map((item) => item.id), "timeline id");
  assertUnique(fixture.evidence.map((item) => item.objectId), "evidence objectId");
  assertUnique(fixture.artifacts.map((item) => item.artifactId), "artifact id");

  const sessions = new Map(fixture.sessions.map((item) => [item.sessionViewId, item]));
  const evidenceIds = new Set(fixture.evidence.map((item) => item.objectId));
  const artifactIds = new Set(fixture.artifacts.map((item) => item.artifactId));
  const statements = new Map(fixture.statements.map((item) => [item.id, item]));

  for (const session of fixture.sessions) {
    assertUnique(session.evidenceIds, `session ${session.sessionViewId} evidenceId`);
    for (const objectId of session.evidenceIds) if (!evidenceIds.has(objectId)) throw new TypeError(`session ${session.sessionViewId} links unknown evidence ${objectId}`);
    if (session.linkedExperimentRunId && !session.evidenceIds.includes(session.linkedExperimentRunId)) throw new TypeError(`session ${session.sessionViewId} experiment run is not explicitly linked evidence`);
  }
  for (const item of fixture.evidence) if (item.artifactId && !artifactIds.has(item.artifactId)) throw new TypeError(`evidence ${item.objectId} links unknown artifact ${item.artifactId}`);

  for (const statement of fixture.statements) {
    const session = sessions.get(statement.sessionViewId);
    if (!session) throw new TypeError(`statement ${statement.id} links unknown session ${statement.sessionViewId}`);
    for (const objectId of statement.evidenceIds) if (!session.evidenceIds.includes(objectId)) throw new TypeError(`statement ${statement.id} cross-session evidence ${objectId}`);
  }

  for (const entry of fixture.timeline) {
    const session = sessions.get(entry.sessionViewId);
    if (!session) throw new TypeError(`timeline ${entry.id} links unknown session ${entry.sessionViewId}`);
    if (!entry.objectId) continue;
    if (evidenceIds.has(entry.objectId)) {
      if (!session.evidenceIds.includes(entry.objectId)) throw new TypeError(`timeline ${entry.id} cross-session evidence ${entry.objectId}`);
      continue;
    }
    const statement = statements.get(entry.objectId);
    if (statement) {
      if (statement.sessionViewId !== session.sessionViewId) throw new TypeError(`timeline ${entry.id} cross-session statement ${entry.objectId}`);
      continue;
    }
    if (entry.objectId === session.linkedTaskId || entry.objectId === session.linkedExperimentRunId) continue;
    throw new TypeError(`timeline ${entry.id} has unbound session object ${entry.objectId}`);
  }
  return true;
}

function assertUnique(values: readonly string[], label: string) {
  if (new Set(values).size !== values.length) throw new TypeError(`duplicate ${label}`);
}

export const ARTIFACT_RENDERER_REGISTRY = Object.freeze({
  table: { availability: "AVAILABLE", label: "Table" },
  metric: { availability: "AVAILABLE", label: "Metrics" },
  text: { availability: "AVAILABLE", label: "Text" },
  details: { availability: "AVAILABLE", label: "Structured details" },
  chart: { availability: "FUTURE_SLOT", label: "Chart" },
  "backtest-result": { availability: "AVAILABLE", label: "Backtest / Result" }
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
  const requireKeys = (keys: readonly string[]) => {
    const actual = Object.keys(envelope).sort();
    const expected = [...keys].sort();
    if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new TypeError("artifact renderer fields do not match the closed shape");
  };
  if (envelope.renderer === "table") { requireKeys(["renderer", "columns", "rows"]); if (!Array.isArray(envelope.columns) || !Array.isArray(envelope.rows)) throw new TypeError("table renderer requires columns and rows"); }
  if (envelope.renderer === "metric") { requireKeys(["renderer", "metrics"]); if (!Array.isArray(envelope.metrics)) throw new TypeError("metric renderer requires metrics"); }
  if (envelope.renderer === "text") { requireKeys(["renderer", "text"]); if (typeof envelope.text !== "string") throw new TypeError("text renderer requires text"); }
  if (envelope.renderer === "details") { requireKeys(["renderer", "entries"]); if (!Array.isArray(envelope.entries)) throw new TypeError("details renderer requires entries"); }
  if (envelope.renderer === "chart") { requireKeys(["renderer", "availability", "reason"]); if (envelope.availability !== "FUTURE_SLOT") throw new TypeError("future chart cannot claim current availability"); }
  if (envelope.renderer === "backtest-result") {
    if (envelope.availability === "FUTURE_SLOT") requireKeys(["renderer", "availability", "reason"]);
    else {
      requireKeys(["renderer", "resultId", "runSpecId", "nav", "fillCount", "diagnosticCount", "cashLedgerSummary", "feeLedgerSummary"]);
      if (typeof envelope.resultId !== "string" || typeof envelope.runSpecId !== "string" || envelope.nav === null || typeof envelope.nav !== "object" || !Number.isInteger(envelope.fillCount) || !Number.isInteger(envelope.diagnosticCount)) throw new TypeError("backtest-result renderer shape is invalid");
    }
  }
}

export function statusTone(state: TimelineState | SessionStatus): "success" | "danger" | "warning" | "neutral" | "draft" {
  if (state === "SUCCEEDED" || state === "PASSED") return "success";
  if (state === "FAILED" || state === "BLOCKED") return "danger";
  if (state === "RUNNING" || state === "PRE_ALPHA") return "warning";
  if (state === "DRAFT") return "draft";
  return "neutral";
}

export const ROUND3_MAIN_CONTRACT_SLOTS = Object.freeze([
  { object: "TargetWeightVector", status: "CONNECTED_READ_ONLY_MAIN_CONTRACT", owner: "CANONICAL_H" },
  { object: "RiskAdjustedWeightVector", status: "CONNECTED_READ_ONLY_MAIN_CONTRACT", owner: "CANONICAL_I" },
  { object: "BacktestRunResult", status: "CONNECTED_READ_ONLY_MAIN_CONTRACT", owner: "CANONICAL_J" }
] as const);
