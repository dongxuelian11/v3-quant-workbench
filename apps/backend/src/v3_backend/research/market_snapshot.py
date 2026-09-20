"""Independent observed market snapshots; research samples never supply breadth."""
from pathlib import Path
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


def _refresh(path,kind,function,arguments):
    previous=read_json(path,{})
    providers=[('akshare/eastmoney',function,arguments)]
    if kind in ALTERNATIVES:
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


def overview(project, params=None):
    import pandas as pd
    params=params or {};root=Path(project['path'])/'market-snapshot'
    values={};coverage=[];errors={};stamps=[]
    tasks={}
    for kind,(function,arguments) in SOURCES.items():
        path=root/(kind+'.json');cached=read_json(path,{})
        if params.get('refresh') or params.get('loadIfMissing') and not cached:
            with _lock:
                key=str(path.resolve())
                task=_pending.get(key)
                if task is None or task.done():
                    task=_pool.submit(_refresh,path,kind,function,arguments)
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
    actual_sources=list(dict.fromkeys(item['source'] for item in coverage if item['rows']))
    return dict(asOfDate=None,updatedAt=max(stamps) if stamps else None,source='、'.join(actual_sources) or '未获取',
        stale=bool(errors or any(stamp[:10]!=now()[:10] for stamp in stamps)),
        status='source_error' if errors else 'ready' if stamps else 'missing',errors=errors,
        summary=summary,indices=values['indices'],industries=values['industries'],concepts=values['concepts'],
        breadth=[dict(name=label,count=int(((changes>low)&(changes<=high)&changes.ne(0)).sum()) if len(changes) else None)
                 for label,low,high in [('跌超5%',-float('inf'),-.05),('跌幅0至5%',-.05,0),('涨幅0至5%',0,.05),('涨超5%',.05,float('inf'))]],
        coverage=coverage)
