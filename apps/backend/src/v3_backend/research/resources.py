"""Resource preferences and conflict keys for the existing job queue."""
import os
from pathlib import Path

PROFILES = {'interactive': (1, 2), 'balanced': (1, 4), 'compute': (2, 4)}


def compute_settings(value=None, cpu_count=1):
    """Pure normalization; caller supplies available CPUs, never edits settings."""
    value = {} if value is None else value
    if not isinstance(value, dict) or value.get('profile', 'interactive') not in PROFILES:
        raise ValueError('计算资源档位无效')
    profile = value.get('profile', 'interactive')
    jobs, threads = PROFILES[profile]
    requested = dict(profile=profile, maxConcurrentJobs=value.get('maxConcurrentJobs', jobs),
                     threadsPerJob=value.get('threadsPerJob', threads))
    for key in ('maxConcurrentJobs', 'threadsPerJob'):
        if type(requested[key]) is not int or requested[key] < 1:
            raise ValueError('并行任务数与线程数必须为正整数')
    cpus = max(1, int(cpu_count or 1))
    jobs = min(requested['maxConcurrentJobs'], cpus)
    threads = min(requested['threadsPerJob'], max(1, cpus // jobs))
    return dict(profile=profile, maxConcurrentJobs=jobs, threadsPerJob=threads, availableCpus=cpus,
                requested=requested, qlibKernels=1, optunaParallelTrials=1,
                limitations=['线程数约束适用于支持环境变量的 BLAS/OpenMP 和 LightGBM；不保证全部原生/RD进程受控',
                             '同项目及同数据目录任务串行；原生RD任务独占队列'])


def thread_count():
    return max(1, int(os.environ.get('V3_RESEARCH_THREADS', '1')))


def environment(resources):
    count = str(resources['threadsPerJob'])
    return {key: count for key in ('V3_RESEARCH_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
                                   'OPENBLAS_NUM_THREADS', 'BLIS_NUM_THREADS', 'NUMEXPR_NUM_THREADS',
                                   'VECLIB_MAXIMUM_THREADS')}


def conflict_keys(job):
    from .storage_migration import resolve_location
    spec = job.get('spec', {})
    projects = [spec.get('projectSnapshot', {})] + [s.get('project', {}) for s in spec.get('strategySnapshots', []) + spec.get('dailyPlanSnapshots', [])]
    keys = {'project:' + str(job.get('projectId') or 'global')}
    for project in projects:
        keys.add('project:' + str(project.get('id') or job.get('projectId') or 'global'))
        path = project.get('settings', {}).get('dataPath') or str(Path(project.get('path') or '.') / 'data')
        keys.add('data:' + os.path.normcase(str(resolve_location(path))))
    if job['kind'].startswith('reports.'):
        keys.add('reports')
    return keys


def compatible(job, running):
    if job['kind'] == 'rdagent.run' or any(other['kind'] == 'rdagent.run' for other in running):
        return not running
    keys = conflict_keys(job)
    return all(not keys.intersection(conflict_keys(other)) for other in running)
