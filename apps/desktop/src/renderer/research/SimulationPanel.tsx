import React, { useEffect, useRef, useState } from "react";
import type { Experiment, JobEvent, JsonObject, ResearchTable, SimulationAccount, SimulationAccountRef, WorkspacePanel } from "../../../../../packages/contracts/src/research";
import { object } from "./configuration";
import { errorText, request, useResearch } from "./state";
import { useWorkspace } from "./workspace";
import { DataTable, Empty, Field, Heading, Plot, tableLabel, valueText } from "./ui";
import { accountKey, accountLabel, accountRef } from "./SelectionPositionsSourceEditor";
import { SimulationBindings, SimulationCashFlow, SimulationCopy, SimulationOwnership } from "./SimulationManagement";
import "./simulation.css";

type Page = ResearchTable & { total:number; offset:number; limit:number };
const views = [["overview","账户概况"],["ownership","当前归属"],["bindings","策略绑定"],["holdings","持仓记录"],["pending","待执行决策"],["trades","成交"],["unfilled","到期未成交"],["cash_flows","资金流水"],["trade_allocations","成交分摊"],["binding_events","绑定事件"],["rule_events","命中规则"],["signals","信号"],["target_weights","目标组合"],["account_events","账户事件"],["model_events","模型事件"]];
const money = (value:number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2}) : "未知";

export function SimulationPanel({panel}:{panel:WorkspacePanel}) {
  const s=useResearch(),w=useWorkspace();
  const [accounts,setAccounts]=useState<SimulationAccount[]>([]),[account,setAccount]=useState<SimulationAccount|null>(null);
  const [name,setName]=useState(""),[startDate,setStartDate]=useState(s.project?.startDate??""),[capital,setCapital]=useState("1000000");
  const [endDate,setEndDate]=useState(new Date().toLocaleDateString("en-CA"));
  const [creating,setCreating]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const [view,setView]=useState(panel.view??"overview"),[revision,setRevision]=useState(0),[loading,setLoading]=useState(true);
  const [activeJob,setActiveJob]=useState<JobEvent|null>(null);
  const loadSequence=useRef(0), mutationLock=useRef(false);
  const ref=account?accountRef(account):null;
  const identity=ref?accountKey(ref):"";
  const refresh=async(target?:SimulationAccountRef)=>{
    const sequence=++loadSequence.current;
    const values=await request<SimulationAccount[]>("simulation.accounts.list");
    const selectedRef=target??(panel.accountId?{accountId:panel.accountId,projectId:panel.projectId??null}:values[0]?accountRef(values[0]):undefined);
    const selected=selectedRef?await request<SimulationAccount>("simulation.accounts.get",selectedRef):null;
    if(sequence!==loadSequence.current)return selected;
    setAccounts(values);setActiveJob(null);setAccount(selected);setName(selected?.name??"");setRevision(v=>v+1);
    if(selected){
      const jobs=await request<JobEvent[]>("jobs.list",{projectId:selected.projectId,statuses:["queued","running"],limit:1000});
      if(sequence===loadSequence.current)setActiveJob(jobs.find(job=>job.kind==="simulation.advance"&&job.spec.parameters.accountId===selected.id&&(job.projectId??null)===(selected.projectId??null))??null);
    }
    return selected;
  };
  useEffect(()=>{setLoading(true);setAccount(null);setError("");const token=++loadSequence.current;void refresh().catch(e=>{if(loadSequence.current===token+1)setError(errorText(e));}).finally(()=>{if(loadSequence.current===token+1)setLoading(false);});return()=>{loadSequence.current++;};},[panel.projectId,panel.accountId]);
  useEffect(()=>window.v3Research?.onEvent(event=>{
    if(!account||event.kind!=="simulation.advance"||(event.projectId??null)!==(account.projectId??null)||event.spec.parameters.accountId!==account.id)return;
    if(["queued","running"].includes(event.status))setActiveJob(event);
    else {setActiveJob(null);void refresh(accountRef(account)).catch(e=>setError(errorText(e)));}
  }),[identity]);
  const run=(work:()=>Promise<void>)=>{if(mutationLock.current)return;mutationLock.current=true;setBusy(true);setError("");void work().catch(e=>setError(errorText(e))).finally(()=>{mutationLock.current=false;setBusy(false);});};
  const choose=(next:SimulationAccount)=>{loadSequence.current++;setCreating(false);setAccount(next);setName(next.name);setView("overview");setActiveJob(null);w.updatePanel(panel.id,{accountId:next.id,projectId:next.projectId??undefined,strategyId:undefined,view:"overview"});};
  const mutate=async(operation:string,params:object)=>{
    if(!account)throw Error("请先读取账户。");
    const payload=operation==="importLegacy"?params:{...accountRef(account),expectedRevision:account.revision,...params};
    const response=await request<SimulationAccount|{account:SimulationAccount}>("simulation.accounts."+operation,payload);
    const next="account" in response?response.account:response;
    // A successful mutation is recorded before any secondary refresh can fail.
    setAccount(next);setName(next.name);setRevision(n=>n+1);
    setAccounts(values=>{const key=accountKey(accountRef(next));return [...values.filter(a=>accountKey(accountRef(a))!==key),next];});
    window.dispatchEvent(new Event("v3-simulation-accounts-changed"));
    return next;
  };
  const blocked=busy||!!activeJob||loading;
  const legacy=!!account?.projectId||account?.schemaVersion!==2;
  return <div className="r-page simulation-page"><Heading title="日线模拟账户" description="多个独立账户，固定策略版本，按交易日保存决策、成交和资金流水。"/>
    {error&&<p role="alert" className="r-local-error">{error} <button disabled={busy} onClick={()=>run(async()=>{await refresh(ref??undefined);})}>重新读取当前账户</button></p>}
    <div className="r-toolbar"><select aria-label="选择模拟账户" disabled={blocked} value={identity} onChange={e=>{const next=accounts.find(a=>accountKey(accountRef(a))===e.target.value);if(next)choose(next);}}><option value="" disabled>选择账户</option>{accounts.map(value=><option key={accountKey(accountRef(value))} value={accountKey(accountRef(value))}>{accountLabel(value)} · {value.asOfDate??"尚未推进"}</option>)}</select><button disabled={blocked} onClick={()=>{setCreating(true);setName("");}}>新建全局账户</button><button disabled={busy||loading} onClick={()=>run(async()=>{await refresh(ref??undefined);})}>刷新</button></div>
    {(creating||(!loading&&!account))&&<section><h2>创建无策略账户</h2><div className="r-form-grid"><Field label="账户名称"><input value={name} disabled={busy} onChange={e=>setName(e.target.value)}/></Field><Field label="起始信号日"><input type="date" value={startDate} disabled={busy} onChange={e=>setStartDate(e.target.value)}/></Field><Field label="初始虚拟资金（元）"><input type="number" min="0.01" step="1000" value={capital} disabled={busy} onChange={e=>setCapital(e.target.value)}/></Field></div><p className="r-note">账户独立保留现金，创建后再绑定每日方案或项目策略。首个信号日收盘决策，下一交易日执行。</p><div className="r-toolbar"><button className="r-primary" disabled={blocked||!name.trim()||!startDate||!Number.isFinite(Number(capital))||Number(capital)<=0} onClick={()=>run(async()=>{const created=await request<SimulationAccount>("simulation.accounts.create",{name:name.trim(),startDate,capital:Number(capital)});setAccounts(values=>[...values,created]);choose(created);s.setNotice("全局账户已创建，尚未绑定策略或推进日期");})}>创建账户</button>{account&&<button disabled={busy} onClick={()=>{setCreating(false);setName(account.name);}}>返回账户</button>}</div></section>}
    {loading?<p role="status">正在读取账户…</p>:account&&!creating&&<>
      <div className="r-toolbar"><input aria-label="模拟账户名称" disabled={blocked} value={name} onChange={e=>setName(e.target.value)}/><button disabled={blocked||!name.trim()||name===account.name} onClick={()=>run(async()=>{await mutate("save",{name:name.trim()});})}>保存名称</button><span>{account.projectId?"旧项目账户":"全局账户"} · 保存版本 {account.revision}</span></div>
      <div className="r-metrics">{[["账户资产（元）",account.valuationStatus==="unavailable"?"估值缺失":money(account.nav)],["可用现金（元）",money(account.cash)],["单位净值",typeof account.unitNav==="number"&&Number.isFinite(account.unitNav)?account.unitNav.toFixed(4):"未知"],["累计净投入（元）",money(account.netContributions)],["最后完成日",account.asOfDate??"尚未开始"]].map(([label,value])=><div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
      <p className="r-note">初始资金 {money(account.capital)} 元 · 起始信号日 {account.startDate} · {account.paused?"已暂停":account.status==="blocked"?"推进受阻":"可推进"}{account.valuationStatus===undefined?" · 旧记录未说明估值状态":""}</p>
      {account.unresolved&&<p role="alert">{account.unresolved.date??"未完成日期"}：{account.unresolved.message}。最后完成日以前的账户记录已保留。</p>}
      {account.origin&&<p className="r-note">迁入来源：{account.origin.projectId} / {account.origin.accountId} · 源版本 {account.origin.revision}。原账户保留。</p>}
      {account.branchOf&&<p className="r-note">历史分支：{account.branchOf.accountId} · 从 {account.branchOf.date} 收盘之后继续。</p>}
      <div className="r-toolbar"><label>推进截至 <input aria-label="模拟推进截至日期" type="date" disabled={blocked} value={endDate} onChange={e=>setEndDate(e.target.value)}/></label><button className="r-primary" disabled={blocked||account.paused||legacy||!endDate||endDate<(account.asOfDate??account.startDate)} onClick={()=>run(async()=>{const job=await request<JobEvent>("jobs.submit",{spec:{kind:"simulation.advance",projectId:account.projectId??undefined,parameters:{...accountRef(account),expectedRevision:account.revision,endDate}}});setActiveJob(job);s.setNotice("模拟推进已进入任务队列");})}>{account.asOfDate?"继续推进 / 补算":"开始推进"}</button><button disabled={blocked} onClick={()=>run(async()=>{await mutate("save",{paused:!account.paused});})}>{account.paused?"恢复账户":"暂停账户"}</button>{activeJob&&<button disabled={busy} onClick={()=>run(async()=>{await request("jobs.cancel",{jobId:activeJob.id});s.setNotice("已请求停止，等待任务确认");})}>停止推进</button>}</div>
      {activeJob&&<p role="status">{activeJob.status==="queued"?"排队中":"推进中"} · {activeJob.message}</p>}
      <p className="r-note">{legacy?"旧账户保留读取、导出、改名和暂停操作；请复制迁入后使用完整账户管理。":"读取不会推进；使用已保存的绑定版本和本地行情逐日执行，历史补算会记录标识。未成交当日到期，后续信号重新决策。"}需要新行情时先在数据中心更新。</p>
      <SimulationCopy key={identity} account={account} disabled={blocked} mutate={mutate} run={run} onCreated={choose}/>
      {!legacy&&<SimulationCashFlow key={identity+"cash"} account={account} disabled={blocked} mutate={mutate} run={run}/>}
      <SimulationExports account={account} view={view} disabled={blocked}/>
      <nav className="r-subtabs" aria-label="模拟账户视图">{views.map(([key,label])=><button key={key} className={view===key?"active":""} onClick={()=>{setView(key);w.updatePanel(panel.id,{view:key});}}>{label}</button>)}</nav>
      {view==="bindings"?<SimulationBindings key={identity} account={account} disabled={blocked||legacy} mutate={mutate} run={run}/>:view==="ownership"?<SimulationOwnership key={identity} account={account} disabled={blocked||legacy} mutate={mutate} run={run}/>:view==="pending"?(account.pendingDecision?<><p className="r-note">最后信号日生成的决策，实际成交以推进结果为准。</p><PendingDecision decision={account.pendingDecision}/></>:<Empty title="尚无待执行决策"/>):<SimulationTable key={identity+":"+view} account={account} table={view==="overview"?"portfolio":view} revision={revision} overview={view==="overview"} onRow={row=>{if(typeof row.symbol==="string")w.open({kind:"stock",title:row.symbol,projectId:account.projectId??undefined,symbol:row.symbol});}}/>}
    </>}
  </div>;
}

function SimulationTable({account,table,revision,overview,onRow}:{account:SimulationAccount;table:string;revision:number;overview:boolean;onRow:(row:JsonObject)=>void}) {
  const [page,setPage]=useState<Page|null>(null),[offset,setOffset]=useState(0),[error,setError]=useState("");
  const [curve,setCurve]=useState<{rows:{date:string;unitNav:number|null;nav:number|null}[];total:number}|null>(null),[curveError,setCurveError]=useState("");
  useEffect(()=>{let alive=true;setPage(null);setError("");
    void request<Page>("simulation.table",{...accountRef(account),table,offset,limit:200}).then(value=>{if(alive)setPage(value);}).catch(e=>{if(alive)setError(errorText(e));});
    return()=>{alive=false;};
  },[account.id,account.projectId,table,revision,offset]);
  useEffect(()=>{let alive=true;setCurve(null);setCurveError("");
    if(overview)void request<{rows:{date:string;unitNav:number|null;nav:number|null}[];total:number}>("simulation.accounts.curve",{...accountRef(account),maxPoints:600}).then(value=>{if(alive)setCurve(value);}).catch(e=>{if(alive)setCurveError(errorText(e));});
    return()=>{alive=false;};
  },[account.id,account.projectId,revision,overview]);
  return <>{overview&&<>{curveError?<p role="alert">曲线读取失败：{curveError}</p>:!curve?<p role="status">正在读取账户曲线…</p>:curve.rows.length>0?<><Plot title="模拟账户单位净值" option={{tooltip:{trigger:"axis"},grid:{left:55,right:20,bottom:55},xAxis:{type:"category",data:curve.rows.map(row=>row.date)},yAxis:{type:"value",scale:true},dataZoom:[{type:"inside"},{type:"slider"}],series:[{name:"单位净值",type:"line",showSymbol:false,connectNulls:false,data:curve.rows.map(row=>row.unitNav)}]}}/><p className="r-note">曲线显示 {curve.rows.length} 个点 / 共 {curve.total} 个日期{curve.total>curve.rows.length?"（服务端抽样）":""}。完整每日记录见下方分页表或导出。缺失单位净值留空。</p></>:<p>尚无已完成日期的净值曲线。</p>}</>}{error?<p role="alert">{error}</p>:!page?<p role="status">正在读取账户记录…</p>:<><DataTable table={{...page,name:overview?"每日账户":views.find(([key])=>key===table)?.[1]??table}} onRow={table==="portfolio"?undefined:onRow}/><div className="r-toolbar"><button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-200))}>上一页</button><span>{page.total?`${Math.min(offset+1,page.total)}–${Math.min(offset+page.rows.length,page.total)} / ${page.total}`:"0"} 行</span><button disabled={offset+page.rows.length>=page.total} onClick={()=>setOffset(offset+200)}>下一页</button><button disabled={offset+page.rows.length>=page.total} onClick={()=>setOffset(Math.max(0,Math.floor((page.total-1)/200)*200))}>最新记录</button></div></>}<p className="r-note">历史补算标识来自记录；搜索和排序作用于当前页。</p></>;
}

function PendingDecision({ decision }: { decision: JsonObject }) {
  const intents = Array.isArray(decision.intents)
    ? decision.intents.filter(value => value && typeof value === "object" && !Array.isArray(value)).map(value => value as JsonObject)
    : [];
  const quantities = object(decision.quantities);
  const weights = object(decision.targetWeights);
  const reasons = object(decision.reasons);
  const rows: JsonObject[] = intents.length
    ? intents.map(intent => ({
        symbol: intent.symbol,
        ownershipId: intent.ownershipId,
        bindingId: intent.bindingId,
        entryVersionId: intent.versionId,
        targetQuantity: intent.targetQuantity,
        costs: intent.costs,
        reason: intent.reason ?? intent.reasons,
      }))
    : Object.keys(quantities).map(symbol => ({
        symbol,
        targetQuantity: quantities[symbol],
        targetWeight: weights[symbol],
        reason: reasons[symbol],
      }));
  const failures = Array.isArray(decision.failures) ? decision.failures : [];
  const columns = intents.length
    ? ["symbol", "ownershipId", "bindingId", "entryVersionId", "targetQuantity", "costs", "reason"]
    : ["symbol", "targetQuantity", "targetWeight", "reason"];

  return <>
    <p>信号日：{valueText(decision.date)} · 执行日期：{valueText(decision.executionDate ?? "下一交易日待确定")} · 生成时间：{valueText(decision.generatedAt)}</p>
    {failures.length > 0 && <div role="alert"><strong>部分归属或策略处理失败</strong><ul>{failures.map((failure, index) => <li key={index}>{valueText(failure)}</li>)}</ul></div>}
    {Array.isArray(decision.conflicts) && decision.conflicts.length > 0 && <p role="alert">无法执行：{valueText(decision.conflicts)}</p>}
    {Array.isArray(decision.warnings) && decision.warnings.length > 0 && <p>{valueText(decision.warnings)}</p>}
    {rows.length > 0 ? <DataTable table={{ name: "待执行意图（不是实际委托或成交）", columns, rows }} /> : <Empty title="当前没有待执行意图" />}
    <p className="r-note">目标股数是决策意图，不代表实际委托或成交。成交情况请在推进完成后查看交易和归属记录；旧版账户只显示其历史目标字段。</p>
  </>;
}

function SimulationExports({account,view,disabled}:{account:SimulationAccount;view:string;disabled:boolean}) {
  const s=useResearch(),w=useWorkspace();
  const [snapshot,setSnapshot]=useState<Experiment|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[historyError,setHistoryError]=useState("");
  const lock=useRef(false);
  useEffect(()=>{let alive=true;setSnapshot(null);setHistoryError("");void request<Experiment[]>("experiments.list",{projectId:account.projectId}).then(values=>{if(alive)setSnapshot(values.filter(value=>value.kind==="simulation.advance"&&value.parameters.accountId===account.id).sort((a,b)=>b.createdAt.localeCompare(a.createdAt))[0]??null);}).catch(e=>{if(alive)setHistoryError(errorText(e));});return()=>{alive=false;};},[account.id,account.projectId,account.revision]);
  const table=view==="overview"?"portfolio":view==="pending"?"target_weights":view==="bindings"?"binding_events":view;
  const label=view==="overview"?"每日账户":view==="pending"?"目标组合":view==="bindings"?"绑定事件":views.find(([key])=>key===view)?.[1]??tableLabel(table);
  const exportFile=(format:"csv"|"xlsx")=>{
    if(lock.current)return;lock.current=true;setBusy(true);setError("");
    void(async()=>{
      const result=await request<{path:string}>("simulation.accounts.export",{...accountRef(account),expectedRevision:account.revision,format,...(format==="csv"?{table}:{})});
      const path=await window.v3Research!.exportFile({format,sourcePath:result.path,suggestedName:`${account.name}-v${account.revision}-${format==="csv"?label:"全部记录"}.${format}`});
      if(path)s.setNotice(`已导出账户版本 ${account.revision}：${path}`);
    })().catch(e=>setError(errorText(e))).finally(()=>{lock.current=false;setBusy(false);});
  };
  return <details><summary>当前账户导出与历史报告</summary><div className="r-toolbar"><button disabled={disabled||busy} onClick={()=>exportFile("csv")}>导出{label}完整 CSV</button><button disabled={disabled||busy} onClick={()=>exportFile("xlsx")}>导出当前账户全部记录 Excel</button><button disabled={!snapshot} onClick={()=>snapshot&&w.open({kind:"experiment",title:`${account.name} · 历史推进结果`,projectId:account.projectId??undefined,strategyId:account.strategyId??undefined,experimentId:snapshot.id})}>查看历史推进 / 交易回放 / PDF</button></div><p className="r-note">当前账户按保存版本 {account.revision} 一致导出，不受分页和搜索影响，无需再次推进。历史推进报告是当次保存的快照，不包含之后的入出金或绑定变更。{!snapshot?"尚无历史推进报告。":""}</p>{error&&<p role="alert">{error}</p>}{historyError&&<p role="alert">历史报告读取失败：{historyError}</p>}</details>;
}
