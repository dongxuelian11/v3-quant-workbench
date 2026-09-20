"""RD bridge tests use explicit synthetic fixtures, never production fallback data."""
from copy import deepcopy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from test_engines import sample_project
from v3_backend.research import rd_agent, worker, data
from v3_backend.research.storage import write_json, read_json, now
from v3_backend.research.workbench import strategy_project


class RDBridgeTests(unittest.TestCase):
    def fixture(self, root):
        project, dates, store=sample_project(root)
        # This fixture is explicitly unadjusted synthetic OHLC, so raw fields are known.
        prices=data.read_table(project)
        for field in ('open','high','low','close'):prices['raw'+field.title()]=prices[field]
        prices['factor']=1.;prices['tradestatus']=1
        prices['rawPreclose']=prices.groupby('symbol').rawClose.shift(1).fillna(prices.rawClose)
        data.merge_table(project,prices,'prices')
        project=strategy_project(store,project['id'])
        params=dict(action='factor',objective='explicit test fixture',rounds=1,codeRepairRounds=1,
            trainStart=str(dates[0].date()),trainEnd=str(dates[59].date()),
            validStart=str(dates[60].date()),validEnd=str(dates[89].date()),
            testStart=str(dates[90].date()),testEnd=str(dates[-1].date()),labelHorizon=2,
            factorIds=['momentum20'],evaluationBacktest={'template':'single_factor','topN':3,'capital':100000})
        folder=Path(project['path'])/'.research/runs/rd_fixture';folder.mkdir(parents=True)
        job=dict(id='rd_fixture',projectId=project['id'],strategyId=project['strategyId'],kind='rdagent.run',
                 name='RD fixture',spec={'parameters':params,'projectSnapshot':project})
        return store,project,params,folder,job

    def test_frozen_inputs_real_baseline_factor_model_and_revaluation(self):
        with tempfile.TemporaryDirectory() as temp:
            store,project,params,folder,job=self.fixture(Path(temp))
            frozen,config,prices=rd_agent._snapshot_inputs(project,params,folder,lambda *_:None)
            dataset=pd.read_parquet(folder/'rd_inputs/dataset.parquet')
            self.assertEqual(set(dataset.partition),{'train','valid'})
            self.assertLessEqual(dataset.date.max(),pd.Timestamp(params['validEnd']))
            for name in ('train','valid'):
                rows=dataset[dataset.partition.eq(name)]
                self.assertTrue(rows.loc[~rows.labelEndDate.le(pd.Timestamp(params[name+'End'])),'label'].isna().all())
            baseline=rd_agent.evaluate_request(store,job,frozen,{'id':'baseline','action':'baseline'},config,prices,folder,lambda *_:None)
            self.assertTrue(np.isfinite(list(baseline['metrics'].values())).all())
            experiment=store.experiment(project['id'],baseline['experimentIds'][0])
            report=pd.read_parquet(store.artifact_path(project['id'],next(a for a in experiment['artifacts'] if a['name']=='portfolio')))
            excess=report['return']-report.cost-report.bench;curve=(1+excess).cumprod()
            self.assertAlmostEqual(baseline['metrics']['1day.excess_return_with_cost.max_drawdown'],float((curve/curve.cummax().clip(lower=1)-1).min()))
            code=folder/'factor.py';code.write_text('# authored fixture of retained output\n')
            factors=folder/'native-factor.parquet'
            dataset.set_index(['date','symbol'])[['momentum20']].rename_axis(['datetime','instrument']).rename(columns={'momentum20':'authored'}).to_parquet(factors)
            request=dict(id='factor_fixture',action='factor',name='fixture',description='authored values',
                         factorPath=rd_agent.linux_path(factors),codePath=rd_agent.linux_path(code))
            response=rd_agent.evaluate_request(store,job,frozen,request,config,prices,folder,lambda *_:None)
            self.assertTrue(response['candidateId']);self.assertEqual(len(response['experimentIds']),2)
            again=rd_agent.evaluate_request(store,job,frozen,request,config,prices,folder,lambda *_:None)
            self.assertEqual(again['candidateId'],response['candidateId'])
            self.assertEqual(again['experimentIds'],response['experimentIds'])
            prediction=folder/'prediction.parquet'
            dataset[dataset.partition.eq('valid')].rename(columns={'momentum20':'prediction'})[['date','symbol','label','partition','prediction']].to_parquet(prediction,index=False)
            model=folder/'model.py';model.write_text('import torch\nclass Tiny(torch.nn.Module):\n    pass\nmodel_cls=Tiny\n')
            request=dict(id='model_fixture',action='model',name='authored retained fixture',description='no training claim',
                         predictionPath=rd_agent.linux_path(prediction),codePath=rd_agent.linux_path(model))
            response=rd_agent.evaluate_request(store,job,frozen,request,config,prices,folder,lambda *_:None)
            from v3_backend.research.candidates import get
            candidate=get(store,project['id'],response['candidateId'])
            rejob={'kind':'model.train','spec':{'parameters':candidate['spec']['parameters'],'candidateSnapshot':candidate}}
            destination=folder/'reevaluate';destination.mkdir()
            result=worker.execute(store,rejob,project,destination,lambda *_:None)
            self.assertFalse(result['details']['trained'])
            self.assertNotIn('test:mse',result['metrics'])
            new_code=Path(project['path'])/candidate['spec']['parameters']['codePath']
            new_code.write_text('# changed\n')
            with self.assertRaisesRegex(ValueError,'代码已修改'):
                worker.execute(store,rejob,project,destination,lambda *_:None)
            changed=data.read_table(project);changed['close']*=2
            data.merge_table(project,changed,'prices')
            pd.testing.assert_frame_equal(data.read_table(frozen),prices)

    def test_cancel_confirms_linux_before_owner_and_queue_release(self):
        from v3_backend.research.jobs import Jobs
        with tempfile.TemporaryDirectory() as temp:
            store,project,params,folder,job=self.fixture(Path(temp))
            jobs=Jobs(store,lambda *_:None)
            job.update(status='running',progress=.2,createdAt=now(),updatedAt=now(),message='fixture')
            jobs._save(job)
            class Process:
                returncode=0
                def wait(self,timeout=None):return 0
                def poll(self):return 0
            process=Process();jobs.processes[job['id']]=process
            order=[]
            with patch.object(rd_agent,'stop',side_effect=lambda *_:order.append('linux')), \
                 patch.object(rd_agent,'terminate_owner',side_effect=lambda *_:order.append('owner')), \
                 patch.object(jobs,'_start_next',side_effect=lambda *_:order.append('queue')):
                jobs.cancel(job['id'])
                self.assertEqual(order,['linux','owner'])
                jobs._watch(job['id'],process,folder,io.BytesIO())
                self.assertEqual(order,['linux','owner','linux','queue'])
            jobs.processes[job['id']]=process
            with patch.object(rd_agent,'stop',side_effect=RuntimeError('not confirmed')),patch.object(jobs,'_start_next') as start:
                jobs._watch(job['id'],process,folder,io.BytesIO())
                start.assert_not_called()
                self.assertIn(job['id'],jobs.processes)
                self.assertTrue(store.get('job',job['id'])['cleanupPending'])

    def test_task_parameters_reject_credentials_and_unbounded_rounds(self):
        with tempfile.TemporaryDirectory() as temp:
            _,_,params,_,_=self.fixture(Path(temp))
            with self.assertRaisesRegex(ValueError,'凭据'):rd_agent.validate({**params,'apiKey':'not-a-real-secret'})
            with self.assertRaisesRegex(ValueError,'1至3'):rd_agent.validate({**params,'rounds':4})


if __name__=='__main__':unittest.main()
