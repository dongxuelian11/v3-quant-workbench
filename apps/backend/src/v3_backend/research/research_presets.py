"""User-owned parameter copies. Saving a preset never changes existing research."""
from copy import deepcopy
import math
from .storage import identifier, now

FIELDS = {
    'factorProcessing': {'directions','winsorize','madScale','standardize','neutralizeIndustry','neutralizeSize'},
    'costs': {'commissionBuy','commissionSell','minCommission','stampDuty','transferFee','slippage','volumeParticipation'},
    'portfolio': {'method','grossExposure','maxWeight','industryCap','turnoverLimit','lookback','minObservations','riskAversion','returnSource'},
    'validation': {'mode','trainYears','validMonths','testMonths','stepMonths'},
}


def validate(category, value):
    if category not in FIELDS or not isinstance(value,dict):raise ValueError('请选择因子处理、费用、组合约束或验证预设')
    if set(value)-FIELDS[category]:raise ValueError('预设包含不属于本类别的参数')
    for key,item in value.items():
        if key=='directions':
            if not isinstance(item,dict) or any(type(v) is not int or v not in {-1,1} for v in item.values()):raise ValueError('因子方向必须为1或-1')
        elif item is not None and not isinstance(item,(str,bool,int,float)):
            raise ValueError('预设参数格式无效')
        elif isinstance(item,(int,float)) and not isinstance(item,bool) and (not math.isfinite(item) or item<0):
            raise ValueError('预设数值必须为非负有限数')
    for key in ('grossExposure','maxWeight','industryCap','turnoverLimit'):
        if value.get(key) is not None and (isinstance(value[key],bool) or not isinstance(value[key],(int,float)) or not 0<=value[key]<=1):raise ValueError('仓位与约束须在0到1之间')
    choices={'winsorize':{'mad','none'},'method':{'equal','score','risk_parity','mean_variance'},'returnSource':{'historical','model'},'mode':{'single','rolling'}}
    for key,allowed in choices.items():
        if key in value and value[key] not in allowed:raise ValueError('未知预设选项：'+key)
    for key in ('standardize','neutralizeIndustry','neutralizeSize'):
        if key in value and not isinstance(value[key],bool):raise ValueError('因子处理开关格式无效')
    for key in ('lookback','minObservations','trainYears','validMonths','testMonths','stepMonths'):
        if key in value and (type(value[key]) is not int or value[key]<1):raise ValueError('样本和窗口长度必须为正整数')
    if category=='costs':
        for key,item in value.items():
            if key=='stampDuty' and item=='historical':continue
            if isinstance(item,bool) or not isinstance(item,(int,float)) or (key!='minCommission' and item>1):raise ValueError('费用或参与率格式无效')
    return deepcopy(value)


def dispatch(store, method, params):
    if method=='researchPresets.list':
        return [v for v in store.list('research_preset') if not params.get('category') or v['category']==params['category']]
    if method=='researchPresets.delete':
        store.get('research_preset',params['id'])
        store.delete('research_preset',params['id'])
        return dict(deleted=True)
    if method=='researchPresets.save':
        supplied=params['preset'];old=store.get('research_preset',supplied['id']) if supplied.get('id') else None
        name=str(supplied.get('name','')).strip()
        if not name:raise ValueError('请填写预设名称')
        category=supplied.get('category');value=validate(category,supplied.get('value'))
        if old and old['category']!=category:raise ValueError('不能改变已有预设类别，请另存')
        return store.put('research_preset',dict(id=old['id'] if old else identifier(),name=name,category=category,value=value,
            revision=(old['revision'] if old else 0)+1,createdAt=old['createdAt'] if old else now(),updatedAt=now()))
    raise ValueError('未知研究预设操作')
