"""PydanticAI research tools and a portable, user-driven conversation."""
import json
from pathlib import Path

from .jobs import validate_spec
from .storage import now, read_json, write_json


def _state_path(service, project_id):
    return Path(service.store.project(project_id)['path']) / 'ai' / 'conversation.json'


def get_state(service, params):
    state = dict(messages=[], phase='', proposals=[], stageJobIds=[], mode='assist')
    if params.get('conversationId'):
        from .workbench import get_conversation
        state.update(get_conversation(service.store,params['conversationId'])['state'])
    else:
        state.update(read_json(_state_path(service, params.get('projectId')), {}))
    return state


def save_state(service, params):
    state = get_state(service, params)
    patch = params['state']
    for key in ('messages', 'phase', 'proposals', 'stageJobIds', 'mode'):
        if key in patch:
            state[key] = patch[key]
    state['updatedAt'] = now()
    if params.get('conversationId'):
        from .workbench import get_conversation, save_conversation
        conversation = get_conversation(service.store,params['conversationId'])
        conversation['state'] = state
        save_conversation(service.store,conversation)
    else:
        write_json(_state_path(service, params.get('projectId')), state)
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
输出中的message只用简洁中文说明变更、结果或下一步，不粘贴JSON、代码块或对象ID。用户要求辅助配置或准备运行时，具体参数必须放入proposals数组，每项包含title、description和spec；只在message写参数不会生成界面的保存或运行按钮。不要漏掉proposals，只有问答、讨论或确实需要用户补充信息时才返回空数组。
未要求修改的参数沿用关联策略的实际值，尤其是交易成本与日期，不用下方默认示例覆盖已有值。selectedFactors和factorProcessing以策略settings根字段为准。
任务kind及参数：
data.update {source:baostock|akshare,financials:true,startDate,endDate}；
factor.analyze {factorIds,customFactors:[],periods:[1,5,10,20],quantiles:5,labelMode:next_open|close,factorProcessing:{directions:{因子ID:1或-1},winsorize:mad|none,madScale:3,standardize:true,neutralizeIndustry:false,neutralizeSize:false}}；
backtest.run {template:single_factor|multi_factor|model_score,factorIds,weights:{},topN:30,rebalance:weekly,capital:1000000,benchmark:csi300|csi500,portfolio:{method:equal|score|risk_parity|mean_variance,grossExposure:0.95,maxWeight:null,industryCap:null,turnoverLimit:null,lookback:252,minObservations:126,riskAversion:3,returnSource:historical|model},costs:{commissionBuy:0.0003,commissionSell:0.0003,minCommission:5,stampDuty:historical,transferFee:0.00001,slippage:0.001,volumeParticipation:0.1},factorProcessing,modelExperimentId?}；
model.train {model:ridge|lightgbm,factorIds,customFactors:[],trainStart,trainEnd,validStart,validEnd,testStart,testEnd,labelHorizon:5,labelMode:next_open,hyperparameters:{},validation:{mode:single|rolling,trainYears:3,validMonths:6,testMonths:1,stepMonths:1},factorProcessing}；单次日期为空字符串可由服务按交易日70/15/15生成；
optimize.run {target:model|backtest,sampler:grid|tpe,trials,baseParameters:{},searchSpace:{},objective:valid:mse|valid:information_ratio,validation:{mode:single,...日期或窗口设置}}；模型参数搜索路径如hyperparameters.alpha，组合如topN；
selection.run {strategies:[{projectId,strategyId,allocation}],portfolio:{...},updateData:true} 使用会话中明确关联且已启用的策略与其资金占比，任务本身不填projectId/strategyId，生成基于全局持仓的合并调仓清单。它依次更新、按月必要时重训、预测、组合、调仓清单及保存，不改实际持仓。未启用方案时说明用户需在选股页启用；不要替用户启用策略或改变资金占比。
默认策略多头30只等权、95%仓位、周调仓。单股/行业/换手约束默认关闭；约束不足保留现金，不自动放宽。风险平价显示实际风险贡献；均值方差预期收益只能来自历史收益或真正的模型收益预测，不能用排名当收益。
交易标签T+1到T+H+1开盘；选参只用验证区间，测试区间独立。历史成员/行业/财报按当时可知，缺失不要用今天的数据回填。
可以辅助本轮功能配置，不设计新治理流程。禁止捏造实验ID、股票数据、文件路径或执行结果；无数据则建议更新，模型评分必须引用真实模型实验。常用因子momentum20/volatility20/volume_ratio/earnings_yield/roe/growth_profit或Alpha158 ROC5/ROC20/MA20。不保证获利。
会话的context.attachedObjects列出明确关联对象。因子、回测、模型及寻优建议必须使用目标对象的projectId和strategyId；存在多项策略而用户没有明确选择时先询问。data.update使用关联的数据或项目范围。全局合并选股使用上述strategies数组。
引用实验使用experimentRefs:[{kind:experiment,projectId,experimentId}]，全局实验projectId为null；experimentIds也可返回无歧义的真实ID。因子结果的IC、RankIC、分组收益已包含实验factorProcessing.directions，不能把负向因子的结果再翻转一次。阶段完成后先用get_current_stage读取状态，再用read_experiment或read_result_table读取新实验。研究建议保持一个小而完整阶段，等待用户运行，不连续自动推进。'''

EXPLAIN_INSTRUCTIONS = '''你是中文量化研究助手。本次只回答用户问题，proposals为空，不运行研究或修改配置。
必须读取关联实验或所问结果表，按实际字段解释；缺失就说明缺失。不能用常见参数或默认值替代实验保存的配置。
收益比较使用同区间的策略total_return与benchmark_total_return，annualized_return单独标为年化。回撤按实际值说明，四舍五入不能改变大于或小于某阈值的判断。
交易表amount是实际股数，adjustedAmount是复权换算量。股票数上限读取parameters.topN，不自行补充未核对的策略描述或因子名称。
只写用户所问的结论，不增加无关配置概括。用简洁中文，所有数字必须在工具或上下文中有对应依据。引用真实实验使用experimentRefs:[{kind:experiment,projectId,experimentId}]。
当前标签页不改变会话的明确关联对象。讨论下一步时给建议，不宣称未经运行的结果。'''


def _create_agent(service, project_id, model, attached=None, conversation_id=None, mode='assist'):
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent, ToolOutput

    class Spec(BaseModel):
        projectId: str | None = None
        strategyId: str | None = None
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
        proposals: list[Proposal]
        experimentIds: list[str] = Field(default_factory=list)
        experimentRefs: list[dict] = Field(default_factory=list)

    # Ling exposes tools/tool_choice, but not native response_format.
    agent = Agent(model, output_type=ToolOutput(Answer, strict=False), instructions=EXPLAIN_INSTRUCTIONS if mode=='ask' else INSTRUCTIONS)

    @agent.tool_plain
    def get_project_context() -> dict:
        """读取本项目的数据概况、历史覆盖和已保存研究设置。"""
        return attached_context(service, attached) if attached is not None else _project_context(service, project_id)

    @agent.tool_plain
    def list_experiments(limit: int = 20) -> list[dict]:
        """列出本项目真实实验的ID、指标及结果表名；配置通过read_experiment读取。"""
        return [_experiment_summary(item) for item in attached_experiments(service,attached,project_id,conversation_id)[:max(1, min(limit, 100))]]

    @agent.tool_plain
    def read_experiment(experiment_id: str, project_id_ref: str | None = None) -> dict:
        """读取某个真实实验的参数、指标、覆盖说明、约束冲突和结果表名。"""
        try:
            matches = [item for item in attached_experiments(service,attached,project_id,conversation_id) if item['id']==experiment_id and (project_id_ref is None or item.get('projectId')==project_id_ref)]
            if len(matches)>1:
                raise ValueError('多个项目存在此实验ID，请明确project_id_ref')
            if not matches:
                raise ValueError('实验未关联此会话或不存在')
            experiment = matches[0]
            directory = Path(service.store.project(experiment.get('projectId'))['path']) / '.research' / 'runs' / experiment_id
            return {'experiment': _experiment_summary(experiment, include_parameters=True), 'details': read_json(directory / 'details.json', {})}
        except ValueError as exc:
            return {'error': str(exc)}

    @agent.tool_plain
    def read_result_table(experiment_id: str, table: str, offset: int = 0, limit: int = 50,
                          symbol: str = '', start_date: str = '', end_date: str = '', project_id_ref: str | None = None) -> dict:
        """按表名分页读取实验的实际持仓、调仓、因子、验证窗口或试参记录，可筛选股票和日期。"""
        try:
            matches = [item for item in attached_experiments(service,attached,project_id,conversation_id) if item['id']==experiment_id and (project_id_ref is None or item.get('projectId')==project_id_ref)]
            if len(matches)>1:
                raise ValueError('多个项目存在此实验ID，请明确project_id_ref')
            if not matches:
                raise ValueError('实验未关联此会话或不存在')
            return service.request('experiments.table', dict(
                projectId=matches[0].get('projectId'), experimentId=experiment_id, table=table, offset=offset,
                limit=min(200, max(1, limit)), symbol=symbol, startDate=start_date, endDate=end_date))
        except ValueError as exc:
            return {'error': str(exc)}

    @agent.tool_plain
    def get_current_stage() -> dict:
        """读取用户启动的研究阶段及每项任务的真实进度、失败原因和实验ID。"""
        if conversation_id:
            state = get_state(service,{'conversationId':conversation_id})
            jobs = {job['id']:job for job in service.store.list('job')}
            return {'phase':state['phase'],'jobs':[{k:jobs[key].get(k) for k in ('id','projectId','strategyId','kind','status','message','experimentId')} if key in jobs else {'id':key,'status':'unavailable'} for key in state.get('stageJobIds',[])]}
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
    project_id = params.get('projectId')
    attached = None
    state_params = {'projectId':project_id}
    if params.get('conversationId'):
        from .workbench import get_conversation
        attached = get_conversation(service.store,params['conversationId'])['context']
        project_id = None
        state_params = {'conversationId':params['conversationId']}
    state = get_state(service, params)
    history = state['messages'] or params.get('history', [])
    user_message = {'role': 'user', 'content': params['message']}
    save_state(service, {**state_params, 'state': {'mode': mode, 'messages': history + [user_message]}})
    provider = OpenAIProvider(base_url=config['baseUrl'], api_key=config.get('apiKey') or 'local-no-key')
    model = OpenAIChatModel(config['model'], provider=provider)
    agent = _create_agent(service, project_id, model, attached, params.get('conversationId'), mode)
    experiments = attached_experiments(service,attached,project_id,params.get('conversationId'))
    prompt = json.dumps({
        'mode': mode, 'context': attached_context(service,attached) if attached is not None else _project_context(service,project_id),
        'experiments': [_experiment_summary(item) for item in experiments[:20]],
        'stage': {'phase':state['phase'],'stageJobIds':state.get('stageJobIds',[])} if attached is not None else _stage_status(service, project_id), 'history': history[-20:], 'message': params['message'],
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
    if not answer.get('experimentRefs') and not answer['experimentIds']:
        # Explicitly attached experiments remain clickable even if the model omits IDs.
        answer['experimentRefs'] = [{'kind':'experiment','projectId':ref.get('projectId'),'experimentId':ref['experimentId']}
                                    for ref in attached or [] if ref.get('experimentId')]
    for proposal in answer['proposals']:
        spec = validate_spec(proposal['spec'])
        linked_strategies = {(ref.get('projectId'),ref.get('strategyId')) for ref in attached or [] if ref.get('strategyId')}
        if attached is not None and spec['kind'] == 'selection.run' and 'strategies' not in spec['parameters']:
            from .workbench import get_strategy
            selected = [(pid,sid) for pid,sid in linked_strategies if (not spec.get('projectId') or pid==spec['projectId']) and (not spec.get('strategyId') or sid==spec['strategyId'])]
            if len(selected) != 1:
                raise ValueError('请明确本次每日选股使用的关联策略及资金占比')
            pid,sid = selected[0]
            strategy = get_strategy(service.store,pid,sid)
            spec['parameters']['strategies'] = [{'projectId':pid,'strategyId':sid,'allocation':strategy['allocation']}]
            spec['projectId'] = None
            spec['strategyId'] = None
        merged_selection = attached is not None and spec['kind'] == 'selection.run' and not spec.get('projectId') and isinstance(spec['parameters'].get('strategies'),list) and bool(spec['parameters']['strategies'])
        if merged_selection:
            if any(not isinstance(ref,dict) or (ref.get('projectId'),ref.get('strategyId')) not in linked_strategies for ref in spec['parameters']['strategies']):
                raise ValueError('合并选股建议包含未关联的策略')
        elif (spec.get('projectId') not in {ref.get('projectId') for ref in attached} if attached is not None else spec.get('projectId') != project_id) or spec['kind'] == 'data.import':
            raise ValueError('AI 建议引用了其他项目或未经选择的导入文件')
        if attached is not None and spec['kind'] in {'factor.analyze','backtest.run','model.train','optimize.run'} and not spec.get('strategyId'):
            candidates = [strategy_id for pid,strategy_id in linked_strategies if pid == spec.get('projectId')]
            if len(candidates) != 1:
                raise ValueError('请在会话中明确本次建议使用哪一份关联策略')
            spec['strategyId'] = candidates[0]
        if attached is not None and spec.get('strategyId') and (spec.get('projectId'),spec['strategyId']) not in linked_strategies:
            raise ValueError('AI建议引用了未关联的策略')
        if spec['parameters'].get('code'):
            raise ValueError('请在策略代码编辑器确认 Python 代码后运行')
    known = {experiment['id'] for experiment in experiments}
    if any(key not in known for key in answer['experimentIds']):
        raise ValueError('AI 返回了不存在的实验引用')
    known_refs = {(item.get('projectId'),item['id']) for item in experiments}
    for ref in answer.get('experimentRefs',[]):
        if (ref.get('projectId'),ref.get('experimentId')) not in known_refs:
            raise ValueError('AI返回了不存在或未关联的实验引用')
    for key in answer['experimentIds']:
        matches = [item for item in experiments if item['id']==key]
        if len(matches)>1 and not any(ref.get('experimentId')==key for ref in answer.get('experimentRefs',[])):
            raise ValueError('跨项目实验ID有歧义，请使用明确实验引用')
        if len(matches)==1 and not any(ref.get('experimentId')==key for ref in answer.get('experimentRefs',[])):
            answer.setdefault('experimentRefs',[]).append({'kind':'experiment','projectId':matches[0].get('projectId'),'experimentId':key})
    assistant_message = dict(role='assistant', content=answer['message'], phase=answer['phase'], experimentIds=answer['experimentIds'],experimentRefs=answer.get('experimentRefs',[]))
    save_state(service, {**state_params, 'state': {
        'messages': history + [user_message, assistant_message], 'mode': mode,
        'phase': answer['phase'], 'proposals': answer['proposals'],
    }})
    return answer


def attached_experiments(service, attached, project_id=None, conversation_id=None):
    if attached is None:
        return service.store.experiments(project_id)
    result = {}
    for ref in attached:
        if ref.get('experimentId'):
            item = service.store.experiment(ref.get('projectId'),ref['experimentId'])
            result[(item.get('projectId'),item['id'])] = item
        elif ref.get('strategyId'):
            for item in service.store.experiments(ref.get('projectId')):
                if item.get('strategyId') == ref['strategyId']:
                    result[(item.get('projectId'),item['id'])] = item
    if conversation_id:
        state = get_state(service, {'conversationId':conversation_id})
        stage_jobs = set(state.get('stageJobIds', []))
        for job in service.store.list('job'):
            if job['id'] not in stage_jobs or not job.get('experimentId'):
                continue
            try:
                item = service.store.experiment(job.get('projectId'),job['experimentId'])
                result[(item.get('projectId'),item['id'])] = item
            except ValueError:
                # A deleted experiment remains visible as a job, without invented results.
                continue
    return list(result.values())


def attached_context(service, attached):
    from .workbench import get_strategy
    result = []
    for ref in attached:
        item = {'reference':ref}
        if ref.get('strategyId'):
            strategy = get_strategy(service.store,ref['projectId'],ref['strategyId'])
            item['strategy'] = {key:strategy[key] for key in ('id','name','universe','settings','enabled','allocation','active') if key in strategy}
        if ref.get('symbol'):
            item['stock'] = service.request('market.stock',{'projectId':ref.get('projectId'),'symbol':ref['symbol']})
            item['bars'] = service.request('data.bars',{'projectId':ref.get('projectId'),'symbol':ref['symbol'],'limit':60})
        if ref.get('experimentId'):
            detail = service.experiment_details(ref.get('projectId'),ref['experimentId'])
            item['experiment'] = _experiment_summary(detail['experiment'],True)
            item['details'] = detail['details']
            item['tables'] = detail['tables']
        if ref['kind'] == 'data':
            item['data'] = service.request('data.preview',{'projectId':ref.get('projectId')})
        if ref['kind'] == 'positions':
            item['positions'] = service.request('positions.get',{})
        result.append(item)
    return {'attachedObjects':result,'instruction':'仅这些明确关联对象是会话上下文，当前界面标签不改变关联。'}
