import unittest
import pandas as pd
from qlib.backtest.high_performance_ds import NumpyQuote
from qlib.backtest.position import Position
from qlib.contrib.strategy.order_generator import OrderGenWOInteract
from v3_backend.research.execution import exchange_class
from v3_backend.research.rules import COST_DEFAULTS


class FirstSessionOrdersTest(unittest.TestCase):
    def test_signal_session_must_be_present_in_exchange_quotes(self):
        signal, trade = pd.Timestamp('2025-01-03'), pd.Timestamp('2025-01-06')
        prices = pd.DataFrame([dict(date=d, symbol='SH600000', open=10., rawOpen=10., factor=1.)
                               for d in (signal, trade)])
        cls = exchange_class(prices, COST_DEFAULTS, [])
        exchange = object.__new__(cls)
        exchange.trade_w_adj_price = False
        exchange.trade_unit = 1
        quote = pd.DataFrame({'$close': [10., 10.], '$factor': [1., 1.],
                              'limit_buy': [False, False], 'limit_sell': [False, False]},
                             index=pd.MultiIndex.from_product([['SH600000'], [signal, trade]],
                                                               names=['instrument', 'datetime']))
        generator = OrderGenWOInteract()
        def orders():
            return generator.generate_order_list_from_target_weight_position(
                Position(cash=1000000), exchange, {'SH600000': .3}, 1., signal, signal, trade, trade)
        exchange.quote = NumpyQuote(quote.iloc[1:], 'day')
        self.assertEqual(orders(), [])  # The original start boundary silently lost the first orders.
        exchange.quote = NumpyQuote(quote, 'day')
        actual = orders()
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0].start_time, trade)
        self.assertEqual(actual[0].amount, 30000)

if __name__ == '__main__': unittest.main()
