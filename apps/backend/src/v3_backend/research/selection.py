"""Monthly model refresh and a daily estimated trade list; never changes holdings."""
from pathlib import Path
import numpy as np
import pandas as pd
from . import data, engines, positions
from .storage import read_json, write_json, now
from .portfolio import construct_portfolio, DEFAULTS, portfolio_turnover
from .history import industries
from .execution import cost_config
from .rules import quantity, affordable, fees


def completed_prices(prices):
    current = pd.Timestamp.now(tz='Asia/Shanghai')
    cutoff = current.tz_localize(None).normalize()
    return prices[prices.date <= cutoff] if current.hour >= 15 else prices[prices.date < cutoff]


def update_end_date():
    current = pd.Timestamp.now(tz='Asia/Shanghai')
    cutoff = current.normalize() if current.hour >= 15 else current.normalize()-pd.Timedelta(days=1)
    return cutoff.strftime('%Y-%m-%d')


def estimate_orders(snapshot, weights, market, costs, config, groups, executable=True):
    """Estimate at the last completed close, sellable shares and real cash only."""
    held = {row['symbol']: row for row in snapshot['rows']}
    names = weights.index.union(pd.Index(held))
    missing = [code for code in names if code not in market.index or not np.isfinite(market.loc[code, 'rawClose']) or market.loc[code, 'rawClose'] <= 0]
    if missing:
        raise ValueError('最新估值价格缺失：' + '、'.join(missing))
    close = market.rawClose.reindex(names)
    current_qty = pd.Series({code: held.get(code, {}).get('quantity', 0) for code in names}, dtype=float)
    nav = float(snapshot['cash'] + (current_qty * close).sum())
    if nav <= 0:
        raise ValueError('请填写持仓或可用现金，当前资产为0')
    before = current_qty * close / nav
    desired = weights.reindex(names, fill_value=0) * nav / close
    cash, actual, rows, conflicts = float(snapshot['cash']), current_qty.copy(), [], []
    date = str(market.date.max())[:10]
    for side in ['sell', 'buy']:
        for code in names:
            delta = float(desired[code] - current_qty[code])
            if delta == 0 or (delta > 0) != (side == 'buy'):
                continue
            price = float(close[code])
            sellable = held.get(code, {}).get('sellableQuantity', 0)
            requested = abs(delta)
            units = quantity(code, requested, side, sellable)
            reasons = []
            if side == 'sell' and requested > sellable:
                reasons.append('可卖数量限制')
            row = market.loc[code]
            if pd.notna(row.get('tradestatus')) and float(row.tradestatus) != 1:
                units = 0
                reasons.append('最新交易日停牌，待复牌确认')
            volume = pd.to_numeric(row.get('volume'),errors='coerce')
            capacity = max(0,float(volume)*costs['volumeParticipation']) if pd.notna(volume) else 0
            if units > capacity:
                units = quantity(code,capacity,side,sellable)
                reasons.append('最新已知成交量参与率限制' if pd.notna(volume) else '最新已知成交量缺失')
            if side == 'buy':
                funded = affordable(code, units, price, cash, date, costs)
                if funded < units:
                    reasons.append('可用现金及费用限制')
                units = funded
            if units < requested - 1:
                reasons.append('申报数量取整或容量不足')
            if not executable:
                units = 0
                reasons.append('组合约束冲突，清单不可执行')
            amount = units * price
            cost = fees(amount, side, date, costs)
            cash += amount - cost['total'] if side == 'sell' else -amount - cost['total']
            actual[code] += -units if side == 'sell' else units
            rows.append(dict(symbol=code, side=side, quantity=units, estimatedPrice=price,
                             estimatedAmount=amount, estimatedFees=cost['total'], reason='；'.join(reasons) or '按目标权重调整',
                             currentWeight=float(before[code]), targetWeight=float(weights.get(code, 0))))
    after_nav = cash + float((actual*close).sum())
    after = actual * close / after_nav
    if after.sum() > config['grossExposure'] + 2e-6:
        conflicts.append('数量取整和费用后总仓位超过上限')
    if config['maxWeight'] is not None and (after > config['maxWeight'] + 2e-6).any():
        conflicts.append('数量取整后单股仓位超过上限')
    if config['industryCap'] is not None:
        if groups.reindex(after[after>0].index).isna().any():
            conflicts.append('实际持仓行业覆盖缺失')
        elif (after.groupby(groups.reindex(after.index)).sum() > config['industryCap'] + 2e-6).any():
            conflicts.append('数量取整后行业仓位超过上限')
    if config['turnoverLimit'] is not None and portfolio_turnover(after.to_numpy(), before.to_numpy()) > config['turnoverLimit'] + 2e-6:
        conflicts.append('数量取整和费用后含现金换手超过上限')
    return pd.DataFrame(rows, columns=['symbol','side','quantity','estimatedPrice','estimatedAmount','estimatedFees','reason','currentWeight','targetWeight']), after, cash, conflicts


def run(project, params, output, progress):
    import joblib
    config = dict(params or project.get('settings', {}).get('selection', {}))
    if not config.get('enabled'):
        raise ValueError('请先明确启用选股策略和模型方案')
    strategy, model_params = config.get('strategy', {}), config.get('model', {})
    if not strategy or not model_params:
        raise ValueError('选股需要已确认的完整策略和模型配置')
    if config.get('retrain', 'monthly') != 'monthly':
        raise ValueError('当前仅支持每月首次运行重训')
    if config.get('updateData', True):
        data.update(project, dict(source=config.get('dataSource','baostock'), financials=config.get('financials',True),
                                 startDate=project.get('startDate') or '2015-01-01',
                                 endDate=update_end_date(),
                                 factorProcessing=model_params.get('factorProcessing', {}), portfolio=strategy.get('portfolio', {})),
                    lambda value, message: progress(value*.4, message))
    prices = completed_prices(engines.prepare(project, output, lambda value,message: progress(.4+value*.1,message)))
    if prices.empty:
        raise ValueError('没有已完成交易日的行情')
    date = pd.Timestamp(prices.date.max())
    month = date.strftime('%Y-%m')
    snapshot = positions.get(project)
    if snapshot.get('asOfDate') and pd.Timestamp(snapshot['asOfDate']) > date:
        raise ValueError('持仓日期晚于最新完成行情，无法一致估值')
    state_path = Path(project['path'])/'.research/selection-model.json'
    state = read_json(state_path, {})
    model_path = Path(project['path'])/state.get('path', '.research/missing-model')
    artifacts = []
    if state.get('month') != month or state.get('parameters') != model_params or not model_path.is_file():
        training = output/'monthly_model'
        training.mkdir(parents=True, exist_ok=True)
        # Refit the confirmed estimator on the newest admissible training rows.
        # Future H+1 opens are excluded; there is no parameter search here.
        feature_params = {**model_params, 'startDate': str(prices.date.min()), 'endDate': str(date)}
        x = engines.features(project, feature_params, prices)
        from .processing import label_prices
        h = int(model_params.get('labelHorizon',5))
        if not 1 <= h <= 252:
            raise ValueError('标签周期必须为1至252')
        market_label = label_prices(prices, model_params.get('labelMode','next_open'))
        label = (market_label.shift(-h)/market_label-1).stack().rename('label')
        label.index.names = x.index.names
        frame = x.join(label).dropna(subset=['label'])
        years = int(model_params.get('validation',{}).get('trainYears',3))
        frame = frame[frame.index.get_level_values(0) >= date-pd.DateOffset(years=years)]
        if frame.empty:
            raise ValueError('月度重训缺少已实现标签')
        estimator = engines.model_estimator(model_params)
        estimator.fit(frame[x.columns], frame.label)
        model_path = training/'model.joblib'
        joblib.dump(estimator, model_path)
        state = dict(month=month,parameters=model_params,path=model_path.relative_to(Path(project['path'])).as_posix(),
                     updatedAt=now(),dataDate=date.strftime('%Y-%m-%d'),trainingRows=len(frame),labelHorizon=h,
                     trainingStart=str(frame.index.get_level_values(0).min())[:10],
                     trainingEnd=str(frame.index.get_level_values(0).max())[:10])
        write_json(state_path,state)
        artifacts.append(dict(name='monthly_model',path=str(model_path),type='joblib'))
    estimator = joblib.load(model_path)
    x = engines.features(project, {**model_params,'startDate':str(date),'endDate':str(date)}, prices)
    if x.empty:
        raise ValueError('最新完成交易日没有有效候选因子')
    scores = pd.Series(estimator.predict(x),index=x.index.get_level_values('instrument'),name='score')
    template = strategy.get('template','model_score')
    factor_contributions = None
    if template in {'single_factor','multi_factor'}:
        x = engines.features(project,{**strategy,'startDate':str(date),'endDate':str(date)},prices)
        if template=='single_factor' and len(x.columns)!=1:
            raise ValueError('单因子模板必须选择一个因子')
        factor_contributions = x.groupby(level=0).rank(pct=True).mul(pd.Series({name:float(strategy.get('weights',{}).get(name,1)) for name in x.columns}))
        scores = factor_contributions.sum(axis=1,min_count=len(x.columns))
        scores.index = scores.index.get_level_values('instrument')
        scores.name = 'score'
    elif template!='model_score':
        raise ValueError('未知选股策略模板')
    if strategy.get('code'):
        scoped_score = scores.copy()
        scoped_score.index = pd.MultiIndex.from_product([[date],scores.index],names=['datetime','instrument'])
        scope = dict(pd=pd,prices=prices.copy(),scores=scoped_score.copy())
        exec(compile(strategy['code'],'<selection-strategy>','exec'),scope)
        changed = scope.get('scores')
        if not isinstance(changed,pd.Series) or not changed.index.equals(scoped_score.index):
            raise ValueError('策略代码必须保留日期/股票索引')
        scores = pd.Series(pd.to_numeric(changed,errors='raise').to_numpy(),index=scores.index,name='score')
    scores = scores.replace([np.inf,-np.inf],np.nan).dropna().sort_values(ascending=False)
    latest = prices[prices.date.eq(date)].set_index('symbol').copy()
    if 'rawClose' not in latest:
        latest['rawClose'] = latest.close/latest.get('factor', 1.)
    owned = pd.DataFrame(snapshot['rows'],columns=['symbol','quantity','sellableQuantity'])
    nav = float(snapshot['cash'])
    previous, locked = {}, {}
    for row in owned.to_dict('records'):
        if row['symbol'] not in latest.index or not np.isfinite(latest.loc[row['symbol'],'rawClose']):
            raise ValueError('持仓最新价格缺失：'+row['symbol'])
        nav += row['quantity']*float(latest.loc[row['symbol'],'rawClose'])
    if nav <= 0:
        raise ValueError('请填写持仓或可用现金，当前资产为0')
    for row in owned.to_dict('records'):
        price = float(latest.loc[row['symbol'],'rawClose'])
        previous[row['symbol']] = row['quantity']*price/nav
        locked[row['symbol']] = (row['quantity']-row['sellableQuantity'])*price/nav
    portfolio = {**DEFAULTS,**strategy.get('portfolio',{})}
    if portfolio['returnSource']=='model' and (template!='model_score' or strategy.get('code')):
        raise ValueError('模型预期收益要求未改写的模型收益预测，排名/自定义评分不能替代')
    chosen = scores.head(int(strategy.get('topN',30)))
    names = chosen.index.union(pd.Index(previous))
    groups = industries(project,date,names)
    returns = prices.pivot(index='date',columns='symbol',values='close').sort_index().pct_change(fill_method=None)
    expected = (1+chosen)**(252/int(model_params.get('labelHorizon',5)))-1 if portfolio['returnSource']=='model' else None
    result = construct_portfolio(chosen,returns.loc[:date],portfolio,pd.Series(previous,dtype=float),groups,pd.Series(locked,dtype=float),expected)
    orders, actual, cash, conflicts = estimate_orders(snapshot,result['weights'],latest,cost_config(strategy),portfolio,groups,result['executable'])
    conflicts = result['conflicts']+conflicts
    candidates = scores.rename_axis('symbol').reset_index()
    candidate_features = x.droplevel(0).rename_axis('symbol')
    candidates = candidates.merge(candidate_features,left_on='symbol',right_index=True,how='left')
    if factor_contributions is not None:
        contribution,base = factor_contributions.to_numpy(),0.
    elif model_params.get('model') == 'ridge':
        transformed = estimator[:-1].transform(x)
        contribution = transformed * estimator[-1].coef_
        base = float(estimator[-1].intercept_)
    else:
        explained = estimator.predict(x, pred_contrib=True)
        contribution, base = explained[:,:-1], explained[:,-1]
    attribution = pd.DataFrame(contribution,index=x.index.get_level_values('instrument'),columns=x.columns).rename_axis('symbol')
    attribution['baseValue'] = base
    targets = pd.DataFrame({'targetWeight':result['weights'],'estimatedActualWeight':actual,
                            'riskContribution':result['riskContributions']}).rename_axis('symbol')
    artifacts += [engines.save_table(output,name,table) for name,table in [('candidates',candidates),('factor_contributions',attribution),('target_weights',targets),('rebalance',orders),('positions',pd.DataFrame(snapshot['rows']))]]
    progress(.95,'最新评分、目标组合及估算调仓清单已保存')
    return dict(metrics=dict(candidates=len(scores),targetExposure=float(result['weights'].sum()),estimatedCash=cash),
                artifacts=artifacts,parameters=config,summary='每日选股与估算调仓清单',
                details=dict(dataDate=date.strftime('%Y-%m-%d'),modelUpdatedAt=state['updatedAt'],executable=result['executable'] and not conflicts,
                             conflicts=conflicts,warnings=result['warnings']+['按最新完成交易日收盘估算；实际开盘价格、停复牌、涨跌停和成交量须届时确认。'],
                             positionsSnapshot=snapshot,modelTrainingRows=state.get('trainingRows'),trainingStart=state.get('trainingStart'),
                             trainingEnd=state.get('trainingEnd'),labelHorizon=state.get('labelHorizon'),
                             factorAttribution=('自定义代码改写前的贡献' if strategy.get('code') else '因子排名乘权重' if factor_contributions is not None else 'Ridge标准化空间线性贡献' if model_params.get('model')=='ridge' else 'LightGBM TreeSHAP贡献')))
