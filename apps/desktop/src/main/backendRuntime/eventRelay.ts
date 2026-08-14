import type { BackendSupervisor } from "./supervisor";
import { BACKEND_RUNTIME_CHANNELS } from "./ipc";
import { contextBridgeSafe } from "./protocol";
import type { ConnectionState, RuntimeEvent } from "./types";

export interface RendererEventTarget {
  send(channel: string, value: unknown): void;
}

export class BackendRuntimeEventRelay {
  private readonly onEvent = (event: RuntimeEvent): void => {
    if (event.event_type === "round3.research.evidence.bundle.v1") this.evidenceSnapshotValue = contextBridgeSafe(event);
    this.trySend(BACKEND_RUNTIME_CHANNELS.taskEvent, contextBridgeSafe(event));
  };
  private evidenceSnapshotValue: RuntimeEvent | null = null;
  private readonly onState = (state: ConnectionState): void => {
    this.trySend(BACKEND_RUNTIME_CHANNELS.connectionState, state);
  };

  constructor(private readonly supervisor: BackendSupervisor, private readonly target: RendererEventTarget) {}

  get evidenceSnapshot(): RuntimeEvent | null {
    return this.evidenceSnapshotValue === null ? null : structuredClone(this.evidenceSnapshotValue);
  }

  start(): void {
    this.supervisor.on("event", this.onEvent);
    this.supervisor.on("state", this.onState);
  }

  stop(): void {
    this.supervisor.off("event", this.onEvent);
    this.supervisor.off("state", this.onState);
  }

  private trySend(channel: string, value: unknown): void {
    try {
      this.target.send(channel, value);
    } catch {
      // The renderer target can be destroyed while the relay intentionally
      // stays attached during shutdown drain; that is not a delivery failure.
    }
  }
}
