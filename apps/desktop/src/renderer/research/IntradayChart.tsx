import React, { useEffect, useRef, useState } from "react";
import { init, dispose, type Chart, type KLineData, type OverlayCreate } from "klinecharts";
import type { IntradayPeriod, QuoteInstrument, QuoteStatus, QuoteBar } from "../../../../../packages/contracts/src/research";
import { useKLineTimeLink } from "./ChartTimeLink";
import { HQIntraday } from "./HQIntraday";
import { useChartVisible, useIntradayQuote } from "./useIntradayQuote";
import { useChartToolkit, type ChartPreferences } from "./ChartToolkit";
import { request, errorText } from "./state";
import { applyChartTheme } from "./PriceChart";
import { useChartSession } from "./ChartSession";

function completeCandle(bar: QuoteBar): bar is QuoteBar & {timestamp:number;open:number;high:number;low:number;close:number} {
 return Number.isFinite(bar.timestamp)&&[bar.open,bar.high,bar.low,bar.close].every(value=>typeof value==='number'&&Number.isFinite(value));
}
export function MinuteCandles({ quote, instrument, period, annotationProjectId }: { annotationProjectId?:string; quote: QuoteStatus | null; instrument: QuoteInstrument; period: IntradayPeriod }) {
  const session=useChartSession();
  const node = useRef<HTMLDivElement>(null), instance = useRef<Chart | null>(null), update = useRef<((bar: KLineData) => void) | null>(null);
  const data = useRef<KLineData[]>([]), initialized = useRef(false);
  const latestQuote=useRef(quote),latestInstrument=useRef(instrument);latestQuote.current=quote;latestInstrument.current=instrument;
  const [historyError,setHistoryError]=useState(""),[barCount,setBarCount]=useState(0);
  const [annotationError, setAnnotationError] = useState("");
  const ready = useRef(false), generation = useRef(0), known = useRef(new Set<string>()), queue = useRef(Promise.resolve());
  const preferences = useRef<ChartPreferences | undefined>(session?.preferences);
  const deletes=useRef(new Set<string>()),saveSerial=useRef(0);
  const toolkit = useChartToolkit(instance, node, () => { void saveAnnotations(); });
  const saveAnnotations = async () => {
    if (!ready.current || !instance.current) return;
    const annotations = toolkit.snapshot(), ids = new Set(annotations.flatMap(item => item.id ? [item.id] : []));
    for(const id of known.current)if(!ids.has(id))deletes.current.add(id);for(const id of ids)deletes.current.delete(id);
    const deletedIds = [...deletes.current]; known.current = ids; const serial=++saveSerial.current;
    const current = generation.current;
    preferences.current = toolkit.preferences();if(session){session.preferences=preferences.current;session.onChange?.();}
    const params = { projectId: annotationProjectId, instrument, symbol: instrument.symbol, period, priceBasis:"raw", annotations, deletedIds, merge:true, preferences:preferences.current };
    queue.current = queue.current.catch(() => {}).then(async () => { await request("charts.save", params); });
    try { await queue.current; if(current===generation.current&&serial===saveSerial.current){deletedIds.forEach(id=>deletes.current.delete(id));setAnnotationError("");} } catch(error) { if(current===generation.current)setAnnotationError(errorText(error)); }
  };
  data.current = (quote?.instrument.symbol===instrument.symbol&&quote?.instrument.kind===instrument.kind&&quote.period===period?quote.bars:[]).filter(completeCandle).map(bar => ({ ...bar, volume:typeof bar.volume==="number"&&Number.isFinite(bar.volume)?bar.volume:undefined, timestamp: bar.timestamp, turnover: bar.amount ?? bar.turnover ?? undefined }));
  useEffect(() => {
    if (!node.current) return; const element = node.current, chart = init(element, { locale: "zh-CN", timezone: "Asia/Shanghai" }); if (!chart) return;
    instance.current = chart; applyChartTheme(chart,element);chart.setStyles({candle:{tooltip:{showRule:"follow_cross",showType:"rect"}},indicator:{tooltip:{showRule:"follow_cross",showType:"rect"}}}); const theme=new MutationObserver(()=>applyChartTheme(chart,element));theme.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});chart.setDataLoader({ getBars: async ({ type, timestamp, callback }) => {
      if(type==="init"){callback(data.current,{forward:(latestQuote.current as (QuoteStatus & {hasMore?:boolean}) | null)?.hasMore===true,backward:false});initialized.current=data.current.length>0;setBarCount(chart.getDataList().length);return;}
      if(type!=="forward"||timestamp==null){callback([],false);return;}
      const target=latestInstrument.current;
      try{const page=await request<QuoteStatus & {hasMore?:boolean}>("market.intraday",{instrument:target,period,beforeDate:new Date(timestamp).toISOString(),limit:500,refresh:false});if(instance.current!==chart||latestInstrument.current.symbol!==target.symbol||latestInstrument.current.kind!==target.kind)return;
       const bars=page.bars.filter(completeCandle).map(bar=>({...bar,volume:typeof bar.volume==='number'&&Number.isFinite(bar.volume)?bar.volume:undefined,turnover:bar.amount??bar.turnover??undefined}));callback(bars,{forward:page.hasMore===true,backward:false});setBarCount(chart.getDataList().length);setHistoryError("");
      }catch(error){if(instance.current===chart&&latestInstrument.current.symbol===target.symbol){callback([],false);setHistoryError(errorText(error));}}
    }, subscribeBar: ({ callback }) => { update.current = callback; }, unsubscribeBar: () => { update.current = null; } });
    chart.setSymbol({ ticker: instrument.symbol, pricePrecision: 3, volumePrecision: 0 }); chart.setPeriod({ type: "minute", span: Number.parseInt(period) || 1 });
    preferences.current=session?.preferences??preferences.current;toolkit.applyPreferences(preferences.current); const observer = new ResizeObserver(() => {chart.resize();toolkit.fitPanes();element.parentElement?.style.setProperty("--chart-tool-height",`${Math.max(0,element.clientHeight-56)}px`);}); observer.observe(element);
    return () => { preferences.current=toolkit.preferences();if(session){session.preferences=preferences.current;session.onChange?.();}theme.disconnect();observer.disconnect(); update.current = null; initialized.current = false; dispose(element); instance.current = null; };
  }, [period]);
  useEffect(() => { initialized.current = false; instance.current?.setSymbol({ ticker: instrument.symbol, pricePrecision: 3, volumePrecision: 0 }); }, [instrument.symbol, instrument.kind]);
  useEffect(() => {
    let active=true;generation.current++;ready.current=false;known.current=new Set();deletes.current=new Set();setAnnotationError("");toolkit.install([]);
    void queue.current.catch(()=>{}).then(()=>request<{annotations:OverlayCreate[];preferences:ChartPreferences}>("charts.load",{projectId:annotationProjectId,instrument,symbol:instrument.symbol,period,priceBasis:"raw"})).then(value=>{if(!active)return;toolkit.install(value.annotations);known.current=new Set(value.annotations.flatMap(item=>item.id?[item.id]:[]));if(!preferences.current){toolkit.applyPreferences(value.preferences);preferences.current=toolkit.preferences();}ready.current=true;}).catch(error=>{if(active)setAnnotationError(errorText(error));});
    return()=>{active=false;generation.current++;ready.current=false;};
  },[annotationProjectId,instrument.kind,instrument.symbol,period]);
  useEffect(() => {
    const chart = instance.current; if (!chart || !data.current.length) return;
    if (!initialized.current) { chart.resetData(); initialized.current = true; return; }
    const last = chart.getDataList().at(-1)?.timestamp;
    // Update the live tail through the native subscription; keep scale and scroll position.
    for (const bar of data.current) if (last == null || bar.timestamp >= last) update.current?.(bar);
  }, [quote]);
  useEffect(()=>{const chart=instance.current;if(!chart)return;const changed=()=>{toolkit.fitPanes();void saveAnnotations();};chart.subscribeAction("onPaneDrag",changed);return()=>chart.unsubscribeAction("onPaneDrag",changed);},[instrument.kind,instrument.symbol,period,annotationProjectId]);
  useKLineTimeLink(instance,`${instrument.kind}:${instrument.symbol}:${period}`);
  return <><span className="r-minute-count" title="向左拖动读取已有缓存">{barCount} 根</span>{historyError&&<p role="alert">更早缓存读取失败：{historyError}</p>}{annotationError&&<p role="alert">批注保存或读取失败：{annotationError}</p>}<div className={`r-intraday-canvas${toolkit.focused?" r-chart-focus":""}`} onKeyDown={toolkit.key}><div ref={node} style={{position:"absolute",inset:0}} tabIndex={0} onMouseDownCapture={toolkit.begin} aria-label={`${instrument.symbol} ${period} 分钟K线`}/>{toolkit.controls(<button disabled={!ready.current} onClick={()=>void saveAnnotations()}>保存批注和图表设置</button>)}</div></>;
}
export function IntradayChart({ instrument, period, paused, intervalSeconds, annotationProjectId }: { annotationProjectId?:string; instrument: QuoteInstrument; period: IntradayPeriod; paused: boolean; intervalSeconds: number }) {
  const node = useRef<HTMLDivElement>(null), visible = useChartVisible(node);
  const { quote, error, loading, refresh, autoFailed } = useIntradayQuote(instrument, period, visible, paused, intervalSeconds);
  return <div ref={node} className="r-intraday-panel"><div className="r-toolbar"><span>{quote?.coverage?.source ?? "尚未取得分钟数据"}</span><button disabled={loading} onClick={() => void refresh()}>{loading ? "更新中…" : "刷新本图"}</button></div>{autoFailed&&<p role="status">来源未完成，本图已暂停自动重试；已有图表保留，可手动刷新本图。</p>}{error && <p role="alert">{error}</p>}<details className="r-minute-coverage"><summary>数据说明 · {quote?.coverage?.endDate?.slice(5,16).replace("T"," ")??"尚无日期"}</summary>{quote?.message && <p className="r-note">{quote.message}</p>}{quote?.coverage && <p className="r-note">{quote.coverage.startDate ?? "—"} — {quote.coverage.endDate ?? "—"} · 量：{quote.coverage.volumeUnit} / 额：{quote.coverage.amountUnit}{quote.bars.at(-1)?.complete === false ? " · 当前分钟尚未完成" : ""}</p>}</details>{period!=="intraday"&&!!quote?.bars.some(bar=>!completeCandle(bar))&&<p className="r-note">{quote.bars.filter(bar=>!completeCandle(bar)).length} 根数据缺少完整开高低收，未绘制为蜡烛；可切换分时查看已有价格。</p>}{!!quote?.bars.some(bar=>typeof bar.volume!=="number"||!Number.isFinite(bar.volume))&&<p className="r-note">部分分钟缺少成交量，该字段保持缺失。</p>}{period === "intraday" ? <HQIntraday quote={quote} symbol={instrument.symbol}/> : <MinuteCandles annotationProjectId={annotationProjectId} quote={quote} instrument={instrument} period={period}/>} {!loading && !quote?.bars.length && <p className="r-note">暂无该周期的真实行情，日线数据不能代替分钟数据。</p>}</div>;
}
