import Ajv from "ajv";
import { randomBytes } from "node:crypto";
import { mkdir, readFile, rename } from "node:fs/promises";
import { dirname } from "node:path";
import {
  DEFAULT_WORKSPACE,
  WORKSPACE_USER_FIELDS,
  applyCommandExactlyOnce,
  type CommandReceipt,
  type DesktopCommandEnvelope,
  type PersistedWorkspace
} from "../../../../../packages/contracts/src/index";

export class WorkspaceStoreError extends Error {
  readonly code: string;
  override readonly cause?: unknown;
  constructor(code: string, message: string, cause?: unknown) {
    super(message);
    this.name = "WorkspaceStoreError";
    this.code = code;
    this.cause = cause;
  }
}

export interface WorkspaceFileOps {
  readFile(path: string): Promise<string>;
  /** Open, write, fsync and close so the temp file is durable before rename. */
  writeFileDurable(path: string, content: string): Promise<void>;
  rename(from: string, to: string): Promise<void>;
  mkdir(path: string): Promise<void>;
  /** Best-effort temp cleanup; failures are swallowed by the store. */
  unlinkBestEffort(path: string): Promise<void>;
}

const defaultFileOps: WorkspaceFileOps = {
  readFile: (path) => readFile(path, "utf8"),
  writeFileDurable: async (path, content) => {
    const { open } = await import("node:fs/promises");
    const handle = await open(path, "w");
    try {
      await handle.writeFile(content, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
  },
  rename,
  mkdir: async (path) => { await mkdir(path, { recursive: true }); },
  unlinkBestEffort: async (path) => {
    const { unlink } = await import("node:fs/promises");
    try { await unlink(path); } catch { /* best effort */ }
  }
};

const LAB_IDS = ["research", "strategy", "model", "backtest", "result"];
const UNIVERSE_MODES = ["all-shares", "index", "industry", "concept", "custom-symbols", "nested-condition", "factor-top-bottom", "saved-reference", "csv-tsv-import"];
const STRATEGY_MODES = ["visual", "code", "split"];
const STRATEGY_VALIDATION = ["not-run", "valid", "invalid"];
const MODEL_FAMILIES = ["LightGBM", "XGBoost", "CatBoost", "sklearn-linear", "sklearn-tree-ensemble", "PyTorch-deep", "custom-plugin"];
const SPLIT_PLANS = ["chronological", "rolling", "expanding", "purge-embargo", "walk-forward"];
const STUDY_STATES = ["ready", "running", "paused", "cancelled", "checkpointed", "completed"];

const strategySchema = {
  type: "object",
  additionalProperties: false,
  required: ["id", "version", "mode", "code", "acceptedHunks", "rejectedHunks", "selectedNodeId", "validation", "handoffId"],
  properties: {
    id: { type: "string" },
    version: { type: "integer", minimum: 0 },
    mode: { enum: STRATEGY_MODES },
    code: { type: "string" },
    acceptedHunks: { type: "array", items: { type: "string" } },
    rejectedHunks: { type: "array", items: { type: "string" } },
    selectedNodeId: { type: ["string", "null"] },
    validation: { enum: STRATEGY_VALIDATION },
    handoffId: { type: ["string", "null"] }
  }
};

const modelSchema = {
  type: "object",
  additionalProperties: false,
  required: ["family", "datasetVersion", "label", "splitPlan", "selectedRunIds", "studyState", "checkpoint", "modelVersion", "predictionSignalVersion"],
  properties: {
    family: { enum: MODEL_FAMILIES },
    datasetVersion: { type: "string" },
    label: { type: "string" },
    splitPlan: { enum: SPLIT_PLANS },
    selectedRunIds: { type: "array", items: { type: "string" } },
    studyState: { enum: STUDY_STATES },
    checkpoint: { type: "integer", minimum: 0 },
    modelVersion: { type: ["string", "null"] },
    predictionSignalVersion: { type: ["string", "null"] }
  }
};

const runtimeFieldSchemas = {
  executedCommandIds: { type: "array", items: { type: "string" } },
  commandExecutionCount: { type: "object", additionalProperties: { type: "integer", minimum: 1 } },
  executedCommands: {
    type: "object",
    additionalProperties: {
      type: "object",
      additionalProperties: false,
      required: ["name", "issuedAt"],
      properties: { name: { type: "string" }, issuedAt: { type: "string" } }
    }
  },
  projectEventCursors: { type: "object", additionalProperties: { type: "integer", minimum: 0 } },
  persistenceRevision: { type: "integer", minimum: 0 },
  runtimeMeta: {
    type: "object",
    additionalProperties: false,
    required: ["storeSchemaVersion"],
    properties: { storeSchemaVersion: { type: "integer", minimum: 1 } }
  },
  savedAt: { type: ["string", "null"] }
};

const userFieldSchemas = {
  activeLab: { enum: LAB_IDS },
  inspectorOpen: { type: "boolean" },
  bottomOpen: { type: "boolean" },
  activeProject: { type: "string" },
  selectedAsset: { type: ["string", "null"] },
  selectedUniverseMode: { enum: UNIVERSE_MODES },
  dockLayouts: { type: "object" },
  strategy: strategySchema,
  model: modelSchema
};

const persistedWorkspaceSchema = {
  type: "object",
  additionalProperties: false,
  required: [...WORKSPACE_USER_FIELDS, "executedCommandIds", "commandExecutionCount"],
  properties: { ...userFieldSchemas, ...runtimeFieldSchemas }
};

// Renderer snapshots carry the full persisted shape (the renderer store
// mirrors runtime-owned ledger fields), but the main process must never
// apply renderer-supplied runtime-owned fields. They are accepted by the
// closed shape check and then stripped by pickUserFields.
const ignoredRendererRuntimeFields = {
  executedCommandIds: { type: "array" },
  commandExecutionCount: { type: "object" },
  executedCommands: { type: "object" },
  projectEventCursors: { type: "object" },
  persistenceRevision: { type: "integer" },
  runtimeMeta: { type: "object" },
  savedAt: { type: ["string", "null"] }
};

const userStateSchema = {
  type: "object",
  additionalProperties: false,
  required: [...WORKSPACE_USER_FIELDS],
  properties: { ...userFieldSchemas, ...ignoredRendererRuntimeFields }
};

type ClosedValidator = ((data: unknown) => boolean) & { errors?: { instancePath: string; message?: string }[] | null };
const validatePersisted = new Ajv({ allErrors: true }).compile(persistedWorkspaceSchema) as ClosedValidator;
const validateUserState = new Ajv({ allErrors: true }).compile(userStateSchema) as ClosedValidator;

function pickUserFields(value: PersistedWorkspace): Pick<PersistedWorkspace, (typeof WORKSPACE_USER_FIELDS)[number]> {
  return {
    activeLab: value.activeLab,
    inspectorOpen: value.inspectorOpen,
    bottomOpen: value.bottomOpen,
    activeProject: value.activeProject,
    selectedAsset: value.selectedAsset,
    selectedUniverseMode: value.selectedUniverseMode,
    dockLayouts: value.dockLayouts,
    strategy: value.strategy,
    model: value.model
  };
}

function materialize(parsed: PersistedWorkspace): PersistedWorkspace {
  const base = structuredClone(DEFAULT_WORKSPACE);
  return {
    ...base,
    ...structuredClone(parsed),
    executedCommands: { ...(base.executedCommands ?? {}), ...(parsed.executedCommands ?? {}) },
    projectEventCursors: { ...(base.projectEventCursors ?? {}), ...(parsed.projectEventCursors ?? {}) },
    persistenceRevision: parsed.persistenceRevision ?? 0,
    runtimeMeta: parsed.runtimeMeta ?? { storeSchemaVersion: 1 }
  };
}

function errorCodeOf(error: unknown): string | null {
  if (error !== null && typeof error === "object" && "code" in error && typeof error.code === "string") return error.code;
  return null;
}

export interface WorkspaceLoadResult {
  state: PersistedWorkspace;
  initializedFresh: boolean;
  quarantinedPath: string | null;
}

export interface WorkspaceStoreOptions {
  fileOps?: WorkspaceFileOps;
  now?: () => string;
}

/**
 * Single-file, atomic, serialized main-process workspace persistence.
 *
 * - Only ENOENT may initialize default state.
 * - Malformed / schema-invalid files are quarantined to a unique
 *   `.corrupt-<timestamp>-<random>` path before defaults are initialized;
 *   if quarantine fails the store fails closed.
 * - EACCES/EPERM and other read I/O failures fail closed and never
 *   overwrite the original file.
 * - Renderer snapshots may only replace user workspace fields; runtime-owned
 *   fields (command ledger, receipts, event cursors, persistence revision,
 *   runtime metadata) can never be overwritten by a renderer save.
 * - Every mutation and persistence entry runs on one serialized queue.
 * - Writes go to a unique `storePath.<pid>.<counter>.tmp` and are atomically
 *   renamed into place after fsync.
 */
export class WorkspaceStore {
  private readonly storePath: string;
  private readonly options: WorkspaceStoreOptions;
  private state: PersistedWorkspace;
  private chain: Promise<unknown> = Promise.resolve();
  private tempCounter = 0;
  private quiescing = false;
  private shuttingDown = false;
  quarantinePath: string | null = null;

  constructor(storePath: string, options: WorkspaceStoreOptions = {}) {
    this.storePath = storePath;
    this.options = options;
    this.state = materialize(structuredClone(DEFAULT_WORKSPACE));
  }

  get fileOps(): WorkspaceFileOps {
    return this.options.fileOps ?? defaultFileOps;
  }

  get now(): () => string {
    return this.options.now ?? (() => new Date().toISOString());
  }

  snapshot(): PersistedWorkspace {
    return structuredClone(this.state);
  }

  get persistenceRevision(): number {
    return this.state.persistenceRevision ?? 0;
  }

  getProjectEventCursor(projectId: string): number {
    return this.state.projectEventCursors?.[projectId] ?? 0;
  }

  async load(): Promise<WorkspaceLoadResult> {
    let raw: string;
    try {
      raw = await this.fileOps.readFile(this.storePath);
    } catch (error) {
      const code = errorCodeOf(error);
      if (code === "ENOENT") {
        return { state: structuredClone(this.state), initializedFresh: true, quarantinedPath: null };
      }
      if (code === "EACCES" || code === "EPERM") {
        throw new WorkspaceStoreError("WORKSPACE_STORE_PERMISSION_DENIED", `cannot read workspace store (${code}); refusing to initialize defaults over it`, error);
      }
      throw new WorkspaceStoreError("WORKSPACE_STORE_READ_FAILED", `workspace store read failed (${String(code)}); refusing to initialize defaults over it`, error);
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      await this.quarantine(error, "malformed JSON");
      return { state: structuredClone(this.state), initializedFresh: true, quarantinedPath: this.quarantinePath };
    }
    if (!validatePersisted(parsed)) {
      await this.quarantine(null, `schema invalid: ${(validatePersisted.errors ?? []).map((entry) => `${entry.instancePath} ${entry.message ?? ""}`).join("; ")}`);
      return { state: structuredClone(this.state), initializedFresh: true, quarantinedPath: this.quarantinePath };
    }
    this.state = materialize(parsed as PersistedWorkspace);
    return { state: structuredClone(this.state), initializedFresh: false, quarantinedPath: null };
  }

  saveUserState(userSnapshot: PersistedWorkspace): Promise<PersistedWorkspace> {
    return this.enqueueUser(async () => {
      if (!validateUserState(userSnapshot)) {
        throw new WorkspaceStoreError("WORKSPACE_STORE_INVALID_STATE", "renderer workspace snapshot does not match the closed user-state shape");
      }
      const next = materialize(this.state);
      Object.assign(next, pickUserFields(structuredClone(userSnapshot)));
      next.savedAt = this.now();
      next.persistenceRevision = (next.persistenceRevision ?? 0) + 1;
      await this.persist(next);
      this.state = next;
      return structuredClone(next);
    });
  }

  resetUserState(): Promise<PersistedWorkspace> {
    return this.enqueueUser(async () => {
      const next = materialize(this.state);
      Object.assign(next, pickUserFields(structuredClone(DEFAULT_WORKSPACE)));
      next.savedAt = this.now();
      next.persistenceRevision = (next.persistenceRevision ?? 0) + 1;
      await this.persist(next);
      this.state = next;
      return structuredClone(next);
    });
  }

  executeCommand(command: DesktopCommandEnvelope): Promise<CommandReceipt> {
    return this.enqueueUser(async () => {
      const applied = applyCommandExactlyOnce(this.state, command);
      if (!applied.receipt.accepted) return applied.receipt;
      applied.state.savedAt = this.now();
      applied.state.persistenceRevision = (applied.state.persistenceRevision ?? 0) + 1;
      await this.persist(applied.state);
      this.state = applied.state;
      return applied.receipt;
    });
  }

  commitProjectEventCursor(projectId: string, sequence: number): Promise<void> {
    return this.enqueue(async () => {
      if (!Number.isInteger(sequence) || sequence < 0) {
        throw new WorkspaceStoreError("WORKSPACE_STORE_INVALID_STATE", "durable event cursor must be a non-negative integer");
      }
      const current = this.state.projectEventCursors?.[projectId] ?? 0;
      if (sequence <= current) return;
      const next = materialize(this.state);
      next.projectEventCursors = { ...(next.projectEventCursors ?? {}), [projectId]: sequence };
      next.savedAt = this.now();
      next.persistenceRevision = (next.persistenceRevision ?? 0) + 1;
      await this.persist(next);
      this.state = next;
    });
  }

  flush(): Promise<void> {
    return this.enqueue(async () => {});
  }

  /**
   * Reject new durable user mutations (save/reset/command) while keeping
   * runtime cursor commits and flush alive for the shutdown drain.
   */
  beginQuiesce(): void {
    this.quiescing = true;
  }

  /** Reject every mutation including runtime cursor commits. */
  beginShutdown(): void {
    this.shuttingDown = true;
  }

  private enqueueUser<T>(task: () => Promise<T>): Promise<T> {
    if (this.shuttingDown) {
      return Promise.reject(new WorkspaceStoreError("WORKSPACE_STORE_SHUTTING_DOWN", "workspace store is shut down and rejects new mutations"));
    }
    if (this.quiescing) {
      return Promise.reject(new WorkspaceStoreError("WORKSPACE_STORE_QUIESCING", "workspace store is quitting and rejects new user mutations"));
    }
    return this.enqueue(task);
  }

  private enqueue<T>(task: () => Promise<T>): Promise<T> {
    if (this.shuttingDown) {
      return Promise.reject(new WorkspaceStoreError("WORKSPACE_STORE_SHUTTING_DOWN", "workspace store is shut down and rejects new mutations"));
    }
    const result = this.chain.then(task, task);
    this.chain = result.then(() => undefined, () => undefined);
    return result;
  }

  private async quarantine(cause: unknown, reason: string): Promise<void> {
    const quarantine = `${this.storePath}.corrupt-${Date.now()}-${randomBytes(4).toString("hex")}`;
    try {
      await this.fileOps.rename(this.storePath, quarantine);
    } catch (error) {
      throw new WorkspaceStoreError("WORKSPACE_STORE_QUARANTINE_FAILED", `workspace store is ${reason} and quarantine rename failed; refusing to overwrite`, error);
    }
    this.quarantinePath = quarantine;
  }

  private async persist(next: PersistedWorkspace): Promise<void> {
    const temporary = `${this.storePath}.${process.pid}.${this.tempCounter++}.tmp`;
    const serialized = JSON.stringify(next, null, 2);
    try {
      await this.fileOps.mkdir(dirname(this.storePath));
      await this.fileOps.writeFileDurable(temporary, serialized);
      await this.fileOps.rename(temporary, this.storePath);
    } catch (error) {
      await this.fileOps.unlinkBestEffort(temporary).catch(() => {});
      throw new WorkspaceStoreError("WORKSPACE_STORE_WRITE_FAILED", "workspace store atomic write failed; in-memory state was not advanced", error);
    }
  }
}
