import { randomBytes, createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import type {
  ArtifactDescriptorView,
  ArtifactStreamBytesView,
  ArtifactStreamTicketView,
  BacktestSubmitOutcomeView,
  ImportResearchPackageOutcomeView,
  LocalDataSourceSelectionView,
  ProductLocalDataImportIntent,
  ProductLocalDataImportOutcomeView,
  ProductLatestResultDetailsView,
  ProductArtifactExportIntent,
  ProductArtifactExportOutcomeView,
  ProductFactorStudyIntent,
  ProductFactorStudyOutcomeView,
  ProductFactorSummaryView,
  ProductProjectHomeView,
  ProductResearchBacktestIntent,
  ProductResearchBacktestOutcomeView,
  ProductResearchBacktestPreviewView,
  ProductResearchStrategyIntent,
  ProductResearchStrategyOutcomeView,
  ProductResearchStrategyPreviewView,
  ProductStrategyAuthoringProfileView,
  ProductStrategyProfileRefsView,
  ProductStrategySummaryView,
  ProductBacktestSummaryView,
  ProductResearchSubmitIntent,
  ProductResearchSubmitOutcomeView,
  ProductBindingRefs,
  ProductCapabilityView,
  ProductResultView,
  ProductStatusView,
  ProductTaskEventsView,
  ProductTaskListFilter,
  ProductTaskPageRequest,
  ProductTasksListView,
  ProductPageRequest,
  ProductTaskView,
  ProjectContextView,
  ProjectCreatedView,
  ProjectsListView,
  RunSpecEntryView,
  RunSpecsListView,
  SessionRestoreView
} from "../../../../../packages/contracts/src/index";
import type { BackendSupervisor } from "../backendRuntime/supervisor";
import type { WorkspaceStore } from "../runtimePersistence/workspaceStore";
import {
  adaptArtifactDescriptor,
  adaptBacktestSubmit,
  adaptCapabilities,
  adaptProjectContext,
  adaptResearchSubmit,
  adaptResult,
  adaptSessionRestore,
  adaptStreamTicket,
  adaptTask,
  adaptTaskEvents,
  adaptTaskList,
  ProductAdapterError,
  type SessionRestoreWithCanonicalIdentity
} from "./adapters";
import {
  ProductBindingStoreError,
  type PersistedProductBinding,
  type ProductBindingStore
} from "./bindingStore";
import {
  CreateProjectIntentStore,
  createProjectIntentPath,
  runCreateProjectIntent,
} from "./createProjectIntentStore";
import { LocalDataSourceBroker } from "./localDataImport";
import { ArtifactExportBroker } from "./artifactExport";
import transportContract from "../../../../../packages/contracts/research_package_transport_v1.json";

/**
 * Typed B3 product bridge owned by the Electron main process.
 *
 * Every method maps to one admitted frozen operation; the transport envelope
 * (request_id, project binding, idempotency keys) is main-process owned.
 * The renderer never receives raw backend payloads and never controls
 * transport envelope fields.
 */

const ADMITTED_EXECUTION_ADAPTER_VERSION_ID = "v3.a_share_daily_eod_engine/0.2.0";
const RUN_SPEC_ID_PATTERN = /^btrs_sha256_[0-9a-f]{64}$/;
const ARTIFACT_ID_PATTERN = /^art_sha256_[0-9a-f]{64}$/;
const CONTENT_SHA_PATTERN = /^[0-9a-f]{64}$/;
const PROJECT_ID_PATTERN = /^prj_[0-9A-HJKMNP-TV-Z]{26}$/;
const PROJECT_CONTEXT_REVISION_PATTERN = /^pcr_[0-9A-HJKMNP-TV-Z]{26}$/;
const TASK_ID_PATTERN = /^tsk_[0-9A-HJKMNP-TV-Z]{26}$/;
const RUN_ID_PATTERN = /^run_[0-9A-HJKMNP-TV-Z]{26}$/;
const CANONICAL_ID_PATTERN = /^[A-Za-z0-9_\-]{1,200}$/;
const PROJECT_LOCATOR_PREFIX = "v3:";
const PRODUCT_ENTRY_PROTOCOL_VERSION = "v3.product-entry/1.0.0";
const PACKAGE_MANIFEST_FILENAME = "manifest.v3.json";
const MAX_PACKAGE_FILE_BYTES = transportContract.max_package_file_bytes;
const MAX_PACKAGE_FILE_COUNT = transportContract.max_package_file_count;
const MAX_PACKAGE_TOTAL_BYTES = transportContract.max_package_total_bytes;
const MAX_PACKAGE_MANIFEST_BYTES = transportContract.max_package_manifest_bytes;
const PACKAGE_PATH_PATTERN = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const RESEARCH_SYMBOL_PATTERN = /^[0-9]{6}$/;
const RESEARCH_DATE_PATTERN = /^[0-9]{8}$/;
const DEFAULT_PRODUCT_PAGE_SIZE = 50;
const MAX_PRODUCT_PAGE_SIZE = 100;
const PRODUCT_CURSOR_VERSION = 1;
const PROJECT_CURSOR_SORT = "project_id ASC";
const RUN_SPEC_CURSOR_SORT = "artifact_id ASC";
const PRODUCT_RESEARCH_BACKTEST_OPERATION = "ProductEntryService.v1.submitResearchBacktest";
const RETRYABLE_PRODUCT_TASK_CATEGORIES = new Set([
  "TRANSIENT_IO",
  "WORKER_LOST",
  "PROVIDER_THROTTLED",
  "RETRYABLE_ADAPTER",
  "WORKER_OOM"
]);

type ProductCursorPayload =
  | {
      readonly v: typeof PRODUCT_CURSOR_VERSION;
      readonly owner: "projects";
      readonly sort: typeof PROJECT_CURSOR_SORT;
      readonly after: string;
    }
  | {
      readonly v: typeof PRODUCT_CURSOR_VERSION;
      readonly owner: "run_specs";
      readonly sort: typeof RUN_SPEC_CURSOR_SORT;
      readonly projectId: string;
      readonly projectContextRevisionId: string;
      readonly after: string;
    };

function encodeProductCursor(payload: ProductCursorPayload): string {
  return Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
}

function decodeProductCursor(cursor: string): Record<string, unknown> {
  if (!/^[A-Za-z0-9_-]+$/.test(cursor)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "cursor must be canonical base64url");
  }
  try {
    const bytes = Buffer.from(cursor, "base64url");
    if (bytes.toString("base64url") !== cursor) throw new Error("non-canonical base64url");
    const value: unknown = JSON.parse(bytes.toString("utf8"));
    if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("non-object cursor");
    return value as Record<string, unknown>;
  } catch (error) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "cursor is not a valid opaque product cursor", error);
  }
}

function decodeProjectCursor(cursor: string): string {
  const value = decodeProductCursor(cursor);
  if (
    Object.keys(value).sort().join(",") !== "after,owner,sort,v"
    || value.v !== PRODUCT_CURSOR_VERSION
    || value.owner !== "projects"
    || value.sort !== PROJECT_CURSOR_SORT
    || typeof value.after !== "string"
    || !PROJECT_ID_PATTERN.test(value.after)
  ) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "project cursor owner or sort binding is invalid");
  }
  return value.after;
}

function decodeRunSpecCursor(cursor: string, refs: ProductBindingRefs): string {
  const value = decodeProductCursor(cursor);
  if (
    Object.keys(value).sort().join(",") !== "after,owner,projectContextRevisionId,projectId,sort,v"
    || value.v !== PRODUCT_CURSOR_VERSION
    || value.owner !== "run_specs"
    || value.sort !== RUN_SPEC_CURSOR_SORT
    || value.projectId !== refs.projectId
    || value.projectContextRevisionId !== refs.projectContextRevisionId
    || typeof value.after !== "string"
    || !ARTIFACT_ID_PATTERN.test(value.after)
  ) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "run-spec cursor project owner or sort binding is invalid");
  }
  return value.after;
}

function assertResearchIntent(request: ProductResearchSubmitIntent): void {
  if (!RESEARCH_SYMBOL_PATTERN.test(request.symbol)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "symbol must be six ASCII digits");
  }
  if (!RESEARCH_DATE_PATTERN.test(request.startDate) || !RESEARCH_DATE_PATTERN.test(request.endDate)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "research dates must use YYYYMMDD");
  }
}

function assertLocalDataImportIntent(request: ProductLocalDataImportIntent): void {
  if (request === null || typeof request !== "object" || Array.isArray(request)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "local-data import intent must be an object");
  }
  const expected = ["adjustment", "amountUnit", "capabilityToken", "timezone", "volumeUnit"];
  if (Object.keys(request).sort().join(",") !== expected.join(",")) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "local-data import intent fields do not match the closed shape");
  }
  if (typeof request.capabilityToken !== "string" || request.capabilityToken.length < 16 || request.capabilityToken.length > 128) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "local-data capabilityToken is invalid");
  }
  if (request.volumeUnit !== "SHARES" && request.volumeUnit !== "HANDS") {
    throw new ProductAdapterError("INVALID_ARGUMENT", "volumeUnit must be SHARES or HANDS");
  }
  if (request.amountUnit !== "CNY" || request.timezone !== "Asia/Shanghai" || request.adjustment !== "UNADJUSTED") {
    throw new ProductAdapterError("INVALID_ARGUMENT", "local-data amount/timezone/adjustment semantics are not admitted");
  }
}

function assertArtifactExportIntent(request: ProductArtifactExportIntent): void {
  if (request === null || typeof request !== "object" || Array.isArray(request)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "artifact export intent must be an object");
  }
  if (Object.keys(request).sort().join(",") !== "artifactId,suggestedName") {
    throw new ProductAdapterError("INVALID_ARGUMENT", "artifact export intent fields do not match the closed shape");
  }
  if (!ARTIFACT_ID_PATTERN.test(request.artifactId)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "artifactId must be a canonical Artifact identity");
  }
  if (typeof request.suggestedName !== "string" || request.suggestedName.length < 1 || request.suggestedName.length > 255) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "suggestedName must be a bounded filename");
  }
}

function adaptArtifactExportAccepted(value: unknown): { taskId: string; runId: string } {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "artifact export acceptance is not an object");
  }
  const record = value as Record<string, unknown>;
  const allowed = new Set(["request_id", "task_id", "run_id", "accepted_state", "event_cursor"]);
  if (Object.keys(record).some((key) => !allowed.has(key)) || record.accepted_state !== "QUEUED") {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "artifact export acceptance fields are invalid");
  }
  if (typeof record.task_id !== "string" || !TASK_ID_PATTERN.test(record.task_id)
    || typeof record.run_id !== "string" || !RUN_ID_PATTERN.test(record.run_id)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "artifact export acceptance identities are invalid");
  }
  if (record.event_cursor !== undefined && (!Number.isSafeInteger(record.event_cursor) || Number(record.event_cursor) < 1)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "artifact export event cursor is invalid");
  }
  return { taskId: record.task_id, runId: record.run_id };
}

function exportFailureReason(error: unknown): string {
  const code = error !== null && typeof error === "object" && "code" in error
    ? String((error as { code?: unknown }).code)
    : "ARTIFACT_EXPORT_FAILED";
  return /^[A-Z][A-Z0-9_]{0,127}$/.test(code) ? code : "ARTIFACT_EXPORT_FAILED";
}

function adaptLocalDataImportOutcome(response: unknown): ProductLocalDataImportOutcomeView {
  if (response === null || typeof response !== "object" || Array.isArray(response)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "local-data import returned a non-object response");
  }
  const top = response as Record<string, unknown>;
  if (top.truth_state !== "NOT_FORMAL") {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "local-data import returned an invalid truth_state");
  }
  const value = top.read_model;
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "local-data import returned a non-object read_model");
  }
  const readModel = value as Record<string, unknown>;
  const required = [
    "accepted_state", "admission", "checkpoint_resume", "maturity", "read_model_version",
    "retry", "run_id", "source_artifact_id", "task_id", "truth"
  ];
  const allowed = new Set([...required, "event_cursor"]);
  if (required.some((key) => !(key in readModel)) || Object.keys(readModel).some((key) => !allowed.has(key))) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "local-data import read_model fields do not match the closed shape");
  }
  if (
    readModel.read_model_version !== "v3.product-entry-local-data/1.1"
    || readModel.accepted_state !== "QUEUED"
    || readModel.maturity !== "PRODUCT_CONNECTED"
    || readModel.truth !== "NOT_FORMAL"
    || readModel.admission !== "PRE_ALPHA"
    || readModel.checkpoint_resume !== "UNAVAILABLE"
    || readModel.retry !== "NEW_ATTEMPT_SAME_RUN_FROM_START"
    || typeof readModel.task_id !== "string"
    || !CANONICAL_ID_PATTERN.test(readModel.task_id)
    || typeof readModel.run_id !== "string"
    || !CANONICAL_ID_PATTERN.test(readModel.run_id)
    || typeof readModel.source_artifact_id !== "string"
    || !ARTIFACT_ID_PATTERN.test(readModel.source_artifact_id)
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "local-data import read_model is invalid");
  }
  if (readModel.event_cursor !== undefined && (!Number.isSafeInteger(readModel.event_cursor) || Number(readModel.event_cursor) < 0)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "local-data import event_cursor is invalid");
  }
  return Object.freeze({
    taskId: readModel.task_id,
    runId: readModel.run_id,
    acceptedState: "QUEUED",
    maturity: "PRODUCT_CONNECTED",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    checkpointResume: "UNAVAILABLE",
    retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
    sourceArtifactId: readModel.source_artifact_id,
    ...(readModel.event_cursor === undefined ? {} : { eventCursor: Number(readModel.event_cursor) })
  });
}

function assertFactorStudyIntent(request: ProductFactorStudyIntent): void {
  if (request === null || typeof request !== "object" || Array.isArray(request)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Factor study intent must be an object");
  }
  if (Object.keys(request).sort().join(",") !== "analysisOutputName,formulaSource") {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Factor study intent fields do not match the closed shape");
  }
  if (typeof request.formulaSource !== "string" || request.formulaSource.trim().length === 0 || request.formulaSource.length > 65_536) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "formulaSource must be bounded non-empty TDX text");
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(request.analysisOutputName)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "analysisOutputName is invalid");
  }
}

function adaptFactorStudyOutcome(response: unknown): ProductFactorStudyOutcomeView {
  if (response === null || typeof response !== "object" || Array.isArray(response)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor study returned a non-object response");
  }
  const top = response as Record<string, unknown>;
  const value = top.read_model;
  if (top.truth_state !== "NOT_FORMAL" || value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor study truth or read model is invalid");
  }
  const model = value as Record<string, unknown>;
  const required = [
    "accepted_state", "admission", "analysis_output_name", "checkpoint_resume",
    "formula_document_version_id", "maturity", "read_model_version", "retry",
    "run_id", "task_id", "truth"
  ];
  const allowed = new Set([...required, "event_cursor"]);
  if (required.some((key) => !(key in model)) || Object.keys(model).some((key) => !allowed.has(key))) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor study acceptance fields do not match the closed shape");
  }
  if (
    model.read_model_version !== "v3.product-entry-factor-study/1.1"
    || model.accepted_state !== "QUEUED"
    || model.maturity !== "PRODUCT_CONNECTED"
    || model.truth !== "NOT_FORMAL"
    || model.admission !== "PRE_ALPHA"
    || model.checkpoint_resume !== "UNAVAILABLE"
    || model.retry !== "NEW_ATTEMPT_SAME_RUN_FROM_START"
    || typeof model.task_id !== "string" || !CANONICAL_ID_PATTERN.test(model.task_id)
    || typeof model.run_id !== "string" || !CANONICAL_ID_PATTERN.test(model.run_id)
    || typeof model.formula_document_version_id !== "string" || !/^fdoc_sha256_[0-9a-f]{64}$/.test(model.formula_document_version_id)
    || typeof model.analysis_output_name !== "string" || !/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(model.analysis_output_name)
    || (model.event_cursor !== undefined && (!Number.isSafeInteger(model.event_cursor) || Number(model.event_cursor) < 1))
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor study acceptance identity or truth is invalid");
  }
  return Object.freeze({
    taskId: model.task_id,
    runId: model.run_id,
    acceptedState: "QUEUED",
    maturity: "PRODUCT_CONNECTED",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    checkpointResume: "UNAVAILABLE",
    retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
    formulaDocumentVersionId: model.formula_document_version_id,
    analysisOutputName: model.analysis_output_name,
    ...(model.event_cursor === undefined ? {} : { eventCursor: Number(model.event_cursor) })
  });
}

function assertResearchStrategyIntent(request: ProductResearchStrategyIntent): void {
  if (request === null || typeof request !== "object" || Array.isArray(request)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Strategy intent must be an object");
  }
  const keys = [
    "assumptionProfileId", "entrySignalFactorVersionId", "exitSignalFactorVersionId",
    "grossExposure", "initialCash", "maxPositions", "positionSizing"
  ];
  if (Object.keys(request).sort().join(",") !== keys.sort().join(",")) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Strategy intent fields do not match the closed shape");
  }
  if (!/^fdv_sha256_[0-9a-f]{64}$/.test(request.entrySignalFactorVersionId)
    || !/^fdv_sha256_[0-9a-f]{64}$/.test(request.exitSignalFactorVersionId)
    || !/^assumption_sha256_[0-9a-f]{64}$/.test(request.assumptionProfileId)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Strategy Factor refs are not canonical");
  }
  if (!['SINGLE_ASSET_FULL_WEIGHT', 'EQUAL_WEIGHT_ACTIVE_SIGNALS'].includes(request.positionSizing)
    || !Number.isInteger(request.maxPositions) || request.maxPositions < 1 || request.maxPositions > 20
    || (request.positionSizing === "SINGLE_ASSET_FULL_WEIGHT" && request.maxPositions !== 1)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Strategy sizing is outside the admitted profile");
  }
  if (!/^(?:0(?:\.[0-9]+)?|1(?:\.0+)?)$/.test(request.grossExposure)
    || !/^(?:[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)$/.test(request.initialCash)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Strategy exposure or initial cash is not canonical decimal text");
  }
}

function assertResearchBacktestIntent(request: ProductResearchBacktestIntent): void {
  if (request === null || typeof request !== "object" || Array.isArray(request)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Backtest intent must be an object");
  }
  if (Object.keys(request).sort().join(",") !== "dailyVolumeParticipationRate,sessionEnd,sessionStart,slippageBps") {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Backtest intent fields do not match the closed shape");
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(request.sessionStart)
    || !/^\d{4}-\d{2}-\d{2}$/.test(request.sessionEnd)
    || request.sessionEnd < request.sessionStart) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Backtest session range is invalid");
  }
  const decimal = /^(?:0\.[0-9]*[1-9][0-9]*|[1-9][0-9]*(?:\.[0-9]+)?)$/;
  if (!decimal.test(request.slippageBps) || Number(request.slippageBps) > 10_000
    || !decimal.test(request.dailyVolumeParticipationRate) || Number(request.dailyVolumeParticipationRate) > 1) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "Backtest execution profile is outside the admitted range");
  }
}

function adaptQueuedC3Outcome(
  response: unknown,
  schemaVersion: "v3.product-entry-research-strategy/1.1" | "v3.product-entry-research-backtest/1.1",
  identityKey: "research_strategy_spec_id" | "research_backtest_request_id"
): Readonly<Record<string, unknown>> {
  if (response === null || typeof response !== "object" || Array.isArray(response)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "product C3 submission returned a non-object response");
  }
  const top = response as Record<string, unknown>;
  if (top.truth_state !== "NOT_FORMAL" || top.read_model === null || typeof top.read_model !== "object" || Array.isArray(top.read_model)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "product C3 submission truth or read model is invalid");
  }
  const model = top.read_model as Record<string, unknown>;
  const required = [
    "accepted_state", "admission", "checkpoint_resume", identityKey, "maturity",
    "read_model_version", "retry", "run_id", "task_id", "truth"
  ];
  const allowed = new Set([...required, "event_cursor"]);
  if (
    required.some((key) => !(key in model)) || Object.keys(model).some((key) => !allowed.has(key))
    || model.read_model_version !== schemaVersion || model.accepted_state !== "QUEUED"
    || model.maturity !== "PRODUCT_CONNECTED" || model.truth !== "NOT_FORMAL" || model.admission !== "PRE_ALPHA"
    || model.checkpoint_resume !== "UNAVAILABLE" || model.retry !== "NEW_ATTEMPT_SAME_RUN_FROM_START"
    || typeof model.task_id !== "string" || !CANONICAL_ID_PATTERN.test(model.task_id)
    || typeof model.run_id !== "string" || !CANONICAL_ID_PATTERN.test(model.run_id)
    || typeof model[identityKey] !== "string" || !CANONICAL_ID_PATTERN.test(model[identityKey])
    || (model.event_cursor !== undefined && (!Number.isSafeInteger(model.event_cursor) || Number(model.event_cursor) < 1))
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "product C3 submission identity or truth drifted");
  }
  return model;
}

function adaptResearchStrategyOutcome(response: unknown): ProductResearchStrategyOutcomeView {
  const model = adaptQueuedC3Outcome(response, "v3.product-entry-research-strategy/1.1", "research_strategy_spec_id");
  return Object.freeze({
    taskId: model.task_id as string, runId: model.run_id as string, acceptedState: "QUEUED",
    maturity: "PRODUCT_CONNECTED", truth: "NOT_FORMAL", admission: "PRE_ALPHA",
    checkpointResume: "UNAVAILABLE", retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
    researchStrategySpecId: model.research_strategy_spec_id as string,
    ...(model.event_cursor === undefined ? {} : { eventCursor: Number(model.event_cursor) })
  });
}

function adaptResearchStrategyPreview(response: unknown): ProductResearchStrategyPreviewView {
  const top = closedRecord(response, ["read_model", "request_id", "truth_state"], "Strategy preview response");
  if (top.truth_state !== "NOT_FORMAL") {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy preview truth drifted");
  }
  const model = closedRecord(top.read_model, [
    "admission", "assumption_mode", "entry_signal_factor_version_id", "exit_signal_factor_version_id",
    "maturity", "planned_decision_chain_count", "profile_refs", "project_context_revision_id",
    "project_id", "research_strategy_spec_id", "schema_version", "side_effects", "snapshot_id",
    "strategy_definition_version_id", "transition_count", "truth", "universe_version_id"
  ], "Strategy preview");
  if (
    model.schema_version !== "v3.product-strategy-preview/1.0.0"
    || model.maturity !== "PRODUCT_CONNECTED" || model.truth !== "NOT_FORMAL" || model.admission !== "PRE_ALPHA"
    || model.side_effects !== "NONE"
    || typeof model.project_id !== "string" || !PROJECT_ID_PATTERN.test(model.project_id)
    || typeof model.project_context_revision_id !== "string" || !PROJECT_CONTEXT_REVISION_PATTERN.test(model.project_context_revision_id)
    || typeof model.snapshot_id !== "string" || !CANONICAL_ID_PATTERN.test(model.snapshot_id)
    || typeof model.universe_version_id !== "string" || !CANONICAL_ID_PATTERN.test(model.universe_version_id)
    || typeof model.research_strategy_spec_id !== "string" || !/^rssv_sha256_[0-9a-f]{64}$/.test(model.research_strategy_spec_id)
    || typeof model.strategy_definition_version_id !== "string" || !/^sdv_sha256_[0-9a-f]{64}$/.test(model.strategy_definition_version_id)
    || typeof model.entry_signal_factor_version_id !== "string" || !CANONICAL_ID_PATTERN.test(model.entry_signal_factor_version_id)
    || typeof model.exit_signal_factor_version_id !== "string" || !CANONICAL_ID_PATTERN.test(model.exit_signal_factor_version_id)
    || (model.assumption_mode !== "RESEARCH_APPROXIMATE" && model.assumption_mode !== "STRICT_FAIL_CLOSED")
    || !Number.isSafeInteger(model.transition_count) || Number(model.transition_count) < 0
    || !Number.isSafeInteger(model.planned_decision_chain_count) || Number(model.planned_decision_chain_count) < 0
    || model.transition_count !== model.planned_decision_chain_count
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy preview identity or counts drifted");
  }
  return Object.freeze({
    schemaVersion: "v3.product-strategy-preview/1.0.0",
    maturity: "PRODUCT_CONNECTED",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    projectId: model.project_id,
    projectContextRevisionId: model.project_context_revision_id,
    snapshotId: model.snapshot_id,
    universeVersionId: model.universe_version_id,
    researchStrategySpecId: model.research_strategy_spec_id,
    strategyDefinitionVersionId: model.strategy_definition_version_id,
    entrySignalFactorVersionId: model.entry_signal_factor_version_id,
    exitSignalFactorVersionId: model.exit_signal_factor_version_id,
    profileRefs: adaptStrategyProfileRefs(model.profile_refs, "Strategy preview"),
    assumptionMode: model.assumption_mode,
    transitionCount: Number(model.transition_count),
    plannedDecisionChainCount: Number(model.planned_decision_chain_count),
    sideEffects: "NONE"
  });
}

function adaptResearchBacktestOutcome(response: unknown): ProductResearchBacktestOutcomeView {
  const model = adaptQueuedC3Outcome(response, "v3.product-entry-research-backtest/1.1", "research_backtest_request_id");
  return Object.freeze({
    taskId: model.task_id as string, runId: model.run_id as string, acceptedState: "QUEUED",
    maturity: "PRODUCT_CONNECTED", truth: "NOT_FORMAL", admission: "PRE_ALPHA",
    checkpointResume: "UNAVAILABLE", retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
    researchBacktestRequestId: model.research_backtest_request_id as string,
    ...(model.event_cursor === undefined ? {} : { eventCursor: Number(model.event_cursor) })
  });
}

function adaptResearchBacktestPreview(response: unknown): ProductResearchBacktestPreviewView {
  const top = closedRecord(response, ["read_model", "request_id", "truth_state"], "Backtest preflight response");
  if (top.truth_state !== "NOT_FORMAL") throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Backtest preflight truth drifted");
  const model = closedRecord(top.read_model, [
    "admission", "assumption_mode", "commission_rate", "daily_volume_participation_rate",
    "maturity", "minimum_commission_cny", "policy_refs", "project_context_revision_id",
    "project_id", "research_backtest_request_id", "research_strategy_spec_id", "resource_estimate",
    "schema_version", "session_end", "session_start", "side_effects", "slippage_bps", "snapshot_id",
    "stamp_duty_sell_rate", "status", "truth", "universe_version_id"
  ], "Backtest preflight");
  const policies = closedRecord(model.policy_refs, ["cost_policy_id", "execution_timing_profile_id", "risk_policy_set_version_id", "rule_profile_id"], "Backtest preflight policies");
  const resource = closedRecord(model.resource_estimate, ["checkpoint_resume", "cpu_slots", "memory_limit_bytes", "resource_class", "scratch_limit_bytes"], "Backtest preflight resource estimate");
  if (
    model.schema_version !== "v3.product-backtest-preflight/1.0.0" || model.maturity !== "PRODUCT_CONNECTED"
    || model.truth !== "NOT_FORMAL" || model.admission !== "PRE_ALPHA" || model.status !== "PASS" || model.side_effects !== "NONE"
    || typeof model.project_id !== "string" || !PROJECT_ID_PATTERN.test(model.project_id)
    || typeof model.project_context_revision_id !== "string" || !PROJECT_CONTEXT_REVISION_PATTERN.test(model.project_context_revision_id)
    || typeof model.research_strategy_spec_id !== "string" || !/^rssv_sha256_[0-9a-f]{64}$/.test(model.research_strategy_spec_id)
    || typeof model.research_backtest_request_id !== "string" || !CANONICAL_ID_PATTERN.test(model.research_backtest_request_id)
    || typeof model.snapshot_id !== "string" || !CANONICAL_ID_PATTERN.test(model.snapshot_id)
    || typeof model.universe_version_id !== "string" || !CANONICAL_ID_PATTERN.test(model.universe_version_id)
    || typeof model.session_start !== "string" || typeof model.session_end !== "string" || model.session_end < model.session_start
    || (model.assumption_mode !== "RESEARCH_APPROXIMATE" && model.assumption_mode !== "STRICT_FAIL_CLOSED")
    || typeof policies.rule_profile_id !== "string" || !/^atrp_sha256_[0-9a-f]{64}$/.test(policies.rule_profile_id)
    || typeof policies.cost_policy_id !== "string" || !/^cost_sha256_[0-9a-f]{64}$/.test(policies.cost_policy_id)
    || typeof policies.execution_timing_profile_id !== "string" || !/^timing_sha256_[0-9a-f]{64}$/.test(policies.execution_timing_profile_id)
    || typeof policies.risk_policy_set_version_id !== "string" || !CANONICAL_ID_PATTERN.test(policies.risk_policy_set_version_id)
    || resource.resource_class !== "PRODUCT_BACKTEST_CPU" || resource.cpu_slots !== 1
    || resource.memory_limit_bytes !== 1_073_741_824 || resource.scratch_limit_bytes !== 1_073_741_824
    || resource.checkpoint_resume !== "UNAVAILABLE"
  ) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Backtest preflight binding drifted");
  return Object.freeze({
    schemaVersion: "v3.product-backtest-preflight/1.0.0", maturity: "PRODUCT_CONNECTED", truth: "NOT_FORMAL", admission: "PRE_ALPHA", status: "PASS",
    projectId: model.project_id, projectContextRevisionId: model.project_context_revision_id,
    researchStrategySpecId: model.research_strategy_spec_id, researchBacktestRequestId: model.research_backtest_request_id,
    snapshotId: model.snapshot_id, universeVersionId: model.universe_version_id,
    sessionStart: model.session_start, sessionEnd: model.session_end,
    slippageBps: decimalText(model.slippage_bps, "preflight.slippage_bps"),
    dailyVolumeParticipationRate: decimalText(model.daily_volume_participation_rate, "preflight.daily_volume_participation_rate"),
    commissionRate: decimalText(model.commission_rate, "preflight.commission_rate"),
    minimumCommissionCny: decimalText(model.minimum_commission_cny, "preflight.minimum_commission_cny"),
    stampDutySellRate: decimalText(model.stamp_duty_sell_rate, "preflight.stamp_duty_sell_rate"),
    assumptionMode: model.assumption_mode,
    policyRefs: Object.freeze({ ruleProfileId: policies.rule_profile_id, costPolicyId: policies.cost_policy_id, executionTimingProfileId: policies.execution_timing_profile_id, riskPolicySetVersionId: policies.risk_policy_set_version_id }),
    resourceEstimate: Object.freeze({ resourceClass: "PRODUCT_BACKTEST_CPU", cpuSlots: 1, memoryLimitBytes: 1_073_741_824, scratchLimitBytes: 1_073_741_824, checkpointResume: "UNAVAILABLE" }),
    sideEffects: "NONE"
  });
}

function finiteNullable(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", `${label} must be finite or null`);
  }
  return value;
}

function adaptFactorMetric(value: unknown, label: string) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", `${label} is not a metric object`);
  }
  const metric = value as Record<string, unknown>;
  const status = String(metric.status);
  if (Object.keys(metric).sort().join(",") !== "reason,status,value"
    || !["AVAILABLE", "INSUFFICIENT_SAMPLE", "NOT_AVAILABLE"].includes(status)
    || (metric.reason !== null && (typeof metric.reason !== "string" || metric.reason.length === 0))
    || (status === "AVAILABLE" && (metric.reason !== null || typeof metric.value !== "number" || !Number.isFinite(metric.value)))
    || (status !== "AVAILABLE" && (metric.value !== null || typeof metric.reason !== "string"))) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", `${label} metric shape is invalid`);
  }
  return Object.freeze({
    status: metric.status as "AVAILABLE" | "INSUFFICIENT_SAMPLE" | "NOT_AVAILABLE",
    value: finiteNullable(metric.value, `${label}.value`),
    reason: metric.reason as string | null
  });
}

function adaptProjectFactor(value: unknown, projectId: string, contextId: string): ProductFactorSummaryView {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "available Factor summary is absent");
  }
  const factor = value as Record<string, unknown>;
  const keys = [
    "admission", "analysis", "analysis_artifact_id", "analysis_output_name",
    "formula_document_artifact_id", "formula_document_version_id", "outputs",
    "project_context_revision_id", "project_id", "schema_version", "snapshot_id",
    "source_manifest_artifact_id", "source_manifest_sha256", "truth",
    "universe_version_id", "visual_preview", "visual_preview_projection",
    "visual_preview_total_rows"
  ];
  if (Object.keys(factor).sort().join(",") !== keys.sort().join(",")
    || factor.schema_version !== "v3.project-factor-summary/1.1.0"
    || factor.truth !== "NOT_FORMAL" || factor.admission !== "PRE_ALPHA"
    || factor.project_id !== projectId || factor.project_context_revision_id !== contextId
    || typeof factor.snapshot_id !== "string" || !CANONICAL_ID_PATTERN.test(factor.snapshot_id)
    || typeof factor.universe_version_id !== "string" || !CANONICAL_ID_PATTERN.test(factor.universe_version_id)
    || typeof factor.source_manifest_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(factor.source_manifest_artifact_id)
    || typeof factor.source_manifest_sha256 !== "string" || !CONTENT_SHA_PATTERN.test(factor.source_manifest_sha256)
    || typeof factor.formula_document_version_id !== "string" || !/^fdoc_sha256_[0-9a-f]{64}$/.test(factor.formula_document_version_id)
    || typeof factor.formula_document_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(factor.formula_document_artifact_id)
    || typeof factor.analysis_output_name !== "string" || !/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(factor.analysis_output_name)
    || typeof factor.analysis_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(factor.analysis_artifact_id)
    || !Array.isArray(factor.outputs) || factor.outputs.length < 1 || factor.outputs.length > 64
    || !Number.isSafeInteger(factor.visual_preview_total_rows) || Number(factor.visual_preview_total_rows) < 0
    || Number(factor.visual_preview_total_rows) > 2_000_000
    || factor.visual_preview_projection !== "TAIL_ASCENDING_MAX_256"
    || !Array.isArray(factor.visual_preview) || factor.visual_preview.length > 256
    || factor.visual_preview.length !== Math.min(Number(factor.visual_preview_total_rows), 256)
    || factor.analysis === null || typeof factor.analysis !== "object" || Array.isArray(factor.analysis)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor summary identity or bounds are invalid");
  }
  const outputs = factor.outputs.map((raw) => {
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor output is invalid");
    const item = raw as Record<string, unknown>;
    if (Object.keys(item).sort().join(",") !== "factor_definition_artifact_id,factor_definition_version_id,materialization_artifact_id,materialization_id,name,output_type,row_count"
      || typeof item.name !== "string" || !/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(item.name)
      || typeof item.factor_definition_version_id !== "string" || !/^fdv_sha256_[0-9a-f]{64}$/.test(item.factor_definition_version_id)
      || typeof item.factor_definition_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(item.factor_definition_artifact_id)
      || typeof item.materialization_id !== "string" || !/^fmt_sha256_[0-9a-f]{64}$/.test(item.materialization_id)
      || typeof item.materialization_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(item.materialization_artifact_id)
      || !["FLOAT_SERIES", "BOOLEAN_SERIES"].includes(String(item.output_type))
      || !Number.isSafeInteger(item.row_count) || Number(item.row_count) < 1 || Number(item.row_count) > 2_000_000) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor output identity is invalid");
    }
    return Object.freeze({
      name: item.name,
      factorDefinitionVersionId: item.factor_definition_version_id,
      factorDefinitionArtifactId: item.factor_definition_artifact_id,
      materializationId: item.materialization_id,
      materializationArtifactId: item.materialization_artifact_id,
      outputType: item.output_type as "FLOAT_SERIES" | "BOOLEAN_SERIES",
      rowCount: Number(item.row_count)
    });
  });
  const outputNames = new Set(outputs.map((item) => item.name));
  if (outputNames.size !== outputs.length) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor output names are duplicated");
  }
  const preview = factor.visual_preview.map((raw) => {
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor preview row is invalid");
    const row = raw as Record<string, unknown>;
    if (Object.keys(row).sort().join(",") !== "amount_cny,close,high,instrument_id,low,open,series,session_date,volume_shares"
      || typeof row.session_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(row.session_date)
      || typeof row.instrument_id !== "string" || !CANONICAL_ID_PATTERN.test(row.instrument_id)
      || !Array.isArray(row.series)) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor preview shape is invalid");
    const series: Record<string, number | boolean | null> = {};
    for (const rawSeries of row.series) {
      if (rawSeries === null || typeof rawSeries !== "object" || Array.isArray(rawSeries)) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor series item is invalid");
      const item = rawSeries as Record<string, unknown>;
      if (Object.keys(item).sort().join(",") !== "name,value" || typeof item.name !== "string" || !outputNames.has(item.name)
        || (item.value !== null && typeof item.value !== "boolean" && (typeof item.value !== "number" || !Number.isFinite(item.value)))) {
        throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor series value is invalid");
      }
      if (item.name in series) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor series name is duplicated");
      series[item.name] = item.value as number | boolean | null;
    }
    if (Object.keys(series).length !== outputNames.size) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor preview output coverage is incomplete");
    return Object.freeze({
      sessionDate: row.session_date,
      instrumentId: row.instrument_id,
      open: finiteNullable(row.open, "Factor open"),
      high: finiteNullable(row.high, "Factor high"),
      low: finiteNullable(row.low, "Factor low"),
      close: finiteNullable(row.close, "Factor close"),
      volumeShares: finiteNullable(row.volume_shares, "Factor volume"),
      amountCny: finiteNullable(row.amount_cny, "Factor amount"),
      series: Object.freeze(series)
    });
  });
  const analysis = factor.analysis as Record<string, unknown>;
  if (Object.keys(analysis).sort().join(",") !== "aggregate,daily_result_count,daily_results,daily_results_projection,factor_analysis_result_id,spec"
    || typeof analysis.factor_analysis_result_id !== "string" || !/^far_sha256_[0-9a-f]{64}$/.test(analysis.factor_analysis_result_id)
    || analysis.spec === null || typeof analysis.spec !== "object" || Array.isArray(analysis.spec)
    || analysis.aggregate === null || typeof analysis.aggregate !== "object" || Array.isArray(analysis.aggregate)
    || !Number.isSafeInteger(analysis.daily_result_count) || Number(analysis.daily_result_count) < 0
    || Number(analysis.daily_result_count) > 2_000_000
    || analysis.daily_results_projection !== "TAIL_ASCENDING_MAX_256"
    || !Array.isArray(analysis.daily_results) || analysis.daily_results.length > 256
    || analysis.daily_results.length !== Math.min(Number(analysis.daily_result_count), 256)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor analysis shape is invalid");
  }
  const spec = analysis.spec as Record<string, unknown>;
  const specKeys = [
    "schema_version", "forward_return_horizon_sessions", "quantiles",
    "minimum_instruments_per_date", "minimum_valid_ic_dates", "formation_price",
    "label_price", "signal_availability"
  ];
  if (Object.keys(spec).sort().join(",") !== specKeys.sort().join(",")
    || spec.schema_version !== "v3.factor-analysis-spec/1.0.0"
    || spec.forward_return_horizon_sessions !== 5 || spec.quantiles !== 5 || spec.minimum_instruments_per_date !== 20
    || spec.minimum_valid_ic_dates !== 20 || spec.formation_price !== "RAW_CLOSE" || spec.label_price !== "RAW_CLOSE"
    || spec.signal_availability !== "AFTER_SESSION_CLOSE") throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor analysis spec drifted");
  const aggregate = analysis.aggregate as Record<string, unknown>;
  const aggregateKeys = ["ic_mean", "ic_std", "icir", "rank_ic_mean", "rank_ic_std", "rank_icir", "valid_dates", "yearly_distribution"];
  if (Object.keys(aggregate).sort().join(",") !== aggregateKeys.sort().join(",")
    || !Number.isSafeInteger(aggregate.valid_dates) || Number(aggregate.valid_dates) < 0
    || !Array.isArray(aggregate.yearly_distribution)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor aggregate shape is invalid");
  }
  const yearlyDistribution = aggregate.yearly_distribution.map((raw) => {
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor yearly analysis is invalid");
    }
    const item = raw as Record<string, unknown>;
    if (Object.keys(item).sort().join(",") !== "ic_mean,ic_std,icir,valid_dates,year"
      || !Number.isSafeInteger(item.year) || Number(item.year) < 1900 || Number(item.year) > 2200
      || !Number.isSafeInteger(item.valid_dates) || Number(item.valid_dates) < 0) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor yearly analysis fields are invalid");
    }
    return Object.freeze({
      year: Number(item.year),
      validDates: Number(item.valid_dates),
      icMean: adaptFactorMetric(item.ic_mean, "yearly.ic_mean"),
      icStd: adaptFactorMetric(item.ic_std, "yearly.ic_std"),
      icir: adaptFactorMetric(item.icir, "yearly.icir")
    });
  });
  const dailyResults = analysis.daily_results.map((raw) => {
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor daily analysis is invalid");
    const item = raw as Record<string, unknown>;
    const dailyKeys = [
      "session_date", "label_session_date", "status", "reason", "universe_size",
      "sample_size", "coverage", "missing_rate", "ic", "rank_ic",
      "quantile_returns", "long_short_spread", "turnover", "diagnostics",
      "excluded_reason_counts"
    ];
    if (Object.keys(item).sort().join(",") !== dailyKeys.sort().join(",")
      || typeof item.session_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(item.session_date)
      || typeof item.label_session_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(item.label_session_date)
      || !["AVAILABLE", "INSUFFICIENT_SAMPLE", "NOT_AVAILABLE"].includes(String(item.status))
      || (item.reason !== null && (typeof item.reason !== "string" || item.reason.length === 0))
      || !Number.isSafeInteger(item.universe_size) || Number(item.universe_size) < 0
      || !Number.isSafeInteger(item.sample_size) || Number(item.sample_size) < 0 || Number(item.sample_size) > Number(item.universe_size)
      || typeof item.coverage !== "number" || !Number.isFinite(item.coverage) || item.coverage < 0 || item.coverage > 1
      || typeof item.missing_rate !== "number" || !Number.isFinite(item.missing_rate) || item.missing_rate < 0 || item.missing_rate > 1
      || (item.quantile_returns !== null && (!Array.isArray(item.quantile_returns) || item.quantile_returns.length !== 5))
      || !Array.isArray(item.diagnostics) || item.diagnostics.some((entry) => typeof entry !== "string")
      || !Array.isArray(item.excluded_reason_counts)) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor daily analysis fields are invalid");
    }
    const excludedReasonCounts = item.excluded_reason_counts.map((entry) => {
      if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== "string" || entry[0].length === 0
        || !Number.isSafeInteger(entry[1]) || Number(entry[1]) < 0) {
        throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Factor exclusion reason is invalid");
      }
      return Object.freeze({ reason: entry[0], count: Number(entry[1]) });
    });
    return Object.freeze({
      sessionDate: item.session_date,
      labelSessionDate: item.label_session_date,
      status: item.status as "AVAILABLE" | "INSUFFICIENT_SAMPLE" | "NOT_AVAILABLE",
      reason: item.reason as string | null,
      universeSize: Number(item.universe_size), sampleSize: Number(item.sample_size),
      coverage: item.coverage, missingRate: item.missing_rate,
      ic: adaptFactorMetric(item.ic, "daily.ic"), rankIc: adaptFactorMetric(item.rank_ic, "daily.rank_ic"),
      quantileReturns: item.quantile_returns === null ? null : item.quantile_returns.map((entry) => {
        const value = finiteNullable(entry, "quantile return");
        if (value === null) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "quantile return cannot be null");
        return value;
      }),
      longShortSpread: finiteNullable(item.long_short_spread, "long-short spread"),
      turnover: adaptFactorMetric(item.turnover, "daily.turnover"),
      diagnostics: Object.freeze(item.diagnostics),
      excludedReasonCounts: Object.freeze(excludedReasonCounts)
    });
  });
  return Object.freeze({
    schemaVersion: "v3.project-factor-summary/1.1.0",
    truth: "NOT_FORMAL", admission: "PRE_ALPHA", projectId, projectContextRevisionId: contextId,
    snapshotId: factor.snapshot_id, universeVersionId: factor.universe_version_id,
    sourceManifestArtifactId: factor.source_manifest_artifact_id, sourceManifestSha256: factor.source_manifest_sha256,
    formulaDocumentVersionId: factor.formula_document_version_id, formulaDocumentArtifactId: factor.formula_document_artifact_id,
    analysisOutputName: factor.analysis_output_name, analysisArtifactId: factor.analysis_artifact_id,
    outputs: Object.freeze(outputs),
    visualPreviewTotalRows: Number(factor.visual_preview_total_rows),
    visualPreviewProjection: "TAIL_ASCENDING_MAX_256",
    visualPreview: Object.freeze(preview),
    analysis: Object.freeze({
      factorAnalysisResultId: analysis.factor_analysis_result_id,
      spec: Object.freeze({
        forwardReturnHorizonSessions: 5, quantiles: 5, minimumInstrumentsPerDate: 20,
        minimumValidIcDates: 20, formationPrice: "RAW_CLOSE", labelPrice: "RAW_CLOSE", signalAvailability: "AFTER_SESSION_CLOSE"
      }),
      aggregate: Object.freeze({
        validDates: Number(aggregate.valid_dates), icMean: adaptFactorMetric(aggregate.ic_mean, "aggregate.ic_mean"),
        icStd: adaptFactorMetric(aggregate.ic_std, "aggregate.ic_std"), icir: adaptFactorMetric(aggregate.icir, "aggregate.icir"),
        rankIcMean: adaptFactorMetric(aggregate.rank_ic_mean, "aggregate.rank_ic_mean"),
        rankIcStd: adaptFactorMetric(aggregate.rank_ic_std, "aggregate.rank_ic_std"),
        rankIcir: adaptFactorMetric(aggregate.rank_icir, "aggregate.rank_icir"),
        yearlyDistribution: Object.freeze(yearlyDistribution)
      }),
      dailyResultCount: Number(analysis.daily_result_count),
      dailyResultsProjection: "TAIL_ASCENDING_MAX_256",
      dailyResults: Object.freeze(dailyResults)
    })
  });
}

function adaptStrategyProfileRefs(value: unknown, label: string): ProductStrategyProfileRefsView {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", `${label} profile refs are invalid`);
  }
  const refs = value as Record<string, unknown>;
  if (
    Object.keys(refs).sort().join(",") !== "assumption_profile_id,cost_policy_version_id,execution_policy_version_id,risk_policy_set_version_id"
    || typeof refs.cost_policy_version_id !== "string" || !/^cost_sha256_[0-9a-f]{64}$/.test(refs.cost_policy_version_id)
    || typeof refs.execution_policy_version_id !== "string" || !/^timing_sha256_[0-9a-f]{64}$/.test(refs.execution_policy_version_id)
    || typeof refs.risk_policy_set_version_id !== "string" || !/^rpsv_sha256_[0-9a-f]{64}$/.test(refs.risk_policy_set_version_id)
    || typeof refs.assumption_profile_id !== "string" || !/^assumption_sha256_[0-9a-f]{64}$/.test(refs.assumption_profile_id)
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", `${label} profile refs drifted`);
  }
  return Object.freeze({
    costPolicyVersionId: refs.cost_policy_version_id,
    executionPolicyVersionId: refs.execution_policy_version_id,
    riskPolicySetVersionId: refs.risk_policy_set_version_id,
    assumptionProfileId: refs.assumption_profile_id
  });
}

function adaptStrategyAuthoringProfile(value: unknown): ProductStrategyAuthoringProfileView {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy authoring profile is absent");
  }
  const profile = value as Record<string, unknown>;
  const keys = [
    "admission", "assumption_profiles", "gross_exposure_max", "gross_exposure_min", "max_positions_max",
    "max_positions_min", "position_sizing_options", "profile_refs", "rebalance",
    "schema_version", "truth"
  ];
  if (
    Object.keys(profile).sort().join(",") !== keys.sort().join(",")
    || profile.schema_version !== "v3.product-strategy-authoring-profile/1.0.0"
    || profile.truth !== "NOT_FORMAL" || profile.admission !== "PRE_ALPHA"
    || !Array.isArray(profile.position_sizing_options)
    || profile.position_sizing_options.length !== 2
    || profile.position_sizing_options[0] !== "SINGLE_ASSET_FULL_WEIGHT"
    || profile.position_sizing_options[1] !== "EQUAL_WEIGHT_ACTIVE_SIGNALS"
    || profile.max_positions_min !== 1 || profile.max_positions_max !== 20
    || profile.gross_exposure_min !== "0" || profile.gross_exposure_max !== "1"
    || profile.rebalance !== "NEXT_OPEN_AFTER_SIGNAL"
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy authoring profile drifted");
  }
  if (!Array.isArray(profile.assumption_profiles) || profile.assumption_profiles.length !== 2) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy assumption profiles are absent");
  }
  const assumptionProfiles = profile.assumption_profiles.map((value, index) => {
    const item = closedRecord(
      value,
      ["assumption_profile_id", "mode"],
      `strategy_assumption_profiles[${index}]`
    );
    if ((item.mode !== "RESEARCH_APPROXIMATE" && item.mode !== "STRICT_FAIL_CLOSED")
      || typeof item.assumption_profile_id !== "string"
      || !/^assumption_sha256_[0-9a-f]{64}$/.test(item.assumption_profile_id)) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy assumption profile drifted");
    }
    return Object.freeze({
      mode: item.mode,
      assumptionProfileId: item.assumption_profile_id
    });
  });
  if (new Set(assumptionProfiles.map((item) => item.mode)).size !== 2
    || new Set(assumptionProfiles.map((item) => item.assumptionProfileId)).size !== 2) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy assumption profiles are not unique");
  }
  const refs = adaptStrategyProfileRefs(profile.profile_refs, "authoring");
  if (!assumptionProfiles.some((item) => item.mode === "RESEARCH_APPROXIMATE"
    && item.assumptionProfileId === refs.assumptionProfileId)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Default assumption profile is not RESEARCH_APPROXIMATE");
  }
  return Object.freeze({
    schemaVersion: "v3.product-strategy-authoring-profile/1.0.0",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    positionSizingOptions: Object.freeze([
      "SINGLE_ASSET_FULL_WEIGHT" as const,
      "EQUAL_WEIGHT_ACTIVE_SIGNALS" as const
    ]),
    maxPositionsMin: 1,
    maxPositionsMax: 20,
    grossExposureMin: "0",
    grossExposureMax: "1",
    rebalance: "NEXT_OPEN_AFTER_SIGNAL",
    profileRefs: refs,
    assumptionProfiles: Object.freeze(assumptionProfiles)
  });
}

function adaptProjectStrategy(
  value: unknown,
  projectId: string,
  contextId: string,
  profile: ProductStrategyAuthoringProfileView
): ProductStrategySummaryView {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "available Strategy summary is absent");
  }
  const strategy = value as Record<string, unknown>;
  const keys = [
    "admission", "decision_chain_count", "entry_signal_factor_version_id",
    "exit_signal_factor_version_id", "profile_refs", "project_context_revision_id",
    "project_id", "research_strategy_spec_id", "schema_version", "snapshot_id",
    "strategy_version_id", "transition_count", "truth", "universe_version_id"
  ];
  const refs = adaptStrategyProfileRefs(strategy.profile_refs, "Strategy");
  if (
    Object.keys(strategy).sort().join(",") !== keys.sort().join(",")
    || strategy.schema_version !== "v3.project-strategy-summary/1.0.0"
    || strategy.truth !== "NOT_FORMAL" || strategy.admission !== "PRE_ALPHA"
    || strategy.project_id !== projectId || strategy.project_context_revision_id !== contextId
    || typeof strategy.snapshot_id !== "string" || !CANONICAL_ID_PATTERN.test(strategy.snapshot_id)
    || typeof strategy.universe_version_id !== "string" || !/^unv_sha256_[0-9a-f]{64}$/.test(strategy.universe_version_id)
    || typeof strategy.research_strategy_spec_id !== "string" || !/^rssv_sha256_[0-9a-f]{64}$/.test(strategy.research_strategy_spec_id)
    || typeof strategy.strategy_version_id !== "string" || !CANONICAL_ID_PATTERN.test(strategy.strategy_version_id)
    || typeof strategy.entry_signal_factor_version_id !== "string" || !/^fdv_sha256_[0-9a-f]{64}$/.test(strategy.entry_signal_factor_version_id)
    || typeof strategy.exit_signal_factor_version_id !== "string" || !/^fdv_sha256_[0-9a-f]{64}$/.test(strategy.exit_signal_factor_version_id)
    || !Number.isSafeInteger(strategy.transition_count) || Number(strategy.transition_count) < 0 || Number(strategy.transition_count) > 3_000
    || !Number.isSafeInteger(strategy.decision_chain_count) || Number(strategy.decision_chain_count) < 0 || Number(strategy.decision_chain_count) > 3_000
    || refs.costPolicyVersionId !== profile.profileRefs.costPolicyVersionId
    || refs.executionPolicyVersionId !== profile.profileRefs.executionPolicyVersionId
    || refs.riskPolicySetVersionId !== profile.profileRefs.riskPolicySetVersionId
    || !profile.assumptionProfiles.some(
      (item) => item.assumptionProfileId === refs.assumptionProfileId
    )
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy summary identity or authority drifted");
  }
  return Object.freeze({
    schemaVersion: "v3.project-strategy-summary/1.0.0",
    truth: "NOT_FORMAL", admission: "PRE_ALPHA", projectId, projectContextRevisionId: contextId,
    snapshotId: strategy.snapshot_id, universeVersionId: strategy.universe_version_id,
    researchStrategySpecId: strategy.research_strategy_spec_id,
    strategyVersionId: strategy.strategy_version_id,
    entrySignalFactorVersionId: strategy.entry_signal_factor_version_id,
    exitSignalFactorVersionId: strategy.exit_signal_factor_version_id,
    profileRefs: refs,
    transitionCount: Number(strategy.transition_count),
    decisionChainCount: Number(strategy.decision_chain_count)
  });
}

function adaptProjectBacktest(
  value: unknown,
  projectId: string,
  contextId: string,
  strategy: ProductStrategySummaryView,
  profile: ProductStrategyAuthoringProfileView
): ProductBacktestSummaryView {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "available Backtest summary is absent");
  }
  const item = value as Record<string, unknown>;
  const keys = [
    "admission", "analytics_artifact_id", "analytics_id", "assumption_mode", "backtest_result_id",
    "diagnostic_count", "engine_version", "fill_count", "first_effective_session_date",
    "fills_export_artifact_id", "first_fill_session_date", "lineage_artifact_id", "maturity", "order_count",
    "orders_export_artifact_id",
    "project_context_revision_id", "project_id", "research_backtest_request_id",
    "research_strategy_spec_id", "result_artifact_id", "result_id", "result_lineage_id",
    "result_state", "run_id", "run_spec_id", "schema_version", "snapshot_id",
    "summary_export_artifact_id", "truth", "universe_version_id"
  ];
  const dateOrNull = (candidate: unknown): boolean => candidate === null
    || (typeof candidate === "string" && /^\d{4}-\d{2}-\d{2}$/.test(candidate));
  if (
    Object.keys(item).sort().join(",") !== keys.sort().join(",")
    || item.schema_version !== "v3.project-backtest-summary/1.0.0"
    || item.maturity !== "PRODUCT_CONNECTED" || item.truth !== "NOT_FORMAL" || item.admission !== "PRE_ALPHA"
    || item.project_id !== projectId || item.project_context_revision_id !== contextId
    || item.research_strategy_spec_id !== strategy.researchStrategySpecId
    || item.snapshot_id !== strategy.snapshotId || item.universe_version_id !== strategy.universeVersionId
    || typeof item.research_backtest_request_id !== "string" || !CANONICAL_ID_PATTERN.test(item.research_backtest_request_id)
    || typeof item.run_id !== "string" || !RUN_ID_PATTERN.test(item.run_id)
    || typeof item.run_spec_id !== "string" || !RUN_SPEC_ID_PATTERN.test(item.run_spec_id)
    || typeof item.result_id !== "string" || !CANONICAL_ID_PATTERN.test(item.result_id)
    || typeof item.backtest_result_id !== "string" || !CANONICAL_ID_PATTERN.test(item.backtest_result_id)
    || typeof item.result_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(item.result_artifact_id)
    || typeof item.analytics_id !== "string" || !CANONICAL_ID_PATTERN.test(item.analytics_id)
    || typeof item.analytics_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(item.analytics_artifact_id)
    || typeof item.summary_export_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(item.summary_export_artifact_id)
    || typeof item.orders_export_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(item.orders_export_artifact_id)
    || typeof item.fills_export_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(item.fills_export_artifact_id)
    || typeof item.result_lineage_id !== "string" || !CANONICAL_ID_PATTERN.test(item.result_lineage_id)
    || typeof item.lineage_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(item.lineage_artifact_id)
    || item.result_state !== "VALID"
    || (item.assumption_mode !== "RESEARCH_APPROXIMATE" && item.assumption_mode !== "STRICT_FAIL_CLOSED")
    || !profile.assumptionProfiles.some((candidate) =>
      candidate.mode === item.assumption_mode
      && candidate.assumptionProfileId === strategy.profileRefs.assumptionProfileId
    )
    || typeof item.engine_version !== "string" || item.engine_version.length < 1 || item.engine_version.length > 200
    || !Number.isSafeInteger(item.order_count) || Number(item.order_count) < 0 || Number(item.order_count) > 2_000_000
    || !Number.isSafeInteger(item.fill_count) || Number(item.fill_count) < 0 || Number(item.fill_count) > 2_000_000
    || !Number.isSafeInteger(item.diagnostic_count) || Number(item.diagnostic_count) < 0 || Number(item.diagnostic_count) > 2_000_000
    || !dateOrNull(item.first_fill_session_date) || !dateOrNull(item.first_effective_session_date)
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Backtest summary identity or truth drifted");
  }
  return Object.freeze({
    schemaVersion: "v3.project-backtest-summary/1.0.0",
    maturity: "PRODUCT_CONNECTED", truth: "NOT_FORMAL", admission: "PRE_ALPHA",
    projectId, projectContextRevisionId: contextId,
    researchBacktestRequestId: item.research_backtest_request_id,
    researchStrategySpecId: item.research_strategy_spec_id,
    snapshotId: item.snapshot_id, universeVersionId: item.universe_version_id,
    runId: item.run_id, runSpecId: item.run_spec_id, resultId: item.result_id,
    backtestResultId: item.backtest_result_id, resultArtifactId: item.result_artifact_id,
    analyticsId: item.analytics_id, analyticsArtifactId: item.analytics_artifact_id,
    summaryExportArtifactId: item.summary_export_artifact_id,
    ordersExportArtifactId: item.orders_export_artifact_id,
    fillsExportArtifactId: item.fills_export_artifact_id,
    resultLineageId: item.result_lineage_id, lineageArtifactId: item.lineage_artifact_id,
    resultState: "VALID", engineVersion: item.engine_version,
    orderCount: Number(item.order_count), fillCount: Number(item.fill_count), diagnosticCount: Number(item.diagnostic_count),
    firstFillSessionDate: item.first_fill_session_date as string | null,
    firstEffectiveSessionDate: item.first_effective_session_date as string | null,
    assumptionMode: item.assumption_mode
  });
}

const RESULT_TABLE_PREVIEW_LIMIT = 200;
const PRODUCT_RESULT_ANALYTICS_ENGINE_VERSION = "v3.result_analytics_engine/1.1.0";
const EXACT_DECIMAL_PATTERN = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const CONTENT_SHA256_PATTERN = /^[0-9a-f]{64}$/;

function closedRecord(value: unknown, keys: readonly string[], label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} is not an object`);
  }
  const record = value as Record<string, unknown>;
  if (Object.keys(record).sort().join(",") !== [...keys].sort().join(",")) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} fields do not match the closed shape`);
  }
  return record;
}

function closedRecordOneOf(value: unknown, shapes: readonly (readonly string[])[], label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} is not an object`);
  }
  const record = value as Record<string, unknown>;
  const actual = Object.keys(record).sort().join(",");
  if (!shapes.some((shape) => [...shape].sort().join(",") === actual)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} fields do not match an admitted closed shape`);
  }
  return record;
}

function decimalText(value: unknown, label: string): string {
  if (typeof value !== "string" || !EXACT_DECIMAL_PATTERN.test(value)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} is not exact decimal text`);
  }
  return value;
}

function resultMetric(value: unknown, label: string) {
  const metric = closedRecord(value, ["status", "value", "reason"], label);
  if (!['AVAILABLE', 'INSUFFICIENT_SAMPLE', 'NOT_AVAILABLE'].includes(String(metric.status))) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} status is invalid`);
  }
  if (metric.status === "AVAILABLE") {
    if (metric.reason !== null) throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} available metric carries a reason`);
    return Object.freeze({ status: "AVAILABLE" as const, value: decimalText(metric.value, `${label}.value`), reason: null });
  }
  if (metric.value !== null || typeof metric.reason !== "string" || metric.reason.length < 1 || metric.reason.length > 500) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} unavailable metric is invalid`);
  }
  return Object.freeze({
    status: metric.status as "INSUFFICIENT_SAMPLE" | "NOT_AVAILABLE",
    value: null,
    reason: metric.reason
  });
}

function assertPreAlphaTruth(value: unknown, label: string): void {
  const truth = closedRecord(value, ["canonical_truth_state", "canonical_admission_state"], label);
  if (truth.canonical_truth_state !== "NOT_FORMAL" || truth.canonical_admission_state !== "PRE_ALPHA") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} exceeds the admitted truth ceiling`);
  }
}

function decodeArtifactJson(bytes: Uint8Array, label: string): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch (error) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} bytes are not strict UTF-8 JSON`, error);
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} root is not an object`);
  }
  return value as Record<string, unknown>;
}

function adaptLatestProductResultArtifacts(
  home: ProductProjectHomeView,
  resultBytes: ArtifactStreamBytesView,
  analyticsBytes: ArtifactStreamBytesView,
  lineageBytes: ArtifactStreamBytesView
): ProductLatestResultDetailsView {
  const summary = home.backtest;
  if (home.backtestState !== "AVAILABLE" || summary === null || summary.resultState !== "VALID") {
    throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "latest VALID Backtest is unavailable");
  }
  if (resultBytes.artifactId !== summary.resultArtifactId
    || analyticsBytes.artifactId !== summary.analyticsArtifactId
    || lineageBytes.artifactId !== summary.lineageArtifactId) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "Result artifact readback does not match Project Home");
  }
  const result = closedRecord(decodeArtifactJson(resultBytes.bytes, "Result"), [
    "artifact_type", "cash_ledger", "content_sha256", "diagnostics", "fills", "holdings",
    "nav", "orders", "position_ledger", "result_id", "run_spec_id",
    "target_quantity_vectors", "truth_admission"
  ], "Result");
  if (
    result.artifact_type !== "BacktestRunResult"
    || result.result_id !== summary.backtestResultId
    || typeof result.content_sha256 !== "string" || !CONTENT_SHA256_PATTERN.test(result.content_sha256)
    || summary.backtestResultId !== `btrr_sha256_${result.content_sha256}`
    || result.run_spec_id !== summary.runSpecId
  ) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "Result identity does not match the VALID summary");
  }
  assertPreAlphaTruth(result.truth_admission, "Result truth");
  if (!Array.isArray(result.orders) || !Array.isArray(result.fills) || !Array.isArray(result.diagnostics)
    || !Array.isArray(result.holdings) || !Array.isArray(result.nav)
    || result.orders.length !== summary.orderCount || result.fills.length !== summary.fillCount
    || result.diagnostics.length !== summary.diagnosticCount) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "Result table counts drifted from Project Home");
  }
  const date = (value: unknown, label: string): string => {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} is not an ISO date`);
    }
    return value;
  };
  const nonNegativeInt = (value: unknown, label: string): number => {
    if (!Number.isSafeInteger(value) || Number(value) < 0) {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} is not a non-negative integer`);
    }
    return Number(value);
  };
  const side = (value: unknown, label: string): "BUY" | "SELL" => {
    if (value !== "BUY" && value !== "SELL") throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} side is invalid`);
    return value;
  };
  const orderRows = result.orders.map((raw, index) => {
    const row = closedRecord(raw, [
      "instrument_id", "order_id", "raw_limit_price", "requested_quantity", "session_date",
      "side", "source_target_quantity_vector_id"
    ], `orders[${index}]`);
    if (typeof row.order_id !== "string" || !CANONICAL_ID_PATTERN.test(row.order_id)
      || typeof row.instrument_id !== "string" || !CANONICAL_ID_PATTERN.test(row.instrument_id)
      || typeof row.source_target_quantity_vector_id !== "string" || !CANONICAL_ID_PATTERN.test(row.source_target_quantity_vector_id)) {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `orders[${index}] identities are invalid`);
    }
    return Object.freeze({
      orderId: row.order_id, sessionDate: date(row.session_date, `orders[${index}]`), instrumentId: row.instrument_id,
      side: side(row.side, `orders[${index}]`), requestedQuantity: nonNegativeInt(row.requested_quantity, `orders[${index}]`),
      rawLimitPrice: decimalText(row.raw_limit_price, `orders[${index}].raw_limit_price`)
    });
  });
  const fillRows = result.fills.map((raw, index) => {
    const baseFillKeys = [
      "consideration", "costs", "fill_id", "instrument_id", "order_id",
      "quantity", "raw_price", "session_date", "side"
    ] as const;
    const row = closedRecordOneOf(raw, [baseFillKeys, [
      ...baseFillKeys, "execution_price", "participation_cap", "slippage_bps"
    ]], `fills[${index}]`);
    const costs = closedRecord(row.costs, ["commission", "exchange_fee", "stamp_duty", "total", "transfer_fee"], `fills[${index}].costs`);
    if (typeof row.fill_id !== "string" || !CANONICAL_ID_PATTERN.test(row.fill_id)
      || typeof row.order_id !== "string" || !CANONICAL_ID_PATTERN.test(row.order_id)
      || typeof row.instrument_id !== "string" || !CANONICAL_ID_PATTERN.test(row.instrument_id)) {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `fills[${index}] identities are invalid`);
    }
    return Object.freeze({
      fillId: row.fill_id, orderId: row.order_id, sessionDate: date(row.session_date, `fills[${index}]`), instrumentId: row.instrument_id,
      side: side(row.side, `fills[${index}]`), quantity: nonNegativeInt(row.quantity, `fills[${index}]`),
      rawPrice: decimalText(row.raw_price, `fills[${index}].raw_price`),
      executionPrice: row.execution_price === undefined || row.execution_price === null ? null : decimalText(row.execution_price, `fills[${index}].execution_price`),
      consideration: decimalText(row.consideration, `fills[${index}].consideration`),
      commission: decimalText(costs.commission, `fills[${index}].costs.commission`),
      stampDuty: decimalText(costs.stamp_duty, `fills[${index}].costs.stamp_duty`),
      transferFee: decimalText(costs.transfer_fee, `fills[${index}].costs.transfer_fee`),
      exchangeFee: decimalText(costs.exchange_fee, `fills[${index}].costs.exchange_fee`),
      totalFees: decimalText(costs.total, `fills[${index}].costs.total`),
      participationCap: row.participation_cap === undefined || row.participation_cap === null ? null : nonNegativeInt(row.participation_cap, `fills[${index}].participation_cap`),
      slippageBps: row.slippage_bps === undefined || row.slippage_bps === null ? null : decimalText(row.slippage_bps, `fills[${index}].slippage_bps`)
    });
  });
  const diagnosticRows = result.diagnostics.map((raw, index) => {
    const baseDiagnosticKeys = ["code", "detail", "filled_quantity", "order_id", "requested_quantity"] as const;
    const row = closedRecordOneOf(raw, [baseDiagnosticKeys, [
      ...baseDiagnosticKeys, "eligible_quantity", "participation_cap", "unfilled_quantity"
    ]], `diagnostics[${index}]`);
    if (typeof row.order_id !== "string" || !CANONICAL_ID_PATTERN.test(row.order_id)
      || typeof row.code !== "string" || row.code.length < 1 || typeof row.detail !== "string") {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `diagnostics[${index}] identity is invalid`);
    }
    const optionalInt = (value: unknown, label: string) => value === null ? null : nonNegativeInt(value, label);
    return Object.freeze({
      orderId: row.order_id, code: row.code,
      requestedQuantity: nonNegativeInt(row.requested_quantity, `diagnostics[${index}]`),
      eligibleQuantity: optionalInt(row.eligible_quantity ?? null, `diagnostics[${index}].eligible_quantity`),
      filledQuantity: nonNegativeInt(row.filled_quantity, `diagnostics[${index}]`),
      unfilledQuantity: optionalInt(row.unfilled_quantity ?? null, `diagnostics[${index}].unfilled_quantity`),
      participationCap: optionalInt(row.participation_cap ?? null, `diagnostics[${index}].participation_cap`),
      detail: row.detail
    });
  });
  const holdingRows = result.holdings.map((raw, index) => {
    const row = closedRecord(raw, ["instrument_id", "market_value", "quantity", "raw_close", "sellable_quantity", "session_date"], `holdings[${index}]`);
    if (typeof row.instrument_id !== "string" || !CANONICAL_ID_PATTERN.test(row.instrument_id)) {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `holdings[${index}] instrument is invalid`);
    }
    return Object.freeze({
      sessionDate: date(row.session_date, `holdings[${index}]`), instrumentId: row.instrument_id,
      quantity: nonNegativeInt(row.quantity, `holdings[${index}]`), sellableQuantity: nonNegativeInt(row.sellable_quantity, `holdings[${index}]`),
      rawClose: decimalText(row.raw_close, `holdings[${index}].raw_close`), marketValue: decimalText(row.market_value, `holdings[${index}].market_value`)
    });
  });

  const analytics = closedRecord(decodeArtifactJson(analyticsBytes.bytes, "Analytics"), [
    "analytics_id", "artifact_type", "concentration", "content_sha256", "core_analytics",
    "engine_version", "exposure_series", "schema_version", "supplemental_metrics",
    "table_summary", "truth_admission"
  ], "Analytics");
  if (analytics.artifact_type !== "ProductBacktestResultAnalytics"
    || analytics.schema_version !== "v3.backtest_result_analytics/1.1.0"
    || analytics.analytics_id !== summary.analyticsId
    || typeof analytics.content_sha256 !== "string" || !CONTENT_SHA256_PATTERN.test(analytics.content_sha256)
    || summary.analyticsId !== `bra_sha256_${analytics.content_sha256}`
    || analytics.engine_version !== PRODUCT_RESULT_ANALYTICS_ENGINE_VERSION) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "Analytics identity does not match Project Home");
  }
  assertPreAlphaTruth(analytics.truth_admission, "Analytics truth");
  const core = closedRecord(analytics.core_analytics, [
    "analytics_id", "analytics_policy", "artifact_type", "benchmark", "benchmark_binding",
    "content_sha256", "costs", "drawdown_episode", "drawdown_series", "metrics",
    "monthly_returns", "return_series", "schema_version", "source_result", "truth_admission",
    "turnover", "yearly_returns"
  ], "core analytics");
  const sourceResult = closedRecord(core.source_result, ["content_sha256", "result_id"], "analytics source Result");
  if (core.artifact_type !== "BacktestResultAnalytics" || core.schema_version !== "v3.backtest_result_analytics/1.0.0"
    || typeof sourceResult.content_sha256 !== "string" || !CONTENT_SHA256_PATTERN.test(sourceResult.content_sha256)
    || sourceResult.result_id !== summary.backtestResultId || sourceResult.content_sha256 !== result.content_sha256) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "Analytics source Result binding drifted");
  }
  assertPreAlphaTruth(core.truth_admission, "core analytics truth");
  const metrics = closedRecord(core.metrics, [
    "annualized_return", "annualized_volatility", "end_nav", "max_drawdown",
    "sharpe", "sortino", "start_nav", "total_return"
  ], "analytics metrics");
  const supplemental = closedRecord(analytics.supplemental_metrics, ["calmar"], "supplemental metrics");
  if (!Array.isArray(core.return_series) || !Array.isArray(core.drawdown_series) || !Array.isArray(analytics.exposure_series)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "Result chart series are invalid");
  }
  const navSeries = core.return_series.map((raw, index) => {
    const row = closedRecord(raw, ["cumulative_return", "nav", "session_date", "session_return"], `return_series[${index}]`);
    return Object.freeze({
      sessionDate: date(row.session_date, `return_series[${index}]`), nav: decimalText(row.nav, `return_series[${index}].nav`),
      sessionReturn: resultMetric(row.session_return, `return_series[${index}].session_return`),
      cumulativeReturn: resultMetric(row.cumulative_return, `return_series[${index}].cumulative_return`)
    });
  });
  const resultNavSeries = result.nav.map((raw, index) => {
    const row = closedRecord(raw, ["cash", "holdings_value", "nav", "session_date"], `result.nav[${index}]`);
    return Object.freeze({
      sessionDate: date(row.session_date, `result.nav[${index}]`),
      nav: decimalText(row.nav, `result.nav[${index}].nav`)
    });
  });
  const drawdownSeries = core.drawdown_series.map((raw, index) => {
    const row = closedRecord(raw, ["drawdown", "session_date"], `drawdown_series[${index}]`);
    return Object.freeze({ sessionDate: date(row.session_date, `drawdown_series[${index}]`), drawdown: resultMetric(row.drawdown, `drawdown_series[${index}].drawdown`) });
  });
  const exposureSeries = analytics.exposure_series.map((raw, index) => {
    const row = closedRecord(raw, ["gross_exposure", "held_instrument_count", "net_exposure", "session_date"], `exposure_series[${index}]`);
    return Object.freeze({
      sessionDate: date(row.session_date, `exposure_series[${index}]`),
      grossExposure: resultMetric(row.gross_exposure, `exposure_series[${index}].gross_exposure`),
      netExposure: resultMetric(row.net_exposure, `exposure_series[${index}].net_exposure`),
      heldInstrumentCount: nonNegativeInt(row.held_instrument_count, `exposure_series[${index}]`)
    });
  });
  const periodReturnRows = (value: unknown, periodKind: "MONTHLY" | "YEARLY", label: string) => {
    if (!Array.isArray(value)) throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} is not an array`);
    return Object.freeze(value.map((raw, index) => {
      const row = closedRecord(raw, ["end_date", "period_kind", "period_label", "period_return", "start_date"], `${label}[${index}]`);
      if (row.period_kind !== periodKind || typeof row.period_label !== "string" || row.period_label.length < 1 || row.period_label.length > 20) {
        throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label}[${index}] period identity is invalid`);
      }
      const startDate = date(row.start_date, `${label}[${index}].start_date`);
      const endDate = date(row.end_date, `${label}[${index}].end_date`);
      if (startDate > endDate) throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label}[${index}] date range is reversed`);
      return Object.freeze({
        periodLabel: row.period_label,
        startDate,
        endDate,
        periodReturn: resultMetric(row.period_return, `${label}[${index}].period_return`)
      });
    }));
  };
  const monthlyReturns = periodReturnRows(core.monthly_returns, "MONTHLY", "monthly_returns");
  const yearlyReturns = periodReturnRows(core.yearly_returns, "YEARLY", "yearly_returns");
  const costs = closedRecord(core.costs, [
    "buy_traded_notional", "fee_breakdown", "fee_over_traded_notional", "fill_count",
    "gross_traded_notional", "observed_fee_load_over_start_nav", "sell_traded_notional", "total_fees"
  ], "analytics costs");
  closedRecord(costs.fee_breakdown, ["commission", "exchange_fee", "stamp_duty", "transfer_fee"], "analytics costs fee breakdown");
  const turnover = closedRecord(core.turnover, ["average_daily_nav", "convention", "gross_traded_notional", "turnover"], "analytics turnover");
  if (typeof turnover.convention !== "string" || turnover.convention.length < 1
    || costs.fill_count !== summary.fillCount || costs.gross_traded_notional !== turnover.gross_traded_notional) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "cost/turnover summary does not bind the current Result");
  }
  const concentration = closedRecord(analytics.concentration, [
    "average_held_instrument_count", "maximum_held_instrument_count", "peak_instrument_id",
    "peak_session_date", "peak_single_position_weight"
  ], "analytics concentration");
  const peakSessionDate = concentration.peak_session_date === null ? null : date(concentration.peak_session_date, "concentration.peak_session_date");
  const peakInstrumentId = concentration.peak_instrument_id;
  if ((peakSessionDate === null) !== (peakInstrumentId === null)
    || (peakInstrumentId !== null && (typeof peakInstrumentId !== "string" || !CANONICAL_ID_PATTERN.test(peakInstrumentId)))) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "concentration peak binding is invalid");
  }
  const benchmark = closedRecord(core.benchmark, [
    "aligned_benchmark_total_return", "alpha", "benchmark_content_sha256", "benchmark_name",
    "benchmark_series_id", "beta", "relative_returns", "status", "tracking_difference", "tracking_error"
  ], "analytics benchmark");
  if (benchmark.status !== "AVAILABLE" && benchmark.status !== "BENCHMARK_NOT_AVAILABLE") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "benchmark status is invalid");
  }
  if (benchmark.status === "BENCHMARK_NOT_AVAILABLE"
    && (benchmark.benchmark_series_id !== null || benchmark.benchmark_content_sha256 !== null || benchmark.benchmark_name !== null)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "unavailable benchmark carries an identity");
  }
  if (benchmark.status === "AVAILABLE"
    && (typeof benchmark.benchmark_series_id !== "string" || !CANONICAL_ID_PATTERN.test(benchmark.benchmark_series_id)
      || typeof benchmark.benchmark_content_sha256 !== "string" || !CONTENT_SHA256_PATTERN.test(benchmark.benchmark_content_sha256)
      || typeof benchmark.benchmark_name !== "string" || benchmark.benchmark_name.length < 1)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "available benchmark identity is invalid");
  }
  if (navSeries.length !== drawdownSeries.length || navSeries.length !== exposureSeries.length
    || navSeries.length !== resultNavSeries.length
    || navSeries.some((row, index) => row.sessionDate !== drawdownSeries[index]?.sessionDate
      || row.sessionDate !== exposureSeries[index]?.sessionDate
      || row.sessionDate !== resultNavSeries[index]?.sessionDate
      || row.nav !== resultNavSeries[index]?.nav)) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "NAV/drawdown/exposure dates are not exactly aligned");
  }
  const tableSummary = closedRecord(analytics.table_summary, ["diagnostic_count", "fill_count", "order_count"], "analytics table summary");
  if (tableSummary.order_count !== summary.orderCount || tableSummary.fill_count !== summary.fillCount || tableSummary.diagnostic_count !== summary.diagnosticCount) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "Analytics table counts drifted");
  }

  const lineage = closedRecord(decodeArtifactJson(lineageBytes.bytes, "Lineage"), [
    "admission", "artifact_type", "content_sha256", "data", "execution", "factors",
    "project_context_revision_id", "project_id", "result", "result_lineage_id",
    "schema_version", "strategy", "truth"
  ], "Lineage");
  if (lineage.artifact_type !== "ProductResultLineage" || lineage.schema_version !== "v3.product-result-lineage/1.0.0"
    || lineage.result_lineage_id !== summary.resultLineageId || typeof lineage.content_sha256 !== "string"
    || !CONTENT_SHA256_PATTERN.test(lineage.content_sha256)
    || summary.resultLineageId !== `rln_sha256_${lineage.content_sha256}`
    || lineage.project_id !== home.projectId || lineage.project_context_revision_id !== home.projectContextRevisionId
    || lineage.truth !== "NOT_FORMAL" || lineage.admission !== "PRE_ALPHA") {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "Result lineage identity or truth drifted");
  }
  const lineageData = closedRecord(lineage.data, [
    "raw_artifact_id", "raw_capture_id", "snapshot_id", "snapshot_manifest_artifact_id",
    "universe_membership_artifact_id", "universe_version_id"
  ], "Lineage.data");
  const lineageFactors = closedRecord(lineage.factors, ["entry", "exit"], "Lineage.factors");
  const entryFactor = closedRecord(lineageFactors.entry, [
    "factor_definition_version_id", "materialization_artifact_id", "materialization_id"
  ], "Lineage.factors.entry");
  const exitFactor = closedRecord(lineageFactors.exit, [
    "factor_definition_version_id", "materialization_artifact_id", "materialization_id"
  ], "Lineage.factors.exit");
  const lineageStrategy = closedRecord(lineage.strategy, [
    "decision_chains", "research_strategy_spec_artifact_id", "research_strategy_spec_id",
    "risk_policy_set_version_id", "strategy_definition_artifact_id",
    "strategy_definition_version_id", "strategy_version_id"
  ], "Lineage.strategy");
  const lineageExecution = closedRecord(lineage.execution, [
    "fills", "orders", "run_id", "run_spec_artifact_id", "run_spec_id", "target_quantity_vectors"
  ], "Lineage.execution");
  const lineageResult = closedRecord(lineage.result, [
    "analytics_artifact_id", "analytics_id", "backtest_result_id", "backtest_result_sha256",
    "result_artifact_id", "result_id"
  ], "Lineage.result");
  const canonicalLineageId = (value: unknown, label: string): string => {
    if (typeof value !== "string" || !CANONICAL_ID_PATTERN.test(value)) {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} is not a canonical identity`);
    }
    return value;
  };
  const lineageArtifactId = (value: unknown, label: string): string => {
    if (typeof value !== "string" || !ARTIFACT_ID_PATTERN.test(value)) {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", `${label} is not an Artifact identity`);
    }
    return value;
  };
  const projectedLineage = {
    rawCaptureId: canonicalLineageId(lineageData.raw_capture_id, "Lineage.data.raw_capture_id"),
    rawArtifactId: lineageArtifactId(lineageData.raw_artifact_id, "Lineage.data.raw_artifact_id"),
    snapshotId: canonicalLineageId(lineageData.snapshot_id, "Lineage.data.snapshot_id"),
    universeVersionId: canonicalLineageId(lineageData.universe_version_id, "Lineage.data.universe_version_id"),
    entryFactorVersionId: canonicalLineageId(entryFactor.factor_definition_version_id, "Lineage.factors.entry.factor_definition_version_id"),
    exitFactorVersionId: canonicalLineageId(exitFactor.factor_definition_version_id, "Lineage.factors.exit.factor_definition_version_id"),
    researchStrategySpecId: canonicalLineageId(lineageStrategy.research_strategy_spec_id, "Lineage.strategy.research_strategy_spec_id"),
    strategyVersionId: canonicalLineageId(lineageStrategy.strategy_version_id, "Lineage.strategy.strategy_version_id"),
    riskPolicySetVersionId: canonicalLineageId(lineageStrategy.risk_policy_set_version_id, "Lineage.strategy.risk_policy_set_version_id"),
    runSpecArtifactId: lineageArtifactId(lineageExecution.run_spec_artifact_id, "Lineage.execution.run_spec_artifact_id")
  };
  if (lineageData.snapshot_id !== summary.snapshotId || lineageData.universe_version_id !== summary.universeVersionId
    || lineageStrategy.research_strategy_spec_id !== summary.researchStrategySpecId
    || lineageStrategy.strategy_version_id !== home.strategy?.strategyVersionId
    || lineageStrategy.risk_policy_set_version_id !== home.strategy?.profileRefs.riskPolicySetVersionId
    || lineageExecution.run_id !== summary.runId || lineageExecution.run_spec_id !== summary.runSpecId
    || lineageResult.result_id !== summary.resultId || lineageResult.backtest_result_id !== summary.backtestResultId
    || lineageResult.backtest_result_sha256 !== result.content_sha256
    || lineageResult.result_artifact_id !== summary.resultArtifactId || lineageResult.analytics_id !== summary.analyticsId
    || lineageResult.analytics_artifact_id !== summary.analyticsArtifactId
    || entryFactor.factor_definition_version_id !== home.strategy?.entrySignalFactorVersionId
    || exitFactor.factor_definition_version_id !== home.strategy?.exitSignalFactorVersionId) {
    throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "Result lineage refs do not close over the current VALID result");
  }
  const table = <T>(rows: readonly T[], sourceArtifactId: string) => Object.freeze({
    rowCount: rows.length,
    preview: Object.freeze(rows.slice(0, RESULT_TABLE_PREVIEW_LIMIT)),
    truncated: rows.length > RESULT_TABLE_PREVIEW_LIMIT,
    sourceArtifactId
  });
  return Object.freeze({
    schemaVersion: "v3.product-result-details/1.0.0",
    maturity: "PRODUCT_CONNECTED", truth: "NOT_FORMAL", admission: "PRE_ALPHA", resultState: "VALID",
    resultId: summary.resultId, backtestResultId: summary.backtestResultId, analyticsId: summary.analyticsId,
    resultLineageId: summary.resultLineageId, runId: summary.runId, runSpecId: summary.runSpecId, engineVersion: summary.engineVersion,
    assumptionMode: summary.assumptionMode,
    metrics: Object.freeze({
      startNav: resultMetric(metrics.start_nav, "metrics.start_nav"), endNav: resultMetric(metrics.end_nav, "metrics.end_nav"),
      totalReturn: resultMetric(metrics.total_return, "metrics.total_return"), annualizedReturn: resultMetric(metrics.annualized_return, "metrics.annualized_return"),
      annualizedVolatility: resultMetric(metrics.annualized_volatility, "metrics.annualized_volatility"), maxDrawdown: resultMetric(metrics.max_drawdown, "metrics.max_drawdown"),
      sharpe: resultMetric(metrics.sharpe, "metrics.sharpe"), sortino: resultMetric(metrics.sortino, "metrics.sortino"),
      calmar: resultMetric(supplemental.calmar, "metrics.calmar")
    }),
    navSeries: Object.freeze(navSeries), drawdownSeries: Object.freeze(drawdownSeries), exposureSeries: Object.freeze(exposureSeries),
    periodReturns: Object.freeze({ monthly: monthlyReturns, yearly: yearlyReturns }),
    costSummary: Object.freeze({
      fillCount: nonNegativeInt(costs.fill_count, "costs.fill_count"),
      grossTradedNotional: decimalText(costs.gross_traded_notional, "costs.gross_traded_notional"),
      totalFees: decimalText(costs.total_fees, "costs.total_fees"),
      turnover: resultMetric(turnover.turnover, "turnover.turnover")
    }),
    concentration: Object.freeze({
      peakSinglePositionWeight: resultMetric(concentration.peak_single_position_weight, "concentration.peak_single_position_weight"),
      peakSessionDate,
      peakInstrumentId: peakInstrumentId as string | null,
      averageHeldInstrumentCount: resultMetric(concentration.average_held_instrument_count, "concentration.average_held_instrument_count"),
      maximumHeldInstrumentCount: nonNegativeInt(concentration.maximum_held_instrument_count, "concentration.maximum_held_instrument_count")
    }),
    benchmarkStatus: benchmark.status as "AVAILABLE" | "BENCHMARK_NOT_AVAILABLE",
    orders: table(orderRows, summary.resultArtifactId), fills: table(fillRows, summary.resultArtifactId),
    diagnostics: table(diagnosticRows, summary.resultArtifactId), holdings: table(holdingRows, summary.resultArtifactId),
    lineage: Object.freeze({
      ...projectedLineage,
      resultArtifactId: summary.resultArtifactId, analyticsArtifactId: summary.analyticsArtifactId, lineageArtifactId: summary.lineageArtifactId
    }),
    exports: Object.freeze({
      summaryJsonArtifactId: summary.summaryExportArtifactId,
      ordersCsvArtifactId: summary.ordersExportArtifactId,
      fillsCsvArtifactId: summary.fillsExportArtifactId,
      analyticsJsonArtifactId: summary.analyticsArtifactId
    })
  });
}

function adaptProjectHome(response: unknown): ProductProjectHomeView {
  if (response === null || typeof response !== "object" || Array.isArray(response)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project home returned a non-object response");
  }
  const top = response as Record<string, unknown>;
  if (top.truth_state !== "NOT_FORMAL" || top.read_model === null || typeof top.read_model !== "object" || Array.isArray(top.read_model)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project home truth or read model is invalid");
  }
  const model = top.read_model as Record<string, unknown>;
  const required = [
    "admission", "data_state", "data_unavailable_reason", "local_import_state",
    "factor_state", "factor_unavailable_reason", "maturity",
    "project_context_revision_id", "project_id", "read_model_version", "truth",
    "strategy_authoring_profile", "strategy_state", "strategy_unavailable_reason",
    "backtest_policy_coverage",
    "backtest_state", "backtest_unavailable_reason"
  ];
  const allowed = new Set([...required, "data", "factor", "strategy", "backtest"]);
  if (required.some((key) => !(key in model)) || Object.keys(model).some((key) => !allowed.has(key))) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project home fields do not match the closed shape");
  }
  if (
    model.read_model_version !== "v3.project-home/1.1"
    || typeof model.project_id !== "string" || !PROJECT_ID_PATTERN.test(model.project_id)
    || typeof model.project_context_revision_id !== "string" || !PROJECT_CONTEXT_REVISION_PATTERN.test(model.project_context_revision_id)
    || model.maturity !== "PRODUCT_CONNECTED"
    || model.truth !== "NOT_FORMAL"
    || model.admission !== "PRE_ALPHA"
    || model.local_import_state !== "AVAILABLE"
    || !["EMPTY", "AVAILABLE", "UNAVAILABLE"].includes(String(model.data_state))
    || !["NONE", "NO_SNAPSHOT", "DATA_READ_MODEL_NOT_AVAILABLE"].includes(String(model.data_unavailable_reason))
    || !["EMPTY", "AVAILABLE", "UNAVAILABLE"].includes(String(model.factor_state))
    || !["NONE", "NO_SNAPSHOT", "NO_FACTOR_STUDY", "FACTOR_READ_MODEL_NOT_AVAILABLE"].includes(String(model.factor_unavailable_reason))
    || !["EMPTY", "AVAILABLE", "UNAVAILABLE"].includes(String(model.strategy_state))
    || !["NONE", "NO_FACTOR_STUDY", "NO_RESEARCH_STRATEGY", "STRATEGY_READ_MODEL_NOT_AVAILABLE"].includes(String(model.strategy_unavailable_reason))
    || !["EMPTY", "AVAILABLE", "UNAVAILABLE"].includes(String(model.backtest_state))
    || !["NONE", "NO_RESEARCH_STRATEGY", "NO_VALID_BACKTEST", "BACKTEST_READ_MODEL_NOT_AVAILABLE"].includes(String(model.backtest_unavailable_reason))
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project home identity or truth fields are invalid");
  }
  let factor: ProductFactorSummaryView | null = null;
  if (model.factor_state === "AVAILABLE") {
    if (model.factor_unavailable_reason !== "NONE") throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "available Factor carries an unavailable reason");
    factor = adaptProjectFactor(model.factor, model.project_id, model.project_context_revision_id);
  } else {
    if ("factor" in model || model.factor_unavailable_reason === "NONE") {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "unavailable Factor state is inconsistent");
    }
  }
  const strategyAuthoringProfile = adaptStrategyAuthoringProfile(model.strategy_authoring_profile);
  const coverage = closedRecord(
    model.backtest_policy_coverage,
    ["admission", "commission_rate", "cost_policy_id", "coverage_end", "coverage_start", "execution_timing_profile_id", "minimum_commission_cny", "resource_estimate", "rule_profile_id", "schema_version", "stamp_duty_sell_rate", "truth"],
    "backtest_policy_coverage"
  );
  if (
    coverage.schema_version !== "v3.product-backtest-policy-coverage/1.0.0"
    || coverage.truth !== "NOT_FORMAL" || coverage.admission !== "PRE_ALPHA"
    || typeof coverage.coverage_start !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(coverage.coverage_start)
    || (coverage.coverage_end !== null && (typeof coverage.coverage_end !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(coverage.coverage_end)))
    || (typeof coverage.coverage_end === "string" && coverage.coverage_end < coverage.coverage_start)
    || typeof coverage.rule_profile_id !== "string" || !/^atrp_sha256_[0-9a-f]{64}$/.test(coverage.rule_profile_id)
    || typeof coverage.cost_policy_id !== "string" || !/^cost_sha256_[0-9a-f]{64}$/.test(coverage.cost_policy_id)
    || typeof coverage.execution_timing_profile_id !== "string" || !/^timing_sha256_[0-9a-f]{64}$/.test(coverage.execution_timing_profile_id)
    || typeof coverage.commission_rate !== "string" || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(coverage.commission_rate)
    || typeof coverage.minimum_commission_cny !== "string" || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(coverage.minimum_commission_cny)
    || typeof coverage.stamp_duty_sell_rate !== "string" || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(coverage.stamp_duty_sell_rate)
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Backtest policy coverage drifted");
  }
  const backtestPolicyCoverage = Object.freeze({
    schemaVersion: "v3.product-backtest-policy-coverage/1.0.0" as const,
    truth: "NOT_FORMAL" as const,
    admission: "PRE_ALPHA" as const,
    coverageStart: coverage.coverage_start,
    coverageEnd: coverage.coverage_end as string | null,
    ruleProfileId: coverage.rule_profile_id,
    costPolicyId: coverage.cost_policy_id,
    executionTimingProfileId: coverage.execution_timing_profile_id,
    commissionRate: coverage.commission_rate,
    minimumCommissionCny: coverage.minimum_commission_cny,
    stampDutySellRate: coverage.stamp_duty_sell_rate,
    resourceEstimate: (() => {
      const estimate = closedRecord(
        coverage.resource_estimate,
        ["checkpoint_resume", "cpu_slots", "memory_limit_bytes", "resource_class", "scratch_limit_bytes"],
        "backtest_policy_coverage.resource_estimate"
      );
      if (
        estimate.resource_class !== "PRODUCT_BACKTEST_CPU"
        || estimate.cpu_slots !== 1
        || estimate.memory_limit_bytes !== 1_073_741_824
        || estimate.scratch_limit_bytes !== 1_073_741_824
        || estimate.checkpoint_resume !== "UNAVAILABLE"
      ) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Backtest resource estimate drifted");
      return Object.freeze({
        resourceClass: "PRODUCT_BACKTEST_CPU" as const,
        cpuSlots: 1 as const,
        memoryLimitBytes: 1_073_741_824 as const,
        scratchLimitBytes: 1_073_741_824 as const,
        checkpointResume: "UNAVAILABLE" as const
      });
    })()
  });
  let strategy: ProductStrategySummaryView | null = null;
  if (model.strategy_state === "AVAILABLE") {
    if (model.strategy_unavailable_reason !== "NONE") throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "available Strategy carries an unavailable reason");
    strategy = adaptProjectStrategy(
      model.strategy,
      model.project_id,
      model.project_context_revision_id,
      strategyAuthoringProfile
    );
  } else if ("strategy" in model || model.strategy_unavailable_reason === "NONE") {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "unavailable Strategy state is inconsistent");
  }
  let backtest: ProductBacktestSummaryView | null = null;
  if (model.backtest_state === "AVAILABLE") {
    if (model.backtest_unavailable_reason !== "NONE" || strategy === null) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "available Backtest has no exact Strategy authority");
    }
    backtest = adaptProjectBacktest(
      model.backtest,
      model.project_id,
      model.project_context_revision_id,
      strategy,
      strategyAuthoringProfile
    );
  } else if ("backtest" in model || model.backtest_unavailable_reason === "NONE") {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "unavailable Backtest state is inconsistent");
  }
  if (model.data_state !== "AVAILABLE") {
    if ("data" in model || factor !== null || strategy !== null || backtest !== null) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "unavailable project data cannot authorize downstream summaries");
    }
    return Object.freeze({
      readModelVersion: "v3.project-home/1.1",
      projectId: model.project_id,
      projectContextRevisionId: model.project_context_revision_id,
      maturity: "PRODUCT_CONNECTED",
      truth: "NOT_FORMAL",
      admission: "PRE_ALPHA",
      localImportState: "AVAILABLE",
      dataState: model.data_state as "EMPTY" | "UNAVAILABLE",
      dataUnavailableReason: model.data_unavailable_reason as "NO_SNAPSHOT" | "DATA_READ_MODEL_NOT_AVAILABLE",
      data: null,
      factorState: model.factor_state as "EMPTY" | "AVAILABLE" | "UNAVAILABLE",
      factorUnavailableReason: model.factor_unavailable_reason as "NONE" | "NO_SNAPSHOT" | "NO_FACTOR_STUDY" | "FACTOR_READ_MODEL_NOT_AVAILABLE",
      factor,
      strategyAuthoringProfile,
      backtestPolicyCoverage,
      strategyState: model.strategy_state as "EMPTY" | "UNAVAILABLE",
      strategyUnavailableReason: model.strategy_unavailable_reason as "NO_FACTOR_STUDY" | "NO_RESEARCH_STRATEGY" | "STRATEGY_READ_MODEL_NOT_AVAILABLE",
      strategy,
      backtestState: model.backtest_state as "EMPTY" | "UNAVAILABLE",
      backtestUnavailableReason: model.backtest_unavailable_reason as "NO_RESEARCH_STRATEGY" | "NO_VALID_BACKTEST" | "BACKTEST_READ_MODEL_NOT_AVAILABLE",
      backtest
    });
  }
  if (model.data_unavailable_reason !== "NONE" || model.data === null || typeof model.data !== "object" || Array.isArray(model.data)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "available project home data is absent");
  }
  const data = model.data as Record<string, unknown>;
  const dataKeys = [
    "adjustment", "admission", "amount_unit", "capability_reasons", "date_coverage_end", "date_coverage_start", "display_name", "imported_at",
    "instrument_count", "media_type", "normalized_payload_hash", "pit_state",
    "partition_count", "project_context_revision_id", "project_id", "quality_status", "raw_artifact_id", "raw_capture_id",
    "raw_content_hash", "row_count", "schema_version", "snapshot_id", "source_type",
    "truth", "universe_role", "universe_version_id", "validation_profile_id", "volume_unit"
  ];
  if (Object.keys(data).sort().join(",") !== dataKeys.sort().join(",")) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project data fields do not match the closed shape");
  }
  if (
    data.schema_version !== "v3.product-data-read-model/1.0.0"
    || data.project_id !== model.project_id
    || data.project_context_revision_id !== model.project_context_revision_id
    || typeof data.display_name !== "string" || data.display_name.length < 1 || data.display_name.length > 255
    || data.truth !== "NOT_FORMAL" || data.admission !== "PRE_ALPHA"
    || data.source_type !== "LOCAL_USER_SUPPLIED" || data.pit_state !== "PIT_UNPROVABLE"
    || !["text/csv", "application/vnd.apache.parquet"].includes(String(data.media_type))
    || !Number.isSafeInteger(data.row_count) || Number(data.row_count) < 1 || Number(data.row_count) > 2_000_000
    || !Number.isSafeInteger(data.instrument_count) || Number(data.instrument_count) < 1 || Number(data.instrument_count) > 2_000
    || typeof data.date_coverage_start !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(data.date_coverage_start)
    || typeof data.date_coverage_end !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(data.date_coverage_end)
    || data.date_coverage_start > data.date_coverage_end
    || !Number.isSafeInteger(data.partition_count) || Number(data.partition_count) < 1 || Number(data.partition_count) > 2_000_000
    || data.universe_role !== "USER_DEFINED_STATIC"
    || data.quality_status !== "PASS"
    || data.validation_profile_id !== "svp_local_user_supplied_v1"
    || data.volume_unit !== "SHARES" || data.amount_unit !== "CNY" || data.adjustment !== "UNADJUSTED"
    || typeof data.raw_capture_id !== "string" || !CANONICAL_ID_PATTERN.test(data.raw_capture_id)
    || typeof data.raw_content_hash !== "string" || !CONTENT_SHA_PATTERN.test(data.raw_content_hash)
    || typeof data.snapshot_id !== "string" || !CANONICAL_ID_PATTERN.test(data.snapshot_id)
    || typeof data.normalized_payload_hash !== "string" || !CONTENT_SHA_PATTERN.test(data.normalized_payload_hash)
    || typeof data.universe_version_id !== "string" || !CANONICAL_ID_PATTERN.test(data.universe_version_id)
    || typeof data.imported_at !== "string" || Number.isNaN(Date.parse(data.imported_at))
    || typeof data.raw_artifact_id !== "string" || !ARTIFACT_ID_PATTERN.test(data.raw_artifact_id)
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project data identity, bounds or truth fields are invalid");
  }
  if (
    (factor !== null && (factor.snapshotId !== data.snapshot_id || factor.universeVersionId !== data.universe_version_id))
    || (strategy !== null && (strategy.snapshotId !== data.snapshot_id || strategy.universeVersionId !== data.universe_version_id))
    || (backtest !== null && (backtest.snapshotId !== data.snapshot_id || backtest.universeVersionId !== data.universe_version_id))
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project downstream summary does not bind the current Data authority");
  }
  if (strategy !== null) {
    if (factor === null) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy requires the current Factor summary");
    const booleanFactorIds = new Set(
      factor.outputs.filter((output) => output.outputType === "BOOLEAN_SERIES").map((output) => output.factorDefinitionVersionId)
    );
    if (!booleanFactorIds.has(strategy.entrySignalFactorVersionId) || !booleanFactorIds.has(strategy.exitSignalFactorVersionId)) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy signal refs are absent from current BOOLEAN Factor outputs");
    }
  }
  const capabilityReasons = data.capability_reasons;
  if (
    capabilityReasons === null || typeof capabilityReasons !== "object" || Array.isArray(capabilityReasons)
    || Object.keys(capabilityReasons).sort().join(",") !== "calendar,pit,revision,status"
    || (capabilityReasons as Record<string, unknown>).pit !== "PIT_UNPROVABLE"
    || (capabilityReasons as Record<string, unknown>).revision !== "PROVIDER_REVISION_UNKNOWN"
    || (capabilityReasons as Record<string, unknown>).calendar !== "OBSERVED_LOCAL_ROWS_NOT_FORMAL_TRADING_CALENDAR"
    || (capabilityReasons as Record<string, unknown>).status !== "SOURCE_COLUMN_ABSENT_OR_NULL_WHEN_NOT_PROVIDED"
  ) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project data capability reasons are invalid");
  }
  return Object.freeze({
    readModelVersion: "v3.project-home/1.1",
    projectId: model.project_id,
    projectContextRevisionId: model.project_context_revision_id,
    maturity: "PRODUCT_CONNECTED",
    truth: "NOT_FORMAL",
    admission: "PRE_ALPHA",
    localImportState: "AVAILABLE",
    dataState: "AVAILABLE",
    dataUnavailableReason: "NONE",
    data: Object.freeze({
      schemaVersion: "v3.product-data-read-model/1.0.0",
      projectId: data.project_id,
      projectContextRevisionId: data.project_context_revision_id,
      displayName: data.display_name,
      truth: "NOT_FORMAL",
      admission: "PRE_ALPHA",
      sourceType: "LOCAL_USER_SUPPLIED",
      pitState: "PIT_UNPROVABLE",
      mediaType: data.media_type as "text/csv" | "application/vnd.apache.parquet",
      rowCount: Number(data.row_count),
      instrumentCount: Number(data.instrument_count),
      dateCoverageStart: data.date_coverage_start,
      dateCoverageEnd: data.date_coverage_end,
      partitionCount: Number(data.partition_count),
      universeRole: "USER_DEFINED_STATIC",
      qualityStatus: "PASS",
      validationProfileId: "svp_local_user_supplied_v1",
      capabilityReasons: Object.freeze({
        pit: "PIT_UNPROVABLE",
        revision: "PROVIDER_REVISION_UNKNOWN",
        calendar: "OBSERVED_LOCAL_ROWS_NOT_FORMAL_TRADING_CALENDAR",
        status: "SOURCE_COLUMN_ABSENT_OR_NULL_WHEN_NOT_PROVIDED"
      }),
      volumeUnit: "SHARES",
      amountUnit: "CNY",
      adjustment: "UNADJUSTED",
      rawCaptureId: data.raw_capture_id,
      rawContentHash: data.raw_content_hash,
      snapshotId: data.snapshot_id,
      normalizedPayloadHash: data.normalized_payload_hash,
      universeVersionId: data.universe_version_id,
      importedAt: data.imported_at,
      rawArtifactId: data.raw_artifact_id
    }),
    factorState: model.factor_state as "EMPTY" | "AVAILABLE" | "UNAVAILABLE",
    factorUnavailableReason: model.factor_unavailable_reason as "NONE" | "NO_SNAPSHOT" | "NO_FACTOR_STUDY" | "FACTOR_READ_MODEL_NOT_AVAILABLE",
    factor,
    strategyAuthoringProfile,
    backtestPolicyCoverage,
    strategyState: model.strategy_state as "EMPTY" | "AVAILABLE" | "UNAVAILABLE",
    strategyUnavailableReason: model.strategy_unavailable_reason as "NONE" | "NO_FACTOR_STUDY" | "NO_RESEARCH_STRATEGY" | "STRATEGY_READ_MODEL_NOT_AVAILABLE",
    strategy,
    backtestState: model.backtest_state as "EMPTY" | "AVAILABLE" | "UNAVAILABLE",
    backtestUnavailableReason: model.backtest_unavailable_reason as "NONE" | "NO_RESEARCH_STRATEGY" | "NO_VALID_BACKTEST" | "BACKTEST_READ_MODEL_NOT_AVAILABLE",
    backtest
  });
}

function researchOperationPayload(
  request: ProductResearchSubmitIntent,
  idempotencyKey: string,
): Record<string, unknown> {
  return {
    research_profile_id: "RESEARCH_FREE_DATA_V1",
    strategy_profile_id: "RESEARCH_CLOSE_RANK_TOP1_V1",
    source: {
      provider_id: "pvd_akshare_eastmoney_a_share_eod_v1",
      connector_version_id: "cov_akshare_eod_research_v1",
      logical_dataset: "CN_A_SHARE_EOD",
      frequency: "P1D",
      symbol: request.symbol,
      start_date: request.startDate,
      end_date: request.endDate
    },
    idempotency_key: idempotencyKey
  };
}

interface RunSpecPageView {
  readonly specs: RunSpecEntryView[];
  readonly hasMore: boolean;
  readonly nextAfterArtifactId: string | null;
}

function runSpecStatus(rawStatus: unknown): RunSpecEntryView["status"] {
  if (rawStatus === "EXECUTABLE" || rawStatus === "UNAVAILABLE") return rawStatus;
  throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "run-spec discovery returned an unknown status");
}

function nullableRunSpecString(
  row: Record<string, unknown>,
  name: string,
  maxLength: number
): string | null {
  const value = row[name];
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", `run-spec discovery returned invalid ${name}`);
  }
  return value;
}

function validRunSpecMetadata(entry: RunSpecEntryView): boolean {
  return entry.runSpecId !== null && RUN_SPEC_ID_PATTERN.test(entry.runSpecId)
    && entry.contentSha256 !== null && CONTENT_SHA_PATTERN.test(entry.contentSha256)
    && entry.projectContextRevisionId !== null && PROJECT_CONTEXT_REVISION_PATTERN.test(entry.projectContextRevisionId)
    && entry.engineVersion !== null
    && entry.createdAt !== null && entry.createdAt.endsWith("Z") && !Number.isNaN(Date.parse(entry.createdAt))
    && entry.executionAdapterVersionId !== null;
}

function validateRunSpecStatusSemantics(entry: RunSpecEntryView): void {
  if (entry.status === "EXECUTABLE") {
    if (!validRunSpecMetadata(entry) || entry.diagnostic !== null) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "EXECUTABLE run-spec discovery metadata is not canonical");
    }
    return;
  }
  if (entry.diagnostic === null) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "UNAVAILABLE run-spec discovery requires a diagnostic");
  }
  for (const [name, value, pattern] of [
    ["run_spec_id", entry.runSpecId, RUN_SPEC_ID_PATTERN],
    ["content_sha256", entry.contentSha256, CONTENT_SHA_PATTERN],
    ["project_context_revision_id", entry.projectContextRevisionId, PROJECT_CONTEXT_REVISION_PATTERN],
  ] as const) {
    if (value !== null && !pattern.test(value)) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", `UNAVAILABLE run-spec discovery returned invalid ${name}`);
    }
  }
  if (entry.createdAt !== null && (!entry.createdAt.endsWith("Z") || Number.isNaN(Date.parse(entry.createdAt)))) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "UNAVAILABLE run-spec discovery returned invalid created_at");
  }
}

function adaptRunSpecEntry(rawEntry: unknown, seenArtifacts: Set<string>): RunSpecEntryView {
  if (rawEntry === null || typeof rawEntry !== "object" || Array.isArray(rawEntry)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "run-spec discovery returned a non-object entry");
  }
  const row = rawEntry as Record<string, unknown>;
  const artifactId = row.artifact_id;
  if (typeof artifactId !== "string" || !ARTIFACT_ID_PATTERN.test(artifactId)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "run-spec discovery returned a malformed artifact identity");
  }
  if (seenArtifacts.has(artifactId)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "run-spec pagination returned a duplicate artifact");
  }
  seenArtifacts.add(artifactId);
  const entry: RunSpecEntryView = {
    runSpecId: nullableRunSpecString(row, "run_spec_id", 76),
    artifactId,
    contentSha256: nullableRunSpecString(row, "content_sha256", 64),
    projectContextRevisionId: nullableRunSpecString(row, "project_context_revision_id", 30),
    engineVersion: nullableRunSpecString(row, "engine_version", 200),
    createdAt: nullableRunSpecString(row, "created_at", 200),
    executionAdapterVersionId: nullableRunSpecString(row, "execution_adapter_version_id", 200),
    status: runSpecStatus(row.status),
    diagnostic: nullableRunSpecString(row, "diagnostic", 500)
  };
  validateRunSpecStatusSemantics(entry);
  return entry;
}

function requiredImportString(
  readModel: Record<string, unknown>,
  name: string,
  pattern: RegExp,
): string {
  const value = readModel[name];
  if (typeof value !== "string" || !pattern.test(value)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", `research package import returned invalid ${name}`);
  }
  return value;
}

/** Fail-closed adapter kept exported for contract-drift regression coverage. */
export function adaptImportResearchPackageOutcome(response: unknown): ImportResearchPackageOutcomeView {
  if (response === null || typeof response !== "object" || Array.isArray(response)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "research package import returned a non-object response");
  }
  const readModel = (response as Record<string, unknown>).read_model;
  if (readModel === null || typeof readModel !== "object" || Array.isArray(readModel)) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "research package import returned a non-object read_model");
  }
  const record = readModel as Record<string, unknown>;
  if (record.read_model_version !== "v3.product-entry/1.0") {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "research package import returned an unsupported read_model_version");
  }
  if (typeof record.already_imported !== "boolean") {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "research package import returned invalid already_imported");
  }
  const importedAt = record.imported_at;
  if (typeof importedAt !== "string" || !importedAt.endsWith("Z") || Number.isNaN(Date.parse(importedAt))) {
    throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "research package import returned invalid imported_at");
  }
  return Object.freeze({
    runSpecId: requiredImportString(record, "run_spec_id", RUN_SPEC_ID_PATTERN),
    runSpecArtifactId: requiredImportString(record, "run_spec_artifact_id", ARTIFACT_ID_PATTERN),
    contextArtifactId: requiredImportString(record, "context_artifact_id", ARTIFACT_ID_PATTERN),
    alreadyImported: record.already_imported,
    sourceProjectId: requiredImportString(record, "source_project_id", PROJECT_ID_PATTERN),
    importedAt,
  });
}

function adaptRunSpecPage(
  response: unknown,
  seenArtifacts: Set<string>,
  priorCursor: string | null
): RunSpecPageView {
  const readModel = (response as {
    read_model?: { specs?: unknown; has_more?: unknown; next_after_artifact_id?: unknown };
  }).read_model ?? {};
  const specs = Array.isArray(readModel.specs)
    ? readModel.specs.map((entry) => adaptRunSpecEntry(entry, seenArtifacts))
    : [];
  const hasMore = readModel.has_more === true;
  const nextCursor = readModel.next_after_artifact_id;
  if (!hasMore) {
    if (nextCursor !== null) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "terminal run-spec page returned a non-null cursor");
    }
    return { specs, hasMore, nextAfterArtifactId: null };
  }
  if (
    typeof nextCursor !== "string"
    || !ARTIFACT_ID_PATTERN.test(nextCursor)
    || nextCursor === priorCursor
    || specs.at(-1)?.artifactId !== nextCursor
  ) {
    throw new ProductAdapterError(
      "PRODUCT_BRIDGE_ERROR",
      "run-spec pagination cursor did not advance at the last returned artifact"
    );
  }
  return { specs, hasMore, nextAfterArtifactId: nextCursor };
}

/** Main-process owned research package directory chooser (Electron dialog). */
export type ResearchPackageChooser = () => Promise<string | null>;

export type ProductBindingOutcome =
  | { readonly state: "PROJECT_BOUND" }
  | { readonly state: "NO_CANONICAL_PROJECT_BOUND" }
  | { readonly state: "BINDING_STALE"; readonly code: string; readonly message: string };

function uuidV4(): string {
  const bytes = randomBytes(16);
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function assertCanonicalId(value: string, name: string): void {
  if (typeof value !== "string" || !CANONICAL_ID_PATTERN.test(value)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", `${name} is not a bounded canonical identifier`);
  }
}

function assertTaskListFilter(filter: ProductTaskListFilter | undefined): ProductTaskListFilter {
  const candidate = filter ?? {};
  if (candidate === null || typeof candidate !== "object" || Array.isArray(candidate)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "task list filter must be an object");
  }
  const unknown = Object.keys(candidate as object).filter((key) => key !== "service" && key !== "state");
  if (unknown.length > 0) {
    throw new ProductAdapterError("INVALID_ARGUMENT", `unknown task list filter fields: ${unknown.join(", ")}`);
  }
  if (candidate.service !== undefined && candidate.service !== "ProductEntryService") {
    throw new ProductAdapterError("INVALID_ARGUMENT", "task list service filter is not admitted");
  }
  if (candidate.state !== undefined && candidate.state !== "SUCCEEDED") {
    throw new ProductAdapterError("INVALID_ARGUMENT", "task list state filter is not admitted");
  }
  return Object.freeze({
    ...(candidate.service === undefined ? {} : { service: candidate.service }),
    ...(candidate.state === undefined ? {} : { state: candidate.state })
  });
}

function assertProductPageRequest(request: ProductPageRequest | undefined): Required<Pick<ProductPageRequest, "pageSize">> & Pick<ProductPageRequest, "cursor"> {
  const candidate = request ?? {};
  if (candidate === null || typeof candidate !== "object" || Array.isArray(candidate)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "page request must be an object");
  }
  const unknown = Object.keys(candidate).filter((key) => key !== "cursor" && key !== "pageSize");
  if (unknown.length > 0) throw new ProductAdapterError("INVALID_ARGUMENT", `unknown page request fields: ${unknown.join(", ")}`);
  const pageSize = candidate.pageSize ?? DEFAULT_PRODUCT_PAGE_SIZE;
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > MAX_PRODUCT_PAGE_SIZE) {
    throw new ProductAdapterError("INVALID_ARGUMENT", `pageSize must be an integer in [1, ${MAX_PRODUCT_PAGE_SIZE}]`);
  }
  if (candidate.cursor !== undefined && (typeof candidate.cursor !== "string" || candidate.cursor.length < 1 || candidate.cursor.length > 2048)) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "cursor must be a bounded opaque string");
  }
  return Object.freeze({ pageSize, ...(candidate.cursor === undefined ? {} : { cursor: candidate.cursor }) });
}

export class ProductBridge {
  private inflightSubmit = new Map<string, Promise<BacktestSubmitOutcomeView>>();
  private inflightResearch = new Map<string, Promise<ProductResearchSubmitOutcomeView>>();
  private inflightFactor = new Map<string, Promise<ProductFactorStudyOutcomeView>>();
  private inflightStrategy = new Map<string, Promise<ProductResearchStrategyOutcomeView>>();
  private inflightResearchBacktest = new Map<string, Promise<ProductResearchBacktestOutcomeView>>();
  private bindingActivationInProgress = false;
  private bindingOutcome: ProductBindingOutcome = { state: "NO_CANONICAL_PROJECT_BOUND" };
  private readonly supervisor: BackendSupervisor;
  private readonly store: WorkspaceStore;
  private readonly bindings: ProductBindingStore;
  private readonly createProjectIntents: CreateProjectIntentStore;
  private readonly localDataSources: LocalDataSourceBroker | null;
  private readonly artifactExports: ArtifactExportBroker | null;

  constructor(
    supervisor: BackendSupervisor,
    store: WorkspaceStore,
    bindings: ProductBindingStore,
    chooseResearchPackage: ResearchPackageChooser = async () => null,
    createProjectIntents: CreateProjectIntentStore = new CreateProjectIntentStore(
      createProjectIntentPath(dirname(bindings.path))
    ),
    localDataSources: LocalDataSourceBroker | null = null,
    artifactExports: ArtifactExportBroker | null = null
  ) {
    this.supervisor = supervisor;
    this.store = store;
    this.bindings = bindings;
    this.chooseResearchPackage = chooseResearchPackage;
    this.createProjectIntents = createProjectIntents;
    this.localDataSources = localDataSources;
    this.artifactExports = artifactExports;
  }

  private readonly chooseResearchPackage: ResearchPackageChooser;

  /** Restore a persisted binding before backend launch; invalid refs are dropped. */
  async restorePersistedBinding(): Promise<ProductBindingRefs | null> {
    const persisted = await this.bindings.load();
    if (persisted === null) {
      this.bindingOutcome = { state: "NO_CANONICAL_PROJECT_BOUND" };
      return null;
    }
    return { projectId: persisted.projectId, projectContextRevisionId: persisted.projectContextRevisionId, sessionId: persisted.sessionId };
  }

  /**
   * Raw persisted refs. These are assumed-revalidatable pointers only: after
   * a failed canonical re-validation they remain as a reconnect hint but are
   * NOT an admitted canonical binding and must never reach the renderer as
   * bound product truth.
   */
  private storedBindingRefs(): ProductBindingRefs | null {
    const persisted = this.bindings.current;
    if (persisted === null) return null;
    return { projectId: persisted.projectId, projectContextRevisionId: persisted.projectContextRevisionId, sessionId: persisted.sessionId };
  }

  /** Admitted refs: only a PROJECT_BOUND outcome admits canonical product truth. */
  private admittedBindingRefs(): ProductBindingRefs | null {
    return this.bindingOutcome.state === "PROJECT_BOUND" ? this.storedBindingRefs() : null;
  }

  recordBindingOutcome(outcome: ProductBindingOutcome): void {
    this.bindingOutcome = outcome;
  }

  async getProductStatus(): Promise<ProductStatusView> {
    // The recorded binding outcome - not the mere existence of persisted
    // refs - is the renderer-facing binding authority. A stale binding
    // (canonical re-validation failed) reports BINDING_STALE with no bound
    // project instead of pretending PROJECT_BOUND.
    const bound = this.admittedBindingRefs();
    const bindingState = this.bindingOutcome.state === "PROJECT_BOUND"
      ? "PROJECT_BOUND" as const
      : this.bindingOutcome.state === "BINDING_STALE"
        ? "BINDING_STALE" as const
        : "NO_CANONICAL_PROJECT_BOUND" as const;
    const health = this.supervisor.state === "READY" && typeof this.supervisor.getHealth === "function"
      ? await this.supervisor.getHealth(2_000).catch(() => null)
      : null;
    const buildManifestId = health !== null && typeof health.build_manifest_id === "string"
      ? health.build_manifest_id
      : null;
    const buildIdentityState = health?.build_identity_state === "CLEAN"
      ? "CLEAN" as const
      : health?.build_identity_state === "DIRTY"
        ? "DIRTY" as const
        : "UNAVAILABLE" as const;
    return Object.freeze({
      productVersion: this.supervisor.config?.desktopVersion ?? "UNAVAILABLE",
      backendState: this.supervisor.state,
      bindingState,
      boundProject: bound,
      capabilities: await this.getCapabilities(),
      buildManifestId,
      buildIdentityState
    });
  }

  async getCapabilities(): Promise<readonly ProductCapabilityView[]> {
    return adaptCapabilities(this.supervisor.capabilities);
  }

  async getBoundProject(): Promise<ProductBindingRefs | null> {
    return this.admittedBindingRefs();
  }

  async getProjectContext(): Promise<ProjectContextView> {
    this.requireBinding();
    const response = await this.supervisor.request("ProjectSessionService.v1.getProjectContext", {});
    return adaptProjectContext(response);
  }

  async getProjectHome(): Promise<ProductProjectHomeView> {
    this.requireBinding();
    const response = await this.supervisor.request(
      "ProductEntryService.v1.getProjectHome",
      {},
      { contractVersion: "1.1.0", expectedApiVersion: "1.1" }
    );
    return adaptProjectHome(response);
  }

  async getLatestProductResultDetails(): Promise<ProductLatestResultDetailsView> {
    this.requireBinding();
    const home = await this.getProjectHome();
    if (home.backtestState !== "AVAILABLE" || home.backtest === null || home.backtest.resultState !== "VALID") {
      throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "latest VALID research Result is unavailable");
    }
    const [resultBytes, analyticsBytes, lineageBytes] = await Promise.all([
      this.readArtifactBytes(home.backtest.resultArtifactId),
      this.readArtifactBytes(home.backtest.analyticsArtifactId),
      this.readArtifactBytes(home.backtest.lineageArtifactId)
    ]);
    return adaptLatestProductResultArtifacts(home, resultBytes, analyticsBytes, lineageBytes);
  }

  async restoreSession(): Promise<SessionRestoreView> {
    const refs = this.requireBindingOrPendingRevalidation();
    try {
      return await this.restoreAndVerify(refs);
    } catch (error) {
      const code = error !== null && typeof error === "object" && "code" in error
        ? String(error.code)
        : null;
      if (code !== "SESSION_PROJECT_BINDING_CONFLICT") throw error;
      try {
        await this.bindings.isolateActive(code);
      } catch (isolationError) {
        this.clearContext();
        this.bindingOutcome = {
          state: "BINDING_STALE",
          code: "BINDING_ACTIVE_ISOLATION_FAILED",
          message: isolationError instanceof Error ? isolationError.message : String(isolationError)
        };
        throw new ProductAdapterError(
          "BINDING_ACTIVE_ISOLATION_FAILED",
          "conflicting persisted session was rejected but its active binding could not be safely isolated",
          isolationError
        );
      }
      this.clearContext();
      this.bindingOutcome = {
        state: "BINDING_STALE",
        code,
        message: "persisted session belongs to a different canonical project; reopen the intended project"
      };
      throw new ProductAdapterError(
        code,
        "persisted session belongs to a different canonical project; reopen the intended project",
        error
      );
    }
  }

  /**
   * Connect an existing canonical project through an atomic activation. The
   * pending file is durable before the prior generation exits; only an exact
   * open/restore under the candidate generation may replace the active commit
   * marker. Any pre-commit failure restarts and revalidates the prior binding.
   */
  async connectExistingProject(candidate: { projectId: string; projectContextRevisionId: string }): Promise<ProjectContextView> {
    if (this.bindingActivationInProgress) {
      throw new ProductAdapterError("BINDING_ACTIVATION_IN_PROGRESS", "another canonical project activation is already in progress");
    }
    this.bindingActivationInProgress = true;
    try {
      return await this.activateExistingProject(candidate);
    } finally {
      this.bindingActivationInProgress = false;
    }
  }

  private async activateExistingProject(candidate: { projectId: string; projectContextRevisionId: string }): Promise<ProjectContextView> {
    assertCanonicalId(candidate.projectId, "projectId");
    assertCanonicalId(candidate.projectContextRevisionId, "projectContextRevisionId");
    const sessionId = uuidV4();
    const priorBinding = this.storedBindingRefs();
    const cursor = this.store.getProjectEventCursor(candidate.projectId);
    const candidateBinding = {
      projectId: candidate.projectId,
      projectContextRevisionId: candidate.projectContextRevisionId,
      sessionId
    };
    let staged: PersistedProductBinding;
    try {
      staged = await this.bindings.stage(candidateBinding);
    } catch (error) {
      throw new ProductAdapterError("BINDING_ACTIVATION_FAILED", "candidate binding could not be durably staged", error);
    }
    try {
      await this.supervisor.shutdown();
      this.supervisor.setProjectContext({
        projectId: candidate.projectId,
        projectContextRevisionId: candidate.projectContextRevisionId,
        lastDurableProjectEventSequence: cursor
      });
      await this.supervisor.start();
      const response = await this.supervisor.request("ProjectSessionService.v1.openProject", {
        project_locator: `${PROJECT_LOCATOR_PREFIX}${candidate.projectId}`,
        session_id: sessionId
      });
      const context = adaptProjectContext(response);
      this.assertExactBindingContext(candidateBinding, context);
      await this.restoreAndVerify(candidateBinding);
      await this.bindings.commit(staged);
      this.bindingOutcome = { state: "PROJECT_BOUND" };
      return context;
    } catch (error) {
      if (error instanceof ProductBindingStoreError && error.code === "BINDING_COMMIT_DURABILITY_UNCERTAIN") {
        this.bindingOutcome = {
          state: "BINDING_STALE",
          code: error.code,
          message: error.message
        };
        throw new ProductAdapterError(
          "BINDING_ACTIVATION_DURABILITY_UNCERTAIN",
          "candidate runtime matches the active binding but durable commit could not be confirmed; restart is required",
          error
        );
      }
      try {
        await this.bindings.abortStaged();
        await this.rollbackToPriorBinding(priorBinding);
      } catch (rollbackError) {
        this.bindingOutcome = priorBinding === null
          ? { state: "NO_CANONICAL_PROJECT_BOUND" }
          : {
              state: "BINDING_STALE",
              code: "BINDING_ACTIVATION_ROLLBACK_FAILED",
              message: rollbackError instanceof Error ? rollbackError.message : String(rollbackError)
            };
        throw new ProductAdapterError(
          "BINDING_ACTIVATION_ROLLBACK_FAILED",
          "candidate activation failed and the prior binding could not be revalidated",
          rollbackError
        );
      }
      throw new ProductAdapterError(
        "BINDING_ACTIVATION_FAILED",
        "candidate binding activation failed; the prior binding remains active",
        error
      );
    }
  }

  async listTasks(request?: ProductTaskPageRequest): Promise<ProductTasksListView> {
    this.requireBinding();
    const candidate = request ?? {};
    if (candidate === null || typeof candidate !== "object" || Array.isArray(candidate)) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "task page request must be an object");
    }
    const unknown = Object.keys(candidate).filter((key) => key !== "filter" && key !== "cursor" && key !== "pageSize");
    if (unknown.length > 0) throw new ProductAdapterError("INVALID_ARGUMENT", `unknown task page request fields: ${unknown.join(", ")}`);
    const admittedFilter = assertTaskListFilter(candidate.filter);
    const page = assertProductPageRequest({
      ...(candidate.cursor === undefined ? {} : { cursor: candidate.cursor }),
      ...(candidate.pageSize === undefined ? {} : { pageSize: candidate.pageSize })
    });
    const response = await this.supervisor.request("TaskService.v1.listTasks", {
      filter: { ...admittedFilter, ...(page.cursor === undefined ? {} : { cursor: page.cursor }) },
      page_size: page.pageSize
    });
    return adaptTaskList(response);
  }

  async getTask(taskId: string): Promise<ProductTaskView> {
    this.requireBinding();
    assertCanonicalId(taskId, "taskId");
    const response = await this.supervisor.request("TaskService.v1.getTask", { task_id: taskId });
    return adaptTask(response);
  }

  async retryResearchBacktest(taskId: string): Promise<ProductTaskView> {
    const refs = this.requireBinding();
    assertCanonicalId(taskId, "taskId");
    const current = await this.getTask(taskId);
    if (current.projectId !== refs.projectId || current.operationId !== PRODUCT_RESEARCH_BACKTEST_OPERATION) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "Task is not the current project's Product research Backtest");
    }
    if (current.state !== "FAILED" && current.state !== "PARTIAL") {
      throw new ProductAdapterError("CONFLICT", "Product research Backtest is not in a retryable terminal state");
    }
    if (
      current.attempt.attemptId === null
      || current.attempt.state !== "FAILED"
      || current.attempt.errorCategory === null
      || !RETRYABLE_PRODUCT_TASK_CATEGORIES.has(current.attempt.errorCategory)
    ) {
      throw new ProductAdapterError("CONFLICT", "persisted Product research Backtest failure is not retry-admitted");
    }
    const response = await this.supervisor.request("TaskService.v1.retryTask", {
      task_id: current.taskId,
      failed_attempt_id: current.attempt.attemptId,
      expected_state_version: current.stateVersion
    });
    const retried = adaptTask(response);
    if (
      retried.taskId !== current.taskId
      || retried.projectId !== current.projectId
      || retried.operationId !== current.operationId
      || retried.runId !== current.runId
      || retried.attempt.ordinal !== current.attempt.ordinal + 1
      || retried.attempt.attemptId === null
      || retried.attempt.attemptId === current.attempt.attemptId
      || !["QUEUED", "RUNNING", "SUCCEEDED"].includes(retried.state)
    ) {
      throw new ProductAdapterError("PRODUCT_READ_MODEL_INVALID", "retry response does not preserve immutable Product Backtest identity");
    }
    return retried;
  }

  async getTaskEvents(afterSequence: number, limit: number): Promise<ProductTaskEventsView> {
    this.requireBinding();
    if (!Number.isInteger(afterSequence) || afterSequence < 0) throw new ProductAdapterError("INVALID_ARGUMENT", "afterSequence must be a non-negative integer");
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw new ProductAdapterError("INVALID_ARGUMENT", "limit must be an integer in [1, 500]");
    const response = await this.supervisor.request("TaskService.v1.getEvents", { after_sequence: afterSequence, limit });
    return adaptTaskEvents(response);
  }

  async getResult(resultId: string): Promise<ProductResultView> {
    this.requireBinding();
    assertCanonicalId(resultId, "resultId");
    const response = await this.supervisor.request("ResultService.v1.getResult", { result_id: resultId, section: "summary", page: {} });
    return adaptResult(response);
  }

  async getArtifactDescriptor(artifactId: string): Promise<ArtifactDescriptorView> {
    this.requireBinding();
    assertCanonicalId(artifactId, "artifactId");
    const response = await this.supervisor.request("ArtifactService.v1.getArtifactDescriptor", { artifact_id: artifactId });
    const body = response as { read_model?: unknown };
    return adaptArtifactDescriptor(body.read_model);
  }

  async openArtifactStream(artifactId: string): Promise<ArtifactStreamTicketView> {
    this.requireBinding();
    assertCanonicalId(artifactId, "artifactId");
    const response = await this.supervisor.request("ArtifactService.v1.openArtifactStream", { artifact_id: artifactId });
    return adaptStreamTicket(response);
  }

  async readArtifactBytes(artifactId: string): Promise<ArtifactStreamBytesView> {
    const descriptor = await this.getArtifactDescriptor(artifactId);
    const ticket = await this.openArtifactStream(artifactId);
    if (ticket.artifactId !== descriptor.artifactId) {
      throw new ProductAdapterError(
        "PRODUCT_READ_MODEL_INVALID",
        "artifact stream ticket does not match the verified descriptor"
      );
    }
    const consumed = await this.supervisor.consumeArtifactStream({
      ticketId: ticket.ticketId,
      artifactId: descriptor.artifactId,
      expectedSha256: descriptor.sha256,
      expectedByteSize: descriptor.byteSize
    });
    if (
      consumed.artifactId !== descriptor.artifactId
      || consumed.sha256 !== descriptor.sha256
      || consumed.byteSize !== descriptor.byteSize
    ) {
      throw new ProductAdapterError(
        "PRODUCT_READ_MODEL_INVALID",
        "consumed artifact bytes do not match the verified descriptor"
      );
    }
    return Object.freeze({
      artifactId: consumed.artifactId,
      sha256: consumed.sha256,
      byteSize: consumed.byteSize,
      bytes: Uint8Array.from(consumed.bytes)
    });
  }

  async exportArtifact(request: ProductArtifactExportIntent): Promise<ProductArtifactExportOutcomeView> {
    const refs = this.requireBinding();
    if (this.artifactExports === null) {
      throw new ProductAdapterError("ARTIFACT_EXPORT_NOT_AVAILABLE", "Artifact 导出尚未绑定原生保存能力");
    }
    assertArtifactExportIntent(request);
    const descriptor = await this.getArtifactDescriptor(request.artifactId);
    const selection = await this.artifactExports.chooseDestination(request.suggestedName);
    if (selection === null) return Object.freeze({ state: "NOT_RUN" });

    const idempotencyKey = `v3-desktop:${uuidV4()}`;
    let accepted: { taskId: string; runId: string } | null = null;
    try {
      accepted = adaptArtifactExportAccepted(await this.supervisor.request(
        "ArtifactService.v1.exportArtifact",
        {
          artifact_ids: [descriptor.artifactId],
          export_profile_id: "LIGHT_REVIEW",
          destination_token: selection.capabilityToken,
          idempotency_key: idempotencyKey
        },
        { idempotencyKey, timeoutMs: 30_000 }
      ));
      const ticket = await this.openArtifactStream(descriptor.artifactId);
      if (ticket.artifactId !== descriptor.artifactId) {
        throw new ProductAdapterError(
          "PRODUCT_READ_MODEL_INVALID",
          "artifact export stream ticket does not match the verified descriptor"
        );
      }
      const receipt = await this.artifactExports.writeDestination(
        {
          capabilityToken: selection.capabilityToken,
          artifactId: descriptor.artifactId,
          expectedSha256: descriptor.sha256,
          expectedByteSize: descriptor.byteSize
        },
        (sink) => this.supervisor.streamArtifactToSink({
          ticketId: ticket.ticketId,
          artifactId: descriptor.artifactId,
          expectedSha256: descriptor.sha256,
          expectedByteSize: descriptor.byteSize
        }, sink)
      );
      const finalized = await this.supervisor.artifactExportControl({
        kind: "artifactExport.complete",
        protocol_version: "v3.artifact-export/1.0.0",
        project_id: refs.projectId,
        project_context_revision_id: refs.projectContextRevisionId,
        task_id: accepted.taskId,
        destination_token: receipt.destinationToken,
        display_name: receipt.displayName,
        artifact_id: receipt.artifactId,
        sha256: receipt.sha256,
        byte_size: receipt.byteSize,
        completed_at: receipt.completedAt
      });
      if (
        finalized.kind !== "artifactExport.completed"
        || finalized.task_id !== accepted.taskId
        || typeof finalized.manifest_artifact_id !== "string"
        || !ARTIFACT_ID_PATTERN.test(finalized.manifest_artifact_id)
        || Object.keys(finalized).sort().join(",") !== "kind,manifest_artifact_id,task_id"
      ) {
        throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "artifact export completion receipt is invalid");
      }
      return Object.freeze({
        state: "COMPLETED",
        taskId: accepted.taskId,
        runId: accepted.runId,
        artifactId: receipt.artifactId,
        manifestArtifactId: finalized.manifest_artifact_id,
        displayName: receipt.displayName,
        sha256: receipt.sha256,
        byteSize: receipt.byteSize,
        completedAt: receipt.completedAt
      });
    } catch (error) {
      this.artifactExports.discardDestination(selection.capabilityToken);
      if (accepted !== null) {
        await this.supervisor.artifactExportControl({
          kind: "artifactExport.fail",
          protocol_version: "v3.artifact-export/1.0.0",
          project_id: refs.projectId,
          project_context_revision_id: refs.projectContextRevisionId,
          task_id: accepted.taskId,
          destination_token: selection.capabilityToken,
          reason_code: exportFailureReason(error)
        }).catch(() => undefined);
      }
      throw error;
    }
  }

  /**
   * Preserve the frozen legacy Backtest DTO without claiming it is executable.
   * Normal V1.1 product composition advertises this service as UNAVAILABLE and
   * uses the additive ProductEntry research-backtest path instead.
   */
  async submitExistingBacktestRunSpec(runSpecId: string): Promise<BacktestSubmitOutcomeView> {
    this.requireBinding();
    const capability = this.supervisor.capabilities.find(
      (item) => item.code === "BacktestService"
    );
    if (capability?.truth_state !== "FORMAL") {
      const reason = capability?.reason_code ?? "FORMAL_EXECUTION_CONTRACT_NOT_CLOSED";
      throw new ProductAdapterError(
        "CAPABILITY_UNAVAILABLE",
        `BacktestService is unavailable: ${reason}`
      );
    }
    if (typeof runSpecId !== "string" || !RUN_SPEC_ID_PATTERN.test(runSpecId)) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "runSpecId must be a canonical btrs_sha256_ identifier");
    }
    const existing = this.inflightSubmit.get(runSpecId);
    if (existing !== undefined) return existing;
    const idempotencyKey = `v3-desktop:${uuidV4()}`;
    const requestPromise = (async (): Promise<BacktestSubmitOutcomeView> => {
      const response = await this.supervisor.request(
        "BacktestService.v1.submitBacktest",
        {
          run_spec_id: runSpecId,
          execution_adapter_version_id: ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
          idempotency_key: idempotencyKey
        },
        { idempotencyKey, timeoutMs: 120_000 }
      );
      return adaptBacktestSubmit(response, idempotencyKey);
    })().finally(() => {
      this.inflightSubmit.delete(runSpecId);
    });
    this.inflightSubmit.set(runSpecId, requestPromise);
    return requestPromise;
  }

  // -- Product Entry ---------------------------------------------------------

  /**
   * Clean-start project creation through the projectless productEntry control
   * protocol. The backend mints every canonical identity; the renderer can
   * only supply bounded display intent. The idempotency key is main-owned.
   */
  async createProject(request: { displayName: string; notes?: string }): Promise<ProjectCreatedView> {
    const displayName = request.displayName.trim();
    if (displayName.length < 1 || displayName.length > 200) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "displayName must be 1..200 characters");
    }
    const notes = request.notes === undefined ? null : request.notes;
    if (notes !== null && (typeof notes !== "string" || notes.length > 2048)) {
      throw new ProductAdapterError("INVALID_ARGUMENT", "notes must be a bounded string");
    }
    return runCreateProjectIntent(
      this.createProjectIntents,
      { displayName, notes },
      (idempotencyKey) => this.supervisor.productEntryControl({
        kind: "productEntry.createProject",
        protocol_version: PRODUCT_ENTRY_PROTOCOL_VERSION,
        display_name: displayName,
        notes,
        idempotency_key: idempotencyKey
      }),
      (response) => {
        const record = response as Record<string, unknown>;
        const projectId = typeof record.project_id === "string" ? record.project_id : "";
        const revisionId = typeof record.project_context_revision_id === "string" ? record.project_context_revision_id : "";
        if (!/^prj_[0-9A-HJKMNP-TV-Z]{26}$/.test(projectId) || !/^pcr_[0-9A-HJKMNP-TV-Z]{26}$/.test(revisionId)) {
          throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "backend did not return canonical project identities");
        }
        return Object.freeze({
          projectId,
          projectContextRevisionId: revisionId,
          displayName,
          createdAt: typeof record.created_at === "string" ? record.created_at : ""
        });
      },
    );
  }

  /** Durable project discovery (works before any project is bound). */
  async listProjects(request?: ProductPageRequest): Promise<ProjectsListView> {
    const page = assertProductPageRequest(request);
    const afterProjectId = page.cursor === undefined ? null : decodeProjectCursor(page.cursor);
    const response = await this.supervisor.productEntryControl({
      kind: "productEntry.listProjects",
      protocol_version: PRODUCT_ENTRY_PROTOCOL_VERSION,
      limit: page.pageSize,
      after_project_id: afterProjectId
    });
    const record = response as { projects?: unknown; has_more?: unknown };
    const projects = Array.isArray(record.projects)
      ? record.projects.map((item) => {
          const row = item as Record<string, unknown>;
          const projectId = row.project_id;
          const revisionId = row.project_context_revision_id;
          const displayName = row.display_name;
          const createdAt = row.created_at;
          if (typeof projectId !== "string" || !PROJECT_ID_PATTERN.test(projectId)) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project page returned an invalid project identity");
          if (typeof revisionId !== "string" || !PROJECT_CONTEXT_REVISION_PATTERN.test(revisionId)) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project page returned an invalid context revision identity");
          if (typeof displayName !== "string" || displayName.length < 1 || displayName.length > 200) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project page returned an invalid display name");
          if (typeof createdAt !== "string" || !createdAt.endsWith("Z") || Number.isNaN(Date.parse(createdAt))) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "project page returned an invalid created_at");
          return { projectId, projectContextRevisionId: revisionId, displayName, createdAt };
        })
      : [];
    const hasMore = record.has_more === true;
    const nextProjectId = hasMore ? projects.at(-1)?.projectId ?? null : null;
    const nextCursor = nextProjectId === null
      ? null
      : encodeProductCursor({ v: PRODUCT_CURSOR_VERSION, owner: "projects", sort: PROJECT_CURSOR_SORT, after: nextProjectId });
    if (hasMore && nextCursor === null) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "non-terminal project page did not provide a usable cursor row");
    return Object.freeze({ projects, hasMore, nextCursor });
  }

  /** Durable run-spec discovery with actual-artifact verification. */
  async listBacktestRunSpecs(request?: ProductPageRequest): Promise<RunSpecsListView> {
    const refs = this.requireBinding();
    const pageRequest = assertProductPageRequest(request);
    const afterArtifactId = pageRequest.cursor === undefined
      ? null
      : decodeRunSpecCursor(pageRequest.cursor, refs);
    const response = await this.supervisor.request("ProductEntryService.v1.listBacktestRunSpecs", {
      page: afterArtifactId === null
        ? { limit: pageRequest.pageSize }
        : { limit: pageRequest.pageSize, after_artifact_id: afterArtifactId }
    });
    const page = adaptRunSpecPage(response, new Set<string>(), afterArtifactId);
    const nextCursor = page.nextAfterArtifactId === null
      ? null
      : encodeProductCursor({
          v: PRODUCT_CURSOR_VERSION,
          owner: "run_specs",
          sort: RUN_SPEC_CURSOR_SORT,
          projectId: refs.projectId,
          projectContextRevisionId: refs.projectContextRevisionId,
          after: page.nextAfterArtifactId,
        });
    return Object.freeze({ specs: page.specs, hasMore: page.hasMore, nextCursor });
  }

  /**
   * Target-canonical-authority reuse. The Electron main process owns the native
   * directory chooser and reads the actual package bytes; the renderer never
   * sees a filesystem path. Returns null when the user cancels the chooser.
   * Every byte/hash/identity is re-verified by the backend before anything is
   * registered - the declared manifest alone is never trusted and cannot
   * establish the target's first source authority.
   */
  async importResearchPackage(): Promise<ImportResearchPackageOutcomeView | null> {
    this.requireBinding();
    const directory = await this.chooseResearchPackage();
    if (directory === null) return null;
    const { manifest, files } = await readResearchPackageDirectory(directory);
    const response = await this.supervisor.request(
      "ProductEntryService.v1.importResearchPackage",
      { manifest, files, idempotency_key: `v3-desktop:${uuidV4()}` },
      { timeoutMs: 120_000 }
    );
    return adaptImportResearchPackageOutcome(response);
  }

  /** Native selection metadata only; the path and open handle remain in main. */
  async chooseLocalDataSource(): Promise<LocalDataSourceSelectionView | null> {
    this.requireBinding();
    if (this.localDataSources === null) {
      throw new ProductAdapterError("LOCAL_DATA_IMPORT_NOT_AVAILABLE", "本地数据导入尚未绑定原生文件能力");
    }
    return this.localDataSources.chooseSource();
  }

  /** Publish raw bytes in backend ownership before the durable import Task. */
  async importLocalDataset(request: ProductLocalDataImportIntent): Promise<ProductLocalDataImportOutcomeView> {
    const refs = this.requireBinding();
    if (this.localDataSources === null) {
      throw new ProductAdapterError("LOCAL_DATA_IMPORT_NOT_AVAILABLE", "本地数据导入尚未绑定原生文件能力");
    }
    assertLocalDataImportIntent(request);
    const source = await this.localDataSources.transferSource(
      {
        capabilityToken: request.capabilityToken,
        projectId: refs.projectId,
        projectContextRevisionId: refs.projectContextRevisionId
      },
      (frame, timeoutMs) => this.supervisor.localDataControl(frame as Record<string, unknown>, timeoutMs)
    );
    const idempotencyKey = `v3-desktop:${uuidV4()}`;
    const response = await this.supervisor.request(
      "ProductEntryService.v1.importLocalDataset",
      {
        idempotency_key: idempotencyKey,
        source: {
          artifact_id: source.artifactId,
          sha256: source.sha256,
          byte_size: source.byteSize,
          media_type: source.mediaType,
          display_name: source.displayName,
          volume_unit: request.volumeUnit,
          amount_unit: request.amountUnit,
          timezone: request.timezone,
          adjustment: request.adjustment
        }
      },
      {
        contractVersion: "1.1.0",
        expectedApiVersion: "1.1",
        idempotencyKey,
        timeoutMs: 30_000
      }
    );
    return adaptLocalDataImportOutcome(response);
  }

  /**
   * Product-connected research entry. Provider identity is fixed by the main
   * process; the renderer can submit only a bounded symbol/date intent.
   */
  private requestResearchOutcome(
    request: ProductResearchSubmitIntent,
    key: string,
    idempotencyKey: string,
  ): Promise<ProductResearchSubmitOutcomeView> {
    return this.supervisor.request(
      "ProductEntryService.v1.submitResearch",
      researchOperationPayload(request, idempotencyKey),
      { idempotencyKey, timeoutMs: 120_000 }
    ).then((response) => adaptResearchSubmit(response, idempotencyKey)).finally(() => {
      this.inflightResearch.delete(key);
    });
  }

  async submitResearch(request: ProductResearchSubmitIntent): Promise<ProductResearchSubmitOutcomeView> {
    this.requireBinding();
    assertResearchIntent(request);
    const key = `${request.symbol}:${request.startDate}:${request.endDate}`;
    const existing = this.inflightResearch.get(key);
    if (existing !== undefined) return existing;
    const idempotencyKey = `v3-desktop:${uuidV4()}`;
    const requestPromise = this.requestResearchOutcome(request, key, idempotencyKey);
    this.inflightResearch.set(key, requestPromise);
    return requestPromise;
  }

  async submitFactorStudy(request: ProductFactorStudyIntent): Promise<ProductFactorStudyOutcomeView> {
    this.requireBinding();
    assertFactorStudyIntent(request);
    const key = createHash("sha256")
      .update(request.formulaSource, "utf8")
      .update("\0", "utf8")
      .update(request.analysisOutputName, "utf8")
      .digest("hex");
    const existing = this.inflightFactor.get(key);
    if (existing !== undefined) return existing;
    const idempotencyKey = `v3-desktop:${uuidV4()}`;
    const pending = this.supervisor.request(
      "ProductEntryService.v1.submitFactorStudy",
      {
        idempotency_key: idempotencyKey,
        formula_source: request.formulaSource,
        analysis_output_name: request.analysisOutputName
      },
      {
        contractVersion: "1.1.0",
        expectedApiVersion: "1.1",
        idempotencyKey,
        timeoutMs: 30_000
      }
    ).then(adaptFactorStudyOutcome).finally(() => this.inflightFactor.delete(key));
    this.inflightFactor.set(key, pending);
    return pending;
  }

  async publishResearchStrategy(request: ProductResearchStrategyIntent): Promise<ProductResearchStrategyOutcomeView> {
    this.requireBinding();
    assertResearchStrategyIntent(request);
    const home = await this.getProjectHome();
    if (home.dataState !== "AVAILABLE" || home.data === null || home.factorState !== "AVAILABLE" || home.factor === null) {
      throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "Strategy publication requires current available Data and Factor summaries");
    }
    if (!home.strategyAuthoringProfile.positionSizingOptions.includes(request.positionSizing)
      || request.maxPositions < home.strategyAuthoringProfile.maxPositionsMin
      || request.maxPositions > home.strategyAuthoringProfile.maxPositionsMax
      || !home.strategyAuthoringProfile.assumptionProfiles.some(
        (item) => item.assumptionProfileId === request.assumptionProfileId
      )) {
      throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "Strategy intent is outside the current backend authoring profile");
    }
    const booleanFactorIds = new Set(
      home.factor.outputs
        .filter((output) => output.outputType === "BOOLEAN_SERIES")
        .map((output) => output.factorDefinitionVersionId)
    );
    if (!booleanFactorIds.has(request.entrySignalFactorVersionId)
      || !booleanFactorIds.has(request.exitSignalFactorVersionId)) {
      throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "Strategy signals must reference current BOOLEAN Factor outputs");
    }
    const key = createHash("sha256")
      .update(JSON.stringify({
        projectContextRevisionId: home.projectContextRevisionId,
        universeVersionId: home.data.universeVersionId,
        request
      }), "utf8")
      .digest("hex");
    const existing = this.inflightStrategy.get(key);
    if (existing !== undefined) return existing;
    const idempotencyKey = `v3-desktop:${uuidV4()}`;
    const refs = home.strategyAuthoringProfile.profileRefs;
    const pending = this.supervisor.request(
      "ProductEntryService.v1.publishResearchStrategy",
      {
        idempotency_key: idempotencyKey,
        universe_version_id: home.data.universeVersionId,
        entry_signal_factor_version_id: request.entrySignalFactorVersionId,
        exit_signal_factor_version_id: request.exitSignalFactorVersionId,
        position_sizing: request.positionSizing,
        max_positions: request.maxPositions,
        gross_exposure: request.grossExposure,
        rebalance: home.strategyAuthoringProfile.rebalance,
        cost_policy_version_id: refs.costPolicyVersionId,
        execution_policy_version_id: refs.executionPolicyVersionId,
        risk_policy_set_version_id: refs.riskPolicySetVersionId,
        initial_cash: request.initialCash,
        assumption_profile_id: request.assumptionProfileId
      },
      {
        contractVersion: "1.1.0",
        expectedApiVersion: "1.1",
        idempotencyKey,
        timeoutMs: 30_000
      }
    ).then(adaptResearchStrategyOutcome).finally(() => this.inflightStrategy.delete(key));
    this.inflightStrategy.set(key, pending);
    return pending;
  }

  async previewResearchStrategy(request: ProductResearchStrategyIntent): Promise<ProductResearchStrategyPreviewView> {
    this.requireBinding();
    assertResearchStrategyIntent(request);
    const home = await this.getProjectHome();
    if (home.dataState !== "AVAILABLE" || home.data === null || home.factorState !== "AVAILABLE" || home.factor === null) {
      throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "Strategy preview requires current available Data and Factor summaries");
    }
    if (!home.strategyAuthoringProfile.positionSizingOptions.includes(request.positionSizing)
      || request.maxPositions < home.strategyAuthoringProfile.maxPositionsMin
      || request.maxPositions > home.strategyAuthoringProfile.maxPositionsMax
      || !home.strategyAuthoringProfile.assumptionProfiles.some(
        (item) => item.assumptionProfileId === request.assumptionProfileId
      )) {
      throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "Strategy preview intent is outside the current backend authoring profile");
    }
    const booleanFactorIds = new Set(
      home.factor.outputs
        .filter((output) => output.outputType === "BOOLEAN_SERIES")
        .map((output) => output.factorDefinitionVersionId)
    );
    if (!booleanFactorIds.has(request.entrySignalFactorVersionId)
      || !booleanFactorIds.has(request.exitSignalFactorVersionId)) {
      throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "Strategy preview signals must reference current BOOLEAN Factor outputs");
    }
    const refs = home.strategyAuthoringProfile.profileRefs;
    const response = await this.supervisor.request(
      "ProductEntryService.v1.previewResearchStrategy",
      {
        universe_version_id: home.data.universeVersionId,
        entry_signal_factor_version_id: request.entrySignalFactorVersionId,
        exit_signal_factor_version_id: request.exitSignalFactorVersionId,
        position_sizing: request.positionSizing,
        max_positions: request.maxPositions,
        gross_exposure: request.grossExposure,
        rebalance: home.strategyAuthoringProfile.rebalance,
        cost_policy_version_id: refs.costPolicyVersionId,
        execution_policy_version_id: refs.executionPolicyVersionId,
        risk_policy_set_version_id: refs.riskPolicySetVersionId,
        initial_cash: request.initialCash,
        assumption_profile_id: request.assumptionProfileId
      },
      { contractVersion: "1.1.0", expectedApiVersion: "1.1", timeoutMs: 30_000 }
    );
    const preview = adaptResearchStrategyPreview(response);
    if (
      preview.projectId !== home.projectId
      || preview.projectContextRevisionId !== home.projectContextRevisionId
      || preview.snapshotId !== home.data.snapshotId
      || preview.universeVersionId !== home.data.universeVersionId
      || preview.entrySignalFactorVersionId !== request.entrySignalFactorVersionId
      || preview.exitSignalFactorVersionId !== request.exitSignalFactorVersionId
      || preview.profileRefs.costPolicyVersionId !== refs.costPolicyVersionId
      || preview.profileRefs.executionPolicyVersionId !== refs.executionPolicyVersionId
      || preview.profileRefs.riskPolicySetVersionId !== refs.riskPolicySetVersionId
      || preview.profileRefs.assumptionProfileId !== request.assumptionProfileId
    ) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Strategy preview does not match current Home intent");
    }
    return preview;
  }

  async submitResearchBacktest(request: ProductResearchBacktestIntent): Promise<ProductResearchBacktestOutcomeView> {
    this.requireBinding();
    assertResearchBacktestIntent(request);
    const home = await this.getProjectHome();
    if (home.dataState !== "AVAILABLE" || home.data === null || home.strategyState !== "AVAILABLE" || home.strategy === null) {
      throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "Backtest requires the latest available Strategy and Data summaries");
    }
    const allowedStart = home.data.dateCoverageStart > home.backtestPolicyCoverage.coverageStart
      ? home.data.dateCoverageStart : home.backtestPolicyCoverage.coverageStart;
    const allowedEnd = home.backtestPolicyCoverage.coverageEnd !== null
      && home.backtestPolicyCoverage.coverageEnd < home.data.dateCoverageEnd
      ? home.backtestPolicyCoverage.coverageEnd : home.data.dateCoverageEnd;
    if (request.sessionStart < allowedStart || request.sessionEnd > allowedEnd) {
      throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "Backtest session range exceeds current Data or execution-policy coverage");
    }
    const preview = await this.previewResearchBacktest(request);
    if (preview.researchStrategySpecId !== home.strategy.researchStrategySpecId) {
      throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Backtest preflight no longer matches current Strategy");
    }
    const key = createHash("sha256")
      .update(JSON.stringify({ researchStrategySpecId: home.strategy.researchStrategySpecId, request }), "utf8")
      .digest("hex");
    const existing = this.inflightResearchBacktest.get(key);
    if (existing !== undefined) return existing;
    const idempotencyKey = `v3-desktop:${uuidV4()}`;
    const pending = this.supervisor.request(
      "ProductEntryService.v1.submitResearchBacktest",
      {
        idempotency_key: idempotencyKey,
        research_strategy_spec_id: home.strategy.researchStrategySpecId,
        session_start: request.sessionStart,
        session_end: request.sessionEnd,
        slippage_bps: request.slippageBps,
        daily_volume_participation_rate: request.dailyVolumeParticipationRate
      },
      {
        contractVersion: "1.1.0",
        expectedApiVersion: "1.1",
        idempotencyKey,
        timeoutMs: 30_000
      }
    ).then(adaptResearchBacktestOutcome).finally(() => this.inflightResearchBacktest.delete(key));
    this.inflightResearchBacktest.set(key, pending);
    return pending;
  }

  async previewResearchBacktest(request: ProductResearchBacktestIntent): Promise<ProductResearchBacktestPreviewView> {
    this.requireBinding();
    assertResearchBacktestIntent(request);
    const home = await this.getProjectHome();
    if (home.dataState !== "AVAILABLE" || home.data === null || home.strategyState !== "AVAILABLE" || home.strategy === null) {
      throw new ProductAdapterError("TRUTH_PRECONDITION_FAILED", "Backtest preflight requires current Data and Strategy owners");
    }
    const response = await this.supervisor.request(
      "ProductEntryService.v1.previewResearchBacktest",
      {
        research_strategy_spec_id: home.strategy.researchStrategySpecId,
        session_start: request.sessionStart,
        session_end: request.sessionEnd,
        slippage_bps: request.slippageBps,
        daily_volume_participation_rate: request.dailyVolumeParticipationRate
      },
      { contractVersion: "1.1.0", expectedApiVersion: "1.1", timeoutMs: 30_000 }
    );
    const preview = adaptResearchBacktestPreview(response);
    if (
      preview.projectId !== home.projectId
      || preview.projectContextRevisionId !== home.projectContextRevisionId
      || preview.researchStrategySpecId !== home.strategy.researchStrategySpecId
      || preview.snapshotId !== home.data.snapshotId
      || preview.universeVersionId !== home.data.universeVersionId
      || preview.sessionStart !== request.sessionStart
      || preview.sessionEnd !== request.sessionEnd
      || preview.slippageBps !== request.slippageBps
      || preview.dailyVolumeParticipationRate !== request.dailyVolumeParticipationRate
    ) throw new ProductAdapterError("PRODUCT_BRIDGE_ERROR", "Backtest preflight does not match current Home intent");
    return preview;
  }

  async dispose(): Promise<void> {
    await this.localDataSources?.close();
  }

  /**
   * Unified project-bound operation guard. Only an admitted PROJECT_BOUND
   * outcome allows product operations; a stale binding fails closed BEFORE
   * any supervisor request so old context can never serve product truth.
   */
  /**
   * restoreSession is the canonical start-up re-validation channel: before
   * the binding outcome has been adjudicated, persisted refs may drive the
   * validation read. Once adjudicated BINDING_STALE it fails closed like
   * every other product operation.
   */
  private requireBindingOrPendingRevalidation(): ProductBindingRefs {
    if (this.bindingOutcome.state === "BINDING_STALE") {
      throw new ProductAdapterError("BINDING_STALE", "canonical project binding requires reconnect and re-validation before product operations");
    }
    const admitted = this.admittedBindingRefs();
    if (admitted !== null) return admitted;
    const stored = this.storedBindingRefs();
    if (stored !== null) return stored;
    throw new ProductAdapterError("NO_CANONICAL_PROJECT_BOUND", "no canonical project is bound");
  }

  private requireBinding(): ProductBindingRefs {
    if (this.bindingOutcome.state === "BINDING_STALE") {
      throw new ProductAdapterError("BINDING_STALE", "canonical project binding requires reconnect and re-validation before product operations");
    }
    const refs = this.admittedBindingRefs();
    if (refs === null) throw new ProductAdapterError("NO_CANONICAL_PROJECT_BOUND", "no canonical project is bound");
    return refs;
  }

  private clearContext(): void {
    // Restore the unbound lifecycle: the supervisor refuses requests until a
    // real context is bound; accept/replay used null project identity.
    this.supervisor.clearProjectContext();
  }

  private assertExactBindingContext(refs: ProductBindingRefs, context: ProjectContextView): void {
    if (context.projectId !== refs.projectId || context.projectContextRevisionId !== refs.projectContextRevisionId) {
      throw new ProductAdapterError("BINDING_CONTEXT_MISMATCH", "candidate project context did not exactly match the requested binding");
    }
  }

  private async restoreAndVerify(refs: ProductBindingRefs): Promise<SessionRestoreWithCanonicalIdentity> {
    const response = await this.supervisor.request("ProjectSessionService.v1.restoreSession", { session_id: refs.sessionId });
    const restored = adaptSessionRestore(response);
    if (
      restored.canonicalSessionUuid !== refs.sessionId
      || restored.projectId !== refs.projectId
      || restored.projectContextRevisionId !== refs.projectContextRevisionId
    ) {
      throw new ProductAdapterError("BINDING_SESSION_MISMATCH", "restored session did not exactly match the candidate binding");
    }
    return restored;
  }

  private async rollbackToPriorBinding(prior: ProductBindingRefs | null): Promise<void> {
    await this.supervisor.shutdown();
    if (prior === null) {
      this.clearContext();
      await this.supervisor.start();
      this.bindingOutcome = { state: "NO_CANONICAL_PROJECT_BOUND" };
      return;
    }
    this.supervisor.setProjectContext({
      projectId: prior.projectId,
      projectContextRevisionId: prior.projectContextRevisionId,
      lastDurableProjectEventSequence: this.store.getProjectEventCursor(prior.projectId)
    });
    await this.supervisor.start();
    await this.restoreAndVerify(prior);
    this.bindingOutcome = { state: "PROJECT_BOUND" };
  }
}

/**
 * Read a V3 research package directory (closed layout): manifest.v3.json plus
 * the exact payload files the manifest declares. Actual bytes are hashed
 * here only for transport; the backend independently re-verifies every byte
 * against the manifest before registration. Unknown extra files are rejected.
 */
export async function readResearchPackageDirectory(
  directory: string
): Promise<{ manifest: Record<string, unknown>; files: ReadonlyArray<Record<string, unknown>> }> {
  const manifestPath = join(directory, PACKAGE_MANIFEST_FILENAME);
  const manifestBytes = await readFile(manifestPath).catch(() => {
    throw new ProductAdapterError("INVALID_ARGUMENT", `研究包缺少 ${PACKAGE_MANIFEST_FILENAME}`);
  });
  let manifest: Record<string, unknown>;
  try {
    manifest = JSON.parse(manifestBytes.toString("utf8")) as Record<string, unknown>;
  } catch {
    throw new ProductAdapterError("INVALID_ARGUMENT", "研究包 manifest 不是有效 JSON");
  }
  if (manifestBytes.byteLength > MAX_PACKAGE_MANIFEST_BYTES) {
    throw new ProductAdapterError("UNBOUNDED", "研究包 manifest 超出有界传输大小");
  }
  const declared = new Set<string>();
  const descriptorNames: unknown[] = [
    (manifest.run_spec_artifact as Record<string, unknown> | undefined)?.name,
    (manifest.execution_context_artifact as Record<string, unknown> | undefined)?.name
  ];
  for (const entry of Array.isArray(manifest.artifacts) ? (manifest.artifacts as unknown[]) : []) {
    descriptorNames.push((entry as Record<string, unknown> | null)?.name);
  }
  for (const name of descriptorNames) {
    if (typeof name !== "string") continue;
    if (!PACKAGE_PATH_PATTERN.test(name)) {
      throw new ProductAdapterError("INVALID_ARGUMENT", `研究包声明了非法的文件名: ${name}`);
    }
    declared.add(name);
  }
  declared.delete(PACKAGE_MANIFEST_FILENAME);
  if (declared.size === 0) {
    throw new ProductAdapterError("INVALID_ARGUMENT", "研究包 manifest 未声明任何 payload 文件");
  }
  if (declared.size > MAX_PACKAGE_FILE_COUNT) {
    throw new ProductAdapterError("UNBOUNDED", "研究包 payload 文件数超出上限");
  }
  const present = new Set((await readdir(directory)).filter((name) => name !== PACKAGE_MANIFEST_FILENAME));
  const missing = [...declared].filter((name) => !present.has(name));
  const extra = [...present].filter((name) => !declared.has(name));
  if (missing.length > 0 || extra.length > 0) {
    throw new ProductAdapterError(
      "INVALID_ARGUMENT",
      `研究包文件集合与 manifest 不一致 (缺失: ${missing.join(", ") || "无"}; 多余: ${extra.join(", ") || "无"})`
    );
  }
  const files: Record<string, unknown>[] = [];
  let total = 0;
  for (const name of [...declared].sort()) {
    const payload = await readFile(join(directory, name));
    if (payload.byteLength < 1 || payload.byteLength > MAX_PACKAGE_FILE_BYTES) {
      throw new ProductAdapterError("UNBOUNDED", `研究包文件大小越界: ${name}`);
    }
    total += payload.byteLength;
    if (total > MAX_PACKAGE_TOTAL_BYTES) {
      throw new ProductAdapterError("UNBOUNDED", "研究包总大小超出上限");
    }
    files.push({
      name,
      sha256: createHash("sha256").update(payload).digest("hex"),
      byte_size: payload.byteLength,
      payload_base64: payload.toString("base64")
    });
  }
  return { manifest, files };
}

export function errorToView(error: unknown): { code: string; message: string; retryable: boolean; operationId?: string } {
  // Structured mapping by duck typing: BackendRuntimeError / ProductAdapterError
  // and backend error envelopes all carry a string code; raw stack details
  // never cross the IPC boundary.
  const raw = error as { code?: unknown; message?: unknown; retryable?: unknown; operationId?: unknown };
  return {
    code: typeof raw?.code === "string" && raw.code.length > 0 ? raw.code : "PRODUCT_BRIDGE_ERROR",
    message: typeof raw?.message === "string" ? raw.message : String(error),
    retryable: raw?.retryable === true,
    ...(typeof raw?.operationId === "string" ? { operationId: raw.operationId } : {})
  };
}
