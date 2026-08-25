import { contextBridge, ipcRenderer } from "electron";
import type {
  ArtifactDescriptorView,
  ArtifactStreamBytesView,
  ArtifactStreamTicketView,
  BacktestSubmitOutcomeView,
  ConnectExistingProjectRequest,
  CreateProjectRequest,
  DesktopBridge,
  DesktopCommandEnvelope,
  ImportResearchPackageOutcomeView,
  LocalDataSourceSelectionView,
  ProductLocalDataImportIntent,
  ProductLocalDataImportOutcomeView,
  ProductLatestResultDetailsView,
  ProductArtifactExportIntent,
  ProductArtifactExportOutcomeView,
  ProductFactorStudyIntent,
  ProductFactorStudyOutcomeView,
  ProductProjectHomeView,
  ProductResearchBacktestIntent,
  ProductResearchBacktestOutcomeView,
  ProductResearchBacktestPreviewView,
  ProductResearchStrategyIntent,
  ProductResearchStrategyOutcomeView,
  ProductResearchStrategyPreviewView,
  ProductResearchSubmitIntent,
  ProductResearchSubmitOutcomeView,
  PersistedWorkspace,
  ProductBindingRefs,
  ProductCapabilityView,
  ProductResultView,
  ProductStatusView,
  ProductTaskEventsView,
  ProductTaskPageRequest,
  ProductTasksListView,
  ProductPageRequest,
  ProductTaskView,
  ProjectContextView,
  ProjectCreatedView,
  ProjectsListView,
  RunSpecsListView,
  SessionRestoreView,
  V3ProductRuntimeBridge
} from "../../../packages/contracts/src/index";
import type { BackendRuntimeReadOnlyBridge, RuntimeConnectionState, TaskEventView } from "./preload/backendRuntime/types";

const subscribe = <T>(channel: string, listener: (value: T) => void): (() => void) => {
  const receive = (_event: unknown, value: unknown): void => listener(structuredClone(value) as T);
  ipcRenderer.on(channel, receive);
  return () => ipcRenderer.removeListener(channel, receive);
};

const bridge: DesktopBridge = Object.freeze({
  loadWorkspace: () => ipcRenderer.invoke("workspace:load") as Promise<PersistedWorkspace>,
  saveWorkspace: (state: PersistedWorkspace) => ipcRenderer.invoke("workspace:save", state) as Promise<PersistedWorkspace>,
  resetWorkspace: () => ipcRenderer.invoke("workspace:reset") as Promise<PersistedWorkspace>,
  executeCommand: (command: DesktopCommandEnvelope) => ipcRenderer.invoke("command:execute", command),
  runtimeInfo: () => ipcRenderer.invoke("runtime:info"),
  windowState: () => ipcRenderer.invoke("window:state"),
  onWindowStateChanged: (listener: (state: { maximized: boolean }) => void) => subscribe("window:state-changed", listener),
  windowControl: (action: "minimize" | "toggle-maximize" | "close") => ipcRenderer.invoke("window:control", action)
});

contextBridge.exposeInMainWorld("v3Desktop", bridge);

// Electron sandbox preloads execute as one isolated bundle and cannot require
// adjacent compiled files. Keep this product exposure in the existing single
// preload while using exactly the same backendRuntime:* IPC namespace.
const backendRuntimeBridge: BackendRuntimeReadOnlyBridge = Object.freeze({
  getCapabilities: () => ipcRenderer.invoke("backendRuntime:capabilities"),
  getHealth: () => ipcRenderer.invoke("backendRuntime:health"),
  getEvidenceSnapshot: () => ipcRenderer.invoke("backendRuntime:evidenceSnapshot"),
  onEvidenceEvent: (listener: (event: TaskEventView) => void) => subscribe("backendRuntime:taskEvent", listener),
  onConnectionState: (listener: (state: RuntimeConnectionState) => void) => subscribe("backendRuntime:connectionState", listener)
});

contextBridge.exposeInMainWorld("v3BackendRuntime", backendRuntimeBridge);

// Narrow typed product bridge: each member maps to one admitted frozen
// operation handled by the Electron main process. There is no generic
// request(operationId, payload) exposure and no arbitrary channel access.
/**
 * Parse a rejected product IPC message into a closed structured error view.
 * Malformed JSON or a wrong shape degrades to the safe generic
 * PRODUCT_BRIDGE_ERROR; a valid structured view (CAPABILITY_UNAVAILABLE,
 * NOT_FOUND, BINDING_STALE, ...) is preserved exactly. Arbitrary backend
 * objects never cross the renderer boundary.
 */
function parseProductBridgeErrorView(message: string): { code: string; message: string; retryable: boolean; operationId?: string } {
  const fallback = { code: "PRODUCT_BRIDGE_ERROR", message, retryable: false as const };
  let parsed: unknown;
  try {
    parsed = JSON.parse(message);
  } catch {
    // Electron wraps rejected ipcMain handlers as
    // "Error invoking remote method '<channel>': Error: <handler message>".
    // Recover the embedded structured JSON instead of degrading it.
    const brace = message.indexOf("{");
    if (brace <= 0) return fallback;
    try {
      parsed = JSON.parse(message.slice(brace));
    } catch {
      return fallback;
    }
  }
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") return fallback;
  const record = parsed as Record<string, unknown>;
  const allowed = new Set(["code", "message", "retryable", "operationId"]);
  if (Object.keys(record).some((key) => !allowed.has(key))) return fallback;
  if (typeof record.code !== "string" || record.code.length === 0) return fallback;
  if (typeof record.message !== "string") return fallback;
  if (typeof record.retryable !== "boolean") return fallback;
  if (record.operationId !== undefined && typeof record.operationId !== "string") return fallback;
  return record.operationId === undefined
    ? { code: record.code, message: record.message, retryable: record.retryable }
    : { code: record.code, message: record.message, retryable: record.retryable, operationId: record.operationId };
}

const invokeProduct = <T>(channel: string, payload?: unknown): Promise<T> => {
  const request: Promise<unknown> = payload === undefined
    ? ipcRenderer.invoke(channel)
    : ipcRenderer.invoke(channel, payload);
  return request.then((value) => structuredClone(value) as T, (error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    // Reject exactly once, outside the parse guard above, with the closed
    // plain view object itself: the context bridge strips custom properties
    // from rejected Errors, so the structured code/message/retryable must
    // travel as structured-cloneable data to survive into the renderer.
    throw parseProductBridgeErrorView(message);
  });
};

const productRuntimeBridge: V3ProductRuntimeBridge = Object.freeze({
  getProductStatus: () => invokeProduct<ProductStatusView>("productRuntime:status"),
  getCapabilities: () => invokeProduct<readonly ProductCapabilityView[]>("productRuntime:capabilities"),
  getBoundProject: () => invokeProduct<ProductBindingRefs | null>("productRuntime:boundProject"),
  getProjectContext: () => invokeProduct<ProjectContextView>("productRuntime:projectContext"),
  getProjectHome: () => invokeProduct<ProductProjectHomeView>("productRuntime:projectHome"),
  getLatestProductResultDetails: () => invokeProduct<ProductLatestResultDetailsView>("productRuntime:latestProductResultDetails"),
  restoreSession: () => invokeProduct<SessionRestoreView>("productRuntime:restoreSession"),
  connectExistingProject: (request: ConnectExistingProjectRequest) => invokeProduct<ProjectContextView>("productRuntime:connectExistingProject", {
    projectId: request.projectId,
    projectContextRevisionId: request.projectContextRevisionId
  }),
  listTasks: (request?: ProductTaskPageRequest) => invokeProduct<ProductTasksListView>("productRuntime:listTasks", request),
  getTask: (taskId: string) => invokeProduct<ProductTaskView>("productRuntime:getTask", { taskId }),
  retryResearchBacktest: (taskId: string) => invokeProduct<ProductTaskView>("productRuntime:retryResearchBacktest", { taskId }),
  getTaskEvents: (afterSequence: number, limit: number) => invokeProduct<ProductTaskEventsView>("productRuntime:getTaskEvents", { afterSequence, limit }),
  getResult: (resultId: string) => invokeProduct<ProductResultView>("productRuntime:getResult", { resultId }),
  getArtifactDescriptor: (artifactId: string) => invokeProduct<ArtifactDescriptorView>("productRuntime:getArtifactDescriptor", { artifactId }),
  openArtifactStream: (artifactId: string) => invokeProduct<ArtifactStreamTicketView>("productRuntime:openArtifactStream", { artifactId }),
  readArtifactBytes: (artifactId: string) => invokeProduct<ArtifactStreamBytesView>("productRuntime:readArtifactBytes", { artifactId }),
  exportArtifact: (request: ProductArtifactExportIntent) => invokeProduct<ProductArtifactExportOutcomeView>("productRuntime:exportArtifact", {
    artifactId: request.artifactId,
    suggestedName: request.suggestedName
  }),
  submitExistingBacktestRunSpec: (runSpecId: string) => invokeProduct<BacktestSubmitOutcomeView>("productRuntime:submitExistingBacktestRunSpec", { runSpecId }),
  createProject: (request: CreateProjectRequest) => invokeProduct<ProjectCreatedView>("productRuntime:createProject", {
    displayName: request.displayName,
    ...(request.notes === undefined ? {} : { notes: request.notes })
  }),
  listProjects: (request?: ProductPageRequest) => invokeProduct<ProjectsListView>("productRuntime:listProjects", request),
  listBacktestRunSpecs: (request?: ProductPageRequest) => invokeProduct<RunSpecsListView>("productRuntime:listBacktestRunSpecs", request),
  importResearchPackage: () => invokeProduct<ImportResearchPackageOutcomeView | null>("productRuntime:importResearchPackage"),
  chooseLocalDataSource: () => invokeProduct<LocalDataSourceSelectionView | null>("productRuntime:chooseLocalDataSource"),
  importLocalDataset: (request: ProductLocalDataImportIntent) => invokeProduct<ProductLocalDataImportOutcomeView>("productRuntime:importLocalDataset", request),
  submitFactorStudy: (request: ProductFactorStudyIntent) => invokeProduct<ProductFactorStudyOutcomeView>("productRuntime:submitFactorStudy", request),
  previewResearchStrategy: (request: ProductResearchStrategyIntent) => invokeProduct<ProductResearchStrategyPreviewView>("productRuntime:previewResearchStrategy", request),
  publishResearchStrategy: (request: ProductResearchStrategyIntent) => invokeProduct<ProductResearchStrategyOutcomeView>("productRuntime:publishResearchStrategy", request),
  previewResearchBacktest: (request: ProductResearchBacktestIntent) => invokeProduct<ProductResearchBacktestPreviewView>("productRuntime:previewResearchBacktest", request),
  submitResearchBacktest: (request: ProductResearchBacktestIntent) => invokeProduct<ProductResearchBacktestOutcomeView>("productRuntime:submitResearchBacktest", request),
  submitResearch: (request: ProductResearchSubmitIntent) => invokeProduct<ProductResearchSubmitOutcomeView>("productRuntime:submitResearch", request)
});

contextBridge.exposeInMainWorld("v3ProductRuntime", productRuntimeBridge);
