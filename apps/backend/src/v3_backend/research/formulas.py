"""Formula records and a thin bridge to the original HQChart Node evaluator."""
from pathlib import Path
from copy import deepcopy
import json,os,re,shutil,subprocess
from .storage import identifier,now
from . import data,quotes


def library(store,method,params):
    pid=params.get('projectId');target=store.project_store(pid) if pid else store
    kind='chart-template' if '.templates.' in method else 'formula'
    action=method.rsplit('.',1)[-1]
    if action=='list':return target.list(kind,pid or '')
    if action=='get':return target.get(kind,params['id'])
    if action=='delete':target.delete(kind,params['id']);return {'deleted':True}
    if action=='copy':
        source_pid=params.get('fromProjectId');source=store.project_store(source_pid) if source_pid else store
        record=deepcopy(source.get(kind,params['id']));record.update(id=identifier(),sourceId=record['id'],sourceProjectId=source_pid,sourceRevision=record.get('revision',1),createdAt=now())
    elif action=='save':record=deepcopy(params['record'])
    else:raise ValueError('未知公式库操作')
    if not str(record.get('name','')).strip():raise ValueError('请填写名称')
    if kind=='formula' and not str(record.get('script','')).strip():raise ValueError('公式内容不能为空')
    if kind=='chart-template':
        def reject_bound(value):
            if isinstance(value,dict):
                if {'symbol','instrument','drawings','annotations'} & value.keys():raise ValueError('模板只保存通用图表设置和公式，不保存个股或批注')
                for child in value.values():reject_bound(child)
            elif isinstance(value,list):
                for child in value:reject_bound(child)
        reject_bound(record)
    old=None
    if record.get('id'):
        try:old=target.get(kind,record['id'])
        except ValueError:pass
    if old and params.get('expectedRevision') is not None and old.get('revision',1)!=params['expectedRevision']:raise ValueError('记录已修改，请刷新后保存')
    record.update(id=record.get('id') or identifier(),projectId=pid,revision=(old.get('revision',1)+1 if old else 1),updatedAt=now())
    record.setdefault('createdAt',now())
    return target.put(kind,record,pid or '')


def native(request):
    executable=os.environ.get('V3_FORMULA_NODE') or shutil.which('node')
    script=os.environ.get('V3_FORMULA_RUNNER') or str(Path(__file__).resolve().parents[5]/'scripts/hq-formula.cjs')
    if not executable or not Path(script).is_file():raise ValueError('HQChart原生公式运行环境不可用')
    environment={**os.environ,'ELECTRON_RUN_AS_NODE':'1'}
    try:
        done=subprocess.run([executable,script],input=json.dumps(request,ensure_ascii=False,allow_nan=False),capture_output=True,
            encoding='utf-8',errors='replace',timeout=45,env=environment,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired:raise ValueError('公式计算超时，已有公式与产物保留') from None
    try:result=json.loads(done.stdout)
    except (ValueError,TypeError):raise ValueError('HQChart未返回可用结果') from None
    if done.returncode or not result.get('ok'):raise ValueError(result.get('error') or '公式不能用于所选用途：'+json.dumps(result.get('assessment',{}),ensure_ascii=False))
    return result


def evaluate(store,params):
    import pandas as pd
    from .selection import completed_prices
    pid=params.get('projectId');purpose=params.get('purpose','chart')
    if purpose not in {'chart','research'}:raise ValueError('公式用途无效')
    if purpose=='research' and not pid:raise ValueError('研究数值需要所属项目')
    project=store.project(pid)
    if params.get('strategyId'):
        from .workbench import strategy_project
        project=strategy_project(store,pid,params['strategyId'])
    formula=deepcopy(params.get('formula'))
    if not formula:formula=(store.project_store(pid) if pid else store).get('formula',params['formulaId'])
    if params.get('instrument'):
        item=quotes.instrument(params['instrument'])
        if purpose=='research' and item['kind']!='stock':raise ValueError('分钟或非股票行情不能作为日线股票研究因子')
        frame=quotes.read(store.project(None),item).copy();frame['symbol']=item['symbol']
    else:frame=data.read_table(project)
    if frame.empty:raise ValueError('没有可计算的实际日线')
    frame=frame.copy();frame['date']=pd.to_datetime(frame.date).dt.normalize()
    if purpose=='research':frame=completed_prices(frame)
    if params.get('period') not in (None,'daily'):raise ValueError('此研究公式桥仅接受日线；分钟图公式由看盘容器处理')
    symbols=None if params.get('instrument') else params.get('symbols') or project['universe'].get('symbols')
    if symbols:frame=frame[frame.symbol.isin([data.symbol(s) for s in symbols])]
    if frame.empty:raise ValueError('没有可计算的实际日线')
    end=params.get('endDate') or (project.get('endDate') if purpose=='research' else None)
    start=params.get('startDate') or (project.get('startDate') if purpose=='research' else None)
    if purpose=='research' and (not start or not end):raise ValueError('研究公式需要明确开始和结束日期')
    if end:frame=frame[pd.to_datetime(frame.date).le(end)]
    basis=params.get('priceBasis',formula.get('priceBasis','raw'))
    formula['priceBasis']=basis
    result=calculate(frame,formula,purpose)
    if params.get('saveFactor'):
        if purpose!='research':raise ValueError('只有通过历史适用性检查的研究数值可保存为因子')
        factor_id=params.get('factorId','')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',factor_id):raise ValueError('请填写字母开头的因子ID')
        from .engines import factor_catalog
        if factor_id in {item['id'] for item in factor_catalog()}:raise ValueError('自定义因子 ID 与内置因子冲突')
        rows=[];output=params.get('output') or formula.get('output')
        for item in result['series']:
            outputs=item['outputs'];chosen=next((v for v in outputs if v['name']==output),None) if output else outputs[0] if len(outputs)==1 else None
            if chosen is None:raise ValueError('请明确选择一个数值输出')
            rows.extend({'date':date,'symbol':item['symbol'],factor_id:value} for date,value in zip(item['dates'],chosen['values']))
        if not rows:raise ValueError('所选公式没有数值输出')
        values=pd.DataFrame(rows);values['date']=pd.to_datetime(values.date).dt.normalize()
        values=values[values.date.between(start,end)]
        if values.empty or values[factor_id].notna().sum()==0:raise ValueError('所选区间没有有效公式数值')
        folder=Path(project['path'])/'.research/formulas'/identifier();folder.mkdir(parents=True,exist_ok=True)
        path=folder/'values.parquet';values.to_parquet(path,index=False)
        factor={'id':factor_id,'name':formula.get('name',factor_id),'source':'parquet','dataPath':path.relative_to(Path(project['path'])).as_posix(),
                'formula':{**formula,'output':output or chosen['name']},'engine':result['engine'],'priceBasis':basis}
        settings=deepcopy(project.get('settings',{}))
        factors=[f for f in settings.get('customFactors',[]) if f['id']!=factor_id]+[factor]
        selected=list(dict.fromkeys(settings.get('selectedFactors',[])+[factor_id]))
        if params.get('strategyId'):
            from .workbench import _save_strategy
            _save_strategy(store,{'projectId':pid,'strategy':{'id':params['strategyId']},'settingsPatch':{'customFactors':factors,'selectedFactors':selected}})
        else:
            settings.update(customFactors=factors,selectedFactors=selected);store.save_project({**project,'settings':settings})
        result['factor']=factor
    return result


def calculate(frame,formula,purpose='research'):
    basis=formula.get('priceBasis','raw')
    if basis not in {'raw','adjusted'}:raise ValueError('公式价格口径必须为raw或adjusted')
    frame=frame.copy()
    if basis=='raw':
        for field in ('open','high','low','close'):
            column='raw'+field.title()
            if column not in frame or frame[column].isna().any():raise ValueError('缺少原始OHLC，无法按不复权价格计算公式')
            frame[field]=frame[column]
    series=[]
    for symbol,part in frame.sort_values('date').groupby('symbol'):
        columns=[key for key in ('date','open','high','low','close','volume','amount') if key in part]
        series.append({'symbol':symbol,'bars':data.records(part[columns])})
    result=native({'formula':formula,'series':series,'purpose':purpose})
    result['priceBasis']=basis
    return result


def refresh_factors(project,params):
    """Recompute formula-backed values on changed daily input, retaining prior artifacts."""
    import pandas as pd
    from .preparation import signature
    from .selection import completed_prices
    from .storage import read_json,write_json
    customs=params.get('customFactors',[])
    selected=set(params.get('factorIds',project.get('settings',{}).get('selectedFactors',[])))
    for index,custom in enumerate(customs):
        if not custom.get('formula') or custom['id'] not in selected:continue
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',custom['id']):raise ValueError('公式因子ID格式无效')
        formula=deepcopy(custom['formula']);formula.setdefault('priceBasis',custom.get('priceBasis','raw'))
        frame=completed_prices(data.read_table(project))
        if frame.empty:raise ValueError('公式因子缺少已完成的实际日线')
        key=signature(project,{'formula':formula,'completedDate':str(frame.date.max())[:10]})
        cache=Path(project['path'])/'.research/formulas/cache'/custom['id']
        cached=read_json(cache.with_suffix('.json'),{})
        if cached.get('input')==key and (Path(project['path'])/cached.get('dataPath','missing')).is_file():
            customs[index]={**custom,'dataPath':cached['dataPath']};continue
        result=calculate(frame,formula)
        rows=[]
        for item in result['series']:
            outputs=item['outputs'];output=next((o for o in outputs if o['name']==formula.get('output')),None)
            if output is None and len(outputs)==1:output=outputs[0]
            if output is None:raise ValueError('公式因子需要明确一个数值输出')
            rows.extend({'date':date,'symbol':item['symbol'],custom['id']:value} for date,value in zip(item['dates'],output['values']))
        if not rows:raise ValueError('公式因子没有数值输出')
        folder=Path(project['path'])/'.research/formulas'/identifier();folder.mkdir(parents=True,exist_ok=True)
        path=folder/'values.parquet';pd.DataFrame(rows).to_parquet(path,index=False)
        relative=path.relative_to(Path(project['path'])).as_posix()
        customs[index]={**custom,'dataPath':relative}
        write_json(cache.with_suffix('.json'),{'input':key,'dataPath':relative})
    return params


def dispatch(store,method,params):
    return evaluate(store,params) if method=='formula.evaluate' else library(store,method,params)
