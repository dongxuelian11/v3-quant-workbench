import tempfile
import unittest
from pathlib import Path
import pandas as pd
from v3_backend.research.analysis_reader import read


class AnalysisReader(unittest.TestCase):
    def test_viewport_sampling_keeps_endpoints_extrema_and_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'chart.parquet'
            dates=pd.date_range('2000-01-01',periods=20000)
            values=[1.]*20000; values[15000]=100.; values[19000]=-50.; values[10000]=None
            pd.DataFrame({'date':dates,'value':values}).to_parquet(path,index=False)
            value=read(path,'curve',{'maxPoints':100,'sampling':'minmax'})
            self.assertEqual(value['aggregation']['method'],'minmax')
            self.assertLessEqual(len(value['rows']),100)
            self.assertEqual(str(value['rows'][0]['date'])[:10],'2000-01-01')
            self.assertEqual(str(value['rows'][-1]['date'])[:10],str(dates[-1].date()))
            sampled=[r['value'] for r in value['rows']]
            self.assertIn(100.,sampled);self.assertIn(-50.,sampled);self.assertIn(None,sampled)

    def test_sampling_does_not_mix_duplicate_date_series(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'chart.parquet'
            pd.DataFrame({'date':['2020-01-01']*100,'value':range(100)}).to_parquet(path,index=False)
            value=read(path,'curve',{'maxPoints':20,'sampling':'minmax'})
            self.assertEqual(value['aggregation']['method'],'preview')

    def test_rolling_uses_full_calendar_before_view_window(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dates = pd.bdate_range('2020-01-01', periods=45)
            path, coverage = root/'ic.parquet', root/'coverage.parquet'
            pd.DataFrame({'date':dates, 'factor':['test']*45}).to_parquet(coverage, index=False)
            pd.DataFrame({'date':dates.delete(10), '5D':[.25]*44}).to_parquet(path, index=False)
            value = read(path, 'test_RankIC', {'rolling':{'window':20,'statistic':'mean'},
                'startDate':str(dates[25].date()), 'maxPoints':50}, coverage)
            self.assertIsNone(value['rows'][0]['5D'])
            self.assertEqual(value['rows'][5]['5D'], .25)
            self.assertEqual(value['calendarSource'], 'experiment_processing_sessions')

    def test_preview_filters_factor_before_limit_and_keeps_total(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'coverage.parquet'
            pd.DataFrame({'date':['2020-01-02']*20,'factor':['a','b']*10,'available':list(range(20))}).to_parquet(path,index=False)
            value = read(path,'processing_coverage',{'factor':'b','maxPoints':3})
            self.assertEqual(value['total'],10)
            self.assertEqual([row['available'] for row in value['rows']],[1,3,5])
            self.assertEqual(value['aggregation']['method'],'preview')


if __name__ == '__main__':
    unittest.main()
