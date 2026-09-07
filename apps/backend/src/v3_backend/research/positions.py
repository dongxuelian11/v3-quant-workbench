"""User-maintained holdings, separate from generated target portfolios."""
from pathlib import Path
import math
from .storage import read_json, write_json, now
from .data import symbol


def validate(value):
    import pandas as pd
    date = pd.Timestamp(value.get('asOfDate') or now()[:10]).strftime('%Y-%m-%d')
    cash = float(value.get('cash', 0))
    if not math.isfinite(cash) or cash < 0:
        raise ValueError('cash 必须为非负有限数值')
    rows, seen = [], set()
    for index, row in enumerate(value.get('rows', []), 1):
        try:
            code = symbol(row['symbol'])
            quantity = float(row['quantity'])
            sellable = float(row.get('sellableQuantity', quantity))
            if code in seen or not math.isfinite(quantity + sellable) or quantity < 0 or not 0 <= sellable <= quantity or quantity % 1 or sellable % 1:
                raise ValueError('重复证券或 quantity/sellableQuantity 无效')
            item = dict(symbol=code, quantity=int(quantity), sellableQuantity=int(sellable))
            if row.get('costPrice') is not None and pd.notna(row['costPrice']):
                cost = float(row['costPrice'])
                if not math.isfinite(cost) or cost < 0:
                    raise ValueError('costPrice 必须为非负有限数值')
                item['costPrice'] = cost
            rows.append(item)
            seen.add(code)
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'持仓第 {index} 行: {exc}') from exc
    return dict(asOfDate=date, cash=cash, rows=rows, updatedAt=now())


def get(project):
    return read_json(Path(project['path']) / 'positions.json', dict(asOfDate='', cash=0, rows=[]))


def save(project, value):
    result = validate(value)
    write_json(Path(project['path']) / 'positions.json', result)
    return result


def import_file(project, path):
    import pandas as pd
    path = Path(path)
    if path.suffix.lower() == '.csv':
        frame = pd.read_csv(path, dtype={'symbol': str})
    elif path.suffix.lower() == '.xlsx':
        frame = pd.read_excel(path, dtype={'symbol': str})
    else:
        raise ValueError('持仓只支持 CSV/XLSX')
    if not {'symbol', 'quantity', 'sellableQuantity'}.issubset(frame):
        raise ValueError('持仓缺少 symbol/quantity/sellableQuantity 列')
    old = get(project)
    return save(project, dict(asOfDate=frame.asOfDate.dropna().iloc[0] if 'asOfDate' in frame and frame.asOfDate.notna().any() else old['asOfDate'],
        cash=frame.cash.dropna().iloc[0] if 'cash' in frame and frame.cash.notna().any() else old['cash'], rows=frame.to_dict('records')))
