"""Provider units/identity and cache preservation; no network calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import pandas as pd
from v3_backend.research import market_snapshot, quotes
from v3_backend.research.storage import read_json, write_json


class MarketAlternatives(unittest.TestCase):
    def test_existing_market_snapshot_supplies_catalog_without_network(self):
        with TemporaryDirectory() as directory, patch.object(quotes,'_ak') as source:
            write_json(Path(directory)/'market-snapshot/industries.json',dict(updatedAt='2026-09-13T12:00:00',source='akshare/sina',
                rows=[dict(symbol='SINA_NEW_CBZZ',name='船舶制造',source='akshare/sina')]))
            result=quotes.catalog({'path':directory},{'kind':'industry','loadIfMissing':True})
            source.assert_not_called()
            self.assertEqual(result['items'][0]['symbol'],'SINA_NEW_CBZZ')
            self.assertEqual(result['status'],'ready')

    def test_member_failure_keeps_saved_list_and_returns_error_state(self):
        with TemporaryDirectory() as directory:
            target=Path(directory)/'quotes/members/industry-SINA_NEW_CBZZ.json'
            saved=dict(asOfDate='2026-09-11',source='akshare/sina',rows=[dict(symbol='SH600000',name='示例',close=10)])
            write_json(target,saved)
            with patch.object(quotes,'_ak',side_effect=ValueError('source timeout')):
                result=quotes.members({'path':directory},{'instrument':dict(kind='industry',symbol='SINA_NEW_CBZZ'),'refresh':True})
            self.assertEqual(result['status'],'source_error')
            self.assertTrue(result['stale'])
            self.assertEqual(result['rows'],saved['rows'])
            self.assertEqual(read_json(target,{}),saved)

    def test_sina_volume_and_exchange_identity(self):
        f=pd.DataFrame([{'代码':'sz000001','名称':'平安银行','最新价':10,'涨跌幅':2,'成交量':350,'成交额':3500},
                        {'代码':'bj920000','名称':'北交所','最新价':10,'涨跌幅':2,'成交量':1,'成交额':10}])
        result=market_snapshot.normalize(f,'stocks','akshare/sina')
        self.assertEqual(result.symbol.tolist(),['SZ000001'])
        self.assertEqual(result.volume.tolist(),[350])
        f.loc[0,'代码']='sh000001'
        result=market_snapshot.normalize(f,'indices','akshare/sina')
        self.assertEqual(result.symbol.tolist(),['SH000001'])
        self.assertEqual(result.volume.tolist(),[35000])

    def test_provider_fallback_preserves_source(self):
        frame=pd.DataFrame([{'代码':'sh600000','名称':'浦发银行','最新价':10,'涨跌幅':1,'成交量':100,'成交额':1000}])
        with TemporaryDirectory() as directory:
            target=Path(directory)/'stocks.json'
            with patch.object(quotes,'_ak',side_effect=[ValueError('Eastmoney unavailable'),frame]) as source:
                result=market_snapshot._refresh(target,'stocks','stock_zh_a_spot_em',{})
                self.assertEqual(source.call_count,2)
                self.assertEqual(result['source'],'akshare/sina')
                self.assertIsNone(result['asOfDate'])
            saved=read_json(target,{})
            with patch.object(quotes,'_ak',side_effect=ValueError('offline')):
                with self.assertRaises(ValueError):market_snapshot._refresh(target,'stocks','stock_zh_a_spot_em',{})
            self.assertEqual(read_json(target,{}),saved)

    def test_sina_sector_is_not_an_eastmoney_index(self):
        frame=pd.DataFrame([{'label':'gn_hwqc','板块':'华为汽车','平均价格':23.5,'涨跌幅':-1,'总成交额':1000,'公司家数':97}])
        result=market_snapshot.normalize(frame,'concepts','akshare/sina')
        self.assertEqual(result.symbol.tolist(),['SINA_GN_HWQC'])
        self.assertEqual(result.priceUnit.iloc[0],'元（成分均价）')
        item=quotes.instrument({'kind':'concept','symbol':'SINA_GN_HWQC'})
        with self.assertRaisesRegex(ValueError,'未提供该板块历史曲线'):
            quotes._fetch(item,'2025-01-01','2025-01-31')

    def test_sina_members_are_current_shares_and_filterable(self):
        frame=pd.DataFrame([{'symbol':'sz000001','name':'平安银行','trade':'10','changepercent':'2','volume':'350','amount':'3500','turnoverratio':'1.2'}])
        with TemporaryDirectory() as directory, patch.object(quotes,'_ak',return_value=frame):
            result=quotes.members({'path':directory},{'instrument':{'kind':'concept','symbol':'SINA_GN_HWQC'},'refresh':True,
                'filters':[{'field':'close','operator':'gte','value':9}]})
            self.assertEqual(result['rows'][0]['symbol'],'SZ000001')
            self.assertEqual(result['rows'][0]['volume'],350)
            self.assertEqual(result['source'],'akshare/sina')


if __name__=='__main__':unittest.main()
