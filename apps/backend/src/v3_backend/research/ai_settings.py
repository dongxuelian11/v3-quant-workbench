"""Explicit purpose selection, with no automatic provider fallback."""
from copy import deepcopy

PURPOSES={'conversation','research','reports'}


def resolve(store,purpose='conversation'):
    if purpose not in PURPOSES:raise ValueError('未知AI用途')
    settings=store.settings();base=deepcopy(settings['ai'])
    selected=settings.get('aiPurposes',{}).get(purpose)
    if selected:
        # A different endpoint must not inherit another provider's credential.
        if selected.get('baseUrl') and selected['baseUrl']!=base.get('baseUrl'):base['apiKey']=''
        base.update(selected)
    return base


def instructions(store,project_id):
    parts=[store.settings().get('aiInstructions','')]
    if project_id:parts.append(store.project(project_id).get('settings',{}).get('aiInstructions',''))
    return '\n用户研究偏好：\n'+'\n'.join(x for x in parts if isinstance(x,str) and x.strip()) if any(parts) else ''


def connection_test(service,params):
    import time
    from .storage import identifier
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.usage import UsageLimits
    config=resolve(service.store,params.get('purpose','conversation'))
    mode=params.get('kind','reply')
    if mode not in {'reply','tools'}:raise ValueError('请选择实际回复或只读工具测试')
    start=time.monotonic();called=[];nonce=identifier()
    # Same supported provider integration as research; this sends a real request.
    import asyncio
    async def run():
        from openai import AsyncOpenAI
        client=AsyncOpenAI(base_url=config['baseUrl'],api_key=config.get('apiKey') or 'local-no-key',max_retries=0)
        try:
            model=OpenAIChatModel(config['model'],provider=OpenAIProvider(openai_client=client))
            agent=Agent(model,instructions='这是用户主动发起的连接测试，只读，不执行研究。')
            if mode=='tools':
                @agent.tool_plain
                def read_local_overview()->dict:
                    """读取本机研究项目数量和本次测试标记，只读。"""
                    called.append(True)
                    return dict(projectCount=len(service.store.list('project')),marker=nonce)
            prompt='请回复“连接正常”。' if mode=='reply' else '调用read_local_overview，返回它实际给出的marker与项目数量。'
            response=await agent.run(prompt,usage_limits=UsageLimits(request_limit=3,tool_calls_limit=1),model_settings={'timeout':30})
            output=str(response.output)
            passed=bool(output.strip()) and (mode=='reply' or bool(called) and nonce in output)
            return dict(success=passed,kind=mode,purpose=params.get('purpose','conversation'),model=config['model'],
                        toolCalled=bool(called),message=output if passed else '模型未完成实际只读工具调用和返回校验',elapsedSeconds=round(time.monotonic()-start,3))
        finally:await client.close()
    return asyncio.run(run())
