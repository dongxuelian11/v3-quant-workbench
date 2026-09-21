import React,{useEffect,useRef,useState} from 'react';
import type {LocalAssistantAction,LocalAssistantApplied,LocalAssistantInterpretation,ScreenerConditionGroup,ScreenerPlan,WorkspacePanel} from '../../../../../packages/contracts/src/research';
import {errorText,request,useResearch} from './state';
import {useWorkspace} from './workspace';
import {ScreenerConditions} from './ScreenerConditions';
import {assistantDraft,replaceAssistantDraft} from './localAssistantDraft';
import type {LocalAssistantStatus} from './SettingsLocalAssistant';
import {stageLocalHandoff} from './localHandoff';
const fields=['symbol','name','industry','close','changeRatio','amount','volume','rawTurn','peTTM','pbMRQ'];
function withIds(group:ScreenerConditionGroup):ScreenerConditionGroup{return {...group,id:group.id||crypto.randomUUID(),children:group.children.map(item=>'children' in item?withIds(item):{...item,id:item.id||crypto.randomUUID()})};}
export function LocalCommand({text,onSearch,close}:{text:string;onSearch:(value:string)=>void;close:()=>void}){
 const w=useWorkspace(),s=useResearch();const [status,setStatus]=useState<LocalAssistantStatus|null>(null),[action,setAction]=useState<LocalAssistantAction|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState(''),[undo,setUndo]=useState<{id:string;before:ScreenerPlan;after:ScreenerPlan}|null>(null);
 const lock=useRef(false),generation=useRef(0),operation=useRef(crypto.randomUUID()),origin=useRef<{id?:string;draft?:ScreenerPlan}>({});
 useEffect(()=>{let alive=true;void request<LocalAssistantStatus>('localAssistant.status').then(value=>{if(alive)setStatus(value);}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;generation.current++;};},[]);
 useEffect(()=>{generation.current++;setAction(null);setMessage('');operation.current=crypto.randomUUID();},[text]);
 async function interpret(){if(lock.current)return;lock.current=true;setBusy(true);setError('');setAction(null);setUndo(null);const serial=++generation.current;origin.current={id:w.active?.kind==='screener'?w.active.id:undefined,draft:assistantDraft(w.active?.id)};try{const result=await request<LocalAssistantInterpretation>('localAssistant.interpret',{text});if(serial!==generation.current)return;setAction(result.action?{...result.action,conditions:result.action.conditions?withIds(result.action.conditions):undefined}:null);setMessage(result.message??result.action?.question??result.action?.message??'未取得明确指令');operation.current=crypto.randomUUID();if(result.status==='proposed'&&result.action&&['navigation','filter_patch','run','search'].includes(result.action.kind))await apply(result.action,true);}catch(e){if(serial===generation.current)setError(errorText(e));}finally{lock.current=false;setBusy(false);}}
 function edit(next:LocalAssistantAction){setAction(next);operation.current=crypto.randomUUID();}
 async function apply(proposed=action,internal=false){const action=proposed;if((lock.current&&!internal)||!action)return;lock.current=true;setBusy(true);setError('');try{
  if(action.kind==='filter_patch'&&(!origin.current.id||!origin.current.draft))throw new Error('请先打开要修改的选股方案，再从 Ctrl+K 输入条件。');
  if(action.kind==='filter_patch'&&JSON.stringify(assistantDraft(origin.current.id))!==JSON.stringify(origin.current.draft))throw new Error('当前草稿已变化，请重新解释。');
  const result=await request<LocalAssistantApplied>('localAssistant.apply',{action,draft:action.kind==='filter_patch'?origin.current.draft:undefined,operationId:operation.current});
  setMessage(result.message??'');
  if(result.kind==='draft'&&result.draft&&origin.current.id&&origin.current.draft){replaceAssistantDraft(origin.current.id,origin.current.draft,result.draft);setUndo({id:origin.current.id,before:origin.current.draft,after:result.draft});setAction(null);}
  if(result.kind==='jobs'){await s.refresh();setAction(null);s.setNotice(result.message??'已提交任务');}
  if(result.kind==='navigation'){
   const pages:Record<string,{kind:WorkspacePanel['kind'];title:string}>={overview:{kind:'market',title:'市场概况'},screeners:{kind:'screener',title:'筛选与自选'},daily:{kind:'selection',title:'每日选股'},positions:{kind:'positions',title:'实际持仓'},research:{kind:'today',title:'研究首页'}};
   const page=pages[result.screen??''];if(page){w.open({...page,...(result.screen==='research'&&result.objectIds?.[0]?{projectId:result.objectIds[0]}:{})});close();}
  }
  if(result.kind==='search'){onSearch(result.query??'');setAction(null);setMessage('已填写搜索内容；可打开对应工具继续查找。');}
  if(result.kind==='handoff'){stageLocalHandoff(text,w.active?.projectId);await w.savePreferences({aiVisible:true,rightPanel:'ai'});s.setNotice('已放入研究助手输入框，请核对后发送。');close();}
 }catch(e){setError(errorText(e));}finally{lock.current=false;setBusy(false);}}
 return <section className="r-local-command"><div className="r-toolbar"><button disabled={busy||!text.trim()||!status?.enabled} onClick={()=>void interpret()}>{busy?'正在处理…':'执行本地指令'}</button><small>{status?.enabled?`${status.model} · 本地`:'本地助手未启用，工具搜索仍可使用'}</small></div>{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}{action&&<><p className="r-note">请补充或核对指令。{action.kind==='run'?'将运行已保存方案；请核对对象。':''}</p><p>{action.message}</p>{action.objectIds.length>0&&<p>对象：{action.objectIds.join('、')}</p>}{action.conditions&&<ScreenerConditions value={action.conditions} fields={fields} onChange={conditions=>edit({...action,conditions})}/ >}{action.kind==='search'&&<label>搜索内容<input aria-label="本地助手搜索内容" value={action.query??''} onChange={event=>edit({...action,query:event.target.value})}/></label>}{action.kind==='clarify'?<p>请修改上方指令后重新解释。</p>:<button className="r-primary" disabled={busy} onClick={()=>void apply()}>{action.kind==='run'?'运行上述已保存方案':action.kind==='filter_patch'?'应用到当前草稿':action.kind==='handoff'?'转入研究助手草稿':'应用此操作'}</button>}</>}{undo&&<button disabled={busy} onClick={()=>{try{replaceAssistantDraft(undo.id,undo.after,undo.before);setUndo(null);setMessage('已撤销条件修改。');}catch(e){setError(errorText(e));}}}>撤销本次条件修改</button>}</section>;
}
