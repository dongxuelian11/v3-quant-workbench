import type {
  ArtifactDescriptorView,
  ArtifactStreamTicketView,
  BacktestSubmitOutcomeView,
  ProductCapabilityView,
  ProductResultView,
  ProductTaskAttemptView,
  ProductTaskEventView,
  ProductTaskEventsView,
  ProductTaskView,
  ProjectContextView,
  SessionRestoreView
} from "../../../../../packages/contracts/src/index";

/**
 * Closed adapters from raw backend read models (unknown) into the frozen
 * Desktop product bridge DTOs. Raw payloads never flow into the renderer
 * store unvalidated: every adapter fails closed on shape drift.
 */

export class ProductAdapterError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = "ProductAdapterError";
  }
}

function record(value: unknown, name: string): Record<string, unknown> {
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${name} is not an object`);
  }
  return value as Record<string, unknown>;
}

function stringField(item: Record<string, unknown>, name: string): string {
  const value = item[name];
  if (typeof value !== "string" || value.length === 0) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${name} must be a non-empty string`);
  }
  return value;
}

function optionalStringField(item: Record<string, unknown>, name: string): string | null {
  const value = item[name];
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" || value.length === 0) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${name} must be null or a non-empty string`);
  }
  return value;
}

function intField(item: Record<string, unknown>, name: string): number {
  const value = item[name];
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${name} must be an integer`);
  }
  return value;
}

function versionField(item: Record<string, unknown>, expected: string, name: string): void {
  const value = item.read_model_version;
  if (typeof value !== "string" || value !== expected) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${name} version is not ${expected}`);
  }
}

export function adaptCapabilities(raw: unknown): readonly ProductCapabilityView[] {
  if (!Array.isArray(raw)) throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "capability list is not an array");
  return Object.freeze(raw.map((entry) => {
    const item = record(entry, "capability");
    const code = stringField(item, "code");
    const truthState = item.truth_state;
    if (truthState !== "FORMAL" && truthState !== "DEMO" && truthState !== "UNAVAILABLE") {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `capability ${code} truth state is invalid`);
    }
    const reason = item.reason_code;
    if (reason !== undefined && typeof reason !== "string") {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `capability ${code} reason code is invalid`);
    }
    return Object.freeze(reason === undefined
      ? { code, truth_state: truthState }
      : { code, truth_state: truthState, reason_code: reason });
  }));
}

export function adaptProjectContext(raw: unknown): ProjectContextView {
  const body = record(raw, "response body");
  const model = record(body.read_model, "project context read model");
  versionField(model, "v3.project-context/1.0", "project context");
  const context = record(model.context, "project context payload");
  const fieldsRaw = context.context_fields;
  const fields: { name?: string; description?: string } = {};
  if (fieldsRaw !== undefined) {
    const fieldsRecord = record(fieldsRaw, "context_fields");
    for (const key of ["name", "description"]) {
      const value = fieldsRecord[key];
      if (value !== undefined) {
        if (typeof value !== "string") throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `context field ${key} must be a string`);
        (fields as Record<string, string>)[key] = value;
      }
    }
  }
  return Object.freeze({
    readModelVersion: "v3.project-context/1.0" as const,
    projectId: stringField(model, "project_id"),
    projectContextRevisionId: stringField(model, "project_context_revision_id"),
    revisionNo: intField(model, "revision_no"),
    canonicalHash: stringField(model, "canonical_hash"),
    contextFields: Object.freeze(fields),
    createdAt: stringField(model, "created_at"),
    createdBy: stringField(model, "created_by")
  });
}

export function adaptSessionRestore(raw: unknown): SessionRestoreView {
  const body = record(raw, "response body");
  const model = record(body.read_model, "session restore read model");
  versionField(model, "v3.session-restore/1.0", "session restore");
  return Object.freeze({
    readModelVersion: "v3.session-restore/1.0" as const,
    sessionRowId: stringField(model, "session_row_id"),
    projectId: stringField(model, "project_id"),
    projectContextRevisionId: stringField(model, "project_context_revision_id"),
    state: stringField(model, "state"),
    openedAt: stringField(model, "opened_at")
  });
}

export function adaptTask(raw: unknown): ProductTaskView {
  const body = record(raw, "response body");
  const model = record(body.read_model, "task read model");
  versionField(model, "v3.task/1.0", "task");
  const attemptRaw = record(model.attempt, "task attempt");
  const attempt: ProductTaskAttemptView = Object.freeze({
    attemptId: optionalStringField(attemptRaw, "attempt_id"),
    ordinal: intField(attemptRaw, "ordinal"),
    state: stringField(attemptRaw, "state"),
    errorCategory: optionalStringField(attemptRaw, "error_category")
  });
  const outputsRaw = record(model.outputs, "task outputs");
  const outputs: Record<string, string> = {};
  for (const [role, artifactId] of Object.entries(outputsRaw)) {
    if (typeof artifactId !== "string" || artifactId.length === 0) {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `task output ${role} must be a non-empty artifact id`);
    }
    outputs[role] = artifactId;
  }
  return Object.freeze({
    readModelVersion: "v3.task/1.0" as const,
    taskId: stringField(model, "task_id"),
    projectId: stringField(model, "project_id"),
    operationId: stringField(model, "operation_id"),
    state: stringField(model, "state"),
    stateVersion: intField(model, "state_version"),
    runId: stringField(model, "run_id"),
    resultId: optionalStringField(model, "result_id"),
    attempt,
    outputs: Object.freeze(outputs),
    createdAt: stringField(model, "created_at"),
    updatedAt: stringField(model, "updated_at"),
    terminalAt: optionalStringField(model, "terminal_at")
  });
}

export function adaptTaskList(raw: unknown): readonly ProductTaskView[] {
  const body = record(raw, "response body");
  const model = record(body.read_model, "task list read model");
  const items = model.items;
  if (!Array.isArray(items)) throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "task list items must be an array");
  return Object.freeze(items.map((entry) => adaptTask({ read_model: entry })));
}

export function adaptTaskEvents(raw: unknown): ProductTaskEventsView {
  const body = record(raw, "response body");
  const model = record(body.read_model, "task events read model");
  const itemsRaw = model.items;
  if (!Array.isArray(itemsRaw)) throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "task event items must be an array");
  const items: ProductTaskEventView[] = itemsRaw.map((entry) => {
    const item = record(entry, "task event");
    const eventType = stringField(item, "event_type");
    let resultId: string | null = null;
    if (eventType === "TASK_SUCCEEDED") {
      const body = item.body;
      if (body !== null && typeof body === "object" && !Array.isArray(body)) {
        const outputs = (body as Record<string, unknown>).outputs;
        if (outputs !== null && typeof outputs === "object" && !Array.isArray(outputs)) {
          const candidate = (outputs as Record<string, unknown>).result_id;
          if (typeof candidate === "string" && candidate.length > 0) resultId = candidate;
        }
      }
    }
    return Object.freeze({
      eventId: stringField(item, "event_id"),
      projectSequence: intField(item, "project_sequence"),
      eventType,
      occurredAt: stringField(item, "occurred_at"),
      resultId
    });
  });
  return Object.freeze({ items: Object.freeze(items), highWatermark: intField(model, "high_watermark") });
}

export function adaptArtifactDescriptor(raw: unknown): ArtifactDescriptorView {
  const model = record(raw, "artifact descriptor");
  return Object.freeze({
    artifactId: stringField(model, "artifact_id"),
    sha256: stringField(model, "sha256"),
    byteSize: intField(model, "byte_size"),
    mediaType: stringField(model, "media_type"),
    role: stringField(model, "role"),
    createdAt: stringField(model, "created_at")
  });
}

export function adaptResult(raw: unknown): ProductResultView {
  const body = record(raw, "response body");
  const model = record(body.read_model, "result read model");
  versionField(model, "v3.result/1.0", "result");
  const artifactRaw = model.result_artifact;
  return Object.freeze({
    readModelVersion: "v3.result/1.0" as const,
    resultId: stringField(model, "result_id"),
    projectId: stringField(model, "project_id"),
    backtestRunId: stringField(model, "backtest_run_id"),
    codeVersion: optionalStringField(model, "code_version"),
    buildManifestId: optionalStringField(model, "build_manifest_id"),
    state: stringField(model, "state"),
    ledgerManifestArtifactId: stringField(model, "ledger_manifest_artifact_id"),
    reconciliationArtifactId: optionalStringField(model, "reconciliation_artifact_id"),
    resultArtifact: artifactRaw === null || artifactRaw === undefined ? null : adaptArtifactDescriptor(artifactRaw)
  });
}

export function adaptStreamTicket(raw: unknown): ArtifactStreamTicketView {
  const body = record(raw, "response body");
  const model = record(body.read_model, "artifact stream ticket");
  if (model.mode !== "STREAM_TICKET") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "artifact stream did not issue a STREAM_TICKET");
  }
  return Object.freeze({
    mode: "STREAM_TICKET" as const,
    ticketId: stringField(model, "ticket_id"),
    artifactId: stringField(model, "artifact_id")
  });
}

export function adaptBacktestSubmit(raw: unknown, requestId: string): BacktestSubmitOutcomeView {
  const body = record(raw, "response body");
  const taskId = stringField(body, "task_id");
  const runId = stringField(body, "run_id");
  if (body.accepted_state !== "QUEUED") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "submitBacktest accepted state must be QUEUED");
  }
  // A durable-idempotency replay repeats the accepted outcome without an
  // event cursor; the UI must not present either case as live progress.
  const idempotentReplay = body.event_cursor === undefined;
  void requestId;
  return Object.freeze({ taskId, runId, acceptedState: "QUEUED" as const, idempotentReplay });
}
