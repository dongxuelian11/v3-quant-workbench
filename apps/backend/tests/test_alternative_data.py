import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from v3_backend.research import alternative_data as alt


class AlternativeDataTest(unittest.TestCase):
    def test_units_whitelist_and_missing(self):
        fund = alt.normalize(pd.DataFrame({'日期': ['2024-01-02'], '主力净流入-净额': [120000], '主力净流入-净占比': [12.5]}), 'fund_flow', '600000')
        self.assertEqual(fund.fund_net_amount.iloc[0], 120000)
        self.assertEqual(fund.fund_net_ratio.iloc[0], .125)
        event = alt.normalize(pd.DataFrame({'date': ['2024-01-02'], 'symbol': ['600000'], '上榜后1日': [999]}), 'lhb')
        self.assertNotIn('上榜后1日', event)
        self.assertTrue(pd.isna(event.lhb_net_amount.iloc[0]))
        with self.assertRaises(ValueError):
            alt.normalize(pd.DataFrame({'date': ['2024-01-02'], 'symbol': ['600000'], '平均成本': [10]}), 'chips')

    def test_incremental_rolling_and_same_price_basis(self):
        dates = pd.bdate_range('2024-01-02', periods=21)
        bars = pd.DataFrame({'date': dates, 'symbol': 'SH600000', 'rawClose': 12., 'close': 120.})
        fund = bars[['symbol', 'date']].assign(fund_net_amount=2., fund_net_ratio=.1)
        with tempfile.TemporaryDirectory() as root:
            alt.import_frame(root, 'fund_flow', fund.iloc[:10])
            alt.import_frame(root, 'fund_flow', fund.iloc[8:])
            self.assertEqual(len(alt.read(root, 'fund_flow')), 21)
            alt.import_frame(root, 'chips', bars[['symbol', 'date']].assign(chip_cost=10., chip_benefit=.8, priceBasis='unadjusted'))
            events = pd.DataFrame({'symbol': ['600000', '600000'], 'date': [dates[4], dates[4]], 'reason': ['a', 'b'], 'lhb_net_amount': [100., 100.], '上榜后5日': [99., 99.]})
            alt.import_frame(root, 'lhb', events)
            value = alt.features(root, bars)
            self.assertTrue(pd.isna(value.fund_net_amount5.iloc[3]))
            self.assertEqual(value.fund_net_amount5.iloc[4], 10)
            self.assertEqual(value.fund_net_amount20.iloc[19], 40)
            self.assertAlmostEqual(value.chip_cost_deviation.iloc[0], .2)
            self.assertEqual(value.chip_benefit.iloc[0], .8)
            self.assertTrue(pd.isna(value.lhb_flag.iloc[0]))
            self.assertEqual(value.lhb_count.iloc[4], 2)
            self.assertEqual(value.lhb_net_amount.iloc[4], 100)
            self.assertTrue(alt.features(root, bars.drop(columns='rawClose')).chip_cost_deviation.isna().all())
            # Missing a source trading date invalidates a full rolling window.
            fund.loc[10, 'fund_net_amount'] = float('nan')
            alt.import_frame(root, 'fund_flow', fund.iloc[[10]])
            self.assertTrue(pd.isna(alt.features(root, bars).fund_net_amount5.iloc[14]))

    def test_transport_retry_is_same_source_and_bounded(self):
        import requests
        sample = pd.DataFrame({'日期':['2026-09-07'],'主力净流入-净额':[-80335202.], '主力净流入-净占比':[-9.96]})
        with tempfile.TemporaryDirectory() as root, patch('time.sleep'), patch('akshare.stock_individual_fund_flow',side_effect=[requests.ConnectionError('closed'),sample]) as source:
            result = alt.update(root,['SH600000'],'2026-09-01','2026-09-07',kinds=('fund_flow',))
            self.assertFalse(result['errors'])
            self.assertEqual(result['attempts']['fund_flow:SH600000'],2)
            self.assertEqual(source.call_args_list[0],source.call_args_list[1])
            self.assertEqual(source.call_args.kwargs,{'stock':'600000','market':'sh'})
            self.assertAlmostEqual(alt.read(root,'fund_flow').fund_net_ratio.iloc[0],-.0996)
        with tempfile.TemporaryDirectory() as root, patch('time.sleep'), patch('akshare.stock_cyq_em',side_effect=requests.Timeout('read')) as source:
            result = alt.update(root,['SH600000'],'2026-09-01','2026-09-07',kinds=('chips',))
            self.assertEqual(source.call_count,2)
            self.assertEqual(source.call_args.kwargs,{'symbol':'600000','adjust':''})
            self.assertEqual(len(result['errors']),1)
            self.assertTrue(alt.read(root,'chips').empty)
        with tempfile.TemporaryDirectory() as root, patch('akshare.stock_cyq_em',side_effect=ValueError('source payload changed')) as source:
            result = alt.update(root,['SH600000'],'2026-09-01','2026-09-07',kinds=('chips',))
            self.assertEqual(source.call_count,1)
            self.assertEqual(result['attempts']['chips:SH600000'],1)
            self.assertEqual(len(result['errors']),1)


if __name__ == '__main__':
    unittest.main()
