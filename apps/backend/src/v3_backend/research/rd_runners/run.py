"""Usage: python -m v3_backend.research.rd_runners.run <bridge_linux_path>."""
import asyncio
import json
import os
import re
import signal
import sys
from pathlib import Path

from . import protocol


def main():
    config = protocol.initialize(sys.argv[1])
    run_id = str(config['runId'])
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run_id):
        raise ValueError('runId格式无效')
    work = Path('/opt/v3-rdagent/runs') / run_id
    work.mkdir(parents=True, exist_ok=True)
    os.chdir(work)
    # Own process group, so Windows may terminate only this research and descendants.
    if os.getpgrp() != os.getpid():
        os.setsid()
    protocol.write_json(protocol.bridge() / 'pid.json', {'pid': os.getpid(), 'processGroupId': os.getpgrp(), 'runId': run_id})

    def cancelled(signum, frame):
        raise InterruptedError('研究任务已取消')

    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    loop = None
    result = {'status': 'failed', 'candidates': [], 'experimentIds': [], 'rounds': 0, 'checkpointPath': None}
    try:
        service = json.loads(sys.stdin.readline())
        from .service import configure as configure_service, redact
        configure_service(service, config.get('embeddingModelPath'))
        del service
        from .runtime import configure, prepare_data
        configure(work)
        prepare_data(work)
        from .native import V3QuantLoop
        if config.get('resumePath'):
            resume = Path(config['resumePath']).resolve()
            if not resume.is_relative_to(Path('/opt/v3-rdagent/runs')):
                raise ValueError('恢复路径必须属于本机RD-Agent运行目录')
            loop = V3QuantLoop.load(resume, checkout=False)
            if not isinstance(loop, V3QuantLoop) or loop.v3_input != {
                    key: config.get(key) for key in loop.v3_input}:
                raise ValueError('原生检查点所属项目/策略/数据区间/特征/训练配置与当前输入不一致')
            if getattr(loop,'v3_budget_id',None)!=config.get('budgetId') or getattr(loop,'v3_lineage_id',None)!=config.get('lineageRunId'):
                raise ValueError('原生检查点与方案预算或原始轮次身份不一致')
            if getattr(loop,'v3_repair',{}).get('requiresConfirmation'):
                if config.get('confirmRepair') is not True:raise ValueError('此检查点需要明确确认修复后才能继续')
                loop.v3_repair['requiresConfirmation']=False
            for coder in (loop.factor_coder,loop.model_coder):coder.max_loop=1
            # A failed first resumed step must not discard the checkpoint that
            # was successfully loaded and matched to this run's frozen inputs.
            result['checkpointPath'] = str(resume)
            protocol.write_json(protocol.bridge() / 'checkpoint.json',
                                {'checkpointPath': str(resume), 'resumedFrom': str(resume)})
            loop.session_folder = work / 'native-log' / '__session__'
            for experiment, _ in loop.trace.hist:
                for item in [experiment,*getattr(experiment,'based_experiments',[])]:
                    if getattr(item,'result',None) is not None:
                        response=getattr(item,'v3_response',None) or {'metrics':item.result['0'].to_dict()}
                        item.result=protocol.native_metrics(response)
        else:
            loop = V3QuantLoop()
        protocol.event('native_run_started', runId=run_id, resumed=bool(config.get('resumePath')),
                       engine='RD-Agent 0.8 QuantRDLoop + Factor/Model CoSTEER')
        # Upstream run resets loop_idx to zero; loop_n includes already completed loops.
        asyncio.run(loop.run(loop_n=min(int(config.get('candidateGroups',6)),int(config.get('rounds',3))*2)))
        result.update(status='completed', summary='本阶段原生研究轮次结束，候选等待讨论。')
    except BaseException as exc:
        from .service import redact, last_provider_failure
        message=redact(str(exc))
        failure=last_provider_failure()
        if failure and 'Failed to create chat completion' in message:
            message=failure['message']+'；本次模型请求已达到现有重试上限。'
        from ..ai_budget import budget_failure
        result['budgetExhausted']=budget_failure(exc) is not None
        result.update(status='cancelled' if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else 'failed',
                      error=message, errorType=type(exc).__name__, summary='原生研究未完成，已保留可用检查点和产物。')
        protocol.event('native_run_failed', errorType=type(exc).__name__, error=result['error'])
    finally:
        if loop is not None:
            result['completedCandidateGroups']=len(loop.trace.hist)
            result['rounds'] = (len(loop.trace.hist)+1)//2
            for exp, feedback in loop.trace.hist:
                response = getattr(exp, 'v3_response', {})
                if response.get('candidateId'):
                    result['candidates'].append(response['candidateId'])
                result['experimentIds'].extend(response.get('experimentIds', []))
        # Windows may have saved a successful candidate before native feedback failed.
        for response_path in (protocol.bridge() / 'evaluations').glob('*/response.json'):
            response = json.loads(response_path.read_text(encoding='utf-8-sig'))
            if not response.get('error'):
                if response.get('candidateId'):
                    result['candidates'].append(response['candidateId'])
                result['experimentIds'].extend(response.get('experimentIds', []))
        result['candidates'] = list(dict.fromkeys(result['candidates']))
        result['experimentIds'] = list(dict.fromkeys(result['experimentIds']))
        checkpoint = protocol.bridge() / 'checkpoint.json'
        if checkpoint.is_file():
            result['checkpointPath'] = json.loads(checkpoint.read_text())['checkpointPath']
        repair=protocol.bridge()/'repair.json'
        if repair.is_file():
            result.update(requiresConfirmation=True,repair=json.loads(repair.read_text(encoding='utf-8')))
        budget_file=protocol.bridge()/'budget.json'
        result['budget']=json.loads(budget_file.read_text(encoding='utf-8')) if budget_file.exists() else None
        protocol.write_json(protocol.bridge() / 'result.json', result)
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
