// Product Research acceptance smoke.
//
// Layer A remains the lower-layer Python facade smoke. Layer C/D below use the
// real typed Desktop ProductBridge, the real BackendSupervisor/framed backend,
// and the real renderer store. The only deterministic input is installed in a
// temporary provider-boundary module, at the external provider boundary;
// the production AkshareAShareEodAdapter still resolves, hashes, and persists
// the provider bytes inside the backend.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const python = process.env.V3_TEST_PYTHON ?? process.env.V3_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
const backendSource = resolve(root, "apps", "backend", "src");
const researchIntent = Object.freeze({ symbol: "000001", startDate: "20260106", endDate: "20260107" });

const pythonEnv = {
  ...process.env,
  PYTHONPATH: [root, backendSource, process.env.PYTHONPATH].filter(Boolean).join(delimiter)
};

function runLowerLayerSmoke(storageRoot) {
  const outcome = spawnSync(
    python,
    [resolve(root, "scripts", "product_research_smoke_python.py"), storageRoot],
    { cwd: root, encoding: "utf8", env: pythonEnv }
  );
  if (outcome.status !== 0) {
    throw new Error(`backend lower-layer smoke failed:\n${outcome.error?.message ?? outcome.stdout ?? ""}\n${outcome.stderr ?? ""}`);
  }
  const evidence = JSON.parse((outcome.stdout ?? "").trim());
  assert.equal(evidence.status, "PASS");
  assert.equal(evidence.truth_state, "DEMO");
  assert.equal(evidence.maturity, "PRODUCT_CONNECTED_CANDIDATE");
  return evidence;
}

function providerBoundarySource(mode, sourceRoot) {
  const rootLiteral = JSON.stringify(sourceRoot);
  const unavailable = mode === "unavailable";
  return `
import sys
from datetime import datetime, timezone

sys.path.insert(0, ${rootLiteral})

from v3_backend.adapters.market_data.akshare import AkshareAShareEodAdapter


class _Frame:
    def to_dict(self, *, orient):
        if orient != "records":
            raise RuntimeError("TEST_EXTERNAL_PROVIDER_BOUNDARY expected records")
        return [
            {"股票代码": "000001", "日期": "2026-01-06", "开盘": "10.00", "最高": "11.00", "最低": "9.50", "收盘": "10.50", "成交量": "1000", "成交额": "10500"},
            {"股票代码": "000001", "日期": "2026-01-07", "开盘": "10.50", "最高": "11.50", "最低": "10.00", "收盘": "11.00", "成交量": "1200", "成交额": "13200"},
        ]


class _Provider:
    __version__ = "1.18.84"

    def stock_zh_a_hist(self, **_request):
        return _Frame()


class _UnavailableProvider:
    __version__ = "1.18.84"


def _loader():
    return _UnavailableProvider() if ${unavailable ? "True" : "False"} else _Provider()


def _clock():
    return datetime(2026, 1, 8, 8, 0, tzinfo=timezone.utc)


_original_init = AkshareAShareEodAdapter.__init__


def _test_boundary_init(self, *, connector_version_id, loader=None, clock=None):
    _original_init(
        self,
        connector_version_id=connector_version_id,
        loader=loader or _loader,
        clock=clock or _clock,
    )


AkshareAShareEodAdapter.__init__ = _test_boundary_init
${unavailable ? `
def _unavailable_policy(self):
    raise ValueError("provider capability admission unavailable at TEST_EXTERNAL_PROVIDER_BOUNDARY")


AkshareAShareEodAdapter.field_capability_policy = _unavailable_policy
` : ""}
`;
}

async function makeProviderBoundaryWorkingDirectory(mode) {
  const directory = await mkdtemp(join(tmpdir(), `v3-product-research-provider-${mode}-`));
  const packageDirectory = join(directory, "v3_backend");
  const runtimeDirectory = join(packageDirectory, "runtime");
  await mkdir(runtimeDirectory, { recursive: true });
  await writeFile(
    join(packageDirectory, "__init__.py"),
    `__path__ = [${JSON.stringify(packageDirectory)}, ${JSON.stringify(join(backendSource, "v3_backend"))}]\n`,
    "utf8"
  );
  await writeFile(
    join(runtimeDirectory, "__init__.py"),
    `__path__ = [${JSON.stringify(runtimeDirectory)}, ${JSON.stringify(join(backendSource, "v3_backend", "runtime"))}]\n`,
    "utf8"
  );
  await writeFile(
    join(runtimeDirectory, "bootstrap.py"),
    `
import importlib.util
from v3_backend.adapters.market_data.akshare import AkshareAShareEodAdapter
${providerBoundarySource(mode, backendSource)}

_canonical_path = ${JSON.stringify(join(backendSource, "v3_backend", "runtime", "bootstrap.py"))}
_spec = importlib.util.spec_from_file_location("v3_backend.runtime._canonical_bootstrap", _canonical_path)
if _spec is None or _spec.loader is None:
    raise RuntimeError("canonical bootstrap spec could not be created")
_canonical = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_canonical)

if __name__ == "__main__":
    raise SystemExit(_canonical.main())
`,
    "utf8"
  );
  const probe = spawnSync(
    python,
    ["-c", "from v3_backend.adapters.market_data.akshare import AkshareAShareEodAdapter; print(AkshareAShareEodAdapter.__name__)"],
    { cwd: directory, encoding: "utf8", env: process.env }
  );
  if (probe.status !== 0) {
    throw new Error(`provider boundary bootstrap failed:\n${probe.stdout ?? ""}\n${probe.stderr ?? ""}`);
  }
  return directory;
}

async function makeProductRuntimeModules() {
  const { BackendSupervisor } = await import("../dist/apps/desktop/src/main/backendRuntime/supervisor.js");
  const { ProductBridge } = await import("../dist/apps/desktop/src/main/productRuntime/productBridge.js");
  const { WorkspaceStore } = await import("../dist/apps/desktop/src/main/runtimePersistence/workspaceStore.js");
  const { ProductBindingStore, productBindingPath } = await import("../dist/apps/desktop/src/main/productRuntime/bindingStore.js");
  return { BackendSupervisor, ProductBridge, WorkspaceStore, ProductBindingStore, productBindingPath };
}

function supervisorConfig(workingDirectory) {
  return {
    pythonExecutable: python,
    backendWorkingDirectory: workingDirectory,
    desktopVersion: "0.1.0-product-research-acceptance",
    handshakeTimeoutMs: 30_000,
    requestTimeoutMs: 120_000,
    crashLoopLimit: 3,
    crashLoopWindowMs: 60_000,
    autoReconnect: false
  };
}

function observeSupervisor(supervisor, label) {
  supervisor.on("diagnostic", (item) => {
    if (item.level === "ERROR") console.error(`[${label}] ${item.code}: ${item.message}`);
  });
}

async function makeBridge(modules, supervisor, userDataDirectory) {
  const workspace = new modules.WorkspaceStore(join(userDataDirectory, "workspace.json"));
  await workspace.load();
  const bindings = new modules.ProductBindingStore(modules.productBindingPath(userDataDirectory));
  await bindings.load();
  return new modules.ProductBridge(supervisor, workspace, bindings);
}

async function stopSupervisor(supervisor) {
  if (supervisor === null || supervisor.state === "STOPPED") return;
  try {
    await supervisor.shutdown(20_000);
  } catch {
    supervisor.stopNow();
  }
  if (supervisor.state !== "STOPPED") supervisor.stopNow();
}

async function removeTemp(path) {
  await rm(path, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 });
}

function resetRendererStore(store) {
  store.setState({
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
    task: null,
    result: null,
    artifactDescriptor: null,
    errorMessage: null
  });
}

async function runDesktopTypedAcceptance() {
  const realStorageRoot = await mkdtemp(join(tmpdir(), "v3-product-research-desktop-storage-"));
  const userDataDirectory = await mkdtemp(join(tmpdir(), "v3-product-research-desktop-userdata-"));
  const providerDirectory = await makeProviderBoundaryWorkingDirectory("pass");
  const modules = await makeProductRuntimeModules();
  const { useProductRuntime } = await import("../dist/apps/desktop/src/renderer/productRuntimeStore.js");
  let supervisorA = null;
  let supervisorB = null;
  try {
    process.env.V3_PRODUCT_STORAGE_ROOT = realStorageRoot;
    supervisorA = new modules.BackendSupervisor(supervisorConfig(providerDirectory));
    observeSupervisor(supervisorA, "desktop-A");
    const bridgeA = await makeBridge(modules, supervisorA, userDataDirectory);
    await supervisorA.start();

    const emptyProjects = await bridgeA.listProjects();
    assert.deepEqual(emptyProjects.projects, [], "PRIMARY must start from empty Product Runtime storage");
    const created = await bridgeA.createProject({ displayName: "Desktop typed research acceptance" });
    await bridgeA.connectExistingProject({
      projectId: created.projectId,
      projectContextRevisionId: created.projectContextRevisionId
    });

    globalThis.window = { v3ProductRuntime: bridgeA };
    resetRendererStore(useProductRuntime);
    await useProductRuntime.getState().refresh();
    await useProductRuntime.getState().submitResearch(researchIntent);
    const before = useProductRuntime.getState();
    assert.equal(before.surface, "RESULT_AVAILABLE", `typed research submit failed: ${before.errorMessage ?? "unknown"}`);
    assert.equal(before.errorMessage, null);
    assert.equal(before.lastResearch?.truthState, "DEMO");
    assert.equal(before.lastResearch?.maturity, "PRODUCT_CONNECTED_CANDIDATE");
    assert.deepEqual(before.lastResearch?.researchClassification, ["RESEARCH_ONLY", "APPROXIMATE"]);
    assert.deepEqual(before.lastResearch?.truthAdmission, { truth: "NOT_FORMAL", admission: "PRE_ALPHA" });
    assert.equal(before.task?.state, "SUCCEEDED");
    assert.equal(before.task?.operationId, "ProductEntryService.v1.submitResearch");
    assert.ok(before.task?.resultId);
    assert.ok(before.result?.resultArtifact?.artifactId);
    assert.ok(before.artifactDescriptor?.artifactId);
    assert.match(before.artifactDescriptor?.sha256 ?? "", /^[0-9a-f]{64}$/);
    assert.equal(before.artifactDescriptor?.artifactId, `art_sha256_${before.artifactDescriptor?.sha256}`);
    const lineageDescriptor = await bridgeA.getArtifactDescriptor(before.result.ledgerManifestArtifactId);
    assert.equal(before.task.outputs.LEDGER_MANIFEST, lineageDescriptor.artifactId);
    assert.equal(lineageDescriptor.role, "RESEARCH_PIPELINE_LINEAGE");
    assert.match(lineageDescriptor.sha256, /^[0-9a-f]{64}$/);
    assert.equal(lineageDescriptor.artifactId, `art_sha256_${lineageDescriptor.sha256}`);
    const artifactTicket = await bridgeA.openArtifactStream(before.artifactDescriptor.artifactId);
    assert.equal(artifactTicket.mode, "STREAM_TICKET");
    assert.equal(artifactTicket.artifactId, before.artifactDescriptor.artifactId);
    const lineageTicket = await bridgeA.openArtifactStream(lineageDescriptor.artifactId);
    assert.equal(lineageTicket.mode, "STREAM_TICKET");
    assert.equal(lineageTicket.artifactId, lineageDescriptor.artifactId);

    const idsBeforeRestart = {
      taskId: before.task.taskId,
      runId: before.task.runId,
      resultId: before.task.resultId,
      artifactId: before.artifactDescriptor.artifactId,
      artifactSha256: before.artifactDescriptor.sha256,
      lineageArtifactId: lineageDescriptor.artifactId,
      lineageSha256: lineageDescriptor.sha256
    };
    await stopSupervisor(supervisorA);
    supervisorA = null;

    supervisorB = new modules.BackendSupervisor(supervisorConfig(providerDirectory));
    observeSupervisor(supervisorB, "desktop-B");
    const bridgeB = await makeBridge(modules, supervisorB, userDataDirectory);
    await supervisorB.start();
    const persisted = await bridgeB.restorePersistedBinding();
    assert.equal(persisted?.projectId, created.projectId);
    assert.equal(persisted?.projectContextRevisionId, created.projectContextRevisionId);
    await bridgeB.connectExistingProject({
      projectId: created.projectId,
      projectContextRevisionId: created.projectContextRevisionId
    });

    const taskAfter = await bridgeB.getTask(idsBeforeRestart.taskId);
    const resultAfter = await bridgeB.getResult(idsBeforeRestart.resultId);
    const artifactAfter = await bridgeB.getArtifactDescriptor(idsBeforeRestart.artifactId);
    const lineageAfter = await bridgeB.getArtifactDescriptor(idsBeforeRestart.lineageArtifactId);
    assert.equal(taskAfter.taskId, idsBeforeRestart.taskId);
    assert.equal(taskAfter.runId, idsBeforeRestart.runId);
    assert.equal(taskAfter.resultId, idsBeforeRestart.resultId);
    assert.equal(resultAfter.resultId, idsBeforeRestart.resultId);
    assert.equal(resultAfter.resultArtifact?.artifactId, idsBeforeRestart.artifactId);
    assert.equal(resultAfter.ledgerManifestArtifactId, idsBeforeRestart.lineageArtifactId);
    assert.equal(artifactAfter.artifactId, idsBeforeRestart.artifactId);
    assert.equal(artifactAfter.sha256, idsBeforeRestart.artifactSha256);
    assert.equal(lineageAfter.artifactId, idsBeforeRestart.lineageArtifactId);
    assert.equal(lineageAfter.sha256, idsBeforeRestart.lineageSha256);

    globalThis.window = { v3ProductRuntime: bridgeB };
    await useProductRuntime.getState().refresh();
    const after = useProductRuntime.getState();
    assert.equal(after.surface, "RESULT_AVAILABLE");
    assert.equal(after.task?.taskId, idsBeforeRestart.taskId);
    assert.equal(after.task?.runId, idsBeforeRestart.runId);
    assert.equal(after.task?.resultId, idsBeforeRestart.resultId);
    assert.equal(after.result?.resultId, idsBeforeRestart.resultId);
    assert.equal(after.artifactDescriptor?.artifactId, idsBeforeRestart.artifactId);
    assert.equal(after.artifactDescriptor?.sha256, idsBeforeRestart.artifactSha256);

    return {
      projectId: created.projectId,
      projectContextRevisionId: created.projectContextRevisionId,
      before: idsBeforeRestart,
      after: {
        taskId: taskAfter.taskId,
        runId: taskAfter.runId,
        resultId: resultAfter.resultId,
        artifactId: artifactAfter.artifactId,
        artifactSha256: artifactAfter.sha256,
        lineageArtifactId: lineageAfter.artifactId,
        lineageSha256: lineageAfter.sha256
      },
      desktopCallerInput: researchIntent,
      forbiddenDesktopFields: ["observations", "bars", "returns", "weights", "predictions", "metrics", "nav", "result", "raw source bytes"],
      sourceKind: "TEST_EXTERNAL_PROVIDER_BOUNDARY",
      path: "ProductBridge.submitResearch -> BackendSupervisor.request -> framed v3_backend.runtime.bootstrap -> ProductEntryService.v1.submitResearch -> AkshareAShareEodAdapter -> ProductResearch -> CoreResearchPipeline -> ProductBridge readback -> renderer store",
      rendererStore: "PASS",
      restartReopen: "PASS"
    };
  } finally {
    await stopSupervisor(supervisorA).catch(() => undefined);
    await stopSupervisor(supervisorB).catch(() => undefined);
    await removeTemp(providerDirectory);
    await removeTemp(userDataDirectory);
    await removeTemp(realStorageRoot);
  }
}

async function runSourceUnavailableAcceptance() {
  const storageRoot = await mkdtemp(join(tmpdir(), "v3-product-research-unavailable-storage-"));
  const userDataDirectory = await mkdtemp(join(tmpdir(), "v3-product-research-unavailable-userdata-"));
  const providerDirectory = await makeProviderBoundaryWorkingDirectory("unavailable");
  const modules = await makeProductRuntimeModules();
  const { useProductRuntime } = await import("../dist/apps/desktop/src/renderer/productRuntimeStore.js");
  let supervisor = null;
  try {
    process.env.V3_PRODUCT_STORAGE_ROOT = storageRoot;
    supervisor = new modules.BackendSupervisor(supervisorConfig(providerDirectory));
    observeSupervisor(supervisor, "unavailable");
    const bridge = await makeBridge(modules, supervisor, userDataDirectory);
    await supervisor.start();
    const created = await bridge.createProject({ displayName: "Desktop typed source unavailable" });
    await bridge.connectExistingProject({
      projectId: created.projectId,
      projectContextRevisionId: created.projectContextRevisionId
    });
    globalThis.window = { v3ProductRuntime: bridge };
    resetRendererStore(useProductRuntime);
    await useProductRuntime.getState().refresh();
    await useProductRuntime.getState().submitResearch(researchIntent);
    const state = useProductRuntime.getState();
    assert.equal(state.surface, "ERROR");
    assert.equal(state.lastResearch, null);
    assert.equal(state.task, null);
    assert.equal(state.result, null);
    assert.equal(state.artifactDescriptor, null);
    assert.match(state.errorMessage ?? "", /AKShare|provider|unavailable|dependency/i);
    assert.equal(supervisor.state, "READY", "source failure must not fake success or tear down healthy transport");
    assert.deepEqual(await bridge.listTasks(), [], "source failure must not mint a fake canonical Task");
    return { status: "PASS", error: state.errorMessage, transport: supervisor.state, fakeSuccess: false };
  } finally {
    await stopSupervisor(supervisor).catch(() => undefined);
    await removeTemp(providerDirectory);
    await removeTemp(userDataDirectory);
    await removeTemp(storageRoot);
  }
}

const lowerStorageRoot = await mkdtemp(join(tmpdir(), "v3-product-research-lower-storage-"));
try {
  const lowerLayer = runLowerLayerSmoke(lowerStorageRoot);
  const desktop = await runDesktopTypedAcceptance();
  const unavailable = await runSourceUnavailableAcceptance();
  console.log(JSON.stringify({
    status: "PASS",
    truth_state: "DEMO",
    maturity: "PRODUCT_CONNECTED_CANDIDATE",
    research_classification: ["RESEARCH_ONLY", "APPROXIMATE"],
    source_kind: "TEST_EXTERNAL_PROVIDER_BOUNDARY",
    backend_lower_layer: lowerLayer,
    desktop_typed_acceptance: desktop,
    source_unavailable: unavailable
  }, null, 2));
  console.log("BACKEND_PRODUCT_RESEARCH_E2E = PASS");
  console.log("PRODUCTBRIDGE_REAL_BACKEND_INTEGRATION = PASS");
  console.log("RENDERER_STORE_REAL_TYPED_PATH = PASS");
  console.log("DESKTOP_TYPED_EXECUTABLE_RESEARCH_E2E = PASS_CANDIDATE");
  console.log("smoke:product-research PASS");
} finally {
  await removeTemp(lowerStorageRoot);
  delete process.env.V3_PRODUCT_STORAGE_ROOT;
  delete globalThis.window;
}
