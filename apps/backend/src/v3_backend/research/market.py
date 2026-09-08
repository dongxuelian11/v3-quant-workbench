"""Read-only dated market views over the shared/project datasets."""
from pathlib import Path

from . import alternative_data as alt
from .data import project_data, read_table, records, symbol
from .storage import read_json, now
from .engines import FINANCIAL, NAMES


LABELS = {'symbol': '代码', 'name': '名称', 'date': '数据日期', 'industry': '行业',
          'close': '复权收盘价', 'rawClose': '收盘价（元）', 'changeRatio': '涨跌幅（比例）',
          'amount': '成交额（元）', 'volume': '成交量（股）', 'rawTurn': '换手率（%）',
          'pettm': '市盈率TTM', 'pbmrq': '市净率', 'fund_net_amount': '主力净流入（元）',
          'fund_net_ratio': '主力净流入占比', 'chip_cost': '估算筹码平均成本（元）',
          'chip_benefit': '估算获利比例', 'chip_cost_deviation': '原始价格偏离筹码成本',
          'lhb_flag': '当日上榜', 'lhb_count': '当日上榜原因数', 'lhb_net_amount': '龙虎榜净买入（元）'}
for _size, _label in [('small', '小单'), ('medium', '中单'), ('large', '大单'), ('superlarge', '超大单')]:
    LABELS[f'fund_{_size}_net_amount'] = f'{_label}净流入（元）'
    LABELS[f'fund_{_size}_net_ratio'] = f'{_label}净流入占比'
for _key, _label in list(LABELS.items()):
    if _key.startswith('fund_'):
        for _window in (5, 20):
            LABELS[f'{_key}{_window}'] = f'{_window}日' + ('累计' if _key.endswith('amount') else '平均') + _label
LABELS.update(NAMES)
LABELS.update({'peTTM': '市盈率TTM', 'pbMRQ': '市净率', 'psTTM': '市销率TTM', 'pcfNcfTTM': '市现率TTM',
               'roeAvg': '平均净资产收益率', 'npMargin': '销售净利率', 'netProfitMargin': '销售净利率',
               'gpMargin': '销售毛利率', 'netProfit': '净利润（元）', 'epsTTM': '每股收益TTM（元）',
               'MBRevenue': '主营营业收入（元）', 'totalShare': '总股本（股）', 'liqaShare': '流通股本（股）',
               'YOYEquity': '净资产同比', 'YOYAsset': '总资产同比', 'YOYNI': '净利润同比',
               'YOYEPSBasic': '基本每股收益同比', 'YOYPNI': '归母净利润同比', 'YOYRevenue': '营业收入同比',
               'currentRatio': '流动比率', 'quickRatio': '速动比率', 'cashRatio': '现金比率',
               'YOYLiability': '总负债同比', 'liabilityToAsset': '资产负债率', 'assetToEquity': '权益乘数',
               'CAToAsset': '流动资产占总资产', 'NCAToAsset': '非流动资产占总资产',
               'tangibleAssetToAsset': '有形资产占总资产', 'ebitToInterest': '利息保障倍数',
               'CFOToOR': '经营现金流占营业收入', 'CFOToNP': '经营现金流占净利润', 'CFOToGr': '经营现金流占营业总收入',
               'CFOToSales': '经营现金流占销售收入', 'CFOToAsset': '经营现金流占总资产', 'CFOToProfit': '经营现金流占利润',
               'pubDate': '公告日期', 'statDate': '报告期', 'historicalName': '历史名称（有日期记录）',
               'nameAsOfDate': '显示名称采集日期', 'nameIsCurrent': '显示名称使用最新观察记录',
               'rawOpen': '原始开盘价（元）', 'rawHigh': '原始最高价（元）', 'rawLow': '原始最低价（元）',
               'rawPreclose': '原始昨收价（元）', 'open': '复权开盘价', 'high': '复权最高价', 'low': '复权最低价',
               'turn': '换手率（%）', 'pctChg': '涨跌幅（%）', 'tradestatus': '交易状态', 'isST': '风险警示状态',
               'factor': '复权因子', 'listingDate': '上市日期', 'delistingDate': '退市日期'})
LABELS.update({'chip_concentration70': '估算70%筹码集中度', 'chip_concentration90': '估算90%筹码集中度',
               'chip_low70': '估算70%成本下限（元）', 'chip_high70': '估算70%成本上限（元）',
               'chip_low90': '估算90%成本下限（元）', 'chip_high90': '估算90%成本上限（元）',
               'lhb_count5': '5日上榜天数', 'lhb_count20': '20日上榜天数',
               'lhb_buy_amount': '龙虎榜买入额（元）', 'lhb_sell_amount': '龙虎榜卖出额（元）',
               'institution_net_amount': '机构净买入（元）', 'institution_buy_amount': '机构买入额（元）',
               'institution_sell_amount': '机构卖出额（元）', 'institution_buy_count': '买方机构数',
               'institution_sell_count': '卖方机构数', 'seat_net_amount': '营业部净额（元）',
               'seat_buy_amount': '营业部买入额（元）', 'seat_sell_amount': '营业部卖出额（元）',
               'seat': '营业部', 'reason': '上榜原因/类型', 'side': '买卖榜单', 'detailType': '明细类型',
               'source': '数据来源', 'collectedAt': '采集时间', 'amountUnit': '金额单位',
               'ratioUnit': '比例单位', 'priceBasis': '价格口径', 'availability': '适用时点',
               'factorSource': '因子来源', 'factorProcessing': '因子处理', 'announcementDate': '公告日期', 'reportDate': '报告期'})
DATA_LABELS = {'prices': '日线行情', 'financials': '公告财务', 'fund_flow': '资金流向', 'chips': '估算筹码',
               'lhb': '龙虎榜事件', 'institutions': '龙虎榜机构', 'seats': '龙虎榜营业部', 'industry': '历史行业', 'benchmarks': '指数行情'}


def _table(name, frame, limit=30):
    return {'name': name, 'columns': list(frame.columns), 'rows': records(frame.tail(limit)), 'total':len(frame), 'offset':max(0,len(frame)-limit), 'limit':limit,
            'fieldLabels': {column: LABELS.get(column, column) for column in frame}}


def _read(project, kind):
    import pandas as pd
    root = Path(project_data(project)['path']) / 'data'
    if not (root / f'{kind}.parquet').exists() and not list((root / kind).glob('*.parquet')):
        return pd.DataFrame(columns=['symbol', 'date'])
    return read_table(project, kind)


def _coverage(kind, frame, date_col='date', source=None):
    import pandas as pd
    dates = pd.to_datetime(frame[date_col], errors='coerce').dropna() if date_col in frame else pd.Series(dtype='datetime64[ns]')
    sources = ', '.join(sorted(frame.source.dropna().astype(str).unique())) if 'source' in frame else source or '本地已存数据'
    return {'dataset': kind, 'label': DATA_LABELS.get(kind, kind), 'source': sources,
            'rows': len(frame), 'symbols': int(frame.symbol.nunique()) if 'symbol' in frame else None,
            'startDate': dates.min().strftime('%Y-%m-%d') if len(dates) else None,
            'endDate': dates.max().strftime('%Y-%m-%d') if len(dates) else None,
            'status': 'partial' if len(frame) else 'missing', 'estimated': kind == 'chips',
            'message': '仅代表本地已观察覆盖，非完整沪深全市场。' if len(frame) else '尚无实际数据；不会以零替代。'}


def basic_features(prices):
    """Cheap unprocessed equivalents of the existing five basic factor expressions.

    These values are explicitly raw, never presented as a saved processed Qlib run.
    No Qlib initialization, cache rebuilding or network calls occur in a view.
    """
    import pandas as pd
    import numpy as np
    keys = ['symbol', 'date']
    data = prices.sort_values(keys).drop_duplicates(keys, keep='last').copy()
    for actual, canonical in [('peTTM', 'pettm'), ('pbMRQ', 'pbmrq')]:
        if actual in data:
            data[canonical] = data[actual]
    output = data[keys].copy()
    for column in ('close', 'volume', 'pettm', 'pbmrq'):
        data[column] = pd.to_numeric(data[column], errors='coerce') if column in data else float('nan')
    grouped = data.groupby('symbol')
    lag = grouped.close.shift(20)
    output['momentum20'] = data.close / lag.where(lag.ne(0)) - 1
    change = data.close / grouped.close.shift(1).where(lambda x: x.ne(0)) - 1
    output['volatility20'] = change.groupby(data.symbol).transform(lambda x: x.rolling(20, min_periods=20).std(ddof=1))
    average = grouped.volume.transform(lambda x: x.rolling(20, min_periods=20).mean())
    output['volume_ratio'] = data.volume / average.where(average.ne(0))
    output['earnings_yield'] = 1 / data.pettm.where(data.pettm.ne(0))
    output['book_yield'] = 1 / data.pbmrq.where(data.pbmrq.ne(0))
    return output.replace([np.inf, -np.inf], np.nan)


def _financial_factors(project, keys):
    """Announcement strictly before signal day, retaining actual report/announcement dates."""
    import pandas as pd
    keys = keys.copy()
    keys['date'] = pd.to_datetime(keys.date).astype('datetime64[ns]')
    data = _read(project, 'financials')
    result = keys.copy()
    for factor in FINANCIAL:
        result[factor] = float('nan')
    if data.empty or result.empty:
        return result
    data = data.copy()
    data['announcementDate'] = pd.to_datetime(data.announcementDate).astype('datetime64[ns]')
    data = data.sort_values(['announcementDate', 'reportDate']).drop_duplicates(['symbol', 'announcementDate'], keep='last')
    for factor, column in FINANCIAL.items():
        if column not in data and column == 'npMargin' and 'netProfitMargin' in data:
            column = 'netProfitMargin'
        data[factor] = pd.to_numeric(data[column], errors='coerce') if column in data else float('nan')
    parts = []
    for code, part in keys.groupby('symbol'):
        # A saved screener may use any source financial field, not only the five
        # named research factors. Preserve the same dated values in both paths.
        columns = [column for column in data if column not in {'symbol', 'date'}]
        financial = data.loc[data.symbol.eq(code), columns]
        merged = pd.merge_asof(part.sort_values('date'), financial.sort_values('announcementDate'), left_on='date', right_on='announcementDate', direction='backward', allow_exact_matches=False)
        parts.append(merged)
    return pd.concat(parts, ignore_index=True) if parts else result


def catalog(project, code=None, end_date=None):
    import pandas as pd
    from . import history
    result = []
    def clip(frame, date_col):
        if code is not None and 'symbol' in frame:
            frame = frame[frame.symbol.eq(symbol(code))]
        if end_date is not None and date_col in frame:
            frame = frame[pd.to_datetime(frame[date_col], errors='coerce').le(pd.Timestamp(end_date))]
        return frame
    for kind in ('prices', 'financials'):
        col = 'announcementDate' if kind == 'financials' else 'date'
        result.append(_coverage(kind, clip(_read(project, kind), col), col))
    for kind in ('fund_flow', 'chips', 'lhb', 'institutions', 'seats'):
        result.append(_coverage(kind, alt.read(project, kind, [code] if code else None, end_date=end_date)))
    result.append(_coverage('industry', clip(history.read(project_data(project), 'industry'), 'effectiveDate'), 'effectiveDate'))
    frames = [pd.read_parquet(p) for p in (Path(project_data(project)['path']) / 'data' / 'benchmarks').glob('*.parquet')]
    result.append(_coverage('benchmarks', clip(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), 'date')))
    return result


def _snapshot(project, date=None, with_features=True):
    import pandas as pd
    from .history import industries
    prices = _read(project, 'prices')
    if prices.empty:
        return prices, date or '', prices
    prices = prices.copy()
    prices['date'] = pd.to_datetime(prices.date).dt.normalize()
    cutoff = pd.Timestamp(date).normalize() if date else prices.date.max()
    prices = prices[prices.date.le(cutoff)].sort_values(['symbol', 'date'])
    if prices.empty:
        return prices, str(cutoff.date()), prices
    # A requested trading day is exact. A weekend selects the last actual market day.
    asof = prices.date.max()
    panel = prices[prices.date.eq(asof)].copy()
    panel['changeRatio'] = float('nan')
    if {'rawClose', 'rawPreclose'}.issubset(panel):
        previous = pd.to_numeric(panel.rawPreclose, errors='coerce')
        panel['changeRatio'] = pd.to_numeric(panel.rawClose, errors='coerce') / previous.where(previous > 0) - 1
    elif 'pctChg' in panel:
        panel['changeRatio'] = pd.to_numeric(panel.pctChg, errors='coerce') / 100
    panel['industry'] = panel.symbol.map(industries(project_data(project), asof, panel.symbol))
    # Names are accepted only when carried by dated rows/observations.
    if 'name' not in panel:
        panel['name'] = panel['code_name'] if 'code_name' in panel else ''
    panel['historicalName'] = panel['name']
    panel['nameAsOfDate'] = panel['date']
    panel['nameIsCurrent'] = False
    metadata = Path(project_data(project)['path']) / 'data' / 'securities.parquet'
    if metadata.exists():
        names = pd.read_parquet(metadata)
        if {'symbol', 'name', 'effectiveDate'}.issubset(names):
            dated_names = names[pd.to_datetime(names.effectiveDate).le(asof)].sort_values('effectiveDate').drop_duplicates('symbol', keep='last').set_index('symbol')
            panel['historicalName'] = panel['historicalName'].astype('string').replace('', pd.NA).fillna(panel.symbol.map(dated_names['name']))
            current = names.sort_values('effectiveDate').drop_duplicates('symbol', keep='last').set_index('symbol')
            observed = panel.symbol.map(current['name'])
            present = observed.notna()
            panel.loc[present, 'name'] = observed[present]
            panel.loc[present, 'nameAsOfDate'] = pd.to_datetime(panel.loc[present, 'symbol'].map(current['effectiveDate']))
            panel.loc[present, 'nameIsCurrent'] = True
    if with_features:
        # Full preceding bars preserve rolling windows; exact-day joins preserve null coverage.
        additions = alt.features(project, prices)
        additions = additions[additions.date.eq(asof)]
        panel = panel.merge(additions, on=['symbol', 'date'], how='left', validate='one_to_one')
        basic = basic_features(prices)
        panel = panel.merge(basic[basic.date.eq(asof)], on=['symbol', 'date'], how='left', validate='one_to_one')
        financial_factors = _financial_factors(project, panel[['symbol', 'date']])
        panel = panel.merge(financial_factors, on=['symbol', 'date'], how='left', validate='one_to_one')
        financials = _read(project, 'financials')
        if not financials.empty:
            financials = financials[pd.to_datetime(financials.announcementDate).lt(asof)]
            financials = financials.sort_values(['announcementDate', 'reportDate']).drop_duplicates('symbol', keep='last')
            columns = ['symbol'] + [c for c in financials if c not in panel and c != 'date']
            panel = panel.merge(financials[columns], on='symbol', how='left', validate='one_to_one')
    return panel, str(asof.date()), prices


def _search_names(frame, query):
    import pandas as pd
    text = str(query).strip().casefold()
    searchable = pd.Series('', index=frame.index)
    for col in ('symbol', 'name', 'pinyin', 'initials'):
        if col in frame:
            searchable = searchable + ' ' + frame[col].fillna('').astype(str).str.casefold()
    try:
        from pypinyin import lazy_pinyin, Style
    except ImportError:
        pass  # Explicit source pinyin columns remain searchable; no fabricated transliteration.
    else:
        if 'name' in frame:
            names = frame['name'].fillna('').astype(str)
            unique = {name: ''.join(lazy_pinyin(name)) + ' ' + ''.join(lazy_pinyin(name, style=Style.FIRST_LETTER)) for name in names.unique()}
            searchable += ' ' + names.map(unique).str.casefold()
    return searchable.str.contains(text, regex=False)


def filter_frame(frame, query=None, watchlists=None):
    """Apply the complete query to an already prepared date slice, without I/O or limits."""
    import pandas as pd
    query = query or {}
    if query.get('symbols') is not None:
        frame = frame[frame.symbol.isin([symbol(x) for x in query['symbols']])]
    if query.get('watchlistId'):
        selected = next((w for w in watchlists or [] if w['id'] == query['watchlistId']), None)
        if selected is None:
            raise ValueError('自选列表不存在')
        frame = frame[frame.symbol.isin([symbol(x) for x in selected['symbols']])]
    masks = []
    for rule in query.get('filters', []):
        field, op, value = rule['field'], rule['operator'], rule.get('value')
        if field not in frame:
            raise ValueError(f'筛选字段尚不可用: {field}')
        series = frame[field]
        if op in {'gt', 'gte', 'lt', 'lte'} or op in {'eq', 'ne'} and isinstance(value, (int, float)):
            numeric = pd.to_numeric(series, errors='coerce')
            functions = {'gt': 'gt', 'gte': 'ge', 'lt': 'lt', 'lte': 'le', 'eq': 'eq', 'ne': 'ne'}
            mask = numeric.notna() & getattr(numeric, functions[op])(float(value))
        elif op == 'contains':
            mask = series.notna() & series.astype(str).str.contains(str(value), regex=False, case=False)
        elif op == 'in':
            if not isinstance(value, list):
                raise ValueError('in 条件需要数组')
            mask = series.notna() & series.isin(value)
        elif op in {'eq', 'ne'}:
            mask = series.notna() & getattr(series, op)(value)
        else:
            raise ValueError(f'不支持筛选运算: {op}')
        masks.append(mask.fillna(False))
    if masks:
        combined = pd.concat(masks, axis=1)
        frame = frame[combined.any(axis=1) if query.get('match') == 'any' else combined.all(axis=1)]
    if query.get('search'):
        frame = frame[_search_names(frame, query['search'])]
    sort = query.get('sortBy') or 'symbol'
    if sort not in frame:
        raise ValueError(f'排序字段尚不可用: {sort}')
    frame = frame.sort_values(sort, ascending=not query.get('descending', False), kind='stable', na_position='last')
    return frame


def screen(project, query=None, watchlists=None):
    query = query or {}
    frame, asof, _ = _snapshot(project, query.get('date'))
    frame = filter_frame(frame, query, watchlists)
    total, offset, limit = len(frame), max(0, int(query.get('offset', 0))), max(1, min(500, int(query.get('limit', 100))))
    if query.get('export'):
        offset, limit = 0, total
    return {'name': 'market', 'columns': list(frame.columns), 'rows': records(frame.iloc[offset:offset + limit]),
            'total': total, 'offset': offset, 'limit': limit, 'asOfDate': asof,
            'coverage': catalog(project, end_date=asof or None), 'fieldLabels': LABELS}


def dated_panel(project, prices=None):
    """Prepare once per research job; slice by date and call filter_frame thereafter.

    Each source is read once, with as-of joins for dated observations. No catalog,
    Qlib initialization or per-trading-day disk access. Caller owns cache lifetime.
    """
    import pandas as pd
    from . import history
    prices = _read(project, 'prices') if prices is None else prices.copy()
    if prices.empty:
        return prices
    prices['date'] = pd.to_datetime(prices.date).dt.normalize().astype('datetime64[ns]')
    prices['symbol'] = prices.symbol.map(symbol)
    panel = prices.sort_values(['symbol', 'date']).drop_duplicates(['symbol', 'date'], keep='last')
    keys = ['symbol', 'date']
    for additions in (basic_features(panel), alt.features(project, panel), _financial_factors(project, panel[keys])):
        columns = keys + [col for col in additions if col not in panel]
        panel = panel.merge(additions[columns], on=keys, how='left', validate='one_to_one')
    panel['changeRatio'] = float('nan')
    if {'rawClose', 'rawPreclose'}.issubset(panel):
        previous = pd.to_numeric(panel.rawPreclose, errors='coerce')
        panel['changeRatio'] = pd.to_numeric(panel.rawClose, errors='coerce') / previous.where(previous > 0) - 1
    elif 'pctChg' in panel:
        panel['changeRatio'] = pd.to_numeric(panel.pctChg, errors='coerce') / 100
    industry = history.read(project_data(project), 'industry')
    industry['effectiveDate'] = pd.to_datetime(industry.effectiveDate).astype('datetime64[ns]')
    industry = industry.sort_values('effectiveDate').drop_duplicates(['symbol', 'effectiveDate'], keep='last')
    # Imported latest industry in price rows has no independent dating authority.
    panel = panel.drop(columns='industry', errors='ignore')
    pieces = []
    for code, part in panel.groupby('symbol'):
        observations = industry[industry.symbol.eq(code)][['effectiveDate', 'industry']]
        pieces.append(pd.merge_asof(part.sort_values('date'), observations.sort_values('effectiveDate'), left_on='date', right_on='effectiveDate', direction='backward').drop(columns='effectiveDate'))
    panel = pd.concat(pieces, ignore_index=True)
    panel['historicalName'] = panel['name'] if 'name' in panel else panel['code_name'] if 'code_name' in panel else ''
    panel['name'] = panel['historicalName']
    panel['nameAsOfDate'] = panel['date']
    panel['nameIsCurrent'] = False
    path = Path(project_data(project)['path']) / 'data' / 'securities.parquet'
    if path.exists():
        names = pd.read_parquet(path)
        if {'symbol', 'name', 'effectiveDate'}.issubset(names):
            names['effectiveDate'] = pd.to_datetime(names.effectiveDate).astype('datetime64[ns]')
            names = names.sort_values('effectiveDate').drop_duplicates(['symbol', 'effectiveDate'], keep='last')
            latest = names.sort_values('effectiveDate').drop_duplicates('symbol', keep='last').set_index('symbol')
            pieces = []
            for code, part in panel.groupby('symbol'):
                observations = names.loc[names.symbol.eq(code), ['effectiveDate', 'name']].rename(columns={'effectiveDate': 'nameObservationDate', 'name': 'observedHistoricalName'})
                merged = pd.merge_asof(part.sort_values('date'), observations, left_on='date', right_on='nameObservationDate', direction='backward')
                dated = merged['historicalName'].astype('string').replace('', pd.NA)
                merged['name'] = dated.fillna(merged['observedHistoricalName']).fillna('')
                merged['historicalName'] = merged['name']
                merged['nameAsOfDate'] = merged['date'].where(dated.notna(), merged['nameObservationDate'])
                # Current names are useful labels, but filter_frame never searches them.
                merged['displayName'] = merged.symbol.map(latest['name'])
                pieces.append(merged.drop(columns=['observedHistoricalName', 'nameObservationDate']))
            panel = pd.concat(pieces, ignore_index=True)
    return panel


def overview(project, date=None):
    import pandas as pd
    frame, asof, _ = _snapshot(project, date)
    def total(col, part=frame):
        values = pd.to_numeric(part[col], errors='coerce') if col in part else pd.Series(dtype=float)
        return float(values.sum(min_count=1)) if values.notna().any() else None
    changes = frame['changeRatio'].dropna() if 'changeRatio' in frame else pd.Series(dtype=float)
    summary = {'observedStocks': len(frame), 'changeCoveredStocks': len(changes), 'advances': int(changes.gt(0).sum()) if len(changes) else None,
               'declines': int(changes.lt(0).sum()) if len(changes) else None, 'unchanged': int(changes.eq(0).sum()) if len(changes) else None,
               'turnoverAmount': total('amount'), 'fundNetAmount': total('fund_net_amount'),
               'fundCoveredStocks': int(frame.fund_net_amount.notna().sum()) if 'fund_net_amount' in frame else 0}
    industry = []
    if 'industry' in frame:
        for name, part in frame.dropna(subset='industry').groupby('industry'):
            values = part.changeRatio.dropna()
            industry.append({'industry': name, 'stocks': len(part), 'changeCoveredStocks': len(values),
                             'meanChangeRatio': float(values.mean()) if len(values) else None, 'turnoverAmount': total('amount', part),
                             'fundNetAmount': total('fund_net_amount', part)})
    indices = []
    for path in (Path(project_data(project)['path']) / 'data' / 'benchmarks').glob('*.parquet'):
        data = pd.read_parquet(path)
        if asof:
            data = data[pd.to_datetime(data.date).eq(pd.Timestamp(asof))]
        else:
            data = data.iloc[:0]
        if not data.empty:
            indices.extend(records(data.tail(1)))
    bins = [('跌超5%', -float('inf'), -.05), ('跌幅0至5%', -.05, 0), ('涨幅0至5%', 0, .05), ('涨超5%', .05, float('inf'))]
    breadth = [{'name': name, 'count': int(((changes > low) & (changes <= high) & changes.ne(0)).sum()) if len(changes) else None} for name, low, high in bins]
    return {'asOfDate': asof, 'summary': summary, 'indices': indices, 'industries': industry, 'breadth': breadth,
            'coverage': catalog(project, end_date=asof or None)}


def stock_frames(project, code, date=None):
    import pandas as pd
    code = symbol(code)
    snapshot, asof, prices = _snapshot(project, date)
    row = snapshot[snapshot.symbol.eq(code)]
    metric = records(row.tail(1))[0] if len(row) else {}
    financials = _read(project, 'financials')
    if not financials.empty:
        financials = financials[financials.symbol.eq(code) & pd.to_datetime(financials.announcementDate).lt(pd.Timestamp(asof or date or now()[:10]))]
    def observations(kind):
        return alt.read(project, kind, [code], end_date=asof or date or now()[:10])
    stock_prices = prices[prices.symbol.eq(code)]
    factor_frame = alt.features(project, stock_prices) if len(stock_prices) else pd.DataFrame(columns=['date', 'symbol'])
    if len(stock_prices):
        factor_frame = factor_frame.merge(basic_features(stock_prices), on=['symbol', 'date'], how='left')
        factor_frame = factor_frame.merge(_financial_factors(project, stock_prices[['symbol', 'date']]), on=['symbol', 'date'], how='left')
        factor_frame['factorSource'] = '本地已存行情/公告财务/补充数据计算'
        factor_frame['factorProcessing'] = '原始值；未做截面去极值/中性化/标准化，不是实验处理结果'
    events, seats, institutions = observations('lhb'), observations('seats'), observations('institutions')
    # Institutions retain an explicit detailType; seats are not summed across buy/sell lists.
    detail_frames = [f.assign(detailType=kind) for kind, f in [('seat', seats), ('institution', institutions)] if not f.empty]
    details = pd.concat(detail_frames, ignore_index=True) if detail_frames else seats
    flow = observations('fund_flow')
    rolling = [col for col in factor_frame if col.startswith('fund_') and col not in flow]
    if len(flow) and rolling:
        flow = flow.merge(factor_frame[['date', 'symbol'] + rolling], on=['date', 'symbol'], how='left')
    tables = {'financials':financials, 'factors':factor_frame, 'flow':flow,
              'chips':observations('chips'), 'events':events, 'seats':details}
    for key, frame in tables.items():
        date_column = 'date' if 'date' in frame else 'announcementDate' if 'announcementDate' in frame else None
        if date_column:
            tables[key] = frame.sort_values(date_column,kind='stable').reset_index(drop=True)
    return metric, asof, tables


def panorama(project, code, date=None, notes=''):
    code = symbol(code)
    metric, asof, tables = stock_frames(project,code,date)
    return {'symbol': code, 'name': metric.get('name') or code, 'asOfDate': asof,
            'profile': {key: metric.get(key) for key in ('name', 'industry', 'listingDate', 'delistingDate')},
            'metrics': metric, **{name:_table(name,frame) for name,frame in tables.items()},
            'coverage': catalog(project, code, asof or date), 'notes': notes}


def stock_table(project, code, table, date=None, offset=0, limit=200, full=False):
    if table not in {'financials','factors','flow','chips','events','seats'}:
        raise ValueError('未知个股数据表')
    _, asof, tables = stock_frames(project,code,date)
    frame = tables[table]
    offset, limit = max(0,int(offset)), max(1,min(500,int(limit)))
    page = frame if full else frame.iloc[offset:offset+limit]
    return {'name':table,'columns':list(frame.columns),'rows':records(page),'total':len(frame),
            'offset':0 if full else offset,'limit':len(frame) if full else limit,'asOfDate':asof,
            'fieldLabels':{column:LABELS.get(column,column) for column in frame}}


def dispatch(service, method, params):
    """Main Service may call this before its legacy method branches."""
    methods = {'market.screen', 'market.securities', 'market.overview', 'market.stock', 'market.stock.table', 'market.stock.export', 'stocks.panorama', 'data.catalog', 'market.notes.save'}
    if method not in methods:
        return False, None
    p = params or {}
    store = service.store
    if method == 'market.notes.save':
        value = {'id': symbol(p['symbol']), 'notes': str(p.get('notes', '')), 'updatedAt': now()}
        return True, store.put('stock-note', value)
    project = store.project(p.get('projectId'))
    if method in {'market.stock.table','market.stock.export'}:
        table = stock_table(project,p['symbol'],p['table'],p.get('date'),p.get('offset',0),p.get('limit',200),full=method=='market.stock.export')
        if method == 'market.stock.export':
            return True, service.export_table({'table':table,'name':p.get('name') or f"{symbol(p['symbol'])}_{p['table']}",'format':p['format']})
        return True, table
    if method in {'market.screen', 'market.securities'}:
        return True, screen(project, p, store.list('watchlist'))
    if method == 'market.overview':
        return True, overview(project, p.get('date'))
    if method == 'data.catalog':
        return True, catalog(project)
    note = next((item for item in store.list('stock-note') if item['id'] == symbol(p['symbol'])), {})
    return True, panorama(project, p['symbol'], p.get('date'), note.get('notes', ''))
