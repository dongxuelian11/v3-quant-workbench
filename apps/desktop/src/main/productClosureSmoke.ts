import type { BrowserWindow } from "electron";
import { mkdir, writeFile } from "node:fs/promises";
import type { BackendRuntimeResolution } from "./backendRuntime/runtimeResolver";
import type { BackendSupervisor } from "./backendRuntime/supervisor";

export type ProductClosureSmokePhase = "create-submit" | "reopen-discover";

export interface ProductClosureSmokeOptions {
  readonly window: BrowserWindow;
  readonly startup: Promise<void>;
  readonly phase: ProductClosureSmokePhase;
  readonly outputPath: string;
  readonly runtime: BackendRuntimeResolution;
  readonly supervisor: BackendSupervisor;
  readonly electronVersion: string;
  readonly appPath: string;
  readonly resourcesPath: string;
}

interface RendererEvidence {
  readonly initialRendererState: {
    readonly lastResearch: unknown;
    readonly task: unknown;
    readonly result: unknown;
    readonly artifactDescriptor: unknown;
  };
  readonly currentRendererState: {
    readonly lastResearch: unknown;
    readonly task: {
      readonly taskId: string;
      readonly runId: string;
      readonly resultId: string | null;
      readonly outputs: Readonly<Record<string, string>>;
    } | null;
    readonly result: {
      readonly resultId: string;
      readonly backtestRunId: string;
      readonly resultArtifact: {
        readonly artifactId: string;
        readonly sha256: string;
        readonly byteSize: number;
      } | null;
    } | null;
    readonly artifactDescriptor: {
      readonly artifactId: string;
      readonly sha256: string;
      readonly byteSize: number;
    } | null;
    readonly researchDiscoveryState: string;
    readonly recoveredResearchTaskId: string | null;
    readonly surface: string;
    readonly boundProject: {
      readonly projectId: string;
      readonly projectContextRevisionId: string;
    } | null;
    readonly errorMessage: string | null;
  };
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function executeRenderer<T>(window: BrowserWindow, source: string): Promise<T> {
  return await window.webContents.executeJavaScript("(async () => {" + source + "\n})()", true) as T;
}

async function waitForRenderer(window: BrowserWindow): Promise<void> {
  const deadline = Date.now() + 60_000;
  let lastError = "renderer did not become ready";
  while (Date.now() < deadline) {
    if (window.isDestroyed() || window.webContents.isDestroyed()) {
      throw new Error("renderer was destroyed before product closure smoke became ready");
    }
    try {
      const ready = await executeRenderer<boolean>(
        window,
        "return document.readyState === \"complete\" && typeof window.v3ProductClosureEvidence === \"function\";"
      );
      if (ready) return;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await sleep(250);
  }
  throw new Error(lastError);
}

async function waitForRecoveredRenderer(window: BrowserWindow): Promise<RendererEvidence> {
  const deadline = Date.now() + 120_000;
  let lastEvidence: RendererEvidence | null = null;
  while (Date.now() < deadline) {
    lastEvidence = await executeRenderer<RendererEvidence>(
      window,
      "return window.v3ProductClosureEvidence();"
    );
    if (lastEvidence.currentRendererState.researchDiscoveryState === "RECOVERED") {
      return lastEvidence;
    }
    if (lastEvidence.currentRendererState.researchDiscoveryState === "ERROR") {
      throw new Error(lastEvidence.currentRendererState.errorMessage ?? "renderer cold research recovery failed");
    }
    await sleep(250);
  }
  throw new Error("renderer did not automatically recover canonical research within 120 seconds");
}

async function runCreateSubmit(window: BrowserWindow): Promise<Record<string, unknown>> {
  return await executeRenderer<Record<string, unknown>>(
    window,
    "if (typeof window.v3ProductClosureRunFirst !== \"function\") throw new Error(\"renderer first-phase smoke action is unavailable\");" +
    "await window.v3ProductClosureRunFirst({" +
    "displayName: \"V1 Product Closure Real Source\"," +
    "notes: \"REAL_AKSHARE_NETWORK_COLD_RESTART\"," +
    "intent: { symbol: \"600519\", startDate: \"20250701\", endDate: \"20250710\" }" +
    "});" +
    "const evidence = window.v3ProductClosureEvidence();" +
    "const current = evidence.currentRendererState;" +
    "if (current.surface !== \"RESULT_AVAILABLE\" || current.lastResearch === null || current.task === null || current.result === null || current.artifactDescriptor === null) throw new Error(\"first renderer store did not reach RESULT_AVAILABLE\");" +
    "const bridge = window.v3ProductRuntime;" +
    "const status = await bridge.getProductStatus();" +
    "const projectContext = await bridge.getProjectContext();" +
    "const task = await bridge.getTask(current.task.taskId);" +
    "if (task.state !== \"SUCCEEDED\" || task.resultId === null || typeof task.outputs.BACKTEST_RUN_RESULT !== \"string\") throw new Error(\"first canonical Task is not a successful research task\");" +
    "const result = await bridge.getResult(task.resultId);" +
    "const artifactDescriptor = await bridge.getArtifactDescriptor(task.outputs.BACKTEST_RUN_RESULT);" +
    "return { phase: \"create-submit\", status, projectContext, task, result, artifactDescriptor, rendererEvidence: evidence };"
  );
}

async function runReopenDiscover(window: BrowserWindow): Promise<Record<string, unknown>> {
  const evidence = await waitForRecoveredRenderer(window);
  return await executeRenderer<Record<string, unknown>>(
    window,
    "const evidence = window.v3ProductClosureEvidence();" +
    "const initial = evidence.initialRendererState;" +
    "if (initial.lastResearch !== null || initial.task !== null || initial.result !== null || initial.artifactDescriptor !== null) throw new Error(\"new renderer did not start with an empty research state\");" +
    "const current = evidence.currentRendererState;" +
    "if (current.lastResearch !== null || current.researchDiscoveryState !== \"RECOVERED\" || current.surface !== \"RESULT_AVAILABLE\" || current.recoveredResearchTaskId === null || current.task === null || current.result === null || current.artifactDescriptor === null) throw new Error(\"cold renderer did not recover canonical research automatically\");" +
    "const bridge = window.v3ProductRuntime;" +
    "const status = await bridge.getProductStatus();" +
    "const projectContext = await bridge.getProjectContext();" +
    "const task = await bridge.getTask(current.recoveredResearchTaskId);" +
    "if (task.state !== \"SUCCEEDED\" || task.resultId === null || typeof task.outputs.BACKTEST_RUN_RESULT !== \"string\") throw new Error(\"recovered task is not canonical successful research\");" +
    "const result = await bridge.getResult(task.resultId);" +
    "const artifactDescriptor = await bridge.getArtifactDescriptor(task.outputs.BACKTEST_RUN_RESULT);" +
    "return { phase: \"reopen-discover\", status, projectContext, task, result, artifactDescriptor, rendererEvidence: evidence, awaitedEvidence: " + JSON.stringify(evidence) + " };"
  );
}

function assertPhase(value: string): ProductClosureSmokePhase {
  if (value === "create-submit" || value === "reopen-discover") return value;
  throw new Error("unknown product closure smoke phase: " + value);
}

async function writeEvidence(path: string, evidence: Record<string, unknown>): Promise<void> {
  await mkdir(path.substring(0, Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"))), { recursive: true });
  await writeFile(path, JSON.stringify(evidence, null, 2) + "\n", "utf8");
}

export async function runProductClosureSmoke(options: ProductClosureSmokeOptions): Promise<void> {
  if (!options.outputPath || !/^[A-Za-z]:[\\/]/.test(options.outputPath)) {
    throw new Error("V3_PRODUCT_CLOSURE_SMOKE_OUTPUT must be an absolute Windows path");
  }
  const phase = assertPhase(options.phase);
  const baseEvidence: Record<string, unknown> = {
    schema_version: "v3.product-closure-packaged-e2e/1.0.0",
    success: false,
    phase,
    process_id: process.pid,
    app_is_packaged: true,
    electron_version: options.electronVersion,
    app_path: options.appPath,
    resources_path: options.resourcesPath,
    backend_runtime_mode: options.runtime.mode,
    backend_executable: options.runtime.executable,
    backend_working_directory: options.runtime.workingDirectory,
    backend_resource_root: options.runtime.backendResourceRoot,
    backend_python_root: options.runtime.pythonRoot,
    backend_pid: options.supervisor.backendPid,
    build_manifest_id: options.runtime.buildManifestId,
    resource_manifest_sha256: options.runtime.manifestSha256
  };
  try {
    await options.startup;
    await waitForRenderer(options.window);
    const flow = phase === "create-submit"
      ? await runCreateSubmit(options.window)
      : await runReopenDiscover(options.window);
    await writeEvidence(options.outputPath, {
      ...baseEvidence,
      success: true,
      flow,
      shutdown_expected: "GRACEFUL_SHUTDOWN_REQUIRED",
      known_id_injection: false,
      renderer_store_instance: phase === "create-submit" ? "FIRST_PROCESS" : "NEW_PROCESS",
      source_truth_ceiling: "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE"
    });
    console.error(JSON.stringify({ level: "INFO", code: "PRODUCT_CLOSURE_PACKAGED_SMOKE_PASS", phase }));
  } catch (error) {
    await writeEvidence(options.outputPath, {
      ...baseEvidence,
      error: error instanceof Error ? error.message : String(error)
    });
    throw error;
  }
}
