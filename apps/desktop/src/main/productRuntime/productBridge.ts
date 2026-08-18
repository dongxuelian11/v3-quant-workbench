import { randomBytes, createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import type {
  ArtifactDescriptorView,
  ArtifactStreamTicketView,
  BacktestSubmitOutcomeView,
  ImportResearchPackageOutcomeView,
  ProductBindingRefs,
  ProductCapabilityView,
  ProductResultView,
  ProductStatusView,
  ProductTaskEventsView,
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
  adaptResult,
  adaptSessionRestore,
  adaptStreamTicket,
  adaptTask,
  adaptTaskEvents,
  adaptTaskList,
  ProductAdapterError
} from "./adapters";
import type { ProductBindingStore } from "./bindingStore";
import {
  CreateProjectIntentStore,
  createProjectIntentPath,
  runCreateProjectIntent,
} from "./createProjectIntentStore";

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
const PROJECT_CONTEXT_REVISION_PATTERN = /^pcr_[0-9A-HJKMNP-TV-Z]{26}$/;
const CANONICAL_ID_PATTERN = /^[A-Za-z0-9_\-]{1,200}$/;
const PROJECT_LOCATOR_PREFIX = "v3:";
const PRODUCT_ENTRY_PROTOCOL_VERSION = "v3.product-entry/1.0.0";
const PACKAGE_MANIFEST_FILENAME = "manifest.v3.json";
const MAX_PACKAGE_FILE_BYTES = 262_144;
const MAX_PACKAGE_FILE_COUNT = 64;
const MAX_RUN_SPEC_AUTO_PAGES = 20;
const PACKAGE_PATH_PATTERN = /^[a-z0-9][a-z0-9._-]{0,63}$/;

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
  const row = rawEntry as Record<string, unknown>;
  const artifactId = String(row.artifact_id ?? "");
  if (!ARTIFACT_ID_PATTERN.test(artifactId)) {
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

export class ProductBridge {
  private inflightSubmit = new Map<string, Promise<BacktestSubmitOutcomeView>>();
  private bindingOutcome: ProductBindingOutcome = { state: "NO_CANONICAL_PROJECT_BOUND" };
  private readonly supervisor: BackendSupervisor;
  private readonly store: WorkspaceStore;
  private readonly bindings: ProductBindingStore;
  private readonly createProjectIntents: CreateProjectIntentStore;

  constructor(
    supervisor: BackendSupervisor,
    store: WorkspaceStore,
    bindings: ProductBindingStore,
    chooseResearchPackage: ResearchPackageChooser = async () => null,
    createProjectIntents: CreateProjectIntentStore = new CreateProjectIntentStore(
      createProjectIntentPath(dirname(bindings.path))
    )
  ) {
    this.supervisor = supervisor;
    this.store = store;
    this.bindings = bindings;
    this.chooseResearchPackage = chooseResearchPackage;
    this.createProjectIntents = createProjectIntents;
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
    return Object.freeze({
      backendState: this.supervisor.state,
      bindingState,
      boundProject: bound,
      capabilities: await this.getCapabilities()
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

  async restoreSession(): Promise<SessionRestoreView> {
    const refs = this.requireBindingOrPendingRevalidation();
    const response = await this.supervisor.request("ProjectSessionService.v1.restoreSession", { session_id: refs.sessionId });
    return adaptSessionRestore(response);
  }

  /**
   * Connect an existing canonical project through candidate refs supplied by
   * the product UI. The backend validates the refs (require_project + current
   * revision precondition); invalid refs are never persisted. On success the
   * backend is restarted under the bound context so durable event replay runs
   * with the correct lifecycle.
   */
  async connectExistingProject(candidate: { projectId: string; projectContextRevisionId: string }): Promise<ProjectContextView> {
    assertCanonicalId(candidate.projectId, "projectId");
    assertCanonicalId(candidate.projectContextRevisionId, "projectContextRevisionId");
    const sessionId = uuidV4();
    const priorContext = this.storedBindingRefs();
    const cursor = this.store.getProjectEventCursor(candidate.projectId);
    this.supervisor.setProjectContext({
      projectId: candidate.projectId,
      projectContextRevisionId: candidate.projectContextRevisionId,
      lastDurableProjectEventSequence: cursor
    });
    try {
      const response = await this.supervisor.request("ProjectSessionService.v1.openProject", {
        project_locator: `${PROJECT_LOCATOR_PREFIX}${candidate.projectId}`,
        session_id: sessionId
      });
      const context = adaptProjectContext(response);
      await this.bindings.persist({
        projectId: context.projectId,
        projectContextRevisionId: context.projectContextRevisionId,
        sessionId
      });
      this.bindingOutcome = { state: "PROJECT_BOUND" };
      // Rebind lifecycle: restart under the bound context so durable replay
      // covers the project history from the durable cursor.
      await this.restartUnderBinding();
      return await this.getProjectContext();
    } catch (error) {
      if (priorContext === null) {
        this.supervisor.setProjectContext({ projectId: "", projectContextRevisionId: "", lastDurableProjectEventSequence: 0 });
        this.clearContext();
      } else {
        this.supervisor.setProjectContext({
          projectId: priorContext.projectId,
          projectContextRevisionId: priorContext.projectContextRevisionId,
          lastDurableProjectEventSequence: this.store.getProjectEventCursor(priorContext.projectId)
        });
      }
      throw error;
    }
  }

  async listTasks(): Promise<readonly ProductTaskView[]> {
    this.requireBinding();
    const response = await this.supervisor.request("TaskService.v1.listTasks", { filter: {}, page_size: 50 });
    return adaptTaskList(response);
  }

  async getTask(taskId: string): Promise<ProductTaskView> {
    this.requireBinding();
    assertCanonicalId(taskId, "taskId");
    const response = await this.supervisor.request("TaskService.v1.getTask", { task_id: taskId });
    return adaptTask(response);
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

  /**
   * Execute an existing canonical BacktestRunSpec. The renderer supplies only
   * the canonical run spec identity; numeric observations/returns/weights are
   * not part of the frozen DTO and cannot be injected. The idempotency key is
   * main-process owned; concurrent duplicate clicks collapse into one request.
   * submitBacktest remains a bounded synchronous in-process executor: this
   * bridge never claims live progress, cancel, or resume.
   */
  async submitExistingBacktestRunSpec(runSpecId: string): Promise<BacktestSubmitOutcomeView> {
    this.requireBinding();
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
  async listProjects(): Promise<ProjectsListView> {
    const response = await this.supervisor.productEntryControl({
      kind: "productEntry.listProjects",
      protocol_version: PRODUCT_ENTRY_PROTOCOL_VERSION,
      limit: 50,
      after_project_id: null
    });
    const record = response as { projects?: unknown; has_more?: unknown };
    const projects = Array.isArray(record.projects)
      ? record.projects.map((item) => {
          const row = item as Record<string, unknown>;
          return {
            projectId: String(row.project_id ?? ""),
            projectContextRevisionId: String(row.project_context_revision_id ?? ""),
            displayName: String(row.display_name ?? ""),
            createdAt: String(row.created_at ?? "")
          };
        })
      : [];
    return Object.freeze({ projects, hasMore: record.has_more === true });
  }

  /** Durable run-spec discovery with actual-artifact verification. */
  async listBacktestRunSpecs(): Promise<RunSpecsListView> {
    this.requireBinding();
    const specs: RunSpecEntryView[] = [];
    const seenArtifacts = new Set<string>();
    let afterArtifactId: string | null = null;
    for (let pageNumber = 0; pageNumber < MAX_RUN_SPEC_AUTO_PAGES; pageNumber += 1) {
      const response = await this.supervisor.request("ProductEntryService.v1.listBacktestRunSpecs", {
        page: afterArtifactId === null
          ? { limit: 50 }
          : { limit: 50, after_artifact_id: afterArtifactId }
      });
      const page = adaptRunSpecPage(response, seenArtifacts, afterArtifactId);
      specs.push(...page.specs);
      if (!page.hasMore) {
        return Object.freeze({ specs, hasMore: false, nextAfterArtifactId: null });
      }
      afterArtifactId = page.nextAfterArtifactId;
    }
    return Object.freeze({
      specs,
      hasMore: true,
      nextAfterArtifactId: afterArtifactId,
    });
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
    const readModel = (response as { read_model?: Record<string, unknown> }).read_model ?? {};
    return Object.freeze({
      runSpecId: String(readModel.run_spec_id ?? ""),
      runSpecArtifactId: String(readModel.run_spec_artifact_id ?? ""),
      contextArtifactId: String(readModel.context_artifact_id ?? ""),
      alreadyImported: readModel.already_imported === true,
      sourceProjectId: String(readModel.source_project_id ?? ""),
      importedAt: String(readModel.imported_at ?? "")
    });
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

  private async restartUnderBinding(): Promise<void> {
    const refs = this.requireBinding();
    await this.supervisor.shutdown();
    this.supervisor.setProjectContext({
      projectId: refs.projectId,
      projectContextRevisionId: refs.projectContextRevisionId,
      lastDurableProjectEventSequence: this.store.getProjectEventCursor(refs.projectId)
    });
    await this.supervisor.start();
    // Session restore after rebind is best-effort: the session row exists
    // (openProject upserted it), but a restore failure must not mask the
    // successful canonical bind.
    try {
      await this.restoreSession();
    } catch {
      /* honest degradation: bound project stays valid; UI re-queries state */
    }
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
    if (total > 786_432) {
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
