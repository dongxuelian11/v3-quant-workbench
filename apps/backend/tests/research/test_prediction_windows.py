import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from test_engines import sample_project
from v3_backend.research import engines,benchmarks


class PredictionWindowsTest(unittest.TestCase):
    def test_first_day_loss_drawdown(self):
        report = pd.DataFrame({'return':[-.1,0.],'cost':[0.,0.],'bench':[-.05,0.]},index=pd.bdate_range('2024-01-01',periods=2))
        _,tables = benchmarks.analyze(report)
        np.testing.assert_allclose(tables['drawdown'].portfolio,[-.1,-.1])
        np.testing.assert_allclose(tables['drawdown'].benchmark,[-.05,-.05])

    def test_full_x_prediction_and_validation_only_portfolio_search(self):
        with tempfile.TemporaryDirectory() as directory:
            project,dates,store = sample_project(Path(directory))
            output = Path(project['path'])/'.research/runs/model'
            output.mkdir(parents=True)
            params = dict(model='ridge',factorIds=['momentum20'],trainStart=str(dates[0]),trainEnd=str(dates[59]),
                          validStart=str(dates[60]),validEnd=str(dates[89]),testStart=str(dates[90]),testEnd=str(dates[-1]),labelHorizon=5)
            model = engines.train(project,params,output,lambda *_:None)
            predictions = pd.read_parquet(output/'test_predictions.parquet')
            self.assertEqual(pd.Timestamp(predictions.datetime.max()),dates[-1])
            self.assertTrue(predictions.loc[predictions.datetime>=dates[-6],'label'].isna().all())
            store.save_experiment(project['id'],dict(id='model',kind='model.train',parameters=model['parameters'],artifacts=model['artifacts']))
            optimized = output.parent/'optimization'
            optimized.mkdir()
            bounds = {key:params[key] for key in ['trainStart','trainEnd','validStart','validEnd','testStart','testEnd']}
            result = engines.optimize(project,dict(target='backtest',sampler='grid',trials=1,objective='valid:annualized_return',
                                      baseParameters=dict(template='model_score',modelExperimentId='model',topN=3),
                                      validation=bounds,searchSpace={'topN':[3]}),optimized,lambda *_:None,store)
            valid = pd.read_parquet(optimized/'trial_0/window_0/signals.parquet')
            self.assertLess(valid.datetime.max(),dates[90])
            holdout = pd.read_parquet(optimized/'holdout/portfolio.parquet')
            self.assertEqual(pd.Timestamp(holdout.date.max()),dates[-1])
            self.assertTrue(np.isfinite(result['metrics']['best_value']))
