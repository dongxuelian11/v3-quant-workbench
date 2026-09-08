"""Persisted subprocess jobs. One writer job per project prevents dataset races."""
from __future__ import annotations
import copy
import os
import subprocess
import sys
import threading
from pathlib import Path

from .storage import Store, identifier, now, read_json, write_json

KINDS = {'data.import', 'data.update', 'factor.analyze', 'backtest.run', 'model.train', 'optimize.run', 'selection.run'}


def validate_spec(spec):
    if not isinstance(spec, dict) or spec.get('kind') not in KINDS or not isinstance(spec.get('parameters'), dict) or (spec.get('projectId') is not None and not isinstance(spec.get('projectId'), str)):
        raise ValueError('任务参数无效')
    p, kind = spec['parameters'], spec['kind']
    required = {'data.import': ['files'], 'data.update': ['startDate'], 'factor.analyze': ['factorIds'],
                'backtest.run': ['template'], 'model.train': ['model', 'factorIds'],
                'selection.run': [], 'optimize.run': ['target', 'sampler', 'baseParameters', 'searchSpace']}[kind]
    if any(key not in p for key in required):
        raise ValueError('任务缺少参数: ' + ', '.join(key for key in required if key not in p))
    if kind in {'factor.analyze', 'model.train'} or kind == 'backtest.run' and p.get('template') != 'model_score':
        if not isinstance(p.get('factorIds'), list) or not p['factorIds'] or any(not isinstance(value, str) for value in p['factorIds']):
            raise ValueError('任务需要非空 factorIds 数组')
    if kind == 'data.import' and (not isinstance(p['files'], list) or not p['files']):
        raise ValueError('请选择导入文件')
    if kind == 'data.update' and p.get('source', 'baostock') not in {'baostock', 'akshare'}:
        raise ValueError('未知数据源')
    if kind == 'backtest.run' and p['template'] not in {'single_factor', 'multi_factor', 'model_score'}:
        raise ValueError('未知组合模板')
    return spec


class Jobs:
    def __init__(self, store, emit):
        self.store, self.emit = store, emit
        self.lock = threading.RLock()
        self.processes = {}
        self.closed = False
        for job in store.list('job'):
            if job['status'] in {'queued', 'running'}:
                self._save(job, status='interrupted', message='上次运行中断，可用原参数重新运行')

    def _save(self, job, **changes):
        job = {**job, **changes, 'updatedAt': now()}
        self.store.put('job', job, job.get('projectId') or '')
        self.store.project_store(job.get('projectId')).put('job', job, job.get('projectId') or '')
        self.emit(job)
        return job

    def submit(self, spec):
        spec = copy.deepcopy(spec)
        validate_spec(spec)
        for key in ('projectSnapshot','positionsSnapshot','strategySnapshots'):
            spec.pop(key,None)
        from .workbench import strategy_project, get_strategy
        project_id = spec.get('projectId')
        project = strategy_project(self.store, project_id, spec.get('strategyId'), active=spec['kind']=='selection.run' and bool(spec.get('strategyId'))) if project_id else self.store.project(None)
        self._freeze_universe(project)
        spec['projectSnapshot'] = project
        if project_id:
            spec['strategyId'] = project.get('strategyId', 'default')
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
                if update and update != previous:
                    with self.lock:
                        job = self.store.get('job', key)
                        if job['status'] == 'running':
                            self._save(job, progress=update['progress'], message=update['message'])
                    previous = update
        log.close()
        with self.lock:
            job = self.store.get('job', key)
            result = read_json(directory / 'result.json')
            if job['status'] == 'running':
                if process.returncode == 0 and result and result.get('experiment'):
                    experiment = result['experiment']
                    self.store.save_experiment(job.get('projectId'), experiment)
                    self._save(job, status='completed', progress=1, message='已完成', experimentId=experiment['id'])
                else:
                    self._save(job, status='failed', message=(result or {}).get('error', f'子进程退出 {process.returncode}，请查看 {directory / "worker.log"}'))
            self.processes.pop(key, None)
            self._start_next(job.get('projectId'))

    def cancel(self, key):
        with self.lock:
            job = self.store.get('job', key)
            if job['status'] in {'queued', 'running'}:
                job = self._save(job, status='cancelled', message='用户取消；已保存任务参数和中间文件')
                process = self.processes.get(key)
                if process:
                    process.terminate()
            return job

    def close(self):
        with self.lock:
            self.closed = True
            for job in self.store.list('job'):
                if job['status'] in {'queued', 'running'}:
                    self._save(job, status='interrupted', message='应用关闭；已保存任务参数和中间文件')
            processes = list(self.processes.values())
            for process in processes:
                process.terminate()
        for process in processes:
            process.wait(timeout=10)
