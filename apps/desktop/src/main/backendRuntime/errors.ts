import type { RuntimeResponseError } from "./types";

export class BackendRuntimeError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly retryable = false,
    readonly details: Readonly<Record<string, unknown>> = {}
  ) {
    super(message);
    this.name = "BackendRuntimeError";
  }

  static fromWire(error: RuntimeResponseError): BackendRuntimeError {
    return new BackendRuntimeError(error.message, error.code, error.retryable, error.details);
  }
}

export class BackendDisconnectedError extends BackendRuntimeError {
  constructor(message = "canonical backend transport is disconnected") {
    super(message, "BACKEND_DISCONNECTED", true);
    this.name = "BackendDisconnectedError";
  }
}

export class BackendTimeoutError extends BackendRuntimeError {
  constructor(message: string) {
    super(message, "BACKEND_TIMEOUT", true);
    this.name = "BackendTimeoutError";
  }
}

export class BackendCrashLoopError extends BackendRuntimeError {
  constructor() {
    super("canonical backend exceeded the crash-loop restart ceiling", "BACKEND_CRASH_LOOP", false);
    this.name = "BackendCrashLoopError";
  }
}
