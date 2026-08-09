export interface RuntimeShutdownPort {
  shutdown(deadlineMs?: number): Promise<void>;
}

export interface CloseEventLike {
  preventDefault(): void;
}

export class BackendRuntimeLifecycle {
  constructor(private readonly runtime: RuntimeShutdownPort) {}

  onWindowClose(event: CloseEventLike, hideWindow: () => void): void {
    event.preventDefault();
    hideWindow();
  }

  async onExplicitQuit(deadlineMs = 10_000): Promise<void> {
    await this.runtime.shutdown(deadlineMs);
  }
}
