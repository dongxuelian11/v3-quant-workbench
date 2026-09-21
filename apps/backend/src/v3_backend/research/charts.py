"""Chart windows and portable drawing coordinates for the existing market tables."""
from copy import deepcopy
from pathlib import Path
from threading import RLock

from .data import project_data, records, symbol
from .storage import read_json, write_json

_drawing_lock = RLock()
TRADING_ANCHOR = '2015-01-05'


def trading_period(params):
    value=params.get('tradingDays')
    if isinstance(value,bool) or not isinstance(value,int) or not 2<=value<=250:
        raise ValueError('自定义周期需要2至250之间的整数交易日数')
    if params.get('anchorDate',TRADING_ANCHOR)!=TRADING_ANCHOR:
        raise ValueError('交易日分组固定以2015-01-05为参照')
    return value


def with_calendar(project,params,frame):
    if params.get('period')!='trading_days':return params
    import pandas as pd
    from . import quotes,data
    count=trading_period(params)
    if frame.empty:return {**params,'_tradingDates':[TRADING_ANCHOR]}
    root=Path(project_data(project)['path'])/'data'
    first=pd.Timestamp(frame.date.min()).normalize();last=pd.Timestamp(frame.date.max()).normalize()
    start=str(min(pd.Timestamp(TRADING_ANCHOR),first-pd.Timedelta(days=max(14,count*3))).date())
    end=str(max(pd.Timestamp(TRADING_ANCHOR),last).date())
    cached=read_json(root/'trading-calendar.json',{})
    existing=pd.DatetimeIndex(cached.get('dates',[])).normalize().sort_values().unique()
    if cached.get('start','9999')<=str(min(first,pd.Timestamp(TRADING_ANCHOR)).date()) and cached.get('end','')>=end and pd.Timestamp(TRADING_ANCHOR) in existing:
        anchor=existing.get_loc(pd.Timestamp(TRADING_ANCHOR));positions=existing.get_indexer(pd.to_datetime(frame.date).dt.normalize())
        if (positions>=0).all() and anchor+((positions.min()-anchor)//count)*count>=0:
            return {**params,'_tradingDates':existing}
    if cached.get('start','9999')>start or cached.get('end','')<end:
        from .app_settings import source_settings
        if project.get('inputDataRoot'):
            raise ValueError('该实验固定输入未包含足够交易日历，自定义周期暂不可用；不会补写原实验输入')
        if source_settings(project.get('settings',{}))['daily']!='baostock':
            raise ValueError('当前来源未提供本适配器所需的完整交易日历；请导入日历或明确选择BaoStock，不自动切换来源')
        try:
            start=min(start,cached.get('start',start));end=max(end,cached.get('end',end))
            result=quotes._baostock(lambda bs:data._bs_query(bs,bs.query_trade_dates,start_date=start,end_date=end))
            if result.empty or str(result.calendar_date.min())>start or str(result.calendar_date.max())<end:
                raise ValueError('交易日历覆盖不完整')
            dates=sorted(str(d) for d in result.loc[result.is_trading_day.astype(str).eq('1'),'calendar_date'])
            cached={'start':start,'end':end,'dates':dates}
            write_json(root/'trading-calendar.json',cached)
        except Exception as exc:
            raise ValueError('缺少覆盖行情与2015-01-05参照日的完整交易日历，自定义周期暂不可用：'+str(exc)) from None
    return {**params,'_tradingDates':cached['dates']}


def prices(project, code):
    import pandas as pd
    import pyarrow.parquet as pq
    root = Path(project_data(project)['path']) / 'data'
    columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'factor',
               'rawOpen', 'rawHigh', 'rawLow', 'rawClose']
    frames = []
    for path, filters in ((root / 'prices.parquet', [('symbol', '==', code)]),
                          (root / 'prices' / f'{code}.parquet', None)):
        if path.exists():
            available = set(pq.ParquetFile(path).schema_arrow.names)
            selected = [column for column in columns if column in available]
            frames.append(pd.read_parquet(path, columns=selected, filters=filters).reindex(columns=columns))
    if not frames:
        return pd.DataFrame(columns=columns)
    frame = pd.concat(frames, ignore_index=True)
    frame['date'] = pd.to_datetime(frame.date).dt.normalize()
    for column in columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors='coerce')
    return frame.drop_duplicates('date', keep='last').sort_values('date').reset_index(drop=True)


def bars(project, params):
    if params.get('instrument'):
        from .quotes import bars as quote_bars
        return quote_bars(project,params)
    frame=prices(project,symbol(params['symbol']))
    return bars_from_frame(frame,with_calendar(project,params,frame))


def bars_from_frame(frame,params):
    import pandas as pd
    period = params.get('period', 'day')
    if period not in ('day', 'week', 'month','trading_days'):
        raise ValueError('行情周期支持日、周、月')
    frame=frame.copy()
    for field in ('factor','amount','rawOpen','rawHigh','rawLow','rawClose'):
        if field not in frame:frame[field]=float('nan')
    frame['date']=pd.to_datetime(frame.date)
    if frame.empty:
        return []
    # Truncate before aggregation, so an as-of chart never includes later days
    # from the same week/month. Pagination then works on complete grouped bars.
    if params.get('endDate'):
        frame = frame[frame.date <= pd.Timestamp(params['endDate'])]
    if frame.empty:
        return []
    calendar=None
    if period=='trading_days':
        count=trading_period(params)
        calendar=pd.DatetimeIndex(params.get('_tradingDates',[])).normalize().sort_values().unique()
        if calendar.empty or pd.Timestamp(TRADING_ANCHOR) not in calendar:
            raise ValueError('自定义周期缺少固定参照交易日历')
        anchor_position=calendar.get_loc(pd.Timestamp(TRADING_ANCHOR))
        positions=calendar.get_indexer(frame.date)
        if (positions<0).any():raise ValueError('行情日期不在完整交易日历内，自定义周期不可用')
        keys=(positions-anchor_position)//count
    if period != 'day':
        grouped = frame.groupby(keys if calendar is not None else frame.date.dt.to_period('W-FRI' if period == 'week' else 'M'), sort=True)
        rows = []
        for key, group in grouped:
            row = {'date': group.date.iloc[-1], 'periodStart': group.date.iloc[0],
                   'periodEnd': group.date.iloc[-1], 'sessions': len(group)}
            if calendar is not None:
                left=anchor_position+int(key)*count;right=left+count-1
                if left<0:raise ValueError('交易日历未覆盖当前分组起点，自定义周期不可用')
                row['periodStart']=calendar[left]
                row['periodEnd']=calendar[min(right,len(calendar)-1)]
                current=pd.Timestamp.now(tz='Asia/Shanghai');today=current.tz_localize(None).normalize()
                row['complete']=bool(right<len(calendar) and (calendar[right]<today or calendar[right]==today and current.hour>=15)
                                     and frame.date.min()<=calendar[left] and frame.date.max()>=calendar[right])
            for prefix in ('', 'raw'):
                fields = [prefix + field.title() if prefix else field for field in ('open', 'high', 'low', 'close')]
                # Incomplete raw OHLC is not filled from adjusted prices.
                if group[fields].isna().any().any():
                    row.update({field: None for field in fields})
                else:
                    row.update(zip(fields, (group[fields[0]].iloc[0], group[fields[1]].max(),
                                            group[fields[2]].min(), group[fields[3]].iloc[-1])))
            for field in ('volume', 'amount'):
                row[field] = group[field].sum(min_count=len(group))
            # A grouped bar has no single adjustment factor if a corporate
            # action occurred inside it. Trade marks retain their daily factor.
            factors = group.factor.dropna()
            row['factor'] = factors.iloc[-1] if len(factors) == len(group) and factors.nunique() == 1 else None
            rows.append(row)
        frame = pd.DataFrame(rows)
    else:
        frame['periodStart'] = frame.date
        frame['periodEnd'] = frame.date
        frame['sessions'] = 1
    frame['period'] = period
    # KLineChart calls traded amount "turnover"; this is yuan, not a rate.
    frame['turnover'] = frame.amount
    if params.get('startDate'):
        frame = frame[frame.periodEnd >= pd.Timestamp(params['startDate'])]
    if params.get('beforeDate'):
        frame = frame[frame.date < pd.Timestamp(params['beforeDate'])]
    return records(frame.tail(max(1, min(500, int(params.get('limit', 500))))))


def _convert(annotation, source, target, frame):
    import math
    import pandas as pd
    value = deepcopy(annotation)
    if source == target or source == 'legacy' or target == 'legacy':
        return value
    if frame.empty:
        raise ValueError('缺少复权因子')
    days = pd.DatetimeIndex(frame.date)
    for point in value.get('points', []):
        if point.get('value') is None:
            continue
        timestamp = point.get('timestamp')
        if timestamp is None:
            raise ValueError('批注缺少日期坐标')
        date = pd.Timestamp(timestamp, unit='ms', tz='UTC').tz_convert('Asia/Shanghai').tz_localize(None).normalize()
        index = days.searchsorted(date, side='right') - 1
        factor = frame.factor.iloc[index] if index >= 0 else None
        if factor is None or not math.isfinite(float(factor)) or float(factor) <= 0:
            raise ValueError('批注日期缺少复权因子')
        point['value'] = float(point['value']) * float(factor) if target == 'adjusted' else float(point['value']) / float(factor)
    return value


def drawings(project, method, params):
    # One local service is shared by all native windows. Serialize the small
    # read/merge/write operation so two windows adding lines retain both.
    with _drawing_lock:
        return _drawings(project, method, params)


def _drawings(project, method, params):
    quote=params.get('instrument')
    if quote:
        from .quotes import instrument,read
        quote=instrument(quote)
    code = quote['kind']+'-'+quote['symbol'] if quote else symbol(params['symbol'])
    root = Path(project['path']) / 'annotations'
    period=params.get('period','daily')
    if period not in ('daily','day','week','month','trading_days','intraday','1m','5m','15m','30m','60m'):raise ValueError('批注周期无效')
    suffix='' if period in ('daily','day') else '-'+period
    if period=='trading_days':suffix+=f'-{trading_period(params)}-{TRADING_ANCHOR}'
    path = root / f'{code}{suffix}.json'
    value = read_json(path, [])
    legacy = isinstance(value, list)
    document = {'version': 2, 'items': [{'basis': 'legacy', 'annotation': item} for item in value]} if legacy else value
    basis = params.get('priceBasis', 'legacy')
    if basis not in ('raw', 'adjusted', 'legacy'):
        raise ValueError('批注价格口径必须为原始或前复权')
    if quote and quote['kind']!='stock' and basis=='adjusted':raise ValueError('指数与板块仅使用原始点位')
    frame = read(project,quote) if quote else prices(project, code)
    preferences_path = root / 'chart-preferences.json'
    preferences = read_json(preferences_path, {})
    warnings = []
    if method == 'charts.save':
        supplied = params.get('annotations', [])
        if not isinstance(supplied, list):
            raise ValueError('图表批注应为数组')
        # New callers merge changes by the chart library's ordinary overlay ID,
        # preventing another open chart from discarding unrelated drawings.
        removed = set(params.get('deletedIds', []))
        items = {item['annotation'].get('id'): item for item in document.get('items', [])
                 if item['annotation'].get('id') not in removed} if params.get('merge') else {}
        for annotation in supplied:
            if annotation.get('groupId') == 'research-trade':
                continue
            copy = deepcopy(annotation)
            for point in copy.get('points', []):
                if point.get('timestamp') is not None:
                    point.pop('dataIndex', None)
            try:
                item = {'basis': 'legacy' if basis == 'legacy' else 'raw',
                        'annotation': _convert(copy, basis, 'raw', frame)}
            except ValueError:
                item = {'basis': basis, 'annotation': copy}
                warnings.append('部分批注缺复权因子，已按当前价格口径保存。')
            items[copy.get('id')] = item
        document = {'version': 2, 'items': list(items.values())}
        write_json(path, document)
        if 'preferences' in params:
            if not isinstance(params['preferences'], dict):
                raise ValueError('图表设置应为对象')
            preferences = {**preferences, **params['preferences']}
            write_json(preferences_path, preferences)
    annotations, omitted = [], []
    for item in document.get('items', []):
        try:
            annotations.append(_convert(item['annotation'], item['basis'], basis, frame))
            if item['basis'] == 'legacy':
                warnings.append('旧批注未记录价格口径，暂保留原坐标；确认后编辑保存。')
        except ValueError:
            omitted.append(item['annotation'].get('id'))
    if omitted:
        warnings.append(f'{len(omitted)} 个批注缺少切换价格口径所需的复权因子，原记录保留。')
    return {'annotations': annotations, 'preferences': preferences,
            'warnings': list(dict.fromkeys(warnings)), 'omittedIds': omitted}
