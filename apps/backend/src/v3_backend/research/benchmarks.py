"""Observed index series and aligned Qlib performance analysis."""
from pathlib import Path
from .data import project_data
from .storage import now, read_json, write_json


def import_weights(project, frame):
    """Import complete dated constituent snapshots, with weights in fractions."""
    import pandas as pd
    import numpy as np
    from .data import symbol
    required={'benchmark','symbol','effectiveDate','weight'}
    if not required.issubset(frame):raise ValueError('基准权重需要 benchmark/symbol/effectiveDate/weight')
    frame=frame.copy()
    frame['symbol']=frame.symbol.map(symbol)
    frame['effectiveDate']=pd.to_datetime(frame.effectiveDate,errors='raise').dt.strftime('%Y-%m-%d')
    frame['weight']=pd.to_numeric(frame.weight,errors='raise')
    if frame[list(required)].isna().any(axis=None) or not np.isfinite(frame.weight).all() or (frame.weight<0).any():
        raise ValueError('基准权重及生效日期必须已知且非负')
    if not frame.benchmark.isin(['csi300','csi500']).all():raise ValueError('基准须为 csi300/csi500')
    if frame.duplicated(['benchmark','effectiveDate','symbol']).any():raise ValueError('同一基准快照证券重复')
    if not np.allclose(frame.groupby(['benchmark','effectiveDate']).weight.sum(),1,atol=1e-6,rtol=0):
        raise ValueError('每个基准日期必须提供完整权重且合计为1，不自动归一化残缺快照')
    path=Path(project_data(project)['path'])/'data'/'benchmark_weights.parquet'
    old=pd.read_parquet(path) if path.exists() else frame.iloc[:0]
    keys=set(zip(frame.benchmark,frame.effectiveDate))
    old=old[[key not in keys for key in zip(old.benchmark,old.effectiveDate)]]
    merged=pd.concat([old,frame],ignore_index=True)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp.parquet');merged.to_parquet(temp,index=False);temp.replace(path)
    return len(merged)


def read_weights(project, name):
    import pandas as pd
    path=Path(project_data(project)['path'])/'data'/'benchmark_weights.parquet'
    frame=pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=['benchmark','symbol','effectiveDate','weight'])
    return frame[frame.benchmark.eq(name)].copy()


def collect(project, bs, start, end, query):
    import pandas as pd
    from .data import normalize
    root = Path(project_data(project)['path']) / 'data' / 'benchmarks'
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
    path = Path(project_data(project)['path']) / 'data' / 'benchmarks' / f'{code}.parquet'
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
