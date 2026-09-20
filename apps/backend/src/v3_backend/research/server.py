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
            if artifact['type'] != 'parquet':
                continue
            frame = pd.read_parquet(self.store.artifact_path(project_id, artifact))
            table_name = artifact['name'].removeprefix('holdout_')
            if table_name in {'trades', 'holdings', 'target_weights', 'unfilled'} and 'symbol' in frame:
                for symbol in frame.symbol.dropna().astype(str).unique():
                    replay.setdefault(symbol, dict(symbol=symbol, tradeCount=0, buyCount=0, sellCount=0))
                if table_name == 'trades':
                    for symbol, group in frame.groupby('symbol'):
                        item = replay[str(symbol)]
                        item['tradeCount'] = len(group)
                        if 'side' in group:
                            item['buyCount'] = int(group.side.eq('buy').sum())
                            item['sellCount'] = int(group.side.eq('sell').sum())
                        elif 'direction' in group:
                            item['buyCount'] = int(group.direction.eq(1).sum())
                            item['sellCount'] = int(group.direction.eq(0).sum())
            if table_name == 'portfolio' and 'date' in frame and not frame.empty:
                dates = pd.to_datetime(frame.date).dropna()
                if not dates.empty:
                    date_range = dict(startDate=str(dates.min())[:10], endDate=str(dates.max())[:10])
            tables.append({'name': artifact['name'], 'columns': list(frame.columns), 'rows': records(frame.head(row_limit))})
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

    def request(self, method, params):
        p = params or {}
        store = self.store
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
            return read(store.project(None),p)
        if method in {'market.instruments','market.quote','market.members'}:
            from . import quotes
            target=store.project(p.get('projectId')) if p.get('projectId') and method!='market.quote' else store.project(None)
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
            return store.save_project(p['project'])
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
        if method == 'settings.get':
            return store.settings()
        if method == 'settings.save':
            return store.settings(p['settings'])
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
        if method == 'jobs.cancel':
            return self.jobs.cancel(p['jobId'])
        if method == 'factors.list':
            from .engines import factor_catalog
            return factor_catalog()
        if method == 'data.preview':
            from .data import preview
            from .workbench import strategy_project
            project = strategy_project(store, p['projectId'], p['strategyId']) if p.get('projectId') and p.get('strategyId') else store.project(p.get('projectId'))
            return preview(project)
        if method.startswith('candidates.'):
            from .candidates import dispatch as candidate_dispatch
            return candidate_dispatch(store, method, p)
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
                frame = pd.read_parquet(store.artifact_path(p.get('projectId'), artifact))
                if 'date' in frame:
                    # Coverage retains sessions even when every factor value is missing.
                    dates = sorted(pd.to_datetime(frame['date'], errors='raise').dt.strftime('%Y-%m-%d').unique().tolist())
                    return dict(tradingDates=dates, source='experiment_processing_sessions', message='该实验输入处理的交易日期；保留指标缺失的交易日')
            return dict(tradingDates=None, source='unavailable', message='旧实验未保存可核对的交易日历，不能从指标非空日期推断')
        if method == 'experiments.table':
            import pandas as pd
            from .data import records, symbol
            experiment = store.experiment(p.get('projectId'), p['experimentId'])
            artifact = next((item for item in experiment['artifacts'] if item['name'] == p['table'] and item['type'] == 'parquet'), None)
            if artifact is None:
                raise ValueError('实验中没有此数据表')
            frame = pd.read_parquet(store.artifact_path(p.get('projectId'), artifact))
            if artifact['name'] == 'trades' and 'tradeId' not in frame:
                frame['tradeId'] = [str(i) for i in range(len(frame))]
            for parameter, choices in (('factorId', ('factor', 'factorId')),
                                       ('tradeId', ('tradeId',)),
                                       ('modelWindowId', ('window', 'windowId', 'modelWindowId'))):
                if p.get(parameter) not in (None, ''):
                    column = next((c for c in choices if c in frame), None)
                    if column is None:
                        raise ValueError('此表没有对应的筛选字段: ' + parameter)
                    frame = frame[frame[column].astype(str) == str(p[parameter])]
            instrument = next((name for name in ('symbol', 'instrument', 'asset') if name in frame), None)
            date_column = 'date' if 'date' in frame else 'datetime' if 'datetime' in frame else None
            if p.get('symbol'):
                if instrument is None:
                    raise ValueError('此表没有股票代码列')
                frame = frame[frame[instrument] == symbol(p['symbol'])]
            if p.get('startDate') or p.get('endDate'):
                if date_column is None:
                    raise ValueError('此表没有日期列')
                dates = pd.to_datetime(frame[date_column], utc=True)
                if p.get('startDate'):
                    frame = frame[dates >= pd.to_datetime(p['startDate'], utc=True)]
                    dates = dates.loc[frame.index]
                if p.get('endDate'):
                    frame = frame[dates < pd.to_datetime(p['endDate'], utc=True).normalize() + pd.Timedelta(days=1)]
            offset, limit = max(0, int(p.get('offset', 0))), max(1, min(500, int(p.get('limit', 200))))
            return dict(name=artifact['name'], columns=list(frame.columns), rows=records(frame.iloc[offset:offset + limit]), total=len(frame), offset=offset, limit=limit)
        if method == 'experiments.compare':
            refs = p.get('experiments') or [{'projectId':p.get('projectId'),'experimentId':key} for key in p.get('experimentIds',[])]
            if len(refs) > 10:
                raise ValueError('一次最多比较10个实验')
            results = [self.experiment_details(ref.get('projectId'), ref['experimentId']) for ref in refs]
            contexts = {json.dumps(result['details'].get('dataContext'), sort_keys=True) for result in results}
            if len(contexts) > 1:
                for result in results:
                    result['details']['comparisonWarning'] = '实验数据日期或覆盖不同，不能视为相同条件下的优劣比较。'
            return results
        if method == 'experiments.update':
            value = store.experiment(p.get('projectId'), p['experimentId'])
            for key in ['name', 'starred']:
                if key in p:
                    value[key] = p[key]
            return store.save_experiment(p.get('projectId'), value)
        if method == 'experiments.delete':
            store.experiment(p.get('projectId'), p['experimentId'])
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
        if p.get('experimentId'):
            experiment=self.store.experiment(p.get('projectId'),p['experimentId'])
            snapshot=read_json(Path(project['path'])/'.research/runs'/experiment['id']/'project.json')
            if snapshot:
                settings=deepcopy(snapshot.get('settings',{}));path=settings.get('dataPath')
                if path:
                    original=Path(snapshot['path']);stored=Path(path)
                    if stored.is_relative_to(original):settings['dataPath']=str(Path(project['path'])/stored.relative_to(original))
                project={**snapshot,'path':project['path'],'id':project['id'],'settings':settings}
            else:warning='旧实验未保存项目数据来源快照；此图兼容读取当前项目数据，不能视为已固定的实验行情。'
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
        import pandas as pd
        import re
        experiment = self.store.experiment(p.get('projectId'), p['experimentId'])
        output = Path(self.store.project(p.get('projectId'))['path']) / 'exports'
        output.mkdir(exist_ok=True)
        tables = [(artifact['name'], pd.read_parquet(self.store.artifact_path(p.get('projectId'), artifact))) for artifact in experiment['artifacts'] if artifact['type'] == 'parquet']
        if not tables:
            tables = [('metrics', pd.DataFrame(list(experiment['metrics'].items()), columns=['metric', 'value']))]
        if p['format'] == 'xlsx':
            path = output / f'{experiment["id"]}.xlsx'
            with pd.ExcelWriter(path, engine='openpyxl') as writer:
                for index, (name, frame) in enumerate(tables):
                    safe_name = re.sub(r'[\\/*?:\[\]]', '_', name)
                    # Excel's worksheet limit must never silently truncate full exports.
                    for chunk, offset in enumerate(range(0, max(1, len(frame)), 1048575)):
                        frame.iloc[offset:offset + 1048575].to_excel(writer, sheet_name=f'{index}_{chunk}_{safe_name}'[:31], index=False)
        elif p['format'] == 'csv':
            # One CSV is directly usable by the desktop exportFile contract; optional table chooses any full artifact.
            selected = next((frame for name, frame in tables if name == p.get('table')), tables[0][1])
            path = output / f'{experiment["id"]}.csv'
            selected.to_csv(path, index=False, encoding='utf-8-sig')
        else:
            raise ValueError('只支持 CSV/XLSX 导出')
        return {'path': str(path)}

    def close(self):
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

    def dispatch(request):
        try:
            result = service.request(request['method'], request.get('params', {}))
            send({'id': request['id'], 'result': result})
        except Exception as exc:
            send({'id': request.get('id'), 'error': {'message': str(exc)}})

    pool = ThreadPoolExecutor(max_workers=12)
    try:
        for request in read_frames(sys.stdin.buffer):
            if request.get('method') in {'ai.chat','ai.projectSummary.refresh','formula.evaluate','market.quote.import'} or request.get('method') in {'data.bars','market.quote'} and request.get('params',{}).get('period')=='trading_days' or request.get('method') in {'market.instruments','market.members','market.overview','market.intraday','market.quote'} and (request.get('params',{}).get('refresh') or request.get('params',{}).get('loadIfMissing')):
                pool.submit(dispatch, request)
            else:
                dispatch(request)
    finally:
        service.close()
        pool.shutdown(wait=True, cancel_futures=True)


if __name__ == '__main__':
    main()
