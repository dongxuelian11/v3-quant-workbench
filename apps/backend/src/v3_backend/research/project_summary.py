"""One editable project summary; successful chat responses may append evidence."""
from copy import deepcopy
from pathlib import Path
from threading import RLock
from .storage import now,read_json,write_json

_lock=RLock()
FIELDS=('goals','userDecisions','experimentFindings','hypotheses','unresolved')


def _path(store,project_id):
    return Path(store.project(project_id)['path'])/'ai/project-summary.json'


def _empty(project_id):
    return dict(projectId=project_id,revision=0,updatedAt=None,cleared=False,notes='',sourceConversationIds=[],**{key:[] for key in FIELDS})


def get(store,project_id):
    with _lock:
        path=_path(store,project_id);value=read_json(path)
        if value is not None:return value
        project=store.project(project_id);value=_empty(project_id)
        if project.get('objective'):value['goals']=[project['objective']]
        value['historyInitialized']=False
        value.update(revision=1,updatedAt=now());write_json(path,value)
        return value


def _validate(store,project_id,update):
    result={}
    for key in FIELDS:
        if key not in update:continue
        rows=update[key]
        if not isinstance(rows,list) or len(rows)>500:raise ValueError('项目摘要条目格式无效: '+key)
        if key=='experimentFindings':
            cleaned=[]
            for row in rows:
                if not isinstance(row,dict) or not isinstance(row.get('conclusion'),str):raise ValueError('实验摘要需要来源与结论')
                experiment=store.experiment(project_id,row.get('experimentId'))
                cleaned.append(dict(experimentId=experiment['id'],date=experiment.get('createdAt',''),conclusion=row['conclusion'][:10000]))
                if row.get('conversationId'):
                    conversation=store.get('conversation',row['conversationId'])
                    if conversation.get('projectId')!=project_id:raise ValueError('摘要会话来源不属于此项目')
                    cleaned[-1]['conversationId']=conversation['id']
            result[key]=cleaned
        else:
            if any(not isinstance(row,str) for row in rows):raise ValueError('项目摘要条目必须是文字')
            result[key]=[row[:10000] for row in rows]
    if 'notes' in update:
        if not isinstance(update['notes'],str):raise ValueError('项目摘要备注必须是文字')
        result['notes']=update['notes'][:50000]
    if 'sourceConversationIds' in update:
        if not isinstance(update['sourceConversationIds'],list):raise ValueError('摘要会话来源必须是数组')
        sources=[]
        for key in update['sourceConversationIds']:
            if store.get('conversation',key).get('projectId')!=project_id:raise ValueError('摘要会话来源不属于此项目')
            if key not in sources:sources.append(key)
        result['sourceConversationIds']=sources
    return result


def save(store,project_id,update,expected_revision=None):
    with _lock:
        old=get(store,project_id)
        if expected_revision is not None and old['revision']!=expected_revision:raise ValueError('摘要已更新，请刷新后再保存')
        value={**old,**_validate(store,project_id,update),'revision':old['revision']+1,'updatedAt':now(),'cleared':False}
        write_json(_path(store,project_id),value);return value


def clear(store,project_id,expected_revision=None):
    with _lock:
        old=get(store,project_id);value=_empty(project_id)
        if expected_revision is not None and old['revision']!=expected_revision:raise ValueError('摘要已更新，请刷新后再清除')
        value.update(revision=old['revision']+1,updatedAt=now(),cleared=True,historyInitialized=True)
        value['clearedAt']=value['updatedAt']
        from .workbench import _legacy_conversations
        _legacy_conversations(store)
        value['historyOffsets']={c['id']:len(c.get('state',{}).get('messages',[])) for c in store.list('conversation')}
        write_json(_path(store,project_id),value);return value


def append_response(store,project_id,update,revision,user_message,conversation_id=None):
    if update is None:update={}
    if not isinstance(update,dict):return get(store,project_id)
    with _lock:
        current=get(store,project_id)
        # Manual edits/clear while the model was running always win.
        if current['revision']!=revision:return current
        update=deepcopy(update)
        update['userDecisions']=[text for text in update.get('userDecisions',[]) if isinstance(text,str) and text.strip() and text in user_message]
        accepted=_validate(store,project_id,update)
        value=deepcopy(current)
        sources=conversation_id if isinstance(conversation_id,list) else [conversation_id] if conversation_id else []
        for source in sources:
            conversation=store.get('conversation',source)
            if conversation.get('projectId')!=project_id:raise ValueError('摘要来源会话不属于当前项目')
            if source not in value.setdefault('sourceConversationIds',[]):value['sourceConversationIds'].append(source)
        for key in FIELDS:
            for row in accepted.get(key,[]):
                if row not in value[key]:value[key].append(row)
        content_changed=any(value[key]!=current[key] for key in FIELDS)
        if not content_changed and value['sourceConversationIds']==current.get('sourceConversationIds',[]) and current.get('historyInitialized',False):return current
        value.update(revision=current['revision']+1,updatedAt=now(),historyInitialized=True)
        if content_changed:value['cleared']=False
        write_json(_path(store,project_id),value);return value


def histories(store,project_id,current):
    from .workbench import _conversation_project,_legacy_conversations
    _legacy_conversations(store)
    conversations=[_conversation_project(store,c) for c in store.list('conversation')]
    return [{'conversationId':c['id'],'messages':c.get('state',{}).get('messages',[])[current.get('historyOffsets',{}).get(c['id'],0):]}
            for c in conversations if c.get('projectId')==project_id]


def refresh(service,project_id):
    from pydantic import BaseModel
    from pydantic_ai import Agent,ToolOutput
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    import json
    store=service.store;current=get(store,project_id)
    discussion=[h for h in histories(store,project_id,current) if h['messages']]
    config=store.settings().get('ai',{})
    if not config.get('baseUrl') or not config.get('model'):raise ValueError('请先配置摘要使用的模型服务')
    class SummaryAnswer(BaseModel):
        goals:list[str]=[]
        userDecisions:list[str]=[]
        experimentFindings:list[dict]=[]
        hypotheses:list[str]=[]
        unresolved:list[str]=[]
    model=OpenAIChatModel(config['model'],provider=OpenAIProvider(base_url=config['baseUrl'],api_key=config.get('apiKey') or 'local-no-key'))
    agent=Agent(model,output_type=ToolOutput(SummaryAnswer,strict=False),instructions='整理提供的本项目历史讨论。只追加有来源的条目，不替换手工摘要。userDecisions必须逐字引用用户明确决定；推测和建议归hypotheses。experimentFindings必须引用提供的experimentId，标清结论。没有讨论证据不要把项目配置称为讨论结论。')
    experiments=[item for item in store.experiments(project_id) if not current.get('clearedAt') or item.get('createdAt','')>=current['clearedAt']]
    try:
        response=agent.run_sync(json.dumps({'summary':current,'conversations':discussion,'experiments':experiments[:30]},ensure_ascii=False,default=str),model_settings={'temperature':float(config.get('temperature',.2)),'timeout':120})
    except Exception as exc:
        status=getattr(exc,'status_code',None)
        message='摘要模型服务限流或额度不足，请稍后手动整理' if status==429 else '摘要模型服务请求失败，原摘要已保留，请检查服务设置或稍后重试'
        raise ValueError(message) from None
    user_text='\n'.join(str(m.get('content','')) for h in discussion for m in h['messages'] if m.get('role')=='user')
    updated=append_response(store,project_id,response.output.model_dump(),current['revision'],user_text,[h['conversationId'] for h in discussion])
    return updated


def dispatch(service,method,params):
    store=service.store
    project_id=params['projectId']
    if method.endswith('.get'):return get(store,project_id)
    if method.endswith('.save'):return save(store,project_id,params['summary'],params.get('expectedRevision'))
    if method.endswith('.clear'):return clear(store,project_id,params.get('expectedRevision'))
    if method.endswith('.refresh'):
        return refresh(service,project_id)
    raise ValueError('未知项目摘要操作')
