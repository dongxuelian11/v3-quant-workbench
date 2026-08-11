import type {
  DisplayNormalization,
  EvidenceField,
  ResearchViewSelector
} from "../../../../../packages/contracts/src/generativeResearchView";
import type { LabId } from "../../../../../packages/contracts/src/index";

const GENERATIVE_RESEARCH_VIEW_SCHEMA_VERSION = "v3.generative_research_view/1.0.0" as const;

export interface ResearchEvidenceProjection {
  readonly kind: string;
  readonly objectId: string;
  readonly title: string;
  readonly summary: string;
  readonly canonicalTruthState: string;
  readonly canonicalAdmissionState: string;
  readonly validationState: string;
  readonly provenanceRefs: readonly string[];
  readonly reviewerFinding: string | null;
  readonly facts: readonly { readonly label: string; readonly value: string }[];
  readonly openInLab: LabId;
  readonly artifactId: string | null;
}

export interface ResearchViewParseContext {
  readonly sessionViewId: string;
  readonly evidence: readonly ResearchEvidenceProjection[];
}

export interface ResolvedMetricGroupBlock {
  readonly type: "MetricGroup";
  readonly blockId: string;
  readonly title: string;
  readonly dataAuthority: "CANONICAL_EVIDENCE";
  readonly evidenceIds: readonly string[];
  readonly metrics: readonly { readonly label: string; readonly value: string; readonly sourceEvidenceId: string }[];
}

export interface ResolvedNarrativeBlock {
  readonly type: "Narrative";
  readonly blockId: string;
  readonly title: string;
  readonly dataAuthority: "AGENT_DRAFT_DERIVED";
  readonly authorityLabel: "NON_CANONICAL / DRAFT";
  readonly evidenceIds: readonly string[];
  readonly text: string;
}

export interface ResolvedEvidenceListBlock {
  readonly type: "EvidenceList";
  readonly blockId: string;
  readonly title: string;
  readonly dataAuthority: "CANONICAL_EVIDENCE";
  readonly evidenceIds: readonly string[];
  readonly items: readonly {
    readonly evidenceId: string;
    readonly openInLab: LabId;
    readonly values: readonly { readonly key: string; readonly label: string; readonly value: string }[];
  }[];
}

export interface ResolvedCalloutBlock {
  readonly type: "Callout";
  readonly blockId: string;
  readonly title: string;
  readonly dataAuthority: "AGENT_DRAFT_DERIVED";
  readonly authorityLabel: "NON_CANONICAL / DRAFT";
  readonly evidenceIds: readonly string[];
  readonly tone: "INFO" | "WARNING" | "BLOCKED";
  readonly text: string;
}

export interface ResolvedDataTableBlock {
  readonly type: "DataTable";
  readonly blockId: string;
  readonly title: string;
  readonly dataAuthority: "CANONICAL_EVIDENCE";
  readonly evidenceIds: readonly string[];
  readonly columns: readonly { readonly key: string; readonly header: string }[];
  readonly rows: readonly { readonly evidenceId: string; readonly cells: readonly string[] }[];
}

export interface ResolvedTimeSeriesChartBlock {
  readonly type: "TimeSeriesChart";
  readonly blockId: string;
  readonly title: string;
  readonly dataAuthority: "CANONICAL_EVIDENCE";
  readonly evidenceIds: readonly string[];
  readonly xLabel: string;
  readonly yLabel: string;
  readonly points: readonly { readonly x: string; readonly y: number; readonly sourceEvidenceId: string }[];
}

export interface ResolvedBarChartBlock {
  readonly type: "BarChart";
  readonly blockId: string;
  readonly title: string;
  readonly dataAuthority: "CANONICAL_EVIDENCE";
  readonly evidenceIds: readonly string[];
  readonly categoryLabel: string;
  readonly valueLabel: string;
  readonly bars: readonly { readonly category: string; readonly value: number; readonly sourceEvidenceId: string }[];
}

export type ResolvedResearchViewBlock = ResolvedNarrativeBlock | ResolvedMetricGroupBlock | ResolvedDataTableBlock | ResolvedTimeSeriesChartBlock | ResolvedBarChartBlock | ResolvedEvidenceListBlock | ResolvedCalloutBlock;

export interface ParsedResearchView {
  readonly status: "VALID" | "PARTIAL_INVALID" | "INVALID";
  readonly specId: string | null;
  readonly sessionViewId: string;
  readonly title: string;
  readonly blocks: readonly ResolvedResearchViewBlock[];
  readonly invalidBlocks: readonly { readonly blockId: string; readonly reason: string }[];
  readonly error: string | null;
}

const EVIDENCE_FIELDS = new Set<EvidenceField>([
  "objectId", "kind", "title", "summary", "canonicalTruthState", "canonicalAdmissionState", "validationState", "reviewerFinding", "openInLab", "artifactId"
]);
const NORMALIZATIONS = new Set<DisplayNormalization>(["NONE", "NUMBER", "PERCENT", "ISO_DATE"]);

export function parseResearchViewSpec(value: unknown, context: ResearchViewParseContext): ParsedResearchView {
  try {
    const envelope = record(value, "research view spec");
    exactKeys(envelope, ["schema_version", "spec_id", "session_view_id", "permission", "authority", "title", "blocks"], "research view spec");
    equal(envelope.schema_version, GENERATIVE_RESEARCH_VIEW_SCHEMA_VERSION, "unknown research view schema");
    equal(envelope.session_view_id, context.sessionViewId, "cross-session research view");
    equal(envelope.permission, "L1_DRAFT", "research view requires L1_DRAFT");
    equal(envelope.authority, "AGENT_DRAFT_PROPOSAL", "research view authority is invalid");
    const specId = text(envelope.spec_id, "spec_id");
    const title = safeText(envelope.title, "title");
    if (!Array.isArray(envelope.blocks) || envelope.blocks.length === 0 || envelope.blocks.length > 64) throw new TypeError("research view requires 1-64 blocks");
    const evidenceById = new Map(context.evidence.map((item) => [item.objectId, item]));
    const blocks: ResolvedResearchViewBlock[] = [];
    const invalidBlocks: { blockId: string; reason: string }[] = [];
    for (let index = 0; index < envelope.blocks.length; index += 1) {
      const candidate = envelope.blocks[index];
      try {
        blocks.push(parseBlock(candidate, evidenceById));
      } catch (error) {
        invalidBlocks.push({ blockId: candidateBlockId(candidate, index), reason: errorMessage(error) });
      }
    }
    return {
      status: invalidBlocks.length === 0 ? "VALID" : blocks.length === 0 ? "INVALID" : "PARTIAL_INVALID",
      specId,
      sessionViewId: context.sessionViewId,
      title,
      blocks,
      invalidBlocks,
      error: null
    };
  } catch (error) {
    return { status: "INVALID", specId: null, sessionViewId: context.sessionViewId, title: "Invalid structured research view", blocks: [], invalidBlocks: [], error: errorMessage(error) };
  }
}

function parseBlock(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedResearchViewBlock {
  const block = record(value, "research view block");
  if (block.type === "Narrative") return parseNarrative(block, evidenceById);
  if (block.type === "EvidenceList") return parseEvidenceList(block, evidenceById);
  if (block.type === "Callout") return parseCallout(block, evidenceById);
  if (block.type === "MetricGroup") return parseMetricGroup(block, evidenceById);
  if (block.type === "DataTable") return parseDataTable(block, evidenceById);
  if (block.type === "TimeSeriesChart") return parseTimeSeriesChart(block, evidenceById);
  if (block.type === "BarChart") return parseBarChart(block, evidenceById);
  throw new TypeError("unknown research view block");
}

function parseCallout(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedCalloutBlock {
  const block = record(value, "Callout");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "tone", "text"], "Callout");
  equal(block.data_authority, "AGENT_DRAFT_DERIVED", "Callout requires AGENT_DRAFT_DERIVED");
  if (block.tone !== "INFO" && block.tone !== "WARNING" && block.tone !== "BLOCKED") throw new TypeError("Callout tone is invalid");
  return {
    type: "Callout",
    blockId: text(block.block_id, "block_id"),
    title: safeText(block.title, "block title"),
    dataAuthority: "AGENT_DRAFT_DERIVED",
    authorityLabel: "NON_CANONICAL / DRAFT",
    evidenceIds: declaredEvidenceIds(block.evidence_ids, evidenceById, "Callout"),
    tone: block.tone,
    text: safeText(block.text, "Callout text")
  };
}

function parseEvidenceList(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedEvidenceListBlock {
  const block = record(value, "EvidenceList");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "fields"], "EvidenceList");
  equal(block.data_authority, "CANONICAL_EVIDENCE", "EvidenceList requires CANONICAL_EVIDENCE");
  const evidenceIds = declaredEvidenceIds(block.evidence_ids, evidenceById, "EvidenceList");
  if (!Array.isArray(block.fields) || block.fields.length === 0 || block.fields.length > 10) throw new TypeError("EvidenceList requires 1-10 fields");
  const fields = block.fields.map((value) => {
    const field = record(value, "EvidenceList field");
    exactKeys(field, ["key", "label", "selector"], "EvidenceList field");
    return { key: text(field.key, "field key"), label: safeText(field.label, "field label"), selector: parseSelector(field.selector) };
  });
  if (new Set(fields.map((item) => item.key)).size !== fields.length) throw new TypeError("EvidenceList field keys must be unique");
  return {
    type: "EvidenceList",
    blockId: text(block.block_id, "block_id"),
    title: safeText(block.title, "block title"),
    dataAuthority: "CANONICAL_EVIDENCE",
    evidenceIds,
    items: evidenceIds.map((evidenceId) => {
      const evidence = requireEvidence(evidenceById, evidenceId);
      return {
        evidenceId,
        openInLab: evidence.openInLab,
        values: fields.map((field) => ({ key: field.key, label: field.label, value: selectValue(evidence, field.selector) }))
      };
    })
  };
}

function parseNarrative(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedNarrativeBlock {
  const block = record(value, "Narrative");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "text"], "Narrative");
  equal(block.data_authority, "AGENT_DRAFT_DERIVED", "Narrative requires AGENT_DRAFT_DERIVED");
  const evidenceIds = declaredEvidenceIds(block.evidence_ids, evidenceById, "Narrative");
  return {
    type: "Narrative",
    blockId: text(block.block_id, "block_id"),
    title: safeText(block.title, "block title"),
    dataAuthority: "AGENT_DRAFT_DERIVED",
    authorityLabel: "NON_CANONICAL / DRAFT",
    evidenceIds,
    text: safeText(block.text, "Narrative text")
  };
}

function parseBarChart(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedBarChartBlock {
  const block = record(value, "BarChart");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "category_label", "value_label", "bars", "sort", "top_n"], "BarChart");
  equal(block.data_authority, "CANONICAL_EVIDENCE", "BarChart requires CANONICAL_EVIDENCE");
  const evidenceIds = declaredEvidenceIds(block.evidence_ids, evidenceById, "BarChart");
  if (!Array.isArray(block.bars) || block.bars.length === 0 || block.bars.length > 100) throw new TypeError("BarChart requires 1-100 bars");
  let bars = block.bars.map((value) => {
    const bar = record(value, "BarChart bar");
    exactKeys(bar, ["evidence_id", "category_selector", "value_selector"], "BarChart bar");
    const evidenceId = text(bar.evidence_id, "bar evidence_id");
    if (!evidenceIds.includes(evidenceId)) throw new TypeError(`bar evidence ${evidenceId} is not declared by block`);
    const evidence = requireEvidence(evidenceById, evidenceId);
    const categorySelector = parseSelector(bar.category_selector);
    const valueSelector = parseSelector(bar.value_selector);
    if (valueSelector.normalization !== "NUMBER") throw new TypeError("BarChart value selector requires NUMBER normalization");
    const numericValue = Number(selectValue(evidence, valueSelector));
    if (!Number.isFinite(numericValue)) throw new TypeError("BarChart value must be finite");
    return { category: selectValue(evidence, categorySelector), value: numericValue, sourceEvidenceId: evidenceId };
  });
  if (block.sort === "VALUE_ASC") bars = [...bars].sort((left, right) => left.value - right.value || left.sourceEvidenceId.localeCompare(right.sourceEvidenceId));
  else if (block.sort === "VALUE_DESC") bars = [...bars].sort((left, right) => right.value - left.value || left.sourceEvidenceId.localeCompare(right.sourceEvidenceId));
  else if (block.sort !== "INPUT") throw new TypeError("BarChart sort is invalid");
  if (block.top_n !== null) {
    if (!Number.isInteger(block.top_n) || (block.top_n as number) < 1 || (block.top_n as number) > 50) throw new TypeError("BarChart top_n must be an integer from 1 to 50");
    bars = bars.slice(0, block.top_n as number);
  }
  return {
    type: "BarChart",
    blockId: text(block.block_id, "block_id"),
    title: safeText(block.title, "block title"),
    dataAuthority: "CANONICAL_EVIDENCE",
    evidenceIds,
    categoryLabel: safeText(block.category_label, "category_label"),
    valueLabel: safeText(block.value_label, "value_label"),
    bars
  };
}

function parseTimeSeriesChart(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedTimeSeriesChartBlock {
  const block = record(value, "TimeSeriesChart");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "x_label", "y_label", "points", "date_window"], "TimeSeriesChart");
  equal(block.data_authority, "CANONICAL_EVIDENCE", "TimeSeriesChart requires CANONICAL_EVIDENCE");
  const evidenceIds = declaredEvidenceIds(block.evidence_ids, evidenceById, "TimeSeriesChart");
  if (!Array.isArray(block.points) || block.points.length === 0 || block.points.length > 200) throw new TypeError("TimeSeriesChart requires 1-200 points");
  let start = Number.NEGATIVE_INFINITY;
  let end = Number.POSITIVE_INFINITY;
  if (block.date_window !== null) {
    const window = record(block.date_window, "TimeSeriesChart date_window");
    exactKeys(window, ["start", "end"], "TimeSeriesChart date_window");
    start = parsedDate(window.start, "date_window start");
    end = parsedDate(window.end, "date_window end");
    if (start > end) throw new TypeError("TimeSeriesChart date_window start must not exceed end");
  }
  const points = block.points.map((value) => {
    const point = record(value, "TimeSeriesChart point");
    exactKeys(point, ["evidence_id", "x_selector", "y_selector"], "TimeSeriesChart point");
    const evidenceId = text(point.evidence_id, "point evidence_id");
    if (!evidenceIds.includes(evidenceId)) throw new TypeError(`point evidence ${evidenceId} is not declared by block`);
    const evidence = requireEvidence(evidenceById, evidenceId);
    const xSelector = parseSelector(point.x_selector);
    const ySelector = parseSelector(point.y_selector);
    if (xSelector.normalization !== "ISO_DATE") throw new TypeError("TimeSeriesChart x selector requires ISO_DATE normalization");
    if (ySelector.normalization !== "NUMBER") throw new TypeError("TimeSeriesChart y selector requires NUMBER normalization");
    const x = selectValue(evidence, xSelector);
    const y = Number(selectValue(evidence, ySelector));
    if (!Number.isFinite(y)) throw new TypeError("TimeSeriesChart y value must be finite");
    return { x, y, sourceEvidenceId: evidenceId };
  }).filter((point) => {
    const timestamp = Date.parse(point.x);
    return timestamp >= start && timestamp <= end;
  }).sort((left, right) => Date.parse(left.x) - Date.parse(right.x) || left.sourceEvidenceId.localeCompare(right.sourceEvidenceId));
  if (points.length === 0) throw new TypeError("TimeSeriesChart date window resolved no evidence points");
  return {
    type: "TimeSeriesChart",
    blockId: text(block.block_id, "block_id"),
    title: safeText(block.title, "block title"),
    dataAuthority: "CANONICAL_EVIDENCE",
    evidenceIds,
    xLabel: safeText(block.x_label, "x_label"),
    yLabel: safeText(block.y_label, "y_label"),
    points
  };
}

function parseMetricGroup(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedMetricGroupBlock {
  const block = record(value, "research view block");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "metrics"], "MetricGroup");
  equal(block.type, "MetricGroup", "unknown research view block");
  equal(block.data_authority, "CANONICAL_EVIDENCE", "MetricGroup requires CANONICAL_EVIDENCE");
  const evidenceIds = stringArray(block.evidence_ids, "evidence_ids");
  if (evidenceIds.length === 0) throw new TypeError("MetricGroup requires evidence_ids");
  for (const evidenceId of evidenceIds) requireEvidence(evidenceById, evidenceId);
  if (!Array.isArray(block.metrics) || block.metrics.length === 0 || block.metrics.length > 32) throw new TypeError("MetricGroup requires 1-32 metrics");
  const metrics = block.metrics.map((value) => {
    const metric = record(value, "metric");
    exactKeys(metric, ["label", "evidence_id", "selector"], "metric");
    const evidenceId = text(metric.evidence_id, "metric evidence_id");
    if (!evidenceIds.includes(evidenceId)) throw new TypeError(`metric evidence ${evidenceId} is not declared by block`);
    const evidence = requireEvidence(evidenceById, evidenceId);
    return { label: safeText(metric.label, "metric label"), value: selectValue(evidence, parseSelector(metric.selector)), sourceEvidenceId: evidenceId };
  });
  return {
    type: "MetricGroup",
    blockId: text(block.block_id, "block_id"),
    title: safeText(block.title, "block title"),
    dataAuthority: "CANONICAL_EVIDENCE",
    evidenceIds,
    metrics
  };
}

function parseDataTable(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedDataTableBlock {
  const block = record(value, "DataTable");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "columns", "rows", "sort", "top_n"], "DataTable");
  equal(block.data_authority, "CANONICAL_EVIDENCE", "DataTable requires CANONICAL_EVIDENCE");
  const evidenceIds = declaredEvidenceIds(block.evidence_ids, evidenceById, "DataTable");
  if (!Array.isArray(block.columns) || block.columns.length === 0 || block.columns.length > 20) throw new TypeError("DataTable requires 1-20 columns");
  const parsedColumns = block.columns.map((value) => {
    const column = record(value, "DataTable column");
    exactKeys(column, ["key", "header", "selector"], "DataTable column");
    return { key: text(column.key, "column key"), header: safeText(column.header, "column header"), selector: parseSelector(column.selector) };
  });
  if (new Set(parsedColumns.map((item) => item.key)).size !== parsedColumns.length) throw new TypeError("DataTable column keys must be unique");
  if (!Array.isArray(block.rows) || block.rows.length === 0 || block.rows.length > 500) throw new TypeError("DataTable requires 1-500 evidence rows");
  let rows = block.rows.map((value) => {
    const row = record(value, "DataTable row");
    exactKeys(row, ["evidence_id"], "DataTable row");
    const evidenceId = text(row.evidence_id, "row evidence_id");
    if (!evidenceIds.includes(evidenceId)) throw new TypeError(`row evidence ${evidenceId} is not declared by block`);
    const evidence = requireEvidence(evidenceById, evidenceId);
    return { evidenceId, cells: parsedColumns.map((column) => selectValue(evidence, column.selector)) };
  });
  if (block.sort !== null) {
    const sort = record(block.sort, "DataTable sort");
    exactKeys(sort, ["column_key", "direction"], "DataTable sort");
    const columnKey = text(sort.column_key, "sort column_key");
    const columnIndex = parsedColumns.findIndex((item) => item.key === columnKey);
    if (columnIndex < 0) throw new TypeError("DataTable sort references an unknown column");
    if (sort.direction !== "ASC" && sort.direction !== "DESC") throw new TypeError("DataTable sort direction is invalid");
    const multiplier = sort.direction === "ASC" ? 1 : -1;
    rows = [...rows].sort((left, right) => multiplier * compareDisplayValues(left.cells[columnIndex], right.cells[columnIndex]) || left.evidenceId.localeCompare(right.evidenceId));
  }
  if (block.top_n !== null) {
    if (!Number.isInteger(block.top_n) || (block.top_n as number) < 1 || (block.top_n as number) > 100) throw new TypeError("DataTable top_n must be an integer from 1 to 100");
    rows = rows.slice(0, block.top_n as number);
  }
  return {
    type: "DataTable",
    blockId: text(block.block_id, "block_id"),
    title: safeText(block.title, "block title"),
    dataAuthority: "CANONICAL_EVIDENCE",
    evidenceIds,
    columns: parsedColumns.map(({ key, header }) => ({ key, header })),
    rows
  };
}

function parseSelector(value: unknown): ResearchViewSelector {
  const selector = record(value, "selector");
  if (selector.kind === "EVIDENCE_FIELD") {
    exactKeys(selector, ["kind", "field", "normalization"], "EVIDENCE_FIELD selector");
    if (typeof selector.field !== "string" || !EVIDENCE_FIELDS.has(selector.field as EvidenceField)) throw new TypeError("unknown evidence field selector");
    return { kind: "EVIDENCE_FIELD", field: selector.field as EvidenceField, normalization: normalization(selector.normalization) };
  }
  if (selector.kind === "FACT") {
    exactKeys(selector, ["kind", "label", "normalization"], "FACT selector");
    return { kind: "FACT", label: safeText(selector.label, "fact label"), normalization: normalization(selector.normalization) };
  }
  throw new TypeError("unknown selector");
}

function selectValue(evidence: ResearchEvidenceProjection, selector: ResearchViewSelector): string {
  let raw: string | null;
  if (selector.kind === "FACT") raw = evidence.facts.find((fact) => fact.label === selector.label)?.value ?? null;
  else {
    const selected = evidence[selector.field];
    raw = typeof selected === "string" ? selected : null;
  }
  if (raw === null) throw new TypeError("selector did not resolve current-session evidence");
  return normalize(raw, selector.normalization);
}

function normalize(value: string, mode: DisplayNormalization): string {
  if (mode === "NONE") return value;
  if (mode === "NUMBER") {
    const stripped = value.replaceAll(",", "");
    if (!/^-?(?:\d+\.?\d*|\.\d+)$/.test(stripped) || !Number.isFinite(Number(stripped))) throw new TypeError("NUMBER normalization requires a finite numeric evidence value");
    return stripped;
  }
  if (mode === "PERCENT") {
    const stripped = value.endsWith("%") ? value.slice(0, -1) : value;
    if (!/^-?(?:\d+\.?\d*|\.\d+)$/.test(stripped) || !Number.isFinite(Number(stripped))) throw new TypeError("PERCENT normalization requires a finite numeric evidence value");
    return `${stripped}%`;
  }
  if (Number.isNaN(Date.parse(value))) throw new TypeError("ISO_DATE normalization requires an ISO date evidence value");
  return new Date(value).toISOString();
}

function requireEvidence(evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>, evidenceId: string): ResearchEvidenceProjection {
  const evidence = evidenceById.get(evidenceId);
  if (!evidence) throw new TypeError(`evidence ${evidenceId} is not bound to the active session`);
  return evidence;
}

function declaredEvidenceIds(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>, label: string): string[] {
  const evidenceIds = stringArray(value, "evidence_ids");
  if (evidenceIds.length === 0) throw new TypeError(`${label} requires evidence_ids`);
  for (const evidenceId of evidenceIds) requireEvidence(evidenceById, evidenceId);
  return evidenceIds;
}

function compareDisplayValues(left: string, right: string): number {
  const leftNumber = Number(left.replaceAll(",", "").replace(/%$/, ""));
  const rightNumber = Number(right.replaceAll(",", "").replace(/%$/, ""));
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return leftNumber - rightNumber;
  return left.localeCompare(right);
}

function parsedDate(value: unknown, label: string): number {
  const source = text(value, label);
  const timestamp = Date.parse(source);
  if (Number.isNaN(timestamp)) throw new TypeError(`${label} must be an ISO date`);
  return timestamp;
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || Array.isArray(value) || typeof value !== "object") throw new TypeError(`${label} must be an object`);
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new TypeError(`${label} fields do not match the closed schema`);
}

function equal(actual: unknown, expected: string, message: string): void {
  if (actual !== expected) throw new TypeError(message);
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 512) throw new TypeError(`${label} must be a bounded non-empty string`);
  return value;
}

function safeText(value: unknown, label: string): string {
  const result = text(value, label);
  if (/<\/?[a-z][^>]*>/i.test(result) || /javascript\s*:/i.test(result)) throw new TypeError(`${label} contains forbidden markup or script`);
  return result;
}

function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.length === 0)) throw new TypeError(`${label} must be a string array`);
  if (new Set(value).size !== value.length) throw new TypeError(`${label} must not contain duplicates`);
  return [...value];
}

function normalization(value: unknown): DisplayNormalization {
  if (typeof value !== "string" || !NORMALIZATIONS.has(value as DisplayNormalization)) throw new TypeError("unknown display normalization");
  return value as DisplayNormalization;
}

function candidateBlockId(value: unknown, index: number): string {
  if (value && typeof value === "object" && !Array.isArray(value) && typeof (value as Record<string, unknown>).block_id === "string") return (value as Record<string, string>).block_id;
  return `block-${index + 1}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "invalid structured research view";
}
