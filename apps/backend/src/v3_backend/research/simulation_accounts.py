"""Shared paper-account records and versioned mutations in the existing SQLite store."""
from copy import deepcopy
import json
import math
import pandas as pd
from .storage import identifier, now
from . import accounting

EXTRA_TABLES=('cash_flows','ownership','trade_allocations','binding_events')


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)


def positive(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
        raise ValueError(label+'必须为有限正数')
    return float(value)


def date_value(value):
    date=pd.Timestamp(value)
    if pd.isna(date):raise ValueError('日期无效')
    return str(date.date())


def get_record(db,kind,key,schema='main'):
    row=db.execute(f'SELECT body FROM {schema}.records WHERE kind=? AND id=?',(kind,key)).fetchone()
    if row is None:raise ValueError('记录不存在：'+kind+'/'+str(key))
    return json.loads(row[0])


def put_record(db,kind,value):
    db.execute('INSERT OR REPLACE INTO records(kind,id,project,body) VALUES(?,?,?,?)',
        (kind,value['id'],value.get('projectId') or '',encoded(value)))


def revision(account,expected):
    if type(expected) is not int or expected!=account['revision']:
        raise ValueError('模拟账户版本已变化，请重新读取后操作')


def get(store,params):
    value=store.project_store(params.get('projectId')).get('simulation',params['accountId'])
    if value.get('projectId')!=params.get('projectId'):raise ValueError('模拟账户不属于此范围')
    return value


def ownership_from_state(state):
    return [dict(id=identifier(),symbol=s,bindingId=None,entryVersionId=None,management='manual',
        quantity=h['quantity'],sellableQuantity=h.get('sellableQuantity',0),pendingQuantity=h.get('pendingQuantity',0),
        costBasis=h.get('costBasis')) for s,h in state['holdings'].items() if h['quantity'] or h.get('pendingQuantity',0)]


def validate_ownership(account):
    ids=[o['id'] for o in account['ownership']]
    if len(set(ids))!=len(ids):raise ValueError('持仓归属ID重复')
    for owner in account['ownership']:
        for field in ('quantity','sellableQuantity','pendingQuantity'):
            value=owner[field]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise ValueError('持仓归属数量无效')
        if owner['sellableQuantity']>owner['quantity']:raise ValueError('持仓归属可卖量超过持仓')
    for symbol in set(account['state']['holdings'])|{o['symbol'] for o in account['ownership']}:
        held=account['state']['holdings'].get(symbol,{})
        for field in ('quantity','sellableQuantity','pendingQuantity'):
            amount=sum(o[field] for o in account['ownership'] if o['symbol']==symbol)
            if not math.isclose(amount,held.get(field,0),rel_tol=0,abs_tol=1e-8):raise ValueError('持仓归属数量不守恒：'+symbol+'/'+field)


def new_account(params):
    cash=positive(params.get('capital',1000000),'初始资金')
    name=str(params.get('name') or '模拟账户').strip()
    if not name:raise ValueError('请输入账户名称')
    if params.get('strategyId'):raise ValueError('全局账户请显式绑定策略，不使用当前项目策略')
    state=accounting.create(cash)
    return dict(id=identifier(),schemaVersion=2,name=name,projectId=None,strategyId=None,
        startDate=date_value(params['startDate']),capital=cash,nav=cash,cash=cash,asOfDate=None,
        state=state,pendingDecision=None,modelState=None,revision=0,status='ready',paused=False,
        unresolved=None,bindings=[],ownership=[],netContributions=cash,unitNav=1.,units=cash,
        valuationStatus='known',createdAt=now(),updatedAt=now())


def preview_source(store,source):
    """Read configuration and supplemental content; never copy or run a source."""
    import hashlib
    from pathlib import Path
    if not isinstance(source,dict):raise ValueError('请明确绑定来源')
    if source.get('kind')=='dailyPlan':
        record=deepcopy(store.get('daily_plan',source['dailyPlanId']))
        if not record.get('enabled'):raise ValueError('每日方案尚未启用')
        plan=record['planSnapshot'];project=deepcopy(store.project(None))
        project['universe']=deepcopy(plan['universe'])
        if plan.get('dataProjectId'):
            from .data import project_data
            project['settings']['dataPath']=str(Path(project_data(store.project(plan['dataProjectId']))['path'])/'data')
        snapshot=dict(kind='dailyPlan',project=project,plan=plan);name=record['name']
    elif source.get('kind')=='strategy':
        from .workbench import strategy_project,get_strategy
        record=deepcopy(get_strategy(store,source['projectId'],source['strategyId']))
        project=strategy_project(store,source['projectId'],source['strategyId'])
        snapshot=dict(kind='strategy',project=project);name=record['name']
    else:raise ValueError('未知绑定来源')
    universe=project['universe'];query=universe.get('query') or universe
    if query.get('watchlistId'):
        watch=store.get('watchlist',query.pop('watchlistId'));symbols=set(watch['symbols'])
        if query.get('symbols') is not None:symbols &= set(query['symbols'])
        query['symbols']=sorted(symbols)
    from .app_settings import source_settings
    project.setdefault('settings',{})['dataSources']=source_settings(store.settings())
    files=[]
    def inspect(value,root):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in {'codePath','dataPath','trainingEventsPath'} and isinstance(item,str) and item:
                    path=(root/item).resolve()
                    if path.is_file():
                        digest=hashlib.sha256()
                        with path.open('rb') as stream:
                            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
                        files.append(dict(path=str(path),content=digest.hexdigest()))
                    elif key!='dataPath':raise ValueError('绑定引用文件不可用：'+item)
                else:inspect(item,root)
        elif isinstance(value,list):
            for item in value:inspect(item,root)
    inspect(project['settings'],Path(project['path']))
    if source['kind']=='dailyPlan':
        for asset in plan.get('assets',[]):
            if asset.get('snapshotOwner')=='shared':root=Path(project['path'])
            elif asset.get('projectId'):root=Path(store.project(asset['projectId'])['path'])
            elif asset['id'].startswith('library:'):root=store.root/'shared/factor-library'/asset['id'].split(':')[1]
            else:root=Path(project['path'])
            inspect(asset.get('snapshot',{}),root)
    from . import history,data
    historical_project=deepcopy(store.project(plan['dataProjectId'])) if source['kind']=='dailyPlan' and plan.get('dataProjectId') else project
    historical_project['universe']=deepcopy(project['universe'])
    membership=history.membership_frame(historical_project)
    historical=dict(membership=data.records(membership) if membership is not None else None,industry=data.records(history.read(historical_project,'industry')))
    version=hashlib.sha256(encoded(dict(source=source,record=record,snapshot=snapshot,files=files,historical=historical)).encode()).hexdigest()
    return dict(source=deepcopy(source),name=name,sourceVersion=version,snapshot=snapshot)


def freeze_version(store,source,expected=None):
    preview=preview_source(store,source)
    if expected is not None and preview['sourceVersion']!=expected:raise ValueError('绑定来源已变化，请重新预览')
    if source.get('kind')=='dailyPlan':
        from .daily_plans import freeze
        from .app_settings import source_settings
        references=freeze(store,[source['dailyPlanId']],source_settings(store.settings()))
        if not references:raise ValueError('每日方案占比为零，不能绑定')
        ref=references[0]
        if ref.get('freezeError'):raise ValueError(ref['freezeError']['message'])
        snapshot=dict(kind='dailyPlan',project=ref['project'],plan=ref['planSnapshot'])
        name=ref['name'];version=str(ref['planVersion'])
    elif source.get('kind')=='strategy':
        from .workbench import strategy_project,get_strategy
        from .candidate_library import _copy_files
        from pathlib import Path
        project=strategy_project(store,source['projectId'],source['strategyId'])
        config=get_strategy(store,source['projectId'],source['strategyId'])
        root=Path(project['path']);destination=root/'.research/simulation-inputs'/identifier()
        for key in ('backtest','model','factors'):
            if key in project['settings']:_copy_files(project['settings'][key],root,destination,root)
        query=project['universe'].get('query') or project['universe']
        if query.get('watchlistId'):
            watch=store.get('watchlist',query.pop('watchlistId'))
            symbols=set(watch['symbols'])
            if query.get('symbols') is not None:symbols &= set(query['symbols'])
            query['symbols']=sorted(symbols)
        snapshot=dict(kind='strategy',project=project)
        name=config['name'];version=config.get('updatedAt')
    else:raise ValueError('未知绑定来源')
    if preview_source(store,source)['sourceVersion']!=preview['sourceVersion']:raise ValueError('绑定来源已变化，请重新预览')
    snapshot['project'].setdefault('settings',{})['dataSources']=deepcopy(preview['snapshot']['project']['settings']['dataSources'])
    return name,dict(id=identifier(),sourceVersion=preview['sourceVersion'],createdAt=now(),snapshot=snapshot)


def checkpoint(db,account):
    key=account['id']+':'+str(account['asOfDate'] or 'initial')
    put_record(db,'simulation_checkpoint',dict(id=key,account=deepcopy(account)))


def rows(store,params,table):
    account=get(store,params)
    if table=='ownership':return deepcopy(account.get('ownership',[]))
    portable=store.project_store(params.get('projectId'))
    if table in ('cash_flows','binding_events'):
        kind='simulation_cash_flow' if table=='cash_flows' else 'simulation_binding_event'
        mutations=sorted([x for x in portable.list(kind) if x['accountId']==account['id']],key=lambda x:(x['createdAt'],x['id']))
        if table=='cash_flows':return mutations
        from .simulation import _days
        return mutations+[row for day in _days(portable,account['id']) for row in day['tables'].get(table,[])]
    from .simulation import _days
    return [row for day in _days(portable,account['id']) for row in day['tables'].get(table,[])]


def dispatch(store,method,params):
    operation=method.removeprefix('simulation.accounts.')
    if operation=='bindings.preview':
        account=get(store,params)
        binding=next((b for b in account.get('bindings',[]) if b['id']==params.get('bindingId')),None)
        if params.get('bindingId') and binding is None:raise ValueError('绑定不存在')
        return preview_source(store,binding['source'] if binding else params.get('source'))
    portable=store.project_store(None)
    request_id=params.get('requestId')
    idempotent=operation in {'cashFlows.create','importLegacy','branch'}
    if idempotent and (not isinstance(request_id,str) or not request_id.strip()):raise ValueError('请提供请求ID')
    payload=encoded(dict(method=method,params=params))
    with portable.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if idempotent:
            prior=db.execute('SELECT body FROM records WHERE kind=? AND id=?',('simulation_request',request_id)).fetchone()
            if prior:
                saved=json.loads(prior[0])
                if saved['payload']!=payload:raise ValueError('请求ID已用于不同内容')
                return saved['result']
        if operation=='create':
            account=new_account(params);put_record(db,'simulation',account);checkpoint(db,account);result=account
        elif operation=='importLegacy':
            source=params.get('source',{})
            if not source.get('projectId'):raise ValueError('迁入来源必须是旧项目账户')
            db.execute('ATTACH DATABASE ? AS legacy',(str(store.project_store(source['projectId']).db),))
            old=get_record(db,'simulation',source['accountId'],'legacy');revision(old,params.get('expectedRevision'))
            if old.get('projectId')!=source['projectId']:raise ValueError('旧账户范围不符')
            account=deepcopy(old);account.update(id=identifier(),schemaVersion=2,projectId=None,strategyId=None,
                name=str(params.get('name') or old['name']),origin=dict(source,revision=old['revision'],asOfDate=old['asOfDate']),
                bindings=[],ownership=ownership_from_state(old['state']),revision=0,createdAt=now(),updatedAt=now(),
                pendingDecision=None,modelState=None,valuationSources=[deepcopy(store.project(source['projectId']))],netContributions=old['capital'],unitNav=None,units=None,
                valuationStatus='unavailable',status='blocked',paused=False,
                unresolved=dict(date=old['asOfDate'],message='迁入持仓按手工管理；原规则归属及现金流净值历史未确认，请先估值，未使用当前策略'))
            if not account['ownership'] and not account['state'].get('receivables'):
                account.update(nav=account['state']['cash'],cash=account['state']['cash'],unitNav=1.,units=account['state']['cash'],valuationStatus='known')
            put_record(db,'simulation',account);checkpoint(db,account);result=account
        else:
            account=get_record(db,'simulation',params['accountId']);revision(account,params.get('expectedRevision'))
            if account.get('schemaVersion')!=2:raise ValueError('请先显式迁入旧账户')
            if operation=='branch':
                date=date_value(params['fromDate'])
                saved=get_record(db,'simulation_checkpoint',account['id']+':'+date)['account']
                copied=deepcopy(saved);copied.update(id=identifier(),name=str(params.get('name') or account['name']+' 分支'),
                    branchOf=dict(accountId=account['id'],projectId=None,date=date,revision=account['revision']),revision=0,createdAt=now(),updatedAt=now())
                put_record(db,'simulation',copied);checkpoint(db,copied)
                # Preserve complete dated history through the chosen checkpoint.
                for kind in ('simulation_day','simulation_checkpoint','simulation_cash_flow','simulation_binding_event'):
                    for row in db.execute('SELECT body FROM records WHERE kind=?',(kind,)).fetchall():
                        value=json.loads(row[0])
                        owned=value.get('accountId')==account['id'] or value.get('id','').startswith(account['id']+':')
                        stamp=value.get('date') or value.get('account',{}).get('asOfDate')
                        if not owned or not stamp or stamp>date:continue
                        value=deepcopy(value);value['id']=copied['id']+':'+value['id'];value['accountId']=copied['id']
                        if kind=='simulation_day':value['id']=copied['id']+':'+stamp
                        if kind=='simulation_checkpoint':
                            if stamp==date:continue
                            value['id']=copied['id']+':'+stamp;value['account']['id']=copied['id']
                        put_record(db,kind,value)
                result=copied
            else:
                event=None
                if operation=='save':
                    if 'name' in params:
                        account['name']=str(params['name']).strip()
                        if not account['name']:raise ValueError('请输入账户名称')
                    if 'paused' in params:
                        if type(params['paused']) is not bool:raise ValueError('暂停状态须为布尔值')
                        account['paused']=params['paused']
                        account['status']='paused' if params['paused'] else ('blocked' if account.get('unresolved') else 'ready')
                elif operation in {'bindings.save','bindings.adopt'}:
                    binding=next((x for x in account['bindings'] if x['id']==params.get('bindingId')),None)
                    if params.get('bindingId') and binding is None:raise ValueError('绑定不存在')
                    if operation=='bindings.adopt' and binding is None:raise ValueError('请选择要采用新版本的绑定')
                    if binding is None:
                        source=deepcopy(params.get('source'));name,version=freeze_version(store,source)
                        binding=dict(id=identifier(),source=source,name=name,allocation=0.,allowNewEntries=True,currentVersionId=version['id'],versions=[version])
                        account['bindings'].append(binding)
                    elif 'source' in params and params['source']!=binding['source']:raise ValueError('不能替换已有绑定的来源，请新增绑定')
                    elif operation=='bindings.adopt':
                        if not params.get('expectedSourceVersion') or preview_source(store,binding['source'])['sourceVersion']!=params['expectedSourceVersion']:raise ValueError('绑定来源已变化，请重新预览')
                        name,version=freeze_version(store,binding['source'],params['expectedSourceVersion']);binding.update(name=name,currentVersionId=version['id']);binding['versions'].append(version)
                    if 'allocation' in params:
                        from .daily_plans import _allocation
                        binding['allocation']=_allocation(params['allocation'])
                    if sum(b['allocation'] for b in account['bindings'])>1+1e-9:raise ValueError('绑定资金占比不得超过100%')
                    if 'allowNewEntries' in params:
                        if type(params['allowNewEntries']) is not bool:raise ValueError('新开仓选项须为布尔值')
                        binding['allowNewEntries']=params['allowNewEntries']
                    event=dict(bindingId=binding['id'],versionId=binding['currentVersionId'],action=operation)
                elif operation in {'ownership.transferToManual','ownership.liquidate'}:
                    ids=params.get('ownershipIds')
                    if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids):raise ValueError('请选择不重复的持仓归属')
                    selected=[x for x in account['ownership'] if x['id'] in ids]
                    if len(selected)!=len(ids):raise ValueError('持仓归属不存在')
                    if operation.endswith('transferToManual'):
                        for item in selected:item.update(management='manual',bindingId=None,entryVersionId=None)
                        if account.get('pendingDecision'):
                            pending=account['pendingDecision']
                            pending['intents']=[i for i in pending.get('intents',[]) if i['ownershipId'] not in ids]
                        account['liquidationOwnershipIds']=[x for x in account.get('liquidationOwnershipIds',[]) if x not in ids]
                    else:
                        from .execution import cost_config
                        account['liquidationOwnershipIds']=list(dict.fromkeys(account.get('liquidationOwnershipIds',[])+ids))
                        if account['asOfDate']:
                            pending=account.setdefault('pendingDecision',None) or dict(date=account['asOfDate'],intents=[],reasons=[],failures=[])
                            pending['intents']=[i for i in pending.get('intents',[]) if i['ownershipId'] not in ids]
                            for owner in selected:pending['intents'].append(dict(ownershipId=owner['id'],bindingId=owner['bindingId'],versionId=owner['entryVersionId'],symbol=owner['symbol'],targetQuantity=0.,costs=cost_config({}),liquidate=True))
                            account['pendingDecision']=pending
                    event=dict(action=operation,ownershipIds=ids)
                elif operation=='cashFlows.create':
                    amount=positive(params.get('amount'),'金额');direction=params.get('direction')
                    if direction not in {'deposit','withdraw'}:raise ValueError('请选择入金或出金')
                    if direction=='deposit' and account.get('units')==0 and account['nav']==0 and not any(o['quantity'] or o['pendingQuantity'] for o in account['ownership']) and not account['state'].get('receivables'):
                        account.update(unitNav=1.,valuationStatus='known')
                    if account.get('valuationStatus')!='known' or not account.get('unitNav') or account['unitNav']<=0:raise ValueError('账户估值未确定，不能计算现金流份额')
                    if direction=='withdraw' and amount>account['state']['cash']:raise ValueError('可用现金不足；未发出卖单')
                    delta=amount if direction=='deposit' else -amount
                    flow=dict(id=identifier(),accountId=account['id'],date=account['asOfDate'] or account['startDate'],direction=direction,amount=amount,
                        effectivePhase='after_close' if account['asOfDate'] else 'before_start',navBefore=account['nav'],navAfter=account['nav']+delta,unitNav=account['unitNav'],unitsBefore=account['units'],unitsAfter=account['units']+delta/account['unitNav'],createdAt=now(),note=str(params.get('note','')))
                    account['state']['cash']+=delta;account['cash']=account['state']['cash'];account['nav']+=delta
                    account['netContributions']+=delta;account['units']+=delta/account['unitNav']
                    put_record(db,'simulation_cash_flow',flow)
                else:raise ValueError('未知共享账户操作')
                account.update(revision=account['revision']+1,updatedAt=now());validate_ownership(account)
                put_record(db,'simulation',account);checkpoint(db,account)
                if event:
                    event.update(id=identifier(),accountId=account['id'],date=account['asOfDate'] or account['startDate'],revision=account['revision'],createdAt=now())
                    put_record(db,'simulation_binding_event',event)
                result=dict(account=account,cashFlow=flow) if operation=='cashFlows.create' else account
        if idempotent:put_record(db,'simulation_request',dict(id=request_id,payload=payload,result=result))
        return deepcopy(result)
