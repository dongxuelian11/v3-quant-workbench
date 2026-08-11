import type { LabId } from "../../../../../packages/contracts/src/index";
import type {
  AgentWorkspaceBoundary,
  ArtifactView,
  CanonicalAdmissionState,
  CanonicalTruthState,
  EvidenceKind,
  EvidenceView,
  ResearchSessionView,
  ValidationState
} from "../agentWorkspace";
import type { ExactLineageRelationInput } from "./contracts";

export type EvidenceIntegrityStatus = "VERIFIED" | "FAILED" | "UNKNOWN" | "NOT_RUN";
export type DiscoveryScopeMode = "ACTIVE_SESSION" | "VISIBLE_WORKSPACE";
export type DiscoveryCompleteness = "DISCOVERY_SCOPE_LIMITED";
export type DiscoverySource =
  | "CURRENT_MAIN_CANONICAL_PROJECTION_VISIBLE_SCOPE"
  | "DEVELOPMENT_INTEGRATION_FIXTURE_VISIBLE_SCOPE"
  | "NO_CANONICAL_EVIDENCE_AVAILABLE_VISIBLE_SCOPE"
  | "BACKEND_RUNTIME_UNAVAILABLE_VISIBLE_SCOPE"
  | "UNKNOWN_SOURCE_VISIBLE_SCOPE";
export type RelationAvailability = "EXACT_RELATIONS_AVAILABLE" | "NO_KNOWN_RELATION";
export type LineageDirection = "UPSTREAM" | "DOWNSTREAM" | "BOTH";

export interface DiscoveryScope {
  readonly mode: DiscoveryScopeMode;
  readonly activeSessionId: string;
  readonly visibleSessionIds: readonly string[];
  readonly explicitlySelected: boolean;
  readonly completeness: DiscoveryCompleteness;
  readonly source: DiscoverySource;
}

export interface SourceEvidenceAuthorityView {
  readonly sourceObjectId: string;
  readonly canonicalTruthState: CanonicalTruthState;
  readonly canonicalAdmissionState: CanonicalAdmissionState;
  readonly validationState: ValidationState;
}

export interface EvidenceNodeView {
  readonly exactId: string;
  readonly nodeType: EvidenceKind | "Artifact";
  readonly displayLabel: string;
  readonly summary: string;
  readonly contentSha256: string | "UNKNOWN";
  readonly canonicalTruthState: CanonicalTruthState;
  readonly canonicalAdmissionState: CanonicalAdmissionState;
  readonly validationState: ValidationState;
  readonly integrityStatus: EvidenceIntegrityStatus;
  readonly provenanceRefs: readonly string[];
  readonly artifactRefs: readonly string[];
  readonly sessionLinks: readonly string[];
  readonly reviewerFinding: string | null;
  readonly openInLab: LabId;
  readonly sourceEvidenceAuthorities: readonly SourceEvidenceAuthorityView[];
}

export interface EvidenceEdgeView {
  readonly edgeId: string;
  readonly relationType: string;
  readonly sourceExactId: string;
  readonly sourceContentSha256: string;
  readonly targetExactId: string;
  readonly targetContentSha256: string;
  readonly bindingRef: string | null;
  readonly sourceAuthority: "EXPLICIT_EXACT_RELATION" | "EXPLICIT_ARTIFACT_REF";
}

export interface EvidenceGraphView {
  readonly authority: "READ_ONLY_UI_VIEW_NOT_GRAPH_AUTHORITY";
  readonly sourceBoundary: "EXPLICIT_EXACT_RELATIONS_ONLY";
  readonly discoveryScope: DiscoveryScope;
  readonly relationAvailability: RelationAvailability;
  readonly nodes: readonly EvidenceNodeView[];
  readonly edges: readonly EvidenceEdgeView[];
  readonly renderedNodeLimit: number;
  readonly truncated: boolean;
}

export interface EvidenceGraphFilter {
  readonly search: string;
  readonly nodeType: EvidenceNodeView["nodeType"] | "ALL";
  readonly truth: CanonicalTruthState | "ALL";
  readonly admission: CanonicalAdmissionState | "ALL";
  readonly validation: ValidationState | "ALL";
  readonly finding: "ALL" | "HAS_FINDING" | "NO_FINDING";
}

export interface BuildEvidenceGraphInput {
  readonly sessions: readonly ResearchSessionView[];
  readonly activeSessionId: string;
  readonly evidence: readonly EvidenceView[];
  readonly artifacts: readonly ArtifactView[];
  readonly exactRelations: readonly ExactLineageRelationInput[];
  readonly discoverySource: DiscoverySource | undefined;
  readonly scopeMode?: DiscoveryScopeMode;
  readonly explicitWorkspaceScope?: boolean;
}

const SHA256 = /^[0-9a-f]{64}$/;

export function exactSha256FromId(value: string): string | null {
  const match = /(?:^|_)sha256_([0-9a-f]{64})$/.exec(value);
  return match?.[1] ?? null;
}

export function discoverySourceFromAgentWorkspaceBoundary(boundary: AgentWorkspaceBoundary): DiscoverySource {
  if (boundary.mode === "LIVE_READ_ONLY" && boundary.source === "CURRENT_MAIN_CANONICAL_PROJECTION") return "CURRENT_MAIN_CANONICAL_PROJECTION_VISIBLE_SCOPE";
  if (boundary.mode === "DEVELOPMENT_INTEGRATION_FIXTURE" && boundary.source === "ACTUAL_CANONICAL_H_I_J_TEST_CHAIN") return "DEVELOPMENT_INTEGRATION_FIXTURE_VISIBLE_SCOPE";
  if (boundary.mode === "LIVE_READ_ONLY_NO_EVIDENCE" && boundary.source === "NO_CANONICAL_EVIDENCE_AVAILABLE") return "NO_CANONICAL_EVIDENCE_AVAILABLE_VISIBLE_SCOPE";
  if (boundary.mode === "BACKEND_DISCONNECTED" && boundary.source === "BACKEND_RUNTIME_UNAVAILABLE") return "BACKEND_RUNTIME_UNAVAILABLE_VISIBLE_SCOPE";
  return "UNKNOWN_SOURCE_VISIBLE_SCOPE";
}

export function labForEvidenceKind(kind: EvidenceKind | "Artifact", fallback: LabId = "research"): LabId {
  if (kind === "DatasetVersion" || kind === "FactorEvaluation" || kind === "Experiment Run" || kind === "Experiment Attempt" || kind === "RewardVector" || kind === "Truth / Admission" || kind === "Reviewer Findings") return "research";
  if (kind === "ModelVersion" || kind === "PredictionArtifact") return "model";
  if (kind === "StrategyDefinition" || kind === "SignalArtifact" || kind === "PortfolioIntent" || kind === "TargetWeightVector") return "strategy";
  if (kind === "RiskAdjustedWeightVector" || kind === "RiskDecisionReport" || kind === "BacktestRunSpec") return "backtest";
  if (kind === "BacktestRunResult") return "result";
  return fallback;
}

export function buildEvidenceGraphView(input: BuildEvidenceGraphInput): EvidenceGraphView {
  const scopeMode = input.scopeMode ?? "ACTIVE_SESSION";
  if (scopeMode === "VISIBLE_WORKSPACE" && input.explicitWorkspaceScope !== true) {
    throw new TypeError("broader visible-workspace discovery requires an explicit user scope switch");
  }
  const activeSession = input.sessions.find((session) => session.sessionViewId === input.activeSessionId);
  if (!activeSession) throw new TypeError(`unknown active Research Session ${input.activeSessionId}`);

  const visibleSessions = scopeMode === "ACTIVE_SESSION" ? [activeSession] : [...input.sessions];
  const visibleEvidenceIds = new Set(visibleSessions.flatMap((session) => [...session.evidenceIds]));
  const evidenceById = new Map<string, EvidenceView>();
  const nodes = new Map<string, EvidenceNodeView>();

  const addNode = (node: EvidenceNodeView) => {
    const existing = nodes.get(node.exactId);
    if (!existing) {
      nodes.set(node.exactId, node);
      return;
    }
    if (existing.contentSha256 !== "UNKNOWN" && node.contentSha256 !== "UNKNOWN" && existing.contentSha256 !== node.contentSha256) {
      throw new TypeError(`duplicate node conflict for ${node.exactId}`);
    }
    if (existing.nodeType !== node.nodeType && existing.nodeType !== "Artifact" && node.nodeType !== "Artifact") {
      throw new TypeError(`duplicate node type conflict for ${node.exactId}`);
    }
    nodes.set(node.exactId, {
      ...existing,
      contentSha256: existing.contentSha256 === "UNKNOWN" ? node.contentSha256 : existing.contentSha256,
      provenanceRefs: unique([...existing.provenanceRefs, ...node.provenanceRefs]),
      artifactRefs: unique([...existing.artifactRefs, ...node.artifactRefs]),
      sessionLinks: unique([...existing.sessionLinks, ...node.sessionLinks]),
      sourceEvidenceAuthorities: mergeSourceEvidenceAuthorities(existing.sourceEvidenceAuthorities, node.sourceEvidenceAuthorities)
    });
  };

  for (const item of input.evidence) {
    if (!visibleEvidenceIds.has(item.objectId)) continue;
    const prior = evidenceById.get(item.objectId);
    const observedSha = item.contentSha256 ?? exactSha256FromId(item.objectId) ?? "UNKNOWN";
    if (prior) {
      const priorSha = prior.contentSha256 ?? exactSha256FromId(prior.objectId) ?? "UNKNOWN";
      if (priorSha !== observedSha) throw new TypeError(`duplicate node conflict for ${item.objectId}`);
    }
    evidenceById.set(item.objectId, item);
    const sessionLinks = visibleSessions.filter((session) => session.evidenceIds.includes(item.objectId)).map((session) => session.sessionViewId);
    addNode({
      exactId: item.objectId,
      nodeType: item.kind,
      displayLabel: item.title,
      summary: item.summary,
      contentSha256: observedSha,
      canonicalTruthState: item.canonicalTruthState,
      canonicalAdmissionState: item.canonicalAdmissionState,
      validationState: item.validationState,
      integrityStatus: item.integrityStatus ?? "NOT_RUN",
      provenanceRefs: [...item.provenanceRefs],
      artifactRefs: item.artifactId ? [item.artifactId] : [],
      sessionLinks,
      reviewerFinding: item.reviewerFinding,
      openInLab: labForEvidenceKind(item.kind, item.openInLab),
      sourceEvidenceAuthorities: []
    });
  }

  const artifactsById = new Map(input.artifacts.map((artifact) => [artifact.artifactId, artifact]));
  for (const evidenceNode of [...nodes.values()]) {
    for (const artifactId of evidenceNode.artifactRefs) {
      if (artifactId === evidenceNode.exactId) continue;
      const artifact = artifactsById.get(artifactId);
      if (!artifact) continue;
      addNode({
        exactId: artifact.artifactId,
        nodeType: "Artifact",
        displayLabel: artifact.title,
        summary: `${artifact.mediaType} · passive renderer view`,
        contentSha256: artifact.contentSha256 ?? exactSha256FromId(artifact.artifactId) ?? "UNKNOWN",
        canonicalTruthState: "UNKNOWN",
        canonicalAdmissionState: "UNKNOWN",
        validationState: artifact.validationState ?? "NOT_RUN",
        integrityStatus: artifact.integrityStatus ?? "NOT_RUN",
        provenanceRefs: artifact.provenanceRefs ?? [artifact.provenanceRef],
        artifactRefs: [],
        sessionLinks: [...evidenceNode.sessionLinks],
        reviewerFinding: null,
        openInLab: artifact.openInLab ?? evidenceNode.openInLab,
        sourceEvidenceAuthorities: [{
          sourceObjectId: evidenceNode.exactId,
          canonicalTruthState: evidenceNode.canonicalTruthState,
          canonicalAdmissionState: evidenceNode.canonicalAdmissionState,
          validationState: evidenceNode.validationState
        }]
      });
    }
  }

  const edges: EvidenceEdgeView[] = [];
  const edgeKeys = new Set<string>();
  const addEdge = (edge: EvidenceEdgeView) => {
    const source = nodes.get(edge.sourceExactId);
    const target = nodes.get(edge.targetExactId);
    if (!source || !target) return;
    if (!SHA256.test(edge.sourceContentSha256) || !SHA256.test(edge.targetContentSha256)) throw new TypeError("exact lineage edge requires full lowercase SHA-256 values");
    if (source.contentSha256 !== edge.sourceContentSha256 || target.contentSha256 !== edge.targetContentSha256) throw new TypeError(`wrong hash edge rejected: ${edge.relationType}`);
    const key = [edge.sourceExactId, edge.sourceContentSha256, edge.targetExactId, edge.targetContentSha256, edge.relationType, edge.bindingRef ?? ""].join("\u0000");
    if (edgeKeys.has(key)) throw new TypeError(`duplicate exact lineage edge: ${edge.relationType}`);
    edgeKeys.add(key);
    edges.push(edge);
  };

  input.exactRelations.forEach((relation, index) => addEdge({
    edgeId: `exact-${index + 1}-${relation.relationType}`,
    relationType: relation.relationType,
    sourceExactId: relation.sourceExactId,
    sourceContentSha256: relation.sourceContentSha256,
    targetExactId: relation.targetExactId,
    targetContentSha256: relation.targetContentSha256,
    bindingRef: relation.bindingRef,
    sourceAuthority: "EXPLICIT_EXACT_RELATION"
  }));

  for (const evidenceNode of [...nodes.values()].filter((node) => node.nodeType !== "Artifact")) {
    for (const artifactId of evidenceNode.artifactRefs) {
      if (artifactId === evidenceNode.exactId) continue;
      const artifactNode = nodes.get(artifactId);
      if (!artifactNode || evidenceNode.contentSha256 === "UNKNOWN" || artifactNode.contentSha256 === "UNKNOWN") continue;
      addEdge({
        edgeId: `artifact-ref-${evidenceNode.exactId}-${artifactId}`,
        relationType: "EXPLICIT_ARTIFACT_REF",
        sourceExactId: evidenceNode.exactId,
        sourceContentSha256: evidenceNode.contentSha256,
        targetExactId: artifactId,
        targetContentSha256: artifactNode.contentSha256,
        bindingRef: artifactId,
        sourceAuthority: "EXPLICIT_ARTIFACT_REF"
      });
    }
  }

  const sortedNodes = [...nodes.values()].sort((left, right) => left.exactId.localeCompare(right.exactId));
  const sortedEdges = edges.sort(edgeOrder);
  return {
    authority: "READ_ONLY_UI_VIEW_NOT_GRAPH_AUTHORITY",
    sourceBoundary: "EXPLICIT_EXACT_RELATIONS_ONLY",
    discoveryScope: {
      mode: scopeMode,
      activeSessionId: activeSession.sessionViewId,
      visibleSessionIds: visibleSessions.map((session) => session.sessionViewId),
      explicitlySelected: scopeMode === "VISIBLE_WORKSPACE",
      completeness: "DISCOVERY_SCOPE_LIMITED",
      source: input.discoverySource ?? "UNKNOWN_SOURCE_VISIBLE_SCOPE"
    },
    relationAvailability: sortedEdges.length > 0 ? "EXACT_RELATIONS_AVAILABLE" : "NO_KNOWN_RELATION",
    nodes: sortedNodes,
    edges: sortedEdges,
    renderedNodeLimit: sortedNodes.length,
    truncated: false
  };
}

export function filterEvidenceGraph(view: EvidenceGraphView, filter: EvidenceGraphFilter): EvidenceGraphView {
  const query = filter.search.trim().toLowerCase();
  const nodes = view.nodes.filter((node) => {
    if (filter.nodeType !== "ALL" && node.nodeType !== filter.nodeType) return false;
    if (filter.truth !== "ALL" && node.canonicalTruthState !== filter.truth) return false;
    if (filter.admission !== "ALL" && node.canonicalAdmissionState !== filter.admission) return false;
    if (filter.validation !== "ALL" && node.validationState !== filter.validation) return false;
    if (filter.finding === "HAS_FINDING" && !node.reviewerFinding) return false;
    if (filter.finding === "NO_FINDING" && node.reviewerFinding) return false;
    if (!query) return true;
    return node.exactId.toLowerCase().startsWith(query)
      || node.artifactRefs.some((value) => value.toLowerCase().startsWith(query))
      || node.nodeType.toLowerCase().includes(query)
      || node.displayLabel.toLowerCase().includes(query);
  });
  return graphSubset(view, new Set(nodes.map((node) => node.exactId)), nodes.length, false);
}

export function boundedEvidenceNeighborhood(
  view: EvidenceGraphView,
  focusExactId: string | null,
  direction: LineageDirection = "BOTH",
  maxHops = 1,
  maxNodes = 60
): EvidenceGraphView {
  if (!Number.isInteger(maxHops) || maxHops < 0 || !Number.isInteger(maxNodes) || maxNodes < 1) throw new TypeError("bounded graph limits must be positive integers");
  if (view.nodes.length <= maxNodes && !focusExactId) return { ...view, renderedNodeLimit: maxNodes };
  const available = new Set(view.nodes.map((node) => node.exactId));
  const start = focusExactId && available.has(focusExactId) ? focusExactId : view.nodes[0]?.exactId;
  if (!start) return { ...view, renderedNodeLimit: maxNodes };

  const adjacency = new Map<string, string[]>();
  const link = (source: string, target: string) => adjacency.set(source, unique([...(adjacency.get(source) ?? []), target]));
  for (const edge of view.edges) {
    if (direction !== "UPSTREAM") link(edge.sourceExactId, edge.targetExactId);
    if (direction !== "DOWNSTREAM") link(edge.targetExactId, edge.sourceExactId);
  }
  const selected = new Set<string>([start]);
  let frontier = [start];
  for (let hop = 0; hop < maxHops && frontier.length > 0 && selected.size < maxNodes; hop += 1) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const adjacent of [...(adjacency.get(id) ?? [])].sort()) {
        if (selected.has(adjacent) || selected.size >= maxNodes) continue;
        selected.add(adjacent);
        next.push(adjacent);
      }
    }
    frontier = next;
  }
  return graphSubset(view, selected, maxNodes, selected.size < view.nodes.length);
}

export function exactRelationsForNode(view: EvidenceGraphView, exactId: string) {
  return {
    derivedFrom: view.edges.filter((edge) => edge.targetExactId === exactId),
    usedBy: view.edges.filter((edge) => edge.sourceExactId === exactId),
    availability: view.edges.some((edge) => edge.sourceExactId === exactId || edge.targetExactId === exactId)
      ? "EXACT_RELATIONS_AVAILABLE" as const
      : "NO_KNOWN_RELATION" as const
  };
}

export function exactBreadcrumb(view: EvidenceGraphView, focusExactId: string): readonly string[] {
  if (!view.nodes.some((node) => node.exactId === focusExactId)) return [];
  const incoming = new Map<string, EvidenceEdgeView[]>();
  for (const edge of view.edges) incoming.set(edge.targetExactId, [...(incoming.get(edge.targetExactId) ?? []), edge]);
  const path = [focusExactId];
  const visited = new Set(path);
  let current = focusExactId;
  while (true) {
    const parent = [...(incoming.get(current) ?? [])].sort(edgeOrder)[0];
    if (!parent || visited.has(parent.sourceExactId)) break;
    path.unshift(parent.sourceExactId);
    visited.add(parent.sourceExactId);
    current = parent.sourceExactId;
  }
  return path;
}

function graphSubset(view: EvidenceGraphView, exactIds: Set<string>, renderedNodeLimit: number, truncated: boolean): EvidenceGraphView {
  const nodes = view.nodes.filter((node) => exactIds.has(node.exactId));
  const edges = view.edges.filter((edge) => exactIds.has(edge.sourceExactId) && exactIds.has(edge.targetExactId));
  return {
    ...view,
    nodes,
    edges,
    relationAvailability: edges.length > 0 ? "EXACT_RELATIONS_AVAILABLE" : "NO_KNOWN_RELATION",
    renderedNodeLimit,
    truncated
  };
}

function edgeOrder(left: EvidenceEdgeView, right: EvidenceEdgeView) {
  return [left.sourceExactId, left.targetExactId, left.relationType, left.bindingRef ?? ""].join("\u0000")
    .localeCompare([right.sourceExactId, right.targetExactId, right.relationType, right.bindingRef ?? ""].join("\u0000"));
}

function unique<T>(values: readonly T[]): T[] {
  return [...new Set(values)];
}

function mergeSourceEvidenceAuthorities(
  left: readonly SourceEvidenceAuthorityView[],
  right: readonly SourceEvidenceAuthorityView[]
): SourceEvidenceAuthorityView[] {
  const merged = new Map(left.map((item) => [item.sourceObjectId, item]));
  for (const item of right) {
    const existing = merged.get(item.sourceObjectId);
    if (existing && (existing.canonicalTruthState !== item.canonicalTruthState
      || existing.canonicalAdmissionState !== item.canonicalAdmissionState
      || existing.validationState !== item.validationState)) {
      throw new TypeError(`conflicting source Evidence authority for ${item.sourceObjectId}`);
    }
    merged.set(item.sourceObjectId, item);
  }
  return [...merged.values()].sort((a, b) => a.sourceObjectId.localeCompare(b.sourceObjectId));
}
