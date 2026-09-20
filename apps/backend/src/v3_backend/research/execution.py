"""Date-specific order constraints around Qlib's exchange and account execution."""
import pandas as pd
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
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
        def is_stock_tradable(self, stock_id, start_time, end_time, direction=None):
            # Qlib's order generators ask before the order direction is known.
            # A one-sided price limit must not discard the permitted opposite side.
            if direction is None:
                return any(super(ResearchExchange, self).is_stock_tradable(
                    stock_id, start_time, end_time, side) for side in (Order.BUY, Order.SELL))
            return super().is_stock_tradable(stock_id, start_time, end_time, direction)

        def _row(self, code, date):
            return market.loc[(pd.Timestamp(date).normalize(), code)]

        def get_deal_price(self, stock_id, start_time, end_time, direction=None, method='ts_data_last'):
            row = self._row(stock_id, start_time)
            # Qlib stores factors at its own precision; amounts and account execution
            # use this same factor, rather than the original frame's float64 value.
            factor = float(self.get_factor(stock_id, start_time, end_time))
            raw_open = float(row.get('rawOpen', row.open/float(row.get('factor', 1))))
            raw_preclose = row.get('rawPreclose')
            listed = pd.to_datetime(row.get('listingDate'), errors='coerce')
            session = int(calendar.searchsorted(pd.Timestamp(start_time).normalize())-calendar.searchsorted(listed)) if pd.notna(listed) and listed >= calendar[0] else None
            lower, upper, _ = limits(stock_id, start_time, raw_preclose, row.get('isST') in (1, '1'), listed, session) if pd.notna(raw_preclose) else (None, None, None)
            slip = Decimal(str(config['slippage']))
            raw = float((Decimal(str(raw_open)) * (1+slip if direction == Order.BUY else 1-slip)).quantize(
                Decimal('.01'), rounding=ROUND_CEILING if direction == Order.BUY else ROUND_FLOOR))
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
            if hasattr(self, 'sellable'):
                available = min(available, self.sellable.get(order.stock_id, 0))
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
            if side == 'sell' and position is not None and position.get_cash()+value < breakdown['total']:
                rejected.append(dict(date=str(order.start_time), symbol=order.stock_id, side=side,
                    requestedQuantity=clipped, allowedQuantity=0, reason='卖出所得及可用现金不足支付手续费'))
                order.deal_amount = 0
                value = 0.
                breakdown = fees(0, side, order.start_time, config)
            order.research_fees = breakdown
            return trade_price, value, breakdown['total']

    return ResearchExchange


def raw_exchange(prices, config, rejected):
    """Use Qlib matching on observed raw shares, without a provider round trip."""
    from qlib.backtest.high_performance_ds import PandasQuote
    source=prices.copy().sort_values(['symbol','date'])
    source['knownVolume']=source.groupby('symbol').volume.shift(1)
    base=exchange_class(source,config,rejected)
    class RawExchange(base):
        def get_quote_from_qlib(self):
            self.trade_w_adj_price = False
            rows=[]
            calendar=pd.DatetimeIndex(sorted(source.date.unique()))
            for row in source.to_dict('records'):
                lower=upper=None;reason=None
                listed=pd.to_datetime(row.get('listingDate'),errors='coerce')
                session=int(calendar.searchsorted(row['date'])-calendar.searchsorted(listed)) if pd.notna(listed) and listed>=calendar[0] else None
                pre=row.get('rawPreclose')
                if pd.notna(pre):lower,upper,reason=limits(row['symbol'],row['date'],pre,row.get('isST') in (1,'1'),listed,session)
                else:reason='缺原始昨收，无法确定价格边界'
                opening=row.get('rawOpen');close=row.get('rawClose')
                missing=pd.isna(opening) or pd.isna(close) or row.get('tradestatus') in (0,'0') or reason is not None
                rows.append({'instrument':row['symbol'],'datetime':row['date'],'$open':opening,'$close':close,
                    '$factor':1.,'$volume':row.get('knownVolume',float('nan')),'$change':0.,
                    '$capacity':row['knownVolume']*config['volumeParticipation'] if pd.notna(row.get('knownVolume')) else 0.,
                    'limit_buy':bool(missing or upper is not None and opening>=upper),
                    'limit_sell':bool(missing or lower is not None and opening<=lower)})
            self.quote_df=pd.DataFrame(rows).set_index(['instrument','datetime']).sort_index()
    result = RawExchange(freq='day',start_time=source.date.min(),end_time=source.date.max(),codes=source.symbol.unique().tolist(),
        deal_price='$open',open_cost=0,close_cost=0,min_cost=0,trade_unit=1,limit_threshold=None,
        volume_threshold=('cum','$capacity'),quote_cls=PandasQuote)
    result.rejections = rejected
    return result
