import type { GenerativeResearchViewBlockType } from "../../../../../packages/contracts/src/generativeResearchView";

export const CLOSED_RESEARCH_RENDERER_KEYS = Object.freeze([
  "Narrative",
  "MetricGroup",
  "DataTable",
  "TimeSeriesChart",
  "BarChart",
  "EvidenceList",
  "Callout"
] as const satisfies readonly GenerativeResearchViewBlockType[]);

export const CLOSED_RESEARCH_RENDERER_REGISTRY = Object.freeze({
  Narrative: { availability: "AVAILABLE", label: "Narrative" },
  MetricGroup: { availability: "AVAILABLE", label: "Metrics" },
  DataTable: { availability: "AVAILABLE", label: "Data table" },
  TimeSeriesChart: { availability: "AVAILABLE", label: "Time series" },
  BarChart: { availability: "AVAILABLE", label: "Bar chart" },
  EvidenceList: { availability: "AVAILABLE", label: "Evidence list" },
  Callout: { availability: "AVAILABLE", label: "Callout" }
} as const);

export function getClosedResearchRenderer(renderer: string) {
  if (!Object.prototype.hasOwnProperty.call(CLOSED_RESEARCH_RENDERER_REGISTRY, renderer)) throw new TypeError(`unsupported research renderer: ${renderer}`);
  return CLOSED_RESEARCH_RENDERER_REGISTRY[renderer as GenerativeResearchViewBlockType];
}
