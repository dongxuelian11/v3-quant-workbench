import { app, BrowserWindow, dialog, ipcMain, Menu, type IpcMainInvokeEvent } from "electron";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { mkdir, writeFile } from "node:fs/promises";
import {
  type CommandReceipt,
  type DesktopCommandEnvelope,
  type PersistedWorkspace,
  type ProductStatusView,
  type ProjectContextView,
  type ProjectCreatedView
} from "../../../packages/contracts/src/index";
import {
  BackendRuntimeEventRelay,
  BackendRuntimeLifecycle,
  BackendSupervisor,
  resolveBackendRuntime,
  registerBackendRuntimeIpc
} from "./main/backendRuntime/index";
import type { BackendRuntimeResolution } from "./main/backendRuntime/runtimeResolver";
import { WorkspaceStore, WorkspaceStoreError } from "./main/runtimePersistence/workspaceStore";
import { resolveAgentEvidenceRuntime } from "./main/agentEvidenceRuntime";
import { runProductClosureSmoke as runProductClosureSmokeFlow, type ProductClosureSmokePhase } from "./main/productClosureSmoke";
import {
  ProductBindingStore,
  ProductBridge,
  LocalDataSourceBroker,
  productBindingPath,
  registerProductRuntimeIpc,
  registerUnavailableProductRuntimeIpc
} from "./main/productRuntime/index";

let mainWindow: BrowserWindow | null = null;
let productClosureRendererLoad: Promise<void> | null = null;
let store: WorkspaceStore;
let storePath = "";
let backendSupervisor: BackendSupervisor | null = null;
let backendRelay: BackendRuntimeEventRelay | null = null;
let backendRuntimeLifecycle: BackendRuntimeLifecycle | null = null;
let backendRuntimeResolution: BackendRuntimeResolution | null = null;
let backendStartPromise: Promise<void> | null = null;
let quitting = false;
let shutdownComplete = false;

const GRACEFUL_SHUTDOWN_DEADLINE_MS = 10_000;
const PACKAGED_RUNTIME_SMOKE = process.argv.includes("--v3-packaged-smoke");
const PACKAGED_RUNTIME_SMOKE_USER_DATA = process.env.V3_PACKAGED_SMOKE_USER_DATA;
const PACKAGED_RUNTIME_SMOKE_OUTPUT = process.env.V3_PACKAGED_SMOKE_OUTPUT;
const PRODUCT_CLOSURE_SMOKE = process.argv.includes("--v3-product-closure-smoke");
const PRODUCT_CLOSURE_SMOKE_PHASE = process.env.V3_PRODUCT_CLOSURE_SMOKE_PHASE ?? "";
const PRODUCT_CLOSURE_SMOKE_OUTPUT = process.env.V3_PRODUCT_CLOSURE_SMOKE_OUTPUT ?? "";
const PRODUCT_CLOSURE_PROVIDER_MODE = process.env.V3_PRODUCT_CLOSURE_PROVIDER_MODE;

if (PACKAGED_RUNTIME_SMOKE || PRODUCT_CLOSURE_SMOKE) {
  if (process.platform !== "win32" || !PACKAGED_RUNTIME_SMOKE_USER_DATA || !isAbsolute(PACKAGED_RUNTIME_SMOKE_USER_DATA)) {
    throw new Error("V3_PACKAGED_SMOKE_USER_DATA must be an absolute Windows path");
  }
  app.setPath("userData", resolve(PACKAGED_RUNTIME_SMOKE_USER_DATA));
  app.setPath("cache", join(resolve(PACKAGED_RUNTIME_SMOKE_USER_DATA), "cache"));
  // The packaged runtime smoke deliberately removes developer PATH entries.
  // Disable Chromium GPU process startup before app readiness so the probe
  // remains independent of optional graphics DLLs on the test host; normal
  // packaged/product launches keep the regular Electron rendering path.
  app.commandLine.appendSwitch("disable-gpu");
  app.commandLine.appendSwitch("disable-gpu-compositing");
  app.disableHardwareAcceleration();
}

// PR #29 production boundary: a packaged build hard-denies the development
// integration fixture; LIVE product mode always uses the canonical bootstrap.
const AGENT_EVIDENCE_RUNTIME = resolveAgentEvidenceRuntime(app.isPackaged, process.env.V3_AGENT_EVIDENCE_MODE);
const AGENT_EVIDENCE_MODE = AGENT_EVIDENCE_RUNTIME.mode;

// Product bindings are runtime-owned assumed-revalidatable refs, never user
// truth and never renderer-controlled. Without a validated binding the normal
// LIVE path boots unbound (NO_CANONICAL_PROJECT_BOUND) instead of fabricating
// a hardcoded project identity. The development integration fixture keeps its
// own bounded fixture project identity: it is the early bounded runtime's
// fixture truth, never LIVE canonical truth.
let productBindings: ProductBindingStore;
let productBridge: ProductBridge;
const FIXTURE_PROJECT_ID = "prj_01ARZ3NDEKTSV4RRFFQ69G5FAV";
const FIXTURE_PROJECT_CONTEXT_REVISION_ID = "pcr_01ARZ3NDEKTSV4RRFFQ69G5FAV";

function trusted(event: IpcMainInvokeEvent): void {
  if (!mainWindow || event.sender.id !== mainWindow.webContents.id) throw new Error("Rejected untrusted IPC sender");
}

async function loadState(): Promise<void> {
  storePath = join(app.getPath("userData"), "v3-workbench-state.json");
  store = new WorkspaceStore(storePath);
  productBindings = new ProductBindingStore(productBindingPath(app.getPath("userData")));
  // Runtime-owned binding recovery happens before backend launch: only refs
  // previously validated by openProject can drive the bound-context startup.
  await productBindings.load();
  const loaded = await store.load();
  if (loaded.quarantinedPath !== null) {
    console.error(JSON.stringify({
      level: "WARN",
      code: "WORKSPACE_STORE_CORRUPT_QUARANTINED",
      message: "workspace store was malformed or schema-invalid; original file was quarantined and defaults were initialized",
      quarantine_file: loaded.quarantinedPath
    }));
  }
}

function registerIpc(): void {
  ipcMain.handle("workspace:load", (event) => { trusted(event); return store.snapshot(); });
  ipcMain.handle("workspace:save", (event, next: PersistedWorkspace) => {
    trusted(event);
    return store.saveUserState(next);
  });
  ipcMain.handle("workspace:reset", (event) => {
    trusted(event);
    return store.resetUserState();
  });
  ipcMain.handle("command:execute", (event, command: DesktopCommandEnvelope): Promise<CommandReceipt> => {
    trusted(event);
    return store.executeCommand(command);
  });
  ipcMain.handle("runtime:info", (event) => {
    trusted(event);
    return {
      electron: process.versions.electron,
      platform: process.platform,
      storePath,
      agentEvidenceMode: AGENT_EVIDENCE_MODE,
      durableEventCursor: AGENT_EVIDENCE_MODE === "DEVELOPMENT_INTEGRATION_FIXTURE"
        ? store.getProjectEventCursor(FIXTURE_PROJECT_ID)
        : productBindings.current !== null ? store.getProjectEventCursor(productBindings.current.projectId) : 0,
      persistenceRevision: store.persistenceRevision
    };
  });
  ipcMain.handle("window:state", (event) => {
    trusted(event);
    return { maximized: mainWindow?.isMaximized() ?? false };
  });
  ipcMain.handle("window:control", (event, action: "minimize" | "toggle-maximize" | "close") => {
    trusted(event);
    if (!mainWindow) return { maximized: false };
    if (action === "minimize") mainWindow.minimize();
    else if (action === "toggle-maximize") mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize();
    else if (action === "close") mainWindow.close();
    else throw new TypeError("Unsupported window control action");
    return { maximized: mainWindow?.isMaximized() ?? false };
  });
}

function logRuntimeSelection(runtime: BackendRuntimeResolution): void {
  console.error(JSON.stringify({
    level: "INFO",
    code: runtime.mode === "PACKAGED" ? "PACKAGED_RUNTIME_SELECTED" : "DEVELOPMENT_RUNTIME_SELECTED",
    runtime_mode: runtime.mode,
    backend_executable: runtime.executable,
    backend_working_directory: runtime.workingDirectory,
    backend_resource_root: runtime.backendResourceRoot || null,
    backend_module: runtime.backendModule,
    source_git_sha: runtime.sourceGitSha,
    build_manifest_id: runtime.buildManifestId,
    resource_manifest_sha256: runtime.manifestSha256,
  }));
}

function resolveRuntimeForStartup(): BackendRuntimeResolution | null {
  try {
    const runtime = resolveBackendRuntime(app.isPackaged, process.resourcesPath, process.env, process.platform);
    backendRuntimeResolution = runtime;
    logRuntimeSelection(runtime);
    return runtime;
  } catch (error) {
    const diagnostic = error instanceof Error ? error.message : String(error);
    console.error(JSON.stringify({
      level: "ERROR",
      code: app.isPackaged ? "PACKAGED_RUNTIME_UNAVAILABLE" : "DEVELOPMENT_RUNTIME_UNAVAILABLE",
      message: diagnostic,
    }));
    registerUnavailableProductRuntimeIpc(ipcMain, trusted, diagnostic);
    return null;
  }
}

function initialProjectContext() {
  const binding = productBindings.current;
  const fixtureMode = AGENT_EVIDENCE_MODE === "DEVELOPMENT_INTEGRATION_FIXTURE";
  return fixtureMode
    ? {
        projectId: FIXTURE_PROJECT_ID,
        projectContextRevisionId: FIXTURE_PROJECT_CONTEXT_REVISION_ID,
        lastDurableProjectEventSequence: store.getProjectEventCursor(FIXTURE_PROJECT_ID)
      }
    : binding === null
      ? undefined
      : {
          projectId: binding.projectId,
          projectContextRevisionId: binding.projectContextRevisionId,
           lastDurableProjectEventSequence: store.getProjectEventCursor(binding.projectId)
         };
}

function createBackendSupervisor(runtime: BackendRuntimeResolution): BackendSupervisor {
  const projectContext = initialProjectContext();
  return new BackendSupervisor({
    pythonExecutable: runtime.executable,
    backendWorkingDirectory: runtime.workingDirectory,
    backendRuntimeRoot: runtime.mode === "PACKAGED" ? runtime.pythonRoot : undefined,
    backendResourceRoot: runtime.mode === "PACKAGED" ? runtime.backendResourceRoot : undefined,
    desktopVersion: app.getVersion(),
    ...(projectContext === undefined ? {} : { projectContext }),
    cursorPort: {
      commit: (projectId, sequence) => store.commitProjectEventCursor(projectId, sequence)
    },
    backendModule: AGENT_EVIDENCE_RUNTIME.backendModule,
    ...(PRODUCT_CLOSURE_SMOKE && (PRODUCT_CLOSURE_PROVIDER_MODE === "DETERMINISTIC_SUCCESS" || PRODUCT_CLOSURE_PROVIDER_MODE === "DETERMINISTIC_UNAVAILABLE")
      ? { productReleaseAcceptanceProvider: PRODUCT_CLOSURE_PROVIDER_MODE }
      : {}),
    autoReconnect: true
  });
}

async function chooseResearchPackage(): Promise<string | null> {
  const window = mainWindow !== null ? (BrowserWindow.fromWebContents(mainWindow.webContents) ?? mainWindow) : null;
  const options = {
    title: "绑定已验证研究包（需要本机 canonical 来源权威）",
    properties: ["openDirectory"] as Array<"openDirectory">,
    buttonLabel: "验证来源并绑定"
  };
  const selection = window !== null
    ? await dialog.showOpenDialog(window, options)
    : await dialog.showOpenDialog(options);
  if (selection.canceled || selection.filePaths.length !== 1) return null;
  return selection.filePaths[0] ?? null;
}

async function chooseLocalDataSource(): Promise<string | null> {
  const window = mainWindow !== null ? (BrowserWindow.fromWebContents(mainWindow.webContents) ?? mainWindow) : null;
  const options = {
    title: "选择本地 A 股日线数据",
    properties: ["openFile"] as Array<"openFile">,
    buttonLabel: "安全打开",
    filters: [
      { name: "A 股日线数据", extensions: ["csv", "parquet"] }
    ]
  };
  const selection = window !== null
    ? await dialog.showOpenDialog(window, options)
    : await dialog.showOpenDialog(options);
  if (selection.canceled || selection.filePaths.length !== 1) return null;
  return selection.filePaths[0] ?? null;
}

function registerBackendRuntime(): void {
  if (!mainWindow || !backendSupervisor) throw new Error("BACKEND_RUNTIME_REGISTRATION_NOT_READY");
  backendRelay = new BackendRuntimeEventRelay(backendSupervisor, mainWindow.webContents);
  backendRelay.start();
  backendRuntimeLifecycle = new BackendRuntimeLifecycle(backendSupervisor);
  backendSupervisor.on("diagnostic", (diagnostic) => console.error(JSON.stringify(diagnostic)));
  registerBackendRuntimeIpc(ipcMain, trusted, backendSupervisor, () => backendRelay?.evidenceSnapshot ?? null);
  productBridge = new ProductBridge(
    backendSupervisor,
    store,
    productBindings,
    chooseResearchPackage,
    undefined,
    new LocalDataSourceBroker({ chooseFile: chooseLocalDataSource })
  );
  registerProductRuntimeIpc(ipcMain, trusted, productBridge);
}

function startBackendProcess(): void {
  if (!backendSupervisor) throw new Error("BACKEND_SUPERVISOR_NOT_INITIALIZED");
  backendStartPromise = backendSupervisor.start().then(() => recoverProductSession());
  void backendStartPromise.catch((error: unknown) => {
    const code = error !== null && typeof error === "object" && "code" in error ? String(error.code) : "BACKEND_START_FAILED";
    console.error(JSON.stringify({ level: "ERROR", code, message: "canonical backendRuntime failed to start; no demo fallback" }));
  });
}

function startBackendRuntime(): void {
  if (!mainWindow || backendSupervisor) return;
  const runtime = resolveRuntimeForStartup();
  if (runtime === null) return;
  backendSupervisor = createBackendSupervisor(runtime);
  registerBackendRuntime();
  startBackendProcess();
}

/**
 * Canonical restart recovery: the durable binding refs were validated by
 * openProject before they were persisted, so a restart re-queries canonical
 * read state (restoreSession) instead of trusting UI event history. A stale
 * binding (project removed from product storage) is demoted honestly, never
 * silently replaced by a fake project.
 */
async function recoverProductSession(): Promise<void> {
  if (!productBridge || AGENT_EVIDENCE_MODE === "DEVELOPMENT_INTEGRATION_FIXTURE" || productBindings.current === null) {
    productBridge?.recordBindingOutcome({ state: "NO_CANONICAL_PROJECT_BOUND" });
    return;
  }
  try {
    const restored = await productBridge.restoreSession();
    productBridge.recordBindingOutcome({ state: "PROJECT_BOUND" });
    console.error(JSON.stringify({
      level: "INFO",
      code: "PRODUCT_SESSION_RESTORED",
      message: `canonical product session restored for project ${restored.projectId}`
    }));
  } catch (error) {
    productBridge.recordBindingOutcome({
      state: "BINDING_STALE",
      code: error !== null && typeof error === "object" && "code" in error ? String(error.code) : "PRODUCT_RECOVERY_FAILED",
      message: error instanceof Error ? error.message : String(error)
    });
    console.error(JSON.stringify({
      level: "WARN",
      code: "PRODUCT_BINDING_STALE",
      message: "persisted product binding failed canonical re-validation; UI shows NOT_AVAILABLE until reconnected"
    }));
  }
}

function pathIsInside(parent: string, candidate: string): boolean {
  const child = relative(resolve(parent), resolve(candidate));
  return child === "" || (child !== ".." && !child.startsWith(`..${sep}`) && !isAbsolute(child));
}

function packagedStoragePaths(): {
  readonly storageRoot: string;
  readonly catalogPath: string;
  readonly artifactRoot: string;
} {
  const localAppData = process.env.LOCALAPPDATA?.length
    ? process.env.LOCALAPPDATA
    : join(app.getPath("userData"), "..", "Local");
  const storageRoot = resolve(localAppData, "v3-quant-workbench", "product");
  return {
    storageRoot,
    catalogPath: join(storageRoot, "catalog.sqlite3"),
    artifactRoot: join(storageRoot, "artifacts")
  };
}

async function writePackagedSmokeEvidence(evidence: Record<string, unknown>): Promise<void> {
  if (!PACKAGED_RUNTIME_SMOKE_OUTPUT || !isAbsolute(PACKAGED_RUNTIME_SMOKE_OUTPUT)) {
    throw new Error("V3_PACKAGED_SMOKE_OUTPUT must be an absolute path");
  }
  await mkdir(dirname(PACKAGED_RUNTIME_SMOKE_OUTPUT), { recursive: true });
  await writeFile(PACKAGED_RUNTIME_SMOKE_OUTPUT, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
}

type PackagedSmokePhase = "create-bind" | "relaunch";

interface PackagedSmokeContext {
  readonly phase: PackagedSmokePhase;
  readonly runtime: BackendRuntimeResolution;
  readonly supervisor: BackendSupervisor;
  readonly bridge: ProductBridge;
}

interface PackagedSmokeFlow {
  readonly statusBefore: ProductStatusView;
  readonly statusAfter: ProductStatusView;
  readonly sourceCapability: ProductStatusView["capabilities"][number];
  readonly createdProject: ProjectCreatedView | null;
  readonly projectContext: ProjectContextView;
}

interface PackagedSmokePaths {
  readonly installRoot: string;
  readonly userDataPath: string;
  readonly storageRoot: string;
  readonly catalogPath: string;
  readonly artifactRoot: string;
  readonly workspaceStatePath: string;
  readonly bindingPath: string;
}

function packagedSmokePhase(value: string): PackagedSmokePhase {
  if (value === "create-bind" || value === "relaunch") return value;
  throw new Error(`PACKAGED_SMOKE_UNKNOWN_PHASE:${value}`);
}

async function awaitPackagedSmokeContext(phaseValue: string): Promise<PackagedSmokeContext> {
  const phase = packagedSmokePhase(phaseValue);
  if (!PACKAGED_RUNTIME_SMOKE || !app.isPackaged) throw new Error("PACKAGED_RUNTIME_SMOKE_REQUIRES_PACKAGED_ELECTRON");
  const startup = backendStartPromise;
  if (startup === null) throw new Error("PACKAGED_BACKEND_START_NOT_SCHEDULED");
  await startup;
  if (!backendSupervisor || !productBridge || !backendRuntimeResolution) {
    throw new Error("PACKAGED_RUNTIME_SMOKE_RUNTIME_NOT_INITIALIZED");
  }
  return { phase, runtime: backendRuntimeResolution, supervisor: backendSupervisor, bridge: productBridge };
}

function assertReadyProductStatus(status: ProductStatusView, suffix: string): void {
  if (status.backendState !== "READY") throw new Error(`PACKAGED_PRODUCT_RUNTIME_NOT_READY${suffix}:${status.backendState}`);
}

async function createAndBindSmokeProject(
  bridge: ProductBridge,
  statusBefore: ProductStatusView,
): Promise<{ readonly createdProject: ProjectCreatedView; readonly projectContext: ProjectContextView }> {
  if (statusBefore.bindingState !== "NO_CANONICAL_PROJECT_BOUND") {
    throw new Error(`PACKAGED_SMOKE_EXPECTED_EMPTY_BINDING:${statusBefore.bindingState}`);
  }
  const createdProject = await bridge.createProject({
    displayName: "打包运行时验证项目",
    notes: "PACKAGING_CLEAN_MACHINE_RUNTIME"
  });
  const projectContext = await bridge.connectExistingProject({
    projectId: createdProject.projectId,
    projectContextRevisionId: createdProject.projectContextRevisionId
  });
  return { createdProject, projectContext };
}

async function reopenSmokeProject(
  bridge: ProductBridge,
  statusBefore: ProductStatusView,
): Promise<{ readonly createdProject: null; readonly projectContext: ProjectContextView }> {
  if (statusBefore.bindingState !== "PROJECT_BOUND" || statusBefore.boundProject === null) {
    throw new Error(`PACKAGED_SMOKE_PROJECT_REOPEN_FAILED:${statusBefore.bindingState}`);
  }
  return { createdProject: null, projectContext: await bridge.getProjectContext() };
}

async function executePackagedSmokeFlow(context: PackagedSmokeContext): Promise<PackagedSmokeFlow> {
  const statusBefore = await context.bridge.getProductStatus();
  assertReadyProductStatus(statusBefore, "");
  const flow = context.phase === "create-bind"
    ? await createAndBindSmokeProject(context.bridge, statusBefore)
    : await reopenSmokeProject(context.bridge, statusBefore);
  const statusAfter = await context.bridge.getProductStatus();
  assertReadyProductStatus(statusAfter, "_AFTER_FLOW");
  if (statusAfter.bindingState !== "PROJECT_BOUND") {
    throw new Error(`PACKAGED_SMOKE_PROJECT_${context.phase === "create-bind" ? "BIND" : "REOPEN"}_FAILED:${statusAfter.bindingState}`);
  }
  const sourceCapability = statusAfter.capabilities.find((capability) => capability.code === "DataSourceService");
  if (sourceCapability === undefined || sourceCapability.truth_state !== "UNAVAILABLE") {
    throw new Error(`PACKAGED_SOURCE_CAPABILITY_NOT_TRUTHFUL:${JSON.stringify(sourceCapability ?? null)}`);
  }
  return { statusBefore, statusAfter, sourceCapability, ...flow };
}

function packagedSmokePaths(): PackagedSmokePaths {
  const userDataPath = app.getPath("userData");
  const storage = packagedStoragePaths();
  const installRoot = resolve(dirname(process.execPath));
  const paths = {
    installRoot,
    userDataPath,
    storageRoot: storage.storageRoot,
    catalogPath: storage.catalogPath,
    artifactRoot: storage.artifactRoot,
    workspaceStatePath: join(userDataPath, "v3-workbench-state.json"),
    bindingPath: productBindingPath(userDataPath),
  };
  if (pathIsInside(installRoot, paths.userDataPath) || pathIsInside(installRoot, paths.storageRoot)) {
    throw new Error("PACKAGED_SMOKE_PATH_BOUNDARY_FAILED");
  }
  return paths;
}

function assertPackagedRuntimePaths(runtime: BackendRuntimeResolution): void {
  if (runtime.mode !== "PACKAGED"
    || !pathIsInside(runtime.backendResourceRoot, runtime.executable)
    || !pathIsInside(runtime.backendResourceRoot, runtime.workingDirectory)) {
    throw new Error("PACKAGED_SMOKE_RESOLVER_PATH_BOUNDARY_FAILED");
  }
}

function createPackagedSmokeEvidence(
  context: PackagedSmokeContext,
  flow: PackagedSmokeFlow,
  paths: PackagedSmokePaths,
): Record<string, unknown> {
  const { runtime, supervisor, phase } = context;
  return {
    schema_version: "v3.packaged-runtime-smoke/1.0.0",
    success: true,
    phase,
    packaged: app.isPackaged,
    process_id: process.pid,
    app_is_packaged: app.isPackaged,
    electron_version: process.versions.electron,
    resources_path: process.resourcesPath,
    app_path: app.getAppPath(),
    install_root: paths.installRoot,
    backend_runtime_mode: runtime.mode,
    backend_executable: runtime.executable,
    backend_working_directory: runtime.workingDirectory,
    backend_resource_root: runtime.backendResourceRoot,
    backend_python_root: runtime.pythonRoot,
    backend_module: runtime.backendModule,
    backend_pid: supervisor.backendPid,
    backend_handshake: supervisor.handshake === null
      ? null
      : {
          transport: "STDIO_FRAMED_V1",
          ready: supervisor.state === "READY",
          hello: supervisor.handshake,
        },
    resource_manifest_path: runtime.manifestPath,
    resource_manifest_sha256: runtime.manifestSha256,
    source_git_sha: runtime.sourceGitSha,
    build_manifest_id: runtime.buildManifestId,
    product_status_before: flow.statusBefore,
    product_status_after: flow.statusAfter,
    source_capability: flow.sourceCapability,
    created_project: flow.createdProject,
    project_context: flow.projectContext,
    user_data_path: paths.userDataPath,
    storage_root: paths.storageRoot,
    catalog_path: paths.catalogPath,
    artifact_root: paths.artifactRoot,
    workspace_state_path: paths.workspaceStatePath,
    product_binding_path: paths.bindingPath,
    writes_inside_install_root: false,
    first_launch_network_install: false,
    shutdown_expected: "GRACEFUL_SHUTDOWN_REQUIRED",
  };
}

async function writePackagedSmokeFailure(evidence: Record<string, unknown>, error: unknown): Promise<void> {
  const failureEvidence = {
    ...evidence,
    error: error instanceof Error ? error.message : String(error),
    backend_runtime_mode: backendRuntimeResolution?.mode ?? null,
    backend_executable: backendRuntimeResolution?.executable ?? null,
    backend_working_directory: backendRuntimeResolution?.workingDirectory ?? null,
    backend_pid: backendSupervisor?.backendPid ?? null,
  };
  try {
    await writePackagedSmokeEvidence(failureEvidence);
  } catch (writeError) {
    console.error(JSON.stringify({ level: "ERROR", code: "PACKAGED_SMOKE_EVIDENCE_WRITE_FAILED", message: writeError instanceof Error ? writeError.message : String(writeError) }));
  }
}

async function runPackagedRuntimeSmoke(): Promise<void> {
  const phase = process.env.V3_PACKAGED_SMOKE_PHASE ?? "create-bind";
  const initialEvidence: Record<string, unknown> = {
    schema_version: "v3.packaged-runtime-smoke/1.0.0", success: false, phase, packaged: app.isPackaged, process_id: process.pid
  };
  try {
    const context = await awaitPackagedSmokeContext(phase);
    assertPackagedRuntimePaths(context.runtime);
    const flow = await executePackagedSmokeFlow(context);
    const paths = packagedSmokePaths();
    await writePackagedSmokeEvidence(createPackagedSmokeEvidence(context, flow, paths));
    console.error(JSON.stringify({ level: "INFO", code: "PACKAGED_RUNTIME_SMOKE_PASS", phase: context.phase }));
    process.exitCode = 0;
  } catch (error) {
    await writePackagedSmokeFailure(initialEvidence, error);
    console.error(JSON.stringify({ level: "ERROR", code: "PACKAGED_RUNTIME_SMOKE_FAILED", message: error instanceof Error ? error.message : String(error) }));
    process.exitCode = 1;
  } finally {
    app.quit();
  }
}

async function runProductClosureSmokeProbe(): Promise<void> {
  try {
    if (!PRODUCT_CLOSURE_SMOKE || !app.isPackaged) throw new Error("PRODUCT_CLOSURE_SMOKE_REQUIRES_PACKAGED_ELECTRON");
    const window = mainWindow;
    const startup = backendStartPromise;
    const supervisor = backendSupervisor;
    const runtime = backendRuntimeResolution;
    const rendererLoad = productClosureRendererLoad;
    if (window === null || startup === null || supervisor === null || runtime === null || rendererLoad === null) throw new Error("PRODUCT_CLOSURE_SMOKE_RUNTIME_NOT_INITIALIZED");
    await rendererLoad;
    await runProductClosureSmokeFlow({
      window,
      startup,
      phase: PRODUCT_CLOSURE_SMOKE_PHASE as ProductClosureSmokePhase,
      outputPath: PRODUCT_CLOSURE_SMOKE_OUTPUT,
      runtime,
      supervisor,
      electronVersion: process.versions.electron,
      appPath: app.getAppPath(),
      resourcesPath: process.resourcesPath
    });
    process.exitCode = 0;
  } catch (error) {
    console.error(JSON.stringify({ level: "ERROR", code: "PRODUCT_CLOSURE_PACKAGED_SMOKE_FAILED", message: error instanceof Error ? error.message : String(error) }));
    process.exitCode = 1;
  } finally {
    app.quit();
  }
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1536,
    height: 864,
    minWidth: 1120,
    minHeight: 680,
    frame: false,
    titleBarStyle: "hidden",
    // The packaged smoke is a main-process/runtime acceptance probe. Keep a
    // hidden owner window for the supervised relay, but do not load the normal
    // renderer during the probe: its startup refreshes can issue concurrent
    // projectless Product Entry reads while the probe is creating the first
    // canonical Project.
    show: !PACKAGED_RUNTIME_SMOKE && !PRODUCT_CLOSURE_SMOKE,
    backgroundColor: "#0B0D14",
    title: "V3 量化研究工作台",
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true
    }
  });
  if (PRODUCT_CLOSURE_SMOKE) {
    productClosureRendererLoad = mainWindow.loadFile(
      join(__dirname, "renderer", "index.html"),
      { search: "v3-product-closure-smoke=1" },
    );
  } else if (!PACKAGED_RUNTIME_SMOKE) {
    void mainWindow.loadFile(join(__dirname, "renderer", "index.html"));
  }
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event) => event.preventDefault());
  const publishWindowState = (): void => {
    if (!mainWindow || mainWindow.webContents.isDestroyed()) return;
    mainWindow.webContents.send("window:state-changed", { maximized: mainWindow.isMaximized() });
  };
  mainWindow.on("maximize", publishWindowState);
  mainWindow.on("unmaximize", publishWindowState);
  mainWindow.on("closed", () => { mainWindow = null; });
}

// Electron single-instance guarantee: the workspace store is a process-local
// serialized queue over one shared state file, so a second V3 instance must
// never read or modify it. This decision happens before any WorkspaceStore
// access (loadState runs inside whenReady below).
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.exit(0);
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null);
    await loadState();
    registerIpc();
    createWindow();
    startBackendRuntime();
    if (PACKAGED_RUNTIME_SMOKE) void runPackagedRuntimeSmoke();
    if (PRODUCT_CLOSURE_SMOKE) void runProductClosureSmokeProbe();
    app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
  }).catch((error: unknown) => {
    const code = error instanceof WorkspaceStoreError ? error.code : "APP_STARTUP_FAILED";
    console.error(JSON.stringify({ level: "ERROR", code, message: error instanceof Error ? error.message : String(error) }));
    app.exit(1);
  });

async function gracefulShutdown(): Promise<void> {
  try {
    // Reject new durable user mutations first, then drain pre-quit user
    // work, then shut the backend down gracefully while the relay and the
    // store stay alive, then perform the final cursor/state flush. Only
    // then may the store be closed and the relay stopped.
    store.beginQuiesce();
    await productBridge.dispose();
    await store.flush();
    if (backendRuntimeLifecycle && backendSupervisor) {
      await backendRuntimeLifecycle.onExplicitQuit(GRACEFUL_SHUTDOWN_DEADLINE_MS);
    }
    await store.flush();
    store.beginShutdown();
    backendRelay?.stop();
    console.error(JSON.stringify({
      level: "INFO",
      code: "GRACEFUL_SHUTDOWN_SUCCESS",
      message: "runtime prepare/commit shutdown handshake completed and persistence queue drained"
    }));
  } catch (error) {
    console.error(JSON.stringify({
      level: "ERROR",
      code: "FORCED_SHUTDOWN_FALLBACK",
      message: error instanceof Error ? error.message : String(error)
    }));
    backendSupervisor?.stopNow();
  } finally {
    shutdownComplete = true;
    app.quit();
  }
}

  app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
  app.on("before-quit", (event) => {
    if (shutdownComplete) return;
    if (quitting) { event.preventDefault(); return; }
    quitting = true;
    event.preventDefault();
    void gracefulShutdown();
  });
}
