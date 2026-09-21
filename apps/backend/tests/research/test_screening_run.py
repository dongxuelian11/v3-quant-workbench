import tempfile,unittest,json
from pathlib import Path
import pandas as pd
from test_engines import sample_project
from v3_backend.research import screening_run,data

class ScreeningRunTests(unittest.TestCase):
    def plan(self,project,date,mode='conditions'):
        return dict(id='plan',name='筛选',version=1,mode=mode,date=str(date.date()),universe=project['universe'],
            conditions=dict(id='root',match='all',children=[]),factors=[],assets=[],rankingReference='base')

    def test_preview_missing_session_is_not_skipped_in_temporal_rule(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,dates,store=sample_project(root)
            project['universe']=dict(source='manual',symbols=[f'SH{600000+i}' for i in range(12)],excludeST=False,minListingDays=0)
            path=Path(data.project_data(project)['path'])/'data/prices/SH600000.parquet'
            rows=pd.read_parquet(path);rows[rows.date.ne(dates[-2])].to_parquet(path,index=False)
            plan=self.plan(project,dates[-1]);plan['conditions']['children']=[dict(id='positive',field='close',operator='gt',value=0,window=2,occurrence='all')]
            result=screening_run.run(store,project,dict(plan=plan,allowPartial=True),Path(project['path'])/'.research/runs/test',lambda *_:None)
            frame=pd.read_parquet(result['artifacts'][0]['path']).set_index('symbol')
            self.assertEqual(frame.loc['SH600000','status'],'missing')
            self.assertEqual(result['details']['counts'],dict(scope=12,valid=11,included=11,missing=1))
            self.assertEqual(result['details']['status'],'preview')
            self.assertFalse(result['details']['diff']['available'])
            self.assertEqual(result['inputSnapshot']['status'],'available')

    def test_factor_direction_once_and_scope_before_rank(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,dates,store=sample_project(root)
            project['universe']=dict(source='manual',symbols=[f'SH{600000+i}' for i in range(12)],excludeST=False,minListingDays=0)
            plan=self.plan(project,dates[-1],'factors');plan.update(factors=[dict(id='momentum20',direction=-1,weight=1)],limit=1)
            result=screening_run.run(store,project,dict(plan=plan,allowPartial=True),Path(project['path'])/'.research/runs/test',lambda *_:None)
            frame=pd.read_parquet(result['artifacts'][0]['path'])
            prices=data.read_table(project);last=prices[prices.date.eq(dates[-1])].set_index('symbol').close
            old=prices[prices.date.eq(dates[-21])].set_index('symbol').close
            expected=(last/old-1).idxmin()
            self.assertEqual(frame.loc[frame.status.eq('included'),'symbol'].tolist(),[expected])
            self.assertAlmostEqual(float(frame.loc[frame.symbol.eq(expected),'score'].iloc[0]),1.)

    def test_public_worker_complete_preview_and_prior_complete_diff(self):
        import time
        from v3_backend.research.server import Service
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source,dates,store=sample_project(root)
            source['universe']=dict(source='manual',symbols=[f'SH{600000+i}' for i in range(12)],excludeST=False,minListingDays=0)
            store.save_project(source)
            service=Service(root/'app')
            try:
                plan=self.plan(source,dates[-1]);plan.pop('id');plan['dataProjectId']=source['id']
                plan['conditions']['children']=[dict(id='positive',field='close',operator='gt',value=0)]
                plan=service.request('screeners.save',dict(plan=plan))
                def run(partial):
                    job=service.request('screeners.run',dict(planId=plan['id'],allowPartial=partial));deadline=time.monotonic()+40
                    while time.monotonic()<deadline:
                        job=store.get('job',job['id'])
                        if job['status'] not in ['queued','running']:break
                        time.sleep(.05)
                    self.assertEqual(job['status'],'completed',job.get('message'))
                    return service.request('screeners.result',dict(planId=plan['id'],experimentId=job['experimentId']))
                first=run(False);self.assertEqual(first['status'],'complete');self.assertEqual(first['counts']['included'],12)
                preview=run(True);self.assertEqual(preview['status'],'preview');self.assertFalse(preview['diff']['available'])
                again=run(False);self.assertEqual(again['diff']['previousExperimentId'],first['experimentId'])
                self.assertEqual(again['diff']['added'],[]);self.assertEqual(again['diff']['removed'],[])
            finally:service.close()

    def test_prefilter_and_st_exclusion_precede_ranking(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,dates,store=sample_project(root)
            project['universe']=dict(source='manual',symbols=[f'SH{600000+i}' for i in range(12)],excludeST=True,minListingDays=0)
            all_prices=data.read_table(project);last=all_prices[all_prices.date.eq(dates[-1])].sort_values('close')
            highest=last.iloc[-1].symbol;median=float(last.close.median());expected=last.iloc[-2].symbol
            path=Path(data.project_data(project)['path'])/'data/prices'/(highest+'.parquet')
            values=pd.read_parquet(path);values['isST']=1;values.to_parquet(path,index=False)
            plan=self.plan(project,dates[-1]);plan.update(rankingReference='prefilter',preconditions=dict(id='pre',match='all',children=[dict(id='above',field='close',operator='gt',value=median)]))
            plan['conditions']['children']=[dict(id='top',field='close',operator='rank_top',value=1)]
            result=screening_run.run(store,project,dict(plan=plan,allowPartial=True),Path(project['path'])/'.research/runs/test',lambda *_:None)
            frame=pd.read_parquet(result['artifacts'][0]['path']).set_index('symbol')
            self.assertEqual(frame.loc[highest,'status'],'outside')
            self.assertEqual(frame.loc[expected,'status'],'included')
            self.assertEqual(result['details']['counts']['missing'],0)

    def test_saved_model_predictions_keep_missing_dates_and_fixed_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,dates,store=sample_project(root)
            project['universe']=dict(source='manual',symbols=['SH600000','SH600001'],excludeST=False,minListingDays=0)
            pred=Path(project['path'])/'predictions.parquet'
            pd.DataFrame({'datetime':[dates[-1]],'instrument':['SH600000'],'score':[.12]}).to_parquet(pred,index=False)
            store.save_experiment(project['id'],dict(id='model',kind='model.train',projectId=project['id'],name='保存预测',createdAt='2025-01-01',parameters={},artifacts=[dict(name='test_predictions',type='parquet',path=str(pred))]))
            plan=self.plan(project,dates[-1]);plan['assets']=[dict(id='model-ref',kind='model',projectId=project['id'],experimentId='model',snapshot={},name='保存预测',revision='model')]
            plan['conditions']['children']=[dict(id='positive',field='model_score',operator='gt',value=0)]
            result=screening_run.run(store,project,dict(plan=plan,allowPartial=True),Path(project['path'])/'.research/runs/test',lambda *_:None)
            frame=pd.read_parquet(result['artifacts'][0]['path']).set_index('symbol')
            self.assertEqual(frame.loc['SH600000','status'],'included');self.assertEqual(frame.loc['SH600001','status'],'missing')
            fixed=Path(project['path'])/result['inputSnapshot']['path']
            snapshot=json.loads((fixed/'snapshot.json').read_text(encoding='utf-8'))
            frozen=Path(project['path'])/snapshot['parameters']['modelScoreFiles'][0]['dataPath']
            original=frozen.read_bytes();pred.write_bytes(b'changed source')
            self.assertEqual(frozen.read_bytes(),original)

    def test_strategy_reuses_decision_code_and_keeps_direction_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,dates,store=sample_project(root)
            project['universe']=dict(source='manual',symbols=[f'SH{600000+i}' for i in range(12)],excludeST=False,minListingDays=0)
            plan=self.plan(project,dates[-1],'strategy');plan['limit']=1
            plan['assets']=[dict(id='strategy',kind='strategy',name='反向动量',revision='1',snapshot={'settings':{'backtest':{'template':'single_factor','factorIds':['momentum20'],'factorProcessing':{'directions':{'momentum20':-1}},'code':'scores = scores * 2'}}})]
            result=screening_run.run(store,project,dict(plan=plan,allowPartial=True),Path(project['path'])/'.research/runs/test',lambda *_:None)
            frame=pd.read_parquet(result['artifacts'][0]['path']);prices=data.read_table(project)
            last=prices[prices.date.eq(dates[-1])].set_index('symbol').close;old=prices[prices.date.eq(dates[-21])].set_index('symbol').close
            self.assertEqual(frame.loc[frame.status.eq('included'),'symbol'].tolist(),[(last/old-1).idxmin()])
            self.assertAlmostEqual(float(frame.loc[frame.status.eq('included'),'score'].iloc[0]),2.)

    def test_formal_calendar_does_not_infer_market_holiday_from_missing_prices(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir()
            project={'path':temp}
            pd.DataFrame({'date':pd.to_datetime(['2025-01-02','2025-01-06'])}).to_parquet(root/'data/prices.parquet')
            with patch.object(screening_run.preparation,'trading_dates',return_value=['2025-01-02','2025-01-03','2025-01-06']) as calendar:
                days=screening_run._calendar(project,'2025-01-06',False,2)
                calendar.assert_called_once();self.assertIn('2025-01-03',days)

    def test_legacy_search_and_sort_determine_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,dates,store=sample_project(root)
            project['universe']=dict(source='manual',symbols=[f'SH{600000+i}' for i in range(12)],excludeST=False,minListingDays=0)
            plan=self.plan(project,dates[-1]);plan.update(query={'search':'60000','sortBy':'close','descending':False},limit=1)
            result=screening_run.run(store,project,dict(plan=plan,allowPartial=True),Path(project['path'])/'.research/runs/test',lambda *_:None)
            frame=pd.read_parquet(result['artifacts'][0]['path']);prices=data.read_table(project)
            candidate=prices[prices.date.eq(dates[-1]) & prices.symbol.str.contains('60000')].sort_values('close').iloc[0].symbol
            self.assertEqual(frame.loc[frame.status.eq('included'),'symbol'].tolist(),[candidate])
            self.assertEqual(frame.set_index('symbol').loc['SH600011','status'],'outside')

    def test_saved_estimator_scores_beyond_original_prediction_dates(self):
        import joblib
        from sklearn.linear_model import Ridge
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,dates,store=sample_project(root)
            project['universe']=dict(source='manual',symbols=[f'SH{600000+i}' for i in range(12)],excludeST=False,minListingDays=0)
            model_path=Path(project['path'])/'estimator.joblib'
            estimator=Ridge().fit(pd.DataFrame({'momentum20':[-2.,-1.,0.,1.,2.]}),[-2.,-1.,0.,1.,2.]);joblib.dump(estimator,model_path)
            training=dict(factorIds=['momentum20'],testStart=str(dates[60].date()),testEnd=str(dates[90].date()))
            store.save_experiment(project['id'],dict(id='model',kind='model.train',projectId=project['id'],name='固定模型',createdAt='2025-01-01',parameters=training,artifacts=[dict(name='model',type='joblib',path=str(model_path))]))
            plan=self.plan(project,dates[-1]);plan['assets']=[dict(id='model-ref',kind='model',projectId=project['id'],experimentId='model',snapshot={},name='固定模型',revision='model')]
            plan['conditions']['children']=[dict(id='positive',field='model_score',operator='gt',value=0)]
            result=screening_run.run(store,project,dict(plan=plan,allowPartial=True),Path(project['path'])/'.research/runs/test',lambda *_:None)
            self.assertEqual(result['details']['counts']['missing'],0)
            self.assertEqual(result['details']['modelScoring'],'固定估计器推理')
            self.assertGreater(result['details']['counts']['included'],0)
