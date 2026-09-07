"""Thin adapters to Qlib, Alphalens, sklearn and Optuna; no local backtest engine."""
from pathlib import Path
import ast
import re

from .data import read_table, records
from .storage import write_json

FINANCIAL = {'roe': 'roeAvg', 'growth_profit': 'YOYNI', 'growth_revenue': 'YOYRevenue', 'profit_margin': 'netProfitMargin', 'leverage': 'liabilityToAsset'}
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
    if chosen:
        from .data import symbol
        prices = prices[prices.symbol.isin([symbol(x) for x in chosen])].copy()
    if prices.empty:
        raise ValueError('股票池没有行情数据')
    csv = output / 'qlib_input'
    cache = output / 'qlib'
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
        halted = frame['volume'].le(0)
        if 'tradestatus' in frame:
            halted = halted | frame['tradestatus'].ne(1)
        opening_change = frame['open'] / frame['close'].shift(1) - 1
        frame['buyblocked'] = (halted | opening_change.ge(.095)).astype(float)
        frame['sellblocked'] = (halted | opening_change.le(-.095)).astype(float)
        frame['volume'] = frame['volume'] / frame['factor']
        frame['vwap'] = frame['amount'] / frame.volume if 'amount' in frame else float('nan')
        frame.to_csv(csv / f'{code}.csv', index=False)
    fields = sorted({c.lower() for c in numeric if c in prices} | {'factor', 'change', 'vwap', 'buyblocked', 'sellblocked'})
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
        pit_dir = output / 'pit_input'
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
                    if pd.notna(value):
                        entries.append(dict(date=calendar[offset].strftime('%Y-%m-%d'), period=period.year * 100 + period.quarter, field=field.lower(), value=float(value)))
            if entries:
                pd.DataFrame(entries).sort_values(['date', 'period']).to_csv(pit_dir / f'{code}.csv', index=False)
        pit = DumpPitData(str(pit_dir), str(cache), max_workers=1)
        # Upstream writer reused verbatim, invoked sequentially to keep job cancellation bounded.
        for file in pit.csv_files:
            pit._dump_pit(file, overwrite=True)
    progress(.25, 'Qlib 行情/PIT 缓存已生成')
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
    frame = D.features(sorted(prices.symbol.unique()), [catalog[item] for item in ids], start_time=start, end_time=end)
    frame.columns = ids
    frame = frame.swaplevel().sort_index()
    frame.index.names = ['datetime', 'instrument']
    market = prices.set_index(['date', 'symbol'])
    market.index.names = frame.index.names
    if project['universe'].get('excludeST') and 'isST' in market:
        flags = pd.to_numeric(market.isST, errors='coerce').reindex(frame.index)
        frame = frame[flags.eq(0)]
    if project['universe'].get('minListingDays', 0) and 'listingDate' in market:
        listed = pd.to_datetime(market.listingDate, errors='coerce').reindex(frame.index)
        age = (frame.index.get_level_values(0) - listed).dt.days
        frame = frame[age >= int(project['universe']['minListingDays'])]
    return frame.replace([float('inf'), -float('inf')], float('nan'))


def save_table(output, name, frame):
    frame = frame.copy()
    if frame.index.name or getattr(frame.index, 'nlevels', 1) > 1:
        frame = frame.reset_index()
    frame.columns = [str(col) for col in frame.columns]
    path = output / f'{name}.parquet'
    frame.to_parquet(path, index=False)
    return dict(name=name, path=str(path), type='parquet')


def analyze(project, params, output, progress, prices=None):
    import pandas as pd
    from alphalens import performance, utils
    prices = prepare(project, output, progress) if prices is None else prices
    values = features(project, params, prices)
    market = prices.pivot(index='date', columns='symbol', values='close').sort_index()
    periods = tuple(int(p) for p in params.get('periods', [1, 5, 10]))
    if not periods or any(p < 1 or p > 252 for p in periods):
        raise ValueError('分析周期必须在 1 到 252 天之间')
    if not 2 <= int(params.get('quantiles', 5)) <= 20:
        raise ValueError('分组数必须为2到20')
    artifacts, metrics, summaries = [], {}, []
    for index, name in enumerate(values.columns):
        series = values[name].dropna()
        clean = utils.get_clean_factor_and_forward_returns(series, market, periods=periods, quantiles=int(params.get('quantiles', 5)), max_loss=.5, filter_zscore=None)
        if clean.empty:
            raise ValueError(f'{name} 没有可分析样本')
        ic = performance.factor_information_coefficient(clean)
        returns, error = performance.mean_return_by_quantile(clean)
        turnover = pd.concat({str(p): pd.concat({str(q): performance.quantile_turnover(clean.factor_quantile, q, p) for q in sorted(clean.factor_quantile.unique())}, axis=1) for p in periods}, axis=1)
        turnover.columns = ['_'.join(col) for col in turnover.columns]
        for period, value in ic.mean().items():
            metrics[f'{name}:IC:{period}'] = float(value) if pd.notna(value) else None
        artifacts.extend([save_table(output, f'{name}_IC', ic), save_table(output, f'{name}_quantile_returns', returns),
                          save_table(output, f'{name}_turnover', turnover), save_table(output, f'{name}_samples', clean)])
        summaries.append({'factor': name, 'samples': len(clean)})
        progress(.3 + .6 * (index + 1) / len(values.columns), f'Alphalens 已分析 {name}')
    artifacts.append(save_table(output, 'factor_correlation', values.corr().rename_axis('factor')))
    return dict(metrics=metrics, artifacts=artifacts, summary='Alphalens 因子分析', details={'factors': summaries, 'engine': 'alphalens-reloaded', 'forwardReturnConvention': 'close-to-close; analysis only, not execution returns'})


def train(project, params, output, progress, prices=None):
    import pandas as pd
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    from sklearn.metrics import mean_squared_error, r2_score
    import joblib
    prices = prepare(project, output, progress) if prices is None else prices
    features_params = {**params, 'startDate': params['trainStart'], 'endDate': params['testEnd']}
    x = features(project, features_params, prices)
    horizon = int(params.get('labelHorizon', 5))
    if not 1 <= horizon <= 252:
        raise ValueError('标签周期必须为1至252')
    market = prices.pivot(index='date', columns='symbol', values='close').sort_index()
    labels = (market.shift(-horizon) / market - 1).stack().rename('label')
    labels.index.names = x.index.names
    frame = x.join(labels).dropna(subset=['label'])
    segments = time_segments(frame, market.index, params, horizon)
    hyper = params.get('hyperparameters', {})
    if params.get('model') == 'ridge':
        if set(hyper) - {'alpha', 'tol', 'max_iter', 'fit_intercept'}:
            raise ValueError('未知 Ridge 超参数')
        estimator = make_pipeline(SimpleImputer(keep_empty_features=True), StandardScaler(), Ridge(**hyper))
    elif params.get('model') == 'lightgbm':
        from lightgbm import LGBMRegressor
        if set(hyper) - {'n_estimators', 'learning_rate', 'num_leaves', 'max_depth', 'min_child_samples', 'subsample', 'colsample_bytree', 'reg_alpha', 'reg_lambda'}:
            raise ValueError('未知 LightGBM 超参数')
        estimator = LGBMRegressor(random_state=42, n_jobs=1, verbosity=-1, **hyper)
    else:
        raise ValueError('未知模型')
    columns = list(x.columns)
    estimator.fit(segments['train'][columns], segments['train'].label)
    artifacts, metrics = [], {}
    for name in ['valid', 'test']:
        part = segments[name]
        prediction = estimator.predict(part[columns])
        metrics[name + ':mse'] = float(mean_squared_error(part.label, prediction))
        metrics[name + ':r2'] = float(r2_score(part.label, prediction)) if len(part) > 1 else None
        table = part[['label']].assign(score=prediction)
        artifacts.append(save_table(output, name + '_predictions', table))
    model_path = output / 'model.joblib'
    joblib.dump(estimator, model_path)
    artifacts.append(dict(name='model', path=str(model_path), type='joblib'))
    progress(.95, '训练及时间隔离评估完成')
    return dict(metrics=metrics, artifacts=artifacts, summary='按时间切分的模型实验',
                details={'segments': {k: len(v) for k, v in segments.items()}, 'purgeSessions': horizon, 'featureIds': columns})


def time_segments(frame, calendar, params, horizon):
    import pandas as pd
    bounds = [(pd.Timestamp(params[f'{name}Start']), pd.Timestamp(params[f'{name}End'])) for name in ['train', 'valid', 'test']]
    if not (bounds[0][0] <= bounds[0][1] < bounds[1][0] <= bounds[1][1] < bounds[2][0] <= bounds[2][1]):
        raise ValueError('训练/验证/测试必须按时间严格分离')
    date = frame.index.get_level_values(0)
    label_end = pd.Series(calendar, index=calendar).shift(-horizon)
    ends = date.map(label_end)
    result = {}
    for name, (start, end) in zip(['train', 'valid', 'test'], bounds):
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
    prices = prepare(project, output, progress) if prices is None else prices
    template = params.get('template', 'multi_factor')
    if template == 'model_score':
        if store is None or not params.get('modelExperimentId'):
            raise ValueError('模型评分模板需要模型实验')
        experiment = store.experiment(project['id'], params['modelExperimentId'])
        if experiment['kind'] != 'model.train':
            raise ValueError('所选实验不是模型训练')
        artifact = next((a for a in experiment['artifacts'] if a['name'] == 'test_predictions'), None)
        if artifact is None:
            raise ValueError('模型实验没有样本外评分')
        predictions = pd.read_parquet(artifact['path'])
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
    top_n = int(params.get('topN', 20))
    frequency = params.get('rebalance', 'weekly')
    if top_n < 1 or top_n > 5000 or frequency not in {'daily', 'weekly', 'monthly'}:
        raise ValueError('持仓数或调仓频率无效')
    capital = float(params.get('capital', 1000000))
    buy, sell, fee, slip = [float(params.get(k, d)) for k, d in [('commissionBuy', .0003), ('commissionSell', .0013), ('minFee', 5), ('slippage', .001)]]
    if capital <= 0 or min(buy, sell, fee, slip) < 0 or max(buy, sell, slip) >= 1:
        raise ValueError('资金或费用参数无效')
    dates = pd.DatetimeIndex(sorted(prices.date.unique()))
    score = score.dropna().sort_index()
    if score.empty:
        raise ValueError('没有有效信号')
    start = max(score.index.get_level_values(0).min(), pd.Timestamp(params.get('startDate') or project.get('startDate') or dates[0]))
    end = min(score.index.get_level_values(0).max(), pd.Timestamp(params.get('endDate') or project.get('endDate') or dates[-1]))
    trading_dates = dates[(dates > start) & (dates <= end)]
    if len(trading_dates) < 2:
        raise ValueError('回测交易日不足')
    schedule = set(trading_dates if frequency == 'daily' else pd.Series(trading_dates, index=trading_dates).groupby(trading_dates.to_period('W' if frequency == 'weekly' else 'M')).first())
    trade_rows = []

    class ResearchWeights(WeightStrategyBase):
        def generate_trade_decision(self, execute_result=None):
            trade_start, _ = self.trade_calendar.get_step_time(self.trade_calendar.get_trade_step())
            if pd.Timestamp(trade_start).normalize() not in schedule:
                return TradeDecisionWO([], self)
            return super().generate_trade_decision(execute_result)

        def generate_target_weight_position(self, score, current, trade_start_time, trade_end_time):
            score = score.iloc[:, 0] if isinstance(score, pd.DataFrame) else score
            chosen = score.dropna().sort_values(ascending=False).head(top_n)
            return {name: 1 / len(chosen) for name in chosen.index} if len(chosen) else {}

    class RecordingExecutor(SimulatorExecutor):
        def _collect_data(self, trade_decision, level=0):
            result, kwargs = super()._collect_data(trade_decision, level)
            for order, value, cost, price in result:
                if order.deal_amount:
                    trade_rows.append(dict(date=str(order.start_time), symbol=order.stock_id, direction=int(order.direction), amount=float(order.deal_amount), value=float(value), cost=float(cost), price=float(price)))
            return result, kwargs

    strategy = ResearchWeights(signal=score, risk_degree=.95)
    portfolio, indicators = qlib_backtest(start_time=trading_dates[0], end_time=trading_dates[-1], strategy=strategy,
        executor=RecordingExecutor(time_per_step='day', generate_portfolio_metrics=True),
        account=capital, benchmark=pd.Series(0.0, index=trading_dates),
        exchange_kwargs={'freq': 'day', 'codes': sorted(prices.symbol.unique()), 'deal_price': (f'$open*(1+{slip})', f'$open*(1-{slip})'),
                         'open_cost': buy, 'close_cost': sell, 'min_cost': fee, 'limit_threshold': ('$buyblocked', '$sellblocked')})
    report, positions = portfolio['1day']
    report.index.name = 'date'
    net = report['return'] - report['cost']
    risk = risk_analysis(net, freq='day')
    metrics = {str(key): float(value) if pd.notna(value) else None for key, value in risk.iloc[:, 0].items()}
    metrics['total_return'] = float((1 + net).prod() - 1)
    metrics['total_cost_ratio'] = float(report.cost.sum())
    holdings = []
    for date, position in positions.items():
        for code in position.get_stock_list():
            holdings.append(dict(date=str(date), symbol=code, amount=position.get_stock_amount(code), price=position.get_stock_price(code)))
    artifacts = [save_table(output, 'portfolio', report), save_table(output, 'holdings', pd.DataFrame(holdings)), save_table(output, 'trades', pd.DataFrame(trade_rows)), save_table(output, 'signals', score.rename('score').to_frame())]
    progress(.95, 'Qlib 组合回测完成')
    return dict(metrics=metrics, artifacts=artifacts, summary='Qlib 多头组合回测',
                details={'engine': 'pyqlib', 'benchmark': 'cash_zero_return', 'signalTiming': 'previous trading session -> next session open', 'rebalance': frequency,
                         'warnings': ['研究近似：统一9.5%涨跌停过滤，未完整实现各板块/ST/上市例外。', '历史成分、复权和停牌语义依赖输入覆盖。', '缺失 isST 或 listingDate 字段时，相应股票池过滤不可用。']})


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
    storage = optuna.storages.RDBStorage('sqlite:///' + (output / 'optuna.sqlite').as_posix())
    study = optuna.create_study(direction='minimize' if target == 'model' else 'maximize', sampler=sampler,
                                storage=storage, study_name='research', load_if_exists=True)

    def objective(trial):
        parameters = copy.deepcopy(params.get('baseParameters', {}))
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
        result = train(project, parameters, trial_dir, lambda *_: None, prices) if target == 'model' else backtest(project, parameters, trial_dir, lambda *_: None, prices, store)
        write_json(trial_dir / 'result.json', result)
        progress(.3 + .65 * (trial.number + 1) / trials, f'Optuna 试验 {trial.number + 1}/{trials}')
        return result['metrics']['valid:mse' if target == 'model' else 'information_ratio']

    try:
        study.optimize(objective, n_trials=trials, n_jobs=1)
        return dict(metrics={'best_value': float(study.best_value)}, artifacts=[save_table(output, 'trials', study.trials_dataframe()), dict(name='optuna', path=str(output / 'optuna.sqlite'), type='sqlite')],
                    summary='Optuna 参数寻优', details={'bestParameters': study.best_params, 'target': target, 'sampler': sampler_name, 'warning': '最优参数是研究区间内选择结果，需独立样本外验证。'})
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
    if key not in allowed:
        raise ValueError(f'无效寻优参数 {key}；模型参数请用 hyperparameters.xxx，不能使用会被忽略的字段')
