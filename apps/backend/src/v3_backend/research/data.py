"""Source adapters, portable market tables and explicitly dated financial observations."""
from pathlib import Path
import re

from .storage import now, write_json, read_json


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
    path = Path(project['path']) / 'data' / f'{kind}.parquet'
    if not path.exists():
        raise ValueError(f'尚未导入 {kind} 数据')
    return pd.read_parquet(path)


def merge_table(project, frame, kind):
    import pandas as pd
    path = Path(project['path']) / 'data' / f'{kind}.parquet'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        frame = pd.concat([pd.read_parquet(path), frame], ignore_index=True)
    frame, _ = normalize(frame, kind)
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
        frame, kind = normalize(frame, params.get('kind', 'auto'))
        saved = merge_table(project, frame, kind)
        summaries.append({'file': str(path), 'kind': kind, 'importedRows': len(frame), 'totalRows': len(saved)})
        progress((index + 1) / len(files) * 0.9, f'已导入 {path.name}')
    warnings = ['导入数据的复权口径和历史修订完整性由来源决定。财务按公告日之后交易日生效。']
    old_source = read_json(Path(project['path']) / 'data' / 'source.json', {})
    write_json(Path(project['path']) / 'data' / 'source.json', {'source': 'import', 'updatedAt': now(), 'imports': summaries,
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
    raw = _bs_query(bs, bs.query_history_k_data_plus, remote, 'date,close',
                    start_date=start, end_date=end, frequency='d', adjustflag='3')
    raw_close = pd.to_numeric(raw.set_index('date')['close'], errors='coerce')
    frame['factor'] = pd.to_numeric(frame['close'], errors='coerce') / frame['date'].map(raw_close)
    basic = _bs_query(bs, bs.query_stock_basic, code=remote)
    if not basic.empty:
        frame['listingDate'] = basic.iloc[0]['ipoDate']
    return frame


def _bs_financials(bs, remote, start, end):
    import pandas as pd
    frames = []
    for year in range(pd.Timestamp(start).year - 1, pd.Timestamp(end).year + 1):
        for quarter in range(1, 5):
            for query in [bs.query_profit_data, bs.query_growth_data, bs.query_balance_data, bs.query_cash_flow_data]:
                frame = _bs_query(bs, query, code=remote, year=year, quarter=quarter)
                if not frame.empty:
                    frames.append(frame)
    if not frames:
        return pd.DataFrame()
    frame = pd.concat(frames, ignore_index=True).replace('', float('nan'))
    frame = frame.groupby(['code', 'pubDate', 'statDate'], as_index=False).first()
    return normalize(frame, 'financials')[0]


def _save_updated_prices(project, frame, code):
    """Never concatenate a new forward-adjustment basis with this stock's old dates."""
    import pandas as pd
    prices, _ = normalize(frame, 'prices')
    if prices.empty:
        raise ValueError(f'{code} 来源未返回有效行情')
    path = Path(project['path']) / 'data' / 'prices.parquet'
    if path.exists():
        existing = pd.read_parquet(path)
        old_dates = set(existing.loc[existing.symbol.eq(code), 'date'])
        if old_dates - set(prices.date):
            raise ValueError('来源未完整返回已有历史区间；为避免混合前复权基准，此股行情未写入')
    merge_table(project, prices, 'prices')


def update(project, params, progress):
    import pandas as pd
    start = params.get('startDate') or project.get('startDate')
    end = params.get('endDate') or project.get('endDate') or now()[:10]
    if not start:
        raise ValueError('请指定开始日期')
    source = params.get('source', 'baostock')
    if source not in {'baostock', 'akshare'}:
        raise ValueError('未知数据源')
    symbols = list(dict.fromkeys(symbol(s) for s in project['universe']['symbols']))
    existing_path = Path(project['path']) / 'data' / 'prices.parquet'
    existing = pd.read_parquet(existing_path) if existing_path.exists() else pd.DataFrame()
    if not existing.empty:
        relevant = existing[existing.symbol.isin(symbols)] if symbols else existing
        if not relevant.empty:
            start = min(str(start)[:10], str(relevant.date.min())[:10])
            end = max(str(end)[:10], str(relevant.date.max())[:10])
    needs_financials = bool(params.get('financials'))
    bs = None
    if source == 'baostock' or needs_financials:
        import baostock as bs
    checkpoint_path = Path(project['path']) / 'data' / 'update-progress.json'
    previous = read_json(checkpoint_path, {})
    completed, price_saved = [], []
    financial_rows = 0
    configuration = None
    reused = []

    def persist(status, error=None):
        checkpoint = dict(configuration=configuration, completedSymbols=completed, priceSymbols=price_saved,
                          financialRows=financial_rows, status=status, updatedAt=now())
        write_json(checkpoint_path, checkpoint)
        warnings = ['免费源历史修订完整性未保证；当前指数名单不是历史成分股，回测存在幸存者偏差。',
                    '前复权更新覆盖该股票全部已存日期；更新后应重新运行实验。']
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
        write_json(Path(project['path']) / 'data' / 'source.json', metadata)
        return metadata

    try:
        if bs is not None:
            login = bs.login()
            if login.error_code != '0':
                raise ValueError(login.error_msg)
        if not symbols and source == 'baostock':
            universe_source = project['universe'].get('source')
            query = bs.query_hs300_stocks if universe_source == 'csi300' else bs.query_zz500_stocks if universe_source == 'csi500' else bs.query_all_stock if universe_source == 'all' else None
            if query is None:
                raise ValueError('请填写股票代码或选择沪深300/中证500/全市场')
            frame = _bs_query(bs, query, **({'day': end} if universe_source == 'all' else {}))
            symbols = [code for code in frame['code'].map(symbol) if re.fullmatch(r'(SH6|SZ[03]|BJ[48])\d{5}', code)]
        if not symbols:
            raise ValueError('来源没有返回股票池，请填写股票代码或确认结束日期为交易日')
        configuration = dict(source=source, startDate=start, endDate=end, financials=needs_financials,
                             symbols=symbols, downloadDate=now()[:10])
        # Resume only an unfinished same-day batch. A fresh completed batch must refresh its adjustment basis.
        if previous.get('configuration') == configuration and previous.get('status') in {'running', 'failed'} and not existing.empty:
            completed = [code for code in previous.get('completedSymbols', []) if code in set(existing.symbol)]
            price_saved = [code for code in previous.get('priceSymbols', []) if code in set(existing.symbol)]
            financial_rows = previous.get('financialRows', 0)
            if financial_rows and not (Path(project['path']) / 'data' / 'financials.parquet').exists():
                completed, financial_rows = [], 0
            reused = list(completed)
        persist('running')
        for index, code in enumerate(symbols):
            if code in completed:
                progress((index + 1) / len(symbols) * .95, f'复用已保存 {code}；完整完成 {len(completed)}/{len(symbols)} 股')
                continue
            remote = code[:2].lower() + '.' + code[2:]
            if source == 'baostock':
                frame = _bs_prices(bs, remote, start, end)
            else:
                import akshare as ak
                query = dict(symbol=code[2:], period='daily', start_date=start.replace('-', ''), end_date=end.replace('-', ''))
                frame = ak.stock_zh_a_hist(**query, adjust='qfq')
                raw = ak.stock_zh_a_hist(**query, adjust='')
                frame['factor'] = frame['收盘'] / frame['日期'].map(raw.set_index('日期')['收盘'])
                frame['symbol'] = code
                frame['成交量'] = frame['成交量'] * 100
            _save_updated_prices(project, frame, code)
            if code not in price_saved:
                price_saved.append(code)
            persist('running')
            if needs_financials:
                financial = _bs_financials(bs, remote, start, end)
                if not financial.empty:
                    merge_table(project, financial, 'financials')
                    financial_rows += len(financial)
            completed.append(code)
            persist('running')
            progress((index + 1) / len(symbols) * .95, f'已落盘 {code}；完整完成 {len(completed)}/{len(symbols)} 股')
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


def preview(project):
    import pandas as pd
    datasets, rows = [], []
    for path in (Path(project['path']) / 'data').glob('*.parquet'):
        frame = pd.read_parquet(path)
        date = 'date' if 'date' in frame else 'announcementDate'
        datasets.append(dict(name=path.stem, rows=len(frame), symbols=int(frame.symbol.nunique()),
                             startDate=str(frame[date].min())[:10], endDate=str(frame[date].max())[:10], columns=list(frame.columns),
                             missingValues=int(frame.drop(columns=['symbol', 'date', 'announcementDate', 'reportDate'], errors='ignore').isna().sum().sum())))
        if path.stem == 'prices':
            rows = records(frame.tail(500))
    source = read_json(Path(project['path']) / 'data' / 'source.json', {})
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
    return {'datasets': datasets, 'rows': rows, 'warnings': warnings}


def records(frame):
    import json
    return json.loads(frame.to_json(orient='records', date_format='iso'))
