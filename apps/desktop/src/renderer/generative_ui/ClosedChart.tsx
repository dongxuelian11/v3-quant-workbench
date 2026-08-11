import React, { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { buildClosedChartOption } from "./closedRenderer";
import type { ResolvedBarChartBlock, ResolvedTimeSeriesChartBlock } from "./schemaParser";

export function ClosedChart({ block }: { block: ResolvedBarChartBlock | ResolvedTimeSeriesChartBlock }) {
  const host = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current, undefined, { renderer: "svg" });
    chart.setOption(buildClosedChartOption(block) as unknown as echarts.EChartsOption, { notMerge: true, lazyUpdate: false });
    const resize = () => chart.resize();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    if (observer && host.current) observer.observe(host.current);
    window.addEventListener("resize", resize);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [block]);

  return <div className="generative-chart" ref={host} role="img" aria-label={`${block.title}; ${block.type}; canonical evidence chart`}/>;
}
