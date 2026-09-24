"""Source adapters, portable market tables and explicitly dated financial observations."""
from pathlib import Path
import re

from .storage import now, write_json, read_json


def project_data(project):
    """Resolve shared data while preserving project-owned outputs and configuration."""
    if project.get('inputDataRoot'):
        return {**project, 'path': project['inputDataRoot']}
    path = project.get('settings', {}).get('dataPath')
    return {**project, 'path': str(Path(path).parent)} if path else project


def symbol(value):
    value = str(value).strip().upper().replace('.', '')
    if re.fullmatch(r'(SH|SZ|BJ)\d{6}', value):
        return value
    if re.fullmatch(r'\d{6}(SH|SZ|BJ)', value):
        return value[-2:] + value[:6]
    if re.fullmatch(r'\d{6}', value):
        return ('SH' if value.startswith(('5', '6', '9')) else 'BJ' if value.startswith(('4', '8')) else 'SZ') + value
    raise ValueError(f'不支持的股票代码: {value}')


def normalize(frame, kind):
    import pandas as pd
    import numpy as np
    if kind not in {'prices', 'financials', 'auto'}:
        raise ValueError('数据类型必须为 prices/financials/auto')
    frame = frame.rename(columns={'code': 'symbol', 'instrument': 'symbol', '日期': 'date', '股票代码': 'symbol',
                                  '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume',
                                  '成交额': 'amount', 'pubDate': 'announcementDate', 'statDate': 'reportDate'})
    if 'symbol' not in frame:
        raise ValueError('数据必须包含 symbol 股票代码列')
    frame['symbol'] = frame['symbol'].map(symbol)
    if kind == 'auto':
        kind = 'prices' if {'date', 'open', 'close', 'high', 'low', 'volume'}.issubset(frame) else 'financials'
    required = {'symbol', 'date', 'open', 'close', 'high', 'low', 'volume'} if kind == 'prices' else {'symbol', 'announcementDate', 'reportDate'}
    if not required.issubset(frame):
        raise ValueError('缺少必要字段: ' + ', '.join(sorted(required - set(frame.columns))))
    dates = ['date'] if kind == 'prices' else ['announcementDate', 'reportDate']
    for col in dates:
        frame[col] = pd.to_datetime(frame[col], errors='raise').dt.normalize()
        if frame[col].isna().any():
            raise ValueError(f'{col} 不能缺失；财务数据必须提供公告日期')
    if kind == 'prices':
        frame = frame.drop_duplicates(['symbol', 'date'], keep='last')
        for col in ['open', 'close', 'high', 'low', 'volume']:
            frame[col] = pd.to_numeric(frame[col], errors='raise')
        if not np.isfinite(frame[['open', 'close', 'high', 'low', 'volume']]).all().all() or (frame[['open', 'close', 'high', 'low']] <= 0).any().any() or (frame.volume < 0).any():
            raise ValueError('行情含缺失值、非正价格或负成交量')
        if 'factor' in frame:
            frame['factor'] = pd.to_numeric(frame['factor'], errors='raise')
            if not np.isfinite(frame.factor).all() or (frame.factor <= 0).any():
                raise ValueError('复权因子缺失或无效，无法匹配原始价格与复权行情')
        keys = ['symbol', 'date']
    else:
        if (frame.announcementDate < frame.reportDate).any():
            raise ValueError('公告日期不能早于报告期')
        keys = ['symbol', 'reportDate', 'announcementDate']
    frame = frame.drop_duplicates(keys, keep='last') if kind == 'prices' else frame.groupby(keys, as_index=False, dropna=False).last()
    return frame.sort_values(keys), kind


def read_table(project, kind='prices', *, symbols=None, start=None, end=None):
    import pandas as pd
    path = Path(project_data(project)['path']) / 'data' / f'{kind}.parquet'
    partitions = list((path.parent / kind).glob('*.parquet'))
    if symbols is not None or start or end:
        codes = set(map(symbol, symbols)) if symbols is not None else None
        frames = []
        for part in ([path] if path.exists() else []) + partitions:
            if codes is not None and part != path and re.fullmatch(r'(SH|SZ|BJ)\d{6}', part.stem) and part.stem not in codes:
                continue
            filters = [('symbol', 'in', sorted(codes))] if codes is not None else []
            date_key = 'date' if kind == 'prices' else 'announcementDate'
            if start: filters.append((date_key, '>=', pd.Timestamp(start)))
            if end: filters.append((date_key, '<=', pd.Timestamp(end)))
            frames.append(pd.read_parquet(part, filters=filters or None))
        return normalize(pd.concat(frames, ignore_index=True), kind)[0] if frames else pd.DataFrame()
    if partitions:
        frames = ([pd.read_parquet(path)] if path.exists() else []) + [pd.read_parquet(part) for part in partitions]
        return normalize(pd.concat(frames, ignore_index=True), kind)[0]
    if not path.exists():
        raise ValueError(f'尚未导入 {kind} 数据')
    return pd.read_parquet(path)


def merge_table(project, frame, kind, return_all=True, *, conflict_policy="replace", provided_columns=None):
    import pandas as pd
    path = Path(project_data(project)['path']) / 'data' / f'{kind}.parquet'
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == 'prices':
        folder = path.parent / 'prices'
        folder.mkdir(exist_ok=True)
        for code, part in frame.groupby('symbol'):
            target = folder / f'{symbol(code)}.parquet'
            prior = pd.read_parquet(target) if target.exists() else pd.read_parquet(path) if path.exists() else None
            from .data_imports import merge_frames,validate_price_groups
            if provided_columns is not None:validate_price_groups(prior[prior.symbol.eq(code)] if prior is not None else None,part,conflict_policy)
            part = merge_frames(prior[prior.symbol.eq(code)] if prior is not None else None,part,['symbol','date'],conflict_policy,provided_columns)[0]
            part = normalize(part, kind)[0]
            if prior is not None and target.exists() and prior.reset_index(drop=True).equals(part.reset_index(drop=True)):
                continue
            temporary = target.with_suffix('.tmp')
            part.to_parquet(temporary, index=False)
            temporary.replace(target)
        return read_table(project, kind) if return_all else frame
    from .data_imports import merge_frames
    frame=merge_frames(pd.read_parquet(path) if path.exists() else None,frame,['symbol','reportDate','announcementDate'],conflict_policy,provided_columns)[0]
    frame, _ = normalize(frame, kind)
    if path.exists() and pd.read_parquet(path).reset_index(drop=True).equals(frame.reset_index(drop=True)):
        return frame
    temporary = path.with_suffix('.tmp.parquet')
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    return frame


def import_files(project, params, progress):
    from .data_imports import import_files as import_local_files
    return import_local_files(project,params,progress)


def _bs_rows(result):
    import pandas as pd
    if result.error_code != '0':
        raise ValueError(result.error_msg)
    rows = []
    while result.next():
        rows.append(result.get_row_data())
    if result.error_code != '0':
        raise ValueError(result.error_msg)
    return pd.DataFrame(rows, columns=result.fields)


def _bs_query(bs, query, *args, **kwargs):
    """Retry this exact query once, and only after an explicit lost-login response."""
    for attempt in range(2):
        result = query(*args, **kwargs)
        try:
            return _bs_rows(result)
        except ValueError:
            message = str(getattr(result, 'error_msg', '')).lower()
            no_login = getattr(result, 'error_code', '') == '10001001' or any(
                text in message for text in ('未登录', '未登陆', 'not logged in'))
            if attempt or not no_login:
                raise
            login = bs.login()
            if login.error_code != '0':
                raise ValueError('BaoStock 重新登录失败: ' + login.error_msg)


def _bs_prices(bs, remote, start, end):
    import pandas as pd
    frame = _bs_query(bs, bs.query_history_k_data_plus, remote,
        'date,code,open,high,low,close,volume,amount,adjustflag,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST',
        start_date=start, end_date=end, frequency='d', adjustflag='2')
    if frame.empty:
        raise ValueError(f'{remote} 来源未返回行情')
    statuses=frame[['date','code','tradestatus']].rename(columns={'code':'symbol'}).to_dict('records')
    frame = frame[frame['volume'].ne('') & frame['close'].ne('')].copy()
    raw = _bs_query(bs, bs.query_history_k_data_plus, remote, 'date,open,high,low,close,preclose,turn',
                    start_date=start, end_date=end, frequency='d', adjustflag='3')
    raw_close = pd.to_numeric(raw.set_index('date')['close'], errors='coerce')
    frame['factor'] = pd.to_numeric(frame['close'], errors='coerce') / frame['date'].map(raw_close)
    for field in ['open', 'high', 'low', 'close', 'preclose', 'turn']:
        if field in raw:
            frame['raw' + field.capitalize()] = frame.date.map(pd.to_numeric(raw.set_index('date')[field], errors='coerce'))
    basic = _bs_query(bs, bs.query_stock_basic, code=remote)
    if not basic.empty:
        frame['observedName'] = basic.iloc[0].get('code_name', '')
        frame['nameObservedAt'] = now()[:10]
        frame['listingDate'] = basic.iloc[0]['ipoDate']
        frame['delistingDate'] = basic.iloc[0].get('outDate', '')
    frame.attrs['tradingStatus']=statuses
    return frame


def _bs_financials(bs, remote, start, end, quarters=None):
    import pandas as pd
    frames = []
    quarters = quarters if quarters is not None else [(year,quarter) for year in range(pd.Timestamp(start).year-1,pd.Timestamp(end).year+1) for quarter in range(1,5)]
    for year, quarter in quarters:
        for query in [bs.query_profit_data, bs.query_growth_data, bs.query_balance_data, bs.query_cash_flow_data]:
            frame = _bs_query(bs, query, code=remote, year=year, quarter=quarter)
            if not frame.empty:
                frames.append(frame)
    if not frames:
        return pd.DataFrame()
    frame = pd.concat(frames, ignore_index=True).replace('', float('nan'))
    frame = frame.groupby(['code', 'pubDate', 'statDate'], as_index=False).first()
    return normalize(frame, 'financials')[0]


def _financial_update(project, bs, remote, start, end):
    import pandas as pd
    path = Path(project_data(project)['path'])/'data'/'financials'/f'{symbol(remote)}.json'
    stamp = read_json(path,{})
    if stamp.get('downloadDate') == now()[:10] and stamp.get('start','9999') <= start and stamp.get('end','') >= end:
        return
    quarters = None
    if stamp:
        recent = pd.period_range(pd.Timestamp(end)-pd.DateOffset(months=12),pd.Timestamp(end),freq='Q')
        quarters = {(period.year,period.quarter) for period in recent}
        if start < stamp.get('start','9999'):
            quarters |= {(year,quarter) for year in range(pd.Timestamp(start).year-1,pd.Timestamp(stamp['start']).year+1) for quarter in range(1,5)}
        if end > stamp.get('end',''):
            added = pd.period_range(pd.Timestamp(stamp['end']),pd.Timestamp(end),freq='Q')
            quarters |= {(period.year,period.quarter) for period in added}
        quarters = sorted(quarters)
    frame = _bs_financials(bs,remote,start,end,quarters)
    if not frame.empty:
        merge_table(project,frame,'financials')
    write_json(path,dict(start=min(start,stamp.get('start',start)),end=max(end,stamp.get('end',end)),downloadDate=now()[:10],
                         revisionPolicy='新日刷新最近约四季度；更早历史修订不保证追补'))


def _incremental_prices(project, bs, remote, start, end):
    import pandas as pd
    import numpy as np
    code = symbol(remote)
    path = Path(project_data(project)['path']) / 'data' / 'prices' / f'{code}.parquet'
    stamp = read_json(path.with_suffix('.json'), {})
    if path.exists():
        old = pd.read_parquet(path)
        if {'rawOpen', 'rawPreclose', 'rawTurn'}.issubset(old) and str(old.date.min())[:10] <= start:
            if stamp.get('downloadDate') == now()[:10] and stamp.get('startDate', '9999') <= start and stamp.get('endDate', '') >= end:
                return old
            overlap_start = max(start, str(old.date.sort_values().iloc[max(0, len(old) - 5)])[:10])
            fresh = normalize(_bs_prices(bs, remote, overlap_start, end), 'prices')[0]
            common = old.set_index('date').join(fresh.set_index('date'), lsuffix='_old', rsuffix='_new', how='inner')
            ratios = (common.factor_new / common.factor_old).dropna()
            if len(ratios) and np.allclose(ratios, ratios.iloc[-1], rtol=1e-5) and np.allclose(common.rawClose_old, common.rawClose_new, equal_nan=True):
                old = old.copy()
                for field in ['open', 'high', 'low', 'close', 'factor']:
                    old[field] *= ratios.iloc[-1]
                return normalize(pd.concat([old, fresh], ignore_index=True), 'prices')[0]
    return _bs_prices(bs, remote, start, end)


def save_security_names(project, names):
    """Append observed basic metadata; observation dates never backfill history."""
    import pandas as pd
    target = Path(project_data(project)['path'])/'data/securities.parquet'
    target.parent.mkdir(parents=True,exist_ok=True)
    old = pd.read_parquet(target) if target.exists() else pd.DataFrame()
    saved = pd.concat([old,names],ignore_index=True)
    saved['effectiveDate'] = pd.to_datetime(saved.effectiveDate).dt.strftime('%Y-%m-%d')
    saved = saved.drop_duplicates(['symbol','effectiveDate'],keep='last')
    temporary = target.with_name(target.stem + '.' + __import__('uuid').uuid4().hex + '.tmp.parquet')
    try:
        saved.to_parquet(temporary,index=False)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return saved


def ensure_security_name(project, bs, remote):
    """Fill missing display metadata even when daily price data is reused."""
    import pandas as pd
    code = symbol(remote)
    target = Path(project_data(project)['path'])/'data/securities.parquet'
    if target.exists():
        existing = pd.read_parquet(target)
        if ((existing.symbol == code) & existing.name.notna() & existing.name.astype(str).str.strip().ne('')).any():
            return
    basic = _bs_query(bs, bs.query_stock_basic, code=remote)
    if basic.empty or not str(basic.iloc[0].get('code_name','')).strip():
        raise ValueError('股票基本资料没有名称：'+code)
    save_security_names(project,pd.DataFrame([dict(symbol=code,name=basic.iloc[0]['code_name'],effectiveDate=now()[:10],source='BaoStock/query_stock_basic')]))



def save_trading_status(project, frame):
    """Preserve source trading state independently of absent suspended-day prices."""
    import pandas as pd
    frame=frame[['symbol','date','tradestatus']].copy()
    frame['symbol']=frame.symbol.map(symbol)
    frame['date']=pd.to_datetime(frame.date,errors='raise').dt.normalize()
    frame['tradestatus']=pd.to_numeric(frame.tradestatus,errors='raise')
    if frame.date.isna().any() or not frame.tradestatus.isin([0,1]).all():
        raise ValueError('来源交易状态无效')
    frame['source']='BaoStock/query_history_k_data_plus'
    frame['observedAt']=now()
    path=Path(project_data(project)['path'])/'data/trading_status.parquet'
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():frame=pd.concat([pd.read_parquet(path),frame],ignore_index=True)
    frame=frame.drop_duplicates(['symbol','date'],keep='last').sort_values(['symbol','date'])
    temporary=path.with_suffix('.tmp.parquet')
    frame.to_parquet(temporary,index=False);temporary.replace(path)


def _save_updated_prices(project, frame, code):
    statuses=frame.attrs.get('tradingStatus')
    if statuses:
        import pandas as pd
        save_trading_status(project,pd.DataFrame(statuses))
        if frame.empty:return
    if 'observedName' in frame and 'nameObservedAt' in frame:
        names = frame[['observedName','nameObservedAt']].dropna().drop_duplicates().rename(columns={'observedName':'name','nameObservedAt':'effectiveDate'})
        names = names[names.name.ne('')]
        names['symbol'] = code
        names['source'] = 'BaoStock/query_stock_basic'
        if not names.empty:
            save_security_names(project,names)
        frame = frame.drop(columns=['observedName','nameObservedAt'])
    """Never concatenate a new forward-adjustment basis with this stock's old dates."""
    import pandas as pd
    prices, _ = normalize(frame, 'prices')
    if prices.empty:
        raise ValueError(f'{code} 来源未返回有效行情')
    path = Path(project_data(project)['path']) / 'data' / 'prices.parquet'
    if path.exists() or (path.parent / 'prices').exists():
        part = path.parent / 'prices' / f'{code}.parquet'
        existing = pd.read_parquet(part) if part.exists() else pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=['symbol', 'date'])
        old_dates = set(existing.loc[existing.symbol.eq(code), 'date'])
        if old_dates - set(prices.date):
            raise ValueError('来源未完整返回已有历史区间；为避免混合前复权基准，此股行情未写入')
    merge_table(project, prices, 'prices', return_all=False)


def _update_prices(project, params, progress):
    import pandas as pd
    start = params.get('startDate') or project.get('startDate')
    end = params.get('endDate') or project.get('endDate') or now()[:10]
    if not start:
        raise ValueError('请指定开始日期')
    from .app_settings import source_settings
    settings=project.get('settings',{});sources=source_settings(settings)
    source=sources['daily'] if 'dataSources' in settings else params.get('source',sources['daily'])
    if source=='file':raise ValueError('日线来源为已有数据与文件，请导入数据；不会自动联网更新')
    if source not in {'baostock', 'akshare'}:
        raise ValueError('未知数据源')
    symbols = list(dict.fromkeys(symbol(s) for s in project['universe']['symbols']))
    if project['universe']['source'] in {'csi300', 'csi500', 'all'}:
        symbols = []
    existing_path = Path(project_data(project)['path']) / 'data' / 'prices.parquet'
    existing = read_table(project) if existing_path.exists() or (existing_path.parent / 'prices').exists() else pd.DataFrame()
    if not existing.empty:
        relevant = existing[existing.symbol.isin(symbols)] if symbols else existing
        if not relevant.empty:
            start = min(str(start)[:10], str(relevant.date.min())[:10])
            end = max(str(end)[:10], str(relevant.date.max())[:10])
    needs_financials = bool(params.get('financials'))
    needs_actions = bool(params.get('corporateActions'))
    if sources['financials']=='file':
        if needs_financials and not (existing_path.parent/'financials.parquet').exists():raise ValueError('公告财务来源为文件，尚未导入所需财务')
        if needs_actions and not (existing_path.parent/'corporate_actions.parquet').exists():raise ValueError('公司行动来源为文件，尚未导入所需记录')
        needs_financials=False;needs_actions=False
    bs = None
    if source == 'baostock' or needs_financials or needs_actions:
        import baostock as bs
    checkpoint_path = Path(project_data(project)['path']) / 'data' / 'update-progress.json'
    previous = read_json(checkpoint_path, {})
    completed, price_saved = [], []
    financial_rows = 0
    configuration = None
    reused = []
    connection_guard = None
    name_warnings = []

    def fill_name(code):
        if bs is not None:
            try:
                ensure_security_name(project,bs,code[:2].lower()+'.'+code[2:])
            except Exception as exc:
                name_warnings.append(f'{code} 名称资料未补齐：{exc}')

    def persist(status, error=None):
        checkpoint = dict(configuration=configuration, completedSymbols=completed, priceSymbols=price_saved,
                          financialRows=financial_rows, status=status, updatedAt=now())
        write_json(checkpoint_path, checkpoint)
        warnings = ['成员/行业按快照记录日期生效；快照间变化及免费源历史修订完整性未保证。',
                    '行情增量通过重叠区间校正复权基准，不一致时重新补历史；财务新日刷新最近约四季度，更早修订不保证追补。']
        warnings.extend(name_warnings)
        if status != 'completed':
            warnings.append(f'采集未全部完成：已保存行情 {len(price_saved)}/{len(symbols)} 股，完整完成 {len(completed)}/{len(symbols)} 股。')
        if error:
            warnings.append(error)
        if source == 'akshare' and needs_financials:
            warnings.append('行情来自 AKShare，带公告日期的财务来自 BaoStock。')
        if needs_financials and completed and not financial_rows:
            warnings.append('已完成的财务查询未返回记录，请检查财务覆盖。')
        metadata = dict(source=source, updatedAt=now(), symbols=price_saved, requestedSymbols=symbols,
                        completedSymbols=completed, reusedSymbols=reused, status=status,
                        adjustment='forward-adjusted', financialSource='baostock' if needs_financials else None,
                        financialRows=financial_rows, warnings=warnings)
        write_json(Path(project_data(project)['path']) / 'data' / 'source.json', metadata)
        return metadata

    try:
        if bs is not None:
            from .baostock_connection import bounded_connection
            connection_guard = bounded_connection()
            connection_guard.__enter__()
            login = bs.login()
            if login.error_code != '0':
                raise ValueError(login.error_msg)
            from . import history, benchmarks
            universe_source = project['universe'].get('source')
            if universe_source in {'csi300', 'csi500'}:
                history.collect(project, bs, start, end, _bs_query,
                                lambda value, message: progress(value*.1, message), names=[universe_source])
            if source=='baostock':benchmarks.collect(project, bs, start, end, _bs_query)
        if not symbols and source == 'baostock':
            universe_source = project['universe'].get('source')
            if universe_source in {'csi300', 'csi500'}:
                frame = history.read(project, universe_source)
                symbols = sorted(set(frame.symbol))
            elif universe_source == 'all':
                frame = _bs_query(bs, bs.query_stock_basic)
                eligible = frame.type.eq('1') & pd.to_datetime(frame.ipoDate, errors='coerce').le(pd.Timestamp(end))
                out = pd.to_datetime(frame.outDate, errors='coerce')
                symbols = frame.loc[eligible & (out.isna() | out.ge(pd.Timestamp(start))), 'code'].map(symbol).tolist()
            else:
                raise ValueError('请填写股票代码或选择沪深300/中证500/全市场')
            symbols = [code for code in symbols if re.fullmatch(r'(SH6|SZ[03])\d{5}', code)]
        if not symbols:
            raise ValueError('来源没有返回股票池，请填写股票代码或确认结束日期为交易日')
        configuration = dict(source=source, startDate=start, endDate=end, financials=needs_financials, corporateActions=needs_actions,
                             symbols=symbols, downloadDate=now()[:10])
        # Resume only an unfinished same-day batch. A fresh completed batch must refresh its adjustment basis.
        if previous.get('configuration') == configuration and previous.get('status') in {'running', 'failed'} and not existing.empty:
            completed = [code for code in previous.get('completedSymbols', []) if code in set(existing.symbol)]
            price_saved = [code for code in previous.get('priceSymbols', []) if code in set(existing.symbol)]
            financial_rows = previous.get('financialRows', 0)
            if financial_rows and not (Path(project_data(project)['path']) / 'data' / 'financials.parquet').exists():
                completed, financial_rows = [], 0
            reused = list(completed)
        persist('running')
        for index, code in enumerate(symbols):
            if code in completed:
                fill_name(code)
                progress(.1 + (index + 1) / len(symbols) * .85, f'复用已保存 {code}；完整完成 {len(completed)}/{len(symbols)} 股')
                continue
            remote = code[:2].lower() + '.' + code[2:]
            if source == 'baostock':
                frame = _bs_prices(bs,remote,start,end) if params.get('repairGaps') else _incremental_prices(project, bs, remote, start, end)
            else:
                import akshare as ak
                query = dict(symbol=code[2:], period='daily', start_date=start.replace('-', ''), end_date=end.replace('-', ''))
                frame = ak.stock_zh_a_hist(**query, adjust='qfq')
                raw = ak.stock_zh_a_hist(**query, adjust='')
                frame['factor'] = frame['收盘'] / frame['日期'].map(raw.set_index('日期')['收盘'])
                frame['symbol'] = code
                frame['成交量'] = frame['成交量'] * 100
            _save_updated_prices(project, frame, code)
            fill_name(code)
            write_json(Path(project_data(project)['path']) / 'data' / 'prices' / f'{code}.json', dict(startDate=start, endDate=end, downloadDate=now()[:10]))
            if code not in price_saved:
                price_saved.append(code)
            persist('running')
            if needs_financials:
                _financial_update(project, bs, remote, start, end)
                financial_path = Path(project_data(project)['path'])/'data'/'financials.parquet'
                if financial_path.exists():
                    financial_rows += int(pd.read_parquet(financial_path,columns=['symbol']).symbol.eq(code).sum())
            if needs_actions:
                from .corporate_actions import collect
                collect(project,bs,[code],start,end,_bs_query)
            completed.append(code)
            persist('running')
            progress(.1 + (index + 1) / len(symbols) * .85, f'已落盘 {code}；完整完成 {len(completed)}/{len(symbols)} 股')
        settings = project.get('settings', {})
        processing = params.get('factorProcessing', settings.get('factorProcessing', {}))
        portfolio = params.get('portfolio', settings.get('backtest', {}).get('portfolio', {}))
        if bs is not None and (processing.get('neutralizeIndustry') or portfolio.get('industryCap') is not None):
            history.collect(project, bs, start, end, _bs_query,
                            lambda value, message: progress(.95 + value*.05, message), names=['industry'])
        return persist('completed')
    except Exception as exc:
        message = (f'{exc}；已保存行情 {len(price_saved)}/{len(symbols)} 股，完整完成 {len(completed)}/{len(symbols)} 股。重跑同日同区间任务可复用已完成部分。'
                   if configuration is not None else f'{exc}；初始化失败，已有落盘数据和续传记录保留。')
        # A failed initial login/discovery must not erase an existing resumable checkpoint.
        if configuration is not None:
            persist('failed', message)
        raise ValueError(message) from exc
    finally:
        if bs is not None:
            try:
                bs.logout()
            except Exception:
                pass
        if connection_guard is not None:
            connection_guard.__exit__(None, None, None)


def preview(project):
    import pandas as pd
    root=Path(project_data(project)['path'])/'data'
    stamp={'version':3,'universe':project['universe'],'start':project.get('startDate'),'end':project.get('endDate'),
        'files':[(str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in sorted(root.rglob('*')) if p.is_file() and p.suffix in {'.parquet','.json'}]}
    import json
    stamp=json.loads(json.dumps(stamp))
    cache=Path(project['path'])/'.research/cache/data_preview.json'
    saved=read_json(cache,{})
    if saved.get('stamp')==stamp:return saved['result']
    datasets, rows = [], []
    prices=pd.DataFrame(columns=['date','symbol'])
    for kind in ['prices', 'financials']:
        path = Path(project_data(project)['path']) / 'data' / f'{kind}.parquet'
        if not path.exists() and not (path.parent / kind).exists():
            continue
        frame = read_table(project, kind)
        date = 'date' if 'date' in frame else 'announcementDate'
        datasets.append(dict(name=path.stem, rows=len(frame), symbols=int(frame.symbol.nunique()),
                             startDate=str(frame[date].min())[:10], endDate=str(frame[date].max())[:10], columns=list(frame.columns),
                             missingValues=int(frame.drop(columns=['symbol', 'date', 'announcementDate', 'reportDate'], errors='ignore').isna().sum().sum())))
        if path.stem == 'prices':
            prices=frame
            rows = records(frame.tail(500))
    source = read_json(Path(project_data(project)['path']) / 'data' / 'source.json', {})
    warnings = source.get('warnings', [])
    if datasets and not source:
        warnings = ['导入数据的复权口径和历史修订完整性未验证。']
    price_dataset = next((dataset for dataset in datasets if dataset['name'] == 'prices'), None)
    if price_dataset:
        if project['universe'].get('excludeST') and 'isST' not in price_dataset['columns']:
            warnings.append('行情缺少 isST，排除 ST 筛选不可用。')
        if project['universe'].get('minListingDays', 0) and 'listingDate' not in price_dataset['columns']:
            warnings.append('行情缺少 listingDate，最短上市天数筛选不可用。')
        if 'factor' not in price_dataset['columns']:
            warnings.append('行情未提供复权因子，回测按未复权单位解释价格和数量。')
    status_path=Path(project_data(project)['path'])/'data/trading_status.parquet'
    if status_path.exists():
        states=pd.read_parquet(status_path)
        datasets.append(dict(name='trading_status',rows=len(states),symbols=int(states.symbol.nunique()),
            startDate=str(states.date.min())[:10],endDate=str(states.date.max())[:10],columns=list(states.columns),missingValues=0))
        halted=int(pd.to_numeric(states.tradestatus,errors='coerce').eq(0).sum())
        warnings.append(f'另存{halted}条来源停牌事实；没有补造价格或成交量，不计入可用行情行。')
    from .history import coverage
    result={'datasets': datasets, 'rows': rows, 'warnings': warnings, 'history':coverage(project),
            'diagnostics':coverage_diagnostics(project,prices)}
    write_json(cache,{'stamp':stamp,'result':result})
    return result


def coverage_diagnostics(project, prices):
    import pandas as pd
    from .history import expected_rows
    prices=prices.copy();prices['date']=pd.to_datetime(prices.date)
    dates=pd.DatetimeIndex(pd.to_datetime(prices.date).unique())
    for path in (Path(project_data(project)['path'])/'data/benchmarks').glob('*.parquet'):
        dates=dates.union(pd.DatetimeIndex(pd.read_parquet(path,columns=['date']).date))
    if project.get('startDate'):dates=dates[dates>=pd.Timestamp(project['startDate'])]
    if project.get('endDate'):dates=dates[dates<=pd.Timestamp(project['endDate'])]
    query_panel=None
    if project['universe'].get('query'):
        from .market import dated_panel
        query_panel=dated_panel(project,prices)
    index,daily=expected_rows(project,prices,dates.sort_values(),query_panel)
    selected=prices.set_index(['date','symbol']).reindex(index)
    fields=[]
    for field in sorted(set(prices.columns)-{'date','symbol'}):
        available=int(selected[field].notna().sum())
        fields.append(dict(field=field,denominator=len(index),available=available,missing=len(index)-available,
            basis='expected_pool_rows' if daily.empty or daily.denominatorStatus.eq('known').all() else 'partial_observed_pool_rows'))
    known=not daily.empty and daily.denominatorStatus.eq('known').all()
    summary=[dict(dataset='prices',startDate=str(dates.min())[:10] if len(dates) else None,endDate=str(dates.max())[:10] if len(dates) else None,
        sessions=len(dates),expected=len(index) if known else None,available=int(daily.available.sum()) if len(daily) else 0,
        missing=int(daily.missing.sum()) if known else None,denominatorStatus='known' if known else 'partial_or_unavailable',
        calendarBasis='local_benchmark_and_price_sessions',universeSource=project['universe']['source'])]
    status_path=Path(project_data(project)['path'])/'data/trading_status.parquet'
    confirmed=0
    if status_path.exists():
        states=pd.read_parquet(status_path)
        states=states[states.source.eq('BaoStock/query_history_k_data_plus')&pd.to_numeric(states.tradestatus,errors='coerce').eq(0)]
        status_index=pd.MultiIndex.from_arrays([pd.to_datetime(states.date),states.symbol])
        actual_index=pd.MultiIndex.from_arrays([prices.date,prices.symbol])
        confirmed=len(index.intersection(status_index).difference(actual_index))
    summary[0]['confirmedSuspensionMissingRows']=confirmed
    summary[0]['unexplainedMissingRows']=max(0,summary[0]['missing']-confirmed) if summary[0]['missing'] is not None else None
    return dict(summary=summary,daily=records(daily),fields=fields,
        message='分母按项目区间内本地指数/行情交易日与当日池计算；明确成员包含未下载证券。全市场、动态条件池及缺历史成员的分母不完整；缺ST/上市资料另列eligibilityUnknown。没有日历证据的日期不推造交易日。')


def records(frame):
    import json
    return json.loads(frame.to_json(orient='records', date_format='iso'))


def update(project, params, progress):
    if params.get('symbols'):
        project = {**project, 'universe': {**project['universe'], 'source': 'manual', 'symbols': params['symbols']}}
    result = _update_prices(project, params, progress)
    kinds = params.get('alternativeData', [])
    if kinds:
        from .alternative_data import update as update_alternative
        prices = read_table(project)
        codes = params.get('symbols') or sorted(prices.symbol.unique())
        result['alternativeData'] = update_alternative(project, codes, params['startDate'], params.get('endDate') or now()[:10],
            kinds=tuple('fund_flow' if kind == 'flow' else kind for kind in kinds), progress=progress, include_institutions='lhb' in kinds, include_seats='lhb' in kinds)
    return result
