import { spawn, type ChildProcess } from "node:child_process";
import type { Writable } from "node:stream";
import type { BackendProcess, BackendProcessFactory, SpawnSpec } from "./types";

class NodeBackendProcess implements BackendProcess {
  readonly stdin;
  readonly stdout;
  readonly stderr;
  readonly pid;

  constructor(private readonly child: ChildProcess) {
    if (!child.stdin || !child.stdout || !child.stderr) throw new Error("backend stdio pipes were not created");
    this.stdin = child.stdin;
    this.stdout = child.stdout;
    this.stderr = child.stderr;
    this.pid = child.pid;
  }

  onExit(listener: (code: number | null, signal: NodeJS.Signals | null) => void): void {
    this.child.once("exit", listener);
  }

  terminate(): void {
    this.child.kill();
  }
}

export class NodeBackendProcessFactory implements BackendProcessFactory {
  spawn(spec: SpawnSpec, supervisorToken: Uint8Array): BackendProcess {
    const child = spawn(spec.executable, [...spec.args], {
      cwd: spec.cwd,
      env: { ...spec.env },
      windowsHide: true,
      shell: false,
      stdio: ["pipe", "pipe", "pipe", "pipe"]
    });
    const tokenPipe = child.stdio[3] as Writable | null;
    if (!tokenPipe || typeof tokenPipe.end !== "function") {
      child.kill();
      throw new Error("supervisor token pipe was not created");
    }
    tokenPipe.end(Buffer.from(supervisorToken));
    return new NodeBackendProcess(child);
  }
}

export function sanitizedBackendEnvironment(source: NodeJS.ProcessEnv = process.env): Readonly<Record<string, string>> {
  const result: Record<string, string> = {};
  for (const name of ["PATH", "SystemRoot", "WINDIR", "TEMP", "TMP"]) {
    const value = source[name];
    if (typeof value === "string" && value.length > 0) result[name] = value;
  }
  result.PYTHONUTF8 = "1";
  result.PYTHONUNBUFFERED = "1";
  return Object.freeze(result);
}
