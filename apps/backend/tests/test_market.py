import tempfile
import unittest
from pathlib import Path

import pandas as pd

from v3_backend.research import market, alternative_data as alt


class MarketTest(unittest.TestCase):
    def test_dynamic_pool_keeps_dated_names_and_raw_financial_fields(self):
        with tempfile.TemporaryDirectory() as root:
            project = {'path': root}
            path = Path(root) / 'data'
            path.mkdir()
            dates = pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04'])
            prices = pd.DataFrame({'date': dates, 'symbol': 'SH600000', 'open': 10., 'high': 10., 'low': 10., 'close': 10., 'volume': 100.})
            prices.to_parquet(path / 'prices.parquet', index=False)
            pd.DataFrame({'symbol': ['SH600000', 'SH600000'], 'name': ['普通公司', 'ST新名称'], 'effectiveDate': ['2024-01-01', '2025-01-01']}).to_parquet(path / 'securities.parquet', index=False)
            pd.DataFrame({'symbol': ['SH600000'], 'reportDate': pd.to_datetime(['2023-12-31']), 'announcementDate': pd.to_datetime(['2024-01-03']), 'currentRatio': [1.5]}).to_parquet(path / 'financials.parquet', index=False)
            panel = market.dated_panel(project)
            self.assertTrue(panel.name.eq('普通公司').all())
            self.assertTrue(market.filter_frame(panel, {'search': 'ST'}).empty)
            self.assertEqual(market.filter_frame(panel, {'filters': [{'field': 'currentRatio', 'operator': 'gte', 'value': 1}]})['date'].tolist(), [dates[-1]])
            # UI may show today's observed label; research eligibility is separately dated.
            self.assertEqual(market.screen(project)['rows'][0]['name'], 'ST新名称')

    def test_all_dynamic_members_and_basic_factors(self):
        with tempfile.TemporaryDirectory() as root:
            project = {'path': root}
            path = Path(root) / 'data'
            path.mkdir()
            frame = pd.DataFrame({'date': pd.Timestamp('2024-01-02'), 'symbol': [f'SH{600000+i}' for i in range(601)], 'close': 10., 'volume': 100.})
            frame.to_parquet(path / 'prices.parquet', index=False)
            query = {'filters': [{'field': 'close', 'operator': 'gt', 'value': 5}]}
            panel = market.dated_panel(project)
            self.assertEqual(len(market.filter_frame(panel, query)), 601)
            self.assertEqual(len(market.screen(project, {**query, 'export': True})['rows']), 601)
            bars = pd.DataFrame({'symbol': 'SH600000', 'date': pd.bdate_range('2024-01-02', periods=21),
                                 'close': range(10,31), 'volume': 100., 'pettm': 5., 'pbmrq': 2.})
            factors = market.basic_features(bars)
            self.assertEqual(factors.momentum20.iloc[-1], 2.)
            self.assertEqual(factors.earnings_yield.iloc[-1], .2)
            self.assertEqual(factors.book_yield.iloc[-1], .5)
            self.assertTrue(pd.isna(factors.momentum20.iloc[-2]))
            actual_case = bars.rename(columns={'pettm': 'peTTM', 'pbmrq': 'pbMRQ'})
            self.assertEqual(market.basic_features(actual_case).earnings_yield.iloc[-1], .2)
            self.assertEqual(market.basic_features(actual_case).book_yield.iloc[-1], .5)
            pd.DataFrame({'symbol': ['SH600000', 'SH600000'], 'announcementDate': ['2024-01-02', '2024-01-03'],
                          'reportDate': ['2023-12-31', '2023-12-31'], 'roeAvg': [.1, .9]}).to_parquet(path / 'financials.parquet', index=False)
            keys = pd.DataFrame({'symbol': ['SH600000'] * 3, 'date': pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04'])})
            financial = market._financial_factors(project, keys)
            self.assertTrue(pd.isna(financial.roe.iloc[0]))
            self.assertEqual(financial.roe.iloc[1], .1)
            self.assertEqual(financial.roe.iloc[2], .9)

    def test_screen_before_page_nulls_and_historical_date(self):
        with tempfile.TemporaryDirectory() as root:
            project = {'path': root}
            path = Path(root) / 'data'
            path.mkdir()
            frame = pd.DataFrame({'date': pd.to_datetime(['2024-01-02'] * 3 + ['2024-01-03']),
                                  'symbol': ['SH600000', 'SZ000001', 'SH600001', 'SH600000'],
                                  'name': ['浦发银行', '平安银行', '测试公司', '未来名称'],
                                  'close': [10., 20., 30., 40.], 'rawClose': [10., 20., 30., 40.],
                                  'rawPreclose': [10., 25., 25., 10.], 'volume': 100., 'amount': [1000., 2000., float('nan'), 4000.],
                                  'open': 10., 'high': 40., 'low': 9.})
            frame.to_parquet(path / 'prices.parquet', index=False)
            result = market.screen(project, {'date': '2024-01-02', 'search': '平安', 'limit': 1})
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['rows'][0]['symbol'], 'SZ000001')
            for search in ('pinganyinhang', 'payh'):
                result = market.screen(project, {'date': '2024-01-02', 'search': search, 'limit': 1})
                self.assertEqual(result['rows'][0]['symbol'], 'SZ000001')
            result = market.screen(project, {'date': '2024-01-02', 'filters': [{'field': 'amount', 'operator': 'ne', 'value': 1000}]})
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['rows'][0]['symbol'], 'SZ000001')
            result = market.overview(project, '2024-01-02')
            self.assertEqual(result['summary']['turnoverAmount'], 3000)
            self.assertEqual(result['summary']['advances'], 1)
            self.assertIsNone(result['summary']['fundNetAmount'])
            self.assertEqual(market.panorama(project, '600000', '2024-01-02')['name'], '浦发银行')
            self.assertEqual(market.panorama(project, '600000', '2024-01-02')['flow']['rows'], [])

    def test_explicit_import_amount_units(self):
        frame = pd.DataFrame({'symbol': ['600000'], 'date': ['2024-01-02'], 'fund_small_net_amount': [1.2], 'amountUnit': ['万元']})
        normalized = alt.normalize(frame, 'fund_flow')
        self.assertEqual(normalized.fund_small_net_amount.iloc[0], 12000)
        self.assertEqual(alt.normalize(normalized, 'fund_flow').fund_small_net_amount.iloc[0], 12000)


if __name__ == '__main__':
    unittest.main()
