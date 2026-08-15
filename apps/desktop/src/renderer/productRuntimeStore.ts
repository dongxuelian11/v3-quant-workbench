import { create } from "zustand";
import type {
  ArtifactDescriptorView,
  BacktestSubmitOutcomeView,
  ProductBindingRefs,
  ProductCapabilityView,
  ProductResultView,
  ProductStatusView,
  ProductTaskView
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
  runSpecId: string;
  inflight: boolean;
  lastSubmit: BacktestSubmitOutcomeView | null;
  task: ProductTaskView | null;
  result: ProductResultView | null;
  artifactDescriptor: ArtifactDescriptorView | null;
  errorMessage: string | null;
  refresh(): Promise<void>;
  setRunSpecId(value: string): void;
  connect(projectId: string, projectContextRevisionId: string): Promise<void>;
  submitRunSpec(): Promise<void>;
}

const RUN_SPEC_PATTERN = /^btrs_sha256_[0-9a-f]{64}$/;

function capabilityOf(capabilities: readonly ProductCapabilityView[], code: string): ProductCapabilityView | undefined {
  return capabilities.find((capability) => capability.code === code);
}

function deriveSurface(state: {
  status: ProductStatusView | null;
  inflight: boolean;
  result: ProductResultView | null;
  task: ProductTaskView | null;
  runSpecId: string;
}): ProductSurfaceState {
  const backendState = state.status?.backendState ?? "STARTING";
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
  runSpecId: "",
  inflight: false,
  lastSubmit: null,
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
      set((state) => ({
        status,
        capabilities,
        boundProject: status.boundProject,
        surface: deriveSurface({ ...state, status }),
        errorMessage: null
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
  const view = (error as { view?: { code?: string; message?: string } })?.view;
  if (view && typeof view.message === "string") {
    return `${view.code ? view.code + " · " : ""}${view.message}`;
  }
  if (error instanceof Error) return error.message;
  return null;
}

export function capabilityTruth(capabilities: readonly ProductCapabilityView[], code: string): { truth_state: string; reason_code?: string } {
  const capability = capabilityOf(capabilities, code);
  if (!capability) return { truth_state: "UNAVAILABLE", reason_code: "ASL_FACADE_NOT_BOUND" };
  return { truth_state: capability.truth_state, reason_code: capability.reason_code };
}
