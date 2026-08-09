import { contextBridge, ipcRenderer } from "electron";
import type { DesktopBridge, DesktopCommandEnvelope, PersistedWorkspace } from "../../../packages/contracts/src/index";

const bridge: DesktopBridge = Object.freeze({
  loadWorkspace: () => ipcRenderer.invoke("workspace:load") as Promise<PersistedWorkspace>,
  saveWorkspace: (state: PersistedWorkspace) => ipcRenderer.invoke("workspace:save", state) as Promise<PersistedWorkspace>,
  resetWorkspace: () => ipcRenderer.invoke("workspace:reset") as Promise<PersistedWorkspace>,
  executeCommand: (command: DesktopCommandEnvelope) => ipcRenderer.invoke("command:execute", command),
  runtimeInfo: () => ipcRenderer.invoke("runtime:info")
});

contextBridge.exposeInMainWorld("v3Desktop", bridge);
