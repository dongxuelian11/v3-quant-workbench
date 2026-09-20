"""One isolated real configured-model import scenario; credentials stay in memory."""
import json,os,time
from pathlib import Path
import pandas as pd
from v3_backend.research.server import Service
from v3_backend.research.storage import read_json,write_json


def main():
    root=Path('artifacts/round6-backend/agent-live-final').resolve();root.mkdir(parents=True,exist_ok=True)
    config=read_json(Path(os.environ['APPDATA'])/'v3-oss-rebuild/research/settings.json')
    service=Service(root/'profile')
    service.store.settings=lambda:config
    project=service.store.create_project(str(root/'project'),'普通Agent一次真实服务验证','明确测试输入，不作为投资研究')
    file=root/'prices.csv'
    pd.DataFrame([{'date':'2025-01-02','symbol':'SH600000','open':10,'high':11,'low':9,'close':10,'volume':100}]).to_csv(file,index=False)
    chat=service.request('ai.conversations.create',{'projectId':project['id']})
    spec={'projectId':project['id'],'kind':'data.import','parameters':{'files':[str(file)],'dataset':'prices'}}
    message='请现在执行一次数据导入，这是明确授权。只调用一次run_research，参数spec为：'+json.dumps(spec,ensure_ascii=False)+'。工具成功返回真实experiment后立即结束，并在最终回复说明导入是否成功、实际实验ID。不要再次导入，不继续因子计算，不提出额外任务。此文件为工程验证样本。'
    started=time.monotonic()
    try:
        execution=service.request('ai.chat.start',{'conversationId':chat['id'],'requestId':'one-real-import','message':message,'mode':'assist','context':[]})
        deadline=started+180
        while time.monotonic()<deadline:
            state=service.request('ai.chat.status',{'conversationId':chat['id'],'executionId':execution['id']})
            if state['status']!='running':break
            time.sleep(.25)
        else:
            service.request('ai.chat.cancel',{'conversationId':chat['id'],'executionId':execution['id']})
            for _ in range(40):
                state=service.request('ai.chat.status',{'conversationId':chat['id'],'executionId':execution['id']})
                if state['status']!='running':break
                time.sleep(.25)
        messages=service.request('ai.conversations.get',{'conversationId':chat['id']})['state']['messages']
        assistant=[m for m in messages if m.get('role')=='assistant']
        result={'status':state['status'],'seconds':round(time.monotonic()-started,3),'executionId':execution['id'],
                'conversationId':chat['id'],'projectId':project['id'],'steps':state['steps'],'message':state.get('message'),
                'finalAnswer':assistant[-1] if assistant else None,'jobs':len(service.store.list('job'))}
        write_json(root/'result.json',result)
        print(json.dumps(result,ensure_ascii=False))
    finally:service.close()


if __name__=='__main__':main()
