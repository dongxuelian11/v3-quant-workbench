"""Standalone screening over the existing dated data, factors and decision adapters."""
from copy import deepcopy
from pathlib import Path
import json
import numpy as np
import pandas as pd
from . import data, engines, history, market, preparation
from .screen_conditions import evaluate, weighted_scores
from .storage import read_json


def _rules(group):
    if 'children' in group:
        for child in group['children']:yield from _rules(child)
    else:yield group


def _calendar(project, end, partial, window):
    root=Path(data.project_data(project)['path'])/'data'
    start=str((pd.Timestamp(end)-pd.Timedelta(days=max(366,(window+30)*3))).date())
    cached=read_json(root/'trading-calendar.json',{})
    dates=set(cached.get('dates',[]))
    for path in (root/'benchmarks').glob('*.parquet'):
        dates.update(pd.to_datetime(pd.read_parquet(path,columns=['date']).date).dt.strftime('%Y-%m-%d'))
    # Observed dates are a partial calendar, explicitly disclosed in preview.
    for path in (([root/'prices.parquet'] if (root/'prices.parquet').exists() else [])+list((root/'prices').glob('*.parquet'))) if partial else []:
        dates.update(pd.to_datetime(pd.read_parquet(path,columns=['date']).date).dt.strftime('%Y-%m-%d'))
    observed=sorted(d for d in dates if start<=d<=end)
    if not partial and (len(observed)<window or max(cached.get('end',''),max(dates,default=''))<end):
        return preparation.trading_dates(root,start,end,source=preparation.source_settings(project.get('settings',{}))['daily'])
    return observed


def _model_inputs(store, assets):
    inputs=[]
    for asset in assets:
        if asset['kind']!='model':continue
        key=asset.get('experimentId') or asset['snapshot'].get('modelExperimentId')
        experiment=store.experiment(asset.get('projectId'),key)
        if experiment['kind']!='model.train':raise ValueError('成果不是模型实验')
        artifact=next((a for a in experiment['artifacts'] if a['name']=='model' and a['type']=='joblib'),None)
        kind='estimator' if artifact else 'predictions'
        if artifact is None:artifact=next((a for a in experiment['artifacts'] if a['name']=='test_predictions'),None)
        if artifact is None:raise ValueError('模型没有可复用估计器或测试预测；原生模型需先生成对应日期预测')
        inputs.append(dict(dataPath=str(store.artifact_path(asset.get('projectId'),artifact)),
            originExperimentId=key,assetId=asset['id'],kind=kind,trainingParameters=asset['snapshot'].get('parameters') or experiment['parameters']))
    if len(inputs)>1:raise ValueError('本次仅支持一份明确模型预测，请选择模型版本')
    return inputs


def _previous_diff(store, plan, frame):
    from .screeners import result_table
    candidates=[]
    for experiment in store.experiments(None):
        if experiment['kind']!='screener.run' or experiment.get('parameters',{}).get('plan',{}).get('id')!=plan['id']:continue
        folder=Path(store.project(None)['path'])/'.research/runs'/experiment['id']
        if read_json(folder/'details.json',{}).get('status')=='complete':candidates.append(experiment)
    if not candidates:return dict(available=False,message='没有上一完整结果可比较')
    previous=max(candidates,key=lambda x:x['createdAt']);old=result_table(store,previous)
    before=set(old.loc[old.status.eq('included'),'symbol']);after=set(frame.loc[frame.status.eq('included'),'symbol'])
    return dict(available=True,previousExperimentId=previous['id'],added=sorted(after-before),removed=sorted(before-after),unchanged=sorted(after&before))


def run(store, project, params, directory, progress, daily_snapshot=None):
    from .input_snapshot import capture
    from .selection import update_end_date
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    plan=deepcopy(params['plan']);partial=bool(params.get('allowPartial'))
    if daily_snapshot is not None and partial:raise ValueError('每日组合不能使用已有数据预览')
    catalog={f['id']:f['expression'] for f in engines.factor_catalog()}
    for asset in plan.get('assets',[]):
        saved=asset.get('snapshot',{})
        if asset['id'].startswith('builtin:') and saved.get('expression')!=catalog.get(saved.get('factorId')):
            raise ValueError('内置因子表达式已变化，请明确重新采用成果版本：'+asset.get('name',asset['id']))
    project=deepcopy(project)
    # Submission owns the copied membership reference; do not restore the source ref.
    universe=project['universe']
    if universe.get('source')=='manual' and not universe.get('symbols') and not universe.get('membershipRef'):
        raise ValueError('手动股票池或自选列表为空，请明确选择证券')
    end=plan.get('date') or update_end_date()
    if end>update_end_date():raise ValueError('选股日期尚无已完成日线')
    rules=list(_rules(plan['conditions']))+list(_rules(plan.get('preconditions',{'children':[]})))
    fields={r['field'] for r in rules}|{r['compareField'] for r in rules if r.get('compareField')}
    window=max([1]+[int(r.get('window',1))+(r['operator'].startswith('cross_')) for r in rules])
    calendar=_calendar(project,end,partial,window)
    if not calendar:raise ValueError('没有可核验的交易日期，请先准备行情和交易日历')
    asof=calendar[-1];dates=calendar[-window:];start=dates[0]
    project.update(startDate=start,endDate=asof)
    assets=plan.get('assets',[]);custom=[a['snapshot']['customFactor'] for a in assets if a['kind']=='factor' and a['snapshot'].get('customFactor')]
    strategy_asset=next((a for a in assets if a['kind']=='strategy'),None)
    strategy_settings=strategy_asset['snapshot'].get('settings',{}) if strategy_asset else {}
    strategy=deepcopy(strategy_settings.get('backtest',{})) if strategy_asset else None
    if strategy is not None:
        strategy.setdefault('factorIds',strategy_settings.get('selectedFactors',[]))
        strategy['factorProcessing']={**strategy_settings.get('factorProcessing',{}),**strategy.get('factorProcessing',{})}
    if plan['mode']=='strategy' and not strategy:raise ValueError('策略成果没有可执行的评分配置')
    account_fields={'quantity','costPrice','returnSinceEntry','sellableQuantity','cash'}
    account_rules=any(r.get('action') in {'exit','reduce','add'} or any(c.get('field') in account_fields for c in r.get('conditions',[])) for r in (strategy or {}).get('rules',[]))
    if daily_snapshot is None and strategy and (strategy.get('dailyCode') or account_rules):
        raise ValueError('该策略含退出、减仓或加仓规则，需要真实账户持仓；独立候选评分不能代替账户执行')
    if daily_snapshot is not None and window>1 and strategy and (strategy.get('dailyCode') or account_rules):
        raise ValueError('账户规则暂只支持当日条件窗口，不能把今日持仓用于过去日期')
    if strategy_asset:
        custom+=strategy_asset['snapshot'].get('settings',{}).get('customFactors',[])
    model_inputs=_model_inputs(store,assets)
    for model in model_inputs:custom+=model['trainingParameters'].get('customFactors',[])
    custom=list({c['id']:c for c in custom}.values())
    catalog={x['id'] for x in engines.factor_catalog()}|{x['id'] for x in custom}
    ids=sorted((fields&catalog)|{f['id'] for f in plan.get('factors',[])}|set((strategy or {}).get('factorIds',[])))
    ids=sorted(set(ids)|{key for model in model_inputs for key in model['trainingParameters'].get('factorIds',[])})
    # Financial fields share the existing announcement-date preparation adapter.
    ids=sorted(set(ids)|{key for key,column in engines.FINANCIAL.items() if column in fields})
    compute=dict(factorIds=ids,customFactors=custom,startDate=start,endDate=asof,
        updateData=params.get('updateData',True),
        factorProcessing={**(strategy or {}).get('factorProcessing',{}),'directions':{}})
    plan_path=directory/'screening-plan.json'
    plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    compute['planFile']={'dataPath':str(plan_path.resolve())}
    compute['modelScoreFiles']=model_inputs
    if daily_snapshot is not None:
        compute['portfolio']=(strategy or {}).get('portfolio',{})
        if model_inputs:
            training=model_inputs[0]['trainingParameters']
            compute['startDate']=training.get('trainStart') or str((pd.Timestamp(asof)-pd.DateOffset(years=int(training.get('validation',{}).get('trainYears',3)))).date())
    if strategy and strategy.get('template')=='model_score' and not compute['modelScoreFiles']:
        raise ValueError('模型评分策略需选择一份保留对应日期测试预测的模型成果')
    if partial:
        prices=market._read(project,'prices')
        if prices.empty:raise ValueError('没有已有行情可形成预览')
        prepared=dict(inputStart=str(pd.to_datetime(prices.date).min().date()),inputEnd=asof,
            effectiveStart=start,effectiveEnd=asof,steps=[dict(name='已有数据预览',status='reused')])
    else:
        compute,prepared=preparation.prepare(store,dict(kind='factor.analyze',spec={'parameters':compute}),project,directory,progress)
    fixed,compute,reference=capture(store,project,compute,directory,prepared)
    prices=data.read_table(fixed);prices=prices[pd.to_datetime(prices.date).le(asof)].copy()
    panel=market.dated_panel(fixed,prices)
    codes=set(map(data.symbol,universe.get('symbols',[])))
    membership=history.membership_frame(fixed)
    if membership is not None:codes|=set(membership.symbol)
    if not codes:codes=set(prices.symbol)
    index=pd.MultiIndex.from_product([pd.to_datetime(dates),sorted(codes)],names=['date','symbol'])
    panel=panel.set_index(['date','symbol']).reindex(index)
    expected,daily=history.expected_rows(fixed,prices,pd.to_datetime(dates),panel.reset_index())
    base=pd.Series(index.isin(expected),index=index)
    observed=panel.get('close',pd.Series(np.nan,index=index)).notna()
    eligibility=pd.Series(True,index=index)
    if universe.get('excludeST'):
        flags=pd.to_numeric(panel.get('isST',pd.Series(np.nan,index=index)),errors='coerce')
        eligibility &= flags.notna();base &= flags.eq(0)|flags.isna()
    if universe.get('minListingDays',0):
        eligibility &= pd.to_datetime(panel.get('listingDate',pd.Series(pd.NaT,index=index)),errors='coerce').notna()
    if ids:
        progress(.25,'计算选股所需因子')
        calculation_prices=engines.prepare(fixed,directory,progress)
        values=engines.features(fixed,compute,calculation_prices)
        values.index=values.index.set_names(['date','symbol'])
        for key in values:panel[key]=values[key].reindex(index)
    monthly=None
    if daily_snapshot is not None and compute['modelScoreFiles']:
        if len(dates)>1:raise ValueError('每日月度模型评分暂不支持跨日条件窗口，请使用当日模型条件')
        from .selection import run as select
        model=compute['modelScoreFiles'][0]
        training=model['trainingParameters']
        if not training.get('model'):raise ValueError('模型成果缺少可重训配置，不能改用其他模型')
        monthly_project=deepcopy(fixed)
        monthly_project.update(startDate=prepared['inputStart'],endDate=asof)
        monthly=select(monthly_project,dict(enabled=True,updateData=False,retrain='monthly',endDate=asof,model=training,
            strategy=dict(template='model_score',topN=max(1,len(codes)),portfolio={'method':'equal'})),
            directory/'daily_model',progress,snapshot=daily_snapshot,score_only=True)
        if pd.Timestamp(monthly['date'])!=pd.Timestamp(asof):raise ValueError('月度模型行情日期与筛选日期不一致')
        panel['model_score']=pd.Series([monthly['scores'].get(code,np.nan) for _,code in index],index=index)
    elif compute['modelScoreFiles']:
        file=compute['modelScoreFiles'][0]['dataPath'];file=Path(file) if Path(file).is_absolute() else Path(fixed['path'])/file
        model=compute['modelScoreFiles'][0]
        if model['kind']=='estimator':
            import joblib
            training=model['trainingParameters']
            if not training.get('testStart') or pd.Timestamp(start)<pd.Timestamp(training['testStart']):
                raise ValueError('模型评分日期早于其保留测试起点，不能用未来训练成果回看')
            estimator=joblib.load(file)
            model_params={**training,'startDate':start,'endDate':asof,'customFactors':compute['customFactors']}
            x=engines.features(fixed,model_params,calculation_prices)
            names=list(getattr(estimator,'feature_names_in_',training.get('factorIds',[])))
            x=x.reindex(columns=names)
            scores=pd.Series(estimator.predict(x) if len(x) else [],index=x.index,dtype=float)
            scores.index=scores.index.set_names(['date','symbol'])
            panel['model_score']=scores.reindex(index)
        else:
            predictions=pd.read_parquet(file).rename(columns={'datetime':'date','instrument':'symbol','prediction':'score'})
            predictions['date']=pd.to_datetime(predictions.date)
            if predictions.duplicated(['date','symbol']).any():raise ValueError('模型预测日期与证券重复')
            panel['model_score']=predictions.set_index(['date','symbol']).score.reindex(index)
    legacy_query=plan.get('query',{})
    if legacy_query.get('search'):
        search_mask=market._search_names(panel.reset_index(),legacy_query['search'])
        base &= pd.Series(search_mask.to_numpy(),index=index)
    reference_mask=base&observed&eligibility
    pre=pd.Series(True,index=index,dtype='boolean')
    if plan.get('rankingReference')=='prefilter':
        if not plan.get('preconditions'):raise ValueError('前置排名参照需要明确前置条件')
        pre,_=evaluate(panel,plan['preconditions'],reference_mask)
        reference_mask &= pre.fillna(False)
    contributions=pd.DataFrame(index=index)
    score=pd.Series(np.nan,index=index,dtype=float)
    decision_allowed=pd.Series(True,index=index)
    if plan['mode']=='factors':score,contributions=weighted_scores(panel,plan['factors'],reference_mask)
    elif plan['mode']=='strategy':
        from .strategy import decide_day
        strategy_ids=strategy.get('factorIds',[])
        if strategy.get('template','multi_factor')=='model_score':score=panel['model_score']
        else:
            directions=strategy.get('factorProcessing',{}).get('directions',{})
            for key in strategy_ids:
                raw=panel[key]*directions.get(key,1)
                contributions[key]=raw.where(reference_mask).groupby(level='date').rank(pct=True)*float(strategy.get('weights',{}).get(key,1))
            if len(contributions.columns):score=contributions.sum(axis=1,min_count=len(contributions.columns))
        decisions=[]
        for date in pd.to_datetime(dates):
            day_scores=score.xs(date,level='date');features=panel.copy();features.index=features.index.set_names(['datetime','instrument'])
            decision=decide_day(dict(date=date,prices=prices,scores=day_scores,features=features,holdings={r['symbol']:{k:v for k,v in r.items() if k!='symbol'} for r in daily_snapshot['rows']} if daily_snapshot is not None else {},cash=daily_snapshot['cash'] if daily_snapshot is not None else 1.,state={}),strategy)
            adjusted=decision['scores'].copy()
            if not strategy.get('rules') and not strategy.get('dailyCode'):
                omitted=day_scores.notna() & ~day_scores.index.isin(adjusted.index)
                decision_allowed.loc[date]=~omitted.reindex(decision_allowed.loc[date].index,fill_value=False).to_numpy()
            if strategy.get('rules') or strategy.get('dailyCode'):
                targets=decision.get('targets') or {}
                allowed=adjusted.index.isin([k for k,v in targets.items() if v>0])
                if daily_snapshot is None:adjusted=adjusted.where(allowed)
                else:
                    decision_allowed.loc[date]=decision_allowed.loc[date].index.isin([k for k,v in targets.items() if v>0])
                    if not strategy_ids and strategy.get('template')!='model_score':adjusted=adjusted.fillna(1.)
            adjusted.index=pd.MultiIndex.from_product([[date],adjusted.index],names=['date','symbol']);decisions.append(adjusted)
        score=pd.concat(decisions).reindex(index)
    panel['score']=score
    matched,condition_details=evaluate(panel,plan['conditions'],reference_mask)
    day=pd.Timestamp(asof);latest=panel.xs(day,level='date');rows=[]
    for code,row in latest.iterrows():
        key=(day,code);status='included';reason='满足条件'
        if not base.loc[key]:status,reason='outside','不在本次基础范围或上市筛选范围'
        elif not observed.loc[key] or not eligibility.loc[key]:status,reason='missing','当日行情或基础筛选资料缺失'
        elif pd.isna(pre.loc[key]):status,reason='missing','前置条件所需资料缺失'
        elif not bool(pre.loc[key]):status,reason='excluded','未满足排名前置条件'
        elif not decision_allowed.loc[key]:status,reason='excluded','策略当日未给出正目标仓位'
        elif pd.isna(matched.loc[key]) or plan['mode']!='conditions' and pd.isna(score.loc[key]):status,reason='missing','所需条件窗口、因子或模型评分缺失'
        elif not bool(matched.loc[key]):status,reason='excluded','未满足条件'
        details=[]
        for rule_id,detail in condition_details.items():
            def scalar(value):return None if pd.isna(value) else value.item() if hasattr(value,'item') else value
            details.append(dict(id=rule_id,field=detail['field'],value=scalar(detail['values'].loc[key]),
                rank=scalar(detail['ranks'].loc[key]) if detail['ranks'] is not None else None,matched=scalar(detail['matches'].loc[key])))
        components={name:(float(contributions.loc[key,name]) if pd.notna(contributions.loc[key,name]) else None) for name in contributions}
        rows.append(dict(symbol=code,name='' if pd.isna(row.get('name')) else row.get('name',''),date=asof,
            score=float(score.loc[key]) if pd.notna(score.loc[key]) else None,status=status,reason=reason,
            conditions=json.dumps(details,ensure_ascii=False),contributions=json.dumps(components,ensure_ascii=False)))
        for field,value in row.items():
            if field in rows[-1]:continue
            rows[-1][field]=None if pd.isna(value) else value.item() if hasattr(value,'item') else value
    frame=pd.DataFrame(rows) if rows else pd.DataFrame(columns=['symbol','name','date','score','status','reason','conditions','contributions'])
    limit=plan.get('limit',legacy_query.get('limit'))
    if limit:
        ordered=frame[frame.status.eq('included')].copy()
        sort_by=legacy_query.get('sortBy') or 'score'
        if sort_by in latest and sort_by not in ordered:ordered[sort_by]=ordered.symbol.map(latest[sort_by])
        if sort_by not in ordered:sort_by='score'
        ordered=ordered.sort_values([sort_by,'symbol'] if sort_by!='symbol' else ['symbol'],
            ascending=[not legacy_query.get('descending',True),True] if sort_by!='symbol' else [not legacy_query.get('descending',True)],na_position='last',kind='stable')
        frame.loc[ordered.index[int(limit):],['status','reason']]=['excluded','超过入选数量限制']
    counts=dict(scope=int(frame.status.ne('outside').sum()),valid=int(frame.status.isin(['included','excluded']).sum()),
        included=int(frame.status.eq('included').sum()),missing=int(frame.status.eq('missing').sum()))
    coverage_row=daily.loc[pd.to_datetime(daily.date).eq(day)].iloc[-1]
    expected_symbols=coverage_row['expected']
    coverage=dict(asOfDate=asof,expectedSymbols=int(expected_symbols) if pd.notna(expected_symbols) else None,
        observedSymbols=int(coverage_row['observedPool']),eligibilityUnknown=int(coverage_row['eligibilityUnknown']),
        denominatorStatus=str(coverage_row['denominatorStatus']))
    known=not daily.empty and daily.denominatorStatus.eq('known').all()
    if not partial and (counts['missing'] or not known):raise ValueError('选股所需输入不完整：'+str(counts['missing'])+'股缺数据；基础范围'+('已知' if known else '覆盖未确认')+'。可明确选择已有数据预览。')
    status='preview' if partial else 'complete'
    message='已有数据预览，未补源，不代表全市场完整覆盖。' if partial else '按固定输入完成；缺数据与范围外证券未当作不满足条件。'
    if strategy:message+=(' 策略采用全局持仓快照。' if daily_snapshot is not None else ' 策略采用空持仓候选上下文，不是现有账户交易建议。')
    details=dict(asOfDate=asof,status=status,counts=counts,message=message,coverage=coverage,
        diff=_previous_diff(store,plan,frame) if status=='complete' else dict(available=False,message='预览不与完整结果比较'),preparation=prepared,
        strategyContext=('全局持仓快照' if daily_snapshot is not None else '独立候选评分，使用空持仓上下文；不是现有账户的交易建议') if strategy else None,
        modelScoring='按固定配置月度重训和推理' if monthly is not None else '固定估计器推理' if model_inputs and model_inputs[0]['kind']=='estimator' else '保留测试预测，仅其实际日期可用' if model_inputs else None)
    progress(.95,'保存选股结果和逐股说明')
    result=dict(metrics=counts,artifacts=[engines.save_table(directory,'screening',frame)],summary=message,details=details,
        parameters=deepcopy(params),inputSnapshot=reference,_inputProject=fixed)

    if daily_snapshot is not None:
        result['_daily']=dict(frame=frame,prices=prices,project=fixed,date=pd.Timestamp(asof),strategy=strategy,
            model=monthly,targets=decision.get('targets') if strategy and (strategy.get('dailyCode') or strategy.get('rules')) else None)
    return result
