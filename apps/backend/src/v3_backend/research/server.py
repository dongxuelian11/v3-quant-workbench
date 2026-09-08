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
        self.jobs = Jobs(self.store, emit)

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
            if table_name == 'portfolio' and 'date' in frame and 'return' in frame:
                net = (1 + frame['return'] - frame['cost']).cumprod()
                points = [{'date': str(date)[:10], 'value': float(value)} for date, value in zip(frame.date, net)]
                if len(points) > 500:
                    step = max(1, (len(points) + 498) // 499)
                    points = points[::step][:499] + [points[-1]]
                series.append({'name': '净值', 'points': points})
        directory = Path(self.store.project(project_id)['path']) / '.research' / 'runs' / experiment_id
        details = read_json(directory / 'details.json', {})
        snapshot = read_json(directory / 'project.json', {})
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
            return store.list('job', p.get('projectId'))
        if method == 'jobs.cancel':
            return self.jobs.cancel(p['jobId'])
        if method == 'factors.list':
            from .engines import factor_catalog
            return factor_catalog()
        if method == 'data.preview':
            from .data import preview
            return preview(store.project(p.get('projectId')))
        if method == 'data.bars':
            import pandas as pd
            from .data import records, symbol
            from .data import project_data
            root = Path(project_data(store.project(p.get('projectId')))['path']) / 'data'
            code = symbol(p['symbol'])
            columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'factor', 'rawOpen', 'rawHigh', 'rawLow', 'rawClose']
            def read_bars(path, filters=None):
                import pyarrow.parquet as pq
                available = set(pq.ParquetFile(path).schema_arrow.names)
                selected = [column for column in columns if column in available]
                # Legacy imports may lack raw prices/factors. Nulls are explicit,
                # never inferred from adjusted OHLC or an invented factor of one.
                return pd.read_parquet(path,columns=selected,filters=filters).reindex(columns=columns)
            # Legacy tables can overlap newer partitions; the partition is the latest copy.
            frames = []
            if (root / 'prices.parquet').exists():
                frames.append(read_bars(root / 'prices.parquet', filters=[('symbol', '==', code)]))
            partition = root / 'prices' / f'{code}.parquet'
            if partition.exists():
                frames.append(read_bars(partition))
            if not frames:
                return []
            frame = pd.concat(frames, ignore_index=True).drop_duplicates('date', keep='last').sort_values('date')
            if p.get('startDate'):
                frame = frame[frame.date >= p['startDate']]
            if p.get('endDate'):
                frame = frame[frame.date <= p['endDate']]
            if p.get('beforeDate'):
                frame = frame[frame.date < p['beforeDate']]
            return records(frame.tail(max(1, min(500, int(p.get('limit', 500))))))
        if method in {'charts.load', 'charts.save'}:
            from .data import symbol
            project = store.project(p.get('projectId'))
            path = Path(project['path']) / 'annotations' / f'{symbol(p["symbol"])}.json'
            if method == 'charts.save':
                write_json(path, p['annotations'])
            return {'annotations': read_json(path, [])}
        if method == 'experiments.list':
            scopes = [None] + [x['id'] for x in store.list('project')] if p.get('all') else [p.get('projectId')]
            values = [item for scope in scopes for item in store.experiments(scope)]
            return sorted([item for item in values if not p.get('strategyId') or item.get('strategyId') == p['strategyId']], key=lambda x:x['createdAt'], reverse=True)
        if method == 'experiments.get':
            return self.experiment_details(p.get('projectId'), p['experimentId'])
        if method == 'experiments.table':
            import pandas as pd
            from .data import records, symbol
            experiment = store.experiment(p.get('projectId'), p['experimentId'])
            artifact = next((item for item in experiment['artifacts'] if item['name'] == p['table'] and item['type'] == 'parquet'), None)
            if artifact is None:
                raise ValueError('实验中没有此数据表')
            frame = pd.read_parquet(store.artifact_path(p.get('projectId'), artifact))
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
        self.jobs.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-data', required=True)
    args = parser.parse_args()
    protocol = sys.stdout.buffer
    lock = threading.Lock()
    # Global redirect covers optional engines and concurrent AI work, not just the main request stack.
    sys.stdout = sys.stderr

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

    pool = ThreadPoolExecutor(max_workers=2)
    try:
        for request in read_frames(sys.stdin.buffer):
            if request.get('method') == 'ai.chat':
                pool.submit(dispatch, request)
            else:
                dispatch(request)
    finally:
        service.close()
        pool.shutdown(wait=True, cancel_futures=True)


if __name__ == '__main__':
    main()
