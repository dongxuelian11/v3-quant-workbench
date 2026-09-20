import React, { createContext, useContext, useEffect, useRef, type RefObject } from "react";
import type { Chart } from "klinecharts";
type Listener = (timestamp: number, source: string) => void;
export interface TimeLink { subscribe: (listener: Listener) => () => void; publish: (timestamp: number, source: string) => void; }
const Context = createContext<{ link: TimeLink; source: string } | null>(null);
export function createTimeLink(): TimeLink {
  const listeners = new Set<Listener>();
  return { subscribe: listener => { listeners.add(listener); return () => { listeners.delete(listener); }; }, publish: (timestamp, source) => { if (Number.isFinite(timestamp)) listeners.forEach(listener => listener(timestamp, source)); } };
}
export function ChartTimeScope({ link, source, children }: { link: TimeLink; source: string; children: React.ReactNode }) { return <Context.Provider value={{ link, source }}>{children}</Context.Provider>; }
export function useTimeLink() { return useContext(Context); }
export function useKLineTimeLink(chart: RefObject<Chart | null>, identity: string) {
  const context = useTimeLink(), latest = useRef(context); latest.current = context;
  useEffect(() => {
    const instance = chart.current, scoped = latest.current;
    if (!instance || !scoped) return;
    const publish = (raw:unknown) => {
      if(!raw||typeof raw!=="object")return;const event=raw as { timestamp?:number;x?:number };
      let timestamp = event.timestamp;
      if (timestamp == null && event.x != null) { const value = instance.convertFromPixel([{ x: event.x }]); const point = Array.isArray(value) ? value[0] : value; timestamp = point?.timestamp; }
      if (timestamp != null) scoped.link.publish(timestamp, scoped.source);
    };
    instance.subscribeAction("onCrosshairChange", publish);
    const off = scoped.link.subscribe((timestamp, source) => {
      if (source === scoped.source) return;
      const bars = instance.getDataList(); if (!bars.length) return;
      const day = new Date(timestamp + 8 * 3600000).toISOString().slice(0, 10);
      let index = -1;
      for (let i = 0; i < bars.length; i++) if (new Date(bars[i].timestamp + 8 * 3600000).toISOString().slice(0, 10) === day && bars[i].timestamp <= timestamp) index = i;
      if (index < 0) return;
      const value = instance.convertToPixel([{ dataIndex: index, value: bars[index].close }]); const point = Array.isArray(value) ? value[0] : value;
      if (point?.x == null || point.y == null) return;
      instance.executeAction("onCrosshairChange", { x: point.x, y: point.y });
    });
    return () => { off(); instance.unsubscribeAction("onCrosshairChange", publish); };
  }, [identity, context?.link, context?.source]);
}
