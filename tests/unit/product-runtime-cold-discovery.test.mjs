import assert from "node:assert/strict";
import test from "node:test";

const {
  productClosureInitialRendererEvidence,
  projectInitialRendererEvidence,
  selectLatestResearchTask,
  useProductRuntime
} = await import("../../apps/desktop/src/renderer/productRuntimeStore.ts");

const PROJECT = "prj_cold_project";
const OTHER_PROJECT = "prj_other_project";
const BOUND_REFS = { projectId: PROJECT, projectContextRevisionId: "pcr_cold", sessionId: "ses_cold" };
const STATUS = {
  backendState: "READY",
  bindingState: "PROJECT_BOUND",
  boundProject: BOUND_REFS,
  capabilities: [],
  buildManifestId: "build_cold",
  buildIdentityState: "VERIFIED"
};
const IMPORT_CONTEXT = "pcr_imported";
const IMPORT_BOUND_REFS = { projectId: PROJECT, projectContextRevisionId: IMPORT_CONTEXT, sessionId: "ses_imported" };
const DATA_HOME = {
  readModelVersion: "v3.project-home/1.1",
  projectId: PROJECT,
  projectContextRevisionId: IMPORT_CONTEXT,
  maturity: "PRODUCT_CONNECTED",
  truth: "NOT_FORMAL",
  admission: "PRE_ALPHA",
  localImportState: "AVAILABLE",
  dataState: "AVAILABLE",
  dataUnavailableReason: "NONE",
  factorState: "EMPTY",
  factorUnavailableReason: "NO_FACTOR_STUDY",
  factor: null,
  data: {
    schemaVersion: "v3.product-data-read-model/1.0.0",
    projectId: PROJECT,
    projectContextRevisionId: IMPORT_CONTEXT,
    displayName: "bars.csv",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    sourceType: "LOCAL_USER_SUPPLIED",
    pitState: "PIT_UNPROVABLE",
    mediaType: "text/csv",
    rowCount: 2,
    instrumentCount: 1,
    dateCoverageStart: "2026-01-05",
    dateCoverageEnd: "2026-01-06",
    partitionCount: 1,
    universeRole: "USER_DEFINED_STATIC",
    qualityStatus: "PASS",
    validationProfileId: "svp_local_user_supplied_v1",
    capabilityReasons: {
      pit: "PIT_UNPROVABLE",
      revision: "PROVIDER_REVISION_UNKNOWN",
      calendar: "OBSERVED_LOCAL_ROWS_NOT_FORMAL_TRADING_CALENDAR",
      status: "SOURCE_COLUMN_ABSENT_OR_NULL_WHEN_NOT_PROVIDED"
    },
    volumeUnit: "SHARES",
    amountUnit: "CNY",
    adjustment: "UNADJUSTED",
    rawCaptureId: "raw_capture",
    rawContentHash: "a".repeat(64),
    snapshotId: "snp_sha256_" + "b".repeat(64),
    normalizedPayloadHash: "b".repeat(64),
    universeVersionId: "unv_imported",
    importedAt: "2026-08-24T00:00:00Z",
    rawArtifactId: "art_sha256_" + "a".repeat(64)
  }
};
const FACTOR_DOCUMENT_ID = `fdoc_sha256_${"d".repeat(64)}`;
const FACTOR_HOME = {
  ...DATA_HOME,
  factorState: "AVAILABLE",
  factorUnavailableReason: "NONE",
  factor: {
    schemaVersion: "v3.project-factor-summary/1.0.0",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    projectId: PROJECT,
    projectContextRevisionId: IMPORT_CONTEXT,
    snapshotId: DATA_HOME.data.snapshotId,
    universeVersionId: DATA_HOME.data.universeVersionId,
    formulaDocumentVersionId: FACTOR_DOCUMENT_ID
  }
};

function task({
  taskId,
  projectId = PROJECT,
  operationId = "ProductEntryService.v1.submitResearch",
  state = "SUCCEEDED",
  resultId = `res_${taskId}`,
  runId = `run_${taskId}`,
  terminalAt,
  updatedAt,
  createdAt = "2026-08-20T00:00:00Z",
  outputId = `art_${taskId}`
}) {
  return {
    readModelVersion: "v3.task/1.0",
    taskId,
    projectId,
    operationId,
    state,
    stateVersion: 3,
    runId,
    resultId,
    attempt: { attemptId: `att_${taskId}`, ordinal: 1, state, errorCategory: null },
    outputs: outputId === null ? {} : { BACKTEST_RUN_RESULT: outputId },
    createdAt,
    updatedAt: updatedAt ?? createdAt,
    terminalAt: terminalAt ?? updatedAt ?? createdAt
  };
}

function resultFor(item, descriptor) {
  return {
    readModelVersion: "v3.result/1.0",
    resultId: item.resultId,
    projectId: item.projectId,
    backtestRunId: item.runId,
    codeVersion: null,
    buildManifestId: "build_cold",
    state: "SUCCEEDED",
    ledgerManifestArtifactId: "art_ledger",
    reconciliationArtifactId: null,
    resultArtifact: descriptor
  };
}

function descriptorFor(item) {
  return {
    artifactId: item.outputs.BACKTEST_RUN_RESULT,
    sha256: `sha_${item.taskId}`,
    byteSize: 123,
    mediaType: "application/json",
    role: "BACKTEST_RUN_RESULT",
    createdAt: item.terminalAt
  };
}

function resetStore() {
  useProductRuntime.setState({
    surface: "BACKEND_STARTING",
    status: null,
    capabilities: [],
    boundProject: null,
    projects: null,
    runSpecs: null,
    entryBusy: false,
    runSpecId: "",
    inflight: false,
    lastSubmit: null,
    lastImport: null,
    lastResearch: null,
    dataHome: null,
    dataTask: null,
    localDataSelection: null,
    localDataImport: null,
    factorStudy: null,
    factorTask: null,
    researchDiscoveryState: "NOT_RUN",
    recoveredResearchTaskId: null,
    task: null,
    result: null,
    artifactDescriptor: null,
    errorMessage: null,
    projectScope: null,
    bindingGeneration: 0
  });
}

test("ACC-C2-10 chooser cancellation creates no Task and exposes no renderer path", async () => {
  resetStore();
  const calls = [];
  globalThis.window = {
    v3ProductRuntime: {
      async chooseLocalDataSource() { calls.push("choose"); return null; },
      async importLocalDataset() { calls.push("import"); throw new Error("cancel must not import"); },
      async getTask() { calls.push("task"); throw new Error("cancel must not create or poll a Task"); }
    }
  };
  try {
    useProductRuntime.getState().activateProjectScope(BOUND_REFS);
    await useProductRuntime.getState().importLocalData("SHARES");
    const state = useProductRuntime.getState();
    assert.deepEqual(calls, ["choose"]);
    assert.equal(state.localDataSelection, null);
    assert.equal(state.localDataImport, null);
    assert.equal(state.dataTask, null);
    assert.equal(state.entryBusy, false);
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

test("ACC-C2-09/10 successful import adopts the worker context before canonical Data readback and restart rediscovers it", async () => {
  resetStore();
  const calls = [];
  const selection = {
    displayName: "bars.csv",
    byteSize: 128,
    mediaType: "text/csv",
    capabilityToken: "capability-token-without-path"
  };
  const completedTask = task({
    taskId: "local-import",
    operationId: "ProductEntryService.v1.importLocalDataset",
    resultId: null,
    outputId: null
  });
  completedTask.outputs = {
    snapshot_id: DATA_HOME.data.snapshotId,
    universe_version_id: DATA_HOME.data.universeVersionId,
    project_context_revision_id: IMPORT_CONTEXT,
    raw_artifact_id: DATA_HOME.data.rawArtifactId
  };
  const bridge = {
    async chooseLocalDataSource() { calls.push("choose"); return selection; },
    async importLocalDataset(intent) {
      calls.push("import");
      assert.deepEqual(intent, {
        capabilityToken: selection.capabilityToken,
        volumeUnit: "SHARES",
        amountUnit: "CNY",
        timezone: "Asia/Shanghai",
        adjustment: "UNADJUSTED"
      });
      return {
        taskId: completedTask.taskId,
        runId: completedTask.runId,
        acceptedState: "QUEUED",
        maturity: "PRODUCT_CONNECTED",
        truth: "NOT_FORMAL",
        admission: "PRE_ALPHA",
        checkpointResume: "UNAVAILABLE",
        retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
        sourceArtifactId: DATA_HOME.data.rawArtifactId
      };
    },
    async getTask() { calls.push("task"); return completedTask; },
    async connectExistingProject(candidate) {
      calls.push("connect");
      assert.deepEqual(candidate, { projectId: PROJECT, projectContextRevisionId: IMPORT_CONTEXT });
    },
    async getBoundProject() { calls.push("bound"); return IMPORT_BOUND_REFS; },
    async getProjectHome() { calls.push("home"); return DATA_HOME; }
  };
  globalThis.window = { v3ProductRuntime: bridge };
  try {
    useProductRuntime.getState().activateProjectScope(BOUND_REFS);
    await useProductRuntime.getState().importLocalData("SHARES");
    const state = useProductRuntime.getState();
    assert.deepEqual(calls, ["choose", "import", "task", "connect", "bound", "home"]);
    assert.equal(state.projectScope.projectContextRevisionId, IMPORT_CONTEXT);
    assert.equal(state.dataHome.data.snapshotId, DATA_HOME.data.snapshotId);
    assert.equal("path" in state.localDataSelection, false);
    assert.equal("bytes" in state.localDataSelection, false);

    resetStore();
    globalThis.window = {
      v3ProductRuntime: {
        async getProductStatus() { return { ...STATUS, boundProject: IMPORT_BOUND_REFS }; },
        async listBacktestRunSpecs() { return { specs: [], hasMore: false, nextCursor: null }; },
        async listTasks() { return { tasks: [], hasMore: false, nextCursor: null }; },
        async getProjectHome() { return DATA_HOME; }
      }
    };
    await useProductRuntime.getState().refresh();
    assert.equal(useProductRuntime.getState().dataHome.data.snapshotId, DATA_HOME.data.snapshotId);
    assert.equal(useProductRuntime.getState().projectScope.projectContextRevisionId, IMPORT_CONTEXT);
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

test("Factor study follows accepted Task identity and publishes only canonical Project Home readback", async () => {
  resetStore();
  const calls = [];
  const completedTask = task({
    taskId: "factor-study",
    operationId: "ProductEntryService.v1.submitFactorStudy",
    resultId: null,
    outputId: null
  });
  completedTask.outputs = { formula_document_version_id: FACTOR_DOCUMENT_ID };
  const outcome = {
    taskId: completedTask.taskId,
    runId: completedTask.runId,
    acceptedState: "QUEUED",
    maturity: "PRODUCT_CONNECTED",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    checkpointResume: "UNAVAILABLE",
    retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
    formulaDocumentVersionId: FACTOR_DOCUMENT_ID,
    analysisOutputName: "MJ"
  };
  globalThis.window = {
    v3ProductRuntime: {
      async submitFactorStudy(intent) {
        calls.push("submit");
        assert.deepEqual(intent, { formulaSource: "MJ:CLOSE;", analysisOutputName: "MJ" });
        return outcome;
      },
      async getTask(taskId) { calls.push("task"); assert.equal(taskId, outcome.taskId); return completedTask; },
      async getProjectHome() { calls.push("home"); return FACTOR_HOME; }
    }
  };
  try {
    useProductRuntime.getState().activateProjectScope(IMPORT_BOUND_REFS);
    useProductRuntime.setState({ dataHome: DATA_HOME });
    await useProductRuntime.getState().submitFactorStudy({ formulaSource: "MJ:CLOSE;", analysisOutputName: "MJ" });
    const state = useProductRuntime.getState();
    assert.deepEqual(calls, ["submit", "task", "home"]);
    assert.equal(state.factorStudy.formulaDocumentVersionId, FACTOR_DOCUMENT_ID);
    assert.equal(state.factorTask.operationId, "ProductEntryService.v1.submitFactorStudy");
    assert.equal(state.dataHome.factor.formulaDocumentVersionId, FACTOR_DOCUMENT_ID);
    assert.equal(state.surface, "PROJECT_BOUND");
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

test("late Factor acceptance from Project A is dropped after project activation changes", async () => {
  resetStore();
  let resolveAcceptance;
  const pendingAcceptance = new Promise((resolve) => { resolveAcceptance = resolve; });
  globalThis.window = {
    v3ProductRuntime: {
      async submitFactorStudy() { return pendingAcceptance; },
      async getTask() { throw new Error("late acceptance must not be polled"); },
      async getProjectHome() { throw new Error("late acceptance must not read Project Home"); }
    }
  };
  try {
    useProductRuntime.getState().activateProjectScope(IMPORT_BOUND_REFS);
    useProductRuntime.setState({ dataHome: DATA_HOME });
    const run = useProductRuntime.getState().submitFactorStudy({ formulaSource: "MJ:CLOSE;", analysisOutputName: "MJ" });
    useProductRuntime.getState().activateProjectScope({
      projectId: OTHER_PROJECT,
      projectContextRevisionId: "pcr_other",
      sessionId: "ses_other"
    });
    resolveAcceptance({
      taskId: "tsk_late_factor",
      runId: "run_late_factor",
      acceptedState: "QUEUED",
      maturity: "PRODUCT_CONNECTED",
      truth: "NOT_FORMAL",
      admission: "PRE_ALPHA",
      checkpointResume: "UNAVAILABLE",
      retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
      formulaDocumentVersionId: FACTOR_DOCUMENT_ID,
      analysisOutputName: "MJ"
    });
    await run;
    const state = useProductRuntime.getState();
    assert.equal(state.projectScope.projectId, OTHER_PROJECT);
    assert.equal(state.factorStudy, null);
    assert.equal(state.factorTask, null);
    assert.equal(state.dataHome, null);
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

function bridgeFor(tasks, { missingResult = false, missingArtifact = false } = {}) {
  const byId = new Map(tasks.map((item) => [item.taskId, item]));
  const calls = { listTasks: [], getTask: [], getResult: [], getArtifactDescriptor: [] };
  return {
    calls,
    async getProductStatus() { return STATUS; },
    async listBacktestRunSpecs() { return { specs: [], hasMore: false, nextCursor: null }; },
    async listTasks(filter) { calls.listTasks.push(filter); return { tasks, hasMore: false, nextCursor: null }; },
    async getTask(taskId) { calls.getTask.push(taskId); return byId.get(taskId); },
    async getResult(resultId) {
      calls.getResult.push(resultId);
      if (missingResult) throw new Error("canonical result missing");
      const item = tasks.find((candidate) => candidate.resultId === resultId);
      const descriptor = descriptorFor(item);
      return resultFor(item, descriptor);
    },
    async getArtifactDescriptor(artifactId) {
      calls.getArtifactDescriptor.push(artifactId);
      if (missingArtifact) throw new Error("canonical artifact unavailable");
      const item = tasks.find((candidate) => candidate.outputs.BACKTEST_RUN_RESULT === artifactId);
      return descriptorFor(item);
    }
  };
}

test("closure evidence is an immutable projection of the real Zustand initial state", () => {
  const actualInitialState = useProductRuntime.getInitialState();
  assert.deepEqual(productClosureInitialRendererEvidence, {
    lastResearch: actualInitialState.lastResearch,
    task: actualInitialState.task,
    result: actualInitialState.result,
    artifactDescriptor: actualInitialState.artifactDescriptor
  });
  assert.deepEqual(productClosureInitialRendererEvidence, {
    lastResearch: null,
    task: null,
    result: null,
    artifactDescriptor: null
  });
  assert.equal(Object.isFrozen(productClosureInitialRendererEvidence), true);
});

test("smoke closure evidence keeps the real initial state after current store mutation", async () => {
  globalThis.window = { location: { search: "?v3-product-closure-smoke" } };
  try {
    const isolated = await import(new URL(
      "../../apps/desktop/src/renderer/productRuntimeStore.ts?closure-evidence-authority",
      import.meta.url,
    ));
    const actualInitialState = isolated.useProductRuntime.getInitialState();
    isolated.useProductRuntime.setState({
      lastResearch: { marker: "current-research" },
      task: { marker: "current-task" },
      result: { marker: "current-result" },
      artifactDescriptor: { marker: "current-artifact" }
    });
    const evidence = globalThis.window.v3ProductClosureEvidence();
    assert.deepEqual(evidence.initialRendererState, isolated.projectInitialRendererEvidence(actualInitialState));
    assert.notDeepEqual(evidence.initialRendererState, {
      lastResearch: isolated.useProductRuntime.getState().lastResearch,
      task: isolated.useProductRuntime.getState().task,
      result: isolated.useProductRuntime.getState().result,
      artifactDescriptor: isolated.useProductRuntime.getState().artifactDescriptor
    });
  } finally {
    delete globalThis.window;
  }
});

test("closure evidence projection propagates a synthetic non-empty initial state", () => {
  const syntheticInitialState = {
    lastResearch: { marker: "research" },
    task: { marker: "task" },
    result: { marker: "result" },
    artifactDescriptor: { marker: "artifact" }
  };
  const evidence = projectInitialRendererEvidence(syntheticInitialState);
  assert.deepEqual(evidence, syntheticInitialState);
  assert.notEqual(evidence.lastResearch, syntheticInitialState.lastResearch);
  assert.notEqual(evidence.task, syntheticInitialState.task);
  assert.notEqual(evidence.result, syntheticInitialState.result);
  assert.notEqual(evidence.artifactDescriptor, syntheticInitialState.artifactDescriptor);
  assert.equal(Object.isFrozen(evidence), true);
});

test("cold selector ignores unrelated, failed, and wrong-project tasks and sorts independently of list order", () => {
  const old = task({ taskId: "old", terminalAt: "2026-08-20T01:00:00Z" });
  const unrelated = task({ taskId: "new-backtest", operationId: "BacktestService.v1.submitBacktest", terminalAt: "2026-08-20T05:00:00Z" });
  const failed = task({ taskId: "failed", state: "FAILED", terminalAt: "2026-08-20T06:00:00Z" });
  const wrongProject = task({ taskId: "wrong-project", projectId: OTHER_PROJECT, terminalAt: "2026-08-20T07:00:00Z" });
  const latest = task({ taskId: "latest", terminalAt: "2026-08-20T03:00:00Z" });
  assert.equal(selectLatestResearchTask([latest, wrongProject, failed, unrelated, old], PROJECT).taskId, "latest");
});

test("fresh store keeps lastResearch null and recovers the latest canonical Task/Result/Artifact", async () => {
  const old = task({ taskId: "old", terminalAt: "2026-08-20T01:00:00Z" });
  const latest = task({ taskId: "latest", terminalAt: "2026-08-20T03:00:00Z" });
  const bridge = bridgeFor([latest, old]);
  resetStore();
  globalThis.window = { v3ProductRuntime: bridge };
  try {
    const cold = useProductRuntime.getState();
    assert.equal(cold.lastResearch, null);
    assert.equal(cold.task, null);
    assert.equal(cold.result, null);
    assert.equal(cold.artifactDescriptor, null);
    await cold.refresh();
    const state = useProductRuntime.getState();
    assert.deepEqual(bridge.calls.listTasks, [{ filter: { service: "ProductEntryService", state: "SUCCEEDED" } }]);
    assert.equal(state.lastResearch, null);
    assert.equal(state.researchDiscoveryState, "RECOVERED");
    assert.equal(state.recoveredResearchTaskId, "latest");
    assert.equal(state.task.taskId, "latest");
    assert.equal(state.result.resultId, "res_latest");
    assert.equal(state.artifactDescriptor.artifactId, "art_latest");
    assert.equal(state.surface, "RESULT_AVAILABLE");
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

test("new bound project with no Product Entry history remains normal and error-free", async () => {
  const bridge = bridgeFor([]);
  resetStore();
  globalThis.window = { v3ProductRuntime: bridge };
  try {
    await useProductRuntime.getState().refresh();
    const state = useProductRuntime.getState();
    assert.equal(state.researchDiscoveryState, "NO_HISTORY");
    assert.equal(state.task, null);
    assert.equal(state.result, null);
    assert.equal(state.artifactDescriptor, null);
    assert.equal(state.errorMessage, null);
    assert.notEqual(state.surface, "ERROR");
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

test("missing canonical historical Result or Artifact fails closed without stale display", async (t) => {
  for (const scenario of [
    { name: "result", missingResult: true },
    { name: "artifact", missingArtifact: true }
  ]) {
    await t.test(scenario.name, async () => {
      const item = task({ taskId: `broken-${scenario.name}`, terminalAt: "2026-08-20T03:00:00Z" });
      const bridge = bridgeFor([item], scenario);
      resetStore();
      globalThis.window = { v3ProductRuntime: bridge };
      try {
        await useProductRuntime.getState().refresh();
        const state = useProductRuntime.getState();
        assert.equal(state.researchDiscoveryState, "ERROR");
        assert.equal(state.surface, "ERROR");
        assert.equal(state.task, null);
        assert.equal(state.result, null);
        assert.equal(state.artifactDescriptor, null);
      } finally {
        delete globalThis.window;
        resetStore();
      }
    });
  }
});

test("stale binding clears previously visible canonical research state", async () => {
  const staleStatus = { ...STATUS, bindingState: "BINDING_STALE", boundProject: null };
  resetStore();
  useProductRuntime.setState({
    status: STATUS,
    task: task({ taskId: "stale-visible" }),
    result: resultFor(task({ taskId: "stale-visible" }), descriptorFor(task({ taskId: "stale-visible" }))),
    artifactDescriptor: descriptorFor(task({ taskId: "stale-visible" })),
    researchDiscoveryState: "RECOVERED",
    recoveredResearchTaskId: "stale-visible"
  });
  globalThis.window = {
    v3ProductRuntime: {
      async getProductStatus() { return staleStatus; },
      async listBacktestRunSpecs() { throw new Error("must not list run specs while unbound"); }
    }
  };
  try {
    await useProductRuntime.getState().refresh();
    const state = useProductRuntime.getState();
    assert.equal(state.task, null);
    assert.equal(state.result, null);
    assert.equal(state.artifactDescriptor, null);
    assert.equal(state.recoveredResearchTaskId, null);
    assert.equal(state.surface, "CAPABILITY_UNAVAILABLE");
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

test("ACC-C1-02 delayed Project A completion is dropped after atomic activation of Project B", async () => {
  resetStore();
  const warnings = [];
  const priorWarn = console.warn;
  console.warn = (line) => { warnings.push(JSON.parse(String(line))); };
  let resolveTask;
  let markTaskRequested;
  const taskRequested = new Promise((resolve) => { markTaskRequested = resolve; });
  const delayedTask = new Promise((resolve) => { resolveTask = resolve; });
  const projectATask = task({ taskId: "late-project-a", projectId: PROJECT });
  let downstreamReads = 0;
  globalThis.window = {
    v3ProductRuntime: {
      async submitResearch() {
        return {
          taskId: projectATask.taskId,
          runId: projectATask.runId,
          acceptedState: "QUEUED",
          idempotencyKey: "renderer-owned-by-main",
          eventCursor: 1,
          truthState: "DEMO",
          maturity: "PRODUCT_CONNECTED_CANDIDATE",
          researchProfileId: "RESEARCH_FREE_DATA_V1",
          strategyProfileId: "RESEARCH_CLOSE_RANK_TOP1_V1",
          researchClassification: ["RESEARCH_ONLY"],
          truthAdmission: { truth: "NOT_FORMAL", admission: "PRE_ALPHA" }
        };
      },
      async getTask() { markTaskRequested(); return delayedTask; },
      async getResult() { downstreamReads += 1; throw new Error("late A result must not be queried in B scope"); },
      async getArtifactDescriptor() { downstreamReads += 1; throw new Error("late A artifact must not be queried in B scope"); }
    }
  };
  try {
    useProductRuntime.getState().activateProjectScope(BOUND_REFS);
    const generationA = useProductRuntime.getState().projectScope.bindingGeneration;
    const pending = useProductRuntime.getState().submitResearch({ symbol: "000001", startDate: "20260101", endDate: "20260131" });
    await taskRequested;
    useProductRuntime.setState({
      runSpecs: { specs: [], hasMore: false, nextCursor: null },
      runSpecId: `btrs_sha256_${"a".repeat(64)}`,
      lastSubmit: { marker: "project-a-submit" },
      lastImport: { marker: "project-a-import" },
      researchDiscoveryState: "RECOVERED",
      recoveredResearchTaskId: "project-a-recovered",
      entryBusy: true,
      errorMessage: "project-a-error"
    });

    useProductRuntime.getState().activateProjectScope({ projectId: OTHER_PROJECT, projectContextRevisionId: "pcr_other", sessionId: "ses_other" });
    const switched = useProductRuntime.getState();
    assert.equal(switched.projectScope.projectId, OTHER_PROJECT);
    assert.equal(switched.projectScope.bindingGeneration, generationA + 1);
    assert.equal(switched.lastResearch, null);
    assert.equal(switched.lastSubmit, null);
    assert.equal(switched.lastImport, null);
    assert.equal(switched.runSpecs, null);
    assert.equal(switched.runSpecId, "");
    assert.equal(switched.researchDiscoveryState, "NOT_RUN");
    assert.equal(switched.recoveredResearchTaskId, null);
    assert.equal(switched.entryBusy, false);
    assert.equal(switched.task, null);
    assert.equal(switched.result, null);
    assert.equal(switched.artifactDescriptor, null);
    assert.equal(switched.inflight, false);
    assert.equal(switched.errorMessage, null);

    resolveTask(projectATask);
    await pending;
    const afterLateA = useProductRuntime.getState();
    assert.equal(afterLateA.projectScope.projectId, OTHER_PROJECT);
    assert.equal(afterLateA.lastResearch, null);
    assert.equal(afterLateA.task, null);
    assert.equal(afterLateA.result, null);
    assert.equal(afterLateA.artifactDescriptor, null);
    assert.equal(afterLateA.surface, "PROJECT_BOUND");
    assert.equal(afterLateA.errorMessage, null);
    assert.equal(downstreamReads, 0, "scope fence must stop the A read chain at the delayed Task boundary");
    assert.equal(warnings.length, 1);
    assert.equal(warnings[0].code, "LATE_SCOPE_RESULT_DROPPED");
    assert.equal(warnings[0].project_id, PROJECT);
    assert.equal(warnings[0].binding_generation, generationA);
    assert.match(warnings[0].request_id, /^renderer_request_[1-9][0-9]*$/);
  } finally {
    console.warn = priorWarn;
    delete globalThis.window;
    resetStore();
  }
});

test("explicit project pagination reports a bounded UI error instead of rejecting its click promise", async () => {
  resetStore();
  const current = {
    projects: [{ projectId: PROJECT, projectContextRevisionId: "pcr_cold", displayName: "项目 A", createdAt: "2026-08-23T00:00:00Z" }],
    hasMore: true,
    nextCursor: PROJECT
  };
  useProductRuntime.setState({ projects: current, surface: "BACKEND_READY" });
  globalThis.window = {
    v3ProductRuntime: {
      async listProjects() { throw new Error("project page unavailable"); }
    }
  };
  try {
    await useProductRuntime.getState().loadNextProjectPage();
    const state = useProductRuntime.getState();
    assert.equal(state.projects, current);
    assert.equal(state.surface, "ERROR");
    assert.match(state.errorMessage, /project page unavailable/);
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

test("late run-spec page is dropped after project activation changes", async () => {
  resetStore();
  const warnings = [];
  const priorWarn = console.warn;
  console.warn = (line) => { warnings.push(JSON.parse(String(line))); };
  let resolvePage;
  const delayedPage = new Promise((resolve) => { resolvePage = resolve; });
  globalThis.window = {
    v3ProductRuntime: {
      async listBacktestRunSpecs() { return delayedPage; }
    }
  };
  try {
    useProductRuntime.getState().activateProjectScope(BOUND_REFS);
    const current = { specs: [], hasMore: true, nextCursor: `art_sha256_${"a".repeat(64)}` };
    useProductRuntime.setState({ runSpecs: current });
    const pending = useProductRuntime.getState().loadNextRunSpecPage();
    useProductRuntime.getState().activateProjectScope({ projectId: OTHER_PROJECT, projectContextRevisionId: "pcr_other", sessionId: "ses_other" });
    resolvePage({
      specs: [{ artifactId: `art_sha256_${"b".repeat(64)}`, runSpecId: null, status: "UNAVAILABLE", diagnostic: "not executable" }],
      hasMore: false,
      nextCursor: null
    });
    await pending;
    const state = useProductRuntime.getState();
    assert.equal(state.projectScope.projectId, OTHER_PROJECT);
    assert.equal(state.runSpecs, null);
    assert.equal(state.errorMessage, null);
    assert.equal(warnings.length, 1);
    assert.equal(warnings[0].code, "LATE_SCOPE_RESULT_DROPPED");
    assert.equal(warnings[0].project_id, PROJECT);
  } finally {
    console.warn = priorWarn;
    delete globalThis.window;
    resetStore();
  }
});
