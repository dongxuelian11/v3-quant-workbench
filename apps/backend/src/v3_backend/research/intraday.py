"""Display-only minute quotes, isolated from daily research data."""
from pathlib import Path
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
import math,time
from . import quotes, data
from .storage import read_json, write_json, now, identifier

PERIODS=['intraday','1m','5m','15m','30m','60m']
_pool=ThreadPoolExecutor(max_workers=8)
_lock=RLock();_pending={};_completed={}


def normalize(frame,item,period,clock=None,source='akshare/eastmoney',volume_multiplier=100):
    import pandas as pd
    import numpy as np
    frame=frame.rename(columns={'day':'date','时间':'date','日期':'date','开盘':'open','最高':'high','最低':'low','收盘':'close','成交量':'volume','成交额':'amount','均价':'averagePrice'}).copy()
    if frame.empty or not {'date','close'}.issubset(frame):raise ValueError('来源未返回分钟数据，已有缓存保留')
    dates=pd.to_datetime(frame.date,errors='raise')
    dates=dates.dt.tz_localize('Asia/Shanghai') if dates.dt.tz is None else dates.dt.tz_convert('Asia/Shanghai')
    current=pd.Timestamp(clock) if clock is not None else pd.Timestamp.now(tz='Asia/Shanghai')
    if current.tzinfo is None:current=current.tz_localize('Asia/Shanghai')
    frame['timestamp']=dates.map(lambda d:d.value//1_000_000)
    frame['date']=dates.map(lambda x:x.isoformat())
    for key in ('open','high','low','close','volume','amount','averagePrice'):
        frame[key]=pd.to_numeric(frame[key],errors='coerce') if key in frame else np.nan
    for key in ('open','high','low','close','averagePrice'):frame[key]=frame[key].where(frame[key]>0)
    frame=frame[frame.close.notna()].copy()
    if frame.empty:raise ValueError('来源分钟价格无效，已有缓存保留')
    frame['volume']*=volume_multiplier
    frame['complete']=dates.loc[frame.index]<current.floor('min')
    frame['source']=source;frame['previousClose']=np.nan
    return frame.sort_values('timestamp').drop_duplicates('timestamp',keep='last')


def fetch(item,period,params):
    minutes='1' if period=='intraday' else period[:-1]
    args={'symbol':item['symbol'][2:] if item['kind'] in {'stock','index'} else item['symbol'],'period':minutes}
    if item['kind']=='stock':function='stock_zh_a_hist_min_em';args['adjust']=''
    elif item['kind']=='index':function='index_zh_a_hist_min_em'
    else:function='stock_board_'+item['kind']+'_hist_min_em'
    if item['kind'] in {'stock','index'}:
        for field,target in [('startDate','start_date'),('endDate','end_date')]:
            if params.get(field):args[target]=str(params[field]).replace('T',' ')[:19]+(' 00:00:00' if field=='startDate' else ' 23:59:59') if len(str(params[field]))==10 else str(params[field]).replace('T',' ')[:19]
    if item['kind'] in {'stock','index'} and params.get('_preferredSource')=='akshare/sina' and params.get('_quoteFallback',True):
        return normalize(quotes._ak('stock_zh_a_minute',_timeout=45,symbol=item['symbol'].lower(),period=minutes,adjust=''),item,period,source='akshare/sina',volume_multiplier=1)
    try:return normalize(quotes._ak(function,_timeout=45,**args),item,period)
    except (ValueError,OSError) as primary:
        if item['kind'] not in {'stock','index'} or not params.get('_quoteFallback',True):raise
        try:return normalize(quotes._ak('stock_zh_a_minute',_timeout=45,symbol=item['symbol'].lower(),period=minutes,adjust=''),item,period,source='akshare/sina',volume_multiplier=1)
        except (ValueError,OSError) as secondary:raise ValueError(str(primary)+'；新浪备用源：'+str(secondary)) from None


def session_average(frame,item,period):
    """Only fill stock VWAP from complete, unit-normalized one-minute prefixes."""
    import pandas as pd
    import numpy as np
    frame=frame.copy()
    if 'averagePrice' not in frame:frame['averagePrice']=np.nan
    prices=pd.to_numeric(frame.averagePrice,errors='coerce')
    valid=prices.gt(0)&np.isfinite(prices)
    frame.loc[~valid,'averagePrice']=np.nan
    frame['averagePriceSource']=np.where(valid,'provider','unavailable')
    frame['averagePriceMessage']=np.where(valid,'来源当日均价','缺少来源均价；未以价格简单平均替代')
    if item['kind']!='stock' or period not in ('intraday','1m'):return frame
    for day,index in frame.groupby(frame.date.str[:10],sort=False).groups.items():
        part=frame.loc[index].sort_values('timestamp')
        times=pd.to_datetime(part.date,utc=True).dt.tz_convert('Asia/Shanghai')
        observed=set(times.dt.strftime('%H:%M'))
        expected=list(pd.date_range(day+' 09:31',day+' 11:30',freq='min').strftime('%H:%M'))+list(pd.date_range(day+' 13:01',day+' 15:00',freq='min').strftime('%H:%M'))
        volume=amount=0.;usable=True
        for ix,stamp in zip(part.index,times):
            row=frame.loc[ix];clock=stamp.strftime('%H:%M')
            prefix=[t for t in expected if t<=clock]
            if clock not in expected+['09:30','13:00'] or not set(prefix).issubset(observed):usable=False
            if row.get('source') not in ('akshare/eastmoney','akshare/sina'):usable=False
            v=row.get('volume');a=row.get('amount')
            if not pd.notna(v) or not pd.notna(a) or not np.isfinite(v) or not np.isfinite(a) or v<0 or a<0 or (v>0 and a<=0) or (v==0 and a>0):usable=False
            if usable:
                volume+=v;amount+=a
                if volume>0 and not valid.loc[ix]:
                    frame.loc[ix,['averagePrice','averagePriceSource','averagePriceMessage']]=[amount/volume,'session_vwap','自开盘完整一分钟成交额（元）/成交量（股）累计']
            elif not valid.loc[ix]:frame.loc[ix,'averagePriceMessage']='缺少开盘至当前的完整一分钟量额或明确单位，当日均价不可得'
    return frame


def _refresh(path,item,period,params,key):
    import pandas as pd
    error=None
    try:
        incoming=fetch(item,period,params)
        with _lock:
            old=pd.read_parquet(path) if path.exists() else incoming.iloc[:0]
            merged=pd.concat([old,incoming],ignore_index=True).drop_duplicates('timestamp',keep='last').sort_values('timestamp')
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_name(path.stem+'.'+identifier()+'.tmp.parquet');merged.to_parquet(temporary,index=False);temporary.replace(path)
            write_json(path.with_suffix('.json'),{'updatedAt':now(),'source':incoming.source.iloc[-1]})
    except (ValueError,OSError) as exc:
        error=str(exc);raise
    finally:
        with _lock:_completed[key]={'at':time.monotonic(),'error':error}


def read(project,params):
    import pandas as pd
    from .app_settings import source_settings
    sources=source_settings(project.get('settings',{}))
    params={**params,'_quoteFallback':sources['quoteFallback']}
    item=quotes.instrument(params['instrument']);period=params.get('period','intraday')
    if period not in PERIODS:raise ValueError('不支持的分钟周期')
    if item['symbol']=='TDX880823':
        return dict(instrument=item,period=period,timezone='Asia/Shanghai',availablePeriods=[],bars=[],hasMore=False,status='unsupported',
            coverage=dict(startDate=None,endDate=None,rows=0,updatedAt=None,source='tdx',priceUnit='点',volumeUnit='来源原始单位',amountUnit='未知'),
            message='通达信微盘股当前接入日线；该来源的分钟行情尚未接入。')
    if item['kind'] in {'industry','concept'} and item['symbol'].startswith('SINA_'):
        return dict(instrument=item,period=period,timezone='Asia/Shanghai',availablePeriods=[],bars=[],hasMore=False,status='unsupported',
            coverage=dict(startDate=None,endDate=None,rows=0,updatedAt=None,source='akshare/sina',priceUnit='来源原始单位',volumeUnit='未知',amountUnit='未知'),
            message='新浪板块当前只提供快照和成分，暂无分钟曲线。')
    canonical='1m' if period=='intraday' else period
    path=Path(project['path'])/'minutes'/item['kind']/item['symbol']/(canonical+'.parquet')
    error=None
    current=pd.Timestamp.now(tz='Asia/Shanghai');today=current.strftime('%Y-%m-%d')
    calendar=read_json(Path(data.project_data(project)['path'])/'data/trading-calendar.json',{})
    known=calendar.get('start','9999')<=today<=calendar.get('end','')
    closed=today not in calendar.get('dates',[]) if known else current.weekday()>=5
    checked=read_json(path.with_suffix('.json'),{}).get('updatedAt','')[:10]==now()[:10]
    skip_auto=bool(params.get('autoRefresh') and path.exists() and closed and checked)
    if params.get('refresh') and not skip_auto and sources['intraday']!='file' and (item['kind'] not in {'industry','concept'} or sources['boards']!='file'):
        interval=float(params.get('refreshIntervalSeconds',60))
        if not math.isfinite(interval) or interval<=0:raise ValueError('刷新间隔必须是正数秒')
        key=(str(path.resolve()),params.get('startDate'),params.get('endDate'))
        with _lock:
            future=_pending.get(key)
            completed=_completed.get(key)
            recent=bool(params.get('autoRefresh') and completed and time.monotonic()-completed['at']<interval)
            if recent and (future is None or future.done()):
                future=None;error=completed['error']
            elif future is None or future.done():
                preferred=read_json(path.with_suffix('.json'),{}).get('source')
                future=_pool.submit(_refresh,path,item,canonical,{**params,'_preferredSource':preferred},key);_pending[key]=future
        if future is not None:
            try:future.result()
            except (ValueError,OSError) as exc:error=str(exc)
    frame=pd.read_parquet(path) if path.exists() else pd.DataFrame()
    stamp=read_json(path.with_suffix('.json'),{})
    if len(frame):
        frame=session_average(frame,item,period)
        daily=quotes.read(project,item)
        if not daily.empty and 'rawClose' in daily:
            prior=daily[['date','rawClose']].copy()
            prior['day']=pd.to_datetime(prior.date).dt.normalize()
            prior=prior[prior.rawClose.gt(0)].sort_values('day').drop_duplicates('day',keep='last')
            if not prior.empty:
                days=pd.DataFrame({'day':pd.to_datetime(frame.date.str[:10].unique())}).sort_values('day')
                sessions=calendar.get('dates',[])
                previous_days={sessions[i]:sessions[i-1] for i in range(1,len(sessions))}
                prior['previousDay']=prior.day.dt.strftime('%Y-%m-%d')
                matched=pd.merge_asof(days,prior[['day','rawClose','previousDay']],on='day',allow_exact_matches=False)
                prices={str(row.day)[:10]:row.rawClose for row in matched.itertuples()
                        if previous_days.get(str(row.day)[:10])==row.previousDay}
                if 'rawPreclose' in daily:
                    prices.update({str(pd.Timestamp(row.date))[:10]:row.rawPreclose for row in daily.itertuples() if pd.notna(row.rawPreclose) and row.rawPreclose>0})
                frame['previousClose']=frame.date.str[:10].map(prices)
        for field,operation in [('startDate','ge'),('endDate','le')]:
            if params.get(field):
                boundary=pd.Timestamp(params[field]);boundary=boundary.tz_localize('Asia/Shanghai') if boundary.tzinfo is None else boundary.tz_convert('Asia/Shanghai')
                if field=='endDate' and len(str(params[field]))==10:boundary+=pd.Timedelta(days=1)-pd.Timedelta(milliseconds=1)
                frame=frame[getattr(frame.timestamp,operation)(boundary.value//1_000_000)]
        if period=='intraday' and len(frame):frame=frame[frame.date.str[:10].eq(frame.date.str[:10].max())]
        if params.get('beforeDate'):
            boundary=pd.Timestamp(params['beforeDate'])
            boundary=boundary.tz_localize('Asia/Shanghai') if boundary.tzinfo is None else boundary.tz_convert('Asia/Shanghai')
            frame=frame[frame.timestamp.lt(boundary.value//1_000_000)]
    available=[p for p in PERIODS if (path.parent/('1m' if p=='intraday' else p)).with_suffix('.parquet').exists()]
    limit=max(1,min(5000,int(params.get('limit',5000))))
    rows=data.records(frame.tail(limit)) if len(frame) else []
    return dict(instrument=item,period=period,timezone='Asia/Shanghai',availablePeriods=available,bars=rows,hasMore=len(frame)>limit,
        status='source_error' if error else 'ready' if rows else 'missing',
        coverage=dict(startDate=rows[0]['date'] if rows else None,endDate=rows[-1]['date'] if rows else None,rows=len(frame),updatedAt=stamp.get('updatedAt'),
            source=stamp.get('source','未获取'),priceUnit='元' if item['kind']=='stock' else '点',volumeUnit='来源原始单位' if item['kind']=='index' and stamp.get('source')=='akshare/sina' else '股',amountUnit='元'),
        message=error or ('分钟仅用于看盘；来源通常仅覆盖近期，未完成分钟不代表已收盘。' if rows else '此周期暂无本地分钟数据，请刷新；免费源可能不提供所选区间。'))
