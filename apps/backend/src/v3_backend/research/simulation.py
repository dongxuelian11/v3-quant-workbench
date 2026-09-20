"""Single-strategy paper accounts in the existing portable SQLite record store."""
from copy import deepcopy
import json
import math
from pathlib import Path
import pandas as pd

from . import accounting, data, engines
from .storage import identifier, now
from .portfolio import DEFAULTS
from .execution import cost_config

TABLES=('portfolio','holdings','trades','unfilled','account_events','signals','target_weights','rule_events','model_events')


def _get(store, project_id, account_id):
    account=store.project_store(project_id).get('simulation',account_id)
    if account['projectId']!=project_id:raise ValueError('模拟账户不属于此项目')
    return account


def _commit(portable, account, previous_revision, day=None):
    """One transaction owns both completed day and its restart state."""
    body=json.dumps(account,ensure_ascii=False,allow_nan=False)
    with portable.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT body FROM records WHERE kind=? AND id=?',('simulation',account['id'])).fetchone()
        if row is None or json.loads(row[0])['revision']!=previous_revision:
            raise ValueError('模拟账户已由另一操作更新，请从已完成日重试')
        if day is not None:
            db.execute('INSERT INTO records VALUES (?,?,?,?)',('simulation_day',day['id'],account['projectId'],json.dumps(day,ensure_ascii=False,allow_nan=False)))
        db.execute('UPDATE records SET body=? WHERE kind=? AND id=?',(body,'simulation',account['id']))


def _days(portable, account_id):
    with portable.connect() as db:
        records=db.execute('SELECT body FROM records WHERE kind=? AND id LIKE ? ORDER BY id',('simulation_day',account_id+':%')).fetchall()
    return [json.loads(row[0]) for row in records]


def dispatch(store, method, params):
    from .workbench import get_strategy
    project_id=params.get('projectId')
    if method=='simulation.accounts.list':
        projects=[store.project(project_id)] if project_id else store.list('project')
        result=[]
        for project in projects:
            result.extend(store.project_store(project['id']).list('simulation',project['id']))
        return result
    if not project_id:raise ValueError('模拟账户需要项目')
    portable=store.project_store(project_id)
    if method=='simulation.accounts.create':
        strategy=get_strategy(store,project_id,params.get('strategyId'))
        capital=float(params.get('capital',1000000))
        if not math.isfinite(capital) or capital<=0:raise ValueError('初始资金必须为正数')
        date=pd.Timestamp(params['startDate'])
        if pd.isna(date):raise ValueError('请填写开始日期')
        name=str(params.get('name') or '单策略模拟账户').strip()
        if not name:raise ValueError('请输入账户名称')
        account=dict(id=identifier(),name=name,projectId=project_id,strategyId=strategy['id'],
            startDate=str(date.date()),capital=capital,nav=capital,cash=capital,asOfDate=None,
            state=accounting.create(capital),pendingDecision=None,modelState=None,lastRebalancePeriod=None,
            revision=0,status='ready',paused=False,unresolved=None,createdAt=now(),updatedAt=now())
        portable.put('simulation',account,project_id)
        return account
    account=_get(store,project_id,params['accountId'])
    if method=='simulation.accounts.get':return account
    if method=='simulation.accounts.save':
        revised=deepcopy(account)
        if 'name' in params:
            revised['name']=str(params['name']).strip()
            if not revised['name']:raise ValueError('请输入账户名称')
        if 'paused' in params:
            if not isinstance(params['paused'],bool):raise ValueError('paused须为布尔值')
            revised['paused']=params['paused']
            revised['status']='paused' if params['paused'] else 'ready'
        revised.update(revision=account['revision']+1,updatedAt=now())
        _commit(portable,revised,account['revision'])
        return revised
    if method=='simulation.table':
        name=params['table']
        if name not in TABLES:raise ValueError('未知模拟表')
        rows=[row for day in _days(portable,account['id']) for row in day['tables'].get(name,[])]
        if params.get('symbol'):rows=[row for row in rows if row.get('symbol')==params['symbol']]
        offset=max(0,int(params.get('offset',0)));limit=min(500,max(1,int(params.get('limit',200))))
        return dict(name=name,columns=list(dict.fromkeys(key for row in rows for key in row)),rows=rows[offset:offset+limit],total=len(rows),offset=offset,limit=limit)
    raise ValueError('未知模拟账户操作')


def _model_scores(project, params, frame, prices, date, previous, folder):
    """Fit only mature labels as of this historical close; never read selection cache."""
    import joblib
    from .processing import label_prices
    from .diagnostics import fit
    if params.get('model') in {'native_torch','native_generated_predictions'}:
        from .rd_agent import native_code, fit_native_asof, predict_native
        context=dict(parameters=params,universe=project['universe'],code=native_code(project,params))
        state=deepcopy(previous);events=[];month=str(date.to_period('M'))
        reusable=state and state['month']==month and state['context']==context and pd.Timestamp(state['trainedAsOf'])<=date and Path(state['path']).is_file()
        if not reusable:
            training=folder/(str(date.date())+'-'+identifier())
            path,observed,event_frame=fit_native_asof(project,params,frame,prices,date,training)
            state=dict(month=month,context=context,path=path,**observed)
            events=data.records(event_frame.assign(date=date,trainedAsOf=str(date.date())))
        scores=predict_native(state['path'],frame,date,folder/'inference'/(str(date.date())+'-'+identifier()))
        return scores,state,events
    month=str(date.to_period('M'));events=[]
    context=dict(parameters=params,universe=project['universe'])
    state=deepcopy(previous)
    admissible=state and state['month']==month and state['context']==context and pd.Timestamp(state['trainedAsOf'])<=date and Path(state['path']).is_file()
    if not admissible:
        h=int(params.get('labelHorizon',5))
        if not 1<=h<=252:raise ValueError('模型标签周期必须为1至252')
        market=label_prices(prices[prices.date.le(date)],params.get('labelMode','next_open'))
        labels=(market.shift(-h)/market-1).stack().rename('label');labels.index.names=frame.index.names
        known=frame[frame.index.get_level_values(0)<=date].join(labels).dropna(subset=['label'])
        known=known[known.index.get_level_values(0)>=date-pd.DateOffset(years=int(params.get('validation',{}).get('trainYears',3)))]
        dates=pd.DatetimeIndex(sorted(known.index.get_level_values(0).unique()))
        if len(dates)<max(20,h+5):raise ValueError('历史模型缺少当时已成熟的训练/验证标签')
        split=max(1,int(len(dates)*.8));valid_start=dates[split]
        label_end=pd.Series(market.index,index=market.index).shift(-(h+(params.get('labelMode','next_open')=='next_open')))
        endpoints=known.index.get_level_values(0).map(label_end)
        train=known[endpoints<valid_start]
        valid=known[known.index.get_level_values(0)>=valid_start]
        if len(train)<10 or len(valid)<2:raise ValueError('历史模型隔离后样本不足')
        estimator=engines.model_estimator(params)
        observed=fit(estimator,train,valid,list(frame.columns),params)
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/(str(date.date())+'-'+identifier()+'.joblib')
        joblib.dump(estimator,path)
        state=dict(month=month,context=context,path=str(path),trainedAsOf=str(date.date()),
            trainingStart=str(train.index.get_level_values(0).min().date()),trainingEnd=str(train.index.get_level_values(0).max().date()),
            validationStart=str(valid_start.date()),validationEnd=str(valid.index.get_level_values(0).max().date()),trainRows=len(train),validRows=len(valid))
        events=data.records(observed['training_events'].assign(date=date,trainedAsOf=str(date.date()),trainingStart=state['trainingStart'],trainingEnd=state['trainingEnd']))
        for name,table in observed.items():table.to_parquet(path.with_name(path.stem+'-'+name+'.parquet'),index=False)
    estimator=joblib.load(state['path'])
    current=frame[frame.index.get_level_values(0)==date]
    if current.empty:raise ValueError('历史信号日没有模型特征')
    scores=pd.Series(estimator.predict(current),index=current.index,name='score')
    return scores,state,events


def _period(date, frequency):
    if frequency=='daily':return str(date.date())
    if frequency in {'weekly','monthly'}:return str(date.to_period('W' if frequency=='weekly' else 'M'))
    raise ValueError('未知调仓频率')


def advance(store, params, output, progress, project=None):
    """Worker entry point. Preparation failures are also visible on the account."""
    original=_get(store,params['projectId'],params['accountId'])
    try:return _advance(store,params,output,progress,project=project)
    except Exception as exc:
        account=_get(store,params['projectId'],params['accountId'])
        if account['revision']==original['revision'] and not account['paused'] and account['status']!='blocked':
            failed={**account,'status':'blocked','unresolved':dict(date=params.get('endDate'),message=str(exc)),
                'revision':account['revision']+1,'updatedAt':now()}
            try:_commit(store.project_store(params['projectId']),failed,account['revision'])
            except ValueError:pass
        raise


def _advance(store, params, output, progress, project=None):
    from .workbench import strategy_project
    from .selection import completed_prices
    from .corporate_actions import read as actions_read
    from .execution import raw_exchange
    project_id=params['projectId'];account_id=params['accountId']
    account=_get(store,project_id,account_id)
    if account['paused']:raise ValueError('模拟账户已暂停，请先恢复')
    portable=store.project_store(project_id)
    project=deepcopy(project) if project is not None else strategy_project(store,project_id,account['strategyId'])
    if project.get('id')!=project_id or project.get('strategyId',account['strategyId'])!=account['strategyId']:
        raise ValueError('冻结策略与模拟账户不一致')
    strategy=deepcopy(project.get('settings',{}).get('backtest',{}))
    model_params=deepcopy(project.get('settings',{}).get('model',{}))
    if not strategy:raise ValueError('策略尚未保存回测/日线规则配置')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    end=pd.Timestamp(params.get('endDate') or pd.Timestamp.now(tz='Asia/Shanghai').date()).normalize()
    held=list(account['state']['holdings'])
    prepare_project=deepcopy(project)
    if project['universe']['source']=='manual':
        prepare_project['universe']['symbols']=sorted(set(project['universe']['symbols'])|set(held))
    prices=completed_prices(engines.prepare(prepare_project,output,lambda value,message:progress(value*.3,message)))
    prices=prices[prices.date.le(end)]
    dates=pd.DatetimeIndex(sorted(prices.date.unique()))
    if dates.empty:raise ValueError('模拟区间没有已完成交易日行情，请先更新数据')
    todo=dates[dates>=pd.Timestamp(account['startDate'])]
    if account['asOfDate']:todo=todo[todo>pd.Timestamp(account['asOfDate'])]
    if todo.empty and not account['asOfDate']:raise ValueError('开始日期之后没有已完成行情')
    portfolio={**DEFAULTS,**strategy.get('portfolio',{})};costs=cost_config(strategy)
    actions=actions_read(project);exchange=raw_exchange(prices,costs,[]) if len(todo) else None
    template=strategy.get('template','multi_factor')
    feature_params=model_params if template=='model_score' else strategy
    if len(todo) and feature_params.get('factorIds'):
        features=engines.features(project,{**feature_params,'startDate':str(prices.date.min()),'endDate':str(prices.date.max())},prices)
    else:
        from .history import expected_rows
        query_panel=None
        if project['universe'].get('query'):
            from .market import dated_panel
            query_panel=dated_panel(project,prices)
        index,_=expected_rows(project,prices,dates,query_panel)
        features=pd.DataFrame(index=index)
    model_folder=Path(project['path'])/'.research/simulation'/account_id/'models'
    for i,day in enumerate(todo):
        try:
            pending=account.get('pendingDecision')
            frequency=(pending or {}).get('rebalance',strategy.get('rebalance','weekly'))
            period=_period(day,frequency)
            due=pending is not None and (pending.get('everyDay') or account.get('lastRebalancePeriod')!=period)
            # Pending orders retain their signal-time execution settings when a strategy changes.
            execution_costs=(pending or {}).get('costs',costs)
            if execution_costs!=costs:exchange=raw_exchange(prices,execution_costs,[])
            elif getattr(exchange,'simulation_costs',costs)!=costs:exchange=raw_exchange(prices,costs,[])
            exchange.simulation_costs=execution_costs
            result=accounting.advance_day(account['state'],day,prices,pending if due else None,execution_costs,actions,exchange)
            state=result['account'];model_state=account.get('modelState');model_events=[]
            if template=='model_score':
                scores,model_state,model_events=_model_scores(project,model_params,features,prices,day,model_state,model_folder)
            elif template in {'single_factor','multi_factor'}:
                current=features[features.index.get_level_values(0)==day]
                if len(current.columns):
                    ranks=current.groupby(level=0).rank(pct=True)
                    scores=ranks.mul(pd.Series({k:float(strategy.get('weights',{}).get(k,1)) for k in ranks})).sum(axis=1,min_count=len(ranks.columns))
                else:scores=pd.Series(index=current.index,dtype=float)
            else:raise ValueError('未知模拟策略模板')
            decision=accounting.make_decision(project,{**strategy,'_modelHorizon':model_params.get('labelHorizon',5)},state,day,prices,scores,features,result['nav'],portfolio)
            decision.update(costs=costs,rebalance=strategy.get('rebalance','weekly'),everyDay=bool(strategy.get('rules') or strategy.get('dailyCode')),
                strategyParameters=strategy,generatedAt=now())
            state['state']=deepcopy(decision['nextState'])
            stamp=str(day.date());fee=sum(t['cost'] for t in result['trades']);prior_nav=account['nav']
            historical=day<pd.Timestamp.now(tz='Asia/Shanghai').tz_localize(None).normalize()
            tables={key:[] for key in TABLES}
            tables['portfolio']=[dict(date=stamp,account=result['nav'],cash=state['cash'],value=result['marketValue'],receivables=state['receivables'],pendingShareValue=result['pendingShareValue'],
                netReturn=result['nav']/prior_nav-1,cost=fee,turnover=sum(t['value'] for t in result['trades'])/prior_nav,historicalBackfill=historical)]
            latest=prices[prices.date.eq(day)].set_index('symbol')
            tables['holdings']=[dict(date=stamp,symbol=s,**h,economicAmount=h['quantity']+h.get('pendingQuantity',0),
                price=float(latest.loc[s,'rawClose']),marketValue=(h['quantity']+h.get('pendingQuantity',0))*float(latest.loc[s,'rawClose']),
                pendingShareValue=h.get('pendingQuantity',0)*float(latest.loc[s,'rawClose'])) for s,h in state['holdings'].items() if h['quantity'] or h.get('pendingQuantity',0)]
            tables['trades']=result['trades'];tables['unfilled']=result['unfilled'];tables['account_events']=result['events'];tables['rule_events']=decision['reasons'];tables['model_events']=model_events
            tables['signals']=[dict(date=stamp,symbol=s,score=float(v),historicalBackfill=historical) for s,v in scores.droplevel(0).dropna().items()]
            tables['target_weights']=[dict(date=stamp,symbol=s,targetWeight=w,targetQuantity=decision['quantities'][s],historicalBackfill=historical) for s,w in decision['targetWeights'].items()]
            completed=dict(id=account_id+':'+stamp,accountId=account_id,date=stamp,createdAt=now(),tables=tables,
                decision=decision,executedDecision=pending if due else None,historicalBackfill=historical,strategySnapshot=strategy)
            revised={**account,'state':state,'pendingDecision':decision,'modelState':model_state,'asOfDate':stamp,'nav':result['nav'],'cash':state['cash'],
                'lastRebalancePeriod':period if due else account.get('lastRebalancePeriod'),'status':'ready','unresolved':None,'revision':account['revision']+1,'updatedAt':now()}
            _commit(portable,revised,account['revision'],completed)
            account=revised
            progress(.3+.65*(i+1)/len(todo),'模拟账户已保存 '+stamp)
        except Exception as exc:
            failed={**account,'status':'blocked','unresolved':dict(date=str(day.date()),message=str(exc)),'revision':account['revision']+1,'updatedAt':now()}
            try:_commit(portable,failed,account['revision'])
            except ValueError:pass  # A concurrent save owns its newer state.
            raise
    days=_days(portable,account_id)
    artifacts=[]
    for name in TABLES:
        frame=pd.DataFrame([row for day in days for row in day['tables'].get(name,[])])
        artifacts.append(engines.save_table(output,name,frame))
    return dict(metrics=dict(nav=account['nav'],cash=account['cash'],totalReturn=account['nav']/account['capital']-1,completedDays=len(todo)),artifacts=artifacts,
        summary='单策略模拟账户更新至 '+str(account['asOfDate'] or '尚无已完成日'),parameters=params,
        details=dict(accountId=account_id,account=account,accountingBasis='raw_shares_cash',historicalBackfill=any(day['historicalBackfill'] for day in days),
            strategyPriceBasis='open/high/low/close are raw yuan; adjustedOHLC is rebased at each signal date',
            signalTiming='startDate close signal -> next observed session open; daily atomic commit',
            requestedEndDate=str(end.date()),availableEndDate=str(dates[-1].date()) if len(dates) else None))
