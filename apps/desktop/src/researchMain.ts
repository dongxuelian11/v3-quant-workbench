import { app, BrowserWindow, dialog, ipcMain, Menu, shell, type IpcMainInvokeEvent } from "electron";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { JsonObject, ResearchBridge, WorkspacePanel, WorkspaceWindow } from "../../../packages/contracts/src/research";
import { ResearchRuntime } from "./main/researchRuntime";
import { WorkspaceWindows } from "./main/workspaceWindows";
import { ResearchBackground } from "./main/researchBackground";

let window: BrowserWindow | null = null;
let runtime: ResearchRuntime | null = null;
let workspaces: WorkspaceWindows | null = null;
let shuttingDown = false;
let background: ResearchBackground | null = null;
if (process.env.V3_RESEARCH_APP_DATA) app.setPath("userData", process.env.V3_RESEARCH_APP_DATA);
const primaryInstance = app.requestSingleInstanceLock();
if (!primaryInstance) app.quit();
else app.on("second-instance", () => workspaces?.show());

function ownWindow(event: IpcMainInvokeEvent): BrowserWindow {
  if (!workspaces) throw new Error("窗口尚未初始化");
  return workspaces.own(event.sender).window;
}

function registerIpc(): void {
  ipcMain.handle("research:request", async (event, method: string, params: object) => {
    ownWindow(event);
    if (!runtime) throw new Error("研究服务尚未启动");
    const finish = background?.beginRequest(method);
    let result: unknown;
    try { result = await runtime.request(method, params); }
    finally { finish?.(); }
    if (method === "workspace.get" && workspaces) return { ...(result as object), windows: workspaces.snapshots() };
    if (/(?:\.save|\.create|\.delete|\.activate|\.import|\.update|\.adopt|\.clear)$/.test(method)) {
      const context: JsonObject = {};
      for (const key of ["projectId", "strategyId", "experimentId", "conversationId", "candidateId", "accountId", "symbol", "id"]) {
        const value = (params as Record<string, unknown>)[key];
        if (typeof value === "string") context[key] = value;
      }
      workspaces?.broadcast({ method, params: context }, event.sender);
    }
    return result;
  });
  ipcMain.handle("research:choose-directory", async (event, options: Parameters<ResearchBridge["chooseDirectory"]>[0] = {}) => {
    const owner = ownWindow(event);
    const result = await dialog.showOpenDialog(owner, { title: options.purpose === "tdx" ? "选择通达信安装目录（含 vipdoc）" : "选择研究项目文件夹", properties: options.purpose === "tdx" ? ["openDirectory"] : ["openDirectory", "createDirectory"] });
    return result.canceled ? null : result.filePaths[0] ?? null;
  });
  ipcMain.handle("research:open-external", async (event, value: string) => {
    ownWindow(event);
    const url = new URL(value);
    if (!["https:", "http:"].includes(url.protocol)) throw new Error("仅支持打开网页来源");
    await shell.openExternal(url.href);
  });
  ipcMain.handle("research:report-document", async (event, reportId: string) => {
    ownWindow(event);
    if (!runtime) throw new Error("研究服务尚未启动");
    if (typeof reportId !== "string" || !reportId.trim()) throw new Error("请选择研报");
    const document = await runtime.request<{ path: string }>("reports.document", { reportId });
    return new Uint8Array(await readFile(document.path));
  });
  ipcMain.handle("research:choose-files", async (event, options: Parameters<ResearchBridge["chooseFiles"]>[0] = {}) => {
    const owner = ownWindow(event);
    const positions = options.purpose === "positions";
    const membership = options.purpose === "membership";
    const report = options.purpose === "report";
    const quote = options.purpose === "quote";
    const result = await dialog.showOpenDialog(owner, {
      title: report ? "导入研报 PDF" : quote ? "导入标的行情" : positions ? "导入当前持仓" : membership ? "导入历史股票池或行业" : "导入行情或财务数据",
      properties: positions ? ["openFile"] : ["openFile", "multiSelections"],
      filters: [{ name: report ? "研报 PDF" : quote ? "标的行情" : positions ? "持仓表格" : "研究数据", extensions: report ? ["pdf"] : quote ? ["csv", "tsv", "txt", "parquet", "day"] : positions ? ["csv", "xlsx"] : ["csv", "xlsx", "parquet"] }],
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

if (primaryInstance) app.whenReady().then(async () => {
  const appData = join(app.getPath("userData"), "research");
  await mkdir(appData, { recursive: true });
  background = new ResearchBackground({
    show: () => workspaces?.show(),
    cancel: async (ids, executions, reproductions) => {
      const reproductionResults = await Promise.allSettled(reproductions.map(event => runtime!.request("reproductions.cancel", {
        projectId: event.projectId, planId: event.planId, runId: event.id,
      })));
      const aiResults = await Promise.allSettled(executions.map(event => runtime!.request("ai.chat.cancel", {
        conversationId: event.conversationId, executionId: event.id,
      })));
      const results = [...reproductionResults, ...aiResults, ...await Promise.allSettled(ids.map(jobId => runtime!.request("jobs.cancel", { jobId })))];
      const failures = results.filter((item): item is PromiseRejectedResult => item.status === "rejected");
      if (failures.length) throw new Error(failures.map(item => String(item.reason)).join("\n"));
    },
    quit: () => app.quit(),
    error: error => dialog.showErrorBox("停止任务未完成", String(error)),
  });
  runtime = new ResearchRuntime({ root: app.getAppPath(), resources: process.resourcesPath, appData, packaged: app.isPackaged }, (event) => {
    if (event.kind === "ai.execution") {
      background?.execution(event);
      workspaces?.broadcast({ method: "ai.execution", params: { id: event.id, conversationId: event.conversationId,
        projectId: event.projectId ?? null, status: event.status, message: event.message ?? "" } });
    } else if (event.kind === "reproduction.execution") {
      background?.reproduction(event);
      workspaces?.broadcast({ method: "reproduction.execution", params: { ...event } });
    } else {
      background?.job(event);
      workspaces?.job(event);
    }
  }, () => background?.serviceStopped());
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
  }, () => !shuttingDown && !!background?.hideIfBusy());
  window = await workspaces.start();
}).catch((error: unknown) => {
  dialog.showErrorBox("V3 启动失败", error instanceof Error ? error.message : String(error));
  app.exit(1);
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (shuttingDown) return;
  event.preventDefault();
  shuttingDown = true;
  void Promise.allSettled([workspaces?.shutdown(), runtime?.close()]).finally(() => { background?.destroy(); app.quit(); });
});
