import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from v3_backend.research import preparation,data,history

class PreparationLifetimeTests(unittest.TestCase):
    def test_lifetime_and_member_dates_do_not_hide_real_gap(self):
        project={'universe':{'source':'manual','symbols':['SH600000']}}
        frame=pd.DataFrame({'symbol':['SH600000']*2,'date':pd.to_datetime(['2025-01-02','2025-01-04']),
            'listingDate':['2025-01-02']*2,'delistingDate':['2025-01-05']*2,'tradestatus':['1','1']})
        dates=['2025-01-01','2025-01-02','2025-01-03','2025-01-04','2025-01-05']
        r=preparation.price_requirements(project,frame,dates,dates[0],0)[0]
        self.assertEqual(r['missingDates'],['2025-01-03']);self.assertEqual(r['expectedSessions'],3)
        _,coverage=history.expected_rows(project,frame,pd.to_datetime(dates))
        self.assertEqual(coverage.expected.tolist(),[0,1,1,1,0])
        self.assertEqual(coverage.available.tolist(),[0,1,0,1,0])
        members=pd.DataFrame({'symbol':['SH600000'],'startDate':pd.to_datetime(['2025-01-03']),'endDate':pd.to_datetime(['2025-01-04'])})
        with patch.object(history,'membership_frame',return_value=members):
            r=preparation.price_requirements(project,frame,dates,dates[0],1)[0]
        self.assertEqual(r['expectedSessions'],2);self.assertEqual(r['availableSessions'],1)
        unknown=frame.drop(columns=['listingDate','delistingDate'])
        r=preparation.price_requirements(project,unknown,dates,dates[0],0)[0]
        self.assertEqual(r['missingDates'],['2025-01-01','2025-01-03','2025-01-05'])

    def test_disabled_update_does_not_fetch_missing_market_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir()
            project={'path':temp,'settings':{'dataSources':{'daily':'file','financials':'file'}},
                'startDate':'2025-01-02','endDate':'2025-01-03',
                'universe':{'source':'manual','symbols':['SH600000']}}
            pd.DataFrame({'symbol':['SH600000'],'date':pd.to_datetime(['2025-01-02']),
                'open':[10.],'high':[10.],'low':[10.],'close':[10.],'volume':[100]}).to_parquet(root/'data/prices.parquet')
            job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':['momentum20'],'updateData':False}}}
            with patch.object(preparation,'lookback',return_value=0),patch.object(preparation,'trading_dates',return_value=['2025-01-02','2025-01-03']),patch.object(data,'update') as update:
                with self.assertRaisesRegex(ValueError,'未启用数据更新'):
                    preparation.prepare(None,job,project,root/'disabled',lambda *_:None)
                update.assert_not_called()

    def test_update_data_false_blocks_calendar_financial_action_and_benchmark_fetches(self):
        from v3_backend.research import engines
        dates=pd.bdate_range('2025-01-02',periods=4)
        def make_project(root,factors,daily_source='file'):
            data_root=root/'data';benchmarks=data_root/'benchmarks'
            benchmarks.mkdir(parents=True,exist_ok=True)
            frame=pd.DataFrame({'symbol':['SH600000']*len(dates),'date':dates,
                'open':[10.]*len(dates),'high':[10.1]*len(dates),'low':[9.9]*len(dates),
                'close':[10.,10.1,10.2,10.3],'volume':[1000]*len(dates),'factor':factors})
            frame.to_parquet(data_root/'prices.parquet',index=False)
            pd.DataFrame({'date':dates,'close':[100.,101.,102.,103.]}).to_parquet(benchmarks/'SH000300.parquet',index=False)
            return {'path':str(root),'settings':{'dataPath':str(data_root),'dataSources':
                {'daily':daily_source,'financials':'baostock'}},'startDate':str(dates[1].date()),
                'endDate':str(dates[-1].date()),'universe':{'source':'manual','symbols':['SH600000']}}
        def job(kind,**extra):
            return {'kind':kind,'spec':{'parameters':{'startDate':str(dates[1].date()),
                'endDate':str(dates[-1].date()),'factorIds':['momentum20'],
                'portfolio':{'lookback':0},'updateData':False,**extra}}}

        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'calendar';root.mkdir();(root/'data').mkdir()
            with patch.object(preparation.quotes,'_baostock') as fetch:
                with self.assertRaisesRegex(ValueError,'未启用数据更新.*交易日历'):
                    preparation.trading_dates(root/'data','2025-01-02','2025-01-06',update_data=False)
                fetch.assert_not_called()

        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project=make_project(root,[1.,1.,1.,1.])
            financial_factor=next(iter(engines.FINANCIAL))
            spec=job('factor.analyze',factorIds=[financial_factor])
            with patch.object(preparation,'lookback',return_value=0),patch.object(preparation.quotes,'_baostock') as fetch,patch.object(data,'update') as update:
                with self.assertRaisesRegex(ValueError,'未启用数据更新.*公告财务'):
                    preparation.prepare(None,spec,project,root/'financial-run',lambda *_:None)
                fetch.assert_not_called();update.assert_not_called()

        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project=make_project(root,[1.,1.,.5,.5])
            spec=job('backtest.run',template='single_factor')
            with patch.object(preparation,'lookback',return_value=0),patch.object(preparation.quotes,'_baostock') as fetch,patch.object(data,'update') as update:
                with self.assertRaisesRegex(ValueError,'未启用数据更新.*公司行动记录'):
                    preparation.prepare(None,spec,project,root/'action-run',lambda *_:None)
                fetch.assert_not_called();update.assert_not_called()

        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project=make_project(root,[1.,1.,1.,1.],'baostock')
            calendar={'start':str(dates[0].date()),'end':str(dates[-1].date()),'dates':dates.strftime('%Y-%m-%d').tolist()}
            preparation.write_json(Path(project['settings']['dataPath'])/'trading-calendar.json',calendar)
            (Path(project['settings']['dataPath'])/'benchmarks'/'SH000300.parquet').unlink()
            spec=job('backtest.run',template='single_factor')
            with patch.object(preparation,'lookback',return_value=0),patch.object(preparation.quotes,'_baostock') as fetch,patch.object(data,'update') as update:
                with self.assertRaisesRegex(ValueError,'未启用数据更新.*基准行情'):
                    preparation.prepare(None,spec,project,root/'benchmark-run',lambda *_:None)
                fetch.assert_not_called();update.assert_not_called()

    def test_prepare_does_not_fetch_prelisting_but_keeps_real_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir()
            project={'path':temp,'settings':{},'startDate':'2025-01-01','endDate':'2025-01-03','universe':{'source':'manual','symbols':['SH600000']}}
            frame=pd.DataFrame({'symbol':['SH600000']*2,'date':pd.to_datetime(['2025-01-02','2025-01-03']),'listingDate':['2025-01-02']*2})
            frame.to_parquet(root/'data/prices.parquet')
            job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':['momentum20']}}}
            with patch.object(preparation,'lookback',return_value=0),patch.object(preparation,'trading_dates',return_value=['2025-01-01','2025-01-02','2025-01-03']),patch.object(data,'update') as update:
                preparation.prepare(None,job,project,root/'ok',lambda *_:None)
                update.assert_not_called()
                frame.iloc[:1].to_parquet(root/'data/prices.parquet')
                with self.assertRaisesRegex(ValueError,'2025-01-03'):
                    preparation.prepare(None,job,project,root/'gap',lambda *_:None)
                update.assert_called_once()
            frame.to_parquet(root/'data/prices.parquet')
            with patch.object(preparation,'lookback',return_value=20),patch.object(preparation,'trading_dates',return_value=['2025-01-01','2025-01-02','2025-01-03']),patch.object(data,'update') as update:
                _,report=preparation.prepare(None,job,project,root/'warmup',lambda *_:None)
                self.assertEqual(report['structuralWarmupSymbols'],['SH600000'])
                self.assertEqual(report['warmupCoverage'][0]['availableSessions'],0)
                self.assertEqual(report['warmupCoverage'][0]['requiredSessions'],20)
                update.assert_not_called()

    def test_no_member_overlap_requires_neither_prices_nor_warmup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir()
            project={'path':temp,'settings':{},'startDate':'2025-01-02','endDate':'2025-01-03',
                'universe':{'source':'manual','symbols':['SH600000','SH600001','SH600002']}}
            dates=pd.bdate_range('2024-11-01','2025-01-03')
            # SH600001 has no rows; SH600002 has no pre-study rows. Both are outside membership.
            frame=pd.concat([pd.DataFrame({'symbol':'SH600000','date':dates}),pd.DataFrame({'symbol':['SH600002'],'date':pd.to_datetime(['2025-01-02'])})])
            frame.to_parquet(root/'data/prices.parquet')
            members=pd.DataFrame({'symbol':['SH600000','SH600001','SH600002'],'startDate':pd.to_datetime(['2024-01-01','2026-01-01','2026-01-01']),'endDate':[pd.NaT]*3})
            job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':['momentum20']}}}
            with patch.object(history,'membership_frame',return_value=members),patch.object(preparation,'lookback',return_value=20),patch.object(preparation,'trading_dates',return_value=['2025-01-02','2025-01-03']),patch.object(preparation.quotes,'_baostock',side_effect=AssertionError('network')),patch.object(data,'update') as update:
                _,report=preparation.prepare(None,job,project,root/'result',lambda *_:None)
                update.assert_not_called()
            for r in report['warmupCoverage'][1:]:self.assertEqual(r['requiredSessions'],0)

    def test_sixty_calendar_days_preserves_post_listing_warmup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir()
            project={'path':temp,'settings':{},'startDate':'2025-01-02','endDate':'2025-03-10',
                'universe':{'source':'manual','symbols':['SH600000'],'minListingDays':60}}
            dates=pd.bdate_range('2025-01-02','2025-03-10')
            frame=pd.DataFrame({'symbol':'SH600000','date':dates,'listingDate':'2025-01-02'})
            frame.to_parquet(root/'data/prices.parquet')
            job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':['momentum20']}}}
            with patch.object(preparation,'lookback',return_value=20),patch.object(preparation,'trading_dates',return_value=dates.strftime('%Y-%m-%d').tolist()),patch.object(preparation.quotes,'_baostock',side_effect=AssertionError('network')),patch.object(data,'update') as update:
                _,report=preparation.prepare(None,job,project,root/'result',lambda *_:None)
                update.assert_not_called()
            r=report['priceRequirements'][0]
            self.assertEqual(r['warmupBefore'],'2025-03-03')
            self.assertEqual(r['expectedSessions'],6)
            self.assertGreaterEqual(r['availableSessions'],20)
            self.assertEqual(report['inputStart'],'2025-01-02')

    def test_empty_universe_initial_download_requests_and_checks_warmup(self):
        for source in ['all','csi300']:
            for enough in [True,False]:
                with self.subTest(source=source,enough=enough),tempfile.TemporaryDirectory() as temp:
                    root=Path(temp);(root/'data').mkdir()
                    project={'path':temp,'settings':{},'startDate':'2025-01-02','endDate':'2025-01-03','universe':{'source':source,'symbols':[]}}
                    calendar=pd.DataFrame({'calendar_date':['2024-12-30','2024-12-31'],'is_trading_day':['1','1']})
                    observed=['2024-12-30','2024-12-31','2025-01-02','2025-01-03'] if enough else ['2025-01-02','2025-01-03']
                    frame=pd.DataFrame({'symbol':'SH600000','date':pd.to_datetime(observed)})
                    def download(*args):frame.to_parquet(root/'data/prices.parquet')
                    job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':['momentum20']}}}
                    with patch.object(preparation,'lookback',return_value=2),patch.object(preparation,'trading_dates',return_value=['2025-01-02','2025-01-03']),patch.object(preparation.quotes,'_baostock',return_value=calendar),patch.object(data,'update',side_effect=download) as update:
                        if enough:
                            _,report=preparation.prepare(None,job,project,root/'result',lambda *_:None)
                            self.assertEqual(report['warmupCoverage'][0]['availableSessions'],2)
                        else:
                            with self.assertRaisesRegex(ValueError,'预热'):
                                preparation.prepare(None,job,project,root/'result',lambda *_:None)
                        update.assert_called_once()
                        self.assertEqual(update.call_args.args[1]['startDate'],'2024-12-30')

    def test_empty_download_without_columns_reports_missing_data(self):
        with tempfile.TemporaryDirectory() as temp:
            project={'path':temp,'settings':{},'startDate':'2025-01-02','endDate':'2025-01-03','universe':{'source':'manual','symbols':['SH600000']}}
            job={'kind':'factor.analyze','spec':{'parameters':{'factorIds':['momentum20']}}}
            with patch.object(preparation,'lookback',return_value=0),patch.object(preparation,'trading_dates',return_value=['2025-01-02','2025-01-03']),patch.object(data,'update') as update,patch.object(data,'read_table',return_value=pd.DataFrame()):
                with self.assertRaisesRegex(ValueError,'来源未返回所需数据'):
                    preparation.prepare(None,job,project,Path(temp)/'result',lambda *_:None)
                update.assert_called_once()


    def test_source_suspension_is_preserved_without_invented_price(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project={'path':temp,'universe':{'source':'manual','symbols':['SH600000']}}
            source=pd.DataFrame({'date':['2025-01-02','2025-01-03'],'code':['sh.600000']*2,'tradestatus':['1','0'],
                'open':['10','10'],'high':['10','10'],'low':['10','10'],'close':['10','10'],'volume':['100','']})
            raw=pd.DataFrame({'date':['2025-01-02','2025-01-03'],'close':['10','10']})
            basic=pd.DataFrame({'ipoDate':['2000-01-01'],'outDate':[''],'code_name':['测试']})
            bs=SimpleNamespace(query_history_k_data_plus=object(),query_stock_basic=object())
            with patch.object(data,'_bs_query',side_effect=[source,raw,basic]):
                frame=data._bs_prices(bs,'sh.600000','2025-01-02','2025-01-03')
            self.assertEqual(len(frame),1)
            self.assertEqual(len(frame.attrs['tradingStatus']),2)
            data._save_updated_prices(project,frame,'SH600000')
            actual=data.read_table(project)
            self.assertEqual(len(actual),1)
            r=preparation.price_requirements(project,actual,['2025-01-02','2025-01-03','2025-01-06'],'2025-01-02',0)[0]
            self.assertEqual(r['confirmedSuspensionDates'],['2025-01-03'])
            self.assertEqual(r['missingDates'],['2025-01-06'])
            project.update(startDate='2025-01-02',endDate='2025-01-06')
            (root/'data/benchmarks').mkdir()
            pd.DataFrame({'date':pd.to_datetime(['2025-01-02','2025-01-03','2025-01-06'])}).to_parquet(root/'data/benchmarks/SH000300.parquet')
            preview=data.preview(project)
            self.assertEqual(next(x for x in preview['datasets'] if x['name']=='prices')['rows'],1)
            summary=preview['diagnostics']['summary'][0]
            self.assertEqual(summary['confirmedSuspensionMissingRows'],1)
            self.assertEqual(summary['unexplainedMissingRows'],1)
            # A later actual state revision must not retain the earlier suspension exemption.
            data.save_trading_status(project,pd.DataFrame({'symbol':['SH600000'],'date':['2025-01-03'],'tradestatus':[1]}))
            r=preparation.price_requirements(project,actual,['2025-01-03'],'2025-01-03',0)[0]
            self.assertEqual(r['missingDates'],['2025-01-03'])
