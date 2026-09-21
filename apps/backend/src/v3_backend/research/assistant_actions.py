"""Apply bounded local commands through existing drafts and research operations."""
from copy import deepcopy
from .storage import identifier


def apply(service, params):
    action = params.get('action') or {}
    kind, namespace = action.get('kind'), action.get('namespace')
    ids = action.get('objectIds') or []
    if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
        raise ValueError('请选择明确的研究对象')
    ids = list(dict.fromkeys(ids))
    if kind in {'clarify', 'handoff'}:
        return dict(kind=kind, message=str(action.get('question') or action.get('message') or '请补充研究条件'))
    if kind == 'search':
        return dict(kind='search', query=str(action.get('query') or ''), message='')
    if kind == 'navigation':
        screen = action.get('screen')
        if screen not in {'overview', 'screeners', 'daily', 'positions', 'research'}:
            raise ValueError('未知工作区')
        return dict(kind='navigation', screen=screen, objectIds=ids)
    if kind == 'filter_patch':
        if namespace != 'screeners':
            raise ValueError('条件修改仅用于选股草稿')
        from .screeners import normalize
        from .screen_conditions import validate
        previous = params.get('draft')
        if previous is None:
            if len(ids) != 1:
                return dict(kind='clarify', message='请先打开一个选股方案，或指定需要修改的方案')
            previous = service.store.get('screener', ids[0])
        previous = normalize(previous)
        if ids and ids != [previous.get('id')]:
            return dict(kind='clarify', message='指定方案与当前草稿不同，请先打开指定方案')
        patch = deepcopy(action.get('conditions'))
        validate(patch)
        if 'children' not in patch:
            patch = dict(id=identifier(), match='all', children=[patch])
        current = previous['conditions']
        # Replace simple same-field rules, retaining all unrelated draft configuration.
        # Editing inside an OR/nested group needs an explicit choice of that group.
        if current.get('children') and (current.get('match') != 'all' or patch.get('match') != 'all'
                or any('children' in rule for rule in current['children'] + patch.get('children', []))):
            return dict(kind='clarify', message='当前包含任一或嵌套条件，请在条件编辑器中指定要修改的组')
        def assign_ids(node):
            node.setdefault('id', identifier())
            for child in node.get('children', []):
                assign_ids(child)
        assign_ids(patch)
        fields = {rule.get('field') for rule in patch['children']}
        updated = deepcopy(previous)
        if not current.get('children'):
            updated['conditions'] = patch
        else:
            updated['conditions']['children'] = [rule for rule in current['children'] if rule.get('field') not in fields] + patch['children']
        return dict(kind='draft', draft=normalize(updated), previousDraft=previous,
                    message='条件已更新为草稿；未运行，可撤销')
    if kind != 'run' or namespace not in {'screeners', 'dailyPlans'} or not ids:
        raise ValueError('不支持的操作；请指定已有选股或每日方案')
    operation = params.get('operationId')
    if not isinstance(operation, str) or not 1 <= len(operation) <= 128:
        raise ValueError('缺少本次操作标识')
    # The existing queue persists the token with each submission, so a lost UI reply
    # can be recovered without launching an identical calculation.
    with service.jobs.lock:
        jobs = []
        targets = ids if namespace == 'screeners' else [','.join(sorted(ids))]
        for target in targets:
            token = operation + ':' + namespace + ':' + target
            existing = next((job for job in service.store.list('job')
                if job.get('spec', {}).get('parameters', {}).get('assistantOperationId') == token), None)
            if existing:
                jobs.append(existing)
                continue
            if namespace == 'screeners':
                job = service.request('screeners.run', dict(planId=target, assistantOperationId=token))
            else:
                for plan_id in ids:
                    if not service.store.get('daily_plan', plan_id).get('enabled'):
                        raise ValueError('每日方案尚未启用，请先明确启用')
                job = service.jobs.submit(dict(kind='selection.run', name='本地助手 · 每日研究',
                    parameters=dict(dailyPlanIds=ids, assistantOperationId=token)))
            jobs.append(job)
        return dict(kind='jobs', jobs=jobs, message='已提交，可在任务栏查看或取消')
