"""One research experiment per isolated Python process."""
import sys
import traceback
from pathlib import Path
from .storage import Store, now, read_json, write_json


def execute(store, job, project, directory, progress):
    parameters = job['spec'].get('parameters', {})
    if parameters.get('budgetId') and job['kind'] != 'rdagent.run':
        from .ai_budget import computation_budget, read_budget
        database = store.project_store(parameters.get('budgetProjectId', job.get('projectId'))).db
        read_budget(database, parameters['budgetId'])
        with computation_budget(database, parameters['budgetId']):
            return _prepared_execute(store, job, project, directory, progress)
    return _prepared_execute(store, job, project, directory, progress)


def _prepared_execute(store, job, project, directory, progress):
    from copy import deepcopy
    from . import preparation
    if job['spec'].get('inputExperimentId'):
        from .input_snapshot import restore
        if job['kind'] not in {'factor.analyze','model.train','backtest.run','optimize.run'}:
            raise ValueError('此任务不支持原输入复现')
        original = store.experiment(project['id'], job['spec']['inputExperimentId'])
        if original.get('kind') != job['kind']:
            raise ValueError('原输入复现必须使用原实验的任务类型')
        project, params, reference = restore(store, project, job['spec']['inputExperimentId'])
        job = deepcopy(job)
        job['spec']['parameters'] = params
        result = _execute(store, job, project, directory, progress)
        result['inputSnapshot'] = reference
        result['_inputProject'] = project
        result.setdefault('parameters', params)
        return result
    if job['kind']=='simulation.advance' and not job.get('projectId'):
        return _execute(store,job,project,directory,progress)
    if job['kind'] not in preparation.KINDS or job['spec']['parameters'].get('model')=='native_generated_predictions' or job['spec']['parameters'].get('rdRequestId'):
        return _execute(store,job,project,directory,progress)
    job=deepcopy(job)
    if job['kind']=='simulation.advance':
        from .simulation import _get
        account=_get(store,job['projectId'],job['spec']['parameters']['accountId'])
        project=deepcopy(project)
        if project['universe']['source']=='manual':
            project['universe']['symbols']=sorted(set(project['universe']['symbols'])|set(account['state']['holdings']))
    params,prepared=preparation.prepare(store,job,project,directory,progress)
    from .input_snapshot import capture
    project, params, reference = capture(store, project, params, directory, prepared)
    job['spec']['parameters']=params
    result=_execute(store,job,project,directory,progress)
    result.setdefault('details',{})['preparation']=prepared
    result['inputSnapshot'] = reference
    result['_inputProject'] = project
    if job['kind']=='model.train':
        result['details']['inputSignature']=preparation.signature(project,params)
    result.setdefault('parameters',params)
    return result


def _execute(store, job, project, directory, progress):
    """Use the same calculation path for queued jobs and RD research evaluations."""
    if job['kind'].startswith('reports.'):
        from .reports import execute as report_execute
        return report_execute(store, job['kind'], job['spec']['parameters'], progress)
    from . import data, engines
    params = job['spec']['parameters']
    kind = job['kind']
    if kind == 'screener.run':
        from .screening_run import run
        return run(store, project, params, directory, progress)
    if kind == 'data.import':
        details = data.import_files(project, params, progress)
        summary=f"导入成功 {details['completedFiles']} 个文件，失败 {len(details['failedFiles'])} 个文件"
        if details.get('metadataStatus')=='failed':summary+='；来源说明保存失败，数据结果已保留'
        return dict(metrics={},artifacts=[],summary=summary,details=details)
    if kind == 'data.update':
        if params.get('quoteOnly'):
            from .quotes import update as update_quote
            details=update_quote(project,params,progress)
            return dict(metrics={},artifacts=[],summary='单标的行情更新',details=details)
        details = data.update(project, params, progress)
        return dict(metrics={}, artifacts=[], summary='数据更新完成', details=details)
    if kind == 'factor.analyze':
        return engines.analyze(project, params, directory, progress)
    if kind == 'model.train':
        if params.get('model')=='native_generated_predictions':
            from .rd_agent import reevaluate_native
            return reevaluate_native(store,job,project,directory,progress)
        return engines.train(project, params, directory, progress)
    if kind == 'backtest.run':
        return engines.backtest(project, params, directory, progress, store=store)
    if kind == 'optimize.run':
        return engines.optimize(project, params, directory, progress, store)
    if kind == 'selection.run':
        source=job['spec'].get('positionsSourceResolved')
        if source and source['kind']=='simulation':
            from .simulation_advance import research
            return research(store,params,directory,progress,job['spec']['accountSnapshot'],source)
        from .selection import run as select
        result=select(project, params, directory, progress, snapshot=job['spec'].get('positionsSnapshot'), strategy_snapshots=job['spec'].get('strategySnapshots'), daily_plan_snapshots=job['spec'].get('dailyPlanSnapshots'), store=store)
        result.setdefault('details',{})['positionsSourceResolved']=source
        if source and source['kind']=='none':
            result['details'].update(executable=False,positionsContext='独立候选研究，未读取实际或模拟账户；权重为候选配置，不是账户调仓指令')
            result['artifacts']=[a for a in result['artifacts'] if a['name'] not in {'positions','rebalance'}]
        return result
    if kind == 'simulation.advance':
        if not job.get('projectId'):
            from .simulation_advance import advance as advance_shared
            return advance_shared(store,params,directory,progress,job['spec'].get('accountSnapshot'))
        from .simulation import advance
        return advance(store, params, directory, progress, project=project)
    if kind == 'rdagent.run':
        from .rd_agent import run as run_native
        return run_native(store,job,project,directory,progress)
    raise ValueError('未知任务')


def save_result(store, job, project, result, directory):
    """Write a normal portable experiment; queue ownership stays with the caller."""
    from . import data, engines
    project = result.get('_inputProject', project)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / 'project.json', project)
    experiment = dict(id=job['id'], projectId=job.get('projectId'), strategyId=job.get('strategyId'), kind=job['kind'], name=job['name'], starred=False,
                      createdAt=now(), parameters=result.get('parameters', job['spec']['parameters']), metrics=result['metrics'], artifacts=[dict(a) for a in result['artifacts']], summary=result['summary'])
    if job['spec'].get('candidateSnapshot'):
        candidate = job['spec']['candidateSnapshot']
        experiment.update(candidateId=candidate['id'], candidateRevision=candidate['revision'])
    if result.get('inputSnapshot'):
        experiment['inputSnapshot'] = result['inputSnapshot']
    if job['spec'].get('reproduction'):
        experiment['reproduction'] = job['spec']['reproduction']
    details = dict(result.get('details', {}))
    if job['spec'].get('effectiveResources'):
        details['effectiveResources'] = job['spec']['effectiveResources']
    if not job['kind'].startswith('reports.'):
        details['dataContext'] = data.preview(project)['datasets']
        details['source'] = read_json(Path(data.project_data(project)['path']) / 'data' / 'source.json', {'source': 'import', 'warnings': ['导入文件的复权与历史修订完整性未验证']})
        details['universe'] = project['universe']
    if job['kind'].startswith('data.') and not job['spec']['parameters'].get('quoteOnly'):
        # Keep the run's actual tables independent of later data updates.
        for kind in ['prices', 'financials']:
            params = job['spec']['parameters']
            if job['kind'] == 'data.update' and kind == 'financials' and not details.get('financialSource'):
                continue
            source = Path(data.project_data(project)['path']) / 'data'
            if not (source / kind).exists() and not (source / f'{kind}.parquet').exists():
                continue
            target = directory / f'{kind}.parquet'
            scope = details.get('symbols') if job['kind'] == 'data.update' else None
            frame = data.read_table(project, kind, symbols=scope,
                start=params.get('startDate') if kind == 'prices' else None, end=params.get('endDate'))
            if frame.empty:
                continue
            frame.to_parquet(target, index=False)
            experiment['artifacts'].append({'name': kind, 'path': str(target), 'type': 'parquet'})
        from .alternative_data import read as read_alternative
        for kind in ('fund_flow', 'chips', 'lhb', 'institutions', 'seats'):
            if job['kind'] == 'data.update' and not details.get('alternativeData'):
                continue
            frame = read_alternative(project, kind)
            if not frame.empty:
                experiment['artifacts'].append(engines.save_table(directory, kind, frame))
    write_json(directory / 'details.json', details)
    for artifact in experiment['artifacts']:
        artifact['path'] = Path(artifact['path']).resolve().relative_to(Path(project['path']).resolve()).as_posix()
    write_json(directory / 'result.json', {'experiment': experiment})
    return experiment


def run(directory):
    directory = Path(directory)
    import os
    os.environ['V3_RESEARCH_OWNER_DIR']=str(directory)
    request = read_json(directory / 'request.json')
    store = Store(request['appData'])
    job = request['job']

    def progress(value, message):
        write_json(directory / 'progress.json', {'progress': min(.99, max(0, value)), 'message': message})

    try:
        from .storage_migration import location_scope
        with location_scope(store):
            project = job['spec'].get('projectSnapshot') or store.project(job.get('projectId'))
            write_json(directory / 'project.json', project)
            result = execute(store, job, project, directory, progress)
            experiment=save_result(store, job, project, result, directory)
            if job['kind']=='data.import' and result['details']['status']!='completed':
                write_json(directory/'result.json',{'experiment':experiment,'runtimeStatus':'failed','error':result['summary']+'；成功结果已保留，可单独重试失败文件'})
                return 1
            if job['kind']=='rdagent.run':
                state=result.get('details',{}).get('status','failed')
                write_json(directory/'result.json',{'experiment':experiment,'runtimeStatus':state,
                    'error':result.get('details',{}).get('error')})
                return 0 if state=='completed' else 1
            return 0
    except Exception as exc:
        traceback.print_exc()
        write_json(directory / 'result.json', {'error': str(exc)})
        return 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
