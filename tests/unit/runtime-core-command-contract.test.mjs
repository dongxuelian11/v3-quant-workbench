import assert from "node:assert/strict";
import test from "node:test";

import { CommandConflictError, DEFAULT_WORKSPACE, applyCommandExactlyOnce } from "../../packages/contracts/src/index.ts";

function command(id, name = "study.resume") {
  return { id, name, issuedAt: "2026-08-15T00:00:00.000Z" };
}

function rematerialize(serialized) {
  return { ...structuredClone(DEFAULT_WORKSPACE), ...JSON.parse(JSON.stringify(serialized)) };
}

test("command ledger defaults carry durable binding and cursor fields", () => {
  assert.deepEqual(DEFAULT_WORKSPACE.executedCommands, {});
  assert.deepEqual(DEFAULT_WORKSPACE.projectEventCursors, {});
  assert.equal(DEFAULT_WORKSPACE.persistenceRevision, 0);
  assert.equal(DEFAULT_WORKSPACE.runtimeMeta.storeSchemaVersion, 2);
});

test("immediate duplicate command stays duplicate with the original count", () => {
  const first = applyCommandExactlyOnce(structuredClone(DEFAULT_WORKSPACE), command("cmd-a"));
  assert.deepEqual(first.receipt, { id: "cmd-a", accepted: true, duplicate: false, executionCount: 1 });
  const second = applyCommandExactlyOnce(first.state, command("cmd-a"));
  assert.deepEqual(second.receipt, { id: "cmd-a", accepted: false, duplicate: true, executionCount: 1 });
  assert.equal(second.state.model.studyState, "running");
});

test("201 commands then replaying the first remains duplicate with count 1", () => {
  let state = structuredClone(DEFAULT_WORKSPACE);
  const first = applyCommandExactlyOnce(state, command("cmd-000"));
  assert.equal(first.receipt.accepted, true);
  state = first.state;
  for (let index = 1; index <= 200; index += 1) {
    const applied = applyCommandExactlyOnce(state, command(`cmd-${String(index).padStart(3, "0")}`));
    assert.equal(applied.receipt.accepted, true);
    state = applied.state;
  }
  assert.equal(state.executedCommandIds.length, 201);
  const replay = applyCommandExactlyOnce(state, command("cmd-000"));
  assert.deepEqual(replay.receipt, { id: "cmd-000", accepted: false, duplicate: true, executionCount: 1 });
  assert.equal(replay.state.model.checkpoint, first.state.model.checkpoint);
});

test("restart replay after serialized persistence stays duplicate", () => {
  const applied = applyCommandExactlyOnce(structuredClone(DEFAULT_WORKSPACE), command("cmd-restart", "study.checkpoint"));
  assert.equal(applied.receipt.accepted, true);
  const restarted = rematerialize(applied.state);
  const replay = applyCommandExactlyOnce(restarted, command("cmd-restart", "study.checkpoint"));
  assert.deepEqual(replay.receipt, { id: "cmd-restart", accepted: false, duplicate: true, executionCount: 1 });
  assert.equal(replay.state.model.checkpoint, 19);
});

test("same id with incompatible command name fails closed before mutation", () => {
  const applied = applyCommandExactlyOnce(structuredClone(DEFAULT_WORKSPACE), command("cmd-conflict", "study.resume"));
  assert.throws(
    () => applyCommandExactlyOnce(applied.state, command("cmd-conflict", "study.pause")),
    (error) => error instanceof CommandConflictError && error.code === "COMMAND_ID_CONFLICT" && error.previousName === "study.resume" && error.nextName === "study.pause"
  );
  assert.equal(applied.state.executedCommandIds.length, 1);
});

test("binding survives a renderer snapshot that mirrors only legacy ledger fields", () => {
  const applied = applyCommandExactlyOnce(structuredClone(DEFAULT_WORKSPACE), command("cmd-binding", "study.resume"));
  const legacyMirror = { ...structuredClone(applied.state) };
  delete legacyMirror.executedCommands;
  const replay = applyCommandExactlyOnce(legacyMirror, command("cmd-binding", "study.resume"));
  assert.deepEqual(replay.receipt, { id: "cmd-binding", accepted: false, duplicate: true, executionCount: 1 });
});
