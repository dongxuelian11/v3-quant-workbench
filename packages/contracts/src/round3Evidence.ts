/**
 * VIEW / TRANSPORT CONTRACT ONLY.
 * NOT CANONICAL FINANCIAL AUTHORITY.
 *
 * This schema preserves IDs, hashes, truth, admission, and exact lineage from
 * canonical Python owners. It has no finance factories and creates no IDs.
 */

export const ROUND3_PROJECTION_SCHEMA_VERSION = "v3.round3_canonical_evidence_projection/1.0.0" as const;
export const ROUND3_BUNDLE_SCHEMA_VERSION = "v3.round3_research_evidence_bundle/1.0.0" as const;
export const ROUND3_EVIDENCE_EVENT_TYPE = "round3.research.evidence.bundle.v1" as const;

export const ROUND3_EVIDENCE_KINDS = [
  "PortfolioIntent",
  "TargetWeightVector",
  "RiskAdjustedWeightVector",
  "RiskDecisionReport",
  "BacktestRunSpec",
  "BacktestRunResult"
] as const;

export type Round3EvidenceKind = (typeof ROUND3_EVIDENCE_KINDS)[number];
export type Round3EvidenceSourceMode = "LIVE_READ_ONLY" | "DEVELOPMENT_INTEGRATION_FIXTURE";
export type CanonicalTruthState = "UNKNOWN" | "NOT_FORMAL" | "FORMAL";
export type CanonicalAdmissionState = "UNKNOWN" | "PRE_ALPHA" | "FORMAL_ADMITTED";
export type CanonicalValidationState = "NOT_RUN" | "FAILED" | "PASSED";

export interface Round3ViewFactV1 {
  readonly label: string;
  readonly value: string;
}

export interface DetailsRendererPayloadV1 {
  readonly renderer: "details";
  readonly entries: readonly Round3ViewFactV1[];
}

export interface TableRendererPayloadV1 {
  readonly renderer: "table";
  readonly columns: readonly string[];
  readonly rows: readonly (readonly string[])[];
}

export interface BacktestResultRendererPayloadV1 {
  readonly renderer: "backtest-result";
  readonly resultId: string;
  readonly runSpecId: string;
  readonly nav: {
    readonly columns: readonly ["Session date", "NAV"];
    readonly rows: readonly (readonly [string, string])[];
  };
  readonly fillCount: number;
  readonly diagnosticCount: number;
  readonly cashLedgerSummary: string;
  readonly feeLedgerSummary: string;
}

export type Round3RendererPayloadV1 =
  | DetailsRendererPayloadV1
  | TableRendererPayloadV1
  | BacktestResultRendererPayloadV1;

export interface CanonicalEvidenceProjectionV1 {
  readonly projection_schema_version: typeof ROUND3_PROJECTION_SCHEMA_VERSION;
  readonly source_artifact_type: Round3EvidenceKind;
  readonly source_object_id: string;
  readonly source_content_sha256: string;
  readonly canonical_truth_state: CanonicalTruthState;
  readonly canonical_admission_state: CanonicalAdmissionState;
  readonly validation_state: CanonicalValidationState;
  readonly provenance_refs: readonly string[];
  readonly lineage_refs: readonly string[];
  readonly view_facts: readonly Round3ViewFactV1[];
  readonly renderer_key: Round3RendererPayloadV1["renderer"];
  readonly renderer_payload: Round3RendererPayloadV1;
}

export interface Round3LineageEdgeV1 {
  readonly source_object_id: string;
  readonly source_content_sha256: string;
  readonly target_object_id: string;
  readonly target_content_sha256: string;
  readonly relation:
    | "PORTFOLIO_INTENT_SOURCE"
    | "RISK_APPLICATION_TARGET_BINDING"
    | "RISK_DECISION_TARGET_BINDING"
    | "RISK_DECISION_OUTPUT_BINDING"
    | "SCHEDULED_WEIGHTS_VECTOR"
    | "BACKTEST_RUN_SPEC_RESULT_BINDING";
  readonly binding_object_id: string | null;
}

export interface Round3ResearchEvidenceBundleV1 {
  readonly bundle_schema_version: typeof ROUND3_BUNDLE_SCHEMA_VERSION;
  readonly session_view_id: string;
  readonly source_mode: Round3EvidenceSourceMode;
  readonly projections: readonly CanonicalEvidenceProjectionV1[];
  readonly lineage_edges: readonly Round3LineageEdgeV1[];
}

const OBJECT_PREFIX: Record<Round3EvidenceKind, string> = {
  PortfolioIntent: "pint_sha256_",
  TargetWeightVector: "twv_sha256_",
  RiskAdjustedWeightVector: "rawv_sha256_",
  RiskDecisionReport: "rdr_sha256_",
  BacktestRunSpec: "btrs_sha256_",
  BacktestRunResult: "btrr_sha256_"
};

const EDGE_RELATIONS = new Set([
  "PORTFOLIO_INTENT_SOURCE",
  "RISK_APPLICATION_TARGET_BINDING",
  "RISK_DECISION_TARGET_BINDING",
  "RISK_DECISION_OUTPUT_BINDING",
  "SCHEDULED_WEIGHTS_VECTOR",
  "BACKTEST_RUN_SPEC_RESULT_BINDING"
]);

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || Array.isArray(value) || typeof value !== "object") throw new TypeError(`${label} must be an object`);
  return value as Record<string, unknown>;
}

function closed(value: Record<string, unknown>, keys: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new TypeError(`${label} fields do not match the closed wire shape`);
  }
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || value !== value.trim()) throw new TypeError(`${label} must be a non-empty exact string`);
  return value;
}

function stringArray(value: unknown, label: string): readonly string[] {
  if (!Array.isArray(value)) throw new TypeError(`${label} must be an array`);
  return value.map((item, index) => text(item, `${label}[${index}]`));
}

function sha256(value: unknown, label: string): string {
  const observed = text(value, label);
  if (!/^[0-9a-f]{64}$/.test(observed)) throw new TypeError(`${label} must be a lowercase SHA-256`);
  return observed;
}

function fact(value: unknown, label: string): Round3ViewFactV1 {
  const item = record(value, label);
  closed(item, ["label", "value"], label);
  return { label: text(item.label, `${label}.label`), value: text(item.value, `${label}.value`) };
}

function facts(value: unknown, label: string): readonly Round3ViewFactV1[] {
  if (!Array.isArray(value)) throw new TypeError(`${label} must be an array`);
  return value.map((item, index) => fact(item, `${label}[${index}]`));
}

function rendererPayload(value: unknown): Round3RendererPayloadV1 {
  const item = record(value, "renderer_payload");
  const renderer = text(item.renderer, "renderer_payload.renderer");
  if (renderer === "details") {
    closed(item, ["renderer", "entries"], "details renderer");
    return { renderer, entries: facts(item.entries, "renderer_payload.entries") };
  }
  if (renderer === "table") {
    closed(item, ["renderer", "columns", "rows"], "table renderer");
    const columns = stringArray(item.columns, "renderer_payload.columns");
    if (!Array.isArray(item.rows)) throw new TypeError("renderer_payload.rows must be an array");
    const rows = item.rows.map((row, index) => stringArray(row, `renderer_payload.rows[${index}]`));
    if (rows.some((row) => row.length !== columns.length)) throw new TypeError("table rows must match the closed column count");
    return { renderer, columns, rows };
  }
  if (renderer === "backtest-result") {
    closed(item, ["renderer", "resultId", "runSpecId", "nav", "fillCount", "diagnosticCount", "cashLedgerSummary", "feeLedgerSummary"], "backtest-result renderer");
    const nav = record(item.nav, "renderer_payload.nav");
    closed(nav, ["columns", "rows"], "backtest-result nav");
    const columns = stringArray(nav.columns, "renderer_payload.nav.columns");
    if (columns.length !== 2 || columns[0] !== "Session date" || columns[1] !== "NAV") throw new TypeError("backtest-result NAV columns are closed");
    if (!Array.isArray(nav.rows)) throw new TypeError("backtest-result NAV rows must be an array");
    const rows = nav.rows.map((row, index) => {
      const values = stringArray(row, `renderer_payload.nav.rows[${index}]`);
      if (values.length !== 2) throw new TypeError("backtest-result NAV row must have two cells");
      return [values[0]!, values[1]!] as const;
    });
    if (!Number.isInteger(item.fillCount) || Number(item.fillCount) < 0 || !Number.isInteger(item.diagnosticCount) || Number(item.diagnosticCount) < 0) {
      throw new TypeError("backtest-result counts must be non-negative integers");
    }
    return {
      renderer,
      resultId: text(item.resultId, "renderer_payload.resultId"),
      runSpecId: text(item.runSpecId, "renderer_payload.runSpecId"),
      nav: { columns: ["Session date", "NAV"], rows },
      fillCount: Number(item.fillCount),
      diagnosticCount: Number(item.diagnosticCount),
      cashLedgerSummary: text(item.cashLedgerSummary, "renderer_payload.cashLedgerSummary"),
      feeLedgerSummary: text(item.feeLedgerSummary, "renderer_payload.feeLedgerSummary")
    };
  }
  throw new TypeError(`unknown Round 3 renderer: ${renderer}`);
}

function projection(value: unknown): CanonicalEvidenceProjectionV1 {
  const item = record(value, "projection");
  closed(item, [
    "projection_schema_version", "source_artifact_type", "source_object_id", "source_content_sha256",
    "canonical_truth_state", "canonical_admission_state", "validation_state", "provenance_refs",
    "lineage_refs", "view_facts", "renderer_key", "renderer_payload"
  ], "projection");
  if (item.projection_schema_version !== ROUND3_PROJECTION_SCHEMA_VERSION) throw new TypeError("unsupported Round 3 projection schema");
  if (!ROUND3_EVIDENCE_KINDS.includes(item.source_artifact_type as Round3EvidenceKind)) throw new TypeError("unknown Round 3 evidence kind");
  const kind = item.source_artifact_type as Round3EvidenceKind;
  const contentHash = sha256(item.source_content_sha256, "projection.source_content_sha256");
  const objectId = text(item.source_object_id, "projection.source_object_id");
  if (objectId !== OBJECT_PREFIX[kind] + contentHash) throw new TypeError("projection source ID/hash mismatch");
  if (!["UNKNOWN", "NOT_FORMAL", "FORMAL"].includes(String(item.canonical_truth_state))) throw new TypeError("unknown canonical truth state");
  if (!["UNKNOWN", "PRE_ALPHA", "FORMAL_ADMITTED"].includes(String(item.canonical_admission_state))) throw new TypeError("unknown canonical admission state");
  if (!["NOT_RUN", "FAILED", "PASSED"].includes(String(item.validation_state))) throw new TypeError("unknown canonical validation state");
  const payload = rendererPayload(item.renderer_payload);
  if (item.renderer_key !== payload.renderer) throw new TypeError("projection renderer key/payload mismatch");
  return {
    projection_schema_version: ROUND3_PROJECTION_SCHEMA_VERSION,
    source_artifact_type: kind,
    source_object_id: objectId,
    source_content_sha256: contentHash,
    canonical_truth_state: item.canonical_truth_state as CanonicalTruthState,
    canonical_admission_state: item.canonical_admission_state as CanonicalAdmissionState,
    validation_state: item.validation_state as CanonicalValidationState,
    provenance_refs: stringArray(item.provenance_refs, "projection.provenance_refs"),
    lineage_refs: stringArray(item.lineage_refs, "projection.lineage_refs"),
    view_facts: facts(item.view_facts, "projection.view_facts"),
    renderer_key: payload.renderer,
    renderer_payload: payload
  };
}

function edge(value: unknown): Round3LineageEdgeV1 {
  const item = record(value, "lineage edge");
  closed(item, ["source_object_id", "source_content_sha256", "target_object_id", "target_content_sha256", "relation", "binding_object_id"], "lineage edge");
  if (!EDGE_RELATIONS.has(String(item.relation))) throw new TypeError("unknown Round 3 lineage relation");
  if (item.binding_object_id !== null && typeof item.binding_object_id !== "string") throw new TypeError("lineage binding_object_id must be string or null");
  return {
    source_object_id: text(item.source_object_id, "lineage source ID"),
    source_content_sha256: sha256(item.source_content_sha256, "lineage source hash"),
    target_object_id: text(item.target_object_id, "lineage target ID"),
    target_content_sha256: sha256(item.target_content_sha256, "lineage target hash"),
    relation: item.relation as Round3LineageEdgeV1["relation"],
    binding_object_id: item.binding_object_id as string | null
  };
}

function requireEdge(edges: readonly Round3LineageEdgeV1[], source: CanonicalEvidenceProjectionV1, target: CanonicalEvidenceProjectionV1, relation: Round3LineageEdgeV1["relation"]): void {
  const match = edges.find((item) => item.source_object_id === source.source_object_id && item.target_object_id === target.source_object_id && item.relation === relation);
  if (!match || match.source_content_sha256 !== source.source_content_sha256 || match.target_content_sha256 !== target.source_content_sha256) {
    throw new TypeError(`missing exact Round 3 lineage edge ${relation}`);
  }
}

export function parseRound3ResearchEvidenceBundle(value: unknown): Round3ResearchEvidenceBundleV1 {
  const item = record(value, "Round 3 evidence bundle");
  closed(item, ["bundle_schema_version", "session_view_id", "source_mode", "projections", "lineage_edges"], "Round 3 evidence bundle");
  if (item.bundle_schema_version !== ROUND3_BUNDLE_SCHEMA_VERSION) throw new TypeError("unsupported Round 3 bundle schema");
  if (!Array.isArray(item.projections) || !Array.isArray(item.lineage_edges)) throw new TypeError("Round 3 projections/edges must be arrays");
  const projections = item.projections.map(projection);
  if (projections.length !== ROUND3_EVIDENCE_KINDS.length || projections.some((value, index) => value.source_artifact_type !== ROUND3_EVIDENCE_KINDS[index])) {
    throw new TypeError("Round 3 projection kind order is closed and deterministic");
  }
  if (!new Set(["LIVE_READ_ONLY", "DEVELOPMENT_INTEGRATION_FIXTURE"]).has(String(item.source_mode))) throw new TypeError("unknown Round 3 evidence source mode");
  const edges = item.lineage_edges.map(edge);
  const [intent, target, adjusted, report, spec, result] = projections as [CanonicalEvidenceProjectionV1, CanonicalEvidenceProjectionV1, CanonicalEvidenceProjectionV1, CanonicalEvidenceProjectionV1, CanonicalEvidenceProjectionV1, CanonicalEvidenceProjectionV1];
  requireEdge(edges, intent, target, "PORTFOLIO_INTENT_SOURCE");
  requireEdge(edges, target, adjusted, "RISK_APPLICATION_TARGET_BINDING");
  requireEdge(edges, target, report, "RISK_DECISION_TARGET_BINDING");
  requireEdge(edges, report, adjusted, "RISK_DECISION_OUTPUT_BINDING");
  requireEdge(edges, adjusted, spec, "SCHEDULED_WEIGHTS_VECTOR");
  requireEdge(edges, spec, result, "BACKTEST_RUN_SPEC_RESULT_BINDING");
  if (edges.length !== 6) throw new TypeError("Round 3 lineage edge set is closed");
  return {
    bundle_schema_version: ROUND3_BUNDLE_SCHEMA_VERSION,
    session_view_id: text(item.session_view_id, "bundle.session_view_id"),
    source_mode: item.source_mode as Round3EvidenceSourceMode,
    projections,
    lineage_edges: edges
  };
}
