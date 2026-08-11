import { app, BrowserWindow, ipcMain, type IpcMainInvokeEvent } from "electron";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import {
  DEFAULT_WORKSPACE,
  applyCommandExactlyOnce,
  type CommandReceipt,
  type DesktopCommandEnvelope,
  type PersistedWorkspace
} from "../../../packages/contracts/src/index";
import {
  BackendRuntimeEventRelay,
  BackendSupervisor,
  registerBackendRuntimeIpc
} from "./main/backendRuntime/index";

let mainWindow: BrowserWindow | null = null;
let state: PersistedWorkspace = structuredClone(DEFAULT_WORKSPACE);
let storePath = "";
let backendSupervisor: BackendSupervisor | null = null;
let backendRelay: BackendRuntimeEventRelay | null = null;

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
  try {
    const parsed = JSON.parse(await readFile(storePath, "utf8")) as PersistedWorkspace;
    state = { ...structuredClone(DEFAULT_WORKSPACE), ...parsed };
  } catch {
    state = structuredClone(DEFAULT_WORKSPACE);
    await persist();
  }
}

async function persist(): Promise<PersistedWorkspace> {
  state.savedAt = new Date().toISOString();
  await mkdir(dirname(storePath), { recursive: true });
  const temporary = `${storePath}.tmp`;
  await writeFile(temporary, JSON.stringify(state, null, 2), "utf8");
  await rename(temporary, storePath);
  return structuredClone(state);
}

function registerIpc(): void {
  ipcMain.handle("workspace:load", (event) => { trusted(event); return structuredClone(state); });
  ipcMain.handle("workspace:save", async (event, next: PersistedWorkspace) => {
    trusted(event);
    state = structuredClone(next);
    return persist();
  });
  ipcMain.handle("workspace:reset", async (event) => {
    trusted(event);
    state = structuredClone(DEFAULT_WORKSPACE);
    return persist();
  });
  ipcMain.handle("command:execute", async (event, command: DesktopCommandEnvelope): Promise<CommandReceipt> => {
    trusted(event);
    const applied = applyCommandExactlyOnce(state, command);
    if (applied.receipt.duplicate) return applied.receipt;
    state = applied.state;
    await persist();
    return applied.receipt;
  });
  ipcMain.handle("runtime:info", (event) => { trusted(event); return { electron: process.versions.electron, platform: process.platform, storePath, agentEvidenceMode: AGENT_EVIDENCE_MODE }; });
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
      lastDurableProjectEventSequence: 0
    },
    backendModule: AGENT_EVIDENCE_MODE === "DEVELOPMENT_INTEGRATION_FIXTURE"
      ? "v3_backend.adapters.round3_evidence.development_runtime"
      : "v3_backend.runtime.bootstrap",
    autoReconnect: false
  });
  backendRelay = new BackendRuntimeEventRelay(backendSupervisor, mainWindow.webContents);
  backendRelay.start();
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

app.whenReady().then(async () => {
  await loadState();
  registerIpc();
  createWindow();
  startBackendRuntime();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
}).catch((error) => { console.error(error); app.exit(1); });

app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
app.on("before-quit", () => {
  backendRelay?.stop();
  backendSupervisor?.stopNow();
});
