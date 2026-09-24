"""Transfer to manual keeps a valuation origin independent of adopted rules."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import unittest
import pandas as pd
from test_simulation_shared_advance import SharedAdvanceTests
from v3_backend.research import data, worker, simulation_advance as advance
from v3_backend.research.server import Service
from v3_backend.research.storage import write_json

class ManualValuationTests(unittest.TestCase):
    setUp=SharedAdvanceTests.setUp
    tearDown=SharedAdvanceTests.tearDown
    call=SharedAdvanceTests.call

    def execute_to(self,end,job=None,output=None,progress=lambda *_:None):
        account=self.call('get',accountId=self.account['id'])
        if job is None:
            with patch.object(self.service.jobs,'_start_next'):
                job=self.service.jobs.submit(dict(kind='simulation.advance',parameters=dict(accountId=account['id'],expectedRevision=account['revision'],endDate=end,updateData=False)))
        output=output or Path(self.store.project(None)['path'])/'.research/runs'/job['id']
        with patch.object(data,'update',side_effect=AssertionError('no network')):
            result=worker.execute(self.store,job,self.store.project(None),output,progress)
        return job,output,result

    def transfer_and_adopt(self):
        row=self.prices.iloc[0].to_dict()
        prices=pd.DataFrame([{**row,'date':day,'symbol':symbol} for symbol in ['SH600000','SH600001'] for day in pd.bdate_range('2023-01-02','2025-01-10')])
        data.merge_table(self.project,prices,'prices')
        self.market_root=Path(data.project_data(self.project)['path'])/'data'
        write_json(self.market_root/'trading-calendar.json',dict(start='2023-01-02',end='2025-01-10',dates=[str(d.date()) for d in pd.bdate_range('2023-01-02','2025-01-10')]))
        account=self.call('get',accountId=self.account['id'])
        account['bindings'][0]['versions'][0]['snapshot']['project']['settings']['dataSources']={'daily':'file','financials':'file'}
        self.store.project_store(None).put('simulation',account)
        _,_,result=self.execute_to('2025-01-03');account=result['details']['account']
        owner=account['ownership'][0];self.original_quantity=owner['quantity'];self.original_nav=account['nav']
        self.old_binding=owner['bindingId'];self.old_version=owner['entryVersionId']
        account=self.call('ownership.transferToManual',accountId=account['id'],expectedRevision=account['revision'],ownershipIds=[owner['id']])
        self.source_id=account['ownership'][0]['valuationSourceId']
        provenance=account['holdingValuationSources'][0]
        self.assertEqual(provenance['bindingId'],self.old_binding);self.assertEqual(provenance['versionId'],self.old_version)
        self.assertNotIn('backtest',provenance['project']['settings'])
        strategy=self.store.project_store(self.project['id']).get('strategy','default')
        strategy['universe'].update(source='manual',symbols=['SH600001'],minListingDays=0,excludeST=False)
        strategy['settings']['backtest']['dailyCode']="def decide(context):\n return {'targets': {}}"
        self.store.project_store(self.project['id']).put('strategy',strategy,self.project['id'])
        preview=self.call('bindings.preview',accountId=account['id'],bindingId=self.old_binding)
        account=self.call('bindings.adopt',accountId=account['id'],expectedRevision=account['revision'],bindingId=self.old_binding,expectedSourceVersion=preview['sourceVersion'])
        return account

    def assert_manual_unchanged(self,account):
        owner=account['ownership'][0]
        self.assertEqual(owner['management'],'manual');self.assertIsNone(owner['bindingId']);self.assertIsNone(owner['entryVersionId'])
        self.assertEqual(owner['quantity'],self.original_quantity);self.assertEqual(owner['valuationSourceId'],self.source_id)
        trades=self.service.request('simulation.table',dict(accountId=account['id'],table='trades'))['rows']
        self.assertEqual(len(trades),1)

    def test_transfer_adopt_removes_symbol_and_restart_continues_valuation(self):
        account=self.transfer_and_adopt()
        self.service.close();self.service=Service(Path(self.tmp.name)/'app');self.store=self.service.store
        _,_,result=self.execute_to('2025-01-07');account=result['details']['account']
        self.assertEqual(account['asOfDate'],'2025-01-07');self.assertEqual(account['status'],'ready')
        self.assertAlmostEqual(account['nav'],self.original_nav)
        self.assert_manual_unchanged(account)
        references=result['details']['inputReferences']
        self.assertIn('holding:'+self.source_id,references)
        self.assertNotIn(self.old_binding+':'+self.old_version,references)
        self.assertEqual(len(references),2)

    def test_interrupted_advance_reuses_frozen_holding_prices_after_restart(self):
        self.transfer_and_adopt()
        class Stopped(BaseException):pass
        def stop(value,message):
            if '已保存' in message:raise Stopped()
        account=self.call('get',accountId=self.account['id'])
        with patch.object(self.service.jobs,'_start_next'):
            job=self.service.jobs.submit(dict(kind='simulation.advance',parameters=dict(accountId=account['id'],expectedRevision=account['revision'],endDate='2025-01-08',updateData=False)))
        output=Path(self.store.project(None)['path'])/'.research/runs'/job['id']
        with self.assertRaises(Stopped):self.execute_to('2025-01-08',job,output,stop)
        self.assertEqual(self.call('get',accountId=account['id'])['asOfDate'],'2025-01-06')
        self.service.close();self.service=Service(Path(self.tmp.name)/'app');self.store=self.service.store
        path=self.market_root/'prices/SH600000.parquet';prices=pd.read_parquet(path)
        for column in ('open','high','low','close','rawOpen','rawHigh','rawLow','rawClose','rawPreclose'):prices[column]*=5
        prices.to_parquet(path,index=False)
        _,_,result=self.execute_to('2025-01-08',job,output)
        self.assertEqual(result['metrics']['completedDays'],2)
        self.assertAlmostEqual(result['details']['account']['nav'],self.original_nav)
        self.assert_manual_unchanged(result['details']['account'])

    def test_missing_manual_raw_price_blocks_without_liquidation(self):
        self.transfer_and_adopt()
        path=self.market_root/'prices/SH600000.parquet';prices=pd.read_parquet(path)
        prices=prices[prices.date.ne(pd.Timestamp('2025-01-06'))];prices.to_parquet(path,index=False)
        with self.assertRaises(ValueError):self.execute_to('2025-01-06')
        account=self.call('get',accountId=self.account['id'])
        self.assertEqual(account['status'],'blocked');self.assertEqual(account['valuationStatus'],'unavailable')
        self.assertEqual(account['asOfDate'],'2025-01-03');self.assertTrue(account['unresolved']['message'])
        self.assert_manual_unchanged(account)

    def test_old_detached_state_without_valuation_origin_reproduces_block(self):
        account=self.transfer_and_adopt()
        # The pre-fix persisted state had neither independent source nor owner link.
        account.pop('holdingValuationSources')
        for owner in account['ownership']:owner.pop('valuationSourceId',None)
        self.store.project_store(None).put('simulation',account)
        with self.assertRaisesRegex(ValueError,'SH600000'):
            self.execute_to('2025-01-06')
        blocked=self.call('get',accountId=account['id'])
        self.assertEqual(blocked['status'],'blocked');self.assertEqual(blocked['asOfDate'],'2025-01-03')
        self.assertEqual(blocked['ownership'][0]['quantity'],self.original_quantity)

    def test_settled_entitlement_releases_empty_source_but_unpaid_cash_retains_it(self):
        account=self.transfer_and_adopt()
        for owner in account['ownership']:
            owner.update(quantity=0,pendingQuantity=0,sellableQuantity=0)
        account['state']['holdings']={}
        account['state']['entitlements']={'dividend':dict(symbol='SH600000',cash=100,shares=0)}
        account['state']['processedActions']=['dividend:ex','dividend:pay']
        params=dict(endDate='2025-01-07',updateData=False)
        root=Path(self.store.project(None)['path'])/'.research/runs/settled-check'
        sources,failures=advance.prepare_sources(self.store,account,params,root,lambda *_:None)
        self.assertNotIn('holding:'+self.source_id,sources)
        self.assertFalse(failures)
        account['state']['processedActions']=['dividend:ex']
        sources,failures=advance.prepare_sources(self.store,account,params,Path(self.store.project(None)['path'])/'.research/runs/unpaid-check',lambda *_:None)
        self.assertIn('holding:'+self.source_id,sources)
        self.assertFalse(failures)

class EntitlementSourceLifetimeTests(unittest.TestCase):
    def test_registration_payment_and_listing_boundaries(self):
        state={'entitlements':{'a':{'symbol':'SH600000','cash':100,'shares':20}},'processedActions':[]}
        self.assertEqual(advance.unsettled_entitlement_symbols(state),{'SH600000'})
        state['processedActions']=['a:ex','a:pay']
        self.assertEqual(advance.unsettled_entitlement_symbols(state),{'SH600000'})
        state['processedActions'].append('a:listing')
        self.assertEqual(advance.unsettled_entitlement_symbols(state),set())
        state['entitlements']['a']['shares']=None
        self.assertEqual(advance.unsettled_entitlement_symbols(state),{'SH600000'})
