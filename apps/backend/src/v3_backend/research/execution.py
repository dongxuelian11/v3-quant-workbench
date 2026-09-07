"""Date-specific order constraints around Qlib's exchange and account execution."""
import pandas as pd
from .rules import COST_DEFAULTS, limits, quantity, affordable, fees


def cost_config(params):
    if 'costs' in params:
        result = {**COST_DEFAULTS, **params['costs']}
    else:
        result = {**COST_DEFAULTS, 'commissionBuy': params.get('commissionBuy', .0003),
                  'commissionSell': params.get('commissionSell', .0003), 'minCommission': params.get('minFee', 5),
                  'slippage': params.get('slippage', .001)}
    for key in result:
        if key == 'stampDuty' and result[key] == 'historical':
            continue
        if float(result[key]) < 0 or (key != 'minCommission' and float(result[key]) > 1):
            raise ValueError(f'costs.{key} 无效')
    return result


def exchange_class(prices, config, rejected):
    from qlib.backtest.exchange import Exchange
    from qlib.backtest.decision import Order
    market = prices.set_index(['date', 'symbol']).sort_index()
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))

    class ResearchExchange(Exchange):
        def _row(self, code, date):
            return market.loc[(pd.Timestamp(date).normalize(), code)]

        def get_deal_price(self, stock_id, start_time, end_time, direction=None, method='ts_data_last'):
            row = self._row(stock_id, start_time)
            factor = float(row.get('factor', 1))
            raw_open = float(row.get('rawOpen', row.open/factor))
            raw_preclose = row.get('rawPreclose')
            listed = pd.to_datetime(row.get('listingDate'), errors='coerce')
            session = int(calendar.searchsorted(pd.Timestamp(start_time).normalize())-calendar.searchsorted(listed)) if pd.notna(listed) and listed >= calendar[0] else None
            lower, upper, _ = limits(stock_id, start_time, raw_preclose, row.get('isST') in (1, '1'), listed, session) if pd.notna(raw_preclose) else (None, None, None)
            raw = raw_open*(1+float(config['slippage']) if direction == Order.BUY else 1-float(config['slippage']))
            if upper is not None:
                raw = min(raw, upper)
            if lower is not None:
                raw = max(raw, lower)
            return raw * factor

        def _calc_trade_info_by_order(self, order, position, dealt_order_amount):
            factor = float(self.get_factor(order.stock_id, order.start_time, order.end_time))
            side = 'buy' if order.direction == Order.BUY else 'sell'
            price = self.get_deal_price(order.stock_id, order.start_time, order.end_time, order.direction)/factor
            requested = order.amount*factor
            available = position.get_stock_amount(order.stock_id)*factor if position is not None and position.check_stock(order.stock_id) else 0
            units = quantity(order.stock_id, requested, side, available)
            if side == 'buy' and position is not None:
                units = affordable(order.stock_id, units, price, position.get_cash(), order.start_time, config)
            if units < requested-1e-6:
                rejected.append(dict(date=str(order.start_time), symbol=order.stock_id, side=side, requestedQuantity=requested,
                    allowedQuantity=units, reason='申报数量、可卖数量或含全部费用的现金约束'))
            order.amount = units/factor
            trade_price, value, _ = super()._calc_trade_info_by_order(order, position, dealt_order_amount)
            # The OSS exchange clips by known volume; reapply raw share declaration rules after that clip.
            clipped = quantity(order.stock_id, order.deal_amount*factor, side, available)
            if clipped < units:
                rejected.append(dict(date=str(order.start_time), symbol=order.stock_id, side=side, requestedQuantity=units,
                    allowedQuantity=clipped, reason='信号日已知成交量参与率约束'))
            order.deal_amount = clipped/factor
            value = order.deal_amount*trade_price
            breakdown = fees(value, side, order.start_time, config)
            order.research_fees = breakdown
            return trade_price, value, breakdown['total']

    return ResearchExchange
