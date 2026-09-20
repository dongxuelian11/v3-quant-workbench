import React, { useState, useRef, useEffect } from "react";
import type { IntradayPeriod, QuoteInstrument, QuoteStatus, ChartViewState, JsonObject } from "../../../../../packages/contracts/src/research";
import { ChartTimeScope, createTimeLink } from "./ChartTimeLink";
import { IntradayChart } from "./IntradayChart";
import { errorText,request } from "./state";
import { useChartVisible,tradingHours } from "./useIntradayQuote";
import { FormulaChart } from "./FormulaChart";
import { useObjectPanel,useWorkspace } from "./workspace";
import { ChartSessionScope,type ChartSession } from "./ChartSession";

type ViewPeriod = "daily" | "formula" | IntradayPeriod;
interface Tile { id: number; period: ViewPeriod; pinned?: QuoteInstrument; }
const periods: [ViewPeriod, string][] = [["daily", "日 / 周 / 月"], ["formula", "通达信公式（日线）"], ["intraday", "分时"], ["1m", "1 分钟"], ["5m", "5 分钟"], ["15m", "15 分钟"], ["30m", "30 分钟"], ["60m", "60 分钟"]];
export function ChartWorkspace({ instrument, renderDaily, annotationProjectId, onDailyQuote, fixedDate }: {fixedDate?:boolean;onDailyQuote?:(instrument:QuoteInstrument,quote:QuoteStatus)=>void; annotationProjectId?:string; instrument: QuoteInstrument; renderDaily: (instrument: QuoteInstrument,revision:number) => React.ReactNode }) {
  const panel=useObjectPanel(),workspace=useWorkspace();const defaults=workspace.preferences.chartDefaults;const saved=useRef(panel?.chartViews??(!fixedDate&&defaults?.period?[{id:"0",instrument,period:defaults.period as ChartViewState["period"],tradingDays:Number(defaults.tradingDays)||3,preferences:defaults.preferences as JsonObject}]:[]));
  const root=useRef<HTMLDivElement>(null),visible=useChartVisible(root);
  const timeLink=useRef(createTimeLink());
  const opened = useRef(1);
  const sessions=useRef<ChartSession[]>([0,1,2,3].map(index=>{const value=saved.current[index];return {dailyPeriod:value&&["day","week","month","trading_days"].includes(value.period)?value.period as ChartSession["dailyPeriod"]:"day",tradingDays:value?.tradingDays??3,preferences:value?.preferences as ChartSession["preferences"],formula:value?.formulaView?.draft?value.formulaView as unknown as ChartSession["formula"]:undefined};}));
  const [count, setCount] = useState(saved.current.length||1), [paused, setPaused] = useState(false), [interval, setInterval] = useState(60);
  const [tiles, setTiles] = useState<Tile[]>([0,1,2,3].map(index=>{const value=saved.current[index];return {id:index,period:value?(value.formulaView?.mode==="formula"?"formula":(["day","week","month","trading_days"].includes(value.period)?"daily":value.period)) as ViewPeriod:(["daily","intraday","5m","15m"] as ViewPeriod[])[index],...(value?.fixed?{pinned:value.instrument}:{})};}));
  opened.current = Math.max(opened.current, count);
  const [dailyRevisions,setDailyRevisions]=useState<Record<string,number>>({}),[dailyErrors,setDailyErrors]=useState<Record<string,string>>({}),[dailyLoading,setDailyLoading]=useState<Record<string,boolean>>({});
  const dailyBusy=useRef(new Set<string>()),dailyFailed=useRef(new Set<string>());
  const quoteKey=(target:QuoteInstrument)=>`${target.kind}:${target.symbol}`;
  const refreshDaily=async(target:QuoteInstrument,automatic=false)=>{const key=quoteKey(target);if(fixedDate||dailyBusy.current.has(key)||automatic&&dailyFailed.current.has(key))return;dailyBusy.current.add(key);setDailyLoading(values=>({...values,[key]:true}));try{const selected=tiles.find(tile=>["daily","formula"].includes(tile.period)&&quoteKey(tile.pinned??instrument)===key);const session=selected?sessions.current[selected.id]:undefined;const period=session?.dailyPeriod??"day";const value=await request<QuoteStatus>("market.quote",{instrument:target,period,...(period==="trading_days"?{tradingDays:session?.tradingDays??3,anchorDate:"2015-01-05"}:{}),refresh:true,autoRefresh:automatic,refreshIntervalSeconds:interval});onDailyQuote?.(target,value);if(value.status==='source_error'){dailyFailed.current.add(key);setDailyErrors(values=>({...values,[key]:value.message??"来源未完成"}));}else{dailyFailed.current.delete(key);setDailyErrors(values=>({...values,[key]:""}));}if(value.bars.length)setDailyRevisions(values=>({...values,[key]:(values[key]??0)+1}));}catch(error){dailyFailed.current.add(key);setDailyErrors(values=>({...values,[key]:errorText(error)}));}finally{dailyBusy.current.delete(key);setDailyLoading(values=>({...values,[key]:false}));}};
  const dailyTargets=tiles.slice(0,count).filter(tile=>tile.period==='daily'||tile.period==='formula').map(tile=>tile.pinned??instrument);
  const dailyIdentity=dailyTargets.map(quoteKey).join('|'),refreshAll=useRef(()=>{});
  refreshAll.current=()=>{for(const target of dailyTargets)void refreshDaily(target,true);};
  useEffect(()=>{if(visible&&!paused&&!fixedDate)refreshAll.current();},[visible,paused,fixedDate,dailyIdentity]);
  useEffect(()=>{if(!visible||paused||fixedDate)return;const timer=window.setInterval(()=>{if(tradingHours())refreshAll.current();},interval*1000);return()=>clearInterval(timer);},[visible,paused,fixedDate,interval,dailyIdentity]);
  const persistViews=()=>{if(!panel)return;const views:ChartViewState[]=tiles.slice(0,count).map(tile=>({id:String(tile.id),instrument:tile.pinned??instrument,period:tile.period==='daily'||tile.period==='formula'?sessions.current[tile.id].dailyPeriod??'day':tile.period,tradingDays:sessions.current[tile.id].tradingDays??3,anchorDate:'2015-01-05',fixed:!!tile.pinned,preferences:sessions.current[tile.id].preferences as unknown as JsonObject,formulaView:{mode:tile.period,...sessions.current[tile.id].formula} as unknown as JsonObject}));if(JSON.stringify(panel.chartViews)!==JSON.stringify(views))workspace.updatePanel(panel.id,{chartViews:views});};
  const rememberDefaults=(index:number,tile=tiles[index])=>{
    if(fixedDate||!panel||workspace.active?.id!==panel.id)return;
    const session=sessions.current[index],preferences=session.preferences;
    const value:JsonObject={period:tile.period==='daily'||tile.period==='formula'?session.dailyPeriod??'day':tile.period,tradingDays:session.tradingDays??3,...(preferences?{preferences:{axis:preferences.axis,continuous:preferences.continuous??false,indicators:preferences.indicators as unknown as JsonObject[]}}:{})};
    if(JSON.stringify(value)!==JSON.stringify(workspace.preferences.chartDefaults))void workspace.savePreferences({chartDefaults:value}).catch(error=>setDailyErrors(values=>({...values,[quoteKey(instrument)]:`图表偏好未保存：${errorText(error)}`})));
  };
  sessions.current.forEach((session,index)=>{session.onChange=()=>{persistViews();rememberDefaults(index);};});
  useEffect(persistViews,[JSON.stringify(tiles),count,instrument.kind,instrument.symbol]);
  const change = (id: number, patch: Partial<Tile>) => {rememberDefaults(id,{...tiles[id],...patch});setTiles(values => values.map(tile => tile.id === id ? { ...tile, ...patch } : tile));};
  return <div ref={root} className="r-chart-workspace"><div className="r-toolbar r-chart-layout"><div role="group" aria-label="图表布局">{[1, 2, 4].map(value => <button key={value} aria-pressed={count === value} onClick={() => setCount(value)}>{value === 1 ? "单图" : value === 2 ? "双图" : "四图"}</button>)}</div><button aria-pressed={paused} onClick={() => setPaused(value => !value)}>{paused ? "恢复行情刷新" : "暂停行情刷新"}</button><select aria-label="行情刷新间隔" value={interval} onChange={event => setInterval(Number(event.target.value))}>{[30, 60, 120].map(value => <option key={value} value={value}>{value} 秒</option>)}</select><span className="r-note">隐藏时暂停 · 各图独立缩放</span></div><div className={`r-chart-tiles r-chart-tiles-${count}`}>{tiles.map((tile, index) => {
    const target = tile.pinned ?? instrument;
    return <section key={tile.id} className="r-chart-tile" hidden={index >= count}><div className="r-toolbar r-chart-tile-heading"><strong>{target.name ?? target.symbol}</strong><select aria-label={`图${index + 1}周期`} value={tile.period} onChange={event => change(tile.id, { period: event.target.value as ViewPeriod })}>{periods.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><button aria-pressed={!!tile.pinned} onClick={() => change(tile.id, { pinned: tile.pinned ? undefined : { ...instrument } })}>{tile.pinned ? "解除固定" : "固定证券"}</button>{(tile.period==="daily"||tile.period==="formula")&&!fixedDate&&<><button disabled={dailyLoading[quoteKey(target)]} onClick={()=>void refreshDaily(target)}>{dailyLoading[quoteKey(target)]?"正在更新日线…":"刷新本图"}</button>{dailyErrors[quoteKey(target)]&&<span role="alert">{dailyErrors[quoteKey(target)]} · 自动重试已暂停</span>}</>}</div>{index < opened.current && <ChartSessionScope session={sessions.current[index]}><ChartTimeScope link={timeLink.current} source={String(tile.id)}>{(tile.period === "daily" ? renderDaily(target,dailyRevisions[quoteKey(target)]??0) : tile.period === "formula" ? <FormulaChart instrument={target} refreshVersion={dailyRevisions[quoteKey(target)]??0}/> : <IntradayChart annotationProjectId={annotationProjectId} instrument={target} period={tile.period} paused={paused} intervalSeconds={interval}/>)}</ChartTimeScope></ChartSessionScope>}</section>;
  })}</div></div>;
}
