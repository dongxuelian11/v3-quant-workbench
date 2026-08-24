import { EventEmitter } from "node:events";
import { randomBytes } from "node:crypto";
import type { Writable } from "node:stream";
import { BackendCrashLoopError, BackendDisconnectedError, BackendRuntimeError, BackendTimeoutError } from "./errors";
import { CrashLoopGuard } from "./crashLoopGuard";
import { encodeFrame, FrameDecoder, TransportProtocolError } from "./framing";
import { contextBridgeSafe, createSupervisorAccept, validateBackendHello, validateEvent, validateReady } from "./protocol";
import { NodeBackendProcessFactory, sanitizedBackendEnvironment } from "./processFactory";
import type {
  BackendCapability,
  BackendHello,
  BackendProcess,
  BackendProcessFactory,
  CancelTaskInput,
  ConnectionState,
  DurableEventCursorPort,
  OpenArtifactStreamInput,
  RequestOptions,
  ResumeTaskInput,
  RetryTaskInput,
  RuntimeDiagnostic,
  RuntimeEvent,
  RuntimeResponseError,
  SpawnSpec,
  SupervisorConfig,
  SupervisorProjectContext
} from "./types";

const REPLAY_PAGE_LIMIT = 1000;
const DEFAULT_MAX_BUFFERED_EVENTS = 1000;
const DEFAULT_MAX_EVENT_SEQUENCE_GAP = 10_000;
const RECENT_EVENT_ID_CACHE_LIMIT = 2000;
const DEFAULT_REQUEST_TOMBSTONE_LIMIT = 2048;
const DEFAULT_REQUEST_TOMBSTONE_TTL_MS = 60_000;
const MAX_PENDING_CONTROL_REQUESTS = 32;
const CONTROL_TOMBSTONE_LIMIT = 256;
const CONTROL_TOMBSTONE_TTL_MS = 5 * 60_000;
const DEFAULT_MAX_BUFFERED_STDIN_BYTES = 4 * 1024 * 1024;
const DEFAULT_MAX_BUFFERED_STDIN_WRITES = 256;
const DEFAULT_MAX_STDERR_LINE_BYTES = 16 * 1024;
const DEFAULT_MAX_STDERR_BYTES = 256 * 1024;

/** Marker for a durable cursor commit failure inside event delivery. */
class DurableCursorCommitError extends Error {
  override readonly cause: unknown;
  constructor(message: string, cause: unknown) {
    super(message);
    this.name = "DurableCursorCommitError";
    this.cause = cause;
  }
}

/**
 * Marker for a replay page that claims delivery beyond the contiguous
 * cursor. This follows a delivery failure (the page's events were sent but
 * not all committed), so the runtime must reconnect and replay rather than
 * permanently reject the protocol.
 */
class ReplayContiguityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ReplayContiguityError";
  }
}

interface PendingRequest {
  readonly requestId: string;
  readonly generation: number;
  readonly resolve: (value: unknown) => void;
  readonly reject: (error: Error) => void;
  readonly timer: NodeJS.Timeout;
}

interface RequestTombstone {
  readonly generation: number;
  readonly ttlBoundaryAt: number;
}

type ControlRequestKind =
  | "runtime.health"
  | "runtime.prepareShutdown"
  | "runtime.commitShutdown"
  | "productEntry.createProject"
  | "productEntry.listProjects";

interface PendingControlRequest<T> {
  readonly kind: ControlRequestKind;
  readonly responseKinds: readonly string[];
  readonly controlRequestId: string;
  readonly generation: number;
  readonly wait: Deferred<T>;
  readonly timer: NodeJS.Timeout;
}

interface ControlTombstone {
  readonly kind: ControlRequestKind;
  readonly responseKinds: readonly string[];
  readonly generation: number;
  readonly ttlBoundaryAt: number;
}

interface Deferred<T> {
  readonly promise: Promise<T>;
  readonly resolve: (value: T | PromiseLike<T>) => void;
  readonly reject: (reason?: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}

function uuidV7(): string {
  const bytes = randomBytes(16);
  let timestamp = BigInt(Date.now());
  for (let index = 5; index >= 0; index -= 1) {
    bytes[index] = Number(timestamp & 0xffn);
    timestamp >>= 8n;
  }
  bytes[6] = (bytes[6]! & 0x0f) | 0x70;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function asRecord(value: unknown, name: string): Record<string, unknown> {
  if (value === null || Array.isArray(value) || typeof value !== "object") throw new TransportProtocolError(`${name} must be an object`);
  return value as Record<string, unknown>;
}

function positiveInteger(value: number | undefined, fallback: number, name: string): number {
  if (value === undefined) return fallback;
  if (!Number.isSafeInteger(value) || value < 1) throw new RangeError(`${name} must be a positive safe integer`);
  return value;
}

function boundedText(value: string, maximum = 2048): string {
  return value.length <= maximum ? value : `${value.slice(0, maximum)}…[TRUNCATED]`;
}

export class BackendSupervisor extends EventEmitter {
  private readonly processFactory: BackendProcessFactory;
  private readonly tokenFactory: () => Uint8Array;
  private readonly crashGuard: CrashLoopGuard;
  private readonly cursorPort: DurableEventCursorPort;
  private readonly maxBufferedEvents: number;
  private readonly maxEventSequenceGap: number;
  private readonly pending = new Map<string, PendingRequest>();
  private readonly tombstones = new Map<string, RequestTombstone>();
  private readonly pendingControls = new Map<string, PendingControlRequest<Readonly<Record<string, unknown>>>>();
  private readonly controlTombstones = new Map<string, ControlTombstone>();
  private readonly requestTombstoneLimit: number;
  private readonly requestTombstoneTtlMs: number;
  private readonly maxBufferedStdinBytes: number;
  private readonly maxBufferedStdinWrites: number;
  private readonly maxStderrLineBytes: number;
  private readonly maxStderrBytes: number;
  private readonly recentEventIds = new Map<string, true>();
  private readonly bufferedEvents = new Map<number, RuntimeEvent>();
  private deliveryChain: Promise<void> = Promise.resolve();
  private deliveryScheduled = false;
  private deliveryInFlight = 0;
  private process?: BackendProcess;
  private sessionGeneration = 0;
  private writeQueue: Buffer[] = [];
  private bufferedStdinBytes = 0;
  private writeBackpressured = false;
  private drainTarget?: Writable;
  private decoder = new FrameDecoder();
  private hello?: BackendHello;
  private ready?: Deferred<void>;
  private readyTimer?: NodeJS.Timeout;
  private restartTimer?: NodeJS.Timeout;
  private restartAttempt = 0;
  private projectContext?: SupervisorProjectContext;
  private replayFrozenWatermark: number | null = null;
  private lastReplayAfterSequence: number | null = null;
  private expectedExit = false;
  private protocolRejected = false;
  private stderrBuffer = Buffer.alloc(0);
  private stderrTotalBytes = 0;
  private stderrLineTruncated = false;
  private stderrLimitDiagnosticEmitted = false;
  private stateValue: ConnectionState = "STOPPED";
  private capabilitiesValue: readonly BackendCapability[] = Object.freeze([]);

  constructor(
    readonly config: SupervisorConfig,
    processFactory: BackendProcessFactory = new NodeBackendProcessFactory(),
    tokenFactory: () => Uint8Array = () => randomBytes(32)
  ) {
    super();
    this.processFactory = processFactory;
    this.tokenFactory = tokenFactory;
    this.projectContext = config.projectContext;
    this.cursorPort = config.cursorPort ?? { commit: async () => {} };
    this.maxBufferedEvents = config.maxBufferedEvents ?? DEFAULT_MAX_BUFFERED_EVENTS;
    this.maxEventSequenceGap = config.maxEventSequenceGap ?? DEFAULT_MAX_EVENT_SEQUENCE_GAP;
    this.requestTombstoneLimit = positiveInteger(config.requestTombstoneLimit, DEFAULT_REQUEST_TOMBSTONE_LIMIT, "requestTombstoneLimit");
    this.requestTombstoneTtlMs = positiveInteger(config.requestTombstoneTtlMs, DEFAULT_REQUEST_TOMBSTONE_TTL_MS, "requestTombstoneTtlMs");
    this.maxBufferedStdinBytes = positiveInteger(config.maxBufferedStdinBytes, DEFAULT_MAX_BUFFERED_STDIN_BYTES, "maxBufferedStdinBytes");
    this.maxBufferedStdinWrites = positiveInteger(config.maxBufferedStdinWrites, DEFAULT_MAX_BUFFERED_STDIN_WRITES, "maxBufferedStdinWrites");
    this.maxStderrLineBytes = positiveInteger(config.maxStderrLineBytes, DEFAULT_MAX_STDERR_LINE_BYTES, "maxStderrLineBytes");
    this.maxStderrBytes = positiveInteger(config.maxStderrBytes, DEFAULT_MAX_STDERR_BYTES, "maxStderrBytes");
    this.crashGuard = new CrashLoopGuard(config.crashLoopLimit ?? 5, config.crashLoopWindowMs ?? 60_000);
  }

  get state(): ConnectionState { return this.stateValue; }

  get backendPid(): number | null { return this.process?.pid ?? null; }

  /**
   * Bounded, path-free handshake evidence for packaged runtime probes.
   *
   * The hello frame is validated before it is stored, and the returned clone
   * contains no supervisor token or filesystem paths. Exposing this read-only
   * projection lets a packaged evidence driver prove the framed identity and
   * READY transition without adding a second transport or a product shortcut.
   */
  get handshake(): BackendHello | null {
    return this.hello === undefined ? null : structuredClone(this.hello);
  }

  get capabilities(): readonly BackendCapability[] { return structuredClone(this.capabilitiesValue); }

  /**
   * Product-bridge unbind seam: drop any bound project context so the next
   * launch handshakes with a null project identity (backend connected,
   * NO_CANONICAL_PROJECT_BOUND). Requests are refused until a real context is
   * bound again.
   */
  clearProjectContext(): void {
    this.projectContext = undefined;
  }

  setProjectContext(context: SupervisorProjectContext): void {
    if (context.lastDurableProjectEventSequence < 0 || !Number.isInteger(context.lastDurableProjectEventSequence)) {
      throw new RangeError("last durable project sequence must be a non-negative integer");
    }
    this.projectContext = { ...context };
  }

  async start(): Promise<void> {
    if (this.stateValue === "SHUTTING_DOWN" && this.process?.isAlive()) {
      throw this.backendExitNotConfirmed(this.process);
    }
    if (!["STOPPED", "DISCONNECTED"].includes(this.stateValue)) throw new Error(`cannot start backend from ${this.stateValue}`);
    this.expectedExit = false;
    this.protocolRejected = false;
    await this.launch();
  }

  async request(operationId: string, payload: Readonly<Record<string, unknown>>, options: RequestOptions = {}): Promise<unknown> {
    if (this.stateValue !== "READY") throw new BackendDisconnectedError(`canonical backend is not ready (${this.stateValue})`);
    const context = this.projectContext;
    if (!context) throw new BackendRuntimeError("project context is not bound", "PROJECT_CONTEXT_NOT_BOUND");
    for (const reserved of ["request_id", "project_id", "project_context_revision_id", "expected_api_version"]) {
      if (reserved in payload) throw new BackendRuntimeError(`renderer-controlled transport field rejected: ${reserved}`, "INVALID_ARGUMENT");
    }
    this.ensureRequestTombstoneCapacity();
    const requestId = uuidV7();
    const body = {
      request_id: requestId,
      project_id: context.projectId,
      project_context_revision_id: context.projectContextRevisionId,
      expected_api_version: "1.0",
      ...contextBridgeSafe(payload)
    };
    const envelope: Record<string, unknown> = {
      kind: "request",
      request_id: requestId,
      operation_id: operationId,
      contract_version: options.contractVersion ?? "1.0.0",
      project_id: context.projectId,
      project_context_revision_id: context.projectContextRevisionId,
      body
    };
    if (options.idempotencyKey !== undefined) envelope.idempotency_key = options.idempotencyKey;
    if (options.deadlineAt !== undefined) envelope.deadline_at = options.deadlineAt;
    const timeoutMs = options.timeoutMs ?? this.config.requestTimeoutMs ?? 30_000;
    const waiting = deferred<unknown>();
    const timer = setTimeout(() => {
      const pending = this.pending.get(requestId);
      if (!pending) return;
      this.pending.delete(requestId);
      this.rememberTombstone(requestId, pending.generation);
      waiting.reject(new BackendTimeoutError(`backend request timed out: ${operationId}`));
    }, timeoutMs);
    this.pending.set(requestId, {
      requestId,
      generation: this.sessionGeneration,
      resolve: waiting.resolve,
      reject: waiting.reject,
      timer
    });
    try {
      this.send(envelope);
    } catch (error) {
      clearTimeout(timer);
      const pending = this.pending.get(requestId);
      if (pending) {
        this.pending.delete(requestId);
        this.rememberTombstone(requestId, pending.generation);
        pending.reject(error instanceof Error ? error : new BackendDisconnectedError(String(error)));
      }
      // A synchronous send failure rejects the async request below, so the
      // internal waiting promise is otherwise left without an owner.  Keep
      // the caller-facing transport error while consuming that internal
      // rejection to avoid an unhandled rejection during queue overflow or
      // a failed writable.
      void waiting.promise.catch(() => undefined);
      throw error;
    }
    return waiting.promise;
  }

  cancelTask(input: CancelTaskInput): Promise<unknown> {
    return this.request("TaskService.v1.cancelTask", {
      task_id: input.taskId,
      expected_state_version: input.expectedStateVersion,
      reason: input.reason
    });
  }

  retryTask(input: RetryTaskInput): Promise<unknown> {
    return this.request("TaskService.v1.retryTask", {
      task_id: input.taskId,
      failed_attempt_id: input.failedAttemptId,
      expected_state_version: input.expectedStateVersion
    });
  }

  resumeTask(input: ResumeTaskInput): Promise<unknown> {
    return this.request("TaskService.v1.resumeTask", {
      task_id: input.taskId,
      checkpoint_artifact_id: input.checkpointArtifactId,
      expected_state_version: input.expectedStateVersion
    });
  }

  openArtifactStream(input: OpenArtifactStreamInput): Promise<unknown> {
    const payload: Record<string, unknown> = { artifact_id: input.artifactId };
    if (input.range !== undefined) payload.range = input.range;
    return this.request("ArtifactService.v1.openArtifactStream", payload);
  }

  async getHealth(timeoutMs = 5_000): Promise<Readonly<Record<string, unknown>>> {
    if (this.stateValue !== "READY") throw new BackendDisconnectedError();
    const message = await this.requestControl(
      "runtime.health",
      ["runtime.health"],
      { deadline_at: new Date(Date.now() + timeoutMs).toISOString() },
      timeoutMs,
      "backend health response timed out",
      true
    );
    const {
      control_request_id: _controlRequestId,
      runtime_generation: _runtimeGeneration,
      ...health
    } = message;
    return contextBridgeSafe(health);
  }

  /**
   * Projectless Product Entry bootstrap control frame (productEntry.*).
   * Works BEFORE any canonical project is bound: the whole point is creating
   * the first project. The frame payload is main-process owned; the closed
   * reply/error frames map onto the same structured error surface as ASL.
   */
  async productEntryControl(frame: Record<string, unknown>, timeoutMs = 30_000): Promise<Readonly<Record<string, unknown>>> {
    if (this.stateValue !== "READY") throw new BackendDisconnectedError();
    const kind = frame.kind;
    if (kind !== "productEntry.createProject" && kind !== "productEntry.listProjects") {
      throw new BackendRuntimeError("unknown Product Entry control kind", "INVALID_ARGUMENT");
    }
    const { kind: _kind, ...payload } = frame;
    const successKind = kind === "productEntry.createProject"
      ? "productEntry.projectCreated"
      : "productEntry.projectsListed";
    const message = await this.requestControl(
      kind,
      [successKind, "productEntry.error"],
      { ...payload, deadline_at: new Date(Date.now() + timeoutMs).toISOString() },
      timeoutMs,
      "product entry control timed out"
    );
    if (message.kind === "productEntry.error") {
      const code = typeof message.code === "string" && message.code.length > 0 ? message.code : "PRODUCT_ENTRY_ERROR";
      const text = typeof message.message === "string" ? message.message : "product entry control failed";
      throw new BackendRuntimeError(text, code);
    }
    const {
      control_request_id: _controlRequestId,
      runtime_generation: _runtimeGeneration,
      ...response
    } = message;
    return contextBridgeSafe(response);
  }

  async shutdown(deadlineMs = 10_000): Promise<void> {
    if (this.stateValue === "STOPPED") return;
    this.setState("SHUTTING_DOWN");
    this.expectedExit = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = undefined;
    if (!this.process) {
      const error = new BackendDisconnectedError("canonical backend shut down");
      this.ready?.reject(error);
      this.ready = undefined;
      this.sessionGeneration += 1;
      this.clearWriteQueue();
      this.rejectAll(error, false);
      this.tombstones.clear();
      this.setState("STOPPED");
      return;
    }
    const process = this.process;
    const deadlineAt = new Date(Date.now() + deadlineMs).toISOString();
    let gracefulCommitAcknowledged = false;
    try {
      await this.requestControl(
        "runtime.prepareShutdown",
        ["runtime.shutdownReady"],
        { deadline_at: deadlineAt },
        deadlineMs,
        "backend prepare shutdown timed out"
      );
      // prepareShutdown is the quiesce barrier: once acknowledged, no new
      // business work may start. Drain and durably ack every event accepted
      // before that barrier while the backend transport is still alive.
      await this.whenDeliveryIdle();
      await this.requestControl(
        "runtime.commitShutdown",
        ["runtime.shutdownCommitted"],
        { deadline_at: deadlineAt },
        deadlineMs,
        "backend commit shutdown timed out"
      );
      // The backend cannot emit any more events after shutdownCommitted:
      // drain accepted event deliveries (application emit, cursor commit,
      // ack) before terminating so no committed-but-unacked event is lost.
      await this.whenDeliveryIdle();
      gracefulCommitAcknowledged = true;
    } finally {
      try {
        await this.confirmBackendExit(process, deadlineMs, gracefulCommitAcknowledged);
      } catch (error) {
        this.clearWriteQueue();
        this.rejectAll(new BackendDisconnectedError("canonical backend shutdown is fenced pending confirmed process exit"), false);
        this.tombstones.clear();
        this.setState("SHUTTING_DOWN");
        throw error;
      }
      if (this.process === process) this.process = undefined;
      this.sessionGeneration += 1;
      this.clearWriteQueue();
      this.rejectAll(new BackendDisconnectedError("canonical backend shut down"), false);
      this.tombstones.clear();
      this.setState("STOPPED");
    }
  }

  private async confirmBackendExit(
    process: BackendProcess,
    deadlineMs: number,
    waitForNaturalExit: boolean
  ): Promise<void> {
    const waitWindowMs = Math.max(1, deadlineMs);
    if (!process.isAlive()) return;
    if (waitForNaturalExit && await process.waitForExit(Date.now() + waitWindowMs)) return;
    if (!process.isAlive()) return;
    process.terminate();
    if (await process.waitForExit(Date.now() + waitWindowMs)) return;
    if (!process.isAlive()) return;
    process.kill();
    if (await process.waitForExit(Date.now() + waitWindowMs)) return;
    if (!process.isAlive()) return;
    throw this.backendExitNotConfirmed(process);
  }

  private backendExitNotConfirmed(process: BackendProcess): BackendRuntimeError {
    return new BackendRuntimeError(
      "canonical backend exit could not be confirmed; replacement generation is fenced",
      "BACKEND_EXIT_NOT_CONFIRMED",
      false,
      { pid: process.pid ?? null }
    );
  }

  private requestControl(
    kind: ControlRequestKind,
    responseKinds: readonly string[],
    payload: Readonly<Record<string, unknown>>,
    timeoutMs: number,
    timeoutMessage: string,
    coalesce = false
  ): Promise<Readonly<Record<string, unknown>>> {
    const generation = this.sessionGeneration;
    if (coalesce) {
      const existing = [...this.pendingControls.values()].find(
        (pending) => pending.kind === kind && pending.generation === generation
      );
      if (existing) return existing.wait.promise;
    }
    for (const reserved of ["kind", "control_request_id", "runtime_generation"]) {
      if (reserved in payload) {
        throw new BackendRuntimeError(`caller-controlled control field rejected: ${reserved}`, "INVALID_ARGUMENT");
      }
    }
    this.ensureControlCapacity();
    const controlRequestId = uuidV7();
    const wait = deferred<Readonly<Record<string, unknown>>>();
    let pending!: PendingControlRequest<Readonly<Record<string, unknown>>>;
    const timer = setTimeout(() => {
      if (this.pendingControls.get(controlRequestId) !== pending) return;
      this.pendingControls.delete(controlRequestId);
      this.rememberControlTombstone(controlRequestId, pending);
      wait.reject(new BackendTimeoutError(timeoutMessage));
    }, timeoutMs);
    pending = { kind, responseKinds: Object.freeze([...responseKinds]), controlRequestId, generation, wait, timer };
    this.pendingControls.set(controlRequestId, pending);
    try {
      this.send({
        kind,
        ...payload,
        control_request_id: controlRequestId,
        runtime_generation: generation
      });
    } catch (error) {
      clearTimeout(timer);
      if (this.pendingControls.get(controlRequestId) === pending) this.pendingControls.delete(controlRequestId);
      throw error;
    }
    return wait.promise;
  }

  stopNow(): void {
    this.expectedExit = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = undefined;
    const process = this.process;
    this.process = undefined;
    this.sessionGeneration += 1;
    this.clearWriteQueue();
    process?.terminate();
    this.rejectAll(new BackendDisconnectedError("canonical backend stopped"), false);
    this.tombstones.clear();
    this.setState("STOPPED");
  }

  private async launch(): Promise<void> {
    const generation = ++this.sessionGeneration;
    this.tombstones.clear();
    this.controlTombstones.clear();
    this.decoder = new FrameDecoder();
    this.clearWriteQueue();
    this.stderrBuffer = Buffer.alloc(0);
    this.stderrTotalBytes = 0;
    this.stderrLineTruncated = false;
    this.stderrLimitDiagnosticEmitted = false;
    this.hello = undefined;
    this.replayFrozenWatermark = null;
    this.lastReplayAfterSequence = null;
    this.bufferedEvents.clear();
    this.deliveryChain = Promise.resolve();
    this.deliveryScheduled = false;
    this.deliveryInFlight = 0;
    this.ready = deferred<void>();
    this.setState("STARTING");
    const token = this.tokenFactory();
    if (token.byteLength !== 32) throw new Error("supervisor token factory must return 256 bits");
    const backendModule = this.config.backendModule ?? "v3_backend.runtime.bootstrap";
    const acceptanceArgument = this.config.productReleaseAcceptanceProvider === undefined
      ? []
      : [`--product-release-acceptance-provider=${this.config.productReleaseAcceptanceProvider}`];
    const spec: SpawnSpec = {
      executable: this.config.pythonExecutable,
      args: ["-m", backendModule, "--transport=stdio-framed-v1", ...acceptanceArgument],
      cwd: this.config.backendWorkingDirectory,
      env: sanitizedBackendEnvironment(process.env, this.config.backendRuntimeRoot, this.config.backendResourceRoot)
    };
    this.process = this.processFactory.spawn(spec, token);
    const launched = this.process;
    launched.stdout.on("data", (chunk: Buffer) => this.onStdout(launched, generation, chunk, token));
    launched.stderr.on("data", (chunk: Buffer) => this.onStderr(launched, generation, chunk));
    launched.onExit((code, signal) => this.onExit(launched, generation, code, signal));
    this.readyTimer = setTimeout(() => this.rejectProtocol(new BackendTimeoutError("backend.hello/ready handshake timed out")), this.config.handshakeTimeoutMs ?? 10_000);
    return this.ready.promise;
  }

  private onStdout(process: BackendProcess, generation: number, chunk: Uint8Array, token: Uint8Array): void {
    if (this.process !== process || this.sessionGeneration !== generation) return;
    try {
      for (const message of this.decoder.feed(chunk)) this.onMessage(message, token);
    } catch (error) {
      this.rejectProtocol(error instanceof Error ? error : new TransportProtocolError(String(error)));
    }
  }

  private onMessage(message: Record<string, unknown>, token: Uint8Array): void {
    if (!this.hello) {
      const hello = validateBackendHello(message);
      this.hello = hello;
      this.capabilitiesValue = Object.freeze(structuredClone(hello.capabilities));
      this.setState("HANDSHAKING");
      const context = this.projectContext;
      this.send(createSupervisorAccept(
        hello,
        token,
        this.config.desktopVersion,
        context?.projectId ?? null,
        context?.projectContextRevisionId ?? null,
        context?.lastDurableProjectEventSequence ?? 0
      ));
      return;
    }
    if (this.stateValue === "HANDSHAKING") {
      validateReady(message, this.hello);
      if (this.readyTimer) clearTimeout(this.readyTimer);
      this.readyTimer = undefined;
      if (this.projectContext) {
        this.setState("REPLAYING");
        this.sendReplay(this.projectContext.lastDurableProjectEventSequence);
      } else {
        this.becomeReady();
      }
      return;
    }
    switch (message.kind) {
      case "response": this.onResponse(message); break;
      case "event": this.onEvent(validateEvent(message)); break;
      case "events.replayComplete": this.onReplayComplete(message); break;
      case "runtime.health": this.onControlResponse(message); break;
      case "productEntry.projectCreated":
      case "productEntry.projectsListed": this.onControlResponse(message); break;
      case "productEntry.error": this.onControlResponse(message); break;
      case "runtime.shutdownReady": this.onControlResponse(message); break;
      case "runtime.shutdownCommitted": this.onControlResponse(message); break;
      default: throw new TransportProtocolError(`unexpected backend frame: ${String(message.kind)}`);
    }
  }

  private onResponse(message: Record<string, unknown>): void {
    const requestId = message.request_id;
    if (typeof requestId !== "string") throw new TransportProtocolError("response request_id is missing");
    const pending = this.pending.get(requestId);
    if (!pending) {
      const tombstone = this.takeTombstone(requestId);
      if (tombstone) {
        const lateWindow = tombstone.ttlBoundaryAt <= Date.now() ? " after the configured TTL window" : "";
        this.emit("diagnostic", {
          level: "WARN",
          code: "LATE_RESPONSE_DISCARDED",
          message: `discarded late response for timed-out request ${requestId} from session generation ${tombstone.generation}${lateWindow}`
        } satisfies RuntimeDiagnostic);
        return;
      }
      throw new TransportProtocolError("response has no pending request correlation");
    }
    if (pending.generation !== this.sessionGeneration) {
      this.pending.delete(requestId);
      clearTimeout(pending.timer);
      this.rememberTombstone(requestId, pending.generation);
      this.emit("diagnostic", {
        level: "WARN",
        code: "STALE_SESSION_RESPONSE_DISCARDED",
        message: `discarded response for stale session generation ${pending.generation}`
      } satisfies RuntimeDiagnostic);
      return;
    }
    this.pending.delete(requestId);
    clearTimeout(pending.timer);
    const keys = Object.keys(message).sort().join("|");
    if (message.status === "OK" && "body" in message && keys === "body|kind|request_id|status") {
      pending.resolve(contextBridgeSafe(message.body));
    } else if (message.status === "ERROR" && message.error && keys === "error|kind|request_id|status") {
      const error = asRecord(message.error, "response error") as unknown as RuntimeResponseError;
      pending.reject(BackendRuntimeError.fromWire(error));
    } else {
      throw new TransportProtocolError("response status/body shape is invalid");
    }
  }

  private onEvent(event: RuntimeEvent): void {
    // Dedupe only against durably committed event ids. Uncommitted events
    // must never enter this cache, otherwise a cursor-commit failure
    // followed by a backend replay of the same event could be swallowed.
    if (this.recentEventIds.has(event.event_id)) return;
    const context = this.projectContext;
    if (!context || event.project_id !== context.projectId) throw new TransportProtocolError("event project does not match the active context");
    const expected = context.lastDurableProjectEventSequence + 1;
    if (event.project_sequence < expected) return;
    const gap = event.project_sequence - expected;
    if (gap > this.maxEventSequenceGap) {
      this.bufferFailClosed("EVENT_SEQUENCE_GAP_ABSURD", `live event sequence gap ${gap} exceeds the bounded replay window`);
      return;
    }
    if (gap > 0) {
      if (this.bufferedEvents.size >= this.maxBufferedEvents) {
        this.bufferFailClosed("EVENT_BUFFER_OVERFLOW", `buffered event count exceeded the hard limit of ${this.maxBufferedEvents}`);
        return;
      }
      this.bufferedEvents.set(event.project_sequence, event);
      if (this.stateValue !== "REPLAYING") {
        this.setState("REPLAYING");
        this.sendReplay(context.lastDurableProjectEventSequence);
      }
      return;
    }
    if (event.project_sequence === this.deliveryInFlight) return;
    this.bufferedEvents.set(event.project_sequence, event);
    this.maybeDeliver();
  }

  private maybeDeliver(): void {
    if (this.deliveryScheduled) return;
    if (!["REPLAYING", "READY", "SHUTTING_DOWN"].includes(this.stateValue)) return;
    this.deliveryScheduled = true;
    this.deliveryChain = this.deliveryChain.then(async () => {
      this.deliveryScheduled = false;
      for (;;) {
        const expected = (this.projectContext?.lastDurableProjectEventSequence ?? 0) + 1;
        const event = this.bufferedEvents.get(expected);
        if (!event) return;
        this.bufferedEvents.delete(expected);
        this.deliveryInFlight = expected;
        try {
          await this.deliverEvent(event);
        } catch (error) {
          this.deliveryInFlight = 0;
          this.deliveryFailed(error);
          return;
        }
        this.deliveryInFlight = 0;
      }
    });
  }

  private async deliverEvent(event: RuntimeEvent): Promise<void> {
    // At-least-once / no-loss semantics: hand the event to the main-process
    // application relay first. A crash between emit and the durable cursor
    // commit re-delivers this event after reconnect (it was never acked),
    // so the application may observe it twice but can never permanently
    // lose it.
    this.emit("event", contextBridgeSafe(event));
    try {
      await this.cursorPort.commit(event.project_id, event.project_sequence);
    } catch (error) {
      throw new DurableCursorCommitError("durable event cursor commit failed", error);
    }
    // Only a durably committed event may enter the id cache.
    this.rememberEventId(event.event_id);
    this.projectContext = {
      projectId: this.projectContext!.projectId,
      projectContextRevisionId: this.projectContext!.projectContextRevisionId,
      lastDurableProjectEventSequence: event.project_sequence
    };
    this.send({ kind: "events.ack", project_sequence: event.project_sequence });
  }

  private onReplayComplete(message: Record<string, unknown>): void {
    if (this.stateValue !== "REPLAYING") {
      this.rejectProtocol(new TransportProtocolError("unsolicited events.replayComplete"));
      return;
    }
    const keys = Object.keys(message).sort().join("|");
    if (keys !== "has_more|high_watermark|kind|last_sequence|next_after_sequence" ||
        !Number.isInteger(message.last_sequence) || !Number.isInteger(message.next_after_sequence) ||
        !Number.isInteger(message.high_watermark) || typeof message.has_more !== "boolean") {
      this.rejectProtocol(new TransportProtocolError("events.replayComplete shape is invalid"));
      return;
    }
    if (message.next_after_sequence !== message.last_sequence) {
      this.rejectProtocol(new TransportProtocolError("events.replayComplete next_after_sequence must equal the page last_sequence"));
      return;
    }
    const lastSequence = Number(message.last_sequence);
    const highWatermark = Number(message.high_watermark);
    const hasMore = message.has_more === true;
    // Completion handling is serialized behind in-flight deliveries so the
    // contiguous cursor check observes the final durable cursor of the page.
    this.deliveryChain = this.deliveryChain.then(() => {
      this.handleReplayComplete(lastSequence, highWatermark, hasMore);
    }).catch((error: unknown) => {
      if (error instanceof ReplayContiguityError) {
        // A delivery failure interrupted the page: reconnect and replay
        // rather than permanently rejecting the protocol.
        this.emit("diagnostic", { level: "ERROR", code: "REPLAY_CONTIGUITY_FAILED", message: error.message });
        this.process?.terminate();
        return;
      }
      this.rejectProtocol(error instanceof Error ? error : new TransportProtocolError(String(error)));
    });
  }

  private handleReplayComplete(lastSequence: number, highWatermark: number, hasMore: boolean): void {
    if (this.replayFrozenWatermark === null) {
      // The first page freezes this replay round's historical high watermark.
      // Live events above H must not extend the historical catch-up window.
      this.replayFrozenWatermark = highWatermark;
    } else if (highWatermark < this.replayFrozenWatermark) {
      throw new TransportProtocolError("events.replayComplete high watermark moved backwards");
    }
    const cursor = this.projectContext?.lastDurableProjectEventSequence ?? 0;
    if (lastSequence > cursor) {
      // The page claims delivery beyond the contiguous cursor: events are
      // missing from durable delivery (a commit failure interrupted the
      // page). Reconnect and replay is the recovery, so this is a
      // contiguity failure, not a permanent protocol rejection.
      throw new ReplayContiguityError("events.replayComplete sequence does not match contiguous delivery");
    }
    if (lastSequence === cursor && lastSequence === this.lastReplayAfterSequence && hasMore) {
      // An empty page that still claims more history would loop forever.
      throw new TransportProtocolError("events.replayComplete page made no progress while claiming more history");
    }
    if (cursor < this.replayFrozenWatermark) {
      if (!hasMore) {
        throw new TransportProtocolError("events.replayComplete reports no more pages before the frozen high watermark");
      }
      this.sendReplay(cursor);
      return;
    }
    // Contiguous durable cursor has reached the frozen high watermark:
    // historical catch-up is complete. Events above H are the live tail and
    // are delivered through normal contiguous event delivery, never by
    // chasing a moving watermark with more replay pages.
    this.replayFrozenWatermark = null;
    this.lastReplayAfterSequence = null;
    this.becomeReady();
    this.maybeDeliver();
  }

  private sendReplay(afterSequence: number): void {
    this.lastReplayAfterSequence = afterSequence;
    this.send({ kind: "events.replay", after_sequence: afterSequence, limit: REPLAY_PAGE_LIMIT });
  }

  private onControlResponse(message: Record<string, unknown>): void {
    const controlRequestId = message.control_request_id;
    const generation = message.runtime_generation;
    if (
      typeof controlRequestId !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(controlRequestId)
    ) {
      throw new TransportProtocolError(`${String(message.kind)} control_request_id is invalid`);
    }
    if (!Number.isSafeInteger(generation) || Number(generation) < 1) {
      throw new TransportProtocolError(`${String(message.kind)} runtime_generation is invalid`);
    }
    const pending = this.pendingControls.get(controlRequestId);
    if (!pending) {
      const tombstone = this.getControlTombstone(controlRequestId);
      if (
        tombstone
        && tombstone.responseKinds.includes(String(message.kind))
        && tombstone.generation === Number(generation)
      ) {
        this.controlTombstones.delete(controlRequestId);
        this.emit("diagnostic", {
          level: "WARN",
          code: "LATE_CONTROL_RESPONSE_DISCARDED",
          message: `discarded late ${String(message.kind)} response for control request ${controlRequestId} from session generation ${tombstone.generation}`
        } satisfies RuntimeDiagnostic);
        return;
      }
      throw new TransportProtocolError(`${String(message.kind)} response has no pending control correlation`);
    }
    if (!pending.responseKinds.includes(String(message.kind))) {
      throw new TransportProtocolError(
        `${String(message.kind)} response does not match pending ${pending.kind} control request`
      );
    }
    if (pending.generation !== Number(generation) || pending.generation !== this.sessionGeneration) {
      this.emit("diagnostic", {
        level: "WARN",
        code: "STALE_CONTROL_RESPONSE_DISCARDED",
        message: `discarded ${String(message.kind)} response for stale session generation ${String(generation)}`
      } satisfies RuntimeDiagnostic);
      return;
    }
    clearTimeout(pending.timer);
    this.pendingControls.delete(controlRequestId);
    pending.wait.resolve(contextBridgeSafe(message));
  }

  private becomeReady(): void {
    this.restartAttempt = 0;
    this.setState("READY");
    this.ready?.resolve();
    this.ready = undefined;
  }

  private deliveryFailed(error: unknown): void {
    const code = error instanceof DurableCursorCommitError ? "CURSOR_COMMIT_FAILED" : "EVENT_APPLICATION_DELIVERY_FAILED";
    const message = error instanceof Error ? error.message : String(error);
    this.emit("diagnostic", { level: "ERROR", code, message });
    this.process?.terminate();
  }

  private bufferFailClosed(code: string, message: string): void {
    this.emit("diagnostic", { level: "ERROR", code, message });
    this.process?.terminate();
  }

  private whenDeliveryIdle(): Promise<void> {
    return this.deliveryChain.then(() => undefined, () => undefined);
  }

  private rememberEventId(eventId: string): void {
    this.recentEventIds.set(eventId, true);
    if (this.recentEventIds.size > RECENT_EVENT_ID_CACHE_LIMIT) {
      const oldest = this.recentEventIds.keys().next().value as string | undefined;
      if (oldest !== undefined) this.recentEventIds.delete(oldest);
    }
  }

  private rememberTombstone(requestId: string, generation: number): void {
    this.tombstones.delete(requestId);
    if (this.tombstones.size >= this.requestTombstoneLimit) {
      this.rejectProtocol(new BackendRuntimeError(
        "backend timed-out request correlation capacity was exceeded",
        "TRANSPORT_TOMBSTONE_CAPACITY"
      ));
      return;
    }
    this.tombstones.set(requestId, {
      generation,
      ttlBoundaryAt: Date.now() + this.requestTombstoneTtlMs
    });
  }

  private takeTombstone(requestId: string): RequestTombstone | undefined {
    const tombstone = this.tombstones.get(requestId);
    if (tombstone) this.tombstones.delete(requestId);
    if (tombstone && tombstone.generation !== this.sessionGeneration) return undefined;
    return tombstone;
  }

  private ensureRequestTombstoneCapacity(): void {
    const reservedCorrelations = this.tombstones.size + this.pending.size;
    if (reservedCorrelations < this.requestTombstoneLimit) return;
    throw new BackendRuntimeError(
      "new backend request rejected while timed-out correlation capacity is reserved",
      "TRANSPORT_TOMBSTONE_CAPACITY",
      true,
      {
        max_tombstones: this.requestTombstoneLimit,
        timed_out_correlations: this.tombstones.size,
        pending_correlations: this.pending.size
      }
    );
  }

  private ensureControlCapacity(): void {
    this.pruneControlTombstones();
    if (
      this.pendingControls.size >= MAX_PENDING_CONTROL_REQUESTS
      || this.pendingControls.size + this.controlTombstones.size >= CONTROL_TOMBSTONE_LIMIT
    ) {
      throw new BackendRuntimeError(
        "new backend control request rejected while correlation capacity is reserved",
        "CONTROL_CORRELATION_CAPACITY",
        true,
        {
          max_pending: MAX_PENDING_CONTROL_REQUESTS,
          max_tombstones: CONTROL_TOMBSTONE_LIMIT,
          pending_correlations: this.pendingControls.size,
          timed_out_correlations: this.controlTombstones.size
        }
      );
    }
  }

  private rememberControlTombstone(
    controlRequestId: string,
    pending: PendingControlRequest<Readonly<Record<string, unknown>>>
  ): void {
    this.pruneControlTombstones();
    this.controlTombstones.set(controlRequestId, {
      kind: pending.kind,
      responseKinds: pending.responseKinds,
      generation: pending.generation,
      ttlBoundaryAt: Date.now() + CONTROL_TOMBSTONE_TTL_MS
    });
  }

  private getControlTombstone(controlRequestId: string): ControlTombstone | undefined {
    this.pruneControlTombstones();
    return this.controlTombstones.get(controlRequestId);
  }

  private pruneControlTombstones(now = Date.now()): void {
    for (const [controlRequestId, tombstone] of this.controlTombstones) {
      if (tombstone.ttlBoundaryAt <= now) this.controlTombstones.delete(controlRequestId);
    }
  }

  private onStderr(process: BackendProcess, generation: number, chunk: Uint8Array): void {
    if (this.process !== process || this.sessionGeneration !== generation) return;
    const incoming = Buffer.from(chunk);
    const remaining = this.maxStderrBytes - this.stderrTotalBytes;
    if (remaining <= 0) {
      this.emitStderrLimitDiagnostic();
      return;
    }
    const accepted = incoming.subarray(0, remaining);
    this.stderrTotalBytes += accepted.byteLength;
    if (accepted.byteLength < incoming.byteLength) this.emitStderrLimitDiagnostic();
    if (accepted.byteLength > 0) this.stderrBuffer = Buffer.concat([this.stderrBuffer, accepted]);
    for (;;) {
      const newline = this.stderrBuffer.indexOf(0x0a);
      if (newline < 0) {
        if (this.stderrBuffer.byteLength > this.maxStderrLineBytes) {
          this.stderrBuffer = this.stderrBuffer.subarray(this.stderrBuffer.byteLength - this.maxStderrLineBytes);
          this.stderrLineTruncated = true;
        }
        return;
      }
      const lineBytes = this.stderrBuffer.subarray(0, newline);
      this.stderrBuffer = this.stderrBuffer.subarray(newline + 1);
      const lineTruncated = this.stderrLineTruncated || lineBytes.byteLength > this.maxStderrLineBytes;
      this.stderrLineTruncated = false;
      if (lineTruncated) {
        this.emitStderrLimitDiagnostic("stderr line exceeded the bounded line limit [TRUNCATED]");
        continue;
      }
      const line = lineBytes.toString("utf8").trim();
      if (!line) continue;
      let diagnostic: RuntimeDiagnostic;
      try {
        const parsed = asRecord(JSON.parse(line), "stderr diagnostic");
        diagnostic = {
          level: ["INFO", "WARN", "ERROR"].includes(String(parsed.level)) ? parsed.level as RuntimeDiagnostic["level"] : "ERROR",
          code: typeof parsed.code === "string" ? parsed.code : "BACKEND_STDERR",
          message: boundedText(typeof parsed.message === "string" ? parsed.message : "redacted backend diagnostic")
        };
      } catch {
        diagnostic = { level: "ERROR", code: "BACKEND_STDERR_UNSTRUCTURED", message: "redacted unstructured backend diagnostic" };
      }
      this.emit("diagnostic", diagnostic);
    }
  }

  private emitStderrLimitDiagnostic(message = "backend stderr exceeded the bounded total limit [TRUNCATED]"): void {
    if (this.stderrLimitDiagnosticEmitted) return;
    this.stderrLimitDiagnosticEmitted = true;
    this.emit("diagnostic", {
      level: "WARN",
      code: "BACKEND_STDERR_TRUNCATED",
      message: boundedText(message)
    } satisfies RuntimeDiagnostic);
  }

  private onExit(process: BackendProcess, generation: number, code: number | null, signal: NodeJS.Signals | null): void {
    if (this.process !== process || this.sessionGeneration !== generation) return;
    this.process = undefined;
    this.clearWriteQueue();
    if (this.readyTimer) clearTimeout(this.readyTimer);
    this.readyTimer = undefined;
    const error = new BackendDisconnectedError(`canonical backend exited (code=${String(code)}, signal=${String(signal)})`);
    this.ready?.reject(error);
    this.ready = undefined;
    this.rejectAll(error, false);
    this.tombstones.clear();
    if (this.expectedExit) {
      this.setState("STOPPED");
      return;
    }
    this.setState("DISCONNECTED");
    if (this.protocolRejected || this.config.autoReconnect === false) return;
    if (!this.crashGuard.recordCrash()) {
      this.setState("CRASH_LOOP");
      this.emit("error", new BackendCrashLoopError());
      return;
    }
    const base = this.config.reconnectBaseDelayMs ?? 250;
    const maximum = this.config.reconnectMaxDelayMs ?? 10_000;
    const delay = Math.min(maximum, base * 2 ** this.restartAttempt++);
    this.restartTimer = setTimeout(() => {
      this.restartTimer = undefined;
      if (this.expectedExit || this.protocolRejected) return;
      this.setState("RECONNECTING");
      void this.launch().catch((launchError: unknown) => this.emit("error", launchError));
    }, delay);
  }

  private rejectProtocol(error: Error): void {
    this.protocolRejected = true;
    this.ready?.reject(error);
    this.ready = undefined;
    this.rejectAll(error, false);
    this.clearWriteQueue();
    this.process?.terminate();
    this.setState("DISCONNECTED");
  }

  private rejectAll(error: Error, preserveTombstones = true): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      if (preserveTombstones) this.rememberTombstone(pending.requestId, pending.generation);
      pending.reject(error);
    }
    this.pending.clear();
    for (const pending of this.pendingControls.values()) {
      clearTimeout(pending.timer);
      pending.wait.reject(error);
    }
    this.pendingControls.clear();
    this.controlTombstones.clear();
  }

  private send(message: Readonly<Record<string, unknown>>): void {
    const target: Writable | undefined = this.process?.stdin;
    if (!target || target.destroyed || !target.writable) throw new BackendDisconnectedError();
    const frame = encodeFrame(message);
    if (this.writeQueue.length > 0 || this.writeBackpressured) {
      this.enqueueWrite(target, frame);
      this.flushWrites(target);
      return;
    }
    this.writeFrame(target, frame);
  }

  private enqueueWrite(target: Writable, frame: Buffer): void {
    if (
      this.writeQueue.length >= this.maxBufferedStdinWrites
      || this.bufferedStdinBytes + frame.byteLength > this.maxBufferedStdinBytes
    ) {
      const error = new BackendRuntimeError(
        "backend stdin backpressure queue exceeded its bounded limit",
        "TRANSPORT_BACKPRESSURE",
        true,
        { max_bytes: this.maxBufferedStdinBytes, max_writes: this.maxBufferedStdinWrites }
      );
      this.emit("diagnostic", { level: "ERROR", code: error.code, message: error.message } satisfies RuntimeDiagnostic);
      this.rejectAll(error, false);
      this.process?.terminate();
      throw error;
    }
    this.writeQueue.push(frame);
    this.bufferedStdinBytes += frame.byteLength;
    void target;
  }

  private flushWrites(target: Writable): void {
    if (this.writeBackpressured || this.process?.stdin !== target) return;
    while (this.writeQueue.length > 0 && !this.writeBackpressured) {
      const frame = this.writeQueue.shift()!;
      this.bufferedStdinBytes -= frame.byteLength;
      this.writeFrame(target, frame);
    }
  }

  private writeFrame(target: Writable, frame: Buffer): void {
    try {
      if (!target.write(frame)) {
        this.writeBackpressured = true;
        this.armDrain(target);
      }
    } catch (error) {
      const failure = new BackendRuntimeError(
        "backend stdin write failed",
        "TRANSPORT_BACKPRESSURE",
        true,
        { cause: boundedText(error instanceof Error ? error.message : String(error)) }
      );
      this.emit("diagnostic", { level: "ERROR", code: failure.code, message: failure.message } satisfies RuntimeDiagnostic);
      this.rejectAll(failure, false);
      this.process?.terminate();
      throw failure;
    }
  }

  private armDrain(target: Writable): void {
    if (this.drainTarget === target) return;
    this.drainTarget = target;
    target.once("drain", () => {
      if (this.process?.stdin !== target) return;
      this.drainTarget = undefined;
      this.writeBackpressured = false;
      this.flushWrites(target);
    });
  }

  private clearWriteQueue(): void {
    this.writeQueue = [];
    this.bufferedStdinBytes = 0;
    this.writeBackpressured = false;
    this.drainTarget = undefined;
  }

  private setState(next: ConnectionState): void {
    if (this.stateValue === next) return;
    this.stateValue = next;
    this.emit("state", next);
  }

  private async withTimeout<T>(promise: Promise<T>, milliseconds: number, message: string): Promise<T> {
    let timer: NodeJS.Timeout | undefined;
    const timeout = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new BackendTimeoutError(message)), milliseconds);
    });
    try {
      return await Promise.race([promise, timeout]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
