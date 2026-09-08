import { app, BrowserWindow, dialog, ipcMain, Menu, type IpcMainInvokeEvent } from "electron";
import { copyFile, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { JsonObject, ResearchBridge, WorkspacePanel, WorkspaceWindow } from "../../../packages/contracts/src/research";
import { ResearchRuntime } from "./main/researchRuntime";
import { WorkspaceWindows } from "./main/workspaceWindows";

let window: BrowserWindow | null = null;
let runtime: ResearchRuntime | null = null;
let workspaces: WorkspaceWindows | null = null;
let shuttingDown = false;
if (process.env.V3_RESEARCH_APP_DATA) app.setPath("userData", process.env.V3_RESEARCH_APP_DATA);

function ownWindow(event: IpcMainInvokeEvent): BrowserWindow {
  if (!workspaces) throw new Error("窗口尚未初始化");
  return workspaces.own(event.sender).window;
}

function registerIpc(): void {
  ipcMain.handle("research:request", async (event, method: string, params: object) => {
    ownWindow(event);
    if (!runtime) throw new Error("研究服务尚未启动");
    const result = await runtime.request(method, params);
    if (method === "workspace.get" && workspaces) return { ...(result as object), windows: workspaces.snapshots() };
    if (/(?:\.save|\.create|\.delete|\.activate|\.import|\.update)$/.test(method)) {
      const context: JsonObject = {};
      for (const key of ["projectId", "strategyId", "experimentId", "conversationId", "symbol", "id"]) {
        const value = (params as Record<string, unknown>)[key];
        if (typeof value === "string") context[key] = value;
      }
      workspaces?.broadcast({ method, params: context }, event.sender);
    }
    return result;
  });
  ipcMain.handle("research:choose-directory", async (event) => {
    const owner = ownWindow(event);
    const result = await dialog.showOpenDialog(owner, { title: "选择研究项目文件夹", properties: ["openDirectory", "createDirectory"] });
    return result.canceled ? null : result.filePaths[0] ?? null;
  });
  ipcMain.handle("research:choose-files", async (event, options: Parameters<ResearchBridge["chooseFiles"]>[0] = {}) => {
    const owner = ownWindow(event);
    const positions = options.purpose === "positions";
    const membership = options.purpose === "membership";
    const result = await dialog.showOpenDialog(owner, {
      title: positions ? "导入当前持仓" : membership ? "导入历史股票池或行业" : "导入行情或财务数据",
      properties: positions ? ["openFile"] : ["openFile", "multiSelections"],
      filters: [{ name: positions ? "持仓表格" : "研究数据", extensions: positions ? ["csv", "xlsx"] : ["csv", "xlsx", "parquet"] }],
    });
    return result.canceled ? [] : result.filePaths;
  });
  ipcMain.handle("research:export", async (event, request: Parameters<ResearchBridge["exportFile"]>[0]) => {
    const owner = ownWindow(event);
    const result = await dialog.showSaveDialog(owner, {
      title: "导出研究结果", defaultPath: request.suggestedName,
      filters: [{ name: request.format.toUpperCase(), extensions: [request.format] }],
    });
    if (result.canceled || !result.filePath) return null;
    if (request.format === "pdf" && request.html) {
      const report = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, javascript: false } });
      try {
        await report.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(request.html)}`);
        const bytes = await report.webContents.printToPDF({ printBackground: true, pageSize: "A4", preferCSSPageSize: true });
        await writeFile(result.filePath, bytes);
      } finally { report.destroy(); }
    } else if (request.sourcePath) await copyFile(request.sourcePath, result.filePath);
    else if (request.dataUrl) {
      const match = /^data:image\/png;base64,(.+)$/s.exec(request.dataUrl);
      if (!match) throw new Error("图片导出格式无效");
      await writeFile(result.filePath, Buffer.from(match[1], "base64"));
    } else if (request.content !== undefined) await writeFile(result.filePath, request.content, "utf8");
    else throw new Error("没有可导出的内容");
    return result.filePath;
  });
  ipcMain.handle("window:state", (event) => ({ maximized: ownWindow(event).isMaximized() }));
  ipcMain.handle("window:control", (event, action: string) => {
    const owner = ownWindow(event);
    if (action === "minimize") owner.minimize();
    else if (action === "toggle-maximize") owner.isMaximized() ? owner.unmaximize() : owner.maximize();
    else if (action === "close") owner.close();
    return { maximized: !owner.isDestroyed() && owner.isMaximized() };
  });
  ipcMain.handle("research:workspace-current", event => workspaces!.current(event.sender));
  ipcMain.handle("research:workspace-detach", (event, panel: WorkspacePanel, bounds?: WorkspaceWindow["bounds"]) => workspaces!.detach(event.sender, panel, bounds));
  ipcMain.handle("research:workspace-update", (event, state: WorkspaceWindow) => workspaces!.update(event.sender, state));
  ipcMain.handle("research:workspace-attach", (event, panels: WorkspacePanel[], target?: string) => workspaces!.attach(event.sender, panels, target));
  ipcMain.handle("research:workspace-restore", (event, states: WorkspaceWindow[]) => { ownWindow(event); return workspaces!.restore(states); });
  ipcMain.on("research:workspace-broadcast", (event, change: { method: string; params?: JsonObject }) => {
    workspaces!.own(event.sender);
    if (change && typeof change.method === "string") workspaces!.broadcast(change, event.sender);
  });
}

app.whenReady().then(async () => {
  const appData = join(app.getPath("userData"), "research");
  await mkdir(appData, { recursive: true });
  runtime = new ResearchRuntime({ root: app.getAppPath(), resources: process.resourcesPath, appData, packaged: app.isPackaged }, (event) => {
    workspaces?.job(event);
  });
  Menu.setApplicationMenu(null);
  registerIpc();
  workspaces = new WorkspaceWindows(join(appData, "workspace-windows.json"), state => {
    const created = new BrowserWindow({
      ...state.bounds, minWidth: state.main ? 1080 : 640, minHeight: state.main ? 700 : 460,
      title: state.main ? "V3 研究工作台" : `${state.panels[0]?.title ?? "研究窗口"} · V3`,
      frame: false, backgroundColor: "#f4f5f7", show: false,
      webPreferences: { preload: join(__dirname, "researchPreload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true },
    });
    created.once("ready-to-show", () => {
      if (!process.argv.includes("--v3-headless")) { if (state.maximized) created.maximize(); created.show(); }
    });
    created.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    return created;
  }, async created => {
    if (process.env.V3_DEV_SERVER_URL) await created.loadURL(process.env.V3_DEV_SERVER_URL);
    else await created.loadFile(join(__dirname, "renderer", "index.html"));
  });
  window = await workspaces.start();
  await workspaces.restoreSaved();
}).catch((error: unknown) => {
  dialog.showErrorBox("V3 启动失败", error instanceof Error ? error.message : String(error));
  app.exit(1);
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (shuttingDown) return;
  event.preventDefault();
  shuttingDown = true;
  void Promise.allSettled([workspaces?.shutdown(), runtime?.close()]).finally(() => app.quit());
});
