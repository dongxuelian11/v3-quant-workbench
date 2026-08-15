import { contextBridge, ipcRenderer } from "electron";
import type {
  ArtifactDescriptorView,
  ArtifactStreamTicketView,
  BacktestSubmitOutcomeView,
  ConnectExistingProjectRequest,
  DesktopBridge,
  DesktopCommandEnvelope,
  PersistedWorkspace,
  ProductBindingRefs,
  ProductCapabilityView,
  ProductResultView,
  ProductStatusView,
  ProductTaskEventsView,
  ProductTaskView,
  ProjectContextView,
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
const invokeProduct = <T>(channel: string, payload?: unknown): Promise<T> => {
  const request: Promise<unknown> = payload === undefined
    ? ipcRenderer.invoke(channel)
    : ipcRenderer.invoke(channel, payload);
  return request.then((value) => structuredClone(value) as T, (error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    try {
      throw Object.assign(new Error("product runtime request failed"), { view: JSON.parse(message) });
    } catch {
      throw Object.assign(new Error("product runtime request failed"), {
        view: { code: "PRODUCT_BRIDGE_ERROR", message, retryable: false }
      });
    }
  });
};

const productRuntimeBridge: V3ProductRuntimeBridge = Object.freeze({
  getProductStatus: () => invokeProduct<ProductStatusView>("productRuntime:status"),
  getCapabilities: () => invokeProduct<readonly ProductCapabilityView[]>("productRuntime:capabilities"),
  getBoundProject: () => invokeProduct<ProductBindingRefs | null>("productRuntime:boundProject"),
  getProjectContext: () => invokeProduct<ProjectContextView>("productRuntime:projectContext"),
  restoreSession: () => invokeProduct<SessionRestoreView>("productRuntime:restoreSession"),
  connectExistingProject: (request: ConnectExistingProjectRequest) => invokeProduct<ProjectContextView>("productRuntime:connectExistingProject", {
    projectId: request.projectId,
    projectContextRevisionId: request.projectContextRevisionId
  }),
  listTasks: () => invokeProduct<readonly ProductTaskView[]>("productRuntime:listTasks"),
  getTask: (taskId: string) => invokeProduct<ProductTaskView>("productRuntime:getTask", { taskId }),
  getTaskEvents: (afterSequence: number, limit: number) => invokeProduct<ProductTaskEventsView>("productRuntime:getTaskEvents", { afterSequence, limit }),
  getResult: (resultId: string) => invokeProduct<ProductResultView>("productRuntime:getResult", { resultId }),
  getArtifactDescriptor: (artifactId: string) => invokeProduct<ArtifactDescriptorView>("productRuntime:getArtifactDescriptor", { artifactId }),
  openArtifactStream: (artifactId: string) => invokeProduct<ArtifactStreamTicketView>("productRuntime:openArtifactStream", { artifactId }),
  submitExistingBacktestRunSpec: (runSpecId: string) => invokeProduct<BacktestSubmitOutcomeView>("productRuntime:submitExistingBacktestRunSpec", { runSpecId })
});

contextBridge.exposeInMainWorld("v3ProductRuntime", productRuntimeBridge);
