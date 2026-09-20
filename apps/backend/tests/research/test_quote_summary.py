import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from v3_backend.research.server import Service
from v3_backend.research import quotes,project_summary
from v3_backend.research.storage import write_json,now


class QuoteSummaryTests(unittest.TestCase):
    def test_strategy_dates_are_independent_and_active_is_frozen(self):
        from v3_backend.research.workbench import strategy_project
        pid=self.project['id']
        self.store.save_project({**self.project,'startDate':'2024-01-01','endDate':'2024-12-31'})
        a=self.service.request('strategies.create',{'projectId':pid,'name':'A'})
        b=self.service.request('strategies.create',{'projectId':pid,'name':'B'})
        self.assertEqual(a['settings']['startDate'],'2024-01-01')
        def save_dates(strategy,start,end):
            return self.service.request('strategies.save',{'projectId':pid,'strategy':{'id':strategy['id']},'settingsPatch':{'startDate':start,'endDate':end}})
        save_dates(a,'2025-01-01','2025-01-31')
        self.service.request('strategies.activate',{'projectId':pid,'strategyId':a['id'],'enabled':True})
        save_dates(a,'2025-02-01','2025-02-28')
        save_dates(b,'2025-03-01','2025-03-31')
        self.assertEqual(strategy_project(self.store,pid,a['id'])['startDate'],'2025-02-01')
        self.assertEqual(strategy_project(self.store,pid,b['id'])['endDate'],'2025-03-31')
        active=strategy_project(self.store,pid,a['id'],active=True)
        self.assertEqual((active['startDate'],active['endDate']),('2025-01-01','2025-01-31'))
        self.assertEqual(self.store.project(pid)['startDate'],'2024-01-01')
        save_dates(b,None,None)
        self.assertEqual(strategy_project(self.store,pid,b['id'])['startDate'],'2024-01-01')

    def test_typed_quote_context_is_local_and_bounded(self):
        from v3_backend.research.ai import attached_context
        targets=[{'kind':'index','symbol':'SH000001'},{'kind':'stock','symbol':'SZ000001'},
                 {'kind':'concept','symbol':'BK0884'}]
        for target in targets:
            path=quotes._path(self.store.project(None),target);path.parent.mkdir(parents=True,exist_ok=True)
            frame=pd.DataFrame({'date':pd.date_range('2026-01-01',periods=100),'open':10.,'high':11.,'low':9.,'close':10.,'volume':100.,'amount':1000.})
            quotes._normalize(frame,target,'baostock').to_parquet(path)
        with patch.object(quotes,'_ak',side_effect=AssertionError('network')),patch.object(quotes,'_baostock',side_effect=AssertionError('network')):
            items=attached_context(self.service,[{'kind':'quote','instrument':target,'date':'2026-03-31'} for target in targets])['attachedObjects']
        for item,target in zip(items,targets):
            self.assertEqual(item['quote']['instrument'],target)
            self.assertEqual(len(item['quote']['bars']),60)
            self.assertLessEqual(pd.Timestamp(item['quote']['bars'][-1]['date']),pd.Timestamp('2026-03-31'))
            self.assertEqual(item['quote']['coverage']['rows'],100)
            self.assertNotIn('stock',item)
        self.assertEqual(items[2]['members']['rows'],[])

    def test_empty_summary_initializes_once_and_keeps_sources(self):
        pid=self.project['id'];initial=project_summary.get(self.store,pid)
        initialized=project_summary.append_response(self.store,pid,{},initial['revision'],'')
        self.assertTrue(initialized['historyInitialized'])
        self.assertEqual(initialized['goals'],initial['goals'])
        self.assertEqual(project_summary.append_response(self.store,pid,None,initialized['revision'],''),initialized)
        chat=self.service.request('ai.conversations.create',{'projectId':pid})
        sourced=project_summary.append_response(self.store,pid,None,initialized['revision'],'',chat['id'])
        self.assertEqual(sourced['sourceConversationIds'],[chat['id']])
        cleared=project_summary.clear(self.store,pid)
        self.assertEqual(project_summary.append_response(self.store,pid,None,sourced['revision'],'',chat['id']),cleared)
        self.assertTrue(project_summary.append_response(self.store,pid,None,cleared['revision'],'',chat['id'])['cleared'])

    def test_success_without_summary_does_not_repeat_initial_history(self):
        from types import SimpleNamespace
        import json
        from v3_backend.research import ai
        pid=self.project['id'];chat=self.service.request('ai.conversations.create',{'projectId':pid})
        chat['state']['messages']=[{'role':'user','content':'历史测试文字'}]
        self.service.request('ai.conversations.save',{'conversation':chat})
        self.store.settings=lambda:{'ai':{'baseUrl':'http://localhost:9999/v1','model':'fixture'}}
        prompts=[]
        def respond(prompt,**kwargs):
            prompts.append(json.loads(prompt))
            return SimpleNamespace(output=SimpleNamespace(model_dump=lambda:{'message':'已回答','phase':'ask','proposals':[], 'experimentIds':[],'summaryUpdate':None}))
        with patch.object(ai,'_create_agent',return_value=SimpleNamespace(run_sync=respond)):
            for _ in range(2):ai.chat(self.service,{'projectId':pid,'conversationId':chat['id'],'mode':'ask','message':'测试问题'})
        self.assertTrue(prompts[0]['summaryHistory'])
        self.assertEqual(prompts[1]['summaryHistory'],[])
        self.assertEqual(project_summary.get(self.store,pid)['sourceConversationIds'],[chat['id']])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.service=Service(self.root/'profile');self.store=self.service.store
        self.project=self.store.create_project(str(self.root/'project'),'fixture','明确目标')
    def tearDown(self):
        self.service.close();self.temp.cleanup()

    def test_identity_and_catalog_read_only(self):
        with patch.object(quotes,'_ak',side_effect=AssertionError('network')),patch.object(quotes,'_baostock',side_effect=AssertionError('network')):
            result=quotes.catalog(self.store.project(None),{})
            self.assertEqual(len(result['items']),8);self.assertTrue(result['needsRefresh'])
        self.assertEqual(quotes.instrument({'kind':'stock','symbol':'000001'})['symbol'],'SZ000001')
        self.assertEqual(quotes.instrument({'kind':'index','symbol':'SH000001'})['symbol'],'SH000001')
        self.assertNotEqual(quotes._path(self.project,{'kind':'stock','symbol':'SH000001'}),quotes._path(self.project,{'kind':'index','symbol':'SH000001'}))
        with self.assertRaises(ValueError):quotes.instrument({'kind':'stock','symbol':'BK0475'})

    def test_units_and_failed_update_preserves_cache(self):
        source=pd.DataFrame([dict(日期='2026-09-08',开盘=10,最高=11,最低=9,收盘=10,成交量=3,成交额=3000)])
        item={'kind':'index','symbol':'SH000001'}
        converted=quotes._normalize(source,item,'akshare/eastmoney')
        self.assertEqual(converted.volume.iloc[0],300);self.assertEqual(converted.amount.iloc[0],3000)
        root=self.store.project(None);path=quotes._path(root,item);path.parent.mkdir(parents=True);converted.to_parquet(path)
        before=path.read_bytes()
        with patch.object(quotes,'_baostock',side_effect=ValueError('offline')),patch.object(quotes,'_ak',side_effect=ValueError('offline')):
            with self.assertRaises(ValueError):quotes.update(root,{'instrument':item,'startDate':'2026-09-01'},lambda *_:None)
        self.assertEqual(before,path.read_bytes())

    def test_conversation_scope_and_clear_wins(self):
        pid=self.project['id'];timestamp=now()
        for key,context in [('one',[{'projectId':pid}]),('mixed',[{'projectId':pid},{'projectId':'another'}]),('none',[])]:
            self.store.put('conversation',dict(id=key,name=key,context=context,state={'messages':[]},createdAt=timestamp,updatedAt=timestamp))
        global_chat=self.service.request('ai.conversations.create',{'projectId':None})
        local=self.service.request('ai.conversations.list',{'projectId':pid})
        self.assertEqual([c['id'] for c in local],['one'])
        self.assertEqual({c['id'] for c in self.service.request('ai.conversations.list',{'unassigned':True})},{'mixed','none'})
        self.assertEqual([c['id'] for c in self.service.request('ai.conversations.list',{'projectId':None})],[global_chat['id']])
        value=project_summary.get(self.store,pid)
        saved=project_summary.save(self.store,pid,{'notes':'手工保留','userDecisions':['人工明确决定']},value['revision'])
        project_summary.append_response(self.store,pid,{'hypotheses':['候选']},saved['revision'],'本次问题')
        cleared=project_summary.clear(self.store,pid)
        stale=project_summary.append_response(self.store,pid,{'hypotheses':['不应回填']},saved['revision'],'本次问题')
        self.assertEqual(stale,cleared)
        self.assertEqual(project_summary.get(self.store,pid)['goals'],[])

    def test_experiment_chart_keeps_snapshot_source(self):
        pid=self.project['id'];old=self.root/'old/data';new=self.root/'new/data'
        for folder,value in [(old,10),(new,99)]:
            folder.mkdir(parents=True)
            pd.DataFrame([dict(date=pd.Timestamp('2026-09-08'),symbol='SH600000',open=value,high=value,low=value,close=value,volume=100,amount=1000,factor=1)]).to_parquet(folder/'prices.parquet',index=False)
        original={**self.project,'settings':{'dataPath':str(old)}}
        run=Path(self.project['path'])/'.research/runs/chart-fixture';run.mkdir(parents=True)
        write_json(run/'project.json',original)
        self.store.save_experiment(pid,dict(id='chart-fixture',projectId=pid,kind='backtest.run',createdAt=now(),parameters={'startDate':'2026-09-08','endDate':'2026-09-08'},artifacts=[],metrics={},summary='fixture'))
        self.store.save_project({**self.project,'settings':{'dataPath':str(new)}})
        rows=self.service.request('data.bars',{'projectId':pid,'symbol':'SH600000','experimentId':'chart-fixture'})
        self.assertEqual(rows[0]['close'],10)
        current=self.service.request('data.bars',{'projectId':pid,'symbol':'SH600000'})
        self.assertEqual(current[0]['close'],99)
        from v3_backend.research.ai import attached_context
        focused=attached_context(self.service,[{'kind':'stock','projectId':pid,'symbol':'SH600000','experimentId':'chart-fixture'}])
        self.assertEqual(focused['attachedObjects'][0]['bars'][0]['close'],10)

    def test_incremental_tail_rebases_only_adjusted_prices(self):
        item={'kind':'stock','symbol':'SH600000'};project=self.store.project(None)
        old=pd.DataFrame([dict(date=pd.Timestamp(day),open=10.,high=10.,low=10.,close=10.,rawOpen=20.,rawHigh=20.,rawLow=20.,rawClose=20.,factor=.5,volume=100,amount=2000) for day in ('2026-09-01','2026-09-02')])
        path=quotes._path(project,item);path.parent.mkdir(parents=True);old.to_parquet(path)
        incoming=old.iloc[-1:].copy();incoming[['open','high','low','close','factor']]*=.5
        next_day=incoming.copy();next_day['date']=pd.Timestamp('2026-09-03');incoming=pd.concat([incoming,next_day])
        with patch.object(quotes,'_fetch',return_value=(incoming,'baostock',None)) as fetch:
            quotes.update(project,{'instrument':item,'startDate':'2026-09-01','endDate':'2026-09-03'},lambda *_:None)
        self.assertEqual(fetch.call_args.args[1:],('2026-09-02','2026-09-03'))
        saved=pd.read_parquet(path);self.assertEqual(len(saved),3)
        self.assertTrue(saved.rawClose.eq(20).all());self.assertTrue(saved.close.eq(5).all());self.assertTrue(saved.factor.eq(.25).all())

    def test_summary_source_and_clear_history_offsets(self):
        pid=self.project['id'];chat=self.service.request('ai.conversations.create',{'projectId':pid})
        chat['state']['messages']=[{'role':'user','content':'旧讨论'}];self.service.request('ai.conversations.save',{'conversation':chat})
        first=project_summary.get(self.store,pid)
        updated=project_summary.append_response(self.store,pid,{'hypotheses':['候选解释']},first['revision'],'本次文字',[chat['id']])
        self.assertEqual(updated['sourceConversationIds'],[chat['id']])
        cleared=project_summary.clear(self.store,pid)
        history=project_summary.histories(self.store,pid,cleared)
        self.assertEqual(history[0]['messages'],[])

    def test_chat_freezes_project_and_appends_same_response_summary(self):
        from types import SimpleNamespace
        from v3_backend.research import ai
        other=self.store.create_project(str(self.root/'other'),'OTHER_PROJECT_MARKER','other')
        chat=self.service.request('ai.conversations.create',{'projectId':self.project['id']})
        self.store.settings=lambda:{'ai':{'baseUrl':'http://localhost:9999/v1','model':'fixture'}}
        answer={'message':'记录明确测试决定','phase':'讨论','proposals':[],'experimentIds':[],
                'summaryUpdate':{'userDecisions':['只做历史研究'],'hypotheses':['未确认假设']}}
        captured=[]
        def respond(prompt,**kwargs):
            captured.append(prompt)
            return SimpleNamespace(output=SimpleNamespace(model_dump=lambda:answer))
        with patch.object(ai,'_create_agent',return_value=SimpleNamespace(run_sync=respond)) as create:
            with self.assertRaisesRegex(ValueError,'所属项目'):
                ai.chat(self.service,{'conversationId':chat['id'],'projectId':other['id'],'message':'wrong'})
            self.assertEqual(create.call_count,0)
            ai.chat(self.service,{'conversationId':chat['id'],'projectId':self.project['id'],'mode':'ask','message':'我决定只做历史研究'})
        self.assertEqual(len(captured),1)
        self.assertNotIn('OTHER_PROJECT_MARKER',captured[0])
        value=project_summary.get(self.store,self.project['id'])
        self.assertIn('只做历史研究',value['userDecisions'])
        self.assertIn(chat['id'],value['sourceConversationIds'])

    def test_members_exclude_beijing_and_use_existing_filter_operator(self):
        rows=pd.DataFrame([{'代码':code,'名称':code,'最新价':10,'涨跌幅':change,'成交量':3,'成交额':3000} for code,change in [('600000',2),('000001',-1),('920001',8),('BJ430001',9)]])
        with patch.object(quotes,'_ak',return_value=rows):
            result=quotes.members(self.store.project(None),{'instrument':{'kind':'industry','symbol':'BK0475'},'refresh':True,
                'filters':[{'field':'pctChange','operator':'gte','value':0}]})
        self.assertEqual(result['total'],1);self.assertEqual(result['rows'][0]['symbol'],'SH600000')
        self.assertEqual(result['rows'][0]['volume'],300)
        with self.assertRaises(ValueError):quotes.instrument({'kind':'stock','symbol':'920001'})

    def test_quote_cancel_stops_provider_child(self):
        import subprocess,sys,psutil
        key='quote-cancel-fixture'
        job=dict(id=key,kind='data.update',projectId=None,status='running',name='quote fixture',progress=0,
                 createdAt=now(),updatedAt=now(),spec={'parameters':{'quoteOnly':True,'instrument':{'kind':'index','symbol':'SH000300'}}})
        self.store.put('job',job)
        script="import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);print(p.pid,flush=True);time.sleep(60)"
        process=subprocess.Popen([sys.executable,'-c',script],stdout=subprocess.PIPE,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        child=int(process.stdout.readline().strip());self.service.jobs.processes[key]=process
        try:
            result=self.service.jobs.cancel(key)
            self.assertEqual(result['status'],'cancelled');self.assertIsNotNone(process.poll());self.assertFalse(psutil.pid_exists(child))
        finally:
            self.service.jobs.processes.pop(key,None)
            if process.poll() is None:process.kill()
            process.wait();process.stdout.close()


if __name__=='__main__':unittest.main()
