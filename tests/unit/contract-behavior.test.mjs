import test from "node:test";
import assert from "node:assert/strict";
import { LAB_IDS, DEFAULT_WORKSPACE, DEMO_TRUTH, applyCommandExactlyOnce } from "../../packages/contracts/src/index.ts";
import { modelFamilies, universeModes, researchSeries } from "../../apps/desktop/src/renderer/demo.ts";
import {
  AGENT_WORKSPACE_BOUNDARY,
  ARTIFACT_RENDERER_REGISTRY,
  FUTURE_EXTENSION_SLOTS,
  PERMISSION_SURFACE,
  assertSafeArtifactOutput,
  getRendererDefinition,
  statusTone
} from "../../apps/desktop/src/renderer/agentWorkspace.ts";
import { agentStatements, artifactViews, evidenceViews, researchSessions, timelineEntries } from "../../apps/desktop/src/renderer/agentWorkspaceFixture.ts";

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
  assert.equal(AGENT_WORKSPACE_BOUNDARY.mode, "DEMO_DEVELOPMENT_ONLY");
  assert.equal(AGENT_WORKSPACE_BOUNDARY.transport, "WS_E_FRONTEND_ENTRYPOINT_UNWIRED");
  assert.ok(researchSessions.length >= 3);
  assert.ok(evidenceViews.length >= 12);
  assert.ok(timelineEntries.some((entry) => entry.authority === "TOOL"));
  assert.ok(timelineEntries.some((entry) => entry.authority === "EXPERIMENT"));
  assert.ok(timelineEntries.some((entry) => entry.authority === "REVIEWER"));
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

test("H/I/J extension slots remain explicit non-connected future slots", () => {
  assert.deepEqual(FUTURE_EXTENSION_SLOTS.map((slot) => slot.object), ["TargetWeightVector", "RiskAdjustedWeightVector", "BacktestRunResult"]);
  assert.ok(FUTURE_EXTENSION_SLOTS.every((slot) => slot.status === "NOT_CONNECTED" && slot.owner === "FUTURE_MAIN_CONTRACT"));
});
