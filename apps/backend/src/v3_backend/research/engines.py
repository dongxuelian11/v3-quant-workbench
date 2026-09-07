"""Thin adapters to Qlib, Alphalens, sklearn and Optuna; no local backtest engine."""
from pathlib import Path
import ast
import re

from .data import read_table, records
from .storage import write_json, read_json

FINANCIAL = {'roe': 'roeAvg', 'growth_profit': 'YOYNI', 'growth_revenue': 'YOYRevenue', 'profit_margin': 'npMargin', 'leverage': 'liabilityToAsset'}
EXTRA = {'momentum20': '$close/Ref($close,20)-1', 'volatility20': 'Std($close/Ref($close,1)-1,20)',
         'volume_ratio': '$volume/Mean($volume,20)', 'earnings_yield': '1/$pettm', 'book_yield': '1/$pbmrq'}
NAMES = {'momentum20': '20日动量', 'volatility20': '20日波动率', 'volume_ratio': '相对成交量',
         'earnings_yield': '盈利收益率', 'book_yield': '账面市值比', 'roe': '净资产收益率',
         'growth_profit': '净利润增长率', 'growth_revenue': '营业收入增长率', 'profit_margin': '净利率', 'leverage': '资产负债率'}


def factor_catalog():
    from qlib.contrib.data.loader import Alpha158DL
    expressions, names = Alpha158DL.get_feature_config()
    result = [dict(id=name, name=name, family='Alpha158', description='Qlib Alpha158', expression=expr) for expr, name in zip(expressions, names)]
    result.extend(dict(id=key, name=NAMES[key], family='量价/估值', description='Qlib 表达式', expression=expr) for key, expr in EXTRA.items())
    result.extend(dict(id=key, name=NAMES[key], family='财务', description='公告后交易日生效的季度财务', expression=f'P($${value.lower()}_q)') for key, value in FINANCIAL.items())
    for item in result:
        if item['id'] == 'growth_revenue':
            item['description'] = '需要导入带公告日期的YOYRevenue；当前BaoStock适配未提供收入同比，未从MBRevenue推算'
        elif item['id'] == 'profit_margin':
            item['description'] = '公告后交易日生效的季度净利率；BaoStock npMargin，兼容导入netProfitMargin'
    return result


def validate_expression(expression):
    if not isinstance(expression, str) or len(expression) > 2000:
        raise ValueError('因子表达式无效或过长')
    substituted = re.sub(r'\${1,2}[A-Za-z_][A-Za-z0-9_]*', 'field', expression)
    tree = ast.parse(substituted, mode='eval')
    allowed = {'Ref', 'Mean', 'Std', 'Sum', 'Max', 'Min', 'Med', 'Mad', 'Rank', 'Quantile', 'Count', 'Slope', 'Rsquare', 'Resi', 'Corr', 'Cov', 'Abs', 'Log', 'Sign', 'Power', 'If', 'Greater', 'Less', 'And', 'Or', 'Not', 'Delta', 'WMA', 'EMA', 'P'}
    nodes = (ast.Expression, ast.Call, ast.Name, ast.Load, ast.Constant, ast.BinOp, ast.UnaryOp,
             ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Compare,
             ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq)
    for node in ast.walk(tree):
        if not isinstance(node, nodes):
            raise ValueError('表达式只允许 Qlib 数学运算和白名单函数')
        if isinstance(node, ast.Name) and node.id not in allowed | {'field'}:
            raise ValueError(f'未知算子 {node.id}')
        if isinstance(node, ast.Constant) and (not isinstance(node.value, (int, float)) or abs(node.value) > 1e8):
            raise ValueError('表达式常量无效')
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in allowed or node.keywords:
                raise ValueError('未知算子')
            if node.func.id == 'Ref' and (len(node.args) != 2 or not isinstance(node.args[1], ast.Constant) or not isinstance(node.args[1].value, int) or node.args[1].value <= 0):
                raise ValueError('自定义因子 Ref 只允许正整数历史窗口，禁止未来数据')
    return expression


def prepare(project, output, progress):
    import pandas as pd
    import qlib
    from .vendor.dump_bin import DumpDataAll
    from .vendor.dump_pit import DumpPitData
    prices = read_table(project)
    chosen = project['universe']['symbols']
    if chosen and project['universe']['source'] == 'manual':
        from .data import symbol
        prices = prices[prices.symbol.isin([symbol(x) for x in chosen])].copy()
    if prices.empty:
        raise ValueError('股票池没有行情数据')
    import time
    data_root = Path(project['path']) / 'data'
    cache_root = Path(project['path']) / '.research' / 'cache'
    signature = {'version': 3, 'files': [(str(path.relative_to(data_root)), path.stat().st_mtime_ns, path.stat().st_size) for path in sorted(data_root.rglob('*.parquet'))], 'symbols': sorted(prices.symbol.unique())}
    signature = __import__('json').loads(__import__('json').dumps(signature))
    cache_state = read_json(cache_root / 'qlib.json', {})
    if cache_state.get('signature') == signature:
        cache = Path(project['path']) / cache_state['path']
        if cache.exists():
            qlib.init(provider_uri=str(cache), region='cn', expression_cache=None, dataset_cache=None, kernels=1)
            progress(.25, '复用项目Qlib缓存')
            return prices
    build = cache_root / str(time.time_ns())
    csv = build / 'input'
    cache = build / 'qlib'
    csv.mkdir(parents=True, exist_ok=True)
    numeric = ['open', 'high', 'low', 'close', 'volume', 'amount', 'peTTM', 'pbMRQ', 'isST', 'tradestatus']
    for code, frame in prices.groupby('symbol'):
        frame = frame.copy()
        for col in numeric:
            if col in frame:
                frame[col.lower()] = pd.to_numeric(frame[col], errors='coerce')
        # Keep supplied adjustment factors; absent factors imply already-adjusted prices and are disclosed.
        frame['factor'] = pd.to_numeric(frame['factor'], errors='raise') if 'factor' in frame else 1.0
        frame['change'] = frame.close.pct_change(fill_method=None)
        from .rules import limits
        halted = frame['open'].isna()
        if 'tradestatus' in frame:
            halted = halted | frame['tradestatus'].ne(1)
        raw_open = pd.to_numeric(frame['rawOpen'], errors='coerce') if 'rawOpen' in frame else frame.open/frame.factor
        preclose = pd.to_numeric(frame['rawPreclose'], errors='coerce') if 'rawPreclose' in frame else (frame.close/frame.factor).shift(1)
        calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
        buyblocked, sellblocked = [], []
        for offset, (_, row) in enumerate(frame.iterrows()):
            listed = pd.to_datetime(row.get('listingDate'), errors='coerce')
            session = int(calendar.searchsorted(row.date) - calendar.searchsorted(listed)) if pd.notna(listed) and listed >= calendar[0] else None
            reference = preclose.iloc[offset]
            st = row.get('isST', 0)
            lower, upper, reason = limits(code, row.date, reference, pd.notna(st) and float(st) != 0, listed, session) if pd.notna(reference) else (None, None, '缺参考昨收')
            buyblocked.append(bool(halted.iloc[offset]) or reason is not None or upper is not None and raw_open.iloc[offset] >= upper-1e-8)
            sellblocked.append(bool(halted.iloc[offset]) or reason is not None or lower is not None and raw_open.iloc[offset] <= lower+1e-8)
        frame['buyblocked'], frame['sellblocked'] = buyblocked, sellblocked
        frame['knownvolume'] = frame['volume'].shift(1)/frame['factor']
        frame['volume'] = frame['volume'] / frame['factor']
        frame['vwap'] = frame['amount'] / frame.volume if 'amount' in frame else float('nan')
        frame.to_csv(csv / f'{code}.csv', index=False)
    fields = sorted({c.lower() for c in numeric if c in prices} | {'factor', 'change', 'vwap', 'buyblocked', 'sellblocked', 'knownvolume'})
    # Reuse the upstream conversion methods sequentially; no grandchildren survive worker cancellation.
    dumper = DumpDataAll(data_path=str(csv), qlib_dir=str(cache), max_workers=1, include_fields=fields)
    calendar = sorted(pd.Timestamp(day) for day in prices.date.unique())
    dumper.save_calendars(calendar)
    # Qlib needs a right-open boundary after the final observed session. This sentinel
    # is never a price row, signal date or executed session; it only closes that interval.
    (cache / 'calendars' / 'day_future.txt').write_text('\n'.join(day.strftime('%Y-%m-%d') for day in calendar + [calendar[-1] + pd.Timedelta(days=1)]) + '\n', encoding='utf-8')
    dumper.save_instruments([f'{code}\t{frame.date.min():%Y-%m-%d}\t{frame.date.max():%Y-%m-%d}' for code, frame in prices.groupby('symbol')])
    for file in dumper.df_files:
        dumper._dump_bin(file, calendar)
    qlib.init(provider_uri=str(cache), region='cn', expression_cache=None, dataset_cache=None, kernels=1)
    financial_path = Path(project['path']) / 'data' / 'financials.parquet'
    if financial_path.exists():
        financial = read_table(project, 'financials')
        pit_dir = build / 'pit_input'
        pit_dir.mkdir(exist_ok=True)
        calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
        for code, frame in financial.groupby('symbol'):
            entries = []
            for _, row in frame.iterrows():
                # Date-only announcements are conservatively usable on the following observed session.
                offset = calendar.searchsorted(pd.Timestamp(row.announcementDate), side='right')
                if offset >= len(calendar):
                    continue
                period = pd.Timestamp(row.reportDate)
                for field in FINANCIAL.values():
                    value = pd.to_numeric(row.get(field), errors='coerce')
                    if field == 'npMargin' and pd.isna(value):
                        value = pd.to_numeric(row.get('netProfitMargin'), errors='coerce')
                    if pd.notna(value):
                        entries.append(dict(date=calendar[offset].strftime('%Y-%m-%d'), period=period.year * 100 + period.quarter, field=field.lower(), value=float(value)))
            if entries:
                pd.DataFrame(entries).sort_values(['date', 'period']).to_csv(pit_dir / f'{code}.csv', index=False)
        pit = DumpPitData(str(pit_dir), str(cache), max_workers=1)
        # Upstream writer reused verbatim, invoked sequentially to keep job cancellation bounded.
        for file in pit.csv_files:
            pit._dump_pit(file, overwrite=True)
    progress(.25, 'Qlib 行情/PIT 缓存已生成')
    write_json(cache_root / 'qlib.json', {'signature': signature, 'path': cache.relative_to(Path(project['path'])).as_posix()})
    return prices


def features(project, params, prices):
    import pandas as pd
    from qlib.data import D
    catalog = {item['id']: item['expression'] for item in factor_catalog()}
    for custom in params.get('customFactors', []):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', custom['id']):
            raise ValueError('自定义因子ID只允许字母开头的字母数字下划线')
        if custom['id'] in catalog:
            raise ValueError('自定义因子 ID 与内置因子冲突')
        catalog[custom['id']] = validate_expression(custom['expression'])
    ids = params.get('factorIds', [])
    if not ids or len(ids) > 300 or any(item not in catalog for item in ids):
        raise ValueError('请选择有效因子')
    start = params.get('startDate') or project.get('startDate') or str(prices.date.min())[:10]
    end = params.get('endDate') or project.get('endDate') or str(prices.date.max())[:10]
    import json, time
    from .storage import read_json, write_json
    root = Path(project['path'])
    cache = root/'.research/cache/factors'
    stamp = dict(version=1, universe=project['universe'], ids=ids, expressions=[catalog[item] for item in ids],
                 start=str(start),end=str(end),processing=params.get('factorProcessing'),
                 data=[(path.relative_to(root).as_posix(),path.stat().st_mtime_ns,path.stat().st_size)
                       for path in sorted((root/'data').rglob('*')) if path.suffix=='.parquet' or path.suffix=='.json' and path.parent.name=='history'])
    stamp = json.loads(json.dumps(stamp))
    entries = read_json(cache/'index.json',[])
    for entry in entries:
        if entry['stamp']==stamp and (cache/entry['file']).is_file():
            cached = pd.read_parquet(cache/entry['file'])
            cached.attrs['processingCoverage'] = entry['coverage']
            return cached
    frame = D.features(sorted(prices.symbol.unique()), [catalog[item] for item in ids], start_time=start, end_time=end)
    frame.columns = ids
    frame = frame.swaplevel().sort_index()
    frame.index.names = ['datetime', 'instrument']
    from .history import members
    if project['universe']['source'] != 'manual' or project['universe']['symbols']:
        keep = []
        for date, panel in frame.groupby(level=0):
            allowed = members(project, date)
            keep.append(panel if allowed is None else panel[panel.index.get_level_values('instrument').isin(allowed)])
        frame = pd.concat(keep) if keep else frame.iloc[:0]
    market = prices.set_index(['date', 'symbol'])
    market.index.names = frame.index.names
    if project['universe'].get('excludeST') and 'isST' in market:
        flags = pd.to_numeric(market.isST, errors='coerce').reindex(frame.index)
        frame = frame[flags.eq(0)]
    if project['universe'].get('minListingDays', 0) and 'listingDate' in market:
        listed = pd.to_datetime(market.listingDate, errors='coerce').reindex(frame.index)
        age = (frame.index.get_level_values(0) - listed).dt.days
        frame = frame[age >= int(project['universe']['minListingDays'])]
    if 'delistingDate' in market:
        out = pd.to_datetime(market.delistingDate, errors='coerce').reindex(frame.index)
        frame = frame[out.isna() | (frame.index.get_level_values(0) < out)]
    from .processing import process
    result, coverage = process(project, frame.replace([float('inf'), -float('inf')], float('nan')), prices, params.get('factorProcessing'))
    result.attrs['processingCoverage'] = coverage.to_dict('records')
    cache.mkdir(parents=True,exist_ok=True)
    name = f'{time.time_ns()}.parquet'
    saved = result.copy()
    saved.attrs = {}
    saved.to_parquet(cache/name)
    entries.append(dict(stamp=stamp,file=name,coverage=json.loads(coverage.to_json(orient='records',date_format='iso'))))
    write_json(cache/'index.json',entries)
    return result


def save_table(output, name, frame):
    frame = frame.copy()
    frame.attrs = {}
    if frame.index.name or getattr(frame.index, 'nlevels', 1) > 1:
        frame = frame.reset_index()
    frame.columns = [str(col) for col in frame.columns]
    path = output / f'{name}.parquet'
    frame.to_parquet(path, index=False)
    return dict(name=name, path=str(path), type='parquet')


def analyze(project, params, output, progress, prices=None):
    import pandas as pd
    from alphalens import performance, utils
    from .processing import label_prices, forward_returns, DEFAULTS as PROCESS_DEFAULTS
    prices = prepare(project, output, progress) if prices is None else prices
    values = features(project, params, prices)
    market = label_prices(prices, params.get('labelMode','next_open'))
    periods = tuple(int(p) for p in params.get('periods', [1, 5, 10, 20]))
    if not periods or any(p < 1 or p > 252 for p in periods):
        raise ValueError('分析周期必须在 1 到 252 天之间')
    if not 2 <= int(params.get('quantiles', 5)) <= 20:
        raise ValueError('分组数必须为2到20')
    artifacts, metrics, summaries, unavailable = [], {}, [], []
    for index, name in enumerate(values.columns):
        series = values[name].dropna()
        try:
            if series.empty:
                if name == 'growth_revenue':
                    raise ValueError('收入同比不可用：当前BaoStock适配未提供YOYRevenue；可导入带公告日期的同口径收入同比，未从MBRevenue推算')
                raise ValueError('因子没有非空数值，请检查所需数据字段')
            forward = forward_returns(market,periods)
            clean = utils.get_clean_factor(series, forward, quantiles=int(params.get('quantiles', 5)), max_loss=.5)
            if clean.empty:
                raise ValueError('因子没有可分析样本')
        except (ValueError, utils.MaxLossExceededError) as exc:
            unavailable.append({'factor': name, 'reason': str(exc)})
            progress(.3 + .6 * (index + 1) / len(values.columns), f'{name} 不可分析，继续其余因子')
            continue
        rank_ic = performance.factor_information_coefficient(clean)
        ic = clean.groupby(level=0).apply(lambda day: pd.Series({column:day.factor.corr(day[column]) for column in rank_ic.columns}))
        ic.index.name = 'date'
        returns, error = performance.mean_return_by_quantile(clean, demeaned=False)
        turnover = pd.concat({str(p): pd.concat({str(q): performance.quantile_turnover(clean.factor_quantile, q, p) for q in sorted(clean.factor_quantile.unique())}, axis=1) for p in periods}, axis=1)
        turnover.columns = ['_'.join(col) for col in turnover.columns]
        for period, value in ic.mean().items():
            metrics[f'{name}:IC:{period}'] = float(value) if pd.notna(value) else None
            metrics[f'{name}:RankIC:{period}'] = float(rank_ic[period].mean()) if rank_ic[period].notna().any() else None
            std = ic[period].std()
            metrics[f'{name}:ICIR:{period}'] = float(value/std) if pd.notna(std) and std > 0 else None
        daily_returns, _ = performance.mean_return_by_quantile(clean,by_date=True,demeaned=False)
        cumulative = {}
        for period in daily_returns:
            horizon = int(period.removesuffix('D'))
            panel = daily_returns[period].unstack('factor_quantile').sort_index()
            # Non-overlapping samples per staggered sleeve avoid compounding overlapping H-day returns.
            for quantile in panel:
                sleeves = []
                for offset in range(horizon):
                    sleeve = panel[quantile].iloc[offset::horizon].dropna().copy()
                    endpoint = market.index.searchsorted(sleeve.index)+horizon+(params.get('labelMode','next_open')=='next_open')
                    valid = endpoint < len(market.index)
                    sleeve = sleeve.iloc[valid]
                    sleeve.index = market.index[endpoint[valid]]
                    sleeves.append(performance.cumulative_returns(sleeve).reindex(market.index).ffill().fillna(1))
                cumulative[f'{period}_Q{quantile}'] = pd.concat(sleeves,axis=1).mean(axis=1)
        cumulative = pd.DataFrame(cumulative).rename_axis('date')
        stability = ic.groupby(ic.index.to_period('Q')).mean()
        stability.index = stability.index.astype(str)
        stability.index.name='quarter'
        artifacts.extend([save_table(output, f'{name}_IC', ic), save_table(output, f'{name}_quantile_returns', returns),
                          save_table(output, f'{name}_turnover', turnover), save_table(output, f'{name}_samples', clean),
                          save_table(output,f'{name}_RankIC',rank_ic),save_table(output,f'{name}_cumulative_quantiles',cumulative),
                          save_table(output,f'{name}_stability',stability),save_table(output,f'{name}_decay',ic.mean().rename('pearsonIC').rename_axis('period').to_frame())])
        summaries.append({'factor': name, 'samples': len(clean)})
        progress(.3 + .6 * (index + 1) / len(values.columns), f'Alphalens 已分析 {name}')
    if not summaries:
        raise ValueError('所有因子均不可分析: ' + '; '.join(f'{item["factor"]}: {item["reason"]}' for item in unavailable))
    correlation = values.groupby(level=0).corr().groupby(level=1).mean().rename_axis('factor')
    artifacts.append(save_table(output, 'factor_correlation', correlation))
    artifacts.append(save_table(output,'processing_coverage',pd.DataFrame(values.attrs['processingCoverage'])))
    return dict(metrics=metrics, artifacts=artifacts, summary=f'Alphalens 分析 {len(summaries)} 项，{len(unavailable)} 项不可分析',
                parameters={**params,'labelMode':params.get('labelMode','next_open'),'periods':list(periods),'quantiles':params.get('quantiles',5),'factorProcessing':{**PROCESS_DEFAULTS,**params.get('factorProcessing',{})}},
                details={'factors': summaries, 'unavailableFactors': unavailable, 'engine': 'alphalens-reloaded',
                         'forwardReturnConvention': 'T+1 open -> T+H+1 open' if params.get('labelMode','next_open')=='next_open' else 'T close -> T+H close',
                         'IC':'Pearson','RankIC':'Spearman','ICIR':'每日Pearson IC均值/样本标准差','correlation':'每日截面相关系数均值'})


def model_estimator(params):
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    hyper = params.get('hyperparameters', {})
    if params.get('model') == 'ridge':
        if set(hyper) - {'alpha', 'tol', 'max_iter', 'fit_intercept'}:
            raise ValueError('未知 Ridge 超参数')
        return make_pipeline(SimpleImputer(keep_empty_features=True), StandardScaler(), Ridge(**hyper))
    if params.get('model') == 'lightgbm':
        from lightgbm import LGBMRegressor
        if set(hyper) - {'n_estimators', 'learning_rate', 'num_leaves', 'max_depth', 'min_child_samples', 'subsample', 'colsample_bytree', 'reg_alpha', 'reg_lambda'}:
            raise ValueError('未知 LightGBM 超参数')
        return LGBMRegressor(random_state=42, n_jobs=1, verbosity=-1, **hyper)
    raise ValueError('未知模型')


def _train_single(project, params, output, progress, prices=None):
    import pandas as pd
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    from sklearn.metrics import mean_squared_error, r2_score
    import joblib
    prices = prepare(project, output, progress) if prices is None else prices
    features_params = {**params, 'startDate': params['trainStart'], 'endDate': params['validEnd'] if params.get('_validationOnly') else params['testEnd']}
    x = features(project, features_params, prices)
    horizon = int(params.get('labelHorizon', 5))
    if not 1 <= horizon <= 252:
        raise ValueError('标签周期必须为1至252')
    from .processing import label_prices
    market = label_prices(prices[prices.date <= features_params['endDate']], params.get('labelMode', 'next_open'))
    labels = (market.shift(-horizon) / market - 1).stack().rename('label')
    labels.index.names = x.index.names
    frame = x.join(labels).dropna(subset=['label'])
    segments = time_segments(frame, market.index, params, horizon)
    estimator = model_estimator(params)
    columns = list(x.columns)
    estimator.fit(segments['train'][columns], segments['train'].label)
    artifacts, metrics = [], {}
    for name in (['valid'] if params.get('_validationOnly') else ['valid', 'test']):
        part = segments[name]
        prediction = estimator.predict(part[columns])
        metrics[name + ':mse'] = float(mean_squared_error(part.label, prediction))
        metrics[name + ':r2'] = float(r2_score(part.label, prediction)) if len(part) > 1 else None
        table = part[['label']].assign(score=prediction)
        daily_ic = table.groupby(level=0).apply(lambda day: day.label.corr(day.score))
        metrics[name + ':ic'] = float(daily_ic.mean()) if daily_ic.notna().any() else None
        feature_dates = x.index.get_level_values(0)
        trading_x = x[(feature_dates>=pd.Timestamp(params[name+'Start'])) & (feature_dates<=pd.Timestamp(params[name+'End']))]
        predictions = pd.DataFrame({'score':estimator.predict(trading_x)},index=trading_x.index)
        predictions['label'] = part.label.reindex(trading_x.index)
        artifacts.append(save_table(output, name + '_predictions', predictions))
    model_path = output / 'model.joblib'
    joblib.dump(estimator, model_path)
    artifacts.append(dict(name='model', path=str(model_path), type='joblib'))
    progress(.95, '训练及时间隔离评估完成')
    return dict(metrics=metrics, artifacts=artifacts, summary='按时间切分的模型实验',
                details={'segments': {k: len(v) for k, v in segments.items()}, 'purgeSessions': horizon + (params.get('labelMode','next_open')=='next_open'), 'featureIds': columns,
                         'predictionRanges':{name:dict(start=params[name+'Start'],end=params[name+'End']) for name in segments if name!='train'}})


def train(project, params, output, progress, prices=None):
    import pandas as pd
    from .processing import windows
    prices = prepare(project, output, progress) if prices is None else prices
    params = {**params, 'labelMode': params.get('labelMode', 'next_open'), 'labelHorizon': params.get('labelHorizon', 5),
              'validation': {**dict(mode='single', trainYears=3, validMonths=6, testMonths=1, stepMonths=1), **params.get('validation', {})}}
    ranges = windows(pd.DatetimeIndex(sorted(prices.date.unique())), params)
    if params['validation']['mode'] == 'single':
        resolved = {**params, **ranges[0]}
        result = _train_single(project, resolved, output, progress, prices)
        result['parameters'] = resolved
        result['details']['windows'] = ranges
        return result
    artifacts, metrics, predictions = [], [], []
    for index, bounds in enumerate(ranges):
        folder = output / f'window_{index}'
        folder.mkdir(parents=True, exist_ok=True)
        result = _train_single(project, {**params, **bounds}, folder, lambda *_: None, prices)
        metrics.append({'window': index, **bounds, **result['metrics']})
        predictions.append(pd.read_parquet(folder/'test_predictions.parquet'))
        artifacts.extend([{**item, 'name': f'window_{index}_'+item['name']} for item in result['artifacts']])
        progress(.3+.65*(index+1)/len(ranges), f'滚动窗口 {index+1}/{len(ranges)}')
    merged = pd.concat(predictions).drop_duplicates(['datetime','instrument'], keep='first').sort_values(['datetime','instrument'])
    artifacts.extend([save_table(output, 'test_predictions', merged), save_table(output,'windows',pd.DataFrame(metrics)),
                      dict(name='model',path=str(output/f'window_{len(ranges)-1}'/'model.joblib'),type='joblib')])
    numeric = pd.DataFrame(metrics).select_dtypes('number').drop(columns='window').mean().to_dict()
    return dict(metrics=numeric, artifacts=artifacts, summary=f'自然月滚动验证 {len(ranges)} 窗口', parameters=params,
                details={'windows': ranges, 'featureIds': params['factorIds'], 'labelMode': params['labelMode']})


def time_segments(frame, calendar, params, horizon):
    import pandas as pd
    bounds = [(pd.Timestamp(params[f'{name}Start']), pd.Timestamp(params[f'{name}End'])) for name in ['train', 'valid', 'test']]
    if not (bounds[0][0] <= bounds[0][1] < bounds[1][0] <= bounds[1][1] < bounds[2][0] <= bounds[2][1]):
        raise ValueError('训练/验证/测试必须按时间严格分离')
    date = frame.index.get_level_values(0)
    label_end = pd.Series(calendar, index=calendar).shift(-(horizon + (params.get('labelMode','next_open')=='next_open')))
    ends = date.map(label_end)
    result = {}
    for name, (start, end) in zip(['train', 'valid', 'test'], bounds):
        if name == 'test' and params.get('_validationOnly'):
            continue
        part = frame[(date >= start) & (date <= end) & (ends <= end)]
        if len(part) < 2:
            raise ValueError(f'{name} 在清除跨区间标签后样本不足')
        result[name] = part
    return result


def backtest(project, params, output, progress, prices=None, store=None):
    import pandas as pd
    from qlib.backtest import backtest as qlib_backtest
    from qlib.contrib.strategy.signal_strategy import WeightStrategyBase
    from qlib.backtest.decision import TradeDecisionWO
    from qlib.backtest.executor import SimulatorExecutor
    from qlib.contrib.evaluate import risk_analysis
    from .portfolio import construct_portfolio, DEFAULTS as PORTFOLIO_DEFAULTS
    from .execution import cost_config, exchange_class
    from .history import industries
    from . import benchmarks
    prices = prepare(project, output, progress) if prices is None else prices
    template = params.get('template', 'multi_factor')
    if template == 'model_score':
        if store is None or not params.get('modelExperimentId'):
            raise ValueError('模型评分模板需要模型实验')
        experiment = store.experiment(project['id'], params['modelExperimentId'])
        if experiment['kind'] != 'model.train':
            raise ValueError('所选实验不是模型训练')
        partition = params.get('_predictionPartition','test')
        if partition not in {'valid','test'}:
            raise ValueError('模型预测区间必须为valid或test')
        prefix = ''
        if params.get('_predictionBounds'):
            bounds = params['_predictionBounds']
            model_bounds = experiment['parameters']
            if model_bounds.get('validation',{}).get('mode','single')=='rolling':
                window_artifact = next((a for a in experiment['artifacts'] if a['name']=='windows'),None)
                if window_artifact is None:
                    raise ValueError('模型缺少滚动窗口信息，请重新训练')
                table = pd.read_parquet(store.artifact_path(project['id'],window_artifact))
                matched = [row for row in table.to_dict('records') if all(pd.Timestamp(row[key])==pd.Timestamp(bounds[key]) for key in bounds)]
                if len(matched)!=1:
                    raise ValueError('模型与组合的滚动验证窗口不一致')
                model_bounds = matched[0]
                prefix = f'window_{int(model_bounds["window"])}_'
            for key in ['trainStart','trainEnd','validStart','validEnd','testStart','testEnd']:
                if not model_bounds.get(key) or pd.Timestamp(model_bounds[key])!=pd.Timestamp(bounds[key]):
                    raise ValueError('所选模型时间窗口与组合验证窗口不一致：'+key)
        artifact = next((a for a in experiment['artifacts'] if a['name'] == prefix+partition+'_predictions'), None)
        if artifact is None:
            raise ValueError('模型实验没有对应的'+partition+'评分，请重新训练模型')
        predictions = pd.read_parquet(store.artifact_path(project['id'], artifact))
        score = predictions.set_index(['datetime', 'instrument']).score
    elif template in {'single_factor', 'multi_factor'}:
        values = features(project, params, prices)
        if template == 'single_factor' and len(values.columns) != 1:
            raise ValueError('单因子模板必须选择一个因子')
        ranks = values.groupby(level=0).rank(pct=True)
        weights = params.get('weights', {})
        score = ranks.mul(pd.Series({name: float(weights.get(name, 1)) for name in ranks.columns})).sum(axis=1, min_count=len(ranks.columns))
    else:
        raise ValueError('未知策略模板')
    if params.get('code'):
        # Explicit user job code executes in this worker, with the same local privileges as the application.
        # It only supplies scores; all order matching, positions and statistics still use Qlib.
        scope = {'pd': pd, 'prices': prices.copy(), 'scores': score.copy()}
        exec(compile(params['code'], '<research-strategy>', 'exec'), scope)
        candidate = scope.get('scores')
        if not isinstance(candidate, pd.Series) or not candidate.index.equals(score.index):
            raise ValueError('Python 策略必须输出保留原日期/股票索引的 pandas Series scores')
        score = pd.to_numeric(candidate, errors='raise').replace([float('inf'), -float('inf')], float('nan'))
    top_n = int(params.get('topN', 30))
    frequency = params.get('rebalance', 'weekly')
    if top_n < 1 or top_n > 5000 or frequency not in {'daily', 'weekly', 'monthly'}:
        raise ValueError('持仓数或调仓频率无效')
    capital = float(params.get('capital', 1000000))
    costs = cost_config(params)
    portfolio_config = {**PORTFOLIO_DEFAULTS, **params.get('portfolio', {})}
    if capital <= 0:
        raise ValueError('资金或费用参数无效')
    dates = pd.DatetimeIndex(sorted(prices.date.unique()))
    score = score.dropna().sort_index()
    if score.empty:
        raise ValueError('没有有效信号')
    start = max(score.index.get_level_values(0).min(), pd.Timestamp(params.get('startDate') or project.get('startDate') or dates[0]))
    end = min(dates[-1], pd.Timestamp(params.get('endDate') or project.get('endDate') or dates[-1]))
    trading_dates = dates[(dates > start) & (dates <= end)]
    if len(trading_dates) < 2:
        raise ValueError('回测交易日不足')
    schedule = set(trading_dates if frequency == 'daily' else pd.Series(trading_dates, index=trading_dates).groupby(trading_dates.to_period('W' if frequency == 'weekly' else 'M')).first())
    trade_rows, rejected, targets, risk_rows, conflicts = [], [], [], [], []
    portfolio_warnings = []
    historical_returns = prices.pivot(index='date',columns='symbol',values='close').sort_index().pct_change(fill_method=None)
    benchmark_name = params.get('benchmark') or ('csi500' if project['universe']['source']=='csi500' else 'csi300')
    benchmark_returns = benchmarks.returns(project, benchmark_name, trading_dates)
    exchange = exchange_class(prices, costs, rejected)(freq='day',start_time=trading_dates[0],end_time=trading_dates[-1],codes=sorted(prices.symbol.unique()),
        deal_price='$open',open_cost=0,close_cost=0,min_cost=0,trade_unit=1,limit_threshold=('$buyblocked','$sellblocked'),
        volume_threshold=('cum',f'$knownvolume*{costs["volumeParticipation"]}'))

    class ResearchWeights(WeightStrategyBase):
        def generate_trade_decision(self, execute_result=None):
            trade_start, _ = self.trade_calendar.get_step_time(self.trade_calendar.get_trade_step())
            if pd.Timestamp(trade_start).normalize() not in schedule:
                return TradeDecisionWO([], self)
            return super().generate_trade_decision(execute_result)

        def generate_target_weight_position(self, score, current, trade_start_time, trade_end_time):
            score = score.iloc[:, 0] if isinstance(score, pd.DataFrame) else score
            chosen = score.dropna().sort_values(ascending=False).head(top_n)
            pred_start, _ = self.trade_calendar.get_step_time(self.trade_calendar.get_trade_step(),shift=1)
            previous = pd.Series(current.get_stock_weight_dict(only_stock=False),dtype=float)
            # Tomorrow's suspension/limit state constrains execution, never today's allocation.
            locked = pd.Series(dtype=float)
            groups = industries(project,pred_start,chosen.index.union(previous.index))
            expected = None
            if portfolio_config['returnSource']=='model':
                if template!='model_score':
                    raise ValueError('模型预期收益要求模型评分模板')
                horizon = int(experiment['parameters'].get('labelHorizon',5))
                expected = (1+chosen)**(252/horizon)-1
            result = construct_portfolio(chosen,historical_returns.loc[:pred_start],portfolio_config,previous,groups,locked,expected)
            conflicts.extend(result['conflicts'])
            portfolio_warnings.extend(result['warnings'])
            for name, weight in result['weights'].items():
                targets.append(dict(date=trade_start_time,signalDate=pred_start,symbol=name,targetWeight=float(weight),cash=result['cash'],executable=result['executable']))
            for name, contribution in result['riskContributions'].items():
                risk_rows.append(dict(date=trade_start_time,symbol=name,targetRiskContribution=contribution))
            if not result['executable']:
                return previous.to_dict()
            return result['weights'].to_dict()

    class RecordingExecutor(SimulatorExecutor):
        def _collect_data(self, trade_decision, level=0):
            result, kwargs = super()._collect_data(trade_decision, level)
            for order, value, cost, price in result:
                if order.deal_amount:
                    factor = float(order.factor)
                    trade_rows.append(dict(date=str(order.start_time), symbol=order.stock_id, direction=int(order.direction),
                        amount=float(order.deal_amount) * factor, price=float(price) / factor,
                        adjustedAmount=float(order.deal_amount), adjustedPrice=float(price), factor=factor, value=float(value), cost=float(cost),
                        **{k:v for k,v in getattr(order,'research_fees',{}).items() if k!='total'}))
                else:
                    rejected.append(dict(date=str(order.start_time),symbol=order.stock_id,side='buy' if order.direction else 'sell',
                        requestedQuantity=order.amount*(order.factor or 1),allowedQuantity=0,reason='停牌、涨跌停、申报或资金条件不满足'))
            return result, kwargs

    strategy = ResearchWeights(signal=score, risk_degree=1.0)
    portfolio, indicators = qlib_backtest(start_time=trading_dates[0], end_time=trading_dates[-1], strategy=strategy,
        executor=RecordingExecutor(time_per_step='day', generate_portfolio_metrics=True),
        account=capital, benchmark=benchmark_returns, exchange_kwargs={'exchange':exchange})
    report, positions = portfolio['1day']
    report.index.name = 'date'
    net = report['return'] - report['cost']
    risk = risk_analysis(net, freq='day')
    metrics = {str(key): float(value) if pd.notna(value) else None for key, value in risk.iloc[:, 0].items()}
    metrics['total_return'] = float((1 + net).prod() - 1)
    metrics['total_cost_ratio'] = float(report.cost.sum())
    metrics['sharpe'] = metrics.get('information_ratio')
    excess_metrics, benchmark_tables = benchmarks.analyze(report)
    metrics['information_ratio'] = excess_metrics['information_ratio']
    metrics['tracking_error'] = excess_metrics['tracking_error']
    metrics['benchmark_total_return'] = float((1+report.bench).prod()-1)
    metrics['excess_annualized_return'] = excess_metrics['annualized_return']
    holdings = []
    factor_rows = prices.assign(factor=prices['factor'] if 'factor' in prices else 1.0).set_index(['date', 'symbol']).factor
    for date, position in positions.items():
        for code in position.get_stock_list():
            factor = factor_rows.get((pd.Timestamp(date).normalize(), code), float('nan'))
            holdings.append(dict(date=str(date), symbol=code, amount=position.get_stock_amount(code) * factor,
                                 price=position.get_stock_price(code) / factor, adjustedAmount=position.get_stock_amount(code), adjustedPrice=position.get_stock_price(code),
                                 actualWeight=position.get_stock_weight_dict(only_stock=False).get(code,0),marketValue=position.get_stock_amount(code)*position.get_stock_price(code)))
    artifacts = [save_table(output, 'portfolio', report), save_table(output, 'holdings', pd.DataFrame(holdings)), save_table(output, 'trades', pd.DataFrame(trade_rows)), save_table(output, 'signals', score.rename('score').to_frame())]
    artifacts += [save_table(output,name,frame) for name,frame in benchmark_tables.items()]
    holding_frame = pd.DataFrame(holdings)
    industry_rows, contribution_rows = [], []
    market_close = prices.set_index(['date','symbol']).close
    prior_amounts = {}
    for date in report.index:
        day = pd.Timestamp(date).normalize()
        position = positions[date]
        amounts = {code:position.get_stock_amount(code) for code in position.get_stock_list()}
        trades_today = [row for row in trade_rows if pd.Timestamp(row['date']).normalize()==day]
        names = set(prior_amounts) | set(amounts) | {row['symbol'] for row in trades_today}
        previous_date = dates[dates.searchsorted(day)-1]
        prior_nav = float(report.loc[date,'account']/(1+net.loc[date]))
        for code in names:
            close = market_close.get((day,code),float('nan'))
            last = market_close.get((previous_date,code),float('nan'))
            amount = prior_amounts.get(code,0)
            pnl = amount*(close-last) if amount else 0.
            for trade in trades_today:
                if trade['symbol']==code:
                    pnl += (1 if trade['direction'] else -1)*trade['adjustedAmount']*(close-trade['adjustedPrice'])-trade['cost']
            contribution_rows.append(dict(date=day,symbol=code,pnl=pnl,returnContribution=pnl/prior_nav))
        weights = pd.Series(position.get_stock_weight_dict(only_stock=False),dtype=float)
        groups = industries(project,day,weights.index).fillna('未知')
        for group, weight in weights.groupby(groups).sum().items():
            industry_rows.append(dict(date=day,industry=group,actualWeight=weight))
        prior_amounts = amounts
    for date in {pd.Timestamp(row['date']) for row in risk_rows}:
        actual = holding_frame[pd.to_datetime(holding_frame.date).eq(date)].set_index('symbol').actualWeight if not holding_frame.empty else pd.Series(dtype=float)
        nonzero = actual[actual>1e-8]
        prior_date = dates[dates.searchsorted(date)-1]
        sample = historical_returns.loc[:prior_date].tail(portfolio_config['lookback']).reindex(columns=nonzero.index).dropna()
        rc = pd.Series(dtype=float)
        if len(nonzero) and len(sample)>=portfolio_config['minObservations']:
            from sklearn.covariance import LedoitWolf
            cov = LedoitWolf().fit(sample.to_numpy()).covariance_*252
            raw_rc = nonzero.to_numpy()*(cov@nonzero.to_numpy())
            if raw_rc.sum()>1e-30:
                rc = pd.Series(raw_rc/raw_rc.sum(),index=nonzero.index)
        for row in risk_rows:
            if pd.Timestamp(row['date'])==date:
                row['actualRiskContribution'] = rc.get(row['symbol'],float('nan'))
                row['actualWeight'] = actual.get(row['symbol'],0.)
                row['contributionDeviation'] = row['actualRiskContribution']-row['targetRiskContribution']
    artifacts += [save_table(output,'target_weights',pd.DataFrame(targets)),save_table(output,'risk',pd.DataFrame(risk_rows)),save_table(output,'unfilled',pd.DataFrame(rejected)),
                  save_table(output,'industry',pd.DataFrame(industry_rows)),save_table(output,'contribution',pd.DataFrame(contribution_rows))]
    progress(.95, 'Qlib 组合回测完成')
    return dict(metrics=metrics, artifacts=artifacts, summary='Qlib 日期规则组合回测',parameters={**params,'costs':costs,'portfolio':portfolio_config,'benchmark':benchmark_name,'topN':top_n},
                details={'engine': 'pyqlib', 'benchmark': benchmark_name, 'signalTiming': 'previous trading session -> next session open', 'rebalance': frequency,
                         'executable':not conflicts,'conflicts':list(dict.fromkeys(conflicts)),
                         'warnings': list(dict.fromkeys(portfolio_warnings))+['日线开盘价近似开盘成交，非逐笔9:25集合报价；旧制IPO缺发行价时不成交。', '原始参考昨收、历史ST/上市日期不足的边界不会自动补齐。']})


def optimize(project, params, output, progress, store):
    import copy
    import optuna
    import pandas as pd
    space = params.get('searchSpace', {})
    if not space or len(space) > 20:
        raise ValueError('请指定1到20个寻优参数')
    sampler_name = params.get('sampler', 'tpe')
    if sampler_name == 'grid':
        if any(not isinstance(v, list) or not v for v in space.values()):
            raise ValueError('Grid searchSpace 值必须是非空候选数组')
        sampler = optuna.samplers.GridSampler(space, seed=42)
    elif sampler_name == 'tpe':
        sampler = optuna.samplers.TPESampler(seed=42)
    else:
        raise ValueError('未知寻优算法')
    target = params.get('target')
    if target not in {'model', 'backtest'}:
        raise ValueError('未知寻优目标')
    for key in space:
        validate_search_key(target, key, params.get('baseParameters', {}))
    trials = int(params.get('trials', 20))
    if not 1 <= trials <= 1000:
        raise ValueError('试验次数必须为1到1000')
    prices = prepare(project, output, progress)
    from .processing import windows
    validation = params.get('validation', {})
    base = {**params.get('baseParameters', {}), **{k:v for k,v in validation.items() if k.endswith(('Start','End'))},
            'validation': {**params.get('baseParameters', {}).get('validation', {}), **{k:v for k,v in validation.items() if not k.endswith(('Start','End'))}}}
    ranges = windows(pd.DatetimeIndex(sorted(prices.date.unique())), base)
    objective_key = params.get('objective') or ('valid:mse' if target == 'model' else 'valid:information_ratio')
    allowed = {'valid:mse', 'valid:ic'} if target == 'model' else {'valid:information_ratio', 'valid:annualized_return', 'valid:sharpe'}
    if objective_key not in allowed:
        raise ValueError('不支持的寻优目标: '+objective_key)
    storage = optuna.storages.RDBStorage('sqlite:///' + (output / 'optuna.sqlite').as_posix())
    study = optuna.create_study(direction='minimize' if objective_key == 'valid:mse' else 'maximize', sampler=sampler,
                                storage=storage, study_name='research', load_if_exists=True)

    def objective(trial):
        parameters = copy.deepcopy(base)
        for key, options in space.items():
            if isinstance(options, list):
                value = trial.suggest_categorical(key, options)
            elif options.get('type') == 'int':
                value = trial.suggest_int(key, int(options['low']), int(options['high']), step=int(options.get('step', 1)), log=bool(options.get('log', False)))
            else:
                value = trial.suggest_float(key, float(options['low']), float(options['high']), step=options.get('step'), log=bool(options.get('log', False)))
            container = parameters
            parts = key.split('.')
            for part in parts[:-1]:
                container = container.setdefault(part, {})
            container[parts[-1]] = value
        trial_dir = output / f'trial_{trial.number}'
        trial_dir.mkdir(exist_ok=True)
        scores = []
        rows = []
        for index, bounds in enumerate(ranges):
            window_dir = trial_dir / f'window_{index}'
            window_dir.mkdir(exist_ok=True)
            if target == 'model':
                result = _train_single(project, {**parameters, **bounds, '_validationOnly': True}, window_dir, lambda *_: None, prices)
                value = result['metrics'][objective_key]
            else:
                result = backtest(project, {**parameters, 'startDate': bounds['validStart'], 'endDate': bounds['validEnd'], '_predictionPartition':'valid','_predictionBounds':bounds}, window_dir, lambda *_: None, prices, store)
                value = result['metrics'][objective_key.removeprefix('valid:')]
            if value is None or not __import__('math').isfinite(value):
                raise ValueError('验证区间目标无有效数值')
            scores.append(value)
            rows.append({'window': index, **bounds, 'objective': value})
            write_json(window_dir/'result.json', result)
        save_table(trial_dir, 'validation_windows', pd.DataFrame(rows))
        progress(.3 + .65 * (trial.number + 1) / trials, f'Optuna 试验 {trial.number + 1}/{trials}')
        return float(sum(scores)/len(scores))

    try:
        study.optimize(objective, n_trials=trials, n_jobs=1)
        best = copy.deepcopy(base)
        for key, value in study.best_params.items():
            node = best
            parts = key.split('.')
            for part in parts[:-1]:
                node = node.setdefault(part,{})
            node[parts[-1]] = value
        holdout_dir = output/'holdout'
        holdout_dir.mkdir(exist_ok=True)
        bounds = ranges[-1]
        holdout = _train_single(project, {**best, **bounds}, holdout_dir, lambda *_: None, prices) if target == 'model' else backtest(project, {**best, 'startDate': bounds['testStart'], 'endDate': bounds['testEnd'], '_predictionPartition':'test','_predictionBounds':bounds}, holdout_dir, lambda *_: None, prices, store)
        write_json(holdout_dir/'result.json', holdout)
        artifacts = [save_table(output, 'trials', study.trials_dataframe()), dict(name='optuna', path=str(output / 'optuna.sqlite'), type='sqlite')]
        artifacts += [{**item, 'name':'holdout_'+item['name']} for item in holdout['artifacts']]
        for trial in study.trials:
            for path in (output/f'trial_{trial.number}').glob('validation_windows.parquet'):
                artifacts.append(dict(name=f'trial_{trial.number}_windows',path=str(path),type='parquet'))
        return dict(metrics={'best_value': float(study.best_value), **{'holdout:'+k:v for k,v in holdout['metrics'].items()}}, artifacts=artifacts,
                    summary='Optuna 验证集选参及最终独立测试', parameters={**params,'objective':objective_key},
                    details={'bestParameters': study.best_params, 'target': target, 'sampler': sampler_name, 'objective': objective_key, 'holdout': bounds,
                             'holdoutMetrics': holdout['metrics'], 'warning': '仅验证集选参；最终窗口测试不参与选择，请明确应用最佳参数。'})
    finally:
        storage.remove_session()
        storage.engine.dispose()


def validate_search_key(target, key, base):
    model_keys = {'ridge': {'alpha', 'tol', 'max_iter', 'fit_intercept'},
                  'lightgbm': {'n_estimators', 'learning_rate', 'num_leaves', 'max_depth', 'min_child_samples', 'subsample', 'colsample_bytree', 'reg_alpha', 'reg_lambda'}}
    if target == 'model':
        allowed = {'hyperparameters.' + name for name in model_keys.get(base.get('model'), set())}
    else:
        allowed = {'topN', 'rebalance', 'capital', 'commissionBuy', 'commissionSell', 'minFee', 'slippage'}
        allowed |= {'weights.' + name for name in base.get('factorIds', [])}
        from .portfolio import DEFAULTS
        from .rules import COST_DEFAULTS
        allowed |= {'portfolio.'+name for name in DEFAULTS}
        allowed |= {'costs.'+name for name in COST_DEFAULTS}
    if key not in allowed:
        raise ValueError(f'无效寻优参数 {key}；模型参数请用 hyperparameters.xxx，不能使用会被忽略的字段')
