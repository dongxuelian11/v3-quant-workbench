import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from v3_backend.research import quotes,intraday,data,preparation
from v3_backend.research.server import Service
from v3_backend.research.storage import write_json

class DataSourceRoutingTests(unittest.TestCase):
    def test_file_settings_disable_all_quote_network_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(Path(temp)/'profile')
            try:
                service.request('settings.save',{'settings':{'dataSources':dict(daily='file',financials='file',boards='file',intraday='file',microcap='file',quoteFallback=False)}})
                with patch.object(quotes,'_ak',side_effect=AssertionError('AK network')) as ak,patch.object(quotes,'_baostock',side_effect=AssertionError('BS network')) as bs:
                    service.request('market.instruments',{'loadIfMissing':True})
                    service.request('market.quote',{'instrument':{'kind':'stock','symbol':'SH600000'},'refresh':True})
                    service.request('market.quote',{'instrument':{'kind':'index','symbol':'TDX880823'},'refresh':True})
                    service.request('market.intraday',{'instrument':{'kind':'stock','symbol':'SH600000'},'period':'5m','refresh':True})
                    service.request('market.members',{'instrument':{'kind':'concept','symbol':'BK0001'},'refresh':True})
                    service.request('market.overview',{'refresh':True})
                    ak.assert_not_called();bs.assert_not_called()
            finally:service.close()

    def test_research_file_gap_and_financial_missing_never_fetch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir()
            project=dict(path=temp,startDate='2025-01-02',endDate='2025-01-03',settings={'dataSources':{'daily':'file','financials':'file'}},universe={'source':'manual','symbols':['SH600000']})
            write_json(root/'data/trading-calendar.json',{'start':'2025-01-02','end':'2025-01-03','dates':['2025-01-02','2025-01-03']})
            job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':['roe']}}}
            with patch.object(quotes,'_baostock',side_effect=AssertionError('network')),patch.object(data,'update',side_effect=AssertionError('download')):
                with self.assertRaisesRegex(ValueError,'日线来源'):
                    preparation.prepare(None,job,project,root/'gap',lambda *_:None)
                pd.DataFrame({'date':pd.to_datetime(['2025-01-02','2025-01-03']),'symbol':'SH600000','close':10.}).to_parquet(root/'data/prices.parquet')
                with self.assertRaisesRegex(ValueError,'公告财务缺失'):
                    preparation.prepare(None,job,project,root/'financial',lambda *_:None)

    def test_quote_and_minute_fallback_switch(self):
        item={'kind':'stock','symbol':'SH600000','_dataSources':{'daily':'baostock','quoteFallback':False}}
        with patch.object(quotes,'_baostock',side_effect=ValueError('primary unavailable')),patch.object(quotes,'_ak',side_effect=AssertionError('fallback')) as ak:
            with self.assertRaisesRegex(ValueError,'primary unavailable'):quotes._fetch(item,'2025-01-02','2025-01-03')
            ak.assert_not_called()
        with patch.object(quotes,'_ak',side_effect=ValueError('primary unavailable')) as ak:
            with self.assertRaises(ValueError):intraday.fetch(item,'5m',{'_quoteFallback':False})
            self.assertEqual(ak.call_count,1)
        with patch.object(quotes,'_ak',side_effect=[ValueError('primary unavailable'),pd.DataFrame()]) as ak,patch.object(intraday,'normalize',return_value='actual fallback adapter'):
            self.assertEqual(intraday.fetch(item,'5m',{'_quoteFallback':True}),'actual fallback adapter')
            self.assertEqual(ak.call_count,2)

    def test_jobs_freeze_source_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(Path(temp)/'profile');store=service.store
            try:
                p=store.create_project(Path(temp)/'project','来源固定');p.update(startDate='2025-01-02',endDate='2025-01-03');store.save_project(p)
                service.request('settings.save',{'settings':{'dataSources':{'daily':'file','financials':'file'}}})
                with patch.object(service.jobs,'_start_next'):
                    first=service.jobs.submit({'kind':'factor.analyze','projectId':p['id'],'parameters':{'factorIds':['momentum20']}})
                    service.request('settings.save',{'settings':{'dataSources':{'daily':'akshare'}}})
                    second=service.jobs.submit({'kind':'factor.analyze','projectId':p['id'],'parameters':{'factorIds':['momentum20']}})
                self.assertEqual(store.get('job',first['id'])['spec']['projectSnapshot']['settings']['dataSources']['daily'],'file')
                self.assertEqual(store.get('job',second['id'])['spec']['projectSnapshot']['settings']['dataSources']['daily'],'akshare')
            finally:service.close()

    def test_selected_akshare_quote_does_not_try_baostock(self):
        item={'kind':'stock','symbol':'SH600000','_dataSources':{'daily':'akshare','quoteFallback':False}}
        frame=pd.DataFrame({'date':['2025-01-02'],'open':[10.],'high':[11.],'low':[9.],'close':[10.],'volume':[1.],'amount':[1000.]})
        with patch.object(quotes,'_baostock',side_effect=AssertionError('wrong source')) as bs,patch.object(quotes,'_ak',return_value=frame) as ak:
            actual,source,warning=quotes._fetch(item,'2025-01-02','2025-01-02')
            self.assertEqual(source,'akshare/eastmoney');self.assertEqual(len(actual),1)
            bs.assert_not_called();ak.assert_called_once()

    def test_research_prepare_passes_fixed_akshare_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir()
            project=dict(path=temp,startDate='2025-01-02',endDate='2025-01-03',settings={'dataSources':{'daily':'akshare','financials':'file'}},universe={'source':'manual','symbols':['SH600000']})
            write_json(root/'data/trading-calendar.json',{'start':'2025-01-02','end':'2025-01-03','dates':['2025-01-02','2025-01-03']})
            def download(*args):pd.DataFrame({'date':pd.to_datetime(['2025-01-02','2025-01-03']),'symbol':'SH600000','close':10.}).to_parquet(root/'data/prices.parquet')
            job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':[]}}}
            with patch.object(data,'update',side_effect=download) as update,patch.object(quotes,'_baostock',side_effect=AssertionError('wrong source')):
                _,report=preparation.prepare(None,job,project,root/'run',lambda *_:None)
                self.assertEqual(update.call_args.args[1]['source'],'akshare')
                self.assertEqual(report['dataSources']['daily'],'akshare')
