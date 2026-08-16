import {
  ROUND3_EVIDENCE_EVENT_TYPE,
  parseRound3ResearchEvidenceBundle,
  type CanonicalEvidenceProjectionV1,
  type Round3EvidenceKind,
  type Round3ResearchEvidenceBundleV1
} from "../../../../packages/contracts/src/round3Evidence";
import type {
  BackendRuntimeReadOnlyBridge,
  RuntimeConnectionState,
  TaskEventView
} from "../preload/backendRuntime/types";
import {
  AGENT_WORKSPACE_BOUNDARY,
  DEVELOPMENT_INTEGRATION_BOUNDARY,
  type AgentWorkspaceBoundary,
  type AgentWorkspaceData,
  type ArtifactPayload,
  type EvidenceView,
  type TimelineState
} from "./agentWorkspace";

declare global {
  interface Window {
    v3BackendRuntime: BackendRuntimeReadOnlyBridge;
  }
}

const EMPTY_SESSION_VIEW_ID = "session-view-round3-live-read-only";

const TITLES: Record<Round3EvidenceKind, string> = {
  PortfolioIntent: "Canonical 组合意图 · PortfolioIntent",
  TargetWeightVector: "Canonical 目标权重 · TargetWeightVector",
  RiskAdjustedWeightVector: "Canonical 风险调整权重 · RiskAdjustedWeightVector",
  RiskDecisionReport: "Canonical 风险决策报告 · RiskDecisionReport",
  BacktestRunSpec: "Canonical 回测运行规范 · BacktestRunSpec",
  BacktestRunResult: "Canonical 回测运行结果 · BacktestRunResult"
};

const LABS: Record<Round3EvidenceKind, EvidenceView["openInLab"]> = {
  PortfolioIntent: "strategy",
  TargetWeightVector: "strategy",
  RiskAdjustedWeightVector: "backtest",
  RiskDecisionReport: "backtest",
  BacktestRunSpec: "backtest",
  BacktestRunResult: "result"
};

export interface Round3AgentWorkspaceState {
  readonly connectionState: RuntimeConnectionState;
  readonly sourceMode: Round3ResearchEvidenceBundleV1["source_mode"] | null;
  readonly boundary: AgentWorkspaceBoundary;
  readonly data: AgentWorkspaceData;
}

function emptyData(): AgentWorkspaceData {
  return {
    sessions: [{
      sessionViewId: EMPTY_SESSION_VIEW_ID,
      title: "Round 3 canonical 证据",
      goal: "等待只读 canonical 组合 → 风险 → 回测证据。",
      status: "PENDING",
      linkedExperimentRunId: null,
      linkedTaskId: null,
      lastEvidenceUpdate: "NOT_AVAILABLE",
      evidenceIds: []
    }],
    statements: [],
    timeline: [],
    evidence: [],
    artifacts: []
  };
}

function disconnectedBoundary(connectionState: RuntimeConnectionState): AgentWorkspaceBoundary {
  return {
    mode: connectionState === "READY" ? "LIVE_READ_ONLY_NO_EVIDENCE" : "BACKEND_DISCONNECTED",
    label: connectionState === "READY" ? "实时只读 · 无证据 · LIVE_READ_ONLY" : "后端未连接 · BACKEND_DISCONNECTED",
    source: connectionState === "READY" ? "NO_CANONICAL_EVIDENCE_AVAILABLE" : "BACKEND_RUNTIME_UNAVAILABLE",
    transport: connectionState === "READY" ? "WS_E_READ_ONLY_CONNECTED" : `WS_E_${connectionState}`,
    authority: "READ_ONLY_VIEW_MODEL"
  };
}

export function initialRound3AgentWorkspaceState(): Round3AgentWorkspaceState {
  return { connectionState: "STOPPED", sourceMode: null, boundary: disconnectedBoundary("STOPPED"), data: emptyData() };
}

export function applyRound3ConnectionState(
  current: Round3AgentWorkspaceState,
  connectionState: RuntimeConnectionState
): Round3AgentWorkspaceState {
  if (current.data.evidence.length > 0) {
    const connectedBoundary = current.sourceMode === "DEVELOPMENT_INTEGRATION_FIXTURE"
      ? DEVELOPMENT_INTEGRATION_BOUNDARY
      : AGENT_WORKSPACE_BOUNDARY;
    return {
      ...current,
      connectionState,
      boundary: connectionState === "READY" ? connectedBoundary : disconnectedBoundary(connectionState)
    };
  }
  return { connectionState, sourceMode: current.sourceMode, boundary: disconnectedBoundary(connectionState), data: current.data };
}

function summary(projection: CanonicalEvidenceProjectionV1): string {
  return `${projection.source_artifact_type} · ${projection.canonical_truth_state} · ${projection.canonical_admission_state} · validation ${projection.validation_state}`;
}

function timelineState(projection: CanonicalEvidenceProjectionV1): TimelineState {
  if (projection.validation_state === "FAILED") return "FAILED";
  if (projection.validation_state === "PASSED") return "PASSED";
  if (projection.canonical_admission_state === "PRE_ALPHA") return "PRE_ALPHA";
  return "NOT_RUN";
}

function asEvidence(projection: CanonicalEvidenceProjectionV1): EvidenceView {
  return {
    kind: projection.source_artifact_type,
    objectId: projection.source_object_id,
    title: TITLES[projection.source_artifact_type],
    summary: summary(projection),
    canonicalTruthState: projection.canonical_truth_state,
    canonicalAdmissionState: projection.canonical_admission_state,
    validationState: projection.validation_state,
    provenanceRefs: [...projection.provenance_refs],
    reviewerFinding: null,
    facts: projection.view_facts.map((fact) => ({ ...fact })),
    openInLab: LABS[projection.source_artifact_type],
    artifactId: projection.source_object_id,
    contentSha256: projection.source_content_sha256,
    integrityStatus: "NOT_RUN"
  };
}

function fromBundle(bundle: Round3ResearchEvidenceBundleV1, occurredAt: string): AgentWorkspaceData {
  const evidence = bundle.projections.map(asEvidence);
  const evidenceIds = evidence.map((item) => item.objectId);
  return {
    sessions: [{
      sessionViewId: bundle.session_view_id,
      title: "Round 3 canonical 证据链",
      goal: "检查精确只读的组合 → 风险 → 回测来源链，不包含执行或发布权威。",
      status: "PENDING",
      linkedExperimentRunId: null,
      linkedTaskId: null,
      lastEvidenceUpdate: occurredAt,
      evidenceIds
    }],
    statements: [],
    evidence,
    artifacts: bundle.projections.map((projection) => ({
      artifactId: projection.source_object_id,
      title: TITLES[projection.source_artifact_type],
      mediaType: `application/vnd.${projection.source_artifact_type.toLowerCase()}+json`,
      provenanceRef: projection.provenance_refs.join(" · "),
      payload: projection.renderer_payload as ArtifactPayload,
      contentSha256: projection.source_content_sha256,
      sourceObjectId: projection.source_object_id,
      provenanceRefs: [...projection.provenance_refs],
      lineageRefs: [...projection.lineage_refs],
      integrityStatus: "NOT_RUN",
      validationState: projection.validation_state,
      openInLab: LABS[projection.source_artifact_type]
    })),
    exactRelations: bundle.lineage_edges.map((edge) => ({
      sourceExactId: edge.source_object_id,
      sourceContentSha256: edge.source_content_sha256,
      targetExactId: edge.target_object_id,
      targetContentSha256: edge.target_content_sha256,
      relationType: edge.relation,
      bindingRef: edge.binding_object_id
    })),
    timeline: bundle.projections.map((projection, index) => ({
      id: `round3-evidence-${index + 1}-${projection.source_object_id}`,
      sessionViewId: bundle.session_view_id,
      authority: "EVIDENCE",
      state: timelineState(projection),
      title: `${projection.source_artifact_type} 证据可用`,
      detail: summary(projection),
      objectId: projection.source_object_id,
      at: occurredAt
    }))
  };
}

export function applyRound3EvidenceEvent(
  current: Round3AgentWorkspaceState,
  event: TaskEventView
): Round3AgentWorkspaceState {
  if (event.event_type !== ROUND3_EVIDENCE_EVENT_TYPE) return current;
  const bundle = parseRound3ResearchEvidenceBundle(event.body);
  const boundary = bundle.source_mode === "DEVELOPMENT_INTEGRATION_FIXTURE"
    ? DEVELOPMENT_INTEGRATION_BOUNDARY
    : AGENT_WORKSPACE_BOUNDARY;
  return {
    connectionState: current.connectionState,
    sourceMode: bundle.source_mode,
    boundary: current.connectionState === "READY" ? boundary : disconnectedBoundary(current.connectionState),
    data: fromBundle(bundle, event.occurred_at)
  };
}
