"""Fixed research inputs survive mutable shared-data updates."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from v3_backend.research import data, input_snapshot
from v3_backend.research.server import Service


class InputReplay(unittest.TestCase):
    def test_capture_filters_unrelated_securities_and_keeps_warmup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = Service(root / 'app')
            try:
                project = service.store.create_project(root / 'project', 'Slice test')
                project['universe']['symbols'] = ['SH600000']
                rows = [dict(symbol=code, date=date, open=10., high=10., low=10., close=10., volume=100.)
                        for code in ('SH600000', 'SH600001') for date in pd.date_range('2020-01-01', periods=10)]
                data.merge_table(project, pd.DataFrame(rows), 'prices', return_all=False)
                original = pd.read_parquet
                read_paths = []
                def read(path, **kwargs):
                    read_paths.append(str(path))
                    return original(path, **kwargs)
                with patch.object(pd, 'read_parquet', side_effect=read):
                    frozen, _, ref = input_snapshot.capture(service.store, project,
                        {'startDate':'2020-01-05','endDate':'2020-01-08'}, root/'project/.research/runs/sliced',
                        {'inputStart':'2020-01-03', 'inputEnd':'2020-01-08'})
                self.assertFalse(any('SH600001' in path for path in read_paths))
                actual = data.read_table(frozen)
                self.assertEqual(len(actual), 6)
                self.assertEqual(str(actual.date.min().date()), '2020-01-03')
                self.assertEqual(str(actual.date.max().date()), '2020-01-08')
                self.assertEqual(ref['startDate'], '2020-01-03')
            finally:
                service.close()

    def test_chart_replay_preserves_partitioned_prices_and_financials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = Service(root / 'app')
            try:
                project = service.store.create_project(root / 'project', 'Snapshot test')
                project['universe']['symbols'] = ['SH600000']
                prices = pd.DataFrame([dict(symbol='SH600000', date=pd.Timestamp('2020-01-02'),
                    open=10., high=10., low=10., close=10., volume=100.)])
                financials = pd.DataFrame([dict(symbol='SH600000', announcementDate=pd.Timestamp('2019-10-30'),
                    reportDate=pd.Timestamp('2019-09-30'), roe=.1)])
                data.merge_table(project, prices, 'prices', return_all=False)
                data.merge_table(project, financials, 'financials', return_all=False)
                run = Path(project['path']) / '.research/runs/fixed'
                frozen, parameters, ref = input_snapshot.capture(service.store, project,
                    {'startDate': '2020-01-02', 'endDate': '2020-01-03'}, run, {})
                service.store.save_experiment(project['id'], dict(id='fixed', projectId=project['id'],
                    createdAt='', artifacts=[], inputSnapshot=ref, parameters=parameters))
                data.merge_table(project, prices.assign(close=20., high=20.), 'prices', return_all=False)
                data.merge_table(project, financials.assign(roe=.9), 'financials', return_all=False)
                selected, _, warning = service.chart_source(dict(projectId=project['id'], experimentId='fixed'))
                self.assertIsNone(warning)
                self.assertEqual(float(data.read_table(selected).close.iloc[0]), 10.)
                self.assertEqual(float(data.read_table(selected, 'financials').roe.iloc[0]), .1)
                (run / 'inputs/data/prices/SH600000.parquet').unlink()
                with self.assertRaisesRegex(ValueError, '原实验输入文件缺失'):
                    service.chart_source(dict(projectId=project['id'], experimentId='fixed'))
            finally:
                service.close()


if __name__ == '__main__':
    unittest.main()
