import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import baostock
from v3_backend.research.storage import Store
from v3_backend.research import data


class AdjustmentUpdateTest(unittest.TestCase):
    def test_recent_update_refreshes_old_adjusted_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'app')
            project = store.create_project(Path(directory) / 'project', 'p')
            project['universe']['symbols'] = ['SH600000']
            store.save_project(project)
            old = pd.DataFrame([dict(symbol='SH600000', date=date, open=20, high=20, low=20, close=20, volume=100, factor=1) for date in ['2025-01-02', '2025-01-03']])
            data.merge_table(project, old, 'prices')
            calls = []

            def history(code, fields, **kwargs):
                calls.append(kwargs)
                dates = ['2025-01-02', '2025-01-03', '2025-01-06']
                if kwargs['adjustflag'] == '3':
                    return pd.DataFrame({'date': dates, 'close': [20, 20, 20]})
                return pd.DataFrame([dict(date=date, code=code, open=10, high=10, low=10, close=10, volume=100, amount=2000, tradestatus=1, isST=0) for date in dates])

            with patch.object(baostock, 'login', return_value=SimpleNamespace(error_code='0')), patch.object(baostock, 'logout'), \
                 patch.object(baostock, 'query_history_k_data_plus', side_effect=history), \
                 patch.object(baostock, 'query_stock_basic', return_value=pd.DataFrame({'ipoDate': ['1999-01-01']})), \
                 patch.object(data, '_bs_rows', side_effect=lambda value: value):
                data.update(project, dict(source='baostock', startDate='2025-01-06', endDate='2025-01-06'), lambda *_: None)
            self.assertTrue(all(call['start_date'] == '2025-01-02' for call in calls))
            updated = data.read_table(project)
            self.assertEqual(updated.close.tolist(), [10, 10, 10])
            self.assertEqual(updated.factor.tolist(), [.5, .5, .5])
            preview = data.preview(project)
            self.assertIn('missingValues', preview['datasets'][0])
            self.assertTrue(preview['warnings'])


if __name__ == '__main__':
    unittest.main()
