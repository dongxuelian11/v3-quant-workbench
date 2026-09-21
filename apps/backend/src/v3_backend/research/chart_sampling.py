"""Bounded visual sampling of an ordered, single-series date table.

Select actual rows (never invented averages), retaining endpoints, extrema and
one missing observation per numeric column in each bucket. Not for statistics.
"""
import numpy as np
import pandas as pd


def sample(frames, total, limit, date_key, *, check_cancel=None):
    selected=[];offset=0;last_date=None;bucket=None;pending=[];bucket_count=None
    def flush():
        if not pending:return
        part=pd.concat(pending,ignore_index=True)
        indices={0,len(part)-1}
        for key in part.select_dtypes(include='number'):
            values=part[key].replace([np.inf,-np.inf],np.nan)
            if values.notna().any():indices.update((int(values.idxmin()),int(values.idxmax())))
            missing=np.flatnonzero(values.isna())
            if len(missing):indices.add(int(missing[0]))
        selected.append(part.iloc[sorted(indices)])
        pending.clear()
    for frame in frames:
        if check_cancel:check_cancel()
        if frame.empty:continue
        dates=pd.to_datetime(frame[date_key],errors='coerce')
        if dates.isna().any() or not dates.is_monotonic_increasing or dates.duplicated().any() or (last_date is not None and dates.iloc[0]<=last_date):
            return None  # A long-form multi-series table needs an explicit series selection.
        last_date=dates.iloc[-1]
        if bucket_count is None:
            slots=2+3*len(frame.select_dtypes(include='number').columns)
            if slots>limit:return None
            bucket_count=max(1,limit//slots)
        ids=np.minimum((np.arange(offset,offset+len(frame))*bucket_count)//max(1,total),bucket_count-1)
        for identifier in np.unique(ids):
            if bucket is not None and identifier!=bucket:flush()
            bucket=identifier
            pending.append(frame.iloc[np.flatnonzero(ids==identifier)])
            # Reduce within the current bucket too, bounding memory across batches.
            if sum(len(x) for x in pending)>8192:
                flush()
                pending.append(selected.pop())
        offset+=len(frame)
    flush()
    return pd.concat(selected,ignore_index=True) if selected else pd.DataFrame()
