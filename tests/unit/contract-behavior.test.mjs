import test from "node:test";
import assert from "node:assert/strict";
import { LAB_IDS, DEFAULT_WORKSPACE, DEMO_TRUTH, applyCommandExactlyOnce } from "../../packages/contracts/src/index.ts";
import { modelFamilies, universeModes, researchSeries } from "../../apps/desktop/src/renderer/demo.ts";

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
