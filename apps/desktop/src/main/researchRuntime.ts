import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import type { ResearchServiceEvent } from "../../../../packages/contracts/src/research";
import { encodeFrame, FrameDecoder } from "./backendRuntime/framing";

const RESEARCH_FRAME_BYTES = 16 * 1024 * 1024;
const CANCELLABLE_READS = new Set(["experiments.get", "experiments.table", "experiments.analysis", "experiments.calendar", "experiments.compare", "exports.create"]);

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

/** A local process connection; research jobs themselves live in Python. */
export class ResearchRuntime {
  private child: ChildProcessWithoutNullStreams | null = null;
  private readonly pending = new Map<string, PendingRequest>();
  private closing = false;
  private stderr = "";

  constructor(
    private readonly options: { root: string; resources: string; appData: string; packaged: boolean },
    private readonly onEvent: (event: ResearchServiceEvent) => void,
    private readonly onStopped: () => void = () => {},
  ) {}

  private start(): ChildProcessWithoutNullStreams {
    if (this.child) return this.child;
    if (this.closing) throw new Error("研究服务正在关闭");
    const base = this.options.packaged ? join(this.options.resources, "backend-runtime") : this.options.root;
    const python = this.options.packaged
      ? join(base, "python", "python.exe")
      : process.env.V3_RESEARCH_PYTHON ?? join(base, "runtime", "research-python", process.platform === "win32" ? "python.exe" : "bin/python3");
    if (!existsSync(python)) throw new Error(`未找到 Python 研究环境：${python}。开发环境请先运行 npm run setup:research。`);
    const source = this.options.packaged ? join(base, "backend-package") : join(base, "apps", "backend", "src");
    const child = spawn(python, ["-u", "-m", "v3_backend.research.server", "--app-data", this.options.appData], {
      cwd: this.options.appData,
      env: { ...process.env, PYTHONPATH: source, PYTHONUTF8: "1", MPLBACKEND: "Agg", PYTHONDONTWRITEBYTECODE: "1",
        V3_FORMULA_NODE: process.execPath,
        V3_FORMULA_RUNNER: this.options.packaged ? join(base, "formula", "hq-formula.cjs") : join(base, "scripts", "hq-formula.cjs"),
      },
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.child = child;
    this.stderr = "";
    const decoder = new FrameDecoder(RESEARCH_FRAME_BYTES);
    child.stderr.on("data", (chunk: Buffer) => { this.stderr = (this.stderr + chunk.toString("utf8")).slice(-6000); });
    child.stdout.on("data", (chunk: Buffer) => {
      try {
        for (const message of decoder.feed(chunk)) {
          if (message.event) { this.onEvent(message.event as ResearchServiceEvent); continue; }
          const request = this.pending.get(String(message.id));
          if (!request) continue;
          this.pending.delete(String(message.id));
          clearTimeout(request.timer);
          if (message.error) request.reject(new Error(String((message.error as { message?: string }).message ?? message.error)));
          else request.resolve(message.result);
        }
      } catch (error) {
        this.fail(new Error(`研究服务通信出错：${String(error)}`));
        child.kill();
      }
    });
    child.on("error", (error) => { this.fail(new Error(`研究服务启动失败：${error.message}`)); });
    child.on("exit", (code) => {
      if (this.child === child) { this.child = null; this.onStopped(); }
      this.fail(new Error(this.closing ? "研究服务已关闭" : `研究服务已退出（${code ?? "中断"}）${this.stderr ? `\n${this.stderr}` : ""}`));
    });
    child.stdin.on("error", (error) => this.fail(new Error(`无法发送研究请求：${error.message}`)));
    return child;
  }

  request<T = unknown>(method: string, params: object = {}): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      try {
        const child = this.start();
        const id = randomUUID();
        const readId = CANCELLABLE_READS.has(method) ? ((params as { readId?: string }).readId ?? id) : undefined;
        const payload = readId ? { ...params, readId } : params;
        const frame = encodeFrame(JSON.parse(JSON.stringify({ id, method, params: payload })) as Record<string, unknown>, RESEARCH_FRAME_BYTES);
        const timer = setTimeout(() => {
          this.pending.delete(id);
          if (readId && child.exitCode === null && !child.stdin.destroyed) {
            child.stdin.write(encodeFrame({ id: randomUUID(), method: "reads.cancel", params: { readId } }, RESEARCH_FRAME_BYTES));
          }
          reject(new Error(readId ? "读取响应超时，已请求停止；已完成的导出可能仍保留在导出目录。" : "研究服务响应超时，请查看底部任务状态"));
        }, 180_000);
        this.pending.set(id, { resolve: (value) => resolve(value as T), reject, timer });
        child.stdin.write(frame);
      } catch (error) { reject(error); }
    });
  }

  private fail(error: Error): void {
    for (const request of this.pending.values()) { clearTimeout(request.timer); request.reject(error); }
    this.pending.clear();
  }

  async close(): Promise<void> {
    this.closing = true;
    const child = this.child;
    if (!child) return;
    await new Promise<void>((resolve) => {
      // Let Python interrupt and save its workers before forcing this owned tree down.
      const timer = setTimeout(() => {
        if (process.platform === "win32" && child.pid && child.exitCode === null) {
          const stop = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
          stop.once("error", error => { console.error("结束研究进程树失败", error); child.kill(); resolve(); });
          stop.once("exit", () => resolve());
        } else { child.kill(); resolve(); }
      }, 15000);
      child.once("exit", () => { clearTimeout(timer); resolve(); });
      child.stdin.end();
    });
  }
}
