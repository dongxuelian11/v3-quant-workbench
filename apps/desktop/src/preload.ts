import { contextBridge, ipcRenderer } from "electron";
import type { DesktopBridge, DesktopCommandEnvelope, PersistedWorkspace } from "../../../packages/contracts/src/index";
import type { BackendRuntimeReadOnlyBridge, RuntimeConnectionState, TaskEventView } from "./preload/backendRuntime/types";

const bridge: DesktopBridge = Object.freeze({
  loadWorkspace: () => ipcRenderer.invoke("workspace:load") as Promise<PersistedWorkspace>,
  saveWorkspace: (state: PersistedWorkspace) => ipcRenderer.invoke("workspace:save", state) as Promise<PersistedWorkspace>,
  resetWorkspace: () => ipcRenderer.invoke("workspace:reset") as Promise<PersistedWorkspace>,
  executeCommand: (command: DesktopCommandEnvelope) => ipcRenderer.invoke("command:execute", command),
  runtimeInfo: () => ipcRenderer.invoke("runtime:info"),
  windowState: () => ipcRenderer.invoke("window:state"),
  windowControl: (action: "minimize" | "toggle-maximize" | "close") => ipcRenderer.invoke("window:control", action)
});

contextBridge.exposeInMainWorld("v3Desktop", bridge);

// Electron sandbox preloads execute as one isolated bundle and cannot require
// adjacent compiled files. Keep this product exposure in the existing single
// preload while using exactly the same backendRuntime:* IPC namespace.
const subscribe = <T>(channel: string, listener: (value: T) => void): (() => void) => {
  const receive = (_event: unknown, value: unknown): void => listener(structuredClone(value) as T);
  ipcRenderer.on(channel, receive);
  return () => ipcRenderer.removeListener(channel, receive);
};

const backendRuntimeBridge: BackendRuntimeReadOnlyBridge = Object.freeze({
  getCapabilities: () => ipcRenderer.invoke("backendRuntime:capabilities"),
  getHealth: () => ipcRenderer.invoke("backendRuntime:health"),
  getEvidenceSnapshot: () => ipcRenderer.invoke("backendRuntime:evidenceSnapshot"),
  onEvidenceEvent: (listener: (event: TaskEventView) => void) => subscribe("backendRuntime:taskEvent", listener),
  onConnectionState: (listener: (state: RuntimeConnectionState) => void) => subscribe("backendRuntime:connectionState", listener)
});

contextBridge.exposeInMainWorld("v3BackendRuntime", backendRuntimeBridge);
