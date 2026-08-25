import { create } from "zustand";
import type {
  ArtifactDescriptorView,
  BacktestSubmitOutcomeView,
  ImportResearchPackageOutcomeView,
  LocalDataSourceSelectionView,
  ProductLocalDataImportOutcomeView,
  ProductFactorStudyIntent,
  ProductFactorStudyOutcomeView,
  ProductLatestResultDetailsView,
  ProductProjectHomeView,
  ProductResearchBacktestIntent,
  ProductResearchBacktestOutcomeView,
  ProductResearchBacktestPreviewView,
  ProductResearchStrategyIntent,
  ProductResearchStrategyOutcomeView,
  ProductResearchStrategyPreviewView,
  ProductResearchSubmitIntent,
  ProductResearchSubmitOutcomeView,
  ProductBindingRefs,
  ProductCapabilityView,
  ProductResultView,
  ProductStatusView,
  ProductTaskView,
  ProductTaskProgressView,
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
    v3ProductV11Evidence?: () => unknown;
    v3ProductV11RunJourneyA?: () => Promise<void>;
    v3ProductV11RunJourneyB?: () => Promise<void>;
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

export interface ProjectScope {
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly bindingGeneration: number;
}

export interface ProjectScopeToken extends ProjectScope {
  readonly requestId: string;
}

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
  dataHome: ProductProjectHomeView | null;
  dataTask: ProductTaskView | null;
  localDataSelection: LocalDataSourceSelectionView | null;
  localDataImport: ProductLocalDataImportOutcomeView | null;
  factorStudy: ProductFactorStudyOutcomeView | null;
  factorTask: ProductTaskView | null;
  strategySubmission: ProductResearchStrategyOutcomeView | null;
  strategyPreview: ProductResearchStrategyPreviewView | null;
  strategyPreviewIntent: ProductResearchStrategyIntent | null;
  strategyTask: ProductTaskView | null;
  backtestSubmission: ProductResearchBacktestOutcomeView | null;
  backtestPreview: ProductResearchBacktestPreviewView | null;
  backtestPreviewIntent: ProductResearchBacktestIntent | null;
  backtestTask: ProductTaskView | null;
  backtestProgress: ProductTaskProgressView | null;
  latestProductResult: ProductLatestResultDetailsView | null;
  latestProductResultError: string | null;
  researchDiscoveryState: ProductResearchDiscoveryState;
  recoveredResearchTaskId: string | null;
  task: ProductTaskView | null;
  result: ProductResultView | null;
  artifactDescriptor: ArtifactDescriptorView | null;
  errorMessage: string | null;
  projectScope: ProjectScope | null;
  bindingGeneration: number;
  refresh(): Promise<void>;
  loadNextProjectPage(): Promise<void>;
  loadNextRunSpecPage(): Promise<void>;
  activateProjectScope(refs: ProductBindingRefs | null): void;
  setRunSpecId(value: string): void;
  connect(projectId: string, projectContextRevisionId: string): Promise<void>;
  submitRunSpec(): Promise<void>;
  createProjectAndBind(displayName: string, notes?: string): Promise<void>;
  importResearchPackage(): Promise<void>;
  importLocalData(volumeUnit: "SHARES" | "HANDS"): Promise<void>;
  submitFactorStudy(intent: ProductFactorStudyIntent): Promise<void>;
  previewResearchStrategy(intent: ProductResearchStrategyIntent): Promise<void>;
  publishResearchStrategy(intent: ProductResearchStrategyIntent): Promise<void>;
  previewResearchBacktest(intent: ProductResearchBacktestIntent): Promise<void>;
  submitResearchBacktest(intent: ProductResearchBacktestIntent): Promise<void>;
  retryResearchBacktest(): Promise<void>;
  loadLatestProductResult(): Promise<void>;
  submitResearch(intent: ProductResearchSubmitIntent): Promise<void>;
}

const RUN_SPEC_PATTERN = /^btrs_sha256_[0-9a-f]{64}$/;
const DATA_TASK_POLL_TIMEOUT_MS = 5 * 60_000;
const TASK_EVENT_PAGE_LIMIT = 500;
const RETRYABLE_PRODUCT_BACKTEST_CATEGORIES = new Set([
  "TRANSIENT_IO",
  "WORKER_LOST",
  "PROVIDER_THROTTLED",
  "RETRYABLE_ADAPTER",
  "WORKER_OOM"
]);
let rendererRequestOrdinal = 0;

export function isRetryableProductBacktestTask(task: ProductTaskView | null): boolean {
  return task !== null
    && task.operationId === "ProductEntryService.v1.submitResearchBacktest"
    && (task.state === "FAILED" || task.state === "PARTIAL")
    && task.attempt.attemptId !== null
    && task.attempt.state === "FAILED"
    && task.attempt.errorCategory !== null
    && RETRYABLE_PRODUCT_BACKTEST_CATEGORIES.has(task.attempt.errorCategory);
}

class LateScopeResultDropped extends Error {
  constructor() {
    super("LATE_SCOPE_RESULT_DROPPED");
    this.name = "LateScopeResultDropped";
  }
}

function captureProjectScope(state: Pick<ProductRuntimeState, "projectScope">): ProjectScopeToken | null {
  if (state.projectScope === null) return null;
  rendererRequestOrdinal += 1;
  return Object.freeze({
    ...state.projectScope,
    requestId: `renderer_request_${rendererRequestOrdinal}`
  });
}

function isCurrentProjectScope(state: Pick<ProductRuntimeState, "projectScope">, token: ProjectScopeToken): boolean {
  return state.projectScope !== null
    && state.projectScope.projectId === token.projectId
    && state.projectScope.projectContextRevisionId === token.projectContextRevisionId
    && state.projectScope.bindingGeneration === token.bindingGeneration;
}

function guardProjectScope(token: ProjectScopeToken): void {
  if (!isCurrentProjectScope(useProductRuntime.getState(), token)) throw new LateScopeResultDropped();
}

function recordLateScopeResult(token: ProjectScopeToken): void {
  console.warn(JSON.stringify({
    level: "WARN",
    code: "LATE_SCOPE_RESULT_DROPPED",
    project_id: token.projectId,
    project_context_revision_id: token.projectContextRevisionId,
    binding_generation: token.bindingGeneration,
    request_id: token.requestId
  }));
}

function latestTaskProgress(
  events: Awaited<ReturnType<V3ProductRuntimeBridge["getTaskEvents"]>>,
  taskId: string,
): ProductTaskProgressView | null {
  for (let index = events.items.length - 1; index >= 0; index -= 1) {
    const event = events.items[index];
    if (event?.taskId === taskId && event.progress !== null) return event.progress;
  }
  return null;
}

function sameStrategyIntent(
  left: ProductResearchStrategyIntent | null,
  right: ProductResearchStrategyIntent,
): boolean {
  return left !== null
    && left.entrySignalFactorVersionId === right.entrySignalFactorVersionId
    && left.exitSignalFactorVersionId === right.exitSignalFactorVersionId
    && left.positionSizing === right.positionSizing
    && left.maxPositions === right.maxPositions
    && left.grossExposure === right.grossExposure
    && left.initialCash === right.initialCash
    && left.assumptionProfileId === right.assumptionProfileId;
}

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
  scopeGuard: () => void = () => undefined,
): Promise<{
  task: ProductTaskView;
  researchResult: ProductResultView | null;
  artifactDescriptor: ArtifactDescriptorView | null;
}> {
  const task = await bridge.getTask(outcome.taskId);
  scopeGuard();
  const resultArtifactId = task.outputs["BACKTEST_RUN_RESULT"];
  const artifactDescriptor = resultArtifactId
    ? await bridge.getArtifactDescriptor(resultArtifactId).catch(() => null)
    : null;
  scopeGuard();
  const researchResult = task.resultId === null
    ? null
    : await bridge.getResult(task.resultId).catch(() => null);
  scopeGuard();
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
  scopeGuard: () => void = () => undefined,
): Promise<Awaited<ReturnType<typeof readResearchTaskView>>> {
  const task = await bridge.getTask(candidate.taskId);
  scopeGuard();
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
  scopeGuard();
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
  dataHome?: ProductProjectHomeView | null;
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
  // V1.1 Project Home is the primary product read model. The legacy B3
  // RunSpec selector is a folded compatibility surface and must not downgrade
  // a verified project overview to CANONICAL_RUN_SPEC_REQUIRED.
  if (state.dataHome != null) return "PROJECT_BOUND";
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
  dataHome: null,
  dataTask: null,
  localDataSelection: null,
  localDataImport: null,
  factorStudy: null,
  factorTask: null,
  strategySubmission: null,
  strategyPreview: null,
  strategyPreviewIntent: null,
  strategyTask: null,
  backtestSubmission: null,
  backtestPreview: null,
  backtestPreviewIntent: null,
  backtestTask: null,
  backtestProgress: null,
  latestProductResult: null,
  latestProductResultError: null,
  researchDiscoveryState: "NOT_RUN",
  recoveredResearchTaskId: null,
  task: null,
  result: null,
  artifactDescriptor: null,
  errorMessage: null,
  projectScope: null,
  bindingGeneration: 0,

  activateProjectScope: (refs) => set((state) => {
    const sameScope = refs !== null
      && state.projectScope !== null
      && state.projectScope.projectId === refs.projectId
      && state.projectScope.projectContextRevisionId === refs.projectContextRevisionId
      && state.boundProject?.sessionId === refs.sessionId;
    if (sameScope || (refs === null && state.projectScope === null)) return state;
    const bindingGeneration = state.bindingGeneration + 1;
    const projectScope = refs === null
      ? null
      : Object.freeze({
          projectId: refs.projectId,
          projectContextRevisionId: refs.projectContextRevisionId,
          bindingGeneration
        });
    const status = state.status === null
      ? null
      : {
          ...state.status,
          bindingState: refs === null ? "NO_CANONICAL_PROJECT_BOUND" as const : "PROJECT_BOUND" as const,
          boundProject: refs
        };
    return {
      ...state,
      projectScope,
      bindingGeneration,
      status,
      boundProject: refs,
      runSpecs: null,
      runSpecId: "",
      inflight: false,
      entryBusy: false,
      lastSubmit: null,
      lastImport: null,
      lastResearch: null,
      dataHome: null,
      dataTask: null,
      localDataSelection: null,
      localDataImport: null,
      factorStudy: null,
      factorTask: null,
      strategySubmission: null,
      strategyPreview: null,
      strategyPreviewIntent: null,
      strategyTask: null,
      backtestSubmission: null,
      backtestPreview: null,
      backtestPreviewIntent: null,
      backtestTask: null,
      backtestProgress: null,
      latestProductResult: null,
      latestProductResultError: null,
      researchDiscoveryState: "NOT_RUN" as const,
      recoveredResearchTaskId: null,
      task: null,
      result: null,
      artifactDescriptor: null,
      errorMessage: null,
      surface: refs === null ? "NO_CANONICAL_PROJECT_BOUND" as const : "PROJECT_BOUND" as const
    };
  }),

  refresh: async () => {
    const bridge = window.v3ProductRuntime;
    if (!bridge) return;
    const startingToken = captureProjectScope(get());
    let refreshToken = startingToken;
    try {
      const status = await bridge.getProductStatus();
      if (startingToken !== null) guardProjectScope(startingToken);
      get().activateProjectScope(status.boundProject);
      refreshToken = captureProjectScope(get());
      const capabilities = status.capabilities;
      const stale = status.bindingState === "BINDING_STALE";
      const productEntryCapability = capabilityOf(capabilities, "ProductEntryService");
      const projects = productEntryCapability?.truth_state === "FORMAL"
        ? await bridge.listProjects().catch(() => null)
        : null;
      if (refreshToken !== null) guardProjectScope(refreshToken);
      const runSpecs = status.boundProject !== null
        ? await bridge.listBacktestRunSpecs().catch(() => null)
        : null;
      if (refreshToken !== null) guardProjectScope(refreshToken);
      const current = get();
      let dataHome: ProductProjectHomeView | null = null;
      let dataHomeError: unknown = null;
      let latestProductResult: ProductLatestResultDetailsView | null = null;
      let latestProductResultError: string | null = null;
      if (!stale && status.boundProject !== null && typeof bridge.getProjectHome === "function") {
        try {
          dataHome = await bridge.getProjectHome();
          if (refreshToken !== null) guardProjectScope(refreshToken);
          if (
            dataHome.projectId !== status.boundProject.projectId
            || dataHome.projectContextRevisionId !== status.boundProject.projectContextRevisionId
          ) {
            throw new Error("project home does not match the active project scope");
          }
          if (dataHome.backtestState === "AVAILABLE" && typeof bridge.getLatestProductResultDetails === "function") {
            try {
              latestProductResult = await bridge.getLatestProductResultDetails();
              if (refreshToken !== null) guardProjectScope(refreshToken);
            } catch (error) {
              latestProductResultError = describeError(error) ?? "VALID Result artifact readback unavailable";
            }
          }
        } catch (error) {
          dataHomeError = error;
          dataHome = null;
        }
      }
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
          const candidate = await readResearchTaskView(
            bridge,
            previousResearch,
            () => { if (refreshToken !== null) guardProjectScope(refreshToken); }
          );
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
          const taskPage = await bridge.listTasks({ filter: { service: "ProductEntryService", state: "SUCCEEDED" } });
          if (refreshToken !== null) guardProjectScope(refreshToken);
          const candidate = selectLatestResearchTask(taskPage.tasks, status.boundProject.projectId);
          if (candidate !== null) {
            researchReadback = await readDiscoveredResearchTaskView(
              bridge,
              candidate,
              status.boundProject.projectId,
              () => { if (refreshToken !== null) guardProjectScope(refreshToken); }
            );
          }
        } catch (error) {
          discoveryError = error;
        }
      }
      if (refreshToken !== null) guardProjectScope(refreshToken);
      set((state) => {
        if (refreshToken !== null && !isCurrentProjectScope(state, refreshToken)) return state;
        const base = {
          status,
          capabilities,
          boundProject: status.boundProject,
          projects,
          runSpecs,
          dataHome,
          latestProductResult,
          latestProductResultError
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
        if (dataHomeError !== null) {
          return {
            ...state,
            ...base,
            surface: "ERROR" as const,
            errorMessage: describeError(dataHomeError) ?? "canonical Data readback unavailable"
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
      if (error instanceof LateScopeResultDropped) {
        const dropped = refreshToken ?? startingToken;
        if (dropped !== null) recordLateScopeResult(dropped);
        return;
      }
      set((state) => ({ surface: "BACKEND_DISCONNECTED", errorMessage: describeError(error) ?? state.errorMessage }));
    }
  },

  loadNextProjectPage: async () => {
    const bridge = window.v3ProductRuntime;
    const current = get().projects;
    if (!bridge || current === null || !current.hasMore || current.nextCursor === null) return;
    try {
      const page = await bridge.listProjects({ cursor: current.nextCursor });
      set((state) => state.projects === current ? {
        projects: {
          projects: Object.freeze([...current.projects, ...page.projects.filter((item) => !current.projects.some((prior) => prior.projectId === item.projectId))]),
          hasMore: page.hasMore,
          nextCursor: page.nextCursor
        },
        errorMessage: null
      } : state);
    } catch (error) {
      set((state) => state.projects === current
        ? { surface: "ERROR", errorMessage: describeError(error) ?? "加载更多 canonical 项目失败" }
        : state);
    }
  },

  loadNextRunSpecPage: async () => {
    const bridge = window.v3ProductRuntime;
    const current = get().runSpecs;
    const token = captureProjectScope(get());
    if (!bridge || current === null || !current.hasMore || current.nextCursor === null || token === null) return;
    try {
      const page = await bridge.listBacktestRunSpecs({ cursor: current.nextCursor });
      guardProjectScope(token);
      set((state) => isCurrentProjectScope(state, token) && state.runSpecs === current ? {
        runSpecs: {
          specs: Object.freeze([...current.specs, ...page.specs.filter((item) => !current.specs.some((prior) => prior.artifactId === item.artifactId))]),
          hasMore: page.hasMore,
          nextCursor: page.nextCursor
        },
        errorMessage: null
      } : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token) && state.runSpecs === current
        ? { surface: "ERROR", errorMessage: describeError(error) ?? "加载更多 canonical 研究配置失败" }
        : state);
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
      // The main-process response is emitted only after the active binding
      // commit. Invalidate the prior scope before the additional refs read so
      // no A completion can land in the post-commit/pre-refresh interval.
      get().activateProjectScope(null);
      const refs = await bridge.getBoundProject();
      if (refs === null || refs.projectId !== projectId || refs.projectContextRevisionId !== projectContextRevisionId) {
        throw new Error("committed binding refs did not exactly match the requested project scope");
      }
      get().activateProjectScope(refs);
      await get().refresh();
    } catch (error) {
      set({ surface: "ERROR", errorMessage: describeError(error) ?? "绑定 canonical 项目失败" });
    }
  },

  submitRunSpec: async () => {
    const bridge = window.v3ProductRuntime;
    const runSpecId = executableRunSpecSelection(get().runSpecs, get().runSpecId);
    const token = captureProjectScope(get());
    if (!bridge || runSpecId === null || token === null) return;
    set((state) => isCurrentProjectScope(state, token)
      ? { ...state, inflight: true, surface: "REQUEST_IN_FLIGHT", errorMessage: null, task: null, result: null, artifactDescriptor: null, lastSubmit: null, researchDiscoveryState: "NOT_RUN" as const, recoveredResearchTaskId: null }
      : state);
    try {
      // submitBacktest is a bounded synchronous in-process executor behind a
      // durable Task: we await the transport request, then re-query canonical
      // Task/Result/Artifact read state. This is REQUEST_IN_FLIGHT, never a
      // claimed live TASK_RUNNING / progress / cancel / resume.
      const outcome = await bridge.submitExistingBacktestRunSpec(runSpecId);
      guardProjectScope(token);
      const task = await bridge.getTask(outcome.taskId);
      guardProjectScope(token);
      let result: ProductResultView | null = null;
      let artifactDescriptor: ArtifactDescriptorView | null = null;
      const resultArtifactId = task.outputs["BACKTEST_RUN_RESULT"];
      if (resultArtifactId) {
        artifactDescriptor = await bridge.getArtifactDescriptor(resultArtifactId).catch(() => null);
        guardProjectScope(token);
      }
      // Result identity is a direct canonical Task read-model relation. Event
      // pages remain notifications only and cannot choose a result for this
      // task.
      const resultId = task.resultId;
      if (resultId !== null) {
        result = await bridge.getResult(resultId).catch(() => null);
        guardProjectScope(token);
      }
      set((state) => isCurrentProjectScope(state, token)
        ? {
            inflight: false,
            lastSubmit: outcome,
            task,
            result,
            artifactDescriptor,
            surface: deriveSurface({ ...state, inflight: false, result, task })
          }
        : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { inflight: false, surface: "ERROR", errorMessage: describeError(error) ?? "执行 canonical 回测失败" }
        : state);
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
      get().activateProjectScope(null);
      const refs = await bridge.getBoundProject();
      if (refs === null || refs.projectId !== created.projectId || refs.projectContextRevisionId !== created.projectContextRevisionId) {
        throw new Error("new project binding refs did not exactly match the created canonical project");
      }
      get().activateProjectScope(refs);
      await get().refresh();
    } catch (error) {
      set((state) => ({ ...state, surface: "ERROR", errorMessage: describeError(error) ?? "创建 canonical 项目失败" }));
    } finally {
      set((state) => ({ ...state, entryBusy: false }));
    }
  },

  importResearchPackage: async () => {
    const bridge = window.v3ProductRuntime;
    const token = captureProjectScope(get());
    if (!bridge || token === null) return;
    set((state) => isCurrentProjectScope(state, token)
      ? { ...state, entryBusy: true, errorMessage: null }
      : state);
    try {
      const outcome = await bridge.importResearchPackage();
      guardProjectScope(token);
      if (outcome === null) {
        set((state) => isCurrentProjectScope(state, token) ? { ...state, entryBusy: false } : state);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, lastImport: outcome, runSpecId: outcome.runSpecId }
        : state);
      await get().refresh();
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      const detail = describeError(error);
      const sourceAuthorityMissing = detail?.includes("SOURCE_AUTHORITY_NOT_VERIFIED") === true;
      set((state) => isCurrentProjectScope(state, token)
        ? {
            ...state,
            surface: "ERROR",
            errorMessage: sourceAuthorityMissing
              ? "SOURCE_AUTHORITY_NOT_VERIFIED · 研究包完整性可验证，但目标端缺少可信来源权威，不能作为可执行研究配置"
              : detail ?? "绑定已验证研究包失败（已拒绝注册）"
          }
        : state);
    } finally {
      set((state) => isCurrentProjectScope(state, token) ? { ...state, entryBusy: false } : state);
    }
  },

  importLocalData: async (volumeUnit) => {
    const bridge = window.v3ProductRuntime;
    const token = captureProjectScope(get());
    if (!bridge || token === null) return;
    set((state) => isCurrentProjectScope(state, token)
      ? {
          ...state,
          entryBusy: true,
          errorMessage: null,
          dataTask: null,
          localDataSelection: null,
          localDataImport: null,
          factorStudy: null,
          factorTask: null,
          strategySubmission: null,
          strategyPreview: null,
          strategyPreviewIntent: null,
          strategyTask: null,
          backtestSubmission: null,
          backtestPreview: null,
          backtestPreviewIntent: null,
          backtestTask: null,
          backtestProgress: null,
          latestProductResult: null,
          latestProductResultError: null
        }
      : state);
    try {
      const selection = await bridge.chooseLocalDataSource();
      guardProjectScope(token);
      if (selection === null) return;
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, localDataSelection: selection }
        : state);
      const outcome = await bridge.importLocalDataset({
        capabilityToken: selection.capabilityToken,
        volumeUnit,
        amountUnit: "CNY",
        timezone: "Asia/Shanghai",
        adjustment: "UNADJUSTED"
      });
      guardProjectScope(token);
      const deadline = Date.now() + DATA_TASK_POLL_TIMEOUT_MS;
      let task: ProductTaskView;
      while (true) {
        task = await bridge.getTask(outcome.taskId);
        guardProjectScope(token);
        if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(task.state)) break;
        if (Date.now() >= deadline) throw new Error("LOCAL_DATA_IMPORT_TASK_TIMEOUT");
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      if (task.projectId !== token.projectId || task.operationId !== "ProductEntryService.v1.importLocalDataset") {
        throw new Error("local-data Task scope or operation does not match the accepted import");
      }
      if (task.state !== "SUCCEEDED") throw new Error(`LOCAL_DATA_IMPORT_${task.state}`);
      const nextRevisionId = task.outputs.project_context_revision_id;
      const snapshotId = task.outputs.snapshot_id;
      if (typeof nextRevisionId !== "string" || !nextRevisionId.startsWith("pcr_") || typeof snapshotId !== "string" || snapshotId.length < 1) {
        throw new Error("local-data Task did not publish the required canonical context outputs");
      }
      guardProjectScope(token);
      await bridge.connectExistingProject({
        projectId: token.projectId,
        projectContextRevisionId: nextRevisionId
      });
      get().activateProjectScope(null);
      const refs = await bridge.getBoundProject();
      if (refs === null || refs.projectId !== token.projectId || refs.projectContextRevisionId !== nextRevisionId) {
        throw new Error("imported Data context was not atomically adopted by the Product binding");
      }
      get().activateProjectScope(refs);
      const home = await bridge.getProjectHome();
      const active = get().projectScope;
      if (
        active === null
        || active.projectId !== home.projectId
        || active.projectContextRevisionId !== home.projectContextRevisionId
        || home.projectContextRevisionId !== nextRevisionId
        || home.dataState !== "AVAILABLE"
        || home.data?.snapshotId !== snapshotId
      ) {
        throw new Error("canonical Data readback does not match the imported Task outputs");
      }
      set((state) => state.projectScope !== null
        && state.projectScope.projectId === refs.projectId
        && state.projectScope.projectContextRevisionId === refs.projectContextRevisionId
        ? {
            ...state,
            dataHome: home,
            dataTask: task,
            localDataSelection: selection,
            localDataImport: outcome,
            surface: "PROJECT_BOUND" as const,
            errorMessage: null
          }
        : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: describeError(error) ?? "导入本地数据失败" }
        : state);
    } finally {
      set((state) => state.projectScope?.projectId === token.projectId
        ? { ...state, entryBusy: false }
        : state);
    }
  },

  submitFactorStudy: async (intent) => {
    const bridge = window.v3ProductRuntime;
    const token = captureProjectScope(get());
    if (!bridge || token === null) return;
    const currentHome = get().dataHome;
    if (currentHome?.dataState !== "AVAILABLE" || currentHome.data === null) {
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: "FACTOR_REQUIRES_AVAILABLE_SNAPSHOT" }
        : state);
      return;
    }
    set((state) => isCurrentProjectScope(state, token)
      ? {
          ...state,
          entryBusy: true,
          errorMessage: null,
          factorStudy: null,
          factorTask: null,
          strategySubmission: null,
          strategyPreview: null,
          strategyPreviewIntent: null,
          strategyTask: null,
          backtestSubmission: null,
          backtestPreview: null,
          backtestPreviewIntent: null,
          backtestTask: null,
          backtestProgress: null,
          latestProductResult: null,
          latestProductResultError: null
        }
      : state);
    try {
      const outcome = await bridge.submitFactorStudy(intent);
      guardProjectScope(token);
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, factorStudy: outcome }
        : state);
      const deadline = Date.now() + DATA_TASK_POLL_TIMEOUT_MS;
      let task: ProductTaskView;
      while (true) {
        task = await bridge.getTask(outcome.taskId);
        guardProjectScope(token);
        set((state) => isCurrentProjectScope(state, token)
          ? { ...state, factorTask: task }
          : state);
        if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(task.state)) break;
        if (Date.now() >= deadline) throw new Error("FACTOR_STUDY_TASK_TIMEOUT");
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      if (task.projectId !== token.projectId || task.operationId !== "ProductEntryService.v1.submitFactorStudy") {
        throw new Error("Factor Task scope or operation does not match the accepted study");
      }
      if (task.state !== "SUCCEEDED") throw new Error(`FACTOR_STUDY_${task.state}`);
      if (task.outputs.formula_document_version_id !== outcome.formulaDocumentVersionId) {
        throw new Error("Factor Task FormulaDocument identity does not match acceptance");
      }
      const home = await bridge.getProjectHome();
      guardProjectScope(token);
      if (
        home.projectId !== token.projectId
        || home.projectContextRevisionId !== token.projectContextRevisionId
        || home.factorState !== "AVAILABLE"
        || home.factor === null
        || home.factor.snapshotId !== currentHome.data.snapshotId
        || home.factor.formulaDocumentVersionId !== outcome.formulaDocumentVersionId
      ) {
        throw new Error("canonical Factor readback does not match the accepted Task");
      }
      set((state) => isCurrentProjectScope(state, token)
        ? {
            ...state,
            dataHome: home,
            factorStudy: outcome,
            factorTask: task,
            surface: "PROJECT_BOUND" as const,
            errorMessage: null
          }
        : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: describeError(error) ?? "因子研究失败" }
        : state);
    } finally {
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, entryBusy: false }
        : state);
    }
  },

  previewResearchStrategy: async (intent) => {
    const bridge = window.v3ProductRuntime;
    const token = captureProjectScope(get());
    if (!bridge || token === null) return;
    const currentHome = get().dataHome;
    if (currentHome?.factorState !== "AVAILABLE" || currentHome.factor === null) {
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: "STRATEGY_REQUIRES_AVAILABLE_FACTOR" }
        : state);
      return;
    }
    set((state) => isCurrentProjectScope(state, token)
      ? { ...state, entryBusy: true, errorMessage: null, strategyPreview: null, strategyPreviewIntent: null }
      : state);
    try {
      const preview = await bridge.previewResearchStrategy(intent);
      guardProjectScope(token);
      if (
        preview.projectId !== token.projectId
        || preview.projectContextRevisionId !== token.projectContextRevisionId
        || preview.snapshotId !== currentHome.data?.snapshotId
        || preview.entrySignalFactorVersionId !== intent.entrySignalFactorVersionId
        || preview.exitSignalFactorVersionId !== intent.exitSignalFactorVersionId
        || preview.sideEffects !== "NONE"
      ) {
        throw new Error("STRATEGY_PREVIEW_SCOPE_OR_INPUT_DRIFT");
      }
      set((state) => isCurrentProjectScope(state, token)
        ? {
            ...state,
            strategyPreview: preview,
            strategyPreviewIntent: Object.freeze({ ...intent }),
            surface: "PROJECT_BOUND",
            errorMessage: null
          }
        : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: describeError(error) ?? "策略验证预览失败" }
        : state);
    } finally {
      set((state) => isCurrentProjectScope(state, token) ? { ...state, entryBusy: false } : state);
    }
  },

  publishResearchStrategy: async (intent) => {
    const bridge = window.v3ProductRuntime;
    const token = captureProjectScope(get());
    if (!bridge || token === null) return;
    const currentHome = get().dataHome;
    if (currentHome?.factorState !== "AVAILABLE" || currentHome.factor === null) {
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: "STRATEGY_REQUIRES_AVAILABLE_FACTOR" }
        : state);
      return;
    }
    if (get().strategyPreview === null || !sameStrategyIntent(get().strategyPreviewIntent, intent)) {
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: "STRATEGY_PREVIEW_REQUIRED" }
        : state);
      return;
    }
    set((state) => isCurrentProjectScope(state, token)
      ? { ...state, entryBusy: true, errorMessage: null, strategySubmission: null, strategyTask: null, backtestPreview: null, backtestPreviewIntent: null, latestProductResult: null, latestProductResultError: null }
      : state);
    try {
      const outcome = await bridge.publishResearchStrategy(intent);
      guardProjectScope(token);
      set((state) => isCurrentProjectScope(state, token) ? { ...state, strategySubmission: outcome } : state);
      const deadline = Date.now() + DATA_TASK_POLL_TIMEOUT_MS;
      let task: ProductTaskView;
      while (true) {
        task = await bridge.getTask(outcome.taskId);
        guardProjectScope(token);
        set((state) => isCurrentProjectScope(state, token) ? { ...state, strategyTask: task } : state);
        if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(task.state)) break;
        if (Date.now() >= deadline) throw new Error("STRATEGY_PUBLICATION_TASK_TIMEOUT");
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      if (task.projectId !== token.projectId || task.operationId !== "ProductEntryService.v1.publishResearchStrategy") {
        throw new Error("Strategy Task scope or operation does not match acceptance");
      }
      if (task.state !== "SUCCEEDED") throw new Error(`STRATEGY_PUBLICATION_${task.state}`);
      const home = await bridge.getProjectHome();
      guardProjectScope(token);
      if (home.projectId !== token.projectId || home.projectContextRevisionId !== token.projectContextRevisionId
        || home.strategyState !== "AVAILABLE" || home.strategy?.researchStrategySpecId !== outcome.researchStrategySpecId) {
        throw new Error("canonical Strategy readback does not match the accepted Task");
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, dataHome: home, strategySubmission: outcome, strategyTask: task, strategyPreview: null, strategyPreviewIntent: null, backtestSubmission: null, backtestPreview: null, backtestPreviewIntent: null, backtestTask: null, backtestProgress: null, latestProductResult: null, latestProductResultError: null, surface: "PROJECT_BOUND", errorMessage: null }
        : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: describeError(error) ?? "发布研究策略失败" }
        : state);
    } finally {
      set((state) => isCurrentProjectScope(state, token) ? { ...state, entryBusy: false } : state);
    }
  },

  previewResearchBacktest: async (intent) => {
    const bridge = window.v3ProductRuntime;
    const token = captureProjectScope(get());
    if (!bridge || token === null) return;
    set((state) => isCurrentProjectScope(state, token)
      ? { ...state, entryBusy: true, errorMessage: null, backtestPreview: null, backtestPreviewIntent: null }
      : state);
    try {
      const preview = await bridge.previewResearchBacktest(intent);
      guardProjectScope(token);
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, backtestPreview: preview, backtestPreviewIntent: Object.freeze({ ...intent }), surface: "PROJECT_BOUND", errorMessage: null }
        : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, backtestPreview: null, backtestPreviewIntent: null, surface: "ERROR", errorMessage: describeError(error) ?? "回测预检失败" }
        : state);
    } finally {
      set((state) => isCurrentProjectScope(state, token) ? { ...state, entryBusy: false } : state);
    }
  },

  submitResearchBacktest: async (intent) => {
    const bridge = window.v3ProductRuntime;
    const token = captureProjectScope(get());
    if (!bridge || token === null) return;
    if (get().dataHome?.strategyState !== "AVAILABLE") {
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: "BACKTEST_REQUIRES_AVAILABLE_STRATEGY" }
        : state);
      return;
    }
    set((state) => isCurrentProjectScope(state, token)
      ? { ...state, entryBusy: true, errorMessage: null, backtestSubmission: null, backtestTask: null, backtestProgress: null, latestProductResult: null, latestProductResultError: null }
      : state);
    try {
      const outcome = await bridge.submitResearchBacktest(intent);
      guardProjectScope(token);
      set((state) => isCurrentProjectScope(state, token) ? { ...state, backtestSubmission: outcome } : state);
      const deadline = Date.now() + DATA_TASK_POLL_TIMEOUT_MS;
      let eventAfter = Math.max(0, (outcome.eventCursor ?? 0) - TASK_EVENT_PAGE_LIMIT);
      let task: ProductTaskView;
      while (true) {
        task = await bridge.getTask(outcome.taskId);
        guardProjectScope(token);
        const events = await bridge.getTaskEvents(eventAfter, TASK_EVENT_PAGE_LIMIT);
        guardProjectScope(token);
        eventAfter = events.highWatermark;
        const observedProgress = latestTaskProgress(events, outcome.taskId);
        set((state) => isCurrentProjectScope(state, token)
          ? { ...state, backtestTask: task, backtestProgress: observedProgress ?? state.backtestProgress }
          : state);
        if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(task.state)) break;
        if (Date.now() >= deadline) throw new Error("RESEARCH_BACKTEST_TASK_TIMEOUT");
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      if (task.projectId !== token.projectId || task.operationId !== "ProductEntryService.v1.submitResearchBacktest") {
        throw new Error("Backtest Task scope or operation does not match acceptance");
      }
      if (task.state !== "SUCCEEDED") throw new Error(`RESEARCH_BACKTEST_${task.state}`);
      const home = await bridge.getProjectHome();
      guardProjectScope(token);
      if (home.projectId !== token.projectId || home.projectContextRevisionId !== token.projectContextRevisionId
        || home.backtestState !== "AVAILABLE" || home.backtest === null || home.backtest.resultState !== "VALID") {
        throw new Error("canonical VALID Result is unavailable after Backtest Task success");
      }
      const details = await bridge.getLatestProductResultDetails();
      guardProjectScope(token);
      if (details.resultId !== home.backtest.resultId || details.backtestResultId !== home.backtest.backtestResultId) {
        throw new Error("Result details do not match the latest VALID Home summary");
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, dataHome: home, backtestSubmission: outcome, backtestTask: task, backtestProgress: state.backtestProgress, latestProductResult: details, latestProductResultError: null, surface: "PROJECT_BOUND", errorMessage: null }
        : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: describeError(error) ?? "研究回测失败" }
        : state);
    } finally {
      set((state) => isCurrentProjectScope(state, token) ? { ...state, entryBusy: false } : state);
    }
  },

  retryResearchBacktest: async () => {
    const bridge = window.v3ProductRuntime;
    const token = captureProjectScope(get());
    const failedTask = get().backtestTask;
    if (!bridge || token === null || failedTask === null || !isRetryableProductBacktestTask(failedTask)) return;
    set((state) => isCurrentProjectScope(state, token)
      ? { ...state, entryBusy: true, errorMessage: null, backtestProgress: null, latestProductResult: null, latestProductResultError: null }
      : state);
    try {
      let task = await bridge.retryResearchBacktest(failedTask.taskId);
      guardProjectScope(token);
      if (
        task.taskId !== failedTask.taskId
        || task.runId !== failedTask.runId
        || task.projectId !== token.projectId
        || task.operationId !== "ProductEntryService.v1.submitResearchBacktest"
        || task.attempt.ordinal !== failedTask.attempt.ordinal + 1
      ) {
        throw new Error("Backtest retry identity does not match the persisted failed Task");
      }
      const deadline = Date.now() + DATA_TASK_POLL_TIMEOUT_MS;
      let eventAfter = 0;
      while (true) {
        const events = await bridge.getTaskEvents(eventAfter, TASK_EVENT_PAGE_LIMIT);
        guardProjectScope(token);
        eventAfter = events.highWatermark;
        const observedProgress = latestTaskProgress(events, task.taskId);
        set((state) => isCurrentProjectScope(state, token)
          ? { ...state, backtestTask: task, backtestProgress: observedProgress ?? state.backtestProgress }
          : state);
        if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(task.state)) break;
        if (Date.now() >= deadline) throw new Error("RESEARCH_BACKTEST_RETRY_TIMEOUT");
        await new Promise((resolve) => setTimeout(resolve, 200));
        task = await bridge.getTask(task.taskId);
        guardProjectScope(token);
      }
      set((state) => isCurrentProjectScope(state, token) ? { ...state, backtestTask: task } : state);
      if (task.state !== "SUCCEEDED") throw new Error(`RESEARCH_BACKTEST_RETRY_${task.state}`);
      const home = await bridge.getProjectHome();
      guardProjectScope(token);
      if (
        home.projectId !== token.projectId
        || home.projectContextRevisionId !== token.projectContextRevisionId
        || home.backtestState !== "AVAILABLE"
        || home.backtest === null
        || home.backtest.resultState !== "VALID"
        || home.backtest.runId !== task.runId
      ) {
        throw new Error("canonical VALID Result is unavailable after Backtest retry success");
      }
      const details = await bridge.getLatestProductResultDetails();
      guardProjectScope(token);
      if (details.resultId !== home.backtest.resultId || details.backtestResultId !== home.backtest.backtestResultId) {
        throw new Error("retried Result details do not match the latest VALID Home summary");
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, dataHome: home, backtestTask: task, latestProductResult: details, latestProductResultError: null, surface: "PROJECT_BOUND", errorMessage: null }
        : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, surface: "ERROR", errorMessage: describeError(error) ?? "研究回测从头重试失败" }
        : state);
    } finally {
      set((state) => isCurrentProjectScope(state, token) ? { ...state, entryBusy: false } : state);
    }
  },

  loadLatestProductResult: async () => {
    const bridge = window.v3ProductRuntime;
    const token = captureProjectScope(get());
    if (!bridge || token === null) return;
    set((state) => isCurrentProjectScope(state, token)
      ? { ...state, latestProductResultError: null }
      : state);
    try {
      const details = await bridge.getLatestProductResultDetails();
      guardProjectScope(token);
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, latestProductResult: details, latestProductResultError: null }
        : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { ...state, latestProductResult: null, latestProductResultError: describeError(error) ?? "VALID Result artifact readback unavailable" }
        : state);
    }
  },

  submitResearch: async (intent) => {
    const bridge = window.v3ProductRuntime;
    if (!bridge) return;
    const token = captureProjectScope(get());
    if (token === null) return;
    set((state) => isCurrentProjectScope(state, token)
      ? { ...state, inflight: true, surface: "REQUEST_IN_FLIGHT", errorMessage: null, task: null, result: null, artifactDescriptor: null, lastResearch: null, researchDiscoveryState: "NOT_RUN" as const, recoveredResearchTaskId: null }
      : state);
    try {
      const outcome = await bridge.submitResearch(intent);
      guardProjectScope(token);
      const view = await readResearchTaskView(bridge, outcome, () => guardProjectScope(token));
      set((state) => isCurrentProjectScope(state, token)
        ? {
            inflight: false,
            lastResearch: outcome,
            researchDiscoveryState: "NOT_RUN" as const,
            recoveredResearchTaskId: null,
            task: view.task,
            result: view.researchResult,
            artifactDescriptor: view.artifactDescriptor,
            surface: deriveSurface({ ...state, inflight: false, result: view.researchResult, task: view.task })
          }
        : state);
    } catch (error) {
      if (error instanceof LateScopeResultDropped || !isCurrentProjectScope(get(), token)) {
        recordLateScopeResult(token);
        return;
      }
      set((state) => isCurrentProjectScope(state, token)
        ? { inflight: false, surface: "ERROR", errorMessage: describeError(error) ?? "提交 Product Entry 研究失败" }
        : state);
    }
  }
}));

export const productClosureInitialRendererEvidence = projectInitialRendererEvidence(
  useProductRuntime.getInitialState(),
);

const V1_1_GOLDEN_FORMULA = `MJ:=AMOUNT/VOL/100;
MA5:=MA(MJ,5);
MA20:=MA(MJ,20);
MA60:=MA(MJ,60);
GOLDEN_CROSS:CROSS(MA20,MA60) AND MA5>MA20;
DEATH_CROSS:CROSS(MA60,MA20) AND MA5<MA20;
`;

async function waitForProductReadyWithoutBinding(): Promise<void> {
  const bridge = window.v3ProductRuntime;
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const status = await bridge.getProductStatus().catch(() => null);
    if (status?.backendState === "READY" && status.bindingState === "NO_CANONICAL_PROJECT_BOUND") return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("V1.1 packaged journey backend did not become READY before Project creation");
}

function requireV11State(label: string): ProductRuntimeState {
  const state = useProductRuntime.getState();
  if (state.errorMessage !== null || state.surface === "ERROR") {
    throw new Error(`${label}: ${state.errorMessage ?? "renderer entered ERROR"}`);
  }
  return state;
}

function projectV11Evidence(state: ProductRuntimeState): Record<string, unknown> {
  const home = state.dataHome;
  const factor = home?.factor ?? null;
  const analysis = factor?.analysis ?? null;
  const firstAvailableDaily = analysis?.dailyResults.find((item) => item.status === "AVAILABLE") ?? null;
  return {
    surface: state.surface,
    boundProject: state.boundProject,
    projectScope: state.projectScope,
    errorMessage: state.errorMessage,
    data: home?.data ?? null,
    factor: factor === null ? null : {
      snapshotId: factor.snapshotId,
      universeVersionId: factor.universeVersionId,
      formulaDocumentVersionId: factor.formulaDocumentVersionId,
      outputs: factor.outputs,
      analysisOutputName: factor.analysisOutputName,
      analysisArtifactId: factor.analysisArtifactId,
      aggregate: analysis?.aggregate ?? null,
      dailyResultCount: analysis?.dailyResults.length ?? 0,
      firstAvailableDaily,
    },
    strategy: home?.strategy ?? null,
    backtest: home?.backtest ?? null,
    policyCoverage: home?.backtestPolicyCoverage ?? null,
    localDataTask: state.dataTask === null ? null : {
      taskId: state.dataTask.taskId,
      runId: state.dataTask.runId,
      state: state.dataTask.state,
      operationId: state.dataTask.operationId,
    },
    factorTask: state.factorTask === null ? null : {
      taskId: state.factorTask.taskId,
      runId: state.factorTask.runId,
      state: state.factorTask.state,
      operationId: state.factorTask.operationId,
    },
    strategyTask: state.strategyTask === null ? null : {
      taskId: state.strategyTask.taskId,
      runId: state.strategyTask.runId,
      state: state.strategyTask.state,
      operationId: state.strategyTask.operationId,
    },
    backtestTask: state.backtestTask === null ? null : {
      taskId: state.backtestTask.taskId,
      runId: state.backtestTask.runId,
      state: state.backtestTask.state,
      operationId: state.backtestTask.operationId,
    },
    result: state.latestProductResult === null ? null : {
      resultState: state.latestProductResult.resultState,
      resultId: state.latestProductResult.resultId,
      backtestResultId: state.latestProductResult.backtestResultId,
      analyticsId: state.latestProductResult.analyticsId,
      resultLineageId: state.latestProductResult.resultLineageId,
      runId: state.latestProductResult.runId,
      assumptionMode: state.latestProductResult.assumptionMode,
      orderCount: state.latestProductResult.orders.rowCount,
      fillCount: state.latestProductResult.fills.rowCount,
      diagnosticCount: state.latestProductResult.diagnostics.rowCount,
      holdingCount: state.latestProductResult.holdings.rowCount,
      metrics: state.latestProductResult.metrics,
      costSummary: state.latestProductResult.costSummary,
      lineage: state.latestProductResult.lineage,
      exports: state.latestProductResult.exports,
    },
  };
}

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

  window.v3ProductV11Evidence = () => projectV11Evidence(useProductRuntime.getState());

  window.v3ProductV11RunJourneyA = async () => {
    await waitForProductReadyWithoutBinding();
    await useProductRuntime.getState().createProjectAndBind("我的第一个量化项目", "V1.1 packaged Golden Journey A");
    requireV11State("Journey A Project activation");
    await useProductRuntime.getState().importLocalData("SHARES");
    requireV11State("Journey A local Data import");
    await useProductRuntime.getState().submitFactorStudy({
      formulaSource: V1_1_GOLDEN_FORMULA,
      analysisOutputName: "MJ",
    });
    let state = requireV11State("Journey A Factor study");
    const factor = state.dataHome?.factor;
    if (state.dataHome?.data?.instrumentCount !== 1 || factor === null || factor === undefined) {
      throw new Error("Journey A did not publish a single-instrument Data/Factor read model");
    }
    const aggregate = factor.analysis.aggregate;
    if (
      aggregate.icMean.status !== "INSUFFICIENT_SAMPLE"
      || aggregate.rankIcMean.status !== "INSUFFICIENT_SAMPLE"
      || aggregate.icMean.reason !== "CROSS_SECTION_REQUIRES_AT_LEAST_20_INSTRUMENTS"
    ) {
      throw new Error("Journey A did not preserve single-symbol cross-sectional honesty");
    }
    const entry = factor.outputs.find((item) => item.name === "GOLDEN_CROSS" && item.outputType === "BOOLEAN_SERIES");
    const exit = factor.outputs.find((item) => item.name === "DEATH_CROSS" && item.outputType === "BOOLEAN_SERIES");
    const profile = state.dataHome?.strategyAuthoringProfile;
    const approximate = profile?.assumptionProfiles.find((item) => item.mode === "RESEARCH_APPROXIMATE");
    if (entry === undefined || exit === undefined || profile === undefined || approximate === undefined) {
      throw new Error("Journey A canonical Strategy inputs are unavailable");
    }
    const strategyIntent: ProductResearchStrategyIntent = {
      entrySignalFactorVersionId: entry.factorDefinitionVersionId,
      exitSignalFactorVersionId: exit.factorDefinitionVersionId,
      positionSizing: "SINGLE_ASSET_FULL_WEIGHT",
      maxPositions: 1,
      grossExposure: "1",
      initialCash: "1000000",
      assumptionProfileId: approximate.assumptionProfileId,
    };
    await useProductRuntime.getState().previewResearchStrategy(strategyIntent);
    requireV11State("Journey A Strategy preview");
    await useProductRuntime.getState().publishResearchStrategy(strategyIntent);
    state = requireV11State("Journey A Strategy publication");
    const home = state.dataHome;
    if (home?.data === null || home?.data === undefined || home.strategyState !== "AVAILABLE") {
      throw new Error("Journey A canonical Strategy read model is unavailable");
    }
    const sessionStart = home.data.dateCoverageStart > home.backtestPolicyCoverage.coverageStart
      ? home.data.dateCoverageStart
      : home.backtestPolicyCoverage.coverageStart;
    const sessionEnd = home.backtestPolicyCoverage.coverageEnd !== null
      && home.backtestPolicyCoverage.coverageEnd < home.data.dateCoverageEnd
      ? home.backtestPolicyCoverage.coverageEnd
      : home.data.dateCoverageEnd;
    const backtestIntent: ProductResearchBacktestIntent = {
      sessionStart,
      sessionEnd,
      slippageBps: "10",
      dailyVolumeParticipationRate: "0.1",
    };
    await useProductRuntime.getState().previewResearchBacktest(backtestIntent);
    requireV11State("Journey A Backtest preflight");
    await useProductRuntime.getState().submitResearchBacktest(backtestIntent);
    state = requireV11State("Journey A Backtest");
    if (
      state.dataHome?.backtestState !== "AVAILABLE"
      || state.dataHome.backtest?.resultState !== "VALID"
      || state.latestProductResult?.resultState !== "VALID"
      || state.latestProductResult.orders.rowCount < 1
      || state.latestProductResult.fills.rowCount < 1
    ) {
      throw new Error("Journey A did not reach a canonical VALID Result with real orders/fills");
    }
  };

  window.v3ProductV11RunJourneyB = async () => {
    await waitForProductReadyWithoutBinding();
    await useProductRuntime.getState().createProjectAndBind("横截面因子研究", "V1.1 packaged Golden Journey B");
    requireV11State("Journey B Project activation");
    await useProductRuntime.getState().importLocalData("SHARES");
    requireV11State("Journey B local Data import");
    await useProductRuntime.getState().submitFactorStudy({
      formulaSource: "MJ:AMOUNT/VOL/100;",
      analysisOutputName: "MJ",
    });
    const state = requireV11State("Journey B Factor Analysis");
    const factor = state.dataHome?.factor;
    const aggregate = factor?.analysis.aggregate;
    if (
      state.dataHome?.data?.instrumentCount !== 20
      || aggregate === undefined
      || aggregate.validDates < 20
      || aggregate.icMean.status !== "AVAILABLE"
      || aggregate.rankIcMean.status !== "AVAILABLE"
      || factor?.analysis.dailyResults.some((item) => item.status === "AVAILABLE" && item.sampleSize !== 20)
    ) {
      throw new Error("Journey B did not produce the admitted 20-symbol cross-sectional analysis");
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
