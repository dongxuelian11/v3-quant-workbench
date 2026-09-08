import { BrowserWindow, screen, type Rectangle, type WebContents } from "electron";
import { readFile, rename, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import type { JsonObject, JobEvent, WorkspacePanel, WorkspaceWindow } from "../../../../packages/contracts/src/research";

type Record = { window: BrowserWindow; state: WorkspaceWindow; suppressReturn?: boolean };
type Change = { method: string; params?: JsonObject };

/** One native window per workspace; all windows share the application runtime. */
export class WorkspaceWindows {
  private readonly records = new Map<string, Record>();
  private writes: Promise<void> = Promise.resolve();
  private saveTimer?: ReturnType<typeof setTimeout>;
  private quitting = false;
  private saved: WorkspaceWindow[] = [];

  constructor(
    private readonly file: string,
    private readonly factory: (state: WorkspaceWindow) => BrowserWindow,
    private readonly load: (window: BrowserWindow) => Promise<void>,
  ) {}

  async start(): Promise<BrowserWindow> {
    try {
      const value: unknown = JSON.parse(await readFile(this.file, "utf8"));
      if (Array.isArray(value)) this.saved = value.filter((item): item is WorkspaceWindow =>
        !!item && typeof item.id === "string" && Array.isArray(item.panels));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") console.warn("无法恢复上次窗口布局", error);
    }
    const state = this.saved.find(item => item.id === "main") ?? { id: "main", main: true, panels: [] };
    return this.open({ ...state, id: "main", main: true });
  }

  async restoreSaved(): Promise<void> {
    for (const state of this.saved) {
      if (state.id !== "main" && state.panels.length && !this.records.has(state.id)) {
        try { await this.open({ ...state, main: false }); }
        catch (error) { console.warn("独立窗口恢复失败", state.id, error); }
      }
    }
    await this.persist();
  }

  private async open(state: WorkspaceWindow): Promise<BrowserWindow> {
    const window = this.factory({ ...state, bounds: this.fitBounds(state.bounds, !!state.main) });
    const record: Record = { window, state: { ...state, bounds: window.getBounds() } };
    this.records.set(state.id, record);
    const geometry = () => { if (!window.isDestroyed()) record.state.bounds = window.getNormalBounds(); this.scheduleSave(); };
    window.on("move", geometry);
    window.on("resize", geometry);
    window.on("maximize", () => { record.state.maximized = true; geometry(); window.webContents.send("window:state-changed", { maximized: true }); });
    window.on("unmaximize", () => { record.state.maximized = false; geometry(); window.webContents.send("window:state-changed", { maximized: false }); });
    window.on("close", () => {
      record.state.bounds = window.getNormalBounds();
      if (state.main) {
        this.quitting = true;
        void this.persist().catch(error => console.warn("保存窗口布局失败", error));
        for (const other of this.records.values()) if (other !== record && !other.window.isDestroyed()) other.window.close();
      }
    });
    window.on("closed", () => {
      if (this.quitting) return;
      this.records.delete(state.id);
      if (!record.suppressReturn && record.state.panels.length) this.deliver("main", record.state.panels);
      void this.persist().catch(error => console.warn("保存窗口布局失败", error));
    });
    try { await this.load(window); }
    catch (error) { record.suppressReturn = true; this.records.delete(state.id); window.destroy(); throw error; }
    return window;
  }

  own(contents: WebContents): Record {
    const record = [...this.records.values()].find(item => !item.window.isDestroyed() && item.window.webContents.id === contents.id);
    if (!record) throw new Error("未知窗口请求");
    return record;
  }

  current(contents: WebContents) {
    const record = this.own(contents);
    return { id: record.state.id, main: !!record.state.main, state: record.state };
  }

  async detach(contents: WebContents, panel: WorkspacePanel, bounds?: WorkspaceWindow["bounds"]) {
    const source = this.own(contents);
    if (!panel || typeof panel.id !== "string" || typeof panel.kind !== "string") throw new Error("工作对象无效");
    const id = randomUUID();
    const cursor = screen.getCursorScreenPoint();
    await this.open({ id, main: false, panels: [panel], activePanelId: panel.id,
      bounds: bounds ?? { x: cursor.x - 80, y: cursor.y - 24, width: 1050, height: 760 } });
    source.state.panels = source.state.panels.filter(item => item.id !== panel.id);
    if (source.state.activePanelId === panel.id) source.state.activePanelId = source.state.panels[0]?.id;
    await this.persist();
    return { windowId: id };
  }

  async update(contents: WebContents, state: WorkspaceWindow): Promise<void> {
    const record = this.own(contents);
    if (!Array.isArray(state.panels)) throw new Error("窗口布局无效");
    record.state = { ...state, id: record.state.id, main: record.state.main, maximized: record.window.isMaximized(), bounds: record.window.getNormalBounds() };
    await this.persist();
  }

  private deliver(targetId: string, panels: WorkspacePanel[]): void {
    const target = this.records.get(targetId);
    if (!target || target.window.isDestroyed()) throw new Error("目标窗口已关闭");
    const merged = new Map(target.state.panels.map(panel => [panel.id, panel]));
    for (const panel of panels) merged.set(panel.id, panel);
    target.state.panels = [...merged.values()];
    target.state.activePanelId = panels.at(-1)?.id ?? target.state.activePanelId;
    target.window.webContents.send("research:workspace-panels", panels);
  }

  async attach(contents: WebContents, panels: WorkspacePanel[], targetId = "main"): Promise<void> {
    const source = this.own(contents);
    if (!Array.isArray(panels)) throw new Error("工作对象无效");
    if (source.state.id === targetId) return;
    this.deliver(targetId, panels);
    const ids = new Set(panels.map(panel => panel.id));
    source.state.panels = source.state.panels.filter(panel => !ids.has(panel.id));
    if (!source.state.main && !source.state.panels.length) source.window.close();
    await this.persist();
  }

  async restore(states: WorkspaceWindow[]): Promise<void> {
    if (!Array.isArray(states)) throw new Error("窗口布局无效");
    const ids = new Set(states.map(state => state.id));
    for (const record of this.records.values()) {
      if (!record.state.main && !ids.has(record.state.id)) { record.suppressReturn = true; record.window.close(); }
    }
    for (const state of states) {
      if (!state.id || !Array.isArray(state.panels)) continue;
      const record = this.records.get(state.id);
      if (record) {
        record.state = { ...state, main: record.state.main };
        if (state.bounds) record.window.setBounds(this.fitBounds(state.bounds, !!record.state.main));
        if (state.maximized && !record.window.isMaximized()) record.window.maximize();
        else if (!state.maximized && record.window.isMaximized()) record.window.unmaximize();
        record.window.webContents.send("research:workspace-changed", { method: "workspace.layout", params: { windowId: state.id } });
      } else if (state.panels.length) await this.open({ ...state, main: false });
    }
    await this.persist();
  }

  broadcast(change: Change, except?: WebContents): void {
    for (const record of this.records.values()) {
      if (!record.window.isDestroyed() && record.window.webContents.id !== except?.id) record.window.webContents.send("research:workspace-changed", change);
    }
  }

  job(event: JobEvent): void {
    for (const record of this.records.values()) if (!record.window.isDestroyed()) record.window.webContents.send("research:event", event);
  }

  private fitBounds(bounds: WorkspaceWindow["bounds"], main: boolean): Rectangle {
    const primary = screen.getPrimaryDisplay().workArea;
    const proposed = {
      x: Number.isFinite(bounds?.x) ? bounds!.x! : primary.x + 40,
      y: Number.isFinite(bounds?.y) ? bounds!.y! : primary.y + 30,
      width: Number.isFinite(bounds?.width) ? bounds!.width : main ? 1540 : 1050,
      height: Number.isFinite(bounds?.height) ? bounds!.height : main ? 980 : 760,
    };
    const area = screen.getDisplayMatching(proposed).workArea;
    const width = Math.min(area.width, Math.max(main ? 1080 : 640, proposed.width));
    const height = Math.min(area.height, Math.max(main ? 700 : 460, proposed.height));
    return { width, height, x: Math.max(area.x, Math.min(proposed.x, area.x + area.width - width)), y: Math.max(area.y, Math.min(proposed.y, area.y + area.height - height)) };
  }

  private scheduleSave(): void {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => { this.saveTimer = undefined; void this.persist().catch(error => console.warn("保存窗口布局失败", error)); }, 350);
  }

  private persist(): Promise<void> {
    const body = JSON.stringify([...this.records.values()].map(record => record.state));
    this.writes = this.writes.catch(() => {}).then(async () => {
      const temporary = `${this.file}.tmp`;
      await writeFile(temporary, body, "utf8");
      await rename(temporary, this.file);
    });
    return this.writes;
  }

  async shutdown(): Promise<void> {
    this.quitting = true;
    if (this.saveTimer) clearTimeout(this.saveTimer);
    await this.persist();
  }
}
