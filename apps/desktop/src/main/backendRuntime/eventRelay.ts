import type { BackendSupervisor } from "./supervisor";
import { BACKEND_RUNTIME_CHANNELS } from "./ipc";
import { contextBridgeSafe } from "./protocol";
import type { ConnectionState, RuntimeEvent } from "./types";

export interface RendererEventTarget {
  send(channel: string, value: unknown): void;
}

export class BackendRuntimeEventRelay {
  private readonly onEvent = (event: RuntimeEvent): void => {
    this.target.send(BACKEND_RUNTIME_CHANNELS.taskEvent, contextBridgeSafe(event));
  };
  private readonly onState = (state: ConnectionState): void => {
    this.target.send(BACKEND_RUNTIME_CHANNELS.connectionState, state);
  };

  constructor(private readonly supervisor: BackendSupervisor, private readonly target: RendererEventTarget) {}

  start(): void {
    this.supervisor.on("event", this.onEvent);
    this.supervisor.on("state", this.onState);
  }

  stop(): void {
    this.supervisor.off("event", this.onEvent);
    this.supervisor.off("state", this.onState);
  }
}
