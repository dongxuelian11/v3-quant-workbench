"""Persisted research subprocesses sharing one local writer queue."""
from __future__ import annotations
import copy
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from .storage import Store, identifier, now, read_json, write_json

KINDS = {'data.import', 'data.update', 'factor.analyze', 'backtest.run', 'model.train', 'optimize.run', 'selection.run', 'simulation.advance', 'rdagent.run', 'reports.import', 'reports.ocr', 'reports.refresh'}
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
                'selection.run': [], 'simulation.advance': ['accountId'], 'rdagent.run': ['objective','action'],
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
        if not spec.get('projectId') or not isinstance(p['accountId'], str) or not p['accountId']:
            raise ValueError('请选择模拟账户及所属项目')
        if p.get('projectId') not in (None, spec['projectId']):
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
                self._save(job, status='interrupted', message='上次运行中断，可用原参数重新运行')

    def _save(self, job, **changes):
        job = {**job, **changes, 'updatedAt': now()}
        self.store.put('job', job, job.get('projectId') or '')
        self.store.project_store(job.get('projectId')).put('job', job, job.get('projectId') or '')
        if job['status'] in TERMINAL:
            self._retain_stage_job(job)
        self.emit(job)
        return job

    def _retain_stage_job(self, job):
        # Conversations keep their result links even when task history is cleared.
        from .workbench import _legacy_conversations
        _legacy_conversations(self.store)
        event = {key: job[key] for key in (
            'id', 'projectId', 'strategyId', 'kind', 'name', 'status', 'progress',
            'message', 'experimentId', 'createdAt', 'updatedAt',
        ) if key in job}
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

    def _records(self, filters):
        clauses, values = ['kind=?'], ['job']
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
        jobs = self._records(filters or {})
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
        return jobs

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
                if not job or job['status'] not in TERMINAL or key in self.processes:
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

    def submit(self, spec, frozen_project=None):
        spec = copy.deepcopy(spec)
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
        for key in ('projectSnapshot','positionsSnapshot','strategySnapshots','candidateSnapshot'):
            spec.pop(key,None)
        if spec['kind'] == 'simulation.advance':
            if not spec['parameters'].get('endDate'):
                raise ValueError('推进模拟账户前请明确选择结束日期')
            from .simulation import dispatch
            account = dispatch(self.store, 'simulation.accounts.get', {
                'projectId': spec['projectId'], 'accountId': spec['parameters']['accountId']})
            if spec.get('strategyId') not in (None, account['strategyId']):
                raise ValueError('模拟任务策略与账户不一致')
            if account['paused']:
                raise ValueError('模拟账户已暂停，请先恢复')
            spec['strategyId'] = account['strategyId']
            spec['parameters']['projectId'] = spec['projectId']
            spec['parameters'].setdefault('startDate',account['startDate'])
        if spec.get('candidateId'):
            from .candidates import get
            candidate = get(self.store, spec.get('projectId'), spec['candidateId'])
            if candidate.get('strategyId') != spec.get('strategyId') or candidate['spec']['kind'] != spec['kind'] or candidate['spec']['parameters'] != spec['parameters']:
                raise ValueError('候选已经变更，请保存当前候选后再运行')
            spec['candidateSnapshot'] = candidate
        from .workbench import strategy_project, get_strategy
        project_id = spec.get('projectId')
        project = strategy_project(self.store, project_id, spec['strategyId'], active=spec['kind']=='selection.run') if project_id and spec.get('strategyId') else copy.deepcopy(self.store.project(project_id))
        if frozen_project is not None:
            if frozen_project.get('id')!=project_id or frozen_project.get('strategyId')!=spec.get('strategyId'):
                raise ValueError('冻结研究范围与任务不一致')
            project=copy.deepcopy(frozen_project)
        from .preparation import KINDS as prepared_kinds, scope
        if spec['kind'] in prepared_kinds:
            scope(project,spec['parameters'],spec['kind'])
        self._freeze_universe(project)
        spec['projectSnapshot'] = project
        if project_id and project.get('strategyId'):
            spec['strategyId'] = project['strategyId']
        if spec['kind'] == 'selection.run':
            from .positions import get
            spec['positionsSnapshot'] = get(self.store.project(None) if spec['parameters'].get('strategies') else project)
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
                    self._freeze_universe(scoped)
                    frozen.append({**reference,'project':scoped})
                spec['strategySnapshots'] = frozen
        with self.lock:
            if self.closed:
                raise ValueError('任务服务已关闭')
            job = dict(id=identifier(), projectId=spec.get('projectId'), kind=spec['kind'], name=spec.get('name') or spec['kind'],
                       strategyId=spec.get('strategyId'), status='queued', progress=0, message='等待执行', createdAt=now(), updatedAt=now(), spec=spec)
            job = self._save(job)
            self._start_next(spec.get('projectId'))
            return self.store.get('job', job['id'])

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
        if self.closed or self.processes:
            return
        queued = [job for job in self.store.list('job') if job['status'] == 'queued']
        if not queued:
            return
        job = queued[-1]
        project_id = job.get('projectId')
        directory = Path(self.store.project(project_id)['path']) / '.research' / 'runs' / job['id']
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / 'request.json', {'appData': str(self.store.root), 'job': job})
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2]) + os.pathsep + env.get('PYTHONPATH', '')
        log = (directory / 'worker.log').open('wb')
        try:
            process = subprocess.Popen([sys.executable, '-m', 'v3_backend.research.worker', str(directory)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception as exc:
            log.close()
            self._save(job, status='failed', message=str(exc))
            self._start_next(project_id)
            return
        self.processes[job['id']] = process
        self._save(job, status='running', message='子进程运行中')
        threading.Thread(target=self._watch, args=(job['id'], process, directory, log), daemon=True).start()

    def _watch(self, key, process, directory, log):
        previous = None
        while True:
            try:
                process.wait(timeout=.25)
                break
            except subprocess.TimeoutExpired:
                update = read_json(directory / 'progress.json')
                if update:
                    prepared=read_json(directory/'preparation.json')
                    if prepared:update={**update,'preparation':prepared}
                if update and update != previous:
                    with self.lock:
                        job = self.store.get('job', key)
                        if job['status'] == 'running':
                            self._save(job, progress=update['progress'], message=update['message'], **({'preparation':update['preparation']} if update.get('preparation') else {}))
                    previous = update
        log.close()
        prepared=read_json(directory/'preparation.json')
        if prepared:
            with self.lock:self._save(self.store.get('job',key),preparation=prepared)
        if self.store.get('job',key)['kind']=='rdagent.run' or (directory/'rd_native_children.json').exists():
            from .rd_agent import stop
            try:
                stop(directory)
            except Exception as exc:
                with self.lock:
                    self._save(self.store.get('job',key),status='failed',cleanupPending=True,
                               message='原生研究进程清理未确认，队列保留占用：'+str(exc))
                return
        with self.lock:
            job = self.store.get('job', key)
            result = read_json(directory / 'result.json')
            if job['kind']=='rdagent.run' and result and result.get('experiment'):
                experiment=result['experiment'];self.store.save_experiment(job.get('projectId'),experiment)
                status=result.get('runtimeStatus','completed' if process.returncode==0 else 'failed')
                if job['status'] in {'cancelled','interrupted'}: status=job['status']
                self._save(job,status=status,experimentId=experiment['id'],progress=1 if status=='completed' else job['progress'],
                           cleanupPending=False,message='已完成' if status=='completed' else result.get('error') or job['message'])
            elif job['status'] == 'running':
                if process.returncode == 0 and result and result.get('experiment'):
                    experiment = result['experiment']
                    self.store.save_experiment(job.get('projectId'), experiment)
                    if experiment.get('candidateId'):
                        from .candidates import link_experiment
                        link_experiment(self.store, job.get('projectId'), experiment['candidateId'], experiment['id'], experiment['candidateRevision'])
                    self._save(job, status='completed', progress=1, message='已完成', experimentId=experiment['id'])
                else:
                    self._save(job, status='failed', message=(result or {}).get('error', f'子进程退出 {process.returncode}，请查看 {directory / "worker.log"}'))
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
                return job
            if job['status'] in {'queued', 'running'}:
                job = self._save(job, status='cancelled', message='用户取消；已保存任务参数和中间文件')
                process = self.processes.get(key)
                if process:
                    if job.get('spec',{}).get('parameters',{}).get('quoteOnly') or job['kind'] in {'factor.analyze','model.train','backtest.run','optimize.run','reports.ocr'}:
                        from .rd_agent import terminate_owner
                        terminate_owner(process)
                    else:process.terminate()
            return job

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
