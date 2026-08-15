import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
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
