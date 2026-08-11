import { contextBridge, ipcRenderer } from "electron";
import { createBackendRuntimeReadOnlyBridge } from "./bridge";

export const BACKEND_RUNTIME_GLOBAL = "v3BackendRuntime";

export function installBackendRuntimeBridge(): void {
  contextBridge.exposeInMainWorld(BACKEND_RUNTIME_GLOBAL, createBackendRuntimeReadOnlyBridge(ipcRenderer));
}
