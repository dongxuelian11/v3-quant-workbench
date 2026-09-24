import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import pandas as pd
from qlib.config import C
from v3_backend.research.server import Service
from v3_backend.research import simulation_advance as advance,simulation_accounts as records,worker


class SharedAdvanceTests(unittest.TestCase):
    def setUp(self):
        C.set(region='cn');self.tmp=tempfile.TemporaryDirectory();self.service=Service(Path(self.tmp.name)/'app');self.store=self.service.store
        self.account=self.call('create',name='共享',capital=10000,startDate='2025-01-02')
        self.project=self.store.create_project(Path(self.tmp.name)/'source','源')
        self.project['universe'].update(source='manual',symbols=['SH600000'],minListingDays=0,excludeST=False)
        self.project['settings']['backtest']=dict(template='multi_factor',factorIds=[],rebalance='daily',costs={'slippage':0},
            dailyCode="def decide(context):\n return {'targets': {'SH600000': .5}}")
        self.store.save_project(self.project)
        self.account=self.call('bindings.save',accountId=self.account['id'],expectedRevision=0,source=dict(kind='strategy',projectId=self.project['id'],strategyId='default'),allocation=1)
        self.prices=pd.DataFrame([dict(date=d,symbol='SH600000',open=10.,high=10.1,low=9.9,close=10.,rawOpen=10.,rawHigh=10.1,rawLow=9.9,rawClose=10.,rawPreclose=10.,factor=1.,volume=1000000,amount=10000000,isST=0,tradestatus=1,listingDate=pd.Timestamp('2000-01-01')) for d in pd.bdate_range('2025-01-01','2025-01-10')])
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def call(self,op,**params):return self.service.request('simulation.accounts.'+op,params)
    def sources(self,store,account,params,output,progress):
        result={}
        for b in account['bindings']:
            for v in b['versions']:
                result[b['id']+':'+v['id']]=dict(binding=b,version=v,project=v['snapshot']['project'],prices=self.prices,calendar=[str(d.date()) for d in pd.bdate_range(account['startDate'],params['endDate'])],actions=[],folder=output,inputSnapshot={'path':'fixture'})
        return result,[]
    def run_to(self,end,job=None):
        if job is None:
            a=self.call('get',accountId=self.account['id'])
            with patch.object(self.service.jobs,'_start_next'):
                job=self.service.jobs.submit(dict(kind='simulation.advance',parameters=dict(accountId=a['id'],expectedRevision=a['revision'],endDate=end,updateData=False)))
        folder=Path(self.tmp.name)/job['id'];folder.mkdir(exist_ok=True)
        with patch.object(advance,'prepare_sources',side_effect=self.sources):
            result=worker.execute(self.store,job,self.store.project(None),folder,lambda *_:None)
        return job,result
    def test_real_daily_matching_ownership_cashflows_and_replay(self):
        job,result=self.run_to('2025-01-03');a=result['details']['account']
        trades=self.service.request('simulation.table',dict(accountId=a['id'],table='trades'))['rows']
        owners=self.service.request('simulation.table',dict(accountId=a['id'],table='ownership'))['rows']
        self.assertEqual(len(trades),1);self.assertEqual(trades[0]['date'],'2025-01-03')
        self.assertEqual(sum(o['quantity'] for o in owners),trades[0]['amount'])
        allocations=self.service.request('simulation.table',dict(accountId=a['id'],table='trade_allocations'))['rows']
        self.assertAlmostEqual(sum(x['fees'] for x in allocations),trades[0]['cost'])
        self.assertEqual(owners[0]['sellableQuantity'],0)
        _,again=self.run_to('2025-01-03',job);self.assertEqual(again['metrics']['completedDays'],0)
        self.assertEqual(self.call('get',accountId=a['id'])['revision'],a['revision'])
        flow=self.call('cashFlows.create',accountId=a['id'],expectedRevision=a['revision'],requestId='deposit',direction='deposit',amount=2000)
        self.assertEqual(flow['account']['unitNav'],a['unitNav']);self.assertEqual(flow['cashFlow']['date'],'2025-01-03')
        with self.assertRaisesRegex(ValueError,'版本'):self.run_to('2025-01-03',job)
        branch=self.call('branch',accountId=a['id'],expectedRevision=flow['account']['revision'],requestId='branch',fromDate='2025-01-03',name='分支')
        self.assertEqual(branch['pendingDecision'],flow['account']['pendingDecision'])
        self.assertEqual(branch['ownership'],flow['account']['ownership'])
    def test_new_version_does_not_rebuy_existing_ticker_and_old_version_can_exit(self):
        a=self.call('get',accountId=self.account['id']);binding=a['bindings'][0]
        strategy=self.store.project_store(self.project['id']).get('strategy','default')
        strategy['settings']['backtest']['dailyCode']="def decide(context):\n return {'targets': {} if str(context['date'])[:10] >= '2025-01-06' else {'SH600000': .5}}"
        self.store.project_store(self.project['id']).put('strategy',strategy,self.project['id'])
        preview=self.call('bindings.preview',accountId=a['id'],bindingId=binding['id'])
        self.call('bindings.adopt',accountId=a['id'],expectedRevision=a['revision'],bindingId=binding['id'],expectedSourceVersion=preview['sourceVersion'])
        _,result=self.run_to('2025-01-03');a=result['details']['account'];binding=a['bindings'][0];old=binding['currentVersionId']
        # Adopt new code through the public API; the old frozen exit version stays unchanged.
        strategy['settings']['backtest']['dailyCode']="def decide(context):\n return {'targets': {'SH600000': .5}}"
        self.store.project_store(self.project['id']).put('strategy',strategy,self.project['id'])
        preview=self.call('bindings.preview',accountId=a['id'],bindingId=binding['id'])
        a=self.call('bindings.adopt',accountId=a['id'],expectedRevision=a['revision'],bindingId=binding['id'],expectedSourceVersion=preview['sourceVersion'])
        _,result=self.run_to('2025-01-07');a=result['details']['account']
        allocations=self.service.request('simulation.table',dict(accountId=a['id'],table='trade_allocations'))['rows']
        sells=[x for x in allocations if x['direction']==0]
        self.assertTrue(sells);self.assertTrue(all(x['versionId']==old for x in sells))
        buys=[x for x in allocations if x['direction']==1]
        self.assertEqual(len(buys),1)

    def test_missing_calendar_session_blocks_and_account_research_is_read_only(self):
        # The frozen calendar includes Jan 3 even when the entire day's prices are missing.
        self.prices=self.prices[self.prices.date.ne(pd.Timestamp('2025-01-03'))]
        with self.assertRaisesRegex(ValueError,'交易日缺完整行情'):self.run_to('2025-01-06')
        a=self.call('get',accountId=self.account['id']);self.assertEqual(a['asOfDate'],'2025-01-02')
        self.assertFalse(self.service.request('simulation.table',dict(accountId=a['id'],table='trades'))['rows'])
        before=deepcopy(a)
        with patch.object(self.service.jobs,'_start_next'):
            with self.assertRaisesRegex(ValueError,'取消自由方案'):
                self.service.jobs.submit(dict(kind='selection.run',parameters=dict(positionsSource=dict(kind='simulation',accountId=a['id']),dailyPlanIds=['free'])))
            job=self.service.jobs.submit(dict(kind='selection.run',parameters=dict(positionsSource=dict(kind='simulation',accountId=a['id']),date='2025-01-06',updateData=False)))
        with patch.object(advance,'prepare_sources',side_effect=self.sources):
            result=worker.execute(self.store,job,self.store.project(None),Path(self.tmp.name)/'read-only',lambda *_:None)
        self.assertEqual(result['details']['positionsSourceResolved']['revision'],a['revision'])
        self.assertFalse(result['details']['executable']);self.assertEqual(self.call('get',accountId=a['id']),before)

    def test_full_local_preparation_and_next_day_matching(self):
        from v3_backend.research.storage import write_json
        from v3_backend.research import data
        row=self.prices.iloc[0].to_dict()
        self.prices=pd.DataFrame([{**row,'date':day} for day in pd.bdate_range('2023-01-02','2025-01-10')])
        data.merge_table(self.project,self.prices,'prices')
        root=Path(data.project_data(self.project)['path'])/'data'
        write_json(root/'trading-calendar.json',dict(start='2025-01-01',end='2025-01-10',dates=[str(d.date()) for d in pd.bdate_range('2025-01-01','2025-01-10')]))
        # Source settings are part of the adopted configuration.
        a=self.call('get',accountId=self.account['id'])
        a['bindings'][0]['versions'][0]['snapshot']['project']['settings']['dataSources']={'daily':'file','financials':'file'}
        self.store.project_store(None).put('simulation',a)
        with patch.object(self.service.jobs,'_start_next'):
            job=self.service.jobs.submit(dict(kind='simulation.advance',parameters=dict(accountId=a['id'],expectedRevision=a['revision'],endDate='2025-01-03',updateData=False)))
        folder=Path(self.store.project(None)['path'])/'.research/runs/full-preparation'
        with patch.object(data,'update',side_effect=AssertionError('no network')):
            result=worker.execute(self.store,job,self.store.project(None),folder,lambda *_:None)
            again=worker.execute(self.store,job,self.store.project(None),folder,lambda *_:None)
        self.assertEqual(result['details']['account']['asOfDate'],'2025-01-03')
        self.assertTrue(self.service.request('simulation.table',dict(accountId=a['id'],table='trades'))['rows'])
        self.assertEqual(again['metrics']['completedDays'],0)
        self.assertTrue(list(folder.glob('inputs/*/*/inputs/snapshot.json')))

    def test_two_owners_exit_as_one_net_trade_and_fee_allocations_conserve(self):
        from v3_backend.research.execution import cost_config
        a=self.call('get',accountId=self.account['id']);b=a['bindings'][0];first=b['versions'][0];second=deepcopy(first);second['id']='old-version';b['versions'].append(second)
        a['asOfDate']='2025-01-02';a['state'].update(cash=6000,asOfDate='2025-01-02',holdings={'SH600000':dict(quantity=400,sellableQuantity=400,costPrice=10)})
        a['cash']=6000;a['ownership']=[dict(id=key,symbol='SH600000',bindingId=b['id'],entryVersionId=v['id'],management='rules',quantity=200,sellableQuantity=200,pendingQuantity=0,costBasis=2000) for key,v in [('one',first),('two',second)]]
        a['pendingDecision']=dict(date='2025-01-02',reasons=[],intents=[dict(ownershipId=o['id'],bindingId=o['bindingId'],versionId=o['entryVersionId'],symbol=o['symbol'],targetQuantity=0,costs=cost_config({})) for o in a['ownership']])
        self.store.project_store(None).put('simulation',a)
        _,result=self.run_to('2025-01-03')
        trades=self.service.request('simulation.table',dict(accountId=a['id'],table='trades'))['rows'];allocations=self.service.request('simulation.table',dict(accountId=a['id'],table='trade_allocations'))['rows']
        self.assertEqual(len(trades),1);self.assertEqual(trades[0]['direction'],0);self.assertEqual(trades[0]['amount'],400)
        self.assertEqual([r['quantity'] for r in allocations],[200,200]);self.assertAlmostEqual(sum(r['fees'] for r in allocations),trades[0]['cost'])
        self.assertEqual(sum(o['quantity'] for o in result['details']['account']['ownership']),0)

    def test_cash_only_local_calendar_and_before_start_flow_is_not_return(self):
        from v3_backend.research import data
        from v3_backend.research.storage import write_json
        a=self.call('create',name='现金',capital=1000,startDate='2025-01-02')
        a=self.call('cashFlows.create',accountId=a['id'],expectedRevision=0,requestId='initial-flow',direction='deposit',amount=1000)['account']
        root=Path(data.project_data(self.store.project(None))['path'])/'data'
        write_json(root/'trading-calendar.json',dict(start='2025-01-01',end='2025-01-10',dates=['2025-01-02','2025-01-03']))
        with patch.object(self.service.jobs,'_start_next'):
            job=self.service.jobs.submit(dict(kind='simulation.advance',parameters=dict(accountId=a['id'],expectedRevision=a['revision'],endDate='2025-01-03')))
        result=worker.execute(self.store,job,self.store.project(None),Path(self.tmp.name)/'cash-only',lambda *_:None)
        self.assertEqual(result['details']['account']['nav'],2000)
        rows=self.service.request('simulation.table',dict(accountId=a['id'],table='portfolio'))['rows']
        self.assertTrue(all(row['netReturn']==0 and row['unitNav']==1 for row in rows))
        self.assertEqual(result['details']['account']['asOfDate'],'2025-01-03')

    def test_daily_plan_binding_real_offline_signal_path(self):
        from v3_backend.research import data
        from v3_backend.research.storage import write_json
        row=self.prices.iloc[0].to_dict();self.prices=pd.DataFrame([{**row,'date':day} for day in pd.bdate_range('2023-01-02','2025-01-10')]);data.merge_table(self.project,self.prices,'prices')
        root=Path(data.project_data(self.project)['path'])/'data'
        write_json(root/'trading-calendar.json',dict(start='2023-01-02',end='2025-01-10',dates=[str(d.date()) for d in pd.bdate_range('2023-01-02','2025-01-10')]))
        plan=self.service.request('screeners.save',dict(plan=dict(name='收盘正值',mode='conditions',dataProjectId=self.project['id'],universe=self.project['universe'],assets=[],factors=[],conditions=dict(id='root',match='all',children=[dict(id='positive',field='close',operator='gt',value=0)]))))
        daily=self.service.request('dailyPlans.save',dict(planId=plan['id'],allocation=1,enabled=True))
        a=self.call('create',name='每日绑定',capital=10000,startDate='2025-01-02')
        a=self.call('bindings.save',accountId=a['id'],expectedRevision=0,source=dict(kind='dailyPlan',dailyPlanId=daily['id']),allocation=.5)
        with patch.object(self.service.jobs,'_start_next'):
            job=self.service.jobs.submit(dict(kind='simulation.advance',parameters=dict(accountId=a['id'],expectedRevision=a['revision'],endDate='2025-01-03',updateData=False)))
        with patch.object(data,'update',side_effect=AssertionError('no network')):
            result=worker.execute(self.store,job,self.store.project(None),Path(self.store.project(None)['path'])/'.research/runs/daily-binding',lambda *_:None)
        self.assertIsNone(result['details']['account']['unresolved'])
        trades=self.service.request('simulation.table',dict(accountId=a['id'],table='trades'))['rows']
        self.assertTrue(trades);self.assertLessEqual(trades[0]['value'],5000)

    def test_output_root_keeps_original_membership_and_project_industry(self):
        from v3_backend.research import input_snapshot,history,data
        from v3_backend.research.storage import write_json
        data.merge_table(self.project,self.prices,'prices')
        members=pd.DataFrame([dict(symbol='SH600000',startDate='2025-01-01',endDate=None)])
        history.import_membership(self.project,members,pool_id='local-pool')
        write_json(Path(self.project['path'])/'data/history/industry_import.json',dict(rows=[dict(symbol='SH600000',effectiveDate='2025-01-01',industry='source-industry')]))
        shared=self.store.project(None)
        write_json(Path(shared['path'])/'data/history/industry_import.json',dict(rows=[dict(symbol='SH600000',effectiveDate='2025-01-01',industry='wrong-shared')]))
        output=Path(shared['path'])/'.research/runs/cross-root';output.mkdir(parents=True)
        fixed,_,ref=input_snapshot.capture(self.store,self.project,dict(startDate='2025-01-01',endDate='2025-01-03'),output,{},output_root=shared['path'])
        self.assertEqual(fixed['path'],shared['path'])
        self.assertTrue((Path(shared['path'])/ref['path']/'snapshot.json').is_file())
        self.assertEqual(history.membership_frame(fixed).symbol.tolist(),['SH600000'])
        self.assertEqual(history.read(fixed,'industry').industry.tolist(),['source-industry'])
        default=Path(self.project['path'])/'.research/runs/original-root';default.mkdir(parents=True)
        old,_,old_ref=input_snapshot.capture(self.store,self.project,dict(startDate='2025-01-01',endDate='2025-01-03'),default,{})
        self.assertEqual(old['path'],self.project['path']);self.assertTrue((Path(old['path'])/old_ref['path']).exists())

    def test_independent_failed_binding_keeps_allocation_and_other_binding_runs(self):
        a=self.call('get',accountId=self.account['id']);a['bindings'][0]['allocation']=.5
        other=deepcopy(a['bindings'][0]);other['id']='binding-b';other['name']='B';other['versions'][0]['id']='version-b';other['currentVersionId']='version-b'
        other['versions'][0]['snapshot']['project']['universe']['symbols']=['SH600001']
        other['versions'][0]['snapshot']['project']['settings']['backtest']['dailyCode']="def decide(context):\n return {'targets': {'SH600001': .5}}"
        a['bindings'].append(other);self.store.project_store(None).put('simulation',a)
        duplicate=self.prices.copy();duplicate['symbol']='SH600001';self.prices=pd.concat([self.prices,duplicate],ignore_index=True)
        real_sources=self.sources
        def isolated(*args):
            sources,_=real_sources(*args);sources={k:v for k,v in sources.items() if v['binding']['id']=='binding-b'}
            return sources,[dict(bindingId=a['bindings'][0]['id'],versionId=a['bindings'][0]['currentVersionId'],stage='prepare',message='A source unavailable')]
        with patch.object(self,'sources',side_effect=isolated):_,result=self.run_to('2025-01-03')
        final=result['details']['account'];self.assertEqual(final['status'],'blocked');self.assertIn('A source unavailable',final['unresolved']['message'])
        trades=self.service.request('simulation.table',dict(accountId=a['id'],table='trades'))['rows']
        self.assertTrue(trades);self.assertEqual({x['symbol'] for x in trades},{'SH600001'})
        self.assertLessEqual(sum(x['value'] for x in trades),2500)
        self.assertEqual([b['allocation'] for b in final['bindings']],[.5,.5])

    def test_fee_conflict_is_explicit_expired_and_does_not_block_unrelated_ticker(self):
        from v3_backend.research.execution import cost_config
        a=self.call('get',accountId=self.account['id']);b=a['bindings'][0]
        default=cost_config({});changed={**default,'minCommission':default['minCommission']+1}
        a['asOfDate']='2025-01-02';a['state']['asOfDate']='2025-01-02'
        a['pendingDecision']=dict(date='2025-01-02',reasons=[],intents=[dict(ownershipId=key,bindingId=b['id'],versionId=b['currentVersionId'],symbol=symbol,targetQuantity=100,costs=costs) for key,symbol,costs in [('one','SH600000',default),('two','SH600000',changed),('other','SH600001',default)]])
        self.store.project_store(None).put('simulation',a)
        duplicate=self.prices.copy();duplicate['symbol']='SH600001';self.prices=pd.concat([self.prices,duplicate],ignore_index=True)
        _,result=self.run_to('2025-01-03')
        trades=self.service.request('simulation.table',dict(accountId=a['id'],table='trades'))['rows'];self.assertEqual({x['symbol'] for x in trades},{'SH600001'})
        unfilled=self.service.request('simulation.table',dict(accountId=a['id'],table='unfilled'))['rows']
        blocked=[r for r in unfilled if r['symbol']=='SH600000'];self.assertEqual(len(blocked),2)
        self.assertTrue(all(r['expiryDate']=='2025-01-03' and r['status']=='expired' and '费用' in r['reason'] for r in blocked))

    def test_commit_interruption_resumes_without_replaying_day(self):
        a=self.call('get',accountId=self.account['id'])
        with patch.object(self.service.jobs,'_start_next'):
            job=self.service.jobs.submit(dict(kind='simulation.advance',parameters=dict(accountId=a['id'],expectedRevision=a['revision'],endDate='2025-01-06',updateData=False)))
        folder=Path(self.tmp.name)/'interrupted'
        class ProcessStopped(BaseException):pass
        def stop_after_first(value,message):
            if '已保存' in message:raise ProcessStopped()
        with patch.object(advance,'prepare_sources',side_effect=self.sources):
            with self.assertRaises(ProcessStopped):worker.execute(self.store,job,self.store.project(None),folder,stop_after_first)
        intermediate=self.call('get',accountId=a['id']);self.assertEqual(intermediate['asOfDate'],'2025-01-02')
        with patch.object(advance,'prepare_sources',side_effect=self.sources):result=worker.execute(self.store,job,self.store.project(None),folder,lambda *_:None)
        self.assertEqual(result['metrics']['completedDays'],2)
        rows=self.service.request('simulation.table',dict(accountId=a['id'],table='portfolio'))['rows'];self.assertEqual(len(rows),3);self.assertEqual(len({r['date'] for r in rows}),3)

    def test_imported_valuation_source_is_frozen_across_interruption_and_missing_file_refused(self):
        from v3_backend.research import data
        from v3_backend.research.storage import write_json
        data.merge_table(self.project,self.prices,'prices')
        root=Path(data.project_data(self.project)['path'])/'data'
        calendar=dict(start='2025-01-01',end='2025-01-10',dates=[str(d.date()) for d in pd.bdate_range('2025-01-01','2025-01-10')])
        write_json(root/'trading-calendar.json',calendar)
        legacy=self.call('create',projectId=self.project['id'],strategyId='default',capital=10000,startDate='2025-01-02')
        legacy['state']['cash']=9000;legacy['cash']=9000
        legacy['state']['holdings']={'SH600000':dict(quantity=100,sellableQuantity=100,costPrice=10)}
        self.store.project_store(self.project['id']).put('simulation',legacy,self.project['id'])
        account=self.call('importLegacy',source=dict(projectId=self.project['id'],accountId=legacy['id']),expectedRevision=0,requestId='frozen-valuation-import')
        with patch.object(self.service.jobs,'_start_next'):
            job=self.service.jobs.submit(dict(kind='simulation.advance',parameters=dict(accountId=account['id'],expectedRevision=account['revision'],endDate='2025-01-06',updateData=False)))
        output=Path(self.store.project(None)['path'])/'.research/runs/valuation-interrupted'
        class ProcessStopped(BaseException):pass
        def stop(value,message):
            if '已保存' in message:raise ProcessStopped()
        with self.assertRaises(ProcessStopped):worker.execute(self.store,job,self.store.project(None),output,stop)
        first=self.call('get',accountId=account['id']);self.assertEqual(first['asOfDate'],'2025-01-02')
        # Change both prices and calendar after the first atomic day; also add invalid live actions.
        altered=self.prices.copy()
        for column in ('open','high','low','close','rawOpen','rawHigh','rawLow','rawClose','rawPreclose'):altered[column]*=2
        data.merge_table(self.project,altered,'prices')
        write_json(root/'trading-calendar.json',{**calendar,'dates':['2025-01-01','2025-01-02','2025-01-06']})
        pd.DataFrame([dict(id='bad-live-action')]).to_parquet(root/'corporate_actions.parquet',index=False)
        result=worker.execute(self.store,job,self.store.project(None),output,lambda *_:None)
        self.assertEqual(result['metrics']['completedDays'],2)
        rows=self.service.request('simulation.table',dict(accountId=account['id'],table='portfolio'))['rows']
        self.assertEqual([r['date'] for r in rows],['2025-01-02','2025-01-03','2025-01-06'])
        self.assertTrue(all(r['account']==10000 and r['unitNav']==1 for r in rows))
        self.assertTrue(result['details']['inputReferences']['manual:0']['files'])
        frozen=next((output/'inputs/valuation_0/inputs/data/prices').glob('*.parquet'));frozen.unlink()
        with self.assertRaisesRegex(ValueError,'已固定估值输入文件缺失'):
            worker.execute(self.store,job,self.store.project(None),output,lambda *_:None)
        self.assertEqual(self.call('get',accountId=account['id'])['asOfDate'],'2025-01-06')
