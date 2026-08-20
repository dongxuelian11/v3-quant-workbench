import type { IpcMain, IpcMainInvokeEvent } from "electron";
import type { TrustIpcSender } from "../backendRuntime/ipc";
import type { ProductBridge } from "./productBridge";
import { errorToView } from "./productBridge";
import { ProductAdapterError } from "./adapters";

/**
 * Typed product runtime IPC channels. Each channel maps to exactly one
 * ProductBridge method; there is no channel that accepts an operation id or a
 * raw transport payload. Payloads are validated with closed key allow-lists
 * before touching the bridge.
 */

export const PRODUCT_RUNTIME_CHANNELS = Object.freeze({
  status: "productRuntime:status",
  capabilities: "productRuntime:capabilities",
  boundProject: "productRuntime:boundProject",
  projectContext: "productRuntime:projectContext",
  restoreSession: "productRuntime:restoreSession",
  connectExistingProject: "productRuntime:connectExistingProject",
  listTasks: "productRuntime:listTasks",
  getTask: "productRuntime:getTask",
  getTaskEvents: "productRuntime:getTaskEvents",
  getResult: "productRuntime:getResult",
  getArtifactDescriptor: "productRuntime:getArtifactDescriptor",
  openArtifactStream: "productRuntime:openArtifactStream",
  submitExistingBacktestRunSpec: "productRuntime:submitExistingBacktestRunSpec",
  createProject: "productRuntime:createProject",
  listProjects: "productRuntime:listProjects",
  listBacktestRunSpecs: "productRuntime:listBacktestRunSpecs",
  importResearchPackage: "productRuntime:importResearchPackage",
  submitResearch: "productRuntime:submitResearch"
} as const);

function assertObject(value: unknown, allowed: readonly string[]): Record<string, unknown> {
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    throw new ProductAdapterError("INVALID_ARGUMENT", "product runtime IPC payload must be an object");
  }
  const record = value as Record<string, unknown>;
  const unknown = Object.keys(record).filter((key) => !allowed.includes(key));
  if (unknown.length > 0) {
    throw new ProductAdapterError("INVALID_ARGUMENT", `unknown product runtime IPC fields: ${unknown.join(", ")}`);
  }
  return record;
}

function requiredString(item: Record<string, unknown>, name: string): string {
  const value = item[name];
  if (typeof value !== "string" || value.length === 0 || value.length > 4096) {
    throw new ProductAdapterError("INVALID_ARGUMENT", `${name} must be a bounded non-empty string`);
  }
  return value;
}

export function registerProductRuntimeIpc(
  ipcMain: IpcMain,
  trusted: TrustIpcSender,
  bridge: ProductBridge
): () => void {
  const handle = (channel: string, listener: (value: unknown) => unknown | Promise<unknown>): void => {
    ipcMain.handle(channel, async (event: IpcMainInvokeEvent, value: unknown) => {
      trusted(event);
      try {
        return await listener(value);
      } catch (error) {
        // Structured bridge errors only; raw stack details never cross IPC.
        throw new Error(JSON.stringify(errorToView(error)));
      }
    });
  };
  handle(PRODUCT_RUNTIME_CHANNELS.status, () => bridge.getProductStatus());
  handle(PRODUCT_RUNTIME_CHANNELS.capabilities, () => bridge.getCapabilities());
  handle(PRODUCT_RUNTIME_CHANNELS.boundProject, () => bridge.getBoundProject());
  handle(PRODUCT_RUNTIME_CHANNELS.projectContext, () => bridge.getProjectContext());
  handle(PRODUCT_RUNTIME_CHANNELS.restoreSession, () => bridge.restoreSession());
  handle(PRODUCT_RUNTIME_CHANNELS.connectExistingProject, (value) => {
    const item = assertObject(value, ["projectId", "projectContextRevisionId"]);
    return bridge.connectExistingProject({
      projectId: requiredString(item, "projectId"),
      projectContextRevisionId: requiredString(item, "projectContextRevisionId")
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.listTasks, () => bridge.listTasks());
  handle(PRODUCT_RUNTIME_CHANNELS.getTask, (value) => {
    const item = assertObject(value, ["taskId"]);
    return bridge.getTask(requiredString(item, "taskId"));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.getTaskEvents, (value) => {
    const item = assertObject(value, ["afterSequence", "limit"]);
    const afterSequence = item.afterSequence;
    const limit = item.limit;
    if (!Number.isInteger(afterSequence) || Number(afterSequence) < 0) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "afterSequence must be a non-negative integer");
    }
    if (!Number.isInteger(limit) || Number(limit) < 1 || Number(limit) > 500) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "limit must be an integer in [1, 500]");
    }
    return bridge.getTaskEvents(Number(afterSequence), Number(limit));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.getResult, (value) => {
    const item = assertObject(value, ["resultId"]);
    return bridge.getResult(requiredString(item, "resultId"));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.getArtifactDescriptor, (value) => {
    const item = assertObject(value, ["artifactId"]);
    return bridge.getArtifactDescriptor(requiredString(item, "artifactId"));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.openArtifactStream, (value) => {
    const item = assertObject(value, ["artifactId"]);
    return bridge.openArtifactStream(requiredString(item, "artifactId"));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.submitExistingBacktestRunSpec, (value) => {
    const item = assertObject(value, ["runSpecId"]);
    return bridge.submitExistingBacktestRunSpec(requiredString(item, "runSpecId"));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.createProject, (value) => {
    const item = assertObject(value, ["displayName", "notes"]);
    const displayName = requiredString(item, "displayName");
    const notes = item.notes;
    if (notes !== undefined && (typeof notes !== "string" || notes.length > 2048)) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "notes must be a bounded string");
    }
    return bridge.createProject({ displayName, ...(notes === undefined ? {} : { notes }) });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.listProjects, () => bridge.listProjects());
  handle(PRODUCT_RUNTIME_CHANNELS.listBacktestRunSpecs, () => bridge.listBacktestRunSpecs());
  handle(PRODUCT_RUNTIME_CHANNELS.importResearchPackage, () => bridge.importResearchPackage());
  handle(PRODUCT_RUNTIME_CHANNELS.submitResearch, (value) => {
    const item = assertObject(value, ["symbol", "startDate", "endDate"]);
    return bridge.submitResearch({
      symbol: requiredString(item, "symbol"),
      startDate: requiredString(item, "startDate"),
      endDate: requiredString(item, "endDate")
    });
  });
  return () => {
    for (const channel of Object.values(PRODUCT_RUNTIME_CHANNELS)) ipcMain.removeHandler(channel);
  };
}
