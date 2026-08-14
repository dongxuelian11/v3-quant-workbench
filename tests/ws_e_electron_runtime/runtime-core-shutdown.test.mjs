import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough } from "node:stream";
import test from "node:test";

import { BackendSupervisor } from "../../dist/apps/desktop/src/main/backendRuntime/supervisor.js";
import { BackendTimeoutError } from "../../dist/apps/desktop/src/main/backendRuntime/errors.js";
import { FrameDecoder, encodeFrame } from "../../dist/apps/desktop/src/main/backendRuntime/framing.js";
import { ASL_SERVICES } from "../../dist/apps/desktop/src/main/backendRuntime/protocol.js";
import { WorkspaceStore, WorkspaceStoreError } from "../../dist/apps/desktop/src/main/runtimePersistence/workspaceStore.js";
import { DEFAULT_WORKSPACE } from "../../dist/packages/contracts/src/index.js";

const PROJECT_ID = `prj_${"0".repeat(26)}`;
const REVISION_ID = `pcr_${"0".repeat(26)}`;

function waitFor(predicate, timeoutMs = 2000) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const poll = () => {
      if (predicate()) resolve();
      else if (Date.now() - started > timeoutMs) reject(new Error("condition timed out"));
      else setTimeout(poll, 1);
    };
    poll();
  });
}

class MockProcess extends EventEmitter {
  stdin = new PassThrough();
  stdout = new PassThrough();
  stderr = new PassThrough();
  pid = 4321;
  terminated = false;
  onExit(listener) { this.once("exit", listener); }
  terminate() {
    if (this.terminated) return;
    this.terminated = true;
    queueMicrotask(() => this.emit("exit", 0, null));
  }
}

class ShutdownBackend {
  decoder = new FrameDecoder();
  prepareResponses = [];
  commitResponses = [];
  shutdownReadyCount = 0;
  shutdownCommittedCount = 0;

  constructor(process, mode = "happy") {
    this.process = process;
    this.mode = mode;
    process.stdin.on("data", (chunk) => {
      for (const message of this.decoder.feed(chunk)) this.onMessage(message);
    });
  }

  hello() {
    this.send({
      kind: "backend.hello",
      protocol: "v3.local/1.0",
      backend_instance_id: "backend-shutdown",
      pid: 4321,
      backend_version: "0.1.0",
      asl_versions: Object.fromEntries(ASL_SERVICES.map((service) => [service, "1.0.0"])),
      schema_compatibility: { min: "1.0.0", max: "1.0.0" },
      capabilities: [{ code: "TaskService", truth_state: "FORMAL" }],
      max_frame_bytes: 1024 * 1024,
      event_replay: true,
      nonce: "ab".repeat(32)
    });
  }

  onMessage(message) {
    if (message.kind === "supervisor.accept") {
      this.send({ kind: "backend.ready", backend_instance_id: "backend-shutdown", protocol: "v3.local/1.0", schema_version: "1.0.0" });
    } else if (message.kind === "events.replay") {
      const after = message.after_sequence;
      this.send({ kind: "events.replayComplete", last_sequence: after, next_after_sequence: after, high_watermark: 0, has_more: false });
    } else if (message.kind === "runtime.prepareShutdown") {
      this.shutdownReadyCount += 1;
      if (this.mode === "happy" || this.mode === "noCommit") {
        this.send({ kind: "runtime.shutdownReady", deadline_at: message.deadline_at });
      }
    } else if (message.kind === "runtime.commitShutdown") {
      this.shutdownCommittedCount += 1;
      if (this.mode === "happy") {
        this.send({ kind: "runtime.shutdownCommitted" });
        queueMicrotask(() => this.process.emit("exit", 0, null));
      }
    }
  }

  send(value) { this.process.stdout.write(encodeFrame(value)); }
}

class ShutdownMockFactory {
  constructor(mode) { this.mode = mode; }
  spawn() {
    const process = new MockProcess();
    const backend = new ShutdownBackend(process, this.mode);
    setImmediate(() => backend.hello());
    this.spawnResult = { process, backend };
    return process;
  }
}

function create(factory) {
  return new BackendSupervisor({
    pythonExecutable: "python.exe",
    backendWorkingDirectory: "D:\\V3\\backend",
    desktopVersion: "0.1.0",
    projectContext: { projectId: PROJECT_ID, projectContextRevisionId: REVISION_ID, lastDurableProjectEventSequence: 0 },
    handshakeTimeoutMs: 500,
    requestTimeoutMs: 500,
    autoReconnect: false
  }, factory, () => Buffer.alloc(32, 7));
}

test("happy prepare/commit shutdown handshake completes", async () => {
  const factory = new ShutdownMockFactory("happy");
  const supervisor = create(factory);
  await supervisor.start();
  await waitFor(() => supervisor.state === "READY");
  await supervisor.shutdown(1000);
  assert.equal(supervisor.state, "STOPPED");
  assert.equal(factory.spawnResult.backend.shutdownReadyCount, 1);
  assert.equal(factory.spawnResult.backend.shutdownCommittedCount, 1);
  // The backend exits by itself after commitShutdown; the supervisor must
  // observe the exit and reach STOPPED without spawning any fallback.
});

test("prepare timeout forces a shutdown fallback", async () => {
  const factory = new ShutdownMockFactory("silent");
  const supervisor = create(factory);
  await supervisor.start();
  await waitFor(() => supervisor.state === "READY");
  await assert.rejects(supervisor.shutdown(100), (error) => error instanceof BackendTimeoutError && /prepare shutdown timed out/.test(error.message));
  assert.equal(supervisor.state, "STOPPED");
  assert.equal(factory.spawnResult.process.terminated, true);
  assert.equal(factory.spawnResult.backend.shutdownCommittedCount, 0, "commit must not be sent after a failed prepare");
});

test("commit timeout forces a shutdown fallback", async () => {
  const factory = new ShutdownMockFactory("noCommit");
  const supervisor = create(factory);
  await supervisor.start();
  await waitFor(() => supervisor.state === "READY");
  await assert.rejects(supervisor.shutdown(100), (error) => error instanceof BackendTimeoutError && /commit shutdown timed out/.test(error.message));
  assert.equal(supervisor.state, "STOPPED");
  assert.equal(factory.spawnResult.process.terminated, true);
  assert.equal(factory.spawnResult.backend.shutdownReadyCount, 1);
});

test("shutdown flush drains pending persistence and then rejects new mutations", async () => {
  const directory = await mkdtemp(join(tmpdir(), "v3-shutdown-store-"));
  const storePath = join(directory, "v3-workbench-state.json");
  const store = new WorkspaceStore(storePath, { now: () => "2026-08-15T00:00:00.000Z" });
  await store.load();
  const saves = [0, 1, 2].map((index) => store.saveUserState({ ...structuredClone(DEFAULT_WORKSPACE), activeProject: `project-${index}` }));
  await store.flush();
  await Promise.all(saves);
  assert.equal(JSON.parse(await readFile(storePath, "utf8")).activeProject, "project-2");
  store.beginShutdown();
  await assert.rejects(
    store.saveUserState({ ...structuredClone(DEFAULT_WORKSPACE) }),
    (error) => error instanceof WorkspaceStoreError && error.code === "WORKSPACE_STORE_SHUTTING_DOWN"
  );
});

test("restart integrity: final state survives a full shutdown cycle", async () => {
  const directory = await mkdtemp(join(tmpdir(), "v3-shutdown-restart-"));
  const storePath = join(directory, "v3-workbench-state.json");
  const store = new WorkspaceStore(storePath, { now: () => "2026-08-15T00:00:00.000Z" });
  await store.load();
  await store.executeCommand({ id: "cmd-before-quit", name: "study.checkpoint", issuedAt: "2026-08-15T00:00:00.000Z" });
  await store.commitProjectEventCursor(PROJECT_ID, 7);
  await store.flush();
  store.beginShutdown();
  const rebuilt = new WorkspaceStore(storePath, { now: () => "2026-08-15T00:00:00.000Z" });
  await rebuilt.load();
  assert.equal(rebuilt.getProjectEventCursor(PROJECT_ID), 7);
  assert.deepEqual(await rebuilt.executeCommand({ id: "cmd-before-quit", name: "study.checkpoint", issuedAt: "2026-08-15T00:00:00.000Z" }), {
    id: "cmd-before-quit", accepted: false, duplicate: true, executionCount: 1
  });
});
