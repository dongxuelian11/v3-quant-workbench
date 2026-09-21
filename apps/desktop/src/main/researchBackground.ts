import { Menu, Tray, nativeImage } from "electron";
import type { JobEvent, ResearchAIEvent, ReproductionEvent } from "../../../../packages/contracts/src/research";

/** Track live work only; experiment and task history remain in the research service. */
export class ResearchBackground {
  private tray: Tray | null = null;
  private readonly jobs = new Map<string, JobEvent>();
  private readonly executions = new Map<string, ResearchAIEvent>();
  private readonly reproductions = new Map<string, ReproductionEvent>();
  private requests = 0;
  private menuKey = "";

  constructor(private readonly actions: {
    show: () => void;
    cancel: (ids: string[], executions: ResearchAIEvent[], reproductions: ReproductionEvent[]) => Promise<void>;
    quit: () => void;
    error: (error: unknown) => void;
  }) {}

  get busy(): boolean { return this.jobs.size > 0 || this.executions.size > 0 || this.reproductions.size > 0 || this.requests > 0; }

  job(event: JobEvent): void {
    if (event.status === "queued" || event.status === "running") this.jobs.set(event.id, event);
    else this.jobs.delete(event.id);
    this.update();
  }

  execution(event: ResearchAIEvent): void {
    if (event.status === "running") this.executions.set(event.id, event);
    else this.executions.delete(event.id);
    this.update();
  }

  reproduction(event: ReproductionEvent): void {
    if (event.status === "running") this.reproductions.set(event.id, event);
    else this.reproductions.delete(event.id);
    this.update();
  }

  serviceStopped(): void { this.jobs.clear(); this.executions.clear(); this.reproductions.clear(); this.update(); }

  beginRequest(method: string): () => void {
    if (method !== "jobs.submit" && method !== "screener.run" && method !== "screeners.run" && method !== "ai.chat" && method !== "ai.chat.start" && method !== "reproductions.run") return () => {};
    this.requests++;
    this.update();
    let ended = false;
    return () => {
      if (ended) return;
      ended = true;
      this.requests--;
      this.update();
    };
  }

  hideIfBusy(): boolean {
    if (!this.busy) return false;
    if (!this.tray) {
      // A small opaque V mark remains legible on either Windows taskbar theme.
      const size = 32, pixels = Buffer.alloc(size * size * 4);
      for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
        const i = (y * size + x) * 4;
        const mark = y >= 7 && y <= 25 && (Math.abs(x - (7 + (y - 7) / 2)) < 2 || Math.abs(x - (25 - (y - 7) / 2)) < 2);
        pixels[i] = mark ? 255 : 180;
        pixels[i + 1] = mark ? 255 : 119;
        pixels[i + 2] = mark ? 255 : 38;
        pixels[i + 3] = 255;
      }
      this.tray = new Tray(nativeImage.createFromBitmap(pixels, { width: size, height: size }));
      this.tray.on("click", () => this.actions.show());
      this.tray.on("double-click", () => this.actions.show());
      this.menuKey = "";
      this.update();
      this.tray.displayBalloon({ title: "V3 已转入后台", content: "已启动的工作继续运行。点击托盘返回，右键可停止当前工作或退出。", noSound: true });
    }
    return true;
  }

  private update(): void {
    if (!this.tray) return;
    const label = this.executions.size ? `${this.executions.size} 个研究对话正在执行 · ${this.jobs.size} 项计算`
      : this.reproductions.size ? `${this.reproductions.size} 项研报复现进行中 · ${this.jobs.size} 项计算`
      : this.jobs.size ? `${this.jobs.size} 项任务正在进行` : this.requests ? "正在等待研究服务" : "工作已结束，可返回查看结果";
    if (label === this.menuKey) return;
    this.menuKey = label;
    this.tray.setToolTip(`V3 · ${label}`);
    this.tray.setContextMenu(Menu.buildFromTemplate([
      { label, enabled: false },
      { label: "返回研究工作台", click: () => this.actions.show() },
      { label: "停止当前工作", enabled: this.jobs.size > 0 || this.executions.size > 0 || this.reproductions.size > 0,
        click: () => { void this.actions.cancel([...this.jobs.keys()], [...this.executions.values()], [...this.reproductions.values()]).catch(this.actions.error); } },
      { type: "separator" },
      { label: "退出 V3", click: () => this.actions.quit() },
    ]));
  }

  destroy(): void { this.tray?.destroy(); this.tray = null; }
}
