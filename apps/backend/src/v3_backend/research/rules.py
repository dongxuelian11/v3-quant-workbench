"""Daily China equity rule adapter; prices/quantities are unadjusted here."""
from decimal import Decimal, ROUND_HALF_UP
import math


COST_DEFAULTS = dict(commissionBuy=.0003, commissionSell=.0003, minCommission=5,
                     stampDuty='historical', transferFee=.00001, slippage=.001, volumeParticipation=.1)


def price_round(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def limits(symbol, date, preclose, is_st=False, listing_date=None, listing_session=None):
    date = str(date)[:10]
    if symbol.startswith('BJ'):
        raise ValueError('北交所不在本轮范围')
    star = symbol.startswith('SH688')
    chinext = symbol.startswith('SZ30')
    if listing_session is not None and listing_session < 5 and (star or chinext and str(listing_date) >= '2020-08-24' or not chinext and str(listing_date) >= '2023-04-10'):
        return None, None, None
    if listing_session == 0:
        return None, None, '旧制IPO首日缺发行价/阶段报价，无法确定可成交边界'
    rate = .2 if star or chinext and date >= '2020-08-24' else .05 if is_st and date < '2026-07-06' else .1
    base = Decimal(str(preclose))
    upper = (base * (1 + Decimal(str(rate)))).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    lower = (base * (1 - Decimal(str(rate)))).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return float(lower), float(upper), None


def fees(value, side, date, config=None):
    config = {**COST_DEFAULTS, **(config or {})}
    if value <= 0:
        return dict(commission=0., stampDuty=0., transferFee=0., total=0.)
    stamp = (.0005 if str(date)[:10] >= '2023-08-28' else .001) if config['stampDuty'] == 'historical' else float(config['stampDuty'])
    commission = max(float(config['minCommission']), value * float(config['commissionBuy' if side == 'buy' else 'commissionSell']))
    duty = value * stamp if side == 'sell' else 0.
    transfer = value * float(config['transferFee'])
    return dict(commission=commission, stampDuty=duty, transferFee=transfer, total=commission+duty+transfer)


def quantity(symbol, requested, side, sellable=0):
    requested = max(0, math.floor(requested + 1e-8))
    if side == 'sell':
        requested = min(requested, math.floor(sellable))
        if requested == sellable:
            return requested
    if symbol.startswith('SH688'):
        return requested if requested >= 200 else 0
    return requested // 100 * 100


def affordable(symbol, requested, price, cash, date, config):
    lower, upper = 0, max(0, math.floor(requested))
    while lower < upper:
        middle = (lower + upper + 1) // 2
        amount = middle * price
        if amount + fees(amount, 'buy', date, config)['total'] <= cash + 1e-9:
            lower = middle
        else:
            upper = middle - 1
    return quantity(symbol, lower, 'buy')
