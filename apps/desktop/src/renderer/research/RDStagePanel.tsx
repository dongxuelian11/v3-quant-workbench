import React, { useEffect, useState } from "react";
import type { ExperimentDetails, JobEvent, JobSpec, JsonObject, ResearchConversation, StrategyConfig } from "../../../../../packages/contracts/src/research";
import { errorText, request, useResearch } from "./state";
import { flushDrafts, useWorkspace } from "./workspace";
import { dateKeys, object } from "./configuration";
import { Field } from "./ui";
interface Preview {factorIds:string[];modelServiceConfigured:boolean;message:string;serviceConnection:string;runtime:string}
const eventLabels:Record<string,string>={native_run_started:"原生研究启动",native_run_failed:"原生研究失败",native_step_started:"步骤开始",native_step_completed:"步骤完成",native_step_failed:"步骤失败",model_request_started:"模型请求开始",model_request_completed:"模型请求完成",embedding_started:"检索编码开始",embedding_completed:"检索编码完成",evaluation_waiting:"等待真实评价",evaluation_completed:"真实评价完成",checkpoint_saved:"检查点已保存",code_attempt_completed:"代码尝试完成",code_evolution_finished:"代码修复阶段结束",factor_prefix_checked:"因子时点检查完成"};
const stepLabels:Record<string,string>={direct_exp_gen:"生成研究方案",research:"研究方案",coding:"编写与修复代码",running:"运行实验",feedback:"整理实验反馈"};
const dateLabels=["训练开始","训练结束","验证开始","验证结束","测试开始","测试结束"];
export function RDStagePanel({conversation,blocked,onSubmitted}:{conversation:ResearchConversation;blocked:boolean;onSubmitted:(job:JobEvent)=>Promise<void>}) {
  const w=useWorkspace(),s=useResearch();
  const targets=w.strategies.filter(strategy=>conversation.context.some(ref=>ref.projectId===strategy.projectId&&(!ref.strategyId||ref.strategyId===strategy.id)));
  const [target,setTarget]=useState(targets.length===1?`${targets[0].projectId}:${targets[0].id}`:"");
  const [objective,setObjective]=useState(""),[action,setAction]=useState("factor"),[rounds,setRounds]=useState(3);
  const [periods,setPeriods]=useState<JsonObject>({}),[preview,setPreview]=useState<Preview|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const [projectId,strategyId]=target.split(":");const strategy=targets.find(value=>value.id===strategyId&&value.projectId===projectId);
  useEffect(()=>{let alive=true;setPreview(null);setError("");const model=object(strategy?.settings.model),validation=object(model.validation);setPeriods(Object.fromEntries(dateKeys.map(key=>[key,String(model[key]??validation[key]??"")])));if(strategy)void request<Preview>("rdagent.preview",{projectId,strategyId}).then(value=>{if(alive)setPreview(value);}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[target]);
  const dates=dateKeys.map(key=>String(periods[key]??""));
  const validDates=dates.every(Boolean)&&dates[0]<=dates[1]&&dates[1]<dates[2]&&dates[2]<=dates[3]&&dates[3]<dates[4]&&dates[4]<=dates[5];
  const valid=!!strategy&&!!objective.trim()&&validDates&&Number.isInteger(rounds)&&rounds>=1&&rounds<=3;
  return <details className="r-rd-stage"><summary>RD-Agent 原生研究</summary><div className="r-rd-stage-form">
    <Field label="本会话的研究策略"><select value={target} disabled={busy||blocked} onChange={e=>setTarget(e.target.value)}><option value="">选择已关联策略</option>{targets.map(value=><option key={`${value.projectId}:${value.id}`} value={`${value.projectId}:${value.id}`}>{s.projects.find(project=>project.id===value.projectId)?.name??value.projectId} · {value.name}</option>)}</select></Field>{!targets.length&&<p className="r-note">先把已有策略关联到本会话。</p>}
    <Field label="本阶段目标"><textarea aria-label="原生研究目标" rows={3} value={objective} onChange={e=>setObjective(e.target.value)}/></Field>
    <Field label="研究内容"><select value={action} onChange={e=>setAction(e.target.value)}><option value="factor">因子研究</option><option value="model">模型研究</option><option value="joint">因子与模型联合研究</option></select></Field>
    <div className="r-rd-grid"><Field label="研究轮数（1–3）"><input type="number" min={1} max={3} step={1} value={rounds} onChange={e=>setRounds(Number(e.target.value))}/></Field><p className="r-note">每次仅尝试一次代码修复；失败后等待你确认下一次尝试。</p>{dateKeys.map((key,index)=><Field key={key} label={dateLabels[index]}><input type="date" value={String(periods[key]??"")} onChange={e=>setPeriods({...periods,[key]:e.target.value})}/></Field>)}</div>
    <p className="r-note">沿用策略已保存的因子与标签设置。训练、验证、测试日期须完整且互不重叠；测试集不参与本阶段研究反馈。</p>
    {preview&&<p className="r-note">{preview.modelServiceConfigured?"模型服务已配置，连接将在运行时检查":"尚未配置模型服务"} · 基线因子 {preview.factorIds.length} 个。运行环境尚待实际检查。</p>}{error&&<p role="alert">{error}</p>}
    <button className="r-primary" disabled={busy||blocked||!valid||!preview?.modelServiceConfigured||!preview.factorIds.length} onClick={()=>{setBusy(true);setError("");void(async()=>{await flushDrafts();const values=await request<StrategyConfig[]>("strategies.list",{projectId});const latest=values.find(value=>value.id===strategyId);if(!latest)throw new Error("策略已不存在，请重新关联策略");const model=object(latest.settings.model);const job=await request<JobEvent>("jobs.submit",{spec:{kind:"rdagent.run",projectId,strategyId,name:`${conversation.name} · 原生研究`,parameters:{objective:objective.trim(),action,rounds,codeRepairRounds:1,periods,labelHorizon:model.labelHorizon??5,labelMode:model.labelMode??"next_open",sourceConversationId:conversation.id}}});await onSubmitted(job);})().catch(e=>setError(errorText(e))).finally(()=>setBusy(false));}}>{busy?"正在提交…":"启动本阶段"}</button>
  </div></details>;
}
export function RDStageEvent({job,blocked,onSubmitted}:{job:JobEvent;blocked:boolean;onSubmitted:(job:JobEvent)=>Promise<void>}) {
  const w=useWorkspace(),s=useResearch();const [status,setStatus]=useState<JsonObject>({}),[detail,setDetail]=useState<ExperimentDetails|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const terminal=["completed","failed","cancelled","interrupted"].includes(job.status);
  useEffect(()=>{let alive=true;setError("");void request<JsonObject>("rdagent.status",{projectId:job.projectId,jobId:job.id}).then(value=>{if(alive)setStatus(value);}).catch(e=>{if(alive)setError(errorText(e));});if(terminal&&job.experimentId)void request<ExperimentDetails>("experiments.get",{projectId:job.projectId,experimentId:job.experimentId}).then(value=>{if(alive)setDetail(value);}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[job.id,job.updatedAt,job.experimentId]);
  const [repairInstructions,setRepairInstructions]=useState("");
  const repair=object(status.repair??detail?.details.repair);
  const requiresConfirmation=status.requiresConfirmation===true||detail?.details.requiresConfirmation===true;
  useEffect(()=>{setRepairInstructions("");},[status.checkpointPath,repair.checkpointPath]);
  const frozen=detail?.experiment.kind==="rdagent.run"?detail.experiment:null;
  const resumeSpec:JobSpec|null=frozen?{kind:frozen.kind,projectId:frozen.projectId,strategyId:frozen.strategyId,name:frozen.name,parameters:{...frozen.parameters,resumeExperimentId:frozen.id}}
    :job.spec?.kind==="rdagent.run"&&job.experimentId?{...job.spec,parameters:{...job.spec.parameters,resumeExperimentId:job.experimentId}}:null;
  const canResume=["interrupted","cancelled","failed"].includes(job.status)&&typeof status.checkpointPath==="string"&&!!status.checkpointPath;
  const rounds=Array.isArray(detail?.details.rounds)?detail.details.rounds as JsonObject[]:[];
  const events=Array.isArray(status.events)?status.events as JsonObject[]:[],usage=object(status.usage);
  const currentStep=typeof status.currentStep==="string"?stepLabels[status.currentStep]??status.currentStep:null;
  const actionName=typeof status.currentAction==="string"?({factor:"因子",model:"模型",joint:"因子与模型"}[status.currentAction]??status.currentAction):null;
  return <div className="r-rd-event">
    {(status.currentRound!=null||currentStep||actionName)&&<p className="r-note">{typeof status.currentRound==="number"?`第 ${status.currentRound} 轮 · `:""}{actionName?`${actionName} · `:""}{currentStep??"等待下一步骤"}</p>}
    {typeof status.completedModelCalls==="number"&&<p className="r-note">已完成模型调用 {status.completedModelCalls} 次{typeof usage.total_tokens==="number"?` · 提供方已报告 ${usage.total_tokens.toLocaleString("zh-CN")} tokens`:" · 提供方未报告总用量"}</p>}
    {events.length>0&&<details><summary>本阶段最近 {events.length} 条真实事件</summary>{events.map((event,index)=><p className="r-note" key={String(event.id??index)}>{typeof event.time==="string"&&<time>{event.time.replace("T"," ").slice(0,19)} · </time>}{typeof event.round==="number"?`第 ${event.round} 轮 · `:""}{eventLabels[String(event.event)]??String(event.event??"研究事件")}{typeof event.step==="string"?` · ${stepLabels[event.step]??event.step}`:""}</p>)}</details>}
{!terminal&&<button disabled={busy} onClick={()=>{setBusy(true);void request("jobs.cancel",{jobId:job.id}).catch(e=>setError(errorText(e))).finally(()=>setBusy(false));}}>停止本阶段</button>}
    {error&&<p role="alert">{error}</p>}{typeof status.error==="string"&&status.error&&<p role="alert">{status.error}</p>}
    {rounds.map((round,index)=><div key={String(round.id??index)}><span>{String(round.name??`研究产物 ${index+1}`)} · {round.status==="completed"?"已评价":round.status==="failed"?"评价失败":"等待评价"}</span>{typeof round.error==="string"&&round.error&&<p>{round.error}</p>}{typeof round.candidateId==="string"&&<button onClick={()=>w.open({kind:"candidate",title:String(round.name??"研究候选"),projectId:job.projectId,strategyId:job.strategyId,candidateId:String(round.candidateId)})}>查看候选</button>}</div>)}
    {requiresConfirmation&&<section className="r-repair-review"><h4>等待修复确认</h4><p role="alert">{String(repair.error??status.error??"原生代码执行失败")}</p>{typeof repair.codeScope==='string'&&<p className="r-note">{repair.codeScope}</p>}{Array.isArray(repair.code)&&repair.code.map((value,index)=>{const file=object(value);return <details key={index}><summary>{String(file.path??"失败代码")}</summary><pre>{String(file.content??"")}</pre></details>;})}<p>{typeof repair.proposal==='string'?repair.proposal:"尚未提供修复尝试说明。"}</p><Field label="补充修复说明（可选）"><textarea value={repairInstructions} disabled={busy||blocked} onChange={e=>setRepairInstructions(e.target.value)}/></Field></section>}
    {canResume&&<><button disabled={busy||blocked||!resumeSpec} onClick={()=>{if(!resumeSpec)return;setBusy(true);setError("");void s.act(async()=>{await flushDrafts();const next=await request<JobEvent>("jobs.submit",{spec:{...resumeSpec,parameters:resumeParameters(resumeSpec.parameters,requiresConfirmation,repairInstructions)}});await onSubmitted(next);}).finally(()=>setBusy(false));}}>{requiresConfirmation?"确认尝试修复并继续":"从检查点继续本阶段"}</button>{!resumeSpec&&<p className="r-note">恢复所需的实验参数尚不可用，请检查阶段结果是否仍然存在。</p>}</>}
    {terminal&&<p className="r-note">本阶段已停止推进。可携实际结果讨论下一阶段；不会自动启动后续研究。</p>}
  </div>;
}

export function resumeParameters(parameters:JsonObject,confirmRepair=false,instructions=""):JsonObject {
 const {confirmRepair:previousConfirmation,repairInstructions:previousInstructions,...rest}=parameters;
 return {...rest,...(confirmRepair?{confirmRepair:true,...(instructions.trim()?{repairInstructions:instructions.trim()}:{})}:{})};
}
