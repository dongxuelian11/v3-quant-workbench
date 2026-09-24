"""Single-security observations using installed adapters, with one cancellable child."""
from datetime import datetime, timedelta, time as day_time
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time

from .storage import now, read_json


def unknown(symbol, mode, reason):
    return dict(id=hashlib.sha256((symbol + str(mode) + reason).encode()).hexdigest(), symbol=symbol,
                kind='minute_close' if mode == 'intraday' else 'daily_close' if mode == 'daily_close' else None,
                price=None, priceBasis='raw', source=None, sourceTime=None, sourceTradeDate=None,
                fetchedAt=None, validity='unknown', reasonCodes=[reason])


def observation(symbol, mode, row, provider, endpoint, clock):
    value = unknown(symbol, mode, 'missing_price')
    value.update(source=dict(provider=provider, endpoint=endpoint), fetchedAt=clock.isoformat())
    try:
        price = float(row['close'])
        if not math.isfinite(price) or price <= 0: raise ValueError()
        day = str(row['date'])[:10]
        value.update(price=price, sourceTradeDate=day)
        if mode == 'intraday':
            stamp = datetime.fromisoformat(str(row['date']))
            if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            value['sourceTime'] = stamp.isoformat()
            age = (clock - stamp).total_seconds()
            reason = 'future_time' if age < 0 else 'stale' if age > 180 or day != clock.date().isoformat() else None
        else:
            # The provider supplies a trading date, not a publication timestamp.
            reason = None if day == clock.date().isoformat() else 'stale'
        value.update(validity='unknown' if reason else 'valid', reasonCodes=[reason] if reason else [])
    except (KeyError, TypeError, ValueError):
        pass
    value['id'] = hashlib.sha256(json.dumps([symbol, mode, provider, endpoint, value['sourceTime'], value['sourceTradeDate'], value['price']], sort_keys=True).encode()).hexdigest()
    return value


def target_day(calendar, clock, mode):
    today = clock.date().isoformat()
    if not isinstance(calendar, dict) or not calendar.get('start', '9999') <= today <= calendar.get('end', ''):
        return None, 'calendar_missing'
    dates = calendar.get('dates', [])
    if not isinstance(dates, list) or any(not isinstance(d, str) or len(d) != 10 for d in dates):
        return None, 'calendar_missing'
    if mode == 'intraday':
        if today not in dates: return None, 'market_closed'
        hm = clock.time().replace(tzinfo=None)
        if not (day_time(9, 30) <= hm <= day_time(11, 30) or day_time(13) <= hm <= day_time(15)):
            return None, 'market_closed'
        return today, None
    if today in dates:
        if clock.hour < 15: return None, 'period_incomplete'
        return today, None
    prior = sorted(d for d in dates if d < today)
    return (prior[-1], None) if prior else (None, 'calendar_missing')


def read_observation(store, symbol, mode, stop):
    from .app_settings import source_settings
    from .data import project_data
    if stop.is_set(): return unknown(symbol, mode, 'cancelled')
    settings = source_settings(store.settings())
    if mode not in {'intraday', 'daily_close'}: return unknown(symbol, mode, 'mode_pending')
    category = 'intraday' if mode == 'intraday' else 'daily'
    # Cached bars alone cannot prove a newly published current observation.
    if settings[category] == 'file': return unknown(symbol, mode, 'source_unavailable')
    project = store.project(None)
    calendar = read_json(Path(project_data(project)['path']) / 'data/trading-calendar.json', {})
    request = dict(symbol=symbol, mode=mode, settings=settings, calendar=calendar)
    with tempfile.TemporaryDirectory(prefix='v3-reminder-') as folder:
        output = Path(folder) / 'observation.json'
        request_path = Path(folder) / 'request.json'
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
        env = dict(os.environ)
        package_root = str(Path(__file__).resolve().parents[2])
        env['PYTHONPATH'] = package_root + os.pathsep + env.get('PYTHONPATH', '')
        # No nested process: child calls upstream APIs directly and reuses normalizers.
        process = subprocess.Popen([sys.executable, '-m', 'v3_backend.research.reminder_source', str(request_path), str(output)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 20
        try:
            while process.poll() is None:
                if stop.wait(.1): return unknown(symbol, mode, 'cancelled')
                if time.monotonic() >= deadline: return unknown(symbol, mode, 'source_timeout')
            if process.returncode or not output.exists(): return unknown(symbol, mode, 'source_error')
            return read_json(output)
        finally:
            if process.poll() is None: process.kill()
            process.wait()


def _fetch(request):
    from . import quotes, data, intraday
    symbol, mode, settings = request['symbol'], request['mode'], request['settings']
    clock = datetime.now(ZoneInfo('Asia/Shanghai'))
    calendar = request['calendar']
    day, reason = target_day(calendar, clock, mode)
    if reason == 'calendar_missing' and settings['daily'] == 'baostock':
        start = (clock.date() - timedelta(days=40)).isoformat()
        end = clock.date().isoformat()
        frame = quotes._baostock(lambda bs: data._bs_query(bs, bs.query_trade_dates, start_date=start, end_date=end))
        if not frame.empty and str(frame.calendar_date.min()) <= start and str(frame.calendar_date.max()) >= end:
            calendar = dict(start=start, end=end, dates=frame.loc[frame.is_trading_day.astype(str).eq('1'), 'calendar_date'].astype(str).tolist())
        day, reason = target_day(calendar, clock, mode)
    if reason: return unknown(symbol, mode, reason)
    if mode == 'intraday':
        import akshare as ak
        providers = [('akshare/eastmoney', 'stock_zh_a_hist_min_em', dict(symbol=symbol[2:], period='1', adjust='', start_date=day+' 09:30:00', end_date=day+' 15:00:00'), 100)]
        if settings['quoteFallback']:
            providers.append(('akshare/sina', 'stock_zh_a_minute', dict(symbol=symbol.lower(), period='1', adjust=''), 1))
        for provider, endpoint, args, multiplier in providers:
            try:
                incoming = getattr(ak, endpoint)(**args)
                observed_clock = datetime.now(ZoneInfo('Asia/Shanghai'))
                frame = intraday.normalize(incoming, dict(kind='stock', symbol=symbol), '1m', clock=observed_clock, source=provider, volume_multiplier=multiplier)
                frame = frame[frame.complete.eq(True)]
                if frame.empty: return unknown(symbol, mode, 'period_incomplete')
                value = observation(symbol, mode, frame.iloc[-1].to_dict(), provider, endpoint, observed_clock)
                value['_calendar'] = calendar
                return value
            except Exception:
                continue
        return unknown(symbol, mode, 'source_error')
    providers = [settings['daily']]
    if settings['quoteFallback']: providers.append('akshare' if settings['daily'] == 'baostock' else 'baostock')
    for provider in providers:
        try:
            if provider == 'baostock':
                endpoint = 'query_history_k_data_plus'
                frame = quotes._baostock(lambda bs: data._bs_query(bs, bs.query_history_k_data_plus,
                    symbol[:2].lower()+'.'+symbol[2:], 'date,code,close,tradestatus', start_date=day, end_date=day, frequency='d', adjustflag='3'))
                if frame.empty: return unknown(symbol, mode, 'source_not_published')
                row = frame.iloc[-1].to_dict()
                if str(row.get('code', '')).lower() != symbol[:2].lower()+'.'+symbol[2:]:
                    return unknown(symbol, mode, 'identity_mismatch')
                if str(row.get('tradestatus')) == '0': return unknown(symbol, mode, 'suspended')
                if str(row.get('tradestatus')) != '1': return unknown(symbol, mode, 'trading_status_unknown')
            else:
                import akshare as ak
                endpoint = 'stock_zh_a_hist'
                frame = ak.stock_zh_a_hist(symbol=symbol[2:], start_date=day.replace('-', ''), end_date=day.replace('-', ''), period='daily', adjust='')
                if frame.empty: return unknown(symbol, mode, 'source_not_published')
                frame = quotes._normalize(frame, dict(kind='stock', symbol=symbol), 'akshare/eastmoney')
                row = frame.iloc[-1].to_dict()
            # On a non-trading day, the calendar explicitly selected the latest session.
            effective = datetime.fromisoformat(day+'T15:00:00+08:00')
            value = observation(symbol, mode, row, provider, endpoint, effective)
            value['fetchedAt'] = now()
            value['_calendar'] = calendar  # Internal evidence, removed before public/history serialization.
            if value['sourceTradeDate'] != day:
                value.update(validity='unknown', reasonCodes=['source_not_published'])
            return value
        except Exception:
            continue
    return unknown(symbol, mode, 'source_error')


if __name__ == '__main__':
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    try: result = _fetch(request)
    except Exception: result = unknown(request['symbol'], request['mode'], 'source_error')
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
