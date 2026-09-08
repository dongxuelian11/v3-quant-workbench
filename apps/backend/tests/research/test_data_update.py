import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack
from collections import Counter

import pandas as pd
import baostock
from v3_backend.research.storage import Store
from v3_backend.research import data


class QueryResult:
    def __init__(self, frame=None, error_code='0', error_msg=''):
        frame = pd.DataFrame() if frame is None else frame
        self.fields = list(frame.columns)
        self.rows = iter(frame.values.tolist())
        self.error_code, self.error_msg = error_code, error_msg

    def next(self):
        self.current = next(self.rows, None)
        return self.current is not None

    def get_row_data(self):
        return self.current


class AdjustmentUpdateTest(unittest.TestCase):
    def _two_stock_project(self, directory):
        store = Store(Path(directory) / 'app')
        project = store.create_project(Path(directory) / 'project', 'p')
        project['universe']['symbols'] = ['SH600000', 'SH600001']
        return store.save_project(project)

    def _mock_source(self, stack, history_error=None, financial_error=None):
        calls = Counter()
        stack.enter_context(patch('v3_backend.research.history.collect'))
        stack.enter_context(patch('v3_backend.research.benchmarks.collect'))

        def history(code, fields, **kwargs):
            key = (code, kwargs['adjustflag'])
            calls[key] += 1
            error = history_error(code, kwargs, calls[key]) if history_error else None
            if error is not None:
                return error
            dates = ['2025-01-02', '2025-01-03', '2025-01-06']
            if kwargs['adjustflag'] == '3':
                return QueryResult(pd.DataFrame({'date': dates, 'close': [20, 20, 20]}))
            return QueryResult(pd.DataFrame([dict(date=date, code=code, open=10, high=10, low=10, close=10, volume=100, amount=2000, tradestatus=1, isST=0) for date in dates]))

        def financial(**kwargs):
            error = financial_error(kwargs) if financial_error else None
            if error is not None:
                return error
            return QueryResult(pd.DataFrame([dict(code=kwargs['code'], pubDate='2025-01-06', statDate='2024-12-31', roeAvg='0.1')]))

        login = stack.enter_context(patch.object(baostock, 'login', return_value=SimpleNamespace(error_code='0')))
        stack.enter_context(patch.object(baostock, 'logout'))
        stack.enter_context(patch.object(baostock, 'query_history_k_data_plus', side_effect=history))
        stack.enter_context(patch.object(baostock, 'query_stock_basic', side_effect=lambda **_: QueryResult(pd.DataFrame({'ipoDate': ['1999-01-01']}))))
        for name in ['query_profit_data', 'query_growth_data', 'query_balance_data', 'query_cash_flow_data']:
            stack.enter_context(patch.object(baostock, name, side_effect=financial))
        return calls, login

    def test_second_stock_lost_login_retries_only_that_query_once(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            project = self._two_stock_project(directory)

            def expire(code, kwargs, count):
                if code == 'sh.600001' and kwargs['adjustflag'] == '2' and count == 1:
                    self.assertEqual(set(data.read_table(project).symbol), {'SH600000'})
                    self.assertEqual(set(data.read_table(project, 'financials').symbol), {'SH600000'})
                    return QueryResult(error_code='10001001', error_msg='用户未登录')

            calls, login = self._mock_source(stack, history_error=expire)
            result = data.update(project, dict(source='baostock', startDate='2025-01-02', endDate='2025-01-06', financials=True), lambda *_: None)
            self.assertEqual(login.call_count, 2)
            self.assertEqual(calls[('sh.600000', '2')], 1)
            self.assertEqual(calls[('sh.600001', '2')], 2)
            self.assertEqual(result['completedSymbols'], ['SH600000', 'SH600001'])
            self.assertEqual(result['status'], 'completed')

    def test_later_failure_preserves_data_and_rerun_skips_complete_stock(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self._two_stock_project(directory)
            params = dict(source='baostock', startDate='2025-01-02', endDate='2025-01-06', financials=True)
            with ExitStack() as stack:
                calls, login = self._mock_source(stack, financial_error=lambda p: QueryResult(error_code='10002001', error_msg='网络错误') if p['code'] == 'sh.600001' else None)
                with self.assertRaisesRegex(ValueError, '完整完成 1/2'):
                    data.update(project, params, lambda *_: None)
                self.assertEqual(login.call_count, 1)  # No blanket retry on network failures.
            self.assertEqual(set(data.read_table(project).symbol), {'SH600000', 'SH600001'})
            self.assertEqual(set(data.read_table(project, 'financials').symbol), {'SH600000'})
            self.assertTrue(any('未全部完成' in warning for warning in data.preview(project)['warnings']))
            with ExitStack() as stack:
                calls, _ = self._mock_source(stack)
                result = data.update(project, params, lambda *_: None)
                self.assertEqual(calls[('sh.600000', '2')], 0)
                self.assertEqual(calls[('sh.600001', '2')], 1)
            self.assertEqual(result['reusedSymbols'], ['SH600000'])
            self.assertEqual(set(data.read_table(project, 'financials').symbol), {'SH600000', 'SH600001'})

    def test_lost_login_retry_is_bounded(self):
        with ExitStack() as stack:
            login = stack.enter_context(patch.object(baostock, 'login', return_value=SimpleNamespace(error_code='0')))
            query = stack.enter_context(patch.object(baostock, 'query_stock_basic', side_effect=lambda **_: QueryResult(error_code='10001001', error_msg='用户未登录')))
            with self.assertRaisesRegex(ValueError, '用户未登录'):
                data._bs_query(baostock, query, code='sh.600000')
            self.assertEqual(query.call_count, 2)
            self.assertEqual(login.call_count, 1)

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

            with patch('v3_backend.research.history.collect'), patch('v3_backend.research.benchmarks.collect'), \
                 patch.object(baostock, 'login', return_value=SimpleNamespace(error_code='0')), patch.object(baostock, 'logout'), \
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
