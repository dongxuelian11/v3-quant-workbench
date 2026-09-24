"""Compare recorded experiment metadata; never recompute or inspect market tables."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
from .storage import read_json


LABELS = dict(kind='研究类型',startDate='有效开始日期',endDate='有效结束日期',universe='股票范围',
    membershipRef='历史成员版本',actualSymbols='实际输入证券',engineVersions='记录的运行库版本',benchmark='基准',priceBasis='价格口径',accountingBasis='会计口径',
    signalTiming='信号与成交时点',strategyPriceBasis='规则价格口径',engine='计算引擎',
    labelHorizon='标签周期',label='标签定义',periods='因子收益周期',annualizationDays='年化天数',
    annualizedReturnMethod='年化方法',transferFeeMode='过户费口径')


def ref(value):
    if not isinstance(value,dict) or not isinstance(value.get('experimentId'),str) or not value['experimentId']:
        raise ValueError('实验引用需要experimentId及所属projectId')
    project = value.get('projectId') or None
    if project is not None and not isinstance(project,str):raise ValueError('项目引用无效')
    return dict(projectId=project,experimentId=value['experimentId'])


def key(value):
    return value['projectId'],value['experimentId']


def references(params):
    values = params.get('experiments')
    if values is None:
        values = [dict(projectId=params.get('projectId'),experimentId=i) for i in params.get('experimentIds',[])]
    if not isinstance(values,list):raise ValueError('比较实验引用须为列表')
    result = list({key(r):r for r in map(ref,values)}.values())
    if not 2 <= len(result) <= 10:raise ValueError('请选择2至10个不同实验')
    baseline = ref(params['baselineRef']) if params.get('baselineRef') is not None else result[0]
    if key(baseline) not in {key(r) for r in result}:raise ValueError('比较基准必须在所选实验中')
    return result,baseline


def _first(*values):
    return next((v for v in values if v is not None and v != ''),None)


def _dict(value):
    return value if isinstance(value,dict) else {}


def _configuration(value):
    # Run-local copied file paths are not changes in the strategy or in file contents.
    if isinstance(value,list):return [_configuration(v) for v in value]
    if isinstance(value,dict):
        return {k:_configuration(v) for k,v in value.items()
                if k not in {'dataPath','codePath','trainingEventsPath','budgetId','budgetProjectId'} and not k.startswith('_')}
    return value


def _supplemental_inputs(value,prefix='parameters'):
    if isinstance(value,list):
        return [path for index,item in enumerate(value) for path in _supplemental_inputs(item,prefix+'.'+str(index))]
    if not isinstance(value,dict):return []
    found=[]
    for field,item in value.items():
        path=prefix+'.'+field
        if field in {'codePath','dataPath','trainingEventsPath'} and isinstance(item,str) and item:
            found.append(path)
        else:found.extend(_supplemental_inputs(item,path))
    return found


def _snapshot_issue(location,snapshot,metadata,check_cancel):
    if not metadata:return '固定输入元数据不可用'
    inventories=[value for value in (snapshot.get('files'),_dict(metadata.get('reference')).get('files')) if isinstance(value,list)]
    entries=[entry for inventory in inventories for entry in inventory]
    if not entries:return '未记录可核对的输入文件清单'
    checked=set()
    for entry in entries:
        if check_cancel:check_cancel()
        relative=_dict(entry).get('path')
        if not isinstance(relative,str) or not relative:return '输入文件清单包含无效路径'
        if relative in checked:continue
        checked.add(relative)
        path=(location/relative).resolve()
        if not path.is_relative_to(location):return '输入文件清单路径越出快照目录'
        if not path.is_file():return '固定输入文件缺失：'+relative
    return None


def load(store, reference, check_cancel=None):
    if check_cancel:check_cancel()
    experiment = store.experiment(reference['projectId'],reference['experimentId'])
    root = Path(store.project(reference['projectId'])['path']).resolve()
    run = (root/'.research/runs'/reference['experimentId']).resolve()
    if not run.is_relative_to(root/'.research/runs'):raise ValueError('实验路径不属于当前项目')
    details = read_json(run/'details.json',{}) or {}
    project = read_json(run/'project.json',{}) or {}
    snapshot = _dict(experiment.get('inputSnapshot'))
    metadata = {}
    snapshot_issue='未记录固定输入快照'
    if snapshot.get('status')=='available' and snapshot.get('path'):
        location = (root/snapshot['path']).resolve()
        if not location.is_relative_to(root):raise ValueError('实验输入路径不属于当前项目')
        metadata = read_json(location/'snapshot.json',{}) or {}
        snapshot_issue=_snapshot_issue(location,snapshot,metadata,check_cancel)
    frozen = _dict(metadata.get('project')) or project
    effective = {**_dict(metadata.get('parameters')),**_dict(experiment.get('parameters'))}
    preparation = _dict(details.get('preparation'))
    kind = experiment.get('kind')
    universe = _first(effective.get('universe'),frozen.get('universe'),details.get('universe'))
    universe = deepcopy(universe)
    member = _dict(universe).get('membershipRef')
    if isinstance(universe,dict):
        universe.pop('name',None)
        universe.pop('membershipRef',None)
        if isinstance(universe.get('symbols'),list):universe['symbols']=sorted(set(universe['symbols']))
    start = _first(effective.get('testStart') if kind=='model.train' else None,
                   effective.get('startDate'),preparation.get('effectiveStart'),frozen.get('startDate'))
    end = _first(effective.get('testEnd') if kind=='model.train' else None,
                 effective.get('endDate'),preparation.get('effectiveEnd'),frozen.get('endDate'))
    identity = _dict(frozen.get('inputCacheIdentity'))
    actual_symbols=_first(_dict(preparation.get('actualCoverage')).get('symbols'),_dict(identity.get('slice')).get('symbols'))
    context = dict(actualSymbols=sorted(set(actual_symbols)) if isinstance(actual_symbols,list) else None,
                   engineVersions=metadata.get('dependencies'),kind=kind,startDate=str(start)[:10] if start else None,endDate=str(end)[:10] if end else None,
                   universe=universe,membershipRef=member)
    for field in LABELS:
        if field not in context:context[field]=_first(effective.get(field),details.get(field))
    coverage = _first(preparation.get('actualCoverage'),identity.get('slice'),details.get('dataContext'))
    if isinstance(coverage,list):coverage={'datasets':coverage}
    supplemental=_supplemental_inputs(effective)
    if frozen.get('inputPrerequisites'):supplemental.append('inputPrerequisites')
    summary = dict(snapshotStatus='available' if metadata and not snapshot_issue else 'unavailable' if snapshot else 'missing',
                   sourceExperimentId=snapshot.get('sourceExperimentId'),
                   recordedVersionAvailable=bool(identity.get('sourceFiles')),coverage=coverage)
    if check_cancel:check_cancel()
    return dict(ref=reference,experiment=experiment,details=details,context=context,
                configuration=_configuration({k:v for k,v in effective.items() if k not in LABELS}),
                snapshot=snapshot,metadata=metadata,identity=identity,inputSummary=summary,run=run,
                snapshotIssue=snapshot_issue,supplementalInputs=supplemental)


def _label(path):
    parts=path.split('.')
    children=dict(capital='初始资金（元）',topN='持仓数量',rebalance='调仓频率',template='策略模板',factorIds='参与因子',customFactors='自定义因子',factorProcessing='因子处理',portfolio='组合约束',costs='交易费用与限制',rules='交易规则',dailyCode='完整日线策略代码',code='评分代码',weights='因子权重',modelExperimentId='模型实验',method='权重方法',grossExposure='总仓位',maxWeight='单股上限',maxIndustryWeight='行业上限',turnoverLimit='换手上限',commissionBuy='买入佣金率',commissionSell='卖出佣金率',minCommission='单笔最低佣金',stampDuty='印花税',transferFee='过户费',slippage='滑点',volumeParticipation='成交量占比上限',symbols='证券名单',source='来源',excludeST='ST筛选',minListingDays='最短上市天数',query='筛选条件',poolId='证券池ID',version='版本')
    return ' / '.join(LABELS.get(part,children.get(part,part)) for part in parts)


def _changes(before,after,prefix=''):
    rows=[]
    for field in sorted(set(before)|set(after)):
        a,b=before.get(field),after.get(field)
        if a==b:continue
        path=prefix+'.'+field if prefix else field
        if isinstance(a,dict) and isinstance(b,dict):rows.extend(_changes(a,b,path))
        else:rows.append(dict(field=path,label=_label(path),before=a,after=b,
                              beforeKnown=field in before and a is not None,afterKnown=field in after and b is not None))
    return rows


def _input_evidence(baseline,current):
    status,basis,message='unknown','insufficient','缺少可对应的固定输入来源版本，不能根据日期、条数或目录判断数据相同。'
    a,b=baseline['snapshot'],current['snapshot']
    if not baseline['snapshotIssue'] and not current['snapshotIssue']:
        same_project=baseline['ref']['projectId']==current['ref']['projectId']
        source_a=a.get('sourceExperimentId') or baseline['ref']['experimentId']
        source_b=b.get('sourceExperimentId') or current['ref']['experimentId']
        if same_project and (a.get('path')==b.get('path') or source_a==source_b):
            status,basis,message='same_recorded_version','snapshot_reference','引用同一记录快照或复现来源版本；未逐字节核对输入内容。'
        else:
            left,right=baseline['identity'],current['identity']
            same_source=left.get('sourceRoot') and left.get('sourceRoot')==right.get('sourceRoot')
            local_left,local_right=left.get('localMembershipIndustryFiles',[]),right.get('localMembershipIndustryFiles',[])
            same_local=not local_left and not local_right or left.get('localRoot')==right.get('localRoot')
            if same_source and same_local and left.get('sourceFiles') and right.get('sourceFiles'):
                same=(left['sourceFiles']==right['sourceFiles'] and local_left==local_right)
                status='same_recorded_version' if same else 'different_recorded_version'
                basis='recorded_source_version'
                message=('记录的来源文件版本一致（更新时间、大小）；并不证明全部输入字节相同。' if same else
                         '记录的来源文件版本有变化；未读取全量数据，不能仅凭文件元数据断言实际值已变化。')
    problems=[record['snapshotIssue'] for record in (baseline,current) if record['snapshotIssue']]
    if problems:
        status,basis='unknown','insufficient'
        message='；'.join(dict.fromkeys(problems))+'；无法确认固定输入对应关系。'
    supplemental=sorted(set(baseline['supplementalInputs']+current['supplementalInputs']))
    if supplemental:
        status,basis='unknown','insufficient'
        message+=' 自定义代码、外部数据或模型依赖未保存可比较的内容版本，未比对附加输入：'+', '.join(supplemental)+'。'
    return dict(status=status,basis=basis,message=message,baseline=baseline['inputSummary'],current=current['inputSummary'])


def describe(baseline,current):
    configuration=_changes(baseline['configuration'],current['configuration'])
    ranges=_changes(baseline['context'],current['context'])
    evidence=_input_evidence(baseline,current)
    reasons=[]
    incompatible=False
    for change in ranges:
        if change['beforeKnown'] and change['afterKnown']:
            incompatible=True
            reasons.append(dict(code='context_changed',field=change['field'],message=change['label']+'不同，不宜直接进行同口径优劣比较。'))
        else:reasons.append(dict(code='context_unknown',field=change['field'],message=change['label']+'在一侧未记录，无法确认口径一致。'))
    required=['kind','startDate','endDate','universe','actualSymbols','engine']
    kinds={baseline['context'].get('kind'),current['context'].get('kind')}
    if 'backtest.run' in kinds:
        required+=['benchmark','accountingBasis','signalTiming','strategyPriceBasis','annualizationDays','annualizedReturnMethod']
    if 'model.train' in kinds:required+=['labelHorizon']
    if 'factor.analyze' in kinds:required+=['periods']
    for field in required:
        if (baseline['context'].get(field) is None or current['context'].get(field) is None) and not any(r['field']==field for r in reasons):
            reasons.append(dict(code='context_unknown',field=field,message=LABELS[field]+'未完整记录，无法确认口径一致。'))
    if evidence['status']=='unknown':reasons.append(dict(code='input_unknown',field=None,message=evidence['message']))
    elif evidence['status']=='different_recorded_version':
        reasons.append(dict(code='input_version_changed',field=None,message=evidence['message']))
    if configuration:reasons.append(dict(code='controlled_configuration_change',field=None,message='策略或实验参数发生变化，作为明确的配置变化对照；不因此自动判定范围不可比。'))
    unknown=any(r['code'] in {'context_unknown','input_unknown','input_version_changed'} for r in reasons)
    status='unknown' if unknown else 'incomparable' if incompatible else 'controlled_change' if configuration else 'comparable'
    return dict(version=1,baselineRef=baseline['ref'],ref=current['ref'],configurationChanges=configuration,
                rangeChanges=ranges,inputEvidence=evidence,comparability=dict(status=status,reasons=reasons))


def compare(store,params,check_cancel=None):
    refs,baseline_ref=references(params)
    records=[load(store,r,check_cancel) for r in refs]
    baseline=next(r for r in records if key(r['ref'])==key(baseline_ref))
    for record in records:
        record['comparison']=describe(baseline,record)
    return records


def warning(comparison):
    return '；'.join(r['message'] for r in comparison['comparability']['reasons'] if r['code']!='controlled_configuration_change')


def _time(value):
    try:
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError,ValueError):return None


def previous(store,params,check_cancel=None):
    current=load(store,ref(params),check_cancel)
    current_ref=current['ref']
    output=dict(currentRef=current_ref,previousRef=None,comparison=None)
    created=_time(current['experiment'].get('createdAt'))
    if created is None:raise ValueError('当前实验创建时间未记录或无效，无法确定前次结果')
    strategy=current['experiment'].get('strategyId') or 'default'
    candidates=[]
    for experiment in store.experiments(current_ref['projectId']):
        date=_time(experiment.get('createdAt'))
        if date is not None and date<created and experiment.get('kind')==current['experiment'].get('kind') and (experiment.get('strategyId') or 'default')==strategy:
            candidates.append((date,experiment['id']))
    jobs=store.project_store(current_ref['projectId']).list('job',current_ref['projectId'] or '')
    for _,experiment_id in sorted(candidates,reverse=True):
        if check_cancel:check_cancel()
        candidate=load(store,dict(projectId=current_ref['projectId'],experimentId=experiment_id),check_cancel)
        experiment,details=candidate['experiment'],candidate['details']
        states=[experiment.get('status'),details.get('status')]
        states += [j.get('status') for j in jobs if (j.get('experimentId') or j.get('id'))==experiment_id]
        result=read_json(candidate['run']/'result.json',{}) or {}
        states.append(result.get('runtimeStatus'))
        if result.get('error') or details.get('incomplete') or any(s not in (None,'completed','succeeded','success') for s in states):continue
        return dict(currentRef=current_ref,previousRef=candidate['ref'],comparison=describe(candidate,current))
    return output


def export_rows(records):
    rows=[]
    def text(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    for record in records:
        comp=record['comparison'];experiment=record['experiment']
        common=dict(projectId=comp['ref']['projectId'],experimentId=comp['ref']['experimentId'],
                    baselineProjectId=comp['baselineRef']['projectId'],baselineExperimentId=comp['baselineRef']['experimentId'])
        def add(section,field,label,value=None,before=None,after=None):
            rows.append(dict(section=section,**common,field=field,label=label,
                             before=text(before),after=text(after),value=text(value)))
        for field in ('name','kind','strategyId','createdAt','parameters'):add('identity',field,field,experiment.get(field))
        # The exact common descriptor makes UI/PDF/CSV/XLSX reasons reconstructable.
        add('identity','comparison','完整比较描述',comp)
        for group,section in [('configurationChanges','configuration'),('rangeChanges','range')]:
            for change in comp[group]:add(section,change['field'],change['label'],
                dict(beforeKnown=change['beforeKnown'],afterKnown=change['afterKnown']),change['before'],change['after'])
        for field,value in record['context'].items():add('range','effective.'+field,LABELS[field],value)
        add('input_evidence','inputEvidence','固定输入证据',comp['inputEvidence'])
        add('comparability','status','可比状态',comp['comparability']['status'])
        for index,reason in enumerate(comp['comparability']['reasons']):add('comparability','reason.'+str(index),reason['message'],reason)
        for field,value in experiment.get('metrics',{}).items():add('metrics',field,field,value)
    return rows
