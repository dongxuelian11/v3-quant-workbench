import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { ProductBindingStore, parsePersistedBinding, productBindingPath } from "../../apps/desktop/src/main/productRuntime/bindingStore.ts";
import { adaptCapabilities, adaptTask, ProductAdapterError } from "../../apps/desktop/src/main/productRuntime/adapters.ts";

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

test("adapters fail closed on shape drift and admit honest capability reasons", () => {
  assert.throws(() => adaptCapabilities([{ code: "X", truth_state: "SORT_OF" }]), ProductAdapterError);
  assert.throws(() => adaptCapabilities("nope"), ProductAdapterError);
  assert.throws(() => adaptTask({ read_model: { read_model_version: "v3.task/9.9" } }), ProductAdapterError);
  const good = adaptCapabilities([
    { code: "TaskService", truth_state: "UNAVAILABLE", reason_code: "PRODUCT_OPERATION_SET_INCOMPLETE" },
    { code: "BacktestService", truth_state: "FORMAL" }
  ]);
  assert.equal(good[0].reason_code, "PRODUCT_OPERATION_SET_INCOMPLETE");
  assert.equal(good[1].truth_state, "FORMAL");
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
  const registrations = [...ipc.matchAll(/handle\((PRODUCT_RUNTIME_CHANNELS\.[A-Za-z]+)/g)].map((match) => match[1]);
  assert.equal(registrations.length, 13);
  assert.doesNotMatch(ipc, /operation_?[Ii]d/);
  assert.match(ipc, /trusted\(event\)/);
});

test("main process boots unbound on the LIVE path; fixture identity stays fixture-scoped", async () => {
  const main = await readFile(new URL("../../apps/desktop/src/main.ts", import.meta.url), "utf8");
  // The early bounded fixture project identity survives ONLY as the
  // development fixture's own truth, gated behind fixture mode; the LIVE
  // product path is strictly binding-driven.
  assert.match(main, /FIXTURE_PROJECT_ID = "prj_01ARZ3NDEKTSV4RRFFQ69G5FAV"/);
  assert.match(main, /const fixtureMode = AGENT_EVIDENCE_MODE === "DEVELOPMENT_INTEGRATION_FIXTURE"/);
  const liveBoot = main.slice(main.indexOf("function startBackendRuntime"));
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
const { deriveSurface } = await import("../../apps/desktop/src/renderer/productRuntimeStore.ts");

const baseState = { inflight: false, result: null, task: null, runSpecId: `btrs_sha256_${"d".repeat(64)}` };

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
