"""Reminder drafts and checks in the app database; no price feed or scheduler yet."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import re

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


def evaluate_observation(condition, observation, state, *, checked_at, max_age_seconds):
    """Internal pure evaluator. Adapters must establish validity; unknown never rearms.

    Returns result, new state, reasons. A trigger is not proof of notification delivery.
    This helper is not exposed through the protocol and does not fetch any data.
    """
    condition = _condition(condition)
    state = deepcopy(state)
    reasons = list(observation.get('reasonCodes') or [])
    price = observation.get('price')
    if observation.get('validity') != 'valid':
        reasons.append('invalid_observation')
    if type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
        reasons.append('invalid_price')
    if observation.get('priceBasis') != 'raw' or not observation.get('source') or not observation.get('id'):
        reasons.append('missing_provenance')
    try:
        observed = _time(observation['sourceTime'])
        age = (_time(checked_at) - observed).total_seconds()
        if not math.isfinite(max_age_seconds) or max_age_seconds < 0:
            raise ValueError('invalid age policy')
        if age < 0: reasons.append('future_time')
        elif age > max_age_seconds: reasons.append('stale')
        if state.get('sourceTime') and observed < _time(state['sourceTime']):
            reasons.append('out_of_order')
    except (KeyError, TypeError, ValueError):
        reasons.append('missing_source_time')
    if reasons:
        return 'unknown', state, list(dict.fromkeys(reasons))
    if state.get('observationId') == observation['id']:
        return 'not_triggered', state, ['duplicate_observation']
    if state.get('sourceTime') and observed == _time(state['sourceTime']):
        return 'not_triggered', state, ['duplicate_observation_time']
    satisfied = price >= condition['threshold'] if condition['operator'] == 'gte' else price <= condition['threshold']
    trigger = satisfied and not state.get('satisfied', False)
    state.update(satisfied=satisfied, observationId=observation['id'], sourceTime=observation['sourceTime'])
    return ('triggered' if trigger else 'not_triggered'), state, []


class Reminders:
    def __init__(self, store):
        self.store = store
        self.session_id = identifier()
        self.started_at = now()
        self.last_check_at = None

    def runtime(self):
        return dict(sessionId=self.session_id, sessionStartedAt=self.started_at,
                    running=False, lastCheckAt=self.last_check_at,
                    message='当前进程仅支持提醒草稿和手动可用性检查；真实来源与自动监控尚未启用。程序未运行期间没有监控，也不会补造触发记录。')

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
                        unavailableReason='真实行情来源尚未接入，自动监控未启用')
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
            if delete:
                rule['status'] = 'deleted'
            else:
                if 'status' in params:
                    if params['status'] not in {'draft', 'paused'}:
                        raise ValueError('真实来源尚未接入，仅允许草稿或暂停，不能启用')
                    rule['status'] = params['status']
                if 'priceMode' in params:
                    if params['priceMode'] not in ('intraday', 'daily_close'): raise ValueError('请选择盘中或收盘提醒')
                    rule['priceMode'] = params['priceMode']
                    rule['observationKind'] = None
                if 'name' in params: rule['name'] = _text(params['name'], '提醒名称')
                if 'condition' in params: rule['condition'] = _condition(params['condition'])
            rule.update(version=rule['version'] + 1, updatedAt=now())
            return _put(db, 'reminder', rule)

    def check(self, params):
        if set(params) != {'ruleId', 'requestId'}:
            raise ValueError('检查仅接受ruleId和requestId，不能提交外部观察或报价')
        request_id = _text(params['requestId'], '请求标识')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT body FROM records WHERE kind='reminder_check_request' AND id=?", (request_id,)).fetchone()
            if row:
                record = json.loads(row[0])
                if record['ruleId'] != params['ruleId']: raise ValueError('同一requestId不能检查不同提醒')
                return _get(db, 'reminder_check', record['checkId'])
            rule = _get(db, 'reminder', params['ruleId'])
            if rule['status'] == 'deleted': raise ValueError('提醒已删除，不能继续检查')
            stamp = now()
            reasons = ['mode_pending', 'source_unavailable'] if rule['priceMode'] is None else ['source_unavailable']
            rows = []
            for symbol in rule['scope']['symbols']:
                observation = dict(id=identifier(), symbol=symbol, kind=None, price=None, priceBasis='raw',
                                   source=None, sourceTime=None, sourceTradeDate=None, fetchedAt=None,
                                   validity='unknown', reasonCodes=reasons)
                rows.append(dict(symbol=symbol, result='unknown', observation=observation, reasonCodes=reasons, notified=False))
            result = dict(id=identifier(), ruleId=rule['id'], ruleVersion=rule['version'], snapshotId=rule['scope']['id'],
                          checkedAt=stamp, origin='manual', rows=rows)
            _put(db, 'reminder_check', result)
            _put(db, 'reminder_check_request', dict(id=request_id, ruleId=rule['id'], checkId=result['id']))
            rule['lastCheckAt'] = stamp
            _put(db, 'reminder', rule)
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
