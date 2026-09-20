import React, { useEffect, useRef, useState } from "react";
import type { QuoteInstrument } from "../../../../../packages/contracts/src/research";
import { errorText, request, useResearch } from "./state";
import { CodeEditor } from "./ui";
import { hqSymbol } from "./HQIntraday";
import { useChartSession } from "./ChartSession";
import { useTimeLink } from "./ChartTimeLink";
import { useWorkspace } from "./workspace";

type Basis = "raw" | "adjusted";
type Placement = "main" | "sub";
interface Formula { name: string; script: string; parameters: { name: string; value: number }[]; output?: string; priceBasis?: Basis; }
interface SavedFormula extends Formula { id: string; revision: number; sourceId?:string;sourceRevision?:number;sourceProjectId?:string|null; }
interface Template { id: string; revision: number; name: string; formula: Formula; placement: Placement; priceBasis: Basis; }
interface Evaluation { engine: string; priceBasis: Basis; assessment: { researchAllowed: boolean; reasons: string[]; volumeUnit: string; amountUnit: string }; series: { symbol: string; dates: string[]; outputs: { name: string; values: (number|null)[] }[]; drawings: unknown[] }[]; factor?: { id: string }; }
interface Bar { date: string; open: number; high: number; low: number; close: number; volume: number; amount?: number; turnover?: number; rawOpen?: number; rawHigh?: number; rawLow?: number; rawClose?: number; }
interface HQData { Date:number; [key:string]:unknown; }
interface HQChart { JSChartContainer?:{ChartOperator:(value:object)=>void;ManualUpdateKData:(value:{Data:HQData[];DataOffset:number})=>void;ChartPaint:{Data:{Data:HQData[];DataOffset:number}}[];SourceData?:{Data:HQData[]}};SetOption: (value: object) => void; OnSize: () => void; StopAutoUpdate: () => void; ChartDestroy: () => void; }
const fresh = (): Formula => ({ name: "移动平均", script: "MA线:MA(CLOSE,N);", parameters: [{ name: "N", value: 5 }] });
const plain = (value: Formula): Formula => ({ name: value.name, script: value.script, parameters: value.parameters.map(item => ({ name: item.name, value: item.value })), ...(value.output ? { output: value.output } : {}) });

function NativeFormulaChart({ formula, instrument, basis, placement, refreshVersion }: { refreshVersion:number; formula: Formula; instrument: QuoteInstrument; basis: Basis; placement: Placement }) {
 const scope=useTimeLink(),linked=useRef(scope);linked.current=scope;
 const refresh=useRef<(()=>void)|null>(null),latestRevision=useRef(refreshVersion);latestRevision.current=refreshVersion;
 const node = useRef<HTMLDivElement>(null), [error, setError] = useState(""), [status, setStatus] = useState("");
 useEffect(() => {
  let active = true, chart: HQChart | undefined, resize: ResizeObserver | undefined,unlink:(()=>void)|undefined,applying=false;
  setError(""); setStatus("正在读取公式图的真实日线…");
  const readValues=async()=>{
   const bars: Bar[] = []; let beforeDate: string | undefined;
   while (active) {
    const page = await request<Bar[]>("data.bars", { instrument, symbol: instrument.symbol, period: "day", limit: 500, beforeDate });
    bars.push(...page); if (page.length < 500) break;
    const earliest = page.reduce((date, bar) => date < bar.date ? date : bar.date, page[0].date).slice(0,10);
    if (beforeDate && earliest >= beforeDate) throw Error("日线分页未前进，请重新读取行情。"); beforeDate = earliest;
   }
   if (!active) throw Error("图表已切换");
   if (!bars.length) throw Error("没有可用于公式图的真实日线，请先更新当前证券行情。");
   bars.sort((a,b) => a.date.localeCompare(b.date));
   const values = bars.map(bar => {
    const prices = basis === "raw" ? [bar.rawOpen,bar.rawHigh,bar.rawLow,bar.rawClose] : [bar.open,bar.high,bar.low,bar.close];
    if (prices.some(value => typeof value !== "number" || !Number.isFinite(value))) throw Error("所选价格口径缺少完整行情，不能应用公式。");
    return { bar, prices: prices as number[] };
   });
   return values;
  };
  const initialRevision=latestRevision.current;
  void (async () => {
   let values=await readValues();let bars=values.map(value=>value.bar);
   const module = await import("hqchart"); if (!active || !node.current) return;
   const api=(module as unknown as { Chart: { HistoryData:new()=>HQData; JS_ID:{JSCHART_EVENT_ID:{ON_MOUSE_MOVE:number};JSCHART_OPERATOR_ID:{OP_CORSSCURSOR_GOTO:number}};JSChart: { Init: (node: HTMLElement) => HQChart } } }).Chart;
   chart = api.JSChart.Init(node.current);
   const native = { Name: formula.name, Script: formula.script, Args: formula.parameters.map(p => ({ Name: p.name, Value: p.value })) };
   const symbol = hqSymbol(instrument.symbol);
   chart.SetOption({ Type: "历史K线图", Symbol: symbol, IsAutoUpdate: false, IsShowRightMenu: false, EventCallback:[{event:api.JS_ID.JSCHART_EVENT_ID.ON_MOUSE_MOVE,callback:(_event:unknown,_data:unknown,sender:{GetCurrentKLineData?:()=>{Date:number}})=>{if(applying)return;const bar=sender?.GetCurrentKLineData?.();if(!bar)return;const date=String(bar.Date);linked.current?.link.publish(Date.parse(`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}T00:00:00+08:00`),linked.current.source);}}], Windows: placement === "main" ? [native] : [{},native],
    KLine: { Right: 0, Period: 0, PageSize: 60, IsShowTooltip: true }, Border: { Left: 55, Right: 55, Top: 20, Bottom: 25 },
    NetworkFilter: (call: { Name: string; PreventDefault: boolean }, callback: (data: object) => void) => {
     call.PreventDefault = true; if (!active) return;
     // HQ requests this optional tooltip dataset even for a pure price formula.
     // No response leaves turnover rate unavailable; formula evaluation rejects unsupported inputs.
     if (call.Name === "KLineChartContainer::RequestFlowCapitalData") return;
     if (call.Name !== "KLineChartContainer::RequestHistoryData") { setError(`公式需要尚未接入的数据：${call.Name}`); return; }
     callback({ code: 0, symbol, name: instrument.name ?? instrument.symbol, data: values.map(({bar,prices},index) => [Number(bar.date.slice(0,10).replaceAll("-","")), index ? values[index-1].prices[3] : null, ...prices, bar.volume, bar.amount ?? bar.turnover ?? null]) });
    }
   });
   unlink=linked.current?.link.subscribe((timestamp,source)=>{if(source===linked.current?.source)return;const date=new Date(timestamp+8*3600000).toISOString().slice(0,10);if(!bars.some(bar=>bar.date.startsWith(date)))return;applying=true;try{chart?.JSChartContainer?.ChartOperator({ID:api.JS_ID.JSCHART_OPERATOR_ID.OP_CORSSCURSOR_GOTO,Date:Number(date.replaceAll('-',''))});}finally{applying=false;}});
   resize = new ResizeObserver(() => chart?.OnSize()); resize.observe(node.current); chart.OnSize();
   setStatus(`${instrument.name ?? instrument.symbol} · ${bars.length} 根日线 · ${basis === "raw" ? "不复权" : "前复权"} · 原生通达信公式`);
   let refreshing=false,pending=false;
   refresh.current=()=>{
    if(refreshing){pending=true;return;}refreshing=true;
    void readValues().then(next=>{
     if(!active)return;const container=chart?.JSChartContainer;if(!container)throw Error("公式图尚未就绪");
     const current=container.ChartPaint[0]?.Data;const offset=Math.max(0,current?.DataOffset??0),anchor=current?.Data[offset]?.Date;
     const data=next.map(({bar,prices},index)=>Object.assign(new api.HistoryData(),{Date:Number(bar.date.slice(0,10).replaceAll('-','')),YClose:index?next[index-1].prices[3]:null,Open:prices[0],High:prices[1],Low:prices[2],Close:prices[3],Vol:bar.volume,Amount:bar.amount??bar.turnover??null}));
     const anchorIndex=anchor==null?-1:data.findIndex(bar=>bar.Date>=anchor);
     // Native manual data update reruns each formula, keeping zoom and the first visible date.
     container.ManualUpdateKData({Data:data,DataOffset:anchorIndex>=0?anchorIndex:Math.min(offset,Math.max(0,data.length-1))});
     if(container.SourceData)container.SourceData.Data=data;
     values=next;bars=next.map(value=>value.bar);setError("");
     setStatus(`${instrument.name??instrument.symbol} · ${bars.length} 根日线 · ${basis==='raw'?'不复权':'前复权'} · 原生通达信公式 · 行情已更新`);
    }).catch(error=>{if(active)setError(`刷新未完成，保留已有公式图：${errorText(error)}`);}).finally(()=>{refreshing=false;if(active&&pending){pending=false;refresh.current?.();}});
   };
   if(initialRevision!==latestRevision.current)refresh.current();
  })().catch(error => { if (active) setError(errorText(error)); });
  return () => { active = false; refresh.current=null;unlink?.();resize?.disconnect(); chart?.StopAutoUpdate(); chart?.ChartDestroy(); node.current?.replaceChildren(); };
 }, [instrument.kind, instrument.symbol, basis, placement, JSON.stringify(formula)]);
 useEffect(()=>{refresh.current?.();},[refreshVersion]);
 return <><p className="r-note">{status}</p>{error && <p role="alert">{error}</p>}<div ref={node} className="r-intraday-canvas" aria-label={`${instrument.symbol} 原生公式日线图`}/></>;
}

export function FormulaChart({ instrument, refreshVersion=0 }: { instrument: QuoteInstrument; refreshVersion?:number }) {
 const session=useChartSession(),workspace=useWorkspace();
 const s = useResearch(), [scope, setScope] = useState(""), [formula, setFormula] = useState<Formula>(()=>session?.formula?.draft??fresh()), [saved, setSaved] = useState<SavedFormula | null>(null);
 const [sourceVersion,setSourceVersion]=useState<SavedFormula|null>(null),[sourceError,setSourceError]=useState("");
 const [library, setLibrary] = useState<SavedFormula[]>([]), [templates, setTemplates] = useState<Template[]>([]), [version, setVersion] = useState(0);
 const [basis, setBasis] = useState<Basis>(session?.formula?.basis??"raw"), [placement, setPlacement] = useState<Placement>(session?.formula?.placement??"main"), [applied, setApplied] = useState<{formula: Formula; basis: Basis; placement: Placement} | null>(session?.formula?.applied??null);
 const [result, setResult] = useState<Evaluation | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
 const [output, setOutput] = useState(""), [factorId, setFactorId] = useState("");
 const [editing, setEditing] = useState(true);
 const token = useRef(0);
 useEffect(()=>{if(session){session.formula={draft:plain(formula),basis,placement,...(applied?{applied}:{})};session.onChange?.();}},[JSON.stringify(formula),basis,placement,applied]);
 useEffect(() => { let active=true;void Promise.all([request<SavedFormula[]>("formula.library.list",{projectId:scope||undefined}),request<Template[]>("formula.templates.list",{projectId:scope||undefined})]).then(([formulas,templates])=>{if(active){setLibrary(formulas);setTemplates(templates);}}).catch(e=>{if(active)setError(errorText(e));});return()=>{active=false;}; },[scope,version]);
 useEffect(() => { token.current++;setResult(null);setError("");setBusy(false); }, [instrument.kind,instrument.symbol,basis,JSON.stringify(formula),scope]);
 const work = async (action: () => Promise<void>) => { if(busy)return;setBusy(true);setError("");setNotice("");try{await action();}catch(e){setError(errorText(e));}finally{setBusy(false);} };
 const evaluate = async () => { const serial=token.current;const value=await request<Evaluation>("formula.evaluate",{formula:plain(formula),instrument,period:"daily",priceBasis:basis,purpose:"chart"});if(serial!==token.current)return null;setResult(value);setOutput(value.series[0]?.outputs[0]?.name??"");return value; };
 const choose = (record: SavedFormula) => {setSaved(record);setFormula(plain(record));setBasis(record.priceBasis??"raw");setEditing(true);};
 useEffect(()=>{let active=true;setSourceVersion(null);setSourceError("");if(saved?.sourceId&&saved.sourceProjectId!==undefined)void request<SavedFormula>("formula.library.get",{id:saved.sourceId,projectId:saved.sourceProjectId??undefined}).then(value=>{if(active)setSourceVersion(value);}).catch(error=>{if(active)setSourceError(errorText(error));});return()=>{active=false;};},[saved?.id,saved?.sourceRevision,scope,version]);
 const valid = formula.name.trim() && formula.script.trim() && formula.parameters.every(p=>p.name.trim()&&Number.isFinite(p.value));
 return <div className="r-formula-chart"><div className="r-toolbar"><button aria-expanded={editing} onClick={()=>setEditing(value=>!value)}>{editing?"收起公式编辑":"编辑通达信公式"}</button><span>{applied?.formula.name??"尚未应用公式"}</span></div>{editing&&<div className="r-formula-editor">
  <div className="r-toolbar"><select aria-label="公式库范围" value={scope} disabled={busy} onChange={e=>{setScope(e.target.value);setSaved(null);}}><option value="">个人公式库</option>{s.project&&<option value={s.project.id}>当前项目公式库</option>}</select><select aria-label="已保存公式" value={saved?.id??""} disabled={busy} onChange={e=>{const record=library.find(item=>item.id===e.target.value);if(record)choose(record);}}><option value="">选择公式…</option>{library.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select><button disabled={busy} onClick={()=>{setSaved(null);setFormula(fresh());}}>新公式</button><button disabled={busy} onClick={()=>setVersion(v=>v+1)}>刷新公式库</button><button onClick={()=>void work(async()=>{await workspace.savePreferences({aiVisible:true,rightPanel:"ai"});window.dispatchEvent(new CustomEvent("v3-ai-draft-append",{detail:{projectId:s.project?.id,text:`请辅助编写以下通达信公式，先讨论修改，不运行研究或启用策略。\n证券：${instrument.name??instrument.symbol}（${instrument.symbol}）\n公式库：${scope?'当前项目':'个人'}；价格口径：${basis==='raw'?'不复权':'前复权'}\n名称：${formula.name}\n参数：${JSON.stringify(formula.parameters)}\n公式：\n${formula.script}`}}));setNotice("已追加到研究助手输入草稿，保留原输入；请编辑后自行发送。");})}>请AI辅助编写</button></div>
  {sourceError&&<p className="r-note">来源版本暂不可用：{sourceError}；当前副本保持不变。</p>}{saved?.sourceId&&saved.sourceProjectId===undefined&&<p className="r-note">此旧副本未记录来源库，保留当前内容，无法自动检查新版。</p>}
  {saved&&sourceVersion&&sourceVersion.revision>(saved.sourceRevision??0)&&<details className="r-formula-update"><summary>来源有新版（{saved.sourceRevision??"未知"} → {sourceVersion.revision}），当前副本尚未改变</summary><strong>当前副本</strong><pre>{saved.script}{'\n'}{JSON.stringify(saved.parameters)}</pre><strong>来源新版</strong><pre>{sourceVersion.script}{'\n'}{JSON.stringify(sourceVersion.parameters)}</pre><button disabled={busy} onClick={()=>void work(async()=>{const next=await request<SavedFormula>("formula.library.save",{projectId:scope||undefined,expectedRevision:saved.revision,record:{...saved,...plain(sourceVersion),priceBasis:sourceVersion.priceBasis??"raw",sourceRevision:sourceVersion.revision}});choose(next);setVersion(v=>v+1);setNotice("已采用来源新版到此副本；图上公式需另行点击应用。");})}>采用来源新版到此副本</button></details>}
  <label>公式名称<input aria-label="公式名称" value={formula.name} disabled={busy} onChange={e=>setFormula({...formula,name:e.target.value})}/></label>
  <CodeEditor label="通达信公式" language="plaintext" value={formula.script} onChange={script=>{if(!busy)setFormula({...formula,script});}}/>
  {formula.parameters.map((p,index)=><div className="r-toolbar" key={index}><input aria-label={`参数${index+1}名称`} value={p.name} disabled={busy} onChange={e=>setFormula({...formula,parameters:formula.parameters.map((item,i)=>i===index?{...item,name:e.target.value}:item)})}/><input aria-label={`参数${index+1}数值`} type="number" value={p.value} disabled={busy} onChange={e=>setFormula({...formula,parameters:formula.parameters.map((item,i)=>i===index?{...item,value:Number(e.target.value)}:item)})}/><button disabled={busy} onClick={()=>setFormula({...formula,parameters:formula.parameters.filter((_,i)=>i!==index)})}>移除参数</button></div>)}
  <div className="r-toolbar"><button disabled={busy} onClick={()=>setFormula({...formula,parameters:[...formula.parameters,{name:"",value:1}]})}>添加参数</button><select aria-label="公式价格口径" value={basis} disabled={busy} onChange={e=>setBasis(e.target.value as Basis)}><option value="raw">不复权</option>{instrument.kind==='stock'&&<option value="adjusted">前复权</option>}</select><select aria-label="公式位置" value={placement} disabled={busy} onChange={e=>setPlacement(e.target.value as Placement)}><option value="main">主图</option><option value="sub">副图</option></select></div>
  <div className="r-toolbar"><button disabled={busy||!valid} onClick={()=>void work(async()=>{await evaluate();})}>预览数值</button><button disabled={busy||!valid} onClick={()=>void work(async()=>{if(await evaluate()){setApplied({formula:plain(formula),basis,placement});setEditing(false);}})}>应用到{placement==='main'?'主图':'副图'}</button><button disabled={busy||!valid} onClick={()=>void work(async()=>{const record=await request<SavedFormula>("formula.library.save",{projectId:scope||undefined,record:{...(saved??{}),...plain(formula),output:formula.output,priceBasis:basis},expectedRevision:saved?.revision});setSaved(record);setVersion(v=>v+1);setNotice("公式已保存；未启用任何策略。");})}>保存公式</button>{saved&&<button disabled={busy||(!scope&&!s.project)} onClick={()=>void work(async()=>{const target=scope?undefined:s.project!.id;await request("formula.library.copy",{fromProjectId:scope||undefined,projectId:target,id:saved.id});setScope(target??"");setSaved(null);setVersion(v=>v+1);setNotice("已创建独立副本，后续编辑互不影响。");})}>复制到{scope?'个人库':'项目'}</button>}</div>
  <div className="r-toolbar"><select aria-label="图表模板" defaultValue="" disabled={busy} onChange={e=>{const item=templates.find(t=>t.id===e.target.value);if(item){setSaved(null);setFormula(plain(item.formula));setBasis(item.priceBasis??"raw");setPlacement(item.placement??"main");}e.target.value="";}}><option value="">载入公式图模板…</option>{templates.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select><button disabled={busy||!valid} onClick={()=>void work(async()=>{await request("formula.templates.save",{projectId:scope||undefined,record:{name:`${formula.name} · ${placement==='main'?'主图':'副图'}`,formula:plain(formula),priceBasis:basis,placement}});setVersion(v=>v+1);setNotice("模板已保存，包含公式、参数与位置，不包含证券或画线。");})}>保存为图表模板</button></div>
  {result&&<><p className="r-note">{result.engine} · 量：{result.assessment.volumeUnit} · 额：{result.assessment.amountUnit} · {result.assessment.researchAllowed?'可用于历史研究':'仅用于看盘，不可作为历史信号'}</p>{result.assessment.reasons.map(reason=><p className="r-note" key={reason}>{reason}</p>)}<div className="r-table-scroll"><table><thead><tr><th>日期</th>{result.series[0]?.outputs.map(o=><th key={o.name}>{o.name}</th>)}</tr></thead><tbody>{result.series[0]?.dates.slice(-5).map((date,index,array)=>{const offset=result.series[0].dates.length-array.length+index;return <tr key={date}><td>{date}</td>{result.series[0].outputs.map(o=><td key={o.name}>{o.values[offset]?.toLocaleString('zh-CN',{maximumFractionDigits:4})??'—'}</td>)}</tr>;})}</tbody></table></div>{s.project&&<div className="r-toolbar"><select aria-label="研究因子输出" value={output} disabled={busy} onChange={e=>setOutput(e.target.value)}>{result.series[0]?.outputs.map(o=><option key={o.name}>{o.name}</option>)}</select><input aria-label="研究因子ID" placeholder="因子ID，字母开头" value={factorId} disabled={busy} onChange={e=>setFactorId(e.target.value)}/><button disabled={busy||!result.assessment.researchAllowed||!output||!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(factorId)} onClick={()=>void work(async()=>{await request("formula.evaluate",{projectId:s.project!.id,formula:plain(formula),purpose:"research",period:"daily",priceBasis:basis,saveFactor:true,factorId,output});await s.refreshProjects();setNotice("已计算项目股票池并保存为可编辑因子，未启用策略。");})}>计算项目股票池并保存因子</button></div>}</>}
 </div>}{busy&&<p role="status">正在读取真实数据并处理公式…</p>}{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{applied?<NativeFormulaChart instrument={instrument} refreshVersion={refreshVersion} {...applied}/>:<p className="r-note">编辑公式后预览数值，或应用到原生日线主图 / 副图。</p>}</div>;
}
