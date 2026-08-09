import { app, BrowserWindow, ipcMain } from "electron";
import { join } from "node:path";
import {
  DEFAULT_WORKSPACE_STATE,
  UNAVAILABLE_BACKEND_STATUS,
  type DesktopCommand,
  type SaveWorkspaceRequest,
  type WorkspaceState
} from "../../../packages/contracts/src/index";

let mainWindow: BrowserWindow | null = null;
let workspaceState: WorkspaceState = structuredClone(DEFAULT_WORKSPACE_STATE);

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 940,
    minWidth: 1120,
    minHeight: 720,
    backgroundColor: "#0b1016",
    title: "V3 Workbench — Recovery Candidate",
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  void mainWindow.loadFile(join(__dirname, "renderer", "index.html"));
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function registerIpc(): void {
  ipcMain.handle("workspace:getState", () => structuredClone(workspaceState));
  ipcMain.handle("workspace:saveState", (_event, request: SaveWorkspaceRequest) => {
    workspaceState = structuredClone(request.state);
    return structuredClone(workspaceState);
  });
  ipcMain.handle("workspace:resetState", () => {
    workspaceState = structuredClone(DEFAULT_WORKSPACE_STATE);
    return structuredClone(workspaceState);
  });
  ipcMain.handle("backend:getStatus", () => structuredClone(UNAVAILABLE_BACKEND_STATUS));
  ipcMain.handle("command:send", (_event, command: DesktopCommand) => {
    if (command === "workspace.reset") {
      workspaceState = structuredClone(DEFAULT_WORKSPACE_STATE);
    }
  });
}

app.whenReady().then(() => {
  registerIpc();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

