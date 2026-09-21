"""Serializable raw-share account; one day is computed before its caller commits."""
from copy import deepcopy
from collections import defaultdict
import math
import pandas as pd
from . import corporate_actions


def create(cash, holdings=None, date=None):
    if not math.isfinite(float(cash)) or cash<0:raise ValueError('初始现金无效')
    holdings=deepcopy(holdings or {})
    for symbol,h in holdings.items():
        quantity=float(h['quantity']);sellable=float(h.get('sellableQuantity',quantity))
        if not math.isfinite(quantity+sellable) or quantity<0 or not 0<=sellable<=quantity or not quantity.is_integer() or not sellable.is_integer():
            raise ValueError('初始持仓数量或可卖数量无效: '+symbol)
        locked=quantity-sellable
        bought=float(h.get('boughtToday',0))
        if bought<0 or bought>locked or not bought.is_integer():raise ValueError('初始当日买入数量无效: '+symbol)
        if locked>bought:raise ValueError('初始不可卖数量缺释放信息；请提供明确的当日买入 boughtToday 数量: '+symbol)
        h['quantity']=int(quantity);h['sellableQuantity']=int(sellable)
    return dict(cash=float(cash),holdings=holdings,asOfDate=date,
                receivables=0.,pendingShares=0.,entitlements={},processedActions=[],state={})


def advance_day(account, date, prices, decision, costs, actions=None, exchange=None):
    """Execute prior-close target quantities and return a new account, never persist.

    decision: {date, quantities:{symbol:raw target shares}, reasons, nextState}.
    No strategy code receives this execution day's prices through this function.
    """
    from qlib.backtest.position import Position
    from qlib.backtest.decision import Order
    from .execution import raw_exchange
    day=pd.Timestamp(date).normalize();stamp=str(day.date())
    if account.get('asOfDate') and pd.Timestamp(account['asOfDate'])>=day:
        raise ValueError('账户日期已完成，不能重复成交')
    if decision and pd.Timestamp(decision['date'])>=day:raise ValueError('只能执行此前交易日信号')
    account=deepcopy(account)
    actions=[] if actions is None else actions
    if len(actions):actions=corporate_actions.validate(pd.DataFrame(actions))
    action_rows=actions.to_dict('records') if isinstance(actions,pd.DataFrame) else actions
    today=prices[pd.to_datetime(prices.date).eq(day)].set_index('symbol')
    previous=prices[pd.to_datetime(prices.date).lt(day)].sort_values('date').groupby('symbol').tail(1).set_index('symbol')
    for symbol,h in account['holdings'].items():
        if not h['quantity'] and not h.get('pendingQuantity',0):continue
        if symbol not in today.index or not math.isfinite(float(today.loc[symbol,'rawClose'])) or float(today.loc[symbol,'rawClose'])<=0:
            raise ValueError('持仓缺当日原始估值/退市处置资料: '+symbol)
        if symbol in previous.index:
            old=previous.loc[symbol].get('factor');new=today.loc[symbol].get('factor')
            if pd.notna(old) and pd.notna(new) and float(old)>0 and abs(float(new)/float(old)-1)>1e-5:
                covered=[e for e in action_rows if e.get('status')=='implemented' and e['symbol']==symbol and e['exDate']==stamp]
                if not covered:raise ValueError(f'{symbol} {stamp} 持仓跨复权变化但缺公司行动记录，无法核算真实现金/股数')
    # A caller may skip weekends, but cannot skip an uncommitted trading session.
    if account.get('asOfDate'):
        skipped=prices[pd.to_datetime(prices.date).gt(pd.Timestamp(account['asOfDate'])) & pd.to_datetime(prices.date).lt(day)]
        if not skipped.empty:raise ValueError('账户存在尚未完成的交易日，请从最后完成日逐日续算')
    for h in account['holdings'].values():
        h['sellableQuantity']=h.get('sellableQuantity',0)+h.pop('boughtToday',0)
    account,events=corporate_actions.apply(account,stamp,actions,'open')
    today=prices[pd.to_datetime(prices.date).eq(day)].set_index('symbol')
    missing=[s for s,h in account['holdings'].items() if (h['quantity'] or h.get('pendingQuantity',0)) and (s not in today.index or pd.isna(today.loc[s,'rawClose']))]
    if missing:raise ValueError('持仓缺当日原始估值/退市处置资料: '+','.join(missing))
    pending=sum(e['shares']*float(today.loc[e['symbol'],'rawClose']) for k,e in account['entitlements'].items()
        if k+':ex' in account['processedActions'] and k+':listing' not in account['processedActions'] and e['shares'])
    rejected=[];trades=[]
    exchange=exchange or raw_exchange(prices,costs,rejected)
    rejection_start=len(exchange.rejections)
    exchange.sellable={s:h['sellableQuantity'] for s,h in account['holdings'].items()}
    position=Position(cash=account['cash'],position_dict={s:{'amount':h['quantity'],'price':float(today.loc[s,'rawClose'])}
        for s,h in account['holdings'].items() if h['quantity']})
    quantities=deepcopy((decision or {}).get('quantities',{}))
    # A previous-close target is expressed in that day's share denomination.
    if decision and decision.get('quantityBasis')=='signal_date':
        for event in actions.to_dict('records') if isinstance(actions,pd.DataFrame) else actions:
            if event.get('status')=='implemented' and event.get('exDate')==stamp and event['symbol'] in quantities:
                quantities[event['symbol']] *= 1+event['bonusRatio']
    orders=[]
    for symbol,target in quantities.items():
        if not math.isfinite(float(target)) or target<0:raise ValueError('目标股数无效')
        current=account['holdings'].get(symbol,{}).get('quantity',0)
        current+=sum(e['shares'] for k,e in account['entitlements'].items() if e['symbol']==symbol
            and k+':ex' in account['processedActions'] and k+':listing' not in account['processedActions'])
        if target!=current:orders.append((symbol,target-current))
    dealt=defaultdict(float)
    for symbol,delta in sorted(orders,key=lambda r:r[1]>0):
        if symbol not in today.index:
            rejected.append(dict(date=stamp,symbol=symbol,side='buy' if delta>0 else 'sell',requestedQuantity=abs(delta),allowedQuantity=0,reason='缺当日行情'));continue
        order=Order(stock_id=symbol,amount=abs(delta),direction=Order.BUY if delta>0 else Order.SELL,start_time=day,end_time=day)
        order_rejection_start=len(exchange.rejections)
        value,cost,price=exchange.deal_order(order,position=position,dealt_order_amount=dealt)
        quantity=int(round(order.deal_amount));dealt[symbol]+=quantity
        if not quantity:
            if len(exchange.rejections)==order_rejection_start:
                rejected.append(dict(date=stamp,symbol=symbol,side='buy' if delta>0 else 'sell',requestedQuantity=abs(delta),allowedQuantity=0,
                    reason='撮合未成交，撮合器未返回具体限制原因'))
            continue
        h=account['holdings'].setdefault(symbol,dict(quantity=0,sellableQuantity=0,costPrice=0))
        if delta>0:
            basis_quantity=h['quantity']+h.get('pendingQuantity',0)
            h['costPrice']=(basis_quantity*h.get('costPrice',0)+value+cost)/(basis_quantity+quantity)
            h['quantity']+=quantity;h['boughtToday']=h.get('boughtToday',0)+quantity
        else:
            h['quantity']-=quantity;h['sellableQuantity']-=quantity;exchange.sellable[symbol]-=quantity
        breakdown=getattr(order,'research_fees',{})
        trades.append(dict(tradeId=f'{stamp}:{symbol}:{int(delta>0)}',date=stamp,symbol=symbol,direction=int(delta>0),amount=quantity,price=price,value=value,cost=cost,
            requestedQuantity=abs(delta),targetQuantity=quantities[symbol],
            reason='; '.join(str(r.get('reason',r.get('action',''))) for r in (decision or {}).get('reasons',[]) if r.get('symbol')==symbol) or '组合目标调仓',
            rawReferenceOpen=float(today.loc[symbol,'rawOpen']),**{k:v for k,v in breakdown.items() if k!='total'}))
    account['cash']=position.get_cash()
    account['asOfDate']=stamp
    if decision:account['state']=deepcopy(decision.get('nextState',account['state']))
    account,closing=corporate_actions.apply(account,stamp,actions,'close');events+=closing
    value=sum(h['quantity']*float(today.loc[s,'rawClose']) for s,h in account['holdings'].items() if h['quantity'])
    nav=account['cash']+value+account['receivables']+pending
    if exchange.rejections is not rejected:rejected += exchange.rejections[rejection_start:]
    return dict(account=account,trades=trades,unfilled=rejected,events=events,marketValue=value,pendingShareValue=pending,nav=nav)


def make_decision(project, params, account, signal_date, prices, scores, features, nav, portfolio_config):
    """Shared close-of-day strategy and constrained raw target builder; no mutation."""
    from .strategy import decide_day
    from .portfolio import construct_portfolio, risk_estimate
    from .selection import constrain_merged
    from .history import industries
    signal_date=pd.Timestamp(signal_date)
    history=prices[prices.date.le(signal_date)]
    previous=history.sort_values('date').groupby('symbol').tail(1).set_index('symbol')
    choice=decide_day(dict(date=signal_date,prices=history,scores=scores,features=features if features is not None else pd.DataFrame(),
        holdings=account['holdings'],cash=account['cash'],nav=nav,state=account['state']),params)
    current=pd.Series({s:(h['quantity']+h.get('pendingQuantity',0))*float(previous.loc[s,'rawClose'])/nav
        for s,h in account['holdings'].items() if h['quantity'] or h.get('pendingQuantity',0)},dtype=float)
    chosen=choice['scores'];names=chosen.index.union(current.index).union(pd.Index(list(choice['targets'] or {})))
    groups=industries(project,signal_date,names)
    raw=None;warnings=[]
    if choice['targets'] is not None:
        raw=pd.Series(choice['targets'],dtype=float)
        raw=raw.reindex(raw.index.union(current.index),fill_value=0.)
        weights,conflicts=constrain_merged(raw,current,pd.Series(dtype=float),groups,portfolio_config)
    else:
        expected=(1+chosen)**(252/int(params.get('_modelHorizon',5)))-1 if portfolio_config['returnSource']=='model' else None
        returns=history.pivot(index='date',columns='symbol',values='close').pct_change(fill_method=None)
        result=construct_portfolio(chosen,returns,portfolio_config,current,groups,pd.Series(dtype=float),expected)
        weights=result['weights'] if result['executable'] else current
        conflicts=result['conflicts'];warnings=result['warnings']
    quantities={}
    for symbol in weights.index.union(current.index):
        if symbol not in previous.index or not pd.notna(previous.loc[symbol,'rawClose']):raise ValueError('目标缺信号日原始价格: '+symbol)
        quantities[symbol]=float(weights.get(symbol,0))*nav/float(previous.loc[symbol,'rawClose'])
    returns=history.pivot(index='date',columns='symbol',values='close').pct_change(fill_method=None)
    contributions, risk = risk_estimate(returns, weights, portfolio_config)
    return dict(date=str(signal_date.date()),quantities=quantities,quantityBasis='signal_date',nextState=choice['nextState'],
        targetRiskContributions=contributions.to_dict(), riskEstimate=risk,
        reasons=choice['reasons'],targetWeights=weights.to_dict(),ruleTargets=raw.to_dict() if raw is not None else {},conflicts=conflicts,warnings=warnings)


def run_backtest(project, params, prices, scores, trading_dates, schedule, costs, portfolio_config, benchmark, progress, features=None):
    """Historical orchestration of the same public daily account function."""
    from qlib.backtest.position import Position
    from .execution import raw_exchange
    actions=corporate_actions.read(project)
    account=create(float(params.get('capital',1000000)),{r['symbol']:{k:v for k,v in r.items() if k!='symbol'} for r in params.get('initialPositions',[])})
    dates=pd.DatetimeIndex(sorted(prices.date.unique()))
    report=[];positions={};account_snapshots={};trades=[];unfilled=[];targets=[];rule_targets=[];rules=[];events=[];conflicts=[];warnings=[]
    risk_rows=[]
    prior_nav=None
    exchange=raw_exchange(prices,costs,[])
    for index,day in enumerate(trading_dates):
        signal_date=dates[dates.searchsorted(day)-1]
        history=prices[prices.date.le(signal_date)]
        previous=history.sort_values('date').groupby('symbol').tail(1).set_index('symbol')
        initial_nav=account['cash']+sum(h['quantity']*float(previous.loc[s,'rawClose']) for s,h in account['holdings'].items() if h['quantity'])+account.get('receivables',0)
        if prior_nav is None:prior_nav=initial_nav
        decision=None
        if day in schedule or params.get('rules') or params.get('dailyCode'):
            decision=make_decision(project,params,account,signal_date,prices,scores,features,prior_nav,portfolio_config)
            conflicts+=decision['conflicts'];warnings+=decision['warnings'];rules+=decision['reasons']
            rule_targets += [dict(date=day,signalDate=signal_date,symbol=s,ruleWeight=w) for s,w in decision['ruleTargets'].items()]
            targets += [dict(date=day,signalDate=signal_date,symbol=s,targetWeight=w,cash=1-sum(decision['targetWeights'].values()),executable=not bool(decision['conflicts'])) for s,w in decision['targetWeights'].items()]
        today=prices[prices.date.eq(day)].set_index('symbol')
        result=advance_day(account,day,prices,decision,costs,actions,exchange)
        account=result['account'];trades+=result['trades'];unfilled+=result['unfilled'];events+=result['events']
        if decision is not None:
            from .portfolio import risk_estimate
            actual = pd.Series({s:(h['quantity']+h.get('pendingQuantity',0))*float(today.loc[s,'rawClose'])/result['nav']
                for s,h in account['holdings'].items() if h['quantity'] or h.get('pendingQuantity',0)}, dtype=float)
            returns=history.pivot(index='date',columns='symbol',values='close').pct_change(fill_method=None)
            actual_rc, actual_meta = risk_estimate(returns, actual, portfolio_config)
            target_rc = decision['targetRiskContributions']
            for code in sorted(set(decision['targetWeights']) | set(actual.index)):
                target = target_rc.get(code, 0. if decision['riskEstimate']['status']=='available' else float('nan'))
                observed = actual_rc.get(code, 0. if actual_meta['status']=='available' else float('nan'))
                risk_rows.append(dict(date=day, signalDate=signal_date, symbol=code,
                    targetWeight=decision['targetWeights'].get(code,0.), actualWeight=float(actual.get(code,0.)),
                    targetRiskContribution=target, actualRiskContribution=observed, contributionDeviation=observed-target,
                    targetRiskStatus=decision['riskEstimate']['status'], actualRiskStatus=actual_meta['status'],
                    targetObservations=decision['riskEstimate']['observations'], actualObservations=actual_meta['observations'],
                    sampleStart=actual_meta['sampleStart'], sampleEnd=actual_meta['sampleEnd'],
                    targetSampleStart=decision['riskEstimate']['sampleStart'], targetSampleEnd=decision['riskEstimate']['sampleEnd'],
                    estimator='LedoitWolf', annualizationDays=252, actualWeightBasis='post_trade_close'))
        cost=sum(t['cost'] for t in result['trades'])
        report.append(dict(date=day,account=result['nav'],cash=account['cash'],value=result['marketValue'],
            receivables=account['receivables'],pendingShareValue=result['pendingShareValue'],
            **{'return':(result['nav']-prior_nav+cost)/prior_nav,'cost':cost/prior_nav,'bench':float(benchmark.loc[day]),
               'turnover':sum(t['value'] for t in result['trades'])/prior_nav}))
        # This Position is an end-of-day valuation projection, never an executable
        # position. Pending shares retain equity exposure; only cash/receivables are cash.
        position=Position(cash=account['cash']+account['receivables'],position_dict={s:{'amount':h['quantity']+h.get('pendingQuantity',0),'price':float(today.loc[s,'rawClose'])}
            for s,h in account['holdings'].items() if h['quantity'] or h.get('pendingQuantity',0)})
        positions[day]=position
        account_snapshots[day]=deepcopy(account)
        prior_nav=result['nav']
        progress(.35+.5*(index+1)/len(trading_dates),'原始股数账户 '+str(day.date()))
    return dict(report=pd.DataFrame(report).set_index('date'),positions=positions,trades=trades,unfilled=unfilled,
                targets=targets,risk=risk_rows,rule_targets=rule_targets,rules=rules,events=events,conflicts=conflicts,warnings=warnings,account=account,accountSnapshots=account_snapshots)
