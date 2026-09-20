"""Saved training observations and sample-out diagnostics, never trading attribution."""
import time
import numpy as np
import pandas as pd


def fit(estimator, train, valid, columns, params):
    started=time.perf_counter();events=[];evaluation={}
    kwargs={}
    if params['model']=='lightgbm':
        from lightgbm import record_evaluation, early_stopping
        callbacks=[record_evaluation(evaluation)]
        kwargs.update(eval_set=[(train[columns],train.label),(valid[columns],valid.label)],eval_names=['train','valid'],eval_metric='l2')
        rounds=params.get('earlyStoppingRounds')
        if rounds:
            if int(rounds)<1:raise ValueError('早停轮数必须为正整数')
            callbacks.append(early_stopping(int(rounds),verbose=False))
        kwargs['callbacks']=callbacks
    estimator.fit(train[columns],train.label,**kwargs)
    events.append(dict(event='fit',elapsedSeconds=time.perf_counter()-started,trainRows=len(train),validRows=len(valid),
                       bestIteration=getattr(estimator,'best_iteration_',None),model=params['model'],
                       **{k:params.get(k) for k in ('trainStart','trainEnd','validStart','validEnd','testStart','testEnd')}))
    curves=[]
    for partition,metrics in evaluation.items():
        for metric,values in metrics.items():
            curves += [dict(partition=partition,metric=metric,iteration=i+1,value=value) for i,value in enumerate(values)]
    if params['model']=='ridge':
        coefficients=estimator[-1].coef_
        importance=pd.DataFrame({'feature':columns,'coefficient':coefficients,'basis':'standardized_model_input'})
    else:
        importance=pd.DataFrame({'feature':columns,'gain':estimator.booster_.feature_importance(importance_type='gain'),
                                 'split':estimator.booster_.feature_importance(importance_type='split')})
    return {'training_events':pd.DataFrame(events),'training_evaluation':pd.DataFrame(curves),'model_importance':importance}


def predictions(frame):
    rows=[]
    for date,day in frame.replace([np.inf,-np.inf],np.nan).groupby(level=0):
        usable=day.dropna(subset=['label','score'])
        residual=usable.label-usable.score
        enough=len(usable)>=2 and usable.label.nunique()>1 and usable.score.nunique()>1
        rows.append(dict(date=date,expected=len(day),predictions=int(day.score.notna().sum()),samples=len(usable),
            status='available' if len(usable) else 'labels_unavailable',
            mse=(residual**2).mean(),mae=residual.abs().mean(),bias=residual.mean(),
            pearsonIC=usable.label.corr(usable.score) if enough else np.nan,
            rankIC=usable.label.corr(usable.score,method='spearman') if enough else np.nan))
    rows=pd.DataFrame(rows,columns=['date','expected','predictions','samples','status','mse','mae','bias','pearsonIC','rankIC']).set_index('date')
    for key in ['pearsonIC','rankIC']:
        rows[key+'Rolling20']=rows[key].rolling(20,min_periods=5).mean()
        rows[key+'Std20']=rows[key].rolling(20,min_periods=5).std()
    return rows


def prediction_contributions(estimator, x, params):
    """Model output decomposition; explicitly unrelated to realized security PnL."""
    if x.empty:return pd.DataFrame(index=x.index,columns=[*x.columns,'model_intercept'],dtype=float)
    if params['model']=='lightgbm':
        values=estimator.predict(x,pred_contrib=True)
        result=pd.DataFrame(values,index=x.index,columns=list(x.columns)+['model_intercept'])
    else:
        values=estimator[:-1].transform(x)*estimator[-1].coef_
        result=pd.DataFrame(values,index=x.index,columns=x.columns)
        result['model_intercept']=float(estimator[-1].intercept_)
    return result


def factor_tables(project, values, clean, forward, prices, ic, rank_ic):
    """Per-date evidence before/after label cleaning; industry IC is conditional."""
    from .history import read
    industry_history=read(project,'industry')
    industry_history['effectiveDate']=pd.to_datetime(industry_history.effectiveDate)
    coverage=[];trend=[];industry_rows=[]
    for date,day in values.groupby(level=0):
        selected=day.droplevel(0)
        aligned=forward.reindex(day.index)
        cleaned=clean[clean.index.get_level_values(0)==date]
        for period in forward:
            valid=day.notna()&aligned[period].notna()
            coverage.append(dict(date=date,period=period,processedAvailable=int(day.notna().sum()),
                forwardAvailable=int(valid.sum()),cleanedAvailable=len(cleaned),
                labelLoss=int(day.notna().sum()-valid.sum()),
                jointCleaningLoss=int(valid.sum()-len(cleaned)),
                denominator=len(day),cleaningBasis='all_requested_horizons_and_quantile_assignment'))
        known=industry_history[industry_history.effectiveDate.le(date)]
        groups=known.sort_values('effectiveDate').drop_duplicates('symbol',keep='last').set_index('symbol').industry.reindex(selected.index)
        for group in sorted(groups.dropna().unique()):
            codes=groups[groups.eq(group)].index
            x=selected.reindex(codes)
            for period in forward:
                y=aligned[period].droplevel(0).reindex(codes)
                usable=pd.concat([x.rename('factor'),y.rename('label')],axis=1).dropna()
                enough=len(usable)>=3 and usable.factor.nunique()>1 and usable.label.nunique()>1
                industry_rows.append(dict(date=date,industry=group,period=period,expected=len(codes),samples=len(usable),
                    pearsonIC=usable.factor.corr(usable.label) if enough else np.nan,
                    rankIC=usable.factor.corr(usable.label,method='spearman') if enough else np.nan,
                    status='available' if enough else 'insufficient_or_constant_cross_section'))
        industry_rows.append(dict(date=date,industry=None,period=None,expected=len(selected),samples=int(groups.notna().sum()),
            pearsonIC=np.nan,rankIC=np.nan,status='industry_coverage'))
    for method,table in [('pearson',ic),('spearman',rank_ic)]:
        for period in table:
            series=table[period].sort_index()
            for window in (20,60):
                rolling=series.rolling(window,min_periods=window)
                average=rolling.mean();sd=rolling.std()
                for date in series.index:
                    trend.append(dict(date=date,period=period,method=method,window=window,validDays=int(series.loc[:date].tail(window).notna().sum()),
                        meanIC=average.loc[date],icir=average.loc[date]/sd.loc[date] if pd.notna(sd.loc[date]) and sd.loc[date]>0 else np.nan))
    return {'sample_coverage':pd.DataFrame(coverage),'industry_diagnostics':pd.DataFrame(industry_rows),'effectiveness_trend':pd.DataFrame(trend)}
