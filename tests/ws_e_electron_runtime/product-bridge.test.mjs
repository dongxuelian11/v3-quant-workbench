import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const { ProductBridge, errorToView } = await import("../../dist/apps/desktop/src/main/productRuntime/productBridge.js");
const { ProductBindingStore, productBindingPath } = await import("../../dist/apps/desktop/src/main/productRuntime/bindingStore.js");
const { PRODUCT_RUNTIME_CHANNELS } = await import("../../dist/apps/desktop/src/main/productRuntime/ipc.js");
const { BackendRuntimeError } = await import("../../dist/apps/desktop/src/main/backendRuntime/errors.js");

const REFS = { projectId: "prj_smoke01", projectContextRevisionId: "pcr_smoke01", sessionId: "aaaaaaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee" };
const RUN_SPEC_ID = `btrs_sha256_${"b".repeat(64)}`;

function projectContextReadModel(projectId, pcrId) {
  return {
    read_model_version: "v3.project-context/1.0",
    project_id: projectId,
    project_context_revision_id: pcrId,
    revision_no: 1,
    parent_revision_id: null,
    canonical_hash: "sha256_test",
    context: { context_fields: {} },
    created_at: "2026-08-15T00:00:00Z",
    created_by: "test",
    capabilities: []
  };
}

function stubSupervisor({ failOpen = false, runSpecRows = null, taskRows = null } = {}) {
  const calls = [];
  return {
    calls,
    config: { desktopVersion: "1.0.0" },
    state: "READY",
    capabilities: [
      { code: "ProjectSessionService", truth_state: "FORMAL" },
      { code: "BacktestService", truth_state: "FORMAL" },
      { code: "TaskService", truth_state: "UNAVAILABLE", reason_code: "PRODUCT_OPERATION_SET_INCOMPLETE" }
    ],
    context: null,
    shutdowns: 0,
    starts: 0,
    setProjectContext(context) { this.context = context; },
    clearProjectContext() { this.context = undefined; },
    async shutdown() { this.shutdowns += 1; this.state = "STOPPED"; },
    async start() { this.starts += 1; this.state = "READY"; },
    async request(operationId, payload) {
      calls.push({ operationId, payload });
      if (operationId === "ProductEntryService.v1.listBacktestRunSpecs" && runSpecRows !== null) {
        const after = payload.page.after_artifact_id;
        const start = after === undefined ? 0 : runSpecRows.findIndex((row) => row.artifact_id === after) + 1;
        const specs = runSpecRows.slice(start, start + 50);
        const hasMore = start + specs.length < runSpecRows.length;
        return { read_model: {
          specs,
          has_more: hasMore,
          next_after_artifact_id: hasMore ? specs.at(-1).artifact_id : null
        } };
      }
      if (operationId === "TaskService.v1.listTasks" && taskRows !== null) {
        return { read_model: { items: taskRows, page_size: payload.page_size, truncated: false } };
      }
      if (operationId === "ProjectSessionService.v1.openProject") {
        if (failOpen) throw new BackendRuntimeError("canonical project not found", "NOT_FOUND");
        return { read_model: projectContextReadModel(this.context.projectId, this.context.projectContextRevisionId) };
      }
      if (operationId === "ProjectSessionService.v1.getProjectContext") {
        return { read_model: projectContextReadModel(this.context.projectId, this.context.projectContextRevisionId) };
      }
      if (operationId === "ProjectSessionService.v1.restoreSession") {
        return { read_model: {
          read_model_version: "v3.session-restore/1.0", session_row_id: "ses_test", project_id: this.context.projectId,
          project_context_revision_id: this.context.projectContextRevisionId, state: "OPEN", active_lab: null,
          layout_artifact_id: null, opened_at: "2026-08-15T00:00:00Z", closed_at: null, context: {}
        } };
      }
      if (operationId === "BacktestService.v1.submitBacktest") {
        return { request_id: "req", task_id: "tsk_bridge01", run_id: "run_bridge01", accepted_state: "QUEUED", event_cursor: 5 };
      }
      if (operationId === "ProductEntryService.v1.submitResearch") {
        return {
          request_id: "req-research",
          truth_state: "DEMO",
          read_model: {
            read_model_version: "v3.product-entry-research/1.0",
            task_id: "tsk_research01",
            run_id: "run_research01",
            accepted_state: "QUEUED",
            event_cursor: 6,
            maturity: "PRODUCT_CONNECTED_CANDIDATE",
            research_profile_id: "RESEARCH_FREE_DATA_V1",
            strategy_profile_id: "RESEARCH_CLOSE_RANK_TOP1_V1",
            research_classification: ["RESEARCH_ONLY", "APPROXIMATE"],
            truth_admission: { truth: "NOT_FORMAL", admission: "PRE_ALPHA" }
          }
        };
      }
      if (operationId === "TaskService.v1.getTask") {
        return { read_model: {
          read_model_version: "v3.task/1.0", task_id: payload.task_id, project_id: this.context?.projectId ?? "prj_smoke01",
          operation_id: "BacktestService.v1.submitBacktest", state: "SUCCEEDED", state_version: 4, run_id: "run_bridge01",
          attempt: { attempt_id: "att_1", ordinal: 1, state: "SUCCEEDED", error_category: null },
          outputs: { BACKTEST_RUN_RESULT: `art_sha256_${"c".repeat(64)}` },
          created_at: "2026-08-15T00:00:00Z", updated_at: "2026-08-15T00:00:01Z", terminal_at: "2026-08-15T00:00:01Z"
        } };
      }
      throw new Error(`unexpected operation ${operationId}`);
    }
  };
}

const stubStore = () => ({ cursors: {}, getProjectEventCursor(id) { return this.cursors[id] ?? 0; }, commitProjectEventCursor(id, sequence) { this.cursors[id] = sequence; return Promise.resolve(); } });

test("typed bridge binds only after canonical validation and restarts under the bound context", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-"));
  try {
    const supervisor = stubSupervisor();
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    assert.equal(await bridge.getBoundProject(), null);
    const context = await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    assert.equal(context.projectId, REFS.projectId);
    assert.equal(supervisor.shutdowns, 1);
    assert.equal(supervisor.starts, 1);
    assert.equal((await bridge.getBoundProject()).projectId, REFS.projectId);
    const status = await bridge.getProductStatus();
    assert.equal(status.bindingState, "PROJECT_BOUND");
    assert.equal(status.backendState, "READY");
    assert.equal(status.productVersion, "1.0.0");
    const restored = await bridge.restoreSession();
    assert.equal(restored.projectId, REFS.projectId);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("typed bridge never persists invalid refs and restores prior context on failure", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-"));
  try {
    const supervisor = stubSupervisor({ failOpen: true });
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await assert.rejects(
      () => bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId }),
      (error) => error.code === "NOT_FOUND"
    );
    assert.equal(await bridge.getBoundProject(), null);
    assert.equal(supervisor.context, undefined, "failed bind must clear the candidate context");
    await assert.rejects(() => bridge.connectExistingProject({ projectId: "not canonical!", projectContextRevisionId: REFS.projectContextRevisionId }));
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("submitExistingBacktestRunSpec admits canonical specs only, collapses duplicates, and blocks numeric caller truth", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-"));
  try {
    const supervisor = stubSupervisor();
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await assert.rejects(() => bridge.submitExistingBacktestRunSpec("btrs_sha256_short"), (error) => error.code === "NO_CANONICAL_PROJECT_BOUND");
    await assert.rejects(() => bridge.submitExistingBacktestRunSpec(42), (error) => error.code === "NO_CANONICAL_PROJECT_BOUND");
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    const [first, second] = await Promise.all([
      bridge.submitExistingBacktestRunSpec(RUN_SPEC_ID),
      bridge.submitExistingBacktestRunSpec(RUN_SPEC_ID)
    ]);
    assert.equal(first.taskId, "tsk_bridge01");
    assert.equal(second.taskId, first.taskId);
    assert.equal(first.acceptedState, "QUEUED");
    assert.equal(first.idempotentReplay, false);
    const submits = supervisor.calls.filter((call) => call.operationId === "BacktestService.v1.submitBacktest");
    assert.equal(submits.length, 1);
    assert.equal(submits[0].payload.run_spec_id, RUN_SPEC_ID);
    assert.equal(submits[0].payload.execution_adapter_version_id, "v3.a_share_daily_eod_engine/0.2.0");
    for (const forbidden of ["observations", "returns", "weights", "predictions", "nav", "metrics"]) {
      assert.ok(!(forbidden in submits[0].payload), `payload must not carry ${forbidden}`);
    }
    const task = await bridge.getTask("tsk_bridge01");
    assert.equal(task.state, "SUCCEEDED");
    assert.ok(task.outputs.BACKTEST_RUN_RESULT.startsWith("art_sha256_"));
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("submitResearch uses the exact Product Entry operation and main-owned closed payload", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-research-bridge-contract-"));
  try {
    const supervisor = stubSupervisor();
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    const intent = { symbol: "000001", startDate: "20260106", endDate: "20260107" };
    const [first, second] = await Promise.all([bridge.submitResearch(intent), bridge.submitResearch(intent)]);
    assert.equal(first.taskId, "tsk_research01");
    assert.deepEqual(second, first, "same in-flight typed research intent must collapse in the main bridge");
    const submits = supervisor.calls.filter((call) => call.operationId === "ProductEntryService.v1.submitResearch");
    assert.equal(submits.length, 1);
    assert.deepEqual(Object.keys(submits[0].payload).sort(), ["idempotency_key", "research_profile_id", "source", "strategy_profile_id"]);
    assert.deepEqual(submits[0].payload.source, {
      provider_id: "pvd_akshare_eastmoney_a_share_eod_v1",
      connector_version_id: "cov_akshare_eod_research_v1",
      logical_dataset: "CN_A_SHARE_EOD",
      frequency: "P1D",
      symbol: "000001",
      start_date: "20260106",
      end_date: "20260107"
    });
    for (const forbidden of ["observations", "bars", "returns", "weights", "predictions", "metrics", "nav", "result", "raw_source_bytes"]) {
      assert.equal(forbidden in submits[0].payload, false, `research payload must not carry ${forbidden}`);
    }
    assert.equal(typeof submits[0].payload.idempotency_key, "string");
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("run-spec discovery reads page two without missing or duplicate artifacts", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-run-spec-pages-"));
  try {
    const runSpecRows = Array.from({ length: 51 }, (_, index) => ({
      run_spec_id: `btrs_sha256_${(index + 1).toString(16).padStart(64, "0")}`,
      artifact_id: `art_sha256_${(index + 1).toString(16).padStart(64, "0")}`,
      content_sha256: (index + 1).toString(16).padStart(64, "0"),
      project_context_revision_id: `pcr_${"A".repeat(26)}`,
      engine_version: "v3.a_share_daily_eod_engine/0.2.0",
      created_at: "2026-08-18T00:00:00Z",
      execution_adapter_version_id: "v3.a_share_daily_eod_engine/0.2.0",
      status: "EXECUTABLE",
      diagnostic: null
    }));
    const supervisor = stubSupervisor({ runSpecRows });
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });

    const listing = await bridge.listBacktestRunSpecs();
    assert.deepEqual(listing.specs.map((spec) => spec.artifactId), runSpecRows.map((row) => row.artifact_id));
    assert.equal(new Set(listing.specs.map((spec) => spec.artifactId)).size, 51);
    assert.equal(listing.hasMore, false);
    assert.equal(listing.nextAfterArtifactId, null);
    const requests = supervisor.calls.filter((call) => call.operationId === "ProductEntryService.v1.listBacktestRunSpecs");
    assert.equal(requests.length, 2);
    assert.equal(requests[0].payload.page.after_artifact_id, undefined);
    assert.equal(requests[1].payload.page.after_artifact_id, runSpecRows[49].artifact_id);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("UNAVAILABLE run-spec with null metadata is readable and never fabricated", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-run-spec-unavailable-"));
  try {
    const artifactId = `art_sha256_${"d".repeat(64)}`;
    const runSpecRows = [{
      run_spec_id: null,
      artifact_id: artifactId,
      content_sha256: null,
      project_context_revision_id: null,
      engine_version: null,
      created_at: null,
      execution_adapter_version_id: null,
      status: "UNAVAILABLE",
      diagnostic: "ArtifactIntegrityError: digest mismatch"
    }];
    const supervisor = stubSupervisor({ runSpecRows });
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    const listing = await bridge.listBacktestRunSpecs();
    assert.equal(listing.specs.length, 1);
    assert.deepEqual(listing.specs[0], {
      runSpecId: null,
      artifactId,
      contentSha256: null,
      projectContextRevisionId: null,
      engineVersion: null,
      createdAt: null,
      executionAdapterVersionId: null,
      status: "UNAVAILABLE",
      diagnostic: "ArtifactIntegrityError: digest mismatch"
    });
    assert.doesNotMatch(JSON.stringify(listing), /btrs_sha256_unknown|"contentSha256":""/);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("product IPC channel set is closed and typed", () => {
  const channels = Object.values(PRODUCT_RUNTIME_CHANNELS);
  assert.equal(channels.length, 18);
  assert.ok(new Set(channels).size === 18);
  for (const channel of channels) assert.ok(channel.startsWith("productRuntime:"));
});

test("errorToView keeps structured codes without leaking stack details", () => {
  const view = errorToView(new BackendRuntimeError("backend said no", "TRUTH_PRECONDITION_FAILED"));
  assert.equal(view.code, "TRUTH_PRECONDITION_FAILED");
  assert.equal(view.retryable, false);
  assert.doesNotMatch(JSON.stringify(view), /at .*productBridge/);
});


// ---- T1/T2/T3: stale canonical binding fails closed -----------------------
test("T1: persisted refs + BINDING_STALE outcome reports stale truth with no admitted project", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-stale-"));
  try {
    const supervisor = stubSupervisor();
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    bridge.recordBindingOutcome({ state: "BINDING_STALE", code: "NOT_FOUND", message: "session row removed" });
    const status = await bridge.getProductStatus();
    assert.equal(status.bindingState, "BINDING_STALE");
    assert.equal(status.boundProject, null);
    assert.equal(await bridge.getBoundProject(), null);
    const fs = await import("node:fs/promises");
    const persisted = JSON.parse(await fs.readFile(productBindingPath(dir), "utf8"));
    assert.equal(persisted.projectId, REFS.projectId);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("T2: stale binding blocks product operations BEFORE any supervisor request", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-stale-"));
  try {
    const supervisor = stubSupervisor();
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    bridge.recordBindingOutcome({ state: "BINDING_STALE", code: "NOT_FOUND", message: "stale" });
    const callsBefore = supervisor.calls.length;
    for (const blocked of [
      () => bridge.getProjectContext(),
      () => bridge.restoreSession(),
      () => bridge.listTasks(),
      () => bridge.getTask("tsk_bridge01"),
      () => bridge.getTaskEvents(0, 10),
      () => bridge.getResult("res_x"),
      () => bridge.getArtifactDescriptor(`art_sha256_${"e".repeat(64)}`),
      () => bridge.openArtifactStream(`art_sha256_${"e".repeat(64)}`),
      () => bridge.submitExistingBacktestRunSpec(RUN_SPEC_ID)
    ]) {
      await assert.rejects(blocked, (error) => error.code === "BINDING_STALE");
    }
    assert.equal(supervisor.calls.length, callsBefore, "no supervisor request may leave the bridge while stale");
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("T3: PROJECT_BOUND flow unchanged after the stale fail-closed fix", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-valid-"));
  try {
    const supervisor = stubSupervisor();
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    const context = await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    assert.equal(context.projectId, REFS.projectId);
    const status = await bridge.getProductStatus();
    assert.equal(status.bindingState, "PROJECT_BOUND");
    assert.equal(status.boundProject.projectId, REFS.projectId);
    assert.equal((await bridge.getBoundProject()).projectId, REFS.projectId);
    const task = await bridge.getTask("tsk_bridge01");
    assert.equal(task.state, "SUCCEEDED");
    const submitted = await bridge.submitExistingBacktestRunSpec(RUN_SPEC_ID);
    assert.equal(submitted.taskId, "tsk_bridge01");
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("listTasks uses only the bounded admitted discovery filter over the existing operation", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-list-tasks-"));
  try {
    const taskRows = [{
      read_model_version: "v3.task/1.0",
      task_id: "tsk_research",
      project_id: REFS.projectId,
      operation_id: "ProductEntryService.v1.submitResearch",
      state: "SUCCEEDED",
      state_version: 3,
      run_id: "run_research",
      result_id: "res_research",
      attempt: { attempt_id: "att_research", ordinal: 1, state: "SUCCEEDED", error_category: null },
      outputs: { BACKTEST_RUN_RESULT: `art_sha256_${"f".repeat(64)}` },
      created_at: "2026-08-15T00:00:00Z",
      updated_at: "2026-08-15T00:00:01Z",
      terminal_at: "2026-08-15T00:00:01Z"
    }];
    const supervisor = stubSupervisor({ taskRows });
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    const tasks = await bridge.listTasks({ service: "ProductEntryService", state: "SUCCEEDED" });
    assert.equal(tasks[0].taskId, "tsk_research");
    const listCall = supervisor.calls.find((call) => call.operationId === "TaskService.v1.listTasks");
    assert.deepEqual(listCall.payload.filter, { service: "ProductEntryService", state: "SUCCEEDED" });
    assert.equal(listCall.payload.page_size, 200);
    await assert.rejects(() => bridge.listTasks({ service: "BacktestService" }), (error) => error.code === "INVALID_ARGUMENT");
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});
test("T2b: unbound bridge still reports NO_CANONICAL_PROJECT_BOUND before requests", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-unbound-"));
  try {
    const supervisor = stubSupervisor();
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await assert.rejects(() => bridge.getProjectContext(), (error) => error.code === "NO_CANONICAL_PROJECT_BOUND");
    await assert.rejects(() => bridge.getTask("tsk_x"), (error) => error.code === "NO_CANONICAL_PROJECT_BOUND");
    await assert.rejects(() => bridge.submitExistingBacktestRunSpec(RUN_SPEC_ID), (error) => error.code === "NO_CANONICAL_PROJECT_BOUND");
    assert.equal(supervisor.calls.length, 0);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});
