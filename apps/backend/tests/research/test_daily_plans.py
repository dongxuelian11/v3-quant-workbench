import tempfile, unittest, time
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from test_engines import sample_project
from v3_backend.research import positions,screening_run,data
from v3_backend.research.server import Service

class DailyPlansTests(unittest.TestCase):
    def setup(self,root):
        project,dates,store=sample_project(root)
        project['universe']=dict(source='manual',symbols=[f'SH{600000+i}' for i in range(12)],excludeST=False,minListingDays=0)
        store.save_project(project)
        service=Service(root/'app')
        plan=service.request('screeners.save',dict(plan=dict(name='独立因子',mode='factors',dataProjectId=project['id'],universe=project['universe'],factors=[dict(id='momentum20',direction=-1,weight=1)],limit=2,conditions=dict(id='root',match='all',children=[]))))
        daily=service.request('dailyPlans.save',dict(planId=plan['id'],allocation=.5,enabled=True))
        return project,dates,store,service,plan,daily

    def test_version_adoption_and_frozen_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            project,dates,store,service,plan,daily=self.setup(Path(temp))
            try:
                plan['limit']=5;new=service.request('screeners.save',dict(plan=plan))
                saved=service.request('dailyPlans.save',dict(id=daily['id'],allocation=.3))
                self.assertEqual(saved['planSnapshot']['limit'],2);self.assertTrue(saved['sourceChanged'])
                with patch.object(service.jobs,'_start_next'):
                    job=service.jobs.submit(dict(kind='selection.run',parameters=dict(dailyPlanIds=[daily['id']],date=str(dates[-1].date()))))
                adopted=service.request('dailyPlans.save',dict(id=daily['id'],adoptLatest=True))
                self.assertEqual(adopted['planVersion'],new['version']);self.assertEqual(adopted['planSnapshot']['limit'],5)
                self.assertEqual(job['spec']['dailyPlanSnapshots'][0]['planSnapshot']['limit'],2)
                self.assertEqual(job['spec']['dailyPlanSnapshots'][0]['allocation'],.3)
                with self.assertRaisesRegex(ValueError,'混用'):
                    service.jobs.submit(dict(kind='selection.run',parameters=dict(dailyPlanIds=[daily['id']],strategies=[])))
                with self.assertRaisesRegex(ValueError,'预览'):
                    service.jobs.submit(dict(kind='selection.run',parameters=dict(dailyPlanIds=[daily['id']],allowPartial=True)))
            finally:service.close()

    def test_real_worker_factor_to_global_orders_and_missing_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            project,dates,store,service,plan,daily=self.setup(Path(temp))
            try:
                before=positions.save(store.project(None),dict(cash=100000,rows=[],asOfDate=str(dates[-1].date())))
                def run():
                    job=service.jobs.submit(dict(kind='selection.run',parameters=dict(dailyPlanIds=[daily['id']],date=str(dates[-1].date()))))
                    deadline=time.monotonic()+45
                    while time.monotonic()<deadline:
                        job=store.get('job',job['id'])
                        if job['status'] not in ('queued','running'):break
                        time.sleep(.05)
                    return job
                job=run();self.assertEqual(job['status'],'completed',job.get('message'))
                result=store.experiment(None,job['experimentId'])
                target=next(a for a in result['artifacts'] if a['name']=='target_weights')
                weights=pd.read_parquet(store.artifact_path(None,target))
                self.assertEqual(len(weights),2);self.assertAlmostEqual(weights.targetWeight.sum(),.475,places=5)
                self.assertEqual(positions.get(store.project(None)),before)
                source=Path(data.project_data(project)['path'])/'data/prices/SH600000.parquet'
                rows=pd.read_parquet(source);rows[rows.date.ne(dates[-1])].to_parquet(source,index=False)
                with patch('v3_backend.research.data.update',side_effect=AssertionError('no network')):
                    # Local entry uses file source and must fail on incomplete candidates.
                    frozen=job['spec']['dailyPlanSnapshots'][0]
                    frozen['project']['settings']['dataSources']={'daily':'file','financials':'file'}
                    fixed_plan=frozen['planSnapshot'];fixed_plan['date']=str(dates[-1].date())
                    with self.assertRaises(ValueError):screening_run.run(store,frozen['project'],dict(plan=fixed_plan),Path(store.project(None)['path'])/'.research/runs/missing',lambda *_:None,daily_snapshot=before)
            finally:service.close()

    def test_monthly_model_uses_frozen_configuration_and_fails_without_fallback(self):
        import joblib
        from v3_backend.research import engines,selection,daily_plans
        with tempfile.TemporaryDirectory() as temp:
            project,dates,store,service,plan,daily=self.setup(Path(temp))
            try:
                training=dict(model='ridge',factorIds=['momentum20'],labelHorizon=5,trainStart=str(dates[20].date()),testStart=str(dates[80].date()))
                artifact=Path(project['path'])/'model.joblib';joblib.dump({'old':'must not be used as estimator'},artifact)
                store.save_experiment(project['id'],dict(id='model',kind='model.train',projectId=project['id'],name='模型',createdAt='2020-01-01',parameters=training,artifacts=[dict(name='model',type='joblib',path=str(artifact))]))
                plan.update(mode='conditions',factors=[],assets=[dict(id='model-ref',kind='model',projectId=project['id'],experimentId='model',revision='1',name='模型',snapshot=dict(parameters=training,modelExperimentId='model'))],conditions=dict(id='root',match='all',children=[dict(id='positive',field='model_score',operator='gt',value=-100)]))
                plan=service.request('screeners.save',dict(plan=plan));service.request('dailyPlans.save',dict(id=daily['id'],adoptLatest=True))
                frozen=daily_plans.freeze(store,[daily['id']],{'daily':'file','financials':'file'})
                snapshot=dict(cash=100000,rows=[])
                params=dict(dailyPlanIds=[daily['id']],date=str(dates[-1].date()))
                result=selection.run(store.project(None),params,Path(store.project(None)['path'])/'.research/runs/first',lambda *_:None,snapshot=snapshot,daily_plan_snapshots=frozen,store=store)
                self.assertGreater(result['details']['strategies'][0]['model']['trainingRows'],0)
                with patch.object(engines,'model_estimator',side_effect=AssertionError('must reuse monthly model')):
                    selection.run(store.project(None),params,Path(store.project(None)['path'])/'.research/runs/second',lambda *_:None,snapshot=snapshot,daily_plan_snapshots=frozen,store=store)
                changed=__import__('copy').deepcopy(frozen)
                changed[0]['planSnapshot']['assets'][0]['snapshot']['parameters']['labelHorizon']=4
                with patch.object(engines,'model_estimator',side_effect=ValueError('controlled retrain failure')):
                    with self.assertRaisesRegex(ValueError,'controlled retrain failure'):
                        selection.run(store.project(None),params,Path(store.project(None)['path'])/'.research/runs/failed',lambda *_:None,snapshot=snapshot,daily_plan_snapshots=changed,store=store)
            finally:service.close()

    def test_account_code_uses_real_holdings_and_builtin_revision_is_guarded(self):
        from v3_backend.research import selection,daily_plans
        with tempfile.TemporaryDirectory() as temp:
            project,dates,store,service,plan,daily=self.setup(Path(temp))
            try:
                code="def decide(context):\n    return {'targets': {'SH600000': .2} if context['holdings'].get('SH600000',{}).get('quantity') == 100 and context['cash'] == 1000 else {}}"
                plan.update(mode='strategy',factors=[],assets=[dict(id='strategy-ref',kind='strategy',revision='1',name='真实账户',snapshot=dict(settings=dict(backtest=dict(template='multi_factor',factorIds=[],dailyCode=code))))])
                plan=service.request('screeners.save',dict(plan=plan));service.request('dailyPlans.save',dict(id=daily['id'],adoptLatest=True))
                frozen=daily_plans.freeze(store,[daily['id']],{'daily':'file','financials':'file'})
                result=selection.run(store.project(None),dict(date=str(dates[-1].date())),Path(store.project(None)['path'])/'.research/runs/account',lambda *_:None,
                    snapshot=dict(cash=1000,rows=[dict(symbol='SH600000',quantity=100,sellableQuantity=100)]),daily_plan_snapshots=frozen,store=store)
                target=next(a for a in result['artifacts'] if a['name']=='target_weights')
                weights=pd.read_parquet(target['path']);self.assertAlmostEqual(weights.targetWeight.sum(),.1)
                bad=frozen[0]['planSnapshot'];bad['assets'].append(dict(id='builtin:momentum20',kind='factor',name='旧表达式',snapshot=dict(factorId='momentum20',expression='old')))
                with self.assertRaisesRegex(ValueError,'表达式已变化'):
                    screening_run.run(store,frozen[0]['project'],dict(plan=bad),Path(store.project(None)['path'])/'.research/runs/bad',lambda *_:None)
            finally:service.close()
