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
  readonly resolve: (value: unknown) => void;
  readonly reject: (error: Error) => void;
  readonly timer: NodeJS.Timeout;
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

export class BackendSupervisor extends EventEmitter {
  private readonly processFactory: BackendProcessFactory;
  private readonly tokenFactory: () => Uint8Array;
  private readonly crashGuard: CrashLoopGuard;
  private readonly cursorPort: DurableEventCursorPort;
  private readonly maxBufferedEvents: number;
  private readonly maxEventSequenceGap: number;
  private readonly pending = new Map<string, PendingRequest>();
  private readonly recentEventIds = new Map<string, true>();
  private readonly bufferedEvents = new Map<number, RuntimeEvent>();
  private deliveryChain: Promise<void> = Promise.resolve();
  private deliveryScheduled = false;
  private deliveryInFlight = 0;
  private process?: BackendProcess;
  private decoder = new FrameDecoder();
  private hello?: BackendHello;
  private ready?: Deferred<void>;
  private readyTimer?: NodeJS.Timeout;
  private shutdownReady?: Deferred<void>;
  private shutdownCommitted?: Deferred<void>;
  private healthReply?: Deferred<Readonly<Record<string, unknown>>>;
  private restartTimer?: NodeJS.Timeout;
  private restartAttempt = 0;
  private projectContext?: SupervisorProjectContext;
  private replayFrozenWatermark: number | null = null;
  private lastReplayAfterSequence: number | null = null;
  private expectedExit = false;
  private protocolRejected = false;
  private stderrBuffer = "";
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
    this.crashGuard = new CrashLoopGuard(config.crashLoopLimit ?? 5, config.crashLoopWindowMs ?? 60_000);
  }

  get state(): ConnectionState { return this.stateValue; }
  get capabilities(): readonly BackendCapability[] { return structuredClone(this.capabilitiesValue); }

  setProjectContext(context: SupervisorProjectContext): void {
    if (context.lastDurableProjectEventSequence < 0 || !Number.isInteger(context.lastDurableProjectEventSequence)) {
      throw new RangeError("last durable project sequence must be a non-negative integer");
    }
    this.projectContext = { ...context };
  }

  async start(): Promise<void> {
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
      this.pending.delete(requestId);
      waiting.reject(new BackendTimeoutError(`backend request timed out: ${operationId}`));
    }, timeoutMs);
    this.pending.set(requestId, { resolve: waiting.resolve, reject: waiting.reject, timer });
    try {
      this.send(envelope);
    } catch (error) {
      clearTimeout(timer);
      this.pending.delete(requestId);
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
    if (this.healthReply) throw new BackendRuntimeError("health request already pending", "CONFLICT");
    const wait = deferred<Readonly<Record<string, unknown>>>();
    this.healthReply = wait;
    this.send({ kind: "runtime.health" });
    return this.withTimeout(wait.promise, timeoutMs, "backend health response timed out").finally(() => { this.healthReply = undefined; });
  }

  async shutdown(deadlineMs = 10_000): Promise<void> {
    if (["STOPPED", "DISCONNECTED"].includes(this.stateValue)) return;
    this.setState("SHUTTING_DOWN");
    this.expectedExit = true;
    this.shutdownReady = deferred<void>();
    this.shutdownCommitted = deferred<void>();
    const deadlineAt = new Date(Date.now() + deadlineMs).toISOString();
    this.send({ kind: "runtime.prepareShutdown", deadline_at: deadlineAt });
    try {
      await this.withTimeout(this.shutdownReady.promise, deadlineMs, "backend prepare shutdown timed out");
      this.send({ kind: "runtime.commitShutdown" });
      await this.withTimeout(this.shutdownCommitted.promise, deadlineMs, "backend commit shutdown timed out");
      // The backend cannot emit any more events after shutdownCommitted:
      // drain accepted event deliveries (application emit, cursor commit,
      // ack) before terminating so no committed-but-unacked event is lost.
      await this.whenDeliveryIdle();
    } finally {
      this.process?.terminate();
      this.rejectAll(new BackendDisconnectedError("canonical backend shut down"));
      this.process = undefined;
      this.setState("STOPPED");
    }
  }

  stopNow(): void {
    this.expectedExit = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = undefined;
    this.process?.terminate();
    this.process = undefined;
    this.rejectAll(new BackendDisconnectedError("canonical backend stopped"));
    this.setState("STOPPED");
  }

  private async launch(): Promise<void> {
    this.decoder = new FrameDecoder();
    this.stderrBuffer = "";
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
    const spec: SpawnSpec = {
      executable: this.config.pythonExecutable,
      args: ["-m", backendModule, "--transport=stdio-framed-v1"],
      cwd: this.config.backendWorkingDirectory,
      env: sanitizedBackendEnvironment()
    };
    this.process = this.processFactory.spawn(spec, token);
    const launched = this.process;
    launched.stdout.on("data", (chunk: Buffer) => this.onStdout(chunk, token));
    launched.stderr.on("data", (chunk: Buffer) => this.onStderr(chunk));
    launched.onExit((code, signal) => this.onExit(launched, code, signal));
    this.readyTimer = setTimeout(() => this.rejectProtocol(new BackendTimeoutError("backend.hello/ready handshake timed out")), this.config.handshakeTimeoutMs ?? 10_000);
    return this.ready.promise;
  }

  private onStdout(chunk: Uint8Array, token: Uint8Array): void {
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
      case "runtime.health": this.onHealth(message); break;
      case "runtime.shutdownReady": this.shutdownReady?.resolve(); break;
      case "runtime.shutdownCommitted": this.shutdownCommitted?.resolve(); break;
      default: throw new TransportProtocolError(`unexpected backend frame: ${String(message.kind)}`);
    }
  }

  private onResponse(message: Record<string, unknown>): void {
    const requestId = message.request_id;
    if (typeof requestId !== "string") throw new TransportProtocolError("response request_id is missing");
    const pending = this.pending.get(requestId);
    if (!pending) throw new TransportProtocolError("response has no pending request correlation");
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

  private onHealth(message: Record<string, unknown>): void {
    if (!this.healthReply) throw new TransportProtocolError("unsolicited runtime.health response");
    this.healthReply.resolve(contextBridgeSafe(message));
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

  private onStderr(chunk: Uint8Array): void {
    this.stderrBuffer += Buffer.from(chunk).toString("utf8");
    for (;;) {
      const newline = this.stderrBuffer.indexOf("\n");
      if (newline < 0) return;
      const line = this.stderrBuffer.slice(0, newline).trim();
      this.stderrBuffer = this.stderrBuffer.slice(newline + 1);
      if (!line) continue;
      let diagnostic: RuntimeDiagnostic;
      try {
        const parsed = asRecord(JSON.parse(line), "stderr diagnostic");
        diagnostic = {
          level: ["INFO", "WARN", "ERROR"].includes(String(parsed.level)) ? parsed.level as RuntimeDiagnostic["level"] : "ERROR",
          code: typeof parsed.code === "string" ? parsed.code : "BACKEND_STDERR",
          message: typeof parsed.message === "string" ? parsed.message : "redacted backend diagnostic"
        };
      } catch {
        diagnostic = { level: "ERROR", code: "BACKEND_STDERR_UNSTRUCTURED", message: "redacted unstructured backend diagnostic" };
      }
      this.emit("diagnostic", diagnostic);
    }
  }

  private onExit(process: BackendProcess, code: number | null, signal: NodeJS.Signals | null): void {
    if (this.process !== process) return;
    this.process = undefined;
    if (this.readyTimer) clearTimeout(this.readyTimer);
    this.readyTimer = undefined;
    const error = new BackendDisconnectedError(`canonical backend exited (code=${String(code)}, signal=${String(signal)})`);
    this.ready?.reject(error);
    this.ready = undefined;
    this.rejectAll(error);
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
      void this.launch().catch((launchError: unknown) => this.emit("error", launchError));
    }, delay);
  }

  private rejectProtocol(error: Error): void {
    this.protocolRejected = true;
    this.ready?.reject(error);
    this.ready = undefined;
    this.rejectAll(error);
    this.process?.terminate();
    this.setState("DISCONNECTED");
  }

  private rejectAll(error: Error): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
  }

  private send(message: Readonly<Record<string, unknown>>): void {
    const target: Writable | undefined = this.process?.stdin;
    if (!target || target.destroyed || !target.writable) throw new BackendDisconnectedError();
    target.write(encodeFrame(message));
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
