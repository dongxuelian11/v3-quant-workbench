// B3 product-runtime smoke: normal production bootstrap over framed stdio.
//
// Flow: python setup (canonical source data/owners, test-setup only)
//   -> spawn the normal production backend (real product ports)
//   -> handshake -> capability matrix -> open/restore project
//   -> golden execution through frozen ASL operations
//   -> canonical Task transition + Result/Artifact evidence
//   -> idempotency (same key same task; same key different request conflict)
//   -> negative paths (unavailable service, unknown operation)
//   -> graceful shutdown -> restart on the same storage root
//   -> restore project/session -> same Task/Result/Artifact
//   -> durable event replay -> python verified byte SHA + determinism check.
//
// No development fixture is used by the runtime path at any point.

import { spawnSync, spawn } from "node:child_process";
import { createHash, createHmac, randomBytes, randomUUID } from "node:crypto";
import { mkdtempSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, delimiter, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const backendSrc = resolve(root, "apps/backend/src");
const python = process.env.V3_PYTHON ?? "python3";
const pythonEnv = {
  ...process.env,
  PYTHONPATH: `${root}${delimiter}${backendSrc}`,
};

let passed = 0;
function check(condition, label) {
  if (!condition) {
    console.error(`FAIL: ${label}`);
    process.exit(1);
  }
  passed += 1;
  console.log(`ok ${passed} - ${label}`);
}

function uuidv7() {
  const nowMs = Date.now();
  const bytes = randomBytes(16);
  bytes[0] = (nowMs / 2 ** 32) & 0xff;
  bytes[1] = (nowMs / 2 ** 24) & 0xff;
  bytes[2] = (nowMs / 2 ** 16) & 0xff;
  bytes[3] = (nowMs / 2 ** 8) & 0xff;
  bytes[4] = nowMs & 0xff;
  bytes[5] = Math.floor(Math.random() * 0x100);
  bytes[6] = (bytes[6] & 0x0f) | 0x70;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function runPython(args) {
  const result = spawnSync(python, args, { env: pythonEnv, encoding: "utf8" });
  if (result.status !== 0) {
    console.error(result.stdout ?? "");
    console.error(result.stderr ?? "");
    throw new Error(`python ${args[0]} failed`);
  }
  return result.stdout.trim();
}

// ---- framed stdio client ------------------------------------------------

class FramedClient {
  constructor(child) {
    this.child = child;
    this.buffer = Buffer.alloc(0);
    this.expected = null;
    this.queue = [];
    this.waiter = null;
    child.stdout.on("data", (chunk) => this._feed(chunk));
  }

  _feed(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    const frames = [];
    while (true) {
      if (this.expected === null) {
        const idx = this.buffer.indexOf("\r\n\r\n");
        if (idx < 0) break;
        const header = this.buffer.slice(0, idx).toString("ascii");
        const match = /Content-Length: (\d+)/.exec(header);
        if (!match) throw new Error(`bad frame header: ${header}`);
        this.expected = Number(match[1]);
        this.buffer = this.buffer.slice(idx + 4);
      }
      if (this.buffer.length < this.expected) break;
      const payload = this.buffer.slice(0, this.expected);
      this.buffer = this.buffer.slice(this.expected);
      this.expected = null;
      frames.push(JSON.parse(payload.toString("utf8")));
    }
    for (const frame of frames) {
      if (this.waiter) {
        const waiter = this.waiter;
        this.waiter = null;
        waiter(frame);
      } else {
        this.queue.push(frame);
      }
    }
  }

  nextFrame() {
    if (this.queue.length > 0) return Promise.resolve(this.queue.shift());
    return new Promise((resolvePromise) => {
      this.waiter = resolvePromise;
    });
  }

  send(message) {
    const payload = Buffer.from(JSON.stringify(message), "utf8");
    const header = `Content-Length: ${payload.length}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n`;
    this.child.stdin.write(Buffer.concat([Buffer.from(header, "ascii"), payload]));
  }
}

function spawnBackend(storageRoot, token) {
  const child = spawn(
    python,
    [
      "-m",
      "v3_backend.runtime.bootstrap",
      "--transport",
      "stdio-framed-v1",
      "--storage-root",
      storageRoot,
    ],
    { env: pythonEnv, stdio: ["pipe", "pipe", "pipe", "pipe"] }
  );
  child.stdio[3].write(token);
  child.stdio[3].end();
  return new FramedClient(child);
}

// ---- smoke ---------------------------------------------------------------

const storageRoot = mkdtempSync(resolve(tmpdir(), "v3-product-runtime-smoke-"));
console.log(`storage root: ${storageRoot}`);

const setupWire = JSON.parse(
  runPython(["scripts/product_runtime_smoke_python.py", "setup", storageRoot])
);
const { project_id: projectId, project_context_revision_id: pcrId, run_spec_id: runSpecId } = setupWire;
console.log(`golden project: ${projectId} @ ${pcrId}`);
console.log(`golden run spec: ${runSpecId}`);

const token = randomBytes(32);
const SERVICE_SET = [
  "ProjectSessionService", "DataSourceService", "InstrumentService", "DataSnapshotService",
  "UniverseService", "ResearchService", "DatasetService", "StrategyService", "ModelService",
  "StudyService", "PortfolioService", "RiskService", "OptimizationService", "BacktestService",
  "ResultService", "TaskService", "ArtifactService",
];

// Phase A: first backend process.
const backend = spawnBackend(storageRoot, token);
const hello = await backend.nextFrame();
check(hello.kind === "backend.hello", "handshake hello received");
check(hello.protocol === "v3.local/1.0", "protocol version");
check(hello.capabilities.length === 17, "capability matrix lists 17 services");
const caps = new Map(hello.capabilities.map((c) => [c.code, c]));
for (const service of SERVICE_SET) check(caps.has(service), `capability present: ${service}`);
for (const service of ["ProjectSessionService", "TaskService", "ArtifactService", "BacktestService"]) {
  check(caps.get(service).truth_state === "FORMAL", `${service} is FORMAL`);
}
for (const service of ["ResearchService", "ModelService", "DatasetService", "StrategyService"]) {
  check(caps.get(service).truth_state === "UNAVAILABLE", `${service} is UNAVAILABLE`);
}
check(caps.get("ResultService").reason_code === "PRODUCT_OPERATION_SET_INCOMPLETE", "ResultService honest reason");
check(![...caps.values()].some((c) => c.truth_state === "DEMO"), "no DEMO capability on the normal path");

const tokenProof = createHmac("sha256", token).update(hello.nonce, "ascii").digest("hex");
const requestedVersions = {};
for (const service of SERVICE_SET) requestedVersions[service] = "1.0";
backend.send({
  kind: "supervisor.accept",
  token_proof: tokenProof,
  requested_protocol: "v3.local/1.0",
  requested_asl_versions: requestedVersions,
  desktop_version: "0.1.0-recovery.1",
  project_id: projectId,
  project_context_revision_id: pcrId,
  last_project_event_sequence: 0,
});
const ready = await backend.nextFrame();
check(ready.kind === "backend.ready", "backend ready after accept");

let requestCounter = 0;
async function request(operationId, bodyFields, extraEnvelope = {}) {
  const requestId = uuidv7();
  const body = {
    request_id: requestId,
    project_id: projectId,
    project_context_revision_id: pcrId,
    expected_api_version: "1.0",
    ...bodyFields,
  };
  backend.send({
    kind: "request",
    request_id: requestId,
    operation_id: operationId,
    contract_version: "1.0",
    project_id: projectId,
    project_context_revision_id: pcrId,
    body,
    ...extraEnvelope,
  });
  return await backend.nextFrame();
}

// Open / restore the real project.
const sessionId = uuidv7();
const opened = await request("ProjectSessionService.v1.openProject", {
  project_locator: `v3:${projectId}`,
  session_id: sessionId,
});
check(opened.status === "OK", "openProject OK");
check(opened.body.read_model.project_id === projectId, "openProject returns the durable project context");
const context = await request("ProjectSessionService.v1.getProjectContext", {});
check(context.status === "OK" && context.body.read_model.project_context_revision_id === pcrId, "getProjectContext OK");

// Golden execution: submit the canonical backtest run spec.
const idempotencyKey = "smoke-golden-key-0001";
const submitted = await request("BacktestService.v1.submitBacktest", {
  run_spec_id: runSpecId,
  execution_adapter_version_id: "v3.a_share_daily_eod_engine/0.2.0",
  idempotency_key: idempotencyKey,
});
check(submitted.status === "OK", "submitBacktest accepted");
check(submitted.body.accepted_state === "QUEUED", "accepted state is QUEUED");
const taskId = submitted.body.task_id;
const runId = submitted.body.run_id;
check(typeof taskId === "string" && taskId.startsWith("tsk_"), "canonical Task identity");
check(typeof runId === "string" && runId.startsWith("run_"), "canonical Run identity");

const task = await request("TaskService.v1.getTask", { task_id: taskId });
check(task.status === "OK" && task.body.read_model.state === "SUCCEEDED", "Task transitioned to SUCCEEDED");
const resultArtifactId = task.body.read_model.outputs["BACKTEST_RUN_RESULT"];
check(typeof resultArtifactId === "string" && resultArtifactId.startsWith("art_sha256_"), "canonical result artifact identity");

const events = await request("TaskService.v1.getEvents", { after_sequence: 0, limit: 100 });
check(events.status === "OK", "task events query OK");
const eventTypes = new Set(events.body.read_model.items.map((item) => item.event_type));
check(eventTypes.has("TASK_QUEUED") && eventTypes.has("TASK_STARTED") && eventTypes.has("TASK_SUCCEEDED"), "canonical Task transition events durable");
const lastEventSequence = events.body.read_model.high_watermark;

const descriptor = await request("ArtifactService.v1.getArtifactDescriptor", { artifact_id: resultArtifactId });
check(descriptor.status === "OK", "artifact descriptor OK");
const declaredSha = descriptor.body.read_model.sha256;
check(/^[0-9a-f]{64}$/.test(declaredSha), "descriptor carries a canonical SHA-256");

const ticket = await request("ArtifactService.v1.openArtifactStream", { artifact_id: resultArtifactId });
check(ticket.status === "OK" && ticket.body.read_model.mode === "STREAM_TICKET", "stream ticket issued without a raw path");

// The canonical result_id is recorded in the durable TASK_SUCCEEDED event.
let resultId = null;
for (const item of events.body.read_model.items) {
  if (item.event_type === "TASK_SUCCEEDED" && item.body.outputs && item.body.outputs.result_id) {
    resultId = item.body.outputs.result_id;
  }
}
check(!!resultId, "canonical result_id recorded in the durable task event");
const resultRow = await request("ResultService.v1.getResult", {
  result_id: resultId,
  section: "summary",
  page: {},
});
check(resultRow.status === "OK" && resultRow.body.read_model.state === "PENDING_RECONCILIATION", "durable Result record reopened");

// Idempotency: same key + same request returns the same Task/Run.
const duplicate = await request("BacktestService.v1.submitBacktest", {
  run_spec_id: runSpecId,
  execution_adapter_version_id: "v3.a_share_daily_eod_engine/0.2.0",
  idempotency_key: idempotencyKey,
});
check(duplicate.status === "OK" && duplicate.body.task_id === taskId && duplicate.body.run_id === runId, "duplicate idempotency_key returns the same task/run (no double execution)");

// Same key + different request fails closed.
const conflicting = await request("BacktestService.v1.submitBacktest", {
  run_spec_id: "btrs_sha256_" + "f".repeat(64),
  execution_adapter_version_id: "v3.a_share_daily_eod_engine/0.2.0",
  idempotency_key: idempotencyKey,
});
check(conflicting.status === "ERROR" && conflicting.error.code === "IDEMPOTENCY_CONFLICT", "same key + different request fails closed");

// Negative: operation in an UNAVAILABLE service fails closed.
const unavailable = await request("ResearchService.v1.submitFactorAnalysis", {
  factor_version_ids: ["fav_AAAAAAAAAAAAAAAAAAAAAAAAAA"],
  universe_version_id: "unv_AAAAAAAAAAAAAAAAAAAAAAAAAA",
  snapshot_id: "snp_AAAAAAAAAAAAAAAAAAAAAAAAAA",
  analysis_spec: {},
  idempotency_key: "smoke-unavailable-key",
});
check(unavailable.status === "ERROR" && unavailable.error.code === "CAPABILITY_UNAVAILABLE", "operation in UNAVAILABLE service fails closed");

// Negative: unknown operation.
const unknown = await request("BacktestService.v1.noSuchOperation", {});
check(unknown.status === "ERROR", "unknown operation fails");

// Durable transport event replay.
backend.send({ kind: "events.replay", after_sequence: 0, limit: 100 });
const replayFrames = [];
while (true) {
  const frame = await backend.nextFrame();
  if (frame.kind === "events.replayComplete") break;
  replayFrames.push(frame);
}
check(replayFrames.length >= 3, "durable event replay delivers the golden run events");

// Graceful shutdown.
backend.send({ kind: "runtime.prepareShutdown", deadline_at: null });
const shutdownReady = await backend.nextFrame();
check(shutdownReady.kind === "runtime.shutdownReady", "shutdown prepared");
backend.send({ kind: "runtime.commitShutdown" });
const shutdownCommitted = await backend.nextFrame();
check(shutdownCommitted.kind === "runtime.shutdownCommitted", "shutdown committed");

// ---- Phase B: restart on the same storage root ---------------------------
const restarted = spawnBackend(storageRoot, token);
const hello2 = await restarted.nextFrame();
check(hello2.kind === "backend.hello", "restart handshake hello");
const proof2 = createHmac("sha256", token).update(hello2.nonce, "ascii").digest("hex");
restarted.send({
  kind: "supervisor.accept",
  token_proof: proof2,
  requested_protocol: "v3.local/1.0",
  requested_asl_versions: requestedVersions,
  desktop_version: "0.1.0-recovery.1",
  project_id: projectId,
  project_context_revision_id: pcrId,
  last_project_event_sequence: lastEventSequence,
});
const ready2 = await restarted.nextFrame();
check(ready2.kind === "backend.ready", "restarted backend ready");

async function request2(operationId, bodyFields) {
  const requestId = uuidv7();
  const body = {
    request_id: requestId,
    project_id: projectId,
    project_context_revision_id: pcrId,
    expected_api_version: "1.0",
    ...bodyFields,
  };
  restarted.send({
    kind: "request",
    request_id: requestId,
    operation_id: operationId,
    contract_version: "1.0",
    project_id: projectId,
    project_context_revision_id: pcrId,
    body,
  });
  return await restarted.nextFrame();
}

const restored = await request2("ProjectSessionService.v1.restoreSession", { session_id: sessionId });
check(restored.status === "OK", "session restored after restart");
check(restored.body.read_model.project_id === projectId, "restored session points at the durable project");

const taskAfter = await request2("TaskService.v1.getTask", { task_id: taskId });
check(taskAfter.status === "OK" && taskAfter.body.read_model.state === "SUCCEEDED", "same Task state after restart");
check(taskAfter.body.read_model.run_id === runId, "same Run identity after restart");

const resultAfter = await request2("ResultService.v1.getResult", {
  result_id: resultId,
  section: "summary",
  page: {},
});
check(resultAfter.status === "OK" && resultAfter.body.read_model.backtest_run_id === runId, "same Result after restart");

const descriptorAfter = await request2("ArtifactService.v1.getArtifactDescriptor", { artifact_id: resultArtifactId });
check(descriptorAfter.status === "OK" && descriptorAfter.body.read_model.sha256 === declaredSha, "same Artifact descriptor SHA after restart");

// Durable events still replay from the restarted runtime.
restarted.send({ kind: "events.replay", after_sequence: 0, limit: 100 });
let replayedTypes = [];
while (true) {
  const frame = await restarted.nextFrame();
  if (frame.kind === "events.replayComplete") break;
  replayedTypes.push(frame.event_type);
}
check(replayedTypes.includes("TASK_SUCCEEDED"), "durable events replay after restart");

restarted.send({ kind: "runtime.prepareShutdown", deadline_at: null });
await restarted.nextFrame();
restarted.send({ kind: "runtime.commitShutdown" });
await restarted.nextFrame();

// ---- Phase C: python verified byte SHA + determinism check ---------------
const verified = JSON.parse(
  runPython([
    "scripts/product_runtime_smoke_python.py",
    "verify",
    storageRoot,
    resultArtifactId,
    declaredSha,
    runSpecId,
    setupWire.expected_backtest_result_id,
  ])
);
check(verified.verified === true && verified.sha256 === declaredSha, "actual artifact bytes SHA matches the descriptor");
check(verified.result_id === setupWire.expected_backtest_result_id, "runtime execution reproduces the canonical pipeline result deterministically");

console.log(`\nPRODUCT_RUNTIME_SMOKE PASS (${passed} checks)`);
