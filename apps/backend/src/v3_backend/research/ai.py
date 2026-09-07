"""PydanticAI research tools and a portable, user-driven conversation."""
import json
from pathlib import Path

from .jobs import validate_spec
from .storage import now, read_json, write_json


def _state_path(service, project_id):
    return Path(service.store.project(project_id)['path']) / 'ai' / 'conversation.json'


def get_state(service, params):
    state = dict(messages=[], phase='', proposals=[], stageJobIds=[], mode='assist')
    state.update(read_json(_state_path(service, params['projectId']), {}))
    return state


def save_state(service, params):
    state = get_state(service, params)
    patch = params['state']
    for key in ('messages', 'phase', 'proposals', 'stageJobIds', 'mode'):
        if key in patch:
            state[key] = patch[key]
    state['updatedAt'] = now()
    write_json(_state_path(service, params['projectId']), state)
    return state


def _experiment_summary(experiment, include_parameters=False):
    hidden = {'artifacts'} if include_parameters else {'artifacts', 'parameters'}
    return {key: value for key, value in experiment.items() if key not in hidden} | {
        'tables': [item['name'] for item in experiment['artifacts'] if item['type'] == 'parquet']
    }


def _project_context(service, project_id):
    from .data import preview
    project = service.store.project(project_id)
    # Research settings are useful context; provider credentials belong to app settings.
    settings = project.get('settings', {})
    research_settings = {key: settings[key] for key in (
        'selectedFactors', 'customFactors', 'factorProcessing', 'factorAnalysis',
        'backtest', 'model', 'selection',
    ) if key in settings}
    data = preview(project)
    data['rows'] = data.get('rows', [])[:20]
    return {
        'project': {key: project[key] for key in ('id', 'name', 'objective', 'universe', 'startDate', 'endDate')},
        'configuration': research_settings,
        'data': data,
    }


def _stage_status(service, project_id):
    state = get_state(service, {'projectId': project_id})
    jobs = {job['id']: job for job in service.store.list('job', project_id)}
    selected = []
    for key in state['stageJobIds']:
        job = jobs.get(key)
        selected.append({field: job.get(field) for field in (
            'id', 'kind', 'name', 'status', 'progress', 'message', 'experimentId',
        )} if job else {'id': key, 'status': 'unavailable'})
    return {'phase': state['phase'], 'proposals': state['proposals'], 'jobs': selected}


INSTRUCTIONS = '''你是中文沪深A股日线研究助手。依据工具返回的真实数据与实验解释，不能把建议写成运行结果。
工具只读数据，不会运行研究或修改持仓。先理解已有配置；解释实验必须读取对应实验，分析明细可按需读取结果表。
ask只问答，proposals为空。assist提供可供用户应用的完整参数。research只规划当前一个阶段；用户点击运行后，读取任务实际状态和结果，再与用户讨论下一阶段。任务进行中不能声称完成，失败或中断要说明实际原因。
任务kind及参数：
data.update {source:baostock|akshare,financials:true,startDate,endDate}；
factor.analyze {factorIds,customFactors:[],periods:[1,5,10,20],quantiles:5,labelMode:next_open|close,factorProcessing:{directions:{因子ID:1或-1},winsorize:mad|none,madScale:3,standardize:true,neutralizeIndustry:false,neutralizeSize:false}}；
backtest.run {template:single_factor|multi_factor|model_score,factorIds,weights:{},topN:30,rebalance:weekly,capital:1000000,benchmark:csi300|csi500,portfolio:{method:equal|score|risk_parity|mean_variance,grossExposure:0.95,maxWeight:null,industryCap:null,turnoverLimit:null,lookback:252,minObservations:126,riskAversion:3,returnSource:historical|model},costs:{commissionBuy:0.0003,commissionSell:0.0003,minCommission:5,stampDuty:historical,transferFee:0.00001,slippage:0.001,volumeParticipation:0.1},factorProcessing,modelExperimentId?}；
model.train {model:ridge|lightgbm,factorIds,customFactors:[],trainStart,trainEnd,validStart,validEnd,testStart,testEnd,labelHorizon:5,labelMode:next_open,hyperparameters:{},validation:{mode:single|rolling,trainYears:3,validMonths:6,testMonths:1,stepMonths:1},factorProcessing}；单次日期为空字符串可由服务按交易日70/15/15生成；
optimize.run {target:model|backtest,sampler:grid|tpe,trials,baseParameters:{},searchSpace:{},objective:valid:mse|valid:information_ratio,validation:{mode:single,...日期或窗口设置}}；模型参数搜索路径如hyperparameters.alpha，组合如topN；
selection.run {} 使用用户已启用的settings.selection。它依次更新、按月必要时重训、预测、组合、调仓清单及保存，不改实际持仓。未启用方案时说明用户需在选股页启用；不要替用户启用策略。
默认策略多头30只等权、95%仓位、周调仓。单股/行业/换手约束默认关闭；约束不足保留现金，不自动放宽。风险平价显示实际风险贡献；均值方差预期收益只能来自历史收益或真正的模型收益预测，不能用排名当收益。
交易标签T+1到T+H+1开盘；选参只用验证区间，测试区间独立。历史成员/行业/财报按当时可知，缺失不要用今天的数据回填。
可以辅助本轮功能配置，不设计新治理流程。禁止捏造实验ID、股票数据、文件路径或执行结果；无数据则建议更新，模型评分必须引用真实模型实验。常用因子momentum20/volatility20/volume_ratio/earnings_yield/roe/growth_profit或Alpha158 ROC5/ROC20/MA20。不保证获利。
proposal.spec.projectId为当前项目ID。引用的实际实验ID放在experimentIds以便界面打开。研究建议保持一个小而完整阶段，等待用户运行，不连续自动推进。'''


def _create_agent(service, project_id, model):
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent, ToolOutput

    class Spec(BaseModel):
        projectId: str
        kind: str
        parameters: dict
        name: str = ''

    class Proposal(BaseModel):
        title: str
        description: str
        spec: Spec

    class Answer(BaseModel):
        message: str
        phase: str
        proposals: list[Proposal] = Field(default_factory=list)
        experimentIds: list[str] = Field(default_factory=list)

    # Ling exposes tools/tool_choice, but not native response_format.
    agent = Agent(model, output_type=ToolOutput(Answer, strict=False), instructions=INSTRUCTIONS)

    @agent.tool_plain
    def get_project_context() -> dict:
        """读取本项目的数据概况、历史覆盖和已保存研究设置。"""
        return _project_context(service, project_id)

    @agent.tool_plain
    def list_experiments(limit: int = 20) -> list[dict]:
        """列出本项目真实实验的ID、配置、指标及可读取的结果表名。"""
        return [_experiment_summary(item) for item in service.store.experiments(project_id)[:max(1, min(limit, 100))]]

    @agent.tool_plain
    def read_experiment(experiment_id: str) -> dict:
        """读取某个真实实验的参数、指标、覆盖说明、约束冲突和结果表名。"""
        try:
            experiment = service.store.experiment(project_id, experiment_id)
            directory = Path(service.store.project(project_id)['path']) / '.research' / 'runs' / experiment_id
            return {'experiment': _experiment_summary(experiment, include_parameters=True), 'details': read_json(directory / 'details.json', {})}
        except ValueError as exc:
            return {'error': str(exc)}

    @agent.tool_plain
    def read_result_table(experiment_id: str, table: str, offset: int = 0, limit: int = 50,
                          symbol: str = '', start_date: str = '', end_date: str = '') -> dict:
        """按表名分页读取实验的实际持仓、调仓、因子、验证窗口或试参记录，可筛选股票和日期。"""
        try:
            return service.request('experiments.table', dict(
                projectId=project_id, experimentId=experiment_id, table=table, offset=offset,
                limit=min(200, max(1, limit)), symbol=symbol, startDate=start_date, endDate=end_date))
        except ValueError as exc:
            return {'error': str(exc)}

    @agent.tool_plain
    def get_current_stage() -> dict:
        """读取用户启动的研究阶段及每项任务的真实进度、失败原因和实验ID。"""
        return _stage_status(service, project_id)

    return agent


def chat(service, params):
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    config = service.store.settings().get('ai', {})
    if not config.get('model') or not config.get('baseUrl'):
        raise ValueError('请先在模型设置填写服务地址与模型')
    if 'openrouter.ai' in config['baseUrl'] and not config.get('apiKey'):
        raise ValueError('请先在模型设置填写 OpenRouter API Key')
    mode = params.get('mode', 'assist')
    if mode not in {'ask', 'assist', 'research'}:
        raise ValueError('未知 AI 模式')
    project_id = params['projectId']
    state = get_state(service, params)
    history = state['messages'] or params.get('history', [])
    user_message = {'role': 'user', 'content': params['message']}
    save_state(service, {'projectId': project_id, 'state': {'mode': mode, 'messages': history + [user_message]}})
    provider = OpenAIProvider(base_url=config['baseUrl'], api_key=config.get('apiKey') or 'local-no-key')
    model = OpenAIChatModel(config['model'], provider=provider)
    agent = _create_agent(service, project_id, model)
    experiments = service.store.experiments(project_id)
    prompt = json.dumps({
        'mode': mode, 'context': _project_context(service, project_id),
        'experiments': [_experiment_summary(item) for item in experiments[:20]],
        'stage': _stage_status(service, project_id), 'history': history[-20:], 'message': params['message'],
    }, ensure_ascii=False, default=str)
    try:
        response = agent.run_sync(prompt, model_settings={'temperature': float(config.get('temperature', .2)), 'timeout': 120})
    except Exception as exc:
        status = getattr(exc, 'status_code', None)
        if status in (401, 403):
            raise ValueError('AI 服务未授权，请检查 API Key 及模型访问权限') from exc
        if status == 429:
            raise ValueError('AI 服务当前限流或额度不足，请稍后重试或在设置调整服务') from exc
        if status in (502, 503, 504):
            raise ValueError('AI 服务当前不可用，请稍后重试') from exc
        raise
    answer = response.output.model_dump()
    if mode == 'ask':
        answer['proposals'] = []
    for proposal in answer['proposals']:
        spec = validate_spec(proposal['spec'])
        if spec['projectId'] != project_id or spec['kind'] == 'data.import':
            raise ValueError('AI 建议引用了其他项目或未经选择的导入文件')
        if spec['parameters'].get('code'):
            raise ValueError('请在策略代码编辑器确认 Python 代码后运行')
    known = {experiment['id'] for experiment in service.store.experiments(project_id)}
    if any(key not in known for key in answer['experimentIds']):
        raise ValueError('AI 返回了不存在的实验引用')
    assistant_message = dict(role='assistant', content=answer['message'], phase=answer['phase'], experimentIds=answer['experimentIds'])
    save_state(service, {'projectId': project_id, 'state': {
        'messages': history + [user_message, assistant_message], 'mode': mode,
        'phase': answer['phase'], 'proposals': answer['proposals'],
    }})
    return answer
