"""One close-of-day decision contract for research and daily accounts."""
from copy import deepcopy
import math
import pandas as pd


def asof_prices(prices, day):
    """Rule OHLC means raw yuan. Optional adjusted OHLC is rebased at signal close."""
    prices=prices[pd.to_datetime(prices.date).le(day)].copy()
    factor=pd.to_numeric(prices.get('factor',pd.Series(1.,index=prices.index)),errors='coerce')
    reference=prices.assign(_factor=factor).sort_values('date').groupby('symbol')._factor.last()
    rebased=factor/prices.symbol.map(reference)
    for field in ('open','high','low','close'):
        raw='raw'+field.title()
        if raw not in prices and field in prices:prices[raw]=prices[field]/factor
        if raw in prices:
            prices[field]=prices[raw]
            prices['adjusted'+field.title()]=prices[raw]*rebased
    prices['factor']=rebased
    return prices


def decide_day(context, config):
    """Return unconstrained target weights; never execute or mutate the account.

    Rules contain action entry/add/reduce/exit, conditions [{field,op,value}],
    and weight (absolute target for entry, delta for add/reduce). Fields are
    columns of the day's feature frame or quantity/costPrice/returnSinceEntry.
    Exit/reduce decisions cannot be overwritten by an entry/add on the same day.
    """
    day = pd.Timestamp(context['date']).normalize()
    prices = asof_prices(context['prices'],day)
    scores = context.get('scores', pd.Series(dtype=float)).copy()
    if isinstance(scores.index, pd.MultiIndex):
        scores = scores[scores.index.get_level_values(0) == day]
        scores.index = scores.index.get_level_values(-1)
    holdings = deepcopy(context.get('holdings', {}))
    state = deepcopy(context.get('state', {}))
    latest = prices.sort_values('date').groupby('symbol').tail(1).set_index('symbol')
    missing=[s for s,h in holdings.items() if h.get('quantity',0) and (s not in latest.index or pd.isna(latest.loc[s,'rawClose']))]
    if missing:raise ValueError('决策持仓缺原始估值: '+','.join(missing))
    nav = float(context['cash']) + sum(float(h['quantity'])*float(latest.loc[s, 'rawClose'])
        for s,h in holdings.items() if s in latest.index)
    nav=float(context.get('nav',nav))
    current = {s:float(h['quantity']+h.get('pendingQuantity',0))*float(latest.loc[s,'rawClose'])/nav
        for s,h in holdings.items() if s in latest.index and nav > 0}
    events = []
    if config.get('dailyCode'):
        frame=context.get('features',pd.DataFrame()).copy()
        if isinstance(frame.index,pd.MultiIndex):frame=frame[frame.index.get_level_values(0)<=day]
        elif 'date' in frame:frame=frame[pd.to_datetime(frame.date).le(day)]
        elif isinstance(frame.index,pd.DatetimeIndex):frame=frame[frame.index<=day]
        safe=dict(date=str(day.date()),prices=prices,features=frame,scores=scores.copy(),
                  holdings=holdings,cash=float(context['cash']),nav=nav,state=state)
        scope={'pd':pd}
        exec(compile(config['dailyCode'],'<daily-strategy>','exec'),scope)
        if not callable(scope.get('decide')):raise ValueError('日线 Python 策略须定义 decide(context)')
        result=scope['decide'](safe)
        if not isinstance(result,dict) or not isinstance(result.get('targets'),dict):raise ValueError('decide 须返回 targets 字典和可选 state/reasons')
        targets={str(k):float(v) for k,v in result['targets'].items()}
        if any(not math.isfinite(v) or not 0<=v<=1 for v in targets.values()):raise ValueError('Python 目标权重必须在0—1')
        return dict(date=str(day.date()),scores=scores,targets=targets,reasons=result.get('reasons',[]),nextState=result.get('state',state))
    rules = config.get('rules', [])
    if not rules:
        if config.get('code'):
            original=scores.copy()
            original.index=pd.MultiIndex.from_product([[day],original.index],names=['datetime','instrument'])
            scope = {'pd':pd, 'prices':prices, 'scores':original}
            exec(compile(config['code'], '<daily-strategy>', 'exec'), scope)
            candidate = scope.get('scores')
            if not isinstance(candidate,pd.Series) or not candidate.index.equals(original.index):
                raise ValueError('日线 Python 评分须保留当日股票索引')
            scores = pd.to_numeric(candidate, errors='raise')
            scores.index=scores.index.get_level_values(-1)
        chosen = scores.replace([math.inf,-math.inf], math.nan).dropna().sort_values(ascending=False).head(int(config.get('topN',30)))
        # Portfolio construction supplies the final exposure and weighting.
        return dict(date=str(day.date()), scores=chosen, targets=None, reasons=events, nextState=state)
    frame = context.get('features', pd.DataFrame(index=scores.index)).copy()
    if isinstance(frame.index,pd.MultiIndex):
        frame = frame[frame.index.get_level_values(0)==day]
        frame.index=frame.index.get_level_values(-1)
    frame = frame.reindex(frame.index.union(scores.index).union(pd.Index(list(holdings))))
    for column in latest:
        if column not in frame or column in {'open','high','low','close','rawOpen','rawHigh','rawLow','rawClose','adjustedOpen','adjustedHigh','adjustedLow','adjustedClose','factor'}:
            frame[column]=latest[column].reindex(frame.index)
    frame['score'] = scores
    targets = current.copy()
    ops = {'gt':lambda a,b:a>b,'gte':lambda a,b:a>=b,'lt':lambda a,b:a<b,
           'lte':lambda a,b:a<=b,'eq':lambda a,b:a==b,'ne':lambda a,b:a!=b}
    protected = set()
    for index,rule in sorted(enumerate(rules), key=lambda r: {'exit':0,'reduce':1,'add':2,'entry':3}.get(r[1]['action'],9)):
        action=rule['action']
        if action not in {'exit','reduce','add','entry'}:
            raise ValueError('未知日线规则动作: '+action)
        amount=float(rule.get('weight',0))
        if not math.isfinite(amount) or not 0<=amount<=1:
            raise ValueError('规则 weight 必须在 0—1')
        for symbol,row in frame.iterrows():
            h=holdings.get(symbol,{}); held=float(h.get('quantity',0))>0
            if action in {'exit','reduce','add'} and not held or action=='entry' and held:
                continue
            if action in {'entry','add'} and symbol in protected:
                continue
            values=row.to_dict();values.update(quantity=h.get('quantity',0),costPrice=h.get('costPrice'))
            cost=h.get('costPrice')
            values['returnSinceEntry']=float(latest.loc[symbol,'rawClose'])/cost-1 if cost and symbol in latest.index else None
            matched=True
            for condition in rule.get('conditions',[]):
                field=condition['field']
                if field not in values:
                    raise ValueError('规则字段不可用: '+field)
                value=values[field]
                if condition.get('op') not in ops:raise ValueError('未知规则比较操作: '+str(condition.get('op')))
                threshold=condition['value']
                if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold):raise ValueError('规则比较值必须为有限数字')
                if value is None or pd.isna(value) or not ops[condition['op']](value,threshold):
                    matched=False;break
            if not matched:continue
            before=targets.get(symbol,0)
            after=0 if action=='exit' else max(0,before-amount) if action=='reduce' else amount if action=='entry' else min(1,before+amount)
            targets[symbol]=after
            if action in {'exit','reduce'}:protected.add(symbol)
            events.append(dict(date=str(day.date()),symbol=symbol,ruleId=rule.get('id',str(index)),action=action,beforeWeight=before,targetWeight=after,reason=rule.get('name',action)))
    state['lastSignalDate']=str(day.date())
    return dict(date=str(day.date()),scores=scores,targets=targets,reasons=events,nextState=state)
