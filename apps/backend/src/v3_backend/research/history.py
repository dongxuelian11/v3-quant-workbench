"""Dated membership and industry observations, never backfilled from current state."""
from pathlib import Path
from .storage import write_json, read_json, now


def snapshot_dates(start, end):
    import pandas as pd
    return sorted({pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), *pd.date_range(start, end, freq='MS')})


def collect(project, bs, start, end, query, progress, names=None):
    import pandas as pd
    from .data import symbol
    root = Path(project['path']) / 'data' / 'history'
    root.mkdir(parents=True, exist_ok=True)
    sources = {'csi300': bs.query_hs300_stocks, 'csi500': bs.query_zz500_stocks, 'industry': bs.query_stock_industry}
    if names is not None:
        sources = {name: sources[name] for name in names}
    dates = snapshot_dates(start, end)
    for index, date in enumerate(dates):
        date_string = date.strftime('%Y-%m-%d')
        for name, function in sources.items():
            path = root / f'{name}_{date_string}.json'
            if path.exists():
                continue
            frame = query(bs, function, date=date_string)
            rows = []
            for row in frame.to_dict('records'):
                effective = row.get('updateDate') or row.get('date')
                if not effective or pd.Timestamp(effective) > date:
                    continue
                rows.append({'symbol': symbol(row['code']), 'effectiveDate': str(effective)[:10], 'industry': row.get('industry')})
            write_json(path, {'source': name, 'queryDate': date_string, 'rows': rows, 'observedAt': now()})
        progress((index + 1) / len(dates), f'历史成员/行业 {date_string}')


def read(project, source):
    import pandas as pd
    root = Path(project['path']) / 'data' / 'history'
    records = []
    for path in root.glob(f'{source}_*.json'):
        for row in read_json(path, {}).get('rows', []):
            records.append(row)
    return pd.DataFrame(records).drop_duplicates() if records else pd.DataFrame(columns=['symbol', 'effectiveDate', 'industry'])


def members(project, date):
    import pandas as pd
    from .data import symbol
    source = project['universe']['source']
    if source == 'manual':
        return set(map(symbol, project['universe']['symbols']))
    imported = Path(project['path']) / 'data' / 'membership.parquet'
    if imported.exists():
        frame = pd.read_parquet(imported)
        return set(frame.loc[(pd.to_datetime(frame.startDate) <= pd.Timestamp(date)) &
            (pd.to_datetime(frame.endDate).isna() | (pd.to_datetime(frame.endDate) >= pd.Timestamp(date))), 'symbol'])
    if source == 'all':
        return None  # The price/listing/delisting filter owns historical listed eligibility.
    frame = read(project, source)
    available = frame[pd.to_datetime(frame.effectiveDate) <= pd.Timestamp(date)]
    if available.empty:
        return set()
    latest = pd.to_datetime(available.effectiveDate).max()
    return set(available.loc[pd.to_datetime(available.effectiveDate).eq(latest), 'symbol'])


def industries(project, date, symbols):
    import pandas as pd
    frame = read(project, 'industry')
    frame = frame[pd.to_datetime(frame.effectiveDate) <= pd.Timestamp(date)]
    if frame.empty:
        return pd.Series(index=symbols, dtype=object)
    return frame.sort_values('effectiveDate').drop_duplicates('symbol', keep='last').set_index('symbol').industry.reindex(symbols)


def import_membership(project, frame):
    import pandas as pd
    from .data import symbol
    if not {'symbol', 'startDate', 'endDate'}.issubset(frame):
        raise ValueError('历史成员需要 symbol/startDate/endDate 列')
    frame = frame.copy()
    frame['symbol'] = frame.symbol.map(symbol)
    frame['startDate'] = pd.to_datetime(frame.startDate, errors='raise')
    frame['endDate'] = pd.to_datetime(frame.endDate, errors='raise')
    if frame.startDate.isna().any() or (frame.endDate < frame.startDate).any():
        raise ValueError('成员生效区间无效')
    path = Path(project['path']) / 'data' / 'membership.parquet'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp.parquet')
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    return len(frame)


def import_industry(project, frame):
    import pandas as pd
    from .data import symbol
    frame = frame.rename(columns={'startDate':'effectiveDate'})
    if not {'symbol','industry','effectiveDate'}.issubset(frame):
        raise ValueError('历史行业需要 symbol/industry/effectiveDate')
    frame = frame[['symbol','industry','effectiveDate']].copy()
    frame['symbol'] = frame.symbol.map(symbol)
    frame['effectiveDate'] = pd.to_datetime(frame.effectiveDate,errors='raise').dt.strftime('%Y-%m-%d')
    if frame.isna().any().any():
        raise ValueError('行业或生效日期缺失')
    path = Path(project['path'])/'data/history/industry_import.json'
    existing = read_json(path,{}).get('rows',[])
    rows = pd.concat([pd.DataFrame(existing),frame]).drop_duplicates(['symbol','effectiveDate'],keep='last').to_dict('records')
    write_json(path,{'source':'import','rows':rows,'observedAt':now()})
    return len(frame)


def coverage(project):
    result = []
    for source in ['csi300','csi500','industry']:
        frame = read(project,source)
        result.append(dict(source=source,rows=len(frame),symbols=int(frame.symbol.nunique()),
                           startDate=str(frame.effectiveDate.min())[:10] if len(frame) else None,
                           endDate=str(frame.effectiveDate.max())[:10] if len(frame) else None))
    return result
