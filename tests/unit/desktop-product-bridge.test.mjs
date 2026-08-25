import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { ProductBindingStore, parsePersistedBinding, productBindingPath } from "../../apps/desktop/src/main/productRuntime/bindingStore.ts";
import { adaptCapabilities, adaptResearchSubmit, adaptTask, adaptTaskEvents, ProductAdapterError } from "../../apps/desktop/src/main/productRuntime/adapters.ts";
import {
  CreateProjectIntentStore,
  createProjectIntentPath,
  runCreateProjectIntent,
} from "../../apps/desktop/src/main/productRuntime/createProjectIntentStore.ts";

const REFS = { projectId: "prj_test01", projectContextRevisionId: "pcr_test01", sessionId: "11111111-2222-7333-8444-555555555555" };

test("binding store rejects invalid persisted shapes and accepts canonical refs", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-binding-"));
  try {
    const store = new ProductBindingStore(productBindingPath(dir));
    assert.equal(parsePersistedBinding(null), null);
    assert.equal(parsePersistedBinding({ schemaVersion: 99, projectId: "p", projectContextRevisionId: "c", sessionId: "s", savedAt: "x" }), null);
    assert.equal(parsePersistedBinding({ schemaVersion: 1, projectId: "../escape", projectContextRevisionId: "c", sessionId: "s", savedAt: "x" }), null);
    assert.equal(parsePersistedBinding({ schemaVersion: 1, projectId: "p", projectContextRevisionId: "c", sessionId: "s" }), null);
    assert.equal(await store.load(), null);
    await writeFile(productBindingPath(dir), "{not-json", "utf8");
    await assert.rejects(
      () => new ProductBindingStore(productBindingPath(dir)).load(),
      (error) => error.code === "BINDING_STORE_CORRUPT"
    );
    await assert.rejects(
      () => new ProductBindingStore(dir).load(),
      (error) => error.code === "BINDING_STORE_IO_FAILED",
      "only ENOENT may be interpreted as an unbound product"
    );
    const persisted = await store.persist(REFS);
    assert.equal(persisted.projectId, REFS.projectId);
    const reloaded = new ProductBindingStore(productBindingPath(dir));
    const loaded = await reloaded.load();
    assert.equal(loaded.projectId, REFS.projectId);
    assert.equal(loaded.sessionId, REFS.sessionId);
    await assert.rejects(() => store.persist({ projectId: "a".repeat(4000), projectContextRevisionId: "c", sessionId: "s" }), TypeError);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

function canonicalProjectOutcome(ordinal) {
  const suffix = String(ordinal).padStart(2, "0");
  return {
    project_id: `prj_${"A".repeat(24)}${suffix}`,
    project_context_revision_id: `pcr_${"B".repeat(24)}${suffix}`,
    display_name: "重试项目",
    created_at: "2026-08-18T00:00:00Z",
  };
}

function durableCreateBackend({ loseResponses = 0 } = {}) {
  const calls = [];
  const projects = new Map();
  return {
    calls,
    projects,
    async productEntryControl(frame) {
      calls.push(structuredClone(frame));
      let outcome = projects.get(frame.idempotency_key);
      if (outcome === undefined) {
        outcome = canonicalProjectOutcome(projects.size + 1);
        projects.set(frame.idempotency_key, outcome);
      }
      if (loseResponses > 0) {
        loseResponses -= 1;
        throw new Error("backend committed but transport response was lost");
      }
      return outcome;
    },
  };
}

function createIntentRunner(supervisor, dir) {
  const intents = new CreateProjectIntentStore(createProjectIntentPath(dir));
  return (request) => runCreateProjectIntent(
    intents,
    {
      displayName: request.displayName.trim(),
      notes: request.notes === undefined ? null : request.notes,
    },
    (idempotencyKey) => supervisor.productEntryControl({
      display_name: request.displayName.trim(),
      notes: request.notes === undefined ? null : request.notes,
      idempotency_key: idempotencyKey,
    }),
    (response) => ({
      projectId: response.project_id,
      projectContextRevisionId: response.project_context_revision_id,
    }),
  );
}

test("createProject response-loss retry reuses one durable idempotency key", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-create-intent-response-loss-"));
  try {
    const backend = durableCreateBackend({ loseResponses: 1 });
    const createProject = createIntentRunner(backend, dir);
    await assert.rejects(() => createProject({ displayName: "重试项目", notes: "same" }));
    const recovered = await createProject({ displayName: "重试项目", notes: "same" });
    assert.equal(backend.calls.length, 2);
    assert.equal(backend.calls[0].idempotency_key, backend.calls[1].idempotency_key);
    assert.equal(backend.projects.size, 1);
    assert.equal(recovered.projectId, [...backend.projects.values()][0].project_id);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("createProject restart retry reloads the unresolved key", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-create-intent-restart-"));
  try {
    const backend = durableCreateBackend({ loseResponses: 1 });
    const createProject1 = createIntentRunner(backend, dir);
    await assert.rejects(() => createProject1({ displayName: "重试项目", notes: "restart" }));
    const persisted = await new CreateProjectIntentStore(createProjectIntentPath(dir)).load();
    assert.equal(persisted.idempotencyKey, backend.calls[0].idempotency_key);
    const createProject2 = createIntentRunner(backend, dir);
    const recovered = await createProject2({ displayName: "重试项目", notes: "restart" });
    assert.equal(backend.calls[1].idempotency_key, backend.calls[0].idempotency_key);
    assert.equal(backend.projects.size, 1);
    assert.equal(recovered.projectId, [...backend.projects.values()][0].project_id);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("createProject different intent gets a new key while unknown outcomes stay pending", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-create-intent-different-"));
  try {
    const calls = [];
    const backend = {
      async productEntryControl(frame) {
        calls.push(structuredClone(frame));
        throw new Error("unknown transport outcome");
      },
    };
    const createProject = createIntentRunner(backend, dir);
    await assert.rejects(() => createProject({ displayName: "A", notes: "one" }));
    await assert.rejects(() => createProject({ displayName: "B", notes: "two" }));
    assert.notEqual(calls[0].idempotency_key, calls[1].idempotency_key);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("createProject success clears pending so a later same-name create gets a new key", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-create-intent-clear-"));
  try {
    const backend = durableCreateBackend();
    const createProject = createIntentRunner(backend, dir);
    const first = await createProject({ displayName: "重试项目", notes: "repeatable" });
    assert.equal(await new CreateProjectIntentStore(createProjectIntentPath(dir)).load(), null);
    const second = await createProject({ displayName: "重试项目", notes: "repeatable" });
    assert.notEqual(backend.calls[0].idempotency_key, backend.calls[1].idempotency_key);
    assert.notEqual(first.projectId, second.projectId);
    assert.equal(backend.projects.size, 2);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("definitive create validation rejection clears the key", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-create-intent-validation-"));
  try {
    const calls = [];
    const backend = {
      async productEntryControl(frame) {
        calls.push(structuredClone(frame));
        if (calls.length === 1) throw Object.assign(new Error("invalid"), { code: "INVALID_ARGUMENT" });
        return canonicalProjectOutcome(1);
      },
    };
    const createProject = createIntentRunner(backend, dir);
    await assert.rejects(() => createProject({ displayName: "重试项目" }));
    await createProject({ displayName: "重试项目" });
    assert.notEqual(calls[0].idempotency_key, calls[1].idempotency_key);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("adapters fail closed on shape drift and admit honest capability reasons", () => {
  assert.throws(() => adaptCapabilities([{ code: "X", truth_state: "SORT_OF" }]), ProductAdapterError);
  assert.throws(() => adaptCapabilities("nope"), ProductAdapterError);
  assert.throws(() => adaptTask({ read_model: { read_model_version: "v3.task/9.9" } }), ProductAdapterError);
  const good = adaptCapabilities([
    { code: "TaskService", truth_state: "UNAVAILABLE", reason_code: "PRODUCT_OPERATION_SET_INCOMPLETE" },
    { code: "BacktestService", truth_state: "UNAVAILABLE", reason_code: "FORMAL_EXECUTION_CONTRACT_NOT_CLOSED" }
  ]);
  assert.equal(good[0].reason_code, "PRODUCT_OPERATION_SET_INCOMPLETE");
  assert.equal(good[1].truth_state, "UNAVAILABLE");
  assert.equal(good[1].reason_code, "FORMAL_EXECUTION_CONTRACT_NOT_CLOSED");
});

test("Task progress adapter preserves exact task identity and rejects phase drift", () => {
  const response = {
    read_model: {
      high_watermark: 12,
      items: [{
        event_id: "tev_progress01",
        task_id: "tsk_progress01",
        project_sequence: 12,
        event_type: "TASK_PROGRESS",
        occurred_at: "2026-08-24T00:00:00Z",
        body: {
          phase: "RECONCILING",
          completed_units: 3,
          total_units: 4,
          work_unit: "RESULT_RECONCILIATION"
        }
      }]
    }
  };
  const adapted = adaptTaskEvents(response);
  assert.equal(adapted.items[0].taskId, "tsk_progress01");
  assert.deepEqual(adapted.items[0].progress, {
    phase: "RECONCILING",
    completedUnits: 3,
    totalUnits: 4,
    workUnit: "RESULT_RECONCILIATION"
  });
  const wrongPhase = structuredClone(response);
  wrongPhase.read_model.items[0].body.phase = "COMPLETE";
  assert.throws(() => adaptTaskEvents(wrongPhase), ProductAdapterError);
  const impossibleUnits = structuredClone(response);
  impossibleUnits.read_model.items[0].body.completed_units = 5;
  assert.throws(() => adaptTaskEvents(impossibleUnits), ProductAdapterError);
  const extraProgressField = structuredClone(response);
  extraProgressField.read_model.items[0].body.percent = 75;
  assert.throws(() => adaptTaskEvents(extraProgressField), ProductAdapterError);
});

test("renderer-facing bridge contract stays free of generic transport members", async () => {
  const source = await readFile(new URL("../../packages/contracts/src/index.ts", import.meta.url), "utf8");
  const iface = source.slice(source.indexOf("export interface V3ProductRuntimeBridge"));
  assert.doesNotMatch(iface, /request\s*\(/);
  assert.doesNotMatch(iface, /operationId/);
  assert.doesNotMatch(iface, /payload\s*:/);
  const preload = await readFile(new URL("../../apps/desktop/src/preload.ts", import.meta.url), "utf8");
  assert.match(preload, /exposeInMainWorld\("v3ProductRuntime", productRuntimeBridge\)/);
  const productSection = preload.slice(preload.indexOf("productRuntimeBridge"));
  assert.doesNotMatch(productSection, /operation_?[Ii]d/);
  const ipc = await readFile(new URL("../../apps/desktop/src/main/productRuntime/ipc.ts", import.meta.url), "utf8");
  assert.match(ipc, /productRuntime:submitExistingBacktestRunSpec/);
  // Every registration uses one of the frozen typed channels; no dynamic
  // channel or renderer-supplied operation id reaches ipcMain.handle.
  // Product Entry Data/Factor/Strategy/Backtest/Result paths remain individually typed. The two
  // unavailable-runtime registrations deliberately reuse status/capabilities.
  const registrations = [...ipc.matchAll(/handle\((PRODUCT_RUNTIME_CHANNELS\.[A-Za-z]+)/g)].map((match) => match[1]);
  assert.equal(registrations.length, 32);
  assert.equal(new Set(registrations).size, 30);
  assert.match(ipc, /PRODUCT_RUNTIME_CHANNELS\.previewResearchBacktest/);
  assert.doesNotMatch(ipc, /operation_?[Ii]d/);
  assert.match(ipc, /trusted\(event\)/);
  const panel = await readFile(new URL("../../apps/desktop/src/renderer/components/ProductRuntimePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /function VirtualizedRows/);
  assert.match(panel, /className="product-virtual-list"/);
});

test("Product Entry research adapter preserves explicit PRE_ALPHA truth and rejects numeric drift", () => {
  const accepted = adaptResearchSubmit({
    truth_state: "DEMO",
    read_model: {
      read_model_version: "v3.product-entry-research/1.0",
      task_id: "tsk_01ARZ3NDEKTSV4RRFFQ69G5FB",
      run_id: "run_01ARZ3NDEKTSV4RRFFQ69G5FB",
      accepted_state: "QUEUED",
      maturity: "PRODUCT_CONNECTED_CANDIDATE",
      research_profile_id: "RESEARCH_FREE_DATA_V1",
      strategy_profile_id: "RESEARCH_CLOSE_RANK_TOP1_V1",
      research_classification: ["RESEARCH_ONLY", "APPROXIMATE"],
      truth_admission: { truth: "NOT_FORMAL", admission: "PRE_ALPHA" },
      event_cursor: 3
    }
  }, "request-1");
  assert.equal(accepted.truthState, "DEMO");
  assert.equal(accepted.maturity, "PRODUCT_CONNECTED_CANDIDATE");
  assert.deepEqual(accepted.researchClassification, ["RESEARCH_ONLY", "APPROXIMATE"]);
  assert.throws(() => adaptResearchSubmit({
    truth_state: "DEMO",
    read_model: {
      read_model_version: "v3.product-entry-research/1.0",
      task_id: "tsk_01ARZ3NDEKTSV4RRFFQ69G5FB",
      run_id: "run_01ARZ3NDEKTSV4RRFFQ69G5FB",
      accepted_state: "QUEUED",
      maturity: "PRODUCT_CONNECTED_CANDIDATE",
      research_profile_id: "RESEARCH_FREE_DATA_V1",
      strategy_profile_id: "RESEARCH_CLOSE_RANK_TOP1_V1",
      research_classification: ["RESEARCH_ONLY", "APPROXIMATE"],
      truth_admission: { truth: "NOT_FORMAL", admission: "PRE_ALPHA" },
      observations: []
    }
  }, "request-2"), ProductAdapterError);
});

test("main process boots unbound on the LIVE path; fixture identity stays fixture-scoped", async () => {
  const main = await readFile(new URL("../../apps/desktop/src/main.ts", import.meta.url), "utf8");
  // The early bounded fixture project identity survives ONLY as the
  // development fixture's own truth, gated behind fixture mode; the LIVE
  // product path is strictly binding-driven.
  assert.match(main, /FIXTURE_PROJECT_ID = "prj_01ARZ3NDEKTSV4RRFFQ69G5FAV"/);
  assert.match(main, /const fixtureMode = AGENT_EVIDENCE_MODE === "DEVELOPMENT_INTEGRATION_FIXTURE"/);
  const liveBoot = main.slice(main.indexOf("function createBackendSupervisor"));
  assert.match(liveBoot, /projectContext === undefined \? \{\} : \{ projectContext \}/);
  assert.match(main, /productBindingPath\(app\.getPath\("userData"\)\)/);
  assert.match(main, /PRODUCT_SESSION_RESTORED/);
  assert.match(main, /PRODUCT_BINDING_STALE/);
  const storeSource = await readFile(new URL("../../apps/desktop/src/main/runtimePersistence/workspaceStore.ts", import.meta.url), "utf8");
  const pick = storeSource.slice(storeSource.indexOf("function pickUserFields"), storeSource.indexOf("function materialize"));
  assert.doesNotMatch(pick, /projectEventCursors/);
});

test("LIVE fixture boundary remains explicit opt-in with packaged hard-deny", async () => {
  const resolver = await readFile(new URL("../../apps/desktop/src/main/agentEvidenceRuntime.ts", import.meta.url), "utf8");
  assert.match(resolver, /v3_backend\.runtime\.bootstrap/);
  assert.match(resolver, /!isPackaged && explicitlyRequestedFixture/);
  const factory = await readFile(new URL("../../apps/desktop/src/main/backendRuntime/processFactory.ts", import.meta.url), "utf8");
  assert.match(factory, /V3_PRODUCT_STORAGE_ROOT/);
  assert.doesNotMatch(factory, /V3_BACKEND_TOKEN|SECRET|PASSWORD/i);
});


// ---- T4: renderer surface derivation honors bindingState over refs -------
const { deriveSurface, executableRunSpecSelection, useProductRuntime } = await import("../../apps/desktop/src/renderer/productRuntimeStore.ts");

const baseState = { inflight: false, result: null, task: null, runSpecId: `btrs_sha256_${"d".repeat(64)}` };

function statusForProductEntryTruth(truthState) {
  return {
    backendState: "READY",
    bindingState: "NO_CANONICAL_PROJECT_BOUND",
    boundProject: null,
    capabilities: truthState === null ? [] : [{ code: "ProductEntryService", truth_state: truthState }],
    buildManifestId: null,
    buildIdentityState: "UNAVAILABLE"
  };
}

test("S1-S4: Product Entry discovery admits only FORMAL capability", async (t) => {
  const scenarios = [
    { name: "S1 UNAVAILABLE keeps discovery unavailable", truthState: "UNAVAILABLE", expectedProjects: null, expectedCalls: 0 },
    { name: "S2 absent capability keeps discovery unavailable", truthState: null, expectedProjects: null, expectedCalls: 0 },
    { name: "S3 DEMO does not grant control authority", truthState: "DEMO", expectedProjects: null, expectedCalls: 0 },
    {
      name: "S4 FORMAL preserves normal project discovery",
      truthState: "FORMAL",
      expectedProjects: { projects: [{ projectId: "prj_formal", projectContextRevisionId: "pcr_formal", displayName: "正式项目", createdAt: "2026-08-20T00:00:00Z" }], hasMore: false, nextCursor: null },
      expectedCalls: 1
    }
  ];
  for (const scenario of scenarios) {
    await t.test(scenario.name, async () => {
      const status = statusForProductEntryTruth(scenario.truthState);
      let statusCalls = 0;
      let listProjectsCalls = 0;
      globalThis.window = {
        v3ProductRuntime: {
          getProductStatus: async () => { statusCalls += 1; return status; },
          listProjects: async () => { listProjectsCalls += 1; return scenario.expectedProjects; }
        }
      };
      useProductRuntime.setState({
        status: null,
        capabilities: [],
        boundProject: null,
        projects: null,
        runSpecs: null,
        surface: "BACKEND_STARTING",
        errorMessage: null,
        task: null,
        result: null,
        artifactDescriptor: null,
        lastSubmit: null,
        inflight: false
      });
      try {
        await useProductRuntime.getState().refresh();
        const state = useProductRuntime.getState();
        assert.equal(statusCalls, 1);
        assert.equal(listProjectsCalls, scenario.expectedCalls);
        assert.deepEqual(state.status, status);
        assert.deepEqual(state.capabilities, status.capabilities);
        assert.deepEqual(state.projects, scenario.expectedProjects);
        assert.equal(state.surface, "NO_CANONICAL_PROJECT_BOUND");
        assert.equal(state.errorMessage, null);
      } finally {
        delete globalThis.window;
      }
    });
  }
});

test("T4: BINDING_STALE wins over any defensively non-null boundProject", () => {
  const status = {
    backendState: "READY",
    bindingState: "BINDING_STALE",
    boundProject: { projectId: "prj_x", projectContextRevisionId: "pcr_x", sessionId: "ses_x" },
    capabilities: []
  };
  const surface = deriveSurface({ ...baseState, status, result: { resultId: "res_x" }, task: { taskId: "tsk_x" } });
  assert.notEqual(surface, "PROJECT_BOUND");
  assert.notEqual(surface, "CANONICAL_RUN_SPEC_REQUIRED");
  assert.notEqual(surface, "TASK_AVAILABLE");
  assert.notEqual(surface, "RESULT_AVAILABLE");
  assert.equal(surface, "CAPABILITY_UNAVAILABLE");
});

test("T4b: healthy states still derive exactly", () => {
  assert.equal(deriveSurface({ ...baseState, status: null }), "BACKEND_STARTING");
  assert.equal(deriveSurface({ ...baseState, status: { backendState: "READY", bindingState: "NO_CANONICAL_PROJECT_BOUND", boundProject: null, capabilities: [] } }), "NO_CANONICAL_PROJECT_BOUND");
  const bound = { backendState: "READY", bindingState: "PROJECT_BOUND", boundProject: { projectId: "p", projectContextRevisionId: "c", sessionId: "s" }, capabilities: [] };
  assert.equal(deriveSurface({ ...baseState, status: bound, runSpecId: "short" }), "CANONICAL_RUN_SPEC_REQUIRED");
  assert.equal(deriveSurface({ ...baseState, status: bound }), "PROJECT_BOUND");
});

test("T4c: a verified V1.1 Project Home is not downgraded by the legacy RunSpec selector", () => {
  const bound = { backendState: "READY", bindingState: "PROJECT_BOUND", boundProject: { projectId: "p", projectContextRevisionId: "c", sessionId: "s" }, capabilities: [] };
  assert.equal(deriveSurface({ ...baseState, status: bound, runSpecId: "", dataHome: { readModelVersion: "v3.project-home/1.1" } }), "PROJECT_BOUND");
});

test("UNAVAILABLE run-spec cannot be selected or submitted by the renderer store gate", async () => {
  const canonicalId = `btrs_sha256_${"e".repeat(64)}`;
  const unavailable = {
    specs: [{
      runSpecId: canonicalId,
      artifactId: `art_sha256_${"f".repeat(64)}`,
      contentSha256: null,
      projectContextRevisionId: null,
      engineVersion: null,
      createdAt: null,
      executionAdapterVersionId: null,
      status: "UNAVAILABLE",
      diagnostic: "source bytes unavailable"
    }],
    hasMore: false,
    nextCursor: null
  };
  assert.equal(executableRunSpecSelection(unavailable, canonicalId), null);
  assert.equal(executableRunSpecSelection({ ...unavailable, specs: [{ ...unavailable.specs[0], status: "EXECUTABLE" }] }, canonicalId), canonicalId);

  let submissions = 0;
  globalThis.window = {
    v3ProductRuntime: {
      submitExistingBacktestRunSpec: async () => {
        submissions += 1;
        throw new Error("UNAVAILABLE submission reached the bridge");
      }
    }
  };
  try {
    useProductRuntime.setState({ runSpecs: unavailable, runSpecId: "" });
    useProductRuntime.getState().setRunSpecId(canonicalId);
    assert.equal(useProductRuntime.getState().runSpecId, "");
    useProductRuntime.setState({ runSpecId: canonicalId });
    await useProductRuntime.getState().submitRunSpec();
    assert.equal(submissions, 0);
  } finally {
    delete globalThis.window;
    useProductRuntime.setState({ runSpecs: null, runSpecId: "" });
  }
});

test("UNAVAILABLE run-spec is disabled and diagnostic-visible in the product panel", async () => {
  const panel = await readFile(new URL("../../apps/desktop/src/renderer/components/ProductRuntimePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /disabled=\{entry\.status !== "EXECUTABLE"\}/);
  assert.match(panel, /UNAVAILABLE.*entry\.diagnostic/s);
});

// ---- T6/T7: preload structured error parser (literal production source) --
const preloadSource = await readFile(new URL("../../apps/desktop/src/preload.ts", import.meta.url), "utf8");
const parserMatch = preloadSource.match(/function parseProductBridgeErrorView[\s\S]*?\n}/);
assert.ok(parserMatch, "parseProductBridgeErrorView must exist in preload.ts");
// Re-materialize the literal production function as a strip-loadable .ts
// module so the tested body is byte-identical to the preload source.
const parserDir = await mkdtemp(join(tmpdir(), "v3-preload-parser-"));
const parserModulePath = join(parserDir, "parser.ts");
let parseProductBridgeErrorView;
try {
  await writeFile(parserModulePath, `export ${parserMatch[0]}\n`);
  ({ parseProductBridgeErrorView } = await import(pathToFileURL(parserModulePath).href));
} finally {
  await rm(parserDir, { recursive: true, force: true }).catch(() => undefined);
}

test("T6: valid structured error views survive with exact fields", () => {
  const view = parseProductBridgeErrorView(JSON.stringify({
    code: "CAPABILITY_UNAVAILABLE",
    message: "operation is unavailable",
    retryable: false,
    operationId: "TaskService.v1.resumeTask"
  }));
  assert.equal(view.code, "CAPABILITY_UNAVAILABLE");
  assert.equal(view.message, "operation is unavailable");
  assert.equal(view.retryable, false);
  assert.equal(view.operationId, "TaskService.v1.resumeTask");
  const stale = parseProductBridgeErrorView(JSON.stringify({ code: "BINDING_STALE", message: "reconnect required", retryable: false }));
  assert.equal(stale.code, "BINDING_STALE");
  assert.equal(stale.operationId, undefined);
  // Electron wraps ipc rejections with a channel prefix; the structured view
  // embedded in the wrapped message must still survive verbatim.
  const wrapped = parseProductBridgeErrorView(`Error invoking remote method 'productRuntime:getTask': Error: ${JSON.stringify({ code: "BINDING_STALE", message: "reconnect required", retryable: false })}`);
  assert.equal(wrapped.code, "BINDING_STALE");
  assert.equal(wrapped.message, "reconnect required");
  assert.equal(wrapped.retryable, false);
});

test("T7: malformed payloads degrade to the safe generic fallback", () => {
  for (const malformed of [
    "not json at all",
    "prefix with no JSON brace at all",
    JSON.stringify(["array"]),
    JSON.stringify({ code: "X" }),
    JSON.stringify({ code: "", message: "m", retryable: false }),
    JSON.stringify({ code: "X", message: 42, retryable: false }),
    JSON.stringify({ code: "X", message: "m", retryable: "yes" }),
    JSON.stringify({ code: "X", message: "m", retryable: false, operationId: 7 }),
    JSON.stringify({ code: "X", message: "m", retryable: false, extraArbitraryField: { deep: "object" } }),
    JSON.stringify("plain string"),
    JSON.stringify(null)
  ]) {
    const view = parseProductBridgeErrorView(malformed);
    assert.equal(view.code, "PRODUCT_BRIDGE_ERROR", `fallback expected for ${malformed}`);
    assert.equal(view.retryable, false);
    assert.equal(view.operationId, undefined);
    assert.equal(typeof view.message, "string");
  }
});

test("T6b: preload rejects exactly once, outside the parse guard, with the plain view", () => {
  const invokeSection = preloadSource.slice(preloadSource.indexOf("const invokeProduct"));
  assert.match(invokeSection, /throw parseProductBridgeErrorView\(message\);/);
  const body = invokeSection.slice(0, invokeSection.indexOf("};"));
  assert.doesNotMatch(body, /try\s*\{[\s\S]*?throw[\s\S]*?\}\s*catch/);
});
