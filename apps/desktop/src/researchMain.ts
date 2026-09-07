import { app, BrowserWindow, dialog, ipcMain, Menu, type IpcMainInvokeEvent } from "electron";
import { copyFile, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { ResearchBridge } from "../../../packages/contracts/src/research";
import { ResearchRuntime } from "./main/researchRuntime";

let window: BrowserWindow | null = null;
let runtime: ResearchRuntime | null = null;
let shuttingDown = false;
if (process.env.V3_RESEARCH_APP_DATA) app.setPath("userData", process.env.V3_RESEARCH_APP_DATA);

function ownWindow(event: IpcMainInvokeEvent): void {
  if (!window || event.sender.id !== window.webContents.id) throw new Error("未知窗口请求");
}

function registerIpc(): void {
  ipcMain.handle("research:request", (event, method: string, params: object) => {
    ownWindow(event);
    if (!runtime) throw new Error("研究服务尚未启动");
    return runtime.request(method, params);
  });
  ipcMain.handle("research:choose-directory", async (event) => {
    ownWindow(event);
    const result = await dialog.showOpenDialog(window!, { title: "选择研究项目文件夹", properties: ["openDirectory", "createDirectory"] });
    return result.canceled ? null : result.filePaths[0] ?? null;
  });
  ipcMain.handle("research:choose-files", async (event, options: Parameters<ResearchBridge["chooseFiles"]>[0] = {}) => {
    ownWindow(event);
    const positions = options.purpose === "positions";
    const membership = options.purpose === "membership";
    const result = await dialog.showOpenDialog(window!, {
      title: positions ? "导入当前持仓" : membership ? "导入历史股票池或行业" : "导入行情或财务数据",
      properties: positions ? ["openFile"] : ["openFile", "multiSelections"],
      filters: [{ name: positions ? "持仓表格" : "研究数据", extensions: positions ? ["csv", "xlsx"] : ["csv", "parquet"] }],
    });
    return result.canceled ? [] : result.filePaths;
  });
  ipcMain.handle("research:export", async (event, request: Parameters<ResearchBridge["exportFile"]>[0]) => {
    ownWindow(event);
    const result = await dialog.showSaveDialog(window!, {
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
  ipcMain.handle("window:state", (event) => { ownWindow(event); return { maximized: window?.isMaximized() ?? false }; });
  ipcMain.handle("window:control", (event, action: string) => {
    ownWindow(event);
    if (action === "minimize") window?.minimize();
    else if (action === "toggle-maximize") window?.isMaximized() ? window.unmaximize() : window?.maximize();
    else if (action === "close") window?.close();
    return { maximized: window?.isMaximized() ?? false };
  });
}

app.whenReady().then(async () => {
  const appData = join(app.getPath("userData"), "research");
  await mkdir(appData, { recursive: true });
  runtime = new ResearchRuntime({ root: app.getAppPath(), resources: process.resourcesPath, appData, packaged: app.isPackaged }, (event) => {
    if (window && !window.isDestroyed()) window.webContents.send("research:event", event);
  });
  Menu.setApplicationMenu(null);
  registerIpc();
  window = new BrowserWindow({
    width: 1540, height: 980, minWidth: 1080, minHeight: 700,
    title: "V3 研究工作台", frame: false, backgroundColor: "#f7f8f5", show: false,
    webPreferences: { preload: join(__dirname, "researchPreload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  const publishWindowState = () => window?.webContents.send("window:state-changed", { maximized: window?.isMaximized() ?? false });
  window.on("maximize", publishWindowState);
  window.on("unmaximize", publishWindowState);
  window.once("ready-to-show", () => { if (!process.argv.includes("--v3-headless")) window?.show(); });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  if (process.env.V3_DEV_SERVER_URL) await window.loadURL(process.env.V3_DEV_SERVER_URL);
  else await window.loadFile(join(__dirname, "renderer", "index.html"));
}).catch((error: unknown) => {
  dialog.showErrorBox("V3 启动失败", error instanceof Error ? error.message : String(error));
  app.exit(1);
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (shuttingDown) return;
  event.preventDefault();
  shuttingDown = true;
  void runtime?.close().finally(() => app.quit());
  if (!runtime) app.quit();
});
