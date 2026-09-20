import tempfile
import unittest
from pathlib import Path
import pandas as pd
from v3_backend.research.server import Service
from v3_backend.research.storage import Store

class RawBarsTest(unittest.TestCase):
    def test_existing_raw_fields_and_missing_legacy_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            service=object.__new__(Service)
            service.store=Store(Path(folder)/'app')
            data=Path(service.store.project(None)['path'])/'data'
            data.mkdir()
            base=dict(symbol='SH600000',date=pd.Timestamp('2025-01-02'),open=5.,high=6.,low=4.,close=5.5,volume=100.)
            pd.DataFrame([base]).to_parquet(data/'prices.parquet',index=False)
            legacy=service.request('data.bars',{'symbol':'SH600000'})[0]
            self.assertEqual(legacy['open'],5.)
            for key in ('factor','rawOpen','rawHigh','rawLow','rawClose'):
                self.assertIsNone(legacy[key])
            (data/'prices').mkdir()
            pd.DataFrame([{**base,'factor':.5,'rawOpen':10.,'rawHigh':12.,'rawLow':8.,'rawClose':11.}]).to_parquet(data/'prices/SH600000.parquet',index=False)
            actual=service.request('data.bars',{'symbol':'SH600000','startDate':'2025-01-02','endDate':'2025-01-02'})
            self.assertEqual(len(actual),1)
            self.assertEqual(actual[0]['open'],5.)
            self.assertEqual(actual[0]['rawOpen'],10.)
            self.assertEqual(actual[0]['factor'],.5)
            self.assertFalse(service.request('data.bars',{'symbol':'SH600000','beforeDate':'2025-01-02'}))

if __name__=='__main__': unittest.main()
