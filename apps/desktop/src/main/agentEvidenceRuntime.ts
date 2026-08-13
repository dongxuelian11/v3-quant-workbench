export type AgentEvidenceMode = "LIVE_READ_ONLY" | "DEVELOPMENT_INTEGRATION_FIXTURE";
export type BackendModule = "v3_backend.runtime.bootstrap" | "v3_backend.adapters.round3_evidence.development_runtime";

export interface AgentEvidenceRuntimeResolution {
  readonly mode: AgentEvidenceMode;
  readonly backendModule: BackendModule;
  readonly fixtureDeniedByPackaging: boolean;
}

const DEVELOPMENT_FIXTURE_MODE = "DEVELOPMENT_INTEGRATION_FIXTURE";
const PRODUCTION_BACKEND_MODULE = "v3_backend.runtime.bootstrap";

export function resolveAgentEvidenceRuntime(isPackaged: boolean, requestedMode: string | undefined): AgentEvidenceRuntimeResolution {
  const explicitlyRequestedFixture = requestedMode === DEVELOPMENT_FIXTURE_MODE;
  const fixtureAllowed = !isPackaged && explicitlyRequestedFixture;
  return Object.freeze({
    mode: fixtureAllowed ? DEVELOPMENT_FIXTURE_MODE : "LIVE_READ_ONLY",
    backendModule: fixtureAllowed ? "v3_backend.adapters.round3_evidence.development_runtime" : PRODUCTION_BACKEND_MODULE,
    fixtureDeniedByPackaging: isPackaged && explicitlyRequestedFixture
  });
}
