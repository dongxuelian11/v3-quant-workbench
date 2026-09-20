"""One real read-only explanation of an existing completed import; no execution tools."""
import asyncio,json,os,time
from pathlib import Path
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from v3_backend.research.server import Service
from v3_backend.research.storage import read_json,write_json


def main():
    root=Path('artifacts/round6-backend/agent-live-final').resolve()
    previous=read_json(root/'result.json')
    config=read_json(Path(os.environ['APPDATA'])/'v3-oss-rebuild/research/settings.json')
    service=Service(root/'profile');service.store.settings=lambda:config
    cid=previous['conversationId'];eid=previous['executionId']
    job=service.store.get('job',previous['steps'][0]['jobId'])
    original=service.store.get('conversation',cid)
    message=next(m['content'] for m in original['state']['messages'] if m['role']=='user')
    before=[j['id'] for j in service.store.list('job')];started=time.monotonic()
    async def explain():
        ai=config['ai']
        async with AsyncOpenAI(base_url=ai['baseUrl'],api_key=ai.get('apiKey') or 'local-no-key',max_retries=0) as client:
            model=OpenAIChatModel(ai['model'],provider=OpenAIProvider(openai_client=client))
            return await service.executions.explain_completed(model,cid,eid,message,job)
    try:
        text,available=asyncio.run(explain())
        def finish(state,value):
            state['messages']=[m for m in state['messages'] if m.get('id')!=eid]
            state['messages'].append({'id':eid,'role':'assistant','content':text,'experimentIds':[job['experimentId']],
                'experimentRefs':[{'kind':'experiment','projectId':job['projectId'],'experimentId':job['experimentId']}],'explanationAvailable':available})
            value.update(status='completed',message=text)
        service.executions.mutate(cid,eid,finish)
        after=[j['id'] for j in service.store.list('job')]
        assert before==after
        result={'executionId':eid,'experimentId':job['experimentId'],'status':'completed','explanationAvailable':available,
                'seconds':round(time.monotonic()-started,3),'jobsBefore':len(before),'jobsAfter':len(after),'message':text}
        write_json(root/'explanation-result.json',result);print(json.dumps(result,ensure_ascii=False))
    finally:service.close()


if __name__=='__main__':main()
