"""Visible planned work; trial reservations include failed attempts on resume."""


def work_counts(specs):
    result = dict(trials=0, trainingTasks=0, backtestTasks=0, rollingTasks=0)
    for spec in specs:
        kind, params = spec['kind'], spec.get('parameters', {})
        if kind == 'optimize.run':
            count = params.get('trials', 20)
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000:
                raise ValueError('试参次数必须为1到1000的整数')
            result['trials'] += count
        result['trainingTasks'] += kind == 'model.train'
        result['backtestTasks'] += kind == 'backtest.run'
        result['rollingTasks'] += params.get('validation', {}).get('mode') == 'rolling'
    return result


def reproduction_budget(store, run):
    specs = [job['spec'] for job in store.list('job', run['projectId'])
             if job.get('spec',{}).get('reproduction',{}).get('planId')==run['planId'] and job.get('spec',{}).get('reproduction',{}).get('revision')==run['revision']]
    result=dict(trialLimit=20, reserved=work_counts(specs),
                planned=work_counts(step['spec'] for step in run['planSnapshot']['steps'] if step['id'] in run.get('selectedStepIds',[s['id'] for s in run['planSnapshot']['steps']])),
                message='同一计划修订共用预算；试参按已提交次数预留，失败与重新执行不返还；训练、回测单列，滚动窗口数量以实际实验为准。')
    if run.get('budgetId'):
        from .ai_budget import read_budget
        result['shared']=read_budget(store.project_store(run.get('budgetProjectId',run['projectId'])).db,run['budgetId'])
    return result
