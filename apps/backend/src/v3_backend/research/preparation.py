"""Prepare only inputs of an explicitly submitted research run, in its worker."""
from copy import deepcopy
from pathlib import Path
from . import data, engines, quotes, corporate_actions
from .app_settings import source_settings
from .storage import read_json, write_json, identifier, now

KINDS={'factor.analyze','model.train','backtest.run','optimize.run','simulation.advance'}

def require_data_update(params, resource):
    if params.get('updateData',True) is False:
        raise ValueError('本次未启用数据更新，缺失'+resource+'需先导入或单独更新后再运行')


def scope(project, params, kind):
    import pandas as pd
    start=params.get('startDate') or project.get('startDate')
    end=params.get('endDate') or project.get('endDate')
    if kind=='model.train':
        start=params.get('trainStart');end=params.get('testEnd')
        for key in ('trainStart','trainEnd','validStart','validEnd','testStart','testEnd'):
            if not params.get(key):raise ValueError('模型运行前请明确选择日期：'+key)
        dates=[pd.Timestamp(params[key]) for key in ('trainStart','trainEnd','validStart','validEnd','testStart','testEnd')]
        if not (dates[0]<=dates[1]<dates[2]<=dates[3]<dates[4]<=dates[5]):
            raise ValueError('训练、验证、测试日期必须按先后排列且不重叠')
    if not start or not end:raise ValueError('运行前请明确选择研究开始和结束日期')
    if pd.Timestamp(start)>pd.Timestamp(end):raise ValueError('研究开始日期不能晚于结束日期')
    return str(pd.Timestamp(start).date()),str(pd.Timestamp(end).date())


def lookback(params):
    from qlib.data.data import LocalExpressionProvider
    from qlib.data.ops import register_all_ops
    register_all_ops({});provider=LocalExpressionProvider()
    catalog={item['id']:item['expression'] for item in engines.factor_catalog()}
    catalog.update({item['id']:item.get('expression','') for item in params.get('customFactors',[])})
    maximum=0
    for key in params.get('factorIds',[]):
        expression=catalog.get(key,'')
        if not expression or expression.startswith(('alternative:','P(')):continue
        left,right=provider.get_expression_instance(engines.validate_expression(expression)).get_extended_window_size()
        if right>0:raise ValueError('因子含未来行情引用，不能作为历史研究输入：'+key)
        maximum=max(maximum,int(left))
    return maximum


def signature(project, params):
    root=Path(data.project_data(project)['path'])/'data'
    params=deepcopy(params)
    if params.get('trainStart') and params.get('testEnd'):
        params.pop('startDate',None);params.pop('endDate',None)
    # File identity belongs to the model input cache, not a release/authority ledger.
    return {'parameters':deepcopy(params),'universe':deepcopy(project['universe']),
            'files':[[str(p),p.stat().st_mtime_ns,p.stat().st_size] for p in sorted(root.rglob('*.parquet'))]}


def trading_dates(root,start,end,source='baostock',update_data=True):
    import pandas as pd
    cached=read_json(root/'trading-calendar.json',{})
    if cached.get('start','9999')<=start and cached.get('end','')>=end:
        return [d for d in cached['dates'] if start<=d<=end]
    observed=set()
    for path in (root/'benchmarks').glob('*.parquet'):
        observed.update(str(pd.Timestamp(d).date()) for d in pd.read_parquet(path,columns=['date']).date)
    if observed and min(observed)<=start and max(observed)>=end:
        return sorted(d for d in observed if start<=d<=end)
    if source!='baostock':raise ValueError('缺少本地交易日历；当前日线来源 '+source+' 不自动调用BaoStock补取')
    if not update_data:raise ValueError('本次未启用数据更新，缺少交易日历需先导入或单独更新后再运行')
    frame=quotes._baostock(lambda bs:data._bs_query(bs,bs.query_trade_dates,start_date=start,end_date=end))
    dates=sorted(str(d) for d in frame.loc[frame.is_trading_day.astype(str).eq('1'),'calendar_date'])
    write_json(root/'trading-calendar.json',{'start':start,'end':end,'dates':dates})
    return dates



def price_requirements(project, prices, dates, start, warmup):
    """Use explicit lifetime/member evidence; never infer listing from first price."""
    import pandas as pd
    from .history import membership_frame
    membership=membership_frame(project)
    codes=set(map(data.symbol,project['universe'].get('symbols',[])))
    if not codes and membership is not None:codes=set(membership.symbol)
    if not codes and len(prices):codes=set(prices.symbol)
    status_path=Path(data.project_data(project)['path'])/'data/trading_status.parquet' if project.get('path') else None
    states=pd.read_parquet(status_path) if status_path and status_path.exists() else pd.DataFrame()
    rows=[]
    for code in sorted(codes):
        part=prices[prices.symbol.eq(code)] if len(prices) else prices
        bounds={}
        for field in ('listingDate','delistingDate'):
            values=pd.to_datetime(part[field],errors='coerce').dropna().unique() if field in part else []
            if len(values)>1:raise ValueError('证券日期记录冲突：'+code+' '+field)
            bounds[field]=pd.Timestamp(values[0]) if len(values) else None
        expected=set(dates)
        if bounds['listingDate'] is not None:
            eligible=bounds['listingDate']+pd.Timedelta(days=max(0,int(project['universe'].get('minListingDays',0))))
            expected={d for d in expected if pd.Timestamp(d)>=eligible}
        if bounds['delistingDate'] is not None:expected={d for d in expected if pd.Timestamp(d)<bounds['delistingDate']}
        if membership is not None:
            intervals=membership[membership.symbol.eq(code)]
            expected={d for d in expected if any(pd.Timestamp(r.startDate)<=pd.Timestamp(d) and
                (pd.isna(r.endDate) or pd.Timestamp(d)<=pd.Timestamp(r.endDate)) for r in intervals.itertuples())}
        observed=set(pd.to_datetime(part.date).dt.strftime('%Y-%m-%d')) if len(part) else set()
        halted=set()
        if len(states):
            known=states[states.symbol.eq(code)&states.source.eq('BaoStock/query_history_k_data_plus')&pd.to_numeric(states.tradestatus,errors='coerce').eq(0)]
            halted=set(pd.to_datetime(known.date).dt.strftime('%Y-%m-%d')) & expected
        first=min(expected) if expected else None
        available=sum(d<first for d in observed) if first else 0
        rows.append(dict(symbol=code,expectedSessions=len(expected),missingDates=sorted(expected-observed-halted),confirmedSuspensionDates=sorted(halted),
            warmupBefore=first,availableSessions=available,requiredSessions=warmup if first else 0,
            listingDate=str(bounds['listingDate'].date()) if bounds['listingDate'] is not None else None,
            delistingDate=str(bounds['delistingDate'].date()) if bounds['delistingDate'] is not None else None))
    return rows


def prepare(store, job, project, directory, progress):
    import pandas as pd
    params=deepcopy(job['spec']['parameters']);kind=job['kind'];directory=Path(directory)
    if type(params.get('updateData',True)) is not bool:raise ValueError('数据更新选项必须为布尔值')
    directory.mkdir(parents=True,exist_ok=True)
    start,end=scope(project,params,kind)
    params.setdefault('startDate',start);params.setdefault('endDate',end)
    sources=source_settings(project.get('settings',{}))
    report={'requestedStart':start,'requestedEnd':end,'steps':[],'experimentIds':[],'dataSources':sources}
    def step(name,state,**info):
        report['steps'].append(dict(name=name,status=state,**info))
        write_json(directory/'preparation.json',report)
        progress(.03,'准备：'+name)
    step('研究范围','completed',startDate=start,endDate=end)
    try:
        input_params=params.get('baseParameters',params) if kind=='optimize.run' else params
        input_params=deepcopy(input_params)
        if not input_params.get('factorIds'):
            input_params['factorIds']=project.get('settings',{}).get('selectedFactors',[])
        if kind=='simulation.advance':
            settings=project.get('settings',{})
            input_params={**settings.get('model',{}),**settings.get('backtest',{})}
            input_params.setdefault('factorIds',settings.get('selectedFactors',[]))
        from .selection import update_end_date
        if kind=='model.train' and params['testEnd']>update_end_date():
            raise ValueError('模型测试区间包含尚未完成的日线，请调整明确日期')
        end=min(end,update_end_date())
        report['completedDailyCutoff']=end
        params['endDate']=min(params['endDate'],end)
        report['effectiveStart']=params['startDate'];report['effectiveEnd']=params['endDate']
        model=None
        if kind=='backtest.run' and params.get('template')=='model_score':
            model=deepcopy(project.get('settings',{}).get('model',{}))
            model.setdefault('factorIds',params.get('factorIds') or project.get('settings',{}).get('selectedFactors',[]))
            if params.get('modelExperimentId') and not model.get('model'):
                model=deepcopy(store.experiment(project['id'],params['modelExperimentId'])['parameters'])
            model_start,model_end=scope(project,model,'model.train')
            start=min(start,model_start);end=max(end,model_end);input_params=model
        elif kind=='optimize.run' and params.get('target')=='model':
            model_start,model_end=scope(project,input_params,'model.train')
            start=min(start,model_start);end=max(end,model_end)
        if end>update_end_date():raise ValueError('模型测试区间包含尚未完成的日线，请调整明确日期')
        root=Path(data.project_data(project)['path'])/'data'
        prices=data.read_table(project) if (root/'prices.parquet').exists() or (root/'prices').exists() else pd.DataFrame()
        codes=project['universe'].get('symbols',[])
        if codes and len(prices):prices=prices[prices.symbol.isin([data.symbol(c) for c in codes])]
        warmup=lookback(input_params)
        if kind in {'backtest.run','optimize.run','simulation.advance'}:
            warmup=max(warmup, int(input_params.get('portfolio',{}).get('lookback',252)) + 1)
        report['warmupSessions']=warmup
        expected=set(trading_dates(root,start,end,source=sources['daily'],update_data=params.get('updateData',True)))
        requirements=price_requirements(project,prices,expected,start,warmup)
        report['priceRequirements']=requirements
        # Missing pre-listing history cannot be repaired by downloading it.
        impossible=[r['symbol'] for r in requirements if r['requiredSessions'] and r['listingDate'] and
                    r['listingDate']>=r['warmupBefore'] and r['availableSessions']<r['requiredSessions']]
        structural=set(impossible) if kind=='factor.analyze' else set()
        if impossible and not structural:raise ValueError('上市后首个所需交易日没有足够因子预热历史：'+','.join(impossible))
        report['structuralWarmupSymbols']=sorted(structural)
        unknown_universe=not len(prices) and not codes and not project['universe'].get('membershipRef')
        need_prices=unknown_universe or any(r['missingDates'] or (r['availableSessions']<r['requiredSessions'] and r['symbol'] not in structural) for r in requirements)
        fetch_start=start
        # An empty catalog is unknown, not an explicitly empty dated membership.
        warmup_requirements=requirements or ([dict(symbol=None,requiredSessions=warmup,warmupBefore=start)] if unknown_universe else [])
        for requirement in warmup_requirements:
            count=requirement['requiredSessions']
            if not count or requirement['symbol'] in structural:continue
            first=requirement['warmupBefore']
            part=prices[prices.symbol.eq(requirement['symbol'])] if len(prices) else prices
            prior=sorted(set(pd.to_datetime(part.date).dt.strftime('%Y-%m-%d'))) if len(part) else []
            prior=[d for d in prior if d<first]
            if len(prior)<count:
                if sources['daily']!='baostock':raise ValueError('缺少所需预热行情或日历；当前日线来源 '+sources['daily']+' 不自动调用BaoStock')
                require_data_update(params,'因子预热交易日历')
                calendar=quotes._baostock(lambda bs:data._bs_query(bs,bs.query_trade_dates,
                    start_date=str((pd.Timestamp(first)-pd.Timedelta(days=max(366,count*4))).date()),end_date=first))
                sessions=calendar[calendar.is_trading_day.astype(str).eq('1')].calendar_date
                prior=sorted(d for d in sessions if d<first)
                if len(prior)<count:raise ValueError('来源交易日历不足以提供因子预热区间')
            fetch_start=min(fetch_start,prior[-count])
        report['inputStart']=fetch_start;report['inputEnd']=end
        if need_prices:
            if params.get('updateData',True) is False:
                raise ValueError('本次未启用数据更新，缺失行情须先导入或单独更新后再运行')
            if sources['daily']=='file':raise ValueError('日线来源为已有数据与文件，所需行情缺失；请导入后重试，不自动联网')
            step('历史行情','running',startDate=fetch_start,endDate=end)
            data.update(project,{'startDate':fetch_start,'endDate':end,'source':sources['daily'],'repairGaps':True},progress)
            prices=data.read_table(project)
            step('历史行情','completed',source=sources['daily'])
        else:step('历史行情','reused',source='本地已有行情')
        if prices.empty:raise ValueError('所选股票范围无实际行情，来源未返回所需数据')
        if not {'symbol','date'}.issubset(prices):raise ValueError('行情缺少证券或日期字段')
        if codes:prices=prices[prices.symbol.isin([data.symbol(c) for c in codes])]
        if prices.empty:raise ValueError('所选股票范围无实际行情')
        required_codes={r['symbol'] for r in requirements if r['expectedSessions']>0}
        if required_codes-set(prices.symbol):
            raise ValueError('来源未返回所选股票：'+','.join(sorted(required_codes-set(prices.symbol))))
        requirements=price_requirements(project,prices,expected,start,warmup)
        report['priceRequirements']=requirements
        gaps={r['symbol']:r['missingDates'] for r in requirements if r['missingDates']}
        if gaps:raise ValueError('来源仍缺所选区间交易日行情：'+'；'.join(code+' '+','.join(dates[:5]) for code,dates in gaps.items()))
        report['actualCoverage']={'startDate':str(pd.to_datetime(prices.date).min().date()),'endDate':str(pd.to_datetime(prices.date).max().date()),'rows':len(prices),'symbols':sorted(prices.symbol.unique())}
        report['warmupCoverage']=[{key:r[key] for key in ('symbol','availableSessions','requiredSessions','warmupBefore')} for r in requirements]
        for item in report['warmupCoverage']:
            item['status']='上市初期因子不可计算，按实际非空样本分析' if item['symbol'] in structural else '完整' if item['availableSessions']>=item['requiredSessions'] else '缺少历史'
        insufficient=[item['symbol'] for item in report['warmupCoverage'] if item['availableSessions']<item['requiredSessions'] and item['symbol'] not in structural]
        if insufficient:raise ValueError('来源历史不足以完成所选因子预热：'+','.join(insufficient))
        # Collect only when a held-price adjustment can require an entitlement.
        if kind in {'backtest.run','optimize.run','simulation.advance'} and 'factor' in prices:
            ordered=prices.sort_values(['symbol','date'])
            changes=ordered.groupby('symbol').factor.pct_change(fill_method=None).abs().gt(1e-5)
            missing=ordered[changes & pd.to_datetime(ordered.date).between(start,end)]
            actions=corporate_actions.read(project)
            known=set(zip(actions.symbol,actions.exDate)) if len(actions) else set()
            missing=missing[[ (r.symbol,str(pd.Timestamp(r.date).date())) not in known for r in missing.itertuples() ]]
            if len(missing):
                if sources['financials']=='file':raise ValueError('已有公司行动记录缺失；财务来源为文件，不自动联网')
                require_data_update(params,'公司行动记录')
                step('公司行动','running')
                quotes._baostock(lambda bs:corporate_actions.collect(project,bs,sorted(missing.symbol.unique()),fetch_start,end,data._bs_query))
                actions=corporate_actions.read(project);known=set(zip(actions.symbol,actions.exDate)) if len(actions) else set()
                unresolved=[f'{r.symbol} {str(pd.Timestamp(r.date).date())}' for r in missing.itertuples() if (r.symbol,str(pd.Timestamp(r.date).date())) not in known]
                if unresolved:raise ValueError('来源仍缺公司行动：'+', '.join(unresolved))
                step('公司行动','completed',source='baostock')
            else:step('公司行动','reused')
        if kind in {'backtest.run','optimize.run'}:
            benchmark='SH000905' if input_params.get('benchmark')=='csi500' else 'SH000300'
            path=root/'benchmarks'/(benchmark+'.parquet')
            benchmark_dates=set(pd.to_datetime(pd.read_parquet(path).date)) if path.exists() else set()
            needed=set(pd.to_datetime(prices.loc[pd.to_datetime(prices.date).between(start,end),'date']))
            if needed-benchmark_dates:
                if sources['daily']!='baostock':raise ValueError('已有基准行情缺失，当前日线来源不自动切换BaoStock')
                require_data_update(params,'基准行情')
                from . import benchmarks
                step('基准行情','running')
                quotes._baostock(lambda bs:benchmarks.collect(project,bs,start,end,data._bs_query))
                step('基准行情','completed',source='baostock')
        financial_ids=set(input_params.get('factorIds',[])) & set(engines.FINANCIAL)
        if financial_ids:
            financial=data.read_table(project,'financials') if (root/'financials.parquet').exists() else pd.DataFrame()
            required={engines.FINANCIAL[key] for key in financial_ids}
            stamps={code:read_json(root/'financials'/(code+'.json'),{}) for code in prices.symbol.unique()}
            stale=[code for code,stamp in stamps.items() if stamp.get('start','9999')>fetch_start or stamp.get('end','')<end or stamp.get('downloadDate')!=now()[:10]]
            missing_financial=not required.issubset(financial) or bool(set(prices.symbol)-set(financial.get('symbol',[])))
            if missing_financial or sources['financials']!='file' and stale:
                if sources['financials']=='file':raise ValueError('所需公告财务缺失；财务来源为文件，请先导入，不自动联网')
                require_data_update(params,'公告财务')
                step('公告财务','running')
                def collect_financial(bs):
                    for code in sorted(prices.symbol.unique()):data._financial_update(project,bs,code[:2].lower()+'.'+code[2:],fetch_start,end)
                quotes._baostock(collect_financial)
                financial=data.read_table(project,'financials')
                if not required.issubset(financial):raise ValueError('来源未提供所选财务因子字段：'+','.join(sorted(required-set(financial))))
                step('公告财务','completed',source='baostock')
            else:step('公告财务','reused')
        if kind=='backtest.run' and params.get('template')=='model_score':
            key=signature(project,model);reused=None
            for experiment in store.experiments(project['id']):
                if experiment['kind']!='model.train':continue
                folder=Path(project['path'])/'.research/runs'/experiment['id']
                if read_json(folder/'details.json',{}).get('inputSignature')==key and all(store.artifact_path(project['id'],a).exists() for a in experiment['artifacts']):
                    reused=experiment;break
            if reused:step('模型训练','reused',experimentId=reused['id'])
            else:
                from .worker import save_result
                child_id=identifier();folder=Path(project['path'])/'.research/runs'/child_id;folder.mkdir(parents=True,exist_ok=True)
                child={**job,'id':child_id,'kind':'model.train','name':'按需模型训练','spec':{**job['spec'],'parameters':model}}
                step('模型训练','running')
                from .input_snapshot import capture
                fixed_project, fixed_model, reference = capture(store,project,model,folder,report)
                result=engines.train(fixed_project,fixed_model,folder,progress)
                result.update(inputSnapshot=reference, _inputProject=fixed_project)
                result.setdefault('details',{})['inputSignature']=key
                reused=save_result(store,child,project,result,folder);store.save_experiment(project['id'],reused)
                step('模型训练','completed',experimentId=reused['id'])
            params['modelExperimentId']=reused['id'];report['experimentIds'].append(reused['id'])
        write_json(directory/'preparation.json',report)
        return params,report
    except Exception as exc:
        step('准备停止','failed',message=str(exc))
        raise
