import React, { useEffect, useMemo, useState } from "react";
import type { ExperimentDetails, JsonObject, ResearchTable } from "../../../../../packages/contracts/src/research";
import { request, errorText, useResearch } from "./state";
import { useObjectPanel, useWorkspace } from "./workspace";
import { DataTable, Empty, Plot, fieldLabel, tableValue, valueText } from "./ui";
import { analysisSessionRows } from "./analysisCalendar";
import { PagedExperimentTable, type TablePage } from "./PagedTable";

interface AnalysisCalendar {tradingDates:string[]|null;source:string;message:string;}
const calendarLoads=new Map<string,Promise<AnalysisCalendar>>();
function useAnalysisCalendar(detail:ExperimentDetails){
 const [value,setValue]=useState<AnalysisCalendar|null>(null);
 useEffect(()=>{let alive=true;setValue(null);const {projectId,id}=detail.experiment,key=`${projectId}:${id}`;
  let pending=calendarLoads.get(key);if(!pending){pending=request<AnalysisCalendar>('experiments.calendar',{projectId,experimentId:id}).catch(error=>({tradingDates:null,source:'unavailable',message:errorText(error)}));calendarLoads.set(key,pending);}
  void pending.then(result=>{if(alive)setValue(result);});return()=>{alive=false;};
 },[detail.experiment.projectId,detail.experiment.id]);return value;
}
const tableName=(detail:ExperimentDetails,name:string)=>detail.experiment.artifacts.find(a=>a.name.replace(/\.[^.]+$/,"")===name||a.name===name)?.name;
const numeric=(value:unknown):value is number=>typeof value==="number"&&Number.isFinite(value);
const dateOf=(row:JsonObject)=>String(row.date??row.datetime??row.trade_date??"").slice(0,10);
const symbolOf=(row:JsonObject)=>String(row.symbol??row.instrument??row.code??"");

function useAnalysisSetting<T extends string|number>(key:string,fallback:T):[T,(value:T)=>void] {
 const panel=useObjectPanel(),w=useWorkspace();
 const stored=panel?.analysis?.[key];
 const [value,setValue]=useState<T>(()=>typeof stored===typeof fallback?stored as T:fallback);
 useEffect(()=>{setValue(typeof stored===typeof fallback?stored as T:fallback);},[stored,panel?.id]);
 const update=(next:T)=>{setValue(next);if(panel)w.updatePanel(panel.id,{analysis:{...panel.analysis,[key]:next}});};
 return [value,update];
}

/** Fetch only the requested artifact; sampled tables remain explicitly paged. */
function useAnalysisTable(detail:ExperimentDetails,name:string,complete=false,date="",symbol="") {
 const [table,setTable]=useState<ResearchTable|null>(null),[error,setError]=useState("");
 const [total,setTotal]=useState(0);const artifact=tableName(detail,name);
 useEffect(()=>{let alive=true;setTable(null);setError("");setTotal(0);if(!artifact)return;
 void(async()=>{const rows:JsonObject[]=[];let offset=0;let filterDate=date;if(date){const probe=await request<TablePage>("experiments.table",{projectId:detail.experiment.projectId,experimentId:detail.experiment.id,table:artifact,offset:0,limit:1});if(!alive)return;if(!probe.total){setTable({name,columns:probe.columns,rows:[]});return;}if(!probe.columns.some(column=>["date","datetime","trade_date"].includes(column)))filterDate="";}while(alive){const page=await request<TablePage>("experiments.table",{projectId:detail.experiment.projectId,experimentId:detail.experiment.id,table:artifact,offset,limit:500,...(symbol?{symbol}:{}),...(filterDate?{startDate:filterDate,endDate:filterDate}:{})});if(!alive)return;rows.push(...page.rows);offset+=page.rows.length;if(!complete||offset>=page.total){setTable({name,columns:page.columns,rows});setTotal(page.total);return;}if(!page.rows.length)throw new Error("分析表未返回剩余记录。");}})().catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};
 },[detail.experiment.id,detail.experiment.projectId,artifact,complete,date,symbol]);
 return {table,error,total,missing:!artifact};
}
function Missing({name}:{name:string}){return <Empty title={`本实验未记录${name}`}>旧实验不会补造此产物；新任务生成对应记录后可在这里查看。</Empty>;}
function FocusRecord({row,onReference}:{row:JsonObject|null;onReference?:()=>void}) {
 if(!row)return null;
 return <aside className="r-analysis-detail"><h3>当前选择</h3>{row?<><dl>{Object.entries(row).map(([key,value])=><div key={key}><dt>{fieldLabel(key)}</dt><dd>{tableValue(value,key)}</dd></div>)}</dl>{onReference&&<button onClick={onReference}>关联到当前会话</button>}</>:<p className="r-note">点击图中数据点或表格行查看数值。</p>}</aside>;
}
export function useAnalysisReference(detail:ExperimentDetails) {
 const panel=useObjectPanel(),w=useWorkspace();
 const choose=(row:JsonObject,patch:Partial<NonNullable<typeof panel>>={})=>{if(panel)w.updatePanel(panel.id,{date:dateOf(row)||undefined,symbol:symbolOf(row)||undefined,...patch});};
 const reference=async(row:JsonObject,patch:Partial<NonNullable<typeof panel>>={})=>{const id=w.preferences.activeConversationId;if(!id)throw new Error("请先在右栏创建或选择研究会话。");const conversation=await request<{id:string;context:JsonObject[]}>("ai.conversations.get",{conversationId:id});const ref={kind:"experiment",projectId:detail.experiment.projectId,strategyId:detail.experiment.strategyId,experimentId:detail.experiment.id,title:`${detail.experiment.name}${dateOf(row)?` · ${dateOf(row)}`:""}${symbolOf(row)?` · ${symbolOf(row)}`:""}`,view:panel?.view,analysis:panel?.analysis,factorId:panel?.factorId,modelWindowId:panel?.modelWindowId,date:dateOf(row)||undefined,symbol:symbolOf(row)||undefined,...patch};await request("ai.conversations.save",{conversation:{id,context:[...conversation.context,ref]}});await w.savePreferences({aiVisible:true,rightPanel:"ai"});window.dispatchEvent(new CustomEvent("v3-conversation-refresh",{detail:id}));};
 return {choose,reference,panel};
}

export function FactorAnalysis({detail}:{detail:ExperimentDetails}) {
 const s=useResearch();const {choose,reference,panel}=useAnalysisReference(detail);
 const factors=Array.isArray(detail.details.factors)?detail.details.factors.flatMap(v=>v&&typeof v==="object"&&!Array.isArray(v)&&typeof v.factor==="string"?[v.factor]:[]):[];
 const [factor,setFactor]=useState(panel?.factorId??factors[0]??""),[view,setView]=useAnalysisSetting<string>("factorView","groups"),[window,setWindow]=useAnalysisSetting<number>("factorWindow",20),[statistic,setStatistic]=useAnalysisSetting<string>("factorStatistic","mean"),[date,setDate]=useAnalysisSetting<string>("factorDate","");const [focus,setFocus]=useState<JsonObject|null>(null);
 const name=s.factors.find(f=>f.id===factor)?.name??factor;
 const views=[['trend','IC 趋势'],['rank','Rank IC 趋势'],['groups','分组表现'],['turnover','分组换手'],['stability','季度稳定性'],['decay','期限衰减'],['distribution','截面分布'],['coverage','处理覆盖'],['samples','标签清洗损失'],['correlation','平均相关性'],['correlationDaily','逐日截面相关'],['industry','行业诊断']];
 const suffix:Record<string,string>={trend:'IC',rank:'RankIC',groups:'cumulative_quantiles',turnover:'turnover',stability:'stability',decay:'decay',distribution:'samples',samples:'sample_coverage',industry:'industry_diagnostics'};
 const artifact=view==='coverage'?'processing_coverage':view==='correlation'?'factor_correlation':view==='correlationDaily'?'factor_correlation_daily':`${factor}_${suffix[view]}`;
 const loaded=useAnalysisTable(detail,artifact,!['distribution','industry','correlationDaily'].includes(view)||!!date,['distribution','industry','correlationDaily','samples'].includes(view)?date:'');
 useEffect(()=>{if(panel?.factorId&&panel.factorId!==factor)setFactor(panel.factorId);},[panel?.factorId]);
 const calendar=useAnalysisCalendar(detail);
 const originalRows=loaded.table?.rows??[];const rows=(view==='trend'||view==='rank')?analysisSessionRows(originalRows,loaded.table?.columns??[],calendar?.tradingDates??null):originalRows;const axis=loaded.table?.columns.find(k=>/date|datetime|quarter|period|factor_quantile/.test(k))??loaded.table?.columns[0]??'';
 const columns=loaded.table?.columns.filter(k=>k!==axis&&rows.some(r=>numeric(r[k])))??[];
 const [holding,setHolding]=useAnalysisSetting<string>("factorHoldingPeriod","5D");
 const holdingPeriods=[...new Set(columns.map(key=>key.match(/^([^_]+)_Q\d+$/)?.[1]).filter((value):value is string=>!!value))];
 const selectedHolding=holdingPeriods.includes(holding)?holding:holdingPeriods[0];
 const chartColumns=view==='groups'?columns.filter(key=>key.startsWith(`${selectedHolding}_`)):columns;
 const trend=view==='trend'||view==='rank';
 const plotted=useMemo(()=>trend?rows.map((row,index)=>({...row,...Object.fromEntries(columns.map(key=>{const values=rows.slice(Math.max(0,index-window+1),index+1).map(r=>r[key]).filter(numeric);const mean=values.length?values.reduce((a,b)=>a+b,0)/values.length:0;const std=values.length>1?Math.sqrt(values.reduce((sum,value)=>sum+(value-mean)**2,0)/(values.length-1)):0;return [key,values.length!==window?null:statistic==="icir"?(std>0?mean/std:null):mean];}))})):rows,[rows,trend,window,statistic,columns.join('|')]);
 const selectRow=(row:JsonObject)=>{setFocus(row);choose(row,{factorId:factor||undefined});};
 useEffect(()=>{const row=loaded.table?.rows.find(row=>dateOf(row)===panel?.date);if(row)setFocus(row);},[loaded.table,panel?.date]);
 const summary:ResearchTable={name:'批量因子指标',columns:['factor',...new Set(factors.flatMap(f=>Object.keys(detail.experiment.metrics).filter(k=>k.startsWith(`${f}:`)).map(k=>k.slice(f.length+1))))],rows:factors.map(f=>({factor:f,...Object.fromEntries(Object.entries(detail.experiment.metrics).filter(([k])=>k.startsWith(`${f}:`)).map(([k,v])=>[k.slice(f.length+1),v]))}))};
 return <section className={`r-factor-analysis ${view==="groups"&&factor?"r-factor-overview":""}`}><div className="r-analysis-controls"><label>因子 <select value={factor} onChange={e=>{setFactor(e.target.value);setFocus(null);choose({},{factorId:e.target.value||undefined});}}><option value="">全部因子 · 指标汇总</option>{factors.map(f=><option key={f} value={f}>{s.factors.find(x=>x.id===f)?.name??f}</option>)}</select></label><select aria-label="因子分析视图" value={view} onChange={e=>{setView(e.target.value);setFocus(null);}}>{views.map(([id,title])=><option key={id} value={id}>{title}</option>)}</select>{view==="groups"&&holdingPeriods.length>0&&<label>持有期 <select aria-label="分组分析持有期" value={selectedHolding} onChange={e=>setHolding(e.target.value)}>{holdingPeriods.map(value=><option key={value} value={value}>{value.replace("D"," 个交易日")}</option>)}</select></label>}{trend&&factor&&<><select aria-label="滚动窗口" value={window} onChange={e=>setWindow(Number(e.target.value))}><option value={20}>20 个交易日</option><option value={60}>60 个交易日</option></select><select aria-label="滚动统计量" value={statistic} onChange={e=>setStatistic(e.target.value)}><option value="mean">滚动均值</option><option value="icir">滚动 ICIR</option></select></>}{['distribution','industry','correlationDaily','samples'].includes(view)&&<input aria-label="截面日期" type="date" value={date} onChange={e=>{setDate(e.target.value);setFocus(null);}}/>}</div>
 {!factor&&!['coverage','correlation','correlationDaily'].includes(view)?<DataTable table={summary} onRow={row=>{setFactor(String(row.factor));choose({},{factorId:String(row.factor)});}}/>:loaded.missing?<Missing name={views.find(v=>v[0]===view)?.[1]??view}/>:loaded.error?<p role="alert">{loaded.error}</p>:!loaded.table?<p role="status">正在读取分析数据…</p>:<>
 <p className="r-note">{name} · {trend?`${window} 个${calendar?.tradingDates?"交易日":"工作日（缺少交易日历）"}${statistic==="icir"?"均值 / 样本标准差":"滚动均值"}；不足完整有效窗口或标准差为零时留空。IC 与 ICIR 为无量纲统计量。`:view==='correlation'?String(detail.details.correlation??'相关性口径未记录'):view==='decay'?'期限衰减按不同持有期限的平均 IC 展示，与时间稳定性及换手率分别计算。':view==='groups'?'按原实验非重叠持有期组合的累计分组净值。':view==='distribution'?`已读取 ${rows.length} / ${loaded.total} 行${!date?'；选择日期查看当日截面。':''}`:''}</p>
 <div className={`r-analysis-grid${focus?" has-selection":""}`}><div>{view==='coverage'?<FactorCoverage rows={rows} factor={factor} onRow={selectRow}/>:view==='correlationDaily'?<DailyCorrelation rows={rows} date={date} total={loaded.total}/>:view==='industry'||view==='samples'?<FactorDiagnosticTable view={view} rows={rows} total={loaded.total} onRow={selectRow}/>:view==='correlation'?<Plot title="因子相关矩阵" option={{tooltip:{},xAxis:{type:'category',data:columns},yAxis:{type:'category',data:rows.map(r=>String(r.factor??r[axis]))},visualMap:{min:-1,max:1,orient:'horizontal',bottom:0,inRange:{color:['#b97468','#f5f5f7','#267a73']}},grid:{left:95,right:20,bottom:75},series:[{type:'heatmap',data:rows.flatMap((r,y)=>columns.flatMap((k,x)=>numeric(r[k])?[[x,y,r[k]]]:[]))}]}}/>:view==='distribution'?<Plot title="因子值分布（已读取截面）" option={{tooltip:{trigger:'item'},xAxis:{type:'category',data:rows.map(symbolOf)},yAxis:{type:'value'},dataZoom:[{type:'inside'},{type:'slider'}],series:[{type:'bar',data:rows.map(r=>numeric(r.factor)?r.factor:null)}]}} onPoint={i=>rows[i]&&selectRow(rows[i])}/>:columns.length>0&&<Plot title={`${name} · ${views.find(v=>v[0]===view)?.[1]}`} option={{tooltip:{trigger:'axis'},legend:{type:'scroll'},grid:{left:65,right:20,bottom:65},xAxis:{type:'category',data:plotted.map(r=>valueText(r[axis],axis))},yAxis:{type:'value',scale:true},dataZoom:[{type:'inside'},{type:'slider',height:18}],series:chartColumns.map(k=>({name:k,type:['decay','stability','coverage','industry'].includes(view)?'bar':'line',showSymbol:false,connectNulls:false,data:plotted.map(r=>numeric(r[k])?r[k]:null)}))}} onPoint={i=>rows[i]&&selectRow(rows[i])}/>}{view==='groups'&&<div className="r-factor-secondary"><FactorICOverview detail={detail} factor={factor} onRow={selectRow}/><FactorCoverageOverview detail={detail} factor={factor}/></div>}</div><FocusRecord row={focus} onReference={()=>focus&&void s.act(()=>reference(focus,{factorId:factor||undefined}))}/></div>
 <details><summary>完整原始数值与导出</summary><PagedExperimentTable projectId={detail.experiment.projectId} experimentId={detail.experiment.id} table={artifact} onRow={selectRow}/></details></>}
 </section>;
}

function DailyCorrelation({rows,date,total}:{rows:JsonObject[];date:string;total:number}) {
 if(!date)return <p className="r-note">选择截面日期查看相关矩阵。当前预览 {rows.length} / {total} 行，不能把不完整的日期切片当作完整矩阵。</p>;
 const factors=[...new Set(rows.flatMap(row=>[String(row.factor),String(row.otherFactor)]))];
 return <Plot title={`${date} · 因子截面相关`} option={{tooltip:{},grid:{left:120,right:20,bottom:90},xAxis:{type:'category',data:factors},yAxis:{type:'category',data:factors},visualMap:{min:-1,max:1,orient:'horizontal',bottom:0,inRange:{color:['#b97468','#f5f5f7','#267a73']}},series:[{type:'heatmap',data:rows.filter(row=>numeric(row.correlation)).map(row=>[factors.indexOf(String(row.factor)),factors.indexOf(String(row.otherFactor)),row.correlation as number])}]}}/>;
}
function FactorDiagnosticTable({view,rows,total,onRow}:{view:string;rows:JsonObject[];total:number;onRow:(row:JsonObject)=>void}) {
 if(view==='samples')return <><p className="r-note">处理有效数 → 当前期限标签有效数 → 所有请求期限与分组共同清洗后样本数。标签损失与联合清洗损失分开；分母来自本实验处理输入，不与股票池完整率互代。</p><DataTable table={{name:'标签清洗损失',columns:['date','period','denominator','processedAvailable','forwardAvailable','labelLoss','jointCleaningLoss','cleanedAvailable','cleaningBasis'],rows}} onRow={onRow}/></>;
 return <><p className="r-note">行业条件下的截面 IC；样本不足或常量截面保留空值。当前 {rows.length} / {total} 行；选择日期查看当日所有行业与期限。industry_coverage 行单独报告行业资料覆盖。</p><DataTable table={{name:'行业条件诊断',columns:['date','industry','period','expected','samples','pearsonIC','rankIC','status'],rows}} onRow={onRow}/></>;
}

export function FactorComparisonView({detail}:{detail:ExperimentDetails}) {
 const factors=Array.isArray(detail.details.factors)?detail.details.factors.flatMap(value=>value&&typeof value==='object'&&!Array.isArray(value)&&typeof value.factor==='string'?[value.factor]:[]):[];
 const [factor,setFactor]=useState(factors[0]??''),[period,setPeriod]=useState('5D');
 const {table,error,missing}=useAnalysisTable(detail,`${factor}_cumulative_quantiles`,true);
 const periods=[...new Set((table?.columns??[]).flatMap(key=>key.match(/^([^_]+)_Q\d+$/)?.[1]??[]))];
 const selected=periods.includes(period)?period:periods[0];
 const columns=table?.columns.filter(key=>key.startsWith(`${selected}_Q`))??[];
 return <div className="r-factor-comparison-view"><div className="r-toolbar"><label>因子 <select value={factor} onChange={e=>setFactor(e.target.value)}>{factors.map(id=><option key={id}>{id}</option>)}</select></label><label>持有期 <select value={selected??''} onChange={e=>setPeriod(e.target.value)}>{periods.map(value=><option key={value}>{value}</option>)}</select></label></div>{!factor?<p>本实验未记录可分析因子。</p>:<>{error?<p role="alert">{error}</p>:missing?<p>本实验未保存分组净值。</p>:table&&columns.length?<Plot title="分组净值" option={{tooltip:{trigger:'axis'},legend:{type:'scroll'},grid:{left:45,right:12,top:30,bottom:30},xAxis:{type:'category',data:table.rows.map(dateOf)},yAxis:{type:'value',scale:true},series:columns.map(key=>({name:key,type:'line',showSymbol:false,connectNulls:false,data:table.rows.map(row=>numeric(row[key])?row[key]:null)}))}}/>:<p>{table?"本实验没有可绘制的分组净值，原始表仍可在实验页查看。":"正在读取分组数值…"}</p>}<FactorICOverview detail={detail} factor={factor} onRow={()=>{}}/><FactorCoverageOverview detail={detail} factor={factor}/></>}</div>;
}

function FactorICOverview({detail,factor,onRow}:{detail:ExperimentDetails;factor:string;onRow:(row:JsonObject)=>void}) {
 const {table,error,missing}=useAnalysisTable(detail,`${factor}_RankIC`,true);
 const calendar=useAnalysisCalendar(detail);
 if(error)return <p role="alert">{error}</p>;
 if(missing)return <div className="r-factor-unavailable"><h3>该实验无可用 Rank IC</h3><p className="r-note">实验未保存 RankIC 产物。</p></div>;
 if(!table)return <p role="status">正在读取 Rank IC…</p>;
 const keys=table.columns.filter(key=>table.rows.some(row=>numeric(row[key])));
 const rows=analysisSessionRows(table.rows,keys,calendar?.tradingDates??null);
 const series=keys.map(key=>({name:key,type:'line' as const,showSymbol:false,connectNulls:false,data:rows.map((_,i)=>{const values=rows.slice(Math.max(0,i-19),i+1).map(row=>row[key]).filter(numeric);return values.length===20?values.reduce((a,b)=>a+b,0)/20:null;})}));
 if(!series.some(item=>item.data.some(numeric)))return <div className="r-factor-unavailable"><h3>{keys.length?"滚动 Rank IC 暂不可用":"该实验无可用 Rank IC"}</h3><p className="r-note">{keys.length?'原始 Rank IC 有值，但各连续 20 个交易观测窗口均含缺失，无法形成完整滚动均值。':'RankIC 产物中没有有效数值，不能绘制走势。'}可在完整原始数值中核对。</p></div>;
 return <Plot title={`RankIC · 20 ${calendar?.tradingDates?"交易日":"工作日（缺少日历）"}均值`} option={{tooltip:{trigger:'axis'},legend:{type:'scroll'},grid:{left:65,right:20,bottom:50},xAxis:{type:'category',data:rows.map(dateOf)},yAxis:{type:'value',min:-1,max:1},series}} onPoint={i=>rows[i]&&onRow(rows[i])}/>;
}

function FactorCoverageOverview({detail,factor}:{detail:ExperimentDetails;factor:string}) {
 const {table,error,missing}=useAnalysisTable(detail,"processing_coverage",true);
 if(error)return <p role="alert">{error}</p>;
 if(missing)return <p className="r-note">本实验未记录处理覆盖。</p>;
 if(!table)return <p role="status">正在读取覆盖…</p>;
 const rows=table.rows.filter(row=>row.factor===factor);
 return <Plot title="处理覆盖率 · 最终有效数 / 输入总数" option={{tooltip:{trigger:'axis'},grid:{left:50,right:15,bottom:40},xAxis:{type:'category',data:rows.map(dateOf)},yAxis:{type:'value',min:0,max:1},series:[{type:'line',showSymbol:false,connectNulls:false,data:rows.map(row=>numeric(row.total)&&row.total>0&&numeric(row.processedAvailable)?row.processedAvailable/row.total:null)}]}}/>;
}

function FactorCoverage({rows,factor,onRow}:{rows:JsonObject[];factor:string;onRow:(row:JsonObject)=>void}) {
 const selected=rows.filter(row=>!factor||row.factor===factor);
 const stages=[['inputAvailable','输入有效'],['winsorAvailable','去极值后'],['neutralizedAvailable','中性化后'],['processedAvailable','最终处理后']];
 const availableStages=stages.filter(([key])=>selected.some(row=>numeric(row[key])));
 const records=selected.map(row=>({...row,
  inputMissing:numeric(row.total)&&numeric(row.inputAvailable)?row.total-row.inputAvailable:null,
  winsorLoss:numeric(row.inputAvailable)&&numeric(row.winsorAvailable)?row.inputAvailable-row.winsorAvailable:null,
  neutralizationLoss:numeric(row.winsorAvailable)&&numeric(row.neutralizedAvailable)?row.winsorAvailable-row.neutralizedAvailable:null,
  finalLoss:numeric(row.neutralizedAvailable)&&numeric(row.processedAvailable)?row.neutralizedAvailable-row.processedAvailable:null,
 }));
 return <><p className="r-note">分母为预处理前所选股票池中的因子行数（total），不是全市场股票数，也不是标签清洗后的样本数。缺少阶段计数的旧记录保留空值。</p>
 {availableStages.length?<Plot title="各处理阶段有效数 / 预期数" option={{tooltip:{trigger:'axis'},legend:{type:'scroll'},grid:{left:65,right:20,bottom:65},xAxis:{type:'category',data:selected.map(row=>`${dateOf(row)}${!factor?` · ${row.factor}`:''}`)},yAxis:{type:'value',min:0},dataZoom:[{type:'inside'},{type:'slider',height:18}],series:[{name:'预期数',type:'line',showSymbol:false,data:selected.map(row=>numeric(row.total)?row.total:null)},...availableStages.map(([key,label])=>({name:label,type:'line' as const,showSymbol:false,connectNulls:false,data:selected.map(row=>numeric(row[key])?row[key]:null)}))]}} onPoint={i=>records[i]&&onRow(records[i])}/>:<p className="r-note">本实验只有最终覆盖记录，未保存各步损失。</p>}
 <DataTable table={{name:'处理各步损失',columns:['date','factor','total','inputAvailable','inputMissing','winsorLoss','neutralizationLoss','finalLoss','processedAvailable','available','status','denominator'],rows:records}} onRow={onRow}/></>;
}

export function ModelAnalysis({detail}:{detail:ExperimentDetails}) {
 const s=useResearch();const {choose,reference,panel}=useAnalysisReference(detail);const [view,setView]=useAnalysisSetting<string>('modelView','prediction'),[partition,setPartition]=useAnalysisSetting<string>('modelPartition','test'),[date,setDate]=useAnalysisSetting<string>('modelDate',''),[symbol,setSymbol]=useAnalysisSetting<string>('modelSymbol',''),[focus,setFocus]=useState<JsonObject|null>(null);
 const names:Record<string,string>={prediction:`${partition}_predictions`,events:'training_events',loss:'training_evaluation',windows:'windows',importance:'model_importance',explanation:`${partition}_prediction_contributions`,diagnostics:`${partition}_diagnostics`};
 const loaded=useAnalysisTable(detail,names[view],['events','loss','windows','importance','diagnostics'].includes(view),['prediction','explanation'].includes(view)?date:'',['prediction','explanation'].includes(view)?symbol:'');
 const rows=loaded.table?.rows??[],valid=rows.filter(r=>numeric(r.score)&&numeric(r.label));
 const select=(row:JsonObject)=>{setFocus(row);choose(row,{modelWindowId:typeof row.window==='string'?row.window:undefined});};
 useEffect(()=>{const row=loaded.table?.rows.find(row=>(!panel?.symbol||symbolOf(row)===panel.symbol)&&(!panel?.date||dateOf(row)===panel.date)&&(!panel?.modelWindowId||String(row.window??row.windowId)===panel.modelWindowId));if(row&&(panel?.date||panel?.symbol))setFocus(row);},[loaded.table,panel?.date,panel?.symbol,panel?.modelWindowId]);
 const p=detail.experiment.parameters;
 return <section><div className="r-strategy-summary"><h3>本实验时间切分</h3><dl>{['trainStart','trainEnd','validStart','validEnd','testStart','testEnd'].map(k=><div key={k}><dt>{({trainStart:'训练开始',trainEnd:'训练结束',validStart:'验证开始',validEnd:'验证结束',testStart:'测试开始',testEnd:'测试结束'} as Record<string,string>)[k]}</dt><dd>{valueText(p[k]??(detail.details.split&&typeof detail.details.split==='object'&&!Array.isArray(detail.details.split)?detail.details.split[k]:undefined))}</dd></div>)}</dl></div><div className="r-analysis-controls"><select aria-label="模型诊断视图" value={view} onChange={e=>{setView(e.target.value);setFocus(null);}}>{[['prediction','样本外预测与残差'],['diagnostics','逐日 IC 与误差'],['events','训练事件'],['loss','原生训练评估'],['windows','滚动窗口'],['importance','特征重要性'],['explanation','单次预测解释']].map(([id,title])=><option key={id} value={id}>{title}</option>)}</select>{['prediction','explanation','diagnostics'].includes(view)&&<><select value={partition} aria-label="评估分区" onChange={e=>{setPartition(e.target.value);setFocus(null);}}><option value="test">独立测试集</option><option value="valid">验证集</option></select><input type="date" aria-label="预测日期" value={date} disabled={view==="diagnostics"} onChange={e=>{setDate(e.target.value);setFocus(null);}}/>{view!=="diagnostics"&&<input aria-label="预测证券代码" placeholder="证券代码" value={symbol} onChange={e=>{setSymbol(e.target.value);setFocus(null);}}/>}</>}</div>
 {loaded.missing?<Missing name={view==='loss'?'原生训练评估（Ridge 无迭代损失曲线）':names[view]}/>:loaded.error?<p role="alert">{loaded.error}</p>:!loaded.table?<p role="status">正在读取诊断记录…</p>:<>{view==='prediction'?<><p className="r-note">实际预测 {rows.length} / {loaded.total} 行，{valid.length} 行有可评估标签；标签缺失的最新预测仍保留。散点和残差仅对应这些行，不代表完整区间指标。</p><div className="r-analysis-grid"><div><Plot title="预测与实际标签" option={{tooltip:{trigger:'item'},grid:{left:65,right:20,bottom:55},xAxis:{type:'value',name:'实际标签'},yAxis:{type:'value',name:'模型评分',scale:true},series:[{type:'scatter',symbolSize:5,data:valid.map(r=>[Number(r.label),Number(r.score)])}]}} onPoint={i=>valid[i]&&select(valid[i])}/><Plot title="残差（标签 − 预测）" option={{tooltip:{trigger:'item'},xAxis:{type:'value',name:'预测值'},yAxis:{type:'value',name:'残差',scale:true},series:[{type:'scatter',symbolSize:5,data:valid.map(r=>[Number(r.score),Number(r.label)-Number(r.score)])}]}} onPoint={i=>valid[i]&&select(valid[i])}/></div><FocusRecord row={focus} onReference={()=>focus&&void s.act(()=>reference(focus))}/></div></>:<><ModelDiagnosticChart view={view} rows={rows} onRow={select}/>{view==="explanation"&&<PredictionExplanation row={focus??rows[0]??null}/>}<DataTable table={loaded.table} onRow={select}/>{focus&&<FocusRecord row={focus} onReference={()=>void s.act(()=>reference(focus))}/>}</>}
 <details><summary>全部记录 · 筛选与分页</summary><PagedExperimentTable projectId={detail.experiment.projectId} experimentId={detail.experiment.id} table={names[view]} onRow={select}/></details></>}
 </section>;
}

function PredictionExplanation({row}:{row:JsonObject|null}) {
 if(!row)return <Empty title="所选范围没有预测解释记录"/>;
 const entries=Object.entries(row).filter(([key,value])=>!['window','windowId','modelWindowId'].includes(key)&&numeric(value));
 return <><p className="r-note">当前解释：{dateOf(row)} · {symbolOf(row)}。特征贡献与截距合计 {entries.reduce((sum,[,value])=>sum+Number(value),0).toLocaleString('zh-CN',{maximumFractionDigits:6})}；点击下表其它记录切换。</p><Plot title="单次预测特征贡献" option={{tooltip:{trigger:'axis'},grid:{left:150,right:20,bottom:40},xAxis:{type:'value'},yAxis:{type:'category',data:entries.map(([key])=>fieldLabel(key))},series:[{type:'bar',data:entries.map(([,value])=>Number(value))}]}}/></>;
}

function ModelDiagnosticChart({view,rows,onRow}:{view:string;rows:JsonObject[];onRow:(row:JsonObject)=>void}) {
 if(view==='loss') {
  if(!rows.length)return <Empty title="没有逐轮训练评估">Ridge 不产生迭代损失；请查看训练事件、系数及样本外诊断。其它模型以本实验实际保存记录为准。</Empty>;
  const iterations=[...new Set(rows.map(r=>Number(r.iteration)).filter(Number.isFinite))].sort((a,b)=>a-b);
  const groups=[...new Set(rows.map(r=>`${r.partition} / ${r.metric}`))];
  return <Plot title="原生训练与验证评估" option={{tooltip:{trigger:'axis'},legend:{type:'scroll'},xAxis:{type:'category',name:'训练轮数',data:iterations},yAxis:{type:'value',scale:true},series:groups.map(group=>({name:group,type:'line',showSymbol:false,connectNulls:false,data:iterations.map(iteration=>{const value=rows.find(r=>Number(r.iteration)===iteration&&`${r.partition} / ${r.metric}`===group)?.value;return numeric(value)?value:null;})}))}} onPoint={i=>{const row=rows.find(r=>Number(r.iteration)===iterations[i]);if(row)onRow(row);}}/>;
 }
 if(view==='importance') {
  const keys=['coefficient','gain','split'].filter(k=>rows.some(r=>numeric(r[k])));
  return <><p className="r-note">模型系数或树模型原生重要性解释预测；不代表实际收益贡献。系数保留正负方向，gain 与 split 使用各自单位。</p>{keys.map(key=><Plot key={key} title={key==='coefficient'?'标准化模型输入系数':key==='gain'?'特征增益':'特征分裂次数'} option={{tooltip:{trigger:'axis'},grid:{left:140,right:25,bottom:35},xAxis:{type:'value'},yAxis:{type:'category',data:rows.map(r=>String(r.feature))},series:[{type:'bar',data:rows.map(r=>numeric(r[key])?r[key]:null)}]}} onPoint={i=>rows[i]&&onRow(rows[i])}/>)}</>;
 }
 if(view==='diagnostics')return <><p className="r-note">逐日指标取自完整分区诊断产物；滚动均值使用 20 个观测日、至少 5 个有效观测。误差定义为标签减预测。</p>{[['pearsonIC','rankIC','pearsonICRolling20','rankICRolling20'],['mse','mae','bias'],['samples']].map((keys,i)=><Plot key={i} title={['样本外 IC 稳定性','逐日预测误差','有效标签样本数'][i]} option={{tooltip:{trigger:'axis'},legend:{type:'scroll'},grid:{left:65,right:20,bottom:60},xAxis:{type:'category',data:rows.map(dateOf)},yAxis:{type:'value',scale:true},dataZoom:[{type:'inside'},{type:'slider',height:18}],series:keys.map(key=>({name:key,type:i===2?'bar':'line',showSymbol:false,connectNulls:false,data:rows.map(r=>numeric(r[key])?r[key]:null)}))}} onPoint={index=>rows[index]&&onRow(rows[index])}/>)}</>;
 if(view==='explanation')return <p className="r-note">各特征项与模型截距之和对应模型预测值。这是单次预测解释，不是证券盈亏或组合收益归因；可按日期筛选并选择记录关联会话。</p>;
 return null;
}

function PortfolioDiagnosticChart({view,rows,total,date,onRow}:{view:string;rows:JsonObject[];total:number;date:string;onRow:(row:JsonObject)=>void}) {
 const measures:Record<string,[string,string]>={portfolio_factor_exposure:['exposure','组合因子暴露'],factor_returns:['factorReturn','当日风险模型因子收益'],factor_pnl_attribution:['pnl','当日收益归因（元）'],factor_risk_attribution:['varianceContribution','年化方差贡献']};
 const measure=measures[view];
 if(!measure)return null;
 if(!rows.length)return <Empty title="所选范围没有可估计的归因记录">请查看“归因覆盖与口径”确认样本、暴露及历史基准资料；没有记录不能解释为零贡献。</Empty>;
 if(!date)return <p className="r-note">已读取 {rows.length} / {total} 行。选择一个日期查看截面归因图；风险贡献不能跨日相加，收益金额和累计收益率也不能混用。</p>;
 return <><p className="r-note">{view==='factor_pnl_attribution'?'单位为元；费用与未解释对账项按账户记录单列，不再重复扣除滑点或费用。':view==='factor_risk_attribution'?'单位为年化收益方差；负贡献保留。moneyVarianceContribution 是金额方差（元²），不是盈亏金额。':view==='factor_returns'?'使用前一日已知暴露拟合的统计解释，不是因果收益，也不是模型预测贡献。':'使用同日持仓与前一日已知暴露，缺失暴露不填零。'} 数据日期：{date}。</p><Plot title={measure[1]} option={{tooltip:{trigger:'axis'},grid:{left:150,right:25,bottom:45},xAxis:{type:'value'},yAxis:{type:'category',data:rows.map(r=>String(r.factor))},series:[{type:'bar',data:rows.map(r=>numeric(r[measure[0]])?r[measure[0]] as number:null)}]}} onPoint={i=>rows[i]&&onRow(rows[i])}/></>;
}

export function PortfolioAnalysis({detail}:{detail:ExperimentDetails}) {
 const s=useResearch();const {choose,reference,panel}=useAnalysisReference(detail);const [view,setView]=useAnalysisSetting<string>('portfolioView','benchmark'),[date,setDate]=useAnalysisSetting<string>('portfolioDate',''),[focus,setFocus]=useState<JsonObject|null>(null);
 const options=[['benchmark','策略与基准净值'],['excess','超额收益'],['drawdown','回撤'],['monthly','月度收益'],['target_weights','目标组合'],['holdings','实际持仓'],['signals','信号排名'],['unfilled','未成交原因'],['rule_events','规则命中'],['industry','行业暴露'],['contribution','证券收益贡献'],['risk','组合风险贡献'],['portfolio_factor_exposure','风险因子暴露'],['factor_returns','风险模型因子收益'],['factor_pnl_attribution','逐日收益归因'],['factor_pnl_summary','累计收益归因'],['factor_risk_attribution','风险归因'],['attribution_coverage','归因覆盖与口径'],['factor_risk_coverage','风险估计窗口与覆盖'],['relative_industry_attribution','相对行业归因'],['relative_factor_exposure','相对因子暴露'],['relative_factor_risk','相对风险贡献'],['relative_risk_coverage','相对风险覆盖'],['pnl_reconciliation','账户收益对账'],['rule_targets','规则目标'],['account_events','账户与公司行动事件']];
 const aggregate=['benchmark','excess','drawdown','monthly'].includes(view);const loaded=useAnalysisTable(detail,view,aggregate||!!date,aggregate||view==='factor_pnl_summary'?"":date);
 const rows=loaded.table?.rows??[],axis=loaded.table?.columns.find(k=>/date|datetime|month/.test(k))??'';const columns=loaded.table?.columns.filter(k=>k!==axis&&rows.some(r=>numeric(r[k])))??[];
 const select=(row:JsonObject)=>{setFocus(row);choose(row,{factorId:typeof row.factor==="string"?row.factor:undefined});};
 useEffect(()=>{const row=loaded.table?.rows.find(row=>(!panel?.symbol||symbolOf(row)===panel.symbol)&&(!panel?.date||dateOf(row)===panel.date)&&(!panel?.factorId||row.factor===panel.factorId));if(row&&(panel?.date||panel?.symbol||panel?.factorId))setFocus(row);},[loaded.table,panel?.date,panel?.symbol,panel?.factorId]);
 return <section><div className="r-analysis-controls"><label>分析视图 <select value={view} onChange={e=>{setView(e.target.value);setFocus(null);}}>{options.map(([id,title])=><option key={id} value={id}>{title}</option>)}</select></label>{!aggregate&&view!=='factor_pnl_summary'&&<input aria-label="组合分析日期" type="date" value={date} onChange={e=>{setDate(e.target.value);setFocus(null);}}/>}</div>{loaded.missing?<Missing name={options.find(v=>v[0]===view)?.[1]??view}/>:loaded.error?<p role="alert">{loaded.error}</p>:!loaded.table?<p role="status">正在读取分析产物…</p>:<>{aggregate?<div className="r-analysis-grid"><Plot title={options.find(v=>v[0]===view)?.[1]??view} option={{tooltip:{trigger:'axis'},legend:{type:'scroll'},grid:{left:65,right:20,bottom:60},xAxis:{type:'category',data:rows.map(r=>valueText(r[axis],axis))},yAxis:{type:'value',scale:true},dataZoom:[{type:'inside'},{type:'slider',height:18}],series:columns.map(k=>({name:fieldLabel(k,view),type:view==='monthly'?'bar':'line',showSymbol:false,data:rows.map(r=>numeric(r[k])?r[k]:null)}))}} onPoint={i=>rows[i]&&select(rows[i])}/><FocusRecord row={focus} onReference={()=>focus&&void s.act(()=>reference(focus))}/></div>:<PortfolioDiagnosticChart view={view} rows={rows} total={loaded.total} date={date} onRow={select}/ >}{view==='risk'&&<p className="r-note">目标与实际风险贡献是组合方差贡献占比，可为负值；不是金额。完整因子风险归因在单独视图中展示。</p>}{view==='factor_pnl_summary'&&<p className="r-note">累计收益贡献按各项逐日损益求和，再除以初始账户资产；以百分比显示，不是日收益率直接相加。</p>}{view.startsWith("relative_")&&!rows.length&&<p className="r-note">本实验没有相对归因记录。请查看“相对风险覆盖”中的历史基准成分权重覆盖原因。</p>}<p className="r-note">下方为全区间原始表与导出，不受上方日期筛选影响。</p><PagedExperimentTable key={view} projectId={detail.experiment.projectId} experimentId={detail.experiment.id} table={view} onRow={select}/>{!aggregate&&focus&&<FocusRecord row={focus} onReference={()=>void s.act(()=>reference(focus))}/>}</>}</section>;
}
