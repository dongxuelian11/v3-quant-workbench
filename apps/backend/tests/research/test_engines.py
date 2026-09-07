"""Small real-library integration samples; no fabricated production outputs."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from v3_backend.research.storage import Store
from v3_backend.research.data import merge_table
from v3_backend.research import engines


def sample_project(root):
    store = Store(root / 'app')
    project = store.create_project(root / 'project', 'test')
    dates = pd.bdate_range('2020-01-01', periods=120)
    rng = np.random.default_rng(47)
    rows = []
    for number in range(12):
        close = 20 * np.cumprod(1 + rng.normal(.0005, .01, len(dates)))
        for date, value in zip(dates, close):
            rows.append(dict(symbol=f'SH{600000 + number}', date=date, open=value * .999, high=value * 1.01,
                             low=value * .99, close=value, volume=1000000, amount=value * 1000000, isST=0))
    merge_table(project, pd.DataFrame(rows), 'prices')
    return project, dates, store


class EngineTest(unittest.TestCase):
    def test_real_alphalens(self):
        with tempfile.TemporaryDirectory() as directory:
            project, dates, store = sample_project(Path(directory))
            output = Path(directory) / 'analysis'
            output.mkdir()
            result = engines.analyze(project, {'factorIds': ['momentum20'], 'periods': [1, 5], 'quantiles': 5}, output, lambda *_: None)
            self.assertIn('momentum20:IC:1D', result['metrics'])
            self.assertTrue((output / 'momentum20_samples.parquet').exists())

    def test_pit_never_uses_same_day_announcement(self):
        with tempfile.TemporaryDirectory() as directory:
            project, dates, _ = sample_project(Path(directory))
            merge_table(project, pd.DataFrame([dict(symbol='SH600000', reportDate=pd.Timestamp('2019-12-31'), announcementDate=dates[40], roeAvg=3.5)]), 'financials')
            output = Path(directory) / 'pit'
            output.mkdir()
            prices = engines.prepare(project, output, lambda *_: None)
            values = engines.features(project, {'factorIds': ['roe']}, prices)
            series = values.xs('SH600000', level='instrument').roe
            self.assertTrue(pd.isna(series.loc[dates[40]]))
            self.assertAlmostEqual(series.loc[dates[41]], 3.5)

    def test_labels_do_not_cross_segments(self):
        dates = pd.bdate_range('2020-01-01', periods=30)
        frame = pd.DataFrame({'label': 1}, index=pd.MultiIndex.from_product([dates, ['SH600000']], names=['datetime', 'instrument']))
        params = dict(trainStart=str(dates[0]), trainEnd=str(dates[9]), validStart=str(dates[10]), validEnd=str(dates[19]), testStart=str(dates[20]), testEnd=str(dates[29]))
        split = engines.time_segments(frame, dates, params, 3)
        self.assertEqual(split['train'].index.get_level_values(0).max(), dates[6])
        self.assertEqual(split['valid'].index.get_level_values(0).max(), dates[16])

    def test_real_qlib_cost_and_next_session(self):
        with tempfile.TemporaryDirectory() as directory:
            project, dates, store = sample_project(Path(directory))
            output = Path(directory) / 'backtest'
            output.mkdir()
            result = engines.backtest(project, {'template': 'single_factor', 'factorIds': ['momentum20'], 'topN': 3, 'rebalance': 'weekly', 'capital': 1000000}, output, lambda *_: None, store=store)
            report = pd.read_parquet(output / 'portfolio.parquet')
            self.assertGreater(report.cost.sum(), 0)
            trades = pd.read_parquet(output / 'trades.parquet')
            signals = pd.read_parquet(output / 'signals.parquet')
            self.assertGreater(pd.Timestamp(trades.date.min()), signals.datetime.min())

    def test_custom_expression_rejects_future_and_python(self):
        for expression in ["__import__('os').system('whoami')", 'Ref($close,-1)', 'Ref($close,1-2)', '$close.__class__']:
            with self.assertRaises(ValueError):
                engines.validate_expression(expression)
        self.assertEqual(engines.validate_expression('$close/Ref($close,20)'), '$close/Ref($close,20)')

    def test_ridge_and_optuna_grid_use_real_estimators(self):
        with tempfile.TemporaryDirectory() as directory:
            project, dates, store = sample_project(Path(directory))
            parameters = dict(model='ridge', factorIds=['momentum20'], trainStart=str(dates[0]), trainEnd=str(dates[59]),
                              validStart=str(dates[60]), validEnd=str(dates[89]), testStart=str(dates[90]), testEnd=str(dates[-1]),
                              labelHorizon=3, hyperparameters={'alpha': 1.0})
            output = Path(directory) / 'model'
            output.mkdir()
            result = engines.train(project, parameters, output, lambda *_: None)
            self.assertIn('valid:mse', result['metrics'])
            optimized = Path(directory) / 'optimize'
            optimized.mkdir()
            result = engines.optimize(project, dict(target='model', sampler='grid', trials=2, baseParameters=parameters,
                searchSpace={'hyperparameters.alpha': [.1, 1.0]}), optimized, lambda *_: None, store)
            self.assertEqual(len(pd.read_parquet(optimized / 'trials.parquet')), 2)
            self.assertTrue(np.isfinite(result['metrics']['best_value']))

    def test_suspension_blocks_actual_qlib_orders_and_invalid_search_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            project, dates, store = sample_project(Path(directory))
            path = Path(project['path']) / 'data' / 'prices.parquet'
            prices = pd.read_parquet(path)
            prices['tradestatus'] = 1
            halted = prices.symbol.eq('SH600000')
            prices.loc[halted, 'volume'] = 0
            prices.loc[halted, 'tradestatus'] = 0
            prices.to_parquet(path, index=False)
            output = Path(directory) / 'suspended'
            output.mkdir()
            engines.backtest(project, dict(template='single_factor', factorIds=['momentum20'], topN=1, rebalance='daily',
                code="scores.loc[:] = 0\nscores.loc[scores.index.get_level_values('instrument') == 'SH600000'] = 10"), output, lambda *_: None, store=store)
            trades = pd.read_parquet(output / 'trades.parquet')
            self.assertTrue(trades.empty)
        with self.assertRaises(ValueError):
            engines.validate_search_key('model', 'learning_rate', {'model': 'lightgbm'})
        engines.validate_search_key('model', 'hyperparameters.learning_rate', {'model': 'lightgbm'})


if __name__ == '__main__':
    unittest.main()
