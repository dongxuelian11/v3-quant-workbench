import type { Readable, Writable } from "node:stream";

export type TruthState = "FORMAL" | "DEMO" | "UNAVAILABLE";
export type ConnectionState = "STOPPED" | "STARTING" | "HANDSHAKING" | "REPLAYING" | "READY" | "RECONNECTING" | "DISCONNECTED" | "CRASH_LOOP" | "SHUTTING_DOWN";

export interface BackendCapability {
  readonly code: string;
  readonly truth_state: TruthState;
  readonly reason_code?: string;
}

export interface BackendHello {
  readonly kind: "backend.hello";
  readonly protocol: string;
  readonly backend_instance_id: string;
  readonly pid: number;
  readonly backend_version: string;
  readonly asl_versions: Readonly<Record<string, string>>;
  readonly schema_compatibility: { readonly min: string; readonly max: string };
  readonly capabilities: readonly BackendCapability[];
  readonly max_frame_bytes: number;
  readonly event_replay: true;
  readonly nonce: string;
}

export interface RuntimeEvent {
  readonly kind: "event";
  readonly event_id: string;
  readonly project_id: string;
  readonly project_sequence: number;
  readonly event_type: string;
  readonly occurred_at: string;
  readonly body: Readonly<Record<string, unknown>>;
}

export interface RuntimeDiagnostic {
  readonly level: "INFO" | "WARN" | "ERROR";
  readonly code: string;
  readonly message: string;
}

export interface SpawnSpec {
  readonly executable: string;
  readonly args: readonly string[];
  readonly cwd: string;
  readonly env: Readonly<Record<string, string>>;
}

export interface BackendProcess {
  readonly pid?: number;
  readonly stdin: Writable;
  readonly stdout: Readable;
  readonly stderr: Readable;
  onExit(listener: (code: number | null, signal: NodeJS.Signals | null) => void): void;
  terminate(): void;
  kill(): void;
  isAlive(): boolean;
  waitForExit(deadlineAt: number): Promise<boolean>;
}

export interface BackendProcessFactory {
  spawn(spec: SpawnSpec, supervisorToken: Uint8Array): BackendProcess;
}

export interface SupervisorProjectContext {
  readonly projectId: string;
  readonly projectContextRevisionId: string;
  readonly lastDurableProjectEventSequence: number;
}

/**
 * Durable event cursor commit seam. The supervisor only sends events.ack
 * after this port has durably persisted the applied sequence; a failed
 * commit must never ack and must never claim durable advancement.
 */
export interface DurableEventCursorPort {
  commit(projectId: string, sequence: number): Promise<void>;
}

export interface SupervisorConfig {
  readonly pythonExecutable: string;
  readonly backendWorkingDirectory: string;
  readonly backendRuntimeRoot?: string;
  readonly backendResourceRoot?: string;
  readonly desktopVersion: string;
  readonly projectContext?: SupervisorProjectContext;
  readonly cursorPort?: DurableEventCursorPort;
  readonly handshakeTimeoutMs?: number;
  readonly requestTimeoutMs?: number;
  readonly reconnectBaseDelayMs?: number;
  readonly reconnectMaxDelayMs?: number;
  readonly crashLoopLimit?: number;
  readonly crashLoopWindowMs?: number;
  readonly autoReconnect?: boolean;
  readonly maxBufferedEvents?: number;
  readonly maxEventSequenceGap?: number;
  readonly requestTombstoneLimit?: number;
  readonly requestTombstoneTtlMs?: number;
  readonly maxBufferedStdinBytes?: number;
  readonly maxBufferedStdinWrites?: number;
  readonly maxStderrLineBytes?: number;
  readonly maxStderrBytes?: number;
  readonly backendModule?: "v3_backend.runtime.bootstrap" | "v3_backend.adapters.round3_evidence.development_runtime";
  readonly productReleaseAcceptanceProvider?: "DETERMINISTIC_SUCCESS" | "DETERMINISTIC_UNAVAILABLE";
}

export interface RuntimeResponseError {
  readonly schema_version: "1.0.0";
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly details: Readonly<Record<string, unknown>>;
  readonly correlation_id?: string;
  readonly operation_id?: string;
}

export interface RequestOptions {
  readonly contractVersion?: string;
  /** Exact ASL major.minor expected by the selected operation contract. */
  readonly expectedApiVersion?: "1.0" | "1.1";
  readonly idempotencyKey?: string;
  readonly timeoutMs?: number;
  readonly deadlineAt?: string;
}

export interface CancelTaskInput {
  readonly taskId: string;
  readonly expectedStateVersion: number;
  readonly reason: string;
}

export interface RetryTaskInput {
  readonly taskId: string;
  readonly failedAttemptId: string;
  readonly expectedStateVersion: number;
}

export interface ResumeTaskInput {
  readonly taskId: string;
  readonly checkpointArtifactId: string;
  readonly expectedStateVersion: number;
}

export interface OpenArtifactStreamInput {
  readonly artifactId: string;
  readonly range?: Readonly<Record<string, unknown>>;
}
