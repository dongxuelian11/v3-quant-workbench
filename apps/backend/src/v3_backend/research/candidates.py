"""Editable research candidates, separate from the active strategy draft."""
from copy import deepcopy
from pathlib import Path

from .storage import identifier, now
from .workbench import get_strategy, _save_strategy

KINDS = {'factor': 'factor.analyze', 'model': 'model.train', 'strategy': 'backtest.run'}


def _merge(base, patch):
    result = deepcopy(base) if isinstance(base, dict) else {}
    for key, value in patch.items():
        result[key] = _merge(result.get(key), value) if isinstance(value, dict) else deepcopy(value)
    return result


def get(store, project_id, candidate_id):
    return store.project_store(project_id).get('candidate', candidate_id)


def save(store, project_id, supplied):
    if not project_id:
        raise ValueError('请为候选选择研究项目')
    old = get(store, project_id, supplied['id']) if supplied.get('id') else None
    value = deepcopy(old) if old else dict(id=identifier(), projectId=project_id, createdAt=now(), revision=0, experiments=[])
    fields = ('strategyId', 'kind', 'name', 'description', 'changeSummary', 'spec', 'sourceConversationId', 'parentId', 'citations', 'sourceLibraryId')
    for key in fields:
        if key in supplied:
            value[key] = deepcopy(supplied[key])
    if value.get('kind') not in KINDS or not str(value.get('name', '')).strip():
        raise ValueError('候选需要名称和因子、模型或策略类型')
    if value.get('citations'):
        from .reports import validate_citations
        validate_citations(store, value['citations'])
    strategy_id = value.get('strategyId')
    if not strategy_id and value['kind'] != 'factor':
        raise ValueError('请明确候选关联的研究策略')
    strategy = get_strategy(store, project_id, strategy_id) if strategy_id else store.project(project_id)
    spec = value.get('spec')
    if not isinstance(spec, dict) or not isinstance(spec.get('parameters'), dict) or spec.get('kind') != KINDS[value['kind']]:
        raise ValueError('候选运行配置与类型不一致')
    if old is None:
        section = {'factor': 'factorAnalysis', 'model': 'model', 'strategy': 'backtest'}[value['kind']]
        base = deepcopy(strategy['settings'].get(section, {}))
        for source, target in (('selectedFactors', 'factorIds'), ('factorProcessing', 'factorProcessing'), ('customFactors', 'customFactors')):
            if source in strategy['settings']:
                base[target] = deepcopy(strategy['settings'][source])
        spec['parameters'] = _merge(base, spec['parameters'])
    spec.update(projectId=project_id, strategyId=strategy_id)
    for key in ('candidateId', 'candidateSnapshot', 'projectSnapshot', 'strategySnapshots', 'positionsSnapshot'):
        spec.pop(key, None)
    if not old or any(value.get(key) != old.get(key) for key in fields):
        value['revision'] += 1
    value['updatedAt'] = now()
    return store.project_store(project_id).put('candidate', value, project_id)


def adopt(store, project_id, candidate_id, strategy_id=None):
    from .jobs import validate_spec
    value = get(store, project_id, candidate_id)
    target = strategy_id or value.get('strategyId')
    if not target:
        raise ValueError('因子候选可独立研究；采用到策略前请先关联目标策略')
    if value['kind'] != 'factor' and target != value.get('strategyId'):
        raise ValueError('非因子候选只能采用到原关联策略')
    spec = validate_spec(deepcopy(value['spec']))
    strategy = get_strategy(store, project_id, target)
    params = spec['parameters']
    section = {'factor': 'factorAnalysis', 'model': 'model', 'strategy': 'backtest'}[value['kind']]
    patch = {section: deepcopy(params)}
    if 'factorIds' in params:
        patch['selectedFactors'] = deepcopy(params['factorIds'])
    if 'factorProcessing' in params:
        patch['factorProcessing'] = deepcopy(params['factorProcessing'])
    if 'customFactors' in params:
        if not isinstance(params['customFactors'], list):
            raise ValueError('自定义因子应为数组')
        replacements = {factor['id']: factor for factor in params['customFactors']}
        patch['customFactors'] = [factor for factor in strategy['settings'].get('customFactors', []) if factor['id'] not in replacements] + list(replacements.values())
    updated = _save_strategy(store, {'projectId': project_id, 'strategy': {'id': strategy['id']}, 'settingsPatch': patch})
    value.update(adoptedAt=now(), adoptedRevision=value['revision'], adoptedTarget={'projectId': project_id, 'strategyId': target})
    store.project_store(project_id).put('candidate', value, project_id)
    return {'candidate': value, 'strategy': updated}


def link_experiment(store, project_id, candidate_id, experiment_id, revision):
    value = get(store, project_id, candidate_id)
    link = dict(projectId=project_id, experimentId=experiment_id, revision=revision)
    value['experiments'] = [item for item in value.get('experiments', []) if item['experimentId'] != experiment_id] + [link]
    store.project_store(project_id).put('candidate', value, project_id)


def _code_target(value, factor_id=None):
    params = value['spec']['parameters']
    if factor_id:
        target = next((factor for factor in params.get('customFactors', []) if factor.get('id') == factor_id), None)
        if target is None:
            raise ValueError('候选中没有这个因子')
    else:
        if value['kind'] != 'model':
            raise ValueError('请选择要编辑的因子')
        target = params
    if not target.get('codePath'):
        raise ValueError('此候选没有保存的 Python 源码')
    return target


def code_get(store, project_id, candidate_id, factor_id=None):
    value = get(store, project_id, candidate_id)
    target = _code_target(value, factor_id)
    root = Path(store.project(project_id)['path']).resolve()
    path = (root / target['codePath']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('候选的 Python 源文件不存在于当前项目')
    return dict(candidateId=value['id'], revision=value['revision'], factorId=factor_id,
                language='python', path=path.relative_to(root).as_posix(), content=path.read_text(encoding='utf-8'))


def code_save(store, project_id, candidate_id, content, factor_id=None):
    if not isinstance(content, str) or not content.strip():
        raise ValueError('Python 源码不能为空')
    # Check syntax without importing or running generated code in the desktop service.
    try:
        compile(content, '<candidate>', 'exec')
    except SyntaxError as error:
        raise ValueError(f'Python 第 {error.lineno} 行语法错误：{error.msg}') from error
    value = deepcopy(get(store, project_id, candidate_id))
    target = _code_target(value, factor_id)
    previous = code_get(store, project_id, candidate_id, factor_id)
    if content == previous['content']:
        return {'candidate': value, 'code': previous}
    root = Path(store.project(project_id)['path']).resolve()
    folder = root / 'candidates' / value['id'] / 'code'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (identifier() + '.py')
    path.write_text(content, encoding='utf-8')
    target['codePath'] = path.relative_to(root).as_posix()
    if value['kind'] == 'model' and value['spec']['parameters'].get('model') == 'native_generated_predictions':
        value['spec']['parameters']['model'] = 'native_torch'
        for key in ('nativeSourcePath', 'dataPath', 'trainingEventsPath'):
            value['spec']['parameters'].pop(key, None)
    saved = save(store, project_id, value)
    return {'candidate': saved, 'code': code_get(store, project_id, candidate_id, factor_id)}


def dispatch(store, method, params):
    if method.startswith('candidates.library.'):
        from .candidate_library import dispatch as library_dispatch
        return library_dispatch(store, method, params)
    project_id = params.get('projectId')
    if method == 'candidates.list':
        items = store.project_store(project_id).list('candidate', project_id)
        return [item for item in items if not params.get('strategyId') or item.get('strategyId') == params['strategyId']]
    if method == 'candidates.get':
        return get(store, project_id, params['candidateId'])
    if method == 'candidates.save':
        return save(store, project_id, params['candidate'])
    if method == 'candidates.code.get':
        return code_get(store, project_id, params['candidateId'], params.get('factorId'))
    if method == 'candidates.code.save':
        return code_save(store, project_id, params['candidateId'], params.get('content'), params.get('factorId'))
    if method == 'candidates.adopt':
        return adopt(store, project_id, params['candidateId'], params.get('strategyId'))
    raise ValueError('未知候选操作')
