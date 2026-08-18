import { createHmac, timingSafeEqual } from "node:crypto";
import type { BackendCapability, BackendHello, RuntimeEvent } from "./types";
import { MAX_FRAME_BYTES, TransportProtocolError } from "./framing";

export const LOCAL_PROTOCOL = "v3.local/1.0";
export const ASL_SERVICES = Object.freeze([
  "ProjectSessionService", "DataSourceService", "InstrumentService", "DataSnapshotService",
  "UniverseService", "ResearchService", "DatasetService", "StrategyService", "ModelService",
  "StudyService", "PortfolioService", "RiskService", "OptimizationService", "BacktestService",
  "ResultService", "TaskService", "ArtifactService", "ProductEntryService"
] as const);

const HELLO_KEYS = Object.freeze([
  "kind", "protocol", "backend_instance_id", "pid", "backend_version", "asl_versions",
  "schema_compatibility", "capabilities", "max_frame_bytes", "event_replay", "nonce"
]);
const RAW_PATH_KEY = /(?:path|database|sqlite|duckdb|parquet|executable|working.?directory|cwd)/i;
const WINDOWS_ABSOLUTE = /^[A-Za-z]:[\\/]/;
const POSIX_ABSOLUTE = /^\/(?!\/)/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && !Array.isArray(value) && typeof value === "object";
}

function requireClosedKeys(value: Record<string, unknown>, expected: readonly string[], name: string): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new TransportProtocolError(`${name} fields do not match the closed wire shape`);
  }
}

function majorMinor(value: string): readonly [number, number] {
  const match = /^(?:v3\.local\/)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.[0-9]+)?$/.exec(value);
  if (!match) throw new TransportProtocolError(`invalid version ${value}`);
  return [Number(match[1]), Number(match[2])];
}

export function validateBackendHello(value: Record<string, unknown>): BackendHello {
  requireClosedKeys(value, HELLO_KEYS, "backend.hello");
  if (value.kind !== "backend.hello") throw new TransportProtocolError("expected backend.hello");
  if (typeof value.protocol !== "string") throw new TransportProtocolError("backend protocol is missing");
  const [clientMajor, clientMinor] = majorMinor(LOCAL_PROTOCOL);
  const [backendMajor, backendMinor] = majorMinor(value.protocol);
  if (backendMajor !== clientMajor || backendMinor < clientMinor) throw new TransportProtocolError("incompatible local runtime protocol");
  if (typeof value.backend_instance_id !== "string" || value.backend_instance_id.length === 0) throw new TransportProtocolError("backend instance ID is missing");
  if (!Number.isInteger(value.pid) || Number(value.pid) <= 0) throw new TransportProtocolError("backend pid is invalid");
  if (typeof value.backend_version !== "string" || value.backend_version.length === 0) throw new TransportProtocolError("backend version is missing");
  if (!isRecord(value.asl_versions) || Object.keys(value.asl_versions).sort().join("|") !== [...ASL_SERVICES].sort().join("|")) {
    throw new TransportProtocolError("backend ASL service set does not match the frozen registry");
  }
  for (const service of ASL_SERVICES) {
    const offered = value.asl_versions[service];
    if (typeof offered !== "string" || majorMinor(offered)[0] !== 1) throw new TransportProtocolError(`incompatible ASL major for ${service}`);
  }
  if (!isRecord(value.schema_compatibility) || typeof value.schema_compatibility.min !== "string" || typeof value.schema_compatibility.max !== "string") {
    throw new TransportProtocolError("schema compatibility range is invalid");
  }
  if (!Array.isArray(value.capabilities)) throw new TransportProtocolError("capability list is invalid");
  const capabilities = value.capabilities.map(validateCapability);
  if (!Number.isInteger(value.max_frame_bytes) || Number(value.max_frame_bytes) < 1 || Number(value.max_frame_bytes) > MAX_FRAME_BYTES) {
    throw new TransportProtocolError("backend max frame size is invalid");
  }
  if (value.event_replay !== true) throw new TransportProtocolError("durable event replay is required");
  if (typeof value.nonce !== "string" || !/^[0-9a-f]{64}$/.test(value.nonce)) throw new TransportProtocolError("handshake nonce is invalid");
  return value as unknown as BackendHello;
}

function validateCapability(value: unknown): BackendCapability {
  if (!isRecord(value)) throw new TransportProtocolError("capability must be an object");
  const expected = value.reason_code === undefined ? ["code", "truth_state"] : ["code", "truth_state", "reason_code"];
  requireClosedKeys(value, expected, "capability");
  if (typeof value.code !== "string" || value.code.length === 0) throw new TransportProtocolError("capability code is invalid");
  if (!["FORMAL", "DEMO", "UNAVAILABLE"].includes(String(value.truth_state))) throw new TransportProtocolError("capability truth is invalid");
  if (value.reason_code !== undefined && typeof value.reason_code !== "string") throw new TransportProtocolError("capability reason code is invalid");
  return value as unknown as BackendCapability;
}

export function createSupervisorAccept(
  hello: BackendHello,
  token: Uint8Array,
  desktopVersion: string,
  projectId: string | null,
  projectContextRevisionId: string | null,
  lastSequence: number
): Record<string, unknown> {
  const proof = createHmac("sha256", token).update(hello.nonce, "ascii").digest("hex");
  return {
    kind: "supervisor.accept",
    token_proof: proof,
    requested_protocol: LOCAL_PROTOCOL,
    requested_asl_versions: Object.fromEntries(ASL_SERVICES.map((service) => [service, "1.0"])),
    desktop_version: desktopVersion,
    project_id: projectId,
    project_context_revision_id: projectContextRevisionId,
    last_project_event_sequence: lastSequence
  };
}

export function validateReady(value: Record<string, unknown>, hello: BackendHello): void {
  requireClosedKeys(value, ["kind", "backend_instance_id", "protocol", "schema_version"], "backend.ready");
  if (value.kind !== "backend.ready" || value.backend_instance_id !== hello.backend_instance_id || value.protocol !== LOCAL_PROTOCOL) {
    throw new TransportProtocolError("backend.ready does not match the accepted backend");
  }
  if (typeof value.schema_version !== "string" || majorMinor(value.schema_version)[0] !== 1) throw new TransportProtocolError("schema major is incompatible");
}

export function validateEvent(value: Record<string, unknown>): RuntimeEvent {
  requireClosedKeys(value, ["kind", "event_id", "project_id", "project_sequence", "event_type", "occurred_at", "body"], "event");
  if (value.kind !== "event" || typeof value.event_id !== "string" || typeof value.project_id !== "string" ||
      !Number.isInteger(value.project_sequence) || Number(value.project_sequence) <= 0 || typeof value.event_type !== "string" ||
      typeof value.occurred_at !== "string" || !isRecord(value.body)) {
    throw new TransportProtocolError("event envelope is invalid");
  }
  return value as unknown as RuntimeEvent;
}

export function contextBridgeSafe<T>(value: T): T {
  const visit = (item: unknown, key = "$"): unknown => {
    if (item === null || typeof item === "string" || typeof item === "boolean") {
      if (typeof item === "string" && (WINDOWS_ABSOLUTE.test(item) || POSIX_ABSOLUTE.test(item))) {
        throw new TransportProtocolError(`raw filesystem path rejected at ${key}`);
      }
      return item;
    }
    if (typeof item === "number") {
      if (!Number.isFinite(item)) throw new TransportProtocolError(`non-finite number rejected at ${key}`);
      return item;
    }
    if (Array.isArray(item)) return item.map((entry, index) => visit(entry, `${key}[${index}]`));
    if (isRecord(item)) {
      const result: Record<string, unknown> = {};
      for (const [name, entry] of Object.entries(item)) {
        if (RAW_PATH_KEY.test(name)) throw new TransportProtocolError(`raw storage field rejected at ${key}.${name}`);
        result[name] = visit(entry, `${key}.${name}`);
      }
      return result;
    }
    throw new TransportProtocolError(`non-serializable value rejected at ${key}`);
  };
  return visit(value) as T;
}

export function constantTimeEqual(left: Uint8Array, right: Uint8Array): boolean {
  return left.byteLength === right.byteLength && timingSafeEqual(left, right);
}
