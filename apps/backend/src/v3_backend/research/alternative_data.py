"""Dated Eastmoney observations. Amounts CNY, ratios fractions; never holdings truth.

Project dictionaries or plain project/shared root paths are accepted. Data lives in
data/alternative/<kind>/<symbol>/<year>.parquet. Signals are known after date close.
"""
from pathlib import Path
from uuid import uuid4

from .data import symbol
from .storage import now


FIELDS = {
    'fund_flow': {'主力净流入-净额': 'fund_net_amount', '主力净流入-净占比': 'fund_net_ratio'},
    'chips': {'平均成本': 'chip_cost', '获利比例': 'chip_benefit', '70集中度': 'chip_concentration70',
              '90集中度': 'chip_concentration90', '70成本-低': 'chip_low70', '70成本-高': 'chip_high70',
              '90成本-低': 'chip_low90', '90成本-高': 'chip_high90'},
    'lhb': {'龙虎榜净买额': 'lhb_net_amount', '龙虎榜买入额': 'lhb_buy_amount', '龙虎榜卖出额': 'lhb_sell_amount'},
    'institutions': {'机构买入净额': 'institution_net_amount', '机构买入总额': 'institution_buy_amount',
                     '机构卖出总额': 'institution_sell_amount', '买方机构数': 'institution_buy_count', '卖方机构数': 'institution_sell_count'},
    'seats': {'买入金额': 'seat_buy_amount', '卖出金额': 'seat_sell_amount', '净额': 'seat_net_amount'},
    'lhb_coverage': {},
}
for _chinese, _name in [('小单', 'small'), ('中单', 'medium'), ('大单', 'large'), ('超大单', 'superlarge')]:
    FIELDS['fund_flow'][f'{_chinese}净流入-净额'] = f'fund_{_name}_net_amount'
    FIELDS['fund_flow'][f'{_chinese}净流入-净占比'] = f'fund_{_name}_net_ratio'
TEXT = {'lhb': {'上榜原因': 'reason'}, 'institutions': {'上榜原因': 'reason'},
        'seats': {'交易营业部名称': 'seat', '类型': 'reason', 'side': 'side'}}
WARNINGS = ['资金流通常仅近期约100日；筹码估算使用210根行情并返回最近90日，不承诺2015覆盖。',
            '筹码为东方财富模型估算，不代表实际托管持仓；成本采用不复权价格。',
            '龙虎榜信号不含上榜后收益；同日多原因金额不重复相加，冲突金额留空。',
            '来源可能修订历史，采集时间单独记录；日期表示收盘后可知，交易须下一交易日执行。']


def _folder(project, kind):
    if kind not in FIELDS:
        raise ValueError(f'未知补充数据类型: {kind}')
    if isinstance(project, dict):
        from .data import project_data
        project = project_data(project)
    return Path(project['path'] if isinstance(project, dict) else project) / 'data' / 'alternative' / kind


def normalize(frame, kind, code=None, source='import', collected_at=None):
    """Whitelist source columns; canonical ratios are fractions, Chinese fund ratio is % points."""
    import pandas as pd
    import numpy as np
    mapping = FIELDS[kind]
    data = frame.copy().rename(columns={'日期': 'date', '上榜日': 'date', '上榜日期': 'date', '代码': 'symbol', '股票代码': 'symbol'})
    if code is not None:
        data['symbol'] = symbol(code)
    if not {'date', 'symbol'}.issubset(data):
        raise ValueError('补充数据必须包含 date 和 symbol')
    out = data[['date', 'symbol']].copy()
    out['date'] = pd.to_datetime(out.date, errors='raise').dt.normalize()
    if out.date.isna().any():
        raise ValueError('补充数据日期不能为空')
    out['symbol'] = out.symbol.map(symbol)
    for chinese, canonical in mapping.items():
        value = data[canonical] if canonical in data else data[chinese] if chinese in data else pd.Series(float('nan'), index=data.index)
        out[canonical] = pd.to_numeric(value, errors='coerce').replace([np.inf, -np.inf], np.nan)
        if canonical.endswith('_ratio') and canonical not in data and chinese in data:
            out[canonical] /= 100
        elif canonical.endswith('_ratio') and 'ratioUnit' in data:
            scales = data.ratioUnit.map({'fraction': 1., '%': .01, 'percent': .01, 'percentage_points': .01})
            if scales.isna().any():
                raise ValueError('比例单位仅支持 fraction/%/percent/percentage_points')
            out[canonical] *= scales
        if canonical.endswith('_amount') and 'amountUnit' in data:
            scales = data.amountUnit.map({'CNY': 1., '元': 1., '万元': 10000., 'million_CNY': 1000000., '百万元': 1000000.})
            if scales.isna().any():
                raise ValueError('金额单位仅支持 CNY/元/万元/million_CNY/百万元')
            out[canonical] *= scales
    for original, canonical in TEXT.get(kind, {}).items():
        out[canonical] = data[canonical] if canonical in data else data[original] if original in data else ''
        out[canonical] = out[canonical].fillna('').astype(str)
    out['source'] = data['source'] if 'source' in data else source
    out['collectedAt'] = data['collectedAt'] if 'collectedAt' in data else collected_at or now()
    out['amountUnit'], out['ratioUnit'] = 'CNY', 'fraction'
    out['availability'] = 'after_close'
    if kind == 'chips':
        if 'priceBasis' not in data and source != 'AKShare/Eastmoney':
            raise ValueError('筹码导入须提供 priceBasis=unadjusted，不能猜测复权口径')
        if 'priceBasis' in data and not data.priceBasis.eq('unadjusted').all():
            raise ValueError('筹码导入必须明确采用 unadjusted 原始价格')
        out['priceBasis'] = 'unadjusted'
    keys = ['symbol', 'date'] + list(TEXT.get(kind, {}).values())
    return out.drop_duplicates(keys, keep='last').sort_values(keys).reset_index(drop=True)


def import_frame(project, kind, frame, code=None, source='import'):
    """Merge canonical/AKShare rows; preserve prior dates, atomically replace each year."""
    import pandas as pd
    data = normalize(frame, kind, code, source)
    folder = _folder(project, kind)
    for (code, year), part in data.groupby(['symbol', data.date.dt.year]):
        target = folder / code / f'{year}.parquet'
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            part = normalize(pd.concat([pd.read_parquet(target), part], ignore_index=True), kind)
        temporary = target.with_name(f'.{target.stem}-{uuid4().hex}.tmp')
        try:
            part.to_parquet(temporary, index=False)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return len(data)


def read(project, kind, symbols=None, start_date=None, end_date=None):
    import pandas as pd
    folder = _folder(project, kind)
    files = sorted(folder.glob('*/*.parquet')) if symbols is None else [p for code in symbols for p in sorted((folder / symbol(code)).glob('*.parquet'))]
    data = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True) if files else pd.DataFrame(columns=['symbol', 'date'])
    if start_date:
        data = data[data.date.ge(pd.Timestamp(start_date))]
    if end_date:
        data = data[data.date.le(pd.Timestamp(end_date))]
    return data.reset_index(drop=True)


def update(project, symbols, start_date, end_date, kinds=('fund_flow', 'chips', 'lhb'), progress=None, include_institutions=False, include_seats=False):
    """Finite requests with per-source errors. Callback exceptions propagate cancellation.

    AKShare calls are synchronous; the job owner can terminate its worker during a
    blocked upstream request. No retry loop or global requests monkeypatch is used.
    """
    import pandas as pd
    import akshare as ak
    codes = list(dict.fromkeys(symbol(x) for x in symbols))
    start, end = pd.Timestamp(start_date).normalize(), min(pd.Timestamp(end_date).normalize(), pd.Timestamp.today().normalize())
    if start > end or not codes:
        raise ValueError('请选择股票和有效的起止日期')
    if set(kinds) - {'fund_flow', 'chips', 'lhb'}:
        raise ValueError('更新类型仅支持 fund_flow/chips/lhb')
    result = {'rows': {}, 'errors': [], 'warnings': list(WARNINGS)}
    def tick(message):
        if progress:
            progress(min(.95, len(result['rows']) / max(1, len(codes) * len(kinds))), message)
    def save(kind, frame, code=None):
        normalized = normalize(frame, kind, code, 'AKShare/Eastmoney')
        normalized = normalized[normalized.date.between(start, end)]
        if code is None:
            normalized = normalized[normalized.symbol.isin(codes)]
        count = import_frame(project, kind, normalized)
        result['rows'][f'{kind}:{code or "market"}'] = count
        return normalized
    for code in codes:
        for kind in (k for k in kinds if k != 'lhb'):
            tick(f'获取 {code} {kind}')
            try:
                frame = ak.stock_individual_fund_flow(stock=code[2:], market=code[:2].lower()) if kind == 'fund_flow' else ak.stock_cyq_em(symbol=code[2:], adjust='')
                if frame.empty:
                    raise ValueError('来源未返回记录')
                save(kind, frame, code)
            except Exception as exc:
                result['errors'].append({'symbol': code, 'kind': kind, 'message': str(exc)})
    if 'lhb' in kinds:
        # Calendar-month chunks bound pagination and preserve successfully fetched ranges.
        cursor = start
        while cursor <= end:
            stop = min(cursor + pd.offsets.MonthEnd(0), end)
            tick(f'获取龙虎榜 {cursor.date()} 至 {stop.date()}')
            events = None
            try:
                raw = ak.stock_lhb_detail_em(start_date=cursor.strftime('%Y%m%d'), end_date=stop.strftime('%Y%m%d'))
                events = save('lhb', raw) if not raw.empty else pd.DataFrame(columns=['symbol', 'date'])
                # Empty response alone cannot establish successful historical coverage.
                # Coverage zeroes are admitted only for a nonempty market response.
                if not raw.empty:
                    observed_dates = pd.to_datetime(raw['上榜日'])
                    first = max(cursor, observed_dates.min())
                    last = min(stop, observed_dates.max())
                    coverage = pd.MultiIndex.from_product([codes, pd.date_range(first, last)], names=['symbol', 'date']).to_frame(index=False)
                    save('lhb_coverage', coverage)
            except Exception as exc:
                result['errors'].append({'kind': 'lhb', 'startDate': str(cursor.date()), 'endDate': str(stop.date()), 'message': str(exc)})
            if include_institutions:
                tick('获取龙虎榜机构明细')
                try:
                    raw = ak.stock_lhb_jgmmtj_em(start_date=cursor.strftime('%Y%m%d'), end_date=stop.strftime('%Y%m%d'))
                    if not raw.empty:
                        save('institutions', raw)
                except Exception as exc:
                    result['errors'].append({'kind': 'institutions', 'message': str(exc)})
            if include_seats and events is not None:
                for event in events[['symbol', 'date']].drop_duplicates().itertuples(index=False):
                    for side in ('买入', '卖出'):
                        tick(f'获取 {event.symbol} {event.date.date()} 席位{side}')
                        try:
                            raw = ak.stock_lhb_stock_detail_em(symbol=event.symbol[2:], date=event.date.strftime('%Y%m%d'), flag=side)
                            if not raw.empty:
                                raw = raw.assign(date=event.date, side=side)
                                save('seats', raw, event.symbol)
                        except Exception as exc:
                            result['errors'].append({'kind': 'seats', 'symbol': event.symbol, 'date': str(event.date.date()), 'message': str(exc)})
            cursor = stop + pd.Timedelta(days=1)
    tick('补充数据采集结束；缺失与失败记录已保留说明')
    return result


def features(project, prices):
    """Return date/symbol feature rows on supplied trading bars, never forward fill.

    Supply full historical bars before clipping dates for 5/20 trading-row windows.
    chip_cost_deviation needs rawClose; adjusted close is never a fallback.
    """
    import pandas as pd
    keys = ['symbol', 'date']
    base = prices.copy()
    base['symbol'] = base.symbol.map(symbol)
    base['date'] = pd.to_datetime(base.date).dt.normalize()
    base = base.sort_values(keys).drop_duplicates(keys, keep='last')
    result = base[keys].copy()
    codes = list(base.symbol.unique())
    for kind in ('fund_flow', 'chips'):
        data = read(project, kind, codes)
        columns = list(FIELDS[kind].values())
        if data.empty:
            for col in columns:
                result[col] = float('nan')
        else:
            result = result.merge(data[keys + columns], on=keys, how='left', validate='one_to_one')
    for window in (5, 20):
        for col in FIELDS['fund_flow'].values():
            operation = 'sum' if col.endswith('_amount') else 'mean'
            result[f'{col}{window}'] = result.groupby('symbol')[col].transform(lambda x: getattr(x.rolling(window, min_periods=window), operation)())
    result['chip_cost_deviation'] = float('nan')
    if 'rawClose' in base:
        raw = base[keys + ['rawClose']]
        result = result.merge(raw, on=keys, how='left', validate='one_to_one')
        result['chip_cost_deviation'] = pd.to_numeric(result.rawClose, errors='coerce').where(lambda x: x > 0) / result.chip_cost.where(result.chip_cost > 0) - 1
        result = result.drop(columns='rawClose')
    coverage = read(project, 'lhb_coverage', codes)
    covered = pd.MultiIndex.from_frame(coverage[keys])
    known = pd.MultiIndex.from_frame(result[keys]).isin(covered)
    for col in ('lhb_flag', 'lhb_count', 'lhb_net_amount'):
        result[col] = float('nan')
        result.loc[known, col] = 0.0
    events = read(project, 'lhb', codes)
    if not events.empty:
        # Multiple disclosure reasons may repeat a daily total or cover different periods.
        # Only an unambiguous single value is admitted, never sum duplicated totals.
        grouped = events.groupby(keys)
        net = grouped.lhb_net_amount.agg(lambda x: x.dropna().iloc[0] if x.notna().all() and x.nunique() == 1 else float('nan'))
        stats = grouped.size().rename('count').to_frame().join(net).reset_index()
        result = result.merge(stats, on=keys, how='left', suffixes=('', '_event'))
        present = result['count'].notna()
        result.loc[present, 'lhb_flag'] = 1.0
        result.loc[present, 'lhb_count'] = result.loc[present, 'count']
        result.loc[present, 'lhb_net_amount'] = result.loc[present, 'lhb_net_amount_event']
        result = result.drop(columns=['count', 'lhb_net_amount_event'])
    for window in (5, 20):
        result[f'lhb_count{window}'] = result.groupby('symbol').lhb_flag.transform(lambda x: x.rolling(window, min_periods=window).sum())
    return result
