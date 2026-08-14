import { app, BrowserWindow, ipcMain, type IpcMainInvokeEvent } from "electron";
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

let mainWindow: BrowserWindow | null = null;
let store: WorkspaceStore;
let storePath = "";
let backendSupervisor: BackendSupervisor | null = null;
let backendRelay: BackendRuntimeEventRelay | null = null;
let backendRuntimeLifecycle: BackendRuntimeLifecycle | null = null;
let quitting = false;
let shutdownComplete = false;

const GRACEFUL_SHUTDOWN_DEADLINE_MS = 10_000;

const AGENT_EVIDENCE_MODE = process.env.V3_AGENT_EVIDENCE_MODE === "DEVELOPMENT_INTEGRATION_FIXTURE"
  ? "DEVELOPMENT_INTEGRATION_FIXTURE" as const
  : "LIVE_READ_ONLY" as const;
const BACKEND_PROJECT_ID = "prj_01ARZ3NDEKTSV4RRFFQ69G5FAV";
const BACKEND_PROJECT_CONTEXT_REVISION_ID = "pcr_01ARZ3NDEKTSV4RRFFQ69G5FAV";

function trusted(event: IpcMainInvokeEvent): void {
  if (!mainWindow || event.sender.id !== mainWindow.webContents.id) throw new Error("Rejected untrusted IPC sender");
}

async function loadState(): Promise<void> {
  storePath = join(app.getPath("userData"), "v3-workbench-state.json");
  store = new WorkspaceStore(storePath);
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
      durableEventCursor: store.getProjectEventCursor(BACKEND_PROJECT_ID),
      persistenceRevision: store.persistenceRevision
    };
  });
}

function startBackendRuntime(): void {
  if (!mainWindow || backendSupervisor) return;
  backendSupervisor = new BackendSupervisor({
    pythonExecutable: process.env.V3_BACKEND_PYTHON ?? process.env.V3_PYTHON ?? (process.platform === "win32" ? "python" : "python3"),
    backendWorkingDirectory: process.env.V3_BACKEND_WORKING_DIRECTORY ?? join(process.cwd(), "apps", "backend", "src"),
    desktopVersion: "0.1.0-recovery.1",
    projectContext: {
      projectId: BACKEND_PROJECT_ID,
      projectContextRevisionId: BACKEND_PROJECT_CONTEXT_REVISION_ID,
      lastDurableProjectEventSequence: store.getProjectEventCursor(BACKEND_PROJECT_ID)
    },
    cursorPort: {
      commit: (projectId, sequence) => store.commitProjectEventCursor(projectId, sequence)
    },
    backendModule: AGENT_EVIDENCE_MODE === "DEVELOPMENT_INTEGRATION_FIXTURE"
      ? "v3_backend.adapters.round3_evidence.development_runtime"
      : "v3_backend.runtime.bootstrap",
    autoReconnect: false
  });
  backendRelay = new BackendRuntimeEventRelay(backendSupervisor, mainWindow.webContents);
  backendRelay.start();
  backendRuntimeLifecycle = new BackendRuntimeLifecycle(backendSupervisor);
  backendSupervisor.on("diagnostic", (item) => console.error(JSON.stringify(item)));
  registerBackendRuntimeIpc(ipcMain, trusted, backendSupervisor, () => backendRelay?.evidenceSnapshot ?? null);
  void backendSupervisor.start().catch((error: unknown) => {
    const code = error !== null && typeof error === "object" && "code" in error ? String(error.code) : "BACKEND_START_FAILED";
    console.error(JSON.stringify({ level: "ERROR", code, message: "canonical backendRuntime failed to start; no demo fallback" }));
  });
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1536,
    height: 864,
    minWidth: 800,
    minHeight: 600,
    backgroundColor: "#0B0D14",
    title: "V3 量化研究工作台 · FR-1 Visual Restoration Candidate",
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
