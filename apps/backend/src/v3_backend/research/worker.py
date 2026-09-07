"""One research experiment per isolated Python process."""
import sys
import traceback
from pathlib import Path
from .storage import Store, now, read_json, write_json


def run(directory):
    directory = Path(directory)
    request = read_json(directory / 'request.json')
    store = Store(request['appData'])
    job = request['job']
    project = store.project(job['projectId'])
    params = job['spec']['parameters']
    write_json(directory / 'project.json', project)

    def progress(value, message):
        write_json(directory / 'progress.json', {'progress': min(.99, max(0, value)), 'message': message})

    try:
        from . import data, engines
        if job['kind'] == 'data.import':
            details = data.import_files(project, params, progress)
            result = dict(metrics={}, artifacts=[], summary='数据导入完成', details=details)
        elif job['kind'] == 'data.update':
            details = data.update(project, params, progress)
            result = dict(metrics={}, artifacts=[], summary='数据更新完成', details=details)
        elif job['kind'] == 'factor.analyze':
            result = engines.analyze(project, params, directory, progress)
        elif job['kind'] == 'model.train':
            result = engines.train(project, params, directory, progress)
        elif job['kind'] == 'backtest.run':
            result = engines.backtest(project, params, directory, progress, store=store)
        elif job['kind'] == 'optimize.run':
            result = engines.optimize(project, params, directory, progress, store)
        else:
            raise ValueError('未知任务')
        experiment = dict(id=job['id'], projectId=job['projectId'], kind=job['kind'], name=job['name'], starred=False,
                          createdAt=now(), parameters=params, metrics=result['metrics'], artifacts=result['artifacts'], summary=result['summary'])
        details = result.get('details', {})
        details['dataContext'] = data.preview(project)['datasets']
        details['source'] = read_json(Path(project['path']) / 'data' / 'source.json', {'source': 'import', 'warnings': ['导入文件的复权与历史修订完整性未验证']})
        details['universe'] = project['universe']
        if job['kind'].startswith('data.'):
            # Preserve the exact imported/updated tables in the experiment, so later updates do not change its export.
            import shutil
            for file in (Path(project['path']) / 'data').glob('*.parquet'):
                target = directory / file.name
                shutil.copyfile(file, target)
                experiment['artifacts'].append({'name': file.stem, 'path': str(target), 'type': 'parquet'})
        write_json(directory / 'details.json', details)
        write_json(directory / 'result.json', {'experiment': experiment})
        return 0
    except Exception as exc:
        traceback.print_exc()
        write_json(directory / 'result.json', {'error': str(exc)})
        return 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
