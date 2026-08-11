import test from "node:test";
import assert from "node:assert/strict";
import { LAB_IDS, DEFAULT_WORKSPACE, DEMO_TRUTH, applyCommandExactlyOnce } from "../../packages/contracts/src/index.ts";
import { modelFamilies, universeModes, researchSeries } from "../../apps/desktop/src/renderer/demo.ts";
import {
  AGENT_WORKSPACE_BOUNDARY,
  ARTIFACT_RENDERER_REGISTRY,
  DEVELOPMENT_INTEGRATION_BOUNDARY,
  ROUND3_MAIN_CONTRACT_SLOTS,
  PERMISSION_SURFACE,
  assertSafeArtifactOutput,
  deriveAgentWorkspaceSessionScope,
  getRendererDefinition,
  resolveSessionArtifact,
  resolveSessionEvidenceSelection,
  validateAgentWorkspaceFixture,
  statusTone
} from "../../apps/desktop/src/renderer/agentWorkspace.ts";
import { agentStatements, artifactViews, evidenceViews, researchSessions, timelineEntries } from "../../apps/desktop/src/renderer/agentWorkspaceFixture.ts";

const workspaceFixture = { sessions: researchSessions, statements: agentStatements, timeline: timelineEntries, evidence: evidenceViews, artifacts: artifactViews };

test("product contract exposes exactly one ordered five-Lab workflow", () => {
  assert.deepEqual([...LAB_IDS], ["research", "strategy", "model", "backtest", "result"]);
  assert.equal(DEFAULT_WORKSPACE.activeLab, "research");
});

test("all nine Universe constructors and seven model families are first-class", () => {
  assert.equal(new Set(universeModes.map((item) => item.id)).size, 9);
  assert.equal(new Set(modelFamilies).size, 7);
  assert.deepEqual(modelFamilies, ["LightGBM", "XGBoost", "CatBoost", "sklearn-linear", "sklearn-tree-ensemble", "PyTorch-deep", "custom-plugin"]);
});

test("deterministic research provider is stable and truth-classified", () => {
  assert.equal(researchSeries.length, 72);
  assert.deepEqual(researchSeries, [...researchSeries]);
  assert.equal(DEMO_TRUTH.classification, "DEMO");
  assert.match(DEMO_TRUTH.label, /NOT FORMAL FINANCIAL OUTPUT/);
  assert.match(DEMO_TRUTH.wave3, /NOT_PRIOR_WAVE3_ACCEPTANCE/);
});

test("typed command transition is exactly-once and preserves resume state", () => {
  const command = { id: "cmd-unit-001", name: "study.resume", issuedAt: "2026-08-09T00:00:00.000Z" };
  const first = applyCommandExactlyOnce(structuredClone(DEFAULT_WORKSPACE), command);
  const second = applyCommandExactlyOnce(first.state, command);
  assert.deepEqual(first.receipt, { id: command.id, accepted: true, duplicate: false, executionCount: 1 });
  assert.deepEqual(second.receipt, { id: command.id, accepted: false, duplicate: true, executionCount: 1 });
  assert.equal(second.state.model.studyState, "running");
  assert.equal(second.state.commandExecutionCount[command.id], 1);
});

test("Agent Workspace fixture is explicit development-only view data", () => {
  assert.equal(AGENT_WORKSPACE_BOUNDARY.mode, "LIVE_READ_ONLY");
  assert.equal(DEVELOPMENT_INTEGRATION_BOUNDARY.mode, "DEVELOPMENT_INTEGRATION_FIXTURE");
  assert.equal(AGENT_WORKSPACE_BOUNDARY.transport, "WS_E_READ_ONLY_CONNECTED");
  assert.ok(researchSessions.length >= 3);
  assert.ok(evidenceViews.length >= 12);
  assert.ok(timelineEntries.some((entry) => entry.authority === "TOOL"));
  assert.ok(timelineEntries.some((entry) => entry.authority === "EXPERIMENT"));
  assert.ok(timelineEntries.some((entry) => entry.authority === "REVIEWER"));
  assert.equal(validateAgentWorkspaceFixture(workspaceFixture), true);
});

test("default Research Session scopes Agent statements and timeline exactly", () => {
  const session = researchSessions[0];
  const scope = deriveAgentWorkspaceSessionScope(session, agentStatements, timelineEntries, evidenceViews);
  assert.ok(scope.statements.length > 0);
  assert.ok(scope.timeline.length > 0);
  assert.ok(scope.statements.every((item) => item.sessionViewId === session.sessionViewId));
  assert.ok(scope.timeline.every((item) => item.sessionViewId === session.sessionViewId));
  assert.ok(!scope.statements.some((item) => item.id === "draft-data-002"));
  assert.ok(!scope.timeline.some((item) => item.id === "tl-10"));
});

test("switching Research Session replaces statements, timeline, and evidence set", () => {
  const first = deriveAgentWorkspaceSessionScope(researchSessions[0], agentStatements, timelineEntries, evidenceViews);
  const second = deriveAgentWorkspaceSessionScope(researchSessions[1], agentStatements, timelineEntries, evidenceViews);
  assert.deepEqual(second.statements.map((item) => item.id), ["draft-data-002"]);
  assert.deepEqual(second.timeline.map((item) => item.id), ["tl-09", "tl-10", "tl-11", "tl-12"]);
  assert.deepEqual(second.evidence.map((item) => item.objectId), researchSessions[1].evidenceIds);
  assert.ok(first.statements.every((item) => !second.statements.includes(item)));
  assert.ok(first.timeline.every((item) => !second.timeline.includes(item)));
});

test("Evidence navigation accepts linked evidence and rejects unlinked evidence as a no-op", () => {
  const scope = deriveAgentWorkspaceSessionScope(researchSessions[1], agentStatements, timelineEntries, evidenceViews);
  const current = scope.evidence[0];
  const linked = resolveSessionEvidenceSelection(scope.evidence, current.objectId, scope.evidence[1].objectId);
  const unlinked = resolveSessionEvidenceSelection(scope.evidence, linked.objectId, researchSessions[0].evidenceIds[1]);
  assert.equal(linked.objectId, scope.evidence[1].objectId);
  assert.equal(unlinked.objectId, linked.objectId);
});

test("switching session resets an invalid selected evidence and artifact without global fallback", () => {
  const first = deriveAgentWorkspaceSessionScope(researchSessions[0], agentStatements, timelineEntries, evidenceViews);
  const second = deriveAgentWorkspaceSessionScope(researchSessions[1], agentStatements, timelineEntries, evidenceViews);
  const prior = first.evidence.find((item) => item.kind === "RewardVector");
  const reset = resolveSessionEvidenceSelection(second.evidence, prior.objectId);
  const artifact = resolveSessionArtifact(reset, artifactViews);
  assert.equal(reset.objectId, researchSessions[1].evidenceIds[0]);
  assert.equal(artifact.artifactId, reset.artifactId);
  assert.notEqual(artifact.artifactId, prior.artifactId);
});

test("zero-evidence Research Session has explicit null evidence and artifact state", () => {
  const emptySession = researchSessions.find((session) => session.sessionViewId === "session-view-empty-004");
  const scope = deriveAgentWorkspaceSessionScope(emptySession, agentStatements, timelineEntries, evidenceViews);
  const selected = resolveSessionEvidenceSelection(scope.evidence, researchSessions[0].evidenceIds[0]);
  assert.deepEqual(scope, { statements: [], timeline: [], evidence: [] });
  assert.equal(selected, null);
  assert.equal(resolveSessionArtifact(selected, artifactViews), null);
});

test("fixture validator rejects statement evidence crossing a session boundary", () => {
  const fixture = structuredClone(workspaceFixture);
  fixture.statements.find((item) => item.id === "draft-research-001").evidenceIds.push(researchSessions[1].evidenceIds[0]);
  assert.throws(() => validateAgentWorkspaceFixture(fixture), /cross-session evidence/);
});

test("fixture validator rejects timeline evidence crossing a session boundary", () => {
  const fixture = structuredClone(workspaceFixture);
  fixture.timeline.find((item) => item.id === "tl-10").sessionViewId = researchSessions[0].sessionViewId;
  assert.throws(() => validateAgentWorkspaceFixture(fixture), /cross-session evidence/);
});

test("fixture validator permits shared evidence only through each session's explicit link", () => {
  const shared = researchSessions[0].evidenceIds.find((objectId) => researchSessions[1].evidenceIds.includes(objectId));
  assert.ok(shared);
  assert.equal(validateAgentWorkspaceFixture(workspaceFixture), true);
  const fixture = structuredClone(workspaceFixture);
  fixture.sessions[1].evidenceIds = fixture.sessions[1].evidenceIds.filter((objectId) => objectId !== shared);
  assert.throws(() => validateAgentWorkspaceFixture(fixture), /cross-session evidence/);
});

test("Agent permission surface allows only L0 read and L1 draft", () => {
  assert.deepEqual(PERMISSION_SURFACE.filter((item) => item.allowed).map((item) => item.level), ["L0_READ", "L1_DRAFT"]);
  assert.deepEqual(PERMISSION_SURFACE.filter((item) => !item.allowed).map((item) => item.level), ["L2_EXECUTE", "L3_PUBLISH"]);
  assert.ok(agentStatements.every((item) => item.authorityStatus === "NON_CANONICAL" && item.lifecycleState === "DRAFT" && item.permission === "L1_DRAFT"));
});

test("PENDING, NOT_RUN, and BLOCKED never receive success tone", () => {
  for (const state of ["PENDING", "NOT_RUN", "BLOCKED"]) assert.notEqual(statusTone(state), "success");
  assert.equal(statusTone("BLOCKED"), "danger");
  assert.equal(statusTone("SUCCEEDED"), "success");
  assert.equal(statusTone("PASSED"), "success");
});

test("Evidence Inspector fixtures keep exact IDs, truth, admission, and provenance", () => {
  for (const item of evidenceViews) {
    assert.match(item.objectId, /^(?:snp|dsv|fev|exprun|expatt|rwv|mdv|pred|sdv|sig|pint|rve)_sha256_[0-9a-f]{64}$/);
    assert.ok(["UNKNOWN", "NOT_FORMAL", "FORMAL"].includes(item.canonicalTruthState));
    assert.ok(["UNKNOWN", "PRE_ALPHA", "FORMAL_ADMITTED"].includes(item.canonicalAdmissionState));
    assert.ok(item.provenanceRefs.length > 0);
    assert.ok(item.artifactId === null || artifactViews.some((artifact) => artifact.artifactId === item.artifactId), `missing exact artifact view for ${item.objectId}`);
  }
});

test("artifact renderer registry is closed and executable payloads are rejected", () => {
  assert.deepEqual(Object.keys(ARTIFACT_RENDERER_REGISTRY), ["table", "metric", "text", "details", "chart", "backtest-result"]);
  for (const artifact of artifactViews) assert.doesNotThrow(() => assertSafeArtifactOutput(artifact.payload));
  assert.throws(() => getRendererDefinition("arbitrary-jsx"), /unknown artifact renderer/);
  assert.throws(() => assertSafeArtifactOutput({ renderer: "text", text: "x", html: "<script>bad()</script>" }), /forbids html/);
  assert.throws(() => assertSafeArtifactOutput({ renderer: "chart", availability: "AVAILABLE", reason: "bad claim" }), /cannot claim current availability/);
});

test("H/I/J main contract slots are connected read-only without a shadow owner", () => {
  assert.deepEqual(ROUND3_MAIN_CONTRACT_SLOTS.map((slot) => slot.object), ["TargetWeightVector", "RiskAdjustedWeightVector", "BacktestRunResult"]);
  assert.deepEqual(ROUND3_MAIN_CONTRACT_SLOTS.map((slot) => slot.owner), ["CANONICAL_H", "CANONICAL_I", "CANONICAL_J"]);
  assert.ok(ROUND3_MAIN_CONTRACT_SLOTS.every((slot) => slot.status === "CONNECTED_READ_ONLY_MAIN_CONTRACT"));
});
