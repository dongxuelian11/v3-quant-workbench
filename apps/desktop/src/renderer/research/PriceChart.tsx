import React, { useEffect, useRef, useState } from "react";
import { init, dispose, registerOverlay, type Chart, type OverlayCreate } from "klinecharts";
import { errorText, request, useResearch } from "./state";
import { Empty, Heading, tradeDirection } from "./ui";
import type { TablePage } from "./PagedTable";

registerOverlay({ name: "research_note", totalStep: 2, needDefaultPointFigure: true, createPointFigures: ({ coordinates, overlay }) => coordinates.length ? [{ type: "text", attrs: { x: coordinates[0].x, y: coordinates[0].y, text: String(overlay.extendData ?? "批注"), align: "left", baseline: "bottom" }, styles: { color: overlay.groupId === "research-trade" ? overlay.styles?.text?.color ?? "#267774" : "#267774", size: 13, backgroundColor: "#fffdf9", paddingLeft: 5, paddingRight: 5, paddingTop: 4, paddingBottom: 4 } }] : [] });
registerOverlay({ name: "research_rect", totalStep: 3, needDefaultPointFigure: true, createPointFigures: ({ coordinates }) => coordinates.length > 1 ? [{ type: "rect", attrs: { x: Math.min(coordinates[0].x, coordinates[1].x), y: Math.min(coordinates[0].y, coordinates[1].y), width: Math.abs(coordinates[1].x - coordinates[0].x), height: Math.abs(coordinates[1].y - coordinates[0].y) }, styles: { style: "stroke_fill", color: "rgba(38,119,116,.08)", borderColor: "#267774", borderSize: 1 } }] : [] });
registerOverlay({ name: "research_trade", totalStep: 1, needDefaultPointFigure: true, createPointFigures: ({ coordinates, overlay }) => {
  if (!coordinates.length) return [];
  const trade = overlay.extendData as TradeMarker, point = coordinates[0], buy = trade.side === "买入";
  const color = buy ? "#d04a45" : "#21845c", offset = buy ? 22 : -22;
  return [{ type: "line", attrs: { coordinates: [point, { x: point.x, y: point.y + offset }] }, styles: { color, size: 1 } },
    { type: "text", attrs: { x: point.x, y: point.y + offset, text: buy ? "买" : "卖", align: "center", baseline: buy ? "top" : "bottom" }, styles: { color: "#ffffff", size: 12, backgroundColor: color, paddingLeft: 4, paddingRight: 4, paddingTop: 3, paddingBottom: 3 } }];
} });
interface Bar { date: string; open: number; high: number; low: number; close: number; volume: number; factor?: number | null; rawOpen?: number | null; rawHigh?: number | null; rawLow?: number | null; rawClose?: number | null }
export interface TradeMarker { id?: string; date: string; price: number; adjustedPrice?: number; side: string; quantity?: number }
function dateAt(timestamp: number) { return new Date(timestamp + 8 * 3600000).toISOString().slice(0, 10); }
function applyChartTheme(instance: Chart, container: HTMLDivElement) {
  const dark = document.documentElement.dataset.theme === "dark";
  const css = getComputedStyle(document.documentElement); const paper = css.getPropertyValue("--paper").trim() || (dark ? "#242830" : "#ffffff");
  const text = dark ? "#cbd2df" : "#525d6b", grid = dark ? "#363d49" : "#e5e8ee", muted = dark ? "#929dab" : "#82909e";
  const colors = { upColor: dark ? "#f07178" : "#d04a45", downColor: dark ? "#4bbf91" : "#21845c", noChangeColor: muted };
  const axis = { axisLine: { color: grid }, tickLine: { color: grid }, tickText: { color: text } };
  const cross = { line: { color: muted }, text: { color: dark ? "#eef1f6" : "#ffffff", backgroundColor: dark ? "#4c586a" : "#64748b", borderColor: grid } };
  container.style.backgroundColor = paper;
  instance.setStyles({ grid: { horizontal: { color: grid }, vertical: { color: grid } },
    candle: { bar: { ...colors, compareRule: "current_open", upBorderColor: colors.upColor, downBorderColor: colors.downColor, noChangeBorderColor: muted, upWickColor: colors.upColor, downWickColor: colors.downColor, noChangeWickColor: muted }, priceMark: { high: { color: text }, low: { color: text }, last: { ...colors, compareRule: "current_open" } }, tooltip: { title: { color: text }, legend: { color: text }, rect: { color: paper, borderColor: grid } } },
    indicator: { ohlc: { ...colors, compareRule: "current_open" }, bars: [{ ...instance.getStyles().indicator.bars[0], ...colors }], tooltip: { title: { color: text }, legend: { color: text } } },
    xAxis: axis, yAxis: axis, separator: { color: grid, activeBackgroundColor: dark ? "#486080" : "#bfd2ed" }, crosshair: { horizontal: cross, vertical: cross }, overlay: { text: { color: text, backgroundColor: paper } }
  });
}
export function chartDateRange(range: { startDate?: string; endDate?: string; beforeDate?: string }, asOfDate?: string) {
  return asOfDate ? { ...range, endDate: !range.endDate || range.endDate > asOfDate ? asOfDate : range.endDate } : range;
}
export function PriceChart({ symbol: initial = "", focusDate, trades = [], experimentId, tradeTable, embedded = false, asOfDate, replayMode = false, priceBasis = "adjusted", initialStartDate, initialEndDate, focusedTrade, onTradeClick }: { symbol?: string; focusDate?: string; trades?: TradeMarker[]; experimentId?: string; tradeTable?: string; embedded?: boolean; asOfDate?: string; replayMode?: boolean; priceBasis?: "raw" | "adjusted"; initialStartDate?: string; initialEndDate?: string; focusedTrade?: TradeMarker; onTradeClick?: (trade: TradeMarker) => void }) {
  const s = useResearch(); const projectId = s.project?.id;
  const [editableSymbol, setSymbol] = useState(initial || s.project?.universe.symbols[0] || ""); const symbol = embedded ? initial : editableSymbol; const [input, setInput] = useState(symbol);
  const [start, setStart] = useState(initialStartDate ?? ""); const [end, setEnd] = useState(initialEndDate ?? ""); const [rangeWindow, setRangeWindow] = useState<{ startDate?: string; endDate?: string }>({ startDate: initialStartDate, endDate: initialEndDate });
  const [note, setNote] = useState(""); const [status, setStatus] = useState(""); const [count, setCount] = useState(0);
  const node = useRef<HTMLDivElement>(null); const chart = useRef<Chart | null>(null);
  const [dirty, setDirty] = useState(false); const [loadFailed, setLoadFailed] = useState(false); const [reload, setReload] = useState(0);
  const [windowTrades, setWindowTrades] = useState<TradeMarker[]>([]);
  const [tradeStatus, setTradeStatus] = useState(""); const [focusStatus,setFocusStatus]=useState("");
  const factors = useRef(new Map<string, number>()); const [markerStatus, setMarkerStatus] = useState(""); const [markerSummary,setMarkerSummary]=useState("");
  const tradeClick = useRef(onTradeClick); tradeClick.current = onTradeClick;
  const loadFocusDate = replayMode ? undefined : focusDate;
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
    setWindowTrades([]); setTradeStatus(""); factors.current.clear();
    const instance = init(node.current, { locale: "zh-CN", timezone: "Asia/Shanghai" });
    if (!instance) return;
    chart.current = instance; applyChartTheme(instance, node.current); const themeObserver = new MutationObserver(() => { if (active && node.current) applyChartTheme(instance, node.current); }); themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] }); setCount(0); setDirty(false); setLoadFailed(false); setStatus("正在读取日线…");
    instance.setDataLoader({ getBars: async ({ type, timestamp, callback }) => {
      if (type === "update") { callback([], false); return; }
      let delivered = false;
      try {
        const day = 86400000;
        const anchor = loadFocusDate ? Date.parse(`${loadFocusDate.slice(0, 10)}T00:00:00+08:00`) : null;
        const range: { startDate?: string; endDate?: string; beforeDate?: string } = type === "forward" && timestamp != null ? { beforeDate: dateAt(timestamp) }
          : type === "backward" && timestamp != null ? { startDate: dateAt(timestamp + day), endDate: dateAt(timestamp + 365 * day) }
          : rangeWindow.startDate ? rangeWindow : anchor != null ? { startDate: dateAt(anchor - 90 * day), endDate: dateAt(anchor + 90 * day) } : {};
        const bounded = chartDateRange(range, asOfDate);
        if (bounded.startDate && bounded.endDate && bounded.startDate > bounded.endDate) { callback([], false); if (type === "init") setStatus("所选区间晚于个股资料截止日期"); return; }
        const bars = await request<Bar[]>("data.bars", { projectId, symbol, ...bounded, limit: 500 });
        if (type === "init" && rangeWindow.startDate) {
          let page = bars;
          while (active && page.length === 500) {
            const earliest = page.reduce((a, b) => a < b.date ? a : b.date, page[0].date).slice(0, 10);
            if (earliest <= rangeWindow.startDate) break;
            page = await request<Bar[]>("data.bars", { projectId, symbol, ...chartDateRange(rangeWindow, asOfDate), beforeDate: earliest, limit: 500 });
            if (page.some(b => b.date.slice(0, 10) >= earliest)) throw new Error("历史行情分页未前进。");
            bars.push(...page);
          }
        }
        if (!active) return;
        if (priceBasis === "raw" && bars.some(b => [b.rawOpen, b.rawHigh, b.rawLow, b.rawClose].some(value => typeof value !== "number" || !Number.isFinite(value)))) throw new Error("此区间缺少部分原始价格，无法绘制不复权日线。可切换前复权查看连续走势。");
        const data = bars.map(b => {
          if (typeof b.factor === "number" && b.factor > 0) factors.current.set(b.date.slice(0, 10), b.factor);
          return { ...b, ...(priceBasis === "raw" ? { open: b.rawOpen!, high: b.rawHigh!, low: b.rawLow!, close: b.rawClose! } : {}), timestamp: Date.parse(`${b.date.slice(0, 10)}T00:00:00+08:00`) };
        }).filter(b => Number.isFinite(b.timestamp)).sort((a, b) => a.timestamp - b.timestamp);
        callback(data, replayMode && rangeWindow.startDate && rangeWindow.endDate ? { forward: false, backward: false } : type === "init" ? { forward: data.length > 0, backward: (anchor != null || !!rangeWindow.endDate) && data.length > 0 } : data.length > 0);
        delivered = true;
        setCount(instance.getDataList().length);
        if (type === "init") { setStatus(data.length ? `${symbol} · ${data.length} 根日线` : "没有这只证券在该区间的日线数据"); if (data.length > 0 && instance.getDataList().length > 0) { if (replayMode && node.current) { /* KLineChart default barSpaceLimit is 1–50; keep long histories at 6px. */ instance.setBarSpace(Math.max(6, Math.min(50, (node.current.clientWidth - 90) / (data.length + 1)))); instance.setOffsetRightDistance(0); } if (anchor != null && Number.isFinite(anchor)) instance.scrollToTimestamp(anchor); } }
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
      } catch (e) { if (active) { if (!delivered) { callback([], false); setStatus(errorText(e)); setLoadFailed(true); } else { setTradeStatus("成交标记读取未完成"); s.setError(errorText(e)); } } }
    } });
    instance.setSymbol({ ticker: symbol, pricePrecision: 2, volumePrecision: 0 }); instance.setPeriod({ type: "day", span: 1 });
    instance.createIndicator("VOL");
    void request<{ annotations: OverlayCreate[] }>("charts.load", { projectId, symbol }).then(({ annotations }) => { if (active && annotations.length) instance.createOverlay(annotations.map(o => ({ ...o, onPressedMoveEnd: () => { if (active) changed(); }, onRemoved: () => { if (active) changed(); } }))); }).catch(e => { if (active) s.setError(errorText(e)); });
    const observer = new ResizeObserver(() => instance.resize()); observer.observe(node.current);
    const container = node.current;
    return () => { active = false; themeObserver.disconnect(); observer.disconnect(); dispose(container); chart.current = null; };
  }, [symbol, projectId, loadFocusDate, experimentId, tradeTable, rangeWindow, asOfDate, reload, priceBasis, replayMode]);
  const markers = experimentId && tradeTable ? windowTrades : trades;
  useEffect(() => {
    const instance = chart.current; if (!instance || !count) return;
    instance.removeOverlay({ groupId: "research-trade" });
    let shown = 0, missing = 0;
    const dates = new Set(instance.getDataList().map(bar => dateAt(bar.timestamp)));
    markers.forEach((trade, index) => {
      const date = trade.date.slice(0, 10); if (!dates.has(date)) return;
      const factor = factors.current.get(date), value = priceBasis === "raw" ? trade.price : factor ? trade.price * factor : undefined;
      if (value === undefined) { missing++; return; }
      instance.createOverlay({ name: "research_trade", id: `trade-${index}`, groupId: "research-trade", lock: true, points: [{ timestamp: Date.parse(`${date}T00:00:00+08:00`), value }], extendData: trade,
        onClick: () => { setMarkerStatus(`${date} ${trade.side} · ${trade.price.toFixed(4)} 元${trade.quantity === undefined ? "" : ` · ${trade.quantity.toLocaleString("zh-CN")} 股`}`); tradeClick.current?.(trade); } });
      shown++;
    });
    setMarkerSummary(`已载入 ${shown} 个模拟成交点，可拖动或逐笔定位${missing ? `；${missing} 笔缺少当日复权因子，未标注` : ""}`);
  }, [JSON.stringify(markers), count, symbol, priceBasis]);
  useEffect(() => {
    const instance = chart.current;
    if (!focusDate || count === 0 || !instance) {setFocusStatus("");return;}
    const data=instance.getDataList();const index=data.findIndex(bar=>dateAt(bar.timestamp)===focusDate.slice(0,10));
    if(index<0){setFocusStatus(`定位日期 ${focusDate.slice(0,10)} 没有已载日线`);return;}
    const width=instance.getSize()?.width ?? node.current?.clientWidth ?? 600;
    const visible=Math.max(1,Math.floor((width-70)/instance.getBarSpace().bar));
    const right=Math.min(data.length-1,Math.max(visible-1,index+Math.floor(visible/2)));
    instance.setOffsetRightDistance(0);instance.scrollToDataIndex(right,0);
    const bar=data[index];setFocusStatus(`定位日线 ${dateAt(bar.timestamp)} · 开 ${bar.open.toFixed(2)} 高 ${bar.high.toFixed(2)} 低 ${bar.low.toFixed(2)} 收 ${bar.close.toFixed(2)}（${priceBasis==='raw'?'原始价格':'前复权'}）`);
    const coordinate=instance.convertToPixel({dataIndex:index,value:bar.close},{paneId:'candle_pane'});
    if(!Array.isArray(coordinate))instance.executeAction('onCrosshairChange',{...coordinate,paneId:'candle_pane'});
  }, [focusDate, count, priceBasis, focusedTrade?.id]);
  useEffect(()=>{setMarkerStatus(focusedTrade?`${focusedTrade.date.slice(0,10)} ${focusedTrade.side} · ${focusedTrade.price.toFixed(4)} 元${focusedTrade.quantity===undefined?'':` · ${focusedTrade.quantity.toLocaleString('zh-CN')} 股`}`:'');},[focusedTrade]);
  const draw = (name: string) => chart.current?.createOverlay({ name, ...(name === "research_note" ? { extendData: note } : {}), onDrawEnd: changed, onPressedMoveEnd: changed, onRemoved: changed });
  const sortedTrades = [...markers].sort((a, b) => a.date.localeCompare(b.date));
  const selectedTrade = sortedTrades.findIndex(t => focusedTrade ? focusedTrade.id !== undefined ? t.id === focusedTrade.id : t.date === focusedTrade.date && t.side === focusedTrade.side && t.price === focusedTrade.price && t.quantity === focusedTrade.quantity : false);
  const locate = (trade: TradeMarker) => { tradeClick.current?.(trade); setMarkerStatus(`${trade.date.slice(0, 10)} ${trade.side} · ${trade.price.toFixed(4)} 元${trade.quantity === undefined ? "" : ` · ${trade.quantity.toLocaleString("zh-CN")} 股`}`); };
  const exportImage = () => void s.act(async () => { const dataUrl = chart.current!.getConvertPictureUrl(true, "png", getComputedStyle(node.current!).backgroundColor); const path = await window.v3Research!.exportFile({ format: "png", dataUrl, suggestedName: `${symbol}-日线.png` }); if (path) s.setNotice(`已导出：${path}`); });
  return <div className={`r-chart-panel${embedded ? " r-chart-embedded" : ""}`}>
    {!embedded && <Heading title="行情与批注" description="拖动、缩放日线；添加趋势线、区间和研究笔记。" />}
    <div className="r-toolbar r-chart-navigation">
      {replayMode && <>
        <button onClick={() => { setStart(initialStartDate ?? ""); setEnd(initialEndDate ?? ""); setRangeWindow({ startDate: initialStartDate, endDate: initialEndDate }); }}>完整回测区间</button>
        <button disabled={!sortedTrades.length} onClick={() => locate(sortedTrades[0])}>首笔成交</button>
        <button disabled={selectedTrade <= 0} onClick={() => locate(sortedTrades[selectedTrade - 1])}>上一笔</button>
        <button disabled={!sortedTrades.length || selectedTrade >= sortedTrades.length - 1} onClick={() => locate(sortedTrades[selectedTrade + 1])}>下一笔</button>
      </>}
      <span role={loadFailed ? "alert" : "status"}>{status}</span>
      {loadFailed && <button onClick={() => setReload(v => v + 1)}>重试日线</button>}
      <button disabled={!count} onClick={exportImage}>导出图表</button>
    </div>
    {!symbol && <Empty title="选择一只证券开始查看">从交易或持仓表点击证券也可打开回放。</Empty>}
    {focusStatus&&<p className="r-note" role="status">{focusStatus}</p>}
    <div ref={node} className="r-kline" role="img" aria-label={`${symbol} 日线与模拟成交图`} style={{ height: replayMode ? 440 : 400 }} />
    {(markers.length > 0 || tradeStatus) && <p className="r-note" role="status">{markerStatus} {markerSummary} {tradeStatus}</p>}
    <details className="r-chart-tools"><summary>日期范围、指标与画线</summary>
      <div className="r-toolbar">
        {!embedded && <form onSubmit={e => { e.preventDefault(); if (input.trim()) setSymbol(input.trim()); }}><input aria-label="证券代码" placeholder="输入证券代码" value={input} onChange={e => setInput(e.target.value)} /><button type="submit">加载</button></form>}
        <label>开始 <input type="date" value={start} onChange={e => setStart(e.target.value)} /></label><label>结束 <input type="date" max={asOfDate} value={end} onChange={e => setEnd(e.target.value)} /></label>
        <button disabled={!start || !end || start > end} onClick={() => setRangeWindow({ startDate: start, endDate: end })}>加载日期区间</button>
        <button onClick={() => { setStart(""); setEnd(""); setRangeWindow({}); }}>{asOfDate ? "截至所选日期" : "最近行情"}</button>
        <button disabled={!count} onClick={() => chart.current?.scrollToDataIndex(0)}>向前查看历史</button>
      </div>
      <div className="r-toolbar">
        <button disabled={!count} onClick={() => draw("segment")}>趋势线</button><button disabled={!count} onClick={() => draw("horizontalStraightLine")}>水平线</button><button disabled={!count} onClick={() => draw("research_rect")}>区间框</button>
        <input aria-label="批注文字" placeholder="写下批注，再点击图表定位" value={note} onChange={e => setNote(e.target.value)} /><button disabled={!count || !note.trim()} onClick={() => draw("research_note")}>文字批注</button>
        <button disabled={!count} onClick={() => chart.current?.createIndicator({ name: "MA", paneId: "candle_pane" }, true)}>均线</button>
        <button disabled={!count} onClick={() => { const instance = chart.current; if (instance) for (const overlay of instance.getOverlays()) if (overlay.groupId !== "research-trade") instance.removeOverlay({ id: overlay.id }); changed(); }}>清除批注</button>
        <button disabled={!symbol || !chart.current} onClick={() => void s.act(async () => { await saveAnnotations(); s.setNotice("批注已保存到项目"); })}>{dirty ? "保存批注 · 未保存" : "保存批注"}</button>
      </div>
    </details>
  </div>;
}
