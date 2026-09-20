"""Run in the installed WSL RD-Agent runtime; no model or market calls."""
import asyncio,json,pickle,sys
from pathlib import Path
from rdagent.utils.workflow import LoopBase
from rdagent.core.exception import CoderError,FactorEmptyError
from types import SimpleNamespace
from v3_backend.research.rd_runners import protocol
from v3_backend.research.rd_runners.native import V3QuantLoop,RepairRequired


class Tracker:
    def log_workflow_state(self):pass


class Progress:
    n=0
    def set_postfix(self,**kwargs):pass


class ControlledFailure(V3QuantLoop):
    def __init__(self,root):
        LoopBase.__init__(self)
        self.steps=['coding','record'];self.session_folder=root/'session'
        self.tracker=Tracker();self._progress=Progress();self.attempts=0

    @property
    def pbar(self):return self._progress

    def coding(self,prev_out):
        self.attempts+=1
        try:exec(compile('result = 1 / 0','factor.py','exec'),{})
        except Exception as exc:raise CoderError(str(exc)) from exc

    def record(self,prev_out):raise AssertionError('失败后不能继续下一步')


class ControlledRunnerFailure(ControlledFailure):
    def __init__(self,root):
        super().__init__(root)
        self.steps=['coding','running','record'];self.step_idx[0]=1
        self.loop_prev_out[0].update(coding=SimpleNamespace(based_experiments=['completed-baseline'],v3_evaluation_id='frozen-evaluation'),
            direct_exp_gen={'exp_gen':SimpleNamespace(based_experiments=[])})

    def running(self,prev_out):raise FactorEmptyError('controlled validation failure')


def main():
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
    protocol.write_json(root/'config.json',{'runId':'controlled-failure','rounds':1,'codeRepairRounds':1,'action':'factor'})
    protocol.initialize(root)
    from v3_backend.research.rd_runners.runtime import configure
    from rdagent.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
    from rdagent.components.coder.model_coder.conf import MODEL_COSTEER_SETTINGS
    configure(root/'runtime')
    assert FACTOR_COSTEER_SETTINGS.max_loop==MODEL_COSTEER_SETTINGS.max_loop==1
    from v3_backend.research.rd_runners import service
    from unittest.mock import patch
    from urllib.error import HTTPError
    from io import BytesIO
    settings={'baseUrl':'https://invalid.local','model':'test'}
    with patch.object(service.urllib.request,'urlopen',side_effect=HTTPError('',401,'auth',{},None)) as request:
        try:service._post(settings,'chat/completions',{})
        except service.ProviderError:pass
        else:raise AssertionError('认证错误必须失败')
        assert request.call_count==1
    with patch.object(service.urllib.request,'urlopen',side_effect=[HTTPError('',429,'limited',{'Retry-After':'0'},None),HTTPError('',503,'busy',{'Retry-After':'0'},None),BytesIO(b'{"ok":true}')]) as request,patch.object(service.time,'sleep') as sleep:
        assert service._post(settings,'chat/completions',{})=={'ok':True}
        assert request.call_count==3 and sleep.call_count==2
    loop=ControlledFailure(root)
    try:asyncio.run(loop._run_step(0))
    except RepairRequired:pass
    else:raise AssertionError('代码异常必须暂停')
    repair=json.loads((root/'repair.json').read_text())
    restored=pickle.loads(Path(repair['checkpointPath']).read_bytes())
    assert restored.step_idx[0]==0
    assert restored.attempts==1
    assert repair['requiresConfirmation'] and repair['errorType']=='CoderError'
    runner=ControlledRunnerFailure(root/'runner')
    try:asyncio.run(runner._run_step(0))
    except RepairRequired:pass
    else:raise AssertionError('输出验证失败必须暂停')
    assert runner.step_idx[0]==0
    assert runner.loop_prev_out[0]['direct_exp_gen']['exp_gen'].based_experiments==['completed-baseline']
    assert runner.loop_prev_out[0]['direct_exp_gen']['exp_gen'].v3_evaluation_id=='frozen-evaluation'
    result={'status':'PASS','actualNativeStep':True,'completedBaselineRetained':True,'codeAttemptLimit':1,'authCalls':1,'transientCalls':3,'attempts':restored.attempts,'resumeStep':restored.steps[restored.step_idx[0]],'repair':repair}
    protocol.write_json(root/'check-result.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
