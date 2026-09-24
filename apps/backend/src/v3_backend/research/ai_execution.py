"""Cancellable model turns stored in their existing conversation, using the Jobs queue."""
import asyncio
import json
from copy import deepcopy
from pathlib import Path
from threading import Thread, RLock
from .storage import identifier, now
from . import ai
from .ai_budget import model_budget, budget_failure, ensure_budget, reserve, read_budget


class CompletedStepRepeated(Exception):
    def __init__(self,job):self.job=job


class RepairStepPaused(Exception):
    def __init__(self,job,repair):self.job=job;self.repair=repair


def temporary_failure(exc):
    if budget_failure(exc):return False
    code=getattr(exc,'status_code',None)
    return (isinstance(code,int) and (code in {408,429} or 500<=code<600)) or isinstance(exc,(ConnectionError,TimeoutError)) or type(exc).__name__ in {'APIConnectionError','APITimeoutError','ConnectError','ReadTimeout','WriteTimeout','PoolTimeout','ReadError','WriteError','RemoteProtocolError'}


class Executions:
    def __init__(self,service,emit):
        self.service=service;self.emit=emit;self.lock=RLock();self.futures={};self.started=set()
        self.loop=asyncio.new_event_loop()
        self.thread=Thread(target=self.loop.run_forever,daemon=True);self.thread.start()
        for conversation in service.store.list('conversation'):
            execution=conversation.get('state',{}).get('execution',{})
            if execution.get('status')=='running':
                self.mutate(conversation['id'],execution['id'],lambda state,value:value.update(status='paused',message='服务已重启；保留已完成任务，请明确继续'))

    def mutate(self,cid,eid,operation):
        with self.lock,self.service.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT body FROM records WHERE kind='conversation' AND id=?",(cid,)).fetchone()
            if row is None:raise ValueError('会话不存在')
            conversation=json.loads(row[0]);state=conversation.setdefault('state',{})
            execution=state.get('execution',{})
            if eid and execution.get('id')!=eid:raise ValueError('执行不属于此会话的当前请求')
            operation(state,execution)
            execution=state.get('execution',{})
            if execution:
                execution['updatedAt']=now()
                state.setdefault('executionRequests',{})[execution['requestId']]=deepcopy(execution)
            conversation['updatedAt']=now()
            db.execute("UPDATE records SET body=? WHERE kind='conversation' AND id=?",(json.dumps(conversation,ensure_ascii=False,allow_nan=False),cid))
        if execution:self.emit({'kind':'ai.execution','id':execution['id'],'conversationId':cid,'projectId':execution.get('projectId'),'status':execution['status'],'message':execution.get('message')})
        return deepcopy(execution)

    def status(self,params):
        from .workbench import get_conversation
        state=get_conversation(self.service.store,params['conversationId']).get('state',{})
        execution=state.get('execution')
        if params.get('executionId') and (not execution or execution['id']!=params['executionId']):
            execution=next((v for v in state.get('executionRequests',{}).values() if v['id']==params['executionId']),None)
        if not execution:raise ValueError('会话没有此执行记录')
        return deepcopy(execution)

    def start(self,params):
        with self.lock:return self._start(params)

    def _start(self,params):
        from .workbench import get_conversation
        cid=params['conversationId'];request=params.get('requestId');message=str(params.get('message','')).strip()
        if not request or not message:raise ValueError('请求ID与消息不能为空')
        conversation=get_conversation(self.service.store,cid)
        if 'projectId' not in conversation:raise ValueError('请先明确旧会话所属项目或全局范围')
        refs=deepcopy(params.get('context',conversation.get('context',[])))
        if not isinstance(refs,list) or any(not isinstance(ref,dict) or not ref.get('kind') for ref in refs):raise ValueError('引用格式无效')
        pid=conversation['projectId']
        if pid and any(ref.get('projectId') not in (None,pid) for ref in refs):raise ValueError('项目会话不能引用其他项目')
        mode=params.get('mode','assist')
        if mode not in {'ask','assist','research'}:raise ValueError('未知会话模式')
        state=conversation.get('state',{})
        prior=state.get('executionRequests',{}).get(request)
        if prior:return prior
        previous=state.get('execution',{})
        continuing=(previous.get('status') in {'paused','failed','cancelled'} or previous.get('pendingMessages')) and previous.get('mode')==mode and previous.get('projectId')==pid
        snapshots={}
        if continuing:
            refs=deepcopy(previous.get('context',[]))
            snapshots=deepcopy(previous.get('projectSnapshots',{}))
            if pid and pid+':' not in snapshots:raise ValueError('原执行缺少冻结项目上下文，请新建会话')
        else:
            if pid:snapshots[pid+':']=deepcopy(self.service.store.project(pid))
            from .workbench import strategy_project
            for ref in refs:
                if ref.get('projectId'):
                    source=ref['projectId'];strategy=ref.get('strategyId')
                    snapshots[source+':'+(strategy or '')]=strategy_project(self.service.store,source,strategy) if strategy else deepcopy(self.service.store.project(source))
        eid=identifier()
        budget_db=self.service.store.project_store(pid).db
        def begin(state,current):
            if current.get('status')=='running':raise ValueError('当前会话正在执行，请发送补充消息或停止')
            if request in state.get('executionRequests',{}):raise ValueError('请求已接收，请读取执行状态')
            pending=deepcopy(current.get('pendingMessages',[])) if current.get('projectId')==pid else []
            selected=set(params.get('resumePendingMessageIds',[]))
            resume_all=message.strip('。！! ') in {'继续处理补充','继续处理未完成补充'}
            for item in pending:
                if current.get('status')=='cancelled':item['requiresConfirmation']=True
                if resume_all or item['id'] in selected:item.pop('requiresConfirmation',None)
            submitted=deepcopy(current.get('submitted',{})) if continuing else {}
            budget=model_budget(current.get('modelBudget') if continuing else None)
            budget_id=current.get('budgetId') if continuing else None
            if budget_id:
                shared=read_budget(budget_db,budget_id)
            else:
                budget_id='ai-'+eid
                shared=ensure_budget(budget_db,budget_id)
                if continuing and budget.get('used',0):
                    shared=reserve(budget_db,budget_id,'modelRequests',budget['used'],operation_id='legacy-execution-'+current['id'])
            budget.update(limit=shared['limits']['modelRequests'],used=shared['used']['modelRequests'],scope='research_plan')
            state['execution']={'id':eid,'requestId':request,'conversationId':cid,'projectId':pid,'status':'running',
                'startedAt':now(),'updatedAt':now(),'message':'正在理解请求','steps':[],'activeJobIds':[],
                'pendingMessages':pending,'deliveredMessageIds':[],'consumedMessageIds':[],'cancelRequested':False,'submitted':submitted,'context':refs,'mode':mode,'projectSnapshots':snapshots,'modelBudget':budget,'budgetId':budget_id,
                'submissionIntents':deepcopy(current.get('submissionIntents',{})) if continuing else {}}
            if continuing and 'frozenContext' in current:state['execution']['frozenContext']=deepcopy(current['frozenContext'])
            state.setdefault('messages',[]).append({'id':request,'role':'user','content':message,'experimentRefs':refs})
        value=self.mutate(cid,None,begin)
        with self.lock:self.futures[eid]=asyncio.run_coroutine_threadsafe(self.run(cid,eid,message),self.loop)
        return value

    def message(self,params):
        mid=params.get('messageId');message=str(params.get('message','')).strip()
        if not mid or not message:raise ValueError('补充消息ID与内容不能为空')
        def append(state,value):
            if value['status']!='running':raise ValueError('此执行已结束，请发送新请求')
            if any(m.get('id')==mid for m in state.get('messages',[])):return
            state.setdefault('messages',[]).append({'id':mid,'role':'user','content':message})
            if message.strip('。！! \t\r\n') not in {'停止','停止当前任务','取消当前任务','停止执行','取消执行'}:
                value['pendingMessages'].append({'id':mid,'message':message,'createdAt':now()})
        result=self.mutate(params['conversationId'],params['executionId'],append)
        if message.strip('。！! \t\r\n') in {'停止','停止当前任务','取消当前任务','停止执行','取消执行'}:
            return self.cancel(params)
        return result

    def cancel(self,params):
        cid=params['conversationId'];eid=params['executionId']
        value=self.mutate(cid,eid,lambda state,value:value.update(cancelRequested=True,message='正在停止模型及本次任务') if value['status']=='running' else None)
        future=self.futures.get(eid)
        if value['status']=='running' and future:
            future.cancel()
            with self.lock:
                if eid not in self.started:
                    value=self.mutate(cid,eid,lambda state,value:value.update(status='cancelled',message='请求已在模型调用前取消'))
                    self.futures.pop(eid,None)
        return value

    def supplements(self,cid,eid):
        messages=[]
        def consume(state,value):
            if value.get('cancelRequested'):raise asyncio.CancelledError()
            delivered=value.setdefault('deliveredMessageIds',[])
            messages.extend(deepcopy(m) for m in value['pendingMessages'] if m['id'] not in delivered and not m.get('requiresConfirmation'))
            delivered.extend(m['id'] for m in messages)
        self.mutate(cid,eid,consume)
        return messages

    async def run_research(self,cid,eid,spec):
        value=self.status({'conversationId':cid,'executionId':eid})
        additions=self.supplements(cid,eid)
        if additions:return {'supplementalMessages':additions,'submitted':False,'instruction':'先理解补充消息，再决定当前步骤；尚未提交任务。'}
        spec=deepcopy(spec);pid=value.get('projectId')
        if pid:
            if spec.get('projectId') not in (None,pid):raise ValueError('不能跨项目执行')
            spec['projectId']=pid
        elif spec.get('projectId') and spec['projectId'] not in {ref.get('projectId') for ref in value['context']}:
            raise ValueError('全局会话仅可执行明确引用的项目')
        if spec.get('kind')=='rdagent.run' and spec.get('parameters',{}).get('resumeExperimentId'):
            raise ValueError('恢复代码修复需要用户在原生研究入口查看错误和建议后明确确认，模型不能自行确认')
        token=json.dumps({k:v for k,v in spec.items() if k!='name'},sort_keys=True,ensure_ascii=False)
        key=identifier()
        with self.lock:
            current=self.status({'conversationId':cid,'executionId':eid})
            if current.get('cancelRequested'):raise asyncio.CancelledError()
            job_id=current['submitted'].get(token)
            if job_id:
                prior=self.service.store.get('job',job_id)
                if prior['status']=='completed':raise CompletedStepRepeated(prior)
            scope_key=(spec.get('projectId') or '')+':'+(spec.get('strategyId') or '')
            frozen=current.get('projectSnapshots',{}).get(scope_key)
            if spec.get('projectId') and frozen is None:raise ValueError('请先明确关联要执行的策略或项目')
            if not job_id:
                intent=current.get('submissionIntents',{}).get(token)
                if not intent:
                    intent={'id':identifier()}
                    self.mutate(cid,eid,lambda state,execution:execution.setdefault('submissionIntents',{}).__setitem__(token,intent))
                key=intent['id']
            if not job_id and current.get('budgetId'):
                budget_db=self.service.store.project_store(current.get('projectId')).db
                spec.setdefault('parameters',{}).update(budgetId=current['budgetId'],budgetProjectId=current.get('projectId'))
                if spec['kind']=='rdagent.run':
                    spec.setdefault('parameters',{}).update(budgetId=current['budgetId'],budgetProjectId=current.get('projectId'))
                elif spec['kind']=='optimize.run':
                    from .research_costs import work_counts
                    reserve(budget_db,current['budgetId'],'trials',work_counts([spec])['trials'],operation_id='submit-'+key)
            job=self.service.store.get('job',job_id) if job_id else self.service.jobs.submit(spec,frozen_project=frozen,submission_id=key)
            def submitted(state,execution):
                execution['submitted'][token]=job['id']
                if job['id'] not in execution['activeJobIds']:execution['activeJobIds'].append(job['id'])
                state['stageJobIds']=list(dict.fromkeys(state.get('stageJobIds',[])+[job['id']]))
                execution['steps'].append({'id':key,'tool':'run_research','status':'running','summary':job['name'],'jobId':job['id']})
            self.mutate(cid,eid,submitted)
        while job['status'] in {'queued','running'}:
            await asyncio.sleep(.25)
            job=self.service.store.get('job',job['id'])
        def finished(state,execution):
            execution['activeJobIds']=[j for j in execution['activeJobIds'] if j!=job['id']]
            step=next(s for s in execution['steps'] if s['id']==key)
            step.update(status='completed' if job['status']=='completed' else 'failed',summary=job.get('message',''))
            if job.get('experimentId'):step['experimentId']=job['experimentId']
        self.mutate(cid,eid,finished)
        if job['status']!='completed':
            if job.get('experimentId'):
                details=self.service.experiment_details(job.get('projectId'),job['experimentId'])['details']
                if details.get('requiresConfirmation'):raise RepairStepPaused(job,details.get('repair') or {})
            raise ValueError('研究步骤未完成：'+job.get('message',job['status']))
        result=self.service.experiment_details(job.get('projectId'),job['experimentId'])
        return {'jobId':job['id'],'experiment':ai._experiment_summary(result['experiment'],True),
                'details':result['details'],'supplementalMessages':self.supplements(cid,eid)}

    async def model_request(self,agent,prompt,cid,eid,supplement_ids=None,**kwargs):
        from pydantic_ai.usage import UsageLimits
        from pydantic_ai import capture_run_messages
        kwargs.setdefault('usage_limits',UsageLimits(request_limit=8,tool_calls_limit=12))
        for attempt in range(3):
            self.mutate(cid,eid,lambda state,value:value.update(deliveredMessageIds=list(supplement_ids or [])))
            try:
                with capture_run_messages() as captured:
                    try:
                        response=await agent.run(prompt,**kwargs)
                        value=self.status({'conversationId':cid,'executionId':eid})
                        self.validate_answer(response.output.model_dump(),value,cid)
                        def acknowledge(state,value):
                            if value.get('cancelRequested'):raise asyncio.CancelledError()
                            delivered=set(value.get('deliveredMessageIds',[]))
                            value['pendingMessages']=[m for m in value['pendingMessages'] if m['id'] not in delivered]
                            value['consumedMessageIds']=list(dict.fromkeys(value['consumedMessageIds']+list(delivered)))
                            value['deliveredMessageIds']=[]
                        self.mutate(cid,eid,acknowledge)
                        return response
                    finally:self.record_tools(cid,eid,captured)
            except asyncio.CancelledError:raise
            except Exception as exc:
                if not temporary_failure(exc) or attempt==2:raise
                headers=getattr(getattr(exc,'response',None),'headers',{})
                delay=headers.get('retry-after','1')
                try:delay=max(0,float(delay))
                except (ValueError,TypeError):
                    from email.utils import parsedate_to_datetime
                    from datetime import datetime,timezone
                    try:delay=max(0,(parsedate_to_datetime(delay)-datetime.now(timezone.utc)).total_seconds())
                    except Exception:delay=1
                self.mutate(cid,eid,lambda state,value:value.update(message='服务暂不可用，等待后重试'))
                await asyncio.sleep(delay)

    def record_tools(self,cid,eid,messages):
        from pathlib import Path
        from .storage import read_json,write_json
        settings=self.service.store.settings()
        secrets=[v.get('apiKey') for v in [settings.get('ai',{}),*(x for x in settings.get('aiPurposes',{}).values() if isinstance(x,dict))] if v.get('apiKey')]
        def clean(value):
            if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if str(k).lower().replace('_','') not in {'apikey','authorization','password','secret','token'}}
            if isinstance(value,list):return [clean(v) for v in value]
            if isinstance(value,str):
                try:return clean(json.loads(value))
                except (ValueError,TypeError):
                    for secret in secrets:value=value.replace(secret,'[redacted]')
                    return value
            return value
        rows=[];report_failures=[]
        from .report_ai import REPORT_TOOLS, validation_message
        for message in messages:
            for part in getattr(message,'parts',[]):
                if getattr(part, 'tool_name', None) in REPORT_TOOLS:
                    if getattr(part, 'part_kind', '') == 'retry-prompt':
                        content = part.content
                        if isinstance(content, list):
                            fields = {'plan','reportId','name','steps','missingConditions','objective','strategyId','id','revision','variant','spec','kind','parameters','projectId','dependsOn','differences','citations','page','excerpt','project_id_ref'}
                            paths = ['.'.join(str(x) for x in row.get('loc', ()) if type(x) is int or x in fields) + '（' + str(row.get('type', 'validation_error'))[:48] + '）' for row in content if isinstance(row, dict)]
                            reason = '工具参数缺少字段或类型不符：' + '、'.join(p for p in paths if p)[:160]
                        else:
                            reason = validation_message(ValueError(str(content).removeprefix('方案尚未保存，请核对工具格式与原文：')))
                        report_failures.append((part.tool_name, reason))
                    continue
                kind=getattr(part,'part_kind','')
                if kind=='tool-call':rows.append({'kind':kind,'tool':part.tool_name,'args':clean(part.args)})
                elif kind=='tool-return':rows.append({'kind':kind,'tool':part.tool_name,'result':clean(part.content)})
        if report_failures:
            def retain_failures(state, value):
                for tool, reason in report_failures:
                    if any(s.get('tool') == tool and s.get('errorMessage') == reason for s in value['steps']):
                        continue
                    summary = '研报工具校验失败：' + reason
                    value['steps'].append(dict(id=identifier(), tool=tool, status='failed', summary=summary, errorType='ValidationError', errorMessage=reason))
                    if value.get('status') == 'running' and not value.get('cancelRequested'):
                        value['message'] = summary
            self.mutate(cid, eid, retain_failures)
        if not rows:return
        value=self.status({'conversationId':cid,'executionId':eid})
        path=Path(self.service.store.project(value.get('projectId'))['path'])/'.research/executions'/eid/'tools.json'
        write_json(path,read_json(path,[])+rows)

    async def explain_completed(self,model,cid,eid,message,job):
        from pydantic_ai import Agent
        from pydantic_ai.usage import UsageLimits
        result=self.service.experiment_details(job.get('projectId'),job['experimentId'])
        value=self.status({'conversationId':cid,'executionId':eid})
        pending=deepcopy([m for m in value.get('pendingMessages',[]) if not m.get('requiresConfirmation')]);included={m['id'] for m in pending}
        delivered=set(value.get('consumedMessageIds',[]))
        state=self.service.store.get('conversation',cid)['state']
        additions=[{'id':m['id'],'message':m['content']} for m in state.get('messages',[]) if m.get('id') in delivered and m.get('role')=='user']+pending
        prompt=json.dumps({'userRequest':message,'experiment':ai._experiment_summary(result['experiment'],True),
            'details':result['details'],'tables':result['tables'],'supplementalMessages':additions,
            'instruction':'任务已经真实完成。只说明实际结果和可讨论的下一阶段，不调用工具，不执行新任务，不声称用户已经确认下一阶段。'},ensure_ascii=False,default=str)
        agent=Agent(model,instructions='你正在完成已执行任务的只读结果说明。以普通中文文本答复，先说明完成内容和实际实验ID，再说明限制。没有任何执行工具，不要输出工具调用。')
        self.mutate(cid,eid,lambda state,value:value.update(message='任务已完成，正在整理结果说明'))
        try:
            response=await agent.run(prompt,model_settings={'timeout':120},usage_limits=UsageLimits(request_limit=1,tool_calls_limit=0))
            if not str(response.output).strip():raise ValueError('模型未返回说明')
            def acknowledge(state,value):
                if value.get('cancelRequested'):raise asyncio.CancelledError()
                value['pendingMessages']=[m for m in value.get('pendingMessages',[]) if m['id'] not in included]
                value['consumedMessageIds']=list(dict.fromkeys(value.get('consumedMessageIds',[])+[m['id'] for m in pending]))
            self.mutate(cid,eid,acknowledge)
            return str(response.output),True
        except asyncio.CancelledError:raise
        except Exception:
            return '任务已完成，AI说明暂不可用。实际实验：'+job['experimentId']+'；可打开结果查看。',False

    def validate_answer(self,answer,value,cid):
        from .jobs import validate_spec
        pid=value.get('projectId')
        experiments=ai.attached_experiments(self.service,value['context'] or None,pid,cid)
        known={(item.get('projectId'),item['id']) for item in experiments}
        refs=answer.setdefault('experimentRefs',[])
        for key in answer.get('experimentIds',[]):
            matches=[scope for scope,eid in known if eid==key]
            if len(matches)!=1:raise ValueError('模型返回不存在或跨项目有歧义的实验引用')
            if not any(ref.get('experimentId')==key for ref in refs):refs.append({'kind':'experiment','projectId':matches[0],'experimentId':key})
        if any((ref.get('projectId'),ref.get('experimentId')) not in known for ref in refs):raise ValueError('模型返回未关联的实验引用')
        if value['mode']=='ask':answer['proposals']=[]
        for proposal in answer.get('proposals',[]):
            spec=validate_spec(proposal['spec']);scope=(spec.get('projectId') or '')+':'+(spec.get('strategyId') or '')
            if scope not in value['projectSnapshots']:raise ValueError('模型建议引用了未关联的项目或策略')
        from .report_ai import validate_output
        validate_output(self.service, answer, pid, value['context'], value.get('steps', []))
        return answer

    async def run_reproduction(self, cid, eid, plan_id, project_id=None, run_id=None):
        value = self.status({'conversationId': cid, 'executionId': eid})
        pid = project_id or value.get('projectId')
        if not pid or not any(key.startswith(pid + ':') for key in value['projectSnapshots']):
            raise ValueError('复现计划必须属于当前关联项目')
        additions = self.supplements(cid, eid)
        if additions:
            return {'supplementalMessages': additions, 'submitted': False}
        params = {'projectId': pid, 'planId': plan_id,'budgetId':value.get('budgetId'),'budgetProjectId':value.get('projectId')}
        if run_id:
            params['runId'] = run_id
        run = await asyncio.to_thread(self.service.report_tasks.dispatch, 'reproductions.run', params)
        params['runId'] = run['runId']
        try:
            while True:
                def track(state, current):
                    if current.get('cancelRequested'):
                        raise asyncio.CancelledError()
                    for step in run['steps']:
                        if step.get('jobId'):
                            if step['jobId'] not in state.setdefault('stageJobIds', []):
                                state['stageJobIds'].append(step['jobId'])
                            if not any(s.get('jobId') == step['jobId'] for s in current['steps']):
                                current['steps'].append(dict(step))
                    current['activeJobIds'] = [s['jobId'] for s in run['steps'] if s.get('jobId') and s['status'] in {'queued', 'running'}]
                self.mutate(cid, eid, track)
                if run['status'] != 'running':
                    return {key: run[key] for key in ('runId', 'planId', 'revision', 'status', 'steps', 'message') if key in run}
                await asyncio.sleep(.3)
                run = await asyncio.to_thread(self.service.report_tasks.dispatch, 'reproductions.status', params)
        except BaseException:
            await asyncio.to_thread(self.service.report_tasks.dispatch, 'reproductions.cancel', params)
            raise

    async def run(self,cid,eid,message):
        with self.lock:self.started.add(eid)
        from openai import AsyncOpenAI
        from pydantic_ai.providers.openai import OpenAIProvider
        from pydantic_ai.models.openai import OpenAIChatModel
        from .workbench import get_conversation
        client=None;terminal='failed';failure='执行未完成'
        try:
            value=self.status({'conversationId':cid,'executionId':eid});pid=value.get('projectId')
            if value.get('cancelRequested'):raise asyncio.CancelledError()
            from .ai_settings import resolve
            purpose='research' if value['mode']=='research' else 'reports' if any(ref.get('kind')=='report' for ref in value['context']) else 'conversation'
            config=resolve(self.service.store,purpose)
            if not config.get('baseUrl') or not config.get('model'):raise ValueError('请先配置模型服务地址与模型')
            import httpx
            async def count_request(request):
                current=self.status({'conversationId':cid,'executionId':eid})
                if current.get('cancelRequested'):raise asyncio.CancelledError()
                shared=reserve(self.service.store.project_store(current.get('projectId')).db,current['budgetId'],'modelRequests')
                self.mutate(cid,eid,lambda state,current:current.update(modelBudget=dict(limit=shared['limits']['modelRequests'],used=shared['used']['modelRequests'],scope='research_plan')))
            client=AsyncOpenAI(base_url=config['baseUrl'],api_key=config.get('apiKey') or 'local-no-key',max_retries=0,
                http_client=httpx.AsyncClient(event_hooks={'request':[count_request]}))
            model=OpenAIChatModel(config['model'],provider=OpenAIProvider(openai_client=client))
            context=deepcopy(value.get('frozenContext'))
            if context is None:
                context=ai.attached_context(self.service,value['context']) if value['context'] else ai._project_context(self.service,pid,value['projectSnapshots'].get((pid or '')+':')) if pid else {}
                for item in context.get('attachedObjects',[]):
                    ref=item.get('reference',{});frozen=value['projectSnapshots'].get((ref.get('projectId') or '')+':'+(ref.get('strategyId') or ''))
                    if frozen and ref.get('strategyId'):
                        item['strategy']={'id':ref['strategyId'],'name':frozen.get('strategyName'),'settings':deepcopy(frozen['settings']),'universe':deepcopy(frozen['universe'])}
                self.mutate(cid,eid,lambda state,execution:execution.update(frozenContext=deepcopy(context)))
            agent=ai._create_agent(self.service,pid,model,value['context'] or None,cid,value['mode'],execution=True,frozen_context=context)
            if value['mode']!='ask':
                @agent.tool_plain
                async def run_research(spec:dict)->dict:
                    """仅在用户明确要求执行时提交当前研究步骤，等待真实完成并返回结果。"""
                    return await self.run_research(cid,eid,spec)
                @agent.tool_plain
                async def run_reproduction_plan(plan_id: str, project_id_ref: str | None = None, run_id: str | None = None) -> dict:
                    """仅用户明确要求执行或恢复时运行真实复现计划，等待依赖任务结束，不启用策略。"""
                    return await self.run_reproduction(cid, eid, plan_id, project_id_ref, run_id)
            conversation=get_conversation(self.service.store,cid)
            from . import project_summary
            summary=project_summary.get(self.service.store,pid) if pid else None
            summary_history=project_summary.histories(self.service.store,pid,summary) if summary and not summary.get('historyInitialized',False) else []
            pending_ids={m['id'] for m in value.get('pendingMessages',[])}
            prompt=json.dumps({'message':message,'history':[m for m in conversation['state']['messages'][-20:] if m.get('id') not in pending_ids],
                'context':context,
                'project':ai._project_context(self.service,pid,value['projectSnapshots'].get((pid or '')+':')) if pid else None,
                'projectSummary':summary,'summaryHistory':summary_history,
                'summaryInstructions':'在同一响应summaryUpdate追加有来源条目；userDecisions必须逐字引用用户明确决定，推测归hypotheses，实验条目必须引用真实experimentId。保留手工摘要和已清除状态。',
                'scope':{'projectId':pid,'references':value['context']}},ensure_ascii=False,default=str)
            response=await self.model_request(agent,prompt,cid,eid,model_settings={'temperature':float(config.get('temperature',.2)),'timeout':120})
            def finish(state,value):
                if value.get('cancelRequested'):raise asyncio.CancelledError()
                state.setdefault('messages',[]).append({'id':eid,'role':'assistant','content':answer['message'],'phase':answer.get('phase',''),'experimentIds':answer.get('experimentIds',[]),'experimentRefs':answer.get('experimentRefs',[]),'uiBlocks':answer.get('uiBlocks',[]),'reportCitations':answer.get('reportCitations',[])})
                state['phase']=answer.get('phase','');state['proposals']=[] if value['mode']=='ask' else answer.get('proposals',[])
            while True:
                answer=response.output.model_dump()
                additions=self.supplements(cid,eid)
                if additions:
                    response=await self.model_request(agent,json.dumps({'supplementalMessages':additions,'instruction':'处理运行期间补充；不得改动已完成实验'},ensure_ascii=False),cid,eid,supplement_ids=[m['id'] for m in additions],message_history=response.all_messages(),model_settings={'timeout':120})
                    continue
                with self.lock:
                    value=self.status({'conversationId':cid,'executionId':eid})
                    if any(not m.get('requiresConfirmation') for m in value['pendingMessages']):continue
                    self.validate_answer(answer,value,cid)
                    self.mutate(cid,eid,finish)
                    break
            if pid and answer.get('summaryUpdate'):
                latest=get_conversation(self.service.store,cid)
                users='\n'.join(str(m.get('content','')) for m in latest['state']['messages'] if m.get('role')=='user')
                users+='\n'+'\n'.join(str(m.get('content','')) for h in summary_history for m in h['messages'] if m.get('role')=='user')
                sources=list(dict.fromkeys([cid]+[h['conversationId'] for h in summary_history]))
                try:project_summary.append_response(self.service.store,pid,answer['summaryUpdate'],summary['revision'],users,sources)
                except (ValueError,TypeError,KeyError):pass
            terminal='completed';failure=answer['message']
        except CompletedStepRepeated as exc:
            try:
                failure,available=await self.explain_completed(model,cid,eid,message,exc.job)
                terminal='completed'
                self.mutate(cid,eid,lambda state,value:state.setdefault('messages',[]).append({'id':eid,'role':'assistant','content':failure,
                    'experimentIds':[exc.job['experimentId']],'experimentRefs':[{'kind':'experiment','projectId':exc.job.get('projectId'),'experimentId':exc.job['experimentId']}],
                    'explanationAvailable':available}))
            except asyncio.CancelledError:
                terminal='cancelled';failure='任务已完成，结果说明已取消；实际实验：'+exc.job['experimentId']
        except RepairStepPaused as exc:
            terminal='paused';failure='代码首次尝试失败，已保留检查点。'+str(exc.repair.get('error',''))+'；'+str(exc.repair.get('proposal','请查看原生研究详情并明确确认修复。'))
            self.mutate(cid,eid,lambda state,value:state.setdefault('messages',[]).append({'id':eid,'role':'assistant','content':failure,'experimentIds':[exc.job['experimentId']]}))
        except asyncio.CancelledError:
            terminal='cancelled';failure='模型请求已取消；已完成产物保留'
        except Exception as exc:
            import traceback
            frames = [{'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name} for frame in traceback.extract_tb(exc.__traceback__)]
            self.mutate(cid, eid, lambda state, value: value.update(errorDetails={'type': type(exc).__name__, 'frames': frames}))
            code=getattr(exc,'status_code',None)
            if budget_failure(exc):
                terminal='paused';failure=str(budget_failure(exc))
            elif temporary_failure(exc):
                terminal='paused';failure='模型服务暂不可用，有限重试已用尽；已暂停并保留结果，可继续或更换模型。'
            else:failure=('模型服务未授权，请检查配置' if code in {401,403} else str(exc) if isinstance(exc,ValueError) else '执行失败：'+type(exc).__name__)
        finally:
            cleanup_errors=[];remaining=[];job_states={}
            try:
                if client:await client.close()
            except Exception as exc:cleanup_errors.append('模型连接关闭失败：'+type(exc).__name__)
            try:
                current=self.status({'conversationId':cid,'executionId':eid})
                for job_id in current.get('activeJobIds',[]):
                    try:
                        await asyncio.to_thread(self.service.jobs.cancel,job_id)
                        job_states[job_id]=self.service.store.get('job',job_id)['status']
                        if job_states[job_id] in {'queued','running'}:remaining.append(job_id)
                    except Exception as exc:
                        remaining.append(job_id);cleanup_errors.append('任务停止未确认：'+type(exc).__name__)
                if remaining or cleanup_errors:terminal='failed';failure+='；'+'；'.join(cleanup_errors or ['部分任务仍在停止'])
                def final_state(state,value):
                    status=terminal;message=failure
                    value['deliveredMessageIds']=[]
                    if terminal=='cancelled':
                        for item in value.get('pendingMessages',[]):item['requiresConfirmation']=True
                    if terminal!='completed' and value.get('pendingMessages'):
                        message+=f"；保留 {len(value['pendingMessages'])} 条未完成补充。"+('可发送“继续处理未完成补充”明确处理，或选择消息ID；不会自动执行。' if terminal=='cancelled' else '可继续处理未完成补充。')
                    if terminal=='completed' and value.get('pendingMessages'):
                        status='paused';notice=f"仍有 {len(value['pendingMessages'])} 条补充消息尚未处理，已保留，可发送“继续处理未完成补充”或选择消息ID处理。"
                        message+='\n'+notice
                        for item in reversed(state.get('messages',[])):
                            if item.get('id')==eid and item.get('role')=='assistant':item['content']+='\n'+notice;break
                    value.update(status=status,message=message,activeJobIds=remaining)
                    for step in value['steps']:
                        if step.get('tool') in {'search_reports','read_report','read_report_pages','read_reproduction_plan','save_reproduction_plan','save_report_factor'} and step.get('status') == 'running':
                            step.update(status='cancelled' if terminal == 'cancelled' else 'interrupted', summary=step['summary'] + '：调用中断')
                        status=job_states.get(step.get('jobId'))
                        if status and status not in {'queued','running'}:step['status']=status
                self.mutate(cid,eid,final_state)
            finally:
                with self.lock:self.futures.pop(eid,None);self.started.discard(eid)

    def close(self):
        for conversation in self.service.store.list('conversation'):
            value=conversation.get('state',{}).get('execution',{})
            if value.get('status')=='running':self.cancel({'conversationId':conversation['id'],'executionId':value['id']})
        async def shutdown():
            pending=[task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in pending:
                if not task.cancelling():task.cancel()
            if pending:await asyncio.gather(*pending,return_exceptions=True)
        if self.loop.is_running():
            try:asyncio.run_coroutine_threadsafe(shutdown(),self.loop).result(timeout=10)
            finally:self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=1)
            if not self.thread.is_alive():self.loop.close()

    def dispatch(self,method,params):
        return getattr(self,method.rsplit('.',1)[-1])(params)
