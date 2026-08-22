import assert from "node:assert/strict";
import test from "node:test";

const { selectLatestResearchTask, useProductRuntime } = await import("../../apps/desktop/src/renderer/productRuntimeStore.ts");

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
    researchDiscoveryState: "NOT_RUN",
    recoveredResearchTaskId: null,
    task: null,
    result: null,
    artifactDescriptor: null,
    errorMessage: null
  });
}

function bridgeFor(tasks, { missingResult = false, missingArtifact = false } = {}) {
  const byId = new Map(tasks.map((item) => [item.taskId, item]));
  const calls = { listTasks: [], getTask: [], getResult: [], getArtifactDescriptor: [] };
  return {
    calls,
    async getProductStatus() { return STATUS; },
    async listBacktestRunSpecs() { return { specs: [], hasMore: false, nextAfterArtifactId: null }; },
    async listTasks(filter) { calls.listTasks.push(filter); return tasks; },
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
    assert.deepEqual(bridge.calls.listTasks, [{ service: "ProductEntryService", state: "SUCCEEDED" }]);
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