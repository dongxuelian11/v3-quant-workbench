"""Observed index series and aligned Qlib performance analysis."""
from pathlib import Path
from .storage import now, read_json, write_json


def collect(project, bs, start, end, query):
    import pandas as pd
    from .data import normalize
    root = Path(project['path']) / 'data' / 'benchmarks'
    root.mkdir(parents=True, exist_ok=True)
    for code in ['SH000300', 'SH000905']:
        path = root / f'{code}.parquet'
        stamp = read_json(path.with_suffix('.json'), {})
        if path.exists() and stamp.get('start', '9999') <= start and stamp.get('end', '') >= end and stamp.get('date') == now()[:10]:
            continue
        frame = query(bs, bs.query_history_k_data_plus, code[:2].lower()+'.'+code[2:],
                      'date,code,open,high,low,close,preclose,volume,amount', start_date=start, end_date=end, frequency='d', adjustflag='3')
        if frame.empty:
            raise ValueError(f'基准 {code} 来源没有返回数据')
        frame = normalize(frame, 'prices')[0]
        if path.exists():
            frame = normalize(pd.concat([pd.read_parquet(path), frame]), 'prices')[0]
        temp = path.with_suffix('.tmp')
        frame.to_parquet(temp, index=False)
        temp.replace(path)
        write_json(path.with_suffix('.json'), {'start': start, 'end': end, 'date': now()[:10]})


def returns(project, name, dates):
    import pandas as pd
    code = 'SH000905' if name == 'csi500' else 'SH000300'
    path = Path(project['path']) / 'data' / 'benchmarks' / f'{code}.parquet'
    if not path.exists():
        raise ValueError('缺少真实基准行情，请先更新指数数据')
    frame = pd.read_parquet(path).set_index('date').sort_index()
    result = (frame.close/pd.to_numeric(frame.preclose,errors='coerce')-1).reindex(dates) if 'preclose' in frame else frame.close.pct_change(fill_method=None).reindex(dates)
    if result.isna().any():
        raise ValueError('基准日期覆盖不足，不以零收益替代')
    return result


def analyze(report):
    from qlib.contrib.evaluate import risk_analysis
    import pandas as pd
    net = report['return'] - report.cost
    benchmark = report.bench
    nav = (1+net).cumprod()
    benchmark_nav = (1+benchmark).cumprod()
    excess = net-benchmark
    risk = risk_analysis(excess, N=252)
    metrics = {str(key): float(value) if pd.notna(value) else None for key, value in risk.iloc[:, 0].items()}
    metrics['tracking_error'] = float(excess.std(ddof=1)*252**.5)
    tables = {'benchmark': pd.DataFrame({'portfolio': nav, 'benchmark': benchmark_nav}),
              'excess': pd.DataFrame({'return': excess, 'cumulative': (1+excess).cumprod()-1}),
              'drawdown': pd.DataFrame({'portfolio': nav/nav.cummax().clip(lower=1)-1, 'benchmark': benchmark_nav/benchmark_nav.cummax().clip(lower=1)-1}),
              'monthly': pd.DataFrame({'portfolio': net, 'benchmark': benchmark}).resample('ME').apply(lambda x: (1+x).prod()-1)}
    for frame in tables.values():
        frame.index.name = 'date'
    return metrics, tables
