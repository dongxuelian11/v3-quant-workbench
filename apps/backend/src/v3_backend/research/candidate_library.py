"""Personal reusable research drafts; importing always creates an independent copy."""
from copy import deepcopy
from pathlib import Path
import shutil
from .storage import identifier, now


def _copy_files(value, source_root, target_root, relative_root):
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key in {'codePath', 'dataPath', 'trainingEventsPath'} and item:
                source = (source_root / item).resolve()
                if not source.is_relative_to(source_root.resolve()) or not source.is_file():
                    raise ValueError('候选引用文件不在来源项目或库目录内：' + key)
                target = target_root / (identifier() + source.suffix)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                value[key] = target.relative_to(relative_root).as_posix()
            else:
                _copy_files(item, source_root, target_root, relative_root)
    elif isinstance(value, list):
        for item in value:
            _copy_files(item, source_root, target_root, relative_root)


def dispatch(store, method, params):
    from . import candidates
    if method == 'candidates.library.list':
        return store.list('candidate_library')
    if method == 'candidates.library.get':
        return store.get('candidate_library', params['libraryId'])
    if method == 'candidates.library.delete':
        store.delete('candidate_library', params['libraryId'])
        return {'deleted': True}
    if method == 'candidates.library.save':
        value = deepcopy(candidates.get(store, params['projectId'], params['candidateId']))
        if value['spec']['parameters'].get('model') == 'native_generated_predictions' and not value['spec']['parameters'].get('codePath'):
            raise ValueError('此原生模型缺少可复训源码，不能收藏为跨项目独立模型；原预测仍可在原实验查看')
        key = identifier()
        root = store.root / 'shared' / 'factor-library' / key
        _copy_files(value['spec'], Path(store.project(params['projectId'])['path']), root / 'code', root)
        item = dict(id=key, name=params.get('name') or value['name'], createdAt=now(),
                    sourceProjectId=params['projectId'], sourceCandidateId=value['id'], sourceRevision=value['revision'], candidate=value)
        return store.put('candidate_library', item)
    if method == 'candidates.library.import':
        item = store.get('candidate_library', params['libraryId'])
        pid = params['projectId']
        project = store.project(pid)
        if not pid:
            raise ValueError('请选择接收候选副本的研究项目')
        value = deepcopy(item['candidate'])
        value = {k: value[k] for k in ('kind', 'name', 'description', 'changeSummary', 'spec', 'citations') if k in value}
        strategy_id = params.get('strategyId')
        if value['kind'] != 'factor' and not strategy_id:
            raise ValueError('导入模型或策略候选前，请明确选择目标研究策略')
        if strategy_id:
            from .workbench import get_strategy
            get_strategy(store, pid, strategy_id)
        value.update(name=params.get('name') or item['name'], strategyId=strategy_id, sourceLibraryId=item['id'])
        value['spec'].pop('strategyId', None)
        value['spec']['projectId'] = pid
        model = value['spec']['parameters']
        if model.get('model') == 'native_generated_predictions':
            if not model.get('codePath'):
                raise ValueError('原生模型副本缺少可复训源码')
            model['model'] = 'native_torch'
            for key in ('nativeSourcePath', 'rdRequestId', 'sourceConversationId'):
                model.pop(key, None)
            value['changeSummary'] = (value.get('changeSummary') or '') + '\n跨项目副本须在目标项目重新训练；复制的原预测与训练记录仅为来源参考，不是本项目实验结果。'
        root = Path(project['path'])
        _copy_files(value['spec'], store.root / 'shared' / 'factor-library' / item['id'], root / 'candidates' / 'library-copies' / identifier(), root)
        return candidates.save(store, pid, value)
    raise ValueError('未知个人候选库操作')
