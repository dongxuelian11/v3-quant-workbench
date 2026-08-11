export const GENERATIVE_RESEARCH_VIEW_SCHEMA_VERSION = "v3.generative_research_view/1.0.0" as const;

export const GENERATIVE_RESEARCH_VIEW_LIMITS = Object.freeze({
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

export const GENERATIVE_RESEARCH_VIEW_EVIDENCE_ID_PATTERN = "^[a-z][a-z0-9_]*_sha256_[0-9a-f]{64}$" as const;

export const GENERATIVE_RESEARCH_VIEW_BLOCK_TYPES = Object.freeze([
  "Narrative",
  "MetricGroup",
  "DataTable",
  "TimeSeriesChart",
  "BarChart",
  "EvidenceList",
  "Callout"
] as const);

export type GenerativeResearchViewBlockType = typeof GENERATIVE_RESEARCH_VIEW_BLOCK_TYPES[number];
export type ResearchViewDataAuthority = "CANONICAL_EVIDENCE" | "AGENT_DRAFT_DERIVED";
export type DisplayNormalization = "NONE" | "NUMBER" | "ISO_DATE";
export type EvidenceField = "objectId" | "kind" | "title" | "summary" | "canonicalTruthState" | "canonicalAdmissionState" | "validationState" | "reviewerFinding" | "openInLab" | "artifactId";

export type ResearchViewSelector =
  | { readonly kind: "EVIDENCE_FIELD"; readonly field: EvidenceField; readonly normalization: DisplayNormalization }
  | { readonly kind: "FACT"; readonly label: string; readonly normalization: DisplayNormalization };

export interface NarrativeBlock {
  readonly type: "Narrative";
  readonly block_id: string;
  readonly title: string;
  readonly data_authority: "AGENT_DRAFT_DERIVED";
  readonly evidence_ids: readonly string[];
  readonly text: string;
}

export interface EvidenceListBlock {
  readonly type: "EvidenceList";
  readonly block_id: string;
  readonly title: string;
  readonly data_authority: "CANONICAL_EVIDENCE";
  readonly evidence_ids: readonly string[];
  readonly fields: readonly { readonly key: string; readonly label: string; readonly selector: ResearchViewSelector }[];
}

export interface CalloutBlock {
  readonly type: "Callout";
  readonly block_id: string;
  readonly title: string;
  readonly data_authority: "AGENT_DRAFT_DERIVED";
  readonly evidence_ids: readonly string[];
  readonly tone: "INFO" | "WARNING" | "BLOCKED";
  readonly text: string;
}

export interface ResearchViewMetric {
  readonly label: string;
  readonly evidence_id: string;
  readonly selector: ResearchViewSelector;
}

export interface MetricGroupBlock {
  readonly type: "MetricGroup";
  readonly block_id: string;
  readonly title: string;
  readonly data_authority: "CANONICAL_EVIDENCE";
  readonly evidence_ids: readonly string[];
  readonly metrics: readonly ResearchViewMetric[];
}

export interface DataTableBlock {
  readonly type: "DataTable";
  readonly block_id: string;
  readonly title: string;
  readonly data_authority: "CANONICAL_EVIDENCE";
  readonly evidence_ids: readonly string[];
  readonly columns: readonly { readonly key: string; readonly header: string; readonly selector: ResearchViewSelector }[];
  readonly rows: readonly { readonly evidence_id: string }[];
  readonly sort: { readonly column_key: string; readonly direction: "ASC" | "DESC" } | null;
  readonly top_n: number | null;
}

export interface TimeSeriesChartBlock {
  readonly type: "TimeSeriesChart";
  readonly block_id: string;
  readonly title: string;
  readonly data_authority: "CANONICAL_EVIDENCE";
  readonly evidence_ids: readonly string[];
  readonly x_label: string;
  readonly y_label: string;
  readonly points: readonly { readonly evidence_id: string; readonly x_selector: ResearchViewSelector; readonly y_selector: ResearchViewSelector }[];
  readonly date_window: { readonly start: string; readonly end: string } | null;
}

export interface BarChartBlock {
  readonly type: "BarChart";
  readonly block_id: string;
  readonly title: string;
  readonly data_authority: "CANONICAL_EVIDENCE";
  readonly evidence_ids: readonly string[];
  readonly category_label: string;
  readonly value_label: string;
  readonly bars: readonly { readonly evidence_id: string; readonly category_selector: ResearchViewSelector; readonly value_selector: ResearchViewSelector }[];
  readonly sort: "INPUT" | "VALUE_ASC" | "VALUE_DESC";
  readonly top_n: number | null;
}

export interface ResearchViewSpecV1 {
  readonly schema_version: typeof GENERATIVE_RESEARCH_VIEW_SCHEMA_VERSION;
  readonly spec_id: string;
  readonly session_view_id: string;
  readonly permission: "L1_DRAFT";
  readonly authority: "AGENT_DRAFT_PROPOSAL";
  readonly title: string;
  readonly blocks: readonly (NarrativeBlock | MetricGroupBlock | DataTableBlock | TimeSeriesChartBlock | BarChartBlock | EvidenceListBlock | CalloutBlock)[];
}
