import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from test_engines import sample_project
from v3_backend.research import selection, positions
from v3_backend.research.rules import limits, fees, affordable, COST_DEFAULTS


class SelectionTest(unittest.TestCase):
    def test_known_volume_and_historical_project_end(self):
        from v3_backend.research.portfolio import DEFAULTS
        market = pd.DataFrame([dict(symbol='SH600000',date=pd.Timestamp('2025-01-06'),rawClose=10.,volume=1000)]).set_index('symbol')
        orders,_,_,_ = selection.estimate_orders(dict(cash=100000,rows=[]),pd.Series({'SH600000':.9}),market,COST_DEFAULTS,DEFAULTS,pd.Series(dtype=object))
        self.assertEqual(orders.quantity.iloc[0],100)
        self.assertIn('参与率',orders.reason.iloc[0])
        project = dict(path='unused',startDate='2015-01-01',endDate='2020-01-01')
        with patch('v3_backend.research.selection.data.update',side_effect=RuntimeError('captured')) as update:
            with self.assertRaisesRegex(RuntimeError,'captured'):
                selection.run(project,dict(enabled=True,model={'model':'ridge'},strategy={'template':'model_score'}),Path('unused'),lambda *_:None)
            self.assertEqual(update.call_args.args[1]['endDate'],selection.update_end_date())

    def test_historical_rules_and_star_cash(self):
        self.assertEqual(limits('SH600000','2025-01-01',10.05)[1],11.06)
        self.assertEqual(limits('SZ300001','2025-01-01',10,True)[1],12)
        self.assertEqual(limits('SH600000','2026-07-06',10,True)[1],11)
        self.assertAlmostEqual(fees(10000,'sell','2023-08-27')['total'],15.1)
        self.assertAlmostEqual(fees(10000,'sell','2023-08-28')['total'],10.1)
        self.assertEqual(affordable('SH688001',200,10,2005.01,'2025-01-01',COST_DEFAULTS),0)
        self.assertEqual(affordable('SH688001',201,10,2015.0201,'2025-01-01',COST_DEFAULTS),201)

    def test_latest_prediction_reuses_monthly_model_without_mutating_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            project,dates,_ = sample_project(Path(directory))
            snapshot = positions.save(project,dict(asOfDate=str(dates[-1])[:10],cash=100000,rows=[]))
            params = dict(enabled=True,updateData=False,retrain='monthly',
                          model=dict(model='ridge',factorIds=['momentum20'],labelHorizon=5,hyperparameters={'alpha':1}),
                          strategy=dict(template='model_score',topN=3,portfolio={'method':'equal'}))
            output = Path(project['path'])/'.research/runs/first'
            output.mkdir(parents=True)
            result = selection.run(project,params,output,lambda *_:None)
            self.assertEqual(result['details']['dataDate'],str(dates[-1])[:10])
            self.assertEqual(len(pd.read_parquet(output/'candidates.parquet')),12)
            self.assertEqual(positions.get(project),snapshot)
            second = output.parent/'second'
            second.mkdir()
            with patch('v3_backend.research.engines.model_estimator',side_effect=AssertionError('unexpected refit')):
                reused = selection.run(project,params,second,lambda *_:None)
            self.assertEqual(reused['details']['modelUpdatedAt'],result['details']['modelUpdatedAt'])
            self.assertLess(pd.Timestamp(result['details']['trainingEnd']),dates[-6])
            from v3_backend.research.storage import write_json,read_json
            from v3_backend.research.worker import run
            third = output.parent/'third'
            third.mkdir()
            write_json(third/'request.json',dict(appData=str(Path(directory)/'app'),job=dict(id='third',projectId=project['id'],kind='selection.run',name='选股',spec={'parameters':params})))
            self.assertEqual(run(third),0)
            self.assertEqual(read_json(third/'result.json')['experiment']['kind'],'selection.run')


if __name__ == '__main__':
    unittest.main()
