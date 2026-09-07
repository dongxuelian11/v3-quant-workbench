import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from v3_backend.research.processing import windows,label_prices,process
from v3_backend.research.storage import Store,write_json


class ProcessingTest(unittest.TestCase):
    def test_natural_month_windows_and_invalid_step(self):
        import qlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dates = pd.bdate_range('2020-01-01','2024-12-31')
            (root/'calendars').mkdir()
            (root/'calendars/day.txt').write_text('\n'.join(dates.strftime('%Y-%m-%d')),encoding='utf-8')
            qlib.init(provider_uri=str(root),region='cn',kernels=1)
            result = windows(dates,{'validation':{'mode':'rolling','trainYears':3,'validMonths':6,'testMonths':1,'stepMonths':1}})
            first,second = result[:2]
            self.assertEqual(pd.Timestamp(first['testStart']),pd.Timestamp('2023-07-03'))
            self.assertEqual(pd.Timestamp(first['testEnd']),pd.Timestamp('2023-07-31'))
            self.assertEqual(pd.Timestamp(second['testStart']),pd.Timestamp('2023-08-01'))
            with self.assertRaises(ValueError):
                windows(dates,{'validation':{'mode':'rolling','stepMonths':0}})

    def test_next_open_labels_and_missing_historical_industry(self):
        prices = pd.DataFrame({'date':pd.bdate_range('2025-01-01',periods=4),'symbol':'SH600000','open':[10.,20.,30.,50.],'close':[9.,15.,25.,35.]})
        market = label_prices(prices)
        self.assertEqual((market.shift(-1)/market-1).iloc[0,0],.5)
        self.assertTrue(np.isnan(market.iloc[-1,0]))
        with tempfile.TemporaryDirectory() as directory:
            project = Store(Path(directory)/'app').create_project(Path(directory)/'project','p')
            codes = ['SH600000','SH600001','SH600002','SH600003']
            write_json(Path(project['path'])/'data/history/industry_future.json',{'rows':[dict(symbol=code,effectiveDate='2025-02-01',industry='银行') for code in codes]})
            values = pd.DataFrame({'f':[1.,2.,3.,4.]},index=pd.MultiIndex.from_product([[pd.Timestamp('2025-01-01')],codes],names=['datetime','instrument']))
            result,coverage = process(project,values,prices,{'neutralizeIndustry':True})
            self.assertTrue(result.f.isna().all())
            self.assertEqual(coverage.available.iloc[0],0)
