"""PydanticAI research tools and a portable, user-driven conversation."""
import json
from pathlib import Path

from .jobs import validate_spec
from .storage import now, read_json, write_json


def _state_path(service, project_id):
    return Path(service.store.project(project_id)['path']) / 'ai' / 'conversation.json'


def get_state(service, params):
    state = dict(messages=[], phase='', proposals=[], stageJobIds=[], stageEvents=[], mode='assist')
    if params.get('conversationId'):
        from .workbench import get_conversation
        state.update(get_conversation(service.store,params['conversationId'])['state'])
    else:
        state.update(read_json(_state_path(service, params.get('projectId')), {}))
    return state


def save_state(service, params):
    state = get_state(service, params)
    patch = params['state']
    for key in ('messages', 'phase', 'proposals', 'stageJobIds', 'stageEvents', 'mode'):
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


def _project_context(service, project_id, project=None):
    from .data import preview
    project = project if project is not None else service.store.project(project_id)
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


def _stage_status(service, project_id=None, conversation_id=None):
    state = get_state(service, {'conversationId': conversation_id} if conversation_id else {'projectId': project_id})
    jobs = {job['id']: job for job in state.get('stageEvents', []) if isinstance(job, dict) and job.get('id')}
    jobs.update({job['id']: job for job in service.store.list('job', None if conversation_id else project_id)})
    selected = []
    for key in state['stageJobIds']:
        job = jobs.get(key)
        if project_id and job and job.get('projectId')!=project_id:continue
        item = {field: job.get(field) for field in (
            'id', 'projectId', 'strategyId', 'kind', 'name', 'status', 'progress', 'message', 'experimentId',
        )} if job else {'id': key, 'status': 'unavailable'}
        if job and job.get('kind') == 'rdagent.run' and job.get('projectId'):
            item['nativeResearch'] = service.request('rdagent.status', {
                'projectId': job['projectId'], 'jobId': job['id']})
        selected.append(item)
    return {'phase': state['phase'], 'proposals': state['proposals'], 'jobs': selected}


TASK_GUIDANCE = '''可辅助编写因子表达式与完整日线策略。自定义因子使用customFactors:[{id,name,expression}]及相应factorIds，表达式遵守Qlib历史窗口。完整规则使用backtest.run的rules:[{name,action:entry|add|reduce|exit,conditions:[{field,op:gt|gte|lt|lte|eq|ne,value:number}],weight:number}]；退出或减仓优先。Python策略放入dailyCode，定义decide(context)返回{targets:{股票:目标权重},state:{},reasons:[]}，只能使用信号日已知上下文；旧code仅选股评分。所有生成内容保存为独立候选，用户可查看中文逻辑和完整代码、运行实验、采用到草稿；保存候选不启用策略。
任务kind及参数：
data.update {source:baostock|akshare,financials:true,startDate,endDate}；
factor.analyze {factorIds,customFactors:[],periods:[1,5,10,20],quantiles:5,labelMode:next_open|close,factorProcessing:{directions:{因子ID:1或-1},winsorize:mad|none,madScale:3,standardize:true,neutralizeIndustry:false,neutralizeSize:false}}；
backtest.run {template:single_factor|multi_factor|model_score,factorIds,weights:{},topN:30,rebalance:weekly,capital:1000000,benchmark:csi300|csi500,portfolio:{method:equal|score|risk_parity|mean_variance,grossExposure:0.95,maxWeight:null,industryCap:null,turnoverLimit:null,lookback:252,minObservations:126,riskAversion:3,returnSource:historical|model},costs:{commissionBuy:0.0003,commissionSell:0.0003,minCommission:5,stampDuty:historical,transferFee:0.00001,slippage:0.001,volumeParticipation:0.1},factorProcessing,modelExperimentId?}；
model.train {model:ridge|lightgbm,factorIds,customFactors:[],trainStart,trainEnd,validStart,validEnd,testStart,testEnd,labelHorizon:5,labelMode:next_open,hyperparameters:{},validation:{mode:single|rolling,trainYears:3,validMonths:6,testMonths:1,stepMonths:1},factorProcessing}；六日期需明确；缺少划分时先询问，不自动选择日期；
optimize.run {target:model|backtest,sampler:grid|tpe,trials,baseParameters:{},searchSpace:{},objective:valid:mse|valid:information_ratio,validation:{mode:single,...日期或窗口设置}}；模型参数搜索路径如hyperparameters.alpha，组合如topN；
selection.run {strategies:[{projectId,strategyId,allocation}],portfolio:{...},updateData:true} 使用会话中明确关联且已启用的策略与其资金占比，任务本身不填projectId/strategyId，生成基于全局持仓的合并调仓清单。它依次更新、按月必要时重训、预测、组合、调仓清单及保存，不改实际持仓。未启用方案时说明用户需在选股页启用；不要替用户启用策略或改变资金占比。
rdagent.run {objective,action:factor|model|joint,rounds:3,codeRepairRounds:1,trainStart,trainEnd,validStart,validEnd,testStart,testEnd,labelHorizon:5,labelMode:next_open,factorIds,evaluationBacktest:{...回测参数}} 使用关联策略的真实数据与成本，运行原生RD-Agent-Quant/CoSTEER提出、编写和评价候选。六日期必须明确且不重叠；日期不齐时先讨论，不猜测。用户要求原生RD-Agent研究时准备这一阶段，阶段内最多三轮，结束后读取rounds及各候选真实实验，再讨论下一阶段。测试集不提供给原生循环选参；通过代码检查不代表研究质量。缺环境或服务时说明实际失败，不能用普通单次因子任务冒充原生循环。完整日线交易规则仍用独立策略候选表达，不能把factor/model循环说成已编写完整交易规则。
'''

INSTRUCTIONS = '''你是中文沪深A股日线研究助手。依据工具返回的真实数据与实验解释，不能把建议写成运行结果。
工具只读数据，不会运行研究或修改持仓。先理解已有配置；解释实验必须读取对应实验，分析明细可按需读取结果表。
ask只问答，proposals为空。assist提供可供用户应用的完整参数。research只规划当前一个阶段；用户点击运行后，读取任务实际状态和结果，再与用户讨论下一阶段。任务进行中不能声称完成，失败或中断要说明实际原因。
输出中的message只用简洁中文说明变更、结果或下一步，不粘贴JSON、代码块或对象ID。用户要求辅助配置或准备运行时，具体参数必须放入proposals数组，每项包含title、description和spec；只在message写参数不会生成界面的保存或运行按钮。不要漏掉proposals，只有问答、讨论或确实需要用户补充信息时才返回空数组。
未要求修改的参数沿用关联策略的实际值，尤其是交易成本与日期，不用下方默认示例覆盖已有值。selectedFactors和factorProcessing以策略settings根字段为准。
''' + TASK_GUIDANCE + '''默认策略多头30只等权、95%仓位、周调仓。单股/行业/换手约束默认关闭；约束不足保留现金，不自动放宽。风险平价显示实际风险贡献；均值方差预期收益只能来自历史收益或真正的模型收益预测，不能用排名当收益。
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


def _create_agent(service, project_id, model, attached=None, conversation_id=None, mode='assist', execution=False, frozen_context=None):
    from .ai_settings import instructions as user_instructions
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
        summaryUpdate: dict | None = None
        uiBlocks: list[dict] = Field(default_factory=list)
        reportCitations: list[dict] = Field(default_factory=list)

    # Ling exposes tools/tool_choice, but not native response_format.
    execution_instructions='''你是研究助手。解释或讨论只读；用户明确要求执行时调用run_research，沿既有参数与明确日期运行当前阶段。
缺关键条件先询问，不猜日期、股票池、费用，不启用策略，不更改持仓。工具返回真实完成结果后才可说明成功或提交依赖。
同一阶段完成后讨论下一步，不自行扩展研究。运行中补充在步骤边界读取，当前任务参数不改。失败暂停，不重复提交。
候选建议不等于用户决定。message用中文说明实际结果；experimentIds只能使用工具返回值。未执行时不得声称执行。
使用get_current_stage和read_experiment核对真实结果。proposals可为空，summaryUpdate仅追加明确用户决定和实际实验结论。'''
    formula_instructions = '''\n通达信公式可先读取当前项目或个人公式库，再调用evaluate_formula用HQChart原生引擎核对结果与适用性；失败如实说明，不编造支持函数或计算结果。
公式预览不保存因子。只有用户明确要求保存且存在save_formula_draft工具时，才创建新公式草稿；不覆盖已有公式，不启用策略。工具返回成功才可说已保存；说明实际名称与项目库或个人库范围。'''
    execution_instructions += '\n' + TASK_GUIDANCE + '\n探索因子、探索模型和比较候选默认使用原生rdagent.run；指定已有因子分析、训练或回测使用对应普通任务。阶段内按依赖顺序执行，阶段结束讨论，不自动进入下一阶段。显式执行指令可直接调用run_research，不要只返回待运行建议。日期缺失先询问。'
    finish_instructions = '\n工具结果已经作为工具消息返回。信息足够时直接用中文回答并结束；也可调用final_answer返回引用、方案按钮等结构化回答。不要为结束回答再次读取相同资料。'
    agent = Agent(model, output_type=[ToolOutput(Answer, name='final_answer', strict=False), str],
                  instructions=(EXPLAIN_INSTRUCTIONS if mode=='ask' else execution_instructions if execution else INSTRUCTIONS) + formula_instructions + finish_instructions + user_instructions(service.store,project_id))

    @agent.output_validator
    def normalize_answer(output: Answer | str) -> Answer:
        # Text is a valid final response; callers still receive the existing Answer shape.
        if isinstance(output, str):
            if not output.strip():
                from pydantic_ai import ModelRetry
                raise ModelRetry('请根据已经读取的资料给出非空中文回答。')
            return Answer(message=output, phase='', proposals=[])
        return output
    from .report_ai import register_tools
    register_tools(agent, service, project_id, attached, conversation_id, execution and mode != 'ask')

    @agent.tool_plain
    def get_project_context() -> dict:
        """读取本项目的数据概况、历史覆盖和已保存研究设置。"""
        result=frozen_context if frozen_context is not None else attached_context(service, attached) if attached is not None else _project_context(service, project_id)
        if project_id:
            from .project_summary import get
            result={**result,'projectSummary':get(service.store,project_id)}
        return result

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
                          symbol: str = '', start_date: str = '', end_date: str = '', project_id_ref: str | None = None,
                          factor_id: str = '', trade_id: str = '', model_window_id: str = '') -> dict:
        """按表名分页读取实验的实际持仓、调仓、因子、验证窗口或试参记录，可筛选股票和日期。"""
        try:
            matches = [item for item in attached_experiments(service,attached,project_id,conversation_id) if item['id']==experiment_id and (project_id_ref is None or item.get('projectId')==project_id_ref)]
            if len(matches)>1:
                raise ValueError('多个项目存在此实验ID，请明确project_id_ref')
            if not matches:
                raise ValueError('实验未关联此会话或不存在')
            return service.request('experiments.table', dict(
                projectId=matches[0].get('projectId'), experimentId=experiment_id, table=table, offset=offset,
                limit=min(200, max(1, limit)), symbol=symbol, startDate=start_date, endDate=end_date,
                factorId=factor_id, tradeId=trade_id, modelWindowId=model_window_id))
        except ValueError as exc:
            return {'error': str(exc)}

    @agent.tool_plain
    def get_current_stage() -> dict:
        """读取用户启动的研究阶段及每项任务的真实进度、失败原因和实验ID。"""
        return _stage_status(service, project_id, conversation_id)

    from . import formulas

    def formula_scope(scope):
        if scope not in {'project', 'personal'}:
            raise ValueError('公式保存范围只能是project或personal')
        if scope == 'project' and not project_id:
            raise ValueError('当前会话没有所属项目，请明确使用个人公式库')
        return project_id if scope == 'project' else None

    @agent.tool_plain
    def read_formula_library(scope: str = 'project', formula_id: str | None = None) -> dict:
        """读取当前项目或个人公式库；返回真实脚本和参数，不访问其他项目。"""
        try:
            pid = formula_scope(scope)
            records = formulas.library(service.store, 'formula.library.get' if formula_id else 'formula.library.list',
                                       {'projectId': pid, 'id': formula_id})
            return {'scope': scope, 'projectId': pid, 'records': records}
        except (ValueError, OSError) as exc:
            return {'error': '读取公式失败：' + str(exc)}

    @agent.tool_plain
    def evaluate_formula(formula: dict, instrument: dict | None = None, purpose: str = 'chart',
                         start_date: str | None = None, end_date: str | None = None,
                         price_basis: str = 'raw', symbols: list[str] | None = None) -> dict:
        """使用HQChart原生引擎预览公式与适用性。只读，不保存研究因子或修改策略。"""
        try:
            return formulas.evaluate(service.store, {'projectId': project_id, 'formula': formula,
                'instrument': instrument, 'purpose': purpose, 'startDate': start_date, 'endDate': end_date,
                'priceBasis': price_basis, 'symbols': symbols, 'saveFactor': False})
        except (ValueError, OSError) as exc:
            return {'error': '公式预览失败：' + str(exc)}

    if execution and mode != 'ask':
        saved_drafts = {}

        @agent.tool_plain
        def save_formula_draft(name: str, script: str, scope: str = 'project',
                               parameters: list[dict] | None = None, output: str | None = None,
                               price_basis: str = 'raw') -> dict:
            """仅用户明确要求保存公式时调用。创建独立新草稿，不覆盖已有公式、不启用策略、不保存研究因子。
            返回真实formulaId、名称和保存范围。相同调用在本次执行内复用已保存草稿。
            """
            try:
                pid = formula_scope(scope)
                if price_basis not in {'raw', 'adjusted'}:
                    raise ValueError('价格口径只能是raw或adjusted')
                record = {'name': name, 'script': script, 'parameters': parameters or [], 'output': output,
                          'priceBasis': price_basis, 'status': 'draft', 'sourceConversationId': conversation_id}
                key = json.dumps([pid, record], sort_keys=True, ensure_ascii=False)
                if key not in saved_drafts:
                    saved = formulas.library(service.store, 'formula.library.save', {'projectId': pid, 'record': record})
                    saved_drafts[key] = {'formulaId': saved['id'], 'name': saved['name'], 'scope': scope,
                                         'projectId': pid, 'record': saved}
                return saved_drafts[key]
            except (ValueError, OSError) as exc:
                return {'error': '保存公式草稿失败：' + str(exc)}

    return agent


def chat(service, params):
    from copy import deepcopy
    params=deepcopy(params)
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from .ai_settings import resolve
    config = resolve(service.store,'research' if params.get('mode')=='research' else 'reports' if any(ref.get('kind')=='report' for ref in params.get('context',[])) else 'conversation')
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
        conversation=get_conversation(service.store,params['conversationId'])
        attached = deepcopy(conversation['context'])
        if 'projectId' in conversation:
            if 'projectId' in params and params['projectId']!=conversation['projectId']:
                raise ValueError('发送时的项目与会话所属项目不一致，请在正确项目中发送')
            project_id=conversation['projectId']
        state_params = {'conversationId':params['conversationId']}
    state = get_state(service, params)
    history = state['messages'] or params.get('history', [])
    if attached is not None:
        from copy import deepcopy
        references = params.get('references', params.get('context', attached))
        if not isinstance(references, list) or any(not isinstance(ref, dict) or not ref.get('kind') for ref in references):
            raise ValueError('消息关联对象格式无效')
        attached = deepcopy(references)
        if project_id and any(ref.get('projectId') not in (None,project_id) for ref in attached):
            raise ValueError('项目会话不能引用其他项目，请使用全局会话')
        if project_id and not attached:attached=None
    from . import project_summary
    summary=project_summary.get(service.store,project_id) if project_id else None
    summary_history=project_summary.histories(service.store,project_id,summary) if summary and not summary.get('historyInitialized',False) else []
    user_message = {'role': 'user', 'content': params['message']}
    if attached is not None:
        user_message['experimentRefs'] = attached
    save_state(service, {**state_params, 'state': {'mode': mode, 'messages': history + [user_message]}})
    provider = OpenAIProvider(base_url=config['baseUrl'], api_key=config.get('apiKey') or 'local-no-key')
    model = OpenAIChatModel(config['model'], provider=provider)
    agent = _create_agent(service, project_id, model, attached, params.get('conversationId'), mode)
    experiments = attached_experiments(service,attached,project_id,params.get('conversationId'))
    prompt = json.dumps({
        'mode': mode, 'context': attached_context(service,attached) if attached is not None else _project_context(service,project_id),
        'project':_project_context(service,project_id) if project_id else None,'projectSummary':summary,
        'summaryHistory':summary_history,
        'summaryInstructions':'可在同一响应summaryUpdate追加goals/userDecisions/experimentFindings/hypotheses/unresolved。用户决定必须逐字引用本次明确决定，建议和推测放hypotheses。实验条目必须有experimentId/date/conclusion。不要重建已清除摘要，也不要替换手工内容。',
        'experiments': [_experiment_summary(item) for item in experiments[:20]],
        'stage': _stage_status(service, project_id, params.get('conversationId')), 'history': history[-20:], 'message': params['message'],
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
    if params.get('conversationId'):
        latest=get_conversation(service.store,params['conversationId'])
        if latest.get('projectId')!=conversation.get('projectId') or ('projectId' in latest)!=('projectId' in conversation):
            raise ValueError('回答期间会话所属项目已改变，本次回答未写入新项目，请在目标项目重新发送')
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
        if attached is not None and spec['kind'] in {'factor.analyze','backtest.run','model.train','optimize.run','rdagent.run'} and not spec.get('strategyId'):
            candidates = [strategy_id for pid,strategy_id in linked_strategies if pid == spec.get('projectId')]
            if len(candidates) != 1:
                raise ValueError('请在会话中明确本次建议使用哪一份关联策略')
            spec['strategyId'] = candidates[0]
        if attached is not None and spec.get('strategyId') and (spec.get('projectId'),spec['strategyId']) not in linked_strategies:
            raise ValueError('AI建议引用了未关联的策略')
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
    from .candidates import save as save_candidate, KINDS as candidate_kinds
    for proposal in answer['proposals']:
        spec = proposal['spec']
        category = next((name for name, kind in candidate_kinds.items() if spec['kind'] == kind), None)
        if category and spec.get('projectId') and spec.get('strategyId'):
            candidate = save_candidate(service.store, spec['projectId'], dict(
                strategyId=spec['strategyId'], kind=category, name=proposal['title'], description=proposal['description'],
                changeSummary=proposal['description'], spec=spec, sourceConversationId=params.get('conversationId')))
            proposal['candidateId'] = candidate['id']
            proposal['spec'] = {**candidate['spec'], 'candidateId': candidate['id']}
    from .report_ai import validate_output
    validate_output(service, answer, project_id, attached)
    assistant_message = dict(role='assistant', content=answer['message'], phase=answer['phase'], experimentIds=answer['experimentIds'],experimentRefs=answer.get('experimentRefs',[]), uiBlocks=answer.get('uiBlocks', []), reportCitations=answer.get('reportCitations', []))
    save_state(service, {**state_params, 'state': {
        'messages': history + [user_message, assistant_message], 'mode': mode,
        'phase': answer['phase'], 'proposals': answer['proposals'],
    }})
    if project_id:
        summary_users=params['message']+'\n'+'\n'.join(str(m.get('content','')) for h in summary_history for m in h['messages'] if m.get('role')=='user')
        summary_sources=list(dict.fromkeys(([params['conversationId']] if params.get('conversationId') else [])+[h['conversationId'] for h in summary_history]))
        try:project_summary.append_response(service.store,project_id,answer.get('summaryUpdate'),summary['revision'],summary_users,summary_sources)
        except (ValueError,TypeError,KeyError):
            answer['summaryWarning']='本次摘要更新格式或来源不完整，已保留原摘要。'
    return answer


def attached_experiments(service, attached, project_id=None, conversation_id=None):
    if attached is None:
        return service.store.experiments(project_id)
    result = {}
    for ref in attached:
        if ref.get('candidateId'):
            from .candidates import get
            try:
                candidate = get(service.store, ref.get('projectId'), ref['candidateId'])
            except (ValueError, OSError):
                continue
            for link in candidate.get('experiments', []):
                try:
                    item = service.store.experiment(ref.get('projectId'), link['experimentId'])
                except (ValueError, OSError):
                    continue
                result[(item.get('projectId'), item['id'])] = item
        elif ref.get('experimentId'):
            try:
                item = service.store.experiment(ref.get('projectId'),ref['experimentId'])
            except (ValueError, OSError):
                continue
            result[(item.get('projectId'),item['id'])] = item
        elif ref.get('strategyId'):
            for item in service.store.experiments(ref.get('projectId')):
                if item.get('strategyId') == ref['strategyId']:
                    result[(item.get('projectId'),item['id'])] = item
    if conversation_id:
        state = get_state(service, {'conversationId':conversation_id})
        stage_jobs = set(state.get('stageJobIds', []))
        retained = {job['id']: job for job in state.get('stageEvents', []) if isinstance(job, dict) and job.get('id')}
        retained.update({job['id']: job for job in service.store.list('job')})
        for job in retained.values():
            if job['id'] not in stage_jobs or not job.get('experimentId'):
                continue
            try:
                item = service.store.experiment(job.get('projectId'),job['experimentId'])
                result[(item.get('projectId'),item['id'])] = item
            except ValueError:
                # A deleted experiment remains visible as a job, without invented results.
                continue
    # A native research stage links its ordinary candidate evaluations. They remain
    # readable when the conversation links only the stage rather than all strategies.
    for experiment in list(result.values()):
        if experiment['kind'] != 'rdagent.run':
            continue
        pid = experiment.get('projectId')
        directory = Path(service.store.project(pid)['path']) / '.research' / 'runs' / experiment['id']
        for row in read_json(directory / 'details.json', {}).get('rounds', []):
            links = row.get('experimentIds', [])
            if isinstance(links, str):
                try:
                    links = json.loads(links)
                except ValueError:
                    continue
            for linked_id in links if isinstance(links, list) else []:
                try:
                    child = service.store.experiment(pid, linked_id)
                except (ValueError, OSError):
                    continue
                result[(pid, child['id'])] = child
    return [item for item in result.values() if not project_id or item.get('projectId')==project_id]


def attached_context(service, attached):
    items = []
    for reference in attached:
        try:
            items.extend(_attached_context(service, [reference])['attachedObjects'])
        except (ValueError, FileNotFoundError) as exc:
            items.append({'reference': reference, 'unavailable': str(exc)})
    return {'attachedObjects': items, 'instruction': '仅这些明确关联对象是会话上下文，当前界面标签不改变关联；不可用对象不补造数据。'}


def _attached_context(service, attached):
    from .workbench import get_strategy
    result = []
    for ref in attached:
        item = {'reference':ref}
        if ref.get('reportId'):
            from . import reports
            item['report'] = reports.get(service.store, ref['reportId'])
            if ref.get('page'):
                item['reportPages'] = reports.pages(service.store, {'reportId': ref['reportId'], 'pages': [ref['page']]})
        if ref.get('reproductionId'):
            item['reproduction'] = service.report_tasks.dispatch('reproductions.get', {'projectId': ref['projectId'], 'planId': ref['reproductionId']})
        if ref.get('candidateId'):
            from .candidates import get
            item['candidate'] = get(service.store, ref.get('projectId'), ref['candidateId'])
        if ref.get('strategyId'):
            strategy = get_strategy(service.store,ref['projectId'],ref['strategyId'])
            item['strategy'] = {key:strategy[key] for key in ('id','name','universe','settings','enabled','allocation','active') if key in strategy}
        if ref.get('kind') == 'quote' and ref.get('instrument'):
            from .quotes import instrument
            target = instrument(ref['instrument'])
            window = ref.get('dateRange') or {}
            query = {'projectId':ref.get('projectId'),'instrument':target,
                     'startDate':window.get('start'),'endDate':ref.get('date') or window.get('end'),'limit':60}
            item['quote'] = service.request('market.quote',query)
            if target['kind'] in {'industry','concept'}:
                item['members'] = service.request('market.members',{'projectId':ref.get('projectId'),
                    'instrument':target,'refresh':False,'limit':60})
        elif ref.get('symbol'):
            window = ref.get('dateRange') or {}
            cutoff = ref.get('date') or window.get('end')
            item['stock'] = service.request('market.stock',{'projectId':ref.get('projectId'),'symbol':ref['symbol'],'date':cutoff})
            item['bars'] = service.request('data.bars',{'projectId':ref.get('projectId'),'symbol':ref['symbol'],'experimentId':ref.get('experimentId'),
                                                      'startDate':window.get('start'),'endDate':cutoff,'limit':60})
        if ref.get('experimentId'):
            detail = service.experiment_details(ref.get('projectId'),ref['experimentId'])
            item['experiment'] = _experiment_summary(detail['experiment'],True)
            item['details'] = detail['details']
            item['tables'] = detail['tables']
            if any(ref.get(key) for key in ('symbol', 'date', 'dateRange', 'factorId', 'tradeId', 'modelWindowId')):
                item['focusedTables'] = []
                for table in detail['tables']:
                    columns = set(table['columns'])
                    focus = {}
                    if ref.get('symbol') and columns.intersection({'symbol', 'instrument', 'asset'}):
                        focus['symbol'] = ref['symbol']
                    if columns.intersection({'date', 'datetime'}):
                        window = ref.get('dateRange') or {}
                        focus.update(startDate=ref.get('date') or window.get('start'), endDate=ref.get('date') or window.get('end'))
                    if ref.get('factorId') and 'factor' in columns:
                        focus['factorId'] = ref['factorId']
                    if ref.get('tradeId') and table['name'] == 'trades':
                        focus['tradeId'] = ref['tradeId']
                    if ref.get('modelWindowId') and columns.intersection({'window', 'windowId', 'modelWindowId'}):
                        focus['modelWindowId'] = ref['modelWindowId']
                    if not any(value is not None for value in focus.values()):
                        continue
                    item['focusedTables'].append(service.request('experiments.table', {
                        'projectId': ref.get('projectId'), 'experimentId': ref['experimentId'],
                        'table': table['name'], 'limit': 60, **focus}))
        if ref['kind'] == 'data':
            item['data'] = service.request('data.preview',{'projectId':ref.get('projectId')})
        if ref['kind'] == 'positions':
            item['positions'] = service.request('positions.get',{})
        result.append(item)
    return {'attachedObjects':result,'instruction':'仅这些明确关联对象是会话上下文，当前界面标签不改变关联。'}
