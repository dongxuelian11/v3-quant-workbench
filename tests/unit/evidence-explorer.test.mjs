import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LAB_IDS } from "../../packages/contracts/src/index.ts";
import {
  boundedEvidenceNeighborhood,
  buildEvidenceGraphView,
  discoverySourceFromAgentWorkspaceBoundary,
  exactBreadcrumb,
  exactRelationsForNode,
  filterEvidenceGraph,
  labForEvidenceKind
} from "../../apps/desktop/src/renderer/evidence_explorer/model.ts";

const sha = (value) => value.repeat(64);
const id = (prefix, value) => `${prefix}_sha256_${sha(value)}`;

function evidence(kind, exactId, title, artifactId = null, overrides = {}) {
  return {
    kind,
    objectId: exactId,
    title,
    summary: `${kind} exact test evidence`,
    canonicalTruthState: "NOT_FORMAL",
    canonicalAdmissionState: "PRE_ALPHA",
    validationState: "NOT_RUN",
    provenanceRefs: [`prov:${exactId}`],
    reviewerFinding: null,
    facts: [],
    openInLab: labForEvidenceKind(kind),
    artifactId,
    contentSha256: exactId.slice(-64),
    integrityStatus: "NOT_RUN",
    ...overrides
  };
}

const intentId = id("pint", "1");
const targetId = id("twv", "2");
const riskId = id("rawv", "3");
const specId = id("btrs", "4");
const resultId = id("btrr", "5");
const artifactId = id("art", "6");
const sharedId = id("dsv", "7");
const otherId = id("mdv", "8");

const sessions = [
  { sessionViewId: "session-a", title: "A", goal: "A", status: "PENDING", linkedExperimentRunId: null, linkedTaskId: null, lastEvidenceUpdate: "now", evidenceIds: [intentId, targetId, riskId, specId, resultId, sharedId] },
  { sessionViewId: "session-b", title: "B", goal: "B", status: "PENDING", linkedExperimentRunId: null, linkedTaskId: null, lastEvidenceUpdate: "now", evidenceIds: [sharedId, otherId] }
];

const evidenceItems = [
  evidence("PortfolioIntent", intentId, "Intent"),
  evidence("TargetWeightVector", targetId, "Target"),
  evidence("RiskAdjustedWeightVector", riskId, "Risk"),
  evidence("BacktestRunSpec", specId, "Run spec"),
  evidence("BacktestRunResult", resultId, "Result", artifactId, { validationState: "PASSED" }),
  evidence("DatasetVersion", sharedId, "Shared dataset"),
  evidence("ModelVersion", otherId, "Other-session model")
];

const artifacts = [{
  artifactId,
  title: "Result bytes",
  mediaType: "application/json",
  provenanceRef: `prov:${resultId}`,
  payload: { renderer: "details", entries: [] },
  contentSha256: sha("6"),
  sourceObjectId: resultId,
  integrityStatus: "NOT_RUN",
  validationState: "PASSED",
  openInLab: "result"
}];

const exactRelations = [
  relation(intentId, targetId, "PORTFOLIO_INTENT_SOURCE"),
  relation(targetId, riskId, "RISK_APPLICATION_TARGET_BINDING", id("rar", "a")),
  relation(riskId, specId, "SCHEDULED_WEIGHTS_VECTOR"),
  relation(specId, resultId, "BACKTEST_RUN_SPEC_RESULT_BINDING")
];

function relation(sourceExactId, targetExactId, relationType, bindingRef = null) {
  return { sourceExactId, sourceContentSha256: sourceExactId.slice(-64), targetExactId, targetContentSha256: targetExactId.slice(-64), relationType, bindingRef };
}

function graph(overrides = {}) {
  return buildEvidenceGraphView({ sessions, activeSessionId: "session-a", evidence: evidenceItems, artifacts, exactRelations, discoverySource: "CURRENT_MAIN_CANONICAL_PROJECTION_VISIBLE_SCOPE", ...overrides });
}

test("exact Round 3 lineage and explicit Artifact refs are the only graph edges", () => {
  const view = graph();
  assert.equal(view.authority, "READ_ONLY_UI_VIEW_NOT_GRAPH_AUTHORITY");
  assert.equal(view.sourceBoundary, "EXPLICIT_EXACT_RELATIONS_ONLY");
  assert.deepEqual(view.edges.filter((edge) => edge.sourceAuthority === "EXPLICIT_EXACT_RELATION").map((edge) => edge.relationType).sort(), [
    "PORTFOLIO_INTENT_SOURCE", "RISK_APPLICATION_TARGET_BINDING", "SCHEDULED_WEIGHTS_VECTOR", "BACKTEST_RUN_SPEC_RESULT_BINDING"
  ].sort());
  assert.ok(view.edges.some((edge) => edge.relationType === "EXPLICIT_ARTIFACT_REF" && edge.targetExactId === artifactId));
});

test("used-by is only the reverse index of accepted exact edges", () => {
  const relations = exactRelationsForNode(graph(), targetId);
  assert.deepEqual(relations.derivedFrom.map((edge) => edge.sourceExactId), [intentId]);
  assert.deepEqual(relations.usedBy.map((edge) => edge.targetExactId), [riskId]);
});

test("missing relation is not inferred from labels, hashes, time, symbol, or prefix", () => {
  const view = graph({ exactRelations: [] });
  const relations = exactRelationsForNode(view, intentId);
  assert.equal(relations.availability, "NO_KNOWN_RELATION");
  assert.deepEqual(relations.derivedFrom, []);
  assert.deepEqual(relations.usedBy, []);
});

test("wrong endpoint hash edge is rejected fail-closed", () => {
  const wrong = structuredClone(exactRelations);
  wrong[0].targetContentSha256 = sha("f");
  assert.throws(() => graph({ exactRelations: wrong }), /wrong hash edge rejected/);
});

test("duplicate node with conflicting exact content hash is rejected", () => {
  const conflict = { ...evidenceItems[0], contentSha256: sha("f") };
  assert.throws(() => graph({ evidence: [...evidenceItems, conflict] }), /duplicate node conflict/);
});

test("active session isolation and shared evidence require explicit session links", () => {
  const active = graph();
  assert.ok(!active.nodes.some((node) => node.exactId === otherId));
  assert.deepEqual(active.nodes.find((node) => node.exactId === sharedId).sessionLinks, ["session-a"]);
  const workspace = graph({ scopeMode: "VISIBLE_WORKSPACE", explicitWorkspaceScope: true });
  assert.ok(workspace.nodes.some((node) => node.exactId === otherId));
  assert.deepEqual(workspace.nodes.find((node) => node.exactId === sharedId).sessionLinks, ["session-a", "session-b"]);
});

test("broader workspace scope is explicit only and remains discovery-limited", () => {
  assert.throws(() => graph({ scopeMode: "VISIBLE_WORKSPACE" }), /explicit user scope switch/);
  const workspace = graph({ scopeMode: "VISIBLE_WORKSPACE", explicitWorkspaceScope: true });
  assert.equal(workspace.discoveryScope.explicitlySelected, true);
  assert.equal(workspace.discoveryScope.completeness, "DISCOVERY_SCOPE_LIMITED");
  assert.equal(workspace.discoveryScope.source, "CURRENT_MAIN_CANONICAL_PROJECTION_VISIBLE_SCOPE");
});

test("discovery source is mapped from the real Agent Workspace boundary", () => {
  assert.equal(discoverySourceFromAgentWorkspaceBoundary({ mode: "LIVE_READ_ONLY", source: "CURRENT_MAIN_CANONICAL_PROJECTION" }), "CURRENT_MAIN_CANONICAL_PROJECTION_VISIBLE_SCOPE");
  assert.equal(discoverySourceFromAgentWorkspaceBoundary({ mode: "DEVELOPMENT_INTEGRATION_FIXTURE", source: "ACTUAL_CANONICAL_H_I_J_TEST_CHAIN" }), "DEVELOPMENT_INTEGRATION_FIXTURE_VISIBLE_SCOPE");
  assert.doesNotMatch(discoverySourceFromAgentWorkspaceBoundary({ mode: "DEVELOPMENT_INTEGRATION_FIXTURE", source: "ACTUAL_CANONICAL_H_I_J_TEST_CHAIN" }), /OFFICIAL_REPOSITORY/);
});

test("scope expansion never changes upstream discovery source authority", () => {
  const active = graph({ discoverySource: "DEVELOPMENT_INTEGRATION_FIXTURE_VISIBLE_SCOPE" });
  const workspace = graph({ discoverySource: "DEVELOPMENT_INTEGRATION_FIXTURE_VISIBLE_SCOPE", scopeMode: "VISIBLE_WORKSPACE", explicitWorkspaceScope: true });
  assert.equal(active.discoveryScope.source, "DEVELOPMENT_INTEGRATION_FIXTURE_VISIBLE_SCOPE");
  assert.equal(workspace.discoveryScope.source, active.discoveryScope.source);
});

test("empty, disconnected, and missing discovery sources remain explicit and fail closed", () => {
  assert.equal(discoverySourceFromAgentWorkspaceBoundary({ mode: "LIVE_READ_ONLY_NO_EVIDENCE", source: "NO_CANONICAL_EVIDENCE_AVAILABLE" }), "NO_CANONICAL_EVIDENCE_AVAILABLE_VISIBLE_SCOPE");
  assert.equal(discoverySourceFromAgentWorkspaceBoundary({ mode: "BACKEND_DISCONNECTED", source: "BACKEND_RUNTIME_UNAVAILABLE" }), "BACKEND_RUNTIME_UNAVAILABLE_VISIBLE_SCOPE");
  assert.equal(graph({ discoverySource: undefined }).discoveryScope.source, "UNKNOWN_SOURCE_VISIBLE_SCOPE");
  assert.equal(discoverySourceFromAgentWorkspaceBoundary({ mode: "LIVE_READ_ONLY", source: "BACKEND_RUNTIME_UNAVAILABLE" }), "UNKNOWN_SOURCE_VISIBLE_SCOPE");
});

test("truth, admission, validation, content hash, and integrity remain distinct", () => {
  const result = graph().nodes.find((node) => node.exactId === resultId);
  assert.equal(result.canonicalTruthState, "NOT_FORMAL");
  assert.equal(result.canonicalAdmissionState, "PRE_ALPHA");
  assert.equal(result.validationState, "PASSED");
  assert.equal(result.contentSha256, sha("5"));
  assert.equal(result.integrityStatus, "NOT_RUN");
});

test("distinct Artifact owns no inherited Truth, Admission, Validation, or integrity state", () => {
  const artifactWithoutAuthority = { ...artifacts[0] };
  delete artifactWithoutAuthority.validationState;
  delete artifactWithoutAuthority.integrityStatus;
  const artifactNode = graph({ artifacts: [artifactWithoutAuthority] }).nodes.find((node) => node.exactId === artifactId);
  assert.equal(artifactNode.canonicalTruthState, "UNKNOWN");
  assert.equal(artifactNode.canonicalAdmissionState, "UNKNOWN");
  assert.equal(artifactNode.validationState, "NOT_RUN");
  assert.equal(artifactNode.integrityStatus, "NOT_RUN");
  assert.equal(artifactNode.contentSha256, sha("6"));
});

test("source Evidence authority stays separately visible on a distinct Artifact", () => {
  const artifactNode = graph().nodes.find((node) => node.exactId === artifactId);
  assert.deepEqual(artifactNode.sourceEvidenceAuthorities, [{
    sourceObjectId: resultId,
    canonicalTruthState: "NOT_FORMAL",
    canonicalAdmissionState: "PRE_ALPHA",
    validationState: "PASSED"
  }]);
  assert.equal(artifactNode.validationState, "PASSED");
  assert.equal(artifactNode.integrityStatus, "NOT_RUN");
});

test("graph and list consume one bounded node set; focus expansion is directional", () => {
  const view = graph();
  const upstream = boundedEvidenceNeighborhood(view, riskId, "UPSTREAM", 1, 60);
  const downstream = boundedEvidenceNeighborhood(view, riskId, "DOWNSTREAM", 1, 60);
  assert.deepEqual(upstream.nodes.map((node) => node.exactId), [riskId, targetId].sort());
  assert.deepEqual(downstream.nodes.map((node) => node.exactId), [riskId, specId].sort());
});

test("exact filters and breadcrumb use only accepted nodes and edges", () => {
  const view = graph();
  const filtered = filterEvidenceGraph(view, { search: "Target", nodeType: "ALL", truth: "ALL", admission: "PRE_ALPHA", validation: "NOT_RUN", finding: "NO_FINDING" });
  assert.deepEqual(filtered.nodes.map((node) => node.exactId), [targetId]);
  assert.deepEqual(exactBreadcrumb(view, resultId), [intentId, targetId, riskId, specId, resultId]);
});

test("Open-in-Lab mappings preserve exactly five canonical Labs", () => {
  assert.deepEqual([...LAB_IDS], ["research", "strategy", "model", "backtest", "result"]);
  assert.equal(labForEvidenceKind("FactorEvaluation"), "research");
  assert.equal(labForEvidenceKind("PredictionArtifact"), "model");
  assert.equal(labForEvidenceKind("SignalArtifact"), "strategy");
  assert.equal(labForEvidenceKind("RiskDecisionReport"), "backtest");
  assert.equal(labForEvidenceKind("BacktestRunResult"), "result");
});

test("bounded large fixture returns promptly without rendering a hairball", () => {
  const count = 600;
  const ids = Array.from({ length: count }, (_, index) => `obj_sha256_${index.toString(16).padStart(64, "0")}`);
  const largeSession = { ...sessions[0], sessionViewId: "large", evidenceIds: ids };
  const largeEvidence = ids.map((exactId, index) => evidence("DatasetVersion", exactId, `Node ${index}`));
  const largeRelations = ids.slice(1).map((exactId, index) => relation(ids[index], exactId, "EXPLICIT_TEST_CHAIN"));
  const started = performance.now();
  const bounded = boundedEvidenceNeighborhood(buildEvidenceGraphView({ sessions: [largeSession], activeSessionId: "large", evidence: largeEvidence, artifacts: [], exactRelations: largeRelations, discoverySource: "CURRENT_MAIN_CANONICAL_PROJECTION_VISIBLE_SCOPE" }), ids[300], "BOTH", 30, 60);
  assert.ok(performance.now() - started < 1000);
  assert.equal(bounded.nodes.length, 60);
  assert.equal(bounded.truncated, true);
});

test("Artifact Viewer and Explorer keep unsupported content passive and expose keyboard/a11y controls", () => {
  const artifactSource = readFileSync(new URL("../../apps/desktop/src/renderer/components/ArtifactViewer.tsx", import.meta.url), "utf8");
  const explorerSource = readFileSync(new URL("../../apps/desktop/src/renderer/evidence_explorer/EvidenceExplorer.tsx", import.meta.url), "utf8");
  assert.match(artifactSource, /渲染器不受支持 · 被动安全状态/);
  assert.match(artifactSource, /未执行 HTML、脚本、嵌入式活动内容或文件系统目标/);
  assert.match(artifactSource, /内容 SHA-256/);
  assert.match(artifactSource, /产物验证/);
  assert.match(artifactSource, /来源证据验证/);
  assert.doesNotMatch(artifactSource, /artifact\.validationState \?\? evidence\?\.validationState/);
  assert.doesNotMatch(artifactSource, /artifact\.integrityStatus \?\? evidence\?\.integrityStatus/);
  assert.match(artifactSource, /复制产物 ID/);
  assert.match(explorerSource, /ArrowDown/);
  assert.match(explorerSource, /aria-label="精确来源链面包屑"/);
  assert.match(explorerSource, /onlyRenderVisibleElements/);
  assert.match(explorerSource, /data-testid="evidence-graph"/);
  assert.match(explorerSource, /data-testid="evidence-list"/);
});
