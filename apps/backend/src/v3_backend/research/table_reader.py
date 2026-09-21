"""Bounded Parquet previews and filtered pages, including legacy trade row IDs."""
import pandas as pd
import pyarrow.parquet as pq


def preview(path, limit, *, check_cancel=None):
    if check_cancel: check_cancel()
    with pq.ParquetFile(path) as source:
        batch = next(batches(source, check_cancel=check_cancel, batch_size=limit), None)
        frame = batch.to_pandas() if batch is not None else pd.DataFrame(columns=source.schema_arrow.names)
        if check_cancel: check_cancel()
        return frame


def replay_counts(path, trades=False, *, check_cancel=None):
    """Reduce large holdings/trade artifacts with bounded working memory."""
    if check_cancel: check_cancel()
    with pq.ParquetFile(path) as source:
        columns = [c for c in ('symbol', 'side', 'direction') if c in source.schema_arrow.names]
        if 'symbol' not in columns:
            if check_cancel: check_cancel()
            return {}
        result = {}
        for batch in batches(source, check_cancel=check_cancel, batch_size=8192, columns=columns):
            frame = batch.to_pandas()
            if check_cancel: check_cancel()
            for code, group in frame.groupby('symbol'):
                item = result.setdefault(str(code), dict(symbol=str(code), tradeCount=0, buyCount=0, sellCount=0))
                if trades:
                    item['tradeCount'] += len(group)
                    if 'side' in group:
                        item['buyCount'] += int(group.side.eq('buy').sum())
                        item['sellCount'] += int(group.side.eq('sell').sum())
                    elif 'direction' in group:
                        item['buyCount'] += int(group.direction.eq(1).sum())
                        item['sellCount'] += int(group.direction.eq(0).sum())
        if check_cancel: check_cancel()
        return result


def calendar(path, *, check_cancel=None):
    if check_cancel: check_cancel()
    with pq.ParquetFile(path) as source:
        if 'date' not in source.schema_arrow.names:
            if check_cancel: check_cancel()
            return None
        dates = set()
        for batch in batches(source, check_cancel=check_cancel, batch_size=8192, columns=['date']):
            dates.update(pd.to_datetime(batch.column(0).to_pandas(), errors='raise').dropna().dt.strftime('%Y-%m-%d'))
        if check_cancel: check_cancel()
        return sorted(dates)


def page(path, params, name, *, check_cancel=None):
    from .data import records, symbol
    if check_cancel: check_cancel()
    with pq.ParquetFile(path) as source:
        columns = source.schema_arrow.names
        synthetic_id = name.removeprefix('holdout_') == 'trades' and 'tradeId' not in columns
        available = columns + (['tradeId'] if synthetic_id else [])
        selected = params.get('columns') or available
        if any(c not in available for c in selected):
            raise ValueError('请求的数据列不存在')
        filters = []
        for parameter, choices in [('factorId', ('factor', 'factorId')), ('tradeId', ('tradeId',)),
                                    ('modelWindowId', ('window', 'windowId', 'modelWindowId')),
                                    ('symbol', ('symbol', 'instrument', 'asset'))]:
            if params.get(parameter) not in (None, ''):
                column = next((c for c in choices if c in available), None)
                if not column:
                    raise ValueError('此表没有对应的筛选字段: ' + parameter)
                value = symbol(params[parameter]) if parameter == 'symbol' else str(params[parameter])
                filters.append((column, value))
        date_column = next((c for c in ('date', 'datetime', 'trade_date') if c in columns), None)
        if (params.get('startDate') or params.get('endDate')) and not date_column:
            raise ValueError('此表没有日期列')
        read_columns = list(dict.fromkeys([c for c in selected if c in columns] +
            [c for c, _ in filters if c in columns] + ([date_column] if date_column else [])))
        offset, limit = max(0, int(params.get('offset', 0))), max(1, min(500, int(params.get('limit', 200))))
        if not filters and not params.get('startDate') and not params.get('endDate'):
            total, rows, group_start = source.metadata.num_rows, [], 0
            for group_index in range(source.num_row_groups):
                count = source.metadata.row_group(group_index).num_rows
                if group_start + count > offset and group_start < offset + limit:
                    batch_start = group_start
                    for batch in batches(source, check_cancel=check_cancel, batch_size=8192, columns=[c for c in selected if c in columns], row_groups=[group_index]):
                        frame = batch.to_pandas()
                        if check_cancel: check_cancel()
                        if synthetic_id:
                            frame['tradeId'] = [str(i) for i in range(batch_start, batch_start + len(frame))]
                        begin, end = max(0, offset-batch_start), max(0, offset+limit-batch_start)
                        rows.extend(records(frame.iloc[begin:end][selected]))
                        batch_start += len(frame)
                        if batch_start >= offset + limit:
                            break
                group_start += count
                if group_start >= offset + limit:
                    break
            if check_cancel: check_cancel()
            return dict(name=name, columns=selected, rows=rows, total=total, offset=offset, limit=limit)
        total, raw_offset, rows = 0, 0, []
        for batch in batches(source, check_cancel=check_cancel, batch_size=8192, columns=read_columns):
            frame = batch.to_pandas()
            if check_cancel: check_cancel()
            if synthetic_id:
                frame['tradeId'] = [str(i) for i in range(raw_offset, raw_offset + len(frame))]
            raw_offset += len(frame)
            for column, value in filters:
                frame = frame[frame[column].astype(str) == value]
            if date_column and (params.get('startDate') or params.get('endDate')):
                dates = pd.to_datetime(frame[date_column], utc=True)
                mask = pd.Series(True, index=frame.index)
                if params.get('startDate'):
                    mask &= dates >= pd.to_datetime(params['startDate'], utc=True)
                if params.get('endDate'):
                    mask &= dates < pd.to_datetime(params['endDate'], utc=True).normalize() + pd.Timedelta(days=1)
                frame = frame[mask]
            begin, end = max(0, offset-total), max(0, offset+limit-total)
            if begin < len(frame) and end > begin:
                rows.extend(records(frame.iloc[begin:end][selected]))
            total += len(frame)
        if check_cancel: check_cancel()
        return dict(name=name, columns=selected, rows=rows, total=total, offset=offset, limit=limit)


def batches(source, *, check_cancel=None, **kwargs):
    """Check before and after each blocking Arrow batch, including early stop."""
    iterator = source.iter_batches(**kwargs)
    while True:
        if check_cancel: check_cancel()
        batch = next(iterator, None)
        if check_cancel: check_cancel()
        if batch is None:
            return
        yield batch
