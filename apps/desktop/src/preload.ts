import { contextBridge, ipcRenderer } from "electron";
import type {
  BackendStatus,
  DesktopBridge,
  DesktopCommand,
  SaveWorkspaceRequest,
  WorkspaceState
} from "../../../packages/contracts/src/index";

const bridge: DesktopBridge = {
  getWorkspaceState: () => ipcRenderer.invoke("workspace:getState") as Promise<WorkspaceState>,
  saveWorkspaceState: (request: SaveWorkspaceRequest) =>
    ipcRenderer.invoke("workspace:saveState", request) as Promise<WorkspaceState>,
  resetWorkspaceState: () => ipcRenderer.invoke("workspace:resetState") as Promise<WorkspaceState>,
  getBackendStatus: () => ipcRenderer.invoke("backend:getStatus") as Promise<BackendStatus>,
  sendCommand: (command: DesktopCommand) => {
    return ipcRenderer.invoke("command:send", command) as Promise<void>;
  }
};

contextBridge.exposeInMainWorld("v3Desktop", bridge);

