"""Windows owner for a native Linux RD-Agent stage and ordinary V3 experiments."""
from copy import deepcopy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path, PureWindowsPath

from .storage import identifier, now, read_json, write_json

DISTRO = 'V3-RD-Agent'
PYTHON = '/opt/v3-rdagent/venv312/bin/python'
EMBEDDING = '/opt/v3-rdagent/models/bge-m3'
BOUNDARIES = [part+edge for part in ('train','valid','test') for edge in ('Start','End')]


def validate(params):
    import pandas as pd
    def no_credentials(value):
        if isinstance(value, dict):
            if any(key.lower() in {'apikey','authorization','password','secret'} for key in value):
                raise ValueError('模型服务凭据只能保存在软件设置，不能写入研究任务')
            for item in value.values(): no_credentials(item)
        elif isinstance(value, list):
            for item in value: no_credentials(item)
    no_credentials(params)
    if params.get('action') not in {'factor','model','joint'} or not str(params.get('objective','')).strip():
        raise ValueError('请明确原生研究目标及factor/model/joint类型')
    for key, default in (('rounds',3),('codeRepairRounds',3)):
        value = params.get(key,default)
        if isinstance(value,bool) or not isinstance(value,int) or not 1 <= value <= 3:
            raise ValueError('研究轮数和代码修复次数必须为1至3的整数')
    bounds = {key:params.get('periods',{}).get(key,params.get(key)) for key in BOUNDARIES}
    if not all(bounds.values()): raise ValueError('原生研究需要明确训练、验证、测试六个时间边界')
    dates = [pd.Timestamp(bounds[key]) for key in BOUNDARIES]
    if any(pd.isna(date) for date in dates) or not dates[0]<=dates[1]<dates[2]<=dates[3]<dates[4]<=dates[5]:
        raise ValueError('原生研究训练/验证/测试区间必须严格分离')
    horizon=params.get('labelHorizon',5)
    if isinstance(horizon,bool) or not isinstance(horizon,int) or not 1<=horizon<=252:
        raise ValueError('标签期限必须为1至252整数')
    if params.get('labelMode','next_open') not in {'next_open','close'}:
        raise ValueError('标签口径必须为next_open/close')
    return {key:str(pd.Timestamp(value).date()) for key,value in bounds.items()}


def linux_path(path):
    text = str(path)
    if text.startswith('/'):
        return text
    value=PureWindowsPath(text)
    if not re.fullmatch(r'[A-Za-z]:',value.drive):
        raise ValueError('原生研究需要本地盘符路径，不支持网络共享目录')
    return '/mnt/'+value.drive[0].lower()+'/'+ '/'.join(value.parts[1:])


def command(*args):
    return ['wsl.exe','-d',DISTRO,'--','env',
            'PYTHONPATH='+linux_path(Path(__file__).resolve().parents[2]),PYTHON,*map(str,args)]


def _subprocess(args, **kwargs):
    return subprocess.run(args, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0), **kwargs)


def _check_cancel(directory):
    if (Path(directory)/'rd_cancel.json').exists():
        raise InterruptedError('用户取消原生研究')


def stop(directory, cancel=True):
    """Called before terminating the Windows owner or releasing its queue slot."""
    directory=Path(directory);bridge=directory/'rd_bridge'
    if cancel:
        write_json(directory/'rd_cancel.json',{'requestedAt':now()})
        write_json(bridge/'cancel.json',{'requestedAt':now()})
    for child in read_json(directory/'rd_native_children.json',[]):
        path=Path(child).resolve()
        if not path.is_relative_to(directory.resolve()):raise ValueError('原生计算子进程目录不属于任务')
        stop(path,cancel=cancel)
    if (bridge/'stopped.json').exists():return read_json(bridge/'stopped.json')
    launch=read_json(bridge/'launch.json',{})
    if not launch:
        return {'stopped':True,'reason':'native process not launched'}
    pid=bridge/'pid.json'
    if launch.get('status')=='exited' and not pid.exists():
        return {'stopped':True,'reason':'native exited before process registration'}
    deadline=time.monotonic()+30
    while not pid.is_file() and time.monotonic()<deadline:
        if (bridge/'result.json').is_file():
            return {'stopped':True,'reason':'native exited before process registration'}
        time.sleep(.1)
    if not pid.is_file():
        raise RuntimeError('尚不能确认原生研究进程身份，队列继续保留占用')
    completed=_subprocess(command('-m','v3_backend.research.rd_runners.control',linux_path(pid),launch['runId']),
                          capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
    if completed.returncode:
        raise RuntimeError('原生研究进程组清理失败: '+completed.stderr[-1200:])
    result=json.loads(completed.stdout.strip())
    if not result.get('stopped') or result.get('remainingPids'):
        raise RuntimeError('原生研究进程组尚未退出')
    write_json(bridge/'stopped.json',result)
    return result


def native_call(operation, output, arguments, progress=lambda *_:None):
    """Run native model computation without an LLM or another job queue."""
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    owner=Path(os.environ.get('V3_RESEARCH_OWNER_DIR',str(output)))
    child=owner/'rd_native'/identifier();bridge=child/'rd_bridge';bridge.mkdir(parents=True,exist_ok=True)
    children=read_json(owner/'rd_native_children.json',[])
    write_json(owner/'rd_native_children.json',children+[str(child)])
    run_id=child.name
    config={'runId':run_id,'operation':operation,'output':linux_path(output),**arguments}
    write_json(bridge/'config.json',config)
    write_json(bridge/'launch.json',{'runId':run_id,'status':'launching'})
    process=None
    try:
        _check_cancel(owner)
        with (bridge/'native.log').open('wb') as log:
            process=subprocess.Popen(command('-m','v3_backend.research.rd_runners.model_io',linux_path(bridge/'config.json')),
                stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            while process.poll() is None:
                _check_cancel(owner);time.sleep(.15)
            write_json(bridge/'launch.json',{'runId':run_id,'status':'exited','exitCode':process.returncode})
            result=read_json(bridge/'result.json',{})
            if process.returncode or result.get('status')!='completed':
                raise ValueError(result.get('error') or '原生模型进程失败，详见 '+str(bridge/'native.log'))
            return result
    finally:
        if process is None:
            write_json(bridge/'launch.json',{'runId':run_id,'status':'exited','exitCode':None})
        stop(child,cancel=False)
        if process is not None and process.poll() is None:process.wait(timeout=10)


def native_code(project, params):
    from .engines import generated_path
    return generated_path(project,params['codePath']).read_text(encoding='utf-8')


def execute_retained_factor(project, custom, prices, end, output):
    """Recompute retained factor code using only observations through end."""
    import numpy as np
    import pandas as pd
    from .engines import generated_path
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    observed=prices[prices.date.le(pd.Timestamp(end))].copy()
    required={'rawOpen','rawClose','factor','volume'}
    if observed.empty or not required.issubset(observed):raise ValueError('原生因子重算缺少原始行情或复权因子')
    observed=observed.set_index(['date','symbol']).sort_index();observed.index.names=['datetime','instrument']
    factor=pd.to_numeric(observed.factor,errors='raise')
    if not np.isfinite(factor).all() or factor.le(0).any():raise ValueError('原生因子重算的复权因子无效')
    daily=pd.DataFrame(index=observed.index)
    for field in ('open','high','low','close'):
        daily['$'+field]=observed['raw'+field.title()] if 'raw'+field.title() in observed else observed[field]/factor
    daily['$volume']=observed.volume
    daily['$factor']=factor/factor.groupby(level='instrument').transform('first')
    path=output/'factor_input.parquet';daily.to_parquet(path)
    result=native_call('factor',output,{'action':'factor','rounds':1,'codeRepairRounds':1,
        'periods':{'trainEnd':str(pd.Timestamp(end).date())},'factorId':custom['id'],
        'factorDataPath':linux_path(path),'codePath':linux_path(generated_path(project,custom['codePath']))})
    values=pd.read_parquet(output/'factor.parquet')
    if values.shape[1]!=1:raise ValueError('单个原生因子代码必须返回一列')
    values.columns=[custom['id']]
    return values


def fit_native_asof(project, params, features, prices, date, output):
    import pandas as pd
    from .processing import label_prices
    output=Path(output);output.mkdir(parents=True,exist_ok=True);date=pd.Timestamp(date)
    h=int(params.get('labelHorizon',5));mode=params.get('labelMode','next_open')
    market=label_prices(prices[prices.date.le(date)],mode)
    labels=(market.shift(-h)/market-1).stack().rename('label');labels.index.names=features.index.names
    frame=features[features.index.get_level_values(0)<=date].join(labels)
    frame=frame[frame.index.get_level_values(0)>=date-pd.DateOffset(years=int(params.get('validation',{}).get('trainYears',3)))]
    mature=pd.DatetimeIndex(sorted(frame.dropna(subset=['label']).index.get_level_values(0).unique()))
    if len(mature)<max(20,h+5):raise ValueError('原生模型缺少当时已成熟的训练/验证标签')
    valid_start=mature[max(1,int(len(mature)*.8))]
    calendar=pd.DatetimeIndex(market.index)
    train_end=calendar[calendar.searchsorted(valid_start)-1]
    endpoints=pd.Series(calendar,index=calendar).shift(-(h+(mode=='next_open')))
    frame['labelEndDate']=frame.index.get_level_values(0).map(endpoints)
    frame['partition']=['train' if day<valid_start else 'valid' for day in frame.index.get_level_values(0)]
    dataset=output/'training_input.parquet';frame.reset_index().to_parquet(dataset,index=False)
    allowed={'n_epochs','lr','early_stop','weight_decay','optimizer','GPU','seed','batch_size','step_len','modelType'}
    training={key:value for key,value in params.get('nativeTrainingParameters',{}).items() if key in allowed}
    training.update({key:value for key,value in params.get('trainingParameters',{}).items() if key in allowed})
    training.update(trainStart=str(frame.index.get_level_values(0).min().date()),trainEnd=str(train_end.date()),
        validStart=str(valid_start.date()),validEnd=str(date.date()),labelHorizon=h,labelMode=mode,
        featureColumns=list(features.columns),includeTest=False)
    code=output/'model.py';code.write_text(native_code(project,params),encoding='utf-8')
    parameters={key:value for key,value in params.get('modelParameters',{}).items() if key not in {'num_features','input_dim','num_timesteps'}}
    result=native_call('train',output,{'codePath':linux_path(code),'datasetPath':linux_path(dataset),
        'modelParameters':parameters,'trainingParameters':training})
    descriptor=output/'native_model.json'
    write_json(descriptor,{'codePath':str(code),'checkpointPath':str(output/'model.pt'),
                          'metadataPath':str(output/'model_result.json'),'trainedAsOf':str(date.date())})
    events=pd.read_parquet(output/'training_events.parquet')
    completed=events[events.event.eq('fit_complete')].iloc[-1]
    return str(descriptor),dict(trainedAsOf=str(date.date()),trainingStart=training['trainStart'],trainingEnd=training['trainEnd'],
        validationStart=training['validStart'],validationEnd=training['validEnd'],trainRows=int(completed.trainRows),validRows=int(completed.validRows)),events


def train_native(project, params, output, progress, prices=None):
    """Manual training of retained Torch code on explicit chronological partitions."""
    import pandas as pd
    from . import engines
    from .processing import label_prices
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    prices=engines.prepare(project,output,progress) if prices is None else prices
    bounds={key:params[key] for key in BOUNDARIES if key in params}
    if any(key not in bounds for key in BOUNDARIES):raise ValueError('原生模型重训需要明确训练、验证及独立测试区间')
    include_test=bool(params.get('includeTest',False))
    end=bounds.get('testEnd') if include_test else bounds['validEnd']
    if not end:raise ValueError('独立测试需要明确测试区间')
    observed=prices[prices.date.le(pd.Timestamp(end))]
    x=engines.features(project,{**params,'startDate':bounds['trainStart'],'endDate':end},observed)
    horizon=int(params.get('labelHorizon',5));mode=params.get('labelMode','next_open')
    market=label_prices(observed,mode)
    labels=(market.shift(-horizon)/market-1).stack().rename('label');labels.index.names=x.index.names
    frame=x.join(labels)
    endpoints=pd.Series(market.index,index=market.index).shift(-(horizon+(mode=='next_open')))
    frame['labelEndDate']=frame.index.get_level_values(0).map(endpoints)
    frame['partition']=''
    for part in (['train','valid','test'] if include_test else ['train','valid']):
        days=frame.index.get_level_values(0)
        frame.loc[(days>=pd.Timestamp(bounds[part+'Start']))&(days<=pd.Timestamp(bounds[part+'End'])),'partition']=part
    frame=frame[frame.partition.ne('')]
    dataset=output/'training_input.parquet';frame.reset_index().to_parquet(dataset,index=False)
    code=output/'model.py';code.write_text(native_code(project,params),encoding='utf-8')
    training={**params.get('nativeTrainingParameters',{}),**params.get('trainingParameters',{}),**bounds,
              'featureColumns':list(x.columns),'labelHorizon':horizon,'labelMode':mode,'includeTest':include_test}
    parameters={key:value for key,value in params.get('modelParameters',{}).items() if key not in {'num_features','input_dim','num_timesteps'}}
    progress(.3,'正在用保留的原生Torch代码重新训练')
    native_call('train',output,{'codePath':linux_path(code),'datasetPath':linux_path(dataset),
        'modelParameters':parameters,'trainingParameters':training})
    relative=lambda path:Path(path).relative_to(Path(project['path'])).as_posix()
    evaluation={**params,'dataPath':relative(output/'predictions.parquet'),
                'trainingEventsPath':relative(output/'training_events.parquet'),'includeTest':include_test}
    result=engines.evaluate_generated_predictions(project,evaluation,output,progress,prices)
    descriptor=output/'native_model.json'
    write_json(descriptor,{'codePath':str(code),'checkpointPath':str(output/'model.pt'),
                          'metadataPath':str(output/'model_result.json'),'trainedAsOf':bounds['validEnd']})
    result['artifacts'].append({'name':'model','path':str(descriptor),'type':'json'})
    result['details'].update(trained=True,engine='Qlib GeneralPTNN / retained native Torch code')
    result['summary']='原生Torch模型已重新训练并完成实际预测评价'
    return result


def predict_native(path, features, date, output):
    import pandas as pd
    source=read_json(path);metadata=read_json(source['metadataPath']);date=pd.Timestamp(date)
    if pd.Timestamp(source['trainedAsOf'])>date:raise ValueError('不能使用未来的原生模型状态预测历史日期')
    frame=features[features.index.get_level_values(0)<=date]
    if metadata['modelType']=='TimeSeries':
        dates=sorted(frame.index.get_level_values(0).unique());steps=int(metadata['trainingParameters'].get('step_len',20))
        if dates:frame=frame[frame.index.get_level_values(0)>=dates[max(0,len(dates)-steps)]]
    else:frame=frame[frame.index.get_level_values(0)==date]
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    input_path=output/'features.parquet';frame=frame.copy();frame.attrs={};frame.to_parquet(input_path)
    native_call('predict',output,{'codePath':linux_path(source['codePath']),'checkpointPath':linux_path(source['checkpointPath']),
        'metadataPath':linux_path(source['metadataPath']),'featuresPath':linux_path(input_path),'asOf':str(date.date())})
    return pd.read_parquet(output/'inference.parquet').score


def terminate_owner(process):
    """Stop Windows computation descendants after Linux group exit is confirmed."""
    import psutil
    try: children=psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess: children=[]
    for child in children:
        try: child.terminate()
        except psutil.NoSuchProcess: pass
    _,alive=psutil.wait_procs(children,timeout=3)
    for child in alive:
        try: child.kill()
        except psutil.NoSuchProcess: pass
    _,alive=psutil.wait_procs(alive,timeout=3)
    if alive: raise RuntimeError('研究计算子进程尚未退出，队列继续保留占用')
    if process.poll() is None: process.terminate()
    process.wait(timeout=10)


def _snapshot_inputs(project, params, directory, progress):
    import pandas as pd
    import numpy as np
    from . import data, engines
    from .processing import label_prices
    bounds=validate(params)
    inputs=directory/'rd_inputs';snapshot=inputs/'data';snapshot.mkdir(parents=True,exist_ok=True)
    prices=data.read_table(project)
    prices=prices[prices.date.le(pd.Timestamp(bounds['validEnd']))].copy()
    if prices.empty: raise ValueError('训练/验证区间没有真实行情')
    if not {'rawOpen','rawClose','factor'}.issubset(prices):
        raise ValueError('原生研究的真实账户评价需要原始开盘/收盘价及明确复权因子，请先补齐行情')
    prices.to_parquet(snapshot/'prices.parquet',index=False)
    source=Path(data.project_data(project)['path'])/'data'
    for path in source.rglob('*'):
        relative=path.relative_to(source)
        if not path.is_file() or relative.parts[0] in {'prices','prices.parquet'} or path.suffix not in {'.parquet','.json'}:
            continue
        target=snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    frozen=deepcopy(project)
    frozen.setdefault('settings',{})['dataPath']=str(snapshot)
    frozen['endDate']=bounds['validEnd']
    settings=frozen['settings']
    feature_params={**settings.get('model',{}),'factorIds':params.get('factorIds',settings.get('selectedFactors',[])),
        'customFactors':deepcopy(params.get('customFactors',settings.get('customFactors',[]))),
        'factorProcessing':deepcopy(params.get('factorProcessing',settings.get('factorProcessing',{}))),
        'startDate':bounds['trainStart'],'endDate':bounds['validEnd']}
    if not feature_params['factorIds']: raise ValueError('原生研究需要已有真实因子作为基线特征')
    for custom in feature_params['customFactors']:
        if custom.get('source')=='parquet':
            path=engines.generated_path(project,custom['dataPath'])
            target=inputs/'custom'/path.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
            custom['dataPath']=target.relative_to(Path(project['path'])).as_posix()
    prices=engines.prepare(frozen,inputs,progress)
    x=engines.features(frozen,feature_params,prices)
    horizon=params.get('labelHorizon',5);mode=params.get('labelMode','next_open')
    market=label_prices(prices,mode)
    labels=(market.shift(-horizon)/market-1).stack().rename('label');labels.index.names=x.index.names
    frame=x.join(labels)
    segments=engines.time_segments(frame.dropna(subset=['label']),market.index,
                                    {**bounds,'labelMode':mode,'_validationOnly':True},horizon)
    end_dates=pd.Series(market.index,index=market.index).shift(-(horizon+(mode=='next_open')))
    dates=frame.index.get_level_values(0)
    frame['labelEndDate']=dates.map(end_dates)
    frame['partition']=np.where(dates<=pd.Timestamp(bounds['trainEnd']),'train','valid')
    frame=frame[((dates>=pd.Timestamp(bounds['trainStart']))&(dates<=pd.Timestamp(bounds['trainEnd']))) |
                ((dates>=pd.Timestamp(bounds['validStart']))&(dates<=pd.Timestamp(bounds['validEnd'])))]
    # Keep prediction rows, but remove every label whose endpoint crosses its partition.
    for name in ('train','valid'):
        frame.loc[frame.partition.eq(name)&~frame.labelEndDate.le(pd.Timestamp(bounds[name+'End'])),'label']=np.nan
    dataset=inputs/'dataset.parquet';frame.reset_index().rename(columns={'datetime':'date','instrument':'symbol'}).to_parquet(dataset,index=False)
    native=prices.set_index(['date','symbol']).sort_index();native.index.names=['datetime','instrument']
    factor=pd.to_numeric(native['factor'],errors='raise') if 'factor' in native else pd.Series(1.,index=native.index)
    if not np.isfinite(factor).all() or (factor<=0).any(): raise ValueError('行情复权因子无效')
    daily=pd.DataFrame(index=native.index)
    for field in ('open','high','low','close'):
        daily['$'+field]=native['raw'+field.title()] if 'raw'+field.title() in native else native[field]/factor
    daily['$volume']=native.volume
    daily['$factor']=factor/factor.groupby(level='instrument').transform('first')
    factor_path=inputs/'factor_data.parquet';daily.to_parquet(factor_path)
    backtest={**settings.get('backtest',{}),**params.get('evaluationBacktest',{}),
              'factorIds':feature_params['factorIds'],'customFactors':feature_params['customFactors'],
              'factorProcessing':feature_params['factorProcessing'],
              'startDate':bounds['validStart'],'endDate':bounds['validEnd']}
    backtest.setdefault('template','multi_factor')
    training={**params.get('trainingParameters',{}),'labelHorizon':horizon,'labelMode':mode,'includeTest':False}
    config=dict(runId=directory.name,projectId=project['id'],strategyId=project['strategyId'],objective=params['objective'],
        action=params['action'],rounds=params.get('rounds',3),codeRepairRounds=1,
        periods=bounds,datasetPath=linux_path(dataset),factorDataPath=linux_path(factor_path),featureColumns=list(x.columns),
        trainingParameters=training,evaluationBacktest=backtest,embeddingModelPath=EMBEDDING,
        counts={'train':len(segments['train']),'valid':len(segments['valid']),'predictionRows':len(frame),'priceRows':len(prices)},
        priceBasis='OHLC are unadjusted yuan; volume is raw shares; $factor is supplied cumulative adjustment factor rebased to each instrument first observed row. Prices are not multiplied by $factor. No test prices exported.')
    write_json(inputs/'owner_project.json',project);write_json(inputs/'evaluation_project.json',frozen)
    write_json(inputs/'config.json',config);write_json(inputs/'feature_parameters.json',feature_params)
    return frozen,config,prices


def _resume_inputs(store, project, params, directory, progress):
    from . import data, engines
    previous=store.experiment(project['id'],params['resumeExperimentId'])
    if previous['kind']!='rdagent.run' or previous.get('strategyId')!=project['strategyId']:
        raise ValueError('恢复实验必须属于当前项目和策略的原生研究')
    old=Path(project['path'])/'.research/runs'/previous['id']
    state=read_json(old/'rd_state.json',{})
    if state.get('requiresConfirmation') and params.get('confirmRepair') is not True:
        raise ValueError('请先查看失败原因和修复建议，并明确确认修复后继续')
    if params.get('repairInstructions') is not None and not isinstance(params['repairInstructions'],str):
        raise ValueError('修复说明必须为文字')
    if state.get('status')=='completed': raise ValueError('研究阶段已经完成，请开启新阶段')
    original_inputs=Path(state.get('inputDirectory',str(old/'rd_inputs')))
    if not original_inputs.resolve().is_relative_to(Path(project['path']).resolve()): raise ValueError('恢复输入不属于项目')
    owner=read_json(original_inputs/'owner_project.json')
    if not owner or any(owner.get(key)!=project.get(key) for key in ('id','strategyId','universe','settings')):
        raise ValueError('策略或数据来源已改变，请开启新研究阶段，不继承旧检查点')
    config=read_json(original_inputs/'config.json');bounds=validate(params)
    if config['periods']!=bounds or any(params.get(key,default)!=config['trainingParameters'][key]
        for key,default in [('labelHorizon',5),('labelMode','next_open')]):
        raise ValueError('恢复时不能改变数据区间或标签定义')
    if params.get('factorIds',config['featureColumns'])!=config['featureColumns']:
        raise ValueError('恢复时不能改变冻结特征')
    if not state.get('checkpointPath'): raise ValueError('此研究没有可恢复的原生检查点')
    config={**config,'runId':directory.name,'objective':params['objective'],'action':params['action'],
            'rounds':config['rounds'],'codeRepairRounds':1,'resumePath':state['checkpointPath'],'confirmRepair':params.get('confirmRepair') is True,
            'repairInstructions':params.get('repairInstructions','')}
    frozen=read_json(original_inputs/'evaluation_project.json')
    prices=engines.prepare(frozen,directory,progress)
    return frozen,config,prices,original_inputs


def _copy_generated(project, request, directory):
    """Retain actual files in an ordinary candidate folder, never a transient Linux path."""
    folder=Path(project['path'])/'candidates'/('rd_'+request['id']);folder.mkdir(parents=True,exist_ok=True)
    existing=read_json(folder/'native_request.json',{})
    fields=('factorPath','predictionPath','trainingEventsPath','modelPath','codePath','codePaths')
    if existing:
        for relative,original in existing.get('codeSnapshots',{}).items():
            if (Path(project['path'])/relative).read_text(encoding='utf-8')!=original:
                raise ValueError('原生候选代码已编辑，不能以旧研究请求覆盖或重新关联旧结果')
        return {key:existing[key] for key in fields if existing.get(key)},folder
    copied={}
    def copy_file(source, name):
        target=folder/name
        source=str(source)
        if source.startswith('/mnt/') and len(source)>7 and source[6]=='/':
            local=Path(source[5].upper()+':/'+source[7:]) if os.name=='nt' else Path(source)
            if local.resolve()!=target.resolve(): shutil.copy2(local,target)
        elif source.startswith('/opt/v3-rdagent/runs/'):
            result=_subprocess(['wsl.exe','-d',DISTRO,'--','cp','--',source,linux_path(target)],capture_output=True,text=True,timeout=30)
            if result.returncode: raise ValueError('复制原生产物失败: '+result.stderr[-1000:])
        else:
            raise ValueError('原生产物路径不属于本机研究目录')
        if not target.is_file(): raise ValueError('原生产物复制后不存在')
        return target.relative_to(Path(project['path'])).as_posix()
    for field,name in [('factorPath','factors.parquet'),('predictionPath','predictions.parquet'),
                       ('trainingEventsPath','training_events.parquet'),('modelPath','model.pt'),
                       ('codePath','model.py' if request['action']=='model' else 'factor.py')]:
        if request.get(field): copied[field]=copy_file(request[field],name)
    if request.get('codePaths'):
        copied['codePaths']=[copy_file(source,f'factor_{i}.py') for i,source in enumerate(request['codePaths'])]
    code_paths=list(dict.fromkeys(copied.get('codePaths',[])+([copied['codePath']] if copied.get('codePath') else [])))
    write_json(folder/'native_request.json',{**request,**copied,'codeSnapshots':{
        path:(Path(project['path'])/path).read_text(encoding='utf-8') for path in code_paths}})
    return copied,folder


def _candidate(store, project, request, params):
    from . import candidates
    for value in store.project_store(project['id']).list('candidate',project['id']):
        if value.get('spec',{}).get('parameters',{}).get('rdRequestId')==request['id']:
            if value.get('revision',1)>1:raise ValueError('候选已经修订，请以新版本运行，不能复用旧原生请求')
            return value
    kind=request['action']
    supplied=dict(strategyId=project['strategyId'],kind=kind,name=request.get('name') or '原生研究候选',
        sourceConversationId=params.get('sourceConversationId'),
        description=request.get('description',''),changeSummary=request.get('changeSummary',''),
        spec={'kind':'factor.analyze' if kind=='factor' else 'model.train','parameters':deepcopy(params)})
    value=candidates.save(store,project['id'],supplied)
    # candidates.save normally supplies current draft defaults; this run already froze them.
    value['spec']['parameters']=deepcopy(params)
    store.project_store(project['id']).put('candidate',value,project['id'])
    return value


def _experiment(store, project, owner, request_id, suffix, kind, params, progress, candidate=None, calculate=None):
    from . import worker, candidates
    key=owner['id']+'_'+request_id+'_'+suffix
    try:
        existing=store.experiment(project['id'],key)
        if all(store.artifact_path(project['id'],artifact).is_file() for artifact in existing['artifacts']):
            return existing
    except ValueError:
        pass
    folder=Path(project['path'])/'.research/runs'/key;folder.mkdir(parents=True,exist_ok=True)
    spec={'parameters':deepcopy(params),'projectSnapshot':project}
    if candidate: spec['candidateSnapshot']=candidate
    job=dict(id=key,projectId=project['id'],strategyId=project['strategyId'],kind=kind,
             name=owner['name']+' / '+suffix,spec=spec)
    result=calculate(folder) if calculate else worker.execute(store,job,project,folder,progress)
    result.setdefault('details',{})['rdOwnerJobId']=owner['id']
    result['details']['rdRequestId']=request_id
    experiment=worker.save_result(store,job,project,result,folder)
    store.save_experiment(project['id'],experiment)
    if candidate:
        candidates.link_experiment(store,project['id'],candidate['id'],key,candidate['revision'])
    return experiment


def _metrics(store, project, experiment, prices, config, prefix='', ic=None):
    import numpy as np
    import pandas as pd
    from .processing import label_prices
    def table(name):
        artifact=next((item for item in experiment['artifacts'] if item['name']==prefix+name),None)
        if artifact is None: raise ValueError('真实评价缺少工件: '+prefix+name)
        return pd.read_parquet(store.artifact_path(project['id'],artifact))
    portfolio=table('portfolio').set_index('date').sort_index()
    excess=portfolio['return']-portfolio['cost']-portfolio['bench']
    if len(excess)<2 or not np.isfinite(excess).all(): raise ValueError('真实超额收益覆盖不足')
    curve=(1+excess).cumprod()
    drawdown=curve/curve.cummax().clip(lower=1)-1
    if ic is None:
        signal=table('signals').set_index(['datetime','instrument']).score
        market=label_prices(prices[prices.date.le(pd.Timestamp(config['periods']['validEnd']))],config['trainingParameters']['labelMode'])
        horizon=config['trainingParameters']['labelHorizon']
        labels=(market.shift(-horizon)/market-1).stack().rename('label');labels.index.names=signal.index.names
        sample=signal.rename('score').to_frame().join(labels).dropna()
        date=sample.index.get_level_values(0)
        sample=sample[(date>=pd.Timestamp(config['periods']['validStart']))&(date<=pd.Timestamp(config['periods']['validEnd']))]
        daily=sample.groupby(level=0).apply(lambda frame:frame.score.corr(frame.label))
        ic=float(daily.mean()) if daily.notna().any() else None
    if ic is None or not np.isfinite(ic): raise ValueError('验证期没有可计算的真实IC，不向原生反馈填零')
    gross=portfolio['return']-portfolio['bench']
    if not np.isfinite(gross).all(): raise ValueError('真实不含成本超额收益覆盖不足')
    gross_curve=(1+gross).cumprod()
    return {'IC':float(ic),'1day.excess_return_with_cost.annualized_return':float(excess.mean()*252),
            '1day.excess_return_with_cost.max_drawdown':float(drawdown.min()),
            '1day.excess_return_without_cost.annualized_return':float(gross.mean()*252),
            '1day.excess_return_without_cost.max_drawdown':float((gross_curve/gross_curve.cummax().clip(lower=1)-1).min())}


def evaluate_request(store, owner, project, request, config, prices, directory, progress):
    """No nested queue: calculate, save, and link each real evaluation immediately."""
    import pandas as pd
    from . import engines
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',str(request.get('id',''))): raise ValueError('原生评价ID无效')
    action=request.get('action')
    factor_response={}
    bounds=config['periods'];training=config['trainingParameters']
    base={**config['evaluationBacktest'],'startDate':bounds['validStart'],'endDate':bounds['validEnd']}
    if base.get('template')=='model_score':
        base.update(_predictionPartition='valid',_predictionBounds=bounds)
    experiments=[];candidate=None
    if action=='baseline':
        experiment=_experiment(store,project,owner,request['id'],'baseline','backtest.run',base,progress)
        experiments.append(experiment)
        metrics=_metrics(store,project,experiment,prices,config)
    elif action=='factor':
        copied,folder=_copy_generated(project,request,directory)
        if 'factorPath' not in copied: raise ValueError('原生因子没有实际Parquet产物')
        path=Path(project['path'])/copied['factorPath']
        values=pd.read_parquet(path)
        if not isinstance(values.index,pd.MultiIndex) or values.shape[1]<1: raise ValueError('生成因子工件格式错误')
        original=list(values.columns)
        ids=['rd_'+request['id'][:16]+'_'+str(i) for i in range(len(original))]
        if list(values.columns)!=ids:
            values.columns=ids;values.to_parquet(path)
        custom=[dict(id=name,name=str(original[i]),source='parquet',dataPath=copied['factorPath'],
                     codePath=(copied.get('codePaths') or [copied.get('codePath')])[min(i,len(copied.get('codePaths') or [0])-1)])
                for i,name in enumerate(ids)]
        params={**project.get('settings',{}).get('factorAnalysis',{}),'factorIds':ids,'customFactors':custom,
                'factorProcessing':base.get('factorProcessing',{}),'startDate':bounds['validStart'],'endDate':bounds['validEnd'],
                'periods':[training['labelHorizon']],'labelMode':training['labelMode'],'rdRequestId':request['id']}
        params['sourceConversationId']=owner.get('spec',{}).get('parameters',{}).get('sourceConversationId')
        candidate=_candidate(store,project,request,params)
        model_features=engines.features(project,{**params,'startDate':bounds['trainStart'],'endDate':bounds['validEnd']},prices)
        model_features=model_features.copy();model_features.attrs={}
        model_feature_path=folder/'model_features.parquet';model_features.to_parquet(model_feature_path)
        factor_response={'factorPath':linux_path(model_feature_path),'customFactors':custom}
        analysis=_experiment(store,project,owner,request['id'],'factor','factor.analyze',params,progress,candidate)
        experiments.append(analysis)
        combined=list(dict.fromkeys(base.get('factorIds',[])+ids))
        backtest={**base,'factorIds':combined,'customFactors':base.get('customFactors',[])+custom}
        if backtest.get('template')=='single_factor' and len(combined)>1: backtest['template']='multi_factor'
        if backtest.get('template')=='model_score':
            reference=store.experiment(project['id'],backtest['modelExperimentId'])
            fit={**reference['parameters'],**bounds,'factorIds':combined,'customFactors':backtest['customFactors'],
                 'factorProcessing':base.get('factorProcessing',{}),**training,'_validationOnly':True,'validation':{'mode':'single'}}
            model=_experiment(store,project,owner,request['id'],'factor_model','model.train',fit,progress,candidate)
            experiments.append(model);backtest['modelExperimentId']=model['id']
        tested=_experiment(store,project,owner,request['id'],'factor_backtest','backtest.run',backtest,progress,candidate)
        experiments.append(tested);metrics=_metrics(store,project,tested,prices,config)
    elif action=='model':
        copied,folder=_copy_generated(project,request,directory)
        if 'predictionPath' not in copied: raise ValueError('原生模型没有实际预测产物')
        params={**bounds,**training,'model':'native_generated_predictions','source':'rdagent',
                'factorIds':request.get('trainingParameters',{}).get('featureColumns',config['featureColumns']),
                'customFactors':base.get('customFactors',[])+request.get('customFactors',[]),
                'factorProcessing':base.get('factorProcessing',{}),
                'dataPath':copied['predictionPath'],'codePath':copied.get('codePath'),
                'trainingEventsPath':copied.get('trainingEventsPath'),'modelParameters':request.get('modelParameters',{}),
                'nativeTrainingParameters':request.get('trainingParameters',{}),'evaluationBacktest':base,
                'includeTest':False,'rdRequestId':request['id']}
        source=directory/'rd_inputs/native_models'/request['id'];source.mkdir(parents=True,exist_ok=True)
        params['nativeSourcePath']=(source/'source.json').relative_to(Path(project['path'])).as_posix()
        params['sourceConversationId']=owner.get('spec',{}).get('parameters',{}).get('sourceConversationId')
        candidate=_candidate(store,project,request,params)
        if (source/'source.json').exists():
            if read_json(source/'source.json')['parameters']!=params:
                raise ValueError('原生训练来源参数已存在且不同，不能覆盖')
        else:
            shutil.copy2(Path(project['path'])/copied['predictionPath'],source/'predictions.parquet')
            if copied.get('codePath'): shutil.copy2(Path(project['path'])/copied['codePath'],source/'model.py')
            write_json(source/'source.json',{'parameters':params,'project':project,
            'candidateId':candidate['id'],'candidateRevision':candidate['revision'],
            'predictionPath':(source/'predictions.parquet').relative_to(Path(project['path'])).as_posix(),
            'codePath':(source/'model.py').relative_to(Path(project['path'])).as_posix(),
                'trainingEventsPath':copied.get('trainingEventsPath'),'mode':'reevaluate_retained_native_predictions'})
        tested=_experiment(store,project,owner,request['id'],'model','model.train',params,progress,candidate,
            calculate=lambda output:engines.evaluate_generated_predictions(project,params,output,progress,prices=prices))
        experiments.append(tested)
        metrics=_metrics(store,project,tested,prices,config,prefix='valid_backtest_',ic=tested['metrics'].get('valid:ic'))
    else:
        raise ValueError('未知原生评价动作')
    return {**factor_response,'experimentIds':[item['id'] for item in experiments], 'candidateId':candidate['id'] if candidate else None,
            'metrics':metrics,'summary':'真实验证期评价已保存；测试集未参与研究反馈。'}


def reevaluate_native(store, job, project, directory, progress):
    import pandas as pd
    from . import engines
    params=job['spec']['parameters']
    source_path=engines.generated_path(project,params['nativeSourcePath'])
    source=read_json(source_path)
    if source['parameters']!=params:
        raise ValueError('原生模型配置/日期已经改变，不能复用旧预测；需要真实重新训练')
    candidate=job['spec'].get('candidateSnapshot')
    if candidate and (candidate['id']!=source['candidateId'] or candidate['revision']!=source['candidateRevision']):
        raise ValueError('候选版本已改变，不能将旧原生预测视作新版本结果')
    code=engines.generated_path(project,params['codePath'])
    original_code=engines.generated_path(project,source['codePath'])
    if code.read_bytes()!=original_code.read_bytes():
        raise ValueError('原生模型代码已修改，必须重新训练，不能复用旧预测')
    retained=pd.read_parquet(engines.generated_path(project,source['predictionPath']))
    if not pd.read_parquet(engines.generated_path(project,params['dataPath'])).equals(retained):
        raise ValueError('原生预测工件已修改，拒绝作为原模型结果重新评价')
    frozen=source['project']
    if frozen['id']!=project['id'] or frozen.get('strategyId')!=project.get('strategyId'):
        raise ValueError('原生预测不属于当前项目/策略')
    result=engines.evaluate_generated_predictions(frozen,params,directory,progress)
    result['summary']='重新评价已有原生预测；未重新训练模型'
    result['details'].update(mode='reevaluate_retained_native_predictions',trained=False,
        sourceCandidateId=source['candidateId'],sourceCandidateRevision=source['candidateRevision'],
        frozenDataPath=frozen['settings']['dataPath'])
    return result


def run(store, job, project, directory, progress):
    import pandas as pd
    from . import engines
    directory=Path(directory);bridge=directory/'rd_bridge';bridge.mkdir(parents=True,exist_ok=True)
    params=job['spec']['parameters'];process=None;log=None;config={};input_directory=directory/'rd_inputs'
    native_result={};error=None;state='failed';events=[];seen=set()
    ai=store.settings()['ai']
    def safe(value):
        text=str(value)
        return text.replace(ai['apiKey'],'[redacted]') if ai.get('apiKey') else text
    def report(value,message):
        _check_cancel(directory);progress(value,safe(message))
    try:
        validate(params)
        if not ai.get('baseUrl') or not ai.get('model'):
            raise ValueError('请在软件设置中配置模型服务地址和模型名称')
        if not ai.get('apiKey') and not re.match(r'^https?://(localhost|127\.0\.0\.1|\[::1\])(?=[:/]|$)',ai['baseUrl']):
            raise ValueError('在线模型服务尚未配置API密钥')
        report(.02,'准备原生研究的冻结训练/验证数据')
        if params.get('resumeExperimentId'):
            frozen,config,prices,input_directory=_resume_inputs(store,project,params,directory,report)
        else:
            frozen,config,prices=_snapshot_inputs(project,params,directory,report)
        write_json(bridge/'config.json',config)
        _check_cancel(directory)
        # This marker precedes the final cancel check, closing the launch/cancel race.
        write_json(bridge/'launch.json',{'runId':job['id'],'status':'launching','createdAt':now()})
        _check_cancel(directory)
        log=(bridge/'native.log').open('wb')
        process=subprocess.Popen(command('-m','v3_backend.research.rd_runners.run',linux_path(bridge)),
            stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        write_json(bridge/'launch.json',{'runId':job['id'],'windowsPid':process.pid,'status':'launched','createdAt':now()})
        try:
            process.stdin.write((json.dumps({key:ai.get(key) for key in ('baseUrl','model','apiKey','temperature')})+'\n').encode('utf-8'))
            process.stdin.close()
        except BrokenPipeError:
            pass
        report(.3,'原生RD-Agent已启动，等待真实研究步骤')
        while True:
            _check_cancel(directory)
            path=bridge/'events.jsonl'
            if path.exists():
                for line in path.read_text(encoding='utf-8').splitlines():
                    try: event=json.loads(line)
                    except json.JSONDecodeError: continue
                    if event.get('id') in seen: continue
                    seen.add(event.get('id'));events.append(event)
                    labels={'native_step_started':'原生研究步骤','model_request_started':'正在调用模型服务',
                            'embedding_started':'正在计算真实文本向量','code_attempt_completed':'原生代码尝试完成',
                            'evaluation_waiting':'等待V3真实验证','checkpoint_saved':'原生检查点已保存'}
                    if event.get('event') in labels:
                        progress(.35,labels[event['event']]+('：'+str(event['step']) if event.get('step') else ''))
            for path in sorted((bridge/'evaluations').glob('*/request.json')):
                response_path=path.with_name('response.json')
                if response_path.exists(): continue
                request=read_json(path)
                try:
                    response=evaluate_request(store,job,frozen,request,config,prices,directory,report)
                except InterruptedError:
                    raise
                except Exception as exc:
                    prefix=job['id']+'_'+str(request.get('id'))+'_'
                    linked=[item['id'] for item in store.experiments(project['id']) if item['id'].startswith(prefix)]
                    response={'error':safe(exc),'experimentIds':linked,'metrics':{},'summary':'评价未完成，已保存的实验仍可查看。'}
                write_json(response_path,response)
            if process.poll() is not None: break
            time.sleep(.2)
        native_result=read_json(bridge/'result.json',{})
        state=native_result.get('status','failed')
        if process.returncode!=0 or state!='completed':
            error=native_result.get('error') or ('原生进程退出 '+str(process.returncode)+'，请查看保留日志')
            if state=='completed': state='failed'
    except InterruptedError as exc:
        state='cancelled';error=safe(exc)
    except Exception as exc:
        state='failed';error=safe(exc)
    finally:
        if process is None and (bridge/'launch.json').exists():
            write_json(bridge/'result.json',{'status':state,'error':error,'launched':False})
        if process is not None:
            try:
                if process.poll() is not None:
                    write_json(bridge/'launch.json',{'runId':job['id'],'status':'exited','exitCode':process.returncode})
                stop(directory)
                if process.poll() is None: process.wait(timeout=10)
            except Exception as exc:
                state='failed';error='研究进程清理尚未确认: '+safe(exc)
                # Jobs._watch retries this and does not release the shared writer slot.
            if process.poll() is not None and log is not None: log.close()
    checkpoint=read_json(bridge/'checkpoint.json',{}).get('checkpointPath') or native_result.get('checkpointPath')
    rounds=[]
    for path in sorted((bridge/'evaluations').glob('*/request.json')):
        request=read_json(path);response=read_json(path.with_name('response.json'),{})
        rounds.append(dict(id=request.get('id'),action=request.get('action'),name=request.get('name'),
            status='failed' if response.get('error') else 'completed' if response else 'waiting',
            candidateId=response.get('candidateId'),experimentIds=json.dumps(response.get('experimentIds',[])),
            error=response.get('error'),metrics=json.dumps(response.get('metrics',{}))))
    state_value={'status':state,'checkpointPath':checkpoint,'inputDirectory':str(input_directory),
                 'requiresConfirmation':bool(native_result.get('requiresConfirmation')),'repair':native_result.get('repair'),
                 'bridgeDirectory':str(bridge),'error':error,'feedbackPartition':'valid',
                 'engine':'RD-Agent 0.8 QuantRDLoop/CoSTEER; native Qlib GeneralPTNN for generated models'}
    write_json(directory/'rd_state.json',state_value)
    artifacts=[engines.save_table(directory,'rounds',pd.DataFrame(rounds)),
               engines.save_table(directory,'events',pd.DataFrame([{'id':event.get('id'),'time':event.get('time'),
                    'event':event.get('event'),'payload':json.dumps(event,ensure_ascii=False)} for event in events]))]
    return dict(metrics={'completedEvaluations':sum(row['status']=='completed' for row in rounds),
                         'candidateCount':sum(bool(row['candidateId']) for row in rounds)},artifacts=artifacts,
                summary='原生研究阶段完成，候选等待讨论。' if state=='completed' else '原生研究未完成：'+str(error),
                details={**state_value,'rounds':rounds,'priceBasis':config.get('priceBasis'),
                         'jointScope':'accepted factors feed subsequent models; factor evaluations use the frozen V3 strategy',
                         'independentTestIncluded':False})


def preview(store, params):
    from .workbench import strategy_project
    project=strategy_project(store,params['projectId'],params.get('strategyId'))
    ai=store.settings()['ai']
    return {'projectId':project['id'],'strategyId':project['strategyId'],'engine':'RD-Agent 0.8 QuantRDLoop + CoSTEER',
        'actions':['factor','model','joint'],'maxRounds':3,'maxCodeRepairRounds':1,
        'factorIds':project.get('settings',{}).get('selectedFactors',[]),
        'modelServiceConfigured':bool(ai.get('baseUrl') and ai.get('model') and (ai.get('apiKey') or re.match(r'^https?://(localhost|127\.0\.0\.1)',ai.get('baseUrl','')))),
        'serviceConnection':'not_checked','embeddingModelPath':EMBEDDING,'runtime':'not_checked',
        'message':'使用真实训练/验证数据；运行时检查Linux环境、模型服务与本地向量模型。'}


def status(store, params):
    project=store.project(params['projectId'])
    key=params.get('jobId') or params.get('experimentId')
    if not key:
        return {'runs':[item for item in store.experiments(project['id']) if item['kind']=='rdagent.run' and
                        (not params.get('strategyId') or item.get('strategyId')==params['strategyId'])]}
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,150}',str(key)): raise ValueError('研究ID无效')
    folder=Path(project['path'])/'.research/runs'/key
    state=read_json(folder/'rd_state.json',{})
    checkpoint=read_json(folder/'rd_bridge/checkpoint.json',{})
    events=[]
    event_path=folder/'rd_bridge/events.jsonl'
    if event_path.exists():
        for line in event_path.read_text(encoding='utf-8').splitlines():
            try: item=json.loads(line)
            except json.JSONDecodeError: continue  # The writer may be appending its last line.
            if isinstance(item,dict): events.append(item)
    current={}
    usage={}
    completed_calls=0
    for item in events:
        for field in ('round','step','action'):
            if item.get(field) is not None: current[field]=item[field]
        if item.get('event')=='model_request_completed':
            completed_calls+=1
            reported=item.get('usage')
            if isinstance(reported,dict):
                for field in ('prompt_tokens','completion_tokens','total_tokens'):
                    value=reported.get(field)
                    if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0:
                        usage[field]=usage.get(field,0)+value
    return {**state,**checkpoint,'projectId':project['id'],'runId':key,
            'events':[{field:item[field] for field in ('id','time','event','round','step','action') if field in item}
                      for item in events[-20:]],
            'currentRound':current.get('round'),'currentStep':current.get('step'),
            'currentAction':current.get('action'),'completedModelCalls':completed_calls,
            'usage':usage or None,
            'nativeResult':read_json(folder/'rd_bridge/result.json'),
            'progress':read_json(folder/'progress.json')}
