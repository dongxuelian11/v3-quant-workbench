import type { IpcMain, IpcMainInvokeEvent } from "electron";
import type { BackendSupervisor } from "./supervisor";
import type { CancelTaskInput, OpenArtifactStreamInput, ResumeTaskInput, RetryTaskInput } from "./types";

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

export type TrustIpcSender = (event: IpcMainInvokeEvent) => void;

function assertObject(value: unknown, allowed: readonly string[]): Record<string, unknown> {
  if (value === null || Array.isArray(value) || typeof value !== "object") throw new TypeError("backend runtime IPC payload must be an object");
  const record = value as Record<string, unknown>;
  const unknown = Object.keys(record).filter((key) => !allowed.includes(key));
  if (unknown.length > 0) throw new TypeError(`unknown backend runtime IPC fields: ${unknown.join(", ")}`);
  return record;
}

function requiredString(item: Record<string, unknown>, name: string): string {
  const value = item[name];
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`${name} must be a non-empty string`);
  return value;
}

function stateVersion(item: Record<string, unknown>): number {
  const value = item.expectedStateVersion;
  if (!Number.isInteger(value) || Number(value) < 0) throw new TypeError("expectedStateVersion must be a non-negative integer");
  return Number(value);
}

export function registerBackendRuntimeIpc(ipcMain: IpcMain, trusted: TrustIpcSender, supervisor: BackendSupervisor): () => void {
  const handle = (channel: string, listener: (value: unknown) => unknown | Promise<unknown>): void => {
    ipcMain.handle(channel, (event, value) => { trusted(event); return listener(value); });
  };
  ipcMain.handle(BACKEND_RUNTIME_CHANNELS.capabilities, (event) => { trusted(event); return supervisor.capabilities; });
  ipcMain.handle(BACKEND_RUNTIME_CHANNELS.health, (event) => { trusted(event); return supervisor.getHealth(); });
  handle(BACKEND_RUNTIME_CHANNELS.cancelTask, (value) => {
    const item = assertObject(value, ["taskId", "expectedStateVersion", "reason"]);
    const request: CancelTaskInput = {
      taskId: requiredString(item, "taskId"),
      expectedStateVersion: stateVersion(item),
      reason: requiredString(item, "reason")
    };
    return supervisor.cancelTask(request);
  });
  handle(BACKEND_RUNTIME_CHANNELS.retryTask, (value) => {
    const item = assertObject(value, ["taskId", "failedAttemptId", "expectedStateVersion"]);
    const request: RetryTaskInput = {
      taskId: requiredString(item, "taskId"),
      failedAttemptId: requiredString(item, "failedAttemptId"),
      expectedStateVersion: stateVersion(item)
    };
    return supervisor.retryTask(request);
  });
  handle(BACKEND_RUNTIME_CHANNELS.resumeTask, (value) => {
    const item = assertObject(value, ["taskId", "checkpointArtifactId", "expectedStateVersion"]);
    const request: ResumeTaskInput = {
      taskId: requiredString(item, "taskId"),
      checkpointArtifactId: requiredString(item, "checkpointArtifactId"),
      expectedStateVersion: stateVersion(item)
    };
    return supervisor.resumeTask(request);
  });
  handle(BACKEND_RUNTIME_CHANNELS.openArtifactStream, (value) => {
    const item = assertObject(value, ["artifactId", "range"]);
    if (item.range !== undefined && (item.range === null || Array.isArray(item.range) || typeof item.range !== "object")) {
      throw new TypeError("range must be an object when present");
    }
    const request: OpenArtifactStreamInput = {
      artifactId: requiredString(item, "artifactId"),
      ...(item.range === undefined ? {} : { range: item.range as Readonly<Record<string, unknown>> })
    };
    return supervisor.openArtifactStream(request);
  });
  return () => {
    for (const channel of Object.values(BACKEND_RUNTIME_CHANNELS).slice(0, 6)) ipcMain.removeHandler(channel);
  };
}
