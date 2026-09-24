import type { QuoteInstrument } from "../../../../../packages/contracts/src/research";
import React, { useEffect, useRef, useState } from "react";
import { init, dispose, registerOverlay, type Chart, type KLineData, type OverlayCreate } from "klinecharts";
import { useKLineTimeLink } from "./ChartTimeLink";
import { useChartSession } from "./ChartSession";
import { useChartToolkit, type ChartPreferences } from "./ChartToolkit";
import { errorText, request, useResearch } from "./state";
import { Empty, Heading, tradeDirection } from "./ui";
import type { TablePage } from "./PagedTable";

registerOverlay({ name: "research_note", totalStep: 2, needDefaultPointFigure: true, createPointFigures: ({ coordinates, overlay }) => coordinates.length ? [{ type: "text", attrs: { x: coordinates[0].x, y: coordinates[0].y, text: String(overlay.extendData ?? "批注"), align: "left", baseline: "bottom" }, styles: { color: overlay.styles?.text?.color ?? "#267774", size: 13, backgroundColor: "#fffdf9", paddingLeft: 5, paddingRight: 5, paddingTop: 4, paddingBottom: 4 } }] : [] });
registerOverlay({ name: "research_rect", totalStep: 3, needDefaultPointFigure: true, createPointFigures: ({ coordinates }) => coordinates.length > 1 ? [{ type: "rect", attrs: { x: Math.min(coordinates[0].x, coordinates[1].x), y: Math.min(coordinates[0].y, coordinates[1].y), width: Math.abs(coordinates[1].x - coordinates[0].x), height: Math.abs(coordinates[1].y - coordinates[0].y) }, styles: { style: "stroke_fill", color: "rgba(38,119,116,.08)", borderColor: "#267774", borderSize: 1 } }] : [] });
registerOverlay({ name: "research_trade", totalStep: 1, needDefaultPointFigure: true, createPointFigures: ({ coordinates, overlay }) => {
  if (!coordinates.length) return [];
  const trade = overlay.extendData as TradeMarker, point = coordinates[0], buy = trade.side === "买入";
  const color = buy ? "#d04a45" : "#21845c", offset = buy ? 22 : -22;
  return [{ type: "line", attrs: { coordinates: [point, { x: point.x, y: point.y + offset }] }, styles: { color, size: 1 } },
    { type: "text", attrs: { x: point.x, y: point.y + offset, text: buy ? "买" : "卖", align: "center", baseline: buy ? "top" : "bottom" }, styles: { color: "#ffffff", size: 12, backgroundColor: color, paddingLeft: 4, paddingRight: 4, paddingTop: 3, paddingBottom: 3 } }];
} });
interface Bar { sourceWarning?: string; date: string; open: number; high: number; low: number; close: number; volume: number; turnover?:number|null; amount?:number|null; periodStart?:string; periodEnd?:string; factor?: number | null; rawOpen?: number | null; rawHigh?: number | null; rawLow?: number | null; rawClose?: number | null }
export interface TradeMarker { id?: string; date: string; price: number; adjustedPrice?: number; side: string; quantity?: number }
function dateAt(timestamp: number) { return new Date(timestamp + 8 * 3600000).toISOString().slice(0, 10); }
export function applyChartTheme(instance: Chart, container: HTMLDivElement) {
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
export function PriceChart({ symbol: initial = "", focusDate, trades = [], experimentId, projectId: explicitProjectId, tradeTable, embedded = false, asOfDate, replayMode = false, priceBasis: initialPriceBasis = "adjusted", initialStartDate, initialEndDate, focusedTrade, onTradeClick, footer, instrument, refreshVersion, onHistoryNeeded, onBarSelect, adjustedAvailable = true, annotationProjectId }: { annotationProjectId?:string; onBarSelect?: (date:string)=>void; adjustedAvailable?: boolean; onHistoryNeeded?: (beforeDate: string) => Promise<void>; instrument?: QuoteInstrument; refreshVersion?: number; symbol?: string; focusDate?: string; trades?: TradeMarker[]; experimentId?: string; projectId?: string; tradeTable?: string; embedded?: boolean; asOfDate?: string; replayMode?: boolean; priceBasis?: "raw" | "adjusted"; initialStartDate?: string; initialEndDate?: string; focusedTrade?: TradeMarker; footer?:React.ReactNode; onTradeClick?: (trade: TradeMarker) => void }) {
  const session=useChartSession();
  const s = useResearch(); const projectId = instrument ? undefined : explicitProjectId ?? (experimentId ? undefined : s.project?.id); const drawingProjectId = annotationProjectId ?? projectId;
  const [editableSymbol, setSymbol] = useState(initial || s.project?.universe.symbols[0] || ""); const symbol = embedded ? initial : editableSymbol; const [input, setInput] = useState(symbol);
  const [start, setStart] = useState(initialStartDate ?? ""); const [end, setEnd] = useState(initialEndDate ?? ""); const [rangeWindow, setRangeWindow] = useState<{ startDate?: string; endDate?: string }>({ startDate: initialStartDate, endDate: initialEndDate });
  const [stockPriceBasis,setStockPriceBasis]=useState<"raw"|"adjusted">(initialPriceBasis);const priceBasis=!adjustedAvailable || instrument && instrument.kind !== "stock" ? "raw" : replayMode?initialPriceBasis:stockPriceBasis;
  const [period,setPeriod]=useState<"day"|"week"|"month"|"trading_days">(session?.dailyPeriod??"day"); const [tradingDays,setTradingDays]=useState(session?.tradingDays??3); const [daysInput,setDaysInput]=useState(String(session?.tradingDays??3));const periodParams=period==="trading_days"?{tradingDays,anchorDate:"2015-01-05"}:{}; const [jump,setJump]=useState(""); const [jumpDate,setJumpDate]=useState("");
  const [sourceWarnings,setSourceWarnings]=useState<string[]>([]);const [barsLoaded,setBarsLoaded]=useState(false);
  const [annotationWarnings,setAnnotationWarnings]=useState<string[]>([]); const [status, setStatus] = useState(""); const [count, setCount] = useState(0);
  const node = useRef<HTMLDivElement>(null); const chart = useRef<Chart | null>(null);
  const [dirty, setDirty] = useState(false); const [loadFailed, setLoadFailed] = useState(false); const [reload, setReload] = useState(0);
  const [windowTrades, setWindowTrades] = useState<TradeMarker[]>([]);
  const [tradeStatus, setTradeStatus] = useState(""); const [focusStatus,setFocusStatus]=useState("");
  const factors = useRef(new Map<string, number>()); const [markerStatus, setMarkerStatus] = useState(""); const [markerSummary,setMarkerSummary]=useState("");
  const [hover,setHover]=useState<{x:number;y:number;bar:KLineData;previous?:KLineData}|null>(null);
  useEffect(()=>setHover(null),[symbol,period,priceBasis]);
  const dragged=useRef(false);
  const barAt=(event:React.PointerEvent<HTMLDivElement>)=>{
    const instance=chart.current;if(!instance)return null;
    const bounds=event.currentTarget.getBoundingClientRect(),x=event.clientX-bounds.left,y=event.clientY-bounds.top;
    const converted=instance.convertFromPixel([{x,y}]);const point=Array.isArray(converted)?converted[0]:converted;
    const index=point?.dataIndex;if(index==null)return null;
    const data=instance.getDataList(),bar=data[index];if(!bar)return null;
    return {x:Math.max(4,Math.min(x+16,bounds.width-226)),y:Math.max(4,Math.min(y+16,bounds.height-228)),bar,previous:data[index-1]};
  };
  const hoverNumber=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?value.toLocaleString("zh-CN",{maximumFractionDigits:3}):"—";
  const historyGesture = useRef(false), historyInFlight = useRef(false);
  const pendingHistory = useRef<((allowed: boolean) => void) | null>(null);
  const dragOrigin = useRef<{x:number;y:number}|null>(null);
  const permitHistory = () => {
    if (!instrument || replayMode || experimentId || toolkit.tool || historyInFlight.current) return;
    if (pendingHistory.current) { const resolve = pendingHistory.current; pendingHistory.current = null; resolve(true); }
    else historyGesture.current = true;
  };
  const restoreFocus = useRef<() => void>(()=>{});
  const tradeClick = useRef(onTradeClick); tradeClick.current = onTradeClick;
  const loadFocusDate = replayMode ? undefined : focusDate||jumpDate;
  const chartFocusDate=focusDate||jumpDate;
  const liveBar=useRef<((bar:KLineData)=>void)|null>(null);
  const saveQueue = useRef(Promise.resolve());
  const knownIds=useRef(new Set<string>()),pendingDeletes=useRef(new Set<string>());const saveRevision=useRef(0); const annotationsReady=useRef(false);
  const rebaseBlocked=useRef(false);
  const carriedPreferences = useRef<ChartPreferences | undefined>(session?.preferences);
  const toolkit=useChartToolkit(chart,node,()=>{setDirty(true);void s.act(saveAnnotations);});
  const saveAnnotations = () => {
    const instance = chart.current; if (!instance) return Promise.resolve();
    if(!annotationsReady.current||rebaseBlocked.current)return Promise.resolve();
    const annotations = toolkit.snapshot();
    const ids=new Set(annotations.flatMap(item=>item.id?[item.id]:[]));
    for(const id of knownIds.current)if(!ids.has(id))pendingDeletes.current.add(id);for(const id of ids)pendingDeletes.current.delete(id);const deletedIds=[...pendingDeletes.current];knownIds.current=ids;const revision=++saveRevision.current;
    const preferences=toolkit.preferences();if(session){session.preferences=preferences;session.onChange?.();}
    const pending = saveQueue.current.catch(() => {}).then(async () => { const saved=await request<{warnings:string[]}>("charts.save", { projectId:drawingProjectId, instrument, experimentId, symbol, period, ...periodParams, priceBasis, annotations, merge:true,deletedIds,preferences }); if(revision===saveRevision.current){deletedIds.forEach(id=>pendingDeletes.current.delete(id));setAnnotationWarnings(saved.warnings??[]);setDirty(false);} });
    saveQueue.current = pending; return pending;
  };
  useEffect(()=>{if(session){session.dailyPeriod=period;session.tradingDays=tradingDays;session.onChange?.();}},[period,tradingDays]);
  useEffect(() => { if (initial) { setSymbol(initial); setInput(initial); } }, [initial]);
  useEffect(() => {
    if (!node.current || !symbol) return;
    let active = true;rebaseBlocked.current=false;setHover(null);historyGesture.current=false;historyInFlight.current=false;
    const loadedTrades = new Map<string, TradeMarker>();
    setWindowTrades([]); setTradeStatus(""); factors.current.clear();annotationsReady.current=false;saveRevision.current++;knownIds.current=new Set();pendingDeletes.current=new Set();setAnnotationWarnings([]);setSourceWarnings([]);setBarsLoaded(false);
    const instance = init(node.current, { locale: "zh-CN", timezone: "Asia/Shanghai" });
    if (!instance) return;
    let focusFrame=0;
    const resizeAndFocus=()=>{
      if(node.current)node.current.parentElement?.style.setProperty("--chart-tool-height",`${Math.max(0,node.current.clientHeight-56)}px`);
      instance.resize();toolkit.fitPanes();cancelAnimationFrame(focusFrame);focusFrame=requestAnimationFrame(()=>{focusFrame=requestAnimationFrame(()=>{if(active&&chart.current===instance)restoreFocus.current();});});};
    chart.current = instance; applyChartTheme(instance, node.current); const themeObserver = new MutationObserver(() => { if (active && node.current) {applyChartTheme(instance, node.current);resizeAndFocus();} }); themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] }); setCount(0); setDirty(false); setLoadFailed(false); setStatus("正在读取日线…");
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
        let bars = await request<Bar[]>("data.bars", { projectId, instrument, experimentId, symbol, period:replayMode?"day":period,...periodParams, ...bounded, limit: 500 });
        if (!bars.length && type === "forward" && bounded.beforeDate && instrument && !experimentId && !replayMode && onHistoryNeeded) {
          const permitted = historyGesture.current || await new Promise<boolean>(resolve => { pendingHistory.current = resolve; });
          historyGesture.current = false;
          if (!active || !permitted) return;
          historyInFlight.current = true;
          setStatus("正在补取更早的行情，保留当前历史位置…");
          try { await onHistoryNeeded(bounded.beforeDate); } finally { historyInFlight.current = false; }

          if (!active) return;
          bars = await request<Bar[]>("data.bars", { instrument, symbol, period,...periodParams, ...bounded, limit: 500 });
          setStatus(bars.length ? `已补取 ${bars.length} 根历史行情` : "来源没有更早的行情");
        }
        if (type === "init" && rangeWindow.startDate) {
          let page = bars;
          while (active && page.length === 500) {
            const earliest = page.reduce((a, b) => a < b.date ? a : b.date, page[0].date).slice(0, 10);
            if (earliest <= rangeWindow.startDate) break;
            page = await request<Bar[]>("data.bars", { projectId, instrument, experimentId, symbol, period:replayMode?"day":period,...periodParams, ...chartDateRange(rangeWindow, asOfDate), beforeDate: earliest, limit: 500 });
            if (page.some(b => b.date.slice(0, 10) >= earliest)) throw new Error("历史行情分页未前进。");
            bars.push(...page);
          }
        }
        if (!active) return;
        setSourceWarnings(previous=>[...new Set([...previous,...bars.flatMap(bar=>bar.sourceWarning?[bar.sourceWarning]:[])])]);setBarsLoaded(true);
        if (priceBasis === "raw" && (!instrument || instrument.kind === "stock") && bars.some(b => [b.rawOpen, b.rawHigh, b.rawLow, b.rawClose].some(value => typeof value !== "number" || !Number.isFinite(value)))) throw new Error("此区间缺少部分原始价格，无法绘制不复权日线。可切换前复权查看连续走势。");
        const data = bars.map(b => {
          if (typeof b.factor === "number" && b.factor > 0) factors.current.set(b.date.slice(0, 10), b.factor);
          return { ...b, ...(priceBasis === "raw" ? { open: b.rawOpen ?? b.open, high: b.rawHigh ?? b.high, low: b.rawLow ?? b.low, close: b.rawClose ?? b.close } : {}), turnover:typeof b.turnover==="number"?b.turnover:typeof b.amount==="number"?b.amount:undefined, timestamp: Date.parse(`${b.date.slice(0, 10)}T00:00:00+08:00`) };
        }).filter(b => Number.isFinite(b.timestamp)).sort((a, b) => a.timestamp - b.timestamp);
        callback(data, replayMode && rangeWindow.startDate && rangeWindow.endDate ? { forward: false, backward: false } : type === "init" ? { forward: data.length > 0, backward: (anchor != null || !!rangeWindow.endDate) && data.length > 0 } : data.length > 0);
        delivered = true;
        setCount(instance.getDataList().length);toolkit.reconcileTurnover();
        if (type === "init") { setStatus(data.length ? `${symbol} · ${data.length} 根${period==="week"?"周线":period==="month"?"月线":period==="trading_days"?`${tradingDays}交易日线`:"日线"}` : "没有这只证券在该区间的日线数据"); if (data.length > 0 && instance.getDataList().length > 0) { if (replayMode && node.current) { /* KLineChart default barSpaceLimit is 1–50; keep long histories at 6px. */ instance.setBarSpace(Math.max(6, Math.min(50, (node.current.clientWidth - 90) / (data.length + 1)))); instance.setOffsetRightDistance(0); } if (anchor != null && Number.isFinite(anchor)) instance.scrollToTimestamp(anchor); } }
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
    },subscribeBar:({callback})=>{liveBar.current=callback;},unsubscribeBar:()=>{liveBar.current=null;} });
    if(instrument)instance.setStyles({candle:{tooltip:{showRule:"none"}},indicator:{tooltip:{showRule:"follow_cross",showType:"rect"}}});
    instance.setSymbol({ ticker: symbol, pricePrecision: 2, volumePrecision: 0 }); instance.setPeriod({ type: replayMode||period==="trading_days"?"day":period, span:period==="trading_days"?tradingDays:1 });
    carriedPreferences.current=session?.preferences??carriedPreferences.current;toolkit.applyPreferences(carriedPreferences.current);
    void request<{ annotations: OverlayCreate[];preferences:ChartPreferences;warnings:string[] }>("charts.load", { projectId:drawingProjectId, instrument, experimentId, symbol, period, ...periodParams, priceBasis }).then(({ annotations,preferences,warnings }) => { if(!active)return;toolkit.install(annotations);knownIds.current=new Set(annotations.flatMap(item=>item.id?[item.id]:[]));toolkit.applyPreferences(carriedPreferences.current ?? preferences);if(instance.getDataList().length)toolkit.reconcileTurnover();setAnnotationWarnings(warnings??[]);annotationsReady.current=true; }).catch(e => { if (active) s.setError(errorText(e)); });
    const paneChanged=()=>{if(active){toolkit.fitPanes();void s.act(saveAnnotations);}};instance.subscribeAction("onPaneDrag",paneChanged);
    const observer = new ResizeObserver(resizeAndFocus); observer.observe(node.current);
    if(replayMode){const page=node.current.closest('.r-page');if(page)observer.observe(page);if(node.current.parentElement)observer.observe(node.current.parentElement);}
    document.fonts.addEventListener("loadingdone",resizeAndFocus);
    void document.fonts.ready.then(()=>{if(active)resizeAndFocus();});
    const container = node.current;
    return () => { carriedPreferences.current = toolkit.preferences();if(session){session.preferences=carriedPreferences.current;session.dailyPeriod=period;session.tradingDays=tradingDays;session.onChange?.();} active = false; pendingHistory.current?.(false);pendingHistory.current=null; instance.unsubscribeAction("onPaneDrag",paneChanged);cancelAnimationFrame(focusFrame); document.fonts.removeEventListener("loadingdone",resizeAndFocus); themeObserver.disconnect(); observer.disconnect(); dispose(container); chart.current = null; };
  }, [symbol, projectId, drawingProjectId, loadFocusDate, experimentId, tradeTable, rangeWindow, asOfDate, reload, priceBasis, replayMode,period,tradingDays,instrument?.kind]);
  useEffect(()=>{
    const instance=chart.current;if(!instrument||replayMode||!refreshVersion||!instance||rebaseBlocked.current)return;let active=true;
    void (async()=>{
      const loaded=instance.getDataList();
      const range=chartDateRange({...rangeWindow,...(loaded.length?{startDate:dateAt(loaded[0].timestamp)}:{})},asOfDate);
      let page=await request<Bar[]>("data.bars",{instrument,symbol,period,...periodParams,...range,limit:500}),bars=[...page];
      while(active&&loaded.length&&page.length===500){const beforeDate=page.reduce((a,b)=>a<b.date?a:b.date,page[0].date).slice(0,10);if(beforeDate<=range.startDate!)break;page=await request<Bar[]>("data.bars",{instrument,symbol,period,...periodParams,...range,beforeDate,limit:500});if(page.some(bar=>bar.date.slice(0,10)>=beforeDate))throw Error("行情分页未前进，保留已有图表。");bars.push(...page);}
      if(!active||chart.current!==instance)return;
      if(!instance.getDataList().length){if(bars.length)instance.resetData();return;}
      if(priceBasis==='adjusted'&&bars.some(bar=>{const old=factors.current.get(bar.date.slice(0,10));return old!==undefined&&old!==bar.factor;})){
        rebaseBlocked.current=true;annotationsReady.current=false;setHover(null);setStatus("复权口径已更新，重新载入以统一价格与批注；当前图表和批注编辑已暂停。");setLoadFailed(true);return;
      }
      const last=instance.getDataList().at(-1)?.timestamp;if(last==null)return;
      for(const bar of bars.sort((a,b)=>a.date.localeCompare(b.date))){const timestamp=Date.parse(`${bar.date.slice(0,10)}T00:00:00+08:00`);if(timestamp<last)continue;
        const raw=priceBasis==='raw';if(raw&&instrument.kind==='stock'&&[bar.rawOpen,bar.rawHigh,bar.rawLow,bar.rawClose].some(value=>typeof value!=='number'||!Number.isFinite(value)))throw Error("新日线缺少原始价格，保留已有图表。");
        if(typeof bar.factor==='number'&&bar.factor>0)factors.current.set(bar.date.slice(0,10),bar.factor);
        liveBar.current?.({...bar,open:raw?bar.rawOpen??bar.open:bar.open,high:raw?bar.rawHigh??bar.high:bar.high,low:raw?bar.rawLow??bar.low:bar.low,close:raw?bar.rawClose??bar.close:bar.close,timestamp,turnover:bar.turnover??bar.amount??undefined});
      }setCount(instance.getDataList().length);
    })().catch(error=>{if(active)setStatus(errorText(error));});return()=>{active=false;};
  },[refreshVersion]);
  useKLineTimeLink(chart,`${symbol}:${period}:${count}:${refreshVersion}:${reload}:${priceBasis}`);
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
        onRightClick:event=>event.preventDefault?.(),
        onClick: () => { setMarkerStatus(`${date} ${trade.side} · ${trade.price.toFixed(4)} 元${trade.quantity === undefined ? "" : ` · ${trade.quantity.toLocaleString("zh-CN")} 股`}`); tradeClick.current?.(trade); } });
      shown++;
    });
    setMarkerSummary(`已载入 ${shown} 个模拟成交点，可拖动或逐笔定位${missing ? `；${missing} 笔缺少当日复权因子，未标注` : ""}`);
  }, [JSON.stringify(markers), count, symbol, priceBasis]);
  restoreFocus.current = () => {
    const instance = chart.current;
    if (!chartFocusDate || count === 0 || !instance) {setFocusStatus("");return;}
    const data=instance.getDataList();const index=data.findIndex(bar=>replayMode?dateAt(bar.timestamp)===chartFocusDate.slice(0,10):dateAt(bar.timestamp)>=chartFocusDate.slice(0,10));
    if(index<0){setFocusStatus(`定位日期 ${chartFocusDate.slice(0,10)} 没有已载日线`);return;}
    const width=instance.getSize()?.width ?? node.current?.clientWidth ?? 600;
    const visible=Math.max(1,Math.floor((width-100)/instance.getBarSpace().bar)-2);
    const right=Math.min(data.length-1,Math.max(visible-1,index+Math.floor(visible/2)));
    instance.setOffsetRightDistance(0);instance.scrollToDataIndex(right,0);
    const bar=data[index];setFocusStatus(`定位日线 ${dateAt(bar.timestamp)} · 开 ${bar.open.toFixed(2)} 高 ${bar.high.toFixed(2)} 低 ${bar.low.toFixed(2)} 收 ${bar.close.toFixed(2)}（${priceBasis==='raw'?'原始价格':'前复权'}）`);
    const coordinate=instance.convertToPixel({dataIndex:index,value:bar.close},{paneId:'candle_pane'});
    if(!Array.isArray(coordinate))instance.executeAction('onCrosshairChange',{...coordinate,paneId:'candle_pane'});
  };
  useEffect(()=>{const frame=requestAnimationFrame(()=>restoreFocus.current());return()=>cancelAnimationFrame(frame);}, [chartFocusDate, count, priceBasis, focusedTrade?.id]);
  useEffect(()=>{setMarkerStatus(focusedTrade?`${focusedTrade.date.slice(0,10)} ${focusedTrade.side} · ${focusedTrade.price.toFixed(4)} 元${focusedTrade.quantity===undefined?'':` · ${focusedTrade.quantity.toLocaleString('zh-CN')} 股`}`:'');},[focusedTrade]);
  const sortedTrades = [...markers].sort((a, b) => a.date.localeCompare(b.date));
  const selectedTrade = sortedTrades.findIndex(t => focusedTrade ? focusedTrade.id !== undefined ? t.id === focusedTrade.id : t.date === focusedTrade.date && t.side === focusedTrade.side && t.price === focusedTrade.price && t.quantity === focusedTrade.quantity : false);
  const locate = (trade: TradeMarker) => { tradeClick.current?.(trade); setMarkerStatus(`${trade.date.slice(0, 10)} ${trade.side} · ${trade.price.toFixed(4)} 元${trade.quantity === undefined ? "" : ` · ${trade.quantity.toLocaleString("zh-CN")} 股`}`); };
  const exportImage = () => void s.act(async () => { const dataUrl = chart.current!.getConvertPictureUrl(true, "png", getComputedStyle(node.current!).backgroundColor); const path = await window.v3Research!.exportFile({ format: "png", dataUrl, suggestedName: `${symbol}-日线.png` }); if (path) s.setNotice(`已导出：${path}`); });
  const chartTools=toolkit.controls(<>
    <label>跳转日期<input type="date" aria-label="跳转日期" max={asOfDate} value={jump} onChange={e=>setJump(e.target.value)}/></label><button disabled={!jump||!!asOfDate&&jump>asOfDate} onClick={()=>{const instance=chart.current;if(instance?.getDataList().some(bar=>dateAt(bar.timestamp)===jump)){instance.scrollToTimestamp(Date.parse(`${jump}T00:00:00+08:00`));if(!replayMode)setJumpDate(jump);}else if(!replayMode){setRangeWindow({});setJumpDate(jump);}toolkit.close();}}>定位日期</button>
    <label>开始<input type="date" value={start} onChange={e=>setStart(e.target.value)}/></label><label>结束<input type="date" max={asOfDate} value={end} onChange={e=>setEnd(e.target.value)}/></label>
    <button disabled={!start||!end||start>end} onClick={()=>{setRangeWindow({startDate:start,endDate:end});toolkit.close();}}>加载日期区间</button>
    {replayMode&&<button onClick={()=>{setStart(initialStartDate??"");setEnd(initialEndDate??"");setRangeWindow({startDate:initialStartDate,endDate:initialEndDate});toolkit.close();}}>完整回测区间</button>}
    <button disabled={!count} onClick={exportImage}>导出图表</button><button disabled={!annotationsReady.current} onClick={()=>void s.act(saveAnnotations)}>{dirty?"保存批注 · 未保存":"保存批注和图表设置"}</button>
    {annotationWarnings.map(warning=><p className="r-note" key={warning}>{warning}</p>)}{focusStatus&&<p className="r-note">{focusStatus}</p>}{(markers.length>0||tradeStatus)&&<p className="r-note">{markerStatus} {markerSummary} {tradeStatus}</p>}
  </>);
  return <div className={`r-chart-panel${embedded ? " r-chart-embedded" : ""}`}>
    {!embedded && <Heading title="行情与批注" description="拖动、缩放日线；添加趋势线、区间和研究笔记。" />}
    <div className="r-toolbar r-chart-navigation">
      {!replayMode&&<>{(!instrument || instrument.kind === "stock")&&adjustedAvailable&&<select aria-label="个股复权口径" value={stockPriceBasis} onChange={e=>setStockPriceBasis(e.target.value as "raw"|"adjusted")}><option value="adjusted">前复权</option><option value="raw">不复权</option></select>}{instrument?.kind==="stock"&&!adjustedAvailable&&<span>原始价格 · 前复权不可用</span>}<select aria-label="K线周期" value={period} onChange={e=>setPeriod(e.target.value as "day"|"week"|"month"|"trading_days")}><option value="day">日线</option><option value="week">周线</option><option value="month">月线</option><option value="trading_days">N 交易日</option></select>{period==="trading_days"&&<label className="r-trading-days"><input aria-label="每根K线交易日数" type="number" min={2} max={250} value={daysInput} onChange={e=>setDaysInput(e.target.value)} onBlur={()=>{const n=Number(daysInput);if(Number.isInteger(n)&&n>=2&&n<=250)setTradingDays(n);else setDaysInput(String(tradingDays));}} onKeyDown={e=>{if(e.key==="Enter")e.currentTarget.blur();}}/>交易日</label>}</> }
      {replayMode && <>
        <button disabled={!sortedTrades.length} onClick={() => locate(sortedTrades[0])}>首笔成交</button>
        <button disabled={selectedTrade <= 0} onClick={() => locate(sortedTrades[selectedTrade - 1])}>上一笔</button>
        <button disabled={!sortedTrades.length || selectedTrade >= sortedTrades.length - 1} onClick={() => locate(sortedTrades[selectedTrade + 1])}>下一笔</button>
      </>}
      <span role={loadFailed ? "alert" : "status"}>{status}</span>
      {loadFailed && <button onClick={() => setReload(v => v + 1)}>{rebaseBlocked.current?"重新载入图表与批注":"重试日线"}</button>}
    </div>
    {[...new Set([...sourceWarnings,...annotationWarnings])].map(warning=><p className="r-note" role="status" key={warning}>{warning}</p>)}
    {!symbol && <Empty title="选择一只证券开始查看">从交易或持仓表点击证券也可打开回放。</Empty>}
    <div className="r-price-values" aria-label="当前K线数值"><strong>{hover?dateAt(hover.bar.timestamp):"移至 K 线查看"}</strong>{[["开",hover?.bar.open],["高",hover?.bar.high],["低",hover?.bar.low],["收",hover?.bar.close]].map(([label,value])=><span key={String(label)}>{label}<b>{hoverNumber(value)}</b></span>)}<details><summary>详情</summary><dl><div><dt>周期 / 价格口径</dt><dd>{replayMode?"日线":({day:"日线",week:"周线",month:"月线",trading_days:`${tradingDays}交易日`})[period]} · {priceBasis==="raw"?"不复权":"复权"}</dd></div><div><dt>较前一根</dt><dd>{hoverNumber(hover?.previous?hover.bar.close-hover.previous.close:undefined)}</dd></div><div><dt>较前一根（%）</dt><dd>{hover?.previous&&hover.previous.close!==0?`${hoverNumber((hover.bar.close/hover.previous.close-1)*100)}%`:"—"}</dd></div><div><dt>成交量（股）</dt><dd>{hoverNumber(hover?.bar.volume)}</dd></div><div><dt>成交额（元）</dt><dd>{hoverNumber(hover?.bar.turnover)}</dd></div></dl></details></div>
    <div className={`r-chart-canvas${toolkit.focused?" r-chart-focus":""}`} inert={rebaseBlocked.current?true:undefined} onKeyDown={toolkit.key} onMouseLeave={()=>{if(replayMode)requestAnimationFrame(()=>restoreFocus.current());}}><div ref={node} className="r-kline" tabIndex={0} onMouseDownCapture={toolkit.begin} onPointerDownCapture={event=>{dragged.current=false;dragOrigin.current={x:event.clientX,y:event.clientY};}} onPointerMoveCapture={event=>{if(!toolkit.tool)setHover(barAt(event));else setHover(null);const origin=dragOrigin.current;if(origin&&event.buttons&&Math.hypot(event.clientX-origin.x,event.clientY-origin.y)>6){dragged.current=true;permitHistory();dragOrigin.current=null;}}} onPointerUpCapture={event=>{if(!dragged.current&&!toolkit.tool&&event.button===0){const picked=barAt(event);if(picked)onBarSelect?.(dateAt(picked.bar.timestamp));}dragOrigin.current=null;}} onWheelCapture={permitHistory} style={{cursor:toolkit.tool?"crosshair":undefined}} role="img" aria-label={`${symbol} 日线与模拟成交图`} />{barsLoaded&&!count&&!loadFailed&&<div className="r-chart-empty" role="status">暂无此区间行情{instrument&&<small>可使用上方“更新当前行情”，或补取其他日期。</small>}</div>}{chartTools}</div>
    {footer}
  </div>;
}
