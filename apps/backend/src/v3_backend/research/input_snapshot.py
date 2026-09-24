"""Necessary run inputs stored beside results, without mutable cache references."""
from copy import deepcopy
from pathlib import Path
import shutil
import importlib.metadata

from . import data, history
from .storage import read_json, write_json, now


def capture(store, project, params, directory, prepared, *, output_root=None):
    import pandas as pd
    directory = Path(directory)
    storage_root = Path(output_root or project['path'])
    root = directory / 'inputs'
    target = root / 'data'
    target.mkdir(parents=True, exist_ok=False)
    source = Path(data.project_data(project)['path']) / 'data'
    start = prepared.get('inputStart') or prepared.get('effectiveStart') or params.get('startDate')
    end = prepared.get('inputEnd') or prepared.get('effectiveEnd') or params.get('endDate')
    codes = prepared.get('actualCoverage', {}).get('symbols') or project['universe'].get('symbols')
    codes = set(map(data.symbol, codes)) if codes else None
    inventory = []
    captured_symbols = set()
    from .engines import input_file_state
    source_state = input_file_state(source)
    if project.get('inputCacheIdentity') is not None and source_state == project.get('inputCacheFiles'):
        # A reproduced snapshot inherits its recorded source version, never live source stats.
        cache_identity = deepcopy(project['inputCacheIdentity'])
    else:
        local = Path(project.get('inputDataRoot') or project['path']) / 'data'
        local_state = []
        for name in ('memberships', 'history'):
            folder = local / name
            if folder != source / name and folder.exists():
                local_state.extend([[name+'/'+row[0],*row[1:]] for row in input_file_state(folder)])
        cache_identity = dict(sourceRoot=str(source.resolve()), sourceFiles=source_state,
            localRoot=str(local.resolve()), localMembershipIndustryFiles=local_state)

    def save(frame, relative, date_key=None, lower=False):
        if codes and 'symbol' in frame:
            frame = frame[frame.symbol.isin(codes)]
        if date_key and date_key in frame:
            dates = pd.to_datetime(frame[date_key])
            if end:
                frame = frame[dates.le(end)]
            if lower and start:
                frame = frame[pd.to_datetime(frame[date_key]).ge(start)]
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        inventory.append(dict(path=path.relative_to(root).as_posix(), rows=len(frame)))

    def capture_table(kind, date_key, lower=False):
        import pyarrow.parquet as pq
        paths = ([source / f'{kind}.parquet'] if (source / f'{kind}.parquet').exists() else [])
        paths += sorted((source / kind).glob('*.parquet'))
        if not paths:
            raise ValueError('所需输入数据不可用：' + kind)
        selected_codes = codes
        if selected_codes is None:
            selected_codes = set()
            for path in paths:
                for batch in pq.ParquetFile(path).iter_batches(columns=['symbol'], batch_size=8192):
                    selected_codes.update(batch.column(0).to_pylist())
        # Read one security at a time. Legacy monolithic tables remain supported,
        # and later partition records override legacy rows as in data.read_table.
        legacy = source / f'{kind}.parquet'
        by_code, common = {}, []
        for path in paths:
            if path == legacy or not (len(path.stem) == 8 and path.stem[:2] in {'SH','SZ','BJ'} and path.stem[2:].isdigit()):
                common.append(path)
            else:
                by_code.setdefault(path.stem, []).append(path)
        for code in sorted(selected_codes):
            frames = []
            for path in common + by_code.get(code, []):
                filters = [('symbol', '=', code)]
                if end:
                    filters.append((date_key, '<=', pd.Timestamp(end)))
                if lower and start:
                    filters.append((date_key, '>=', pd.Timestamp(start)))
                frames.append(pd.read_parquet(path, filters=filters))
            if frames:
                frame = data.normalize(pd.concat(frames, ignore_index=True), kind)[0]
                if len(frame):
                    if kind == 'prices':captured_symbols.add(code)
                    save(frame, Path(kind) / f'{code}.parquet')

    capture_table('prices', 'date', True)
    if (source / 'financials.parquet').exists() or (source / 'financials').is_dir():
        capture_table('financials', 'announcementDate')
    if (source / 'trading_status.parquet').exists():
        save(pd.read_parquet(source / 'trading_status.parquet'), 'trading_status.parquet', 'date', True)
    for name, date_key in [('securities', None), ('corporate_actions', None), ('benchmark_weights', 'effectiveDate')]:
        path = source / (name + '.parquet')
        if path.exists():
            save(pd.read_parquet(path), path.name, date_key)
    # Benchmark securities are not members of the stock universe.
    for path in (source / 'benchmarks').glob('*.parquet'):
        frame = pd.read_parquet(path)
        if 'date' in frame:
            frame = frame[pd.to_datetime(frame.date).le(end)] if end else frame
            frame = frame[pd.to_datetime(frame.date).ge(start)] if start else frame
        destination = target / 'benchmarks' / path.name
        destination.parent.mkdir(exist_ok=True)
        frame.to_parquet(destination, index=False)
        inventory.append(dict(path=destination.relative_to(root).as_posix(), rows=len(frame)))
    for name in ('source.json', 'trading-calendar.json', 'corporate_actions_source.json'):
        if (source / name).exists():
            shutil.copy2(source / name, target / name)
    for name in ('csi300', 'csi500', 'industry'):
        frame = history.read(project, name)
        if end and len(frame):
            frame = frame[pd.to_datetime(frame.effectiveDate).le(end)]
        write_json(target / 'history' / (name + '_snapshot.json'), {'source': name, 'rows': frame.to_dict('records')})
    ref = project['universe'].get('membershipRef')
    if ref:
        frame = history.membership_frame(project)
        member_root = target / 'memberships' / ref['poolId'] / ref['version']
        member_root.mkdir(parents=True)
        frame.to_parquet(member_root / 'members.parquet', index=False)
        write_json(member_root / 'source.json', ref)
    for path in (source / 'alternative').rglob('*.parquet'):
        save(pd.read_parquet(path), path.relative_to(source), 'date')
    for path in (source / 'alternative').rglob('*.json'):
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    frozen_params = deepcopy(params)
    files = {}
    def freeze_files(value):
        if isinstance(value, list):
            for item in value: freeze_files(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in {'codePath', 'dataPath', 'trainingEventsPath'} and isinstance(item, str):
                    path = Path(item) if Path(item).is_absolute() else Path(project['path']) / item
                    if not path.is_file():
                        raise ValueError('所需输入文件不可用：' + item)
                    if str(path) not in files:
                        destination = root / 'files' / (str(len(files)) + path.suffix)
                        destination.parent.mkdir(exist_ok=True)
                        shutil.copy2(path, destination)
                        files[str(path)] = destination.relative_to(storage_root).as_posix()
                    value[key] = files[str(path)]
                else: freeze_files(item)
    freeze_files(frozen_params)
    prerequisites = {}
    def model_references(value):
        if isinstance(value, dict):
            if value.get('modelExperimentId'):
                yield value['modelExperimentId']
            for item in value.values():
                yield from model_references(item)
        elif isinstance(value, list):
            for item in value:
                yield from model_references(item)
    for model_index, model_id in enumerate(dict.fromkeys(model_references(params))):
        model = deepcopy(store.experiment(project['id'], model_id))
        for index, artifact in enumerate(model['artifacts']):
            path = store.artifact_path(project['id'], artifact)
            destination = root / 'prerequisites' / str(model_index) / (str(index) + path.suffix)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            artifact['path'] = destination.relative_to(storage_root).as_posix()
        prerequisites[model_id] = model
    frozen = deepcopy(project)
    if output_root is not None:frozen['path'] = str(storage_root)
    frozen['inputDataRoot'] = str(root)
    frozen.setdefault('settings', {})['dataPath'] = str(target)
    frozen['inputPrerequisites'] = prerequisites
    cache_identity['slice'] = dict(startDate=start, endDate=end, symbols=sorted(captured_symbols))
    frozen['inputCacheIdentity'] = cache_identity
    frozen['inputCacheFiles'] = input_file_state(target)
    versions = {}
    for package in ('pandas', 'numpy', 'pyqlib', 'scikit-learn', 'scipy', 'lightgbm'):
        try: versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: pass
    listed = {entry['path'] for entry in inventory}
    for path in root.rglob('*'):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and relative not in listed:
            inventory.append(dict(path=relative))
    reference = dict(version=1, path=root.relative_to(storage_root).as_posix(), status='available',
                     startDate=start, endDate=end, createdAt=now(), files=inventory)
    write_json(root / 'snapshot.json', dict(reference=reference, project=frozen, parameters=frozen_params,
               dependencies=versions, seeds={'lightgbm': 42, 'optuna': 42}, prerequisiteExperimentIds=list(prerequisites)))
    return frozen, frozen_params, reference


def restore(store, project, experiment_id):
    experiment = store.experiment(project['id'], experiment_id)
    reference = experiment.get('inputSnapshot')
    if not reference or reference.get('status') != 'available':
        raise ValueError('旧实验没有完整固定输入，不能按原输入复现；请明确选择最新数据重算')
    root = (Path(project['path']) / reference['path']).resolve()
    if not root.is_relative_to(Path(project['path']).resolve()):
        raise ValueError('实验输入路径不属于当前项目')
    manifest = read_json(root / 'snapshot.json')
    if not manifest or not ((root / 'data/prices.parquet').exists() or any((root / 'data/prices').glob('*.parquet'))):
        raise ValueError('原实验输入文件缺失，不能切换为最新行情')
    for entry in reference.get('files', []):
        if not (root / entry['path']).is_file():
            raise ValueError('原实验输入文件缺失：' + entry['path'])
    frozen = manifest['project']
    frozen['path'] = project['path']
    frozen['inputDataRoot'] = str(root)
    frozen['settings']['dataPath'] = str(root / 'data')
    return frozen, manifest['parameters'], {**reference, 'sourceExperimentId': experiment_id}
