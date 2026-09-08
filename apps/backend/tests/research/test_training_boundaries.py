"""Targeted real-Qlib regressions for future features and immature rolling labels."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from v3_backend.research import engines
from test_engines import sample_project


class TrainingBoundaryTest(unittest.TestCase):
    def test_future_window_rejected_and_causal_qlib_expression_preserved(self):
        for expression in ['Delta($close,-1)', 'Delta($close,1-2)', 'Mean($close,-2)',
                           'Corr($close,$volume,-1)', 'Cov($close,$volume,1-3)',
                           'EMA($close,-.5)', 'Delta($close,If($close>0,1,-1))']:
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                engines.validate_expression(expression)
        for expression in ['$close/Ref($close,20)', 'Delta($close,1)',
                           'Mean($close,10+10)', 'EMA($close,.5)', 'Sum($volume,0)']:
            self.assertEqual(engines.validate_expression(expression), expression)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, dates, _ = sample_project(root)
            prices = engines.prepare(project, root/'prepare', lambda *_: None)
            from qlib.data import D
            values = D.features(['SH600000'], ['Delta($close,-1)', 'Delta($close,1)'],
                                start_time=dates[40], end_time=dates[42]).xs('SH600000', level='instrument')
            close = prices[prices.symbol.eq('SH600000')].set_index('date').close
            # The rejected upstream expression really uses tomorrow's close.
            self.assertAlmostEqual(values.iloc[0, 0], close.loc[dates[40]]-close.loc[dates[41]], places=5)
            self.assertAlmostEqual(values.iloc[1, 1], close.loc[dates[41]]-close.loc[dates[40]], places=5)

    def test_final_rolling_window_predicts_without_mature_test_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, dates, _ = sample_project(root)
            output = root/'rolling'
            output.mkdir()
            bounds = dict(trainStart=str(dates[0]), trainEnd=str(dates[69]),
                          validStart=str(dates[70]), validEnd=str(dates[99]),
                          testStart=str(dates[114]), testEnd=str(dates[119]))
            params = dict(model='ridge', factorIds=['momentum20', 'volatility20'],
                          labelHorizon=5, labelMode='next_open', hyperparameters={'alpha':1.},
                          validation={'mode':'rolling'})
            with patch('v3_backend.research.processing.windows', return_value=[bounds]):
                result = engines.train(project, params, output, lambda *_: None)
            predictions = pd.read_parquet(output/'test_predictions.parquet')
            self.assertEqual(len(predictions), 6*12)
            self.assertTrue(predictions.score.notna().all())
            self.assertTrue(predictions.label.isna().all())
            self.assertIsNone(result['metrics']['test:mse'])
            self.assertIsNotNone(result['metrics']['valid:mse'])
            self.assertEqual(result['details']['testEvaluationUnavailableWindows'], [0])
            frame = pd.DataFrame({'label':1.}, index=pd.MultiIndex.from_product([dates, ['SH600000']], names=['datetime','instrument']))
            with self.assertRaisesRegex(ValueError, 'test'):
                engines.time_segments(frame, dates, bounds, 5)
            # Allowing immature test labels must never relax the training boundary.
            with self.assertRaisesRegex(ValueError, 'train'):
                engines.time_segments(frame, dates, {**bounds, 'trainEnd':str(dates[2]), '_allowUnmaturedTest':True}, 5)


if __name__ == '__main__':
    unittest.main()
