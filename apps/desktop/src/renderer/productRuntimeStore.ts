import { create } from "zustand";
import type {
  ArtifactDescriptorView,
  BacktestSubmitOutcomeView,
  ImportResearchPackageOutcomeView,
  ProductResearchSubmitIntent,
  ProductResearchSubmitOutcomeView,
  ProductBindingRefs,
  ProductCapabilityView,
  ProductResultView,
  ProductStatusView,
  ProductTaskView,
  ProjectsListView,
  RunSpecsListView,
  V3ProductRuntimeBridge
} from "../../../../packages/contracts/src/index";

declare global {
  interface Window {
    v3ProductRuntime: import("../../../../packages/contracts/src/index").V3ProductRuntimeBridge;
    v3ProductClosureEvidence?: () => unknown;
    v3ProductClosureRunFirst?: (input: { displayName: string; notes: string; intent: ProductResearchSubmitIntent }) => Promise<void>;
    v3ProductClosureRunUnavailable?: (input: { displayName: string; notes: string; intent: ProductResearchSubmitIntent }) => Promise<void>;
  }
}

export type ProductSurfaceState =
  | "BACKEND_STARTING"
  | "BACKEND_READY"
  | "BACKEND_RECONNECTING"
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

export type ProductResearchDiscoveryState = "NOT_RUN" | "NO_HISTORY" | "RECOVERED" | "ERROR";

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
  lastResearch: ProductResearchSubmitOutcomeView | null;
  researchDiscoveryState: ProductResearchDiscoveryState;
  recoveredResearchTaskId: string | null;
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
  submitResearch(intent: ProductResearchSubmitIntent): Promise<void>;
}

const RUN_SPEC_PATTERN = /^btrs_sha256_[0-9a-f]{64}$/;

export function executableRunSpecSelection(
  specs: RunSpecsListView | null,
  value: string,
): string | null {
  const candidate = value.trim();
  if (!RUN_SPEC_PATTERN.test(candidate)) return null;
  const entry = specs?.specs.find((item) => item.runSpecId === candidate);
  return entry?.status === "EXECUTABLE" ? candidate : null;
}

function capabilityOf(capabilities: readonly ProductCapabilityView[], code: string): ProductCapabilityView | undefined {
  return capabilities.find((capability) => capability.code === code);
}

async function readResearchTaskView(
  bridge: V3ProductRuntimeBridge,
  outcome: ProductResearchSubmitOutcomeView,
): Promise<{
  task: ProductTaskView;
  researchResult: ProductResultView | null;
  artifactDescriptor: ArtifactDescriptorView | null;
}> {
  const task = await bridge.getTask(outcome.taskId);
  const resultArtifactId = task.outputs["BACKTEST_RUN_RESULT"];
  const artifactDescriptor = resultArtifactId
    ? await bridge.getArtifactDescriptor(resultArtifactId).catch(() => null)
    : null;
  const researchResult = task.resultId === null
    ? null
    : await bridge.getResult(task.resultId).catch(() => null);
  return { task, researchResult, artifactDescriptor };
}

const RESEARCH_OPERATION_ID = "ProductEntryService.v1.submitResearch";

type ProductClosureInitialRendererEvidence = Readonly<Pick<
  ProductRuntimeState,
  "lastResearch" | "task" | "result" | "artifactDescriptor"
>>;

export function projectInitialRendererEvidence(
  state: ProductClosureInitialRendererEvidence,
): ProductClosureInitialRendererEvidence {
  return Object.freeze(structuredClone({
    lastResearch: state.lastResearch,
    task: state.task,
    result: state.result,
    artifactDescriptor: state.artifactDescriptor
  }));
}

function compareTaskRecencyDescending(left: ProductTaskView, right: ProductTaskView): number {
  for (const field of ["terminalAt", "updatedAt", "createdAt"] as const) {
    const leftValue = left[field] ?? "";
    const rightValue = right[field] ?? "";
    if (leftValue === rightValue) continue;
    const leftTime = Date.parse(leftValue);
    const rightTime = Date.parse(rightValue);
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return rightTime - leftTime;
    return rightValue.localeCompare(leftValue);
  }
  return right.taskId.localeCompare(left.taskId);
}

/** Select only canonical successful Product Entry tasks for the bound project. */
export function selectLatestResearchTask(tasks: readonly ProductTaskView[], projectId: string): ProductTaskView | null {
  return [...tasks].filter((task) => (
    task.projectId === projectId &&
    task.operationId === RESEARCH_OPERATION_ID &&
    task.state === "SUCCEEDED" &&
    task.resultId !== null &&
    typeof task.outputs["BACKTEST_RUN_RESULT"] === "string" &&
    task.outputs["BACKTEST_RUN_RESULT"].length > 0
  )).sort(compareTaskRecencyDescending)[0] ?? null;
}

async function readDiscoveredResearchTaskView(
  bridge: V3ProductRuntimeBridge,
  candidate: ProductTaskView,
  projectId: string,
): Promise<Awaited<ReturnType<typeof readResearchTaskView>>> {
  const task = await bridge.getTask(candidate.taskId);
  if (task.projectId !== projectId || task.operationId !== RESEARCH_OPERATION_ID || task.state !== "SUCCEEDED") {
    throw new Error("canonical research task no longer matches the bound project or operation");
  }
  const resultId = task.resultId;
  const resultArtifactId = task.outputs["BACKTEST_RUN_RESULT"];
  if (resultId === null || resultArtifactId === undefined) {
    throw new Error("canonical research task is missing its Result or BACKTEST_RUN_RESULT Artifact");
  }
  const [researchResult, artifactDescriptor] = await Promise.all([
    bridge.getResult(resultId),
    bridge.getArtifactDescriptor(resultArtifactId)
  ]);
  if (researchResult.resultId !== resultId || researchResult.projectId !== projectId || researchResult.backtestRunId !== task.runId) {
    throw new Error("canonical research Result identity does not match the selected Task");
  }
  if (artifactDescriptor.artifactId !== resultArtifactId) {
    throw new Error("canonical research Artifact identity does not match the selected Task");
  }
  const resultArtifact = researchResult.resultArtifact;
  if (resultArtifact === null || resultArtifact.artifactId !== artifactDescriptor.artifactId || resultArtifact.sha256 !== artifactDescriptor.sha256 || resultArtifact.byteSize !== artifactDescriptor.byteSize) {
    throw new Error("canonical research Result is missing the exact BACKTEST_RUN_RESULT Artifact");
  }
  return { task, researchResult, artifactDescriptor };
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
    if (backendState === "RECONNECTING") return "BACKEND_RECONNECTING";
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
  lastResearch: null,
  researchDiscoveryState: "NOT_RUN",
  recoveredResearchTaskId: null,
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
      const productEntryCapability = capabilityOf(capabilities, "ProductEntryService");
      const projects = productEntryCapability?.truth_state === "FORMAL"
        ? await bridge.listProjects().catch(() => null)
        : null;
      const runSpecs = status.boundProject !== null
        ? await bridge.listBacktestRunSpecs().catch(() => null)
        : null;
      const current = get();
      const previousResearch = current.lastResearch;
      const coldResearchDiscoveryEligible = previousResearch === null
        && current.lastSubmit === null
        && current.task === null
        && current.result === null
        && current.artifactDescriptor === null;
      let researchReadback: Awaited<ReturnType<typeof readResearchTaskView>> | null = null;
      let researchReadbackError: unknown = null;
      let discoveryError: unknown = null;
      if (!stale && status.boundProject !== null && previousResearch !== null) {
        try {
          const candidate = await readResearchTaskView(bridge, previousResearch);
          if (candidate.task.projectId === status.boundProject.projectId) {
            researchReadback = candidate;
          } else {
            researchReadbackError = new Error("research readback project binding changed");
          }
        } catch (error) {
          researchReadbackError = error;
        }
      } else if (!stale && status.boundProject !== null && coldResearchDiscoveryEligible) {
        try {
          const tasks = await bridge.listTasks({ service: "ProductEntryService", state: "SUCCEEDED" });
          const candidate = selectLatestResearchTask(tasks, status.boundProject.projectId);
          if (candidate !== null) {
            researchReadback = await readDiscoveredResearchTaskView(bridge, candidate, status.boundProject.projectId);
          }
        } catch (error) {
          discoveryError = error;
        }
      }
      set((state) => {
        const base = {
          status,
          capabilities,
          boundProject: status.boundProject,
          projects,
          runSpecs
        };
        if (stale) {
          return {
            ...state,
            ...base,
            task: null,
            result: null,
            artifactDescriptor: null,
            lastSubmit: null,
            inflight: false,
            researchDiscoveryState: "NOT_RUN" as const,
            recoveredResearchTaskId: null,
            surface: deriveSurface({ ...state, ...base, task: null, result: null, inflight: false }),
            errorMessage: "项目绑定已失效 · BINDING_STALE - 需要重新验证并重新绑定 canonical 项目"
          };
        }
        if (previousResearch !== null) {
          const task = researchReadback?.task ?? null;
          const result = researchReadback?.researchResult ?? null;
          return {
            ...state,
            ...base,
            task,
            result,
            artifactDescriptor: researchReadback?.artifactDescriptor ?? null,
            researchDiscoveryState: "NOT_RUN" as const,
            recoveredResearchTaskId: null,
            surface: researchReadbackError === null
              ? deriveSurface({ ...state, ...base, task, result, inflight: false })
              : "ERROR" as const,
            errorMessage: researchReadbackError === null
              ? null
              : describeError(researchReadbackError) ?? "canonical research readback unavailable after reconnect"
          };
        }
        if (coldResearchDiscoveryEligible) {
          if (discoveryError !== null) {
            return {
              ...state,
              ...base,
              task: null,
              result: null,
              artifactDescriptor: null,
              researchDiscoveryState: "ERROR" as const,
              recoveredResearchTaskId: null,
              surface: "ERROR" as const,
              errorMessage: describeError(discoveryError) ?? "canonical historical research recovery unavailable"
            };
          }
          if (researchReadback !== null) {
            const task = researchReadback.task;
            const result = researchReadback.researchResult;
            return {
              ...state,
              ...base,
              task,
              result,
              artifactDescriptor: researchReadback.artifactDescriptor,
              researchDiscoveryState: "RECOVERED" as const,
              recoveredResearchTaskId: task.taskId,
              surface: deriveSurface({ ...state, ...base, task, result, inflight: false }),
              errorMessage: null
            };
          }
          return {
            ...state,
            ...base,
            task: null,
            result: null,
            artifactDescriptor: null,
            researchDiscoveryState: "NO_HISTORY" as const,
            recoveredResearchTaskId: null,
            surface: deriveSurface({ ...state, ...base, task: null, result: null, inflight: false }),
            errorMessage: null
          };
        }
        return {
          ...state,
          ...base,
          surface: deriveSurface({ ...state, ...base })
        };
      });
    } catch (error) {
      set((state) => ({ surface: "BACKEND_DISCONNECTED", errorMessage: describeError(error) ?? state.errorMessage }));
    }
  },
  setRunSpecId: (value) => set((state) => {
    const runSpecId = executableRunSpecSelection(state.runSpecs, value) ?? "";
    return { runSpecId, surface: deriveSurface({ ...state, runSpecId }) };
  }),

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
    const runSpecId = executableRunSpecSelection(get().runSpecs, get().runSpecId);
    if (!bridge || runSpecId === null) return;
    set((state) => ({ ...state, inflight: true, surface: "REQUEST_IN_FLIGHT", errorMessage: null, task: null, result: null, artifactDescriptor: null, lastSubmit: null, researchDiscoveryState: "NOT_RUN" as const, recoveredResearchTaskId: null }));
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
      // Result identity is a direct canonical Task read-model relation. Event
      // pages remain notifications only and cannot choose a result for this
      // task.
      const resultId = task.resultId;
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
      const detail = describeError(error);
      const sourceAuthorityMissing = detail?.includes("SOURCE_AUTHORITY_NOT_VERIFIED") === true;
      set((state) => ({
        ...state,
        surface: "ERROR",
        errorMessage: sourceAuthorityMissing
          ? "SOURCE_AUTHORITY_NOT_VERIFIED · 研究包完整性可验证，但目标端缺少可信来源权威，不能作为可执行研究配置"
          : detail ?? "绑定已验证研究包失败（已拒绝注册）"
      }));
    } finally {
      set((state) => ({ ...state, entryBusy: false }));
    }
  },

  submitResearch: async (intent) => {
    const bridge = window.v3ProductRuntime;
    if (!bridge) return;
    set((state) => ({ ...state, inflight: true, surface: "REQUEST_IN_FLIGHT", errorMessage: null, task: null, result: null, artifactDescriptor: null, lastResearch: null, researchDiscoveryState: "NOT_RUN" as const, recoveredResearchTaskId: null }));
    try {
      const outcome = await bridge.submitResearch(intent);
      const view = await readResearchTaskView(bridge, outcome);
      set((state) => ({
        inflight: false,
        lastResearch: outcome,
        researchDiscoveryState: "NOT_RUN" as const,
        recoveredResearchTaskId: null,
        task: view.task,
        result: view.researchResult,
        artifactDescriptor: view.artifactDescriptor,
        surface: deriveSurface({ ...state, inflight: false, result: view.researchResult, task: view.task })
      }));
    } catch (error) {
      set({ inflight: false, surface: "ERROR", errorMessage: describeError(error) ?? "提交 Product Entry 研究失败" });
    }
  }
}));

export const productClosureInitialRendererEvidence = projectInitialRendererEvidence(
  useProductRuntime.getInitialState(),
);

if (typeof window !== "undefined" && new URLSearchParams(window.location.search).has("v3-product-closure-smoke")) {
  window.v3ProductClosureEvidence = () => {
    const state = useProductRuntime.getState();
    return {
      initialRendererState: productClosureInitialRendererEvidence,
      currentRendererState: {
        lastResearch: state.lastResearch,
        task: state.task,
        result: state.result,
        artifactDescriptor: state.artifactDescriptor,
        researchDiscoveryState: state.researchDiscoveryState,
        recoveredResearchTaskId: state.recoveredResearchTaskId,
        surface: state.surface,
        boundProject: state.boundProject,
        errorMessage: state.errorMessage
      }
    };
  };

  window.v3ProductClosureRunFirst = async (input) => {
    const bridge = window.v3ProductRuntime;
    const readyDeadline = Date.now() + 30_000;
    while (Date.now() < readyDeadline) {
      const status = await bridge.getProductStatus().catch(() => null);
      if (status?.backendState === "READY" && status.bindingState === "NO_CANONICAL_PROJECT_BOUND") break;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    if (Date.now() >= readyDeadline) throw new Error("product closure smoke backend did not become READY before create");
    await new Promise((resolve) => setTimeout(resolve, 1_500));
    await useProductRuntime.getState().createProjectAndBind(input.displayName, input.notes);
    const afterBind = useProductRuntime.getState();
    if (afterBind.boundProject === null || afterBind.errorMessage !== null) {
      throw new Error(afterBind.errorMessage ?? "product closure smoke could not bind canonical Project");
    }
    // One smoke invocation owns exactly one authoritative source request.
    // A single bounded retry, when authorized after preserving the first
    // failure evidence and a cooldown, is orchestrated outside this renderer.
    await useProductRuntime.getState().submitResearch(input.intent);
    const afterSubmit = useProductRuntime.getState();
    if (afterSubmit.lastResearch === null || afterSubmit.task === null || afterSubmit.result === null || afterSubmit.artifactDescriptor === null || afterSubmit.surface !== "RESULT_AVAILABLE") {
      throw new Error(afterSubmit.errorMessage ?? "product closure smoke research did not reach RESULT_AVAILABLE");
    }
  };

  window.v3ProductClosureRunUnavailable = async (input) => {
    const bridge = window.v3ProductRuntime;
    const readyDeadline = Date.now() + 30_000;
    while (Date.now() < readyDeadline) {
      const status = await bridge.getProductStatus().catch(() => null);
      if (status?.backendState === "READY" && status.bindingState === "NO_CANONICAL_PROJECT_BOUND") break;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    if (Date.now() >= readyDeadline) throw new Error("provider-unavailable smoke backend did not become READY before create");
    await new Promise((resolve) => setTimeout(resolve, 1_500));
    await useProductRuntime.getState().createProjectAndBind(input.displayName, input.notes);
    const afterBind = useProductRuntime.getState();
    if (afterBind.boundProject === null || afterBind.errorMessage !== null) {
      throw new Error(afterBind.errorMessage ?? "provider-unavailable smoke could not bind canonical Project");
    }
    await useProductRuntime.getState().submitResearch(input.intent);
    const afterSubmit = useProductRuntime.getState();
    if (afterSubmit.surface !== "ERROR" || afterSubmit.errorMessage === null ||
        !afterSubmit.errorMessage.includes("CAPABILITY_UNAVAILABLE") ||
        !afterSubmit.errorMessage.includes("PROVIDER_ACQUISITION_UNAVAILABLE")) {
      throw new Error(afterSubmit.errorMessage ?? "provider-unavailable smoke did not expose the explicit acquisition failure");
    }
    if (afterSubmit.lastResearch !== null || afterSubmit.task !== null || afterSubmit.result !== null || afterSubmit.artifactDescriptor !== null) {
      throw new Error("provider-unavailable smoke created a renderer-visible successful canonical chain");
    }
  };
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
