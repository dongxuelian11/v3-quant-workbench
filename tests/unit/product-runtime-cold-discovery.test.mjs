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
const BACKTEST_POLICY_COVERAGE = {
  schemaVersion: "v3.product-backtest-policy-coverage/1.0.0",
  truth: "NOT_FORMAL",
  admission: "PRE_ALPHA",
  coverageStart: "2026-01-01",
  coverageEnd: null,
  ruleProfileId: `atrp_sha256_${"1".repeat(64)}`,
  costPolicyId: `cost_sha256_${"2".repeat(64)}`,
  executionTimingProfileId: `timing_sha256_${"3".repeat(64)}`
};
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
  backtestPolicyCoverage: BACKTEST_POLICY_COVERAGE,
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
const ENTRY_FACTOR_VERSION_ID = `fver_sha256_${"e".repeat(64)}`;
const EXIT_FACTOR_VERSION_ID = `fver_sha256_${"f".repeat(64)}`;
const STRATEGY_SPEC_ID = `rstrat_sha256_${"1".repeat(64)}`;
const STRATEGY_VERSION_ID = `sgv_sha256_${"2".repeat(64)}`;
const PROFILE_REFS = {
  costPolicyVersionId: `cpv_sha256_${"3".repeat(64)}`,
  executionPolicyVersionId: `epv_sha256_${"4".repeat(64)}`,
  riskPolicySetVersionId: `rpsv_sha256_${"5".repeat(64)}`,
  assumptionProfileId: `assumption_sha256_${"6".repeat(64)}`
};
const STRATEGY_AUTHORING_PROFILE = {
  schemaVersion: "v3.product-strategy-authoring-profile/1.0.0",
  truth: "NOT_FORMAL",
  admission: "PRE_ALPHA",
  positionSizingOptions: ["SINGLE_ASSET_FULL_WEIGHT", "EQUAL_WEIGHT_ACTIVE_SIGNALS"],
  maxPositionsMin: 1,
  maxPositionsMax: 20,
  grossExposureMin: "0",
  grossExposureMax: "1",
  rebalance: "NEXT_OPEN_AFTER_SIGNAL",
  profileRefs: PROFILE_REFS,
  assumptionProfiles: [
    { mode: "RESEARCH_APPROXIMATE", assumptionProfileId: PROFILE_REFS.assumptionProfileId },
    { mode: "STRICT_FAIL_CLOSED", assumptionProfileId: `assumption_sha256_${"7".repeat(64)}` }
  ]
};
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
  },
  strategyAuthoringProfile: STRATEGY_AUTHORING_PROFILE,
  strategyState: "EMPTY",
  strategyUnavailableReason: "NO_RESEARCH_STRATEGY",
  strategy: null,
  backtestState: "EMPTY",
  backtestUnavailableReason: "NO_RESEARCH_STRATEGY",
  backtest: null
};
const STRATEGY_HOME = {
  ...FACTOR_HOME,
  strategyState: "AVAILABLE",
  strategyUnavailableReason: "NONE",
  strategy: {
    schemaVersion: "v3.project-strategy-summary/1.0.0",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    projectId: PROJECT,
    projectContextRevisionId: IMPORT_CONTEXT,
    snapshotId: DATA_HOME.data.snapshotId,
    universeVersionId: DATA_HOME.data.universeVersionId,
    researchStrategySpecId: STRATEGY_SPEC_ID,
    strategyVersionId: STRATEGY_VERSION_ID,
    entrySignalFactorVersionId: ENTRY_FACTOR_VERSION_ID,
    exitSignalFactorVersionId: EXIT_FACTOR_VERSION_ID,
    profileRefs: PROFILE_REFS,
    transitionCount: 2,
    decisionChainCount: 2
  },
  backtestState: "EMPTY",
  backtestUnavailableReason: "NO_VALID_BACKTEST",
  backtest: null
};
const BACKTEST_SUMMARY = {
  schemaVersion: "v3.project-backtest-summary/1.0.0",
  maturity: "PRODUCT_CONNECTED",
  truth: "NOT_FORMAL",
  admission: "PRE_ALPHA",
  projectId: PROJECT,
  projectContextRevisionId: IMPORT_CONTEXT,
  researchBacktestRequestId: `rbtr_sha256_${"7".repeat(64)}`,
  researchStrategySpecId: STRATEGY_SPEC_ID,
  snapshotId: DATA_HOME.data.snapshotId,
  universeVersionId: DATA_HOME.data.universeVersionId,
  runId: `run_${"8".repeat(32)}`,
  runSpecId: `btrs_sha256_${"9".repeat(64)}`,
  resultId: `res_${"a".repeat(32)}`,
  backtestResultId: `btr_sha256_${"b".repeat(64)}`,
  resultArtifactId: `art_sha256_${"c".repeat(64)}`,
  analyticsId: `ran_sha256_${"d".repeat(64)}`,
  analyticsArtifactId: `art_sha256_${"e".repeat(64)}`,
  resultLineageId: `rln_sha256_${"f".repeat(64)}`,
  lineageArtifactId: `art_sha256_${"1".repeat(64)}`,
  resultState: "VALID",
  engineVersion: "v3.ashare-backtest/0.3-research",
  orderCount: 2,
  fillCount: 2,
  diagnosticCount: 0,
  firstFillSessionDate: "2026-01-06",
  firstEffectiveSessionDate: "2026-01-06",
  assumptionMode: "RESEARCH_APPROXIMATE"
};
const BACKTEST_HOME = {
  ...STRATEGY_HOME,
  backtestState: "AVAILABLE",
  backtestUnavailableReason: "NONE",
  backtest: BACKTEST_SUMMARY
};
const RESULT_DETAILS = {
  schemaVersion: "v3.product-result-details/1.0.0",
  maturity: "PRODUCT_CONNECTED",
  truth: "NOT_FORMAL",
  admission: "PRE_ALPHA",
  resultState: "VALID",
  resultId: BACKTEST_SUMMARY.resultId,
  backtestResultId: BACKTEST_SUMMARY.backtestResultId,
  analyticsId: BACKTEST_SUMMARY.analyticsId,
  resultLineageId: BACKTEST_SUMMARY.resultLineageId,
  runId: BACKTEST_SUMMARY.runId,
  runSpecId: BACKTEST_SUMMARY.runSpecId,
  engineVersion: BACKTEST_SUMMARY.engineVersion,
  assumptionMode: BACKTEST_SUMMARY.assumptionMode,
  metrics: Object.fromEntries([
    "startNav", "endNav", "totalReturn", "annualizedReturn", "annualizedVolatility",
    "maxDrawdown", "sharpe", "sortino", "calmar"
  ].map((name) => [name, { status: "AVAILABLE", value: "1", reason: null }])),
  navSeries: [],
  drawdownSeries: [],
  exposureSeries: [],
  orders: { rowCount: 0, preview: [], truncated: false, sourceArtifactId: BACKTEST_SUMMARY.resultArtifactId },
  fills: { rowCount: 0, preview: [], truncated: false, sourceArtifactId: BACKTEST_SUMMARY.resultArtifactId },
  diagnostics: { rowCount: 0, preview: [], truncated: false, sourceArtifactId: BACKTEST_SUMMARY.resultArtifactId },
  holdings: { rowCount: 0, preview: [], truncated: false, sourceArtifactId: BACKTEST_SUMMARY.resultArtifactId },
  lineage: {
    rawCaptureId: DATA_HOME.data.rawCaptureId,
    rawArtifactId: DATA_HOME.data.rawArtifactId,
    snapshotId: DATA_HOME.data.snapshotId,
    universeVersionId: DATA_HOME.data.universeVersionId,
    entryFactorVersionId: ENTRY_FACTOR_VERSION_ID,
    exitFactorVersionId: EXIT_FACTOR_VERSION_ID,
    researchStrategySpecId: STRATEGY_SPEC_ID,
    strategyVersionId: STRATEGY_VERSION_ID,
    riskPolicySetVersionId: PROFILE_REFS.riskPolicySetVersionId,
    runSpecArtifactId: BACKTEST_SUMMARY.runSpecId,
    resultArtifactId: BACKTEST_SUMMARY.resultArtifactId,
    analyticsArtifactId: BACKTEST_SUMMARY.analyticsArtifactId,
    lineageArtifactId: BACKTEST_SUMMARY.lineageArtifactId
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
    strategySubmission: null,
    strategyTask: null,
    backtestSubmission: null,
    backtestTask: null,
    latestProductResult: null,
    latestProductResultError: null,
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

test("ACC-C3-13 Strategy and Backtest adopt only exact terminal Tasks and canonical Home/Result readback", async () => {
  resetStore();
  const calls = [];
  const strategyTask = task({
    taskId: "strategy-authoring",
    operationId: "ProductEntryService.v1.publishResearchStrategy",
    resultId: null,
    outputId: null
  });
  const backtestTask = task({
    taskId: "research-backtest",
    operationId: "ProductEntryService.v1.submitResearchBacktest",
    resultId: BACKTEST_SUMMARY.resultId,
    runId: BACKTEST_SUMMARY.runId,
    outputId: BACKTEST_SUMMARY.resultArtifactId
  });
  const strategyOutcome = {
    taskId: strategyTask.taskId,
    runId: strategyTask.runId,
    acceptedState: "QUEUED",
    maturity: "PRODUCT_CONNECTED",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    checkpointResume: "UNAVAILABLE",
    retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
    researchStrategySpecId: STRATEGY_SPEC_ID
  };
  const backtestOutcome = {
    taskId: backtestTask.taskId,
    runId: backtestTask.runId,
    acceptedState: "QUEUED",
    maturity: "PRODUCT_CONNECTED",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    checkpointResume: "UNAVAILABLE",
    retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
    researchBacktestRequestId: BACKTEST_SUMMARY.researchBacktestRequestId
  };
  const strategyIntent = {
    entrySignalFactorVersionId: ENTRY_FACTOR_VERSION_ID,
    exitSignalFactorVersionId: EXIT_FACTOR_VERSION_ID,
    positionSizing: "SINGLE_ASSET_FULL_WEIGHT",
    maxPositions: 1,
    grossExposure: "1",
    initialCash: "1000000",
    assumptionProfileId: PROFILE_REFS.assumptionProfileId
  };
  const strategyPreview = {
    schemaVersion: "v3.product-strategy-preview/1.0.0",
    maturity: "PRODUCT_CONNECTED",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    projectId: PROJECT,
    projectContextRevisionId: IMPORT_CONTEXT,
    snapshotId: DATA_HOME.data.snapshotId,
    universeVersionId: DATA_HOME.data.universeVersionId,
    researchStrategySpecId: STRATEGY_SPEC_ID,
    strategyDefinitionVersionId: `sdv_sha256_${"9".repeat(64)}`,
    entrySignalFactorVersionId: ENTRY_FACTOR_VERSION_ID,
    exitSignalFactorVersionId: EXIT_FACTOR_VERSION_ID,
    profileRefs: PROFILE_REFS,
    assumptionMode: "RESEARCH_APPROXIMATE",
    transitionCount: 2,
    plannedDecisionChainCount: 2,
    sideEffects: "NONE"
  };
  let home = FACTOR_HOME;
  globalThis.window = {
    v3ProductRuntime: {
      async previewResearchStrategy(intent) {
        calls.push("preview-strategy");
        assert.deepEqual(intent, strategyIntent);
        return strategyPreview;
      },
      async publishResearchStrategy(intent) {
        calls.push("publish-strategy");
        assert.deepEqual(intent, strategyIntent);
        return strategyOutcome;
      },
      async submitResearchBacktest(intent) {
        calls.push("submit-backtest");
        assert.deepEqual(intent, {
          sessionStart: "2026-01-05",
          sessionEnd: "2026-01-06",
          slippageBps: "5",
          dailyVolumeParticipationRate: "0.1"
        });
        return backtestOutcome;
      },
      async previewResearchBacktest(intent) {
        calls.push("preview-backtest");
        return {
          schemaVersion: "v3.product-backtest-preflight/1.0.0",
          maturity: "PRODUCT_CONNECTED",
          truth: "NOT_FORMAL",
          admission: "PRE_ALPHA",
          status: "PASS",
          projectId: PROJECT,
          projectContextRevisionId: IMPORT_CONTEXT,
          researchStrategySpecId: STRATEGY_SPEC_ID,
          researchBacktestRequestId: BACKTEST_SUMMARY.researchBacktestRequestId,
          snapshotId: DATA_HOME.data.snapshotId,
          universeVersionId: DATA_HOME.data.universeVersionId,
          sessionStart: intent.sessionStart,
          sessionEnd: intent.sessionEnd,
          slippageBps: intent.slippageBps,
          dailyVolumeParticipationRate: intent.dailyVolumeParticipationRate,
          commissionRate: "0.0003",
          minimumCommissionCny: "5",
          stampDutySellRate: "0.0005",
          assumptionMode: "RESEARCH_APPROXIMATE",
          policyRefs: {
            ruleProfileId: `atrp_sha256_${"4".repeat(64)}`,
            costPolicyId: PROFILE_REFS.costPolicyVersionId,
            executionTimingProfileId: PROFILE_REFS.executionPolicyVersionId,
            riskPolicySetVersionId: PROFILE_REFS.riskPolicySetVersionId
          },
          resourceEstimate: {
            resourceClass: "PRODUCT_BACKTEST_CPU",
            cpuSlots: 1,
            memoryLimitBytes: 1073741824,
            scratchLimitBytes: 1073741824,
            checkpointResume: "UNAVAILABLE"
          },
          sideEffects: "NONE"
        };
      },
      async getTask(taskId) {
        calls.push(`task:${taskId}`);
        return taskId === strategyTask.taskId ? strategyTask : backtestTask;
      },
      async getTaskEvents() {
        calls.push("events");
        return {
          highWatermark: 40,
          items: [{
            eventId: "progress-1",
            taskId: backtestTask.taskId,
            projectSequence: 39,
            eventType: "TASK_PROGRESS",
            occurredAt: "2026-08-24T00:00:00Z",
            resultId: null,
            progress: {
              phase: "RECONCILING",
              completedUnits: 3,
              totalUnits: 4,
              workUnit: "RESULT_RECONCILIATION"
            }
          }]
        };
      },
      async getProjectHome() {
        calls.push("home");
        return home;
      },
      async getLatestProductResultDetails() {
        calls.push("result-details");
        return RESULT_DETAILS;
      }
    }
  };
  try {
    useProductRuntime.getState().activateProjectScope(IMPORT_BOUND_REFS);
    useProductRuntime.setState({ dataHome: FACTOR_HOME });
    await useProductRuntime.getState().publishResearchStrategy(strategyIntent);
    assert.equal(useProductRuntime.getState().errorMessage, "STRATEGY_PREVIEW_REQUIRED");
    assert.deepEqual(calls, []);
    await useProductRuntime.getState().previewResearchStrategy(strategyIntent);
    assert.equal(useProductRuntime.getState().strategyPreview.sideEffects, "NONE");
    await useProductRuntime.getState().publishResearchStrategy({ ...strategyIntent, maxPositions: 2 });
    assert.equal(useProductRuntime.getState().errorMessage, "STRATEGY_PREVIEW_REQUIRED");
    assert.deepEqual(calls, ["preview-strategy"]);
    home = STRATEGY_HOME;
    await useProductRuntime.getState().publishResearchStrategy(strategyIntent);
    assert.equal(useProductRuntime.getState().strategyTask.taskId, strategyTask.taskId);
    assert.equal(useProductRuntime.getState().dataHome.strategy.researchStrategySpecId, STRATEGY_SPEC_ID);
    assert.equal(useProductRuntime.getState().backtestPreview, null);

    home = BACKTEST_HOME;
    const backtestIntent = {
      sessionStart: "2026-01-05",
      sessionEnd: "2026-01-06",
      slippageBps: "5",
      dailyVolumeParticipationRate: "0.1"
    };
    await useProductRuntime.getState().previewResearchBacktest(backtestIntent);
    assert.equal(useProductRuntime.getState().backtestPreview.sideEffects, "NONE");
    assert.deepEqual(useProductRuntime.getState().backtestPreviewIntent, backtestIntent);
    await useProductRuntime.getState().submitResearchBacktest(backtestIntent);
    const state = useProductRuntime.getState();
    assert.deepEqual(calls, [
      "preview-strategy", "publish-strategy", `task:${strategyTask.taskId}`, "home",
      "preview-backtest", "submit-backtest", `task:${backtestTask.taskId}`, "events", "home", "result-details"
    ]);
    assert.equal(state.backtestTask.taskId, backtestTask.taskId);
    assert.equal(state.dataHome.backtest.resultState, "VALID");
    assert.equal(state.latestProductResult.resultId, BACKTEST_SUMMARY.resultId);
    assert.deepEqual(state.backtestProgress, {
      phase: "RECONCILING",
      completedUnits: 3,
      totalUnits: 4,
      workUnit: "RESULT_RECONCILIATION"
    });
    assert.equal(state.surface, "PROJECT_BOUND");
    useProductRuntime.getState().activateProjectScope({
      projectId: OTHER_PROJECT,
      projectContextRevisionId: "pcr_other",
      sessionId: "ses_other"
    });
    assert.equal(useProductRuntime.getState().backtestPreview, null);
    assert.equal(useProductRuntime.getState().backtestPreviewIntent, null);
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

test("Task feedback retries only a persisted retry-admitted Product Backtest and rebuilds VALID result truth", async () => {
  resetStore();
  const calls = [];
  const failed = task({
    taskId: "research-backtest-retry",
    operationId: "ProductEntryService.v1.submitResearchBacktest",
    state: "FAILED",
    resultId: null,
    runId: BACKTEST_SUMMARY.runId,
    outputId: null
  });
  failed.stateVersion = 7;
  failed.attempt = { attemptId: "att_retry_1", ordinal: 1, state: "FAILED", errorCategory: "TRANSIENT_IO" };
  const queued = {
    ...failed,
    state: "QUEUED",
    stateVersion: 8,
    terminalAt: null,
    attempt: { attemptId: "att_retry_2", ordinal: 2, state: "QUEUED", errorCategory: null }
  };
  const succeeded = {
    ...queued,
    state: "SUCCEEDED",
    stateVersion: 11,
    resultId: BACKTEST_SUMMARY.resultId,
    terminalAt: "2026-08-25T00:00:03Z",
    attempt: { ...queued.attempt, state: "SUCCEEDED" }
  };
  globalThis.window = {
    v3ProductRuntime: {
      async retryResearchBacktest(taskId) {
        calls.push("retry");
        assert.equal(taskId, failed.taskId);
        return queued;
      },
      async getTask(taskId) { calls.push("task"); assert.equal(taskId, failed.taskId); return succeeded; },
      async getTaskEvents() { calls.push("events"); return { highWatermark: 50, items: [] }; },
      async getProjectHome() { calls.push("home"); return BACKTEST_HOME; },
      async getLatestProductResultDetails() { calls.push("details"); return RESULT_DETAILS; }
    }
  };
  try {
    useProductRuntime.getState().activateProjectScope(IMPORT_BOUND_REFS);
    useProductRuntime.setState({ dataHome: STRATEGY_HOME, backtestTask: failed, surface: "ERROR", errorMessage: "TRANSIENT_IO" });
    await useProductRuntime.getState().retryResearchBacktest();
    const state = useProductRuntime.getState();
    assert.deepEqual(calls, ["retry", "events", "task", "events", "home", "details"]);
    assert.equal(state.backtestTask.attempt.ordinal, 2);
    assert.equal(state.backtestTask.state, "SUCCEEDED");
    assert.equal(state.dataHome.backtest.resultState, "VALID");
    assert.equal(state.latestProductResult.resultId, BACKTEST_SUMMARY.resultId);
    assert.equal(state.errorMessage, null);

    calls.length = 0;
    useProductRuntime.setState({
      backtestTask: { ...failed, attempt: { ...failed.attempt, errorCategory: "INVALID_ARGUMENT" } },
      errorMessage: "INVALID_ARGUMENT"
    });
    await useProductRuntime.getState().retryResearchBacktest();
    assert.deepEqual(calls, []);
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

test("ACC-C3-13 cold restart reconstructs the latest VALID Product Result without prior renderer cache", async () => {
  resetStore();
  const calls = [];
  useProductRuntime.setState({ latestProductResult: { ...RESULT_DETAILS, resultId: "stale-renderer-cache" } });
  globalThis.window = {
    v3ProductRuntime: {
      async getProductStatus() { calls.push("status"); return { ...STATUS, boundProject: IMPORT_BOUND_REFS }; },
      async listBacktestRunSpecs() { calls.push("run-specs"); return { specs: [], hasMore: false, nextCursor: null }; },
      async listTasks() { calls.push("tasks"); return { tasks: [], hasMore: false, nextCursor: null }; },
      async getProjectHome() { calls.push("home"); return BACKTEST_HOME; },
      async getLatestProductResultDetails() { calls.push("result-details"); return RESULT_DETAILS; }
    }
  };
  try {
    await useProductRuntime.getState().refresh();
    const state = useProductRuntime.getState();
    assert.equal(state.latestProductResult.resultId, BACKTEST_SUMMARY.resultId);
    assert.notEqual(state.latestProductResult.resultId, "stale-renderer-cache");
    assert.deepEqual(calls, ["status", "run-specs", "home", "result-details", "tasks"]);
  } finally {
    delete globalThis.window;
    resetStore();
  }
});

test("ACC-C3-13 late Product Result from Project A is dropped after Project B activation", async () => {
  resetStore();
  let resolveDetails;
  const delayedDetails = new Promise((resolve) => { resolveDetails = resolve; });
  globalThis.window = {
    v3ProductRuntime: {
      async getLatestProductResultDetails() { return delayedDetails; }
    }
  };
  try {
    useProductRuntime.getState().activateProjectScope(IMPORT_BOUND_REFS);
    useProductRuntime.setState({ dataHome: BACKTEST_HOME });
    const pending = useProductRuntime.getState().loadLatestProductResult();
    useProductRuntime.getState().activateProjectScope({
      projectId: OTHER_PROJECT,
      projectContextRevisionId: "pcr_other",
      sessionId: "ses_other"
    });
    resolveDetails(RESULT_DETAILS);
    await pending;
    const state = useProductRuntime.getState();
    assert.equal(state.projectScope.projectId, OTHER_PROJECT);
    assert.equal(state.latestProductResult, null);
    assert.equal(state.latestProductResultError, null);
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
