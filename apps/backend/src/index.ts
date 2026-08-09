/**
 * Compile-time placeholder only. The future backend will implement this contract
 * behind an Application Service Layer; the recovered frontend uses the explicit
 * unavailable provider until then.
 */
export interface FutureCanonicalBackendBoundary {
  readonly status: "not_rebuilt";
}

