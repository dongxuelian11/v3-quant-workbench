"""Explicit selection of a project's imported historical membership version."""
from copy import deepcopy
from pathlib import Path
from . import history
from .storage import read_json


def dispatch(store, method, params):
    project_id = params.get('projectId')
    if not project_id:
        raise ValueError('请选择成员记录所属的研究项目')
    project = store.project(project_id)
    if method == 'history.memberships.list':
        result = []
        for path in (Path(project['path']) / 'data/memberships').glob('*/*/source.json'):
            metadata = read_json(path, {})
            ref = {key: metadata.get(key) for key in ('poolId', 'version', 'source')}
            query = deepcopy(project)
            query['universe']['membershipRef'] = ref
            frame = history.membership_frame(query)
            result.append(dict(membershipRef=ref, observedAt=metadata.get('observedAt'), rows=len(frame),
                symbols=int(frame.symbol.nunique()), startDate=str(frame.startDate.min())[:10] if len(frame) else None,
                endDate=None if frame.endDate.isna().any() or frame.empty else str(frame.endDate.max())[:10]))
        return sorted(result, key=lambda item: item.get('observedAt') or '', reverse=True)
    if method != 'history.memberships.apply':
        raise ValueError('未知成员版本操作')
    strategy_id = params.get('strategyId')
    if strategy_id:
        from .workbench import get_strategy
        current = get_strategy(store, project_id, strategy_id)['universe']
    else:
        current = project['universe']
    universe = deepcopy(current)
    ref = params.get('membershipRef')
    if ref is None:
        universe.pop('membershipRef', None)
    else:
        universe['membershipRef'] = deepcopy(ref)
        history.membership_frame({**project, 'universe': universe})
    if strategy_id:
        from .workbench import _save_strategy
        _save_strategy(store, {'projectId': project_id, 'strategy': {'id': strategy_id, 'universe': universe}})
    else:
        store.save_project({**project, 'universe': universe})
    return universe
