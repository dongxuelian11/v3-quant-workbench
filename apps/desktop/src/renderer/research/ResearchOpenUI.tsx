import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { createLibrary, createParser, defineComponent, Renderer, useStateField } from "@openuidev/react-lang";
import { z } from "zod/v4";
import type { JsonObject, ResearchUIBlock, ReproductionPlan, ReproductionRun } from "../../../../../packages/contracts/src/research";
import { request, errorText } from "./state";
import { useWorkspace } from "./workspace";
import type { TablePage } from "./PagedTable";
import { DataTable, Plot } from "./ui";
import { object } from "./configuration";

const BlockContext = createContext<ResearchUIBlock | null>(null);
const ActionContext = createContext<{state:JsonObject;busy:boolean;edit:(step:string,key:string,value:string|number|boolean)=>void;apply:(run:boolean)=>void}|null>(null);
const Text = defineComponent({ name: "ResearchText", description: "研究解释；结论必须注明依据和未验证条件。", props: z.object({ text: z.string() }), component: ({ props }) => <p>{props.text}</p> });
const Citation = defineComponent({ name: "ReportCitation", description: "打开当前研报原文的指定页；摘录是待核对引用。", props: z.object({ page: z.number().int().positive(), excerpt: z.string() }), component: ({ props }) => {
  const block = useContext(BlockContext), w = useWorkspace();
  return <blockquote><p>{props.excerpt}</p><button disabled={!block?.reportId} onClick={() => block?.reportId && w.open({ kind: "report", title: "研报原文", projectId: block.projectId ?? undefined, reportId: block.reportId, page: props.page })}>核对原文 · 第 {props.page} 页</button></blockquote>;
} });
const Choice = defineComponent({ name: "ResearchChoice", description: "保存用户选择的方案条件，仅编辑表单，不执行任务。", props: z.object({ name: z.string(), label: z.string(), options: z.array(z.string()), value: z.string() }), component: ({ props }) => {
  const field = useStateField(props.name, props.value);
  return <label className="r-openui-choice">{props.label}<select value={String(field.value ?? props.value)} onChange={e => field.setValue(e.target.value)}>{props.options.map(option => <option key={option} value={option}>{option}</option>)}</select></label>;
} });
const Plan = defineComponent({ name: "ReproductionLink", description: "打开已保存的复现计划核对；不会启动执行。", props: z.object({ label: z.string() }), component: ({ props }) => {
  const block = useContext(BlockContext), w = useWorkspace();
  return <button disabled={!block?.projectId || !block.reproductionId} onClick={() => block?.projectId && block.reproductionId && w.open({ kind: "reproduction", title: "研报复现", projectId: block.projectId, reportId: block.reportId, reproductionId: block.reproductionId })}>{props.label}</button>;
} });
const Result = defineComponent({ name: "ExperimentLink", description: "打开当前消息关联的真实实验。", props: z.object({ experimentId: z.string(), label: z.string() }), component: ({ props }) => {
  const block = useContext(BlockContext), w = useWorkspace();
  const available = !!block?.projectId && block.experimentIds?.includes(props.experimentId);
  return <button disabled={!available} onClick={() => available && w.open({ kind: "experiment", title: props.label, projectId: block!.projectId!, experimentId: props.experimentId })}>{props.label}</button>;
} });
const Parameter = defineComponent({name:"PlanParameter",description:"编辑已保存复现计划中指定步骤的现有标量参数；应用按钮点击后才保存。",props:z.object({stepId:z.string(),parameter:z.string(),label:z.string(),value:z.union([z.string(),z.number(),z.boolean()])}),component:({props})=>{
  const action=useContext(ActionContext),value=object(object(action?.state.parameters)[props.stepId])[props.parameter]??props.value;
  return <label className="r-openui-choice">{props.label}{typeof props.value==='boolean'?<input disabled={action?.busy} type="checkbox" checked={value===true} onChange={e=>action?.edit(props.stepId,props.parameter,e.target.checked)}/>:<input disabled={action?.busy} type={typeof props.value==='number'?'number':'text'} value={String(value)} onChange={e=>{const next=typeof props.value==='number'?Number(e.target.value):e.target.value;if(typeof next==='number'&&!Number.isFinite(next))return;action?.edit(props.stepId,props.parameter,next);}}/>}</label>;
}});
const Apply = defineComponent({name:"ReproductionAction",description:"用户点击后应用已编辑参数；run=true会保存新修订并启动依赖流水。",props:z.object({label:z.string(),run:z.boolean()}),component:({props})=>{
  const action=useContext(ActionContext),block=useContext(BlockContext);
  return <button disabled={action?.busy||!block?.projectId||!block.reproductionId} onClick={()=>action?.apply(props.run)}>{action?.busy?'正在处理…':props.label}</button>;
}});
function SavedTable({experimentId,table}:{experimentId:string;table:string}) {
  const block=useContext(BlockContext),[data,setData]=useState<TablePage|null>(null),[error,setError]=useState(''),[offset,setOffset]=useState(0);
  const allowed=!!block?.projectId&&block.experimentIds?.includes(experimentId);
  useEffect(()=>{let alive=true;setData(null);setError('');if(!allowed)return;void request<TablePage>('experiments.table',{projectId:block!.projectId,experimentId,table,offset,limit:50}).then(value=>{if(alive)setData(value);}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[allowed,block?.projectId,experimentId,table,offset]);
  if(!allowed)return <p>未关联此实验。</p>;
  if(error)return <p role="alert">{error}</p>;
  if(!data)return <p role="status">正在读取真实实验表…</p>;
  return <><DataTable table={{name:table,columns:data.columns,rows:data.rows}}/><div className="r-toolbar"><button disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-50))}>上页</button><span>{offset+1}—{offset+data.rows.length} / {data.total}</span><button disabled={offset+50>=data.total} onClick={()=>setOffset(offset+50)}>下页</button></div></>;
}
const Table=defineComponent({name:'ExperimentTable',description:'分页读取关联实验的真实表格，不接受生成数值。',props:z.object({experimentId:z.string(),table:z.string()}),component:({props})=><SavedTable {...props}/>});
function SavedComparison({table,x,y,title}:{table:string;x:string;y:string;title:string}) {
  const block=useContext(BlockContext),[data,setData]=useState<{id:string;page:TablePage}[]>([]),[error,setError]=useState('');
  const ids=block?.experimentIds??[];
  useEffect(()=>{let alive=true;setData([]);setError('');if(!block?.projectId||ids.length<2)return;void Promise.all(ids.map(async id=>({id,page:await request<TablePage>('experiments.table',{projectId:block.projectId,experimentId:id,table,offset:0,limit:500})}))).then(value=>{if(alive)setData(value);}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[block?.projectId,ids.join('|'),table]);
  if(ids.length<2)return <p>至少需要两份关联的真实实验。</p>;
  if(error)return <p role="alert">比较数据未读取：{error}</p>;
  if(!data.length)return <p role="status">正在读取比较数据…</p>;
  if(data.some(item=>!item.page.columns.includes(x)||!item.page.columns.includes(y)))return <p>部分实验没有相同指标，无法直接比较。</p>;
  const dates=[...new Set(data.flatMap(item=>item.page.rows.map(row=>String(row[x]??''))))].sort();
  return <><Plot title={title} option={{legend:{type:'scroll'},tooltip:{trigger:'axis'},grid:{left:50,right:15,top:35,bottom:45},xAxis:{type:'category',data:dates},yAxis:{type:'value',scale:true},series:data.map(item=>{const values=new Map(item.page.rows.map(row=>[String(row[x]??''),row[y]]));return {name:item.id,type:'line' as const,showSymbol:false,connectNulls:false,data:dates.map(date=>{const value=values.get(date);return typeof value==='number'&&Number.isFinite(value)?value:null;})};})}}/><p className="r-note">按原始横轴对齐，缺失保留断线；各实验最多显示前 500 条。不同复现口径请在完整实验中核对。</p></>;
}
const Compare=defineComponent({name:'ExperimentCompare',description:'按相同表及指标比较所有关联实验，读取真实数据，缺值断线。',props:z.object({table:z.string(),x:z.string(),y:z.string(),title:z.string()}),component:({props})=><SavedComparison {...props}/>});
function SavedChart({ experimentId, table, x, y, title }: { experimentId: string; table: string; x: string; y: string; title: string }) {
  const block = useContext(BlockContext);
  const allowed = !!block?.projectId && block.experimentIds?.includes(experimentId);
  const [data, setData] = useState<TablePage | null>(null), [error, setError] = useState("");
  useEffect(() => {
    let alive = true;setData(null);setError("");
    if (!allowed) return;
    void request<TablePage>("experiments.table", { projectId: block!.projectId, experimentId, table, offset: 0, limit: 500 }).then(value => { if (alive) setData(value); }).catch(e => { if (alive) setError(errorText(e)); });
    return () => { alive = false; };
  }, [allowed, block?.projectId, experimentId, table]);
  if (!allowed) return <p className="r-note">此图没有关联到当前消息的已保存实验。</p>;
  if (error) return <p role="alert">实验图未读取：{error}</p>;
  if (!data) return <p role="status">正在读取实验原始数值…</p>;
  if (!data.columns.includes(x) || !data.columns.includes(y) || !data.rows.some(row => typeof row[y] === "number" && Number.isFinite(row[y]))) return <p className="r-note">该实验没有可绘制的 {y} 数值。</p>;
  return <><Plot title={title} option={{ grid: { left: 50, right: 12, top: 12, bottom: 45 }, tooltip: { trigger: "axis" }, xAxis: { type: "category", data: data.rows.map(row => String(row[x] ?? "")) }, yAxis: { type: "value", scale: true }, series: [{ name: y, type: "line", showSymbol: false, connectNulls: false, data: data.rows.map(row => typeof row[y] === "number" && Number.isFinite(row[y]) ? row[y] as number : null) }] }} /><p className="r-note">已保存实验 · {data.rows.length} / {data.total} 条{data.total > data.rows.length ? "，当前只展示前 500 条，完整结果见实验页。" : ""}</p></>;
}
const Chart = defineComponent({ name: "ExperimentChart", description: "从关联实验读取真实表格绘图，不接受模型编造的数列；最多显示前500条。", props: z.object({ experimentId: z.string(), table: z.string(), x: z.string(), y: z.string(), title: z.string() }), component: ({ props }) => <SavedChart {...props} /> });
const Stack = defineComponent({ name: "ResearchStack", description: "研究回复组件容器。", props: z.object({ children: z.array(z.union([Text.ref, Citation.ref, Choice.ref, Plan.ref, Result.ref, Chart.ref, Parameter.ref, Apply.ref, Table.ref, Compare.ref])) }), component: ({ props, renderNode }) => <div className="r-openui-stack">{renderNode(props.children)}</div> });
export const researchUILibrary = createLibrary({ root: "ResearchStack", components: [Stack, Text, Citation, Choice, Plan, Result, Chart, Parameter, Apply, Table, Compare] });
export const researchUIPrompt = researchUILibrary.prompt({ additionalRules: ["只引用消息绑定的研报、项目和已保存实验。ResearchChoice只保存选择；PlanParameter编辑已有标量参数，只有用户点击ReproductionAction后才保存或运行。不要使用Query或Mutation。"] });

class UIErrorBoundary extends React.Component<{ children: React.ReactNode }, { failed: boolean }> {
  override state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  override render() { return this.state.failed ? <p role="alert">此交互内容无法显示，文字回复仍可阅读。</p> : this.props.children; }
}
export function ResearchOpenUI({ block, onState }: { block: ResearchUIBlock; onState: (state: JsonObject) => void }) {
  const [state,setState]=useState<JsonObject>(block.state??{}),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
  function persist(next:JsonObject){setState(next);onState(next);}
  async function apply(run:boolean){
    if(busy||!block.projectId||!block.reproductionId)return;
    const frozen=structuredClone({projectId:block.projectId,planId:block.reproductionId,state,revision:state.appliedRevision??block.reproductionRevision});
    setBusy(true);setMessage('');
    try {
      const plan=await request<ReproductionPlan>('reproductions.get',{projectId:frozen.projectId,planId:frozen.planId});
      if(typeof frozen.revision!=='number'||plan.revision!==frozen.revision)throw new Error('计划修订已变化或消息缺少修订号，请打开计划核对后重新生成交互方案。');
      const changes=object(frozen.state.parameters),known=new Set(plan.steps.map(step=>step.id));
      if(Object.keys(changes).some(id=>!known.has(id)))throw new Error('参数指向不存在的复现步骤。');
      const steps=plan.steps.map(step=>{const patch=object(changes[step.id]);for(const [key,value] of Object.entries(patch)){const previous=step.spec.parameters[key];if(!['string','number','boolean'].includes(typeof previous)||typeof previous!==typeof value)throw new Error(`参数 ${key} 与已保存计划类型不一致。`);}return {...step,spec:{...step.spec,parameters:{...step.spec.parameters,...patch}}};});
      const saved=await request<ReproductionPlan>('reproductions.save',{projectId:frozen.projectId,plan:{...plan,steps}});
      persist({...frozen.state,appliedRevision:saved.revision});
      if(run){const result=await request<ReproductionRun>('reproductions.run',{projectId:frozen.projectId,planId:saved.id,revision:saved.revision});setMessage(`已提交修订 ${saved.revision}：${result.message??result.status}`);}
      else setMessage(`已保存修订 ${saved.revision}，尚未执行。`);
    }catch(e){setMessage(`未完成：${errorText(e)}`);}finally{setBusy(false);}
  }
  const validation = useMemo(() => {
    try { const parsed = createParser(researchUILibrary.toJSONSchema()).parse(block.content);return parsed.meta.errors.length || parsed.meta.unresolved.length ? "交互内容不完整，请查看文字回复。" : ""; }
    catch { return "交互内容无法解析，请查看文字回复。"; }
  }, [block.content]);
  if (validation) return <p role="alert">{validation}</p>;
  return <UIErrorBoundary key={`${block.id}:${block.content}`}><BlockContext.Provider value={block}><ActionContext.Provider value={{state,busy,apply:run=>void apply(run),edit:(step,key,value)=>persist({...state,parameters:{...object(state.parameters),[step]:{...object(object(state.parameters)[step]),[key]:value}}})}}><Renderer response={block.content} library={researchUILibrary} initialState={block.state ?? {}} onStateUpdate={value => persist({...state,...value} as JsonObject)} publishObservability={false} toolProvider={null} />{message&&<p role="status">{message}</p>}</ActionContext.Provider></BlockContext.Provider></UIErrorBoundary>;
}
