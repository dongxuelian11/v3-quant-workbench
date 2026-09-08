import unittest
from unittest.mock import patch
import pandas as pd
from qlib.backtest.exchange import Exchange
from qlib.backtest.decision import Order
from v3_backend.research.execution import exchange_class
from v3_backend.research.rules import COST_DEFAULTS


class ExecutionBoundariesTest(unittest.TestCase):
    def test_slippage_cent_rounding_then_limit_clamp(self):
        date = pd.Timestamp('2025-01-02')
        for raw_open, previous, expected_buy, expected_sell in (
            (10.13, 10., 10.15, 10.11), (11., 10., 11., 10.98), (9., 10., 9.01, 9.)):
            cls = exchange_class(pd.DataFrame([dict(date=date, symbol='SH600000', open=raw_open*.5,
                rawOpen=raw_open, rawPreclose=previous, factor=.5)]), COST_DEFAULTS, [])
            exchange = object.__new__(cls)
            exchange.get_factor = lambda *args: .5
            self.assertEqual(exchange.get_deal_price('SH600000', date, date, Order.BUY)/.5, expected_buy)
            self.assertEqual(exchange.get_deal_price('SH600000', date, date, Order.SELL)/.5, expected_sell)

    def test_execution_factor_precision_preserves_raw_price_and_value(self):
        date = pd.Timestamp('2025-01-02')
        source_factor = .893976
        execution_factor = .8939759731292725
        cls = exchange_class(pd.DataFrame([dict(date=date, symbol='SH600000', open=6.85*source_factor,
            rawOpen=6.85, factor=source_factor)]), {**COST_DEFAULTS, 'slippage': 0}, [])
        exchange = object.__new__(cls)
        exchange.get_factor = lambda *args: execution_factor
        adjusted = exchange.get_deal_price('SH600000', date, date, Order.BUY)
        self.assertAlmostEqual(adjusted/execution_factor, 6.85, places=12)
        self.assertAlmostEqual((100/execution_factor)*adjusted, 685., places=10)
        self.assertEqual(adjusted, 6.85*execution_factor)

    def make_exchange(self, price=10):
        rejected = []
        cls = exchange_class(pd.DataFrame([dict(date=pd.Timestamp('2025-01-02'), symbol='SH600000',
            open=price, rawOpen=price, factor=1.)]), {**COST_DEFAULTS, 'slippage': 0}, rejected)
        exchange = object.__new__(cls)
        exchange.get_factor = lambda *args, **kwargs: 1.
        exchange.check_stock_suspended = lambda *args: False
        exchange.trade_w_adj_price = False
        exchange.trade_unit = 1
        return exchange, rejected

    def test_one_sided_limits_preserve_orders_and_direction_checks(self):
        exchange, _ = self.make_exchange()
        date = pd.Timestamp('2025-01-02')
        for blocked in (Order.BUY, Order.SELL):
            exchange.check_stock_limit = lambda stock, start, end, direction: direction == blocked
            for target, current, side in (({}, {'SH600000': 100}, Order.SELL),
                                           ({'SH600000': 100}, {}, Order.BUY)):
                orders = exchange.generate_order_for_target_amount_position(target, current, date, date)
                self.assertEqual(len(orders), 1)
                self.assertEqual(orders[0].direction, side)
                self.assertEqual(exchange.check_order(orders[0]), side != blocked)

    def test_sell_minimum_fee_cannot_make_cash_negative(self):
        exchange, rejected = self.make_exchange(price=1)
        class Position:
            cash = 0
            def check_stock(self, code): return True
            def get_stock_amount(self, code): return 1
            def get_cash(self): return self.cash
        position = Position()
        date = pd.Timestamp('2025-01-02')
        def upstream(self, order, position, dealt):
            order.deal_amount = order.amount
            return 1., order.amount, 0.
        with patch.object(Exchange, '_calc_trade_info_by_order', upstream):
            order = Order('SH600000', 1, Order.SELL, date, date)
            _, value, cost = exchange._calc_trade_info_by_order(order, position, {})
            self.assertEqual((order.deal_amount, value, cost), (0, 0, 0))
            self.assertIn('不足支付手续费', rejected[-1]['reason'])
            position.cash = 10
            order = Order('SH600000', 1, Order.SELL, date, date)
            _, value, cost = exchange._calc_trade_info_by_order(order, position, {})
            self.assertAlmostEqual(cost, 5.00051)
            self.assertAlmostEqual(position.cash+value-cost, 5.99949)

if __name__ == '__main__':
    unittest.main()
