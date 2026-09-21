import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from v3_backend.research import market_snapshot,quotes
from v3_backend.research.storage import write_json

class MarketStrengthTests(unittest.TestCase):
    def setup(self,root):
        project={'path':str(root),'settings':{'dataSources':{'daily':'file','boards':'file'}}}
        dates=pd.bdate_range('2026-06-01',periods=23)
        write_json(root/'data/trading-calendar.json',dict(dates=[str(d.date()) for d in dates],start=str(dates[0].date()),end=str(dates[-1].date())))
        write_json(root/'market-snapshot/stocks.json',dict(rows=[dict(symbol='SH600000',changeRatio=.1,amount=100)],updatedAt='2026-07-01',source='real-stock-source'))
        for category,symbol in [('indices','SH000001'),('industries','BK0001'),('concepts','BK0002')]:
            rows=[dict(symbol=symbol,name=symbol,changeRatio=.5,amount=9999,source='spot-source')]
            if category=='concepts':rows.append(dict(symbol='SINA_GN_EXAMPLE',name='新浪概念',changeRatio=.2,amount=9999,source='akshare/sina'))
            write_json(root/'market-snapshot'/(category+'.json'),dict(rows=rows,updatedAt='2026-07-01',source='spot-source'))
        def curve(kind,symbol,chosen=dates):
            path=root/'quotes'/kind/(symbol+'.parquet');path.parent.mkdir(parents=True,exist_ok=True)
            pd.DataFrame(dict(date=chosen,close=[100+dates.get_loc(d) for d in chosen])).to_parquet(path,index=False)
            write_json(path.with_suffix('.json'),dict(source='source-history'))
        curve('index','SH000001');curve('industry','BK0001');curve('concept','BK0002',dates[:-1])
        return project,dates

    def test_periods_align_to_common_sessions_without_fetch_or_concept_sum(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(quotes,'_ak',side_effect=AssertionError('no network')),patch.object(quotes,'_fetch',side_effect=AssertionError('no download')):
            project,dates=self.setup(Path(temp))
            five=market_snapshot.overview(project,{'strengthDays':5})
            self.assertAlmostEqual(five['indices'][0]['strengthChangeRatio'],122/117-1)
            self.assertEqual(five['industries'][0]['strengthEndDate'],str(dates[-1].date()))
            self.assertIsNone(five['concepts'][0]['strengthChangeRatio'])
            self.assertEqual(five['concepts'][0]['strengthStatus'],'partial')
            self.assertEqual(five['concepts'][1]['strengthStatus'],'unsupported')
            self.assertEqual(five['summary']['turnoverAmount'],100)
            self.assertEqual(five['strength']['covered'],2);self.assertEqual(five['strength']['total'],4)
            twenty=market_snapshot.overview(project,{'strengthDays':20})
            self.assertAlmostEqual(twenty['indices'][0]['strengthChangeRatio'],122/102-1)
            self.assertEqual(twenty['industries'][0]['strengthStartDate'],str(dates[2].date()))
            today=market_snapshot.overview(project,{'strengthDays':1})
            self.assertEqual(today['indices'][0]['strengthChangeRatio'],.5)
            self.assertIsNone(today['indices'][0]['strengthEndDate'])

    def test_missing_intermediate_date_and_calendar_never_bridge(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,dates=self.setup(root)
            path=root/'quotes/industry/BK0001.parquet';frame=pd.read_parquet(path)
            frame[frame.date.ne(dates[-3])].to_parquet(path,index=False)
            result=market_snapshot.overview(project,{'strengthDays':5})
            self.assertIsNone(result['industries'][0]['strengthChangeRatio'])
            self.assertIn('有效5个',result['industries'][0]['strengthMessage'])
            (root/'data/trading-calendar.json').unlink()
            # Only the broad source index provides shared dates, not each board.
            result=market_snapshot.overview(project,{'strengthDays':5})
            self.assertIn('上证指数',result['strength']['calendarSource'])
            self.assertIsNone(result['industries'][0]['strengthChangeRatio'])
            (root/'quotes/index/SH000001.parquet').unlink()
            result=market_snapshot.overview(project,{'strengthDays':20})
            self.assertIsNone(result['industries'][0]['strengthChangeRatio'])
            self.assertIsNone(result['strength']['asOfDate'])
