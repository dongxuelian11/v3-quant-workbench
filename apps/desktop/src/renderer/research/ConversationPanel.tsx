import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { JobEvent, JobSpec, JsonObject, ResearchConversation, ResearchObjectRef, ResearchCandidate, ResearchUIBlock, ReportCitation } from "../../../../../packages/contracts/src/research";
import { request, errorText, useResearch } from "./state";
import { useWorkspace } from "./workspace";
import { Field, requestText } from "./ui";
import { RDStagePanel, RDStageEvent } from "./RDStagePanel";
import { LegacyConversations } from "./LegacyConversations";
import { ProjectSummaryPanel } from "./ProjectSummaryPanel";
import { ResearchOpenUI } from "./ResearchOpenUI";
import { object } from "./configuration";
interface Message { reportCitations?: ReportCitation[]; uiBlocks?: ResearchUIBlock[]; role: "user" | "assistant"; content: string; experimentRefs?: ResearchObjectRef[]; experimentIds?: string[]; }
interface Proposal { candidateId?:string; title: string; description: string; spec: JobSpec; }
interface Answer { summaryWarning?: string; message: string; phase: string; proposals: Proposal[]; experimentIds: string[]; }
interface Settings { ai: { baseUrl: string; model: string; apiKey: string; temperature: number }; defaultDataSource: string; }
import {takeLocalHandoff} from './localHandoff';
interface Session { conversation: ResearchConversation; draft: string; scrollTop: number; atBottom: boolean; busy: boolean; }
function draftConversation(projectId?: string): ResearchConversation {
 return { id: `draft:${crypto.randomUUID()}`, name: "新对话", context: projectId ? [{kind:"today",projectId,title:"当前研究项目"}] : [], state: { messages: [], mode: "assist" }, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
}
export function ConversationPanel() {
 const w=useWorkspace();const sessions=useRef(new Map<string,Session>());const projectId=w.active?.projectId;const key=projectId??"global";
 if(!sessions.current.has(key))sessions.current.set(key,{conversation:draftConversation(projectId),draft:"",scrollTop:0,atBottom:true,busy:false});
 return <>{[...sessions.current].map(([sessionKey, session])=><div key={sessionKey} hidden={sessionKey!==key} style={{height:"100%",minHeight:0}}><ProjectConversation active={sessionKey===key} projectId={sessionKey==="global"?undefined:sessionKey} session={session}/></div>)}</>;
}
function ProjectConversation({projectId,session,active}:{active:boolean;projectId?:string;session:Session}) {
 const activeRef=useRef(active);activeRef.current=active;
 const s=useResearch(); const w=useWorkspace(); const [list,setList]=useState<ResearchConversation[]>([]);
 const [conversation,renderConversation]=useState<ResearchConversation|null>(session.conversation);const current=useRef(conversation);current.current=conversation;
 const setConversation=(value:ResearchConversation|null)=>{const next=value??draftConversation(projectId);session.conversation=next;current.current=next;renderConversation(next);};
 const [search,setSearch]=useState("");const [input,renderInput]=useState(session.draft);const setInput=(value:string)=>{session.draft=value;renderInput(value);};
 const [sending,setSending]=useState(false);const syncPending=useRef<Promise<void>|null>(null);
 const [busy,renderBusy]=useState(session.busy);const setBusy=(value:boolean)=>{session.busy=value;renderBusy(value);};
 const [serviceStatus,setServiceStatus]=useState("正在读取服务设置");
 const log=useRef<HTMLDivElement>(null);const bottom=useRef(session.atBottom);const inputRef=useRef(input);inputRef.current=input;
 useEffect(()=>{const receive=()=>{if(!activeRef.current)return;const text=takeLocalHandoff(projectId);if(text){const next=inputRef.current?`${inputRef.current}\n\n${text}`:text;inputRef.current=next;setInput(next);}};receive();window.addEventListener('v3-local-handoff',receive);return()=>window.removeEventListener('v3-local-handoff',receive);},[active,projectId]);
 const [summaryWarning,setSummaryWarning]=useState("");const [chatError,setChatError]=useState("");const [summaryVersion,setSummaryVersion]=useState(0);
 const isDraft=!!conversation?.id.startsWith("draft:");
 function remember(){session.draft=inputRef.current;session.scrollTop=log.current?.scrollTop??0;session.atBottom=bottom.current;}
 useLayoutEffect(()=>{bottom.current=session.atBottom;if(log.current)log.current.scrollTop=session.atBottom?log.current.scrollHeight:session.scrollTop;return()=>remember();},[]);
 const configurationStatus = (value: Settings) => !value.ai.baseUrl?.trim() || !value.ai.model?.trim() ? "未配置服务" : !/localhost|127\.0\.0\.1|\[::1\]/.test(value.ai.baseUrl) && !value.ai.apiKey?.trim() ? "未配置 API 密钥" : "已配置 · 尚未验证";
 const state=object(conversation?.state);const messages=Array.isArray(state.messages)?state.messages as unknown as Message[]:[];const proposals=Array.isArray(state.proposals)?state.proposals as unknown as Proposal[]:[];const mode=String(state.mode??"assist");const stageIds=Array.isArray(state.stageJobIds)?state.stageJobIds.filter((x):x is string=>typeof x==="string"):[];const storedEvents=Array.isArray(state.stageEvents)?state.stageEvents as unknown as JobEvent[]:[];const events=[...s.jobs,...storedEvents];const terminal=stageIds.length>0&&stageIds.every(id=>events.some(j=>j.id===id&&["completed","failed","interrupted","cancelled"].includes(j.status)));
 const execution=object(state.execution);const modelBudget=object(execution.modelBudget);const executionActive=(value:JsonObject)=>typeof value.id==='string'&&!['completed','failed','cancelled','interrupted','paused'].includes(String(value.status));
 const currentRefs:ResearchObjectRef[]=active&&w.active&&w.active.projectId===projectId?(()=>{const {id,experimentRefs,...ref}=w.active;return ref.kind==='compare'&&experimentRefs?.length?experimentRefs:[ref];})():[];
 async function syncExecution(){
  if(syncPending.current)return syncPending.current;
  const id=current.current?.id;if(!id||id.startsWith('draft:'))return;
  const promise=(async()=>{const next=await request<ResearchConversation>('ai.conversations.get',{conversationId:id});if(current.current?.id!==id)return;const previous=object(current.current.state.execution),value=object(next.state.execution);setConversation(next);setBusy(executionActive(value));if(previous.id&&executionActive(previous)&&!executionActive(value)){setSummaryVersion(v=>v+1);setServiceStatus(value.status==='completed'?'最近执行完成':value.status==='cancelled'?'执行已停止':'执行已结束');}const warning=object(next.state).summaryWarning;if(typeof warning==='string')setSummaryWarning(warning);})().finally(()=>{syncPending.current=null;});
  syncPending.current=promise;return promise;
 }
 useEffect(()=>window.v3Research?.workspace?.onChanged(event=>{if(event.method==='ai.execution'&&event.params?.conversationId===current.current?.id)void syncExecution().catch(error=>setChatError(errorText(error)));}),[]);
 useEffect(()=>{if(!executionActive(execution))return;const timer=setInterval(()=>void syncExecution().catch(error=>setChatError(errorText(error))),2000);return()=>clearInterval(timer);},[execution.id,execution.status]);
 async function stopExecution(){const id=current.current?.id,value=object(current.current?.state.execution);if(!id||!executionActive(value))return;try{await request('ai.chat.cancel',{conversationId:id,executionId:value.id});await syncExecution();}catch(error){setChatError(errorText(error));}}
 const referenceName = (ref: ResearchObjectRef) => ref.title || (ref.experimentId ? s.experiments.find(e => e.id === ref.experimentId && e.projectId === ref.projectId)?.name : undefined) || (ref.strategyId ? w.strategies.find(st => st.id === ref.strategyId && st.projectId === ref.projectId)?.name : undefined) || ref.symbol || ({ reports: "研报库", report: "研报原文", reproduction: "研报复现", quote: "行情", today: "项目研究", strategy: "策略研究", factors: "因子研究", model: "模型训练", experiment: "实验结果", compare: "实验比较", market: "市场概况", screener: "筛选与自选", stock: "个股全景", selection: "每日选股", positions: "实际持仓", data: "数据中心", universe: "股票池", candidate: "研究候选", simulation: "模拟账户" }[ref.kind]);
 async function refreshList(){const items=await request<ResearchConversation[]>("ai.conversations.list",{projectId:projectId??null});const scoped=items.filter(c=>c.projectId===(projectId??null));setList(scoped);return scoped;}
 const contextSaves=useRef(Promise.resolve());
 useEffect(()=>{const append=(event:Event)=>{
  const detail=(event as CustomEvent<{projectId?:string;text:string;ref?:ResearchObjectRef}>).detail;
  if((detail.projectId??"")!==(projectId??"")||!detail.text)return;
  if(detail.ref&&(detail.ref.projectId??"")!==(projectId??""))return;
  const value=[inputRef.current,detail.text].filter(Boolean).join("\n\n");setInput(value);inputRef.current=value;remember();
  const origin=current.current,ref=detail.ref;if(!origin||!ref)return;
  const exists=origin.context.some(item=>item.kind===ref.kind&&item.projectId===ref.projectId&&item.reportId===ref.reportId&&item.reproductionId===ref.reproductionId&&item.page===ref.page);
  if(exists)return;
  const context=[...origin.context,structuredClone(ref)];setConversation({...origin,context});
  if(origin.id.startsWith('draft:'))return;
  const id=origin.id;
  contextSaves.current=contextSaves.current.catch(()=>undefined).then(async()=>{
   try{await request('ai.conversations.save',{conversation:{id,context}});}
   catch(error){if(current.current?.id===id)setChatError(`研报引用尚未保存：${errorText(error)}`);}
  });
 };window.addEventListener("v3-ai-draft-append",append);return()=>window.removeEventListener("v3-ai-draft-append",append);},[projectId]);
 useEffect(()=>{const refresh=()=>{void refreshList().catch(error=>setChatError(errorText(error)));};window.addEventListener("v3-conversation-list-refresh",refresh);return()=>window.removeEventListener("v3-conversation-list-refresh",refresh);},[]);
 async function select(id:string){if(busy)return;remember();const next=await request<ResearchConversation>("ai.conversations.get",{conversationId:id});setConversation(next);setInput("");inputRef.current="";bottom.current=true;session.atBottom=true;if(log.current)log.current.scrollTop=log.current.scrollHeight;await w.savePreferences({activeConversationId:id});}
 useEffect(()=>{void s.act(async()=>{const config=await request<Settings>("settings.get");setServiceStatus(configurationStatus(config));await refreshList();});},[]);
 useEffect(()=>{if(active){void w.savePreferences({activeConversationId:session.conversation.id.startsWith("draft:")?"":session.conversation.id});bottom.current=session.atBottom;requestAnimationFrame(()=>{if(log.current)log.current.scrollTop=session.atBottom?log.current.scrollHeight:session.scrollTop;});}},[active]);
 useEffect(()=>{const id=w.preferences.activeConversationId;if(active&&id&&current.current?.id!==id&&!busy)void s.act(async()=>{const items=await refreshList();if(items.some(c=>c.id===id))await select(id);});},[w.preferences.activeConversationId,busy]);
 useEffect(()=>{const refresh=()=>{void request<Settings>("settings.get").then(value=>setServiceStatus(configurationStatus(value))).catch(()=>setServiceStatus("设置读取失败"));};window.addEventListener("v3-settings-saved",refresh);return()=>window.removeEventListener("v3-settings-saved",refresh);},[]);
 async function save(patch:Partial<ResearchConversation>){if(!current.current)return;if(current.current.id.startsWith("draft:")){setConversation({...current.current,...patch});return;}const next=await request<ResearchConversation>("ai.conversations.save",{conversation:{id:current.current.id,...patch}});setConversation(next);current.current=next;await refreshList();}
 const uiSaves=useRef(new Map<string,Promise<void>>());
 const uiStates=useRef(new Map<string,string>());
 function saveUIState(block:ResearchUIBlock,state:JsonObject){
  const id=current.current?.id;if(!id||id.startsWith("draft:"))return;
  const key=`${id}:${block.id}`,serialized=JSON.stringify(state);
  if(serialized===(uiStates.current.get(key)??JSON.stringify(block.state??{})))return;
  uiStates.current.set(key,serialized);
  const pending=(uiSaves.current.get(key)??Promise.resolve()).catch(()=>undefined).then(async()=>{
   try{const next=await request<ResearchUIBlock>("ai.conversations.uiState",{conversationId:id,blockId:block.id,state});
    if(current.current?.id===id&&uiStates.current.get(key)===serialized){const latest=object(current.current.state);const rows=(Array.isArray(latest.messages)?latest.messages:[]) as unknown as Message[];setConversation({...current.current,state:{...latest,messages:rows.map(message=>({...message,...(message.uiBlocks?{uiBlocks:message.uiBlocks.map(value=>value.id===block.id?next:value)}:{})})) as unknown as JsonObject[]}});}
   }catch(error){uiStates.current.delete(key);if(current.current?.id===id)setChatError(`表单状态未保存：${errorText(error)}`);}
  });uiSaves.current.set(key,pending);void pending.finally(()=>{if(uiSaves.current.get(key)===pending)uiSaves.current.delete(key);});
 }
 async function create(){if(busy)return;remember();setConversation(draftConversation(projectId));setInput("");inputRef.current="";bottom.current=true;await w.savePreferences({activeConversationId:""});}
 async function send(text=input, preserveDraft=false){
  if(!conversation||sending||!text.trim())return;
  const origin=conversation, running=object(origin.state.execution);
  if(busy&&!executionActive(running))return;
  const frozenContext=structuredClone(preserveDraft&&Array.isArray(running.context)?running.context:[...origin.context,...currentRefs.filter(ref=>!origin.context.some(existing=>JSON.stringify(existing)===JSON.stringify(ref)))]);
  const frozenHistory=structuredClone(messages), requestId=crypto.randomUUID();
  setSending(true);setChatError('');if(!preserveDraft){setInput('');inputRef.current='';}bottom.current=true;remember();
  let id=origin.id;
  try{
   if(executionActive(running)){await request('ai.chat.message',{conversationId:id,executionId:running.id,messageId:requestId,message:text});}
   else{
    setBusy(true);setServiceStatus('正在提交执行…');
    if(id.startsWith('draft:')){const created=await request<ResearchConversation>('ai.conversations.create',{projectId:projectId??null,name:origin.name==='新对话'?text.slice(0,28):origin.name,context:origin.context});id=created.id;setConversation(created);if(activeRef.current)await w.savePreferences({activeConversationId:id});}
    setConversation({...session.conversation,state:{...object(session.conversation.state),messages:[...frozenHistory,{role:'user',content:text}] as unknown as JsonObject[]}});
    await request('ai.chat.start',{conversationId:id,requestId,message:text,mode,context:frozenContext});
   }
   await syncExecution();await refreshList();
  }catch(error){
   // A lost acknowledgement may still have started the execution; read before offering a retry.
   let accepted=false;
   try{if(!id.startsWith('draft:')){await syncExecution();const value=object(current.current?.state.execution);accepted=value.requestId===requestId||(Array.isArray(value.pendingMessages)&&value.pendingMessages.some(item=>object(item).id===requestId))||(Array.isArray(value.consumedMessageIds)&&value.consumedMessageIds.includes(requestId));}}catch{}
   if(!accepted){if(!preserveDraft){const restored=inputRef.current.trim()?`${text}\n\n${inputRef.current}`:text;setInput(restored);inputRef.current=restored;remember();}setChatError(errorText(error));}
  }finally{setSending(false);setBusy(executionActive(object(current.current?.state.execution)));}
 }
 useLayoutEffect(()=>{if(activeRef.current&&bottom.current&&log.current)log.current.scrollTop=log.current.scrollHeight;},[messages.length,busy,conversation?.updatedAt]);
 useEffect(()=>window.v3Research?.onEvent(event=>{const c=current.current;if(!c)return;const value=object(c.state);const ids=Array.isArray(value.stageJobIds)?value.stageJobIds:[];if(!ids.includes(event.id))return;const previous=Array.isArray(value.stageEvents)?value.stageEvents as unknown as JobEvent[]:[];const next={...value,stageEvents:[event,...previous.filter(e=>e.id!==event.id)] as unknown as JsonObject[]};setConversation({...c,state:next});current.current={...c,state:next};if(["completed","failed","cancelled","interrupted"].includes(event.status))void s.act(()=>save({state:next}));}),[]);
 useEffect(()=>{const listener=(event:Event)=>{const id=(event as CustomEvent<string>).detail;if(current.current?.id===id)void s.act(async()=>{const next=await request<ResearchConversation>("ai.conversations.get",{conversationId:id});setConversation(next);});};window.addEventListener("v3-conversation-refresh",listener);return()=>window.removeEventListener("v3-conversation-refresh",listener);},[]);
 async function apply(proposal:Proposal){
  const projectId=proposal.spec.projectId,strategyId=proposal.spec.strategyId;
  if(!projectId||!strategyId)throw new Error("请先明确方案关联的研究项目与策略。");
  let candidateId=proposal.candidateId??proposal.spec.candidateId;
  if(!candidateId){
   const kind=proposal.spec.kind==='factor.analyze'?'factor':proposal.spec.kind==='model.train'?'model':proposal.spec.kind==='backtest.run'?'strategy':null;
   if(!kind)throw new Error("此任务暂不支持候选编辑。");
   const candidate=await request<ResearchCandidate>('candidates.save',{projectId,candidate:{strategyId,kind,name:proposal.title,description:proposal.description,changeSummary:'由会话方案创建；请核对与草稿的差异。',sourceConversationId:conversation?.id,spec:proposal.spec}});
   candidateId=candidate.id;
   const updated=proposals.map(item=>item===proposal?{...item,candidateId,spec:{...item.spec,candidateId}}:item);
   await save({state:{...object(current.current?.state),proposals:updated as unknown as JsonObject[]}});
  }
  w.open({kind:'candidate',title:proposal.title,projectId,strategyId,candidateId});
 }
 async function stageSubmitted(job:JobEvent,id=conversation?.id){if(!id)return;const origin=current.current?.id===id?current.current:await request<ResearchConversation>("ai.conversations.get",{conversationId:id});const value=object(origin.state);const ids=Array.isArray(value.stageJobIds)?value.stageJobIds:[];const previous=Array.isArray(value.stageEvents)?value.stageEvents:[];const next=await request<ResearchConversation>("ai.conversations.save",{conversation:{id,state:{...value,mode:"research",stageJobIds:[...new Set([...ids,job.id])],stageEvents:[job,...previous]}}});if(current.current?.id===id){setConversation(next);current.current=next;}await refreshList();s.setNotice("原生研究阶段已提交，结果会保留在原会话");}
 async function run(){if(!conversation||busy)return;setBusy(true);const submitted:string[]=[];await s.act(async()=>{for(let i=0;i<proposals.length;i++){const p=proposals[i];const event=await request<JobEvent>("jobs.submit",{spec:p.spec});submitted.push(event.id);await save({state:{...object(current.current?.state),proposals:proposals.slice(i+1) as unknown as JsonObject[],stageJobIds:[...submitted]}});}s.setNotice("当前研究阶段已提交；完成后可携结果继续讨论");});setBusy(false);}
 return <aside className="r-ai"><div className="r-conversation-heading"><details className="r-conversation-menu"><summary title={conversation?.name??"选择研究会话"}><span className="r-conversation-title">{conversation?.name??"选择研究会话"}</span><span aria-hidden="true">⌄</span></summary><div className="r-conversation-menu-content"><input aria-label="搜索研究会话" placeholder="搜索会话…" value={search} onChange={e=>setSearch(e.target.value)}/><select aria-label="当前研究会话" disabled={busy} value={conversation?.id??""} onChange={e=>{const menu=e.currentTarget.closest('details');if(menu)menu.open=false;void s.act(()=>select(e.target.value));}}><option value={isDraft?conversation?.id:""} disabled>新对话 · 尚未发送</option>{list.filter(c=>c.name.toLowerCase().includes(search.toLowerCase())).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select>{conversation&&<button disabled={busy} aria-label="重命名会话" onClick={()=>void s.act(async()=>{const name=await requestText("研究会话名称",conversation.name);if(name?.trim())await save({name:name.trim()});})}>重命名会话</button>}{conversation&&!isDraft&&<button className="r-danger" disabled={busy} onClick={()=>void s.act(async()=>{if(!window.confirm(`删除会话“${conversation.name}”？`))return;await request("ai.conversations.delete",{conversationId:conversation.id});setConversation(null);await refreshList();await w.savePreferences({activeConversationId:""});})}>删除会话</button>}<LegacyConversations/></div></details><button disabled={busy} aria-label="新建研究会话" title="新建研究会话" onClick={()=>void s.act(create)}>＋</button></div>
 <>
 {projectId&&<ProjectSummaryPanel projectId={projectId} refreshVersion={summaryVersion} onOpenConversation={select} conversationBusy={busy}/>}
 {currentRefs.length>0&&<div className="r-current-context"><span>当前对象</span>{currentRefs.map((ref,i)=><strong key={i}>{referenceName(ref)}{ref.date?` · ${ref.date}`:""}</strong>)}</div>}{conversation&&<details className="r-conversation-context" open={!messages.length || undefined}><summary>已固定 {conversation.context.length} 个对象 · {mode==="research"?"阶段研究":mode==="assist"?"辅助配置":"问答"}</summary><div className="r-conversation-refs"><div className="r-toolbar"><strong>明确关联对象</strong><button disabled={!w.active||busy} onClick={()=>void s.act(async()=>{if(!w.active)return;const {id:panelId,experimentRefs,...snapshot}=w.active;const ref:ResearchObjectRef={...snapshot};const refs = w.active.kind === "compare" && w.active.experimentRefs?.length ? w.active.experimentRefs : [ref]; const unique = [...conversation.context]; for (const item of refs) if (!unique.some(x => x.kind === item.kind && x.instrument?.kind === item.instrument?.kind && x.instrument?.symbol === item.instrument?.symbol && x.projectId === item.projectId && x.strategyId === item.strategyId && x.experimentId === item.experimentId && x.symbol === item.symbol && x.date === item.date && x.factorId === item.factorId && x.tradeId === item.tradeId && x.reportId === item.reportId && x.reproductionId === item.reproductionId && x.page === item.page)) unique.push(item); await save({context:unique});})}>固定当前对象</button></div>{conversation.context.length?conversation.context.map((ref,i)=><div className="r-ref" key={i}><button onClick={()=>w.open({...ref,title:referenceName(ref)})}>{referenceName(ref)}</button><button aria-label="解除关联" disabled={busy} onClick={()=>void s.act(()=>save({context:conversation.context.filter((_,j)=>j!==i)}))}>×</button></div>):<p className="r-note">尚未关联对象。切换标签不会改变这个会话。</p>}</div><nav className="r-subtabs">{[["ask","问答"],["assist","辅助配置"],["research","阶段研究"]].map(([id,title])=><button disabled={busy} key={id} className={mode===id?"active":""} onClick={()=>void s.act(()=>save({state:{...state,mode:id}}))}>{title}</button>)}</nav></details>}
 {conversation&&!isDraft&&<RDStagePanel key={conversation.id} conversation={conversation} blocked={busy||stageIds.length>0&&!terminal} onSubmitted={stageSubmitted}/>}
 {summaryWarning&&<p role="status" className="r-note">{summaryWarning}</p>}
 {chatError&&<p role="alert" className="r-note">{chatError}</p>}
 <div ref={log} className="r-chat-log" aria-live="polite" onScroll={()=>{const node=log.current;if(activeRef.current&&node){bottom.current=node.scrollHeight-node.scrollTop-node.clientHeight<48;remember();}}}>{!conversation?<p className="r-note">描述问题即可开始新对话，首次发送时保存。</p>:!messages.length?(!input.trim()&&!busy&&!proposals.length&&!stageIds.length?<p className="r-note">围绕已关联对象讨论方案，运行真实实验后再解释结果。</p>:null):messages.map((m,i)=><div className={`r-message ${m.role}`} key={i}><small>{m.role==="user"?"你":"研究助手"}</small><div className="r-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>{m.reportCitations?.map((citation,index)=><button key={`citation:${index}`} title={citation.excerpt} onClick={()=>w.open({kind:"report",title:"核对研报原文",projectId,reportId:citation.reportId,page:citation.page})}>原文第 {citation.page} 页</button>)}{m.uiBlocks?.map(block=><ResearchOpenUI key={block.id} block={block} onState={state=>saveUIState(block,state)}/>)}{(m.experimentRefs ?? m.experimentIds?.flatMap(id => { const matches = s.experiments.filter(e => e.id === id && conversation.context.some(ref => ref.projectId === e.projectId)); return matches.length === 1 ? [{ kind: "experiment" as const, projectId: matches[0].projectId, experimentId: id, title: matches[0].name }] : []; }) ?? []).map((ref,index) => <button key={index} onClick={() => w.open({ ...ref, title: ref.title ?? s.experiments.find(e => e.id === ref.experimentId && e.projectId === ref.projectId)?.name ?? "实验结果" })}>{referenceName(ref)} →</button>)}</div>)}{execution.id&&<section className="r-execution-status">{modelBudget.scope==='execution'&&typeof modelBudget.used==='number'&&typeof modelBudget.limit==='number'&&<p className="r-note">本次执行模型请求 {modelBudget.used} / {modelBudget.limit}</p>}<div className="r-toolbar"><strong>{({queued:'排队中',running:'执行中',paused:'已暂停',completed:'阶段完成',failed:'执行失败',cancelled:'已停止',interrupted:'已中断'} as Record<string,string>)[String(execution.status)]??String(execution.status??'')}</strong>{executionActive(execution)&&<button disabled={execution.cancelRequested===true} onClick={()=>void stopExecution()}>{execution.cancelRequested?'正在停止…':'停止执行'}</button>}</div>{typeof execution.message==='string'&&<p>{execution.message}</p>}{Array.isArray(execution.steps)&&<ol>{execution.steps.map((item,i)=>{const step=object(item);return <li key={String(step.id??i)}><strong>{String(step.summary??step.tool??'步骤')}</strong> · {({running:'进行中',completed:'完成',failed:'失败',cancelled:'已取消'} as Record<string,string>)[String(step.status)]??String(step.status??'')}{typeof step.error==='string'&&<p role="alert">{step.error}</p>}{typeof step.experimentId==='string'&&<button onClick={()=>w.open({kind:'experiment',title:'步骤实验',projectId,experimentId:String(step.experimentId)})}>查看实验</button>}</li>;})}</ol>}{Array.isArray(execution.pendingMessages)&&execution.pendingMessages.map(item=>{const message=object(item);return <p className="r-note" key={String(message.id)}>{message.requiresConfirmation===true?'已停止，待你决定是否继续':'尚未处理'}：{String(message.message??'')}</p>;})}{!executionActive(execution)&&Array.isArray(execution.pendingMessages)&&execution.pendingMessages.length>0&&<button disabled={sending||busy} onClick={()=>void send('继续处理未完成补充',true)}>继续处理未完成补充</button>}</section>}{sending&&<p role="status">正在提交…</p>}{proposals.map((p,i)=><section className="r-proposal" key={i}><h3>{p.title}</h3><p>{p.description}</p><details><summary>{p.spec.kind==="rdagent.run"?"查看阶段参数":"查看运行参数"}</summary><pre>{JSON.stringify(p.spec,null,2)}</pre></details>{p.spec.kind!=="rdagent.run"&&<button disabled={busy} onClick={()=>void s.act(()=>apply(p))}>查看 / 编辑独立候选</button>}</section>)}{(mode==="research"||proposals.some(p=>p.spec.kind==="rdagent.run"))&&proposals.length>0&&<button className="r-primary" disabled={busy||stageIds.length>0&&!terminal} onClick={()=>void run()}>运行这一阶段（{proposals.length} 项）</button>}{stageIds.map(id=>{const job=events.find(j=>j.id===id);return <div key={id} className="r-note">{job?.name??id} · {job?.message??"等待任务状态"}{job?.experimentId&&<button onClick={()=>w.open({kind:'experiment',title:job.name||'阶段研究结果',projectId:job.projectId,strategyId:job.strategyId,experimentId:job.experimentId})}>查看阶段结果 →</button>}{job?.kind==="rdagent.run"&&<RDStageEvent job={job} blocked={busy||stageIds.length>0&&!terminal} onSubmitted={stageSubmitted}/>}</div>;})}{terminal&&<button onClick={()=>void send(`本阶段任务已结束，请读取实际结果并讨论下一步，先不要执行：${stageIds.join(", ")}`)}>携阶段结果继续讨论</button>}</div><form className="r-chat-compose" onSubmit={e=>{e.preventDefault();void send();}}><textarea aria-label="研究问题" placeholder={executionActive(execution)?"补充要求，将交给当前执行…":"描述问题，先讨论再运行…"} disabled={!conversation} value={input} onChange={e=>{setInput(e.target.value);inputRef.current=e.target.value;remember();}}/><button className="r-send" disabled={!conversation||sending||(busy&&!executionActive(execution))||!input.trim()} aria-label={executionActive(execution)?"发送补充":"发送"}>↑</button></form><div className="r-toolbar r-ai-footer"><button onClick={()=>window.dispatchEvent(new CustomEvent("v3-open-settings",{detail:{section:"ai"}}))}>服务设置</button><span role="status">{serviceStatus}</span></div></>
 </aside>;
}
