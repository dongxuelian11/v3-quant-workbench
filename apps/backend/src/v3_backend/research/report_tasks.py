"""Small service scheduler; all expensive report work remains in existing Jobs."""
import json
from copy import deepcopy
from datetime import date, timedelta
from threading import Event, RLock, Thread

from . import reports
from .jobs import validate_spec
from .storage import identifier, now, read_json
from .research_costs import work_counts, reproduction_budget


def missing_conditions(value):
    if not isinstance(value,list) or any(not isinstance(item,str) or not item.strip() for item in value):
        raise ValueError('缺失条件必须为非空文字数组')
    return value


def validate_step_dates(plan):
    for step in plan['steps']:
        kind, params = step['spec']['kind'], step['spec']['parameters']
        if kind not in {'factor.analyze','backtest.run','model.train','optimize.run'}:continue
        keys=('trainStart','trainEnd','validStart','validEnd','testStart','testEnd') if kind=='model.train' else ('startDate','endDate')
        incomplete=bool(plan.get('missingConditions') or step.get('missingConditions'))
        if any(not params.get(key) for key in keys) and not incomplete:
            if kind=='model.train':raise ValueError('模型步骤必须在 spec.parameters 明确 trainStart/trainEnd/validStart/validEnd/testStart/testEnd；尚未确定时填 missingConditions')
            raise ValueError('计算步骤必须在 spec.parameters 明确 startDate/endDate，不能只写 objective；尚未确定时填 missingConditions')
        try:
            values={key:date.fromisoformat(params[key]) for key in keys if key in params and params[key] is not None and isinstance(params[key],str) and len(params[key])==10}
            if any(key in params and (params[key] is not None or not incomplete) and key not in values for key in keys):raise ValueError()
            if any(keys[i] in values and keys[i+1] in values and values[keys[i]]>values[keys[i+1]] for i in range(0,len(keys),2)):raise ValueError()
        except (ValueError,TypeError):raise ValueError('步骤日期必须为 YYYY-MM-DD，且开始日期不得晚于结束日期') from None


def validate_draft_spec(spec, incomplete=False):
    if spec.get('kind') not in {'data.update','data.import','factor.analyze','model.train','backtest.run','optimize.run'}:
        raise ValueError('复现步骤仅支持数据、因子、模型、回测与寻优任务')
    params=spec.get('parameters')
    if not isinstance(params,dict):raise ValueError('任务参数无效')
    if 'factorIds' in params and (not isinstance(params['factorIds'],list) or not params['factorIds'] or any(not isinstance(v,str) for v in params['factorIds'])):raise ValueError('任务需要非空 factorIds 数组')
    if spec['kind']=='data.import' and 'files' in params and (not isinstance(params['files'],list) or not params['files']):raise ValueError('请选择导入文件')
    if spec['kind']=='backtest.run' and 'template' in params and params['template'] not in {'single_factor','multi_factor','model_score'}:raise ValueError('未知组合模板')
    if spec['kind']=='data.update' and 'source' in params and params['source'] not in {'baostock','akshare'}:raise ValueError('未知数据源')
    try:validate_spec(spec)
    except ValueError as exc:
        missing=str(exc).startswith('任务缺少参数:') or str(exc)=='任务需要非空 factorIds 数组' and 'factorIds' not in params
        if not incomplete or not missing:raise


def plan_readiness(plan):
    plan=deepcopy(plan);steps={s['id']:s for s in plan['steps']};blocked={}
    def blockers(key):
        if key in blocked:return blocked[key]
        parents=set()
        for dep in steps[key]['dependsOn']:
            inherited=blockers(dep)
            if inherited or steps[dep].get('missingConditions'):parents.add(dep);parents.update(inherited)
        blocked[key]=parents
        return parents
    rows=[];ready=[]
    for step in plan['steps']:
        parents=blockers(step['id']);missing=list(plan.get('missingConditions',[]))+list(step.get('missingConditions',[]))
        if missing or parents:rows.append(dict(stepId=step['id'],missingConditions=missing,blockedByStepIds=[s['id'] for s in plan['steps'] if s['id'] in parents]))
        else:ready.append(step['id'])
    plan['readiness']=dict(runnableStepIds=ready,blockedSteps=rows)
    return plan


def select_steps(plan, selected=None):
    ids=[s['id'] for s in plan['steps']]
    if selected is None:selected=ids
    if not isinstance(selected,list) or not selected or any(not isinstance(key,str) for key in selected) or len(set(selected))!=len(selected) or any(key not in ids for key in selected):
        raise ValueError('所选步骤必须非空、有效且不重复')
    if plan.get('missingConditions'):raise ValueError('全局缺失条件未解决，不能运行任何子集')
    chosen=set(selected);steps=[s for s in plan['steps'] if s['id'] in chosen]
    if any(not set(step['dependsOn'])<=chosen for step in steps):raise ValueError('所选步骤依赖不闭合，请明确选择所需前置步骤')
    ready=set(plan_readiness(plan)['readiness']['runnableStepIds'])
    if not chosen<=ready:raise ValueError('所选步骤或其前置步骤仍有缺失条件')
    for step in steps:validate_draft_spec(step['spec'])
    validate_step_dates({**plan,'steps':steps})
    return steps


def run_scope(run):
    ids=[s['id'] for s in run['planSnapshot']['steps']]
    selected=run.setdefault('selectedStepIds',ids)
    run['excludedStepIds']=[key for key in ids if key not in selected]
    run['executionScope']='subset' if run['excludedStepIds'] else 'full'
    return run


class ReportTasks:
    def __init__(self, service):
        self.service, self.store, self.jobs = service, service.store, service.jobs
        self.lock, self.stop = RLock(), Event()
        self.emitted = {}
        self.update_checked_minute = None
        for run in self.store.list('reproduction_run'):
            if run['status'] == 'running':
                run.update(status='interrupted', message='应用曾中断，请明确继续；已完成步骤不会重复提交')
                self._save_run(run)
        self.thread = Thread(target=self._loop, daemon=True, name='report-scheduler')
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)
        with self.lock:
            for run in self.store.list('reproduction_run'):
                if run['status'] == 'running':
                    run.update(status='interrupted', message='应用关闭，已完成步骤保留，请明确继续')
                    self._save_run(run)

    def _step_messages(self, run):
        from .report_ai import safe_step_message
        jobs={job['id']:job for job in self.store.list('job',run['projectId'])}
        for step in run['steps']:
            for attempt in [step,*step.get('attemptHistory',[])]:
                job=jobs.get(attempt.get('jobId'),{})
                attempt['message']=safe_step_message(job.get('message',attempt.get('message')),attempt['status'])

    def _run_view(self, run):
        self._step_messages(run)
        run_scope(run)
        run['budget']=reproduction_budget(self.store,run)
        return run

    def _save_run(self, run):
        self._step_messages(run)
        run_scope(run)
        run['budget'] = reproduction_budget(self.store, run)
        self.store.put('reproduction_run', run, run['projectId'])
        self._link_execution(run)
        if self.emitted.get(run['id']) != run['status']:
            self.emitted[run['id']] = run['status']
            emit = getattr(self.service, 'emit', lambda value: None)
            emit(dict(kind='reproduction.execution', id=run['id'], planId=run['planId'], projectId=run['projectId'], status=run['status'], message=run.get('message')))

    def _link_execution(self, run):
        owner=run.get('executionOwner')
        if not owner:return
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT body FROM records WHERE kind='conversation' AND id=?",(owner['conversationId'],)).fetchone()
            if row is None:raise ValueError('复现所属会话已不存在')
            conversation=json.loads(row[0]);state=conversation.setdefault('state',{})
            execution=state.get('execution',{})
            if execution.get('id')!=owner['executionId']:
                execution=next((v for v in state.get('executionRequests',{}).values() if v.get('id')==owner['executionId']),None)
            if execution is None:raise ValueError('复现所属执行已不存在')
            ids=execution.setdefault('reproductionRunIds',[])
            if run['id'] not in ids:ids.append(run['id'])
            state['stageJobIds']=list(dict.fromkeys(state.get('stageJobIds',[])+[s['jobId'] for s in run['steps'] if s.get('jobId')]))
            state.setdefault('executionRequests',{})[execution['requestId']]=deepcopy(execution)
            db.execute("UPDATE records SET body=? WHERE kind='conversation' AND id=?",(json.dumps(conversation,ensure_ascii=False,allow_nan=False),owner['conversationId']))

    def _loop(self):
        from .storage_migration import location_scope
        while not self.stop.wait(1):
            with self.lock,location_scope(self.store):
                if getattr(self.service,'migrations',None) and self.service.migrations.pause.is_set():continue
                minute=now()[:16]
                if minute!=self.update_checked_minute:
                    self.update_checked_minute=minute
                    from .scheduled_updates import tick
                    try:tick(self.service)
                    except Exception as exc:
                        self.service.emit(dict(kind='data.update.notice',status='failed',message='盘后更新暂不可用：'+str(exc)))
                for run in self.store.list('reproduction_run'):
                    if run['status'] == 'running':
                        try:
                            self._advance(run)
                        except Exception as exc:
                            run.update(status='failed', message=str(exc))
                            self._save_run(run)
                for subscription in self.store.list('report_subscription'):
                    try:
                        self._subscription_tick(subscription)
                    except Exception as exc:
                        subscription.update(lastCheckedAt=now(), message=str(exc))
                        self.store.put('report_subscription', subscription)

    def _subscription_tick(self, value):
        job_id = value.get('jobId')
        if job_id:
            job = self.store.get('job', job_id)
            if job['status'] in {'queued', 'running'}:
                return
            value.pop('jobId', None)
            value['message'] = job['message']
            if job['status'] == 'completed':
                from pathlib import Path
                directory = Path(self.store.project(None)['path']) / '.research' / 'runs' / job['id']
                result = read_json(directory / 'details.json', {})
                if result.get('documentFailures', 0) == 0:
                    value['lastSuccessfulDate'] = value.get('checkedDate')
                else:
                    value['message'] = '目录已更新，部分原文未收集成功，下次继续补查'
            self.store.put('report_subscription', value)
        if value.get('enabled') and (value.get('lastCheckedAt') or '')[:10] != now()[:10]:
            self._refresh_subscription(value)

    def _refresh_subscription(self, value):
        if value.get('jobId'):
            job = self.store.get('job', value['jobId'])
            if job['status'] in {'queued', 'running'}:
                return job
        today = date.today()
        query = {**value['query'], 'collectDocuments': True}
        query.setdefault('startDate', (today - timedelta(days=365)).isoformat())
        query.setdefault('endDate', today.isoformat())
        if value.get('lastSuccessfulDate'):
            overlap = (date.fromisoformat(value['lastSuccessfulDate']) - timedelta(days=1)).isoformat()
            query['startDate'] = max(query['startDate'], min(overlap, query['endDate']))
        job = self.jobs.submit({'kind': 'reports.refresh', 'name': '订阅：' + value['name'], 'parameters': query})
        value.update(jobId=job['id'], lastCheckedAt=now(), checkedDate=today.isoformat(), message='已提交公开目录刷新任务')
        self.store.put('report_subscription', value)
        return job

    def _plan(self, params):
        project_id = params['projectId']
        if not project_id:
            raise ValueError('复现计划需要所属项目')
        return plan_readiness(self.store.project_store(project_id).get('reproduction', params['planId']))

    def _save_plan(self, params):
        project_id, value = params['projectId'], deepcopy(params['plan'])
        if not isinstance(value, dict) or not value.get('reportId'):
            raise ValueError('plan 必须包含真实 reportId、name、steps、missingConditions')
        portable = self.store.project_store(project_id)
        old = portable.get('reproduction', value['id']) if value.get('id') else None
        if old and 'revision' in value and value['revision'] != old['revision']:
            raise ValueError('复现计划已有新修订，请刷新并核对差异后再保存')
        reports.get(self.store, value['reportId'])
        if not value.get('name') or not isinstance(value.get('steps'), list):
            raise ValueError('复现计划需要名称与步骤数组')
        value['missingConditions']=missing_conditions(value.get('missingConditions',[]))
        value.pop('readiness',None)
        steps = value['steps']
        if any(not isinstance(step,dict) for step in steps):raise ValueError('复现步骤 ID 必须非空且不重复')
        ids = [step.get('id') for step in steps]
        if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
            raise ValueError('复现步骤 ID 必须非空且不重复')
        for step in steps:
            if not isinstance(step, dict) or not isinstance(step.get('spec'), dict):
                raise ValueError('每步必须提供 spec:{kind,parameters}，以及 id、name、variant、dependsOn、differences、citations')
            if step.get('variant') not in {'original', 'adapted', 'post_publication', 'execution'}:
                raise ValueError('请区分原文、适配、发布后与执行验证')
            if not isinstance(step.get('differences'), list) or not isinstance(step.get('dependsOn'), list):
                raise ValueError('步骤需要差异说明与依赖列表')
            if any(key not in ids or key == step['id'] for key in step['dependsOn']):
                raise ValueError('复现依赖指向不存在的步骤或自身')
            if step['variant'] != 'original' and not step['differences']:
                raise ValueError('适配或验证步骤必须说明与原文的差异')
            reports.validate_citations(self.store, step.get('citations', []))
            if any(c['reportId'] != value['reportId'] for c in step.get('citations', [])):
                raise ValueError('步骤引用必须属于计划研报')
            step['missingConditions']=missing_conditions(step.get('missingConditions',[]))
            spec = step['spec']
            if spec.get('projectId') not in (None, project_id):
                raise ValueError('步骤必须属于当前研究项目')
            spec['projectId'] = project_id
            if spec.get('strategyId') not in (None, value.get('strategyId')):
                raise ValueError('步骤策略必须与计划一致')
            spec['strategyId'] = value.get('strategyId')
            validate_draft_spec(spec,bool(value['missingConditions'] or step['missingConditions']))
            if spec['kind'] not in {'data.update', 'data.import', 'factor.analyze', 'model.train', 'backtest.run', 'optimize.run'}:
                raise ValueError('复现步骤仅支持数据、因子、模型、回测与寻优任务')
        pending, done = {s['id']: set(s['dependsOn']) for s in steps}, set()
        while pending:
            ready = [key for key, deps in pending.items() if deps <= done]
            if not ready:
                raise ValueError('复现步骤存在循环依赖')
            for key in ready:
                done.add(key)
                del pending[key]
        value.update(id=old['id'] if old else identifier(), projectId=project_id, revision=(old['revision'] if old else 0) + 1,
                     createdAt=old['createdAt'] if old else now(), updatedAt=now())
        value.setdefault('objective', '')
        value.setdefault('missingConditions', [])
        value['plannedWork'] = work_counts(step['spec'] for step in steps)
        validate_step_dates(value)
        portable.put('reproduction', value, project_id)
        return plan_readiness(value)

    def run_for_execution(self, params, conversation_id, execution_id):
        with self.lock:
            conversation=self.store.get('conversation',conversation_id)
            execution=conversation.get('state',{}).get('execution',{})
            if execution.get('id')!=execution_id or not any(key.startswith(params['projectId']+':') for key in execution.get('projectSnapshots',{})):
                raise ValueError('复现执行不属于当前会话及冻结项目范围')
            if params.get('budgetId')!=execution.get('budgetId') or params.get('budgetProjectId')!=execution.get('projectId'):
                raise ValueError('复现预算与所属会话不一致')
            return self._run(params, execution_owner={'conversationId':conversation_id,'executionId':execution_id})

    def _recover_children(self, run):
        jobs=self.store.list('job',run['projectId'])
        for state in run['steps']:
            found=None
            for job in jobs:
                link=job.get('spec',{}).get('reproduction',{})
                if state.get('jobId')==job['id'] or state.get('submissionId')==job['id']:
                    found=job;break
                if not state.get('jobId') and not state.get('submissionId') and link.get('runId')==run['id'] and link.get('stepId')==state['stepId'] and link.get('attempt',1)==state.get('attempt',1):
                    found=job
            if found:
                from .report_ai import safe_step_message
                state.update(jobId=found['id'],status=found['status'],message=safe_step_message(found.get('message'),found['status']))
                if found.get('experimentId'):state['experimentId']=found['experimentId']
            elif state.get('jobId') and state['status']!='completed':
                raise ValueError('复现任务记录缺失，不能自动重新提交：'+state['jobId'])

    def _owner_cancelled(self, run):
        owner=run.get('executionOwner')
        if not owner or run.get('executionActive') is False:return False
        conversation=self.store.get('conversation',owner['conversationId'])
        execution=conversation.get('state',{}).get('execution',{})
        return execution.get('id')!=owner['executionId'] or execution.get('cancelRequested') or execution.get('status')!='running'

    def _cancel_run(self, run):
        self._recover_children(run)
        run.update(status='failed',cancelPending=True,message='正在停止复现，后台终止尚未确认')
        self._save_run(run)
        for state in run['steps']:
            if state.get('jobId'):
                job=self.store.get('job',state['jobId'])
                process=getattr(self.jobs,'processes',{}).get(state['jobId'])
                if job['status']=='completed':
                    state.update(status='completed',experimentId=job.get('experimentId'))
                elif job['status'] in {'running','queued'} or process is not None and process.poll() is None:
                    stopped=self.jobs.cancel(state['jobId'])
                    if stopped['status'] in {'queued','running'} or stopped.get('cleanupPending') or process is not None and process.poll() is None:
                        raise ValueError('后台任务停止尚未确认')
            if state['status']!='completed':state['status']='cancelled'
        run.update(status='cancelled',cancelPending=False,message='复现已停止，已完成实验保留')
        self._save_run(run)
        return run

    @staticmethod
    def _check_owner(run, owner):
        if owner and run.get('executionOwner',{}).get('conversationId')!=owner['conversationId']:
            raise ValueError('已有运行不属于此会话，请在原复现入口查看或恢复')

    @staticmethod
    def _check_budget(run, params):
        if 'budgetId' in params and params['budgetId']!=run.get('budgetId') or 'budgetProjectId' in params and params['budgetProjectId']!=run.get('budgetProjectId',run['projectId']):
            raise ValueError('同一计划修订的子集不能替换研究预算')

    def _run(self, params, execution_owner=None):
        if 'selectedStepIds' in params and not isinstance(params['selectedStepIds'],list):raise ValueError('所选步骤必须非空、有效且不重复')
        if 'retryFailed' in params and not isinstance(params['retryFailed'],bool):raise ValueError('retryFailed必须为布尔值')
        if params.get('retryFailed') and not params.get('runId'):raise ValueError('重试失败步骤必须明确runId')
        plan = self._plan(params)
        if not params.get('runId') and params.get('revision', plan['revision']) != plan['revision']:
            raise ValueError('复现计划已有新修订，请刷新后再运行')
        if params.get('runId'):
            run = self._get_run(params)
            self._check_owner(run,execution_owner)
            self._check_budget(run,params)
            if run.get('cancelPending'):raise ValueError('上次停止尚未确认，请先重试停止')
            run_scope(run)
            requested=params.get('selectedStepIds',run['selectedStepIds'])
            if [s['id'] for s in select_steps(run['planSnapshot'],requested)]!=run['selectedStepIds']:raise ValueError('恢复不能改变已冻结的所选步骤')
            if run['status']=='running':self._advance(run)
            if run['status'] in {'completed','running'}:return run
            self._recover_children(run)
            for state in run['steps']:
                if state['status']=='completed' or state['status'] in {'queued','running'}:continue
                if params.get('retryFailed') is True and state.get('jobId'):
                    history=deepcopy(state.get('attemptHistory',[]))
                    history.append({key:deepcopy(value) for key,value in state.items() if key!='attemptHistory'})
                    step_id=state['stepId'];attempt=state.get('attempt',1)+1
                    state.clear();state.update(stepId=step_id,status='pending',attempt=attempt,attemptHistory=history)
                elif not state.get('jobId'):
                    # No task was persisted: finish this same submission/reservation.
                    state['status']='pending'
            run.update(status='running', message='继续冻结版本的未完成步骤')
        else:
            selected=select_steps(plan,params.get('selectedStepIds'))
            selected_ids=[step['id'] for step in selected]
            siblings=[r for r in self.store.list('reproduction_run',plan['projectId']) if r['planId']==plan['id'] and r['revision']==plan['revision']]
            for existing in siblings:
                if run_scope(existing)['selectedStepIds']==selected_ids:
                    self._check_owner(existing,execution_owner)
                    self._check_budget(existing,params)
                    if existing['status']=='running':self._advance(existing)
                    return self._run_view(existing)
            if work_counts(step['spec'] for step in selected)['trials'] > 20:
                raise ValueError('全方案试参总数超过20次，请先调整方案；不会自动拆分或扩大预算')
            if any(not step.get('citations') for step in selected):
                raise ValueError('运行前每个步骤必须有真实研报原文引用')
            from .workbench import strategy_project
            project = strategy_project(self.store, plan['projectId'], plan['strategyId']) if plan.get('strategyId') else self.store.project(plan['projectId'])
            published = reports.get(self.store, plan['reportId']).get('publishedAt')
            for step in selected:
                if step['variant'] == 'post_publication':
                    if step['spec']['kind'] in {'model.train', 'optimize.run'}:
                        raise ValueError('发布后独立验证不可用于训练或寻优，请引用已选定模型或规则')
                    begin = step['spec']['parameters'].get('startDate') or project.get('startDate')
                    if not published or not begin or begin <= published:
                        raise ValueError('发布后验证必须明确使用晚于研报发布日期的验证区间')
            run = dict(id=identifier(), planId=plan['id'], projectId=plan['projectId'], revision=plan['revision'], status='running',
                       planSnapshot=deepcopy(plan), projectSnapshot=deepcopy(project),
                       steps=[dict(stepId=s['id'], status='pending') for s in selected], selectedStepIds=selected_ids, createdAt=now())
            run['runId'] = run['id']
            run['planSnapshot']['publishedAt'] = published
            from .ai_budget import ensure_budget,read_budget
            if siblings:
                budgets={(r.get('budgetId'),r.get('budgetProjectId',plan['projectId'])) for r in siblings}
                if len(budgets)!=1 or next(iter(budgets))[0] is None:raise ValueError('已有修订预算不一致或缺失，不能为子集重置额度')
                budget_id,budget_project=next(iter(budgets))
                if params.get('budgetId',budget_id)!=budget_id or params.get('budgetProjectId',budget_project)!=budget_project:raise ValueError('同一计划修订的子集不能替换研究预算')
                read_budget(self.store.project_store(budget_project).db,budget_id)
            else:
                budget_id=params.get('budgetId') or ('report-'+plan['id']+'-'+str(plan['revision']))
                budget_project=params.get('budgetProjectId',plan['projectId'])
                ensure_budget(self.store.project_store(budget_project).db,budget_id)
            run.update(budgetId=budget_id,budgetProjectId=budget_project)
        if execution_owner is not None:run['executionOwner']=execution_owner
        run['executionActive']=execution_owner is not None
        self._save_run(run)
        self._advance(run)
        return run

    def _get_run(self, params):
        run = self.store.get('reproduction_run', params['runId'])
        if run['projectId'] != params['projectId'] or params.get('planId', run['planId']) != run['planId']:
            raise ValueError('复现运行不属于当前计划或项目')
        return self._run_view(run)

    def _advance(self, run):
        states = {s['stepId']: s for s in run['steps']}
        self._recover_children(run)
        if run.get('cancelPending') or self._owner_cancelled(run):
            self._cancel_run(run);return
        for step in run['planSnapshot']['steps']:
            if step['id'] not in states:continue
            if self._owner_cancelled(run):
                self._cancel_run(run);return
            state = states[step['id']]
            if state['status']=='queued' and state.get('submissionSpec'):
                job=self.jobs.submit(state['submissionSpec'],frozen_project=run['projectSnapshot'],submission_id=state['submissionId'])
                state.update(status=job['status'])
                if job.get('experimentId'):state['experimentId']=job['experimentId']
                if self._owner_cancelled(run):
                    self._cancel_run(run);return
            if state['status'] != 'pending':
                continue
            dependencies = [states[key]['status'] for key in step['dependsOn']]
            if any(s in {'failed', 'cancelled', 'interrupted'} for s in dependencies):
                state.update(status='failed', message='前置步骤未成功，未提交计算')
            elif all(s == 'completed' for s in dependencies):
                spec = deepcopy(step['spec'])
                spec['reproduction'] = dict(planId=run['planId'], revision=run['revision'], reportId=run['planSnapshot']['reportId'], variant=step['variant'], runId=run['id'], stepId=step['id'], attempt=state.get('attempt',1))
                try:
                    reference = spec['parameters'].get('modelExperimentId')
                    if isinstance(reference, str) and reference.startswith('$step:'):
                        source_id = reference.removeprefix('$step:')
                        if source_id not in step['dependsOn'] or not states[source_id].get('experimentId'):
                            raise ValueError('模型实验引用必须指向已完成的直接依赖步骤')
                        spec['parameters']['modelExperimentId'] = states[source_id]['experimentId']
                    if step['variant'] == 'post_publication' and spec['parameters'].get('modelExperimentId'):
                        model = self.store.experiment(run['projectId'], spec['parameters']['modelExperimentId'])
                        selected = model['parameters']
                        boundary = run['planSnapshot'].get('publishedAt') or reports.get(self.store, run['planSnapshot']['reportId']).get('publishedAt')
                        if not selected.get('trainEnd') or not selected.get('validEnd') or max(selected['trainEnd'], selected['validEnd']) > boundary or selected.get('validation', {}).get('mode') == 'rolling':
                            raise ValueError('发布后独立验证只能引用训练与选参结束不晚于发布日期的固定模型')
                    if run.get('budgetId'):
                        spec.setdefault('parameters',{}).update(budgetId=run['budgetId'],budgetProjectId=run.get('budgetProjectId',run['projectId']))
                    state['submissionSpec']=deepcopy(spec)
                    state.setdefault('attempt',1)
                    state.setdefault('submissionId',identifier())
                    self._save_run(run)
                    budget = reproduction_budget(self.store, run)
                    if budget['reserved']['trials'] + work_counts([spec])['trials'] > budget['trialLimit']:
                        raise ValueError('本方案试参预算已用尽；失败和重跑计入预算，已有结果保留')
                    if run.get('budgetId') and spec['kind']=='optimize.run':
                        from .ai_budget import reserve
                        reserve(self.store.project_store(run.get('budgetProjectId',run['projectId'])).db,run['budgetId'],
                                'trials',work_counts([spec])['trials'],operation_id='report-submit-'+state['submissionId'])
                    job = self.jobs.submit(spec, frozen_project=run['projectSnapshot'], submission_id=state['submissionId'])
                    state.update(jobId=job['id'], status=job['status'])
                    if self._owner_cancelled(run):
                        self._cancel_run(run);return
                except Exception as exc:
                    from .report_ai import safe_step_message
                    state.update(status='failed',message=safe_step_message(exc))
                self._save_run(run)
        if all(s['status'] not in {'pending', 'queued', 'running'} for s in run['steps']):
            run['status'] = 'completed' if all(s['status'] == 'completed' for s in run['steps']) else 'failed'
            scope=run_scope(run)
            completed=f"所选{len(run['steps'])}/{len(run['planSnapshot']['steps'])}步完成，未执行其余步骤；结论仍须检查实际实验" if scope['executionScope']=='subset' else '所有步骤已完成，研究结论仍须检查实际实验'
            run['message']=completed if run['status']=='completed' else '本次所选步骤部分未成功，依赖这些步骤的计算未提交'
        self._save_run(run)

    def dispatch(self, method, params):
        with self.lock:
            if method == 'reports.search':
                return reports.search(self.store, params)
            if method == 'reports.get':
                return reports.get(self.store, params['reportId'])
            if method == 'reports.metadata.save':
                value = reports.get(self.store, params['reportId'])
                patch = params.get('patch', {})
                if not isinstance(patch, dict):
                    raise ValueError('元信息必须为对象')
                for key in ('title', 'institution', 'authors', 'publishedAt'):
                    if key in patch:
                        value[key] = deepcopy(patch[key])
                if not isinstance(value.get('title'), str) or not value['title'].strip():
                    raise ValueError('研报标题不能为空')
                if value.get('publishedAt'):
                    date.fromisoformat(value['publishedAt'])
                if value.get('authors') is not None and (not isinstance(value['authors'], list) or any(not isinstance(a, str) for a in value['authors'])):
                    raise ValueError('作者必须为文字数组')
                return self.store.put('report', value)
            if method == 'reports.pages':
                return reports.pages(self.store, params)
            if method == 'reports.document':
                return reports.document(self.store, params['reportId'])
            if method in {'reports.import', 'reports.ocr', 'reports.refresh'}:
                return self.jobs.submit({'kind': method, 'name': {'reports.import': '导入研报', 'reports.ocr': '研报 OCR', 'reports.refresh': '刷新研报目录'}[method], 'parameters': params})
            if method == 'reports.subscriptions.list':
                return self.store.list('report_subscription')
            if method == 'reports.subscriptions.save':
                value = deepcopy(params['subscription'])
                value['id'] = value.get('id') or identifier()
                if not value.get('name') or not isinstance(value.get('query'), dict):
                    raise ValueError('订阅需要名称与搜索条件')
                # Preserve runtime fields; callers may only edit the subscription definition.
                try:
                    saved = self.store.get('report_subscription', value['id'])
                except ValueError:
                    saved = {'id': value['id']}
                saved.update({k: value[k] for k in ('name', 'query', 'enabled') if k in value})
                saved.setdefault('enabled', True)
                saved['query'].setdefault('startDate', (date.today() - timedelta(days=365)).isoformat())
                return self.store.put('report_subscription', saved)
            if method == 'reports.subscriptions.delete':
                self.store.delete('report_subscription', params['subscriptionId'])
                return {'deleted': True}
            if method == 'reports.subscriptions.refresh':
                return self._refresh_subscription(self.store.get('report_subscription', params['subscriptionId']))
            if method == 'reproductions.list':
                return [plan_readiness(p) for p in self.store.project_store(params['projectId']).list('reproduction',params['projectId'])]
            if method == 'reproductions.runs':
                return [self._run_view(r) for r in self.store.list('reproduction_run',params['projectId']) if r['planId']==params['planId']]
            if method == 'reproductions.get':
                return self._plan(params)
            if method == 'reproductions.save':
                return self._save_plan(params)
            if method == 'reproductions.run':
                return self._run(params)
            if method == 'reproductions.status':
                return self._get_run(params)
            if method == 'reproductions.cancel':
                return self._cancel_run(self._get_run(params))
        raise ValueError('未知研报操作')
