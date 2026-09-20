"""One real-service RD failure/confirmed-resume check on isolated real daily inputs."""
from copy import deepcopy
import json,os,threading,time
from pathlib import Path
from v3_backend.research.storage import Store,read_json,write_json,identifier
from v3_backend.research import rd_agent,worker
from v3_backend.research.workbench import strategy_project


def main():
    root=Path('artifacts/round6-backend/rd-live-final').resolve();root.mkdir(parents=True,exist_ok=True)
    config=read_json(Path(os.environ['APPDATA'])/'v3-oss-rebuild/research/settings.json')
    store=Store(root/'profile');store.settings=lambda:config
    original=read_json(Path('artifacts/round6-backend/compute/project/project.json'))
    project=store.create_project(str(root/'project'),'RD真实服务失败恢复验证','受控错误恢复验证，不评价策略收益')
    project.update(startDate='2024-10-08',endDate='2025-01-27',universe=deepcopy(original['universe']))
    project['settings']={'dataPath':original['settings']['dataPath'],'selectedFactors':['momentum20'],
        'factorProcessing':{'winsorize':'none','standardize':False,'neutralizeIndustry':False,'neutralizeSize':False},
        'backtest':{'template':'single_factor','factorIds':['momentum20'],'topN':3,'rebalance':'weekly','capital':100000,'benchmark':'csi300'}}
    store.save_project(project);project=strategy_project(store,project['id'],'default')
    params={'action':'factor','rounds':1,'codeRepairRounds':1,'factorIds':['momentum20'],'labelHorizon':2,'labelMode':'next_open',
        'trainStart':'2024-10-08','trainEnd':'2024-11-15','validStart':'2024-11-18','validEnd':'2024-12-13','testStart':'2024-12-16','testEnd':'2025-01-27',
        'evaluationBacktest':project['settings']['backtest'],
        'objective':'Controlled engineering failure-and-repair check, not investment research. Define one factor as daily close divided by previous close minus 1, using past data only. For this initial run, the factor.py implementation MUST deliberately raise ValueError("V3_CONTROLLED_FIRST_CODE_FAILURE") immediately. This intentional error verifies that execution pauses after one attempt; do not repair it automatically. A later explicitly confirmed resume will instruct you to remove that error and implement the factor with datetime/instrument MultiIndex and result.h5.'}
    results=[]
    for stage in ('initial','confirmed-resume'):
        job={'id':identifier(),'kind':'rdagent.run','projectId':project['id'],'strategyId':'default','name':'受控真实RD '+stage,'spec':{'parameters':deepcopy(params)}}
        directory=Path(project['path'])/'.research/runs'/job['id'];directory.mkdir(parents=True)
        done=threading.Event()
        def watchdog():
            if not done.wait(360):write_json(directory/'rd_cancel.json',{'reason':'最小验证达到360秒，停止继续请求'})
        threading.Thread(target=watchdog,daemon=True).start()
        last=[None]
        def progress(value,message):
            if message!=last[0]:print(json.dumps({'stage':stage,'message':message},ensure_ascii=False),flush=True);last[0]=message
        started=time.monotonic()
        try:result=rd_agent.run(store,job,project,directory,progress)
        finally:done.set()
        experiment=worker.save_result(store,job,project,result,directory);store.save_experiment(project['id'],experiment)
        details=result['details'];entry={'stage':stage,'experimentId':job['id'],'seconds':round(time.monotonic()-started,3),
            'status':details['status'],'requiresConfirmation':details.get('requiresConfirmation'),'error':details.get('error'),
            'checkpointPath':details.get('checkpointPath'),'repair':details.get('repair'),'summary':result['summary']}
        results.append(entry);write_json(root/'result.json',{'projectId':project['id'],'stages':results})
        print(json.dumps({k:v for k,v in entry.items() if k!='repair'},ensure_ascii=False),flush=True)
        if stage=='initial':
            if not details.get('requiresConfirmation'):break
            blocked=False
            try:rd_agent._resume_inputs(store,project,{**params,'resumeExperimentId':job['id']},directory/'unconfirmed',lambda *_:None)
            except ValueError as exc:blocked='明确确认' in str(exc)
            if not blocked:raise AssertionError('未确认的修复恢复应拒绝')
            params.update(resumeExperimentId=job['id'],confirmRepair=True,
                objective='Explicitly confirmed repair: remove the intentionally inserted V3_CONTROLLED_FIRST_CODE_FAILURE and implement close / previous close - 1 with past data only; save result.h5 with datetime/instrument index. One code attempt only.',
                repairInstructions='用户明确确认本次工程修复：删除故意的ValueError，按C/REF(C,1)-1实现因子并保存result.h5，保留原始索引，每只股票单独shift(1)，不使用未来数据。')


if __name__=='__main__':main()
