import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from v3_backend.research import charts,intraday,quotes
from v3_backend.research.server import Service


class MarketNextTests(unittest.TestCase):
    def test_negative_groups_and_cached_history_do_not_require_today(self):
        from v3_backend.research.storage import write_json
        dates=['2014-12-26','2014-12-29','2014-12-30','2014-12-31','2015-01-05','2015-01-06','2015-01-07','2015-01-08']
        frame=pd.DataFrame([dict(date=d,open=10,high=12,low=9,close=11,volume=100,amount=1000) for d in dates])
        params={'period':'trading_days','tradingDays':4,'_tradingDates':dates}
        bars=charts.bars_from_frame(frame,params)
        self.assertEqual([r['periodStart'][:10] for r in bars],['2014-12-26','2015-01-05'])
        reduced=charts.bars_from_frame(frame.iloc[1:],params)
        self.assertEqual([r['periodStart'] for r in reduced],[r['periodStart'] for r in bars])
        with tempfile.TemporaryDirectory() as root:
            project={'path':root,'settings':{}}
            write_json(Path(root)/'data/trading-calendar.json',{'start':dates[0],'end':dates[-1],'dates':dates})
            with patch.object(quotes,'_baostock',side_effect=ValueError('今日不可用')) as remote:
                actual=charts.with_calendar(project,params,frame)
            remote.assert_not_called();self.assertEqual(charts.bars_from_frame(frame,actual),bars)

    def test_fixed_trading_calendar_groups_survive_suspension_and_pagination(self):
        dates=['2015-01-05','2015-01-06','2015-01-07','2015-01-08','2015-01-09','2015-01-12']
        frame=pd.DataFrame([dict(date=d,open=i+10,high=i+12,low=i+9,close=i+11,volume=100,amount=1000) for i,d in enumerate(dates)])
        params={'period':'trading_days','tradingDays':4,'_tradingDates':dates}
        full=charts.bars_from_frame(frame,params)
        suspended=charts.bars_from_frame(frame.drop(index=[1]),params)
        self.assertEqual([r['periodStart'] for r in full],[r['periodStart'] for r in suspended])
        self.assertEqual(suspended[0]['sessions'],3)
        self.assertTrue(full[0]['complete']);self.assertFalse(full[-1]['complete'])
        page=charts.bars_from_frame(frame,{**params,'beforeDate':full[-1]['date']})
        self.assertEqual(page,[full[0]])
        partial=charts.bars_from_frame(frame.iloc[2:],params)
        self.assertEqual(partial[0]['periodStart'],full[0]['periodStart']);self.assertFalse(partial[0]['complete'])
        with self.assertRaises(ValueError):charts.bars_from_frame(frame,{**params,'_tradingDates':[]})
        with self.assertRaises(ValueError):charts.bars_from_frame(frame,{**params,'anchorDate':'2016-01-01'})

    def test_session_vwap_requires_complete_stock_volume_and_amount(self):
        item={'kind':'stock','symbol':'SH600000'}
        raw=pd.DataFrame([dict(day='2025-01-02 '+t,open=10,high=12,low=9,close=11,volume=v,amount=a) for t,v,a in [('09:31',100,1000),('09:32',200,2200),('09:33',100,1200)]])
        frame=intraday.normalize(raw,item,'1m',source='akshare/sina',volume_multiplier=1)
        result=intraday.session_average(frame,item,'1m')
        self.assertAlmostEqual(result.averagePrice.iloc[1],3200/300)
        self.assertEqual(result.averagePriceSource.iloc[-1],'session_vwap')
        for incomplete in (frame.iloc[1:],frame.drop(index=1),frame.assign(amount=float('nan'))):
            missing=intraday.session_average(incomplete,item,'1m')
            self.assertTrue(pd.isna(missing.averagePrice.iloc[-1]))
        index=intraday.session_average(frame,{'kind':'index','symbol':'SH000300'},'1m')
        self.assertTrue(index.averagePrice.isna().all())
        provider=intraday.session_average(frame.assign(averagePrice=12),item,'1m')
        self.assertTrue(provider.averagePrice.eq(12).all());self.assertTrue(provider.averagePriceSource.eq('provider').all())
        inconsistent=frame.copy();inconsistent.loc[0,['volume','amount']]=[0,100]
        rejected=intraday.session_average(inconsistent,item,'1m')
        self.assertTrue(rejected.averagePrice.isna().all())
        empty_minute=frame.copy();empty_minute.loc[0,['volume','amount']]=[0,0]
        accepted=intraday.session_average(empty_minute,item,'1m')
        self.assertAlmostEqual(accepted.averagePrice.iloc[1],11)

    def test_tdx_identity_import_failure_retention_and_annotation_scope(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);service=Service(root/'profile')
            try:
                item={'kind':'index','symbol':'TDX880823'}
                entries=service.request('market.instruments',{'kind':'index'})['items']
                self.assertEqual(len(entries),9);self.assertEqual(entries[-1]['source'],'tdx')
                path=root/'880823.csv'
                pd.DataFrame([dict(date='2025-01-02',open=100,high=102,low=99,close=101,volume=1000,amount=5000)]).to_csv(path,index=False)
                imported=service.request('market.quote.import',{'instrument':item,'filePath':str(path)})
                self.assertEqual(imported['coverage']['source'],'file/import')
                self.assertEqual(imported['bars'][0]['close'],101)
                with patch.object(quotes,'_fetch',side_effect=ValueError('TDX未连接')):
                    failed=service.request('market.quote',{'instrument':item,'refresh':True})
                self.assertEqual(failed['status'],'source_error');self.assertEqual(failed['bars'],imported['bars'])
                params={'instrument':item,'period':'trading_days','tradingDays':4,'priceBasis':'raw'}
                service.request('charts.save',{**params,'annotations':[{'id':'a','points':[]}]})
                self.assertEqual(len(service.request('charts.load',params)['annotations']),1)
                self.assertEqual(service.request('charts.load',{**params,'tradingDays':10})['annotations'],[])
            finally:service.close()
