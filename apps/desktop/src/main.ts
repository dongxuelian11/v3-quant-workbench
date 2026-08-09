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

let mainWindow: BrowserWindow | null = null;
let state: PersistedWorkspace = structuredClone(DEFAULT_WORKSPACE);
let storePath = "";

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
  ipcMain.handle("runtime:info", (event) => { trusted(event); return { electron: process.versions.electron, platform: process.platform, storePath }; });
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
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
}).catch((error) => { console.error(error); app.exit(1); });

app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
