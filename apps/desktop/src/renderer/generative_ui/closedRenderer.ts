import type { ResolvedResearchViewBlock } from "./schemaParser";

export type ClosedChartBlock = Extract<ResolvedResearchViewBlock, { type: "TimeSeriesChart" | "BarChart" }>;

export interface ClosedChartOption {
  readonly animation: false;
  readonly aria: { readonly enabled: true; readonly decal: { readonly show: true } };
  readonly tooltip: { readonly show: true; readonly trigger: "axis" };
  readonly grid: { readonly left: 52; readonly right: 18; readonly top: 24; readonly bottom: 42 };
  readonly xAxis: Readonly<Record<string, unknown>>;
  readonly yAxis: Readonly<Record<string, unknown>>;
  readonly series: readonly Readonly<Record<string, unknown>>[];
}

export function buildClosedChartOption(block: ResolvedResearchViewBlock): ClosedChartOption {
  if (block.type === "BarChart") {
    return {
      animation: false,
      aria: { enabled: true, decal: { show: true } },
      tooltip: { show: true, trigger: "axis" },
      grid: { left: 52, right: 18, top: 24, bottom: 42 },
      xAxis: { type: "category", name: block.categoryLabel, data: block.bars.map((bar) => bar.category), axisLabel: { color: "#9AA6B2", hideOverlap: true } },
      yAxis: { type: "value", name: block.valueLabel, axisLabel: { color: "#9AA6B2" }, splitLine: { lineStyle: { color: "#26303B" } } },
      series: [{ type: "bar", name: block.valueLabel, data: block.bars.map((bar) => bar.value), itemStyle: { color: "#51A8DD" }, emphasis: { disabled: true } }]
    };
  }
  if (block.type === "TimeSeriesChart") {
    return {
      animation: false,
      aria: { enabled: true, decal: { show: true } },
      tooltip: { show: true, trigger: "axis" },
      grid: { left: 52, right: 18, top: 24, bottom: 42 },
      xAxis: { type: "time", name: block.xLabel, axisLabel: { color: "#9AA6B2", hideOverlap: true } },
      yAxis: { type: "value", name: block.yLabel, axisLabel: { color: "#9AA6B2" }, splitLine: { lineStyle: { color: "#26303B" } } },
      series: [{ type: "line", name: block.yLabel, data: block.points.map((point) => [point.x, point.y] as const), showSymbol: block.points.length <= 40, symbolSize: 5, lineStyle: { width: 1.5, color: "#51A8DD" }, itemStyle: { color: "#51A8DD" }, emphasis: { disabled: true } }]
    };
  }
  throw new TypeError(`unsupported closed chart renderer: ${block.type}`);
}
