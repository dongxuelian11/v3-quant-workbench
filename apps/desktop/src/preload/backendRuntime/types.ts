export type RuntimeTruthState = "FORMAL" | "DEMO" | "UNAVAILABLE";
export type RuntimeConnectionState = "STOPPED" | "STARTING" | "HANDSHAKING" | "REPLAYING" | "READY" | "DISCONNECTED" | "CRASH_LOOP" | "SHUTTING_DOWN";

export interface RuntimeCapability {
  readonly code: string;
  readonly truth_state: RuntimeTruthState;
  readonly reason_code?: string;
}

export interface TaskEventView {
  readonly kind: "event";
  readonly event_id: string;
  readonly project_id: string;
  readonly project_sequence: number;
  readonly event_type: string;
  readonly occurred_at: string;
  readonly body: Readonly<Record<string, unknown>>;
}

export interface CancelTaskRequest {
  readonly taskId: string;
  readonly expectedStateVersion: number;
  readonly reason: string;
}

export interface RetryTaskRequest {
  readonly taskId: string;
  readonly failedAttemptId: string;
  readonly expectedStateVersion: number;
}

export interface ResumeTaskRequest {
  readonly taskId: string;
  readonly checkpointArtifactId: string;
  readonly expectedStateVersion: number;
}

export interface ArtifactStreamRequest {
  readonly artifactId: string;
  readonly range?: Readonly<Record<string, unknown>>;
}

export interface BackendRuntimeBridge {
  getCapabilities(): Promise<readonly RuntimeCapability[]>;
  getHealth(): Promise<Readonly<Record<string, unknown>>>;
  cancelTask(request: CancelTaskRequest): Promise<unknown>;
  retryTask(request: RetryTaskRequest): Promise<unknown>;
  resumeTask(request: ResumeTaskRequest): Promise<unknown>;
  openArtifactStream(request: ArtifactStreamRequest): Promise<unknown>;
  onTaskEvent(listener: (event: TaskEventView) => void): () => void;
  onConnectionState(listener: (state: RuntimeConnectionState) => void): () => void;
}

export interface BackendRuntimeReadOnlyBridge {
  getCapabilities(): Promise<readonly RuntimeCapability[]>;
  getHealth(): Promise<Readonly<Record<string, unknown>>>;
  getEvidenceSnapshot(): Promise<TaskEventView | null>;
  onEvidenceEvent(listener: (event: TaskEventView) => void): () => void;
  onConnectionState(listener: (state: RuntimeConnectionState) => void): () => void;
}
