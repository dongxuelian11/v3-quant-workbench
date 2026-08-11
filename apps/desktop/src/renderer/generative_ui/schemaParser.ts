import type {
  DisplayNormalization,
  EvidenceField,
  ResearchViewSelector
} from "../../../../../packages/contracts/src/generativeResearchView";
import type { LabId } from "../../../../../packages/contracts/src/index";

const GENERATIVE_RESEARCH_VIEW_SCHEMA_VERSION = "v3.generative_research_view/1.0.0" as const;
// Keep this runtime parser table byte-for-byte aligned with the exported Track M
// contract constants. The renderer compiles as CommonJS, while the contract is
// also executed directly by Node's TypeScript test runner, so a runtime TS import
// would make one of those two consumers depend on extension-specific resolution.
const GENERATIVE_RESEARCH_VIEW_LIMITS = Object.freeze({
  SHORT_TEXT_MAX: 256,
  BOUNDED_TEXT_MAX: 4096,
  MAX_BLOCKS: 64,
  MAX_EVIDENCE_IDS_PER_BLOCK: 128,
  MAX_METRICS: 32,
  MAX_TABLE_COLUMNS: 20,
  MAX_TABLE_ROWS: 500,
  MAX_TIME_SERIES_POINTS: 200,
  MAX_BAR_POINTS: 100,
  MAX_EVIDENCE_LIST_FIELDS: 10
} as const);
const GENERATIVE_RESEARCH_VIEW_EVIDENCE_ID_PATTERN = "^[a-z][a-z0-9_]*_sha256_[0-9a-f]{64}$";

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
const NORMALIZATIONS = new Set<DisplayNormalization>(["NONE", "NUMBER", "ISO_DATE"]);
const EVIDENCE_ID_PATTERN = new RegExp(GENERATIVE_RESEARCH_VIEW_EVIDENCE_ID_PATTERN);
const ISO_DATE_ONLY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_TIMESTAMP_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|([+-])(\d{2}):(\d{2}))$/;

export function parseResearchViewSpec(value: unknown, context: ResearchViewParseContext): ParsedResearchView {
  try {
    const envelope = record(value, "research view spec");
    exactKeys(envelope, ["schema_version", "spec_id", "session_view_id", "permission", "authority", "title", "blocks"], "research view spec");
    equal(envelope.schema_version, GENERATIVE_RESEARCH_VIEW_SCHEMA_VERSION, "unknown research view schema");
    equal(envelope.session_view_id, context.sessionViewId, "cross-session research view");
    equal(envelope.permission, "L1_DRAFT", "research view requires L1_DRAFT");
    equal(envelope.authority, "AGENT_DRAFT_PROPOSAL", "research view authority is invalid");
    const specId = shortText(envelope.spec_id, "spec_id");
    shortText(envelope.session_view_id, "session_view_id");
    const title = safeShortText(envelope.title, "title");
    if (!Array.isArray(envelope.blocks) || envelope.blocks.length === 0 || envelope.blocks.length > GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_BLOCKS) throw new TypeError(`research view requires 1-${GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_BLOCKS} blocks`);
    const blockIds = envelope.blocks.flatMap((candidate) => {
      if (candidate === null || Array.isArray(candidate) || typeof candidate !== "object") return [];
      const value = (candidate as Record<string, unknown>).block_id;
      return typeof value === "string" ? [shortText(value, "block_id")] : [];
    });
    if (new Set(blockIds).size !== blockIds.length) throw new TypeError("ResearchViewSpec block_id values must be unique");
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
    blockId: shortText(block.block_id, "block_id"),
    title: safeShortText(block.title, "block title"),
    dataAuthority: "AGENT_DRAFT_DERIVED",
    authorityLabel: "NON_CANONICAL / DRAFT",
    evidenceIds: declaredEvidenceIds(block.evidence_ids, evidenceById, "Callout"),
    tone: block.tone,
    text: safeBoundedText(block.text, "Callout text")
  };
}

function parseEvidenceList(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedEvidenceListBlock {
  const block = record(value, "EvidenceList");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "fields"], "EvidenceList");
  equal(block.data_authority, "CANONICAL_EVIDENCE", "EvidenceList requires CANONICAL_EVIDENCE");
  const evidenceIds = declaredEvidenceIds(block.evidence_ids, evidenceById, "EvidenceList");
  if (!Array.isArray(block.fields) || block.fields.length === 0 || block.fields.length > GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_EVIDENCE_LIST_FIELDS) throw new TypeError(`EvidenceList requires 1-${GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_EVIDENCE_LIST_FIELDS} fields`);
  const fields = block.fields.map((value) => {
    const field = record(value, "EvidenceList field");
    exactKeys(field, ["key", "label", "selector"], "EvidenceList field");
    return { key: shortText(field.key, "field key"), label: safeShortText(field.label, "field label"), selector: parseSelector(field.selector) };
  });
  if (new Set(fields.map((item) => item.key)).size !== fields.length) throw new TypeError("EvidenceList field keys must be unique");
  return {
    type: "EvidenceList",
    blockId: shortText(block.block_id, "block_id"),
    title: safeShortText(block.title, "block title"),
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
    blockId: shortText(block.block_id, "block_id"),
    title: safeShortText(block.title, "block title"),
    dataAuthority: "AGENT_DRAFT_DERIVED",
    authorityLabel: "NON_CANONICAL / DRAFT",
    evidenceIds,
    text: safeBoundedText(block.text, "Narrative text")
  };
}

function parseBarChart(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedBarChartBlock {
  const block = record(value, "BarChart");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "category_label", "value_label", "bars", "sort", "top_n"], "BarChart");
  equal(block.data_authority, "CANONICAL_EVIDENCE", "BarChart requires CANONICAL_EVIDENCE");
  const evidenceIds = declaredEvidenceIds(block.evidence_ids, evidenceById, "BarChart");
  if (!Array.isArray(block.bars) || block.bars.length === 0 || block.bars.length > GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_BAR_POINTS) throw new TypeError(`BarChart requires 1-${GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_BAR_POINTS} bars`);
  let bars = block.bars.map((value) => {
    const bar = record(value, "BarChart bar");
    exactKeys(bar, ["evidence_id", "category_selector", "value_selector"], "BarChart bar");
    const evidenceId = parseEvidenceId(bar.evidence_id, "bar evidence_id");
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
    blockId: shortText(block.block_id, "block_id"),
    title: safeShortText(block.title, "block title"),
    dataAuthority: "CANONICAL_EVIDENCE",
    evidenceIds,
    categoryLabel: safeShortText(block.category_label, "category_label"),
    valueLabel: safeShortText(block.value_label, "value_label"),
    bars
  };
}

function parseTimeSeriesChart(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedTimeSeriesChartBlock {
  const block = record(value, "TimeSeriesChart");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "x_label", "y_label", "points", "date_window"], "TimeSeriesChart");
  equal(block.data_authority, "CANONICAL_EVIDENCE", "TimeSeriesChart requires CANONICAL_EVIDENCE");
  const evidenceIds = declaredEvidenceIds(block.evidence_ids, evidenceById, "TimeSeriesChart");
  if (!Array.isArray(block.points) || block.points.length === 0 || block.points.length > GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_TIME_SERIES_POINTS) throw new TypeError(`TimeSeriesChart requires 1-${GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_TIME_SERIES_POINTS} points`);
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
    const evidenceId = parseEvidenceId(point.evidence_id, "point evidence_id");
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
    const timestamp = parseStrictIsoTemporal(point.x, "TimeSeriesChart x value").sortKey;
    return timestamp >= start && timestamp <= end;
  }).sort((left, right) => parseStrictIsoTemporal(left.x, "TimeSeriesChart x value").sortKey - parseStrictIsoTemporal(right.x, "TimeSeriesChart x value").sortKey || left.sourceEvidenceId.localeCompare(right.sourceEvidenceId));
  if (points.length === 0) throw new TypeError("TimeSeriesChart date window resolved no evidence points");
  return {
    type: "TimeSeriesChart",
    blockId: shortText(block.block_id, "block_id"),
    title: safeShortText(block.title, "block title"),
    dataAuthority: "CANONICAL_EVIDENCE",
    evidenceIds,
    xLabel: safeShortText(block.x_label, "x_label"),
    yLabel: safeShortText(block.y_label, "y_label"),
    points
  };
}

function parseMetricGroup(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>): ResolvedMetricGroupBlock {
  const block = record(value, "research view block");
  exactKeys(block, ["type", "block_id", "title", "data_authority", "evidence_ids", "metrics"], "MetricGroup");
  equal(block.type, "MetricGroup", "unknown research view block");
  equal(block.data_authority, "CANONICAL_EVIDENCE", "MetricGroup requires CANONICAL_EVIDENCE");
  const evidenceIds = declaredEvidenceIds(block.evidence_ids, evidenceById, "MetricGroup");
  if (!Array.isArray(block.metrics) || block.metrics.length === 0 || block.metrics.length > GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_METRICS) throw new TypeError(`MetricGroup requires 1-${GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_METRICS} metrics`);
  const metrics = block.metrics.map((value) => {
    const metric = record(value, "metric");
    exactKeys(metric, ["label", "evidence_id", "selector"], "metric");
    const evidenceId = parseEvidenceId(metric.evidence_id, "metric evidence_id");
    if (!evidenceIds.includes(evidenceId)) throw new TypeError(`metric evidence ${evidenceId} is not declared by block`);
    const evidence = requireEvidence(evidenceById, evidenceId);
    return { label: safeShortText(metric.label, "metric label"), value: selectValue(evidence, parseSelector(metric.selector)), sourceEvidenceId: evidenceId };
  });
  return {
    type: "MetricGroup",
    blockId: shortText(block.block_id, "block_id"),
    title: safeShortText(block.title, "block title"),
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
  if (!Array.isArray(block.columns) || block.columns.length === 0 || block.columns.length > GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_TABLE_COLUMNS) throw new TypeError(`DataTable requires 1-${GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_TABLE_COLUMNS} columns`);
  const parsedColumns = block.columns.map((value) => {
    const column = record(value, "DataTable column");
    exactKeys(column, ["key", "header", "selector"], "DataTable column");
    return { key: shortText(column.key, "column key"), header: safeShortText(column.header, "column header"), selector: parseSelector(column.selector) };
  });
  if (new Set(parsedColumns.map((item) => item.key)).size !== parsedColumns.length) throw new TypeError("DataTable column keys must be unique");
  if (!Array.isArray(block.rows) || block.rows.length === 0 || block.rows.length > GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_TABLE_ROWS) throw new TypeError(`DataTable requires 1-${GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_TABLE_ROWS} evidence rows`);
  let rows = block.rows.map((value) => {
    const row = record(value, "DataTable row");
    exactKeys(row, ["evidence_id"], "DataTable row");
    const evidenceId = parseEvidenceId(row.evidence_id, "row evidence_id");
    if (!evidenceIds.includes(evidenceId)) throw new TypeError(`row evidence ${evidenceId} is not declared by block`);
    const evidence = requireEvidence(evidenceById, evidenceId);
    return { evidenceId, cells: parsedColumns.map((column) => selectValue(evidence, column.selector)) };
  });
  if (block.sort !== null) {
    const sort = record(block.sort, "DataTable sort");
    exactKeys(sort, ["column_key", "direction"], "DataTable sort");
    const columnKey = shortText(sort.column_key, "sort column_key");
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
    blockId: shortText(block.block_id, "block_id"),
    title: safeShortText(block.title, "block title"),
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
    return { kind: "FACT", label: safeShortText(selector.label, "fact label"), normalization: normalization(selector.normalization) };
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
  return parseStrictIsoTemporal(value, "ISO_DATE evidence value").normalized;
}

function requireEvidence(evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>, evidenceId: string): ResearchEvidenceProjection {
  const evidence = evidenceById.get(evidenceId);
  if (!evidence) throw new TypeError(`evidence ${evidenceId} is not bound to the active session`);
  return evidence;
}

function declaredEvidenceIds(value: unknown, evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>, label: string): string[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_EVIDENCE_IDS_PER_BLOCK) throw new TypeError(`${label} requires 1-${GENERATIVE_RESEARCH_VIEW_LIMITS.MAX_EVIDENCE_IDS_PER_BLOCK} evidence_ids`);
  const evidenceIds = value.map((item) => parseEvidenceId(item, "evidence_id"));
  if (new Set(evidenceIds).size !== evidenceIds.length) throw new TypeError("evidence_ids must not contain duplicates");
  for (const item of evidenceIds) requireEvidence(evidenceById, item);
  return evidenceIds;
}

function compareDisplayValues(left: string, right: string): number {
  const leftNumber = Number(left.replaceAll(",", "").replace(/%$/, ""));
  const rightNumber = Number(right.replaceAll(",", "").replace(/%$/, ""));
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return leftNumber - rightNumber;
  return left.localeCompare(right);
}

function parsedDate(value: unknown, label: string): number {
  return parseStrictIsoTemporal(shortText(value, label), label).sortKey;
}

function parseStrictIsoTemporal(value: string, label: string): { normalized: string; sortKey: number } {
  const dateOnly = ISO_DATE_ONLY_PATTERN.exec(value);
  if (dateOnly) {
    const [year, month, day] = dateOnly.slice(1).map(Number);
    validateCalendarDate(year, month, day, label);
    return { normalized: value, sortKey: utcMilliseconds(year, month, day, 0, 0, 0, 0) };
  }
  const timestamp = ISO_TIMESTAMP_PATTERN.exec(value);
  if (!timestamp) throw new TypeError(`${label} must be YYYY-MM-DD or a timezone-aware ISO timestamp`);
  const year = Number(timestamp[1]);
  const month = Number(timestamp[2]);
  const day = Number(timestamp[3]);
  const hour = Number(timestamp[4]);
  const minute = Number(timestamp[5]);
  const second = Number(timestamp[6]);
  const fraction = timestamp[7] ?? "";
  validateCalendarDate(year, month, day, label);
  if (hour > 23 || minute > 59 || second > 59) throw new TypeError(`${label} has an invalid clock time`);
  const offsetHour = timestamp[8] === "Z" ? 0 : Number(timestamp[10]);
  const offsetMinute = timestamp[8] === "Z" ? 0 : Number(timestamp[11]);
  if (offsetHour > 23 || offsetMinute > 59) throw new TypeError(`${label} has an invalid timezone offset`);
  const millisecond = Number(fraction.padEnd(3, "0").slice(0, 3) || "0");
  const direction = timestamp[9] === "-" ? -1 : 1;
  const offset = timestamp[8] === "Z" ? 0 : direction * (offsetHour * 60 + offsetMinute) * 60_000;
  const sortKey = utcMilliseconds(year, month, day, hour, minute, second, millisecond) - offset;
  return { normalized: new Date(sortKey).toISOString(), sortKey };
}

function validateCalendarDate(year: number, month: number, day: number, label: string): void {
  if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) throw new TypeError(`${label} has an invalid calendar date`);
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function utcMilliseconds(year: number, month: number, day: number, hour: number, minute: number, second: number, millisecond: number): number {
  const value = new Date(0);
  value.setUTCFullYear(year, month - 1, day);
  value.setUTCHours(hour, minute, second, millisecond);
  return value.getTime();
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

function shortText(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || value.length > GENERATIVE_RESEARCH_VIEW_LIMITS.SHORT_TEXT_MAX) throw new TypeError(`${label} must be ShortText with length 1-${GENERATIVE_RESEARCH_VIEW_LIMITS.SHORT_TEXT_MAX}`);
  return value;
}

function safeShortText(value: unknown, label: string): string {
  return rejectUnsafeText(shortText(value, label), label);
}

function safeBoundedText(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || value.length > GENERATIVE_RESEARCH_VIEW_LIMITS.BOUNDED_TEXT_MAX) throw new TypeError(`${label} must be BoundedText with length 1-${GENERATIVE_RESEARCH_VIEW_LIMITS.BOUNDED_TEXT_MAX}`);
  return rejectUnsafeText(value, label);
}

function rejectUnsafeText(result: string, label: string): string {
  if (/<\/?[a-z][^>]*>/i.test(result) || /javascript\s*:/i.test(result)) throw new TypeError(`${label} contains forbidden markup or script`);
  return result;
}

function parseEvidenceId(value: unknown, label: string): string {
  if (typeof value !== "string" || !EVIDENCE_ID_PATTERN.test(value)) throw new TypeError(`${label} must match the canonical EvidenceId pattern`);
  return value;
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
