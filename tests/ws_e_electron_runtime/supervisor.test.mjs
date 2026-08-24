import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import test from "node:test";

import { BackendRuntimeLifecycle } from "../../dist/apps/desktop/src/main/backendRuntime/lifecycle.js";
import { FrameDecoder, encodeFrame } from "../../dist/apps/desktop/src/main/backendRuntime/framing.js";
import { ASL_SERVICES } from "../../dist/apps/desktop/src/main/backendRuntime/protocol.js";
import { BackendSupervisor } from "../../dist/apps/desktop/src/main/backendRuntime/supervisor.js";

const PROJECT_ID = `prj_${"0".repeat(26)}`;
const REVISION_ID = `pcr_${"0".repeat(26)}`;

function waitFor(predicate, timeoutMs = 1000) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const poll = () => {
      if (predicate()) resolve();
      else if (Date.now() - started > timeoutMs) reject(new Error("condition timed out"));
      else setTimeout(poll, 2);
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
  exited = false;
  constructor() {
    super();
    this.exitPromise = new Promise((resolve) => {
      this.once("exit", () => { this.exited = true; resolve(); });
    });
  }

  onExit(listener) { this.once("exit", listener); }
  terminate() {
    if (this.terminated) return;
    this.terminated = true;
    queueMicrotask(() => this.emit("exit", 0, null));
  }
  kill() {
    if (this.exited) return;
    this.terminated = true;
    queueMicrotask(() => this.emit("exit", null, "SIGKILL"));
  }
  isAlive() { return !this.exited; }
  async waitForExit(deadlineAt) {
    if (!this.isAlive()) return true;
    const remaining = Math.max(0, deadlineAt - Date.now());
    return Promise.race([
      this.exitPromise.then(() => true),
      new Promise((resolve) => setTimeout(() => resolve(false), remaining))
    ]);
  }
  crash() {
    if (this.terminated) return;
    this.terminated = true;
    this.emit("exit", 9, null);
  }
}

class BackpressureStdin extends PassThrough {
  blocked = false;
  writeCalls = 0;
  blockedWriteCalls = 0;

  write(...args) {
    this.writeCalls += 1;
    const accepted = super.write(...args);
    if (!this.blocked) return accepted;
    this.blockedWriteCalls += 1;
    return false;
  }
}

class BackpressureProcess extends MockProcess {
  constructor() {
    super();
    this.stdin = new BackpressureStdin();
  }
}

class MockBackend {
  decoder = new FrameDecoder();
  received = [];
  acceptSequences = [];
  requestMode = "ok";
  queuedRequests = [];
  healthMode = "ok";
  queuedHealthRequests = [];
  productEntryMode = "ok";
  queuedProductEntryRequests = [];
  localDataMode = "ok";
  queuedLocalDataRequests = [];

  constructor(process, index, protocol = "v3.local/1.0") {
    this.process = process;
    this.index = index;
    this.protocol = protocol;
    process.stdin.on("data", (chunk) => {
      for (const message of this.decoder.feed(chunk)) this.onMessage(message);
    });
  }

  hello() {
    this.send({
      kind: "backend.hello",
      protocol: this.protocol,
      backend_instance_id: `backend-${this.index}`,
      pid: 4321 + this.index,
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
    this.received.push(message);
    if (message.kind === "supervisor.accept") {
      this.acceptSequences.push(message.last_project_event_sequence);
      this.send({ kind: "backend.ready", backend_instance_id: `backend-${this.index}`, protocol: "v3.local/1.0", schema_version: "1.0.0" });
    } else if (message.kind === "events.replay") {
      const sequence = message.after_sequence + 1;
      this.send({
        kind: "event",
        event_id: `event-${sequence}`,
        project_id: PROJECT_ID,
        project_sequence: sequence,
        event_type: "TASK_UPDATED",
        occurred_at: "2026-08-09T00:00:00Z",
        body: { state: sequence === 1 ? "RUNNING" : "SUCCEEDED" }
      });
      this.send({ kind: "events.replayComplete", last_sequence: sequence, next_after_sequence: sequence, high_watermark: sequence, has_more: false });
    } else if (message.kind === "request") {
      if (this.requestMode === "silent") return;
      if (this.requestMode === "error") {
        this.send({ kind: "response", request_id: message.request_id, status: "ERROR", error: {
          schema_version: "1.0.0",
          code: "CAPABILITY_UNAVAILABLE",
          message: "mock unavailable",
          retryable: false,
          details: { reason_code: "MOCK_UNAVAILABLE" },
          correlation_id: message.request_id,
          operation_id: message.operation_id
        }});
        return;
      }
      if (this.requestMode === "queue") {
        this.queuedRequests.push(message);
        return;
      }
      this.respondOk(message);
    } else if (message.kind === "runtime.health") {
      if (this.healthMode === "queue") {
        this.queuedHealthRequests.push(message);
        return;
      }
      this.respondHealth(message);
    } else if (message.kind === "productEntry.listProjects") {
      if (this.productEntryMode === "queue") {
        this.queuedProductEntryRequests.push(message);
        return;
      }
      this.respondProductEntry(message);
    } else if (message.kind === "localData.beginTransfer") {
      if (this.localDataMode === "queue") {
        this.queuedLocalDataRequests.push(message);
        return;
      }
      this.respondLocalData(message);
    } else if (message.kind === "runtime.prepareShutdown") {
      this.send({
        kind: "runtime.shutdownReady",
        deadline_at: message.deadline_at,
        control_request_id: message.control_request_id,
        runtime_generation: message.runtime_generation
      });
    } else if (message.kind === "runtime.commitShutdown") {
      this.send({
        kind: "runtime.shutdownCommitted",
        control_request_id: message.control_request_id,
        runtime_generation: message.runtime_generation
      });
      queueMicrotask(() => this.process.emit("exit", 0, null));
    }
  }

  respondOk(message) {
      const body = {
        operation_id: message.operation_id,
        received_body: message.body
      };
      if (message.operation_id === "ArtifactService.v1.openArtifactStream") {
        body.access = { mode: "STREAM_TICKET", ticket_id: "ticket-1", expires_at: "2026-08-09T00:00:00Z" };
      }
      this.send({ kind: "response", request_id: message.request_id, status: "OK", body });
  }

  respondHealth(request = this.queuedHealthRequests.shift()) {
    const response = {
      kind: "runtime.health",
      backend_instance_id: `backend-${this.index}`,
      state: "READY",
      uptime_seconds: 1
    };
    if (request?.control_request_id !== undefined) response.control_request_id = request.control_request_id;
    if (request?.runtime_generation !== undefined) response.runtime_generation = request.runtime_generation;
    this.send(response);
  }

  respondProductEntry(request = this.queuedProductEntryRequests.shift()) {
    const response = {
      kind: "productEntry.projectsListed",
      projects: [],
      has_more: false
    };
    if (request?.control_request_id !== undefined) response.control_request_id = request.control_request_id;
    if (request?.runtime_generation !== undefined) response.runtime_generation = request.runtime_generation;
    this.send(response);
  }

  respondLocalData(request = this.queuedLocalDataRequests.shift()) {
    this.send({
      kind: "localData.transferReady",
      transfer_id: `ldt_${"0".repeat(26)}`,
      next_offset: 0,
      max_chunk_bytes: 262144,
      control_request_id: request.control_request_id,
      runtime_generation: request.runtime_generation
    });
  }

  flushRequestsInReverse() {
    for (const message of this.queuedRequests.splice(0).reverse()) this.respondOk(message);
  }

  send(value) { this.process.stdout.write(encodeFrame(value)); }
}

class MockFactory {
  specs = [];
  tokens = [];
  processes = [];
  backends = [];
  protocol = "v3.local/1.0";

  constructor(processType = MockProcess) {
    this.processType = processType;
  }

  spawn(spec, token) {
    this.specs.push(spec);
    this.tokens.push(Buffer.from(token));
    const process = new this.processType();
    const backend = new MockBackend(process, this.processes.length + 1, this.protocol);
    this.processes.push(process);
    this.backends.push(backend);
    setImmediate(() => backend.hello());
    return process;
  }
}

function create(factory, overrides = {}) {
  return new BackendSupervisor({
    pythonExecutable: "python.exe",
    backendWorkingDirectory: "D:\\V3\\backend",
    desktopVersion: "0.1.0",
    projectContext: {
      projectId: PROJECT_ID,
      projectContextRevisionId: REVISION_ID,
      lastDurableProjectEventSequence: 0
    },
    handshakeTimeoutMs: 500,
    requestTimeoutMs: 500,
    reconnectBaseDelayMs: 1,
    reconnectMaxDelayMs: 2,
    ...overrides
  }, factory, () => Buffer.alloc(32, 7));
}

test("supervisor owns fixed spawn, handshake, capabilities, correlation, cancel, health and stream tickets", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory, { autoReconnect: false });
  const events = [];
  const diagnostics = [];
  supervisor.on("event", (event) => events.push(event));
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  await supervisor.start();
  assert.equal(supervisor.state, "READY");
  assert.equal(supervisor.capabilities[0].code, "TaskService");
  assert.deepEqual(factory.specs[0].args, ["-m", "v3_backend.runtime.bootstrap", "--transport=stdio-framed-v1"]);
  assert.equal(factory.tokens[0].length, 32);
  assert.equal(factory.specs[0].args.some((item) => item.includes(factory.tokens[0].toString("hex"))), false);
  assert.equal("PYTHONPATH" in factory.specs[0].env, false);
  assert.equal(factory.specs[0].env.APPDATA, process.env.APPDATA);
  for (const forbidden of ["V3_AGENT_EVIDENCE_MODE", "V3_BACKEND_PYTHON", "SUPERVISOR_TOKEN", "DATABASE_URL"]) assert.equal(forbidden in factory.specs[0].env, false);
  assert.equal(events[0].project_sequence, 1);
  factory.processes[0].stderr.write('{"level":"WARN","code":"MOCK_NOTICE","message":"redacted diagnostic"}\n');
  await waitFor(() => diagnostics.length === 1);
  assert.deepEqual(diagnostics[0], { level: "WARN", code: "MOCK_NOTICE", message: "redacted diagnostic" });

  const cancelled = await supervisor.cancelTask({ taskId: `tsk_${"0".repeat(26)}`, expectedStateVersion: 3, reason: "user" });
  assert.equal(cancelled.operation_id, "TaskService.v1.cancelTask");
  assert.equal(cancelled.received_body.expected_state_version, 3);
  assert.match(cancelled.received_body.request_id, /^[0-9a-f-]{36}$/);

  const stream = await supervisor.openArtifactStream({ artifactId: `art_sha256_${"a".repeat(64)}` });
  assert.equal(stream.access.ticket_id, "ticket-1");
  const health = await supervisor.getHealth();
  assert.equal(health.state, "READY");
  await supervisor.shutdown(500);
  assert.equal(supervisor.state, "STOPPED");
  assert.equal(factory.specs.length, 1, "no legacy fallback process may be spawned");
});

test("timed-out health releases its slot and a late correlated reply cannot satisfy the next request", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory, { autoReconnect: false });
  const diagnostics = [];
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  await supervisor.start();
  const backend = factory.backends[0];
  backend.healthMode = "queue";

  const timedOutHealth = supervisor.getHealth(10);
  await waitFor(() => backend.queuedHealthRequests.length === 1);
  await assert.rejects(timedOutHealth, (error) => error.code === "BACKEND_TIMEOUT");
  const firstRequest = backend.queuedHealthRequests[0];
  assert.match(firstRequest.control_request_id, /^[0-9a-f-]{36}$/);
  assert.equal(Number.isSafeInteger(firstRequest.runtime_generation), true);

  const recoveredHealthPromise = supervisor.getHealth(200);
  let recoveredSettled = false;
  void recoveredHealthPromise.finally(() => { recoveredSettled = true; }).catch(() => undefined);
  await waitFor(() => backend.queuedHealthRequests.length === 2);
  const secondRequest = backend.queuedHealthRequests[1];
  assert.notEqual(secondRequest.control_request_id, firstRequest.control_request_id);
  assert.equal(secondRequest.runtime_generation, firstRequest.runtime_generation);

  backend.respondHealth(firstRequest);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(recoveredSettled, false, "the late first reply must not settle the second health request");
  await waitFor(() => diagnostics.some((item) => item.code === "LATE_CONTROL_RESPONSE_DISCARDED"));

  backend.respondHealth(secondRequest);
  const recoveredHealth = await recoveredHealthPromise;
  assert.equal(recoveredHealth.state, "READY");
  assert.equal(supervisor.state, "READY");
  assert.equal(factory.processes[0].terminated, false);
  supervisor.stopNow();
});

test("concurrent health calls in one runtime generation coalesce onto one control frame", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory, { autoReconnect: false });
  await supervisor.start();
  const backend = factory.backends[0];
  backend.healthMode = "queue";

  const first = supervisor.getHealth(200);
  const second = supervisor.getHealth(200);
  try {
    await waitFor(() => backend.queuedHealthRequests.length >= 1);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(backend.queuedHealthRequests.length, 1);

    backend.respondHealth();
    const [firstHealth, secondHealth] = await Promise.all([first, second]);
    assert.deepEqual(secondHealth, firstHealth);
    assert.equal(supervisor.state, "READY");
  } finally {
    supervisor.stopNow();
    await Promise.allSettled([first, second]);
  }
});

test("health control tombstones stay bounded and a known late reply reopens one slot", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory, { autoReconnect: false });
  const diagnostics = [];
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  await supervisor.start();
  const backend = factory.backends[0];
  backend.healthMode = "queue";

  try {
    for (let index = 0; index < 256; index += 1) {
      await assert.rejects(supervisor.getHealth(0), (error) => error.code === "BACKEND_TIMEOUT");
    }
    assert.equal(backend.queuedHealthRequests.length, 256);
    await assert.rejects(
      supervisor.getHealth(200),
      (error) => error.code === "CONTROL_CORRELATION_CAPACITY"
        && error.details.max_tombstones === 256
        && error.details.timed_out_correlations === 256
    );
    assert.equal(backend.queuedHealthRequests.length, 256, "capacity rejection must not emit a frame");

    backend.respondHealth(backend.queuedHealthRequests[0]);
    await waitFor(() => diagnostics.some((item) => item.code === "LATE_CONTROL_RESPONSE_DISCARDED"));

    const recovered = supervisor.getHealth(200);
    await waitFor(() => backend.queuedHealthRequests.length === 257);
    backend.respondHealth(backend.queuedHealthRequests.at(-1));
    assert.equal((await recovered).state, "READY");
  } finally {
    supervisor.stopNow();
  }
});

test("timed-out Product Entry control releases its slot and discards its correlated late reply", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory, { autoReconnect: false });
  const diagnostics = [];
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  await supervisor.start();
  const backend = factory.backends[0];
  backend.productEntryMode = "queue";
  const frame = {
    kind: "productEntry.listProjects",
    protocol_version: "v3.product-entry/1.0.0",
    limit: 50,
    after_project_id: null
  };

  const timedOut = supervisor.productEntryControl(frame, 10);
  await waitFor(() => backend.queuedProductEntryRequests.length === 1);
  await assert.rejects(timedOut, (error) => error.code === "BACKEND_TIMEOUT");
  const firstRequest = backend.queuedProductEntryRequests[0];
  assert.match(firstRequest.control_request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);

  const recovered = supervisor.productEntryControl(frame, 200);
  let recoveredSettled = false;
  void recovered.finally(() => { recoveredSettled = true; }).catch(() => undefined);
  try {
    await waitFor(() => backend.queuedProductEntryRequests.length === 2);
    const secondRequest = backend.queuedProductEntryRequests[1];
    assert.notEqual(secondRequest.control_request_id, firstRequest.control_request_id);
    assert.equal(secondRequest.runtime_generation, firstRequest.runtime_generation);

    backend.respondProductEntry(firstRequest);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(recoveredSettled, false);
    await waitFor(() => diagnostics.some((item) => item.code === "LATE_CONTROL_RESPONSE_DISCARDED"));

    backend.respondProductEntry(secondRequest);
    assert.deepEqual((await recovered).projects, []);
    assert.equal(supervisor.state, "READY");
  } finally {
    supervisor.stopNow();
    await Promise.allSettled([recovered]);
  }
});

test("local-data control is correlated, generation-fenced and rejects every path field before transport", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory, { autoReconnect: false });
  await supervisor.start();
  const backend = factory.backends[0];
  const frame = {
    kind: "localData.beginTransfer",
    protocol_version: "v3.local-data-transfer/1.0.0",
    project_id: PROJECT_ID,
    project_context_revision_id: REVISION_ID,
    display_name: "bars.csv",
    media_type: "text/csv",
    expected_byte_size: 128
  };
  try {
    const before = backend.received.length;
    await assert.rejects(
      () => supervisor.localDataControl({ ...frame, path: "D:\\secret\\bars.csv" }),
      (error) => error.code === "INVALID_ARGUMENT"
    );
    assert.equal(backend.received.length, before, "path-bearing frame must not reach the backend");
    backend.localDataMode = "queue";
    const pending = supervisor.localDataControl(frame, 200);
    await waitFor(() => backend.queuedLocalDataRequests.length === 1);
    const request = backend.queuedLocalDataRequests[0];
    assert.match(request.control_request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.equal(Number.isSafeInteger(request.runtime_generation), true);
    assert.equal("path" in request, false);
    backend.respondLocalData(request);
    assert.deepEqual(await pending, {
      kind: "localData.transferReady",
      transfer_id: `ldt_${"0".repeat(26)}`,
      next_offset: 0,
      max_chunk_bytes: 262144
    });
  } finally {
    supervisor.stopNow();
  }
});

test("release acceptance provider is absent by default and forwarded only when explicitly configured", async () => {
  const normalFactory = new MockFactory();
  const normal = create(normalFactory, { autoReconnect: false });
  await normal.start();
  assert.deepEqual(normalFactory.specs[0].args, ["-m", "v3_backend.runtime.bootstrap", "--transport=stdio-framed-v1"]);
  await normal.shutdown(500);

  const acceptanceFactory = new MockFactory();
  const acceptance = create(acceptanceFactory, {
    autoReconnect: false,
    productReleaseAcceptanceProvider: "DETERMINISTIC_UNAVAILABLE"
  });
  await acceptance.start();
  assert.deepEqual(acceptanceFactory.specs[0].args, [
    "-m",
    "v3_backend.runtime.bootstrap",
    "--transport=stdio-framed-v1",
    "--product-release-acceptance-provider=DETERMINISTIC_UNAVAILABLE"
  ]);
  await acceptance.shutdown(500);
});

test("request correlation survives reversed responses and maps backend errors/timeouts", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory, { autoReconnect: false, requestTimeoutMs: 25 });
  await supervisor.start();
  const backend = factory.backends[0];
  backend.requestMode = "queue";
  const cancel = supervisor.cancelTask({ taskId: `tsk_${"0".repeat(26)}`, expectedStateVersion: 1, reason: "user" });
  const stream = supervisor.openArtifactStream({ artifactId: `art_sha256_${"b".repeat(64)}` });
  await waitFor(() => backend.queuedRequests.length === 2);
  backend.flushRequestsInReverse();
  assert.equal((await cancel).operation_id, "TaskService.v1.cancelTask");
  assert.equal((await stream).operation_id, "ArtifactService.v1.openArtifactStream");

  backend.requestMode = "error";
  await assert.rejects(
    supervisor.cancelTask({ taskId: `tsk_${"0".repeat(26)}`, expectedStateVersion: 2, reason: "user" }),
    (error) => error.code === "CAPABILITY_UNAVAILABLE" && error.details.reason_code === "MOCK_UNAVAILABLE"
  );
  backend.requestMode = "silent";
  await assert.rejects(
    supervisor.cancelTask({ taskId: `tsk_${"0".repeat(26)}`, expectedStateVersion: 3, reason: "user" }),
    (error) => error.code === "BACKEND_TIMEOUT"
  );
  supervisor.stopNow();
});

test("incompatible major fails closed without fallback or reconnect", async () => {
  const factory = new MockFactory();
  factory.protocol = "v3.local/2.0";
  const supervisor = create(factory);
  await assert.rejects(supervisor.start(), /incompatible local runtime protocol/);
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(factory.specs.length, 1);
  assert.equal(factory.processes[0].terminated, true);
  assert.equal(supervisor.state, "DISCONNECTED");
});

test("disconnect reconnects, changes instance and replays from highest contiguous sequence", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory);
  const sequences = [];
  supervisor.on("event", (event) => sequences.push(event.project_sequence));
  supervisor.on("error", () => {});
  await supervisor.start();
  factory.processes[0].crash();
  await waitFor(() => factory.backends.length === 2 && supervisor.state === "READY");
  assert.deepEqual(sequences, [1, 2]);
  assert.deepEqual(factory.backends.map((backend) => backend.acceptSequences[0]), [0, 1]);
  supervisor.stopNow();
});

test("crash loop guard stops bounded reconnects", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory, { crashLoopLimit: 1, crashLoopWindowMs: 1000 });
  supervisor.on("error", () => {});
  await supervisor.start();
  factory.processes[0].crash();
  await waitFor(() => factory.processes.length === 2 && supervisor.state === "READY");
  factory.processes[1].crash();
  await waitFor(() => supervisor.state === "CRASH_LOOP");
  assert.equal(factory.processes.length, 2);
});

test("timed-out known reply is discarded without terminating the live backend", async () => {
  const factory = new MockFactory();
  const diagnostics = [];
  const supervisor = create(factory, { autoReconnect: false, requestTimeoutMs: 20 });
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  await supervisor.start();
  const backend = factory.backends[0];
  backend.requestMode = "queue";
  const request = supervisor.cancelTask({ taskId: `tsk_${"0".repeat(26)}`, expectedStateVersion: 1, reason: "late-reply" });
  await waitFor(() => backend.queuedRequests.length === 1);
  await assert.rejects(request, (error) => error.code === "BACKEND_TIMEOUT");
  backend.respondOk(backend.queuedRequests.shift());
  await waitFor(() => diagnostics.some((item) => item.code === "LATE_RESPONSE_DISCARDED"));
  assert.equal(supervisor.state, "READY");
  backend.requestMode = "ok";
  assert.equal((await supervisor.cancelTask({ taskId: `tsk_${"1".repeat(26)}`, expectedStateVersion: 1, reason: "still-live" })).operation_id, "TaskService.v1.cancelTask");
  supervisor.stopNow();
});

test("very-late known reply remains safe after the configured TTL window", async () => {
  const factory = new MockFactory();
  const diagnostics = [];
  const supervisor = create(factory, {
    autoReconnect: false,
    requestTimeoutMs: 10,
    requestTombstoneTtlMs: 10
  });
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  await supervisor.start();
  const backend = factory.backends[0];
  backend.requestMode = "queue";
  const request = supervisor.cancelTask({ taskId: `tsk_${"8".repeat(26)}`, expectedStateVersion: 1, reason: "very-late-reply" });
  await waitFor(() => backend.queuedRequests.length === 1);
  await assert.rejects(request, (error) => error.code === "BACKEND_TIMEOUT");
  await new Promise((resolve) => setTimeout(resolve, 25));
  backend.respondOk(backend.queuedRequests.shift());
  await waitFor(() => diagnostics.some((item) => item.code === "LATE_RESPONSE_DISCARDED" && item.message.includes("configured TTL window")));
  assert.equal(supervisor.state, "READY");
  assert.equal(supervisor.tombstones.size, 0);
  backend.requestMode = "ok";
  assert.equal((await supervisor.cancelTask({ taskId: `tsk_${"9".repeat(26)}`, expectedStateVersion: 1, reason: "capacity-released" })).operation_id, "TaskService.v1.cancelTask");
  supervisor.stopNow();
});

test("tombstone capacity rejects new work without evicting live-generation correlations", async () => {
  const factory = new MockFactory();
  const diagnostics = [];
  const supervisor = create(factory, {
    autoReconnect: false,
    requestTimeoutMs: 10,
    requestTombstoneLimit: 2,
    requestTombstoneTtlMs: 10
  });
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  await supervisor.start();
  const backend = factory.backends[0];
  backend.requestMode = "queue";
  const first = supervisor.cancelTask({ taskId: `tsk_${"a".repeat(26)}`, expectedStateVersion: 1, reason: "capacity-first" });
  const second = supervisor.cancelTask({ taskId: `tsk_${"b".repeat(26)}`, expectedStateVersion: 1, reason: "capacity-second" });
  await waitFor(() => backend.queuedRequests.length === 2);
  await Promise.all([
    assert.rejects(first, (error) => error.code === "BACKEND_TIMEOUT"),
    assert.rejects(second, (error) => error.code === "BACKEND_TIMEOUT")
  ]);
  assert.equal(supervisor.tombstones.size, 2);
  await new Promise((resolve) => setTimeout(resolve, 25));
  await assert.rejects(
    supervisor.cancelTask({ taskId: `tsk_${"c".repeat(26)}`, expectedStateVersion: 1, reason: "capacity-rejected" }),
    (error) => error.code === "TRANSPORT_TOMBSTONE_CAPACITY"
  );
  assert.equal(supervisor.tombstones.size, 2);
  backend.respondOk(backend.queuedRequests.shift());
  await waitFor(() => diagnostics.filter((item) => item.code === "LATE_RESPONSE_DISCARDED").length === 1);
  assert.equal(supervisor.tombstones.size, 1);
  backend.respondOk(backend.queuedRequests.shift());
  await waitFor(() => diagnostics.filter((item) => item.code === "LATE_RESPONSE_DISCARDED").length === 2);
  assert.equal(supervisor.tombstones.size, 0);
  backend.requestMode = "ok";
  assert.equal((await supervisor.cancelTask({ taskId: `tsk_${"d".repeat(26)}`, expectedStateVersion: 1, reason: "capacity-released" })).operation_id, "TaskService.v1.cancelTask");
  supervisor.stopNow();
});

test("old session output cannot satisfy the new session after reconnect", async () => {
  const factory = new MockFactory();
  const states = [];
  const supervisor = create(factory, { requestTimeoutMs: 10, reconnectBaseDelayMs: 10, reconnectMaxDelayMs: 10 });
  supervisor.on("state", (state) => states.push(state));
  await supervisor.start();
  const oldBackend = factory.backends[0];
  oldBackend.requestMode = "queue";
  const request = supervisor.cancelTask({ taskId: `tsk_${"2".repeat(26)}`, expectedStateVersion: 1, reason: "old-session" });
  await waitFor(() => oldBackend.queuedRequests.length === 1);
  const oldMessage = oldBackend.queuedRequests[0];
  await assert.rejects(request, (error) => error.code === "BACKEND_TIMEOUT");
  assert.equal(supervisor.tombstones.size, 1);
  factory.processes[0].crash();
  await waitFor(() => factory.backends.length === 2 && supervisor.state === "READY");
  assert.equal(supervisor.tombstones.size, 0);
  oldBackend.respondOk(oldMessage);
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(supervisor.state, "READY");
  assert.ok(states.includes("RECONNECTING"));
  supervisor.stopNow();
});

test("unknown unsolicited response remains a protocol failure", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory, { autoReconnect: false });
  await supervisor.start();
  factory.backends[0].send({
    kind: "response",
    request_id: "00000000-0000-7000-8000-000000000099",
    status: "OK",
    body: {}
  });
  await waitFor(() => supervisor.state === "DISCONNECTED");
  assert.equal(factory.processes[0].terminated, true);
});

test("stdin false write is drained and queued frames stay bounded", async () => {
  const factory = new MockFactory(BackpressureProcess);
  const supervisor = create(factory, {
    autoReconnect: false,
    maxBufferedStdinWrites: 1,
    maxBufferedStdinBytes: 4096
  });
  await supervisor.start();
  const process = factory.processes[0];
  const stdin = process.stdin;
  stdin.blocked = true;
  const backend = factory.backends[0];
  backend.requestMode = "queue";
  const first = supervisor.cancelTask({ taskId: `tsk_${"3".repeat(26)}`, expectedStateVersion: 1, reason: "backpressure-1" });
  await waitFor(() => backend.queuedRequests.length === 1);
  const firstRejection = assert.rejects(first, (error) => error.code === "TRANSPORT_BACKPRESSURE");
  const second = supervisor.cancelTask({ taskId: `tsk_${"4".repeat(26)}`, expectedStateVersion: 1, reason: "backpressure-2" });
  const secondRejection = assert.rejects(second, (error) => error.code === "TRANSPORT_BACKPRESSURE");
  const third = supervisor.cancelTask({ taskId: `tsk_${"5".repeat(26)}`, expectedStateVersion: 1, reason: "backpressure-3" });
  const thirdRejection = assert.rejects(third, (error) => error.code === "TRANSPORT_BACKPRESSURE");
  await Promise.all([firstRejection, secondRejection, thirdRejection]);
  assert.equal(stdin.blockedWriteCalls, 1, "queued frames must wait for drain rather than write repeatedly");
  assert.equal(supervisor.state, "DISCONNECTED");
});

test("stderr without newlines is bounded and emits one truncation diagnostic", async () => {
  const factory = new MockFactory();
  const diagnostics = [];
  const supervisor = create(factory, { autoReconnect: false, maxStderrLineBytes: 32, maxStderrBytes: 64 });
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  await supervisor.start();
  factory.processes[0].stderr.write("x".repeat(10_000));
  await waitFor(() => diagnostics.some((item) => item.code === "BACKEND_STDERR_TRUNCATED"));
  assert.equal(diagnostics.filter((item) => item.code === "BACKEND_STDERR_TRUNCATED").length, 1);
  assert.equal(supervisor.state, "READY");
  supervisor.stopNow();
});

test("intentional shutdown never enters the reconnect loop", async () => {
  const factory = new MockFactory();
  const states = [];
  const supervisor = create(factory, { reconnectBaseDelayMs: 1, reconnectMaxDelayMs: 2 });
  supervisor.on("state", (state) => states.push(state));
  await supervisor.start();
  await supervisor.shutdown(500);
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(supervisor.state, "STOPPED");
  assert.equal(factory.processes.length, 1);
  assert.equal(states.includes("RECONNECTING"), false);
});

test("intentional shutdown during reconnect cancels the timer and clears tombstones", async () => {
  const factory = new MockFactory();
  const supervisor = create(factory, { reconnectBaseDelayMs: 50, reconnectMaxDelayMs: 50, requestTimeoutMs: 20 });
  await supervisor.start();
  factory.backends[0].requestMode = "queue";
  const request = supervisor.cancelTask({ taskId: `tsk_${"a".repeat(26)}`, expectedStateVersion: 1, reason: "shutdown-reconnect" });
  await waitFor(() => factory.backends[0].queuedRequests.length === 1);
  factory.processes[0].crash();
  await assert.rejects(request, (error) => error.code === "BACKEND_DISCONNECTED");
  assert.equal(supervisor.state, "DISCONNECTED");
  await supervisor.shutdown(500);
  await new Promise((resolve) => setTimeout(resolve, 70));
  assert.equal(supervisor.state, "STOPPED");
  assert.equal(factory.processes.length, 1);
  assert.equal(supervisor.tombstones.size, 0);
});

test("window close preserves backend and explicit quit delegates graceful shutdown", async () => {
  const calls = [];
  const lifecycle = new BackendRuntimeLifecycle({ shutdown: async (deadline) => { calls.push(["shutdown", deadline]); } });
  let prevented = false;
  let hidden = false;
  lifecycle.onWindowClose({ preventDefault: () => { prevented = true; } }, () => { hidden = true; });
  assert.equal(prevented, true);
  assert.equal(hidden, true);
  assert.deepEqual(calls, []);
  await lifecycle.onExplicitQuit(1234);
  assert.deepEqual(calls, [["shutdown", 1234]]);
});
