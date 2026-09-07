import React, { useEffect, useRef, useState } from "react";
import { init, dispose, registerOverlay, type Chart, type OverlayCreate } from "klinecharts";
import { errorText, request, useResearch } from "./state";
import { Empty, Heading, tradeDirection } from "./ui";
import type { TablePage } from "./PagedTable";

registerOverlay({ name: "research_note", totalStep: 2, needDefaultPointFigure: true, createPointFigures: ({ coordinates, overlay }) => coordinates.length ? [{ type: "text", attrs: { x: coordinates[0].x, y: coordinates[0].y, text: String(overlay.extendData ?? "批注"), align: "left", baseline: "bottom" }, styles: { color: "#267774", size: 13, backgroundColor: "#fffdf9", paddingLeft: 5, paddingRight: 5, paddingTop: 4, paddingBottom: 4 } }] : [] });
registerOverlay({ name: "research_rect", totalStep: 3, needDefaultPointFigure: true, createPointFigures: ({ coordinates }) => coordinates.length > 1 ? [{ type: "rect", attrs: { x: Math.min(coordinates[0].x, coordinates[1].x), y: Math.min(coordinates[0].y, coordinates[1].y), width: Math.abs(coordinates[1].x - coordinates[0].x), height: Math.abs(coordinates[1].y - coordinates[0].y) }, styles: { style: "stroke_fill", color: "rgba(38,119,116,.08)", borderColor: "#267774", borderSize: 1 } }] : [] });
interface Bar { date: string; open: number; high: number; low: number; close: number; volume: number }
export interface TradeMarker { date: string; price: number; adjustedPrice?: number; side: string }
function dateAt(timestamp: number) { return new Date(timestamp + 8 * 3600000).toISOString().slice(0, 10); }
export function PriceChart({ symbol: initial = "", focusDate, trades = [], experimentId, tradeTable }: { symbol?: string; focusDate?: string; trades?: TradeMarker[]; experimentId?: string; tradeTable?: string }) {
  const s = useResearch(); const projectId = s.project!.id;
  const [symbol, setSymbol] = useState(initial || s.project!.universe.symbols[0] || ""); const [input, setInput] = useState(symbol);
  const [note, setNote] = useState(""); const [status, setStatus] = useState(""); const [count, setCount] = useState(0);
  const node = useRef<HTMLDivElement>(null); const chart = useRef<Chart | null>(null);
  const [dirty, setDirty] = useState(false);
  const [windowTrades, setWindowTrades] = useState<TradeMarker[]>([]);
  const [tradeStatus, setTradeStatus] = useState("");
  const saveQueue = useRef(Promise.resolve());
  const saveAnnotations = () => {
    const instance = chart.current; if (!instance) return Promise.resolve();
    const annotations = instance.getOverlays().filter(o => o.groupId !== "research-trade").map(o => ({ id: o.id, name: o.name, points: o.points, extendData: o.extendData ?? null, lock: o.lock, visible: o.visible }));
    const pending = saveQueue.current.catch(() => {}).then(async () => { await request("charts.save", { projectId, symbol, annotations }); setDirty(false); });
    saveQueue.current = pending; return pending;
  };
  const changed = () => { setDirty(true); void s.act(saveAnnotations); };
  useEffect(() => { if (initial) { setSymbol(initial); setInput(initial); } }, [initial]);
  useEffect(() => {
    if (!node.current || !symbol) return;
    let active = true;
    const loadedTrades = new Map<string, TradeMarker>();
    setWindowTrades([]); setTradeStatus("");
    const instance = init(node.current, { locale: "zh-CN", timezone: "Asia/Shanghai" });
    if (!instance) return;
    chart.current = instance; setCount(0); setDirty(false); setStatus("正在读取日线…");
    instance.setDataLoader({ getBars: async ({ type, timestamp, callback }) => {
      if (type === "update") { callback([], false); return; }
      let delivered = false;
      try {
        const day = 86400000;
        const anchor = focusDate ? Date.parse(`${focusDate.slice(0, 10)}T00:00:00+08:00`) : null;
        const range = type === "forward" && timestamp != null ? { startDate: dateAt(timestamp - 365 * day), endDate: dateAt(timestamp - day) }
          : type === "backward" && timestamp != null ? { startDate: dateAt(timestamp + day), endDate: dateAt(timestamp + 365 * day) }
          : anchor != null ? { startDate: dateAt(anchor - 90 * day), endDate: dateAt(anchor + 90 * day) } : {};
        const bars = await request<Bar[]>("data.bars", { projectId, symbol, ...range });
        if (!active) return;
        const data = bars.map(b => ({ ...b, timestamp: Date.parse(`${b.date.slice(0, 10)}T00:00:00+08:00`) })).filter(b => Number.isFinite(b.timestamp)).sort((a, b) => a.timestamp - b.timestamp);
        callback(data, type === "init" ? { forward: data.length > 0, backward: anchor != null && data.length > 0 } : data.length > 0);
        delivered = true;
        if (type === "init") { setCount(data.length); setStatus(data.length ? `${symbol} · 日线，可拖动加载历史` : "没有这只证券在该区间的日线数据"); if (data.length > 0 && instance.getDataList().length > 0 && anchor != null && Number.isFinite(anchor)) instance.scrollToTimestamp(anchor); }
        if (experimentId && tradeTable && data.length) {
          setTradeStatus("正在读取这个行情区间的成交…");
          let offset = 0;
          while (active) {
            const result = await request<TablePage>("experiments.table", { projectId, experimentId, table: tradeTable, symbol, startDate: data[0].date.slice(0, 10), endDate: data[data.length - 1].date.slice(0, 10), offset, limit: 500 });
            if (!active) return;
            for (const row of result.rows) {
              const date = row.date ?? row.trade_date, price = row.price ?? row.execution_price ?? row.trade_price, side = tradeDirection(row.side ?? row.direction);
              if (typeof date === "string" && typeof price === "number" && Number.isFinite(price) && side) loadedTrades.set(JSON.stringify(row), { date, price, ...(typeof row.adjustedPrice === "number" && Number.isFinite(row.adjustedPrice) ? { adjustedPrice: row.adjustedPrice } : {}), side });
            }
            offset += result.rows.length;
            if (offset >= result.total) break;
            if (!result.rows.length) throw new Error("成交表分页未返回剩余记录，请重新加载回放。");
          }
          setWindowTrades([...loadedTrades.values()]);
          setTradeStatus(`已载入行情区间内 ${loadedTrades.size} 个成交标记`);
        }
      } catch (e) { if (active) { if (!delivered) { callback([], false); setStatus(errorText(e)); } else { setTradeStatus("成交标记读取未完成"); s.setError(errorText(e)); } } }
    } });
    instance.setSymbol({ ticker: symbol, pricePrecision: 2, volumePrecision: 0 }); instance.setPeriod({ type: "day", span: 1 });
    instance.createIndicator("VOL");
    void request<{ annotations: OverlayCreate[] }>("charts.load", { projectId, symbol }).then(({ annotations }) => { if (active && annotations.length) instance.createOverlay(annotations.map(o => ({ ...o, onPressedMoveEnd: () => { if (active) changed(); }, onRemoved: () => { if (active) changed(); } }))); }).catch(e => { if (active) s.setError(errorText(e)); });
    const observer = new ResizeObserver(() => instance.resize()); observer.observe(node.current);
    const container = node.current;
    return () => { active = false; observer.disconnect(); dispose(container); chart.current = null; };
  }, [symbol, projectId, focusDate, experimentId, tradeTable]);
  const markers = experimentId && tradeTable ? windowTrades : trades;
  useEffect(() => {
    const instance = chart.current; if (!instance || !count) return;
    instance.removeOverlay({ groupId: "research-trade" });
    markers.forEach((trade, index) => instance.createOverlay({ name: "research_note", id: `trade-${index}`, groupId: "research-trade", lock: true, points: [{ timestamp: Date.parse(`${trade.date.slice(0, 10)}T00:00:00+08:00`), value: trade.adjustedPrice ?? trade.price }], extendData: `${trade.side} · 成交价 ${trade.price}`, styles: { text: { color: trade.side === "买入" ? "#b35c4f" : "#287775" } } }));
  }, [JSON.stringify(markers), count, symbol]);
  useEffect(() => {
    const instance = chart.current;
    if (!focusDate || count === 0 || !instance || instance.getDataList().length === 0) return;
    const timestamp = Date.parse(`${focusDate.slice(0, 10)}T00:00:00+08:00`);
    if (Number.isFinite(timestamp)) instance.scrollToTimestamp(timestamp);
  }, [focusDate, count]);
  const draw = (name: string) => chart.current?.createOverlay({ name, ...(name === "research_note" ? { extendData: note } : {}), onDrawEnd: changed, onPressedMoveEnd: changed, onRemoved: changed });
  return <div className="r-chart-panel"><Heading title="行情与批注" description="拖动、缩放日线；添加趋势线、区间和研究笔记。" /><div className="r-toolbar"><form onSubmit={e => { e.preventDefault(); if (input.trim() && (!dirty || window.confirm("当前批注尚未保存，切换证券？"))) setSymbol(input.trim()); }}><input aria-label="证券代码" placeholder="输入证券代码" value={input} onChange={e => setInput(e.target.value)} /><button type="submit">加载</button></form><span>{status}</span><span>{tradeStatus}</span></div><div className="r-toolbar"><button disabled={!count} onClick={() => draw("segment")}>趋势线</button><button disabled={!count} onClick={() => draw("horizontalStraightLine")}>水平线</button><button disabled={!count} onClick={() => draw("research_rect")}>区间框</button><input aria-label="批注文字" placeholder="写下批注，再点击图表定位" value={note} onChange={e => setNote(e.target.value)} /><button disabled={!count || !note.trim()} onClick={() => draw("research_note")}>文字批注</button><button disabled={!count} onClick={() => chart.current?.createIndicator({ name: "MA", paneId: "candle_pane" }, true)}>均线</button><button disabled={!count} onClick={() => { chart.current?.removeOverlay(); setDirty(true); }}>清除批注</button></div>{!symbol && <Empty title="选择一只证券开始查看">从交易或持仓表点击证券也可打开回放。</Empty>}<div ref={node} className="r-kline" style={{ height: 400 }} /><div className="r-toolbar"><button disabled={!symbol || !chart.current} onClick={() => void s.act(async () => { const annotations = chart.current!.getOverlays().filter(o => o.groupId !== "research-trade").map(o => ({ id: o.id, name: o.name, points: o.points, extendData: o.extendData ?? null, lock: o.lock, visible: o.visible })); await request("charts.save", { projectId, symbol, annotations }); setDirty(false); s.setNotice("批注已保存到项目"); })}>{dirty ? "保存批注 · 未保存" : "保存批注"}</button><button disabled={!count} onClick={() => void s.act(async () => { const dataUrl = chart.current!.getConvertPictureUrl(true, "png", "#fffefa"); const path = await window.v3Research!.exportFile({ format: "png", dataUrl, suggestedName: `${symbol}-日线.png` }); if (path) s.setNotice(`已导出：${path}`); })}>导出图片</button></div></div>;
}
