import type { IpcMain, IpcMainInvokeEvent } from "electron";
import type { TrustIpcSender } from "../backendRuntime/ipc";
import type { ProductStatusView } from "../../../../../packages/contracts/src/index";
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
  projectHome: "productRuntime:projectHome",
  latestProductResultDetails: "productRuntime:latestProductResultDetails",
  restoreSession: "productRuntime:restoreSession",
  connectExistingProject: "productRuntime:connectExistingProject",
  listTasks: "productRuntime:listTasks",
  getTask: "productRuntime:getTask",
  getOperationReceipt: "productRuntime:getOperationReceipt",
  listQueue: "productRuntime:listQueue",
  startQueuedTask: "productRuntime:startQueuedTask",
  resumeFromCheckpoint: "productRuntime:resumeFromCheckpoint",
  cancelTask: "productRuntime:cancelTask",
  retryResearchBacktest: "productRuntime:retryResearchBacktest",
  getTaskEvents: "productRuntime:getTaskEvents",
  getResult: "productRuntime:getResult",
  getArtifactDescriptor: "productRuntime:getArtifactDescriptor",
  openArtifactStream: "productRuntime:openArtifactStream",
  readArtifactBytes: "productRuntime:readArtifactBytes",
  exportArtifact: "productRuntime:exportArtifact",
  submitExistingBacktestRunSpec: "productRuntime:submitExistingBacktestRunSpec",
  createProject: "productRuntime:createProject",
  listProjects: "productRuntime:listProjects",
  listBacktestRunSpecs: "productRuntime:listBacktestRunSpecs",
  importResearchPackage: "productRuntime:importResearchPackage",
  chooseLocalDataSource: "productRuntime:chooseLocalDataSource",
  importLocalDataset: "productRuntime:importLocalDataset",
  submitFactorStudy: "productRuntime:submitFactorStudy",
  previewResearchStrategy: "productRuntime:previewResearchStrategy",
  publishResearchStrategy: "productRuntime:publishResearchStrategy",
  previewResearchBacktest: "productRuntime:previewResearchBacktest",
  submitResearchBacktest: "productRuntime:submitResearchBacktest",
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

function requiredInteger(item: Record<string, unknown>, name: string, minimum: number, maximum: number): number {
  const value = item[name];
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum || value > maximum) {
    throw new ProductAdapterError("INVALID_ARGUMENT", `${name} must be an integer in [${minimum}, ${maximum}]`);
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
  handle(PRODUCT_RUNTIME_CHANNELS.projectHome, () => bridge.getProjectHome());
  handle(PRODUCT_RUNTIME_CHANNELS.latestProductResultDetails, () => bridge.getLatestProductResultDetails());
  handle(PRODUCT_RUNTIME_CHANNELS.restoreSession, () => bridge.restoreSession());
  handle(PRODUCT_RUNTIME_CHANNELS.connectExistingProject, (value) => {
    const item = assertObject(value, ["projectId", "projectContextRevisionId"]);
    return bridge.connectExistingProject({
      projectId: requiredString(item, "projectId"),
      projectContextRevisionId: requiredString(item, "projectContextRevisionId")
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.listTasks, (value) => {
    if (value === undefined) return bridge.listTasks();
    const item = assertObject(value, ["filter", "cursor", "pageSize"]);
    const filter = item.filter === undefined ? {} : assertObject(item.filter, ["service", "state"]);
    if (filter.service !== undefined && filter.service !== "ProductEntryService") {
      throw new ProductAdapterError("INVALID_ARGUMENT", "task list service filter is not admitted");
    }
    if (filter.state !== undefined && filter.state !== "SUCCEEDED") {
      throw new ProductAdapterError("INVALID_ARGUMENT", "task list state filter is not admitted");
    }
    return bridge.listTasks({
      filter: {
        ...(filter.service === undefined ? {} : { service: filter.service as "ProductEntryService" }),
        ...(filter.state === undefined ? {} : { state: filter.state as "SUCCEEDED" })
      },
      ...(item.cursor === undefined ? {} : { cursor: requiredString(item, "cursor") }),
      ...(item.pageSize === undefined ? {} : { pageSize: requiredInteger(item, "pageSize", 1, 100) })
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.getTask, (value) => {
    const item = assertObject(value, ["taskId"]);
    return bridge.getTask(requiredString(item, "taskId"));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.getOperationReceipt, (value) => {
    const item = assertObject(value, ["operationReceiptId"]);
    return bridge.getOperationReceipt(requiredString(item, "operationReceiptId"));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.listQueue, (value) => {
    if (value === undefined) return bridge.listQueue();
    const item = assertObject(value, ["states", "cursor", "pageSize"]);
    const states = item.states;
    if (states !== undefined) {
      if (!Array.isArray(states) || states.length === 0 || states.length > 4) {
        throw new ProductAdapterError("INVALID_ARGUMENT", "queue states must be a non-empty array of at most four items");
      }
      if (new Set(states).size !== states.length || states.some((state) => !["HOLD", "READY", "DISPATCHED", "TERMINAL"].includes(String(state)))) {
        throw new ProductAdapterError("INVALID_ARGUMENT", "queue states contain an unsupported or duplicate value");
      }
    }
    return bridge.listQueue({
      ...(states === undefined ? {} : { states: states as ("HOLD" | "READY" | "DISPATCHED" | "TERMINAL")[] }),
      ...(item.cursor === undefined ? {} : { cursor: requiredString(item, "cursor") }),
      ...(item.pageSize === undefined ? {} : { pageSize: requiredInteger(item, "pageSize", 1, 200) })
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.startQueuedTask, (value) => {
    const item = assertObject(value, ["taskId", "expectedStateVersion", "expectedDispatchStateVersion"]);
    return bridge.startQueuedTask({
      taskId: requiredString(item, "taskId"),
      expectedStateVersion: requiredInteger(item, "expectedStateVersion", 0, Number.MAX_SAFE_INTEGER),
      expectedDispatchStateVersion: requiredInteger(item, "expectedDispatchStateVersion", 0, Number.MAX_SAFE_INTEGER)
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.resumeFromCheckpoint, (value) => {
    const item = assertObject(value, ["taskId", "checkpointArtifactId", "compatibilityHash", "expectedStateVersion"]);
    return bridge.resumeFromCheckpoint({
      taskId: requiredString(item, "taskId"),
      checkpointArtifactId: requiredString(item, "checkpointArtifactId"),
      compatibilityHash: requiredString(item, "compatibilityHash"),
      expectedStateVersion: requiredInteger(item, "expectedStateVersion", 0, Number.MAX_SAFE_INTEGER)
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.cancelTask, (value) => {
    const item = assertObject(value, ["taskId", "expectedStateVersion", "reason"]);
    return bridge.cancelTask({
      taskId: requiredString(item, "taskId"),
      expectedStateVersion: requiredInteger(item, "expectedStateVersion", 0, Number.MAX_SAFE_INTEGER),
      reason: requiredString(item, "reason")
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.retryResearchBacktest, (value) => {
    const item = assertObject(value, ["taskId"]);
    return bridge.retryResearchBacktest(requiredString(item, "taskId"));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.getTaskEvents, (value) => {
    const item = assertObject(value, ["afterSequence", "limit"]);
    const afterSequence = item.afterSequence;
    const limit = item.limit;
    if (typeof afterSequence !== "number" || !Number.isInteger(afterSequence) || afterSequence < 0) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "afterSequence must be a non-negative integer");
    }
    if (typeof limit !== "number" || !Number.isInteger(limit) || limit < 1 || limit > 500) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "limit must be an integer in [1, 500]");
    }
    return bridge.getTaskEvents(afterSequence, limit);
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
  handle(PRODUCT_RUNTIME_CHANNELS.readArtifactBytes, (value) => {
    const item = assertObject(value, ["artifactId"]);
    return bridge.readArtifactBytes(requiredString(item, "artifactId"));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.exportArtifact, (value) => {
    const item = assertObject(value, ["artifactId", "suggestedName"]);
    return bridge.exportArtifact({
      artifactId: requiredString(item, "artifactId"),
      suggestedName: requiredString(item, "suggestedName")
    });
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
  const pageRequest = (value: unknown) => {
    if (value === undefined) return undefined;
    const item = assertObject(value, ["cursor", "pageSize"]);
    return {
      ...(item.cursor === undefined ? {} : { cursor: requiredString(item, "cursor") }),
      ...(item.pageSize === undefined ? {} : { pageSize: requiredInteger(item, "pageSize", 1, 100) })
    };
  };
  handle(PRODUCT_RUNTIME_CHANNELS.listProjects, (value) => bridge.listProjects(pageRequest(value)));
  handle(PRODUCT_RUNTIME_CHANNELS.listBacktestRunSpecs, (value) => bridge.listBacktestRunSpecs(pageRequest(value)));
  handle(PRODUCT_RUNTIME_CHANNELS.importResearchPackage, () => bridge.importResearchPackage());
  handle(PRODUCT_RUNTIME_CHANNELS.chooseLocalDataSource, (value) => {
    if (value !== undefined) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "chooseLocalDataSource does not accept a payload");
    }
    return bridge.chooseLocalDataSource();
  });
  handle(PRODUCT_RUNTIME_CHANNELS.importLocalDataset, (value) => {
    const item = assertObject(value, ["capabilityToken", "volumeUnit", "amountUnit", "timezone", "adjustment"]);
    const volumeUnit = item.volumeUnit;
    if (volumeUnit !== "SHARES" && volumeUnit !== "HANDS") {
      throw new ProductAdapterError("INVALID_ARGUMENT", "volumeUnit must be SHARES or HANDS");
    }
    if (item.amountUnit !== "CNY" || item.timezone !== "Asia/Shanghai" || item.adjustment !== "UNADJUSTED") {
      throw new ProductAdapterError("INVALID_ARGUMENT", "local-data semantic declarations are not admitted");
    }
    return bridge.importLocalDataset({
      capabilityToken: requiredString(item, "capabilityToken"),
      volumeUnit,
      amountUnit: "CNY",
      timezone: "Asia/Shanghai",
      adjustment: "UNADJUSTED"
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.submitResearch, (intentPayload) => {
    const intentFields = assertObject(intentPayload, ["symbol", "startDate", "endDate"]);
    return bridge.submitResearch({
      symbol: requiredString(intentFields, "symbol"),
      startDate: requiredString(intentFields, "startDate"),
      endDate: requiredString(intentFields, "endDate")
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.submitFactorStudy, (intentPayload) => {
    const intent = assertObject(intentPayload, ["formulaSource", "analysisOutputName"]);
    if (typeof intent.formulaSource !== "string" || intent.formulaSource.trim().length === 0 || intent.formulaSource.length > 65_536) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "formulaSource must be bounded non-empty TDX text");
    }
    return bridge.submitFactorStudy({
      formulaSource: intent.formulaSource,
      analysisOutputName: requiredString(intent, "analysisOutputName")
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.publishResearchStrategy, (intentPayload) => {
    const intent = assertObject(intentPayload, [
      "entrySignalFactorVersionId", "exitSignalFactorVersionId", "positionSizing",
      "maxPositions", "grossExposure", "initialCash", "assumptionProfileId"
    ]);
    if (intent.positionSizing !== "SINGLE_ASSET_FULL_WEIGHT" && intent.positionSizing !== "EQUAL_WEIGHT_ACTIVE_SIGNALS") {
      throw new ProductAdapterError("INVALID_ARGUMENT", "positionSizing is not admitted");
    }
    return bridge.publishResearchStrategy({
      entrySignalFactorVersionId: requiredString(intent, "entrySignalFactorVersionId"),
      exitSignalFactorVersionId: requiredString(intent, "exitSignalFactorVersionId"),
      positionSizing: intent.positionSizing,
      maxPositions: requiredInteger(intent, "maxPositions", 1, 20),
      grossExposure: requiredString(intent, "grossExposure"),
      initialCash: requiredString(intent, "initialCash"),
      assumptionProfileId: requiredString(intent, "assumptionProfileId")
    });
  });
  handle(PRODUCT_RUNTIME_CHANNELS.previewResearchStrategy, (intentPayload) => {
    const intent = assertObject(intentPayload, [
      "entrySignalFactorVersionId", "exitSignalFactorVersionId", "positionSizing",
      "maxPositions", "grossExposure", "initialCash", "assumptionProfileId"
    ]);
    if (intent.positionSizing !== "SINGLE_ASSET_FULL_WEIGHT" && intent.positionSizing !== "EQUAL_WEIGHT_ACTIVE_SIGNALS") {
      throw new ProductAdapterError("INVALID_ARGUMENT", "positionSizing is not admitted");
    }
    return bridge.previewResearchStrategy({
      entrySignalFactorVersionId: requiredString(intent, "entrySignalFactorVersionId"),
      exitSignalFactorVersionId: requiredString(intent, "exitSignalFactorVersionId"),
      positionSizing: intent.positionSizing,
      maxPositions: requiredInteger(intent, "maxPositions", 1, 20),
      grossExposure: requiredString(intent, "grossExposure"),
      initialCash: requiredString(intent, "initialCash"),
      assumptionProfileId: requiredString(intent, "assumptionProfileId")
    });
  });
  const researchBacktestIntent = (intentPayload: unknown) => {
    const intent = assertObject(intentPayload, [
      "sessionStart", "sessionEnd", "slippageBps", "dailyVolumeParticipationRate"
    ]);
    return {
      sessionStart: requiredString(intent, "sessionStart"),
      sessionEnd: requiredString(intent, "sessionEnd"),
      slippageBps: requiredString(intent, "slippageBps"),
      dailyVolumeParticipationRate: requiredString(intent, "dailyVolumeParticipationRate")
    };
  };
  handle(PRODUCT_RUNTIME_CHANNELS.previewResearchBacktest, (intentPayload) => {
    return bridge.previewResearchBacktest(researchBacktestIntent(intentPayload));
  });
  handle(PRODUCT_RUNTIME_CHANNELS.submitResearchBacktest, (intentPayload) => {
    return bridge.submitResearchBacktest(researchBacktestIntent(intentPayload));
  });
  return () => {
    for (const channel of Object.values(PRODUCT_RUNTIME_CHANNELS)) ipcMain.removeHandler(channel);
  };
}

export function registerUnavailableProductRuntimeIpc(
  ipcMain: IpcMain,
  trusted: TrustIpcSender,
  diagnostic: string,
): () => void {
  const capabilities = Object.freeze([
    { code: "ProductRuntime", truth_state: "UNAVAILABLE" as const, reason_code: "PACKAGED_RUNTIME_UNAVAILABLE" },
    { code: "DataSourceService", truth_state: "UNAVAILABLE" as const, reason_code: "PACKAGED_RUNTIME_UNAVAILABLE" },
  ]);
  const status: ProductStatusView = Object.freeze({
    productVersion: "UNAVAILABLE",
    backendState: "DISCONNECTED",
    bindingState: "NO_CANONICAL_PROJECT_BOUND",
    boundProject: null,
    capabilities,
    buildManifestId: null,
    buildIdentityState: "UNAVAILABLE",
  });
  const unavailable = (event: IpcMainInvokeEvent): never => {
    trusted(event);
    throw new Error(JSON.stringify(errorToView(new ProductAdapterError("BACKEND_UNAVAILABLE", diagnostic))));
  };
  ipcMain.handle(PRODUCT_RUNTIME_CHANNELS.status, (event) => { trusted(event); return status; });
  ipcMain.handle(PRODUCT_RUNTIME_CHANNELS.capabilities, (event) => { trusted(event); return capabilities; });
  for (const channel of Object.values(PRODUCT_RUNTIME_CHANNELS)) {
    if (channel !== PRODUCT_RUNTIME_CHANNELS.status && channel !== PRODUCT_RUNTIME_CHANNELS.capabilities) {
      ipcMain.handle(channel, unavailable);
    }
  }
  return () => {
    for (const channel of Object.values(PRODUCT_RUNTIME_CHANNELS)) ipcMain.removeHandler(channel);
  };
}
