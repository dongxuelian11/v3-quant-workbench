import assert from "node:assert/strict";
import { mkdir, mkdtemp, open, readFile, readdir, rename, rm, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const { ProductBridge, adaptImportResearchPackageOutcome, errorToView } = await import("../../dist/apps/desktop/src/main/productRuntime/productBridge.js");
const { ProductBindingStore, productBindingPath } = await import("../../dist/apps/desktop/src/main/productRuntime/bindingStore.js");
const { PRODUCT_RUNTIME_CHANNELS, registerProductRuntimeIpc } = await import("../../dist/apps/desktop/src/main/productRuntime/ipc.js");
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

function stubSupervisor({ failOpen = false, failStartAt = null, failRestoreAt = null, runSpecRows = null, taskRows = null, projectHome = null } = {}) {
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
    restores: 0,
    setProjectContext(context) { this.context = context; },
    clearProjectContext() { this.context = undefined; },
    async shutdown() { this.shutdowns += 1; this.state = "STOPPED"; },
    async start() {
      this.starts += 1;
      if (this.starts === failStartAt) {
        this.state = "STOPPED";
        throw new BackendRuntimeError("candidate runtime failed to start", "BACKEND_START_FAILED");
      }
      this.state = "READY";
    },
    async request(operationId, payload, options) {
      calls.push({ operationId, payload, options });
      if (operationId === "ProductEntryService.v1.getProjectHome" && projectHome !== null) {
        return structuredClone(projectHome);
      }
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
        return { read_model: { items: taskRows, page_size: payload.page_size, truncated: false, has_more: false, next_cursor: null } };
      }
      if (operationId === "ProjectSessionService.v1.openProject") {
        if (failOpen) throw new BackendRuntimeError("canonical project not found", "NOT_FOUND");
        return { read_model: projectContextReadModel(this.context.projectId, this.context.projectContextRevisionId) };
      }
      if (operationId === "ProjectSessionService.v1.getProjectContext") {
        return { read_model: projectContextReadModel(this.context.projectId, this.context.projectContextRevisionId) };
      }
      if (operationId === "ProjectSessionService.v1.restoreSession") {
        this.restores += 1;
        if (this.restores === failRestoreAt) {
          throw new BackendRuntimeError("candidate session restore failed", "SESSION_RESTORE_FAILED");
        }
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
      if (operationId === "ProductEntryService.v1.submitFactorStudy") {
        return {
          request_id: "req-factor",
          truth_state: "NOT_FORMAL",
          read_model: {
            read_model_version: "v3.product-entry-factor-study/1.1",
            task_id: "tsk_factor01",
            run_id: "run_factor01",
            accepted_state: "QUEUED",
            event_cursor: 7,
            maturity: "PRODUCT_CONNECTED",
            truth: "NOT_FORMAL",
            admission: "PRE_ALPHA",
            checkpoint_resume: "UNAVAILABLE",
            retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
            formula_document_version_id: `fdoc_sha256_${"d".repeat(64)}`,
            analysis_output_name: "MJ"
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

function bindingFileOps({ failRenameAt = null } = {}) {
  let renameCount = 0;
  return {
    readFile: (path) => readFile(path, "utf8"),
    async writeFileDurable(path, content) {
      const handle = await open(path, "w");
      try { await handle.writeFile(content, "utf8"); await handle.sync(); } finally { await handle.close(); }
    },
    rename: async (from, to) => {
      renameCount += 1;
      if (renameCount === failRenameAt) {
        const error = new Error("injected binding rename failure");
        error.code = "EACCES";
        throw error;
      }
      await rename(from, to);
    },
    mkdir: async (path) => { await mkdir(path, { recursive: true }); },
    unlink,
    syncCommitDirectory: async () => undefined
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
      (error) => error.code === "BINDING_ACTIVATION_FAILED" && error.cause?.code === "NOT_FOUND"
    );
    assert.equal(await bridge.getBoundProject(), null);
    assert.equal(supervisor.context, undefined, "failed bind must clear the candidate context");
    await assert.rejects(() => bridge.connectExistingProject({ projectId: "not canonical!", projectContextRevisionId: REFS.projectContextRevisionId }));
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C1-01 candidate start failure preserves and revalidates the prior active binding", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-binding-activation-start-fail-"));
  try {
    const supervisor = stubSupervisor({ failStartAt: 2 });
    const bindingPath = productBindingPath(dir);
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(bindingPath));
    const prior = { projectId: "prj_prior01", projectContextRevisionId: "pcr_prior01" };
    const candidate = { projectId: "prj_candidate01", projectContextRevisionId: "pcr_candidate01" };

    await bridge.connectExistingProject(prior);
    const priorActive = JSON.parse(await (await import("node:fs/promises")).readFile(bindingPath, "utf8"));

    await assert.rejects(
      () => bridge.connectExistingProject(candidate),
      (error) => error.code === "BINDING_ACTIVATION_FAILED"
        && error.cause?.code === "BACKEND_START_FAILED"
    );

    const activeAfterFailure = JSON.parse(await (await import("node:fs/promises")).readFile(bindingPath, "utf8"));
    assert.deepEqual(activeAfterFailure, priorActive, "active file is the only commit marker and must remain prior");
    assert.equal(supervisor.state, "READY", "prior runtime must be restarted after candidate failure");
    assert.equal(supervisor.starts, 3, "initial prior, failed candidate, then recovered prior generations");
    assert.equal(supervisor.context.projectId, prior.projectId);
    assert.equal((await bridge.getBoundProject()).projectId, prior.projectId, "renderer authority must remain prior");
    const restoredSessions = supervisor.calls.filter((call) => call.operationId === "ProjectSessionService.v1.restoreSession");
    assert.equal(restoredSessions.at(-1).payload.session_id, priorActive.sessionId, "recovery must revalidate the prior session");
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C1-01 candidate restore failure rolls back runtime, session, and visible binding", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-binding-activation-restore-fail-"));
  try {
    const supervisor = stubSupervisor({ failRestoreAt: 2 });
    const bindingPath = productBindingPath(dir);
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(bindingPath));
    const prior = { projectId: "prj_prior02", projectContextRevisionId: "pcr_prior02" };
    const candidate = { projectId: "prj_candidate02", projectContextRevisionId: "pcr_candidate02" };
    await bridge.connectExistingProject(prior);
    const priorActive = JSON.parse(await readFile(bindingPath, "utf8"));

    await assert.rejects(
      () => bridge.connectExistingProject(candidate),
      (error) => error.code === "BINDING_ACTIVATION_FAILED"
        && error.cause?.code === "SESSION_RESTORE_FAILED"
    );

    assert.deepEqual(JSON.parse(await readFile(bindingPath, "utf8")), priorActive);
    assert.equal(supervisor.state, "READY");
    assert.equal(supervisor.starts, 3);
    assert.equal(supervisor.restores, 3, "candidate failure must be followed by prior-session revalidation");
    assert.equal(supervisor.context.projectId, prior.projectId);
    assert.equal((await bridge.getBoundProject()).projectId, prior.projectId);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C1-01 binding rename failure never commits candidate and recovers prior generation", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-binding-activation-rename-fail-"));
  try {
    const supervisor = stubSupervisor();
    const bindingPath = productBindingPath(dir);
    const bridge = new ProductBridge(
      supervisor,
      stubStore(),
      new ProductBindingStore(bindingPath, bindingFileOps({ failRenameAt: 2 }))
    );
    const prior = { projectId: "prj_prior03", projectContextRevisionId: "pcr_prior03" };
    const candidate = { projectId: "prj_candidate03", projectContextRevisionId: "pcr_candidate03" };
    await bridge.connectExistingProject(prior);
    const priorActive = JSON.parse(await readFile(bindingPath, "utf8"));

    await assert.rejects(
      () => bridge.connectExistingProject(candidate),
      (error) => error.code === "BINDING_ACTIVATION_FAILED"
        && error.cause?.code === "BINDING_COMMIT_RENAME_FAILED"
        && error.cause?.cause?.code === "EACCES"
    );

    assert.deepEqual(JSON.parse(await readFile(bindingPath, "utf8")), priorActive);
    assert.equal(supervisor.starts, 3);
    assert.equal(supervisor.context.projectId, prior.projectId);
    assert.equal((await bridge.getBoundProject()).projectId, prior.projectId);
    await assert.rejects(() => readFile(`${bindingPath}.pending`, "utf8"), (error) => error.code === "ENOENT");
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C1-01 crash before rename isolates pending and starts from prior active", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-binding-crash-before-rename-"));
  try {
    const bindingPath = productBindingPath(dir);
    const priorStore = new ProductBindingStore(bindingPath);
    const prior = await priorStore.persist({ ...REFS, projectId: "prj_prior04", projectContextRevisionId: "pcr_prior04" });
    await priorStore.stage({ ...REFS, projectId: "prj_candidate04", projectContextRevisionId: "pcr_candidate04" });

    const recoveredStore = new ProductBindingStore(bindingPath);
    const recovered = await recoveredStore.load();
    assert.equal(recovered.projectId, prior.projectId);
    assert.equal(recovered.sessionId, prior.sessionId);
    assert.equal(recoveredStore.current.projectId, prior.projectId);
    const names = await readdir(dir);
    assert.equal(names.includes("v3-product-binding.json.pending"), false);
    assert.equal(names.filter((name) => name.startsWith("v3-product-binding.json.pending.orphaned.")).length, 1);
    const supervisor = stubSupervisor();
    supervisor.setProjectContext({
      projectId: recovered.projectId,
      projectContextRevisionId: recovered.projectContextRevisionId,
      lastDurableProjectEventSequence: 0
    });
    await supervisor.start();
    const bridge = new ProductBridge(supervisor, stubStore(), recoveredStore);
    const restored = await bridge.restoreSession();
    bridge.recordBindingOutcome({ state: "PROJECT_BOUND" });
    assert.equal(restored.projectId, prior.projectId);
    assert.equal(supervisor.calls.at(-1).payload.session_id, prior.sessionId);
    assert.equal(supervisor.starts, 1);
    assert.equal((await bridge.getBoundProject()).projectId, prior.projectId);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C1-01 crash after rename recovers candidate because active is the commit marker", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-binding-crash-after-rename-"));
  try {
    const bindingPath = productBindingPath(dir);
    const store = new ProductBindingStore(bindingPath);
    await store.persist({ ...REFS, projectId: "prj_prior05", projectContextRevisionId: "pcr_prior05" });
    const candidate = await store.stage({ ...REFS, projectId: "prj_candidate05", projectContextRevisionId: "pcr_candidate05" });
    await store.commit(candidate);

    const recoveredStore = new ProductBindingStore(bindingPath);
    const recovered = await recoveredStore.load();
    assert.equal(recovered.projectId, candidate.projectId);
    assert.equal(recovered.projectContextRevisionId, candidate.projectContextRevisionId);
    assert.equal(recovered.sessionId, candidate.sessionId);
    assert.equal((await readdir(dir)).some((name) => name.includes(".pending")), false);
    const supervisor = stubSupervisor();
    supervisor.setProjectContext({
      projectId: recovered.projectId,
      projectContextRevisionId: recovered.projectContextRevisionId,
      lastDurableProjectEventSequence: 0
    });
    await supervisor.start();
    const bridge = new ProductBridge(supervisor, stubStore(), recoveredStore);
    const restored = await bridge.restoreSession();
    bridge.recordBindingOutcome({ state: "PROJECT_BOUND" });
    assert.equal(restored.projectId, candidate.projectId);
    assert.equal(supervisor.calls.at(-1).payload.session_id, candidate.sessionId);
    assert.equal(supervisor.starts, 1);
    assert.equal((await bridge.getBoundProject()).projectId, candidate.projectId);
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

test("submitFactorStudy owns idempotency in main, collapses exact intent, and carries no caller truth", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-factor-bridge-contract-"));
  try {
    const supervisor = stubSupervisor();
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    const intent = { formulaSource: "MJ:AMOUNT/VOL/100;", analysisOutputName: "MJ" };
    const [first, second] = await Promise.all([bridge.submitFactorStudy(intent), bridge.submitFactorStudy(intent)]);
    assert.deepEqual(second, first);
    assert.equal(first.formulaDocumentVersionId, `fdoc_sha256_${"d".repeat(64)}`);
    const submits = supervisor.calls.filter((call) => call.operationId === "ProductEntryService.v1.submitFactorStudy");
    assert.equal(submits.length, 1);
    assert.deepEqual(Object.keys(submits[0].payload).sort(), ["analysis_output_name", "formula_source", "idempotency_key"]);
    assert.equal(submits[0].payload.formula_source, intent.formulaSource);
    assert.equal(submits[0].payload.analysis_output_name, "MJ");
    assert.match(submits[0].payload.idempotency_key, /^v3-desktop:/);
    assert.deepEqual(submits[0].options, {
      contractVersion: "1.1.0",
      expectedApiVersion: "1.1",
      idempotencyKey: submits[0].payload.idempotency_key,
      timeoutMs: 30_000
    });
    for (const forbidden of ["bars", "values", "snapshot_id", "universe_version_id", "factor_definition_version_id", "artifact_id"]) {
      assert.equal(forbidden in submits[0].payload, false);
    }
    await assert.rejects(
      () => bridge.submitFactorStudy({ ...intent, snapshotId: "caller-owned" }),
      { code: "INVALID_ARGUMENT" }
    );
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("getProjectHome uses Product Entry 1.1 and rejects date-coverage or closed-shape drift", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-project-home-bridge-contract-"));
  const refs = {
    projectId: `prj_${"A".repeat(26)}`,
    projectContextRevisionId: `pcr_${"B".repeat(26)}`
  };
  const data = {
    schema_version: "v3.product-data-read-model/1.0.0",
    project_id: refs.projectId,
    project_context_revision_id: refs.projectContextRevisionId,
    display_name: "golden.csv",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    source_type: "LOCAL_USER_SUPPLIED",
    pit_state: "PIT_UNPROVABLE",
    media_type: "text/csv",
    row_count: 40,
    instrument_count: 20,
    date_coverage_start: "2026-01-05",
    date_coverage_end: "2026-02-06",
    partition_count: 1,
    universe_role: "USER_DEFINED_STATIC",
    quality_status: "PASS",
    validation_profile_id: "svp_local_user_supplied_v1",
    capability_reasons: {
      pit: "PIT_UNPROVABLE",
      revision: "PROVIDER_REVISION_UNKNOWN",
      calendar: "OBSERVED_LOCAL_ROWS_NOT_FORMAL_TRADING_CALENDAR",
      status: "SOURCE_COLUMN_ABSENT_OR_NULL_WHEN_NOT_PROVIDED"
    },
    volume_unit: "SHARES",
    amount_unit: "CNY",
    adjustment: "UNADJUSTED",
    raw_capture_id: `raw_sha256_${"a".repeat(64)}`,
    raw_content_hash: "a".repeat(64),
    snapshot_id: `snp_sha256_${"b".repeat(64)}`,
    normalized_payload_hash: "b".repeat(64),
    universe_version_id: `unv_sha256_${"c".repeat(64)}`,
    imported_at: "2026-08-24T00:00:00Z",
    raw_artifact_id: `art_sha256_${"a".repeat(64)}`
  };
  const response = {
    request_id: "018f47f2-9b02-7cc0-8ee6-1b82e3d62c01",
    truth_state: "NOT_FORMAL",
    read_model: {
      read_model_version: "v3.project-home/1.1",
      project_id: refs.projectId,
      project_context_revision_id: refs.projectContextRevisionId,
      maturity: "PRODUCT_CONNECTED",
      truth: "NOT_FORMAL",
      admission: "PRE_ALPHA",
      local_import_state: "AVAILABLE",
      data_state: "AVAILABLE",
      data_unavailable_reason: "NONE",
      factor_state: "EMPTY",
      factor_unavailable_reason: "NO_FACTOR_STUDY",
      data
    }
  };
  const unavailableMetric = (reason) => ({ status: "INSUFFICIENT_SAMPLE", value: null, reason });
  const factor = {
    schema_version: "v3.project-factor-summary/1.0.0",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    project_id: refs.projectId,
    project_context_revision_id: refs.projectContextRevisionId,
    snapshot_id: data.snapshot_id,
    universe_version_id: data.universe_version_id,
    source_manifest_artifact_id: `art_sha256_${"d".repeat(64)}`,
    source_manifest_sha256: "d".repeat(64),
    formula_document_version_id: `fdoc_sha256_${"e".repeat(64)}`,
    formula_document_artifact_id: `art_sha256_${"e".repeat(64)}`,
    analysis_output_name: "MJ",
    analysis_artifact_id: `art_sha256_${"f".repeat(64)}`,
    outputs: [{
      name: "MJ",
      factor_definition_version_id: `fdv_sha256_${"1".repeat(64)}`,
      factor_definition_artifact_id: `art_sha256_${"1".repeat(64)}`,
      materialization_id: `fmt_sha256_${"2".repeat(64)}`,
      materialization_artifact_id: `art_sha256_${"2".repeat(64)}`,
      output_type: "FLOAT_SERIES",
      row_count: 40
    }],
    visual_preview: [{
      session_date: "2026-01-05",
      instrument_id: "ins_000001",
      open: 10,
      high: 11,
      low: 9,
      close: 10.5,
      volume_shares: 1000,
      amount_cny: 10500,
      series: [{ name: "MJ", value: 10.5 }]
    }],
    analysis: {
      factor_analysis_result_id: `far_sha256_${"3".repeat(64)}`,
      spec: {
        schema_version: "v3.factor-analysis-spec/1.0.0",
        forward_return_horizon_sessions: 5,
        quantiles: 5,
        minimum_instruments_per_date: 20,
        minimum_valid_ic_dates: 20,
        formation_price: "RAW_CLOSE",
        label_price: "RAW_CLOSE",
        signal_availability: "AFTER_SESSION_CLOSE"
      },
      aggregate: {
        valid_dates: 0,
        ic_mean: unavailableMetric("MINIMUM_VALID_IC_DATES"),
        ic_std: unavailableMetric("MINIMUM_VALID_IC_DATES"),
        icir: unavailableMetric("MINIMUM_VALID_IC_DATES"),
        rank_ic_mean: unavailableMetric("MINIMUM_VALID_IC_DATES"),
        rank_ic_std: unavailableMetric("MINIMUM_VALID_IC_DATES"),
        rank_icir: unavailableMetric("MINIMUM_VALID_IC_DATES"),
        yearly_distribution: []
      },
      daily_results: [{
        session_date: "2026-01-05",
        label_session_date: "2026-01-12",
        status: "INSUFFICIENT_SAMPLE",
        reason: "MINIMUM_INSTRUMENTS_PER_DATE",
        universe_size: 1,
        sample_size: 1,
        coverage: 1,
        missing_rate: 0,
        ic: unavailableMetric("MINIMUM_INSTRUMENTS_PER_DATE"),
        rank_ic: unavailableMetric("MINIMUM_INSTRUMENTS_PER_DATE"),
        quantile_returns: null,
        long_short_spread: null,
        turnover: unavailableMetric("NO_PRIOR_PORTFOLIO"),
        diagnostics: ["MINIMUM_INSTRUMENTS_PER_DATE"],
        excluded_reason_counts: [["WARMUP", 1]]
      }]
    }
  };
  try {
    const supervisor = stubSupervisor({ projectHome: response });
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject(refs);
    const home = await bridge.getProjectHome();
    assert.equal(home.data.dateCoverageStart, "2026-01-05");
    assert.equal(home.data.dateCoverageEnd, "2026-02-06");
    const call = supervisor.calls.find((item) => item.operationId === "ProductEntryService.v1.getProjectHome");
    assert.deepEqual(call.payload, {});
    assert.deepEqual(call.options, { contractVersion: "1.1.0", expectedApiVersion: "1.1" });

    const factorResponse = structuredClone(response);
    factorResponse.read_model.factor_state = "AVAILABLE";
    factorResponse.read_model.factor_unavailable_reason = "NONE";
    factorResponse.read_model.factor = factor;
    const factorBridge = new ProductBridge(
      stubSupervisor({ projectHome: factorResponse }),
      stubStore(),
      new ProductBindingStore(productBindingPath(join(dir, "factor")))
    );
    await factorBridge.connectExistingProject(refs);
    const factorHome = await factorBridge.getProjectHome();
    assert.equal(factorHome.factor.analysis.dailyResults[0].excludedReasonCounts[0].reason, "WARMUP");
    assert.equal(factorHome.factor.visualPreview[0].series.MJ, 10.5);

    for (const mutate of [
      (candidate) => { candidate.read_model.factor.project_id = `prj_${"C".repeat(26)}`; },
      (candidate) => { candidate.read_model.factor.visual_preview[0].series[0].value = Infinity; },
      (candidate) => { candidate.read_model.factor.visual_preview[0].series = []; },
      (candidate) => { candidate.read_model.factor.analysis.daily_results[0].excluded_reason_counts = [{ reason: "WARMUP", count: 1 }]; }
    ]) {
      const candidate = structuredClone(factorResponse);
      mutate(candidate);
      const candidateBridge = new ProductBridge(
        stubSupervisor({ projectHome: candidate }),
        stubStore(),
        new ProductBindingStore(productBindingPath(join(dir, `factor-drift-${Math.random()}`)))
      );
      await candidateBridge.connectExistingProject(refs);
      await assert.rejects(() => candidateBridge.getProjectHome(), { code: "PRODUCT_BRIDGE_ERROR" });
    }

    response.read_model.data.date_coverage_start = "2026-03-01";
    const driftSupervisor = stubSupervisor({ projectHome: response });
    const driftBridge = new ProductBridge(driftSupervisor, stubStore(), new ProductBindingStore(productBindingPath(join(dir, "drift"))));
    await driftBridge.connectExistingProject(refs);
    await assert.rejects(() => driftBridge.getProjectHome(), { code: "PRODUCT_BRIDGE_ERROR" });
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("run-spec discovery exposes an explicit next page without bridge auto-looping", async () => {
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

    const first = await bridge.listBacktestRunSpecs();
    assert.deepEqual(first.specs.map((spec) => spec.artifactId), runSpecRows.slice(0, 50).map((row) => row.artifact_id));
    assert.equal(first.hasMore, true);
    assert.match(first.nextCursor, /^[A-Za-z0-9_-]+$/);
    assert.notEqual(first.nextCursor, runSpecRows[49].artifact_id, "renderer cursor must not expose the backend artifact cursor");
    const second = await bridge.listBacktestRunSpecs({ cursor: first.nextCursor, pageSize: 50 });
    assert.deepEqual(second.specs.map((spec) => spec.artifactId), [runSpecRows[50].artifact_id]);
    assert.equal(second.hasMore, false);
    assert.equal(second.nextCursor, null);
    const requests = supervisor.calls.filter((call) => call.operationId === "ProductEntryService.v1.listBacktestRunSpecs");
    assert.equal(requests.length, 2);
    assert.equal(requests[0].payload.page.after_artifact_id, undefined);
    assert.equal(requests[1].payload.page.after_artifact_id, runSpecRows[49].artifact_id);
    await bridge.connectExistingProject({ projectId: "prj_smoke02", projectContextRevisionId: "pcr_smoke02" });
    await assert.rejects(
      () => bridge.listBacktestRunSpecs({ cursor: first.nextCursor }),
      /project owner or sort binding is invalid/
    );
    assert.equal(supervisor.calls.filter((call) => call.operationId === "ProductEntryService.v1.listBacktestRunSpecs").length, 2);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("run-spec and import adapters reject coercible contract drift", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-coercion-"));
  try {
    const runSpecRows = [{
      run_spec_id: RUN_SPEC_ID,
      artifact_id: 42,
      content_sha256: "a".repeat(64),
      project_context_revision_id: `pcr_${"A".repeat(26)}`,
      engine_version: "v3.a_share_daily_eod_engine/0.2.0",
      created_at: "2026-08-18T00:00:00Z",
      execution_adapter_version_id: "v3.a_share_daily_eod_engine/0.2.0",
      status: "EXECUTABLE",
      diagnostic: null
    }];
    const bridge = new ProductBridge(stubSupervisor({ runSpecRows }), stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    await assert.rejects(() => bridge.listBacktestRunSpecs(), /malformed artifact identity/);

    const valid = {
      read_model: {
        read_model_version: "v3.product-entry/1.0",
        run_spec_id: RUN_SPEC_ID,
        run_spec_artifact_id: `art_sha256_${"b".repeat(64)}`,
        context_artifact_id: `art_sha256_${"c".repeat(64)}`,
        already_imported: false,
        source_project_id: `prj_${"A".repeat(26)}`,
        imported_at: "2026-08-23T00:00:00Z"
      }
    };
    assert.equal(adaptImportResearchPackageOutcome(valid).alreadyImported, false);
    for (const [field, drift] of [
      ["run_spec_id", 7],
      ["run_spec_artifact_id", 8],
      ["context_artifact_id", 9],
      ["already_imported", "false"],
      ["source_project_id", 10],
      ["imported_at", 11]
    ]) {
      const response = structuredClone(valid);
      response.read_model[field] = drift;
      assert.throws(() => adaptImportResearchPackageOutcome(response), { code: "PRODUCT_BRIDGE_ERROR" });
    }
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("project discovery exposes one validated keyset page and an explicit next cursor", async () => {
  const rows = Array.from({ length: 51 }, (_, index) => ({
    project_id: `prj_${String(index + 1).padStart(26, "0")}`,
    project_context_revision_id: `pcr_${String(index + 1).padStart(26, "0")}`,
    display_name: `项目 ${index + 1}`,
    created_at: "2026-08-18T00:00:00Z"
  }));
  const supervisor = stubSupervisor();
  const controls = [];
  supervisor.productEntryControl = async (frame) => {
    controls.push(frame);
    const start = frame.after_project_id === null
      ? 0
      : rows.findIndex((row) => row.project_id === frame.after_project_id) + 1;
    const projects = rows.slice(start, start + frame.limit);
    return { projects, has_more: start + projects.length < rows.length };
  };
  const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore("unused-for-project-list.json"));
  const first = await bridge.listProjects();
  assert.equal(first.projects.length, 50);
  assert.equal(first.hasMore, true);
  assert.match(first.nextCursor, /^[A-Za-z0-9_-]+$/);
  assert.notEqual(first.nextCursor, rows[49].project_id, "renderer cursor must not expose the backend project cursor");
  const second = await bridge.listProjects({ cursor: first.nextCursor });
  assert.deepEqual(second.projects.map((item) => item.projectId), [rows[50].project_id]);
  assert.equal(second.hasMore, false);
  assert.equal(second.nextCursor, null);
  assert.equal(controls.length, 2);
  assert.equal(controls[1].after_project_id, rows[49].project_id);
  await assert.rejects(
    () => bridge.listProjects({ cursor: `art_sha256_${"a".repeat(64)}` }),
    /valid opaque product cursor/
  );
  assert.equal(controls.length, 2, "invalid opaque cursor must fail before backend control dispatch");
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
  assert.equal(channels.length, 22);
  assert.ok(new Set(channels).size === 22);
  for (const channel of channels) assert.ok(channel.startsWith("productRuntime:"));
});

test("product IPC rejects numeric strings instead of coercing pagination", async () => {
  const handlers = new Map();
  const ipcMain = {
    handle(channel, listener) { handlers.set(channel, listener); },
    removeHandler(channel) { handlers.delete(channel); }
  };
  const bridge = {
    async listProjects(request) { return request; },
    async listTasks(request) { return request; },
    async submitFactorStudy(request) { return request; }
  };
  const unregister = registerProductRuntimeIpc(ipcMain, () => undefined, bridge);
  try {
    await assert.rejects(
      () => handlers.get(PRODUCT_RUNTIME_CHANNELS.listProjects)({}, { pageSize: "50" }),
      /INVALID_ARGUMENT/
    );
    await assert.rejects(
      () => handlers.get(PRODUCT_RUNTIME_CHANNELS.listTasks)({}, { filter: {}, pageSize: "50" }),
      /INVALID_ARGUMENT/
    );
    assert.deepEqual(
      await handlers.get(PRODUCT_RUNTIME_CHANNELS.listProjects)({}, { pageSize: 50 }),
      { pageSize: 50 }
    );
    assert.deepEqual(
      await handlers.get(PRODUCT_RUNTIME_CHANNELS.submitFactorStudy)({}, { formulaSource: "MJ:CLOSE;", analysisOutputName: "MJ" }),
      { formulaSource: "MJ:CLOSE;", analysisOutputName: "MJ" }
    );
    await assert.rejects(
      () => handlers.get(PRODUCT_RUNTIME_CHANNELS.submitFactorStudy)({}, { formulaSource: "MJ:CLOSE;", analysisOutputName: "MJ", snapshotId: "forbidden" }),
      /INVALID_ARGUMENT/
    );
    await assert.rejects(
      () => handlers.get(PRODUCT_RUNTIME_CHANNELS.submitFactorStudy)({}, { formulaSource: "X".repeat(65_537), analysisOutputName: "MJ" }),
      /INVALID_ARGUMENT/
    );
  } finally {
    unregister();
  }
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
    const tasks = await bridge.listTasks({ filter: { service: "ProductEntryService", state: "SUCCEEDED" } });
    assert.equal(tasks.tasks[0].taskId, "tsk_research");
    const listCall = supervisor.calls.find((call) => call.operationId === "TaskService.v1.listTasks");
    assert.deepEqual(listCall.payload.filter, { service: "ProductEntryService", state: "SUCCEEDED" });
    assert.equal(listCall.payload.page_size, 50);
    await assert.rejects(() => bridge.listTasks({ filter: { service: "BacktestService" } }), (error) => error.code === "INVALID_ARGUMENT");
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
