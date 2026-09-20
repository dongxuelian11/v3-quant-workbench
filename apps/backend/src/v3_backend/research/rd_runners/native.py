"""Native RD-Agent 0.8 Quant loop with V3 scenario and evaluation adapters."""
import json
import platform
import uuid
from pathlib import Path

from rdagent.app.qlib_rd_loop.quant import QuantRDLoop
from rdagent.app.qlib_rd_loop.conf import QuantBasePropSetting, QUANT_PROP_SETTING
from rdagent.core.developer import Developer
from rdagent.core.exception import CoderError, FactorEmptyError, ModelEmptyError
from rdagent.core.experiment import Experiment
from rdagent.scenarios.qlib.experiment.quant_experiment import QlibQuantScenario
from rdagent.scenarios.qlib.proposal.quant_proposal import QlibQuantHypothesisGen
from rdagent.scenarios.qlib.proposal.factor_proposal import QlibFactorHypothesisGen
from rdagent.scenarios.qlib.proposal.model_proposal import QlibModelHypothesisGen, QlibModelHypothesis2Experiment
from rdagent.utils.agent.tpl import T

from . import protocol
from .factors import execute_and_check
from .models import train_generated_model


class V3Scenario(QlibQuantScenario):
    def __init__(self):
        # Parent __init__ introspects/downloads the upstream default dataset.
        self._source_data = (
            'Windows-prepared A-share data only. Factor input: daily_pv.h5, pandas MultiIndex '
            'datetime/instrument, columns $open/$high/$low/$close/$volume/$factor. Read with pd.read_hdf. '
            'No test data is available. Use current/past observations only. Do not center rolling windows, '
            'shift backward, fit scalers on the whole period, or infer future values. Factor output: result.h5. '
            + str(protocol.config().get('priceBasis', '')) + ' ' + self.actual_data_description())
        self._rich_style_description = 'V3 日线因子与模型研究：原生 RD-Agent Quant / CoSTEER'
        self._experiment_setting = self.actual_data_description()

    def actual_data_description(self):
        config = protocol.config()
        return ('Actual input counts: ' + json.dumps(config.get('counts', {}), ensure_ascii=False)
                + '; explicit periods: ' + json.dumps(config['periods'])
                + '; features: ' + json.dumps(config['featureColumns'], ensure_ascii=False)
                + '; research objective: ' + str(config.get('objective', '')))

    def background(self, tag=None):
        return ('Research A-share daily factors and Torch models with native RD-Agent interfaces. '
                'Performance comes from the V3 daily account engine with actual fees and trading restrictions. '
                'Only validation metrics guide development. A candidate is not user acceptance. '
                'Generate one small task per experiment. ' + self.get_runtime_environment(tag))

    def simulator(self, tag=None):
        return ('Factor code executes on supplied HDF data and receives sampled cutoff consistency checks. '
                'Model code exposes model_cls, a torch.nn.Module class, constructor num_features and '
                'num_timesteps for TimeSeries, output [batch,1]. Native GeneralPTNN trains on mature '
                'train labels and early-stops on mature valid labels. No test prediction/feedback. '
                'V3 returns actual validation IC and daily-account benchmark-relative returns/cost/drawdown.')

    def get_runtime_environment(self, tag=None):
        import importlib.metadata
        versions = {name: importlib.metadata.version(name) for name in ('rdagent', 'pyqlib', 'torch', 'pandas')}
        return 'Linux Python ' + platform.python_version() + '; installed packages: ' + json.dumps(versions)


class V3HypothesisGen(QlibQuantHypothesisGen):
    def prepare_context(self, trace):
        action = protocol.config()['action']
        if action == 'joint':
            # Retain native LLM action selection; its bandit assumes unavailable metrics are zero.
            QUANT_PROP_SETTING.action_selection = 'llm'
            context, json_mode = super().prepare_context(trace)
        else:
            self.targets = action
            method = QlibFactorHypothesisGen.prepare_context if action == 'factor' else QlibModelHypothesisGen.prepare_context
            context, json_mode = method(self, trace)
        context['RAG'] = (self.scen.actual_data_description() + '; use a compact model appropriate to these actual counts; '
                          'the selected action must be ' + self.targets + '. Generate one task per experiment.')
        context['hypothesis_output_format'] = T('scenarios.qlib.prompts:hypothesis_output_format_with_action').r()
        return context, json_mode

    def convert_response(self, response):
        hypothesis = super().convert_response(response)
        if hypothesis.action != self.targets:
            raise ValueError('原生假设返回了未选择的研究动作')
        return hypothesis


class V3ModelHypothesis2Experiment(QlibModelHypothesis2Experiment):
    def prepare_context(self, hypothesis, trace):
        context, mode = super().prepare_context(hypothesis, trace)
        context['RAG'] = trace.scen.actual_data_description() + '; generate one compact Torch model.'
        return context, mode


def _baseline(exp):
    existing = [item for item in exp.based_experiments if item.result is not None]
    if not existing:
        baseline = Experiment(sub_tasks=[])
        baseline.result = protocol.native_metrics(protocol.evaluate({'action': 'baseline', 'name': '当前研究基线'}, 'baseline'))
        existing = [baseline]
    exp.based_experiments = existing


def _request(exp, action):
    if not hasattr(exp, 'v3_evaluation_id'):
        exp.v3_evaluation_id = uuid.uuid4().hex
    return {'action': action, 'name': ' / '.join(task.name for task in exp.sub_tasks),
            'description': '\n'.join(task.description for task in exp.sub_tasks),
            'changeSummary': str(exp.hypothesis), 'hypothesis': str(exp.hypothesis)}


def _finish(exp, request):
    response = protocol.evaluate(request, exp.v3_evaluation_id)
    exp.result = protocol.native_metrics(response)
    exp.v3_response = response
    return exp


class V3FactorRunner(Developer):
    def develop(self, exp):
        import pandas as pd
        _baseline(exp)
        request = _request(exp, 'factor')
        values, codes = [], []
        folder = protocol.bridge() / 'generated' / exp.v3_evaluation_id
        for number, workspace in enumerate(exp.sub_workspace_list):
            if workspace is None:
                continue
            try:
                path = execute_and_check(workspace, folder / str(number))
            except ValueError as exc:
                raise FactorEmptyError('原生因子未通过输出/截断检查: ' + str(exc)) from exc
            values.append(pd.read_parquet(path))
            codes.append(str(workspace.workspace_path / 'factor.py'))
            workspace.target_task.factor_implementation = True
        if not values:
            raise FactorEmptyError('原生因子没有可用输出')
        combined = pd.concat(values, axis=1)
        if combined.columns.duplicated().any():
            raise ValueError('原生因子名称重复')
        path = folder / 'factors.parquet'
        combined.to_parquet(path)
        exp.v3_factor_path = str(path)
        request.update(factorPath=str(path), codePaths=codes,
                       factorNames=list(combined.columns), codePath=codes[0])
        exp=_finish(exp, request)
        exp.v3_factor_path=exp.v3_response.get('factorPath',str(path))
        exp.v3_custom_factors=exp.v3_response.get('customFactors',[])
        return exp


class V3ModelRunner(Developer):
    def develop(self, exp):
        import pandas as pd
        _baseline(exp)
        request = _request(exp, 'model')
        workspaces = [item for item in exp.sub_workspace_list if item is not None]
        if len(workspaces) != 1:
            raise ModelEmptyError('每个原生模型实验必须有一个成功的model.py')
        workspace = workspaces[0]
        task = workspace.target_task
        config = protocol.config()
        folder = protocol.bridge() / 'generated' / exp.v3_evaluation_id
        folder.mkdir(parents=True, exist_ok=True)
        dataset_path = config['datasetPath']
        features = list(config['featureColumns'])
        # Native joint research can carry accepted factor candidates into model features.
        factor_paths = list(dict.fromkeys(path for base in exp.based_experiments
            for path in getattr(base,'v3_factor_paths',[getattr(base,'v3_factor_path','')])))
        factor_paths = [path for path in factor_paths if path]
        custom={item['id']:item for base in exp.based_experiments for item in getattr(base,'v3_custom_factors',[])}
        if factor_paths:
            data = pd.read_parquet(dataset_path).rename(columns={'date': 'datetime', 'symbol': 'instrument'})
            data = data.set_index(['datetime', 'instrument'])
            for path in factor_paths:
                factors = pd.read_parquet(path)
                for column in factors:
                    if column not in features:
                        data[column] = factors[column].reindex(data.index)
                        features.append(column)
            dataset_path = folder / 'model_input.parquet'
            data.reset_index().rename(columns={'datetime': 'date', 'instrument': 'symbol'}).to_parquet(dataset_path, index=False)
        training = {**config.get('trainingParameters', {}), **dict(task.training_hyperparameters or {}),
                    **config['periods'], 'featureColumns': features, 'modelType': task.model_type, 'includeTest': False}
        for key in ('labelHorizon', 'labelMode'):
            if key in config.get('trainingParameters', {}):
                training[key] = config['trainingParameters'][key]
        try:
            result = train_generated_model(workspace.workspace_path / 'model.py', dataset_path, folder,
                                           dict(task.hyperparameters or {}), training)
        except Exception as exc:
            raise ModelEmptyError('原生模型训练失败: ' + str(exc)) from exc
        request.update(codePath=str(workspace.workspace_path / 'model.py'), predictionPath=result['dataPath'],
                       modelPath=result['modelPath'],
                       trainingEventsPath=result['trainingEventsPath'], modelParameters=result['modelParameters'],
                       trainingParameters=training,customFactors=list(custom.values()))
        exp.v3_model_result = result
        exp.v3_factor_paths=factor_paths
        exp.v3_custom_factors=list(custom.values())
        return _finish(exp, request)


class RepairRequired(RuntimeError):
    pass


class V3QuantLoop(QuantRDLoop):
    skip_loop_error = ()

    def __init__(self):
        prefix = 'v3_backend.research.rd_runners.native.'
        settings = QuantBasePropSetting(scen=prefix+'V3Scenario', quant_hypothesis_gen=prefix+'V3HypothesisGen',
            model_hypothesis2experiment=prefix+'V3ModelHypothesis2Experiment',
            factor_runner=prefix+'V3FactorRunner', model_runner=prefix+'V3ModelRunner')
        super().__init__(settings)
        self.v3_run_id = protocol.config()['runId']
        self.v3_input = {key: protocol.config().get(key) for key in
                         ('projectId', 'strategyId', 'periods', 'featureColumns', 'trainingParameters')}

    async def direct_exp_gen(self, prev_out):
        result = await super().direct_exp_gen(prev_out)
        # Persist identity in the native checkpoint before coding/running starts.
        result['exp_gen'].v3_evaluation_id = uuid.uuid4().hex
        return result

    def coding(self, prev_out):
        action = prev_out['direct_exp_gen']['propose'].action
        coder = self.factor_coder if action == 'factor' else self.model_coder
        instructions=protocol.config().get('repairInstructions')
        if instructions:
            for task in prev_out['direct_exp_gen']['exp_gen'].sub_tasks:
                marker='\n用户确认的本次修复说明：'+instructions
                if marker not in task.description:task.description+=marker
        try:
            return super().coding(prev_out)
        finally:
            agent = getattr(coder, 'evolve_agent', None)
            protocol.event('code_evolution_finished', action=action,
                           attempts=len(agent.evolving_trace) if agent is not None else 0,
                           maxAttempts=coder.max_loop)

    async def _run_step(self, li, force_subproc=False):
        step_index=self.step_idx[li]
        name = self.steps[step_index]
        protocol.event('native_step_started', round=li+1, step=name)
        try:
            await super()._run_step(li, force_subproc=False)
        except Exception as exc:
            protocol.event('native_step_failed', round=li+1, step=name)
            if isinstance(exc,(CoderError,FactorEmptyError,ModelEmptyError)) or name=='coding':
                from .service import redact,last_provider_failure
                # Service errors are a separate failure, not permission to rewrite code.
                if last_provider_failure():raise
                resume_index=self.steps.index('coding') if isinstance(exc,(FactorEmptyError,ModelEmptyError)) and 'coding' in self.steps else step_index
                self.step_idx[li]=resume_index
                if resume_index!=step_index:
                    failed=self.loop_prev_out[li].pop('coding',None)
                    if failed is not None:self.loop_prev_out[li]['direct_exp_gen']['exp_gen']=failed
                error=redact(str(exc))
                from rdagent.core.conf import RD_AGENT_SETTINGS
                code=[]
                try:
                    paths=[path for name in ('factor.py','model.py') for path in Path(RD_AGENT_SETTINGS.workspace_path).rglob(name)]
                    for path in sorted(paths,key=lambda path:path.stat().st_mtime,reverse=True)[:4]:
                        code.append({'path':str(path),'content':redact(path.read_text(encoding='utf-8',errors='replace'))[:16000]})
                except OSError:pass
                self.v3_repair={'requiresConfirmation':True,'round':li+1,'step':name,'error':error,
                    'errorType':type(exc).__name__,'maxAttempts':1,
                    'resumeStep':self.steps[resume_index],
                    'code':code,'codeScope':'本次运行最近保存的工作区代码；可能含本轮依赖工作区，缺文件时不补造',
                    'proposal':'保留当前工作区与失败反馈；确认后仅重试失败步骤一次，先修复报告中的代码或输出格式问题，再重新验证，不重跑已完成实验。'}
                path=self.session_folder/'repair'/f'{li}-{step_index}.pkl'
                self.dump(path)
                protocol.write_json(protocol.bridge()/'repair.json',{**self.v3_repair,'checkpointPath':str(path.resolve())})
                protocol.event('repair_confirmation_required',**self.v3_repair,checkpointPath=str(path.resolve()))
                raise RepairRequired('代码首次尝试失败，已暂停并保存错误、修复建议和检查点；需要明确确认后继续。') from exc
            raise
        protocol.event('native_step_completed', round=li+1, step=name)

    def dump(self, path):
        super().dump(path)
        protocol.write_json(protocol.bridge() / 'checkpoint.json', {'checkpointPath': str(Path(path).resolve())})
        protocol.event('checkpoint_saved', checkpointPath=str(Path(path).resolve()))
