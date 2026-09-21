import tempfile
import unittest
from pathlib import Path
import pandas as pd
from v3_backend.research.table_reader import page, replay_counts


class TableReader(unittest.TestCase):
    def test_legacy_trade_ids_and_replay_counts_across_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trades.parquet'
            size = 17000
            pd.DataFrame({'symbol': ['SH600000'] * size,
                'date': pd.date_range('2000-01-01', periods=size),
                'side': ['buy', 'sell'] * (size // 2), 'price': range(size)
            }).to_parquet(path, index=False, row_group_size=1000)
            result = page(path, {'tradeId':'8200', 'columns':['tradeId', 'price']}, 'trades')
            self.assertEqual(result['rows'], [{'tradeId':'8200', 'price':8200}])
            self.assertEqual(result['total'], 1)
            result = page(path, {'offset':15999, 'limit':3, 'columns':['tradeId', 'price']}, 'trades')
            self.assertEqual(result['total'], size)
            self.assertEqual(result['rows'], [{'tradeId':str(i), 'price':i} for i in range(15999,16002)])
            result = page(path, {'startDate':'2000-01-02', 'endDate':'2000-01-04',
                'columns':['price'], 'offset':1, 'limit':1}, 'trades')
            self.assertEqual(result['total'], 3)
            self.assertEqual(result['rows'], [{'price':2}])
            self.assertEqual(replay_counts(path, True)['SH600000'], dict(
                symbol='SH600000', tradeCount=size, buyCount=size//2, sellCount=size//2))


if __name__ == '__main__':
    unittest.main()
