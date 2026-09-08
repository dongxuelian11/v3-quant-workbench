"""Source adapters, portable market tables and explicitly dated financial observations."""
from pathlib import Path
import re

from .storage import now, write_json, read_json


def project_data(project):
    """Resolve shared data while preserving project-owned outputs and configuration."""
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


def read_table(project, kind='prices'):
    import pandas as pd
    path = Path(project_data(project)['path']) / 'data' / f'{kind}.parquet'
    partitions = list((path.parent / kind).glob('*.parquet'))
    if partitions:
        frames = ([pd.read_parquet(path)] if path.exists() else []) + [pd.read_parquet(part) for part in partitions]
        return normalize(pd.concat(frames, ignore_index=True), kind)[0]
    if not path.exists():
        raise ValueError(f'尚未导入 {kind} 数据')
    return pd.read_parquet(path)


def merge_table(project, frame, kind, return_all=True):
    import pandas as pd
    path = Path(project_data(project)['path']) / 'data' / f'{kind}.parquet'
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == 'prices':
        folder = path.parent / 'prices'
        folder.mkdir(exist_ok=True)
        for code, part in frame.groupby('symbol'):
            target = folder / f'{symbol(code)}.parquet'
            prior = pd.read_parquet(target) if target.exists() else pd.read_parquet(path) if path.exists() else None
            if prior is not None:
                part = pd.concat([prior[prior.symbol.eq(code)], part], ignore_index=True)
            part = normalize(part, kind)[0]
            if prior is not None and target.exists() and prior.reset_index(drop=True).equals(part.reset_index(drop=True)):
                continue
            temporary = target.with_suffix('.tmp')
            part.to_parquet(temporary, index=False)
            temporary.replace(target)
        return read_table(project, kind) if return_all else frame
    if path.exists():
        frame = pd.concat([pd.read_parquet(path), frame], ignore_index=True)
    frame, _ = normalize(frame, kind)
    if path.exists() and pd.read_parquet(path).reset_index(drop=True).equals(frame.reset_index(drop=True)):
        return frame
    temporary = path.with_suffix('.tmp.parquet')
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    return frame


def import_files(project, params, progress):
    import pandas as pd
    files = params.get('files', [])
    if not files:
        raise ValueError('请选择 CSV 或 Parquet 文件')
    summaries = []
    for index, file in enumerate(files):
        path = Path(file)
        if path.suffix.lower() == '.parquet':
            frame = pd.read_parquet(path)
        elif path.suffix.lower() == '.csv':
            frame = pd.read_csv(path, dtype={'symbol': str, 'code': str, '股票代码': str})
        else:
            raise ValueError('只支持 CSV/Parquet')
        frame = frame.rename(columns=params.get('mapping', params.get('fieldMapping', {})))
        dataset = params.get('dataset', params.get('kind', 'auto'))
        if dataset in {'flow', 'fund_flow', 'chips', 'lhb'}:
            from .alternative_data import import_frame
            count = import_frame(project, 'fund_flow' if dataset == 'flow' else dataset, frame)
            summaries.append({'file': str(path), 'kind': dataset, 'result': count})
            continue
        if 'industry' in frame and 'symbol' in frame and ('effectiveDate' in frame or 'startDate' in frame):
            from .history import import_industry
            count = import_industry(project,frame)
            summaries.append({'file':str(path),'kind':'industry','importedRows':count,'totalRows':count})
            continue
        if {'symbol', 'startDate', 'endDate'}.issubset(frame):
            from .history import import_membership
            count = import_membership(project, frame)
            summaries.append({'file': str(path), 'kind': 'membership', 'importedRows': count, 'totalRows': count})
            continue
        frame, kind = normalize(frame, dataset)
        saved = merge_table(project, frame, kind)
        summaries.append({'file': str(path), 'kind': kind, 'importedRows': len(frame), 'totalRows': len(saved)})
        progress((index + 1) / len(files) * 0.9, f'已导入 {path.name}')
    warnings = ['导入数据的复权口径和历史修订完整性由来源决定。财务按公告日之后交易日生效。']
    old_source = read_json(Path(project_data(project)['path']) / 'data' / 'source.json', {})
    write_json(Path(project_data(project)['path']) / 'data' / 'source.json', {'source': 'import', 'updatedAt': now(), 'imports': summaries,
        'warnings': list(dict.fromkeys(old_source.get('warnings', []) + warnings))})
    return {'imports': summaries, 'warnings': warnings}


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


def _save_updated_prices(project, frame, code):
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
    source = params.get('source', 'baostock')
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
    bs = None
    if source == 'baostock' or needs_financials:
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
            benchmarks.collect(project, bs, start, end, _bs_query)
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
        configuration = dict(source=source, startDate=start, endDate=end, financials=needs_financials,
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
                frame = _incremental_prices(project, bs, remote, start, end)
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
    datasets, rows = [], []
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
    from .history import coverage
    return {'datasets': datasets, 'rows': rows, 'warnings': warnings, 'history':coverage(project)}


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
