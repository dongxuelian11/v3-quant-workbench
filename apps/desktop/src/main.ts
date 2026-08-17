import { app, BrowserWindow, dialog, ipcMain, Menu, type IpcMainInvokeEvent } from "electron";
import { join } from "node:path";
import {
  type CommandReceipt,
  type DesktopCommandEnvelope,
  type PersistedWorkspace
} from "../../../packages/contracts/src/index";
import {
  BackendRuntimeEventRelay,
  BackendRuntimeLifecycle,
  BackendSupervisor,
  registerBackendRuntimeIpc
} from "./main/backendRuntime/index";
import { WorkspaceStore, WorkspaceStoreError } from "./main/runtimePersistence/workspaceStore";
import { resolveAgentEvidenceRuntime } from "./main/agentEvidenceRuntime";
import { ProductBindingStore, ProductBridge, productBindingPath, registerProductRuntimeIpc } from "./main/productRuntime/index";

let mainWindow: BrowserWindow | null = null;
let store: WorkspaceStore;
let storePath = "";
let backendSupervisor: BackendSupervisor | null = null;
let backendRelay: BackendRuntimeEventRelay | null = null;
let backendRuntimeLifecycle: BackendRuntimeLifecycle | null = null;
let quitting = false;
let shutdownComplete = false;

const GRACEFUL_SHUTDOWN_DEADLINE_MS = 10_000;

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

function startBackendRuntime(): void {
  if (!mainWindow || backendSupervisor) return;
  const binding = productBindings.current;
  const fixtureMode = AGENT_EVIDENCE_MODE === "DEVELOPMENT_INTEGRATION_FIXTURE";
  const projectContext = fixtureMode
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
  backendSupervisor = new BackendSupervisor({
    pythonExecutable: process.env.V3_BACKEND_PYTHON ?? process.env.V3_PYTHON ?? (process.platform === "win32" ? "python" : "python3"),
    backendWorkingDirectory: process.env.V3_BACKEND_WORKING_DIRECTORY ?? join(process.cwd(), "apps", "backend", "src"),
    desktopVersion: "0.1.0-recovery.1",
    ...(projectContext === undefined ? {} : { projectContext }),
    cursorPort: {
      commit: (projectId, sequence) => store.commitProjectEventCursor(projectId, sequence)
    },
    backendModule: AGENT_EVIDENCE_RUNTIME.backendModule,
    autoReconnect: false
  });
  backendRelay = new BackendRuntimeEventRelay(backendSupervisor, mainWindow.webContents);
  backendRelay.start();
  backendRuntimeLifecycle = new BackendRuntimeLifecycle(backendSupervisor);
  backendSupervisor.on("diagnostic", (item) => console.error(JSON.stringify(item)));
  registerBackendRuntimeIpc(ipcMain, trusted, backendSupervisor, () => backendRelay?.evidenceSnapshot ?? null);
  // Main-process owned research package chooser: the renderer never sees a
  // filesystem path; it only asks the product bridge to start an import.
  const chooseResearchPackage = async (): Promise<string | null> => {
    const window = mainWindow !== null ? (BrowserWindow.fromWebContents(mainWindow.webContents) ?? mainWindow) : null;
    const options = {
      title: "导入 V3 研究包",
      properties: ["openDirectory"] as Array<"openDirectory">,
      buttonLabel: "验证并导入"
    };
    const selection = window !== null
      ? await dialog.showOpenDialog(window, options)
      : await dialog.showOpenDialog(options);
    if (selection.canceled || selection.filePaths.length !== 1) return null;
    return selection.filePaths[0] ?? null;
  };
  productBridge = new ProductBridge(backendSupervisor, store, productBindings, chooseResearchPackage);
  registerProductRuntimeIpc(ipcMain, trusted, productBridge);
  void backendSupervisor.start()
    .then(() => recoverProductSession())
    .catch((error: unknown) => {
      const code = error !== null && typeof error === "object" && "code" in error ? String(error.code) : "BACKEND_START_FAILED";
      console.error(JSON.stringify({ level: "ERROR", code, message: "canonical backendRuntime failed to start; no demo fallback" }));
    });
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

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1536,
    height: 864,
    minWidth: 1120,
    minHeight: 680,
    frame: false,
    titleBarStyle: "hidden",
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
  void mainWindow.loadFile(join(__dirname, "renderer", "index.html"));
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
