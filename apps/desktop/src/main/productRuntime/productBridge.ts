import { randomBytes } from "node:crypto";
import type {
  ArtifactDescriptorView,
  ArtifactStreamTicketView,
  BacktestSubmitOutcomeView,
  ProductBindingRefs,
  ProductCapabilityView,
  ProductResultView,
  ProductStatusView,
  ProductTaskEventsView,
  ProductTaskView,
  ProjectContextView,
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
const CANONICAL_ID_PATTERN = /^[A-Za-z0-9_\-]{1,200}$/;
const PROJECT_LOCATOR_PREFIX = "v3:";

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

  constructor(supervisor: BackendSupervisor, store: WorkspaceStore, bindings: ProductBindingStore) {
    this.supervisor = supervisor;
    this.store = store;
    this.bindings = bindings;
  }

  /** Restore a persisted binding before backend launch; invalid refs are dropped. */
  async restorePersistedBinding(): Promise<ProductBindingRefs | null> {
    const persisted = await this.bindings.load();
    if (persisted === null) {
      this.bindingOutcome = { state: "NO_CANONICAL_PROJECT_BOUND" };
      return null;
    }
    return { projectId: persisted.projectId, projectContextRevisionId: persisted.projectContextRevisionId, sessionId: persisted.sessionId };
  }

  bindingRefs(): ProductBindingRefs | null {
    const persisted = this.bindings.current;
    if (persisted === null) return null;
    return { projectId: persisted.projectId, projectContextRevisionId: persisted.projectContextRevisionId, sessionId: persisted.sessionId };
  }

  recordBindingOutcome(outcome: ProductBindingOutcome): void {
    this.bindingOutcome = outcome;
  }

  async getProductStatus(): Promise<ProductStatusView> {
    const bound = this.bindingRefs();
    return Object.freeze({
      backendState: this.supervisor.state,
      bindingState: bound === null ? "NO_CANONICAL_PROJECT_BOUND" as const : "PROJECT_BOUND" as const,
      boundProject: bound,
      capabilities: await this.getCapabilities()
    });
  }

  async getCapabilities(): Promise<readonly ProductCapabilityView[]> {
    return adaptCapabilities(this.supervisor.capabilities);
  }

  async getBoundProject(): Promise<ProductBindingRefs | null> {
    return this.bindingRefs();
  }

  async getProjectContext(): Promise<ProjectContextView> {
    const response = await this.supervisor.request("ProjectSessionService.v1.getProjectContext", {});
    return adaptProjectContext(response);
  }

  async restoreSession(): Promise<SessionRestoreView> {
    const refs = this.requireBinding();
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
    const priorContext = this.bindingRefs();
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
    const response = await this.supervisor.request("TaskService.v1.listTasks", { filter: {}, page_size: 50 });
    return adaptTaskList(response);
  }

  async getTask(taskId: string): Promise<ProductTaskView> {
    assertCanonicalId(taskId, "taskId");
    const response = await this.supervisor.request("TaskService.v1.getTask", { task_id: taskId });
    return adaptTask(response);
  }

  async getTaskEvents(afterSequence: number, limit: number): Promise<ProductTaskEventsView> {
    if (!Number.isInteger(afterSequence) || afterSequence < 0) throw new ProductAdapterError("INVALID_ARGUMENT", "afterSequence must be a non-negative integer");
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw new ProductAdapterError("INVALID_ARGUMENT", "limit must be an integer in [1, 500]");
    const response = await this.supervisor.request("TaskService.v1.getEvents", { after_sequence: afterSequence, limit });
    return adaptTaskEvents(response);
  }

  async getResult(resultId: string): Promise<ProductResultView> {
    assertCanonicalId(resultId, "resultId");
    const response = await this.supervisor.request("ResultService.v1.getResult", { result_id: resultId, section: "summary", page: {} });
    return adaptResult(response);
  }

  async getArtifactDescriptor(artifactId: string): Promise<ArtifactDescriptorView> {
    assertCanonicalId(artifactId, "artifactId");
    const response = await this.supervisor.request("ArtifactService.v1.getArtifactDescriptor", { artifact_id: artifactId });
    const body = response as { read_model?: unknown };
    return adaptArtifactDescriptor(body.read_model);
  }

  async openArtifactStream(artifactId: string): Promise<ArtifactStreamTicketView> {
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

  private requireBinding(): ProductBindingRefs {
    const refs = this.bindingRefs();
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
