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


def run(project, params, output, progress, snapshot=None, strategy_snapshots=None, score_only=False, daily_plan_snapshots=None, store=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if daily_plan_snapshots is not None:
        if store is None:raise ValueError('每日方案需要共享研究存储')
        return run_daily(store,project,params,output,progress,snapshot,daily_plan_snapshots)
    if strategy_snapshots is not None:
        return run_multi(project, params, output, progress, snapshot, strategy_snapshots)
    import joblib
    settings = project.get('settings', {})
    config = dict(params or settings.get('selection', {}))
    if not params and project.get('strategyId'):
        config.update(enabled=True, strategy=settings.get('backtest') or config.get('strategy',{}), model=settings.get('model') or config.get('model',{}))
    if not config.get('enabled'):
        raise ValueError('请先明确启用选股策略和模型方案')
    strategy, model_params = config.get('strategy', {}), config.get('model', {})
    if not strategy or strategy.get('template', 'model_score') == 'model_score' and not model_params:
        raise ValueError('选股需要已确认的完整策略和模型配置')
    if config.get('retrain', 'monthly') != 'monthly':
        raise ValueError('当前仅支持每月首次运行重训')
    snapshot = snapshot if snapshot is not None else positions.get(project)
    held_codes = [row['symbol'] for row in snapshot['rows'] if row['quantity']>0]
    prepare_project = {**project,'universe':dict(project['universe'])}
    if project['universe']['source']=='manual' and project['universe']['symbols']:
        prepare_project['universe']['symbols'] = sorted(set(map(data.symbol,project['universe']['symbols'])) | set(held_codes))
    if config.get('updateData', True):
        if not project.get('startDate'):
            raise ValueError('运行选股前请明确选择研究开始日期')
        update_params = dict(source=config.get('dataSource','baostock'), financials=config.get('financials',True),
                                 startDate=project['startDate'],corporateActions=True,
                                 endDate=update_end_date(),
                                 factorProcessing=model_params.get('factorProcessing', {}), portfolio=strategy.get('portfolio', {}))
        data.update(prepare_project, update_params,
                    lambda value, message: progress(value*.4, message))
        if held_codes and project['universe']['source']!='manual':
            holdings_project = {**project,'universe':{**project['universe'],'source':'manual','symbols':held_codes}}
            data.update(holdings_project,update_params,lambda value,message:progress(.35+value*.05,message))
    prices = completed_prices(engines.prepare(prepare_project, output, lambda value,message: progress(.4+value*.1,message)))
    if prices.empty:
        raise ValueError('没有已完成交易日的行情')
    date = pd.Timestamp(prices.date.max())
    month = date.strftime('%Y-%m')
    if strategy.get('template', 'model_score') == 'model_score':
        state_path = Path(project['path'])/'.research'/('strategies/' + project['strategyId'] + '/selection-model.json' if project.get('strategyId') else 'selection-model.json')
        state = read_json(state_path, {})
        model_path = Path(project['path'])/state.get('path', '.research/missing-model')
        artifacts = []
        model_context = {'universe':project['universe'],'dataPath':project.get('inputCacheIdentity',{}).get('sourceRoot') or str(Path(data.project_data(project)['path']).resolve()), 'source':read_json(Path(data.project_data(project)['path'])/'data/source.json',{}).get('source','import')}
        native_model=model_params.get('model') in {'native_torch','native_generated_predictions'}
        if native_model:
            from .rd_agent import native_code,fit_native_asof,predict_native
            model_context['nativeCode']=native_code(project,model_params)
        future_native_state=native_model and state.get('trainedAsOf') and pd.Timestamp(state['trainedAsOf'])>date
        if state.get('month') != month or state.get('parameters') != model_params or state.get('context') != model_context or not model_path.is_file() or future_native_state:
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
            if native_model:
                model_path,observed,events=fit_native_asof(project,model_params,x,prices,date,training)
                model_path=Path(model_path)
                artifacts.append(engines.save_table(output,'native_training_events',events))
            else:
                estimator = engines.model_estimator(model_params)
                estimator.fit(frame[x.columns], frame.label)
                model_path = training/'model.joblib'
                joblib.dump(estimator, model_path)
            state = dict(month=month,parameters=model_params,context=model_context,path=str(model_path.resolve()),
                         updatedAt=now(),dataDate=date.strftime('%Y-%m-%d'),trainingRows=len(frame),labelHorizon=h,
                         trainingStart=str(frame.index.get_level_values(0).min())[:10],
                         trainingEnd=str(frame.index.get_level_values(0).max())[:10])
            if native_model:state.update(observed,trainingRows=observed['trainRows'])
            write_json(state_path,state)
            artifacts.append(dict(name='monthly_model',path=str(model_path),type='json' if native_model else 'joblib'))
        estimator = None if native_model else joblib.load(model_path)
        x = engines.features(project, {**model_params,'startDate':str(prices.date.min()) if native_model else str(date),'endDate':str(date)}, prices)
        if x.empty:
            raise ValueError('最新完成交易日没有有效候选因子')
        if native_model:
            predicted=predict_native(model_path,x,date,output/'native_inference')
            x=x.reindex(predicted.index)
            scores=predicted.droplevel(0)
        else:scores = pd.Series(estimator.predict(x),index=x.index.get_level_values('instrument'),name='score')
    else:
        state = {'updatedAt': None}
        artifacts = []
        estimator = None
        x = pd.DataFrame()
        scores = pd.Series(dtype=float)
    template = strategy.get('template','model_score')
    factor_contributions = None
    if template in {'single_factor','multi_factor'}:
        independent_rules=bool(strategy.get('dailyCode') or strategy.get('rules')) and not strategy.get('factorIds')
        if independent_rules:
            from .history import expected_rows
            query_panel=None
            if project['universe'].get('query'):
                from .market import dated_panel
                query_panel=dated_panel(project,prices)
            index,_=expected_rows(project,prices,[date],query_panel)
            x=pd.DataFrame(index=index)
        else:x = engines.features(project,{**strategy,'startDate':str(date),'endDate':str(date)},prices)
        if template=='single_factor' and len(x.columns)!=1 and not independent_rules:
            raise ValueError('单因子模板必须选择一个因子')
        factor_contributions = x.groupby(level=0).rank(pct=True).mul(pd.Series({name:float(strategy.get('weights',{}).get(name,1)) for name in x.columns}))
        scores = factor_contributions.sum(axis=1,min_count=len(x.columns)) if len(x.columns) else pd.Series(index=x.index,dtype=float)
        scores.index = scores.index.get_level_values('instrument')
        scores.name = 'score'
    elif template!='model_score':
        raise ValueError('未知选股策略模板')
    from .strategy import decide_day
    decision = decide_day(dict(date=date,prices=prices,scores=scores,features=x,
        holdings={r['symbol']:{k:v for k,v in r.items() if k!='symbol'} for r in snapshot['rows']},
        cash=snapshot['cash'],state=config.get('strategyState',{})),strategy)
    scores = decision['scores']
    scores = scores.replace([np.inf,-np.inf],np.nan).dropna().sort_values(ascending=False)
    latest = prices[prices.date.eq(date)].set_index('symbol').copy()
    if 'rawClose' not in latest:
        latest['rawClose'] = latest.close/latest.get('factor', 1.)
    if score_only:
        portfolio = {**DEFAULTS, **strategy.get('portfolio', {}), 'turnoverLimit': None}
        if portfolio['returnSource'] == 'model' and (template != 'model_score' or strategy.get('code')):
            raise ValueError('模型预期收益要求真实模型收益预测')
        chosen = scores.head(int(strategy.get('topN', 30)))
        returns = prices.pivot(index='date', columns='symbol', values='close').sort_index().pct_change(fill_method=None)
        expected = (1+chosen)**(252/int(model_params.get('labelHorizon', 5)))-1 if portfolio['returnSource'] == 'model' else None
        proposed = construct_portfolio(chosen, returns.loc[:date], portfolio, industries=industries(project,date,chosen.index), expected_returns=expected)
        if decision['targets'] is not None:
            desired=pd.Series(decision['targets'],dtype=float)
            weights,problems=constrain_merged(desired,pd.Series(dtype=float),pd.Series(dtype=float),industries(project,date,desired.index),portfolio)
            proposed.update(weights=weights,conflicts=problems,executable=not problems)
        if strategy.get('portfolio', {}).get('turnoverLimit') is not None:
            proposed['warnings'].append('策略换手上限不对独立虚拟账户计算；请使用全局组合换手上限。')
        return dict(weights=proposed['weights'], scores=scores, market=latest, date=date, project=project, state=state, warnings=proposed['warnings'], conflicts=proposed['conflicts'], executable=proposed['executable'], features=x, artifacts=artifacts)
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
    if decision['targets'] is not None:
        desired=pd.Series(decision['targets'],dtype=float)
        groups=industries(project,date,desired.index.union(pd.Index(previous)))
        weights,problems=constrain_merged(desired,pd.Series(previous,dtype=float),pd.Series(locked,dtype=float),groups,portfolio)
        result.update(weights=weights,conflicts=problems,executable=not problems)
    orders, actual, cash, conflicts = estimate_orders(snapshot,result['weights'],latest,cost_config(strategy),portfolio,groups,result['executable'])
    conflicts = result['conflicts']+conflicts
    candidates = scores.rename_axis('symbol').reset_index()
    candidate_features = x.droplevel(0).rename_axis('symbol')
    candidates = candidates.merge(candidate_features,left_on='symbol',right_index=True,how='left')
    if factor_contributions is not None:
        contribution,base = factor_contributions.to_numpy(),0.
    elif model_params.get('model') in {'native_torch','native_generated_predictions'}:
        contribution=np.full((len(x),len(x.columns)),np.nan)
        base=float('nan')
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
                details=dict(strategyState=decision['nextState'],ruleReasons=decision['reasons'],dataDate=date.strftime('%Y-%m-%d'),valuationDate=date.strftime('%Y-%m-%d'),bookAsOfDate=snapshot.get('asOfDate'),modelUpdatedAt=state['updatedAt'],executable=result['executable'] and not conflicts,
                             conflicts=conflicts,warnings=result['warnings']+['按最新完成交易日收盘估算；实际开盘价格、停复牌、涨跌停和成交量须届时确认。'],
                             positionsSnapshot=snapshot,modelTrainingRows=state.get('trainingRows'),trainingStart=state.get('trainingStart'),
                             trainingEnd=state.get('trainingEnd'),labelHorizon=state.get('labelHorizon'),
                             factorAttribution=('自定义代码改写前的贡献' if strategy.get('code') else '因子排名乘权重' if factor_contributions is not None else '原生Torch模型未提供因子归因' if model_params.get('model') in {'native_torch','native_generated_predictions'} else 'Ridge标准化空间线性贡献' if model_params.get('model')=='ridge' else 'LightGBM TreeSHAP贡献')))


def merge_allocations(proposals):
    """Weights remain fractions of global NAV, including unallocated cash."""
    rows = []
    for reference, result in proposals:
        for code, weight in result['weights'].items():
            rows.append(dict(projectId=reference['projectId'], strategyId=reference['strategyId'], symbol=code,
                             allocation=reference['allocation'], strategyWeight=float(weight),
                             targetWeight=float(weight)*reference['allocation'], score=float(result['scores'].get(code, np.nan))))
    frame = pd.DataFrame(rows, columns=['projectId','strategyId','symbol','allocation','strategyWeight','targetWeight','score'])
    return frame.groupby('symbol').targetWeight.sum(), frame


def constrain_merged(desired, current, locked, groups, config):
    """Project the merged target once; never maximize or renormalize its budget."""
    import cvxpy as cp
    names = desired.index.union(current.index)
    target, before, lower = [series.reindex(names, fill_value=0).to_numpy(float) for series in (desired,current,locked)]
    for key in ('grossExposure','maxWeight','industryCap','turnoverLimit'):
        value = config[key]
        if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or not 0 <= value <= 1):
            raise ValueError(key+'必须为0至1的比例')
    if not len(names):
        return desired, []
    budget = min(config['grossExposure'],float(desired.sum()))
    feasible = bool(np.all(target >= lower-1e-9) and target.sum() <= budget+1e-9)
    if config['maxWeight'] is not None:
        feasible = feasible and bool(np.all(target <= config['maxWeight']+1e-9))
    if config['turnoverLimit'] is not None:
        feasible = feasible and portfolio_turnover(target,before) <= config['turnoverLimit']+1e-9
    if config['industryCap'] is not None:
        mapped = groups.reindex(names)
        feasible = feasible and not mapped.isna().any() and bool((pd.Series(target,index=names).groupby(mapped).sum()<=config['industryCap']+1e-9).all())
    if feasible:
        return pd.Series(target,index=names), []
    w = cp.Variable(len(names))
    constraints = [w >= lower, w <= (config['maxWeight'] if config['maxWeight'] is not None else 1), cp.sum(w) <= min(config['grossExposure'], float(desired.sum()))]
    if config['turnoverLimit'] is not None:
        constraints.append((cp.norm1(w-before)+cp.abs(cp.sum(w)-before.sum()))/2 <= config['turnoverLimit'])
    if config['industryCap'] is not None:
        mapped = groups.reindex(names)
        if mapped.isna().any():
            return current, ['全局组合行业覆盖缺失']
        for group in mapped.unique():
            constraints.append(cp.sum(w[np.flatnonzero(mapped.eq(group).to_numpy())]) <= config['industryCap'])
    problem = cp.Problem(cp.Minimize(cp.sum_squares(w-target)), constraints)
    try:
        problem.solve(solver='CLARABEL',tol_gap_abs=1e-9,tol_feas=1e-9,tol_gap_rel=1e-9)
    except cp.error.SolverError:
        return current, ['全局组合约束求解失败']
    if problem.status != cp.OPTIMAL or w.value is None:
        return current, ['全局组合约束与不可卖持仓或资金占比冲突']
    values = np.asarray(w.value).reshape(-1)
    values[np.abs(values)<1e-8]=0
    return pd.Series(values,index=names), []


def run_multi(project, params, output, progress, snapshot, strategy_snapshots):
    if not strategy_snapshots:
        raise ValueError('请选择至少一个启用策略')
    snapshot = snapshot if snapshot is not None else positions.get(project)
    proposals, all_artifacts = [], []
    for index, reference in enumerate(strategy_snapshots):
        scoped = reference['project']
        settings = scoped.get('settings', {})
        selection = {**settings.get('selection', {}), 'enabled': True,
                     'strategy': settings.get('backtest') or settings.get('selection', {}).get('strategy', {}),
                     'model': settings.get('model') or settings.get('selection', {}).get('model', {}),
                     'updateData': params.get('updateData', True)}
        target = output / ('strategy_' + str(index))
        target.mkdir(parents=True, exist_ok=True)
        result = run(scoped, selection, target, lambda value,message: progress((index+value)/len(strategy_snapshots)*.8,message), snapshot=snapshot, score_only=True)
        proposals.append((reference,result))
        all_artifacts.extend({**a,'name':f"strategy_{index}_"+a['name']} for a in result['artifacts'])
        candidate = result['scores'].rename_axis('symbol').reset_index()
        candidate = candidate.merge(result['features'].droplevel(0).rename_axis('symbol'),left_on='symbol',right_index=True,how='left')
        all_artifacts.append(engines.save_table(output, f'strategy_{index}_candidates', candidate))
    return finish_multi(project,params,output,snapshot,proposals,all_artifacts)


def finish_multi(project,params,output,snapshot,proposals,all_artifacts):
    dates = {result['date'] for _,result in proposals}
    if len(dates) != 1:
        raise ValueError('启用策略最新完成行情日期不一致，请更新数据后生成')
    date = next(iter(dates))
    market_rows = pd.concat([result['market'].reset_index() for _,result in proposals])
    for code, records in market_rows.groupby('symbol'):
        raw = pd.to_numeric(records.rawClose,errors='coerce')
        if raw.notna().any() and not np.allclose(raw,raw.iloc[0],rtol=1e-7,equal_nan=True):
            raise ValueError('不同策略数据的同日原始收盘价不一致：'+code)
    market = market_rows.drop_duplicates('symbol').set_index('symbol')
    nav = float(snapshot['cash'])
    for row in snapshot['rows']:
        if row['symbol'] not in market.index or not np.isfinite(market.loc[row['symbol'],'rawClose']):
            raise ValueError('全局持仓最新估值价格缺失：'+row['symbol'])
        nav += row['quantity']*float(market.loc[row['symbol'],'rawClose'])
    if nav <= 0:
        raise ValueError('请填写全局持仓或可用现金')
    current = pd.Series({row['symbol']:row['quantity']*float(market.loc[row['symbol'],'rawClose'])/nav for row in snapshot['rows']},dtype=float)
    locked = pd.Series({row['symbol']:(row['quantity']-row['sellableQuantity'])*float(market.loc[row['symbol'],'rawClose'])/nav for row in snapshot['rows']},dtype=float)
    desired, contributions = merge_allocations(proposals)
    config = {**DEFAULTS, **params.get('portfolio', {})}
    names = desired.index.union(current.index)
    groups = pd.Series(index=names,dtype=object)
    for _, result in proposals:
        observed = industries(result['project'],date,names)
        groups = groups.combine_first(observed)
    weights, conflicts = constrain_merged(desired,current,locked,groups,config)
    conflicts += [conflict for _,result in proposals for conflict in result['conflicts']]
    orders, actual, cash, order_conflicts = estimate_orders(snapshot,weights,market,cost_config(params),config,groups,not conflicts)
    conflicts += order_conflicts
    targets = pd.DataFrame({'unconstrainedWeight':desired,'targetWeight':weights,'estimatedActualWeight':actual}).rename_axis('symbol')
    all_artifacts += [engines.save_table(output,name,frame) for name,frame in [('strategy_contributions',contributions),('candidates',contributions),('target_weights',targets),('rebalance',orders),('positions',pd.DataFrame(snapshot['rows']))]]
    return dict(metrics=dict(candidates=len(desired),targetExposure=float(weights.sum()),estimatedCash=cash),artifacts=all_artifacts,
                parameters={**params,'strategies':[{key:value for key,value in ref.items() if key!='project'} for ref,_ in proposals]},summary='多策略合并选股与全局净调仓清单',
                details=dict(dataDate=str(date)[:10],valuationDate=str(date)[:10],bookAsOfDate=snapshot.get('asOfDate'),positionsSnapshot=snapshot,strategies=[{'projectId':ref['projectId'],'strategyId':ref['strategyId'],'allocation':ref['allocation'],'configuration':ref['project'],'model':result['state']} for ref,result in proposals],
                             executable=not conflicts,conflicts=conflicts,unallocatedCashWeight=1-sum(ref['allocation'] for ref,_ in proposals),warnings=list(dict.fromkeys(['按已完成日收盘估算，下一交易日实际成交条件需确认。']+[warning for _,result in proposals for warning in result['warnings']]))))


def run_daily(store,project,params,output,progress,snapshot,references):
    from copy import deepcopy
    from . import screening_run
    if not references:raise ValueError('请选择至少一个启用每日方案')
    if snapshot is None:raise ValueError('每日方案缺少全局持仓快照')
    proposals=[];artifacts=[]
    for i,reference in enumerate(references):
        plan=deepcopy(reference['planSnapshot'])
        # Daily use advances the date, retaining the saved screening configuration.
        plan['date']=params.get('date') or update_end_date()
        target=output/('daily_'+str(i));target.mkdir(parents=True,exist_ok=True)
        screened=screening_run.run(store,reference['project'],dict(plan=plan,allowPartial=False),target,
            lambda v,m:progress((i+v)/len(references)*.8,m),daily_snapshot=snapshot)
        context=screened['_daily'];frame=context['frame'];prices=context['prices'];date=context['date']
        selected=frame[frame.status.eq('included')].set_index('symbol')
        scores=selected.score.astype(float)
        # Pure boolean conditions have no score: equal selection strength is explicit.
        if plan['mode']=='conditions' and scores.isna().all():scores=pd.Series(1.,index=selected.index)
        if not np.isfinite(scores).all():raise ValueError('每日候选评分缺失，不能生成目标')
        strategy=context['strategy'] or {}
        if context['strategy'] and context['targets'] is None:scores=scores.sort_values(ascending=False).head(int(strategy.get('topN',30)))
        config={**DEFAULTS,**strategy.get('portfolio',{}),'turnoverLimit':None}
        returns=prices.pivot(index='date',columns='symbol',values='close').sort_index().pct_change(fill_method=None)
        expected=None
        if config['returnSource']=='model':
            if context['model'] is None or strategy.get('code'):raise ValueError('模型预期收益要求真实月度模型预测')
            horizon=context['model']['state']['parameters'].get('labelHorizon',5)
            expected=(1+context['model']['scores'].reindex(scores.index))**(252/int(horizon))-1
        built=construct_portfolio(scores,returns.loc[:date],config,industries=industries(context['project'],date,scores.index),expected_returns=expected)
        if context['targets'] is not None:
            desired=pd.Series(context['targets'],dtype=float)
            desired=desired.where(desired.index.isin(scores.index),0.)
            weights,conflicts=constrain_merged(desired,pd.Series(dtype=float),pd.Series(dtype=float),industries(context['project'],date,desired.index),config)
            built.update(weights=weights,conflicts=conflicts,executable=not conflicts)
        latest=prices[prices.date.eq(date)].set_index('symbol').copy()
        if 'rawClose' not in latest:latest['rawClose']=latest.close/latest.get('factor',1.)
        ref=dict(projectId=reference['project'].get('id'),strategyId=reference['id'],allocation=reference['allocation'],project=context['project'],dailyPlanId=reference['id'],planVersion=reference['planVersion'])
        result=dict(weights=built['weights'],scores=scores,market=latest,date=date,project=context['project'],
            state=context['model']['state'] if context['model'] else {},warnings=built['warnings'],conflicts=built['conflicts'])
        proposals.append((ref,result))
        artifacts.extend({**a,'name':f'daily_{i}_'+a['name']} for a in screened['artifacts'])
        if context['model']:artifacts.extend({**a,'name':f'daily_{i}_'+a['name']} for a in context['model']['artifacts'])
    result=finish_multi(project,params,output,snapshot,proposals,artifacts)
    result['summary']='每日固定方案合并与全局净调仓清单'
    result['parameters']=deepcopy(params)
    result['details']['dailyPlans']=[{k:deepcopy(v) for k,v in r.items() if k!='project'} for r in references]
    return result
