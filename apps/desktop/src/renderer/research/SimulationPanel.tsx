import React, { useEffect, useRef, useState } from "react";
import type { Experiment, ExperimentDetails, JobEvent, JsonObject, ResearchTable, SimulationAccount, WorkspacePanel } from "../../../../../packages/contracts/src/research";
import { object } from "./configuration";
import { errorText, request, useResearch } from "./state";
import { useWorkspace, flushDrafts } from "./workspace";
import { DataTable, Empty, Field, Heading, Plot, tableLabel, valueText } from "./ui";

type Page = ResearchTable & { total:number; offset:number; limit:number };
const views = [["overview","账户概况"],["holdings","持仓记录"],["pending","待执行决策"],["trades","成交"],["unfilled","未成交"],["rule_events","命中规则"],["signals","信号"],["target_weights","目标组合"],["account_events","账户事件"],["model_events","模型事件"]];
const money = (value:number) => value.toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2});

export function SimulationPanel({panel}:{panel:WorkspacePanel}) {
  const s=useResearch(),w=useWorkspace();
  const [accounts,setAccounts]=useState<SimulationAccount[]>([]),[account,setAccount]=useState<SimulationAccount|null>(null);
  const [name,setName]=useState(""),[startDate,setStartDate]=useState(s.project?.startDate??""),[capital,setCapital]=useState("1000000");
  const [strategyId,setStrategyId]=useState(panel.strategyId??"");
  const [endDate,setEndDate]=useState(new Date().toLocaleDateString("en-CA"));
  const [creating,setCreating]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const [view,setView]=useState(panel.view??"overview"),[revision,setRevision]=useState(0),[loading,setLoading]=useState(true);
  const [activeJob,setActiveJob]=useState<JobEvent|null>(null);
  const projectId=panel.projectId;
  const loadSequence=useRef(0);
  const strategies=w.strategies.filter(value=>value.projectId===projectId);
  const refresh=async(id=panel.accountId)=>{
    const sequence=++loadSequence.current;
    const values=await request<SimulationAccount[]>("simulation.accounts.list",{projectId});
    const selected=id?await request<SimulationAccount>("simulation.accounts.get",{projectId,accountId:id}):values[0]??null;
    if(sequence!==loadSequence.current)return selected;
    setAccounts(values);setActiveJob(null);setAccount(selected);setName(selected?.name??"");setRevision(v=>v+1);
    if(selected){const jobs=await request<JobEvent[]>("jobs.list",{projectId,statuses:["queued","running"],limit:1000});if(sequence===loadSequence.current)setActiveJob(jobs.find(job=>job.kind==="simulation.advance"&&job.spec.parameters.accountId===selected.id)??null);}
    return selected;
  };
  useEffect(()=>{let alive=true;setLoading(true);setError("");void refresh().catch(e=>{if(alive)setError(errorText(e));}).finally(()=>{if(alive)setLoading(false);});return()=>{alive=false;loadSequence.current++;};},[projectId,panel.accountId]);
  useEffect(()=>window.v3Research?.onEvent(event=>{
    if(event.kind!=="simulation.advance"||event.projectId!==projectId||event.spec.parameters.accountId!==account?.id)return;
    if(["queued","running"].includes(event.status))setActiveJob(event);
    else {setActiveJob(null);void refresh(account.id).catch(e=>setError(errorText(e)));}
  }),[projectId,account?.id]);
  const run=(work:()=>Promise<void>)=>{setBusy(true);setError("");void work().catch(e=>setError(errorText(e))).finally(()=>setBusy(false));};
  const choose=(id:string)=>{setCreating(false);w.updatePanel(panel.id,{accountId:id,view:"overview"});setView("overview");};
  const blocked=busy||!!activeJob;
  return <div className="r-page"><Heading title="日线模拟账户" description="独立虚拟资金，按交易日保存信号、成交与账户状态。"/>
    {error&&<p role="alert" className="r-local-error">{error}</p>}
    <div className="r-toolbar"><select aria-label="选择模拟账户" disabled={busy} value={account?.id??""} onChange={e=>choose(e.target.value)}><option value="" disabled>选择账户</option>{accounts.map(value=><option key={value.id} value={value.id}>{value.name} · {value.asOfDate??"尚未推进"}</option>)}</select><button disabled={blocked} onClick={()=>{setCreating(true);setName("");}}>新建账户</button><button disabled={busy} onClick={()=>run(async()=>{await refresh(account?.id);})}>刷新</button></div>
    {(creating||(!loading&&!account))&&<section><h2>创建单策略账户</h2><div className="r-form-grid"><Field label="账户名称"><input value={name} onChange={e=>setName(e.target.value)}/></Field><Field label="使用策略"><select value={strategyId} onChange={e=>setStrategyId(e.target.value)}><option value="">选择策略</option>{strategies.map(strategy=><option key={strategy.id} value={strategy.id}>{strategy.name}</option>)}</select></Field><Field label="起始信号日"><input type="date" value={startDate} onChange={e=>setStartDate(e.target.value)}/></Field><Field label="初始虚拟资金（元）"><input type="number" min="0.01" step="1000" value={capital} onChange={e=>setCapital(e.target.value)}/></Field></div><p className="r-note">首个交易日收盘生成信号，下一交易日开始模拟成交。策略修改用于后续信号，已完成日期保留原记录。</p><div className="r-toolbar"><button className="r-primary" disabled={blocked||!name.trim()||!strategyId||!startDate||!Number.isFinite(Number(capital))||Number(capital)<=0} onClick={()=>run(async()=>{await flushDrafts();const created=await request<SimulationAccount>("simulation.accounts.create",{projectId,strategyId,name:name.trim(),startDate,capital:Number(capital)});await refresh(created.id);choose(created.id);s.setNotice("模拟账户已创建，尚未推进日期");})}>创建账户</button>{account&&<button onClick={()=>{setCreating(false);setName(account.name);}}>返回账户</button>}</div></section>}
    {loading?<p role="status">正在读取账户…</p>:account&&!creating&&<>
      <div className="r-toolbar"><input aria-label="模拟账户名称" value={name} onChange={e=>setName(e.target.value)}/><button disabled={blocked||!name.trim()||name===account.name} onClick={()=>run(async()=>{await request("simulation.accounts.save",{projectId,accountId:account.id,name:name.trim()});await refresh(account.id);})}>保存名称</button><span>{strategies.find(value=>value.id===account.strategyId)?.name??account.strategyId}</span></div>
      <div className="r-metrics">{[["账户资产（元）",money(account.nav)],["可用现金（元）",money(account.cash)],["累计净值",(account.nav/account.capital).toFixed(4)],["最后完成日",account.asOfDate??"尚未开始"]].map(([label,value])=><div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
      <p className="r-note">初始资金 {money(account.capital)} 元 · 起始信号日 {account.startDate} · {account.paused?"已暂停":account.status==="blocked"?"推进受阻":"可推进"}</p>
      {account.unresolved&&<p role="alert">{account.unresolved.date??"未完成日期"}：{account.unresolved.message}。最后完成日以前的账户记录已保留。</p>}
      <div className="r-toolbar"><label>推进截至 <input aria-label="模拟推进截至日期" type="date" value={endDate} onChange={e=>setEndDate(e.target.value)}/></label><button className="r-primary" disabled={blocked||account.paused||!endDate||endDate<(account.asOfDate??account.startDate)} onClick={()=>run(async()=>{await flushDrafts();const job=await request<JobEvent>("jobs.submit",{spec:{kind:"simulation.advance",projectId,parameters:{accountId:account.id,endDate}}});setActiveJob(job);s.setNotice("模拟推进已进入任务队列");})}>{account.asOfDate?"继续推进 / 补算":"开始推进"}</button><button disabled={blocked} onClick={()=>run(async()=>{await request("simulation.accounts.save",{projectId,accountId:account.id,paused:!account.paused});await refresh(account.id);})}>{account.paused?"恢复账户":"暂停账户"}</button>{activeJob&&<button disabled={busy} onClick={()=>run(async()=>{await request("jobs.cancel",{jobId:activeJob.id});})}>停止推进</button>}</div>
      {activeJob&&<p role="status">{activeJob.status==="queued"?"排队中":"推进中"} · {activeJob.message}</p>}
      <p className="r-note">使用本地已覆盖行情逐日执行；关闭期间的日期会标为历史补算。需要新行情时先在数据中心更新。</p>
      <SimulationExports account={account} view={view} disabled={blocked}/>
      <nav className="r-subtabs">{views.map(([key,label])=><button key={key} className={view===key?"active":""} onClick={()=>{setView(key);w.updatePanel(panel.id,{view:key});}}>{label}</button>)}</nav>
      {view==="pending"?(account.pendingDecision?<><p className="r-note">这是最后信号日生成、尚待后续交易日执行的决策。</p><PendingDecision decision={account.pendingDecision}/></>:<Empty title="尚无待执行决策"/>):<SimulationTable key={`${account.id}:${view}`} account={account} table={view==="overview"?"portfolio":view} revision={revision} overview={view==="overview"} onRow={row=>{if(typeof row.symbol==="string")w.open({kind:"stock",title:row.symbol,projectId,symbol:row.symbol});}}/>}
    </>}
  </div>;
}

function SimulationTable({account,table,revision,overview,onRow}:{account:SimulationAccount;table:string;revision:number;overview:boolean;onRow:(row:JsonObject)=>void}) {
  const [page,setPage]=useState<Page|null>(null),[offset,setOffset]=useState(0),[error,setError]=useState("");
  useEffect(()=>{let alive=true;setPage(null);setError("");void(async()=>{
    const first=await request<Page>("simulation.table",{projectId:account.projectId,accountId:account.id,table,offset:overview?0:offset,limit:overview?500:200});
    if(overview){let next=first.rows.length;while(next<first.total){const more=await request<Page>("simulation.table",{projectId:account.projectId,accountId:account.id,table,offset:next,limit:500});if(!more.rows.length)throw new Error("账户曲线分页未返回剩余记录");first.rows.push(...more.rows);next+=more.rows.length;}}
    if(alive)setPage(first);
  })().catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[account.id,table,revision,offset,overview]);
  if(error)return <p role="alert">{error}</p>;
  if(!page)return <p role="status">正在读取账户记录…</p>;
  return <>{overview&&page.rows.length>0&&<Plot title="模拟账户累计净值" option={{tooltip:{trigger:"axis"},grid:{left:55,right:20,bottom:55},xAxis:{type:"category",data:page.rows.map(row=>String(row.date))},yAxis:{type:"value",scale:true},dataZoom:[{type:"inside"},{type:"slider"}],series:[{name:"累计净值",type:"line",showSymbol:false,data:page.rows.map(row=>typeof row.account==="number"?row.account/account.capital:null)}]}}/>}<DataTable table={{...page,name:overview?"每日账户":views.find(([key])=>key===table)?.[1]??table}} onRow={table==="portfolio"?undefined:onRow}/>{!overview&&<div className="r-toolbar"><button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-200))}>上一页</button><span>{page.total?`${offset+1}–${offset+page.rows.length} / ${page.total}`:"0"} 行</span><button disabled={offset+page.rows.length>=page.total} onClick={()=>setOffset(offset+200)}>下一页</button><button disabled={offset+page.rows.length>=page.total} onClick={()=>setOffset(Math.max(0,Math.floor((page.total-1)/200)*200))}>最新记录</button></div>}<p className="r-note">历史补算标识来自账户记录；表格搜索和排序作用于当前页。</p></>;
}

function PendingDecision({decision}:{decision:JsonObject}) {
  const quantities=object(decision.quantities),weights=object(decision.targetWeights),reasons=object(decision.reasons);
  const rows=Object.keys(quantities).map(symbol=>({symbol,targetQuantity:quantities[symbol],targetWeight:weights[symbol],reason:reasons[symbol]}));
  return <><p>信号日：{valueText(decision.date)} · 生成时间：{valueText(decision.generatedAt)}</p>{Array.isArray(decision.conflicts)&&decision.conflicts.length>0&&<p role="alert">无法执行：{valueText(decision.conflicts)}</p>}{Array.isArray(decision.warnings)&&decision.warnings.length>0&&<p>{valueText(decision.warnings)}</p>}<DataTable table={{name:"待执行目标",columns:["symbol","targetQuantity","targetWeight","reason"],rows}}/><p className="r-note">目标股数按信号日价格计算，实际成交受下一交易日行情、可卖数量和费用规则约束。</p></>;
}

function SimulationExports({account,view,disabled}:{account:SimulationAccount;view:string;disabled:boolean}) {
  const s=useResearch(),w=useWorkspace();const [snapshot,setSnapshot]=useState<Experiment|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  useEffect(()=>{let alive=true;setSnapshot(null);setError("");void request<Experiment[]>("experiments.list",{projectId:account.projectId}).then(values=>{if(alive)setSnapshot(values.filter(value=>value.kind==="simulation.advance"&&value.parameters.accountId===account.id).sort((a,b)=>b.createdAt.localeCompare(a.createdAt))[0]??null);}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[account.id,account.revision]);
  const table=view==="overview"?"portfolio":view==="pending"?"target_weights":view;
  const label=view==="overview"?"每日账户":view==="pending"?"目标组合":views.find(([key])=>key===view)?.[1]??tableLabel(table);
  const exportFile=(format:"csv"|"xlsx")=>{if(!snapshot)return;setBusy(true);setError("");void(async()=>{
    const detail=await request<ExperimentDetails>("experiments.get",{projectId:account.projectId,experimentId:snapshot.id});
    if(object(detail.details.account).asOfDate!==account.asOfDate)throw new Error("最近推进结果与当前账户日期不同，请先查看推进结果，确认导出范围。");
    const result=await request<{path:string}>("exports.create",{projectId:account.projectId,experimentId:snapshot.id,format,...(format==="csv"?{table}:{})});
    const path=await window.v3Research!.exportFile({format,sourcePath:result.path,suggestedName:`${account.name}-${account.asOfDate??"未开始"}-${format==="csv"?label:"全部记录"}.${format}`});
    if(path)s.setNotice(`已导出：${path}`);
  })().catch(e=>setError(errorText(e))).finally(()=>setBusy(false));};
  return <details><summary>账户导出与报告</summary><div className="r-toolbar"><button disabled={disabled||busy||!snapshot} onClick={()=>exportFile("csv")}>导出{label}完整 CSV</button><button disabled={disabled||busy||!snapshot} onClick={()=>exportFile("xlsx")}>导出账户全部记录 Excel</button><button disabled={!snapshot} onClick={()=>snapshot&&w.open({kind:"experiment",title:`${account.name} · 推进结果`,projectId:account.projectId??undefined,strategyId:account.strategyId??undefined,experimentId:snapshot.id})}>查看推进结果 / PDF 报告</button></div><p className="r-note">导出最近一次推进保存的完整记录，不受表格分页和搜索影响。{!snapshot?"尚无推进结果可导出。":""}</p>{error&&<p role="alert">{error}</p>}</details>;
}
