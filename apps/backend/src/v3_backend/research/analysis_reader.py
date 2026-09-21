"""Bounded chart responses; rolling IC is computed on full session windows."""
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from .data import records, symbol
from .table_reader import calendar, batches


def read(path, name, params, calendar_path=None, *, check_cancel=None):
    if check_cancel: check_cancel()
    with pq.ParquetFile(path) as source:
        columns = params.get('columns') or source.schema_arrow.names
        if any(c not in source.schema_arrow.names for c in columns):
            raise ValueError('请求的数据列不存在')
        date_key = next((c for c in ('date', 'datetime', 'trade_date') if c in source.schema_arrow.names), None)
        extra = [c for c in (date_key, 'factor', 'symbol', 'instrument', 'asset') if c and c in source.schema_arrow.names]
        projection = list(dict.fromkeys(columns + extra))
        limit = max(1, min(5000, int(params.get('maxPoints', 1200))))
        rolling = params.get('rolling')
        if rolling and not (name.endswith('_IC') or name.endswith('_RankIC')):
            raise ValueError('滚动统计仅用于已保存的 IC 序列')
        total, chunks, kept = 0, [], 0
        def frames():
            for batch in batches(source, check_cancel=check_cancel, columns=projection, batch_size=8192):
                frame = batch.to_pandas()
                if check_cancel: check_cancel()
                if params.get('factor'):
                    if 'factor' not in frame:
                        raise ValueError('此表没有因子筛选字段')
                    frame = frame[frame.factor == params['factor']]
                if params.get('symbol'):
                    key = next((c for c in ('symbol','instrument','asset') if c in frame), None)
                    if key is None:
                        raise ValueError('此表没有证券筛选字段')
                    frame = frame[frame[key] == symbol(params['symbol'])]
                # Rolling windows need their preceding sessions; slice only after computing.
                if not rolling and (params.get('startDate') or params.get('endDate')):
                    if date_key is None:
                        raise ValueError('此表没有日期列')
                    dates = pd.to_datetime(frame[date_key])
                    mask = pd.Series(True, index=frame.index)
                    if params.get('startDate'): mask &= dates >= pd.Timestamp(params['startDate'])
                    if params.get('endDate'): mask &= dates < pd.Timestamp(params['endDate']) + pd.Timedelta(days=1)
                    frame = frame[mask]
                yield frame
        for frame in frames():
            total += len(frame)
            if rolling:
                chunks.append(frame)
            elif kept < limit:
                subset = frame.head(limit-kept)
                chunks.append(subset)
                kept += len(subset)
        if check_cancel: check_cancel()
        source_rows = total
        frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=projection)
        calendar_source = None
        sampled = False
        if not rolling and date_key and params.get('sampling') == 'minmax' and total > limit:
            from .chart_sampling import sample
            reduced = sample(frames(), total, limit, date_key, check_cancel=check_cancel)
            if reduced is not None:
                frame, sampled = reduced, True
        if rolling and len(frame):
            window = int(rolling.get('window', 20))
            statistic = rolling.get('statistic', 'mean')
            if window not in (20, 60) or statistic not in ('mean', 'icir') or not date_key:
                raise ValueError('滚动 IC 仅支持20/60期均值或ICIR')
            frame[date_key] = pd.to_datetime(frame[date_key])
            frame = frame.sort_values(date_key).set_index(date_key)
            sessions = calendar(calendar_path, check_cancel=check_cancel) if calendar_path else None
            if sessions is not None:
                index = pd.to_datetime([d for d in sessions if str(frame.index.min())[:10] <= d <= str(frame.index.max())[:10]])
                frame = frame.reindex(index)
                frame.index.name = date_key
                calendar_source = 'experiment_processing_sessions'
            else:
                calendar_source = 'unavailable'
                valid_numeric = frame.select_dtypes(include='number').notna().any(axis=1)
                frame = frame[(frame.index.dayofweek < 5) | valid_numeric]
            numeric = frame.select_dtypes(include='number').columns
            for key in numeric:
                if check_cancel: check_cancel()
                values = frame[key].replace([np.inf, -np.inf], np.nan)
                mean = values.rolling(window, min_periods=window).mean()
                frame[key] = mean if statistic == 'mean' else mean / values.rolling(window, min_periods=window).std(ddof=1).replace(0, np.nan)
            frame = frame.reset_index()
            if params.get('startDate'): frame = frame[frame[date_key] >= pd.Timestamp(params['startDate'])]
            if params.get('endDate'): frame = frame[frame[date_key] < pd.Timestamp(params['endDate']) + pd.Timedelta(days=1)]
            total = len(frame)
            if params.get('sampling') == 'minmax' and total > limit:
                from .chart_sampling import sample
                reduced = sample(iter([frame]), total, limit, date_key, check_cancel=check_cancel)
                if reduced is not None: frame, sampled = reduced, True
            if not sampled: frame = frame.head(limit)
        if check_cancel: check_cancel()
        rows = records(frame.reindex(columns=columns))
        if check_cancel: check_cancel()
        return dict(name=name, columns=columns, rows=rows, total=total, returned=len(rows), calendarSource=calendar_source,
                    aggregation=dict(method='minmax' if sampled else 'preview' if total > len(rows) else 'complete', sampled=sampled, sourceRows=source_rows),
                    message=f'图表按视口抽取 {len(rows)} / {total} 点，保留分段端点、极值及缺失标记；统计与导出使用完整数据' if sampled else f'显示 {len(rows)} / {total} 行；完整明细与导出保留全部数据' if total > len(rows) else '')
