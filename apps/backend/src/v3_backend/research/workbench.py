"""Small portable strategy records and application-wide workspace objects."""
from copy import deepcopy
import math
from pathlib import Path

from .storage import identifier, now, read_json


def _name(value, fallback=''):
    name = str(value or fallback).strip()
    if not name:
        raise ValueError('请填写名称')
    return name


def _universe(value):
    from .data import symbol
    value = deepcopy(value)
    if not isinstance(value, dict) or not isinstance(value.get('symbols'), list):
        raise ValueError('股票池格式无效')
    if value.get('source') not in {'manual', 'all', 'csi300', 'csi500'}:
        raise ValueError('未知股票池来源')
    value['symbols'] = list(dict.fromkeys(symbol(item) for item in value['symbols']))
    return value


def _strategy_store(store, project_id):
    project = store.project(project_id)
    portable = store.project_store(project_id)
    try:
        portable.get('workbench', 'strategies')
    except ValueError:
        # Old project files and experiments remain untouched. The migration marker
        # prevents a deliberately deleted last strategy reappearing on next open.
        settings = deepcopy(project.get('settings', {}))
        value = dict(id='default', projectId=project_id, name='默认策略',
                     createdAt=project.get('createdAt', now()), updatedAt=now(),
                     universe=deepcopy(project['universe']), settings=settings,
                     enabled=bool(settings.get('selection', {}).get('enabled')), allocation=0.)
        if value['enabled']:
            value['active'] = dict(universe=deepcopy(value['universe']), settings=deepcopy(settings), updatedAt=now())
        portable.put('strategy', value, project_id)
        portable.put('workbench', dict(id='strategies', createdAt=now()), project_id)
    return portable


def list_strategies(store, project_id=None):
    if project_id:
        return _strategy_store(store, project_id).list('strategy', project_id)
    values = []
    for project in store.list('project'):
        try:
            values.extend(list_strategies(store, project['id']))
        except (ValueError, FileNotFoundError):
            # A removable project folder can be unavailable while global work continues.
            continue
    return values


def get_strategy(store, project_id, strategy_id=None):
    return _strategy_store(store, project_id).get('strategy', strategy_id or 'default')


def strategy_project(store, project_id, strategy_id=None, active=False):
    """Return a detached config; callers freeze this at submission, not at execution."""
    project = deepcopy(store.project(project_id))
    strategy = get_strategy(store, project_id, strategy_id)
    config = strategy
    if active:
        if not strategy['enabled'] or not strategy.get('active'):
            raise ValueError(f'策略“{strategy["name"]}”尚未应用到每日选股')
        config = strategy['active']
    project['universe'] = deepcopy(config['universe'])
    data_path = project.get('settings', {}).get('dataPath')
    project['settings'] = deepcopy(config['settings'])
    if data_path is not None:
        project['settings']['dataPath'] = data_path
    project['strategyId'] = strategy['id']
    project['strategyName'] = strategy['name']
    return project


def _create_strategy(store, params):
    project_id = params['projectId']
    project = store.project(project_id)
    portable = _strategy_store(store, project_id)
    original = get_strategy(store, project_id, params['fromStrategyId']) if params.get('fromStrategyId') else project
    timestamp = now()
    value = dict(id=identifier(), projectId=project_id, name=_name(params.get('name'), '新策略'),
                 createdAt=timestamp, updatedAt=timestamp, universe=deepcopy(original['universe']),
                 settings=deepcopy(original.get('settings', {})), enabled=False, allocation=0.)
    return portable.put('strategy', value, project_id)


def _save_strategy(store, params):
    supplied = params['strategy']
    project_id = params.get('projectId') or supplied['projectId']
    old = get_strategy(store, project_id, supplied['id'])
    # Autosaving a stale editor must not overwrite the independently activated plan.
    for key in ('name', 'universe', 'settings'):
        if key in supplied:
            old[key] = deepcopy(supplied[key])
    old['name'] = _name(old['name'])
    old['universe'] = _universe(old['universe'])
    if not isinstance(old['settings'], dict):
        raise ValueError('策略设置格式无效')
    old['updatedAt'] = now()
    return store.project_store(project_id).put('strategy', old, project_id)


def _activate_strategy(store, params):
    project_id = params['projectId']
    value = get_strategy(store, project_id, params['strategyId'])
    if 'allocation' in params:
        allocation = float(params['allocation'])
        if not math.isfinite(allocation) or not 0 <= allocation <= 1:
            raise ValueError('资金占比应在 0% 到 100% 之间')
        value['allocation'] = allocation
    if 'enabled' in params:
        value['enabled'] = bool(params['enabled'])
    elif 'allocation' not in params:
        value['enabled'] = True
    # An allocation-only edit changes its budget, not the strategy it will run.
    if value['enabled'] and ('enabled' in params or 'allocation' not in params):
        value['active'] = dict(universe=deepcopy(value['universe']), settings=deepcopy(value['settings']), updatedAt=now())
    value['updatedAt'] = now()
    return store.project_store(project_id).put('strategy', value, project_id)


def workspace(store, patch=None):
    defaults = dict(theme='light', density='comfortable', sidebarWidth=224, aiWidth=360,
                    windows=[], presets={}, tablePreferences={})
    try:
        saved = store.get('workspace', 'current')
    except ValueError:
        saved = {}
    value = {**defaults, **saved}
    if patch is not None:
        for key in ('theme', 'density', 'sidebarWidth', 'aiWidth', 'windows', 'activeConversationId'):
            if key in patch:
                value[key] = deepcopy(patch[key])
        for key in ('presets', 'tablePreferences'):
            if key in patch:
                value[key] = {**value.get(key, {}), **deepcopy(patch[key])}
        if value['theme'] not in {'light', 'dark'} or value['density'] not in {'comfortable', 'compact'}:
            raise ValueError('未知主题或表格密度')
        store.put('workspace', {**value, 'id': 'current'})
    value.pop('id', None)
    return value


def _state(value=None):
    return dict(messages=[], phase='', proposals=[], stageJobIds=[], mode='assist') | deepcopy(value or {})


def _legacy_conversations(store):
    for project in store.list('project'):
        key = 'legacy-' + project['id']
        try:
            store.get('conversation-migration', key)
            continue
        except ValueError:
            pass
        original = read_json(Path(project['path']) / 'ai' / 'conversation.json')
        if original is None:
            continue
        timestamp = original.get('updatedAt') or now()
        value = dict(id=key, name=f'{project["name"]} · 历史研究',
                     context=[dict(kind='strategy', projectId=project['id'], strategyId='default', title=project['name'])],
                     state=_state(original), createdAt=timestamp, updatedAt=timestamp)
        store.put('conversation', value)
        store.put('conversation-migration', dict(id=key, createdAt=now()))


def get_conversation(store, conversation_id):
    _legacy_conversations(store)
    return store.get('conversation', conversation_id)


def save_conversation(store, record):
    old = get_conversation(store, record['id'])
    for key in ('name', 'context'):
        if key in record:
            old[key] = deepcopy(record[key])
    old['name'] = _name(old['name'])
    if not isinstance(old['context'], list):
        raise ValueError('研究关联对象格式无效')
    if 'state' in record:
        old['state'] = {**_state(old.get('state')), **deepcopy(record['state'])}
    old['updatedAt'] = now()
    return store.put('conversation', old)


def dispatch(service, method, params):
    """Return (handled, result); no new queue or service layer."""
    store, p = service.store, params or {}
    if method == 'strategies.list':
        return True, list_strategies(store, p.get('projectId'))
    if method == 'strategies.create':
        return True, _create_strategy(store, p)
    if method == 'strategies.save':
        return True, _save_strategy(store, p)
    if method == 'strategies.activate':
        return True, _activate_strategy(store, p)
    if method == 'strategies.delete':
        portable = _strategy_store(store, p['projectId'])
        portable.delete('strategy', p['strategyId'])
        return True, {'deleted': True}
    if method in {'workspace.get', 'workspace.save'}:
        return True, workspace(store, p.get('state') if method == 'workspace.save' else None)
    if method.startswith(('watchlists.', 'screeners.')):
        kind = 'watchlist' if method.startswith('watchlists.') else 'screener'
        operation = method.rsplit('.', 1)[1]
        if operation == 'list':
            return True, store.list(kind)
        if operation == 'delete':
            store.delete(kind, p['id'])
            return True, {'deleted': True}
        if operation == 'save':
            value = deepcopy(p[kind])
            value['id'] = value.get('id') or identifier()
            value['name'] = _name(value.get('name'))
            value['updatedAt'] = now()
            if kind == 'watchlist':
                from .data import symbol
                value['symbols'] = list(dict.fromkeys(symbol(item) for item in value.get('symbols', [])))
            elif not isinstance(value.get('query'), dict):
                raise ValueError('筛选条件格式无效')
            return True, store.put(kind, value)
    if method.startswith('ai.conversations.'):
        _legacy_conversations(store)
        operation = method.rsplit('.', 1)[1]
        if operation == 'list':
            values = sorted(store.list('conversation'), key=lambda item: item['updatedAt'], reverse=True)
            if p.get('search'):
                text = str(p['search']).casefold()
                values = [item for item in values if text in item['name'].casefold() or any(text in str(row.get('content', '')).casefold() for row in item['state']['messages'])]
            return True, values
        if operation == 'get':
            return True, get_conversation(store, p['conversationId'])
        if operation == 'create':
            timestamp = now()
            value = dict(id=identifier(), name=_name(p.get('name'), '新研究会话'), context=deepcopy(p.get('context', [])),
                         state=_state(), createdAt=timestamp, updatedAt=timestamp)
            return True, store.put('conversation', value)
        if operation == 'save':
            return True, save_conversation(store, p['conversation'])
        if operation == 'delete':
            store.delete('conversation', p['conversationId'])
            return True, {'deleted': True}
    return False, None
