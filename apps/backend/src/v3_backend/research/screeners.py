"""Saved standalone screening plans using the existing jobs and experiment stores."""
from copy import deepcopy
import json
import math
from pathlib import Path
from .storage import identifier, now, read_json
from .screen_conditions import validate


def normalize(value):
    plan = deepcopy(value)
    if 'mode' not in plan:  # Older simple screeners keep equivalent filter logic.
        query = plan.get('query', {})
        plan.update(mode='conditions', conditions={'id':'root','match':query.get('match','all'),
            'children':[dict(rule,id='legacy-'+str(i)) for i,rule in enumerate(query.get('filters',[]))]},
            universe=dict(name='原筛选范围',source='manual' if query.get('symbols') is not None else 'all',
                          symbols=query.get('symbols',[]),excludeST=False,minListingDays=0,
                          **({'watchlistId':query['watchlistId']} if query.get('watchlistId') else {})),date=query.get('date'))
    plan.setdefault('factors',[])
    plan.setdefault('assets',[])
    plan.setdefault('rankingReference','base')
    plan.setdefault('version',1)
    plan.setdefault('conditions',dict(id='root',match='all',children=[]))
    if not str(plan.get('name','')).strip(): raise ValueError('请填写选股方案名称')
    if plan['mode'] not in {'conditions','factors','strategy'}: raise ValueError('未知选股起点')
    if plan['rankingReference'] not in {'base','prefilter'}: raise ValueError('未知排名参照')
    from .workbench import _universe
    plan['universe'] = _universe(plan['universe'])
    validate(plan['conditions'])
    if plan.get('preconditions'): validate(plan['preconditions'],ranking_allowed=False)
    seen = set()
    for factor in plan['factors']:
        if factor.get('id') in seen: raise ValueError('同一因子不能重复计权')
        seen.add(factor.get('id'))
        weight = factor.get('weight')
        if factor.get('direction') not in {-1,1} or isinstance(weight,bool) or not isinstance(weight,(int,float)) or not math.isfinite(weight) or weight < 0:
            raise ValueError('因子方向和非负权重无效')
    if plan.get('limit') is not None and (isinstance(plan['limit'],bool) or not isinstance(plan['limit'],int) or plan['limit']<1):
        raise ValueError('入选数量须为正整数')
    return plan


def configuration(plan):
    return {k:v for k,v in plan.items() if k not in {'id','name','version','updatedAt','lastUsedAt','favorite','archived'}}


def freeze_assets(store, plan):
    from .candidate_library import _copy_files
    root=Path(store.project(None)['path'])
    for asset in plan['assets']:
        if asset.get('snapshotOwner')=='shared': continue
        if asset['kind']=='strategy':
            asset['snapshot'].get('settings',{}).pop('dataPath',None)
        source=None
        if asset.get('projectId'):source=Path(store.project(asset['projectId'])['path'])
        elif asset['id'].startswith('library:'):
            key=asset['id'].split(':')[1];store.get('candidate_library',key)
            source=store.root/'shared/factor-library'/key
        if source:
            _copy_files(asset['snapshot'],source,root/'.research/screener-assets'/identifier(),root)
            asset['snapshotOwner']='shared'


def assets(store):
    from .engines import factor_catalog
    from .workbench import list_strategies
    rows=[]
    def candidate_factors(candidate, base, prefix):
        if candidate.get('kind')!='factor': return
        params=candidate.get('spec',{}).get('parameters',{})
        custom={f['id']:f for f in params.get('customFactors',[])}
        for factor_id in params.get('factorIds',[]):
            snapshot=dict(factorId=factor_id)
            if factor_id in custom: snapshot['customFactor']=deepcopy(custom[factor_id])
            rows.append(dict(base,id=prefix+':'+factor_id,kind='factor',
                name=candidate['name']+' · '+custom.get(factor_id,{}).get('name',factor_id),snapshot=snapshot))
    for factor in factor_catalog():
        rows.append(dict(id='builtin:'+factor['id'],kind='factor',name=factor['name'],revision='builtin-1',
                         snapshot=dict(factorId=factor['id'],expression=factor['expression']),available=True,projectName='内置因子'))
    for project in store.list('project'):
        try:
            strategies=list_strategies(store,project['id'])
            for candidate in store.project_store(project['id']).list('candidate',project['id']):
                candidate_factors(candidate,dict(projectId=project['id'],projectName=project['name'],
                    revision=str(candidate['revision']),available=True), 'candidate:'+project['id']+':'+candidate['id'])
            for strategy in strategies:
                base=dict(projectId=project['id'],projectName=project['name'],revision=str(strategy['updatedAt']),available=True)
                rows.append(dict(base,id='strategy:'+project['id']+':'+strategy['id'],kind='strategy',name=strategy['name'],
                    snapshot=dict(strategyId=strategy['id'],universe=strategy['universe'],settings=strategy['settings'])))
                for factor in strategy['settings'].get('customFactors',[]):
                    rows.append(dict(base,id='factor:'+project['id']+':'+strategy['id']+':'+factor['id'],kind='factor',
                        name=factor.get('name',factor['id']),snapshot=dict(factorId=factor['id'],customFactor=factor)))
            for experiment in store.experiments(project['id']):
                if experiment['kind']=='model.train':
                    present=all(store.artifact_path(project['id'],a).exists() for a in experiment['artifacts'])
                    rows.append(dict(id='model:'+project['id']+':'+experiment['id'],kind='model',name=experiment['name'],
                        projectId=project['id'],projectName=project['name'],revision=experiment['id'],experimentId=experiment['id'],
                        snapshot=dict(parameters=experiment['parameters'],modelExperimentId=experiment['id']),available=present,
                        **({} if present else {'reason':'模型产物缺失'})))
        except (ValueError,FileNotFoundError):
            continue
    for item in store.list('candidate_library'):
        candidate_factors(item['candidate'],dict(projectName='个人共用库',revision=str(item['sourceRevision']),
            available=True), 'library:'+item['id'])
    return rows


def latest_result(store, plan_id, experiment_id=None):
    matches=[e for e in store.experiments(None) if e['kind']=='screener.run' and
             e.get('parameters',{}).get('plan',{}).get('id')==plan_id and (not experiment_id or e['id']==experiment_id)]
    return max(matches,key=lambda e:e['createdAt']) if matches else None


def result_table(store, experiment):
    import pandas as pd
    artifact=next(a for a in experiment['artifacts'] if a['name']=='screening')
    return pd.read_parquet(store.artifact_path(None,artifact))


def _decode_explanation(row):
    for key in ('conditions','contributions'):
        if isinstance(row.get(key),str):row[key]=json.loads(row[key])
    return row


def freeze_run(store, plan):
    target=deepcopy(store.project(None))
    source_id=plan.get('dataProjectId')
    if source_id:
        from .data import project_data
        target['settings']['dataPath']=str(Path(project_data(store.project(source_id))['path'])/'data')
    target['universe']=deepcopy(plan['universe'])
    if target['universe'].get('watchlistId'):
        watch=store.get('watchlist',target['universe'].pop('watchlistId'))
        selected=set(watch['symbols'])
        if target['universe']['source']=='manual': selected &= set(target['universe']['symbols'])
        target['universe'].update(source='manual',symbols=sorted(selected))
    if target['universe'].get('membershipRef') and not source_id:
        raise ValueError('历史成员引用需选择所属项目数据')
    if target['universe'].get('membershipRef'):
        from .history import membership_frame, import_membership
        source=deepcopy(store.project(source_id))
        source['universe']=deepcopy(target['universe'])
        ref=target['universe']['membershipRef']
        import_membership(target,membership_frame(source),pool_id=ref['poolId'],source=ref.get('source','import'))
    # Resolve source code/data into a plan-owned immutable copy at submission.
    from .candidate_library import _copy_files
    copy_root=Path(target['path'])/'.research/screener-inputs'/identifier()
    for asset in plan['assets']:
        if not asset.get('available',True): raise ValueError('所选成果不可用：'+asset['name'])
        if asset.get('snapshotOwner')=='shared':
            _copy_files(asset['snapshot'],Path(target['path']),copy_root,Path(target['path']))
        elif asset.get('projectId'):
            source=Path(store.project(asset['projectId'])['path'])
            _copy_files(asset['snapshot'],source,copy_root,Path(target['path']))
        elif asset['id'].startswith('library:'):
            library_id=asset['id'].split(':')[1]
            store.get('candidate_library',library_id)
            _copy_files(asset['snapshot'],store.root/'shared/factor-library'/library_id,copy_root,Path(target['path']))
    return target


def dispatch(service, method, params):
    store=service.store
    if method=='screeners.workspace.get':
        try: return store.get('screener_workspace','current').get('state',{})
        except ValueError: return {}
    if method=='screeners.workspace.save':
        state=deepcopy(params['state'])
        if not isinstance(state,dict): raise ValueError('工作区状态无效')
        store.put('screener_workspace',dict(id='current',state=state))
        return state
    if method=='screeners.list':
        return sorted([normalize(x) for x in store.list('screener')],key=lambda x:x.get('lastUsedAt') or x.get('updatedAt',''),reverse=True)
    if method=='screeners.get': return normalize(store.get('screener',params['id']))
    if method=='screeners.save':
        value=normalize(params.get('plan') or params.get('screener'))
        freeze_assets(store,value)
        if value.get('id'):
            old=normalize(store.get('screener',value['id']))
            value['version']=old['version']+(configuration(value)!=configuration(old))
        else:
            value.update(id=identifier(),version=1)
        value.update(updatedAt=now())
        return store.put('screener',value)
    if method=='screeners.delete':
        store.delete('screener',params['id'])
        return dict(deleted=True)
    if method=='screeners.assets':
        query=str(params.get('search','')).casefold()
        return [a for a in assets(store) if (not params.get('kind') or a['kind']==params['kind']) and
                (not query or query in (a['name']+' '+a.get('projectName','')).casefold())]
    if method=='screeners.run':
        plan=normalize(store.get('screener',params['planId']))
        if plan.get('archived'): raise ValueError('请先取消方案归档')
        if plan['mode']=='factors' and (not plan['factors'] or sum(f['weight'] for f in plan['factors'])<=0):
            raise ValueError('因子模式需要选择因子且权重合计大于零')
        if plan['mode']=='strategy' and not any(a['kind']=='strategy' for a in plan['assets']):
            raise ValueError('请选择一份明确版本的策略')
        target=freeze_run(store,plan)
        parameters=dict(plan=plan,allowPartial=bool(params.get('allowPartial')))
        if params.get('assistantOperationId'): parameters['assistantOperationId']=params['assistantOperationId']
        event=service.jobs.submit(dict(kind='screener.run',name=plan['name'],parameters=parameters),frozen_project=target)
        old=store.get('screener',plan['id']);old['lastUsedAt']=now();store.put('screener',old)
        return event
    if method=='screeners.result':
        experiment=latest_result(store,params['planId'],params.get('experimentId'))
        if experiment is None:return None
        from .data import records
        from .market import _search_names
        frame=result_table(store,experiment)
        if params.get('search'):frame=frame[_search_names(frame,params['search'])]
        if params.get('status'):frame=frame[frame.status.eq(params['status'])]
        if params.get('includedOnly'):frame=frame[frame.status.eq('included')]
        sort=params.get('sortBy') or 'score'
        if sort in frame:frame=frame.sort_values(sort,ascending=not params.get('descending',True),kind='stable',na_position='last')
        total=len(frame);offset=max(0,int(params.get('offset',0)));limit=max(1,min(500,int(params.get('limit',100))))
        folder=Path(store.project(None)['path'])/'.research/runs'/experiment['id']
        details=read_json(folder/'details.json',{})
        try: changed=normalize(store.get('screener',params['planId']))['version']!=experiment['parameters']['plan']['version']
        except ValueError:changed=True
        rows=[_decode_explanation(row) for row in records(frame.iloc[offset:offset+limit])]
        result=dict(name='screening',columns=list(frame.columns),rows=rows,total=total,
                    offset=offset,limit=limit,experimentId=experiment['id'],asOfDate=details.get('asOfDate',''),
                    status=details.get('status','preview'),counts=details.get('counts',{}),configChanged=changed,
                    message=details.get('message',''),diff=details.get('diff',{}))
        if isinstance(details.get('coverage'),dict):result['coverage']=details['coverage']
        return result
    if method=='screeners.explain':
        from .data import records,symbol
        experiment=store.experiment(None,params['experimentId']);frame=result_table(store,experiment)
        selected=frame[frame.symbol.eq(symbol(params['symbol']))]
        if selected.empty:return dict(symbol=symbol(params['symbol']),status='outside',reason='不在本次运行范围内')
        return _decode_explanation(records(selected.iloc[:1])[0])
    if method=='watchlists.add':
        from .data import symbol
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record=db.execute('SELECT body FROM records WHERE kind=? AND id=?',('watchlist',params['id'])).fetchone()
            if not record:raise ValueError('自选列表不存在')
            value=json.loads(record[0]);symbols=params.get('symbols')
            if symbols is None and params.get('experimentId'):
                frame=result_table(store,store.experiment(None,params['experimentId']))
                symbols=frame.loc[frame.status.eq('included'),'symbol'].tolist()
            symbols=list(dict.fromkeys(map(symbol,symbols or [])))
            if params.get('mode','append') not in {'append','replace'}:raise ValueError('未知自选写入方式')
            value['symbols']=list(dict.fromkeys((value.get('symbols',[]) if params.get('mode','append')=='append' else [])+symbols))
            value['updatedAt']=now()
            db.execute('UPDATE records SET body=? WHERE kind=? AND id=?',(json.dumps(value,ensure_ascii=False),'watchlist',value['id']))
        return value
    raise ValueError('未知选股器操作')
