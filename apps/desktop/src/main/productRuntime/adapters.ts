import type {
  ArtifactDescriptorView,
  ArtifactStreamTicketView,
  BacktestSubmitOutcomeView,
  ProductResearchSubmitOutcomeView,
  ProductCapabilityView,
  ProductResultView,
  ProductTaskAttemptView,
  ProductTaskEventView,
  ProductTaskEventsView,
  ProductTasksListView,
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
  override readonly cause?: unknown;

  constructor(code: string, message: string, cause?: unknown) {
    super(message);
    this.code = code;
    this.name = "ProductAdapterError";
    this.cause = cause;
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

export type SessionRestoreWithCanonicalIdentity = SessionRestoreView & {
  readonly canonicalSessionUuid: string;
};

export function adaptSessionRestore(raw: unknown): SessionRestoreWithCanonicalIdentity {
  const body = record(raw, "response body");
  const model = record(body.read_model, "session restore read model");
  versionField(model, "v3.session-restore/1.0", "session restore");
  return Object.freeze({
    readModelVersion: "v3.session-restore/1.0" as const,
    sessionRowId: stringField(model, "session_row_id"),
    canonicalSessionUuid: stringField(model, "canonical_session_uuid"),
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
    errorCategory: optionalStringField(attemptRaw, "error_category"),
    reasonCode: optionalStringField(attemptRaw, "reason_code")
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

export function adaptTaskList(raw: unknown): ProductTasksListView {
  const body = record(raw, "response body");
  const model = record(body.read_model, "task list read model");
  const items = model.items;
  if (!Array.isArray(items)) throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "task list items must be an array");
  const hasMore = model.has_more;
  const nextCursor = model.next_cursor;
  if (typeof hasMore !== "boolean") throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "task list has_more must be boolean");
  if (nextCursor !== null && (typeof nextCursor !== "string" || nextCursor.length < 1 || nextCursor.length > 2048)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "task list next_cursor must be null or a bounded opaque string");
  }
  if (hasMore !== (nextCursor !== null)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "task list cursor does not match has_more");
  }
  return Object.freeze({
    tasks: Object.freeze(items.map((entry) => adaptTask({ read_model: entry }))),
    hasMore,
    nextCursor: nextCursor as string | null
  });
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
    let progress: ProductTaskEventView["progress"] = null;
    if (eventType === "TASK_SUCCEEDED") {
      const eventBody = item.body;
      if (eventBody !== null && typeof eventBody === "object" && !Array.isArray(eventBody)) {
        const direct = (eventBody as Record<string, unknown>).result_id;
        if (typeof direct === "string" && direct.length > 0) resultId = direct;
        const outputs = (eventBody as Record<string, unknown>).outputs;
        if (outputs !== null && typeof outputs === "object" && !Array.isArray(outputs)) {
          const candidate = (outputs as Record<string, unknown>).result_id;
          if (typeof candidate === "string" && candidate.length > 0) resultId = candidate;
        }
      }
    } else if (eventType === "TASK_PROGRESS") {
      const eventBody = record(item.body, "task progress body");
      const keys = Object.keys(eventBody).sort().join(",");
      const phase = eventBody.phase;
      const completedUnits = eventBody.completed_units;
      const totalUnits = eventBody.total_units;
      const workUnit = eventBody.work_unit;
      if (
        keys !== "completed_units,phase,total_units,work_unit"
        || !["ACQUIRING", "VALIDATING", "COMPUTING", "PUBLISHING", "RECONCILING"].includes(String(phase))
        || !Number.isSafeInteger(completedUnits) || Number(completedUnits) < 0
        || !Number.isSafeInteger(totalUnits) || Number(totalUnits) < 1 || Number(completedUnits) > Number(totalUnits)
        || typeof workUnit !== "string" || workUnit.length < 1 || workUnit.length > 128
      ) {
        throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "task progress event is invalid");
      }
      progress = Object.freeze({
        phase: phase as NonNullable<ProductTaskEventView["progress"]>["phase"],
        completedUnits: Number(completedUnits),
        totalUnits: Number(totalUnits),
        workUnit
      });
    }
    return Object.freeze({
      eventId: stringField(item, "event_id"),
      taskId: stringField(item, "task_id"),
      projectSequence: intField(item, "project_sequence"),
      eventType,
      occurredAt: stringField(item, "occurred_at"),
      resultId,
      progress
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

const RESEARCH_ADMISSION_FIELDS = new Set([
  "read_model_version", "task_id", "run_id", "accepted_state", "maturity",
  "research_profile_id", "strategy_profile_id", "research_classification",
  "truth_admission", "event_cursor"
]);

function researchAdmissionModel(raw: unknown): Record<string, unknown> {
  const body = record(raw, "response body");
  if (body.truth_state !== "DEMO") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "research submission truth state is not DEMO");
  }
  const model = record(body.read_model, "research submission read model");
  const unknownFields = Object.keys(model).filter((key) => !RESEARCH_ADMISSION_FIELDS.has(key));
  if (unknownFields.length > 0) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `research submission returned unsupported fields: ${unknownFields.join(", ")}`);
  }
  versionField(model, "v3.product-entry-research/1.0", "research submission");
  return model;
}

function assertResearchAdmissionIdentity(model: Record<string, unknown>): void {
  if (model.accepted_state !== "QUEUED") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "research submission accepted state must be QUEUED");
  }
  if (model.maturity !== "PRODUCT_CONNECTED_CANDIDATE") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "research submission maturity is not PRODUCT_CONNECTED_CANDIDATE");
  }
  if (model.research_profile_id !== "RESEARCH_FREE_DATA_V1" || model.strategy_profile_id !== "RESEARCH_CLOSE_RANK_TOP1_V1") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "research submission profile identity is invalid");
  }
}

function assertResearchClassification(model: Record<string, unknown>): void {
  const classification = model.research_classification;
  if (!Array.isArray(classification) || classification.length !== 2 || classification[0] !== "RESEARCH_ONLY" || classification[1] !== "APPROXIMATE") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "research submission classification is invalid");
  }
}

function assertResearchTruthAdmission(model: Record<string, unknown>): void {
  const admission = record(model.truth_admission, "research truth admission");
  if (admission.truth !== "NOT_FORMAL" || admission.admission !== "PRE_ALPHA") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "research submission truth admission is invalid");
  }
}

function researchEventCursor(model: Record<string, unknown>): number | undefined {
  const eventCursor = model.event_cursor;
  if (eventCursor !== undefined && (typeof eventCursor !== "number" || !Number.isInteger(eventCursor) || eventCursor < 1)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "research submission event cursor is invalid");
  }
  return eventCursor as number | undefined;
}

export function adaptResearchSubmit(raw: unknown, requestId: string): ProductResearchSubmitOutcomeView {
  const model = researchAdmissionModel(raw);
  assertResearchAdmissionIdentity(model);
  assertResearchClassification(model);
  assertResearchTruthAdmission(model);
  const eventCursor = researchEventCursor(model);
  void requestId;
  return Object.freeze({
    truthState: "DEMO" as const,
    taskId: stringField(model, "task_id"),
    runId: stringField(model, "run_id"),
    acceptedState: "QUEUED" as const,
    idempotentReplay: eventCursor === undefined,
    maturity: "PRODUCT_CONNECTED_CANDIDATE" as const,
    researchProfileId: "RESEARCH_FREE_DATA_V1" as const,
    strategyProfileId: "RESEARCH_CLOSE_RANK_TOP1_V1" as const,
    researchClassification: ["RESEARCH_ONLY", "APPROXIMATE"] as const,
    truthAdmission: { truth: "NOT_FORMAL", admission: "PRE_ALPHA" } as const,
    ...(eventCursor === undefined ? {} : { eventCursor })
  });
}
