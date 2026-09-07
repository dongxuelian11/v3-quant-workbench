import tempfile
import unittest
from pathlib import Path
import pandas as pd
from v3_backend.research.storage import Store, write_json
from v3_backend.research import history, data


class HistoricalDataTest(unittest.TestCase):
    def test_members_and_industry_do_not_backfill(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Store(Path(temporary)/'app').create_project(Path(temporary)/'project','p')
            project['universe']['source'] = 'csi300'
            root = Path(project['path'])/'data/history'
            write_json(root/'csi300_2020-01-01.json', {'rows':[dict(symbol='SH600000',effectiveDate='2019-12-16',industry=None)]})
            write_json(root/'csi300_2020-07-01.json', {'rows':[dict(symbol='SH600001',effectiveDate='2020-06-15',industry=None)]})
            write_json(root/'industry_2020-07-01.json', {'rows':[dict(symbol='SH600001',effectiveDate='2020-06-15',industry='银行')]})
            self.assertEqual(history.members(project,'2019-01-01'),set())
            self.assertEqual(history.members(project,'2020-01-02'),{'SH600000'})
            self.assertEqual(history.members(project,'2020-06-16'),{'SH600001'})
            self.assertTrue(history.industries(project,'2020-01-02',['SH600001']).isna().all())
            history.import_membership(project,pd.DataFrame([dict(symbol='600002',startDate='2020-01-01',endDate='2020-02-01')]))
            self.assertEqual(history.members(project,'2020-01-02'),{'SH600002'})
            self.assertEqual(history.members(project,'2020-02-02'),set())

    def test_partition_merge_preserves_other_security(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Store(Path(temporary)/'app').create_project(Path(temporary)/'project','p')
            frame = pd.DataFrame([dict(symbol=code,date='2025-01-02',open=10,high=10,low=10,close=10,volume=100) for code in ['SH600000','SH600001']])
            data.merge_table(project,frame,'prices')
            root = Path(project['path'])/'data/prices'
            stamp = (root/'SH600001.parquet').stat().st_mtime_ns
            update = frame.iloc[:1].assign(close=11,high=11)
            data.merge_table(project,update,'prices',return_all=False)
            self.assertEqual((root/'SH600001.parquet').stat().st_mtime_ns,stamp)
            self.assertEqual(data.read_table(project).set_index('symbol').loc['SH600000','close'],11)
