"""Small service scheduler; all expensive report work remains in existing Jobs."""
from copy import deepcopy
from datetime import date, timedelta
from threading import Event, RLock, Thread

from . import reports
from .jobs import validate_spec
from .storage import identifier, now, read_json
from .research_costs import work_counts, reproduction_budget


def validate_step_dates(plan):
    if plan.get('missingConditions'):
        return
    for step in plan['steps']:
        kind, params = step['spec']['kind'], step['spec']['parameters']
        if kind not in {'factor.analyze', 'backtest.run', 'model.train', 'optimize.run'}:
            continue
        keys = ('trainStart', 'trainEnd', 'validStart', 'validEnd', 'testStart', 'testEnd') if kind == 'model.train' else ('startDate', 'endDate')
        if any(not params.get(key) for key in keys):
            if kind == 'model.train':
                raise ValueError('模型步骤必须在 spec.parameters 明确 trainStart/trainEnd/validStart/validEnd/testStart/testEnd；尚未确定时填 missingConditions')
            raise ValueError('计算步骤必须在 spec.parameters 明确 startDate/endDate，不能只写 objective；尚未确定时填 missingConditions')
        try:
            dates = [date.fromisoformat(params[key]) if isinstance(params[key], str) and len(params[key]) == 10 else None for key in keys]
            if any(d is None for d in dates) or any(dates[i] > dates[i + 1] for i in range(0, len(dates), 2)):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('步骤日期必须为 YYYY-MM-DD，且开始日期不得晚于结束日期') from None


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

    def _save_run(self, run):
        run['budget'] = reproduction_budget(self.store, run)
        self.store.put('reproduction_run', run, run['projectId'])
        if self.emitted.get(run['id']) != run['status']:
            self.emitted[run['id']] = run['status']
            emit = getattr(self.service, 'emit', lambda value: None)
            emit(dict(kind='reproduction.execution', id=run['id'], planId=run['planId'], projectId=run['projectId'], status=run['status'], message=run.get('message')))

    def _loop(self):
        while not self.stop.wait(1):
            with self.lock:
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
        return self.store.project_store(project_id).get('reproduction', params['planId'])

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
        steps = value['steps']
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
            spec = step['spec']
            if spec.get('projectId') not in (None, project_id):
                raise ValueError('步骤必须属于当前研究项目')
            spec['projectId'] = project_id
            if spec.get('strategyId') not in (None, value.get('strategyId')):
                raise ValueError('步骤策略必须与计划一致')
            spec['strategyId'] = value.get('strategyId')
            validate_spec(spec)
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
        return portable.put('reproduction', value, project_id)

    def _run(self, params):
        plan = self._plan(params)
        if not params.get('runId') and params.get('revision', plan['revision']) != plan['revision']:
            raise ValueError('复现计划已有新修订，请刷新后再运行')
        if params.get('runId'):
            run = self._get_run(params)
            validate_step_dates(run['planSnapshot'])
            if run['status'] in {'completed', 'running'}:
                return run
            # Resume the frozen revision, never silently switch to today's edited plan.
            for state in run['steps']:
                if state['status'] != 'completed':
                    if state.get('jobId'):
                        prior = self.store.get('job', state['jobId'])
                        if prior['status'] == 'completed':
                            state.update(status='completed', experimentId=prior.get('experimentId'))
                            continue
                        if prior['status'] in {'queued', 'running'}:
                            state['status'] = prior['status']
                            continue
                    state.clear()
                    # Re-populated below by position; successful state retains its IDs.
            for state, step in zip(run['steps'], run['planSnapshot']['steps']):
                if not state:
                    state.update(stepId=step['id'], status='pending')
            run.update(status='running', message='继续冻结版本的未完成步骤')
        else:
            for existing in self.store.list('reproduction_run', plan['projectId']):
                if existing['planId'] == plan['id'] and existing['revision'] == plan['revision']:
                    return existing
            if not plan['steps'] or plan['missingConditions']:
                raise ValueError('请先补全复现步骤与缺失条件')
            validate_step_dates(plan)
            if work_counts(step['spec'] for step in plan['steps'])['trials'] > 20:
                raise ValueError('全方案试参总数超过20次，请先调整方案；不会自动拆分或扩大预算')
            if any(not step.get('citations') for step in plan['steps']):
                raise ValueError('运行前每个步骤必须有真实研报原文引用')
            from .workbench import strategy_project
            project = strategy_project(self.store, plan['projectId'], plan['strategyId']) if plan.get('strategyId') else self.store.project(plan['projectId'])
            published = reports.get(self.store, plan['reportId']).get('publishedAt')
            for step in plan['steps']:
                if step['variant'] == 'post_publication':
                    if step['spec']['kind'] in {'model.train', 'optimize.run'}:
                        raise ValueError('发布后独立验证不可用于训练或寻优，请引用已选定模型或规则')
                    begin = step['spec']['parameters'].get('startDate') or project.get('startDate')
                    if not published or not begin or begin <= published:
                        raise ValueError('发布后验证必须明确使用晚于研报发布日期的验证区间')
            run = dict(id=identifier(), planId=plan['id'], projectId=plan['projectId'], revision=plan['revision'], status='running',
                       planSnapshot=deepcopy(plan), projectSnapshot=deepcopy(project),
                       steps=[dict(stepId=s['id'], status='pending') for s in plan['steps']], createdAt=now())
            run['runId'] = run['id']
            run['planSnapshot']['publishedAt'] = published
            from .ai_budget import ensure_budget
            run['budgetId']=params.get('budgetId') or ('report-'+run['id'])
            run['budgetProjectId']=params.get('budgetProjectId',plan['projectId'])
            ensure_budget(self.store.project_store(run['budgetProjectId']).db,run['budgetId'])
        self._save_run(run)
        self._advance(run)
        return run

    def _get_run(self, params):
        run = self.store.get('reproduction_run', params['runId'])
        if run['projectId'] != params['projectId'] or params.get('planId', run['planId']) != run['planId']:
            raise ValueError('复现运行不属于当前计划或项目')
        return run

    def _advance(self, run):
        states = {s['stepId']: s for s in run['steps']}
        # Recover a submitted child even if the service stopped before persisting its ID.
        for job in self.store.list('job', run['projectId']):
            link = job.get('spec', {}).get('reproduction', {})
            if link.get('runId') == run['id'] and link.get('stepId') in states:
                state = states[link['stepId']]
                if state['status'] == 'pending' and not state.get('jobId') and job['status'] in {'running', 'queued', 'completed'}:
                    state.update(jobId=job['id'], status=job['status'])
                    if job.get('experimentId'):
                        state['experimentId'] = job['experimentId']
        for state in run['steps']:
            if state.get('jobId') and state['status'] in {'queued', 'running'}:
                job = self.store.get('job', state['jobId'])
                state.update(status=job['status'])
                if job.get('experimentId'):
                    state['experimentId'] = job['experimentId']
        for step in run['planSnapshot']['steps']:
            state = states[step['id']]
            if state['status'] != 'pending':
                continue
            dependencies = [states[key]['status'] for key in step['dependsOn']]
            if any(s in {'failed', 'cancelled', 'interrupted'} for s in dependencies):
                state.update(status='failed', message='前置步骤未成功，未提交计算')
            elif all(s == 'completed' for s in dependencies):
                spec = deepcopy(step['spec'])
                spec['reproduction'] = dict(planId=run['planId'], revision=run['revision'], reportId=run['planSnapshot']['reportId'], variant=step['variant'], runId=run['id'], stepId=step['id'])
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
                    budget = reproduction_budget(self.store, run)
                    if budget['reserved']['trials'] + work_counts([spec])['trials'] > budget['trialLimit']:
                        raise ValueError('本方案试参预算已用尽；失败和重跑计入预算，已有结果保留')
                    if run.get('budgetId') and spec['kind']=='optimize.run':
                        from .ai_budget import reserve
                        reserve(self.store.project_store(run.get('budgetProjectId',run['projectId'])).db,run['budgetId'],
                                'trials',work_counts([spec])['trials'],operation_id='report-submit-'+identifier())
                    if run.get('budgetId'):
                        spec.setdefault('parameters',{}).update(budgetId=run['budgetId'],
                            budgetProjectId=run.get('budgetProjectId',run['projectId']))
                    job = self.jobs.submit(spec, frozen_project=run['projectSnapshot'])
                    state.update(jobId=job['id'], status=job['status'])
                except Exception as exc:
                    state.update(status='failed', message=str(exc))
                self._save_run(run)
        if all(s['status'] not in {'pending', 'queued', 'running'} for s in run['steps']):
            run['status'] = 'completed' if all(s['status'] == 'completed' for s in run['steps']) else 'failed'
            run['message'] = '所有步骤已完成，研究结论仍须检查实际实验' if run['status'] == 'completed' else '部分步骤未成功，依赖这些步骤的计算未提交'
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
                return self.store.project_store(params['projectId']).list('reproduction', params['projectId'])
            if method == 'reproductions.runs':
                return [r for r in self.store.list('reproduction_run', params['projectId']) if r['planId'] == params['planId']]
            if method == 'reproductions.get':
                return self._plan(params)
            if method == 'reproductions.save':
                return self._save_plan(params)
            if method == 'reproductions.run':
                return self._run(params)
            if method == 'reproductions.status':
                return self._get_run(params)
            if method == 'reproductions.cancel':
                run = self._get_run(params)
                run.update(status='cancelled', message='复现已停止，已完成实验保留')
                self._save_run(run)
                for state in run['steps']:
                    if state.get('jobId') and state['status'] in {'running', 'queued'}:
                        job = self.store.get('job', state['jobId'])
                        if job['status'] == 'completed':
                            state.update(status='completed', experimentId=job.get('experimentId'))
                        else:
                            self.jobs.cancel(state['jobId'])
                    if state['status'] != 'completed':
                        state['status'] = 'cancelled'
                self._save_run(run)
                return run
        raise ValueError('未知研报操作')
