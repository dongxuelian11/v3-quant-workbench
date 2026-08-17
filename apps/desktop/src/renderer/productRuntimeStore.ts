import { create } from "zustand";
import type {
  ArtifactDescriptorView,
  BacktestSubmitOutcomeView,
  ImportResearchPackageOutcomeView,
  ProductBindingRefs,
  ProductCapabilityView,
  ProductResultView,
  ProductStatusView,
  ProductTaskView,
  ProjectsListView,
  RunSpecsListView
} from "../../../../packages/contracts/src/index";

declare global {
  interface Window {
    v3ProductRuntime: import("../../../../packages/contracts/src/index").V3ProductRuntimeBridge;
  }
}

export type ProductSurfaceState =
  | "BACKEND_STARTING"
  | "BACKEND_READY"
  | "BACKEND_DISCONNECTED"
  | "NO_CANONICAL_PROJECT_BOUND"
  | "PROJECT_BOUND"
  | "CANONICAL_RUN_SPEC_REQUIRED"
  | "REQUEST_IN_FLIGHT"
  | "TASK_AVAILABLE"
  | "RESULT_AVAILABLE"
  | "CAPABILITY_UNAVAILABLE"
  | "PRODUCT_OPERATION_SET_INCOMPLETE"
  | "ERROR";

interface ProductRuntimeState {
  surface: ProductSurfaceState;
  status: ProductStatusView | null;
  capabilities: readonly ProductCapabilityView[];
  boundProject: ProductBindingRefs | null;
  projects: ProjectsListView | null;
  runSpecs: RunSpecsListView | null;
  entryBusy: boolean;
  runSpecId: string;
  inflight: boolean;
  lastSubmit: BacktestSubmitOutcomeView | null;
  lastImport: ImportResearchPackageOutcomeView | null;
  task: ProductTaskView | null;
  result: ProductResultView | null;
  artifactDescriptor: ArtifactDescriptorView | null;
  errorMessage: string | null;
  refresh(): Promise<void>;
  setRunSpecId(value: string): void;
  connect(projectId: string, projectContextRevisionId: string): Promise<void>;
  submitRunSpec(): Promise<void>;
  createProjectAndBind(displayName: string, notes?: string): Promise<void>;
  importResearchPackage(): Promise<void>;
}

const RUN_SPEC_PATTERN = /^btrs_sha256_[0-9a-f]{64}$/;

function capabilityOf(capabilities: readonly ProductCapabilityView[], code: string): ProductCapabilityView | undefined {
  return capabilities.find((capability) => capability.code === code);
}

/** Exported for focused tests: the binding-state authority derivation. */
export function deriveSurface(state: {
  status: ProductStatusView | null;
  inflight: boolean;
  result: ProductResultView | null;
  task: ProductTaskView | null;
  runSpecId: string;
}): ProductSurfaceState {
  const backendState = state.status?.backendState ?? "STARTING";
  // The binding state from the canonical product status is the authority:
  // even if a defensively inconsistent status carries a non-null boundProject,
  // BINDING_STALE must never surface as PROJECT_BOUND, TASK_AVAILABLE,
  // RESULT_AVAILABLE, or CANONICAL_RUN_SPEC_REQUIRED.
  const bindingState = state.status?.bindingState ?? "NO_CANONICAL_PROJECT_BOUND";
  if (bindingState === "BINDING_STALE") return "CAPABILITY_UNAVAILABLE";
  if (backendState !== "READY") {
    if (backendState === "DISCONNECTED" || backendState === "CRASH_LOOP") return "BACKEND_DISCONNECTED";
    return "BACKEND_STARTING";
  }
  if (state.status?.boundProject == null) return "NO_CANONICAL_PROJECT_BOUND";
  if (state.inflight) return "REQUEST_IN_FLIGHT";
  if (state.result !== null) return "RESULT_AVAILABLE";
  if (state.task !== null) return "TASK_AVAILABLE";
  if (!RUN_SPEC_PATTERN.test(state.runSpecId)) return "CANONICAL_RUN_SPEC_REQUIRED";
  return "PROJECT_BOUND";
}

export const useProductRuntime = create<ProductRuntimeState>((set, get) => ({
  surface: "BACKEND_STARTING",
  status: null,
  capabilities: [],
  boundProject: null,
  projects: null,
  runSpecs: null,
  entryBusy: false,
  runSpecId: "",
  inflight: false,
  lastSubmit: null,
  lastImport: null,
  task: null,
  result: null,
  artifactDescriptor: null,
  errorMessage: null,

  refresh: async () => {
    const bridge = window.v3ProductRuntime;
    if (!bridge) return;
    try {
      const status = await bridge.getProductStatus();
      const capabilities = status.capabilities;
      const stale = status.bindingState === "BINDING_STALE";
      // Durable entry discovery alongside the status read: projects always,
      // run specs only through the bound project's canonical references.
      const projects = await bridge.listProjects().catch(() => null);
      const runSpecs = status.boundProject !== null
        ? await bridge.listBacktestRunSpecs().catch(() => null)
        : null;
      set((state) => ({
        status,
        capabilities,
        boundProject: status.boundProject,
        projects,
        runSpecs,
        surface: deriveSurface({ ...state, status }),
        // A stale binding must not keep presenting previously-read canonical
        // task/result/artifact state as currently valid product truth.
        ...(stale ? {
          task: null,
          result: null,
          artifactDescriptor: null,
          lastSubmit: null,
          inflight: false,
          errorMessage: "项目绑定已失效 · BINDING_STALE - 需要重新验证并重新绑定 canonical 项目"
        } : { errorMessage: null })
      }));
    } catch (error) {
      set((state) => ({ surface: "BACKEND_DISCONNECTED", errorMessage: describeError(error) ?? state.errorMessage }));
    }
  },

  setRunSpecId: (value) => set((state) => ({ runSpecId: value, surface: deriveSurface({ ...state, runSpecId: value }) })),

  connect: async (projectId, projectContextRevisionId) => {
    const bridge = window.v3ProductRuntime;
    if (!bridge) return;
    try {
      await bridge.connectExistingProject({ projectId, projectContextRevisionId });
      await get().refresh();
    } catch (error) {
      set({ surface: "ERROR", errorMessage: describeError(error) ?? "绑定 canonical 项目失败" });
    }
  },

  submitRunSpec: async () => {
    const bridge = window.v3ProductRuntime;
    const runSpecId = get().runSpecId.trim();
    if (!bridge || !RUN_SPEC_PATTERN.test(runSpecId)) return;
    set((state) => ({ ...state, inflight: true, surface: "REQUEST_IN_FLIGHT", errorMessage: null, task: null, result: null, artifactDescriptor: null, lastSubmit: null }));
    try {
      // submitBacktest is a bounded synchronous in-process executor behind a
      // durable Task: we await the transport request, then re-query canonical
      // Task/Result/Artifact read state. This is REQUEST_IN_FLIGHT, never a
      // claimed live TASK_RUNNING / progress / cancel / resume.
      const outcome = await bridge.submitExistingBacktestRunSpec(runSpecId);
      const task = await bridge.getTask(outcome.taskId);
      let result: ProductResultView | null = null;
      let artifactDescriptor: ArtifactDescriptorView | null = null;
      const resultArtifactId = task.outputs["BACKTEST_RUN_RESULT"];
      if (resultArtifactId) {
        artifactDescriptor = await bridge.getArtifactDescriptor(resultArtifactId).catch(() => null);
      }
      const resultId = await discoverResultId(outcome.taskId);
      if (resultId !== null) {
        result = await bridge.getResult(resultId).catch(() => null);
      }
      set((state) => ({
        inflight: false,
        lastSubmit: outcome,
        task,
        result,
        artifactDescriptor,
        surface: deriveSurface({ ...state, inflight: false, result, task })
      }));
    } catch (error) {
      set({ inflight: false, surface: "ERROR", errorMessage: describeError(error) ?? "执行 canonical 回测失败" });
    }
  },

  createProjectAndBind: async (displayName, notes) => {
    const bridge = window.v3ProductRuntime;
    if (!bridge) return;
    set((state) => ({ ...state, entryBusy: true, errorMessage: null }));
    try {
      // Backend mints every canonical identity; the renderer only supplies
      // bounded display intent. Immediately bind + persist the new project.
      const created = await bridge.createProject({ displayName, ...(notes === undefined ? {} : { notes }) });
      await bridge.connectExistingProject({
        projectId: created.projectId,
        projectContextRevisionId: created.projectContextRevisionId
      });
      await get().refresh();
    } catch (error) {
      set((state) => ({ ...state, surface: "ERROR", errorMessage: describeError(error) ?? "创建 canonical 项目失败" }));
    } finally {
      set((state) => ({ ...state, entryBusy: false }));
    }
  },

  importResearchPackage: async () => {
    const bridge = window.v3ProductRuntime;
    if (!bridge) return;
    set((state) => ({ ...state, entryBusy: true, errorMessage: null }));
    try {
      const outcome = await bridge.importResearchPackage();
      if (outcome === null) {
        set((state) => ({ ...state, entryBusy: false }));
        return;
      }
      set((state) => ({ ...state, lastImport: outcome, runSpecId: outcome.runSpecId }));
      await get().refresh();
    } catch (error) {
      set((state) => ({ ...state, surface: "ERROR", errorMessage: describeError(error) ?? "导入 V3 研究包失败（已拒绝注册）" }));
    } finally {
      set((state) => ({ ...state, entryBusy: false }));
    }
  }
}));

async function discoverResultId(taskId: string): Promise<string | null> {
  const bridge = window.v3ProductRuntime;
  if (!bridge) return null;
  try {
    const events = await bridge.getTaskEvents(0, 500);
    const succeeded = [...events.items].reverse().find((item) => item.eventType === "TASK_SUCCEEDED" && item.resultId !== null);
    return succeeded?.resultId ?? null;
  } catch {
    return null;
  }
}

export function describeError(error: unknown): string | null {
  // The product bridge rejects with the closed structured view object itself
  // (context-bridge-safe structured clone). A legacy { view } envelope or a
  // plain Error is still described honestly without stack details.
  const candidate = (error as { view?: { code?: unknown; message?: unknown } })?.view ?? (error as { code?: unknown; message?: unknown } | null);
  if (candidate !== null && typeof candidate === "object" && typeof (candidate as { message?: unknown }).message === "string") {
    const code = (candidate as { code?: unknown }).code;
    return `${typeof code === "string" && code.length > 0 ? code + " · " : ""}${(candidate as { message: unknown }).message}`;
  }
  if (error instanceof Error) return error.message;
  return null;
}

export function capabilityTruth(capabilities: readonly ProductCapabilityView[], code: string): { truth_state: string; reason_code?: string } {
  const capability = capabilityOf(capabilities, code);
  if (!capability) return { truth_state: "UNAVAILABLE", reason_code: "ASL_FACADE_NOT_BOUND" };
  return { truth_state: capability.truth_state, reason_code: capability.reason_code };
}
