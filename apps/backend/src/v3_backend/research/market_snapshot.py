"""Independent observed market snapshots; research samples never supply breadth."""
from pathlib import Path
from .storage_migration import resolve_location
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
from . import quotes, data
from .storage import now, read_json, write_json

_lock = RLock()
_pool = ThreadPoolExecutor(max_workers=4)
_pending = {}
SOURCES = {'stocks':('stock_zh_a_spot_em',{}),
           'indices':('stock_zh_index_spot_em',{'symbol':'沪深重要指数'}),
           'industries':('stock_board_industry_name_em',{}),
           'concepts':('stock_board_concept_name_em',{})}
ALTERNATIVES = {'stocks':('stock_zh_a_spot',{}), 'indices':('stock_zh_index_spot_sina',{}),
                'industries':('stock_sector_spot',{'indicator':'新浪行业'}), 'concepts':('stock_sector_spot',{'indicator':'概念'})}


def normalize(frame, kind, source='akshare/eastmoney'):
    import pandas as pd
    if frame.empty:raise ValueError('市场来源未返回记录，旧快照保留')
    if source=='akshare/sina' and kind in ('industries','concepts'):
        frame=frame.rename(columns={'label':'代码','板块':'名称','平均价格':'最新价','总成交额':'成交额','公司家数':'memberCount'}).copy()
        frame['代码']='SINA_'+frame['代码'].astype(str)
    frame=frame.rename(columns={'代码':'symbol','名称':'name','板块代码':'symbol','板块名称':'name',
        '最新价':'close','涨跌幅':'pctChange','成交额':'amount','成交量':'volume'}).copy()
    if not {'symbol','name','close','pctChange'}.issubset(frame):
        raise ValueError('市场来源字段不完整，旧快照保留')
    def code(value):
        value=str(value).upper()
        if kind=='indices':return value if value in quotes.INDEX_NAMES else next((k for k in quotes.INDEX_NAMES if k[2:]==value),None)
        try:return quotes.instrument({'kind':{'stocks':'stock','industries':'industry','concepts':'concept'}[kind], 'symbol':value})['symbol']
        except ValueError:return None
    frame['symbol']=frame.symbol.map(code);frame=frame[frame.symbol.notna()].copy()
    for field in ('close','pctChange','amount','volume'):
        frame[field]=pd.to_numeric(frame[field],errors='coerce') if field in frame else float('nan')
    frame['changeRatio']=frame.pctChange/100
    # AKShare Sina stock volume is shares; Sina index / Eastmoney stock volume is lots.
    if kind=='stocks':frame['volume']=frame.volume*(1 if source=='akshare/sina' else 100)
    elif kind=='indices' and source=='akshare/sina':frame['volume']=frame.volume*100
    else:frame['volume']=float('nan')
    frame['priceUnit']='元' if kind=='stocks' else '元（成分均价）' if source=='akshare/sina' and kind in ('industries','concepts') else '点'
    frame['amountUnit']='元';frame['volumeUnit']='股' if kind=='stocks' or kind=='indices' and source=='akshare/sina' else None
    frame['source']=source
    if '时间戳' in frame:frame['quoteTime']=frame['时间戳'].astype(str)
    if kind in ('industries','concepts'):
        frame['industry']=frame['name'];frame['meanChangeRatio']=frame['changeRatio']
        frame['turnoverAmount']=frame['amount']
    if frame.empty:raise ValueError('来源未返回支持的市场标的，旧快照保留')
    return frame


def _refresh(path,kind,function,arguments,allow_fallback=True):
    previous=read_json(path,{})
    providers=[('akshare/eastmoney',function,arguments)]
    if kind in ALTERNATIVES and allow_fallback:
        name,args=ALTERNATIVES[kind];providers.append(('akshare/sina',name,args))
    if previous.get('source')=='akshare/sina':providers.reverse()
    errors=[]
    for source,name,args in providers:
        try:
            frame=normalize(quotes._ak(name,**args),kind,source)
            break
        except (ValueError,OSError) as exc:errors.append(str(exc))
    else:raise ValueError('；'.join(errors))
    cached={'rows':data.records(frame),'updatedAt':now(),'asOfDate':None,'source':source,
            'sourceNotes':errors}
    write_json(path,cached)
    return cached


def _history_path(project, kind, symbol):
    item=quotes.instrument(dict(kind=kind,symbol=symbol))
    path=quotes._path(project,item)
    if not path.exists() and kind=='index':
        path=Path(data.project_data(project)['path'])/'data/benchmarks'/(symbol+'.parquet')
    return path


def _strength_calendar(project, cutoff):
    """Read a common local calendar; never infer sessions from each board's gaps."""
    import pandas as pd
    root=Path(data.project_data(project)['path'])/'data'
    calendar=read_json(root/'trading-calendar.json',{})
    dates=pd.to_datetime(calendar.get('dates',[]),errors='coerce')
    dates=sorted(set(d.normalize() for d in dates if pd.notna(d) and d<=cutoff))
    if dates:return dates,'本地交易日历'
    # The broad market index provides an explicitly observed reference calendar.
    path=_history_path(project,'index','SH000001')
    if path.exists():
        try:
            values=pd.to_datetime(pd.read_parquet(path,columns=['date']).date,errors='coerce')
            dates=sorted(set(d.normalize() for d in values if pd.notna(d) and d<=cutoff))
            if dates:return dates,'上证指数已缓存行情日期（非完整交易日历证明）'
        except (ValueError,OSError,KeyError):pass
    return [],'缺少本地交易日历或上证指数日期'


def strength(project, values, days):
    import math
    import pandas as pd
    if type(days) is not int or days not in (1,5,20):raise ValueError('市场强弱周期仅支持1、5或20个交易日')
    current=pd.Timestamp.now(tz='Asia/Shanghai')
    cutoff=current.tz_localize(None).normalize()
    if current.hour<15:cutoff-=pd.Timedelta(days=1)
    dates,calendar_source=_strength_calendar(project,cutoff) if days!=1 else ([], '来源实时快照')
    window=dates[-days-1:] if len(dates)>=days+1 else []
    asof=dates[-1].strftime('%Y-%m-%d') if dates else None
    total=covered=0
    for category,kind in [('indices','index'),('industries','industry'),('concepts','concept')]:
        for row in values[category]:
            total+=1
            row.update(strengthDays=days,strengthChangeRatio=None,strengthStartDate=None,strengthEndDate=asof,
                       strengthStatus='missing',strengthSource=None,strengthMessage='尚无来源历史曲线缓存，请在该标的走势中更新')
            if days==1:
                value=row.get('changeRatio')
                valid=isinstance(value,(int,float)) and math.isfinite(value)
                row.update(strengthChangeRatio=value if valid else None,strengthStatus='ready' if valid else 'missing',
                    strengthSource=row.get('source'),strengthMessage='来源当日涨跌幅；采集时间不代表行情日期')
                covered+=int(valid)
                continue
            if str(row['symbol']).startswith('SINA_'):
                row.update(strengthStatus='unsupported',strengthSource=row.get('source'),strengthMessage='新浪板块不提供对应历史指数曲线，不能用当前成员回拼')
                continue
            if not window:
                row.update(strengthStatus='partial',strengthMessage=f'共同日期不足{days+1}个，不能核验{days}交易日涨跌幅')
                continue
            row['strengthStartDate']=window[0].strftime('%Y-%m-%d')
            try:
                path=_history_path(project,kind,row['symbol'])
                if not path.exists():continue
                frame=pd.read_parquet(path,columns=['date','close'])
                frame['date']=pd.to_datetime(frame.date,errors='coerce').dt.normalize()
                frame=frame[frame.date.isin(window)]
                if frame.date.duplicated().any():raise ValueError('历史曲线同一日期重复，无法核验')
                prices=pd.to_numeric(frame.set_index('date').close,errors='coerce').reindex(window)
                valid=prices.map(lambda x:pd.notna(x) and math.isfinite(x) and x>0)
                stamp=read_json(path.with_suffix('.json'),{})
                row['strengthSource']=stamp.get('source','本地来源指数曲线（来源未注明）')
                if not valid.all():
                    row.update(strengthStatus='partial',strengthMessage=f'共同区间需要{days+1}个收盘价，缓存有效{int(valid.sum())}个；不跨缺失交易日计算')
                    continue
                row.update(strengthChangeRatio=float(prices.iloc[-1]/prices.iloc[0]-1),strengthStatus='ready',
                    strengthMessage='按来源指数曲线共同日期计算；仅反映所示缓存日期，未补取历史')
                covered+=1
            except (ValueError,OSError,KeyError) as exc:
                row.update(strengthStatus='partial',strengthMessage=str(exc))
    return dict(days=days,asOfDate=asof,calendarSource=calendar_source,covered=covered,total=total,
        message='当日强弱来自独立市场快照。' if days==1 else '按共同交易日期读取已缓存来源曲线；切换周期不下载。行业和概念存在重叠，涨幅及成交额不可相加为市场总量。')


def overview(project, params=None):
    import pandas as pd
    params=params or {}
    days=params.get('strengthDays',1)
    if type(days) is not int or days not in (1,5,20):raise ValueError('市场强弱周期仅支持1、5或20个交易日')
    root=resolve_location(Path(project['path'])/'market-snapshot')
    from .app_settings import source_settings
    sources=source_settings(project.get('settings',{}))
    values={};coverage=[];errors={};stamps=[]
    tasks={}
    for kind,(function,arguments) in SOURCES.items():
        path=root/(kind+'.json');cached=read_json(path,{})
        category='boards' if kind in {'industries','concepts'} else 'daily'
        if sources[category]=='file':continue
        if category=='daily' and sources['daily']!='akshare' and not sources['quoteFallback']:
            if params.get('refresh') or params.get('loadIfMissing') and not cached:errors[kind]='实时概况仅接入AKShare；当前关闭备用源，保留已有快照'
            continue
        if params.get('refresh') or params.get('loadIfMissing') and not cached:
            with _lock:
                key=(str(path.resolve()),sources[category],sources['quoteFallback'])
                task=_pending.get(key)
                if task is None or task.done():
                    task=_pool.submit(_refresh,path,kind,function,arguments,sources['quoteFallback'])
                    _pending[key]=task
                tasks[kind]=task
    for kind in SOURCES:
        path=root/(kind+'.json');cached=read_json(path,{})
        if kind in tasks:
            try:cached=tasks[kind].result()
            except (ValueError,OSError) as exc:errors[kind]=str(exc)
        values[kind]=cached.get('rows',[])
        if cached.get('updatedAt'):stamps.append(cached['updatedAt'])
        coverage.append(dict(dataset=kind,label={'stocks':'沪深A股快照','indices':'配置指数快照','industries':'行业板块快照','concepts':'概念板块快照'}[kind],
            source=cached.get('source','未获取'),rows=len(values[kind]),symbols=len(values[kind]),
            startDate=cached.get('asOfDate'),endDate=cached.get('asOfDate'),updatedAt=cached.get('updatedAt'),
            status='partial' if values[kind] else 'missing',estimated=False,
            message='来源当前快照，采集时间不等于行情日期；仅统计实际返回覆盖，不证明全市场完整。'+('；'.join(cached.get('sourceNotes',[])))))
    stocks=pd.DataFrame(values['stocks'])
    changes=pd.to_numeric(stocks.get('changeRatio',pd.Series(dtype=float)),errors='coerce').dropna()
    amount=pd.to_numeric(stocks.get('amount',pd.Series(dtype=float)),errors='coerce')
    summary=dict(observedStocks=len(stocks),changeCoveredStocks=len(changes),
        advances=int(changes.gt(0).sum()) if len(changes) else None,
        declines=int(changes.lt(0).sum()) if len(changes) else None,
        unchanged=int(changes.eq(0).sum()) if len(changes) else None,
        turnoverAmount=float(amount.sum(min_count=1)) if amount.notna().any() else None,
        fundNetAmount=None,fundCoveredStocks=0)
    period_strength=strength(project,values,days)
    actual_sources=list(dict.fromkeys(item['source'] for item in coverage if item['rows']))
    return dict(asOfDate=None,updatedAt=max(stamps) if stamps else None,source='、'.join(actual_sources) or '未获取',
        stale=bool(errors or any(stamp[:10]!=now()[:10] for stamp in stamps)),
        status='source_error' if errors else 'ready' if stamps else 'missing',errors=errors,
        summary=summary,strength=period_strength,indices=values['indices'],industries=values['industries'],concepts=values['concepts'],
        breadth=[dict(name=label,count=int(((changes>low)&(changes<=high)&changes.ne(0)).sum()) if len(changes) else None)
                 for label,low,high in [('跌超5%',-float('inf'),-.05),('跌幅0至5%',-.05,0),('涨幅0至5%',0,.05),('涨超5%',.05,float('inf'))]],
        coverage=coverage)
