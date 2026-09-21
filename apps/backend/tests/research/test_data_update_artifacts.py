import tempfile
import unittest
from pathlib import Path
import pandas as pd
from v3_backend.research import data
from v3_backend.research.storage import Store, read_json
from v3_backend.research.worker import save_result


class DataUpdateArtifactsTests(unittest.TestCase):
    def test_update_keeps_its_scope_and_immutable_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / 'app')
            project = store.create_project(Path(temp) / 'project', '更新范围')
            rows = [dict(symbol=code, date=date, open=10., high=11., low=9., close=10., volume=100.)
                    for code in ['SH600000', 'SZ000001'] for date in ['2025-01-02', '2025-01-03']]
            frame, _ = data.normalize(pd.DataFrame(rows), 'prices')
            source = Path(data.project_data(project)['path']) / 'data'
            source.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(source / 'prices.parquet', index=False)
            # Newer partition overrides the old monolithic row in the captured slice.
            folder = Path(data.project_data(project)['path']) / 'data/prices'
            folder.mkdir(exist_ok=True)
            override = frame[frame.symbol.eq('SH600000')].copy(); override['close'] = 10.5
            override.to_parquet(folder / 'SH600000.parquet', index=False)
            job = dict(id='update', projectId=project['id'], kind='data.update', name='update',
                       spec=dict(parameters=dict(startDate='2025-01-03', endDate='2025-01-03')))
            run = Path(project['path']) / '.research/runs/update'
            result = dict(metrics={}, artifacts=[], summary='完成', details=dict(symbols=['SH600000']))
            experiment = save_result(store, job, project, result, run)
            self.assertEqual([a['name'] for a in experiment['artifacts']], ['prices'])
            saved = pd.read_parquet(run / 'prices.parquet')
            self.assertEqual(saved.symbol.tolist(), ['SH600000'])
            self.assertEqual(saved.close.tolist(), [10.5])
            self.assertEqual(saved.date.dt.strftime('%Y-%m-%d').tolist(), ['2025-01-03'])
            override['close'] = 11.; override.to_parquet(folder / 'SH600000.parquet', index=False)
            self.assertEqual(pd.read_parquet(run / 'prices.parquet').close.tolist(), [10.5])
