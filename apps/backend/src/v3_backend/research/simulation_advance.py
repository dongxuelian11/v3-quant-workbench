"""Daily shared-account orchestration over the existing raw-share accounting engine."""
from copy import deepcopy
from pathlib import Path
import math
import pandas as pd
from . import accounting, engines, data, simulation_accounts as records
from .storage import identifier, now
from .execution import cost_config, raw_exchange
from .portfolio import DEFAULTS


def unsettled_entitlement_symbols(state):
    """Historical paid/listed entitlements do not keep an empty holding source alive."""
    pending=set();done=set(state.get('processedActions',[]))
    for key,entry in state.get('entitlements',{}).items():
        cash,shares=entry.get('cash'),entry.get('shares')
        known=all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0 for v in (cash,shares))
        if not known or (cash>0 and (key+':ex' not in done or key+':pay' not in done)) or (shares>0 and (key+':ex' not in done or key+':listing' not in done)):
            pending.add(entry['symbol'])
    return pending


def prepare_sources(store,account,params,output,progress):
    from . import preparation,input_snapshot,corporate_actions
    from .selection import completed_prices
    sources={};failures=[]
    for binding in account['bindings']:
        needed={binding['currentVersionId']}|{o['entryVersionId'] for o in account['ownership'] if o['bindingId']==binding['id'] and (o['quantity'] or o['pendingQuantity'])}
        for version in binding['versions']:
            if version['id'] not in needed:continue
            key=binding['id']+':'+version['id'];saved=version['snapshot'];project=deepcopy(saved['project'])
            try:
                if saved['kind']=='dailyPlan':
                    asset=next((a for a in saved['plan'].get('assets',[]) if a['kind']=='strategy'),None)
                    if asset:project['settings'].update(deepcopy(asset['snapshot'].get('settings',{})))
                owned=[o['symbol'] for o in account['ownership'] if o['bindingId']==binding['id'] and (o['quantity'] or o['pendingQuantity'])]
                local=output/'inputs'/binding['id']/version['id'];local.mkdir(parents=True,exist_ok=True)
                compute=dict(startDate=account['startDate'],endDate=params['endDate'],updateData=params.get('updateData',False))
                model=project.get('settings',{}).get('model',{})
                if model.get('trainStart'):compute['startDate']=min(compute['startDate'],model['trainStart'])
                from .storage import read_json
                manifest=local/'inputs/snapshot.json'
                if (local/'failure.json').exists():raise ValueError(read_json(local/'failure.json')['message'])
                if manifest.exists():
                    saved_input=read_json(manifest);fixed=saved_input['project'];reference=saved_input['reference']
                    for item in reference.get('files',[]):
                        if not (manifest.parent/item['path']).is_file():raise ValueError('已固定账户输入文件缺失，不能切回当前数据')
                    calculation=deepcopy(fixed)
                    calculation['universe']=dict(source='manual',symbols=sorted(data.read_table(fixed).symbol.unique()),excludeST=False,minListingDays=0)
                    prices=completed_prices(engines.prepare(calculation,local,progress))
                    calendar=preparation.trading_dates(Path(data.project_data(fixed)['path'])/'data',account['startDate'],params['endDate'],source='file',update_data=False)
                else:
                    if (local/'inputs').exists():raise ValueError('固定输入尚未完整保存，请保留失败任务并明确重新提交')
                    compute,prepared=preparation.prepare(store,dict(kind='simulation.advance',spec={'parameters':compute}),project,local,progress)
                    if owned:
                        held_project=deepcopy(project);held_project['universe']=dict(source='manual',symbols=sorted(set(owned)),excludeST=False,minListingDays=0)
                        _,held_prepared=preparation.prepare(store,dict(kind='simulation.advance',spec={'parameters':deepcopy(compute)}),held_project,local/'holdings',progress)
                        coverage=prepared.setdefault('actualCoverage',{})
                        coverage['symbols']=sorted(set(coverage.get('symbols',[]))|set(owned))
                        if held_prepared.get('inputStart'):prepared['inputStart']=min(prepared.get('inputStart',held_prepared['inputStart']),held_prepared['inputStart'])
                    capture_project=deepcopy(project)
                    source_root=Path(project['path'])
                    def absolute_files(value):
                        if isinstance(value,dict):
                            for key,item in value.items():
                                if key in {'codePath','dataPath','trainingEventsPath'} and isinstance(item,str) and item:value[key]=str((source_root/item).resolve())
                                else:absolute_files(item)
                        elif isinstance(value,list):
                            for item in value:absolute_files(item)
                    absolute_files(capture_project['settings'])
                    capture_project['settings']['dataPath']=str(Path(data.project_data(project)['path'])/'data')
                    fixed,compute,reference=input_snapshot.capture(store,capture_project,compute,local,prepared,output_root=store.project(None)['path'])
                    calculation=deepcopy(fixed)
                    calculation['universe']=dict(source='manual',symbols=prepared.get('actualCoverage',{}).get('symbols',[]),excludeST=False,minListingDays=0)
                    prices=completed_prices(engines.prepare(calculation,local,progress))
                    calendar=preparation.trading_dates(Path(data.project_data(fixed)['path'])/'data',account['startDate'],compute['endDate'],source='file',update_data=False)
                sources[key]=dict(binding=binding,version=version,project=fixed,calculationProject=calculation,prices=prices,calendar=calendar,inputSnapshot=reference,actions=corporate_actions.read(fixed),folder=local)
            except Exception as exc:
                from .storage import write_json
                error=str(exc) or type(exc).__name__
                failed_path=output/'inputs'/binding['id']/version['id']/'failure.json'
                if not failed_path.exists():write_json(failed_path,dict(message=error))
                failures.append(dict(bindingId=binding['id'],versionId=version['id'],message=error,stage='prepare'))
    entitlement_symbols=unsettled_entitlement_symbols(account['state'])
    held_symbols={o['symbol'] for o in account['ownership'] if o['quantity'] or o['pendingQuantity']}|entitlement_symbols
    valuation_sources=[('manual:'+str(index),'valuation_'+str(index),project,sorted(held_symbols)) for index,project in enumerate(account.get('valuationSources',[]))]
    for source in account.get('holdingValuationSources',[]):
        held=sorted({o['symbol'] for o in account['ownership'] if o.get('valuationSourceId')==source['id'] and (o['quantity'] or o['pendingQuantity'] or o['symbol'] in entitlement_symbols)})
        if held:valuation_sources.append(('holding:'+source['id'],'holding_valuation_'+source['id'],source['project'],held))
    for source_key,folder_name,project,held in valuation_sources:
        from .storage import read_json,write_json
        local=output/'inputs'/folder_name
        manifest=local/'inputs/snapshot.json'
        try:
            if (local/'failure.json').exists():raise ValueError(read_json(local/'failure.json')['message'])
            if manifest.exists():
                saved=read_json(manifest);fixed=saved['project'];reference=saved['reference']
                for item in reference.get('files',[]):
                    if not (manifest.parent/item['path']).is_file():raise ValueError('已固定估值输入文件缺失，不能切回当前数据')
            else:
                if (local/'inputs').exists():raise ValueError('固定估值输入尚未完整保存，不能切回当前数据')
                capture_project=deepcopy(project)
                capture_project['universe']=dict(source='manual',symbols=held,excludeST=False,minListingDays=0)
                start=min(account['startDate'],account['asOfDate'] or account['startDate'])
                preparation.trading_dates(Path(data.project_data(project)['path'])/'data',start,params['endDate'],source='file',update_data=False)
                fixed,_,reference=input_snapshot.capture(store,capture_project,dict(startDate=start,endDate=params['endDate']),local,
                    dict(actualCoverage={'symbols':held}),output_root=store.project(None)['path'])
            prices=completed_prices(data.read_table(fixed))
            calendar=preparation.trading_dates(Path(data.project_data(fixed)['path'])/'data',account['startDate'],params['endDate'],source='file',update_data=False)
            sources[source_key]=dict(project=fixed,prices=prices,calendar=calendar,inputSnapshot=reference,actions=corporate_actions.read(fixed))
        except Exception as exc:
            error=str(exc) or type(exc).__name__
            if not (local/'failure.json').exists():write_json(local/'failure.json',dict(message=error))
            failures.append(dict(bindingId=None,versionId=None,message=error,stage='valuation'))
    return sources,failures


def merged_market(sources):
    frames=[s['prices'] for s in sources.values() if not s['prices'].empty]
    if not frames:raise ValueError('绑定来源均不可用，没有可核验行情')
    joined=pd.concat(frames,ignore_index=True)
    duplicated=joined[joined.duplicated(['date','symbol'],keep=False)]
    conflicts=set()
    for (date,symbol),group in duplicated.groupby(['date','symbol']):
        for field in ('rawOpen','rawClose','rawPreclose','factor','volume','tradestatus'):
            if field in group and group[field].nunique(dropna=False)>1:conflicts.add((pd.Timestamp(date),symbol))
    # A conflict is retained separately and never silently used for a held valuation.
    prices=joined.drop_duplicates(['date','symbol']).sort_values(['date','symbol'])
    actions={}
    for source in sources.values():
        for action in pd.DataFrame(source['actions']).to_dict('records'):
            key=action['id']
            if key in actions and records.encoded(actions[key])!=records.encoded(action):
                raise ValueError('绑定来源公司行动冲突：'+key)
            actions[key]=action
    return prices,list(actions.values()),conflicts


def scoped_state(account,binding_id,version_id):
    rows=[o for o in account['ownership'] if o['bindingId']==binding_id and o['entryVersionId']==version_id and o['management']=='rules']
    holdings={}
    for owner in rows:
        h=holdings.setdefault(owner['symbol'],dict(quantity=0,sellableQuantity=0,pendingQuantity=0,costPrice=0))
        for key in ('quantity','sellableQuantity','pendingQuantity'):h[key]+=owner[key]
    for symbol,h in holdings.items():
        selected=[o for o in rows if o['symbol']==symbol];quantity=h['quantity']+h['pendingQuantity']
        h['costPrice']=sum(o['costBasis'] for o in selected)/quantity if quantity and all(o['costBasis'] is not None for o in selected) else None
    state=dict(cash=account['cash'],holdings=holdings,state=deepcopy(account.get('ruleStates',{}).get(binding_id+':'+version_id,{})))
    return rows,state


def signal(store,account,source,day,folder):
    from .simulation import _model_scores
    from .history import industries
    binding=source['binding'];version=source['version'];project=source['project'];prices=source['prices']
    if pd.Timestamp(day) not in set(pd.to_datetime(prices.date)):raise ValueError('绑定缺当日行情')
    owners,state=scoped_state(account,binding['id'],version['id'])
    capital=account['nav']*binding['allocation']
    if version['id']==binding['currentVersionId']:
        latest=prices[prices.date.eq(day)].set_index('symbol')
        old_value=sum((o['quantity']+o['pendingQuantity'])*float(latest.loc[o['symbol'],'rawClose']) for o in account['ownership'] if o['bindingId']==binding['id'] and o['entryVersionId']!=version['id'] and (o['quantity'] or o['pendingQuantity']))
        capital=max(0,capital-old_value)
    if capital<=0 and not owners:return {},cost_config({}),[],None
    if capital<=0:capital=sum((o['quantity']+o['pendingQuantity'])*float(prices[prices.date.eq(day)].set_index('symbol').loc[o['symbol'],'rawClose']) for o in owners)
    state['cash']=min(account['cash'],max(0,capital))
    saved=version['snapshot'];model_state=None
    if saved['kind']=='dailyPlan':
        from . import screening_run
        from .portfolio import construct_portfolio
        plan=deepcopy(saved['plan']);plan['date']=str(day.date())
        snapshot=dict(cash=state['cash'],rows=[dict(symbol=s,**h) for s,h in state['holdings'].items()],asOfDate=account['asOfDate'])
        screened=screening_run.run(store,project,dict(plan=plan,allowPartial=False,updateData=False),folder,lambda *_:None,daily_snapshot=snapshot)
        context=screened['_daily'];strategy=context['strategy'] or {};selected=context['frame'].query("status == 'included'").set_index('symbol');scores=selected.score.astype(float)
        if plan['mode']=='conditions' and scores.isna().all():scores=pd.Series(1.,index=selected.index)
        if not all(math.isfinite(x) for x in scores):raise ValueError('每日方案评分缺失')
        if context['targets'] is not None:weights=pd.Series(context['targets'],dtype=float)
        else:
            returns=prices[prices.date.le(day)].pivot(index='date',columns='symbol',values='close').pct_change(fill_method=None)
            built=construct_portfolio(scores,returns,{**DEFAULTS,**strategy.get('portfolio',{})},industries=industries(project,day,scores.index))
            if built['conflicts']:raise ValueError('；'.join(built['conflicts']))
            weights=built['weights']
        latest=prices[prices.date.eq(day)].set_index('symbol')
        quantities={s:float(weights.get(s,0))*capital/float(latest.loc[s,'rawClose']) for s in weights.index.union(pd.Index(state['holdings']))}
        decision=dict(quantities=quantities,nextState=state['state'],reasons=[])
    else:
        strategy=deepcopy(project['settings'].get('backtest',{}));model=deepcopy(project['settings'].get('model',{}))
        strategy.setdefault('factorIds',project['settings'].get('selectedFactors',[]))
        if not strategy:raise ValueError('绑定没有可执行规则')
        feature_params=model if strategy.get('template')=='model_score' else strategy
        if feature_params.get('factorIds'):features=engines.features(source.get('calculationProject',project),{**feature_params,'startDate':str(prices.date.min().date()),'endDate':str(day.date())},prices[prices.date.le(day)])
        else:features=pd.DataFrame(index=pd.MultiIndex.from_frame(prices.loc[prices.date.le(day),['date','symbol']]))
        key=binding['id']+':'+version['id']
        if strategy.get('template')=='model_score':
            scores,model_state,_=_model_scores(project,model,features,prices,day,account.get('modelStates',{}).get(key),folder/'model')
        elif len(features.columns):
            current=features[features.index.get_level_values(0)==day];rank=current.groupby(level=0).rank(pct=True)
            scores=rank.mul(pd.Series({k:float(strategy.get('weights',{}).get(k,1)) for k in rank})).sum(axis=1,min_count=len(rank.columns))
        else:scores=pd.Series(index=features[features.index.get_level_values(0)==day].index,dtype=float)
        decision=accounting.make_decision(project,{**strategy,'_modelHorizon':model.get('labelHorizon',5)},state,day,prices,scores,features,capital,{**DEFAULTS,**strategy.get('portfolio',{})})
        if decision['conflicts']:raise ValueError('；'.join(decision['conflicts']))
    from .simulation import _period
    key=binding['id']+':'+version['id'];period=_period(day,strategy.get('rebalance','daily'))
    if not (strategy.get('rules') or strategy.get('dailyCode')) and account.get('signalPeriods',{}).get(key)==period:return {},cost_config(strategy),[],model_state
    account.setdefault('signalPeriods',{})[key]=period
    account.setdefault('ruleStates',{})[key]=deepcopy(decision['nextState'])
    # Old versions only maintain/exit their existing owners. New versions cannot buy an owned ticker again.
    current_version=version['id']==binding['currentVersionId'];all_held={o['symbol'] for o in account['ownership'] if o['quantity'] or o['pendingQuantity']}
    from .history import expected_rows
    from .market import dated_panel
    panel=dated_panel(project,prices) if project['universe'].get('query') else None
    expected,_=expected_rows(project,prices,[day],panel)
    eligible=set(expected.get_level_values(-1))
    quantities={}
    for symbol,target in decision['quantities'].items():
        owned=sum(o['quantity']+o['pendingQuantity'] for o in owners if o['symbol']==symbol)
        if not current_version or not binding['allowNewEntries']:target=min(float(target),owned)
        if not owned and (symbol in all_held or symbol not in eligible):target=0
        if owned or target>0:quantities[symbol]=max(0,float(target))
    return quantities,cost_config(strategy),decision['reasons'],model_state


class RoutedExchange:
    def __init__(self,prices,costs):
        self.prices=prices;self.costs=costs;self.exchanges={};self.rejections=[];self.sellable={}
    def deal_order(self,order,**kwargs):
        config=self.costs.get(order.stock_id,cost_config({}));key=records.encoded(config)
        if key not in self.exchanges:self.exchanges[key]=raw_exchange(self.prices,config,self.rejections)
        exchange=self.exchanges[key];exchange.sellable=self.sellable
        return exchange.deal_order(order,**kwargs)


def release_and_actions(account,actions,day,phase):
    """Allocate recorded corporate-action share entitlements to their original owners."""
    stamp=str(day.date());entitlements=account.setdefault('ownershipEntitlements',{})
    if phase=='open':
        for o in account['ownership']:o['sellableQuantity']=o['quantity']
    for action in actions:
        if action.get('status')!='implemented' or action['announcementDate']>stamp:continue
        key=action['id'];owners={o['id']:o for o in account['ownership']}
        if phase=='close' and action['recordDate']==stamp and key not in entitlements:
            entitlements[key]={o['id']:o['quantity']*action['bonusRatio'] for o in owners.values() if o['symbol']==action['symbol'] and o['quantity']}
        if phase!='open' or key not in entitlements:continue
        for owner_id,shares in entitlements[key].items():
            if owner_id not in owners:raise ValueError('企业行动持仓归属缺失')
            owner=owners[owner_id]
            if action['exDate']==stamp:owner['pendingQuantity']+=shares
            if action.get('listingDate')==stamp:
                if not float(shares).is_integer():raise ValueError('归属红股零碎股缺实际分配数量')
                owner['quantity']+=shares;owner['sellableQuantity']+=shares;owner['pendingQuantity']-=shares


def allocate_trades(account,trades,intents,day):
    allocations=[]
    for trade in trades:
        sign=1 if trade['direction'] else -1
        candidates=[i for i in intents if i['symbol']==trade['symbol'] and i['delta']*sign>0]
        if not candidates:raise ValueError('实际成交缺归属委托')
        requested=sum(abs(i['delta']) for i in candidates);remaining=int(trade['amount']);fee_left=float(trade['cost'])
        shares=[]
        for intent in candidates:
            exact=trade['amount']*abs(intent['delta'])/requested;shares.append([intent,min(int(math.floor(exact)),int(math.ceil(abs(intent['delta'])))),exact%1])
        extra=remaining-sum(r[1] for r in shares)
        for row in sorted(shares,key=lambda x:(-x[2],x[0]['ownershipId'])):
            if extra and row[1]<math.ceil(abs(row[0]['delta'])):row[1]+=1;extra-=1
        if extra:raise ValueError('成交量无法分配至有效委托')
        active=[row for row in shares if row[1]]
        for index,(intent,amount,_) in enumerate(active):
            owner=next((o for o in account['ownership'] if o['id']==intent['ownershipId']),None)
            if owner is None:
                owner=dict(id=intent['ownershipId'],symbol=intent['symbol'],bindingId=intent['bindingId'],entryVersionId=intent['versionId'],management='rules',quantity=0,sellableQuantity=0,pendingQuantity=0,costBasis=0.)
                account['ownership'].append(owner)
            fees=fee_left if index==len(active)-1 else trade['cost']*amount/trade['amount'];fee_left-=fees
            before=owner['quantity']+owner['pendingQuantity']
            if sign<0:
                if amount>owner['sellableQuantity']:raise ValueError('归属卖出超过可卖数量')
                owner['quantity']-=amount;owner['sellableQuantity']-=amount
                if owner['costBasis'] is not None:owner['costBasis']*=max(0,before-amount)/before
            else:
                owner['quantity']+=amount
                if owner['costBasis'] is not None:owner['costBasis']+=trade['price']*amount+fees
            allocations.append(dict(date=str(day.date()),tradeId=trade['tradeId'],ownershipId=owner['id'],bindingId=owner['bindingId'],versionId=owner['entryVersionId'],symbol=owner['symbol'],quantity=amount,direction=trade['direction'],fees=fees))
    return allocations


def pending_for_day(account,day,conflicts,actions):
    pending=deepcopy(account.get('pendingDecision'))
    if not pending:return None,[],{},[]
    owners={o['id']:o for o in account['ownership']};intents=[];blocked={s for date,s in conflicts if date==day}
    for item in pending.get('intents',[]):
        intent=deepcopy(item);owner=owners.get(intent['ownershipId'])
        if owner and owner['management']=='manual' and not intent.get('liquidate'):continue
        ratio=1.
        for action in actions:
            if action.get('status')=='implemented' and action['symbol']==intent['symbol'] and action['exDate']==str(day.date()):ratio*=1+action['bonusRatio']
        intent['targetQuantity']*=ratio
        current=(owner['quantity']+owner['pendingQuantity']) if owner else 0
        intent['delta']=intent['targetQuantity']-current
        if abs(intent['delta'])<1e-7:continue
        if intent['delta']<0:intent['delta']=-min(-intent['delta'],owner['sellableQuantity'] if owner else 0)
        intents.append(intent)
    costs={}
    for item in intents:
        symbol=item['symbol']
        if symbol in costs and costs[symbol]!=item['costs']:blocked.add(symbol)
        costs[symbol]=item['costs']
    rejected=[dict(date=str(day.date()),signalDate=pending['date'],symbol=i['symbol'],ownershipId=i['ownershipId'],bindingId=i['bindingId'],versionId=i['versionId'],side='buy' if i['delta']>0 else 'sell',requestedQuantity=abs(i['delta']),allowedQuantity=0,reason='同证券行情来源冲突' if (day,i['symbol']) in conflicts else '同证券委托费用口径冲突') for i in intents if i['symbol'] in blocked]
    intents=[i for i in intents if i['symbol'] not in blocked and abs(i['delta'])>=1e-7]
    quantities={}
    for item in intents:
        symbol=item['symbol'];held=account['state']['holdings'].get(symbol,{})
        quantities.setdefault(symbol,sum(o['quantity']+o['pendingQuantity'] for o in account['ownership'] if o['symbol']==symbol))
        quantities[symbol]+=item['delta']
    return dict(date=pending['date'],quantities=quantities,reasons=pending.get('reasons',[]),nextState=account['state'].get('state',{})),intents,costs,rejected


def next_decision(store,account,sources,day,output,source_failures):
    intents=[];failures=deepcopy(source_failures);reasons=[];failed_symbols=set()
    for source in sources.values():
        if 'binding' not in source:continue
        binding=source['binding'];version=source['version'];key=binding['id']+':'+version['id']
        try:
            proposed=deepcopy(account)
            targets,costs,why,model=signal(store,proposed,source,day,output/'signals'/str(day.date())/binding['id']/version['id'])
            for field in ('ruleStates','signalPeriods'):
                if field in proposed:account[field]=proposed[field]
            if model:account.setdefault('modelStates',{})[key]=model
            reasons.extend(why)
            for symbol,target in targets.items():
                owners=[o for o in account['ownership'] if o['bindingId']==binding['id'] and o['entryVersionId']==version['id'] and o['symbol']==symbol and o['management']=='rules' and (o['quantity'] or o['pendingQuantity'])]
                total=sum(o['quantity']+o['pendingQuantity'] for o in owners)
                if not owners:
                    intents.append(dict(ownershipId=identifier(),bindingId=binding['id'],versionId=version['id'],symbol=symbol,targetQuantity=target,costs=costs))
                else:
                    for owner in owners:intents.append(dict(ownershipId=owner['id'],bindingId=binding['id'],versionId=version['id'],symbol=symbol,targetQuantity=target*(owner['quantity']+owner['pendingQuantity'])/total if total else 0,costs=costs))
        except Exception as exc:failures.append(dict(bindingId=binding['id'],versionId=version['id'],stage='signal',message=str(exc) or type(exc).__name__))
    for failure in failures:
        failed_symbols.update(o['symbol'] for o in account['ownership'] if o['bindingId']==failure['bindingId'] and o['entryVersionId']==failure['versionId'] and (o['quantity'] or o['pendingQuantity']))
    intents=[i for i in intents if i['symbol'] not in failed_symbols]
    for owner in account['ownership']:
        if owner['id'] in account.get('liquidationOwnershipIds',[]) and owner['symbol'] not in failed_symbols:
            intents=[i for i in intents if i['ownershipId']!=owner['id']]
            intents.append(dict(ownershipId=owner['id'],bindingId=owner['bindingId'],versionId=owner['entryVersionId'],symbol=owner['symbol'],targetQuantity=0.,costs=cost_config({}),liquidate=True))
    return dict(date=str(day.date()),intents=intents,reasons=reasons,failures=failures)


def advance(store,params,output,progress,submitted):
    from .simulation import _commit,_days,TABLES
    account=records.get(store,params);expected=params.get('expectedRevision');job_id=params.get('_advanceJobId')
    resumed=job_id and account.get('lastAdvanceJobId')==job_id and account.get('lastAdvanceExpectedRevision')==expected and account.get('lastAdvanceRevision')==account['revision']
    if not resumed:records.revision(account,expected)
    if account['paused']:raise ValueError('模拟账户已暂停')
    if not submitted or submitted['id']!=account['id']:raise ValueError('缺少提交时冻结的账户')
    if not resumed and submitted['revision']!=account['revision']:raise ValueError('提交账户版本不一致')
    output=Path(output);output.mkdir(parents=True,exist_ok=True);portable=store.project_store(None)
    try:
        if not account['bindings'] and not any(h['quantity'] or h.get('pendingQuantity',0) for h in account['state']['holdings'].values()):
            return advance_cash(store,account,params,output,progress,submitted)
        sources,failures=prepare_sources(store,account,params,output,progress)
        if not sources:raise ValueError('绑定来源均不可用：'+'；'.join(str(f.get('bindingId'))+' '+f['message'] for f in failures))
        prices,actions,conflicts=merged_market(sources)
        end=pd.Timestamp(params['endDate'])
        calendars=[s['calendar'] for s in sources.values() if s.get('calendar') is not None]
        if not calendars:raise ValueError('缺少已冻结交易日历，不能按观察行情跳日推进')
        if any(calendar!=calendars[0] for calendar in calendars[1:]):raise ValueError('绑定来源交易日历不一致')
        dates=sorted(pd.to_datetime(calendars[0]))
        todo=[pd.Timestamp(d) for d in dates if d>=pd.Timestamp(account['startDate']) and (not account['asOfDate'] or d>pd.Timestamp(account['asOfDate']))]
        if not todo and not account['asOfDate']:raise ValueError('开始日期后没有已完成行情')
        for index,day in enumerate(todo):
            working=deepcopy(account)
            held={s for s,h in working['state']['holdings'].items() if h['quantity'] or h.get('pendingQuantity',0)}
            if any((day,s) in conflicts for s in held):raise ValueError('持仓估值来源冲突，未推进账户')
            if prices[prices.date.eq(day)].empty:raise ValueError('交易日缺完整行情：'+str(day.date())+'，未跨日执行')
            release_and_actions(working,actions,day,'open')
            decision,intents,costs,blocked_orders=pending_for_day(working,day,conflicts,actions)
            # Quantity targets already use the execution-day share denomination.
            result=accounting.advance_day(working['state'],day,prices,decision,cost_config({}),actions,RoutedExchange(prices,costs),collect_orders=True)
            allocations=allocate_trades(working,result['trades'],intents,day)
            for intent in intents:
                filled=sum(row['quantity'] for row in allocations if row['ownershipId']==intent['ownershipId'] and row['direction']==int(intent['delta']>0))
                if abs(intent['delta'])-filled>1e-7:
                    blocked_orders.append(dict(date=str(day.date()),signalDate=decision['date'],symbol=intent['symbol'],ownershipId=intent['ownershipId'],bindingId=intent['bindingId'],versionId=intent['versionId'],side='buy' if intent['delta']>0 else 'sell',requestedQuantity=abs(intent['delta']),allowedQuantity=filled,reason='归属委托未完全成交：净额抵消、整手或交易约束；剩余当日到期'))
            working.update(state=result['account'],nav=result['nav'],cash=result['account']['cash'],asOfDate=str(day.date()),valuationStatus='known')
            release_and_actions(working,actions,day,'close');records.validate_ownership(working)
            prior_unit=working.get('unitNav')
            if working.get('units') is None:
                working['units']=working['nav'];working['unitNav']=1. if working['nav']>0 else None
            elif working['units']>0:working['unitNav']=working['nav']/working['units']
            elif working['nav']==0:working['unitNav']=None
            else:raise ValueError('账户零份额存在未解释残值')
            pending=next_decision(store,working,sources,day,output,failures)
            working['pendingDecision']=pending
            working['liquidationOwnershipIds']=[o['id'] for o in working['ownership'] if o['id'] in working.get('liquidationOwnershipIds',[]) and (o['quantity'] or o['pendingQuantity'])]
            stamp=str(day.date());tables={name:[] for name in TABLES}
            tables['portfolio']=[dict(date=stamp,account=working['nav'],cash=working['cash'],unitNav=working['unitNav'],units=working['units'],netContributions=working['netContributions'],netReturn=working['unitNav']/prior_unit-1 if prior_unit and working['unitNav'] is not None else None)]
            tables['holdings']=[dict(date=stamp,symbol=s,**h) for s,h in working['state']['holdings'].items() if h['quantity'] or h.get('pendingQuantity',0)]
            tables['ownership']=[dict(date=stamp,**o) for o in working['ownership']]
            tables['trades']=result['trades'];tables['unfilled']=[dict(row,executionDate=stamp,expiryDate=stamp,status='expired') for row in result['unfilled']+blocked_orders]
            tables['trade_allocations']=allocations;tables['account_events']=result['events'];tables['rule_events']=pending['reasons']
            tables['signals']=[dict(date=stamp,signalDate=stamp,**i) for i in pending['intents']]
            tables['binding_events']=[dict(date=stamp,**f) for f in pending['failures']]
            working.update(status='blocked' if pending['failures'] else 'ready',unresolved=dict(date=stamp,message='；'.join(f['message'] for f in pending['failures'])) if pending['failures'] else None,
                revision=account['revision']+1,updatedAt=now(),lastAdvanceJobId=job_id,lastAdvanceExpectedRevision=expected,lastAdvanceRevision=account['revision']+1)
            completed=dict(id=account['id']+':'+stamp,accountId=account['id'],date=stamp,createdAt=now(),tables=tables,decision=pending,executedDecision=account.get('pendingDecision'),inputReferences={k:s.get('inputSnapshot') for k,s in sources.items()},historicalBackfill=True)
            _commit(portable,working,account['revision'],completed);account=working
            progress((index+1)/max(1,len(todo))*.95,'模拟账户已保存 '+stamp)
        artifacts=[]
        for name in TABLES:
            frame=pd.DataFrame(records.rows(store,dict(accountId=account['id']),name));artifacts.append(engines.save_table(output,name,frame))
        return dict(metrics=dict(nav=account['nav'],cash=account['cash'],unitNav=account['unitNav'],completedDays=len(todo)),artifacts=artifacts,parameters=params,
            summary='共享模拟账户更新至 '+str(account['asOfDate']),details=dict(accountId=account['id'],account=account,status='partial' if account['unresolved'] else 'complete',failures=failures,
                accountingBasis='raw_shares_cash',signalTiming='信号日收盘决策，下一交易日执行；未成交当日到期',inputReferences={k:s.get('inputSnapshot') for k,s in sources.items()}))
    except Exception as exc:
        latest=records.get(store,params)
        if latest['revision']==account['revision']:
            failed=deepcopy(latest);failed.update(status='blocked',unresolved=dict(date=params['endDate'],message=str(exc)),revision=latest['revision']+1,updatedAt=now(),valuationStatus='unavailable',lastAdvanceRevision=None)
            try:_commit(portable,failed,latest['revision'])
            except ValueError:pass
        raise


def research(store,params,output,progress,submitted,source):
    """Read-only signals from the account's submitted bindings and ownership versions."""
    from .selection import update_end_date
    account=deepcopy(submitted);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    date=params.get('date') or update_end_date()
    if date>update_end_date():raise ValueError('研究日期尚无已完成日线')
    if account['asOfDate'] and date<account['asOfDate']:raise ValueError('不能用当前账户持仓计算过去信号，请先创建历史分支')
    sources,failures=prepare_sources(store,account,{**params,'endDate':date},output,progress)
    prices,actions,conflicts=merged_market(sources);day=pd.Timestamp(date)
    today=prices[prices.date.eq(day)].set_index('symbol')
    for owner in account['ownership']:
        if not (owner['quantity'] or owner['pendingQuantity']):continue
        if owner['symbol'] not in today.index or (day,owner['symbol']) in conflicts:raise ValueError('账户持仓当日估值不可用，请核对来源后再研究')
    if account['asOfDate'] and date>account['asOfDate']:
        if any(account['asOfDate']<str(a.get('exDate',''))<=date and a['symbol'] in account['state']['holdings'] for a in actions):raise ValueError('持仓跨公司行动，请先明确推进账户后研究')
    account['nav']=account['cash']+account['state'].get('receivables',0)+sum((h['quantity']+h.get('pendingQuantity',0))*float(today.loc[s,'rawClose']) for s,h in account['state']['holdings'].items() if h['quantity'] or h.get('pendingQuantity',0))
    decision=next_decision(store,account,sources,day,output,failures)
    rows=[]
    for intent in decision['intents']:
        owner=next((o for o in account['ownership'] if o['id']==intent['ownershipId']),None)
        current=owner['quantity']+owner['pendingQuantity'] if owner else 0
        rows.append(dict(symbol=intent['symbol'],bindingId=intent['bindingId'],versionId=intent['versionId'],ownershipId=intent['ownershipId'],signalDate=date,currentQuantity=current,targetQuantity=intent['targetQuantity'],requestedDelta=intent['targetQuantity']-current,status='proposal'))
    artifacts=[engines.save_table(output,'candidates',pd.DataFrame(rows)),engines.save_table(output,'binding_events',pd.DataFrame(decision['failures']))]
    return dict(metrics=dict(candidates=len(rows)),artifacts=artifacts,parameters=params,summary='账户固定版本只读研究；未推进账户、未成交',
        details=dict(accountId=account['id'],positionsSourceResolved=source,positionsSnapshot=dict(cash=submitted['cash'],asOfDate=submitted['asOfDate'],rows=[dict(symbol=s,**h) for s,h in submitted['state']['holdings'].items()]),
            bindings=submitted['bindings'],ownership=submitted['ownership'],dataDate=date,executable=False,status='partial' if decision['failures'] else 'complete',failures=decision['failures'],
            message='只读建议来自账户固定绑定版本；旧仓沿入场版本退出，实际交易需明确推进账户。'))


def advance_cash(store,account,params,output,progress,submitted):
    from .simulation import _commit,TABLES
    calendar=submitted.get('calendarSnapshot')
    if calendar is None:raise ValueError('空现金账户需先准备共享本地交易日历，未推算交易日')
    if account['state'].get('receivables') or account['state'].get('pendingShares'):raise ValueError('账户仍有待结算权益，不能按纯现金推进')
    dates=[d for d in calendar if d<=params['endDate'] and (not account['asOfDate'] or d>account['asOfDate'])]
    portable=store.project_store(None)
    for date in dates:
        updated=deepcopy(account);updated['state']['asOfDate']=date
        updated.update(asOfDate=date,revision=account['revision']+1,status='ready',unresolved=None,updatedAt=now(),lastAdvanceJobId=params['_advanceJobId'],lastAdvanceExpectedRevision=params['expectedRevision'],lastAdvanceRevision=account['revision']+1)
        tables={name:[] for name in TABLES}
        tables['portfolio']=[dict(date=date,account=account['nav'],cash=account['cash'],unitNav=account['unitNav'],units=account['units'],netContributions=account['netContributions'],netReturn=0. if account['unitNav'] is not None else None)]
        completed=dict(id=account['id']+':'+date,accountId=account['id'],date=date,createdAt=now(),tables=tables,decision=None,executedDecision=None,historicalBackfill=True,inputReferences={'calendar':calendar})
        _commit(portable,updated,account['revision'],completed);account=updated;progress(.9,'现金账户已保存 '+date)
    artifacts=[engines.save_table(output,name,pd.DataFrame(records.rows(store,dict(accountId=account['id']),name))) for name in TABLES]
    return dict(metrics=dict(nav=account['nav'],cash=account['cash'],unitNav=account['unitNav'],completedDays=len(dates)),artifacts=artifacts,parameters=params,summary='纯现金模拟账户更新至 '+str(account['asOfDate']),details=dict(accountId=account['id'],account=account,status='complete',calendarSnapshot=calendar))
