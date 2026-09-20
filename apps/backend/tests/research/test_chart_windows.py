"""Known OHLC aggregates, as-of boundaries, and portable annotation coordinates."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from v3_backend.research.charts import bars, drawings
from v3_backend.research.storage import write_json


class ChartWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = {'path': str(self.root), 'settings': {}}
        (self.root / 'data').mkdir()
        self.frame = pd.DataFrame([
            {'date': date, 'symbol': 'SH600000', 'open': 5 + i, 'high': 6 + i,
             'low': 4 + i, 'close': 5.5 + i, 'volume': 100 + i,
             'amount': (100 + i) * (5.5 + i), 'factor': .5,
             'rawOpen': 10 + i * 2, 'rawHigh': 12 + i * 2,
             'rawLow': 8 + i * 2, 'rawClose': 11 + i * 2}
            for i, date in enumerate(pd.to_datetime(['2025-01-02', '2025-01-03',
                '2025-01-06', '2025-01-07', '2025-01-08', '2025-01-09',
                '2025-01-10', '2025-01-13']))])
        self.save_prices()

    def save_prices(self):
        self.frame.to_parquet(self.root / 'data' / 'prices.parquet', index=False)

    def query(self, **params):
        return bars(self.project, {'symbol': '600000', **params})

    def test_weekly_as_of_and_page_boundary(self):
        full = self.query(period='week')
        self.assertEqual([row['sessions'] for row in full], [2, 5, 1])
        week = full[1]
        self.assertEqual([week[k] for k in ('open', 'high', 'low', 'close')], [7, 12, 6, 11.5])
        self.assertEqual(week['volume'], sum(range(102, 107)))
        self.assertEqual(week['turnover'], self.frame.iloc[2:7].amount.sum())
        prior = self.query(period='week', beforeDate=week['date'])
        self.assertEqual([row['date'] for row in prior], [full[0]['date']])
        bounded = self.query(period='week', endDate='2025-01-07')
        self.assertEqual([bounded[-1][k] for k in ('sessions', 'high', 'close')], [2, 9, 8.5])
        self.assertTrue(str(bounded[-1]['periodEnd']).startswith('2025-01-07'))

    def test_month_daily_and_missing_raw_data(self):
        month = self.query(period='month', endDate='2025-01-08')
        self.assertEqual(month[0]['sessions'], 5)
        self.assertEqual(month[0]['rawOpen'], 10)
        self.assertEqual(self.query(limit=2)[0]['turnover'], self.frame.iloc[-2].amount)
        self.frame.loc[3, 'rawHigh'] = None
        self.frame.loc[5:, 'factor'] = .8
        self.save_prices()
        week = self.query(period='week')[1]
        self.assertIsNone(week['rawHigh'])
        self.assertIsNone(week['factor'])
        self.assertEqual(week['high'], 12)

    def annotation(self, key, price):
        stamp = int(pd.Timestamp('2025-01-03', tz='Asia/Shanghai').timestamp() * 1000)
        return {'id': key, 'name': 'horizontalStraightLine', 'points': [{'timestamp': stamp,
            'dataIndex': 100, 'value': price}], 'styles': {'line': {'color': '#abcdef', 'size': 2}},
            'mode': 'weak_magnet', 'lock': True, 'visible': True}

    def persist(self, **params):
        return drawings(self.project, 'charts.save', {'symbol': '600000', 'merge': True, **params})

    def load(self, basis):
        return drawings(self.project, 'charts.load', {'symbol': '600000', 'priceBasis': basis})

    def test_adjustment_coordinates_styles_and_merge(self):
        self.persist(priceBasis='adjusted', annotations=[self.annotation('a', 5)], preferences={'axisType': 'log'})
        original = self.load('raw')['annotations'][0]
        self.assertEqual(original['points'][0]['value'], 10)
        self.assertNotIn('dataIndex', original['points'][0])
        self.assertEqual(original['styles']['line']['color'], '#abcdef')
        self.assertEqual(original['mode'], 'weak_magnet')
        self.frame['factor'] = .75
        self.save_prices()
        self.assertEqual(self.load('adjusted')['annotations'][0]['points'][0]['value'], 7.5)
        self.persist(priceBasis='raw', annotations=[self.annotation('b', 12)])
        self.assertEqual({item['id'] for item in self.load('raw')['annotations']}, {'a', 'b'})
        result = self.persist(priceBasis='raw', annotations=[], deletedIds=['a'])
        self.assertEqual([item['id'] for item in result['annotations']], ['b'])
        self.assertEqual(result['preferences']['axisType'], 'log')

    def test_unknown_legacy_basis_and_unrenderable_annotations_are_retained(self):
        target = self.root / 'annotations' / 'SH600000.json'
        write_json(target, [self.annotation('legacy', 12)])
        original = target.read_bytes()
        result = self.load('raw')
        self.assertEqual(result['annotations'][0]['points'][0]['value'], 12)
        self.assertTrue(result['warnings'])
        self.assertEqual(target.read_bytes(), original)
        self.persist(priceBasis='raw', annotations=[self.annotation('raw', 15)])
        self.frame['factor'] = None
        self.save_prices()
        result = self.load('adjusted')
        self.assertEqual(result['omittedIds'], ['raw'])
        self.persist(priceBasis='adjusted', annotations=[])
        self.assertIn('raw', [item['id'] for item in self.load('raw')['annotations']])


if __name__ == '__main__':
    unittest.main()
