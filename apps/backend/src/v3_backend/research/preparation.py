"""Prepare only inputs of an explicitly submitted research run, in its worker."""
from copy import deepcopy
from pathlib import Path
from . import data, engines, quotes, corporate_actions
from .storage import read_json, write_json, identifier, now

KINDS={'factor.analyze','model.train','backtest.run','optimize.run','simulation.advance'}


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


def trading_dates(root,start,end):
    import pandas as pd
    cached=read_json(root/'trading-calendar.json',{})
    if cached.get('start','9999')<=start and cached.get('end','')>=end:
        return [d for d in cached['dates'] if start<=d<=end]
    observed=set()
    for path in (root/'benchmarks').glob('*.parquet'):
        observed.update(str(pd.Timestamp(d).date()) for d in pd.read_parquet(path,columns=['date']).date)
    if observed and min(observed)<=start and max(observed)>=end:
        return sorted(d for d in observed if start<=d<=end)
    frame=quotes._baostock(lambda bs:data._bs_query(bs,bs.query_trade_dates,start_date=start,end_date=end))
    dates=sorted(str(d) for d in frame.loc[frame.is_trading_day.astype(str).eq('1'),'calendar_date'])
    write_json(root/'trading-calendar.json',{'start':start,'end':end,'dates':dates})
    return dates


def prepare(store, job, project, directory, progress):
    import pandas as pd
    params=deepcopy(job['spec']['parameters']);kind=job['kind'];directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    start,end=scope(project,params,kind)
    params.setdefault('startDate',start);params.setdefault('endDate',end)
    report={'requestedStart':start,'requestedEnd':end,'steps':[],'experimentIds':[]}
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
        warmup=lookback(input_params);report['warmupSessions']=warmup
        expected=set(trading_dates(root,start,end))
        before=sorted(pd.to_datetime(prices.date).unique()) if len(prices) else []
        prior=[d for d in before if d<pd.Timestamp(start)]
        need_prices=not len(prices) or len(prior)<warmup
        if codes and len(prices):need_prices=need_prices or bool(set(map(data.symbol,codes))-set(prices.symbol))
        if len(prices):
            for _,part in prices.groupby('symbol'):
                dates=pd.to_datetime(part.date)
                if dates.lt(start).sum()<warmup:need_prices=True
                if expected-set(dates.dt.strftime('%Y-%m-%d')):need_prices=True
        fetch_start=str(pd.Timestamp(prior[-warmup]).date()) if warmup and len(prior)>=warmup else start
        if warmup and len(prior)<warmup:
            calendar=quotes._baostock(lambda bs:data._bs_query(bs,bs.query_trade_dates,
                start_date=str((pd.Timestamp(start)-pd.Timedelta(days=max(366,warmup*4))).date()),end_date=start))
            sessions=calendar[calendar.is_trading_day.astype(str).eq('1')].calendar_date
            sessions=sorted(d for d in sessions if d<start)
            if len(sessions)<warmup:raise ValueError('来源交易日历不足以提供因子预热区间')
            fetch_start=sessions[-warmup]
        if need_prices:
            step('历史行情','running',startDate=fetch_start,endDate=end)
            data.update(project,{'startDate':fetch_start,'endDate':end,'source':'baostock','repairGaps':True},progress)
            prices=data.read_table(project)
            step('历史行情','completed',source='baostock')
        else:step('历史行情','reused',source='本地已有行情')
        if codes:prices=prices[prices.symbol.isin([data.symbol(c) for c in codes])]
        if prices.empty:raise ValueError('所选股票范围无实际行情')
        if codes and set(map(data.symbol,codes))-set(prices.symbol):
            raise ValueError('来源未返回所选股票：'+','.join(sorted(set(map(data.symbol,codes))-set(prices.symbol))))
        gaps={code:sorted(expected-set(pd.to_datetime(part.date).dt.strftime('%Y-%m-%d'))) for code,part in prices.groupby('symbol')}
        gaps={code:dates for code,dates in gaps.items() if dates}
        if gaps:
            # Only actual source listing/delisting dates can excuse absent sessions.
            def listing_check(bs):
                for code in list(gaps):
                    basic=data._bs_query(bs,bs.query_stock_basic,code=code[:2].lower()+'.'+code[2:])
                    if len(basic):
                        row=basic.iloc[0];listed=str(row.get('ipoDate') or '0000');ended=str(row.get('outDate') or '9999')
                        gaps[code]=[d for d in gaps[code] if listed<=d<=ended]
            quotes._baostock(listing_check)
            gaps={code:dates for code,dates in gaps.items() if dates}
            if gaps:raise ValueError('来源仍缺所选区间交易日行情：'+'；'.join(code+' '+','.join(dates[:5]) for code,dates in gaps.items()))
        report['actualCoverage']={'startDate':str(pd.to_datetime(prices.date).min().date()),'endDate':str(pd.to_datetime(prices.date).max().date()),'rows':len(prices),'symbols':sorted(prices.symbol.unique())}
        report['warmupCoverage']=[{'symbol':code,'availableSessions':int(pd.to_datetime(part.date).lt(start).sum()),'requiredSessions':warmup} for code,part in prices.groupby('symbol')]
        insufficient=[item['symbol'] for item in report['warmupCoverage'] if item['availableSessions']<warmup]
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
            if not required.issubset(financial) or set(prices.symbol)-set(financial.get('symbol',[])) or stale:
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
                result=engines.train(project,model,folder,progress)
                result.setdefault('details',{})['inputSignature']=key
                reused=save_result(store,child,project,result,folder);store.save_experiment(project['id'],reused)
                step('模型训练','completed',experimentId=reused['id'])
            params['modelExperimentId']=reused['id'];report['experimentIds'].append(reused['id'])
        write_json(directory/'preparation.json',report)
        return params,report
    except Exception as exc:
        step('准备停止','failed',message=str(exc))
        raise
