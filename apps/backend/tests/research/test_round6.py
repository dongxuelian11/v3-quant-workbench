import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from v3_backend.research import quotes, market_snapshot, preparation, data
from v3_backend.research.server import Service
from v3_backend.research.storage import write_json


class Round6Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.service=Service(self.root/'profile');self.store=self.service.store
        self.project=self.store.create_project(str(self.root/'project'),'测试','')

    def tearDown(self):
        self.service.close();self.temp.cleanup()

    def test_catalog_missing_empty_failure_preserves_cache(self):
        root=self.store.project(None)
        self.assertEqual(quotes.catalog(root,{'kind':'concept'})['status'],'missing')
        with patch.object(quotes,'_ak',return_value=pd.DataFrame([{'板块代码':'BK0884','板块名称':'光刻机'}])) as source:
            self.assertEqual(quotes.catalog(root,{'kind':'concept','loadIfMissing':True})['status'],'ready')
            self.assertEqual(quotes.catalog(root,{'kind':'concept','loadIfMissing':True,'query':'no-such'})['status'],'empty')
            self.assertEqual(source.call_count,1)
        path=quotes._root(root)/'catalog-concept.json';original=path.read_bytes()
        with patch.object(quotes,'_ak',side_effect=ValueError('离线')):
            failed=quotes.catalog(root,{'kind':'concept','refresh':True})
        self.assertEqual(failed['errors'],{'concept':'离线'});self.assertEqual(failed['total'],1)
        self.assertEqual(path.read_bytes(),original)

    def test_overview_independent_partial_and_units(self):
        def source(name,**args):
            if name=='stock_zh_a_spot_em':return pd.DataFrame([{'代码':'000001','名称':'平安银行','最新价':10,'涨跌幅':2,'成交量':3,'成交额':3000}])
            if name=='stock_zh_index_spot_em':return pd.DataFrame([{'代码':'000001','名称':'上证指数','最新价':3000,'涨跌幅':-1}])
            return pd.DataFrame([{'板块代码':'BK0884','板块名称':'板块','最新价':100,'涨跌幅':3}])
        with patch.object(quotes,'_ak',side_effect=source),patch.object(data,'read_table',side_effect=AssertionError('research sample')):
            value=self.service.request('market.overview',{'projectId':self.project['id'],'loadIfMissing':True})
        self.assertEqual(value['summary']['observedStocks'],1)
        self.assertEqual(value['indices'][0]['symbol'],'SH000001');self.assertIsNone(value['asOfDate'])
        stocks=market_snapshot.normalize(source('stock_zh_a_spot_em'),'stocks')
        self.assertEqual(stocks.iloc[0].symbol,'SZ000001');self.assertEqual(stocks.iloc[0].volume,300)
        with patch.object(quotes,'_ak',side_effect=ValueError('离线')):
            failed=self.service.request('market.overview',{'refresh':True})
        self.assertEqual(failed['summary'],value['summary']);self.assertTrue(failed['stale'])

    def test_project_run_requires_dates_and_does_not_create_strategy(self):
        spec={'projectId':self.project['id'],'kind':'factor.analyze','parameters':{'factorIds':['book_yield']}}
        with self.assertRaisesRegex(ValueError,'日期'):self.service.jobs.submit(spec)
        self.store.save_project({**self.project,'startDate':'2025-01-01','endDate':'2025-01-31'})
        with patch.object(self.service.jobs,'_start_next'):
            job=self.service.jobs.submit(spec)
        self.assertIsNone(job.get('strategyId'));self.assertNotIn('strategyId',job['spec']['projectSnapshot'])
        self.store.save_experiment(self.project['id'],{'id':'project-level','strategyId':None,'artifacts':[]})
        self.assertIsNone(self.store.experiment(self.project['id'],'project-level')['strategyId'])
        self.assertIsNone(next(e for e in self.store.experiments(self.project['id']) if e['id']=='project-level')['strategyId'])

    def test_cross_project_copy_freezes_inherited_dates(self):
        source={**self.project,'startDate':'2024-01-01','endDate':'2024-12-31'}
        self.store.save_project(source)
        original=self.service.request('strategies.list',{'projectId':source['id']})[0]
        target=self.store.create_project(str(self.root/'target'),'目标','')
        copied=self.service.request('strategies.create',{'projectId':target['id'],'fromProjectId':source['id'],'fromStrategyId':original['id']})
        self.store.save_project({**source,'startDate':'2025-01-01'})
        self.assertEqual(copied['settings']['startDate'],'2024-01-01')
        self.assertFalse(copied['enabled']);self.assertNotIn('active',copied)
        self.assertEqual(copied['projectId'],target['id'])

    def test_model_dependency_reuses_for_fees_and_invalidates_inputs(self):
        project={**self.project,'startDate':'2025-01-01','endDate':'2025-03-31','universe':{'source':'manual','symbols':['SH600000']}}
        model={'model':'ridge','factorIds':['book_yield'],'trainStart':'2025-01-01','trainEnd':'2025-01-31','validStart':'2025-02-01','validEnd':'2025-02-28','testStart':'2025-03-01','testEnd':'2025-03-31'}
        project['settings']={**project['settings'],'model':model};self.store.save_project(project)
        root=Path(data.project_data(project)['path'])/'data';root.mkdir(parents=True,exist_ok=True)
        frame=pd.DataFrame({'date':pd.date_range('2025-01-01','2025-03-31'),'symbol':'SH600000','open':10.,'high':10.,'low':10.,'close':10.,'factor':1.,'volume':100.})
        frame.to_parquet(root/'prices.parquet');(root/'benchmarks').mkdir()
        frame.to_parquet(root/'benchmarks/SH000300.parquet')
        job={'id':'parent','name':'回测','projectId':project['id'],'kind':'backtest.run','spec':{'parameters':{'template':'model_score','fee':.001}}}
        output=self.root/'output';output.mkdir()
        with patch.object(preparation.engines,'train',return_value={'metrics':{},'artifacts':[],'summary':'测试训练'} ) as train,patch.object(quotes,'_baostock',side_effect=AssertionError('network')):
            first,_=preparation.prepare(self.store,job,project,output,lambda *_:None)
            job['spec']['parameters']['fee']=.002
            second,_=preparation.prepare(self.store,job,project,output,lambda *_:None)
            self.assertEqual(first['modelExperimentId'],second['modelExperimentId']);self.assertEqual(train.call_count,1)
            project['settings']['model']['hyperparameters']={'alpha':2}
            third,_=preparation.prepare(self.store,job,project,output,lambda *_:None)
            self.assertNotEqual(first['modelExperimentId'],third['modelExperimentId']);self.assertEqual(train.call_count,2)

    def test_internal_gap_is_repaired_or_stops_with_preserved_report(self):
        project={**self.project,'startDate':'2025-01-01','endDate':'2025-01-03','universe':{'source':'manual','symbols':['SH600000']}}
        root=Path(data.project_data(project)['path'])/'data';root.mkdir(parents=True,exist_ok=True)
        frame=pd.DataFrame({'date':pd.to_datetime(['2025-01-01','2025-01-03']),'symbol':'SH600000','close':10.})
        frame.to_parquet(root/'prices.parquet');(root/'benchmarks').mkdir()
        pd.DataFrame({'date':pd.date_range('2025-01-01','2025-01-03')}).to_parquet(root/'benchmarks/SH000300.parquet')
        job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':['book_yield']}}}
        with patch.object(data,'update') as update,patch.object(quotes,'_baostock',return_value=None):
            with self.assertRaisesRegex(ValueError,'2025-01-02'):
                preparation.prepare(self.store,job,project,self.root/'gap',lambda *_:None)
        self.assertTrue(update.call_args.args[1]['repairGaps'])
        self.assertTrue((self.root/'gap/preparation.json').is_file())

    def test_existing_financial_field_with_short_coverage_is_refreshed(self):
        project={**self.project,'startDate':'2025-01-01','endDate':'2025-01-03','universe':{'source':'manual','symbols':['SH600000']}}
        root=Path(data.project_data(project)['path'])/'data';root.mkdir(parents=True,exist_ok=True)
        frame=pd.DataFrame({'date':pd.date_range('2025-01-01','2025-01-03'),'symbol':'SH600000','close':10.})
        frame.to_parquet(root/'prices.parquet');(root/'benchmarks').mkdir()
        frame.to_parquet(root/'benchmarks/SH000300.parquet')
        pd.DataFrame([{'symbol':'SH600000','roeAvg':.1,'announcementDate':pd.Timestamp('2024-10-01'),'reportDate':pd.Timestamp('2024-09-30')}]).to_parquet(root/'financials.parquet')
        write_json(root/'financials/SH600000.json',{'start':'2024-01-01','end':'2024-12-31'})
        job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':['roe']}}}
        with patch.object(data,'_financial_update') as update,patch.object(quotes,'_baostock',side_effect=lambda operation:operation(object())):
            preparation.prepare(self.store,job,project,self.root/'financial',lambda *_:None)
        update.assert_called_once()

    def test_holiday_and_completed_cutoff_do_not_fetch_or_use_future(self):
        project={**self.project,'startDate':'2025-09-30','endDate':'2025-10-06','universe':{'source':'manual','symbols':['SH600000']}}
        root=Path(data.project_data(project)['path'])/'data';root.mkdir(parents=True,exist_ok=True)
        pd.DataFrame({'date':pd.to_datetime(['2025-09-30']),'symbol':'SH600000','close':10.}).to_parquet(root/'prices.parquet')
        write_json(root/'trading-calendar.json',{'start':'2025-09-30','end':'2025-10-06','dates':['2025-09-30']})
        job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':['book_yield']}}}
        with patch.object(quotes,'_baostock',side_effect=AssertionError('holiday network')),patch('v3_backend.research.selection.update_end_date',return_value='2025-10-03'):
            params,report=preparation.prepare(self.store,job,project,self.root/'holiday',lambda *_:None)
        self.assertEqual(params['endDate'],'2025-10-03');self.assertEqual(report['requestedEnd'],'2025-10-06')
        self.assertEqual(report['effectiveEnd'],'2025-10-03')

    def test_simulation_scope_uses_account_and_explicit_end(self):
        self.store.save_project({**self.project,'startDate':'2020-01-01','endDate':'2030-01-01'})
        account=self.service.request('simulation.accounts.create',{'projectId':self.project['id'],'strategyId':'default','startDate':'2025-01-02'})
        spec={'projectId':self.project['id'],'kind':'simulation.advance','parameters':{'accountId':account['id']}}
        with self.assertRaisesRegex(ValueError,'结束日期'):self.service.jobs.submit(spec)
        spec['parameters']['endDate']='2025-01-27'
        with patch.object(self.service.jobs,'_start_next'):
            job=self.service.jobs.submit(spec)
        self.assertEqual(preparation.scope(job['spec']['projectSnapshot'],job['spec']['parameters'],'simulation.advance'),('2025-01-02','2025-01-27'))
