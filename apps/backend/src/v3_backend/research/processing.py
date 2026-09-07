"""Cross-sectional preprocessing and observable label/window alignment."""
import numpy as np
import pandas as pd

DEFAULTS = dict(directions={}, winsorize='mad', madScale=3, standardize=True, neutralizeIndustry=False, neutralizeSize=False)


def process(project, values, prices, config=None):
    from sklearn.linear_model import LinearRegression
    from .history import industries
    config = {**DEFAULTS, **(config or {})}
    panels, coverage = [], []
    market = prices.set_index(['date', 'symbol'])
    for date, panel in values.groupby(level=0):
        cross = panel.droplevel(0).copy()
        design = pd.DataFrame(index=cross.index)
        if config['neutralizeIndustry']:
            groups = industries(project, date, cross.index)
            design = pd.get_dummies(groups, dtype=float)
            design.loc[groups.isna(), :] = np.nan
        if config['neutralizeSize']:
            rows = market.reindex(pd.MultiIndex.from_product([[date], cross.index])).droplevel(0)
            if 'floatShares' in rows:
                cap = pd.to_numeric(rows.floatShares, errors='coerce') * pd.to_numeric(rows.get('rawClose', rows.close), errors='coerce')
                basis = '明确流通股本'
            elif 'rawTurn' in rows:
                cap = rows.volume / (pd.to_numeric(rows.rawTurn, errors='coerce')/100) * rows.get('rawClose', rows.close)
                basis = '成交量/换手率估算流通市值'
            else:
                cap = pd.Series(np.nan, index=cross.index)
                basis = '缺少流通市值'
            design['logFloatMarketCap'] = np.log(cap.where(cap > 0)).replace([np.inf, -np.inf], np.nan)
        else:
            basis = None
        for name in cross:
            direction = config['directions'].get(name, 1)
            if direction not in {-1, 1}:
                raise ValueError(f'{name} 因子方向必须为1或-1')
            series = cross[name] * direction
            if config['winsorize'] == 'mad':
                median = series.median()
                mad = (series-median).abs().median()
                series = series.clip(median-float(config['madScale'])*mad, median+float(config['madScale'])*mad) if mad > 0 else series
            elif config['winsorize'] != 'none':
                raise ValueError('未知因子去极值方式')
            if config['neutralizeIndustry'] or config['neutralizeSize']:
                valid = series.notna() & design.notna().all(axis=1)
                if design.shape[1] == 0 or valid.sum() <= design.shape[1]+1:
                    series[:] = np.nan
                else:
                    estimator = LinearRegression().fit(design[valid], series[valid])
                    series.loc[valid] -= estimator.predict(design[valid])
                    series.loc[~valid] = np.nan
            std = series.std(ddof=0)
            if pd.isna(std) or std <= 1e-12:
                series[:] = np.nan
                status = '无区分度或有效覆盖不足'
            else:
                status = '可用'
                if config['standardize']:
                    series = (series-series.mean()) / std
            cross[name] = series
            coverage.append(dict(date=date, factor=name, available=int(series.notna().sum()), total=len(series), status=status, marketCapBasis=basis))
        cross['datetime'] = date
        panels.append(cross.reset_index().set_index(['datetime', 'instrument']))
    return pd.concat(panels).sort_index() if panels else values, pd.DataFrame(coverage)


def label_prices(prices, mode='next_open'):
    column = 'open' if mode == 'next_open' else 'close'
    if mode not in {'next_open', 'close'}:
        raise ValueError('labelMode 必须为 next_open/close')
    market = prices.pivot(index='date', columns='symbol', values=column).sort_index()
    return market.shift(-1) if mode == 'next_open' else market


def windows(calendar, params):
    from qlib.workflow.task.utils import TimeAdjuster
    dates = pd.DatetimeIndex(calendar).sort_values().unique()
    mode = params.get('validation', {}).get('mode', 'single')
    if mode == 'single':
        if all(params.get(f'{part}{edge}') for part in ['train', 'valid', 'test'] for edge in ['Start', 'End']):
            return [{key: params[key] for key in ['trainStart', 'trainEnd', 'validStart', 'validEnd', 'testStart', 'testEnd']}]
        if len(dates) < 20:
            raise ValueError('单次切分交易日不足')
        a, b = int(len(dates)*.7), int(len(dates)*.85)
        return [dict(trainStart=str(dates[0]), trainEnd=str(dates[a-1]), validStart=str(dates[a]), validEnd=str(dates[b-1]), testStart=str(dates[b]), testEnd=str(dates[-1]))]
    if mode != 'rolling':
        raise ValueError('未知验证模式')
    config = {**dict(trainYears=3, validMonths=6, testMonths=1, stepMonths=1), **{k:v for k,v in params.get('validation', {}).items() if k!='mode'}}
    if any(int(config[key]) < 1 for key in ['trainYears', 'validMonths', 'testMonths', 'stepMonths']):
        raise ValueError('滚动窗口长度和步长必须为正整数')
    adjuster = TimeAdjuster(future=False)
    first_test = (dates[0] + pd.DateOffset(years=int(config['trainYears']), months=int(config['validMonths']))).to_period('M').to_timestamp()
    result = []
    while first_test <= dates[-1]:
        valid_start = first_test-pd.DateOffset(months=int(config['validMonths']))
        train_start = valid_start-pd.DateOffset(years=int(config['trainYears']))
        test_end = first_test+pd.DateOffset(months=int(config['testMonths']))-pd.Timedelta(days=1)
        window = {}
        for name, start, end in [('train', train_start, valid_start-pd.Timedelta(days=1)), ('valid', valid_start, first_test-pd.Timedelta(days=1)), ('test', first_test, test_end)]:
            subset = dates[(dates >= start)&(dates <= end)]
            if not len(subset):
                break
            aligned = adjuster.align_seg((str(subset[0]), str(subset[-1])))
            window[name+'Start'], window[name+'End'] = map(str, aligned)
        if len(window) == 6:
            result.append(window)
        first_test += pd.DateOffset(months=int(config['stepMonths']))
    if not result:
        raise ValueError('数据不足以生成滚动窗口')
    return result
