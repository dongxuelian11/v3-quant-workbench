"""Optional PydanticAI provider; structured suggestions require a user stage action."""
import json
from .jobs import validate_spec


def chat(service, params):
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    config = service.store.settings().get('ai', {})
    if not config.get('model') or not config.get('baseUrl'):
        raise ValueError('请先配置在线或本地兼容服务的地址与模型')
    mode = params.get('mode', 'assist')
    if mode not in {'ask', 'assist', 'research'}:
        raise ValueError('未知 AI 模式')
    project = service.store.project(params['projectId'])
    from .data import preview
    context = {'project': project, 'data': preview(project), 'experiments': service.store.experiments(project['id'])[:20]}
    # The model never receives saved provider credentials or arbitrary app settings.
    context['project'] = {key: value for key, value in project.items() if key not in {'settings', 'path'}}

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

    instructions = '''你是中文 A 股研究助手。只依据提供的真实项目和实验解释，不把建议称为运行结果。
ask 模式只解释，proposals 必须为空。assist 提出可运行参数配置。research 提出当前一个阶段的任务批次；用户点击运行后才会执行，等待带实际结果的下一条消息再规划下一阶段。
任务 kind 与参数：data.update {source:baostock|akshare,financials:boolean,startDate,endDate}；factor.analyze {factorIds,periods:[1,5,10],quantiles:5}；backtest.run {template:single_factor|multi_factor|model_score,factorIds,topN,rebalance:daily|weekly|monthly,capital,commissionBuy,commissionSell,minFee,slippage,modelExperimentId?}；model.train {model:ridge|lightgbm,factorIds,trainStart,trainEnd,validStart,validEnd,testStart,testEnd,labelHorizon,hyperparameters:{}}；optimize.run {target:model|backtest,sampler:grid|tpe,trials,baseParameters:{},searchSpace:{}}。
禁止捏造文件路径、实验ID、股票数据或执行结果。没有数据就建议采集；模型评分必须引用已有 model.train 实验。股票池未设置时先说明并请用户设置。常用有效因子 momentum20/volatility20/volume_ratio/roe/growth_profit 或 Alpha158 ROC5/ROC20/MA20。不给交易获利保证。每个 proposal 的 spec.projectId 必须等于当前项目ID。'''
    provider = OpenAIProvider(base_url=config['baseUrl'], api_key=config.get('apiKey') or 'local-no-key')
    model = OpenAIChatModel(config['model'], provider=provider)
    agent = Agent(model, output_type=Answer, instructions=instructions)
    history = params.get('history', [])[-20:]
    prompt = json.dumps({'mode': mode, 'context': context, 'history': history, 'message': params['message']}, ensure_ascii=False, default=str)
    response = agent.run_sync(prompt, model_settings={'temperature': float(config.get('temperature', .2)), 'timeout': 120})
    answer = response.output.model_dump()
    if mode == 'ask':
        answer['proposals'] = []
    if len(answer['proposals']) > 10:
        raise ValueError('AI 返回过多任务，请缩小本阶段范围')
    for proposal in answer['proposals']:
        spec = validate_spec(proposal['spec'])
        if spec['projectId'] != project['id'] or spec['kind'] == 'data.import':
            raise ValueError('AI 建议引用了不允许的项目或文件导入')
        if spec['parameters'].get('code'):
            raise ValueError('AI 阶段建议不能包含任意 Python 代码')
    known = {experiment['id'] for experiment in context['experiments']}
    if any(key not in known for key in answer['experimentIds']):
        raise ValueError('AI 返回了不存在的实验引用')
    return answer
