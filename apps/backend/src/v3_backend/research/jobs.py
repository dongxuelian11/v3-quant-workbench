"""Persisted research subprocesses sharing one local writer queue."""
from __future__ import annotations
import copy
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .storage import Store, identifier, now, read_json, write_json

KINDS = {'data.import', 'data.update', 'factor.analyze', 'backtest.run', 'model.train', 'optimize.run', 'selection.run', 'screener.run', 'simulation.advance', 'rdagent.run', 'reports.import', 'reports.ocr', 'reports.refresh'}
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}


def validate_spec(spec):
    if not isinstance(spec, dict) or spec.get('kind') not in KINDS or not isinstance(spec.get('parameters'), dict) or (spec.get('projectId') is not None and not isinstance(spec.get('projectId'), str)):
        raise ValueError('任务参数无效')
    p, kind = spec['parameters'], spec['kind']
    if kind=='data.update' and p.get('quoteOnly'):
        from .quotes import instrument
        instrument(p.get('instrument'))
    required = {'data.import': ['files'], 'data.update': ['startDate'], 'factor.analyze': ['factorIds'],
                'backtest.run': ['template'], 'model.train': ['model', 'factorIds'],
                'selection.run': [], 'screener.run': ['plan'], 'simulation.advance': ['accountId'], 'rdagent.run': ['objective','action'],
                'optimize.run': ['target', 'sampler', 'baseParameters', 'searchSpace'],
                'reports.import': [], 'reports.ocr': ['reportId', 'pages'], 'reports.refresh': []}[kind]
    if kind=='data.update' and p.get('quoteOnly'):required=[]
    if any(key not in p for key in required):
        raise ValueError('任务缺少参数: ' + ', '.join(key for key in required if key not in p))
    rule_strategy = bool(p.get('rules') or str(p.get('dailyCode') or '').strip())
    if kind in {'factor.analyze', 'model.train'} or kind == 'backtest.run' and p.get('template') != 'model_score' and not rule_strategy:
        if not isinstance(p.get('factorIds'), list) or not p['factorIds'] or any(not isinstance(value, str) for value in p['factorIds']):
            raise ValueError('任务需要非空 factorIds 数组')
    if kind == 'data.import' and (not isinstance(p['files'], list) or not p['files']):
        raise ValueError('请选择导入文件')
    if kind == 'data.update' and p.get('source', 'baostock') not in {'baostock', 'akshare'}:
        raise ValueError('未知数据源')
    if kind == 'backtest.run' and p['template'] not in {'single_factor', 'multi_factor', 'model_score'}:
        raise ValueError('未知组合模板')
    if kind == 'simulation.advance':
        if not isinstance(p['accountId'], str) or not p['accountId']:
            raise ValueError('请选择模拟账户及所属项目')
        if p.get('projectId') not in (None, spec.get('projectId')):
            raise ValueError('模拟账户项目与任务不一致')
    if kind == 'rdagent.run':
        from .rd_agent import validate
        if not spec.get('projectId'): raise ValueError('原生研究需要所属项目')
        validate(p)
    return spec


class Jobs:
    def __init__(self, store, emit):
        self.store, self.emit = store, emit
        self.lock = threading.RLock()
        self.processes = {}
        self.closed = False
        for job in store.list('job'):
            recovery_folder=None
            if job['status'] in {'queued','running'} or job.get('cleanupPending'):
                try:
                    recovery_folder=Path(store.project(job.get('projectId'))['path'])/'.research/runs'/job['id']
                except (ValueError,KeyError,TypeError):
                    pass
            native_pending=job['kind']=='rdagent.run' or bool(recovery_folder and (recovery_folder/'rd_native_children.json').is_file())
            if native_pending and (job['status'] in {'queued','running'} or job.get('cleanupPending')):
                from .rd_agent import stop
                try:
                    if recovery_folder is None:raise ValueError('原生任务所属项目不可用，无法定位进程记录')
                    stop(recovery_folder)
                except Exception as exc:
                    self.closed=True
                    self._save(job,status='failed',cleanupPending=True,message='上次原生进程清理未确认，暂停新任务：'+str(exc))
                    continue
            if job['status'] in {'queued', 'running'}:
                exited = read_json(recovery_folder / 'process-exit.json', {}) if recovery_folder else {}
                if exited.get('cleanupConfirmed') and (recovery_folder / 'result.json').is_file():
                    self._save(job, status='failed', registrationPending=True, message='上次进程已退出，结果尚未登记；可恢复登记')
                else:
                    self._save(job, status='interrupted', message='上次运行中断，可用原参数重新运行')

    @staticmethod
    def public_event(job):
        parameters=job.get('spec',{}).get('parameters',{})
        default=1 if parameters.get('scheduledUpdateId') else 0
        return {**job,'priority':job.get('queuePriority',default)}

    def _save(self, job, **changes):
        job = {**job, **changes, 'updatedAt': now()}
        self.store.put('job', job, job.get('projectId') or '')
        self.store.project_store(job.get('projectId')).put('job', job, job.get('projectId') or '')
        if job['status'] in TERMINAL:
            self._retain_stage_job(job)
        self.emit(self.public_event(job))
        return job

    def _retain_stage_job(self, job):
        # Conversations keep their result links even when task history is cleared.
        from .workbench import _legacy_conversations
        _legacy_conversations(self.store)
        event = {key: job[key] for key in (
            'id', 'projectId', 'strategyId', 'kind', 'name', 'status', 'progress',
            'message', 'experimentId', 'createdAt', 'updatedAt',
        ) if key in job}
        event['priority']=self.public_event(job)['priority']
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for key, body in db.execute("SELECT id, body FROM records WHERE kind='conversation'").fetchall():
                conversation = json.loads(body)
                state = conversation.get('state', {})
                if job['id'] not in state.get('stageJobIds', []):
                    continue
                retained = {item['id']: item for item in state.get('stageEvents', []) if isinstance(item, dict) and item.get('id')}
                retained[job['id']] = event
                state['stageEvents'] = list(retained.values())
                conversation['state'] = state
                db.execute("UPDATE records SET body=? WHERE kind='conversation' AND id=?",
                           (json.dumps(conversation, ensure_ascii=False, allow_nan=False), key))

    def _records(self, filters, recent_since=None):
        clauses, values = ['kind=?'], ['job']
        if recent_since is not None:
            visible = ["json_extract(body, '$.createdAt') >= ?", "json_extract(body, '$.status') IN ('queued','running')",
                       "json_extract(body, '$.registrationPending') = 1", "json_extract(body, '$.cleanupPending') = 1"]
            values.append(recent_since)
            active = list(self.processes)
            if active:
                visible.append('id IN (' + ','.join('?' for _ in active) + ')')
                values.extend(active)
            clauses.append('(' + ' OR '.join(visible) + ')')
        if filters.get('projectId') is not None:
            clauses.append('project=?')
            values.append(filters['projectId'])
        if filters.get('strategyId') is not None:
            clauses.append("json_extract(body, '$.strategyId')=?")
            values.append(filters['strategyId'])
        statuses = filters.get('statuses')
        if statuses is None and filters.get('status'):
            statuses = [filters['status']]
        if statuses is not None:
            if not isinstance(statuses, list) or any(s not in TERMINAL | {'queued', 'running'} for s in statuses):
                raise ValueError('任务状态筛选无效')
            if not statuses:
                return []
            clauses.append("json_extract(body, '$.status') IN (" + ','.join('?' for _ in statuses) + ')')
            values.extend(statuses)
        if filters.get('before'):
            clauses.append("json_extract(body, '$.createdAt') < ?")
            values.append(filters['before'])
        sql = 'SELECT body FROM records WHERE ' + ' AND '.join(clauses)
        sql += " ORDER BY json_extract(body, '$.createdAt') DESC, id DESC LIMIT ? OFFSET ?"
        values.extend([max(1, min(1000, int(filters['limit']))) if filters.get('limit') is not None else -1,
                       max(0, int(filters.get('offset', 0)))])
        with self.store.connect() as db:
            rows = db.execute(sql, values).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list(self, filters=None):
        filters = filters or {}
        if type(filters.get('allHistory', False)) is not bool:
            raise ValueError('allHistory 必须为布尔值')
        since = None if filters.get('allHistory') else (datetime.fromisoformat(now()) - timedelta(days=30)).isoformat()
        jobs = self._records(filters, recent_since=since)
        available = {}
        for job in jobs:
            key = job.get('projectId')
            if job.get('experimentId'):
                if key not in available:
                    try:
                        available[key] = {e['id'] for e in self.store.experiments(key)}
                    except (ValueError, OSError):
                        available[key] = set()
                job['resultAvailable'] = job['experimentId'] in available[key]
        return [self.public_event(job) for job in jobs]

    def clear(self, filters=None):
        filters = filters or {}
        keys = filters.get('jobIds')
        if keys is not None and (not isinstance(keys, list) or any(not isinstance(k, str) for k in keys)):
            raise ValueError('请选择需要清理的任务记录')
        removed, skipped = [], []
        with self.lock:
            query = {k: v for k, v in filters.items() if k not in {'jobIds', 'offset', 'limit'}}
            if keys is None and 'statuses' not in query and 'status' not in query:
                query['statuses'] = sorted(TERMINAL)
            selected = {job['id']: job for job in self._records(query)}
            for key in dict.fromkeys(keys if keys is not None else selected):
                job = selected.get(key)
                # A cancelled process can still be writing its final status.
                if not job or job['status'] not in TERMINAL or key in self.processes or job.get('registrationPending') or job.get('cleanupPending'):
                    skipped.append(key)
                    continue
                try:
                    portable = self.store.project_store(job.get('projectId'))
                    self._retain_stage_job(job)
                    portable.delete('job', key)
                except (ValueError, OSError):
                    skipped.append(key)
                    continue
                self.store.delete('job', key)
                removed.append(key)
        return {'removedIds': removed, 'skippedIds': skipped}

    def submit(self, spec, frozen_project=None, *, submission_id=None):
        if submission_id is None:
            return self._submit(spec, frozen_project)
        # Internal AI intent only; not read from the public job spec.
        import hashlib
        intent = hashlib.sha256(json.dumps({'spec': {key: value for key, value in spec.items() if key != 'name'}, 'project': frozen_project},
            sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
        with self.lock:
            try:
                existing = self.store.get('job', submission_id)
            except ValueError:
                existing = None
            if existing is not None:
                if existing.get('submissionIntent') != intent:
                    raise ValueError('任务提交标识对应不同的执行意图或研究范围')
                if existing['status'] == 'queued':
                    self._start_next(existing.get('projectId'))
                    existing = self.store.get('job', submission_id)
                return self.public_event(existing)
            return self._submit(spec, frozen_project, submission_id=submission_id, submission_intent=intent)

    def _submit(self, spec, frozen_project=None, *, submission_id=None, submission_intent=None):
        spec = copy.deepcopy(spec)
        replay_project = None
        if isinstance(spec, dict) and spec.get('inputExperimentId'):
            if spec.get('kind') not in {'factor.analyze','model.train','backtest.run','optimize.run'} or not spec.get('projectId'):
                raise ValueError('此任务不支持原输入复现')
            original = self.store.experiment(spec['projectId'], spec['inputExperimentId'])
            if original.get('kind') != spec['kind']:
                raise ValueError('原输入复现必须使用原实验的任务类型')
            from .input_snapshot import restore
            replay_project, parameters, _ = restore(self.store, self.store.project(spec['projectId']), spec['inputExperimentId'])
            if spec.get('strategyId') not in (None, replay_project.get('strategyId')):
                raise ValueError('原输入复现不能改换研究策略')
            spec['strategyId'] = replay_project.get('strategyId')
            spec['parameters'] = parameters
            spec.pop('candidateId', None)
        validate_spec(spec)
        if spec['kind'] == 'reports.refresh':
            spec['parameters'].setdefault('_refreshId', identifier())
        if spec['kind']=='data.update' and spec['parameters'].get('quoteOnly'):
            from .quotes import instrument
            target=instrument(spec['parameters']['instrument'])
            for existing in self.store.list('job'):
                prior=existing.get('spec',{}).get('parameters',{})
                if existing['status'] in {'queued','running'} and existing['kind']=='data.update' and prior.get('quoteOnly'):
                    old_target=instrument(prior['instrument'])
                    if (target['kind'],target['symbol'])==(old_target['kind'],old_target['symbol']) and all(prior.get(key)==spec['parameters'].get(key) for key in ('startDate','endDate')):
                        return existing
        for key in ('projectSnapshot','positionsSnapshot','strategySnapshots','dailyPlanSnapshots','candidateSnapshot','accountSnapshot','positionsSourceResolved'):
            spec.pop(key,None)
        if spec['kind'] == 'simulation.advance':
            if not spec['parameters'].get('endDate'):
                raise ValueError('推进模拟账户前请明确选择结束日期')
            from .simulation import dispatch
            account = dispatch(self.store, 'simulation.accounts.get', {
                'projectId': spec.get('projectId'), 'accountId': spec['parameters']['accountId']})
            if spec.get('strategyId') not in (None, account['strategyId']):
                raise ValueError('模拟任务策略与账户不一致')
            if account['paused']:
                raise ValueError('模拟账户已暂停，请先恢复')
            spec['strategyId'] = account['strategyId']
            spec['parameters']['projectId'] = spec.get('projectId')
            if not spec.get('projectId'):
                from .simulation_accounts import revision
                revision(account,spec['parameters'].get('expectedRevision'))
                spec['accountSnapshot']=copy.deepcopy(account)
                if not account['bindings'] and not any(h['quantity'] or h.get('pendingQuantity',0) for h in account['state']['holdings'].values()):
                    from .preparation import trading_dates
                    from .data import project_data
                    from .selection import update_end_date
                    end=min(str(spec['parameters']['endDate'])[:10],update_end_date())
                    spec['accountSnapshot']['calendarSnapshot']=trading_dates(Path(project_data(self.store.project(None))['path'])/'data',account['startDate'],end,source='file',update_data=False)
                spec['parameters']['_advanceJobId']=identifier()
            spec['parameters'].setdefault('startDate',account['startDate'])
        if spec.get('candidateId'):
            from .candidates import get
            candidate = get(self.store, spec.get('projectId'), spec['candidateId'])
            if candidate.get('strategyId') != spec.get('strategyId') or candidate['spec']['kind'] != spec['kind'] or candidate['spec']['parameters'] != spec['parameters']:
                raise ValueError('候选已经变更，请保存当前候选后再运行')
            spec['candidateSnapshot'] = candidate
        from .workbench import strategy_project, get_strategy
        project_id = spec.get('projectId')
        project = replay_project or (strategy_project(self.store, project_id, spec['strategyId'], active=spec['kind']=='selection.run') if project_id and spec.get('strategyId') else copy.deepcopy(self.store.project(project_id)))
        if frozen_project is not None and replay_project is None:
            if frozen_project.get('id')!=project_id or frozen_project.get('strategyId')!=spec.get('strategyId'):
                raise ValueError('冻结研究范围与任务不一致')
            project=copy.deepcopy(frozen_project)
        from .preparation import KINDS as prepared_kinds, scope
        if spec['kind'] in prepared_kinds and replay_project is None and not (spec['kind']=='simulation.advance' and not project_id):
            scope(project,spec['parameters'],spec['kind'])
        if replay_project is None:
            from .app_settings import source_settings
            project.setdefault('settings',{})['dataSources']=source_settings(self.store.settings())
        self._freeze_universe(project)
        spec['projectSnapshot'] = project
        if project_id and project.get('strategyId'):
            spec['strategyId'] = project['strategyId']
        if spec['kind'] == 'selection.run':
            from .positions import get
            source=copy.deepcopy(spec['parameters'].get('positionsSource',{'kind':'none'}))
            if not isinstance(source,dict) or source.get('kind') not in {'none','actual','simulation'}:raise ValueError('持仓来源无效')
            spec['positionsSourceResolved']=source
            if source['kind']=='simulation':
                if spec.get('projectId'):raise ValueError('共享账户研究请从全局每日研究入口运行')
                if spec.get('strategyId') or spec['parameters'].get('dailyPlanIds') or spec['parameters'].get('strategies'):
                    raise ValueError('账户研究使用已绑定固定版本，请取消自由方案选择')
                from .simulation_accounts import get as get_account
                account=get_account(self.store,source)
                if account.get('schemaVersion')!=2:raise ValueError('旧账户请先显式迁入后使用固定规则研究')
                spec['accountSnapshot']=copy.deepcopy(account)
                spec['positionsSnapshot']=dict(cash=account['cash'],asOfDate=account['asOfDate'],rows=[dict(symbol=s,**h) for s,h in account['state']['holdings'].items()])
                spec['positionsSourceResolved'].update(revision=account['revision'],asOfDate=account['asOfDate'])
            elif source['kind']=='actual':
                spec['positionsSnapshot']=get(self.store.project(None) if ('strategies' in spec['parameters'] or 'dailyPlanIds' in spec['parameters']) else project)
            else:
                spec['positionsSnapshot']=dict(cash=float(project.get('settings',{}).get('backtest',{}).get('capital',1000000)),rows=[],asOfDate=None)
            if source['kind']=='simulation':
                spec['parameters'].pop('dailyPlanIds',None);spec['parameters'].pop('strategies',None)
            if 'dailyPlanIds' in spec['parameters']:
                if 'strategies' in spec['parameters'] or spec.get('strategyId'):
                    raise ValueError('每日方案与旧策略引用不能混用')
                if spec['parameters'].get('allowPartial'):
                    raise ValueError('每日组合不能使用已有数据预览')
                from .daily_plans import freeze
                spec['dailyPlanSnapshots']=freeze(self.store,spec['parameters']['dailyPlanIds'],project['settings']['dataSources'],
                    freeze_universe=self._freeze_universe)
            references = spec['parameters'].get('strategies', [])
            if 'strategies' in spec['parameters']:
                import math
                if not isinstance(references,list) or any(not isinstance(item,dict) for item in references):
                    raise ValueError('策略引用必须为数组')
                allocations = [item.get('allocation', 0) for item in references]
                if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x < 0 for x in allocations):
                    raise ValueError('策略资金占比必须为有限非负数')
                if not 0 < sum(allocations) <= 1 + 1e-9:
                    raise ValueError('策略资金占比合计必须大于0且不超过100%')
                if len({(item.get('projectId'),item.get('strategyId')) for item in references}) != len(references):
                    raise ValueError('不可重复分配同一策略')
                frozen = []
                for reference,allocation in zip(references,allocations):
                    if allocation == 0:
                        continue
                    strategy = get_strategy(self.store,reference['projectId'],reference['strategyId'])
                    if not strategy.get('enabled') or not strategy.get('active'):
                        raise ValueError('所选策略尚未启用')
                    scoped = strategy_project(self.store,reference['projectId'],reference['strategyId'],active=True)
                    scoped.setdefault('settings',{})['dataSources']=copy.deepcopy(project['settings']['dataSources'])
                    self._freeze_universe(scoped)
                    frozen.append({**reference,'project':scoped})
                spec['strategySnapshots'] = frozen
        with self.lock:
            if self.closed:
                raise ValueError('任务服务已关闭')
            from .resources import compute_settings
            spec['effectiveResources'] = compute_settings(self.store.settings().get('compute'), os.cpu_count())
            job = dict(id=submission_id or identifier(), projectId=spec.get('projectId'), kind=spec['kind'], name=spec.get('name') or spec['kind'],
                       strategyId=spec.get('strategyId'), status='queued', progress=0, message='等待执行', createdAt=now(), updatedAt=now(), spec=spec,
                       effectiveResources=spec['effectiveResources'])
            if submission_id is not None:job['submissionIntent'] = submission_intent
            job = self._save(job)
            self._start_next(spec.get('projectId'))
            return self.public_event(self.store.get('job', job['id']))

    def _freeze_universe(self, project):
        query = project.get('universe', {}).get('query')
        if query and query.get('watchlistId'):
            watchlist = self.store.get('watchlist', query['watchlistId'])
            symbols = set(watchlist['symbols'])
            if query.get('symbols') is not None:
                symbols &= set(query['symbols'])
            query['symbols'] = sorted(symbols)
            query.pop('watchlistId')

    def _start_next(self, project_id):
        from .resources import compute_settings, compatible
        if self.closed:
            return
        records = self.store.list('job')
        running = [job for job in records if job['id'] in self.processes]
        if len(running) != len(self.processes):
            return  # Missing process ownership must not grant another slot.
        queued = sorted((job for job in records if job['status']=='queued'), key=lambda j:(
            j.get('queuePriority',1 if j.get('spec',{}).get('parameters',{}).get('scheduledUpdateId') else 0),j.get('createdAt','')))
        for job in queued:
            config = job.get('effectiveResources') or compute_settings(None, os.cpu_count())
            active = [r.get('effectiveResources') or compute_settings(None, os.cpu_count()) for r in running]
            limit = min([config['maxConcurrentJobs']] + [r['maxConcurrentJobs'] for r in active])
            if len(running) >= limit or sum(r['threadsPerJob'] for r in active) + config['threadsPerJob'] > max(1, os.cpu_count() or 1):
                continue
            if not compatible(job, running):
                continue
            self._launch(job, config)
            if job['id'] in self.processes:
                running.append(job)

    def _launch(self, job, config):
        project_id = job.get('projectId')
        directory = Path(self.store.project(project_id)['path']) / '.research' / 'runs' / job['id']
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / 'request.json', {'appData': str(self.store.root), 'job': job})
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        from .resources import environment
        env.update(environment(config))
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2]) + os.pathsep + env.get('PYTHONPATH', '')
        log = (directory / 'worker.log').open('wb')
        try:
            process = subprocess.Popen([sys.executable, '-m', 'v3_backend.research.worker', str(directory)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception as exc:
            log.close()
            self._save(job, status='failed', message=str(exc))
            return
        self.processes[job['id']] = process
        try:
            self._save(job, status='running', message='子进程运行中', effectiveResources=config)
        finally:
            threading.Thread(target=self._watch, args=(job['id'], process, directory, log), daemon=True).start()

    def _register_result(self, job, directory, returncode):
        result = read_json(directory / 'result.json')
        if result and result.get('experiment') and (returncode == 0 or job['kind'] in {'rdagent.run','data.import'}):
            experiment = result['experiment']
            if experiment.get('id') != job['id'] or experiment.get('projectId') != job.get('projectId'):
                raise ValueError('结果文件与任务或项目不一致，不能登记')
            for artifact in experiment.get('artifacts', []):
                path = self.store.artifact_path(job.get('projectId'), artifact)
                if not path.is_file():
                    raise ValueError(f"结果文件缺失，不能登记完成：{artifact.get('name', path.name)}")
            try:
                existing = self.store.experiment(job.get('projectId'), experiment['id'])
            except ValueError as exc:
                if str(exc) != f"experiment 不存在: {experiment['id']}":
                    raise
                existing = None
            # Registration can succeed before the final job update fails. Repeating
            # recovery must keep subsequent user edits to the registered experiment.
            if existing is None:
                self.store.save_experiment(job.get('projectId'), experiment)
            if experiment.get('candidateId'):
                from .candidates import link_experiment
                link_experiment(self.store, job.get('projectId'), experiment['candidateId'], experiment['id'], experiment['candidateRevision'])
            status = result.get('runtimeStatus', 'completed' if returncode == 0 else 'failed')
            if job['status'] in {'cancelled', 'interrupted'}:
                status = job['status']
            return self._save(job, status=status, experimentId=experiment['id'], registrationPending=False,
                              registrationError=None, progress=1 if status == 'completed' else job.get('progress',0),
                              message='已完成' if status == 'completed' else result.get('error') or job['message'])
        return self._save(job, status=job['status'] if job['status'] in {'cancelled','interrupted'} else 'failed',
                          registrationPending=False, registrationError=None,
                          message=(result or {}).get('error', f'子进程退出 {returncode}，没有可登记结果'))

    def recover_result(self, key):
        with self.lock:
            if key in self.processes:
                raise ValueError('进程停止尚未确认，不能恢复登记')
            job = self.store.get('job', key)
            directory = Path(self.store.project(job.get('projectId'))['path']) / '.research/runs' / key
            exited = read_json(directory / 'process-exit.json', {})
            if not exited.get('cleanupConfirmed') or 'returncode' not in exited:
                raise ValueError('缺少进程退出确认，不能恢复登记')
            if not read_json(directory / 'result.json', {}).get('experiment'):
                raise ValueError('没有已完成的结果文件可登记')
            try:
                return self.public_event(self._register_result(job, directory, exited['returncode']))
            except Exception as exc:
                try:
                    self._save(job, status='failed', registrationPending=True, registrationError=str(exc),
                               message='恢复登记失败，原结果保留：'+str(exc))
                except Exception:
                    self.emit(self.public_event({**job, 'status':'failed', 'registrationPending':True, 'registrationError':str(exc),
                               'message':'数据库登记失败，原结果保留'}))
                raise

    def _watch(self, key, process, directory, log):
        previous = None
        while True:
            try:
                process.wait(timeout=.25)
                break
            except subprocess.TimeoutExpired:
                try:
                    update = read_json(directory / 'progress.json')
                    if update and update != previous:
                        with self.lock:
                            job = self.store.get('job', key)
                            if job['status'] == 'running':
                                self._save(job, progress=update['progress'], message=update['message'])
                        previous = update
                except Exception as exc:
                    # Keep watching the real process even if status persistence fails.
                    try:current=self.store.get('job',key)
                    except Exception:current={}
                    self.emit(self.public_event({**current,'id':key,'status':'running',
                        'message':'任务状态登记失败：'+str(exc),'registrationError':str(exc)}))
        log.close()
        native = (directory / 'rd_native_children.json').exists()
        try:
            job = self.store.get('job', key)
            native = native or job['kind'] == 'rdagent.run'
        except Exception:
            job = read_json(directory / 'request.json', {}).get('job', {})
            native = native or job.get('kind') == 'rdagent.run'
        if native:
            from .rd_agent import stop
            try:
                stop(directory)
            except Exception as exc:
                with self.lock:
                    self._save(job, status='failed', cleanupPending=True,
                               message='原生研究进程清理未确认，队列保留占用：'+str(exc))
                return
        with self.lock:
            try:
                write_json(directory / 'process-exit.json', dict(returncode=process.returncode, cleanupConfirmed=True, exitedAt=now()))
                prepared = read_json(directory / 'preparation.json')
                if prepared:
                    job = {**job, 'preparation': prepared}
                self._register_result(job, directory, process.returncode)
            except Exception as exc:
                failure = dict(status='failed', registrationPending=True, registrationError=str(exc),
                               message='进程已退出，结果登记失败；可恢复登记：'+str(exc))
                try:
                    self._save(job, **failure)
                except Exception:
                    self.emit(self.public_event({**job, **failure}))
            finally:
                self.processes.pop(key, None)
                self._start_next(job.get('projectId'))

    def cancel(self, key):
        with self.lock:
            job = self.store.get('job', key)
            native_directory=Path(self.store.project(job.get('projectId'))['path'])/'.research/runs'/job['id']
            if (job['kind']=='rdagent.run' or (native_directory/'rd_native_children.json').exists()) and (job['status'] in {'queued','running'} or job.get('cleanupPending')):
                from .rd_agent import stop, terminate_owner
                was_cleanup_pending=bool(job.get('cleanupPending'))
                directory=Path(self.store.project(job.get('projectId'))['path'])/'.research/runs'/job['id']
                stop(directory)
                process=self.processes.get(key)
                if process: terminate_owner(process)
                job=self._save(job,status='cancelled',cleanupPending=False,message='原生研究及计算子进程已停止；已完成实验与候选保留')
                if process and process.poll() is not None and self.processes.get(key) is process and was_cleanup_pending:
                    self.processes.pop(key,None)
                    self._start_next(job.get('projectId'))
                return self.public_event(job)
            if job['status'] in {'queued', 'running'}:
                job = self._save(job, status='cancelled', message='用户取消；已保存任务参数和中间文件')
                process = self.processes.get(key)
                if process:
                    if job.get('spec',{}).get('parameters',{}).get('quoteOnly') or job['kind'] in {'factor.analyze','model.train','backtest.run','optimize.run','reports.ocr'}:
                        from .rd_agent import terminate_owner
                        terminate_owner(process)
                    else:process.terminate()
            return self.public_event(job)

    def close(self):
        with self.lock:
            self.closed = True
            for job in self.store.list('job'):
                if job['status'] in {'queued', 'running'}:
                    self._save(job, status='interrupted', message='应用关闭；已保存任务参数和中间文件')
            processes = list(self.processes.values())
            for key,process in list(self.processes.items()):
                native_directory=Path(self.store.project(self.store.get('job',key).get('projectId'))['path'])/'.research/runs'/key
                if self.store.get('job',key)['kind']=='rdagent.run' or (native_directory/'rd_native_children.json').exists():
                    from .rd_agent import stop, terminate_owner
                    job=self.store.get('job',key)
                    stop(Path(self.store.project(job.get('projectId'))['path'])/'.research/runs'/key)
                    terminate_owner(process)
                elif self.store.get('job',key).get('spec',{}).get('parameters',{}).get('quoteOnly') or self.store.get('job',key)['kind'] in {'factor.analyze','model.train','backtest.run','optimize.run','reports.ocr'}:
                    from .rd_agent import terminate_owner
                    terminate_owner(process)
                else: process.terminate()
        for process in processes:
            process.wait(timeout=10)
