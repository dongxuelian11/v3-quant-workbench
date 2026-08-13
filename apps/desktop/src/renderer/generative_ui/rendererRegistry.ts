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
  Narrative: { availability: "AVAILABLE", label: "叙述" },
  MetricGroup: { availability: "AVAILABLE", label: "指标" },
  DataTable: { availability: "AVAILABLE", label: "数据表" },
  TimeSeriesChart: { availability: "AVAILABLE", label: "时间序列" },
  BarChart: { availability: "AVAILABLE", label: "柱状图" },
  EvidenceList: { availability: "AVAILABLE", label: "证据列表" },
  Callout: { availability: "AVAILABLE", label: "提示" }
} as const);

export function getClosedResearchRenderer(renderer: string) {
  if (!Object.prototype.hasOwnProperty.call(CLOSED_RESEARCH_RENDERER_REGISTRY, renderer)) throw new TypeError(`unsupported research renderer: ${renderer}`);
  return CLOSED_RESEARCH_RENDERER_REGISTRY[renderer as GenerativeResearchViewBlockType];
}
