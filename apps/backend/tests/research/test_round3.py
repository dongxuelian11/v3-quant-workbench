"""Round 3 scope, immutable submissions and a single global book."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from v3_backend.research.server import Service
from v3_backend.research import selection, positions, data
from v3_backend.research.portfolio import DEFAULTS
from test_engines import sample_project


class Round3Test(unittest.TestCase):
    def test_allocation_cash_and_merged_caps(self):
        proposals = [({'projectId':'p','strategyId':'a','allocation':.6},{'weights':pd.Series({'X':.5,'Y':.5}),'scores':pd.Series({'X':1.,'Y':1.})}),
                     ({'projectId':'p','strategyId':'b','allocation':.2},{'weights':pd.Series({'X':.25,'Z':.75}),'scores':pd.Series({'X':1.,'Z':3.})})]
        merged, frame = selection.merge_allocations(proposals)
        self.assertAlmostEqual(merged.X,.35)
        self.assertAlmostEqual(merged.Y,.30)
        self.assertAlmostEqual(merged.Z,.15)
        weights, errors = selection.constrain_merged(merged,pd.Series(dtype=float),pd.Series(dtype=float),pd.Series(dtype=object),{**DEFAULTS,'grossExposure':1})
        self.assertFalse(errors)
        self.assertAlmostEqual(weights.sum(),.8,places=6)
        capped, errors = selection.constrain_merged(merged,pd.Series(dtype=float),pd.Series(dtype=float),pd.Series(dtype=object),{**DEFAULTS,'grossExposure':1,'maxWeight':.3})
        self.assertFalse(errors)
        self.assertLessEqual(capped.X,.300001)
        self.assertLess(capped.sum(),.8)
        weights, errors = selection.constrain_merged(merged,pd.Series({'X':.9}),pd.Series({'X':.9}),pd.Series(dtype=object),{**DEFAULTS,'grossExposure':1})
        self.assertTrue(errors)

    def test_freeze_queued_strategy_book_and_global_records(self):
        with tempfile.TemporaryDirectory() as folder:
            service = Service(Path(folder)/'app')
            project = service.store.create_project(Path(folder)/'project','test')
            strategy = service.request('strategies.list',{'projectId':project['id']})[0]
            strategy['settings']['backtest'] = {'template':'single_factor','factorIds':['momentum20'],'topN':2}
            service.request('strategies.save',{'projectId':project['id'],'strategy':strategy})
            service.request('strategies.activate',{'projectId':project['id'],'strategyId':strategy['id'],'enabled':True,'allocation':.6})
            service.request('positions.save',{'positions':{'asOfDate':'2020-01-01','cash':100000,'rows':[]}})
            with patch.object(service.jobs,'_start_next'):
                job = service.jobs.submit({'kind':'selection.run','parameters':{'strategies':[{'projectId':project['id'],'strategyId':strategy['id'],'allocation':.6}],'updateData':False}})
            strategy['settings']['backtest']['topN'] = 9
            service.request('strategies.save',{'projectId':project['id'],'strategy':strategy})
            self.assertEqual(job['spec']['strategySnapshots'][0]['project']['settings']['backtest']['topN'],2)
            self.assertEqual(job['spec']['positionsSnapshot']['cash'],100000)
            self.assertEqual(len(service.store.list('job','')),1)
            run = Path(service.store.project(None)['path'])/'.research/runs/e'
            run.mkdir(parents=True)
            file = run/'table.parquet'
            pd.DataFrame({'value':[1]}).to_parquet(file)
            service.store.save_experiment(None,dict(id='e',projectId=None,kind='selection.run',name='e',createdAt='2026',parameters={},metrics={},artifacts=[{'name':'table','path':str(file),'type':'parquet'}],summary='',starred=False))
            self.assertEqual(len(service.request('experiments.list',{})),1)
            self.assertEqual(service.request('experiments.compare',{'experiments':[{'experimentId':'e'}]})[0]['tables'][0]['rows'][0]['value'],1)
            self.assertTrue(Path(service.request('exports.create',{'experimentId':'e','format':'csv'})['path']).is_file())
            service.close()

    def test_factor_only_multi_run_does_not_change_book(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project,dates,store = sample_project(root)
            snapshot = {'asOfDate':str(dates[-1]+pd.Timedelta(days=1))[:10],'cash':100000.,'rows':[]}
            global_project = store.project(None)
            positions.save(global_project,snapshot)
            before = positions.get(global_project)
            frozen=[]
            for key,codes,allocation in [('a',['SH600000','SH600001'],.6),('b',['SH600000','SH600002'],.2)]:
                scoped=copy.deepcopy(project)
                scoped['strategyId']=key
                scoped['universe']['symbols']=codes
                scoped['settings']['backtest']={'template':'single_factor','factorIds':['momentum20'],'topN':2,'portfolio':{'method':'equal','grossExposure':1}}
                frozen.append({'projectId':project['id'],'strategyId':key,'allocation':allocation,'project':scoped})
            output=Path(global_project['path'])/'.research/runs/test'
            output.mkdir(parents=True)
            result=selection.run(global_project,{'updateData':False,'portfolio':{'grossExposure':1}},output,lambda *_:None,snapshot=before,strategy_snapshots=frozen)
            self.assertAlmostEqual(result['metrics']['targetExposure'],.8,places=6)
            self.assertEqual(positions.get(global_project),before)
            self.assertEqual(result['details']['bookAsOfDate'],before['asOfDate'])
            self.assertEqual(result['details']['valuationDate'],str(dates[-1])[:10])
            self.assertTrue((output/'strategy_contributions.parquet').exists())
            self.assertEqual(len(pd.read_parquet(output/'rebalance.parquet').symbol.unique()),3)
            self.assertFalse((Path(project['path'])/'.research/selection-model.json').exists())

    def test_monthly_cache_isolates_strategy_and_universe(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            project,dates,store=sample_project(root)
            config={'enabled':True,'updateData':False,'model':{'model':'ridge','factorIds':['momentum20'],'labelHorizon':5},'strategy':{'template':'model_score','topN':2}}
            book={'asOfDate':str(dates[-1])[:10],'cash':100000.,'rows':[]}
            for key,codes in [('a',['SH600000','SH600001']),('b',['SH600000','SH600002'])]:
                scoped=copy.deepcopy(project)
                scoped['strategyId']=key
                scoped['universe']['symbols']=codes
                output=root/key
                output.mkdir()
                selection.run(scoped,config,output,lambda *_:None,snapshot=book,score_only=True)
            from v3_backend.research.storage import read_json
            a=Path(project['path'])/'.research/strategies/a/selection-model.json'
            b=Path(project['path'])/'.research/strategies/b/selection-model.json'
            self.assertNotEqual(read_json(a)['path'],read_json(b)['path'])
            scoped['strategyId']='a'
            with patch('v3_backend.research.selection.engines.model_estimator',wraps=selection.engines.model_estimator) as fit:
                selection.run(scoped,config,root/'a',lambda *_:None,snapshot=book,score_only=True)
                self.assertEqual(fit.call_count,1)
            self.assertEqual(read_json(a)['context']['universe']['symbols'],['SH600000','SH600002'])

    def test_global_typed_import_through_worker(self):
        import time
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            service=Service(root/'app')
            file=root/'flow.csv'
            pd.DataFrame([{'symbol':'SH600000','date':'2020-01-02','fund_net_amount':1000,'fund_net_ratio':.1}]).to_csv(file,index=False)
            try:
                job=service.jobs.submit({'kind':'data.import','parameters':{'files':[str(file)],'dataset':'flow'}})
                deadline=time.monotonic()+25
                while job['status'] in {'queued','running'} and time.monotonic()<deadline:
                    time.sleep(.05)
                    job=service.store.get('job',job['id'])
                self.assertEqual(job['status'],'completed',job['message'])
                detail=service.experiment_details(None,job['experimentId'])
                self.assertEqual(detail['tables'][0]['rows'][0]['fund_net_amount'],1000)
                self.assertEqual(len(service.request('experiments.list',{})),1)
            finally:
                service.close()


if __name__ == '__main__':
    unittest.main()
