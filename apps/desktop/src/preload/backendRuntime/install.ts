import { contextBridge, ipcRenderer } from "electron";
import { createBackendRuntimeBridge } from "./bridge";

export const BACKEND_RUNTIME_GLOBAL = "v3BackendRuntime";

export function installBackendRuntimeBridge(): void {
  contextBridge.exposeInMainWorld(BACKEND_RUNTIME_GLOBAL, createBackendRuntimeBridge(ipcRenderer));
}
