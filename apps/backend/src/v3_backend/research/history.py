"""Dated membership and industry observations, never backfilled from current state."""
from pathlib import Path
from .data import project_data
from .storage import write_json, read_json, now, identifier


def membership_frame(project):
    """Only an explicit pool/version can replace the configured universe."""
    import pandas as pd
    ref = project['universe'].get('membershipRef')
    if not ref:
        return None
    for key in ('poolId', 'version'):
        if not isinstance(ref.get(key), str) or not ref[key] or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in ref[key]):
            raise ValueError('历史成员引用无效')
    root = Path(project.get('inputDataRoot') or project['path']) / 'data' / 'memberships' / ref['poolId'] / ref['version']
    meta = read_json(root / 'source.json', {})
    if any(meta.get(k) != ref.get(k) for k in ('poolId', 'version', 'source')):
        raise ValueError('历史成员版本不可用，请明确选择股票池成员记录')
    return pd.read_parquet(root / 'members.parquet')


def snapshot_dates(start, end):
    import pandas as pd
    return sorted({pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), *pd.date_range(start, end, freq='MS')})


def collect(project, bs, start, end, query, progress, names=None):
    import pandas as pd
    from .data import symbol
    root = Path(project_data(project)['path']) / 'data' / 'history'
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
    root = Path(project_data(project)['path']) / 'data' / 'history'
    records = []
    for path in root.glob(f'{source}_*.json'):
        if path.name == 'industry_import.json' and not project.get('inputDataRoot') and root != Path(project['path']) / 'data' / 'history':
            continue  # A shared legacy import has no project ownership.
        for row in read_json(path, {}).get('rows', []):
            records.append(row)
    local = Path(project['path']) / 'data' / 'history' / 'industry_import.json'
    if source == 'industry' and not project.get('inputDataRoot') and local.parent != root:
        records.extend(read_json(local, {}).get('rows', []))
    return pd.DataFrame(records).drop_duplicates() if records else pd.DataFrame(columns=['symbol', 'effectiveDate', 'industry'])


def members(project, date, query_panel=None):
    import pandas as pd
    from .data import symbol
    query = project['universe'].get('query')
    if query:
        from .market import dated_panel, filter_frame
        panel = dated_panel(project) if query_panel is None else query_panel
        return set(filter_frame(panel[panel.date.eq(pd.Timestamp(date))],query).symbol)
    source = project['universe']['source']
    frame = membership_frame(project)
    if frame is not None:
        return set(frame.loc[(pd.to_datetime(frame.startDate) <= pd.Timestamp(date)) &
            (pd.to_datetime(frame.endDate).isna() | (pd.to_datetime(frame.endDate) >= pd.Timestamp(date))), 'symbol'])
    if source == 'manual':
        return set(map(symbol, project['universe']['symbols']))
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


def import_membership(project, frame, pool_id=None, source='import'):
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
    pool_id = pool_id or ('pool-' + identifier())
    if not isinstance(pool_id, str) or not pool_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in pool_id):
        raise ValueError('股票池标识无效')
    ref = dict(poolId=pool_id, version=identifier(), source=source)
    path = Path(project['path']) / 'data' / 'memberships' / pool_id / ref['version'] / 'members.parquet'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp.parquet')
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    write_json(path.parent / 'source.json', {**ref, 'projectId': project.get('id'), 'observedAt': now()})
    project['universe']['membershipRef'] = ref
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
    legacy = Path(project_data(project)['path']) / 'data' / 'membership.parquet'
    if legacy.exists() and not project['universe'].get('membershipRef'):
        result.append(dict(source='legacy_membership', status='unclassified', message='旧成员文件未标明股票池，保留原文件；请明确归类后导入'))
    return result


def expected_rows(project, prices, dates, query_panel=None):
    """Dated pool denominator independent of whether a selected symbol was downloaded.

    All-market and field queries cannot establish absent securities from price files;
    those denominators stay explicitly partial instead of reporting 100% coverage.
    """
    import pandas as pd
    from .data import symbol
    universe=project['universe'];source=universe['source'];query=universe.get('query')
    membership=membership_frame(project)
    snapshots=read(project,source) if source not in {'manual','all'} and membership is None else None
    if snapshots is not None:snapshots['effectiveDate']=pd.to_datetime(snapshots.effectiveDate)
    panel=prices.copy();panel['date']=pd.to_datetime(panel.date)
    lifetimes={}
    for code,part in panel.groupby('symbol'):
        lifetimes[code]={}
        for field in ('listingDate','delistingDate'):
            values=pd.to_datetime(part[field],errors='coerce').dropna().unique() if field in part else []
            if len(values)==1:lifetimes[code][field]=pd.Timestamp(values[0])
    by_date={d:g.set_index('symbol') for d,g in panel.groupby('date')}
    tuples=[];rows=[]
    for date in pd.DatetimeIndex(dates):
        observed=by_date.get(date,pd.DataFrame())
        status='known';basis='dated_membership'
        if query:
            allowed=members(project,date,query_panel);status='partial_query_inputs';basis='observed_query_matches'
        elif source=='manual' and membership is None:
            if universe.get('symbols'):allowed=set(map(symbol,universe['symbols']));basis='manual_symbols'
            else:allowed=set(observed.index);basis='observed_imported_symbols';status='partial_unspecified_manual_pool'
        elif membership is not None:
            allowed=set(membership.loc[pd.to_datetime(membership.startDate).le(date)&(pd.to_datetime(membership.endDate).isna()|pd.to_datetime(membership.endDate).ge(date)),'symbol'])
        elif snapshots is not None:
            known=snapshots[snapshots.effectiveDate.le(date)]
            allowed=set(known.loc[known.effectiveDate.eq(known.effectiveDate.max()),'symbol'])
            if known.empty:status='missing_membership'
        else:allowed=set(observed.index);status='partial_observed_market';basis='observed_market_symbols'
        unknown=0;eligible=[]
        for code in sorted(allowed):
            row=observed.loc[code] if code in observed.index else pd.Series(dtype=object)
            listed=pd.to_datetime(row.get('listingDate',lifetimes.get(code,{}).get('listingDate')),errors='coerce')
            delisted=pd.to_datetime(row.get('delistingDate',lifetimes.get(code,{}).get('delistingDate')),errors='coerce')
            if pd.notna(listed) and date<listed or pd.notna(delisted) and date>=delisted:continue
            if universe.get('excludeST'):
                st=pd.to_numeric(row.get('isST'),errors='coerce')
                if pd.isna(st):unknown+=1
                elif st!=0:continue
            if universe.get('minListingDays',0):
                if pd.isna(listed):unknown+=1
                elif (date-listed).days<int(universe['minListingDays']):continue
            eligible.append(code)
        count=len(eligible);available=sum(s in observed.index for s in eligible)
        tuples.extend((date,s) for s in eligible)
        rows.append(dict(date=date,expected=count if status=='known' else None,observedPool=count,available=available,
            missing=count-available if status=='known' else None,eligibilityUnknown=unknown,
            denominatorStatus=status,denominator=basis,undownloadedIncluded=status=='known'))
    return pd.MultiIndex.from_tuples(tuples,names=['datetime','instrument']),pd.DataFrame(rows)
