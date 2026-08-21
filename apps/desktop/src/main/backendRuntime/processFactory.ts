import { spawn, type ChildProcess } from "node:child_process";
import type { Writable } from "node:stream";
import { join } from "node:path";
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

export function sanitizedBackendEnvironment(
  source: NodeJS.ProcessEnv = process.env,
  packagedRuntimeRoot?: string,
  packagedBackendResourceRoot?: string,
): Readonly<Record<string, string>> {
  const environment: Record<string, string> = {};
  // APPDATA lets a Windows CPython installation locate its standard per-user
  // site-packages (notably the IANA tzdata required by canonical BacktestRunSpec).
  // LOCALAPPDATA is the documented Windows base directory that
  // resolve_product_storage_root() (v3_backend.runtime.product_runtime) uses for
  // the normal product storage root (%LOCALAPPDATA%/v3-quant-workbench/product).
  // No package-specific, project, token, or raw storage path is admitted.
  for (const name of ["PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA"]) {
    const inheritedValue = source[name];
    if (typeof inheritedValue === "string" && inheritedValue.length > 0) environment[name] = inheritedValue;
  }
  if (packagedRuntimeRoot === undefined) {
    const developmentStorageRoot = source.V3_PRODUCT_STORAGE_ROOT;
    if (typeof developmentStorageRoot === "string" && developmentStorageRoot.length > 0) {
      environment.V3_PRODUCT_STORAGE_ROOT = developmentStorageRoot;
    }
  } else {
    environment.PYTHONHOME = packagedRuntimeRoot;
    environment.PYTHONNOUSERSITE = "1";
    environment.PYTHONDONTWRITEBYTECODE = "1";
    environment.V3_BACKEND_RUNTIME_MODE = "PACKAGED";
    if (packagedBackendResourceRoot !== undefined) {
      environment.V3_RESEARCH_PACKAGE_TRANSPORT_PATH = join(
        packagedBackendResourceRoot,
        "backend-package",
        "packages",
        "contracts",
        "research_package_transport_v1.json",
      );
    }
  }
  environment.PYTHONUTF8 = "1";
  environment.PYTHONUNBUFFERED = "1";
  return Object.freeze(environment);
}
