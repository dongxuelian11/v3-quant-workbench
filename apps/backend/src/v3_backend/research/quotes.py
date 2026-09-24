"""On-demand quote cache, separate from research datasets and historical membership."""
from pathlib import Path
from .storage_migration import resolve_location
from datetime import datetime
import json,re,subprocess,sys,tempfile
import time,math
from concurrent.futures import Future
from threading import RLock
from .storage import now,read_json,write_json,identifier
from . import data
from .app_settings import source_settings

INDEX_NAMES={'SH000001':'上证指数','SZ399001':'深证成指','SZ399006':'创业板指','SH000688':'科创50',
             'SH000016':'上证50','SH000300':'沪深300','SH000905':'中证500','SH000852':'中证1000'}
KINDS={'stock','index','industry','concept'}
_bs_lock=RLock()
_quote_lock=RLock();_quote_pending={};_quote_completed={};_quote_writers={}


def instrument(value):
    if not isinstance(value,dict) or value.get('kind') not in KINDS:raise ValueError('请选择明确类型的行情标的')
    kind=value['kind'];code=str(value.get('symbol','')).strip().upper().replace('.','')
    if kind=='stock':
        code=data.symbol(code)
        if not code.startswith(('SH60','SH68','SZ00','SZ30')):raise ValueError('当前行情仅支持沪深A股，不支持北交所或其他证券类型')
    elif kind=='index':
        if code not in INDEX_NAMES and code!='TDX880823':raise ValueError('请选择目录中的指数')
    elif not re.fullmatch(r'BK\d{4,6}|SINA_(?:NEW|GN)_[A-Z0-9_]+',code):raise ValueError('请选择板块目录中的明确代码')
    result=dict(kind=kind,symbol=code,**{k:str(value[k]) for k in ('name','source') if value.get(k)})
    if code=='TDX880823':result.update(name='通达信微盘股',source='tdx')
    return result


def _root(project):return resolve_location(Path(project['path'])/'quotes')
def _path(project,item):return _root(project)/item['kind']/(item['symbol']+'.parquet')


def _ak(name,_timeout=90,**kwargs):
    """Bound the installed upstream call in a disposable process, not a retry loop."""
    import pandas as pd
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'result.parquet'
        script='import akshare,json,sys; frame=getattr(akshare,sys.argv[1])(**json.loads(sys.argv[2])); frame.to_parquet(sys.argv[3],index=False)'
        try:
            # This child takes arguments only; never inherit the live RPC stdin
            # pipe (Windows can stall even before the child Python script starts).
            done=subprocess.run([sys.executable,'-c',script,name,json.dumps(kwargs),str(path)],stdin=subprocess.DEVNULL,capture_output=True,text=True,
                encoding='utf-8',errors='replace',timeout=_timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired:raise ValueError(f'AKShare来源{_timeout}秒内未完成，保留已有缓存，请稍后手动重试') from None
        if done.returncode or not path.is_file():
            reason='来源连接被中断' if any(term in done.stderr for term in ('ConnectionError','RemoteDisconnected')) else '来源未返回可用数据'
            raise ValueError('AKShare '+name+' '+reason+'，已有缓存保留，请稍后手动刷新')
        return pd.read_parquet(path)


def _baostock(operation):
    import baostock as bs
    from contextlib import redirect_stdout
    from .baostock_connection import bounded_connection
    with _bs_lock,redirect_stdout(sys.stderr),bounded_connection():
        login=bs.login()
        if login.error_code!='0':raise ValueError('BaoStock登录失败: '+login.error_msg)
        try:return operation(bs)
        finally:bs.logout()


def catalog(project,params):
    sources=source_settings(project.get('settings',{}))
    kind=params.get('kind')
    if kind is not None and kind not in KINDS:raise ValueError('行情目录类型无效')
    kinds=[kind] if kind else ['stock','index','industry','concept']
    items=[];stamps=[];missing=[];errors={}
    for key in kinds:
        if key=='index':
            items.extend(dict(kind=key,symbol=code,name=name,source='configured') for code,name in INDEX_NAMES.items())
            items.append(instrument({'kind':'index','symbol':'TDX880823'}));continue
        path=_root(project)/('catalog-'+key+'.json');cached=read_json(path,{})
        if not cached:
            snapshot=read_json(resolve_location(Path(project['path'])/'market-snapshot')/({'stock':'stocks','industry':'industries','concept':'concepts'}[key]+'.json'),{})
            rows=[]
            for row in snapshot.get('rows',[]):
                try:rows.append(instrument(dict(kind=key,symbol=row['symbol'],name=row.get('name',''),source=row.get('source',snapshot.get('source','')))))
                except (ValueError,KeyError):continue
            if rows:
                cached={'items':rows,'updatedAt':snapshot.get('updatedAt'),'sourceNotes':['目录来自已取得的市场快照，仅包含来源实际返回标的。']}
                write_json(path,cached)
        if key=='stock' and not cached:
            import pandas as pd
            local=Path(data.project_data(project)['path'])/'data/securities.parquet'
            if local.exists():
                known=pd.read_parquet(local)
                if 'effectiveDate' in known:known=known.sort_values('effectiveDate')
                known=known.drop_duplicates('symbol',keep='last')
                cached={'items':[dict(kind='stock',symbol=r['symbol'],name=r.get('name',r.get('code_name','')),source='local/securities') for r in known.to_dict('records')],
                        'updatedAt':datetime.fromtimestamp(local.stat().st_mtime).astimezone().isoformat()}
        category='daily' if key=='stock' else 'boards'
        if sources[category]!='file' and (params.get('refresh') or params.get('loadIfMissing') and not cached):
            try:
                if key=='stock':
                    if sources['daily']=='akshare':
                        frame=_ak('stock_zh_a_spot_em').rename(columns={'代码':'code','名称':'code_name'})
                    else:
                        frame=_baostock(lambda bs:data._bs_query(bs,bs.query_stock_basic))
                        frame=frame[frame.type.eq('1') & frame.status.eq('1')]
                    rows=[]
                    for r in frame.to_dict('records'):
                        try:rows.append(instrument(dict(kind=key,symbol=r['code'],name=r['code_name'],source=sources['daily'])))
                        except ValueError:continue
                else:
                    rows,source_notes=board_catalog(key,prefer_sina=sources['quoteFallback'] and any(r.get('source')=='akshare/sina' for r in cached.get('items',[])),allow_fallback=sources['quoteFallback'])
                if not rows:raise ValueError('来源未返回目录，旧目录保留')
                cached={'items':rows,'updatedAt':now(), 'sourceNotes':source_notes if key!='stock' else []};write_json(path,cached)
            except (ValueError,OSError) as exc:
                errors[key]=str(exc)
        items.extend(cached.get('items',[]))
        if cached.get('updatedAt'):stamps.append(cached['updatedAt'])
        else:missing.append(key)
    query=str(params.get('query','')).casefold()
    if query:
        from pypinyin import lazy_pinyin,Style
        items=[item for item in items if query in (' '.join([item['symbol'],item.get('name',''),''.join(lazy_pinyin(item.get('name',''))),''.join(lazy_pinyin(item.get('name',''),style=Style.FIRST_LETTER))])).casefold()]
    offset=max(0,int(params.get('offset',0)));limit=max(1,min(1000,int(params.get('limit',200))))
    return dict(items=items[offset:offset+limit],total=len(items),updatedAt=max(stamps) if stamps else None,
        needsRefresh=bool(missing),source='本地目录',status='source_error' if errors else 'missing' if missing else 'ready' if items else 'empty',
        errors=errors,missingKinds=missing,stale=bool(errors and stamps),
        message='；'.join(errors.values()) if errors else '缺少目录，请刷新：'+','.join(missing) if missing else '没有匹配的标的' if not items else '')


def board_catalog(kind,prefer_sina=False,allow_fallback=True):
    """Keep provider sector identities separate: Sina groups are not Eastmoney indices."""
    providers=(['sina','eastmoney'] if prefer_sina else ['eastmoney','sina']) if allow_fallback else ['eastmoney'];notes=[]
    for provider in providers:
        try:
            if provider=='eastmoney':
                frame=_ak('stock_board_'+kind+'_name_em')
                rows=[instrument(dict(kind=kind,symbol=r['板块代码'],name=r['板块名称'],source='akshare/eastmoney')) for r in frame.to_dict('records')]
            else:
                frame=_ak('stock_sector_spot',indicator='新浪行业' if kind=='industry' else '概念')
                rows=[instrument(dict(kind=kind,symbol='SINA_'+r['label'],name=r['板块'],source='akshare/sina')) for r in frame.to_dict('records')]
            if not rows:raise ValueError('来源未返回板块目录')
            return rows,notes
        except (ValueError,OSError) as exc:notes.append(str(exc))
    raise ValueError('；'.join(notes))


def read(project,item):
    import pandas as pd
    path=_path(project,item)
    if path.exists():return pd.read_parquet(path)
    if item['kind']=='stock':
        from .charts import prices
        return prices(project,item['symbol'])
    if item['kind']=='index':
        legacy=Path(data.project_data(project)['path'])/'data/benchmarks'/(item['symbol']+'.parquet')
        if legacy.exists():
            frame=pd.read_parquet(legacy)
            for key in ('open','high','low','close'):frame['raw'+key.title()]=frame[key]
            frame['factor']=1.
            return frame
    return pd.DataFrame(columns=['date','open','high','low','close','volume','amount','factor','rawOpen','rawHigh','rawLow','rawClose'])


def _normalize(frame,item,source):
    import numpy as np
    import pandas as pd
    frame=frame.rename(columns={'日期':'date','开盘':'open','最高':'high','最低':'low','收盘':'close','成交量':'volume','成交额':'amount'}).copy()
    if frame.empty:raise ValueError('来源未返回该标的区间行情，保留原缓存')
    frame['date']=pd.to_datetime(frame.date,errors='raise').dt.normalize()
    for key in ('open','high','low','close','volume','amount'):
        frame[key]=pd.to_numeric(frame[key],errors='coerce') if key in frame else np.nan
    if frame[['open','high','low','close']].isna().any(axis=None):raise ValueError('来源OHLC不完整，保留原缓存')
    if not np.isfinite(frame[['open','high','low','close']]).all(axis=None) or frame[['open','high','low','close']].le(0).any(axis=None):
        raise ValueError('来源价格无效，保留原缓存')
    if source.startswith('akshare'):frame['volume']*=100  # Eastmoney daily kline volume is lots.
    for key in ('open','high','low','close'):
        raw='raw'+key.title()
        if raw not in frame:frame[raw]=frame[key]
    if 'factor' not in frame:frame['factor']=1.
    frame['symbol']=item['symbol']
    return frame.sort_values('date').drop_duplicates('date',keep='last')


def _fetch(item,start,end):
    import pandas as pd
    sources=source_settings({'dataSources':item.get('_dataSources',{})})
    category='microcap' if item['symbol']=='TDX880823' else 'boards' if item['kind'] in {'industry','concept'} else 'daily'
    if sources[category]=='file':raise ValueError('当前类别仅使用已有或导入数据，不自动联网')
    if item['symbol']=='TDX880823':
        from .tdx_quotes import read_source
        frame,source=read_source(start,end)
        frame=_normalize(frame,item,source)
        return frame[frame.date.between(start,end)],source,None
    if item['kind'] in {'industry','concept'}:
        if item['symbol'].startswith('SINA_'):raise ValueError('新浪板块未提供该板块历史曲线，不以当前成员合成历史指数')
        frame=_ak('stock_board_'+item['kind']+'_hist_em',symbol=item['symbol'],start_date=start.replace('-',''),end_date=end.replace('-',''),
            period='日k' if item['kind']=='industry' else 'daily',adjust='')
        return _normalize(frame,item,'akshare/eastmoney'),'akshare/eastmoney',None
    primary=sources['daily'];providers=[primary]
    if sources['quoteFallback']:providers.append('akshare' if primary=='baostock' else 'baostock')
    errors=[]
    for provider in providers:
        try:
            source=provider
            if provider=='baostock':
                remote=item['symbol'][:2].lower()+'.'+item['symbol'][2:]
                if item['kind']=='stock':frame=_baostock(lambda bs:data._bs_prices(bs,remote,start,end))
                else:frame=_baostock(lambda bs:data._bs_query(bs,bs.query_history_k_data_plus,remote,'date,code,open,high,low,close,volume,amount',start_date=start,end_date=end,frequency='d',adjustflag='3'))
            else:
                source='akshare/eastmoney'
                if item['kind']=='index':
                    try:frame=_ak('index_zh_a_hist',symbol=item['symbol'][2:],start_date=start.replace('-',''),end_date=end.replace('-',''),period='daily')
                    except ValueError:
                        if not sources['quoteFallback']:raise
                        frame=_ak('stock_zh_index_daily_tx',symbol=item['symbol'].lower(),start_date=start.replace('-',''),end_date=end.replace('-',''))
                        frame=frame.rename(columns={'amount':'volume'});frame['amount']=float('nan');source='akshare/tencent'
                else:frame=_ak('stock_zh_a_hist',symbol=item['symbol'][2:],start_date=start.replace('-',''),end_date=end.replace('-',''),period='daily',adjust='')
            frame=_normalize(frame,item,source)
            if provider=='baostock' and item['kind']=='index' and (frame.date.min()>pd.Timestamp(start)+pd.Timedelta(days=7) or frame.date.max()<pd.Timestamp(end)-pd.Timedelta(days=7)):
                raise ValueError('BaoStock指数区间覆盖不足')
            return frame[frame.date.between(start,end)],source,'；'.join(errors) or None
        except (ValueError,OSError) as exc:errors.append(str(exc))
    raise ValueError('；'.join(errors))


def update(project,params,progress):
    key=str(_path(project,instrument(params.get('instrument'))).resolve())
    with _quote_lock:writer=_quote_writers.setdefault(key,RLock())
    with writer:return _update(project,params,progress)


def import_quote(project,params):
    item=instrument(params.get('instrument'))
    if item['symbol']!='TDX880823':raise ValueError('此导入入口只接受通达信微盘股880823')
    if bool(params.get('filePath'))==bool(params.get('tdxDirectory')):raise ValueError('请选择一个文件或一个通达信目录')
    from .tdx_quotes import read_source
    frame,source=read_source(tdx_directory=params.get('tdxDirectory'),file_path=params.get('filePath'))
    frame=_normalize(frame,item,source)
    path=_path(project,item);key=str(path.resolve())
    with _quote_lock:writer=_quote_writers.setdefault(key,RLock())
    with writer:
        import pandas as pd
        old=read(project,item)
        merged=(frame if old.empty else pd.concat([old,frame],ignore_index=True)).drop_duplicates('date',keep='last').sort_values('date')
        path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.stem+'.'+identifier()+'.tmp.parquet')
        merged.to_parquet(temp,index=False);temp.replace(path)
        write_json(path.with_suffix('.json'),{'updatedAt':now(),'source':source,'warning':'本机导入数据；不表示在线行情已连接'})
    return status(project,{'instrument':item})


def _update(project,params,progress):
    import pandas as pd
    item=instrument(params.get('instrument'));path=_path(project,item);old=read(project,item)
    sources=source_settings(project.get('settings',{}))
    category='microcap' if item['symbol']=='TDX880823' else 'boards' if item['kind'] in {'industry','concept'} else 'daily'
    if sources[category]=='file':
        progress(1,'仅使用已有或导入行情，未联网')
        return status(project,{'instrument':item})
    start=str(params.get('startDate') or (pd.Timestamp.now()-pd.DateOffset(years=1)).date())[:10]
    end=str(params.get('endDate') or pd.Timestamp.now().date())[:10]
    if pd.Timestamp(start)>pd.Timestamp(end):raise ValueError('行情开始日期晚于结束日期')
    stamp=read_json(path.with_suffix('.json'),{})
    if not params.get('_forceRefresh') and stamp.get('requestedStart','9999')<=start and stamp.get('requestedEnd','')>=end and stamp.get('updatedAt','')[:10]==now()[:10]:
        progress(1,'该标的所选区间今天已更新');return status(project,{'instrument':item})
    intervals=[]
    if old.empty:intervals=[(start,end)]
    else:
        old=old.copy();old['date']=pd.to_datetime(old.date)
        first=str(old.date.min().date());last=str(old.date.max().date())
        if start<first:intervals.append((start,first if item['kind']=='stock' else min(end,first)))
        if end>last:intervals.append((last if item['kind']=='stock' else max(start,last),end))
        if not intervals and end>=str(pd.Timestamp.now().date()):intervals=[(max(start,last),end)]
        if not intervals and params.get('_forceRefresh'):intervals=[(start,end)]
    progress(.1,'正在补取 '+item.get('name',item['symbol'])+' 缺失区间，仅此标的')
    frame=old;source=stamp.get('source','本地已有行情');warning=stamp.get('warning')
    for left,right in intervals:
        incoming,source,warning=_fetch({**item,'_dataSources':source_settings(project.get('settings',{}))},left,right)
        if incoming.empty:continue
        if item['kind']=='stock' and not frame.empty:
            if source=='akshare/eastmoney':
                # This fallback is unadjusted; preserve actual historical raw quotes.
                for key in ('open','high','low','close'):frame[key]=frame['raw'+key.title()]
                frame['factor']=1.;warning='AKShare来源为未复权行情，已保留原始价格。'
            else:
                overlap=frame.set_index('date').join(incoming.set_index('date')[['close']],rsuffix='_new',how='inner')
                if len(overlap):
                    ratio=float(overlap.close_new.iloc[-1]/overlap.close.iloc[-1])
                    for key in ('open','high','low','close','factor'):frame[key]*=ratio
                elif len(frame):raise ValueError('股票增量缺复权基准重叠日，原缓存保留，请补齐衔接日期')
        frame=(incoming.copy() if frame.empty else pd.concat([frame,incoming],ignore_index=True)).drop_duplicates('date',keep='last').sort_values('date')
    if frame.empty:raise ValueError('此区间无来源行情，原缓存保留')
    progress(.85,'正在保存该标的真实日线')
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.stem+'.'+identifier()+'.tmp.parquet')
    frame.to_parquet(temp,index=False);temp.replace(path)
    write_json(path.with_suffix('.json'),dict(updatedAt=now(),source=source,requestedStart=min(start,str(frame.date.min().date())),requestedEnd=max(end,str(frame.date.max().date())),warning=warning))
    progress(1,'单标的行情更新完成')
    return status(project,{'instrument':item})


def bars(project,params):
    from .charts import bars_from_frame,with_calendar
    import pandas as pd
    if params.get('period')=='daily':params={**params,'period':'day'}
    frame=read(project,instrument(params['instrument']))
    result=bars_from_frame(frame,with_calendar(project,params,frame))
    current=pd.Timestamp.now(tz='Asia/Shanghai');today=current.tz_localize(None).normalize()
    for bar in result:
        day=pd.Timestamp(bar['date']).tz_localize(None).normalize()
        complete=day<today or day==today and current.hour>=15
        if params.get('period') in {'week','month'}:
            last=day.to_period('W-FRI' if params['period']=='week' else 'M').end_time.normalize()
            complete=complete and (last<today or last==today and current.hour>=15)
        bar['complete']=bool(complete and bar.get('complete',True))
    return result


def _refresh_quote(project,item,params):
    """Share the caller's read worker; no Jobs or additional queue."""
    path=_path(project,item);key=(str(path.resolve()),params.get('startDate'),params.get('endDate'))
    interval=float(params.get('refreshIntervalSeconds',60))
    if not math.isfinite(interval) or interval<=0:raise ValueError('刷新间隔必须为正数秒')
    with _quote_lock:
        future=_quote_pending.get(key);completed=_quote_completed.get(key)
        if future is not None and not future.done():owner=False
        elif params.get('autoRefresh') and completed and time.monotonic()-completed['at']<interval:return completed['error']
        else:future=Future();_quote_pending[key]=future;owner=True
    if owner:
        error=None
        try:update(project,{**params,'instrument':item,'_forceRefresh':True},lambda *_:None)
        except Exception as exc:error=str(exc)
        finally:
            with _quote_lock:_quote_completed[key]={'at':time.monotonic(),'error':error}
            future.set_result(error)
    return future.result()


def status(project,params):
    import pandas as pd
    sources=source_settings(project.get('settings',{}))
    item=instrument(params['instrument']);path=_path(project,item);error=None
    unsupported=item['symbol'].startswith('SINA_')
    category='microcap' if item['symbol']=='TDX880823' else 'boards' if item['kind'] in {'industry','concept'} else 'daily'
    if params.get('refresh') and not unsupported and sources[category]!='file':
        current=pd.Timestamp.now(tz='Asia/Shanghai');today=current.strftime('%Y-%m-%d')
        calendar=read_json(Path(data.project_data(project)['path'])/'data/trading-calendar.json',{})
        known=calendar.get('start','9999')<=today<=calendar.get('end','')
        closed=today not in calendar.get('dates',[]) if known else current.weekday()>=5
        checked=read_json(path.with_suffix('.json'),{}).get('updatedAt','')[:10]==now()[:10]
        if not (params.get('autoRefresh') and path.exists() and closed and checked):error=_refresh_quote(project,item,params)
    frame=read(project,item);stamp=read_json(path.with_suffix('.json'),{})
    return dict(instrument=item,period=params.get('period','day'),tradingDays=params.get('tradingDays'),anchorDate='2015-01-05' if params.get('period')=='trading_days' else None,bars=bars(project,params),status='unsupported' if unsupported else 'source_error' if error else 'ready' if len(frame) else 'missing',historyAvailable=not unsupported,coverage=dict(startDate=str(pd.to_datetime(frame.date).min().date()) if len(frame) else None,
        endDate=str(pd.to_datetime(frame.date).max().date()) if len(frame) else None,rows=len(frame),updatedAt=stamp.get('updatedAt'),
        source=stamp.get('source','本地已有行情' if len(frame) else '未下载'),priceUnit='元' if item['kind']=='stock' else '点',
        volumeUnit='来源原始单位' if item['symbol']=='TDX880823' else '股',amountUnit='元'),message='新浪板块可查看当前成员和实时强弱，来源不提供历史曲线。' if unsupported else error or stamp.get('warning') or ('' if len(frame) else '尚无缓存，请更新当前标的'))


def members(project,params):
    import pandas as pd
    item=instrument(params['instrument'])
    if item['kind'] not in {'industry','concept'}:raise ValueError('当前成员查询仅支持行业或概念板块')
    path=_root(project)/'members'/(item['kind']+'-'+item['symbol']+'.json');cached=read_json(path,{})
    failure=None
    if params.get('refresh') and source_settings(project.get('settings',{}))['boards']!='file':
        try:
            sina=item['symbol'].startswith('SINA_')
            if sina:
                frame=_ak('stock_sector_detail',_timeout=45,sector=item['symbol'][5:].lower())
                frame=frame.rename(columns={'trade':'close','changepercent':'pctChange','turnoverratio':'turnoverRate','per':'pe'})
            else:
                frame=_ak('stock_board_'+item['kind']+'_cons_em',_timeout=45,symbol=item['symbol'])
                frame=frame.rename(columns={'代码':'symbol','名称':'name','最新价':'close','涨跌幅':'pctChange','成交量':'volume','成交额':'amount','换手率':'turnoverRate','市盈率-动态':'pe'})
            def mainland(value):
                try:return instrument({'kind':'stock','symbol':str(value)})['symbol']
                except ValueError:return None
            frame['symbol']=frame.symbol.map(mainland)
            frame=frame[frame.symbol.notna()].copy()
            if 'volume' in frame:frame['volume']=pd.to_numeric(frame.volume,errors='coerce')*(1 if sina else 100)
            incoming=dict(updatedAt=now(),asOfDate=datetime.now().astimezone().date().isoformat(),source='akshare/sina' if sina else 'akshare/eastmoney',rows=data.records(frame))
            if not incoming['rows']:raise ValueError('来源未返回板块成员，旧名单保留')
            cached=incoming
            write_json(path,cached)
        except (ValueError,OSError) as exc:
            failure=str(exc)
    frame=pd.DataFrame(cached.get('rows',[]));query=str(params.get('query','')).casefold()
    if len(frame) and query:frame=frame[(frame.symbol+' '+frame.get('name','')).str.casefold().str.contains(query,regex=False)]
    for rule in params.get('filters',[]):
        key=rule.get('field')
        if key not in frame:raise ValueError('成员筛选字段不可用: '+str(key))
        series=pd.to_numeric(frame[key],errors='coerce');value=float(rule['value'])
        operations={'gt':series.gt,'gte':series.ge,'lt':series.lt,'lte':series.le,'eq':series.eq}
        operation=rule.get('operator',rule.get('op'))
        if operation not in operations:raise ValueError('成员筛选操作无效')
        frame=frame[operations[operation](value)]
    if params.get('sortBy') in frame:frame=frame.sort_values(params['sortBy'],ascending=not params.get('descending',False),na_position='last')
    offset=max(0,int(params.get('offset',0)));limit=max(1,min(500,int(params.get('limit',200))))
    return dict(instrument=item,asOfDate=cached.get('asOfDate'),source=cached.get('source','未查询'),total=len(frame),offset=offset,limit=limit,
        rows=data.records(frame.iloc[offset:offset+limit]),status='source_error' if failure else 'ready' if cached else 'missing',
        stale=bool(failure and cached),updatedAt=cached.get('updatedAt'),
        message=failure if failure else '仅记录查询日当前成员，不能作为历史成分。' if cached else '尚无成员缓存，请显式刷新')
