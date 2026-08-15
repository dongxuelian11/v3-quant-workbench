import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import test from "node:test";

import { BackendSupervisor } from "../../dist/apps/desktop/src/main/backendRuntime/supervisor.js";
import { FrameDecoder, encodeFrame } from "../../dist/apps/desktop/src/main/backendRuntime/framing.js";
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

class CursorBackend {
  decoder = new FrameDecoder();
  ackSequences = [];
  acceptSequences = [];
  replayRequests = [];
  replayPages = [];   // consumed per replay request when autoReplay is on
  autoReplay = false;
  order = null;

  constructor(process, { autoReplay = false, replayPages = [], order = null } = {}) {
    this.process = process;
    this.autoReplay = autoReplay;
    this.replayPages = replayPages;
    this.order = order;
    process.stdin.on("data", (chunk) => {
      for (const message of this.decoder.feed(chunk)) this.onMessage(message);
    });
  }

  hello() {
    this.send({
      kind: "backend.hello",
      protocol: "v3.local/1.0",
      backend_instance_id: "backend-cursor",
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
      this.acceptSequences.push(message.last_project_event_sequence);
      this.send({ kind: "backend.ready", backend_instance_id: "backend-cursor", protocol: "v3.local/1.0", schema_version: "1.0.0" });
    } else if (message.kind === "events.replay") {
      this.replayRequests.push(message.after_sequence);
      if (!this.autoReplay) return;
      const page = this.replayPages.shift();
      if (!page) throw new Error("mock received an unexpected replay request");
      for (let sequence = message.after_sequence + 1; sequence <= page.end; sequence += 1) this.pushEvent(sequence);
      const last = Math.max(message.after_sequence, page.end);
      this.send({
        kind: "events.replayComplete",
        last_sequence: last,
        next_after_sequence: last,
        high_watermark: page.watermark,
        has_more: page.hasMore ?? (last < page.watermark)
      });
    } else if (message.kind === "events.ack") {
      this.ackSequences.push(message.project_sequence);
      this.order?.push(`ack:${message.project_sequence}`);
    }
  }

  /** Respond to the last pending replay request with a manual page. */
  sendReplayPage(end, watermark, hasMore) {
    const after = this.replayRequests[this.replayRequests.length - 1] ?? 0;
    for (let sequence = after + 1; sequence <= end; sequence += 1) this.pushEvent(sequence);
    const last = Math.max(after, end);
    this.send({
      kind: "events.replayComplete",
      last_sequence: last,
      next_after_sequence: last,
      high_watermark: watermark,
      has_more: hasMore ?? (last < watermark)
    });
  }

  pushEvent(sequence, eventId = `event-${sequence}`) {
    this.send({
      kind: "event",
      event_id: eventId,
      project_id: PROJECT_ID,
      project_sequence: sequence,
      event_type: "TASK_UPDATED",
      occurred_at: "2026-08-09T00:00:00Z",
      body: { state: "RUNNING" }
    });
  }

  send(value) { this.process.stdout.write(encodeFrame(value)); }
}

class CursorMockFactory {
  constructor({ autoReplay = false, replayPages = [], order = null, spawnPages = null } = {}) {
    this.autoReplay = autoReplay;
    this.replayPages = replayPages;
    this.order = order;
    this.spawnPages = spawnPages;   // per-spawn replay page batches when set
    this.spawnResults = [];
  }
  spawn() {
    const process = new MockProcess();
    const pages = this.spawnPages && this.spawnPages.length > 0 ? this.spawnPages.shift() : this.replayPages;
    const backend = new CursorBackend(process, { autoReplay: this.autoReplay, replayPages: pages, order: this.order });
    setImmediate(() => backend.hello());
    this.spawnResult = { process, backend };
    this.spawnResults.push(this.spawnResult);
    return process;
  }
}

function create(factory, overrides = {}, cursorPort) {
  return new BackendSupervisor({
    pythonExecutable: "python.exe",
    backendWorkingDirectory: "D:\\V3\\backend",
    desktopVersion: "0.1.0",
    projectContext: { projectId: PROJECT_ID, projectContextRevisionId: REVISION_ID, lastDurableProjectEventSequence: 0 },
    handshakeTimeoutMs: 500,
    requestTimeoutMs: 500,
    autoReconnect: false,
    ...(cursorPort ? { cursorPort } : {}),
    ...overrides
  }, factory, () => Buffer.alloc(32, 7));
}

test("event delivery is emit -> durable commit -> ack", async () => {
  const order = [];
  const factory = new CursorMockFactory({
    autoReplay: true,
    replayPages: [{ end: 3, watermark: 3 }],
    order
  });
  const port = { commit: async (_projectId, sequence) => { order.push(`commit:${sequence}`); } };
  const supervisor = create(factory, {}, port);
  const events = [];
  supervisor.on("event", (event) => { events.push(event.project_sequence); order.push(`emit:${event.project_sequence}`); });
  await supervisor.start();
  await waitFor(() => supervisor.state === "READY");
  assert.deepEqual(order, [
    "emit:1", "commit:1", "ack:1",
    "emit:2", "commit:2", "ack:2",
    "emit:3", "commit:3", "ack:3"
  ]);
  assert.deepEqual(events, [1, 2, 3]);
  supervisor.stopNow();
});

test("cursor commits persist and a restart replays from the durable cursor", async () => {
  const commits = [];
  const factory = new CursorMockFactory({
    autoReplay: true,
    replayPages: [{ end: 2, watermark: 2 }]
  });
  const port = { commit: async (projectId, sequence) => { commits.push([projectId, sequence]); } };
  const first = create(factory, {}, port);
  await first.start();
  await waitFor(() => first.state === "READY");
  assert.deepEqual(commits, [[PROJECT_ID, 1], [PROJECT_ID, 2]]);
  first.stopNow();

  const restartedFactory = new CursorMockFactory({ autoReplay: true, replayPages: [{ end: 2, watermark: 2 }] });
  const restarted = new BackendSupervisor({
    pythonExecutable: "python.exe",
    backendWorkingDirectory: "D:\\V3\\backend",
    desktopVersion: "0.1.0",
    projectContext: { projectId: PROJECT_ID, projectContextRevisionId: REVISION_ID, lastDurableProjectEventSequence: 2 },
    handshakeTimeoutMs: 500,
    requestTimeoutMs: 500,
    autoReconnect: false
  }, restartedFactory, () => Buffer.alloc(32, 7));
  const restartedEvents = [];
  restarted.on("event", (event) => restartedEvents.push(event.project_sequence));
  await restarted.start();
  await waitFor(() => restarted.state === "READY");
  assert.deepEqual(restartedFactory.spawnResult.backend.acceptSequences, [2]);
  assert.deepEqual(restartedFactory.spawnResult.backend.replayRequests, [2]);
  assert.deepEqual(restartedEvents, []);
  restarted.stopNow();
});

test("cursor persistence failure emits first, sends no ack, and fails closed honestly", async () => {
  const commits = [];
  const diagnostics = [];
  const emitted = [];
  const factory = new CursorMockFactory({
    autoReplay: true,
    replayPages: [{ end: 3, watermark: 3 }]
  });
  const port = {
    commit: async (_projectId, sequence) => {
      commits.push(sequence);
      if (sequence === 2) throw new Error("disk write failed");
    }
  };
  const supervisor = create(factory, {}, port);
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  supervisor.on("event", (event) => emitted.push(event.project_sequence));
  await assert.rejects(supervisor.start(), (error) => error instanceof Error);
  await waitFor(() => supervisor.state === "DISCONNECTED");
  assert.deepEqual(emitted, [1, 2], "event 2 is emitted before its commit attempt (at-least-once)");
  assert.deepEqual(commits, [1, 2]);
  assert.deepEqual(factory.spawnResult.backend.ackSequences, [1], "event 2 must not be acked");
  assert.equal(diagnostics.some((item) => item.code === "CURSOR_COMMIT_FAILED"), true);
  assert.equal(factory.spawnResult.process.terminated, true);
});

test("normal sequence gap recovers through replay without loss or reorder", async () => {
  const factory = new CursorMockFactory({ autoReplay: false });
  const commits = [];
  const supervisor = create(factory, {}, { commit: async (_projectId, sequence) => { commits.push(sequence); } });
  const events = [];
  supervisor.on("event", (event) => events.push(event.project_sequence));
  const starting = supervisor.start();
  starting.catch(() => {});
  await waitFor(() => supervisor.state === "REPLAYING");
  const backend = factory.spawnResult.backend;
  // Live event 5 arrives while the cursor is still 0: it is buffered and the
  // supervisor fills the gap through replay pages. Once pages 1..4 are
  // delivered, the buffered live event 5 completes the contiguous range up
  // to the frozen high watermark, so the supervisor becomes READY without a
  // third page.
  backend.pushEvent(5, "event-5-live");
  await waitFor(() => backend.replayRequests.length === 1);
  backend.sendReplayPage(2, 5, true);
  await waitFor(() => backend.replayRequests.length === 2);
  backend.sendReplayPage(4, 5, true);
  await waitFor(() => supervisor.state === "READY");
  await starting;
  assert.deepEqual(backend.replayRequests, [0, 2]);
  assert.deepEqual(events, [1, 2, 3, 4, 5]);
  assert.deepEqual(commits, [1, 2, 3, 4, 5]);
  assert.deepEqual(backend.ackSequences, [1, 2, 3, 4, 5]);
  supervisor.stopNow();
});

test("commit failure + reconnect replays the event without stale cache suppression", async () => {
  const commits = [];
  const diagnostics = [];
  let failedOnce = false;
  const factory = new CursorMockFactory({
    autoReplay: true,
    spawnPages: [
      [{ end: 3, watermark: 3 }],
      [{ end: 3, watermark: 3 }]
    ]
  });
  const port = {
    commit: async (_projectId, sequence) => {
      commits.push(sequence);
      if (sequence === 2 && !failedOnce) { failedOnce = true; throw new Error("disk write failed"); }
    }
  };
  const supervisor = new BackendSupervisor({
    pythonExecutable: "python.exe",
    backendWorkingDirectory: "D:\\V3\\backend",
    desktopVersion: "0.1.0",
    projectContext: { projectId: PROJECT_ID, projectContextRevisionId: REVISION_ID, lastDurableProjectEventSequence: 0 },
    handshakeTimeoutMs: 500,
    requestTimeoutMs: 500,
    autoReconnect: true,
    reconnectBaseDelayMs: 1,
    reconnectMaxDelayMs: 2,
    cursorPort: port
  }, factory, () => Buffer.alloc(32, 7));
  const emitted = [];
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  supervisor.on("event", (event) => emitted.push(event.project_sequence));
  supervisor.on("error", () => {});
  const starting = supervisor.start();
  starting.catch(() => {});
  // First session: 1 committed+acked, 2 emitted but commit failed -> disconnect.
  await waitFor(() => supervisor.state === "DISCONNECTED");
  assert.deepEqual(emitted, [1, 2]);
  assert.deepEqual(factory.spawnResults[0].backend.ackSequences, [1]);
  // Reconnect: the backend replays from the durable cursor (1), so event 2
  // must be re-delivered (at-least-once), not swallowed by any stale cache.
  await waitFor(() => supervisor.state === "READY", 5000);
  assert.deepEqual(emitted, [1, 2, 2, 3], "event 2 replayed after reconnect and event 3 followed");
  assert.deepEqual(commits, [1, 2, 2, 3]);
  assert.deepEqual(factory.spawnResults[1].backend.ackSequences, [2, 3]);
  assert.equal(diagnostics.some((item) => item.code === "CURSOR_COMMIT_FAILED"), true);
  supervisor.stopNow();
});

test("application delivery failure before commit: no commit, no ack, replay possible", async () => {
  const commits = [];
  const diagnostics = [];
  const factory = new CursorMockFactory({ autoReplay: true, replayPages: [{ end: 1, watermark: 1 }] });
  const supervisor = create(factory, {}, { commit: async (_projectId, sequence) => { commits.push(sequence); } });
  supervisor.on("event", () => { throw new Error("application relay exploded"); });
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  await assert.rejects(supervisor.start(), (error) => error instanceof Error);
  await waitFor(() => supervisor.state === "DISCONNECTED");
  assert.deepEqual(commits, [], "no durable cursor commit after an application delivery failure");
  assert.deepEqual(factory.spawnResult.backend.ackSequences, [], "no ack after an application delivery failure");
  assert.equal(diagnostics.some((item) => item.code === "EVENT_APPLICATION_DELIVERY_FAILED"), true);
  assert.equal(factory.spawnResult.process.terminated, true);

  // A fresh runtime replays the same event: the failure left no durable
  // cursor and no stale cache entry, so the event is delivered again.
  const retryFactory = new CursorMockFactory({ autoReplay: true, replayPages: [{ end: 1, watermark: 1 }] });
  const retry = create(retryFactory, {}, { commit: async (_projectId, sequence) => { commits.push(sequence); } });
  const retried = [];
  retry.on("event", (event) => retried.push(event.project_sequence));
  await retry.start();
  await waitFor(() => retry.state === "READY");
  assert.deepEqual(retried, [1]);
  assert.deepEqual(commits, [1]);
  retry.stopNow();
});

test("duplicate event id redelivery is dropped", async () => {
  const factory = new CursorMockFactory({ autoReplay: true, replayPages: [{ end: 1, watermark: 1 }] });
  const supervisor = create(factory);
  const events = [];
  supervisor.on("event", (event) => events.push(event.project_sequence));
  await supervisor.start();
  await waitFor(() => supervisor.state === "READY");
  factory.spawnResult.backend.pushEvent(1, "event-1");
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.equal(events.length, 1);
  assert.deepEqual(factory.spawnResult.backend.ackSequences, [1]);
  supervisor.stopNow();
});

test("buffer overflow fails closed with a hard diagnostic", async () => {
  const diagnostics = [];
  const factory = new CursorMockFactory({ autoReplay: false });
  const supervisor = create(factory, { maxBufferedEvents: 3, maxEventSequenceGap: 1000 });
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  supervisor.on("state", () => {});
  const starting = supervisor.start();
  starting.catch(() => {});
  await waitFor(() => supervisor.state === "REPLAYING");
  const backend = factory.spawnResult.backend;
  backend.pushEvent(4);
  backend.pushEvent(5);
  backend.pushEvent(6);
  backend.pushEvent(7);
  await waitFor(() => diagnostics.some((item) => item.code === "EVENT_BUFFER_OVERFLOW"), 2000);
  await waitFor(() => supervisor.state === "DISCONNECTED");
  await assert.rejects(starting, (error) => error instanceof Error);
  assert.deepEqual(backend.ackSequences, [], "no event may be acked after overflow");
});

test("absurd sequence gap fails closed", async () => {
  const diagnostics = [];
  const factory = new CursorMockFactory({ autoReplay: false });
  const supervisor = create(factory, { maxEventSequenceGap: 5 });
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  supervisor.on("state", () => {});
  const starting = supervisor.start();
  starting.catch(() => {});
  await waitFor(() => supervisor.state === "REPLAYING");
  factory.spawnResult.backend.pushEvent(100);
  await waitFor(() => diagnostics.some((item) => item.code === "EVENT_SEQUENCE_GAP_ABSURD"), 2000);
  await waitFor(() => supervisor.state === "DISCONNECTED");
  await assert.rejects(starting, (error) => error instanceof Error);
});
