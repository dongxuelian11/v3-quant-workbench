import { contextBridge, ipcRenderer } from "electron";
import type { JobEvent, JsonObject, ResearchBridge, WorkspacePanel } from "../../../packages/contracts/src/research";

const subscribe = <T>(channel: string, listener: (value: T) => void) => {
  const receive = (_event: unknown, value: T) => listener(value);
  ipcRenderer.on(channel, receive);
  return () => ipcRenderer.removeListener(channel, receive);
};

const research: ResearchBridge = {
  request: (method, params = {}) => ipcRenderer.invoke("research:request", method, params),
  onEvent: (listener) => subscribe<JobEvent>("research:event", listener),
  chooseDirectory: () => ipcRenderer.invoke("research:choose-directory"),
  chooseFiles: (options) => ipcRenderer.invoke("research:choose-files", options),
  exportFile: (request) => ipcRenderer.invoke("research:export", request),
  workspace: {
    current: () => ipcRenderer.invoke("research:workspace-current"),
    detach: (panel, bounds) => ipcRenderer.invoke("research:workspace-detach", panel, bounds),
    update: state => ipcRenderer.invoke("research:workspace-update", state),
    attach: (panels, target) => ipcRenderer.invoke("research:workspace-attach", panels, target),
    restore: states => ipcRenderer.invoke("research:workspace-restore", states),
    onPanels: listener => subscribe<WorkspacePanel[]>("research:workspace-panels", listener),
    onChanged: listener => subscribe<{ method: string; params?: JsonObject }>("research:workspace-changed", listener),
    broadcast: change => ipcRenderer.send("research:workspace-broadcast", change),
  },
};
contextBridge.exposeInMainWorld("v3Research", research);
contextBridge.exposeInMainWorld("v3Desktop", {
  windowState: () => ipcRenderer.invoke("window:state"),
  onWindowStateChanged: (listener: (value: { maximized: boolean }) => void) => subscribe("window:state-changed", listener),
  windowControl: (action: "minimize" | "toggle-maximize" | "close") => ipcRenderer.invoke("window:control", action),
});
