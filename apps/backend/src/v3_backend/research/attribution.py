"""Named market/industry/style model. Realized PnL and ex-ante risk stay separate."""
import numpy as np
import pandas as pd
from scipy.linalg import lstsq, null_space
from sklearn.covariance import LedoitWolf


def risk_contributions(exposure, covariance):
    exposure=np.asarray(exposure,dtype=float)
    return exposure*(np.asarray(covariance,dtype=float)@exposure)


def fit_cross_section(exposure, returns, cap):
    """WLS with capitalization-weighted industry coefficient sum constrained to zero."""
    usable=exposure.join(returns.rename('return')).join(cap.rename('cap')).replace([np.inf,-np.inf],np.nan).dropna()
    usable=usable[usable.cap>0]
    columns=list(exposure.columns)
    if len(usable)<max(20,len(columns)+5):return None
    x=usable[columns].to_numpy(float);y=usable['return'].to_numpy(float)
    constraint=np.zeros((1,len(columns)))
    for i,name in enumerate(columns):
        if name.startswith('industry:'):constraint[0,i]=float(usable.loc[usable[name]>0,'cap'].sum())
    basis=null_space(constraint) if constraint.any() else np.eye(len(columns))
    weight=np.sqrt(np.sqrt(usable.cap.to_numpy()/usable.cap.median()))
    coef,_,rank,_=lstsq((x@basis)*weight[:,None],y*weight)
    if rank<basis.shape[1]:return None
    coef=basis@coef
    return pd.Series(coef,index=columns),pd.Series(y-x@coef,index=usable.index)


def relative_industry(weights, benchmark_weights, industry, returns):
    """Use Qlib's Brinson portfolio decomposition with already aligned V3 data.

    Qlib's top-level brinson_pa reads its own global data provider and forward-fills
    prices. Here its decomposition primitive receives validated dated observations.
    Cash is an explicit zero-return group, not a normalization of stock weights.
    """
    from qlib.backtest.profit_attribution import decompose_portofolio
    codes=weights.index.union(benchmark_weights.index)
    groups=industry.reindex(codes);ret=returns.reindex(codes)
    if groups.isna().any() or ret.isna().any():return None
    mapping={name:i for i,name in enumerate(sorted(groups.unique()))}
    groups=groups.map(mapping).astype(float)
    groups.loc['__cash__']=len(mapping);ret.loc['__cash__']=0.
    wp=weights.reindex(groups.index,fill_value=0.);wb=benchmark_weights.reindex(groups.index,fill_value=0.)
    wp.loc['__cash__']=1-weights.sum();wb.loc['__cash__']=1-benchmark_weights.sum()
    def row(series):return pd.DataFrame([series.to_dict()],index=[0])
    pw,pr=decompose_portofolio(row(wp),row(groups),row(ret))
    bw,br=decompose_portofolio(row(wb),row(groups),row(ret))
    rows=[]
    for group,label in {**{v:k for k,v in mapping.items()},len(mapping):'cash'}.items():
        p=float(pw.iloc[0][group]);b=float(bw.iloc[0][group]);rp=pr.iloc[0][group];rb=br.iloc[0][group]
        # A benchmark-empty group contributes through interaction. A portfolio-empty
        # group takes benchmark return, exactly as brinson_pa does.
        rb=0. if b==0 else float(rb);rp=rb if p==0 else float(rp)
        rows.append(dict(industry=label,portfolioWeight=p,benchmarkWeight=b,portfolioReturn=rp,benchmarkReturn=rb,
            allocation=(p-b)*rb,selection=b*(rp-rb),interaction=(p-b)*(rp-rb)))
    return pd.DataFrame(rows)


def analyze(project, prices, holdings, report, initial=None, config=None, trades=None, benchmark_name='csi300'):
    from .market import dated_panel
    from .corporate_actions import read
    config={'lookback':252,'minObservations':126,**(config or {})}
    lookback=int(config['lookback']);minimum=int(config['minObservations'])
    trades=pd.DataFrame() if trades is None else trades
    from .benchmarks import read_weights
    benchmark_weights=read_weights(project,benchmark_name)
    panel=dated_panel(project,prices).sort_values(['symbol','date'])
    panel['rawReturn']=panel.groupby('symbol').rawClose.pct_change(fill_method=None)
    panel['previousRawClose']=panel.groupby('symbol').rawClose.shift(1)
    panel['factorChange']=panel.groupby('symbol').factor.pct_change(fill_method=None).abs()>1e-5
    actions=read(project)
    action_keys=set(zip(actions.symbol,pd.to_datetime(actions.exDate))) if not actions.empty else set()
    affected=panel.factorChange | pd.Series([(s,d) in action_keys for s,d in zip(panel.symbol,panel.date)],index=panel.index)
    for i,row in panel[affected].iterrows():
        event=actions[(actions.symbol==row.symbol)&(actions.exDate==str(row.date)[:10])&(actions.status=='implemented')] if not actions.empty else pd.DataFrame()
        if len(event)!=1:
            panel.loc[i,'rawReturn']=np.nan
        else:
            e=event.iloc[0]
            panel.loc[i,'rawReturn']=(row.rawClose*(1+e.bonusRatio)+e.cashPerShare)/row.previousRawClose-1
    panel['floatCap']=pd.to_numeric(panel.get('floatShares',pd.Series(np.nan,index=panel.index)),errors='coerce')*panel.rawClose
    # Explicitly label this fallback; it is not reported share capital.
    if 'rawTurn' in panel:
        estimated=panel.volume/(pd.to_numeric(panel.rawTurn,errors='coerce')/100)*panel.rawClose
        panel['floatCap']=panel.floatCap.fillna(estimated.where(estimated>0))
    panel['logSize']=np.log(panel.floatCap.where(panel.floatCap>0))
    panel['liquidity20']=pd.to_numeric(panel.get('rawTurn',pd.Series(np.nan,index=panel.index)),errors='coerce').groupby(panel.symbol).transform(lambda x:x.rolling(20,min_periods=20).mean())
    styles=['momentum20','volatility20','logSize','book_yield','liquidity20']
    for name in styles:
        if name not in panel:panel[name]=np.nan
    all_dates=pd.DatetimeIndex(sorted(panel.date.unique()))
    groups={date:frame.set_index('symbol') for date,frame in panel.groupby('date')}
    factor_history=[];specific_history=[];returns_rows=[];exposure_rows=[];risk_rows=[];coverage=[];pnl_rows=[];specific_rows=[];risk_coverage=[];relative_rows=[]
    active_risk_rows=[];active_exposure_rows=[];active_coverage=[]
    prior_holdings=initial or {}
    last_nav=None
    for index,day in enumerate(all_dates[1:],1):
        previous_date=all_dates[index-1];before=groups[previous_date];after=groups[day]
        industry=before.get('industry',pd.Series(index=before.index,dtype=object))
        exposure=pd.get_dummies(industry,prefix='industry',prefix_sep=':',dtype=float)
        exposure.loc[industry.isna(),:]=np.nan
        exposure['market']=1.
        for name in styles:
            values=pd.to_numeric(before[name],errors='coerce')
            sd=values.std(ddof=0)
            exposure['style:'+name]=(values-values.mean())/sd if pd.notna(sd) and sd>1e-12 else np.nan
        fitted=fit_cross_section(exposure,after.rawReturn,before.floatCap)
        in_report=day in report.index
        if fitted is not None:
            factors,specific=fitted
            returns_rows += [dict(date=day,factor=k,factorReturn=v,exposureDate=previous_date) for k,v in factors.items()]
            specific_rows += [dict(date=day,symbol=k,specificReturn=v,exposureDate=previous_date) for k,v in specific.items()]
        else:factors=specific=None
        if in_report:
            if last_nav is None:last_nav=float(report.loc[day,'account']/(1+report.loc[day,'return']-report.loc[day,'cost']))
            weights=pd.Series({s:quantity*float(before.loc[s,'rawClose'])/last_nav for s,quantity in prior_holdings.items() if quantity and s in before.index},dtype=float)
            held=exposure.reindex(weights.index)
            complete=held.notna().all(axis=None) and all(s in before.index for s,q in prior_holdings.items() if q)
            coverage.append(dict(date=day,marketRows=len(before),fitRows=len(specific) if specific is not None else 0,
                status='available' if fitted is not None and complete else 'insufficient_cross_section_or_exposure',
                industryRows=int(industry.notna().sum()),capitalizationRows=int(before.floatCap.notna().sum()),
                completeExposureRows=int(exposure.notna().all(axis=1).sum()),requiredFitRows=max(20,len(exposure.columns)+5),
                heldWeight=float(weights.sum()),coveredHeldWeight=float(weights[held.notna().all(axis=1)].sum()),
                sizeBasis='floatShares where available; otherwise volume/rawTurn estimated float capitalization',
                benchmarkAttribution='missing_historical_benchmark_weights',riskReturnBasis='raw_close_plus_gross_entitlement'))
            bench=benchmark_weights[benchmark_weights.effectiveDate.eq(str(previous_date.date()))].set_index('symbol').weight
            if not bench.empty:
                relative=relative_industry(weights,bench,industry,after.rawReturn)
                coverage[-1]['benchmarkAttribution']='available' if relative is not None else 'missing_benchmark_security_returns_or_industry'
                coverage[-1]['benchmarkWeightDate']=previous_date
                if relative is not None:
                    relative_rows += relative.assign(date=day,exposureDate=previous_date,benchmark=benchmark_name,
                        basis='prior_close_holdings_raw_total_security_returns').to_dict('records')
            active_status='missing_historical_benchmark_weights'
            if not bench.empty:
                active=weights.subtract(bench,fill_value=0.)
                active=active[active.abs()>1e-14]
                active_design=exposure.reindex(active.index)
                active_status='missing_benchmark_or_portfolio_exposure'
                if active_design.notna().all(axis=None):
                    active_exposure=active_design.mul(active,axis=0).sum()
                    active_exposure_rows += [dict(date=day,asOfDate=previous_date,factor=k,exposure=v,benchmark=benchmark_name) for k,v in active_exposure.items()]
                    past=pd.DataFrame(factor_history).tail(lookback).reindex(columns=exposure.columns).dropna()
                    residual_sample=pd.DataFrame(specific_history).tail(lookback).reindex(columns=active.index)
                    active_status='insufficient_prior_factor_or_specific_history'
                    if len(past)>=minimum and (residual_sample.count()>=minimum).all():
                        covariance=LedoitWolf().fit(past.to_numpy()).covariance_*252
                        e=active_exposure.reindex(past.columns).to_numpy()
                        rc=risk_contributions(e,covariance)
                        sr=float((active**2*residual_sample.var()*252).sum());total=float(rc.sum()+sr)
                        active_risk_rows += [dict(date=day,asOfDate=previous_date,benchmark=benchmark_name,factor=k,
                            varianceContribution=v,moneyVarianceContribution=v*last_nav**2,totalVariance=total,
                            share=v/total if total>0 else None,lookback=lookback,minObservations=minimum,observations=len(past))
                            for k,v in [*zip(past.columns,rc),('specific',sr)]]
                        active_status='available'
            active_coverage.append(dict(date=day,asOfDate=previous_date,benchmark=benchmark_name,status=active_status,lookback=lookback,minObservations=minimum))
            actual=float(report.loc[day,'account']-last_nav)
            cost=float(report.loc[day,'cost']*last_nav)
            modeled=None
            if complete:
                portfolio_exposure=held.mul(weights,axis=0).sum()
                exposure_rows += [dict(date=day,exposureDate=previous_date,factor=k,exposure=v) for k,v in portfolio_exposure.items()]
                if factors is not None and weights.index.isin(specific.index).all():
                    contributions=portfolio_exposure*factors
                    pnl_rows += [dict(date=day,factor=k,pnl=v*last_nav,returnContribution=v,kind='factor') for k,v in contributions.items()]
                    residual=float((weights*specific.reindex(weights.index)).sum())
                    pnl_rows.append(dict(date=day,factor='specific',pnl=residual*last_nav,returnContribution=residual,kind='specific'))
                    modeled=float(contributions.sum()+residual)*last_nav
                # Only previous fitted return dates inform risk at the start of this day.
                history=pd.DataFrame(factor_history).tail(lookback).reindex(columns=exposure.columns).dropna()
                residuals=pd.DataFrame(specific_history).tail(lookback).reindex(columns=weights.index)
                estimable=len(history)>=minimum and (residuals.count()>=minimum).all()
                risk_coverage.append(dict(date=day,asOfDate=previous_date,lookback=lookback,minObservations=minimum,
                    factorObservations=len(history),minimumSpecificObservations=int(residuals.count().min()) if len(weights) else None,
                    status='available' if estimable else 'insufficient_prior_factor_or_specific_history',annualizationDays=252))
                if estimable:
                    covariance=LedoitWolf().fit(history.to_numpy()).covariance_*252
                    e=portfolio_exposure.reindex(history.columns).to_numpy()
                    factor_risk=risk_contributions(e,covariance)
                    specific_risk=float((weights**2*residuals.var()*252).sum())
                    total=float(factor_risk.sum()+specific_risk)
                    risk_rows += [dict(date=day,asOfDate=previous_date,factor=k,varianceContribution=v,
                        moneyVarianceContribution=v*last_nav**2,totalVariance=total,share=v/total if total>0 else None,
                        marginalVolatility=(covariance@e)[i]/np.sqrt(total) if total>0 else None,
                        lookback=lookback,minObservations=minimum,observations=len(history))
                        for i,(k,v) in enumerate(zip(history.columns,factor_risk))]
                    risk_rows.append(dict(date=day,asOfDate=previous_date,factor='specific',varianceContribution=specific_risk,
                        moneyVarianceContribution=specific_risk*last_nav**2,totalVariance=total,share=specific_risk/total if total>0 else None))
            else:
                risk_coverage.append(dict(date=day,asOfDate=previous_date,lookback=lookback,minObservations=minimum,
                    status='missing_portfolio_exposure',annualizationDays=252))
            if modeled is None:
                # The account still reconciles when a statistical factor fit is unavailable.
                security_returns=after.rawReturn.reindex(weights.index)
                modeled=float((weights*security_returns).sum())*last_nav if security_returns.notna().all() else None
                pnl_rows.append(dict(date=day,factor='beginning_holdings_unmodeled',pnl=modeled,
                    returnContribution=modeled/last_nav if modeled is not None else None,kind='unmodeled'))
            today_trades=trades[pd.to_datetime(trades.date).eq(day)] if not trades.empty else trades
            trading=0.
            for trade in today_trades.to_dict('records'):
                close=after.rawClose.get(trade['symbol'],np.nan)
                trading+=(1 if trade['direction'] else -1)*trade['amount']*(close-trade['price'])
            fee_columns=['commission','stampDuty','transferFee']
            if not today_trades.empty and set(fee_columns).issubset(today_trades) and today_trades[fee_columns].notna().all(axis=None):
                fees=today_trades[fee_columns].sum()
                pnl_rows += [dict(date=day,factor=k,pnl=-v,returnContribution=-v/last_nav,kind='cost') for k,v in fees.items()]
                fee_residual=cost-float(fees.sum())
                if abs(fee_residual)>1e-8:pnl_rows.append(dict(date=day,factor='unclassified_fees',pnl=-fee_residual,returnContribution=-fee_residual/last_nav,kind='cost'))
            else:pnl_rows.append(dict(date=day,factor='fees',pnl=-cost,returnContribution=-cost/last_nav,kind='cost'))
            pnl_rows += [dict(date=day,factor='trading_adjustment',pnl=trading,returnContribution=trading/last_nav,kind='trading'),
                dict(date=day,factor='cash_and_event_residual',pnl=actual-modeled-trading+cost if modeled is not None else None,
                    returnContribution=(actual-modeled-trading+cost)/last_nav if modeled is not None else None,kind='reconciliation')]
            last_nav=float(report.loc[day,'account'])
            today_holdings=holdings[pd.to_datetime(holdings.date).eq(day)] if not holdings.empty else pd.DataFrame()
            prior_holdings=dict(zip(today_holdings.symbol,today_holdings.get('economicAmount',today_holdings.amount))) if not today_holdings.empty else {}
        factor_history.append(factors if fitted is not None else pd.Series(np.nan,index=exposure.columns))
        specific_history.append(specific if fitted is not None else pd.Series(np.nan,index=after.index))
    pnl=pd.DataFrame(pnl_rows)
    summary=pnl.groupby(['factor','kind']).pnl.agg(lambda x:x.sum(min_count=len(x))).reset_index() if len(pnl) else pd.DataFrame()
    if len(summary):
        initial_nav=report.account.iloc[0]/(1+report['return'].iloc[0]-report.cost.iloc[0])
        summary['linkedReturnContribution']=summary.pnl/initial_nav
        summary['linkMethod']='sum_daily_pnl_over_initial_nav; wealth_scaled_daily_contributions'
    return {'factor_returns':pd.DataFrame(returns_rows),'portfolio_factor_exposure':pd.DataFrame(exposure_rows),
            'factor_pnl_attribution':pnl,'factor_pnl_summary':summary,'factor_risk_attribution':pd.DataFrame(risk_rows),
            'factor_specific_returns':pd.DataFrame(specific_rows),'factor_risk_coverage':pd.DataFrame(risk_coverage),
            'relative_industry_attribution':pd.DataFrame(relative_rows),
            'relative_factor_risk':pd.DataFrame(active_risk_rows),'relative_factor_exposure':pd.DataFrame(active_exposure_rows),
            'relative_risk_coverage':pd.DataFrame(active_coverage),
            'attribution_coverage':pd.DataFrame(coverage)}
