import type {
  ArtifactStreamRequest,
  BackendRuntimeBridge,
  CancelTaskRequest,
  ResumeTaskRequest,
  RetryTaskRequest,
  RuntimeCapability,
  RuntimeConnectionState,
  TaskEventView
} from "./types";

export const BACKEND_RUNTIME_CHANNELS = Object.freeze({
  capabilities: "backendRuntime:capabilities",
  health: "backendRuntime:health",
  cancelTask: "backendRuntime:cancelTask",
  retryTask: "backendRuntime:retryTask",
  resumeTask: "backendRuntime:resumeTask",
  openArtifactStream: "backendRuntime:openArtifactStream",
  taskEvent: "backendRuntime:taskEvent",
  connectionState: "backendRuntime:connectionState"
} as const);

export interface NarrowIpcRenderer {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>;
  on(channel: string, listener: (event: unknown, value: unknown) => void): void;
  removeListener(channel: string, listener: (event: unknown, value: unknown) => void): void;
}

function subscribe<T>(ipc: NarrowIpcRenderer, channel: string, listener: (value: T) => void): () => void {
  const receive = (_event: unknown, value: unknown): void => listener(structuredClone(value) as T);
  ipc.on(channel, receive);
  return () => ipc.removeListener(channel, receive);
}

export function createBackendRuntimeBridge(ipc: NarrowIpcRenderer): BackendRuntimeBridge {
  return Object.freeze({
    getCapabilities: () => ipc.invoke(BACKEND_RUNTIME_CHANNELS.capabilities) as Promise<readonly RuntimeCapability[]>,
    getHealth: () => ipc.invoke(BACKEND_RUNTIME_CHANNELS.health) as Promise<Readonly<Record<string, unknown>>>,
    cancelTask: (request: CancelTaskRequest) => ipc.invoke(BACKEND_RUNTIME_CHANNELS.cancelTask, structuredClone(request)),
    retryTask: (request: RetryTaskRequest) => ipc.invoke(BACKEND_RUNTIME_CHANNELS.retryTask, structuredClone(request)),
    resumeTask: (request: ResumeTaskRequest) => ipc.invoke(BACKEND_RUNTIME_CHANNELS.resumeTask, structuredClone(request)),
    openArtifactStream: (request: ArtifactStreamRequest) => ipc.invoke(BACKEND_RUNTIME_CHANNELS.openArtifactStream, structuredClone(request)),
    onTaskEvent: (listener: (event: TaskEventView) => void) => subscribe(ipc, BACKEND_RUNTIME_CHANNELS.taskEvent, listener),
    onConnectionState: (listener: (state: RuntimeConnectionState) => void) => subscribe(ipc, BACKEND_RUNTIME_CHANNELS.connectionState, listener)
  });
}
