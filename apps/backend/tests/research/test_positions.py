import tempfile
import unittest
from pathlib import Path
import pandas as pd
from v3_backend.research.server import Service


class PositionsTest(unittest.TestCase):
    def test_save_import_and_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = Service(root/'app')
            project = service.store.create_project(root/'project', '持仓')
            p = dict(projectId=project['id'])
            self.assertEqual(service.request('positions.get', p)['cash'], 0)
            value = dict(asOfDate='2025-01-06', cash=5000, rows=[dict(symbol='600000', quantity=250, sellableQuantity=200, costPrice=10)])
            saved = service.request('positions.save', {**p, 'positions': value})
            self.assertEqual(saved['rows'][0]['symbol'], 'SH600000')
            path = root/'positions.xlsx'
            pd.DataFrame([{**value['rows'][0], 'cash': 6000, 'asOfDate': '2025-01-07'}]).to_excel(path, index=False)
            saved = service.request('positions.import', {**p, 'path': str(path)})
            self.assertEqual(saved['cash'], 6000)
            pd.DataFrame([{'证券代码':1,'持仓数量':250,'可卖数量':200,'可用资金':7000,'日期':'2025-01-07'}]).to_excel(path,index=False)
            saved = service.request('positions.import',{**p,'path':str(path)})
            self.assertEqual(saved['rows'][0]['symbol'],'SZ000001')
            service.close()
            reopened = Service(root/'app')
            self.assertEqual(reopened.request('positions.get', p)['rows'][0]['sellableQuantity'], 200)
            with self.assertRaisesRegex(ValueError, '第 1 行'):
                reopened.request('positions.save', {**p, 'positions': {**value, 'rows':[dict(symbol='600000', quantity=100, sellableQuantity=200)]}})
            reopened.close()
