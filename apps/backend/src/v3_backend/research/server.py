"""Content-Length stdio service for the independent research desktop."""
from __future__ import annotations
import argparse
import contextlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .framing import encode_frame, read_frames
from .storage import Store, identifier, read_json, write_json
from .jobs import Jobs


class Service:
    def __init__(self, app_data, emit=lambda event: None):
        self.store = Store(app_data)
        self.emit = emit
        self.jobs = Jobs(self.store, emit)
        from .read_operations import ReadOperations
        self.read_operations = ReadOperations()
        self._read_context = threading.local()
        self._project_write_lock = threading.RLock()
        from .ai_execution import Executions
        self.executions = Executions(self,emit)
        from .report_tasks import ReportTasks
        self.report_tasks = ReportTasks(self)

    def experiment_details(self, project_id, experiment_id):
        import pandas as pd
        from .data import records, project_data
        experiment = self.store.experiment(project_id, experiment_id)
        tables, series = [], []
        replay = {}
        date_range = None
        count = max(1, sum(a['type'] == 'parquet' for a in experiment['artifacts']))
        row_limit = max(1, 500 // count)
        for artifact in experiment['artifacts']:
            self.check_read_cancel()
            if artifact['type'] != 'parquet':
                continue
            from .table_reader import preview
            path = self.store.artifact_path(project_id, artifact)
            frame = preview(path, row_limit, check_cancel=self.check_read_cancel)
            table_name = artifact['name'].removeprefix('holdout_')
            tables.append({'name': artifact['name'], 'columns': list(frame.columns), 'rows': records(frame)})
            if table_name in {'trades', 'holdings', 'target_weights', 'unfilled'}:
                from .table_reader import replay_counts
                for code, counts in replay_counts(path, table_name == 'trades', check_cancel=self.check_read_cancel).items():
                    item = replay.setdefault(code, dict(symbol=code, tradeCount=0, buyCount=0, sellCount=0))
                    for key in ('tradeCount', 'buyCount', 'sellCount'):
                        item[key] += counts[key]
            if table_name == 'portfolio':
                selected = [c for c in ('date', 'return', 'netReturn', 'cost') if c in frame]
                frame = pd.read_parquet(path, columns=selected)
            if table_name == 'portfolio' and 'date' in frame and not frame.empty:
                dates = pd.to_datetime(frame.date).dropna()
                if not dates.empty:
                    date_range = dict(startDate=str(dates.min())[:10], endDate=str(dates.max())[:10])
            if table_name == 'portfolio' and 'date' in frame and ('return' in frame or 'netReturn' in frame):
                # Paper accounts record cost in yuan; their netReturn already includes it.
                net = (1 + frame['netReturn']).cumprod() if 'netReturn' in frame else (1 + frame['return'] - frame['cost']).cumprod()
                points = [{'date': str(date)[:10], 'value': float(value)} for date, value in zip(frame.date, net)]
                if len(points) > 500:
                    step = max(1, (len(points) + 498) // 499)
                    points = points[::step][:499] + [points[-1]]
                series.append({'name': '净值', 'points': points})
        directory = Path(self.store.project(project_id)['path']) / '.research' / 'runs' / experiment_id
        details = read_json(directory / 'details.json', {})
        snapshot = read_json(directory / 'project.json', {})
        if snapshot:
            details['projectSnapshot'] = {key:snapshot[key] for key in ('startDate','endDate','universe','settings','strategyId','strategyName') if key in snapshot}
        if 'universe' in snapshot:
            details['researchUniverse'] = snapshot['universe']
            if snapshot['universe'].get('source') == 'manual':
                for symbol in snapshot['universe'].get('symbols', []):
                    replay.setdefault(symbol, dict(symbol=symbol, tradeCount=0, buyCount=0, sellCount=0))
        for item in replay.values():
            item['name'] = ''
        # Display metadata only: use the run's data location, never today's project settings.
        if snapshot.get('path') or snapshot.get('settings', {}).get('dataPath'):
            metadata = Path(project_data(snapshot)['path']) / 'data' / 'securities.parquet'
            if metadata.exists():
                names = pd.read_parquet(metadata)
                if {'symbol', 'name'}.issubset(names):
                    if 'effectiveDate' in names:
                        names = names.sort_values('effectiveDate')
                    for row in records(names.drop_duplicates('symbol', keep='last')):
                        if row['symbol'] in replay:
                            replay[row['symbol']].update({key: row[key] for key in ('name', 'pinyin', 'initials')
                                if row.get(key) is not None})
        details['replayStocks'] = [replay[symbol] for symbol in sorted(replay)]
        if date_range:
            details['dateRange'] = date_range
        return dict(experiment=experiment, tables=tables, series=series, details=details)

    def check_read_cancel(self):
        self.read_operations.check(getattr(self._read_context, 'operation', None))

    def request(self, method, params, *, read_operation=None):
        if method == 'reads.cancel':
            return self.read_operations.cancel((params or {}).get('readId'))
        operation = read_operation or self.read_operations.begin(method, params or {})
        previous = getattr(self._read_context, 'operation', None)
        self._read_context.operation = operation or previous
        try:
            self.check_read_cancel()
            # Do not turn a completed export into cancellation after its atomic replace.
            return self._request(method, params)
        finally:
            self._read_context.operation = previous
            self.read_operations.finish(operation)

    def _request(self, method, params):
        from copy import deepcopy
        p = params or {}
        store = self.store
        if method == 'localAssistant.apply':
            from .assistant_actions import apply
            return apply(self,p)
        if method.startswith('localAssistant.'):
            from .local_assistant import dispatch
            return dispatch(self,method,p)
        if method in {'workspace.project.get','workspace.project.save'}:
            from .workbench import project_display
            return project_display(store,p,save=method.endswith('.save'))
        if method=='jobs.priority':
            priority=p.get('priority')
            if type(priority) is not int or not -10<=priority<=10:raise ValueError('等待优先级须为-10至10，越小越优先')
            with self.jobs.lock:
                job=store.get('job',p['jobId'])
                if job['status']!='queued':raise ValueError('只有等待中的任务可调整顺序')
                self.jobs._save(job,queuePriority=priority)
                self.jobs._start_next(job.get('projectId'))
                return self.jobs.public_event(store.get('job',job['id']))
        if method=='ai.connectionTest':
            from .ai_settings import connection_test
            return connection_test(self,p)
        if method.startswith('researchPresets.'):
            from .research_presets import dispatch
            return dispatch(store,method,p)
        if method.startswith('dailyPlans.'):
            from .daily_plans import dispatch
            return dispatch(self,method,p)
        if method in {'storage.inspect','storage.clearCache'}:
            from .storage_tools import dispatch
            return dispatch(self,method,p)
        if method in {'settings.export','settings.importPreview','settings.import','diagnostics.preview'}:
            from .settings_package import dispatch
            return dispatch(store,method,p)
        if method.startswith('screeners.') or method == 'watchlists.add':
            from .screeners import dispatch as screener_dispatch
            return screener_dispatch(self, method, p)
        if method.startswith('history.memberships.'):
            from .membership_sources import dispatch as membership_dispatch
            return membership_dispatch(store, method, p)
        if method == 'ai.conversations.uiState':
            from .report_ai import save_ui_state
            return save_ui_state(self, p)
        if method.startswith(('reports.', 'reproductions.')):
            return self.report_tasks.dispatch(method, p)
        if method=='market.quote.import':
            from .quotes import import_quote
            return import_quote(store.project(None),p)
        if method.startswith('formula.'):
            from .formulas import dispatch as formula_dispatch
            return formula_dispatch(store,method,p)
        if method in {'ai.chat.start','ai.chat.message','ai.chat.cancel','ai.chat.status'}:
            return self.executions.dispatch(method,p)
        if method=='market.intraday':
            from .intraday import read
            from .app_settings import source_settings
            target=store.project(None)
            target['settings']={**target.get('settings',{}),'dataSources':source_settings(store.settings())}
            return read(target,p)
        if method in {'market.instruments','market.quote','market.members'}:
            from . import quotes
            target=store.project(p.get('projectId')) if p.get('projectId') and method!='market.quote' else store.project(None)
            from .app_settings import source_settings
            target['settings']={**target.get('settings',{}),'dataSources':source_settings(store.settings())}
            return {'market.instruments':quotes.catalog,'market.quote':quotes.status,'market.members':quotes.members}[method](target,p)
        if method.startswith('ai.projectSummary.'):
            from .project_summary import dispatch as summary_dispatch
            return summary_dispatch(self,method,p)
        from .workbench import dispatch
        handled, result = dispatch(self, method, p)
        if handled:
            return result
        if method.startswith('market.') or method == 'data.catalog':
            from .market import dispatch as market_dispatch
            handled, result = market_dispatch(self, method, p)
            if handled:
                return result
        if method == 'projects.list':
            return store.list('project')
        if method == 'projects.create':
            return store.create_project(p['path'], p['name'], p.get('objective', ''))
        if method == 'projects.open':
            return store.open_project(p['path'])
        if method == 'projects.save':
            with self._project_write_lock:
                project = deepcopy(p['project'])
                latest=store.project(project['id'])
                if p.get('preserveMembershipRef'):
                    ref = latest['universe'].get('membershipRef')
                    project['universe'].pop('membershipRef', None)
                    if ref is not None:project['universe']['membershipRef'] = deepcopy(ref)
                if 'aiInstructions' in latest.get('settings',{}):
                    project.setdefault('settings',{})['aiInstructions']=latest['settings']['aiInstructions']
                return store.save_project(project)
        if method=='projects.aiInstructions.save':
            if not isinstance(p.get('text'),str):raise ValueError('项目AI补充说明须为文字')
            with self._project_write_lock:
                project=store.project(p['projectId'])
                project.setdefault('settings',{})['aiInstructions']=p['text']
                store.save_project(project)
                return dict(projectId=project['id'],text=p['text'])
        if method == 'projects.summary':
            from .data import preview
            project = store.project(p.get('projectId'))
            return dict(project=project, data=preview(project), experiments=store.experiments(project['id']), jobs=store.list('job', project['id']))
        if method == 'universe.templates':
            return store.list('template')
        if method == 'universe.saveTemplate':
            universe = p['universe']
            if not isinstance(universe.get('symbols'), list) or universe.get('source') not in {'manual', 'all', 'csi300', 'csi500'}:
                raise ValueError('股票池格式无效')
            template = dict(id=p.get('id') or identifier(), name=p['name'], universe=universe)
            return store.put('template', template)
        if method in {'settings.get', 'settings.save'}:
            import os
            from .resources import compute_settings
            from .app_settings import validate as validate_settings, source_settings, capabilities
            if method == 'settings.save':
                changes = validate_settings(p['settings'],store.settings())
                changes.pop('effectiveResources', None)
                changes.pop('dataSourceCapabilities', None)
                changes.pop('effectiveStorage', None)
                if 'compute' in changes:
                    compute_settings(changes['compute'], os.cpu_count())
                value = store.settings(changes)
            else:
                value = store.settings()
            return {**value, 'dataSources':source_settings(value), 'dataSourceCapabilities':capabilities(),
                    'effectiveStorage':{'dataDirectory':str(store.data_root()),'newProjectDirectory':value.get('storage',{}).get('newProjectDirectory'),
                        'message':'目录更改用于后续共享行情、新研报和新项目；不移动已有资料，旧项目沿用原路径。'},
                    'effectiveResources': compute_settings(value.get('compute'), os.cpu_count())}
        if method in {'positions.get', 'positions.save', 'positions.import'}:
            from . import positions
            project = store.project(p.get('projectId'))
            if method == 'positions.get':
                return positions.get(project)
            return positions.save(project, p['positions']) if method == 'positions.save' else positions.import_file(project, p['path'])
        if method in {'ai.state.get', 'ai.state.save'}:
            from .ai import get_state, save_state
            return get_state(self, p) if method == 'ai.state.get' else save_state(self, p)
        if method == 'jobs.submit':
            return self.jobs.submit(p['spec'])
        if method == 'jobs.list':
            return self.jobs.list(p)
        if method == 'jobs.clear':
            return self.jobs.clear(p)
        if method == 'jobs.recoverResult':
            return self.jobs.recover_result(p['jobId'])
        if method == 'jobs.cancel':
            return self.jobs.cancel(p['jobId'])
        if method == 'factors.list':
            from .engines import factor_catalog
            return factor_catalog()
        if method == 'data.import.preview':
            from .data_imports import preview as preview_import
            from .workbench import strategy_project
            project=strategy_project(store,p['projectId'],p['strategyId']) if p.get('projectId') and p.get('strategyId') else store.project(p.get('projectId'))
            return preview_import(project,p)
        if method == 'data.preview':
            from .data import preview
            from .workbench import strategy_project
            project = strategy_project(store, p['projectId'], p['strategyId']) if p.get('projectId') and p.get('strategyId') else store.project(p.get('projectId'))
            return preview(project)
        if method.startswith('candidates.'):
            from .candidates import dispatch as candidate_dispatch
            return candidate_dispatch(store, method, p)
        if method in {'simulation.table','simulation.accounts.export','simulation.accounts.curve'}:
            from .simulation_reads import dispatch as simulation_read
            return simulation_read(store,method,p,self.check_read_cancel)
        if method.startswith('simulation.accounts.') or method == 'simulation.table':
            from .simulation import dispatch as simulation_dispatch
            return simulation_dispatch(store, method, p)
        if method in {'rdagent.preview', 'rdagent.status'}:
            from . import rd_agent
            return (rd_agent.preview if method == 'rdagent.preview' else rd_agent.status)(store, p)
        if method == 'data.bars':
            from .charts import bars
            project,query,warning=self.chart_source(p)
            result=bars(project,query)
            if warning:
                for row in result:row['sourceWarning']=warning
            return result
        if method in {'charts.load', 'charts.save'}:
            from .charts import drawings
            project,query,warning=self.chart_source(p)
            result=drawings(project, method, query)
            if warning:result.setdefault('warnings',[]).append(warning)
            return result
        if method == 'experiments.list':
            scopes = [None] + [x['id'] for x in store.list('project')] if p.get('all') else [p.get('projectId')]
            values = [item for scope in scopes for item in store.experiments(scope)]
            return sorted([item for item in values if not p.get('strategyId') or item.get('strategyId') == p['strategyId']], key=lambda x:x['createdAt'], reverse=True)
        if method == 'experiments.get':
            return self.experiment_details(p.get('projectId'), p['experimentId'])
        if method == 'experiments.calendar':
            import pandas as pd
            experiment = store.experiment(p.get('projectId'), p['experimentId'])
            artifact = next((a for a in experiment['artifacts'] if a['name'] == 'processing_coverage' and a['type'] == 'parquet'), None)
            if artifact:
                from .table_reader import calendar
                dates = calendar(store.artifact_path(p.get('projectId'), artifact), check_cancel=self.check_read_cancel)
                if dates is not None:
                    # Coverage retains sessions even when every factor value is missing.
                    return dict(tradingDates=dates, source='experiment_processing_sessions', message='该实验输入处理的交易日期；保留指标缺失的交易日')
            return dict(tradingDates=None, source='unavailable', message='旧实验未保存可核对的交易日历，不能从指标非空日期推断')
        if method == 'experiments.analysis':
            from .analysis_reader import read
            experiment = store.experiment(p.get('projectId'), p['experimentId'])
            artifact = next((a for a in experiment['artifacts'] if a['name'] == p['table'] and a['type'] == 'parquet'), None)
            if artifact is None:
                raise ValueError('实验中没有此数据表')
            coverage = next((a for a in experiment['artifacts'] if a['name'] == 'processing_coverage' and a['type'] == 'parquet'), None)
            return read(store.artifact_path(p.get('projectId'), artifact), artifact['name'], p,
                        store.artifact_path(p.get('projectId'), coverage) if coverage else None,
                        check_cancel=self.check_read_cancel)
        if method == 'experiments.table':
            import pandas as pd
            from .data import records, symbol
            experiment = store.experiment(p.get('projectId'), p['experimentId'])
            artifact = next((item for item in experiment['artifacts'] if item['name'] == p['table'] and item['type'] == 'parquet'), None)
            if artifact is None:
                raise ValueError('实验中没有此数据表')
            from .table_reader import page
            return page(store.artifact_path(p.get('projectId'), artifact), p, artifact['name'], check_cancel=self.check_read_cancel)
        if method == 'experiments.previousComparison':
            from .comparison import previous
            return previous(store,p,self.check_read_cancel)
        if method == 'experiments.compare':
            from .comparison import compare, warning
            records = compare(store,p,self.check_read_cancel)
            results = []
            for record in records:
                reference = record['ref']
                result = self.experiment_details(reference['projectId'],reference['experimentId'])
                result['details']['comparison'] = record['comparison']
                result['details']['comparisonWarning'] = warning(record['comparison'])
                results.append(result)
            return results
        if method == 'experiments.update':
            value = store.experiment(p.get('projectId'), p['experimentId'])
            for key in ['name', 'starred']:
                if key in p:
                    value[key] = p[key]
            return store.save_experiment(p.get('projectId'), value)
        if method == 'experiments.dependencies':
            return store.experiment_dependencies(p.get('projectId'), p['experimentId'])
        if method == 'experiments.delete':
            store.experiment(p.get('projectId'), p['experimentId'])
            dependencies = store.experiment_dependencies(p.get('projectId'), p['experimentId'])
            if dependencies:
                raise ValueError('此结果仍被引用，不能删除：' + '、'.join(str(item['name']) for item in dependencies[:8]))
            import shutil
            root = (Path(store.project(p.get('projectId'))['path']) / '.research' / 'runs').resolve()
            target = (root / p['experimentId']).resolve()
            if target.parent != root:
                raise ValueError('实验路径无效')
            if target.exists():
                shutil.rmtree(target)
            store.project_store(p.get('projectId')).delete('experiment', p['experimentId'])
            return {'deleted': True}
        if method == 'exports.table':
            return self.export_table(p)
        if method == 'exports.create':
            return self.export(p)
        if method == 'ai.chat':
            from .ai import chat
            return chat(self, p)
        raise ValueError(f'未知研究方法: {method}')

    def chart_source(self,p):
        from copy import deepcopy
        from pathlib import Path
        from .storage import read_json
        project=self.store.project(p.get('projectId'));query=deepcopy(p);warning=None
        if not p.get('experimentId'):
            from .app_settings import source_settings
            project['settings']={**project.get('settings',{}),'dataSources':source_settings(self.store.settings())}
        if p.get('experimentId'):
            experiment=self.store.experiment(p.get('projectId'),p['experimentId'])
            if experiment.get('inputSnapshot'):
                from .input_snapshot import restore
                project, _, _ = restore(self.store, project, experiment['id'])
            snapshot=read_json(Path(project['path'])/'.research/runs'/experiment['id']/'project.json')
            if snapshot and not experiment.get('inputSnapshot'):
                if not experiment.get('inputSnapshot'):
                    warning='旧实验未固定实际行情输入；兼容图表读取可能包含后续更新，不能作为原输入复现。'
                settings=deepcopy(snapshot.get('settings',{}));path=settings.get('dataPath')
                if path:
                    original=Path(snapshot['path']);stored=Path(path)
                    if stored.is_relative_to(original):settings['dataPath']=str(Path(project['path'])/stored.relative_to(original))
                project={**snapshot,'path':project['path'],'id':project['id'],'settings':settings}
            elif not experiment.get('inputSnapshot'):warning='旧实验未保存项目数据来源快照；此图兼容读取当前项目数据，不能视为已固定的实验行情。'
            parameters=experiment.get('parameters',{})
            for key,choose in (('startDate',max),('endDate',min)):
                if parameters.get(key):query[key]=choose(str(query.get(key) or parameters[key])[:10],str(parameters[key])[:10])
        return project,query,warning


    def export_table(self, p):
        import pandas as pd
        import re
        table = p['table']
        frame = pd.DataFrame(table['rows'], columns=table['columns'])
        folder = self.store.root / 'shared' / 'exports'
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[<>:"/\\|?*]', '_', str(p.get('name') or table['name'])).strip('. ') or 'table'
        if p['format'] == 'csv':
            path = folder / (name + '.csv')
            frame.to_csv(path, index=False, encoding='utf-8-sig')
        elif p['format'] == 'xlsx':
            path = folder / (name + '.xlsx')
            with pd.ExcelWriter(path, engine='openpyxl') as writer:
                for chunk, offset in enumerate(range(0, max(1,len(frame)),1048575)):
                    frame.iloc[offset:offset+1048575].to_excel(writer,sheet_name=f'table_{chunk}',index=False)
        else:
            raise ValueError('只支持CSV/XLSX')
        return {'path':str(path)}

    def export(self, p):
        from .result_export import export
        output = Path(self.store.project(p.get('projectId'))['path']) / 'exports'
        output.mkdir(exist_ok=True)
        if 'experimentIds' in p or 'experiments' in p:
            from .result_export import export_comparison
            return export_comparison(self.store,p.get('projectId'),p.get('experimentIds'),output,p['format'],
                check_cancel=self.check_read_cancel, experiments=p.get('experiments'), baseline_ref=p.get('baselineRef'))
        experiment = self.store.experiment(p.get('projectId'), p['experimentId'])
        return export(self.store, p.get('projectId'), experiment, output, p['format'], p.get('table'), check_cancel=self.check_read_cancel)

    def close(self):
        from .local_assistant import close as close_local_assistant
        close_local_assistant(self)
        self.read_operations.cancel_all()
        self.report_tasks.close()
        self.executions.close()
        self.jobs.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-data', required=True)
    args = parser.parse_args()
    protocol = sys.stdout.buffer
    lock = threading.Lock()
    # Global redirect covers optional engines and concurrent AI work, not just the main request stack.
    sys.stdout = sys.stderr
    # On Windows, first loading NumPy's native DLL in a worker can stall while
    # the main thread blocks on the Node stdin pipe. Initialize before reading.
    import pandas  # noqa: F401

    def send(message):
        with lock:
            protocol.write(encode_frame(message))
            protocol.flush()

    service = Service(args.app_data, lambda event: send({'event': event}))

    def dispatch(request, read_operation=None):
        try:
            result = service.request(request['method'], request.get('params', {}), read_operation=read_operation)
            send({'id': request['id'], 'result': result})
        except Exception as exc:
            send({'id': request.get('id'), 'error': {'message': str(exc)}})

    pool = ThreadPoolExecutor(max_workers=12)
    reads = ThreadPoolExecutor(max_workers=2, thread_name_prefix='research-read')
    try:
        for request in read_frames(sys.stdin.buffer):
            if request.get('method') in {'storage.inspect', 'experiments.get', 'experiments.table', 'experiments.analysis', 'experiments.calendar', 'experiments.compare', 'experiments.previousComparison', 'exports.create', 'exports.table', 'simulation.table', 'simulation.accounts.export', 'simulation.accounts.curve'}:
                # Register before queuing so a later cancel also reaches queued requests.
                try:
                    operation = service.read_operations.begin(request['method'], request.get('params') or {})
                    reads.submit(dispatch, request, operation)
                except Exception as exc:
                    send({'id': request.get('id'), 'error': {'message': str(exc)}})
            elif request.get('method','').startswith('localAssistant.') or request.get('method') in {'ai.connectionTest','ai.chat','ai.projectSummary.refresh','formula.evaluate','market.quote.import'} or request.get('method') in {'data.bars','market.quote'} and request.get('params',{}).get('period')=='trading_days' or request.get('method') in {'market.instruments','market.members','market.overview','market.intraday','market.quote'} and (request.get('params',{}).get('refresh') or request.get('params',{}).get('loadIfMissing')):
                pool.submit(dispatch, request)
            else:
                dispatch(request)
    finally:
        service.close()
        pool.shutdown(wait=True, cancel_futures=True)
        reads.shutdown(wait=True, cancel_futures=True)


if __name__ == '__main__':
    main()
