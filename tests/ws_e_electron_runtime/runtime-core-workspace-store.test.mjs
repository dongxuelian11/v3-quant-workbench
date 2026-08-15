import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { CommandConflictError, DEFAULT_WORKSPACE } from "../../dist/packages/contracts/src/index.js";
import { WorkspaceStore, WorkspaceStoreError } from "../../dist/apps/desktop/src/main/runtimePersistence/workspaceStore.js";

async function freshStore(fixture) {
  const directory = await mkdtemp(join(tmpdir(), "v3-workspace-store-"));
  const storePath = join(directory, "v3-workbench-state.json");
  if (fixture !== undefined) await writeFile(storePath, fixture, "utf8");
  return { directory, storePath, store: new WorkspaceStore(storePath, { now: () => "2026-08-15T00:00:00.000Z" }) };
}

function command(id, name = "study.resume") {
  return { id, name, issuedAt: "2026-08-15T00:00:00.000Z" };
}

test("ENOENT initializes default state without touching the store file", async () => {
  const { store, storePath } = await freshStore();
  const loaded = await store.load();
  assert.equal(loaded.initializedFresh, true);
  assert.equal(loaded.quarantinedPath, null);
  assert.equal(loaded.state.activeLab, DEFAULT_WORKSPACE.activeLab);
  await assert.rejects(readFile(storePath, "utf8"), (error) => error.code === "ENOENT");
});

test("valid persisted state loads without quarantine", async () => {
  const valid = { ...structuredClone(DEFAULT_WORKSPACE), activeProject: "Persisted Project", executedCommandIds: ["cmd-1"], commandExecutionCount: { "cmd-1": 1 }, persistenceRevision: 3 };
  const { store } = await freshStore(JSON.stringify(valid));
  const loaded = await store.load();
  assert.equal(loaded.initializedFresh, false);
  assert.equal(loaded.quarantinedPath, null);
  assert.equal(loaded.state.activeProject, "Persisted Project");
  assert.deepEqual(loaded.state.executedCommandIds, ["cmd-1"]);
  assert.equal(loaded.state.persistenceRevision, 3);
});

test("malformed JSON is quarantined and never overwritten", async () => {
  const { store, storePath } = await freshStore("{ not json !");
  const loaded = await store.load();
  assert.equal(loaded.initializedFresh, true);
  assert.match(loaded.quarantinedPath, new RegExp(`^${storePath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\.corrupt-\\d+-[0-9a-f]{8}$`));
  assert.equal(await readFile(loaded.quarantinedPath, "utf8"), "{ not json !");
  assert.equal(store.snapshot().activeLab, DEFAULT_WORKSPACE.activeLab);
});

test("schema-invalid state is quarantined and never overwritten", async () => {
  const invalid = { ...structuredClone(DEFAULT_WORKSPACE), activeLab: "not-a-lab", extraUnknownField: true };
  const { store } = await freshStore(JSON.stringify(invalid));
  const loaded = await store.load();
  assert.equal(loaded.initializedFresh, true);
  assert.match(loaded.quarantinedPath, /\.corrupt-\d+-[0-9a-f]{8}$/);
  const quarantined = JSON.parse(await readFile(loaded.quarantinedPath, "utf8"));
  assert.equal(quarantined.activeLab, "not-a-lab");
});

test("permission-like read errors fail closed and never initialize defaults", async () => {
  const { storePath } = await freshStore();
  const permissionError = Object.assign(new Error("permission denied"), { code: "EACCES" });
  const blocked = new WorkspaceStore(storePath, {
    now: () => "2026-08-15T00:00:00.000Z",
    fileOps: {
      readFile: async () => { throw permissionError; },
      writeFileDurable: async () => {},
      rename: async () => {},
      mkdir: async () => {},
      unlinkBestEffort: async () => {}
    }
  });
  await assert.rejects(blocked.load(), (error) => error instanceof WorkspaceStoreError && error.code === "WORKSPACE_STORE_PERMISSION_DENIED");
});

test("generic read I/O errors fail closed and never initialize defaults", async () => {
  const { storePath } = await freshStore();
  const readError = Object.assign(new Error("io failure"), { code: "EIO" });
  const blocked = new WorkspaceStore(storePath, {
    now: () => "2026-08-15T00:00:00.000Z",
    fileOps: {
      readFile: async () => { throw readError; },
      writeFileDurable: async () => {},
      rename: async () => {},
      mkdir: async () => {},
      unlinkBestEffort: async () => {}
    }
  });
  await assert.rejects(blocked.load(), (error) => error instanceof WorkspaceStoreError && error.code === "WORKSPACE_STORE_READ_FAILED");
});

test("quarantine rename failure fails closed", async () => {
  const { storePath } = await freshStore("{ bad");
  const blocked = new WorkspaceStore(storePath, {
    now: () => "2026-08-15T00:00:00.000Z",
    fileOps: {
      readFile: async () => "{ bad",
      writeFileDurable: async () => {},
      rename: async () => { throw new Error("rename denied"); },
      mkdir: async () => {},
      unlinkBestEffort: async () => {}
    }
  });
  await assert.rejects(blocked.load(), (error) => error instanceof WorkspaceStoreError && error.code === "WORKSPACE_STORE_QUARANTINE_FAILED");
});

test("serialized saves preserve order without lost updates", async () => {
  const { store, storePath } = await freshStore();
  await store.load();
  const saves = [];
  for (let index = 0; index < 50; index += 1) {
    saves.push(store.saveUserState({ ...structuredClone(DEFAULT_WORKSPACE), activeProject: `project-${index}` }));
  }
  await Promise.all(saves);
  assert.equal(store.snapshot().activeProject, "project-49");
  const onDisk = JSON.parse(await readFile(storePath, "utf8"));
  assert.equal(onDisk.activeProject, "project-49");
  assert.equal(onDisk.persistenceRevision, 50);
});

test("unique temp files per write", async () => {
  const { store, storePath } = await freshStore();
  await store.load();
  const tempNames = [];
  const real = await import("node:fs/promises");
  const recording = new WorkspaceStore(storePath, {
    now: () => "2026-08-15T00:00:00.000Z",
    fileOps: {
      readFile: (path) => real.readFile(path, "utf8"),
      writeFileDurable: async (path, content) => {
        const handle = await real.open(path, "w");
        try { await handle.writeFile(content, "utf8"); await handle.sync(); } finally { await handle.close(); }
      },
      rename: async (from, to) => { tempNames.push(from); await real.rename(from, to); },
      mkdir: (path) => real.mkdir(path, { recursive: true }),
      unlinkBestEffort: async (path) => { try { await real.unlink(path); } catch { /* ignore */ } }
    }
  });
  await recording.load();
  await Promise.all([0, 1, 2].map((index) => recording.saveUserState({ ...structuredClone(DEFAULT_WORKSPACE), activeProject: `p-${index}` })));
  assert.equal(new Set(tempNames).size, 3);
  for (const name of tempNames) assert.match(name, /v3-workbench-state\.json\.\d+\.\d+\.tmp$/);
});

test("immediate duplicate command does not re-execute or re-persist", async () => {
  const { store, storePath } = await freshStore();
  await store.load();
  const first = await store.executeCommand(command("cmd-a"));
  assert.deepEqual(first, { id: "cmd-a", accepted: true, duplicate: false, executionCount: 1 });
  const diskAfterFirst = await readFile(storePath, "utf8");
  const second = await store.executeCommand(command("cmd-a"));
  assert.deepEqual(second, { id: "cmd-a", accepted: false, duplicate: true, executionCount: 1 });
  assert.equal(await readFile(storePath, "utf8"), diskAfterFirst);
});

test("201 commands then replaying the first remains duplicate with count 1", async () => {
  const { store } = await freshStore();
  await store.load();
  const first = await store.executeCommand(command("cmd-000"));
  assert.equal(first.accepted, true);
  for (let index = 1; index <= 200; index += 1) {
    const receipt = await store.executeCommand(command(`cmd-${String(index).padStart(3, "0")}`));
    assert.equal(receipt.accepted, true);
  }
  assert.equal(store.snapshot().executedCommandIds.length, 201);
  const replay = await store.executeCommand(command("cmd-000"));
  assert.deepEqual(replay, { id: "cmd-000", accepted: false, duplicate: true, executionCount: 1 });
});

test("restart rebuilds the runtime and replayed commands stay duplicate", async () => {
  const { store, storePath } = await freshStore();
  await store.load();
  const first = await store.executeCommand(command("cmd-restart"));
  assert.equal(first.accepted, true);
  const rebuilt = new WorkspaceStore(storePath, { now: () => "2026-08-15T00:00:00.000Z" });
  await rebuilt.load();
  assert.deepEqual(await rebuilt.executeCommand(command("cmd-restart")), { id: "cmd-restart", accepted: false, duplicate: true, executionCount: 1 });
});

test("stale renderer save cannot erase the command ledger", async () => {
  const { store } = await freshStore();
  await store.load();
  await store.executeCommand(command("cmd-stale"));
  const stale = structuredClone(DEFAULT_WORKSPACE);
  stale.activeProject = "stale renderer view";
  stale.executedCommandIds = [];
  stale.commandExecutionCount = {};
  await store.saveUserState(stale);
  assert.deepEqual(store.snapshot().executedCommandIds, ["cmd-stale"]);
  assert.equal(store.snapshot().activeProject, "stale renderer view");
  assert.deepEqual(await store.executeCommand(command("cmd-stale")), { id: "cmd-stale", accepted: false, duplicate: true, executionCount: 1 });
});

test("same id with incompatible command name fails closed without mutation", async () => {
  const { store, storePath } = await freshStore();
  await store.load();
  await store.executeCommand(command("cmd-conflict", "study.resume"));
  const diskBefore = await readFile(storePath, "utf8");
  await assert.rejects(store.executeCommand(command("cmd-conflict", "study.pause")), (error) => error instanceof CommandConflictError && error.code === "COMMAND_ID_CONFLICT");
  assert.equal(await readFile(storePath, "utf8"), diskBefore);
  assert.equal(store.snapshot().executedCommandIds.length, 1);
});

test("workspace reset keeps the runtime-owned command ledger", async () => {
  const { store } = await freshStore();
  await store.load();
  await store.executeCommand(command("cmd-reset"));
  await store.resetUserState();
  assert.deepEqual(store.snapshot().executedCommandIds, ["cmd-reset"]);
  assert.equal(store.snapshot().activeProject, DEFAULT_WORKSPACE.activeProject);
  assert.deepEqual(await store.executeCommand(command("cmd-reset")), { id: "cmd-reset", accepted: false, duplicate: true, executionCount: 1 });
});

test("durable event cursor persists, is monotonic, and survives restart", async () => {
  const { store, storePath } = await freshStore();
  await store.load();
  assert.equal(store.getProjectEventCursor("prj_1"), 0);
  await store.commitProjectEventCursor("prj_1", 42);
  await store.commitProjectEventCursor("prj_1", 7);
  assert.equal(store.getProjectEventCursor("prj_1"), 42);
  const rebuilt = new WorkspaceStore(storePath, { now: () => "2026-08-15T00:00:00.000Z" });
  await rebuilt.load();
  assert.equal(rebuilt.getProjectEventCursor("prj_1"), 42);
  assert.equal(JSON.parse(await readFile(storePath, "utf8")).projectEventCursors.prj_1, 42);
});
