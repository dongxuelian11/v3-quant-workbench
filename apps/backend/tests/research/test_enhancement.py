import asyncio,tempfile,time,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd
from v3_backend.research.server import Service
from v3_backend.research import ai,intraday,quotes


class EnhancementTests(unittest.TestCase):
    def test_pending_supplement_failure_continue_and_cancel_choice(self):
        import json
        owner=self
        def response():return SimpleNamespace(output=SimpleNamespace(model_dump=lambda:{'message':'已处理','phase':'done','proposals':[]}),all_messages=lambda:[])
        class Agent:
            def __init__(self,fail=False,cancel=False):self.calls=0;self.payloads=[];self.fail=fail;self.cancel=cancel
            def tool_plain(self,f):return f
            async def run(self,prompt,**kwargs):
                self.calls+=1;payload=json.loads(prompt);self.payloads.append(payload)
                state=owner.service.request('ai.chat.status',{'conversationId':owner.chat['id']})
                if self.fail and self.calls==1:
                    owner.service.request('ai.chat.message',{'conversationId':owner.chat['id'],'executionId':state['id'],'messageId':'retained','message':'解释尚未处理的费用'})
                if payload.get('supplementalMessages'):
                    owner.assertIn('retained',[m['id'] for m in state['pendingMessages']])
                    owner.assertNotIn('retained',state['consumedMessageIds'])
                    if self.cancel:raise asyncio.CancelledError()
                    if self.fail=='temporary':raise TimeoutError('受控临时失败')
                    if self.fail:raise ValueError('受控处理失败')
                return response()
        def start(agent,request,message='解释',**extra):
            with patch.object(ai,'_create_agent',return_value=agent):
                value=owner.service.request('ai.chat.start',{'conversationId':owner.chat['id'],'requestId':request,'message':message,'mode':'ask',**extra})
                return owner.wait(value['id'])
        from unittest.mock import AsyncMock
        temporary=Agent(fail='temporary')
        with patch('asyncio.sleep',new=AsyncMock()):paused=start(temporary,'temporary-supplement')
        self.assertEqual(paused['status'],'paused');self.assertEqual(temporary.calls,4)
        self.assertEqual([m['id'] for m in paused['pendingMessages']],['retained'])
        self.assertNotIn('retained',paused['consumedMessageIds'])
        failed=start(Agent(fail=True),'failed-supplement')
        self.assertEqual(failed['status'],'failed');self.assertIn('未完成补充',failed['message'])
        self.assertEqual([m['id'] for m in failed['pendingMessages']],['retained'])
        spec={'projectId':self.project['id'],'kind':'data.import','parameters':{}}
        token=json.dumps(spec,sort_keys=True,ensure_ascii=False)
        self.service.store.put('job',{'id':'completed-before-failure','status':'completed','projectId':self.project['id'],'experimentId':'prior-result'})
        self.service.executions.mutate(self.chat['id'],failed['id'],lambda state,value:value['submitted'].update({token:'completed-before-failure'}))
        cancelled=start(Agent(cancel=True),'cancel-supplement','继续处理补充')
        self.assertEqual(cancelled['status'],'cancelled');self.assertTrue(cancelled['pendingMessages'][0]['requiresConfirmation'])
        unrelated=Agent();held=start(unrelated,'unrelated','说明今天的状态')
        self.assertEqual(held['status'],'paused');self.assertEqual(unrelated.calls,1)
        self.assertFalse(any(m.get('id')=='retained' for m in unrelated.payloads[0]['history']))
        success=Agent();done=start(success,'resume-supplement','继续处理未完成补充')
        self.assertEqual(done['status'],'completed',done);self.assertEqual(done['pendingMessages'],[])
        self.assertIn('retained',done['consumedMessageIds']);self.assertEqual(success.calls,2)
        old=owner.service.request('ai.chat.status',{'conversationId':owner.chat['id'],'executionId':failed['id']})
        self.assertEqual(old['pendingMessages'][0]['message'],'解释尚未处理的费用')
        from v3_backend.research.ai_execution import CompletedStepRepeated
        with patch.object(self.service.jobs,'submit') as submit,self.assertRaises(CompletedStepRepeated):
            asyncio.run(self.service.executions.run_research(self.chat['id'],done['id'],spec))
        submit.assert_not_called();self.assertEqual(len(self.service.store.list('job')),1)

    def test_agent_formula_tools_scope_new_draft_and_native_preview(self):
        from v3_backend.research import data
        class Capture:
            def __init__(self,*args,**kwargs):self.functions={}
            def tool_plain(self,function):self.functions[function.__name__]=function;return function
        def create(mode='assist',execution=True,pid=None):
            with patch('pydantic_ai.Agent',Capture):
                return ai._create_agent(self.service,pid,None,conversation_id=self.chat['id'],mode=mode,execution=execution).functions
        pid=self.project['id'];tools=create(pid=pid)
        for readonly in (create('ask',pid=pid),create(execution=False,pid=pid)):
            self.assertIn('evaluate_formula',readonly);self.assertNotIn('save_formula_draft',readonly)
        self.assertIn('error',create()['read_formula_library']())
        save=tools['save_formula_draft']
        saved=save('三日均线','M:MA(C,3);')
        self.assertEqual(saved['projectId'],pid);self.assertEqual(saved['scope'],'project')
        self.assertEqual(save('三日均线','M:MA(C,3);')['formulaId'],saved['formulaId'])
        self.assertNotEqual(save('三日均线','M:MA(C,5);')['formulaId'],saved['formulaId'])
        self.assertEqual(tools['read_formula_library'](formula_id=saved['formulaId'])['records']['script'],'M:MA(C,3);')
        personal=save('个人均线','M:MA(C,3);',scope='personal')
        self.assertIsNone(personal['projectId'])
        self.assertEqual(len(tools['read_formula_library']('personal')['records']),1)
        self.assertEqual(len(tools['read_formula_library']()['records']),2)
        self.assertIn('error',tools['read_formula_library']('other-project'))
        before=self.service.store.project(pid)['settings']
        frame=pd.DataFrame([{'date':pd.Timestamp('2025-01-02')+pd.Timedelta(days=i),'symbol':'SH600000',
            'open':10+i,'high':12+i,'low':9+i,'close':11+i,'volume':100} for i in range(4)])
        for field in ('open','high','low','close'):frame['raw'+field.title()]=frame[field]
        with patch.object(data,'read_table',return_value=frame):
            result=tools['evaluate_formula']({'script':'M:MA(C,3);','saveFactor':True},purpose='research',start_date='2025-01-02',end_date='2025-01-05')
            self.assertEqual(result['series'][0]['outputs'][0]['values'][-2:],[12,13])
            self.assertNotIn('factor',result)
            failed=tools['evaluate_formula']({'script':'F:REF(C,-1);'},purpose='research',start_date='2025-01-02',end_date='2025-01-05')
            self.assertIn('error',failed)
        self.assertEqual(self.service.store.project(pid)['settings'],before)
        self.assertFalse((Path(self.project['path'])/'.research/formulas').exists())
        self.assertEqual(self.service.store.list('job'),[])

    def test_closed_day_old_daily_and_minute_cache_refresh_once(self):
        from v3_backend.research.storage import write_json
        project=self.service.store.project(None);today=pd.Timestamp.now(tz='Asia/Shanghai').strftime('%Y-%m-%d')
        write_json(Path(project['path'])/'data/trading-calendar.json',{'start':today,'end':today,'dates':[]})
        item={'kind':'stock','symbol':'SH600000'}
        old=quotes._normalize(pd.DataFrame([{'date':'2026-09-07','open':10,'high':11,'low':9,'close':10,'volume':100}]),item,'baostock')
        fresh=old.copy();fresh['date']=pd.Timestamp('2026-09-11')
        path=quotes._path(project,item);path.parent.mkdir(parents=True,exist_ok=True);old.to_parquet(path,index=False)
        write_json(path.with_suffix('.json'),{'updatedAt':'2026-09-07T16:00:00+08:00'})
        query={'instrument':item,'startDate':'2026-09-07','endDate':today,'refresh':True,'autoRefresh':True}
        with patch.object(quotes,'_fetch',return_value=(pd.concat([old,fresh],ignore_index=True),'baostock',None)) as fetch:
            result=quotes.status(project,query);self.assertEqual(result['coverage']['endDate'],'2026-09-11')
            count=fetch.call_count;self.assertGreater(count,0)
            quotes.status(project,query);self.assertEqual(fetch.call_count,count)
        minute=intraday.normalize(pd.DataFrame([{'day':'2026-09-07 15:00:00','open':10,'high':11,'low':9,'close':10,'volume':100}]),item,'5m')
        minute_path=Path(project['path'])/'minutes/stock/SH600000/5m.parquet'
        minute_path.parent.mkdir(parents=True,exist_ok=True);minute.to_parquet(minute_path,index=False)
        write_json(minute_path.with_suffix('.json'),{'updatedAt':'2026-09-07T16:00:00+08:00'})
        fresh_minute=intraday.normalize(pd.DataFrame([{'day':'2026-09-11 15:00:00','open':10,'high':11,'low':9,'close':10,'volume':100}]),item,'5m')
        with patch.object(intraday,'fetch',return_value=fresh_minute) as fetch:
            result=intraday.read(project,{**query,'period':'5m'})
            self.assertTrue(result['coverage']['endDate'].startswith('2026-09-11'))
            intraday.read(project,{**query,'period':'5m'});self.assertEqual(fetch.call_count,1)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.service=Service(self.root/'profile')
        self.project=self.service.store.create_project(str(self.root/'project'),'测试','')
        self.chat=self.service.request('ai.conversations.create',{'projectId':self.project['id']})
        self.service.store.settings=lambda:{'ai':{'baseUrl':'http://127.0.0.1:1/v1','model':'fixture'}}

    def tearDown(self):self.service.close();self.temp.cleanup()

    def wait(self,eid):
        end=time.monotonic()+12
        while time.monotonic()<end:
            state=self.service.request('ai.chat.status',{'conversationId':self.chat['id'],'executionId':eid})
            if state['status']!='running':return state
            time.sleep(.03)
        self.fail('execution did not finish')

    def test_minute_units_timezone_missing_prices_and_daily_isolation(self):
        item={'kind':'stock','symbol':'SZ000001'}
        source=pd.DataFrame([{'时间':'2026-09-11 09:31:00','开盘':0,'最高':10,'最低':9,'收盘':10,'成交量':3,'成交额':3000}])
        frame=intraday.normalize(source,item,'1m',clock='2026-09-11T09:31:30+08:00')
        self.assertEqual(frame.volume.iloc[0],300);self.assertFalse(frame.complete.iloc[0])
        self.assertTrue(pd.isna(frame.open.iloc[0]));self.assertEqual(frame.timestamp.iloc[0],pd.Timestamp('2026-09-11T09:31:00+08:00').value//1_000_000)
        with patch.object(intraday,'fetch',return_value=frame):
            value=self.service.request('market.intraday',{'instrument':item,'period':'1m','refresh':True})
        self.assertEqual(value['bars'][0]['open'],None)
        self.assertTrue(quotes.read(self.service.store.project(None),item).empty)
        with patch.object(intraday,'fetch',side_effect=ValueError('源失败')):
            failed=self.service.request('market.intraday',{'instrument':item,'period':'1m','refresh':True})
        self.assertEqual(failed['bars'],value['bars']);self.assertEqual(failed['status'],'source_error')

    def test_async_cancel_interrupts_model_and_keeps_supplement(self):
        started=threading.Event();cancelled=threading.Event()
        class Agent:
            async def run(self,*args,**kwargs):
                started.set()
                try:await asyncio.sleep(120)
                finally:cancelled.set()
            def tool_plain(self,f):return f
        with patch.object(ai,'_create_agent',return_value=Agent()):
            params={'conversationId':self.chat['id'],'requestId':'first','message':'解释','mode':'ask','context':[]}
            value=self.service.request('ai.chat.start',params)
            self.assertTrue(started.wait(3))
            self.assertEqual(self.service.request('ai.chat.start',params)['id'],value['id'])
            self.service.request('ai.chat.message',{'conversationId':self.chat['id'],'executionId':value['id'],'messageId':'extra','message':'补充文字'})
            self.service.request('ai.chat.message',{'conversationId':self.chat['id'],'executionId':value['id'],'messageId':'not-stop','message':'不要停止'})
            self.assertFalse(cancelled.is_set())
            self.service.request('ai.chat.message',{'conversationId':self.chat['id'],'executionId':value['id'],'messageId':'stop','message':'停止当前任务'})
            self.assertEqual(self.wait(value['id'])['status'],'cancelled');self.assertTrue(cancelled.is_set())
            self.assertNotIn(value['id'],self.service.executions.futures)
            self.assertNotIn(value['id'],self.service.executions.started)
        messages=self.service.request('ai.conversations.get',{'conversationId':self.chat['id']})['state']['messages']
        self.assertIn('extra',[m.get('id') for m in messages])
        self.assertIn('stop',[m.get('id') for m in messages])

    def test_async_tool_uses_real_job_and_returns_experiment(self):
        path=self.root/'prices.csv'
        pd.DataFrame([{'date':'2025-01-02','symbol':'SH600000','open':10,'high':11,'low':9,'close':10,'volume':100}]).to_csv(path,index=False)
        spec={'projectId':self.project['id'],'kind':'data.import','parameters':{'files':[str(path)],'dataset':'prices'}}
        class Agent:
            def tool_plain(self,f):
                if f.__name__ == 'run_research': self.tool=f
                return f
            async def run(self,*args,**kwargs):
                result=await self.tool(spec)
                return SimpleNamespace(output=SimpleNamespace(model_dump=lambda:{'message':'导入完成','phase':'done','proposals':[],'experimentIds':[result['experiment']['id']]}),all_messages=lambda:[])
        with patch.object(ai,'_create_agent',return_value=Agent()):
            value=self.service.request('ai.chat.start',{'conversationId':self.chat['id'],'requestId':'import','message':'导入测试文件','mode':'assist','context':[]})
            state=self.wait(value['id'])
        self.assertEqual(state['status'],'completed',state)
        self.assertEqual(state['steps'][0]['status'],'completed')
        self.assertTrue(self.service.store.experiment(self.project['id'],state['steps'][0]['experimentId']))

    def test_repeated_completed_tool_explains_without_second_job(self):
        from unittest.mock import AsyncMock
        path=self.root/'prices.csv'
        pd.DataFrame([{'date':'2025-01-02','symbol':'SH600000','open':10,'high':11,'low':9,'close':10,'volume':100}]).to_csv(path,index=False)
        spec={'projectId':self.project['id'],'kind':'data.import','parameters':{'files':[str(path)],'dataset':'prices'}}
        class Agent:
            def tool_plain(self,f):
                if f.__name__ == 'run_research': self.tool=f
                return f
            async def run(self,*args,**kwargs):
                await self.tool(spec)
                await self.tool({**spec,'name':'重复改名'})
                raise AssertionError('重复调用应当停止')
        summary_agent=SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(output='实际导入已完成。')))
        with patch.object(ai,'_create_agent',return_value=Agent()),patch('pydantic_ai.Agent',return_value=summary_agent) as readonly:
            value=self.service.request('ai.chat.start',{'conversationId':self.chat['id'],'requestId':'repeat','message':'导入','mode':'assist','context':[]})
            state=self.wait(value['id'])
        self.assertNotIn('tools',readonly.call_args.kwargs)
        self.assertEqual(state['status'],'completed',state)
        self.assertEqual(len(state['steps']),1)
        self.assertEqual(len(self.service.store.list('job')),1)
        messages=self.service.request('ai.conversations.get',{'conversationId':self.chat['id']})['state']['messages']
        self.assertEqual(messages[-1]['experimentIds'],[state['steps'][0]['experimentId']])
        self.assertEqual(messages[-1]['content'],'实际导入已完成。')
        summary_agent.run=AsyncMock(side_effect=ValueError('说明服务不可用'))
        with patch('pydantic_ai.Agent',return_value=summary_agent):
            text,available=asyncio.run(self.service.executions.explain_completed(None,self.chat['id'],value['id'],'导入',self.service.store.list('job')[0]))
        self.assertFalse(available);self.assertIn('任务已完成，AI说明暂不可用',text)
        self.assertEqual(len(self.service.store.list('job')),1)

    def test_native_formula_library_copy_and_saved_factor_math(self):
        from v3_backend.research import data,engines
        call=self.service.request;pid=self.project['id']
        formula=call('formula.library.save',{'record':{'name':'三日均线','script':'M:MA(C,3);V:VOL;'}})
        copied=call('formula.library.copy',{'projectId':pid,'id':formula['id']})
        self.assertIsNone(copied['sourceProjectId']);self.assertEqual(copied['sourceRevision'],1)
        call('formula.library.save',{'record':{**formula,'script':'M:MA(C,5);'}})
        self.assertEqual(call('formula.library.get',{'projectId':pid,'id':copied['id']})['script'],'M:MA(C,3);V:VOL;')
        project=self.service.store.save_project({**self.project,'startDate':'2025-01-03','endDate':'2025-01-06'})
        frame=pd.DataFrame([{'date':f'2025-01-0{i+1}','symbol':'SH600000','open':10+i,'high':12+i,'low':9+i,'close':11+i,'volume':100*(i+1),'amount':1000*(i+1)} for i in range(6)])
        for field in ('open','high','low','close'):frame['raw'+field.title()]=frame[field]
        frame['date']=pd.to_datetime(frame.date)
        with patch.object(data,'read_table',return_value=frame):
            result=call('formula.evaluate',{'projectId':pid,'formulaId':copied['id'],'purpose':'research','saveFactor':True,'factorId':'tdx_ma3','output':'M'})
        actual=engines.generated_factor(project,result['factor']['dataPath'],'tdx_ma3')
        self.assertEqual(actual.tdx_ma3.tolist(),[12,13,14,15])
        self.assertEqual(result['series'][0]['outputs'][1]['values'],[1,2,3,4,5,6])
        custom=result['factor'];original=custom['dataPath']
        actual_frame=frame.copy();actual_frame['rawClose']*=2
        with patch.object(data,'read_table',return_value=actual_frame):
            params={'customFactors':[custom],'factorIds':['tdx_ma3']}
            from v3_backend.research.formulas import refresh_factors
            refresh_factors(project,params)
            saved=params['customFactors'][0]['dataPath']
            self.assertNotEqual(saved,original)
            self.assertEqual(engines.generated_factor(project,saved,'tdx_ma3').tdx_ma3.dropna().tolist(),[24,26,28,30])
            refresh_factors(project,params)
            self.assertEqual(params['customFactors'][0]['dataPath'],saved)
        self.assertEqual(engines.generated_factor(project,original,'tdx_ma3').tdx_ma3.tolist(),[12,13,14,15])
        with patch.object(quotes,'read',return_value=frame):
            external=call('formula.evaluate',{'projectId':pid,'instrument':{'kind':'index','symbol':'SH000300'},'formula':{'script':'X:C;'},'purpose':'chart'})
            self.assertEqual(external['series'][0]['symbol'],'SH000300')
        with self.assertRaises(ValueError):call('formula.templates.save',{'record':{'name':'禁止个股模板','settings':{'symbol':'SH600000'}}})
        with patch.object(data,'read_table',return_value=frame),self.assertRaises(ValueError):
            call('formula.evaluate',{'projectId':pid,'formula':{'script':'F:REF(C,-1);'},'purpose':'research','saveFactor':True,'factorId':'future'})

    def test_rd_repair_requires_explicit_confirmation(self):
        from v3_backend.research import rd_agent
        from v3_backend.research.storage import write_json
        pid=self.project['id'];eid='failed-code'
        self.service.store.save_experiment(pid,{'id':eid,'kind':'rdagent.run','strategyId':'default','artifacts':[]})
        write_json(Path(self.project['path'])/'.research/runs'/eid/'rd_state.json',{'status':'failed','requiresConfirmation':True})
        with self.assertRaisesRegex(ValueError,'明确确认'):
            rd_agent._resume_inputs(self.service.store,{**self.project,'strategyId':'default'},{'resumeExperimentId':eid},self.root/'new',lambda *_:None)

    def test_client_close_failure_still_persists_terminal_state(self):
        from unittest.mock import AsyncMock
        class Agent:
            async def run(self,*args,**kwargs):
                return SimpleNamespace(output=SimpleNamespace(model_dump=lambda:{'message':'解释完成','proposals':[]}),all_messages=lambda:[])
        with patch.object(ai,'_create_agent',return_value=Agent()),patch('openai.AsyncOpenAI.close',new=AsyncMock(side_effect=RuntimeError('close error'))):
            value=self.service.request('ai.chat.start',{'conversationId':self.chat['id'],'requestId':'close-error','message':'解释','mode':'ask'})
            state=self.wait(value['id'])
        self.assertEqual(state['status'],'failed')
        self.assertIn('关闭失败',state['message'])
        self.assertNotIn(value['id'],self.service.executions.futures)

    def test_retry_is_bounded_and_auth_not_retried(self):
        from unittest.mock import AsyncMock
        class Failure(Exception):
            def __init__(self,status):self.status_code=status;self.response=SimpleNamespace(headers={'retry-after':'0'})
        self.service.executions.mutate(self.chat['id'],None,lambda state,value:state.update(execution={
            'id':'retry','requestId':'retry','status':'running','projectId':self.project['id'],'context':[],
            'mode':'ask','projectSnapshots':{},'pendingMessages':[],'consumedMessageIds':[]}))
        async def check():
            agent=SimpleNamespace(run=AsyncMock(side_effect=Failure(401)))
            with self.assertRaises(Failure):await self.service.executions.model_request(agent,'',self.chat['id'],'')
            self.assertEqual(agent.run.call_count,1)
            success=SimpleNamespace(output=SimpleNamespace(model_dump=lambda:{'message':'成功','proposals':[]}))
            agent.run=AsyncMock(side_effect=[Failure(429),Failure(503),success])
            with patch('asyncio.sleep',new=AsyncMock()) as wait:
                self.assertIs(await self.service.executions.model_request(agent,'',self.chat['id'],''),success)
                self.assertEqual(agent.run.call_count,3);self.assertEqual(wait.call_count,2)
        asyncio.run(check())

    def test_chart_annotations_separate_project_and_period(self):
        instrument={'kind':'stock','symbol':'SH600000'}
        params={'projectId':self.project['id'],'instrument':instrument,'period':'5m','priceBasis':'raw'}
        self.service.request('charts.save',{**params,'annotations':[{'id':'line','points':[{'timestamp':1789110000000,'value':9.26}]}]})
        self.assertEqual(len(self.service.request('charts.load',params)['annotations']),1)
        self.assertEqual(self.service.request('charts.load',{**params,'period':'daily'})['annotations'],[])
        self.assertEqual(self.service.request('charts.load',{**params,'projectId':None})['annotations'],[])

    def test_sina_board_minute_is_explicitly_unsupported(self):
        with patch.object(intraday,'fetch') as fetch:
            result=self.service.request('market.intraday',{'instrument':{'kind':'concept','symbol':'SINA_GN_TEST'},'period':'5m','refresh':True})
        self.assertEqual(result['status'],'unsupported');self.assertFalse(fetch.called)
        self.assertEqual(result['coverage']['rows'],0)

    def test_sina_fallback_units_and_closed_day_auto_refresh(self):
        from v3_backend.research.storage import write_json
        project=self.service.store.project(None)
        today=pd.Timestamp.now(tz='Asia/Shanghai').strftime('%Y-%m-%d')
        write_json(Path(project['path'])/'data/trading-calendar.json',{'start':today,'end':today,'dates':[]})
        item={'kind':'stock','symbol':'SH600000'}
        source=pd.DataFrame([{'day':'2026-09-11 15:00:00','open':'9.25','high':'9.26','low':'9.24','close':'9.26','volume':'1528152','amount':'14141764.5515'}])
        def fetch(name,**kwargs):
            if name=='stock_zh_a_minute':return source
            raise ValueError('东财连接失败')
        with patch.object(quotes,'_ak',side_effect=fetch) as remote:
            value=self.service.request('market.intraday',{'instrument':item,'period':'5m','refresh':True,'autoRefresh':True})
            self.assertEqual(remote.call_count,2)
            self.assertEqual(value['bars'][0]['volume'],1528152)
            self.assertEqual(value['coverage']['source'],'akshare/sina')
            self.service.request('market.intraday',{'instrument':item,'period':'5m','refresh':True,'autoRefresh':True})
            self.assertEqual(remote.call_count,2)
            self.service.request('market.intraday',{'instrument':item,'period':'5m','refresh':True})
            self.assertEqual(remote.call_count,3)

    def test_minute_coalesces_and_respects_custom_ttl(self):
        from concurrent.futures import ThreadPoolExecutor
        from v3_backend.research.storage import write_json
        project=self.service.store.project(None);today=pd.Timestamp.now(tz='Asia/Shanghai').strftime('%Y-%m-%d')
        write_json(Path(project['path'])/'data/trading-calendar.json',{'start':today,'end':today,'dates':[today]})
        item={'kind':'stock','symbol':'SH600000'}
        frame=intraday.normalize(pd.DataFrame([{'时间':'2026-09-11 15:00:00','收盘':10,'成交量':3}]),item,'1m')
        started=threading.Event();release=threading.Event()
        def fetch(*args):started.set();release.wait(3);return frame
        query={'instrument':item,'period':'1m','refresh':True,'autoRefresh':True,'refreshIntervalSeconds':15}
        with patch.object(intraday,'fetch',side_effect=fetch) as remote,ThreadPoolExecutor(max_workers=4) as callers:
            futures=[callers.submit(intraday.read,project,query) for _ in range(4)]
            self.assertTrue(started.wait(2));time.sleep(.05);self.assertEqual(remote.call_count,1)
            release.set()
            for future in futures:self.assertEqual(future.result(3)['status'],'ready')
            intraday.read(project,query);self.assertEqual(remote.call_count,1)
            key=(str((Path(project['path'])/'minutes/stock/SH600000/1m.parquet').resolve()),None,None)
            with intraday._lock:intraday._completed[key]['at']-=16
            intraday.read(project,query);self.assertEqual(remote.call_count,2)
            intraday.read(project,{**query,'autoRefresh':False});self.assertEqual(remote.call_count,3)
            with intraday._lock:intraday._completed[key]['at']-=16
            remote.side_effect=ValueError('来源暂不可用')
            failed=intraday.read(project,query)
            repeated=intraday.read(project,query)
            self.assertEqual(remote.call_count,4)
            self.assertEqual(failed['status'],repeated['status']);self.assertEqual(repeated['status'],'source_error')
            self.assertEqual(failed['bars'],repeated['bars'])

    def test_four_minute_periods_fetch_concurrently(self):
        from concurrent.futures import ThreadPoolExecutor
        project=self.service.store.project(None);item={'kind':'stock','symbol':'SH600000'}
        gate=threading.Barrier(4)
        frame=intraday.normalize(pd.DataFrame([{'时间':'2026-09-11 15:00:00','收盘':10,'成交量':3}]),item,'1m')
        def fetch(*args):gate.wait(timeout=3);return frame
        with patch.object(intraday,'fetch',side_effect=fetch),ThreadPoolExecutor(max_workers=4) as callers:
            futures=[callers.submit(intraday.read,project,{'instrument':item,'period':period,'refresh':True}) for period in ('1m','5m','15m','60m')]
            self.assertTrue(all(f.result(5)['status']=='ready' for f in futures))

    def test_minute_pagination_reaches_older_than_5000_without_source(self):
        project=self.service.store.project(None);item={'kind':'stock','symbol':'SH600000'}
        dates=pd.date_range('2025-01-02 09:30',periods=5200,freq='5min')
        frame=intraday.normalize(pd.DataFrame({'时间':dates,'收盘':10,'成交量':3}),item,'5m')
        path=Path(project['path'])/'minutes/stock/SH600000/5m.parquet';path.parent.mkdir(parents=True);frame.to_parquet(path,index=False)
        query={'instrument':item,'period':'5m','refresh':False,'limit':500}
        all_dates=[]
        with patch.object(intraday,'fetch') as source:
            while True:
                page=intraday.read(project,query);all_dates.extend(row['date'] for row in page['bars'])
                if not page['hasMore']:break
                query['beforeDate']=page['bars'][0]['date']
        self.assertEqual(len(all_dates),5200);self.assertEqual(len(set(all_dates)),5200)
        self.assertEqual(min(all_dates),frame.date.min());self.assertFalse(source.called)

    def test_tool_trace_redacts_credentials_and_omits_plain_messages(self):
        from v3_backend.research.storage import read_json
        eid='trace'
        self.service.executions.mutate(self.chat['id'],None,lambda state,value:state.update(execution={'id':eid,'requestId':eid,'projectId':self.project['id'],'status':'completed'}))
        self.service.store.settings=lambda:{'ai':{'apiKey':'TEST_SECRET'}}
        parts=[SimpleNamespace(part_kind='tool-call',tool_name='run_research',args='{"apiKey":"TEST_SECRET","kind":"data.import"}'),
               SimpleNamespace(part_kind='tool-return',tool_name='run_research',content={'summary':'TEST_SECRET should be removed'}),
               SimpleNamespace(part_kind='text',content='plain text is not tool trace')]
        self.service.executions.record_tools(self.chat['id'],eid,[SimpleNamespace(parts=parts)])
        path=Path(self.project['path'])/'.research/executions'/eid/'tools.json'
        rows=read_json(path);self.assertEqual(len(rows),2)
        self.assertNotIn('apiKey',rows[0]['args']);self.assertNotIn('TEST_SECRET',path.read_text(encoding='utf-8'))

    def test_exhausted_temporary_model_errors_pause_without_jobs(self):
        from unittest.mock import AsyncMock
        class Failure(Exception):
            def __init__(self,code):self.status_code=code;self.response=SimpleNamespace(headers={'retry-after':'0'})
        for code in (408,429,500,503,599):
            agent=SimpleNamespace(run=AsyncMock(side_effect=Failure(code)))
            with patch.object(ai,'_create_agent',return_value=agent):
                value=self.service.request('ai.chat.start',{'conversationId':self.chat['id'],'requestId':'temporary-'+str(code),'message':'解释','mode':'ask'})
                state=self.wait(value['id'])
            self.assertEqual(state['status'],'paused');self.assertEqual(agent.run.call_count,3)
        agent=SimpleNamespace(run=AsyncMock(side_effect=ConnectionError('offline')))
        with patch.object(ai,'_create_agent',return_value=agent),patch('asyncio.sleep',new=AsyncMock()):
            value=self.service.request('ai.chat.start',{'conversationId':self.chat['id'],'requestId':'connection','message':'解释','mode':'ask'})
            self.assertEqual(self.wait(value['id'])['status'],'paused')
        self.assertEqual(agent.run.call_count,3);self.assertEqual(self.service.store.list('job'),[])

    def test_readonly_explanation_includes_pending_and_keeps_late_messages(self):
        import json
        from v3_backend.research.ai_execution import CompletedStepRepeated
        from v3_backend.research.storage import now
        owner=self;pid=self.project['id'];job={'id':'existing','projectId':pid,'experimentId':'existing','status':'completed'}
        self.service.store.put('job',job)
        self.service.store.save_experiment(pid,{'id':'existing','projectId':pid,'name':'已有导入','kind':'data.import','createdAt':now(),'parameters':{},'metrics':{},'artifacts':[],'summary':'已导入'})
        class Agent:
            def tool_plain(self,f):return f
            async def run(self,*args,**kwargs):
                eid=owner.service.request('ai.chat.status',{'conversationId':owner.chat['id']})['id']
                owner.service.request('ai.chat.message',{'conversationId':owner.chat['id'],'executionId':eid,'messageId':'before','message':'解释样本限制'})
                raise CompletedStepRepeated(job)
        class Explanation:
            async def run(self,prompt,**kwargs):
                self.payload=json.loads(prompt)
                eid=owner.service.request('ai.chat.status',{'conversationId':owner.chat['id']})['id']
                owner.service.request('ai.chat.message',{'conversationId':owner.chat['id'],'executionId':eid,'messageId':'during','message':'再讨论下一步'})
                return SimpleNamespace(output='已说明样本限制')
        explanation=Explanation()
        with patch.object(ai,'_create_agent',return_value=Agent()),patch('pydantic_ai.Agent',return_value=explanation):
            value=self.service.request('ai.chat.start',{'conversationId':self.chat['id'],'requestId':'late','message':'导入','mode':'assist'})
            state=self.wait(value['id'])
        self.assertEqual(explanation.payload['supplementalMessages'][0]['id'],'before')
        self.assertEqual(state['status'],'paused');self.assertIn('尚未处理',state['message'])
        self.assertEqual([m['id'] for m in state['pendingMessages']],['during'])
        self.assertIn('before',state['consumedMessageIds']);self.assertNotIn('during',state['consumedMessageIds'])
        self.assertEqual(len(self.service.store.list('job')),1)
        class FailedExplanation:
            async def run(self,prompt,**kwargs):
                self.payload=json.loads(prompt)
                raise ValueError('说明暂不可用')
        failed=FailedExplanation()
        with patch.object(ai,'_create_agent',return_value=Agent()),patch('pydantic_ai.Agent',return_value=failed):
            next_value=self.service.request('ai.chat.start',{'conversationId':self.chat['id'],'requestId':'continue-late','message':'继续处理补充','mode':'assist'})
            next_state=self.wait(next_value['id'])
        self.assertEqual(failed.payload['supplementalMessages'][0]['id'],'during')
        self.assertEqual(next_state['status'],'paused')
        self.assertIn('AI说明暂不可用',next_state['message'])
        self.assertEqual([m['id'] for m in next_state['pendingMessages']],['during'])
        self.assertNotIn('during',next_state['consumedMessageIds'])
        self.assertEqual(len(self.service.store.list('job')),1)

    def test_global_tool_trace_uses_shared_project(self):
        chat=self.service.request('ai.conversations.create',{'projectId':None})
        self.service.executions.mutate(chat['id'],None,lambda state,value:state.update(execution={'id':'global-trace','requestId':'global-trace','projectId':None,'status':'completed'}))
        part=SimpleNamespace(part_kind='tool-call',tool_name='get_project_context',args={})
        self.service.executions.record_tools(chat['id'],'global-trace',[SimpleNamespace(parts=[part])])
        path=Path(self.service.store.project(None)['path'])/'.research/executions/global-trace/tools.json'
        self.assertTrue(path.is_file())

    def test_daily_refresh_coalesces_ttl_preserves_failure_and_creates_no_job(self):
        from concurrent.futures import ThreadPoolExecutor
        from v3_backend.research.storage import write_json
        project=self.service.store.project(None);today=pd.Timestamp.now(tz='Asia/Shanghai').strftime('%Y-%m-%d')
        write_json(Path(project['path'])/'data/trading-calendar.json',{'start':today,'end':today,'dates':[today]})
        item={'kind':'stock','symbol':'SH600000'}
        frame=quotes._normalize(pd.DataFrame([{'date':'2025-01-02','open':10,'high':11,'low':9,'close':10,'volume':100,'amount':1000}]),item,'baostock')
        query={'projectId':self.project['id'],'instrument':item,'startDate':'2025-01-02','endDate':'2025-01-02','refresh':True,'autoRefresh':True,'refreshIntervalSeconds':15}
        started=threading.Event();release=threading.Event()
        def fetch(*args):started.set();release.wait(3);return frame,'baostock',None
        with patch.object(quotes,'_fetch',side_effect=fetch) as remote,ThreadPoolExecutor(max_workers=4) as callers:
            futures=[callers.submit(self.service.request,'market.quote',{**query,'period':period}) for period in ('day','week','month','day')]
            self.assertTrue(started.wait(2));time.sleep(.05);self.assertEqual(remote.call_count,1);release.set()
            self.assertTrue(all(f.result(3)['status']=='ready' for f in futures))
            self.service.request('market.quote',query);self.assertEqual(remote.call_count,1)
            key=(str(quotes._path(project,item).resolve()),query['startDate'],query['endDate'])
            with quotes._quote_lock:quotes._quote_completed[key]['at']-=16
            self.service.request('market.quote',query);self.assertEqual(remote.call_count,2)
            self.service.request('market.quote',{**query,'autoRefresh':False});self.assertEqual(remote.call_count,3)
            remote.side_effect=ValueError('行情源失败')
            failed=self.service.request('market.quote',{**query,'autoRefresh':False})
            again=self.service.request('market.quote',query)
            self.assertEqual(remote.call_count,4);self.assertEqual(again['status'],'source_error')
            self.assertEqual(failed['bars'],again['bars']);self.assertEqual(len(again['bars']),1)
        self.assertTrue(quotes._path(project,item).is_file())
        self.assertFalse(quotes._path(self.project,item).exists())
        self.assertFalse((Path(project['path'])/'data/prices.parquet').exists())
        self.assertEqual(self.service.store.list('job'),[])

    def test_daily_bar_in_progress_is_not_complete(self):
        item={'kind':'stock','symbol':'SH600000'}
        dates=['2026-09-10','2026-09-11']
        frame=quotes._normalize(pd.DataFrame([{'date':d,'open':10,'high':11,'low':9,'close':10,'volume':100} for d in dates]),item,'baostock')
        with patch.object(quotes,'read',return_value=frame),patch.object(pd.Timestamp,'now',return_value=pd.Timestamp('2026-09-11T10:30:00+08:00')):
            rows=quotes.bars(self.service.store.project(None),{'instrument':item})
            self.assertTrue(rows[0]['complete']);self.assertFalse(rows[1]['complete'])
