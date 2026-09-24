"""Fixed screening-plan versions for the shared daily research desk."""
from copy import deepcopy
import math
from .storage import identifier, now
from . import screeners


def _allocation(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('资金占比必须在0至100%之间')
    return value


def describe(store, value):
    result=deepcopy(value)
    try:
        latest=screeners.normalize(store.get('screener',value['planId']))
        result.update(latestVersion=latest['version'],sourceChanged=latest['version']!=value['planVersion'],sourceUnavailable=False)
    except ValueError:result.update(sourceUnavailable=True,sourceChanged=False)
    return result


def dispatch(service, method, params):
    store=service.store
    if method=='dailyPlans.list':return [describe(store,v) for v in store.list('daily_plan')]
    if method=='dailyPlans.delete':
        store.delete('daily_plan',params['id'])
        return dict(deleted=True)
    if method!='dailyPlans.save':raise ValueError('未知每日方案操作')
    value=deepcopy(store.get('daily_plan',params['id'])) if params.get('id') else dict(id=identifier(),allocation=1.,enabled=True)
    if not value.get('planSnapshot') or params.get('adoptLatest') is True:
        plan=screeners.normalize(store.get('screener',params.get('planId') or value['planId']))
        if plan.get('archived'):raise ValueError('请先取消选股方案归档')
        screeners.freeze_assets(store,plan)
        value.update(planId=plan['id'],planVersion=plan['version'],planSnapshot=plan)
        value.setdefault('name',plan['name'])
    elif params.get('planId',value['planId'])!=value['planId']:
        raise ValueError('替换来源须明确采用新版本')
    if 'name' in params:value['name']=str(params['name']).strip()
    if not value.get('name'):raise ValueError('请填写每日方案名称')
    value['allocation']=_allocation(params.get('allocation',value['allocation']))
    if 'enabled' in params:
        if not isinstance(params['enabled'],bool):raise ValueError('启用状态必须为布尔值')
        value['enabled']=params['enabled']
    value['updatedAt']=now()
    store.put('daily_plan',value)
    return describe(store,value)


def freeze(store, ids, sources, freeze_universe=None):
    if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):
        raise ValueError('请选择不重复的每日方案')
    values=[deepcopy(store.get('daily_plan',key)) for key in ids]
    if any(not x['enabled'] for x in values):raise ValueError('所选每日方案尚未启用')
    allocations=[_allocation(x['allocation']) for x in values]
    if not 0 < sum(allocations) <= 1+1e-9:raise ValueError('每日方案资金占比合计必须大于0且不超过100%')
    frozen=[]
    for value in values:
        if value['allocation']==0:continue
        plan=deepcopy(value['planSnapshot'])
        reference=dict(value,planSnapshot=plan)
        try:
            target=screeners.freeze_run(store,plan)
            target.setdefault('settings',{})['dataSources']=deepcopy(sources)
            # Separate monthly model state for each adopted plan version.
            target['strategyId']='daily-'+value['id']+'-'+str(value['planVersion'])
            if freeze_universe is not None:freeze_universe(target)
            reference['project']=target
        except Exception as exc:
            # Persist the failed source resolution too; workers must not resolve it again.
            reference['freezeError']=dict(stage='freeze',message=str(exc) or type(exc).__name__)
        frozen.append(reference)
    return frozen
