"""Source adapters, portable market tables and explicitly dated financial observations."""
from pathlib import Path
import re

from .storage import now, write_json


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
    return frame.drop_duplicates(keys, keep='last').sort_values(keys), kind


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
    return {'imports': summaries, 'warnings': ['导入数据的复权口径和历史修订完整性由来源决定。财务按公告日之后交易日生效。']}


def _bs_rows(result):
    import pandas as pd
    if result.error_code != '0':
        raise ValueError(result.error_msg)
    rows = []
    while result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=result.fields)


def update(project, params, progress):
    import pandas as pd
    start = params.get('startDate') or project.get('startDate')
    end = params.get('endDate') or project.get('endDate') or now()[:10]
    if not start:
        raise ValueError('请指定开始日期')
    source = params.get('source', 'baostock')
    symbols = [symbol(s) for s in project['universe']['symbols']]
    frames, financials = [], []
    if source == 'baostock':
        import baostock as bs
        login = bs.login()
        if login.error_code != '0':
            raise ValueError(login.error_msg)
        try:
            if not symbols:
                universe_source = project['universe'].get('source')
                query = bs.query_hs300_stocks if universe_source == 'csi300' else bs.query_zz500_stocks if universe_source == 'csi500' else (lambda: bs.query_all_stock(day=end)) if universe_source == 'all' else None
                if query is None:
                    raise ValueError('请填写股票代码或选择沪深300/中证500；全市场请导入明确股票列表')
                symbols = [code for code in _bs_rows(query())['code'].map(symbol).tolist() if re.fullmatch(r'(SH6|SZ[03]|BJ[48])\d{5}', code)]
                if not symbols:
                    raise ValueError('来源没有返回股票池，请确认结束日期为交易日')
            for index, code in enumerate(symbols):
                remote = code[:2].lower() + '.' + code[2:]
                frame = _bs_rows(bs.query_history_k_data_plus(remote,
                    'date,code,open,high,low,close,volume,amount,adjustflag,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST',
                    start_date=start, end_date=end, frequency='d', adjustflag='2'))
                if not frame.empty:
                    frame = frame[frame['volume'].ne('') & frame['close'].ne('')]
                    raw = _bs_rows(bs.query_history_k_data_plus(remote, 'date,close', start_date=start, end_date=end, frequency='d', adjustflag='3'))
                    raw_close = pd.to_numeric(raw.set_index('date')['close'], errors='coerce')
                    frame['factor'] = pd.to_numeric(frame['close'], errors='coerce') / frame['date'].map(raw_close)
                    basic = _bs_rows(bs.query_stock_basic(code=remote))
                    if not basic.empty:
                        frame['listingDate'] = basic.iloc[0]['ipoDate']
                    frames.append(frame)
                if params.get('financials'):
                    for year in range(pd.Timestamp(start).year - 1, pd.Timestamp(end).year + 1):
                        for quarter in range(1, 5):
                            for query in [bs.query_profit_data, bs.query_growth_data, bs.query_balance_data, bs.query_cash_flow_data]:
                                result = _bs_rows(query(code=remote, year=year, quarter=quarter))
                                if not result.empty:
                                    financials.append(result)
                progress((index + 1) / len(symbols) * .85, f'已采集 {code}')
        finally:
            bs.logout()
    elif source == 'akshare':
        import akshare as ak
        if not symbols:
            raise ValueError('AKShare 更新需要项目明确股票列表')
        if params.get('financials'):
            raise ValueError('AKShare 财务自动更新尚无统一公告日期契约，请用 BaoStock 或带 announcementDate 的 CSV')
        for index, code in enumerate(symbols):
            frame = ak.stock_zh_a_hist(symbol=code[2:], period='daily', start_date=start.replace('-', ''), end_date=end.replace('-', ''), adjust='qfq')
            raw = ak.stock_zh_a_hist(symbol=code[2:], period='daily', start_date=start.replace('-', ''), end_date=end.replace('-', ''), adjust='')
            raw_close = raw.set_index('日期')['收盘']
            frame['factor'] = frame['收盘'] / frame['日期'].map(raw_close)
            frame['symbol'] = code
            frame['成交量'] = frame['成交量'] * 100
            frames.append(frame)
            progress((index + 1) / len(symbols) * .85, f'已采集 {code}')
    else:
        raise ValueError('未知数据源')
    if not frames:
        raise ValueError('来源未返回行情')
    prices, _ = normalize(pd.concat(frames, ignore_index=True), 'prices')
    merge_table(project, prices, 'prices')
    if financials:
        frame = pd.concat(financials, ignore_index=True).replace('', float('nan'))
        # Different statements share announcement/report keys; coalesce, do not drop other statement fields.
        frame = frame.groupby(['code', 'pubDate', 'statDate'], as_index=False).first()
        normalized, _ = normalize(frame, 'financials')
        merge_table(project, normalized, 'financials')
    metadata = {'source': source, 'updatedAt': now(), 'symbols': symbols, 'adjustment': 'forward-adjusted',
                'warnings': ['免费源历史修订完整性未保证；当前指数名单不是历史成分股，回测存在幸存者偏差。',
                             '前复权行情随来源最新复权基准变化；更新后应重新运行实验。']}
    write_json(Path(project['path']) / 'data' / 'source.json', metadata)
    return metadata


def preview(project):
    import pandas as pd
    datasets, rows = [], []
    for path in (Path(project['path']) / 'data').glob('*.parquet'):
        frame = pd.read_parquet(path)
        date = 'date' if 'date' in frame else 'announcementDate'
        datasets.append(dict(name=path.stem, rows=len(frame), symbols=int(frame.symbol.nunique()),
                             startDate=str(frame[date].min())[:10], endDate=str(frame[date].max())[:10], columns=list(frame.columns)))
        if path.stem == 'prices':
            rows = records(frame.tail(500))
    return {'datasets': datasets, 'rows': rows}


def records(frame):
    import json
    return json.loads(frame.to_json(orient='records', date_format='iso'))
