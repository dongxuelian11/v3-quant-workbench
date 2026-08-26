import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, open, readFile, readdir, rename, rm, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const { ProductBridge, adaptImportResearchPackageOutcome, errorToView } = await import("../../dist/apps/desktop/src/main/productRuntime/productBridge.js");
const { ProductBindingStore, productBindingPath } = await import("../../dist/apps/desktop/src/main/productRuntime/bindingStore.js");
const { PRODUCT_RUNTIME_CHANNELS, registerProductRuntimeIpc } = await import("../../dist/apps/desktop/src/main/productRuntime/ipc.js");
const { ArtifactExportBroker } = await import("../../dist/apps/desktop/src/main/productRuntime/artifactExport.js");
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

function stubSupervisor({ failOpen = false, failStartAt = null, failRestoreAt = null, restoreErrorCode = null, runSpecRows = null, taskRows = null, projectHome = null, artifactPayload = null, artifactPayloads = null, artifactStreamFailure = null } = {}) {
  const calls = [];
  const payloadFor = (artifactId) => artifactPayloads?.get(artifactId) ?? artifactPayload;
  return {
    calls,
    config: { desktopVersion: "1.0.0" },
    state: "READY",
    capabilities: [
      { code: "ProjectSessionService", truth_state: "FORMAL" },
      { code: "BacktestService", truth_state: "UNAVAILABLE", reason_code: "FORMAL_EXECUTION_CONTRACT_NOT_CLOSED" },
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
        if (restoreErrorCode !== null) {
          throw new BackendRuntimeError("session binding conflicts with the current project", restoreErrorCode);
        }
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
      if (operationId === "ProductEntryService.v1.previewResearchStrategy") {
        const home = projectHome.read_model;
        return {
          request_id: "req-strategy-preview",
          truth_state: "NOT_FORMAL",
          read_model: {
            schema_version: "v3.product-strategy-preview/1.0.0",
            maturity: "PRODUCT_CONNECTED",
            truth: "NOT_FORMAL",
            admission: "PRE_ALPHA",
            project_id: home.project_id,
            project_context_revision_id: home.project_context_revision_id,
            snapshot_id: home.data.snapshot_id,
            universe_version_id: payload.universe_version_id,
            research_strategy_spec_id: `rssv_sha256_${"8".repeat(64)}`,
            strategy_definition_version_id: `sdv_sha256_${"d".repeat(64)}`,
            entry_signal_factor_version_id: payload.entry_signal_factor_version_id,
            exit_signal_factor_version_id: payload.exit_signal_factor_version_id,
            profile_refs: {
              cost_policy_version_id: payload.cost_policy_version_id,
              execution_policy_version_id: payload.execution_policy_version_id,
              risk_policy_set_version_id: payload.risk_policy_set_version_id,
              assumption_profile_id: payload.assumption_profile_id
            },
            assumption_mode: payload.assumption_profile_id === `assumption_sha256_${"e".repeat(64)}`
              ? "STRICT_FAIL_CLOSED" : "RESEARCH_APPROXIMATE",
            transition_count: 2,
            planned_decision_chain_count: 2,
            side_effects: "NONE"
          }
        };
      }
      if (operationId === "ProductEntryService.v1.publishResearchStrategy") {
        return {
          request_id: "req-strategy",
          truth_state: "NOT_FORMAL",
          read_model: {
            read_model_version: "v3.product-entry-research-strategy/1.1",
            task_id: "tsk_strategy01",
            run_id: "run_strategy01",
            accepted_state: "QUEUED",
            maturity: "PRODUCT_CONNECTED",
            truth: "NOT_FORMAL",
            admission: "PRE_ALPHA",
            checkpoint_resume: "UNAVAILABLE",
            retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
            research_strategy_spec_id: `rssv_sha256_${"8".repeat(64)}`,
            event_cursor: 8
          }
        };
      }
      if (operationId === "ProductEntryService.v1.previewResearchBacktest") {
        const home = projectHome.read_model;
        return {
          request_id: "req-backtest-preview",
          truth_state: "NOT_FORMAL",
          read_model: {
            schema_version: "v3.product-backtest-preflight/1.0.0",
            maturity: "PRODUCT_CONNECTED",
            truth: "NOT_FORMAL",
            admission: "PRE_ALPHA",
            status: "PASS",
            project_id: home.project_id,
            project_context_revision_id: home.project_context_revision_id,
            research_strategy_spec_id: payload.research_strategy_spec_id,
            research_backtest_request_id: `rbr_sha256_${"9".repeat(64)}`,
            snapshot_id: home.data.snapshot_id,
            universe_version_id: home.data.universe_version_id,
            session_start: payload.session_start,
            session_end: payload.session_end,
            slippage_bps: payload.slippage_bps,
            daily_volume_participation_rate: payload.daily_volume_participation_rate,
            commission_rate: home.backtest_policy_coverage.commission_rate,
            minimum_commission_cny: home.backtest_policy_coverage.minimum_commission_cny,
            stamp_duty_sell_rate: home.backtest_policy_coverage.stamp_duty_sell_rate,
            assumption_mode: home.strategy.profile_refs.assumption_profile_id === `assumption_sha256_${"e".repeat(64)}`
              ? "STRICT_FAIL_CLOSED" : "RESEARCH_APPROXIMATE",
            policy_refs: {
              rule_profile_id: home.backtest_policy_coverage.rule_profile_id,
              cost_policy_id: home.backtest_policy_coverage.cost_policy_id,
              execution_timing_profile_id: home.backtest_policy_coverage.execution_timing_profile_id,
              risk_policy_set_version_id: home.strategy.profile_refs.risk_policy_set_version_id
            },
            resource_estimate: structuredClone(home.backtest_policy_coverage.resource_estimate),
            side_effects: "NONE"
          }
        };
      }
      if (operationId === "ProductEntryService.v1.submitResearchBacktest") {
        return {
          request_id: "req-backtest",
          truth_state: "NOT_FORMAL",
          read_model: {
            read_model_version: "v3.product-entry-research-backtest/1.1",
            task_id: "tsk_product_backtest01",
            run_id: "run_product_backtest01",
            accepted_state: "QUEUED",
            maturity: "PRODUCT_CONNECTED",
            truth: "NOT_FORMAL",
            admission: "PRE_ALPHA",
            checkpoint_resume: "UNAVAILABLE",
            retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
            research_backtest_request_id: `rbr_sha256_${"9".repeat(64)}`,
            event_cursor: 9
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
      if (payloadFor(payload.artifact_id) !== null && operationId === "ArtifactService.v1.getArtifactDescriptor") {
        const selectedPayload = payloadFor(payload.artifact_id);
        const sha256 = createHash("sha256").update(selectedPayload).digest("hex");
        return { read_model: {
          read_model_version: "v3.artifact-descriptor/1.0",
          artifact_id: payload.artifact_id,
          sha256,
          byte_size: selectedPayload.byteLength,
          media_type: "application/json",
          role: "PRODUCT_RESEARCH_BACKTEST_READ_MODEL",
          state: "PUBLISHED",
          created_at: "2026-08-24T00:00:00Z",
          published_at: "2026-08-24T00:00:00Z"
        } };
      }
      if (payloadFor(payload.artifact_id) !== null && operationId === "ArtifactService.v1.openArtifactStream") {
        const selectedPayload = payloadFor(payload.artifact_id);
        return { read_model: {
          read_model_version: "v3.artifact-stream-ticket/1.0",
          mode: "STREAM_TICKET",
          ticket_id: `stk_${"0".repeat(26)}`,
          artifact_id: payload.artifact_id,
          project_id: REFS.projectId,
          expires_at: "2026-08-24T00:05:00Z",
          range_start: null,
          range_end_exclusive: null
        } };
      }
      if (artifactPayload !== null && operationId === "ArtifactService.v1.exportArtifact") {
        return {
          request_id: "aaaaaaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee",
          task_id: `tsk_${"4".repeat(26)}`,
          run_id: `run_${"4".repeat(26)}`,
          accepted_state: "QUEUED",
          event_cursor: 8
        };
      }
      throw new Error(`unexpected operation ${operationId}`);
    },
    async consumeArtifactStream(input) {
      calls.push({ operationId: "artifactStream.consume", payload: input });
      const selectedPayload = payloadFor(input.artifactId);
      const sha256 = createHash("sha256").update(selectedPayload).digest("hex");
      return {
        artifactId: input.artifactId,
        sha256,
        byteSize: selectedPayload.byteLength,
        bytes: Uint8Array.from(selectedPayload)
      };
    },
    async streamArtifactToSink(input, sink) {
      calls.push({ operationId: "artifactStream.sink", payload: input });
      if (artifactStreamFailure !== null) throw artifactStreamFailure;
      const sha256 = createHash("sha256").update(artifactPayload).digest("hex");
      for (let offset = 0; offset < artifactPayload.byteLength; offset += 256 * 1024) {
        const chunk = artifactPayload.subarray(offset, Math.min(artifactPayload.byteLength, offset + 256 * 1024));
        await sink(Uint8Array.from(chunk), offset);
      }
      return {
        artifactId: `art_sha256_${sha256}`,
        sha256,
        byteSize: artifactPayload.byteLength
      };
    },
    async artifactExportControl(frame) {
      calls.push({ operationId: frame.kind, payload: frame });
      if (frame.kind === "artifactExport.complete") {
        return {
          kind: "artifactExport.completed",
          task_id: frame.task_id,
          manifest_artifact_id: `art_sha256_${"c".repeat(64)}`
        };
      }
      return { kind: "artifactExport.failed", task_id: frame.task_id };
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

test("restoreSession rejects a response whose context revision is no longer the persisted binding", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-binding-restore-revision-mismatch-"));
  try {
    const bindingPath = productBindingPath(dir);
    const recoveredStore = new ProductBindingStore(bindingPath);
    await recoveredStore.persist(REFS);
    await recoveredStore.load();
    const supervisor = stubSupervisor();
    supervisor.setProjectContext({
      projectId: REFS.projectId,
      projectContextRevisionId: "pcr_superseding_revision",
      lastDurableProjectEventSequence: 0
    });
    await supervisor.start();
    const bridge = new ProductBridge(supervisor, stubStore(), recoveredStore);
    await assert.rejects(
      () => bridge.restoreSession(),
      (error) => error.code === "BINDING_SESSION_MISMATCH"
    );
    assert.equal(await bridge.getBoundProject(), null, "mismatched restore must not admit a binding");
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("SESSION_PROJECT_BINDING_CONFLICT isolates the active binding before another restart", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-binding-project-conflict-"));
  try {
    const bindingPath = productBindingPath(dir);
    const recoveredStore = new ProductBindingStore(bindingPath);
    await recoveredStore.persist(REFS);
    await recoveredStore.load();
    const supervisor = stubSupervisor({
      restoreErrorCode: "SESSION_PROJECT_BINDING_CONFLICT"
    });
    supervisor.setProjectContext({
      projectId: REFS.projectId,
      projectContextRevisionId: REFS.projectContextRevisionId,
      lastDurableProjectEventSequence: 0
    });
    await supervisor.start();
    const bridge = new ProductBridge(supervisor, stubStore(), recoveredStore);

    await assert.rejects(
      () => bridge.restoreSession(),
      (error) => error.code === "SESSION_PROJECT_BINDING_CONFLICT"
    );
    assert.equal(recoveredStore.current, null);
    assert.equal(await bridge.getBoundProject(), null);
    const status = await bridge.getProductStatus();
    assert.equal(status.bindingState, "BINDING_STALE");
    await assert.rejects(() => readFile(bindingPath, "utf8"), (error) => error.code === "ENOENT");
    const isolated = (await readdir(dir)).filter((name) =>
      name.startsWith("v3-product-binding.json.isolated.SESSION_PROJECT_BINDING_CONFLICT.")
    );
    assert.equal(isolated.length, 1);
    assert.equal(supervisor.context, undefined);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("submitExistingBacktestRunSpec preserves wire compatibility but refuses the unclosed formal capability", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-"));
  try {
    const supervisor = stubSupervisor();
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await assert.rejects(() => bridge.submitExistingBacktestRunSpec("btrs_sha256_short"), (error) => error.code === "NO_CANONICAL_PROJECT_BOUND");
    await assert.rejects(() => bridge.submitExistingBacktestRunSpec(42), (error) => error.code === "NO_CANONICAL_PROJECT_BOUND");
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    await assert.rejects(
      () => bridge.submitExistingBacktestRunSpec(RUN_SPEC_ID),
      (error) => error.code === "CAPABILITY_UNAVAILABLE"
        && error.message.includes("FORMAL_EXECUTION_CONTRACT_NOT_CLOSED")
    );
    const submits = supervisor.calls.filter((call) => call.operationId === "BacktestService.v1.submitBacktest");
    assert.equal(submits.length, 0);
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
      strategy_authoring_profile: {
        schema_version: "v3.product-strategy-authoring-profile/1.0.0",
        truth: "NOT_FORMAL",
        admission: "PRE_ALPHA",
        position_sizing_options: ["SINGLE_ASSET_FULL_WEIGHT", "EQUAL_WEIGHT_ACTIVE_SIGNALS"],
        max_positions_min: 1,
        max_positions_max: 20,
        gross_exposure_min: "0",
        gross_exposure_max: "1",
        rebalance: "NEXT_OPEN_AFTER_SIGNAL",
        profile_refs: {
          cost_policy_version_id: `cost_sha256_${"4".repeat(64)}`,
          execution_policy_version_id: `timing_sha256_${"5".repeat(64)}`,
          risk_policy_set_version_id: `rpsv_sha256_${"6".repeat(64)}`,
          assumption_profile_id: `assumption_sha256_${"7".repeat(64)}`
        },
        assumption_profiles: [
          { mode: "RESEARCH_APPROXIMATE", assumption_profile_id: `assumption_sha256_${"7".repeat(64)}` },
          { mode: "STRICT_FAIL_CLOSED", assumption_profile_id: `assumption_sha256_${"e".repeat(64)}` }
        ]
      },
      backtest_policy_coverage: {
        schema_version: "v3.product-backtest-policy-coverage/1.0.0",
        truth: "NOT_FORMAL",
        admission: "PRE_ALPHA",
        coverage_start: "2026-01-01",
        coverage_end: null,
        rule_profile_id: `atrp_sha256_${"4".repeat(64)}`,
        cost_policy_id: `cost_sha256_${"4".repeat(64)}`,
        execution_timing_profile_id: `timing_sha256_${"5".repeat(64)}`,
        commission_rate: "0.0003",
        minimum_commission_cny: "5",
        stamp_duty_sell_rate: "0.0005",
        resource_estimate: {
          resource_class: "PRODUCT_BACKTEST_CPU",
          cpu_slots: 1,
          memory_limit_bytes: 1073741824,
          scratch_limit_bytes: 1073741824,
          checkpoint_resume: "UNAVAILABLE"
        }
      },
      strategy_state: "EMPTY",
      strategy_unavailable_reason: "NO_FACTOR_STUDY",
      backtest_state: "EMPTY",
      backtest_unavailable_reason: "NO_RESEARCH_STRATEGY",
      data
    }
  };
  const unavailableMetric = (reason) => ({ status: "INSUFFICIENT_SAMPLE", value: null, reason });
  const factor = {
    schema_version: "v3.project-factor-summary/1.1.0",
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
    }, {
      name: "ENTRY",
      factor_definition_version_id: `fdv_sha256_${"8".repeat(64)}`,
      factor_definition_artifact_id: `art_sha256_${"8".repeat(64)}`,
      materialization_id: `fmt_sha256_${"9".repeat(64)}`,
      materialization_artifact_id: `art_sha256_${"9".repeat(64)}`,
      output_type: "BOOLEAN_SERIES",
      row_count: 40
    }],
    visual_preview_total_rows: 1,
    visual_preview_projection: "TAIL_ASCENDING_MAX_256",
    visual_preview: [{
      session_date: "2026-01-05",
      instrument_id: "ins_000001",
      open: 10,
      high: 11,
      low: 9,
      close: 10.5,
      volume_shares: 1000,
      amount_cny: 10500,
      series: [{ name: "MJ", value: 10.5 }, { name: "ENTRY", value: true }]
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
      daily_result_count: 1,
      daily_results_projection: "TAIL_ASCENDING_MAX_256",
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
    factorResponse.read_model.strategy_unavailable_reason = "NO_RESEARCH_STRATEGY";
    factorResponse.read_model.factor = factor;
    const factorSupervisor = stubSupervisor({ projectHome: factorResponse });
    const factorBridge = new ProductBridge(
      factorSupervisor,
      stubStore(),
      new ProductBindingStore(productBindingPath(join(dir, "factor")))
    );
    await factorBridge.connectExistingProject(refs);
    const factorHome = await factorBridge.getProjectHome();
    assert.equal(factorHome.factor.analysis.dailyResults[0].excludedReasonCounts[0].reason, "WARMUP");
    assert.equal(factorHome.factor.visualPreview[0].series.MJ, 10.5);
    assert.equal(factorHome.backtestPolicyCoverage.coverageStart, "2026-01-01");
    assert.match(factorHome.backtestPolicyCoverage.ruleProfileId, /^atrp_sha256_/);

    assert.equal(typeof factorBridge.previewResearchStrategy, "function");
    const strategyIntent = {
      entrySignalFactorVersionId: `fdv_sha256_${"8".repeat(64)}`,
      exitSignalFactorVersionId: `fdv_sha256_${"8".repeat(64)}`,
      positionSizing: "EQUAL_WEIGHT_ACTIVE_SIGNALS",
      maxPositions: 10,
      grossExposure: "1",
      initialCash: "1000000",
      assumptionProfileId: `assumption_sha256_${"e".repeat(64)}`
    };
    const preview = await factorBridge.previewResearchStrategy(strategyIntent);
    assert.equal(preview.sideEffects, "NONE");
    assert.equal(preview.strategyDefinitionVersionId, `sdv_sha256_${"d".repeat(64)}`);
    const previewCall = factorSupervisor.calls.find((item) => item.operationId === "ProductEntryService.v1.previewResearchStrategy");
    assert.equal("idempotency_key" in previewCall.payload, false);
    assert.deepEqual(previewCall.options, { contractVersion: "1.1.0", expectedApiVersion: "1.1", timeoutMs: 30_000 });

    assert.equal(typeof factorBridge.publishResearchStrategy, "function");
    const strategyOutcome = await factorBridge.publishResearchStrategy(strategyIntent);
    assert.equal(strategyOutcome.researchStrategySpecId, `rssv_sha256_${"8".repeat(64)}`);
    const strategyCall = factorSupervisor.calls.find((item) => item.operationId === "ProductEntryService.v1.publishResearchStrategy");
    assert.deepEqual(Object.keys(strategyCall.payload).sort(), [
      "assumption_profile_id", "cost_policy_version_id", "entry_signal_factor_version_id",
      "execution_policy_version_id", "exit_signal_factor_version_id", "gross_exposure",
      "idempotency_key", "initial_cash", "max_positions", "position_sizing", "rebalance",
      "risk_policy_set_version_id", "universe_version_id"
    ]);
    assert.equal(strategyCall.payload.universe_version_id, data.universe_version_id);
    assert.equal(strategyCall.payload.cost_policy_version_id, factorResponse.read_model.strategy_authoring_profile.profile_refs.cost_policy_version_id);
    assert.equal(strategyCall.payload.assumption_profile_id, `assumption_sha256_${"e".repeat(64)}`);
    for (const forbidden of ["bars", "factor_values", "weights", "target_weights", "portfolio", "risk_adjusted_weights"]) {
      assert.equal(forbidden in strategyCall.payload, false);
    }

    const strategyResponse = structuredClone(factorResponse);
    strategyResponse.read_model.strategy_state = "AVAILABLE";
    strategyResponse.read_model.strategy_unavailable_reason = "NONE";
    strategyResponse.read_model.backtest_unavailable_reason = "NO_VALID_BACKTEST";
    strategyResponse.read_model.strategy = {
      schema_version: "v3.project-strategy-summary/1.0.0",
      truth: "NOT_FORMAL",
      admission: "PRE_ALPHA",
      project_id: refs.projectId,
      project_context_revision_id: refs.projectContextRevisionId,
      snapshot_id: data.snapshot_id,
      universe_version_id: data.universe_version_id,
      research_strategy_spec_id: `rssv_sha256_${"8".repeat(64)}`,
      strategy_version_id: `stv_sha256_${"a".repeat(64)}`,
      entry_signal_factor_version_id: `fdv_sha256_${"8".repeat(64)}`,
      exit_signal_factor_version_id: `fdv_sha256_${"8".repeat(64)}`,
      profile_refs: {
        ...structuredClone(strategyResponse.read_model.strategy_authoring_profile.profile_refs),
        assumption_profile_id: `assumption_sha256_${"e".repeat(64)}`
      },
      transition_count: 2,
      decision_chain_count: 2
    };
    const backtestSupervisor = stubSupervisor({ projectHome: strategyResponse });
    const backtestBridge = new ProductBridge(
      backtestSupervisor,
      stubStore(),
      new ProductBindingStore(productBindingPath(join(dir, "backtest")))
    );
    await backtestBridge.connectExistingProject(refs);
    assert.equal(typeof backtestBridge.submitResearchBacktest, "function");
    const backtestOutcome = await backtestBridge.submitResearchBacktest({
      sessionStart: "2026-01-05",
      sessionEnd: "2026-02-06",
      slippageBps: "10",
      dailyVolumeParticipationRate: "0.1"
    });
    assert.equal(backtestOutcome.researchBacktestRequestId, `rbr_sha256_${"9".repeat(64)}`);
    const backtestPreviewCall = backtestSupervisor.calls.find((item) => item.operationId === "ProductEntryService.v1.previewResearchBacktest");
    assert.deepEqual(Object.keys(backtestPreviewCall.payload).sort(), [
      "daily_volume_participation_rate", "research_strategy_spec_id", "session_end", "session_start", "slippage_bps"
    ]);
    assert.deepEqual(backtestPreviewCall.options, { contractVersion: "1.1.0", expectedApiVersion: "1.1", timeoutMs: 30_000 });
    const backtestCall = backtestSupervisor.calls.find((item) => item.operationId === "ProductEntryService.v1.submitResearchBacktest");
    assert.deepEqual(Object.keys(backtestCall.payload).sort(), [
      "daily_volume_participation_rate", "idempotency_key", "research_strategy_spec_id",
      "session_end", "session_start", "slippage_bps"
    ]);
    assert.equal(backtestCall.payload.research_strategy_spec_id, strategyResponse.read_model.strategy.research_strategy_spec_id);

    const truthAdmission = { canonical_truth_state: "NOT_FORMAL", canonical_admission_state: "PRE_ALPHA" };
    const metric = (value) => ({ status: "AVAILABLE", value, reason: null });
    const resultContentSha = "a".repeat(64);
    const backtestResultId = `btrr_sha256_${resultContentSha}`;
    const runSpecId = `btrs_sha256_${"b".repeat(64)}`;
    const resultPayload = {
      artifact_type: "BacktestRunResult",
      result_id: backtestResultId,
      content_sha256: resultContentSha,
      run_spec_id: runSpecId,
      target_quantity_vectors: [],
      orders: [{
        order_id: "ord_result01", session_date: "2026-01-06", instrument_id: "ins_000001",
        side: "BUY", requested_quantity: 100, raw_limit_price: "10",
        source_target_quantity_vector_id: "tqv_result01"
      }],
      fills: [{
        fill_id: "fil_result01", order_id: "ord_result01", session_date: "2026-01-06",
        instrument_id: "ins_000001", side: "BUY", quantity: 100, raw_price: "10",
        consideration: "1000", costs: { commission: "5", stamp_duty: "0", transfer_fee: "0.01", exchange_fee: "0", total: "5.01" },
        execution_price: "10.01", participation_cap: 100, slippage_bps: "10"
      }],
      diagnostics: [{
        order_id: "ord_result01", code: "PARTIAL_FILL_VOLUME_CAP", requested_quantity: 200,
        filled_quantity: 100, detail: "volume participation cap", eligible_quantity: 200,
        unfilled_quantity: 100, participation_cap: 100
      }],
      cash_ledger: [], position_ledger: [],
      holdings: [{ session_date: "2026-01-06", instrument_id: "ins_000001", quantity: 100, sellable_quantity: 0, raw_close: "10.2", market_value: "1020" }],
      nav: [
        { session_date: "2026-01-05", cash: "1000000", holdings_value: "0", nav: "1000000" },
        { session_date: "2026-01-06", cash: "998994.99", holdings_value: "1020", nav: "1000014.99" }
      ],
      truth_admission: truthAdmission
    };
    const analyticsContentSha = "c".repeat(64);
    const analyticsId = `bra_sha256_${analyticsContentSha}`;
    const analyticsPayload = {
      artifact_type: "ProductBacktestResultAnalytics",
      analytics_id: analyticsId,
      content_sha256: analyticsContentSha,
      schema_version: "v3.backtest_result_analytics/1.1.0",
      engine_version: "v3.result_analytics_engine/1.1.0",
      core_analytics: {
        artifact_type: "BacktestResultAnalytics", analytics_id: `bra_sha256_${"d".repeat(64)}`,
        content_sha256: "d".repeat(64), schema_version: "v3.backtest_result_analytics/1.0.0",
        source_result: { result_id: backtestResultId, content_sha256: resultContentSha },
        analytics_policy: { policy_id: `rap_sha256_${"e".repeat(64)}`, content_sha256: "e".repeat(64) },
        benchmark_binding: null,
        metrics: {
          start_nav: metric("1000000"), end_nav: metric("1000014.99"), total_return: metric("0.00001499"),
          annualized_return: metric("0.00377748"), annualized_volatility: metric("0.001"),
          max_drawdown: metric("0"), sharpe: metric("3.7"), sortino: metric("4.1")
        },
        return_series: [
          { session_date: "2026-01-05", nav: "1000000", session_return: metric("0"), cumulative_return: metric("0") },
          { session_date: "2026-01-06", nav: "1000014.99", session_return: metric("0.00001499"), cumulative_return: metric("0.00001499") }
        ],
        drawdown_series: [
          { session_date: "2026-01-05", drawdown: metric("0") },
          { session_date: "2026-01-06", drawdown: metric("0") }
        ],
        drawdown_episode: null,
        monthly_returns: [{ period_kind: "MONTHLY", period_label: "2026-01", start_date: "2026-01-05", end_date: "2026-01-06", period_return: metric("0.00001499") }],
        yearly_returns: [{ period_kind: "YEARLY", period_label: "2026", start_date: "2026-01-05", end_date: "2026-01-06", period_return: metric("0.00001499") }],
        costs: { fill_count: 1, buy_traded_notional: "1000", sell_traded_notional: "0", gross_traded_notional: "1000", fee_breakdown: { commission: "5", stamp_duty: "0", transfer_fee: "0.01", exchange_fee: "0" }, total_fees: "5.01", fee_over_traded_notional: metric("0.00501"), observed_fee_load_over_start_nav: metric("0.00000501") },
        turnover: { convention: "GROSS_TRADED_NOTIONAL_OVER_AVERAGE_DAILY_NAV", gross_traded_notional: "1000", average_daily_nav: "1000007.495", turnover: metric("0.0009999925") },
        benchmark: { status: "BENCHMARK_NOT_AVAILABLE", benchmark_series_id: null, benchmark_content_sha256: null, benchmark_name: null, aligned_benchmark_total_return: { status: "NOT_AVAILABLE", value: null, reason: "BENCHMARK_NOT_AVAILABLE" }, relative_returns: [], tracking_difference: { status: "NOT_AVAILABLE", value: null, reason: "BENCHMARK_NOT_AVAILABLE" }, tracking_error: { status: "NOT_AVAILABLE", value: null, reason: "BENCHMARK_NOT_AVAILABLE" }, alpha: { status: "NOT_AVAILABLE", value: null, reason: "BENCHMARK_NOT_AVAILABLE" }, beta: { status: "NOT_AVAILABLE", value: null, reason: "BENCHMARK_NOT_AVAILABLE" } },
        truth_admission: truthAdmission
      },
      supplemental_metrics: { calmar: { status: "NOT_AVAILABLE", value: null, reason: "ZERO_DRAWDOWN" } },
      exposure_series: [
        { session_date: "2026-01-05", gross_exposure: metric("0"), net_exposure: metric("0"), held_instrument_count: 0 },
        { session_date: "2026-01-06", gross_exposure: metric("0.00101998"), net_exposure: metric("0.00101998"), held_instrument_count: 1 }
      ],
      concentration: { peak_single_position_weight: metric("0.00101998"), peak_session_date: "2026-01-06", peak_instrument_id: "ins_000001", average_held_instrument_count: metric("0.5"), maximum_held_instrument_count: 1 },
      table_summary: { order_count: 1, fill_count: 1, diagnostic_count: 1 },
      truth_admission: truthAdmission
    };
    const resultBytes = Buffer.from(JSON.stringify(resultPayload), "utf8");
    const analyticsBytes = Buffer.from(JSON.stringify(analyticsPayload), "utf8");
    const resultArtifactId = `art_sha256_${createHash("sha256").update(resultBytes).digest("hex")}`;
    const analyticsArtifactId = `art_sha256_${createHash("sha256").update(analyticsBytes).digest("hex")}`;
    const resultId = "res_result01";
    const lineageContentSha = "f".repeat(64);
    const resultLineageId = `rln_sha256_${lineageContentSha}`;
    const lineagePayload = {
      artifact_type: "ProductResultLineage", result_lineage_id: resultLineageId,
      content_sha256: lineageContentSha, schema_version: "v3.product-result-lineage/1.0.0",
      project_id: refs.projectId, project_context_revision_id: refs.projectContextRevisionId,
      data: { raw_capture_id: data.raw_capture_id, raw_artifact_id: data.raw_artifact_id, snapshot_id: data.snapshot_id, snapshot_manifest_artifact_id: `art_sha256_${"1".repeat(64)}`, universe_version_id: data.universe_version_id, universe_membership_artifact_id: `art_sha256_${"2".repeat(64)}` },
      factors: {
        entry: {
          factor_definition_version_id: `fdv_sha256_${"8".repeat(64)}`,
          materialization_id: `fmat_sha256_${"6".repeat(64)}`,
          materialization_artifact_id: `art_sha256_${"6".repeat(64)}`
        },
        exit: {
          factor_definition_version_id: `fdv_sha256_${"8".repeat(64)}`,
          materialization_id: `fmat_sha256_${"7".repeat(64)}`,
          materialization_artifact_id: `art_sha256_${"7".repeat(64)}`
        }
      },
      strategy: { research_strategy_spec_id: strategyResponse.read_model.strategy.research_strategy_spec_id, research_strategy_spec_artifact_id: `art_sha256_${"3".repeat(64)}`, strategy_version_id: strategyResponse.read_model.strategy.strategy_version_id, strategy_definition_version_id: "sdv_result01", strategy_definition_artifact_id: `art_sha256_${"4".repeat(64)}`, risk_policy_set_version_id: strategyResponse.read_model.strategy.profile_refs.risk_policy_set_version_id, decision_chains: [] },
      execution: { run_id: `run_${"C".repeat(26)}`, run_spec_id: runSpecId, run_spec_artifact_id: `art_sha256_${"5".repeat(64)}`, target_quantity_vectors: [], orders: [{ order_id: "ord_result01", source_target_quantity_vector_id: "tqv_result01", instrument_id: "ins_000001", session_date: "2026-01-06" }], fills: [{ fill_id: "fil_result01", order_id: "ord_result01", instrument_id: "ins_000001", session_date: "2026-01-06" }] },
      result: { result_id: resultId, backtest_result_id: backtestResultId, backtest_result_sha256: resultContentSha, result_artifact_id: resultArtifactId, analytics_id: analyticsId, analytics_artifact_id: analyticsArtifactId },
      truth: "NOT_FORMAL", admission: "PRE_ALPHA"
    };
    const lineageBytes = Buffer.from(JSON.stringify(lineagePayload), "utf8");
    const lineageArtifactId = `art_sha256_${createHash("sha256").update(lineageBytes).digest("hex")}`;
    const resultHome = structuredClone(strategyResponse);
    resultHome.read_model.backtest_state = "AVAILABLE";
    resultHome.read_model.backtest_unavailable_reason = "NONE";
    resultHome.read_model.backtest = {
      schema_version: "v3.project-backtest-summary/1.0.0", maturity: "PRODUCT_CONNECTED", truth: "NOT_FORMAL", admission: "PRE_ALPHA",
      project_id: refs.projectId, project_context_revision_id: refs.projectContextRevisionId,
      research_backtest_request_id: `rbrq_sha256_${"9".repeat(64)}`, research_strategy_spec_id: strategyResponse.read_model.strategy.research_strategy_spec_id,
      snapshot_id: data.snapshot_id, universe_version_id: data.universe_version_id,
      run_id: lineagePayload.execution.run_id, run_spec_id: runSpecId, result_id: resultId, backtest_result_id: backtestResultId,
      result_artifact_id: resultArtifactId, analytics_id: analyticsId, analytics_artifact_id: analyticsArtifactId,
      summary_export_artifact_id: `art_sha256_${"6".repeat(64)}`,
      orders_export_artifact_id: `art_sha256_${"7".repeat(64)}`,
      fills_export_artifact_id: `art_sha256_${"8".repeat(64)}`,
      result_lineage_id: resultLineageId, lineage_artifact_id: lineageArtifactId, result_state: "VALID",
      engine_version: "v3.a_share_daily_eod_engine/0.3.0-research", order_count: 1, fill_count: 1, diagnostic_count: 1,
      first_fill_session_date: "2026-01-06", first_effective_session_date: "2026-01-06",
      assumption_mode: "STRICT_FAIL_CLOSED"
    };
    const resultSupervisor = stubSupervisor({
      projectHome: resultHome,
      artifactPayloads: new Map([
        [resultArtifactId, resultBytes], [analyticsArtifactId, analyticsBytes], [lineageArtifactId, lineageBytes]
      ])
    });
    const restartedBridge = new ProductBridge(
      resultSupervisor,
      stubStore(),
      new ProductBindingStore(productBindingPath(join(dir, "result-restart")))
    );
    await restartedBridge.connectExistingProject(refs);
    assert.equal(typeof restartedBridge.getLatestProductResultDetails, "function");
    const details = await restartedBridge.getLatestProductResultDetails();
    assert.equal(details.assumptionMode, "STRICT_FAIL_CLOSED");
    assert.equal(details.backtestResultId, backtestResultId);
    assert.equal(details.metrics.totalReturn.value, "0.00001499");
    assert.equal(details.navSeries.length, 2);
    assert.equal(details.orders.preview[0].orderId, "ord_result01");
    assert.deepEqual(
      {
        commission: details.fills.preview[0].commission,
        stampDuty: details.fills.preview[0].stampDuty,
        transferFee: details.fills.preview[0].transferFee,
        exchangeFee: details.fills.preview[0].exchangeFee,
        totalFees: details.fills.preview[0].totalFees
      },
      { commission: "5", stampDuty: "0", transferFee: "0.01", exchangeFee: "0", totalFees: "5.01" }
    );
    assert.equal(details.lineage.rawCaptureId, data.raw_capture_id);
    assert.equal(details.periodReturns.monthly[0].periodLabel, "2026-01");
    assert.equal(details.periodReturns.yearly[0].periodLabel, "2026");
    assert.equal(details.costSummary.totalFees, "5.01");
    assert.equal(details.concentration.peakInstrumentId, "ins_000001");
    assert.equal(details.benchmarkStatus, "BENCHMARK_NOT_AVAILABLE");
    assert.equal(details.exports.summaryJsonArtifactId, resultHome.read_model.backtest.summary_export_artifact_id);
    assert.equal(details.exports.ordersCsvArtifactId, resultHome.read_model.backtest.orders_export_artifact_id);
    assert.equal(details.exports.fillsCsvArtifactId, resultHome.read_model.backtest.fills_export_artifact_id);
    assert.equal(details.exports.analyticsJsonArtifactId, analyticsArtifactId);
    assert.equal(resultSupervisor.calls.some((item) => item.operationId.includes("submit")), false, "restart Result readback must not recompute or submit work");

    const variantBridge = async (candidateResult, candidateAnalytics, candidateLineage, suffix) => {
      const nextResultBytes = Buffer.from(JSON.stringify(candidateResult), "utf8");
      const nextAnalyticsBytes = Buffer.from(JSON.stringify(candidateAnalytics), "utf8");
      const nextResultArtifactId = `art_sha256_${createHash("sha256").update(nextResultBytes).digest("hex")}`;
      const nextAnalyticsArtifactId = `art_sha256_${createHash("sha256").update(nextAnalyticsBytes).digest("hex")}`;
      candidateLineage.result.result_artifact_id = nextResultArtifactId;
      candidateLineage.result.analytics_artifact_id = nextAnalyticsArtifactId;
      const nextLineageBytes = Buffer.from(JSON.stringify(candidateLineage), "utf8");
      const nextLineageArtifactId = `art_sha256_${createHash("sha256").update(nextLineageBytes).digest("hex")}`;
      const nextHome = structuredClone(resultHome);
      nextHome.read_model.backtest.result_artifact_id = nextResultArtifactId;
      nextHome.read_model.backtest.analytics_artifact_id = nextAnalyticsArtifactId;
      nextHome.read_model.backtest.lineage_artifact_id = nextLineageArtifactId;
      nextHome.read_model.backtest.order_count = candidateResult.orders.length;
      nextHome.read_model.backtest.fill_count = candidateResult.fills.length;
      nextHome.read_model.backtest.diagnostic_count = candidateResult.diagnostics.length;
      const nextSupervisor = stubSupervisor({
        projectHome: nextHome,
        artifactPayloads: new Map([
          [nextResultArtifactId, nextResultBytes],
          [nextAnalyticsArtifactId, nextAnalyticsBytes],
          [nextLineageArtifactId, nextLineageBytes]
        ])
      });
      const nextBridge = new ProductBridge(
        nextSupervisor,
        stubStore(),
        new ProductBindingStore(productBindingPath(join(dir, suffix)))
      );
      await nextBridge.connectExistingProject(refs);
      return nextBridge;
    };

    const baseShapeResult = structuredClone(resultPayload);
    delete baseShapeResult.fills[0].execution_price;
    delete baseShapeResult.fills[0].participation_cap;
    delete baseShapeResult.fills[0].slippage_bps;
    delete baseShapeResult.diagnostics[0].eligible_quantity;
    delete baseShapeResult.diagnostics[0].unfilled_quantity;
    delete baseShapeResult.diagnostics[0].participation_cap;
    const baseShapeBridge = await variantBridge(
      baseShapeResult,
      structuredClone(analyticsPayload),
      structuredClone(lineagePayload),
      "result-base-wire-shapes"
    );
    const baseShapeDetails = await baseShapeBridge.getLatestProductResultDetails();
    assert.equal(baseShapeDetails.fills.preview[0].executionPrice, null);
    assert.equal(baseShapeDetails.fills.preview[0].participationCap, null);
    assert.equal(baseShapeDetails.diagnostics.preview[0].eligibleQuantity, null);

    const navDriftAnalytics = structuredClone(analyticsPayload);
    navDriftAnalytics.core_analytics.return_series[1].nav = "999999";
    const navDriftBridge = await variantBridge(
      structuredClone(resultPayload), navDriftAnalytics, structuredClone(lineagePayload), "result-nav-drift"
    );
    await assert.rejects(() => navDriftBridge.getLatestProductResultDetails(), { code: "PRODUCT_READ_MODEL_INVALID" });

    const missingLineage = structuredClone(lineagePayload);
    delete missingLineage.strategy.risk_policy_set_version_id;
    const missingLineageBridge = await variantBridge(
      structuredClone(resultPayload), structuredClone(analyticsPayload), missingLineage, "result-lineage-missing-field"
    );
    await assert.rejects(() => missingLineageBridge.getLatestProductResultDetails(), { code: "PRODUCT_READ_MODEL_INVALID" });

    for (const mutate of [
      (candidate) => { candidate.read_model.factor.project_id = `prj_${"C".repeat(26)}`; },
      (candidate) => { candidate.read_model.factor.visual_preview[0].series[0].value = Infinity; },
      (candidate) => { candidate.read_model.factor.visual_preview[0].series = []; },
      (candidate) => { candidate.read_model.factor.visual_preview_total_rows = 2; },
      (candidate) => { candidate.read_model.factor.analysis.daily_results[0].excluded_reason_counts = [{ reason: "WARMUP", count: 1 }]; },
      (candidate) => { candidate.read_model.factor.analysis.daily_result_count = 2; },
      (candidate) => { candidate.read_model.backtest_policy_coverage.rule_profile_id = `rules_sha256_${"4".repeat(64)}`; },
      (candidate) => { delete candidate.read_model.backtest_policy_coverage; }
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
  assert.equal(channels.length, 30);
  assert.ok(new Set(channels).size === 30);
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
    async submitFactorStudy(request) { return request; },
    async previewResearchStrategy(request) { return request; },
    async publishResearchStrategy(request) { return request; },
    async previewResearchBacktest(request) { return request; },
    async submitResearchBacktest(request) { return request; },
    async exportArtifact(request) { return request; }
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
    const strategyIntent = {
      entrySignalFactorVersionId: `fdv_sha256_${"1".repeat(64)}`,
      exitSignalFactorVersionId: `fdv_sha256_${"2".repeat(64)}`,
      positionSizing: "EQUAL_WEIGHT_ACTIVE_SIGNALS",
      maxPositions: 10,
      grossExposure: "1",
      initialCash: "1000000",
      assumptionProfileId: `assumption_sha256_${"7".repeat(64)}`
    };
    assert.deepEqual(
      await handlers.get(PRODUCT_RUNTIME_CHANNELS.previewResearchStrategy)({}, strategyIntent),
      strategyIntent
    );
    assert.deepEqual(
      await handlers.get(PRODUCT_RUNTIME_CHANNELS.publishResearchStrategy)({}, strategyIntent),
      strategyIntent
    );
    await assert.rejects(
      () => handlers.get(PRODUCT_RUNTIME_CHANNELS.publishResearchStrategy)({}, {
        entrySignalFactorVersionId: `fdv_sha256_${"1".repeat(64)}`,
        exitSignalFactorVersionId: `fdv_sha256_${"2".repeat(64)}`,
        positionSizing: "EQUAL_WEIGHT_ACTIVE_SIGNALS",
        maxPositions: 10,
        grossExposure: "1",
        initialCash: "1000000",
        assumptionProfileId: `assumption_sha256_${"7".repeat(64)}`,
        universeVersionId: "renderer-forbidden"
      }),
      /INVALID_ARGUMENT/
    );
    assert.deepEqual(
      await handlers.get(PRODUCT_RUNTIME_CHANNELS.previewResearchBacktest)({}, {
        sessionStart: "2026-01-05",
        sessionEnd: "2026-02-06",
        slippageBps: "10",
        dailyVolumeParticipationRate: "0.1"
      }),
      {
        sessionStart: "2026-01-05",
        sessionEnd: "2026-02-06",
        slippageBps: "10",
        dailyVolumeParticipationRate: "0.1"
      }
    );
    assert.deepEqual(
      await handlers.get(PRODUCT_RUNTIME_CHANNELS.submitResearchBacktest)({}, {
        sessionStart: "2026-01-05",
        sessionEnd: "2026-02-06",
        slippageBps: "10",
        dailyVolumeParticipationRate: "0.1"
      }),
      {
        sessionStart: "2026-01-05",
        sessionEnd: "2026-02-06",
        slippageBps: "10",
        dailyVolumeParticipationRate: "0.1"
      }
    );
    assert.deepEqual(
      await handlers.get(PRODUCT_RUNTIME_CHANNELS.exportArtifact)({}, { artifactId: `art_sha256_${"a".repeat(64)}`, suggestedName: "result.json" }),
      { artifactId: `art_sha256_${"a".repeat(64)}`, suggestedName: "result.json" }
    );
    await assert.rejects(
      () => handlers.get(PRODUCT_RUNTIME_CHANNELS.exportArtifact)({}, { artifactId: `art_sha256_${"a".repeat(64)}`, suggestedName: "result.json", path: "D:\\secret" }),
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

test("T3: PROJECT_BOUND flow remains usable while the legacy Backtest action stays unavailable", async () => {
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
    await assert.rejects(
      () => bridge.submitExistingBacktestRunSpec(RUN_SPEC_ID),
      (error) => error.code === "CAPABILITY_UNAVAILABLE"
    );
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C3-09 ProductBridge consumes a ticket against the exact descriptor", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-stream-"));
  try {
    const payload = Buffer.from('{"result":"verified"}', "utf8");
    const sha256 = createHash("sha256").update(payload).digest("hex");
    const artifactId = `art_sha256_${sha256}`;
    const supervisor = stubSupervisor({ artifactPayload: payload });
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    const result = await bridge.readArtifactBytes(artifactId);
    assert.equal(result.artifactId, artifactId);
    assert.equal(result.sha256, sha256);
    assert.equal(result.byteSize, payload.byteLength);
    assert.deepEqual(Buffer.from(result.bytes), payload);
    assert.deepEqual(
      supervisor.calls.slice(-3).map((call) => call.operationId),
      ["ArtifactService.v1.getArtifactDescriptor", "ArtifactService.v1.openArtifactStream", "artifactStream.consume"]
    );
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C3-10 ProductBridge chooser cancellation is NOT_RUN and creates no export Task", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-export-cancel-"));
  try {
    const payload = Buffer.from('{"result":"verified"}', "utf8");
    const sha256 = createHash("sha256").update(payload).digest("hex");
    const artifactId = `art_sha256_${sha256}`;
    const supervisor = stubSupervisor({ artifactPayload: payload });
    const broker = new ArtifactExportBroker({ chooseDestination: async () => null });
    const bridge = new ProductBridge(
      supervisor,
      stubStore(),
      new ProductBindingStore(productBindingPath(dir)),
      undefined,
      undefined,
      null,
      broker
    );
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    supervisor.calls.length = 0;
    assert.deepEqual(await bridge.exportArtifact({ artifactId, suggestedName: "result.json" }), { state: "NOT_RUN" });
    assert.deepEqual(supervisor.calls.map((call) => call.operationId), ["ArtifactService.v1.getArtifactDescriptor"]);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C3-10 ProductBridge streams exact bytes to native destination before completing Task", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-export-success-"));
  try {
    const payload = Buffer.alloc(600 * 1024 + 19, 0x64);
    const sha256 = createHash("sha256").update(payload).digest("hex");
    const artifactId = `art_sha256_${sha256}`;
    const destination = join(dir, "result.json");
    const supervisor = stubSupervisor({ artifactPayload: payload });
    const broker = new ArtifactExportBroker({
      chooseDestination: async () => destination,
      tokenFactory: () => "edc_01ARZ3NDEKTSV4RRFFQ69G5FAV",
      now: () => Date.parse("2026-08-24T00:00:00Z")
    });
    const bridge = new ProductBridge(
      supervisor,
      stubStore(),
      new ProductBindingStore(productBindingPath(dir)),
      undefined,
      undefined,
      null,
      broker
    );
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    supervisor.calls.length = 0;
    const outcome = await bridge.exportArtifact({ artifactId, suggestedName: "result.json" });
    assert.deepEqual(await readFile(destination), payload);
    assert.deepEqual(outcome, {
      state: "COMPLETED",
      taskId: `tsk_${"4".repeat(26)}`,
      runId: `run_${"4".repeat(26)}`,
      artifactId,
      manifestArtifactId: `art_sha256_${"c".repeat(64)}`,
      displayName: "result.json",
      sha256,
      byteSize: payload.byteLength,
      completedAt: "2026-08-24T00:00:00.000Z"
    });
    assert.deepEqual(
      supervisor.calls.map((call) => call.operationId),
      [
        "ArtifactService.v1.getArtifactDescriptor",
        "ArtifactService.v1.exportArtifact",
        "ArtifactService.v1.openArtifactStream",
        "artifactStream.sink",
        "artifactExport.complete"
      ]
    );
    assert.equal(JSON.stringify(outcome).includes(destination), false);
    assert.equal(JSON.stringify(supervisor.calls).includes(destination), false);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C3-10 ProductBridge records a durable failure receipt after accepted stream failure", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-export-fail-"));
  try {
    const payload = Buffer.from("verified result", "utf8");
    const sha256 = createHash("sha256").update(payload).digest("hex");
    const artifactId = `art_sha256_${sha256}`;
    const destination = join(dir, "result.json");
    const streamError = new BackendRuntimeError("stream failed", "ARTIFACT_STREAM_FAILED");
    const supervisor = stubSupervisor({ artifactPayload: payload, artifactStreamFailure: streamError });
    const broker = new ArtifactExportBroker({
      chooseDestination: async () => destination,
      tokenFactory: () => "edc_01ARZ3NDEKTSV4RRFFQ69G5FAW"
    });
    const bridge = new ProductBridge(
      supervisor,
      stubStore(),
      new ProductBindingStore(productBindingPath(dir)),
      undefined,
      undefined,
      null,
      broker
    );
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    supervisor.calls.length = 0;
    await assert.rejects(
      () => bridge.exportArtifact({ artifactId, suggestedName: "result.json" }),
      (error) => error.code === "ARTIFACT_STREAM_FAILED"
    );
    assert.equal(supervisor.calls.at(-1).operationId, "artifactExport.fail");
    assert.equal(supervisor.calls.at(-1).payload.reason_code, "ARTIFACT_STREAM_FAILED");
    await assert.rejects(() => readFile(destination), (error) => error.code === "ENOENT");
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

test("Product Backtest retry re-reads persisted Task truth and sends only owner-derived retry coordinates", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-product-bridge-retry-backtest-"));
  try {
    const supervisor = stubSupervisor();
    const bridge = new ProductBridge(supervisor, stubStore(), new ProductBindingStore(productBindingPath(dir)));
    await bridge.connectExistingProject({ projectId: REFS.projectId, projectContextRevisionId: REFS.projectContextRevisionId });
    supervisor.calls.length = 0;
    const failed = {
      read_model_version: "v3.task/1.0",
      task_id: "tsk_retry_backtest",
      project_id: REFS.projectId,
      operation_id: "ProductEntryService.v1.submitResearchBacktest",
      state: "FAILED",
      state_version: 7,
      run_id: "run_retry_backtest",
      result_id: null,
      attempt: { attempt_id: "att_retry_backtest_1", ordinal: 1, state: "FAILED", error_category: "TRANSIENT_IO" },
      outputs: {},
      created_at: "2026-08-25T00:00:00Z",
      updated_at: "2026-08-25T00:00:01Z",
      terminal_at: "2026-08-25T00:00:01Z"
    };
    const queued = {
      ...failed,
      state: "QUEUED",
      state_version: 8,
      attempt: { attempt_id: "att_retry_backtest_2", ordinal: 2, state: "QUEUED", error_category: null },
      updated_at: "2026-08-25T00:00:02Z",
      terminal_at: null
    };
    const originalRequest = supervisor.request.bind(supervisor);
    supervisor.request = async (operationId, payload, options) => {
      supervisor.calls.push({ operationId, payload, options });
      if (operationId === "TaskService.v1.getTask") return { read_model: failed };
      if (operationId === "TaskService.v1.retryTask") return { read_model: queued };
      return originalRequest(operationId, payload, options);
    };

    const retried = await bridge.retryResearchBacktest(failed.task_id);
    assert.equal(retried.taskId, failed.task_id);
    assert.equal(retried.attempt.ordinal, 2);
    assert.deepEqual(supervisor.calls.map((call) => call.operationId), [
      "TaskService.v1.getTask",
      "TaskService.v1.retryTask"
    ]);
    assert.deepEqual(supervisor.calls[1].payload, {
      task_id: failed.task_id,
      failed_attempt_id: failed.attempt.attempt_id,
      expected_state_version: failed.state_version
    });

    failed.attempt.error_category = "INVALID_ARGUMENT";
    supervisor.calls.length = 0;
    await assert.rejects(
      () => bridge.retryResearchBacktest(failed.task_id),
      (error) => error.code === "CONFLICT"
    );
    assert.deepEqual(supervisor.calls.map((call) => call.operationId), ["TaskService.v1.getTask"]);
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
