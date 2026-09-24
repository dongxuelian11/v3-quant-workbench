"""Persistent reminder rules and a single bounded observation worker."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import re
import queue
import threading
import time
from concurrent.futures import Future
from contextlib import nullcontext

from .storage import identifier, now

READ_METHODS = frozenset({'reminders.list', 'reminders.get', 'reminders.history', 'reminders.runtime'})
# Metadata lives in the app database, outside copied data directories.
MANAGEMENT_METHODS = frozenset({'reminders.scope.preview', 'reminders.create', 'reminders.update', 'reminders.delete'})


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(label + '无效')
    return value.strip()


def _condition(value):
    if not isinstance(value, dict) or set(value) != {'operator', 'threshold'}:
        raise ValueError('条件须包含operator和threshold')
    number = value['threshold']
    if value['operator'] not in {'gte', 'lte'} or type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
        raise ValueError('请选择价格大于等于或小于等于，阈值须为有限正数')
    return dict(operator=value['operator'], threshold=number)


def _symbol(value):
    code = _text(value, '证券代码').upper().replace('.', '')
    if re.fullmatch(r'\d{6}', code):
        code = ('SH' if code.startswith(('60', '68')) else 'SZ' if code.startswith(('00', '30')) else '') + code
    if not re.fullmatch(r'(SH(?:60|68)\d{4}|SZ(?:00|30)\d{4})', code):
        raise ValueError('提醒范围仅支持明确的沪深A股证券代码：' + code)
    return code


def _get(db, kind, key):
    row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
    if row is None:
        raise ValueError('提醒记录不存在：' + str(key))
    return json.loads(row[0])


def _put(db, kind, value):
    db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?)',
               (kind, value['id'], '', json.dumps(value, ensure_ascii=False, allow_nan=False)))
    return value


def _time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('时间缺少时区')
    return parsed.astimezone(timezone.utc)


def evaluate_observation(condition, observation, state, *, checked_at, max_age_seconds, expected_trade_date=None):
    """Internal pure evaluator. Adapters must establish validity; unknown never rearms.

    Returns result, new state, reasons. A trigger is not proof of notification delivery.
    This helper is not exposed through the protocol and does not fetch any data.
    """
    condition = _condition(condition)
    state = deepcopy(state)
    reasons = list(observation.get('reasonCodes') or [])
    if observation.get('validity') != 'valid' and reasons:
        return 'unknown', state, list(dict.fromkeys(reasons))
    price = observation.get('price')
    if observation.get('validity') != 'valid':
        reasons.append('invalid_observation')
    if type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
        reasons.append('invalid_price')
    if observation.get('priceBasis') != 'raw' or not observation.get('source') or not observation.get('id'):
        reasons.append('missing_provenance')
    daily = observation.get('kind') == 'daily_close'
    time_key = 'sourceTradeDate' if daily else 'sourceTime'
    try:
        if daily:
            observed = datetime.strptime(observation['sourceTradeDate'], '%Y-%m-%d').date()
            if expected_trade_date is None: reasons.append('calendar_missing')
            elif observation['sourceTradeDate'] != expected_trade_date: reasons.append('stale')
            from zoneinfo import ZoneInfo
            if observed > _time(checked_at).astimezone(ZoneInfo('Asia/Shanghai')).date():
                reasons.append('future_time')
            prior = datetime.strptime(state[time_key], '%Y-%m-%d').date() if state.get(time_key) else None
        else:
            observed = _time(observation['sourceTime'])
            age = (_time(checked_at) - observed).total_seconds()
            if not math.isfinite(max_age_seconds) or max_age_seconds < 0: raise ValueError()
            if age < 0: reasons.append('future_time')
            elif age > max_age_seconds: reasons.append('stale')
            prior = _time(state[time_key]) if state.get(time_key) else None
        if prior is not None and observed < prior: reasons.append('out_of_order')
    except (KeyError, TypeError, ValueError):
        reasons.append('missing_source_time')
    if reasons:
        return 'unknown', state, list(dict.fromkeys(reasons))
    if state.get('observationId') == observation['id']:
        return 'not_triggered', state, ['duplicate_observation']
    if prior is not None and observed == prior:
        return 'not_triggered', state, ['duplicate_observation_time']
    satisfied = price >= condition['threshold'] if condition['operator'] == 'gte' else price <= condition['threshold']
    trigger = satisfied and not state.get('satisfied', False)
    state.update(satisfied=satisfied, observationId=observation['id'])
    state[time_key] = observation[time_key]
    return ('triggered' if trigger else 'not_triggered'), state, []


class Reminders:
    def __init__(self, store):
        self.store = store
        self.session_id = identifier()
        self.started_at = now()
        self.last_check_at = None
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.tasks = queue.Queue(maxsize=1)
        self.pending = {}
        self.thread = None
        self.service = None
        self.due = {}
        self.baseline = {}
        from .reminder_source import read_observation
        self.observe = read_observation

    def start(self, service=None):
        with self.lock:
            if self.stop.is_set(): raise ValueError('提醒服务已停止')
            if self.thread is not None: return
            self.service = service
            self.baseline = {r['id']: set(r['scope']['symbols']) for r in self.store.list('reminder') if r['status'] == 'enabled'}
            self.next_schedule = time.monotonic() + 60
            self.thread = threading.Thread(target=self._loop, name='reminder-check', daemon=True)
            self.thread.start()

    def close(self):
        with self.lock: self.stop.set()
        if self.thread: self.thread.join()

    def runtime(self):
        alive = bool(self.thread and self.thread.is_alive() and not self.stop.is_set())
        paused = bool(self.service and self.service.migrations.pause.is_set())
        return dict(sessionId=self.session_id, sessionStartedAt=self.started_at,
                    running=alive and not paused, lastCheckAt=self.last_check_at,
                    message=('数据迁移期间检查暂停。' if paused else '串行检查服务运行中；仅明确启用的规则每分钟检查，盘中使用分钟收盘价。' if alive else '提醒检查服务未运行。') +
                            '每轮最多60秒内开始新的证券查询；未查尾部下轮优先。程序未运行期间没有监控；启动首次自动观察只建立基线，不补造停机期间触发。通知尚未确认发送。')

    def _loop(self):
        try:
            while not self.stop.is_set():
                try:
                    request, future = self.tasks.get(timeout=.2)
                except queue.Empty:
                    if time.monotonic() < self.next_schedule: continue
                    rules = [r for r in self.store.list('reminder') if r['status'] == 'enabled' and self.due.get(r['id'], 0) <= time.monotonic()]
                    if not rules:
                        self.next_schedule = time.monotonic() + 1
                        continue
                    rule = min(rules, key=lambda r: self.due.get(r['id'], 0))
                    self.due[rule['id']] = time.monotonic() + 60
                    try:
                        self._perform(dict(ruleId=rule['id'], requestId=identifier()), 'scheduled')
                    except Exception:
                        # The next bounded interval retries. No fabricated successful result.
                        pass
                    self.due[rule['id']] = time.monotonic() + 60
                    continue
                try:
                    if self.stop.is_set(): raise ValueError('提醒服务已停止')
                    future.set_result(self._perform(request, 'manual'))
                except Exception as exc:
                    future.set_exception(exc)
                finally:
                    with self.lock: self.pending.pop(request['requestId'], None)
        finally:
            while True:
                try: request, future = self.tasks.get_nowait()
                except queue.Empty: break
                future.set_exception(ValueError('提醒服务已停止'))
                with self.lock: self.pending.pop(request['requestId'], None)

    def preview(self, params):
        if set(params) - {'symbol', 'watchlistId'} or bool(params.get('symbol')) == bool(params.get('watchlistId')):
            raise ValueError('请选择单证券或一个自选组')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            snapshot = dict(id=identifier(), kind='single', symbols=[], createdAt=now(), confirmedAt=None)
            if params.get('watchlistId'):
                watch = _get(db, 'watchlist', params['watchlistId'])
                snapshot.update(kind='watchlist', sourceWatchlist=dict(id=watch['id'], name=watch['name'], updatedAt=watch.get('updatedAt')))
                symbols = list(watch.get('symbols', []))
                symbols += [item['symbol'] for item in watch.get('instruments', []) if item.get('kind') == 'stock']
            else:
                symbols = [params['symbol']]
            snapshot['symbols'] = list(dict.fromkeys(_symbol(value) for value in symbols))
            if not snapshot['symbols']:
                raise ValueError('范围中没有可确认的A股证券')
            return _put(db, 'reminder_scope', snapshot)

    def create(self, params):
        if set(params) - {'requestId', 'name', 'snapshotId', 'condition', 'priceMode'} or not {'requestId', 'name', 'snapshotId', 'condition'} <= set(params):
            raise ValueError('创建提醒字段无效')
        mode = params.get('priceMode')
        if mode not in (None, 'intraday', 'daily_close'):
            raise ValueError('请选择盘中或收盘提醒')
        request_id = _text(params['requestId'], '请求标识')
        intent = dict(name=_text(params['name'], '提醒名称'), snapshotId=_text(params['snapshotId'], '范围标识'), condition=_condition(params['condition']))
        if mode is not None: intent['priceMode'] = mode
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT body FROM records WHERE kind='reminder_create_request' AND id=?", (request_id,)).fetchone()
            if row:
                saved = json.loads(row[0])
                if saved['intent'] != intent: raise ValueError('同一requestId不能提交不同提醒意图')
                return saved['result']
            scope = _get(db, 'reminder_scope', intent['snapshotId'])
            stamp = now()
            scope['confirmedAt'] = stamp
            rule = dict(id=identifier(), version=1, name=intent['name'], status='draft', scope=scope,
                        condition=intent['condition'], priceMode=mode, observationKind=None,
                        notificationPolicy='on_reentry', createdAt=stamp, updatedAt=stamp, lastCheckAt=None,
                        unavailableReason='请选择价格提醒口径' if mode is None else None)
            _put(db, 'reminder', rule)
            _put(db, 'reminder_create_request', dict(id=request_id, intent=intent, result=rule))
            return rule

    def update(self, params, delete=False):
        allowed = {'ruleId', 'expectedVersion'} if delete else {'ruleId', 'expectedVersion', 'name', 'condition', 'status', 'priceMode'}
        if set(params) - allowed or not {'ruleId', 'expectedVersion'} <= set(params):
            raise ValueError('提醒修改字段无效')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rule = _get(db, 'reminder', params['ruleId'])
            if type(params['expectedVersion']) is not int or params['expectedVersion'] != rule['version']:
                raise ValueError('提醒版本冲突，请重新读取后再修改')
            if rule['status'] == 'deleted': raise ValueError('提醒已删除，历史记录仍保留')
            original = deepcopy(rule)
            if delete:
                rule['status'] = 'deleted'
            else:
                if 'status' in params:
                    if params['status'] not in {'draft', 'paused', 'enabled'}:
                        raise ValueError('未知提醒状态')
                    rule['status'] = params['status']
                if 'priceMode' in params:
                    if params['priceMode'] not in ('intraday', 'daily_close'): raise ValueError('请选择盘中或收盘提醒')
                    rule['priceMode'] = params['priceMode']
                    rule['observationKind'] = None
                if 'name' in params: rule['name'] = _text(params['name'], '提醒名称')
                if 'condition' in params: rule['condition'] = _condition(params['condition'])
                if rule['status'] == 'enabled' and rule['priceMode'] not in ('intraday', 'daily_close'):
                    raise ValueError('请先选择盘中或收盘口径，当前不能启用')
                rule['unavailableReason'] = None if rule['priceMode'] else '请选择价格提醒口径'
            rule.update(version=rule['version'] + 1, updatedAt=now())
            if rule['condition'] == original['condition'] and rule['priceMode'] == original['priceMode']:
                old_id = rule['id'] + ':' + str(original['version'])
                old_state = db.execute("SELECT body FROM records WHERE kind='reminder_state' AND id=?", (old_id,)).fetchone()
                if old_state:
                    copied = json.loads(old_state[0])
                    copied['id'] = rule['id'] + ':' + str(rule['version'])
                    _put(db, 'reminder_state', copied)
            return _put(db, 'reminder', rule)

    def check(self, params):
        if set(params) != {'ruleId', 'requestId'}:
            raise ValueError('检查仅接受ruleId和requestId，不能提交外部观察或报价')
        request_id = _text(params['requestId'], '请求标识')
        _text(params['ruleId'], '规则标识')
        with self.lock:
            self.start(self.service)
            if request_id in self.pending:
                intent, future = self.pending[request_id]
                if intent != params: raise ValueError('同一requestId不能检查不同提醒')
            else:
                future = Future()
                try: self.tasks.put_nowait((deepcopy(params), future))
                except queue.Full: raise ValueError('已有提醒检查等待，请稍后重试') from None
                self.pending[request_id] = (deepcopy(params), future)
        return future.result()

    def _perform(self, params, origin):
        from .storage_migration import location_scope
        manager = self.service.migrations if self.service else None
        with manager.request_scope('reminders.check') if manager else nullcontext(), location_scope(self.store):
            return self._perform_in_scope(params, origin)

    def _perform_in_scope(self, params, origin):
        from .reminder_source import unknown
        request_id = params['requestId']
        with self.store.connect() as db:
            row = db.execute("SELECT body FROM records WHERE kind='reminder_check_request' AND id=?", (request_id,)).fetchone()
            if row:
                record = json.loads(row[0])
                if record['ruleId'] != params['ruleId']: raise ValueError('同一requestId不能检查不同提醒')
                return _get(db, 'reminder_check', record['checkId'])
            rule = _get(db, 'reminder', params['ruleId'])
        if rule['status'] == 'deleted': raise ValueError('提醒已删除，不能继续检查')
        if origin == 'scheduled' and rule['status'] != 'enabled': raise ValueError('提醒未启用')
        symbols = rule['scope']['symbols']
        cursor_id = rule['id'] + ':' + rule['scope']['id']
        try: start = self.store.get('reminder_cursor', cursor_id)['offset'] % len(symbols)
        except ValueError: start = 0
        order = list(range(start, len(symbols))) + list(range(start))
        observations = []
        next_cursor = start
        exhausted = False
        deadline = time.monotonic() + 60
        for index in order:
            symbol = symbols[index]
            if self.stop.is_set(): raise ValueError('提醒服务已停止')
            latest = self.store.get('reminder', rule['id'])
            if latest['version'] != rule['version'] or latest['status'] != rule['status']:
                observations.append(unknown(symbol, rule['priceMode'], 'rule_changed'))
                continue
            if rule['priceMode'] is None:
                obs = unknown(symbol, None, 'mode_pending')
                obs['reasonCodes'].append('source_unavailable')
            elif time.monotonic() >= deadline:
                if not exhausted: next_cursor = index
                exhausted = True
                obs = unknown(symbol, rule['priceMode'], 'check_budget_exhausted')
            else:
                try: obs = self.observe(self.store, symbol, rule['priceMode'], self.stop)
                except Exception: obs = unknown(symbol, rule['priceMode'], 'source_error')
            if obs.get('symbol') != symbol:
                obs = unknown(symbol, rule['priceMode'], 'identity_mismatch')
            observations.append(obs)
        by_symbol = {obs['symbol']: obs for obs in observations}
        observations = [by_symbol[symbol] for symbol in symbols]
        stamp = now()
        # Close and commit serialize: once close sets stop, no new result is committed.
        with self.lock, self.store.connect() as db:
            if self.stop.is_set(): raise ValueError('提醒服务已停止')
            db.execute('BEGIN IMMEDIATE')
            current = _get(db, 'reminder', rule['id'])
            superseded = current['version'] != rule['version'] or current['status'] != rule['status']
            state_id = rule['id'] + ':' + str(rule['version'])
            saved = db.execute("SELECT body FROM records WHERE kind='reminder_state' AND id=?", (state_id,)).fetchone()
            state = json.loads(saved[0]) if saved else dict(id=state_id, symbols={})
            rows = []
            baseline = self.baseline.get(rule['id'], set()) if origin == 'scheduled' else set()
            for obs in observations:
                symbol = obs['symbol']
                calendar = obs.pop('_calendar', None)
                expected_day = None
                if obs.get('validity') == 'valid':
                    from .reminder_source import target_day
                    from zoneinfo import ZoneInfo
                    expected_day, boundary_reason = target_day(calendar, _time(stamp).astimezone(ZoneInfo('Asia/Shanghai')), rule['priceMode'])
                    if boundary_reason:
                        obs.update(validity='unknown', reasonCodes=[boundary_reason])
                    elif obs.get('sourceTradeDate') != expected_day:
                        obs.update(validity='unknown', reasonCodes=['stale'])
                if superseded:
                    result, reasons = 'unknown', ['rule_changed']
                else:
                    result, updated, reasons = evaluate_observation(rule['condition'], obs, state['symbols'].get(symbol, {}), checked_at=stamp, max_age_seconds=180, expected_trade_date=expected_day)
                    if symbol in baseline and result == 'triggered':
                        result, reasons = 'not_triggered', ['startup_baseline']
                    state['symbols'][symbol] = updated
                rows.append(dict(symbol=symbol, result=result, observation=obs, reasonCodes=reasons, notified=False))
            result = dict(id=identifier(), ruleId=rule['id'], ruleVersion=rule['version'], snapshotId=rule['scope']['id'],
                          checkedAt=stamp, origin=origin, rows=rows)
            _put(db, 'reminder_check', result)
            _put(db, 'reminder_check_request', dict(id=request_id, ruleId=rule['id'], checkId=result['id']))
            if not superseded:
                _put(db, 'reminder_state', state)
                _put(db, 'reminder_cursor', dict(id=cursor_id, offset=next_cursor))
                current['lastCheckAt'] = stamp
                current['observationKind'] = 'minute_close' if rule['priceMode'] == 'intraday' else 'daily_close' if rule['priceMode'] else None
                current['unavailableReason'] = '；'.join(dict.fromkeys(reason for row in rows if row['result'] == 'unknown' for reason in row['reasonCodes'])) or None
                _put(db, 'reminder', current)
                for row in rows:
                    if row['result'] != 'unknown': baseline.discard(row['symbol'])
            self.last_check_at = stamp
        return result

    def history(self, params):
        offset, limit = params.get('offset', 0), params.get('limit', 50)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('分页offset须非负，limit须为1至200')
        with self.store.connect() as db:
            _get(db, 'reminder', params['ruleId'])
            where = "kind='reminder_check' AND json_extract(body,'$.ruleId')=?"
            total = db.execute('SELECT count(*) FROM records WHERE ' + where, (params['ruleId'],)).fetchone()[0]
            rows = db.execute('SELECT body FROM records WHERE ' + where + " ORDER BY json_extract(body,'$.checkedAt') DESC,id DESC LIMIT ? OFFSET ?", (params['ruleId'], limit, offset)).fetchall()
        return dict(items=[json.loads(row[0]) for row in rows], total=total, offset=offset, limit=limit)

    def dispatch(self, method, params):
        if method == 'reminders.scope.preview': return self.preview(params)
        if method == 'reminders.create': return self.create(params)
        if method == 'reminders.list':
            if set(params) - {'includeDeleted'} or type(params.get('includeDeleted', False)) is not bool:
                raise ValueError('includeDeleted须为布尔值')
            return [r for r in self.store.list('reminder') if params.get('includeDeleted', False) or r['status'] != 'deleted']
        if method == 'reminders.get': return self.store.get('reminder', params['ruleId'])
        if method == 'reminders.update': return self.update(params)
        if method == 'reminders.delete': return self.update(params, delete=True)
        if method == 'reminders.check': return self.check(params)
        if method == 'reminders.history': return self.history(params)
        if method == 'reminders.runtime': return self.runtime()
        raise ValueError('未知提醒操作')
