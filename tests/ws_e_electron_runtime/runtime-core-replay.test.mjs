import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import test from "node:test";

import { BackendSupervisor } from "../../dist/apps/desktop/src/main/backendRuntime/supervisor.js";
import { FrameDecoder, encodeFrame, TransportProtocolError } from "../../dist/apps/desktop/src/main/backendRuntime/framing.js";
import { ASL_SERVICES } from "../../dist/apps/desktop/src/main/backendRuntime/protocol.js";

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

/**
 * Paginated durable source mock. Each replay request consumes one page
 * config: events are sent contiguously from after_sequence+1 to `end`, and
 * the completion frame reports the page's own high watermark.
 */
class PaginatedBackend {
  decoder = new FrameDecoder();
  replayRequests = [];
  pushedLive = [];

  constructor(process, pages) {
    this.process = process;
    this.pages = pages.map((page) => ({ ...page }));
    process.stdin.on("data", (chunk) => {
      for (const message of this.decoder.feed(chunk)) this.onMessage(message);
    });
  }

  hello() {
    this.send({
      kind: "backend.hello",
      protocol: "v3.local/1.0",
      backend_instance_id: "backend-paginated",
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
      this.send({ kind: "backend.ready", backend_instance_id: "backend-paginated", protocol: "v3.local/1.0", schema_version: "1.0.0" });
    } else if (message.kind === "events.replay") {
      this.replayRequests.push(message.after_sequence);
      const page = this.pages.shift();
      if (!page) throw new Error("mock received an unexpected replay request");
      for (let sequence = message.after_sequence + 1; sequence <= page.end; sequence += 1) {
        this.sendEvent(sequence);
      }
      const last = Math.max(message.after_sequence, page.end);
      this.send({
        kind: "events.replayComplete",
        last_sequence: last,
        next_after_sequence: last,
        high_watermark: page.watermark,
        has_more: page.hasMore ?? (last < page.watermark)
      });
    } else if (message.kind === "events.ack") {
      // durable cursor commits are verified separately; ack ordering tests
      // live in runtime-core-cursor.test.mjs.
    }
  }

  sendEvent(sequence) {
    this.send({
      kind: "event",
      event_id: `event-${sequence}`,
      project_id: PROJECT_ID,
      project_sequence: sequence,
      event_type: "TASK_UPDATED",
      occurred_at: "2026-08-09T00:00:00Z",
      body: { state: "RUNNING" }
    });
  }

  pushLive(sequence) {
    this.pushedLive.push(sequence);
    this.sendEvent(sequence);
  }

  send(value) { this.process.stdout.write(encodeFrame(value)); }
}

class MockFactory {
  constructor(pages) { this.pages = pages; }
  spawn() {
    const process = new MockProcess();
    const backend = new PaginatedBackend(process, this.pages);
    setImmediate(() => backend.hello());
    this.spawnResult = { process, backend };
    return process;
  }
}

function create(factory) {
  const supervisor = new BackendSupervisor({
    pythonExecutable: "python.exe",
    backendWorkingDirectory: "D:\\V3\\backend",
    desktopVersion: "0.1.0",
    projectContext: { projectId: PROJECT_ID, projectContextRevisionId: REVISION_ID, lastDurableProjectEventSequence: 0 },
    handshakeTimeoutMs: 500,
    requestTimeoutMs: 500,
    autoReconnect: false
  }, factory, () => Buffer.alloc(32, 7));
  return supervisor;
}

async function startAndCollect(pages, { timeoutMs = 5000 } = {}) {
  const factory = new MockFactory(pages);
  const supervisor = create(factory);
  const sequences = [];
  const states = [];
  supervisor.on("event", (event) => sequences.push(event.project_sequence));
  supervisor.on("state", (state) => states.push(state));
  await supervisor.start();
  await waitFor(() => supervisor.state === "READY", timeoutMs);
  return { supervisor, backend: factory.spawnResult?.backend, sequences, states };
}

test("999 historical events replay in one page and become READY", async () => {
  const { supervisor, backend, sequences, states } = await startAndCollect([{ end: 999, watermark: 999 }]);
  assert.deepEqual(backend.replayRequests, [0]);
  assert.deepEqual(sequences, Array.from({ length: 999 }, (_value, index) => index + 1));
  assert.equal(states.includes("REPLAYING"), true);
  assert.equal(states[states.length - 1], "READY");
  supervisor.stopNow();
});

test("1000 historical events fill one page exactly and become READY", async () => {
  const { supervisor, backend, sequences } = await startAndCollect([{ end: 1000, watermark: 1000 }]);
  assert.deepEqual(backend.replayRequests, [0]);
  assert.equal(sequences.length, 1000);
  assert.deepEqual(sequences.slice(0, 3), [1, 2, 3]);
  assert.deepEqual(sequences.slice(-3), [998, 999, 1000]);
  supervisor.stopNow();
});

test("1001 historical events span two pages without skip or duplicate", async () => {
  const { supervisor, backend, sequences } = await startAndCollect([
    { end: 1000, watermark: 1001 },
    { end: 1001, watermark: 1001 }
  ]);
  assert.deepEqual(backend.replayRequests, [0, 1000]);
  assert.deepEqual(sequences, Array.from({ length: 1001 }, (_value, index) => index + 1));
  supervisor.stopNow();
});

test("2501 historical events span three pages and READY only after the frozen watermark", async () => {
  const { supervisor, backend, sequences, states } = await startAndCollect([
    { end: 1000, watermark: 2501 },
    { end: 2000, watermark: 2501 },
    { end: 2501, watermark: 2501 }
  ], { timeoutMs: 10000 });
  assert.deepEqual(backend.replayRequests, [0, 1000, 2000]);
  assert.equal(sequences.length, 2501);
  assert.equal(new Set(sequences).size, 2501);
  assert.deepEqual(sequences.slice(-1), [2501]);
  const replayingRuns = states.filter((state) => state === "REPLAYING").length;
  assert.equal(replayingRuns, 1, "state stays REPLAYING across pages until READY");
  assert.equal(states[states.length - 1], "READY");
  supervisor.stopNow();
});

test("live events during replay do not extend the frozen high watermark", async () => {
  // Page 1 freezes H=1001. A live event raises the source watermark to 1002
  // before page 2. Page 2 reports has_more=true but the supervisor must stop
  // chasing at the frozen H and deliver the live tail through normal delivery.
  const factory = new MockFactory([
    { end: 1000, watermark: 1001 },
    { end: 1001, watermark: 1002, hasMore: true }
  ]);
  const supervisor = create(factory);
  const sequences = [];
  supervisor.on("event", (event) => sequences.push(event.project_sequence));
  await supervisor.start();
  await waitFor(() => supervisor.state === "READY", 5000);
  const backend = factory.spawnResult.backend;
  assert.deepEqual(backend.replayRequests, [0, 1000], "no replay page beyond the frozen watermark");
  backend.pushLive(1002);
  await waitFor(() => sequences.length === 1002, 3000);
  assert.deepEqual(sequences.slice(-2), [1001, 1002]);
  assert.equal(supervisor.state, "READY");
  supervisor.stopNow();
});

test("has_more=false before the frozen watermark fails closed", async () => {
  const factory = new MockFactory([
    { end: 500, watermark: 999, hasMore: false }
  ]);
  const supervisor = create(factory);
  supervisor.on("state", () => {});
  await assert.rejects(
    supervisor.start(),
    (error) => error instanceof TransportProtocolError && /no more pages before the frozen high watermark/.test(error.message)
  );
  assert.equal(supervisor.state, "DISCONNECTED");
  assert.equal(factory.spawnResult.backend.replayRequests.length, 1, "no further page requested after protocol failure");
  assert.equal(factory.spawnResult.process.terminated, true);
});
