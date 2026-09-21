"""Independent recovery-boundary QA; transport is never invoked."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from copy import deepcopy
from v3_backend.research.server import Service
import test_reports

class ExecutionRecoveryQA(unittest.TestCase):
    def check_resume(self, extra):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(Path(temp)/'app')
            try:
                old=dict(id='old',requestId='old-request',projectId=None,status='paused',mode='research',message='paused',pendingMessages=[],submitted={},modelBudget=dict(limit=30,used=30,scope='execution'),**extra)
                service.store.put('conversation',dict(id='qa',projectId=None,state=dict(execution=old)))
                with patch.object(service.executions,'run',new=AsyncMock()):
                    result=service.request('ai.chat.start',dict(conversationId='qa',requestId='new-request',message='继续',mode='research'))
                self.assertEqual(result['modelBudget']['used'],30,'Resuming exhausted research must never reset spent model calls')
            finally:service.close()
    def test_legacy_paused_budget_not_reset(self):
        self.check_resume({})
    def test_missing_shared_record_cannot_reset(self):
        try:self.check_resume(dict(budgetId='missing-shared'))
        except ValueError as exc:self.assertIn('预算',str(exc))

class ReportRetryQA(unittest.TestCase):
    setUp=test_reports.ReportsTests.setUp
    tearDown=test_reports.ReportsTests.tearDown
    plan=test_reports.ReportsTests.plan
    def test_same_revision_retry_without_run_id_keeps_failed_trials(self):
        plan=self.plan();step=deepcopy(plan['steps'][0])
        step['spec']=dict(kind='optimize.run',parameters=dict(trials=12,target='backtest',sampler='grid',baseParameters={},searchSpace={'topN':[2,3]},startDate='2025-07-01',endDate='2025-12-31'))
        plan['steps']=[step]
        plan=self.tasks.dispatch('reproductions.save',dict(projectId=self.project['id'],plan=plan))
        params=dict(projectId=self.project['id'],planId=plan['id'])
        run=self.tasks.dispatch('reproductions.run',params)
        job=self.store.get('job',run['steps'][0]['jobId']);job['status']='failed';self.store.put('job',job,self.project['id']);self.tasks._advance(run)
        try:self.tasks.dispatch('reproductions.run',params)
        except ValueError:pass
        self.assertEqual(len(self.jobs.calls),1,'Retrying same plan revision must include prior 12 failed trials in ceiling 20')


class ActualWireHookQA(unittest.TestCase):
    def test_legacy_29_then_429_counts_before_wire_and_resume_sends_nothing(self):
        import time
        import httpx
        from v3_backend.research.ai_budget import read_budget
        with tempfile.TemporaryDirectory() as temp:
            service=Service(Path(temp)/'app')
            real_client=httpx.AsyncClient
            sent=[]
            try:
                service.store.settings({'ai':{'baseUrl':'https://qa.invalid/v1','model':'qa-model','apiKey':'offline'}})
                old=dict(id='old',requestId='old-request',projectId=None,status='paused',mode='ask',message='paused',pendingMessages=[],submitted={},modelBudget=dict(limit=30,used=29,scope='execution'))
                service.store.put('conversation',dict(id='wire-qa',projectId=None,state=dict(execution=old,messages=[])))
                def wire(request):
                    current=service.executions.status({'conversationId':'wire-qa'})
                    count=read_budget(service.store.project_store(None).db,current['budgetId'])['used']['modelRequests']
                    sent.append(count)
                    return httpx.Response(429,headers={'retry-after':'0'},json={'error':{'message':'offline limit','type':'rate_limit'}})
                class OfflineClient(real_client):
                    def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(wire),**kwargs)
                def await_terminal():
                    end=time.monotonic()+20
                    while time.monotonic()<end:
                        current=service.executions.status({'conversationId':'wire-qa'})
                        if current['status']!='running':return current
                        time.sleep(.02)
                    self.fail('Execution did not finish')
                with patch('httpx.AsyncClient',OfflineClient),patch('socket.socket.connect',side_effect=AssertionError('No external network permitted')):
                    service.request('ai.chat.start',dict(conversationId='wire-qa',requestId='attempt1',message='继续',mode='ask'))
                    first=await_terminal()
                    self.assertEqual(first['status'],'paused',first)
                    self.assertEqual(sent,[30])
                    service.request('ai.chat.start',dict(conversationId='wire-qa',requestId='attempt2',message='继续',mode='ask'))
                    second=await_terminal()
                    self.assertEqual(second['status'],'paused',second)
                    self.assertEqual(second['budgetId'],first['budgetId'])
                    self.assertEqual(second['modelBudget']['used'],30)
                    self.assertEqual(sent,[30])
            finally:service.close()


class NativePermitQA(unittest.TestCase):
    def test_shared_owner_permit_ceiling_and_idempotent_new_request_folder(self):
        from concurrent.futures import ThreadPoolExecutor
        from v3_backend.research.storage import Store,write_json
        from v3_backend.research.ai_budget import ensure_budget,reserve,read_budget,BudgetExhausted
        from v3_backend.research import rd_agent
        from v3_backend.research.rd_runners import protocol
        import time
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'owner');bridge=root/'bridge';bridge.mkdir()
            ensure_budget(store.db,'shared');reserve(store.db,'shared','modelRequests',29)
            write_json(bridge/'config.json',dict(action='factor',rounds=1,codeRepairRounds=1,budgetId='shared'))
            protocol.initialize(bridge)
            with ThreadPoolExecutor(max_workers=1) as pool:
                def permit(category,operation=None):
                    future=pool.submit(protocol.reserve,category,1,operation)
                    deadline=time.monotonic()+3
                    while not future.done() and time.monotonic()<deadline:
                        rd_agent._budget_requests(bridge,store.db,'shared');time.sleep(.005)
                    if not future.done():write_json(bridge/'cancel.json',{})
                    return future.result(timeout=1)
                self.assertEqual(permit('modelRequests')['used']['modelRequests'],30)
                with self.assertRaises(BudgetExhausted):permit('modelRequests')
                permit('candidateGroups','lineage_group_1');permit('candidateGroups','lineage_group_1')
                value=read_budget(store.db,'shared')
                self.assertEqual(value['used']['modelRequests'],30)
                self.assertEqual(value['used']['candidateGroups'],1)
                responses=[__import__('json').loads(p.read_text()) for p in (bridge/'budgetRequests').glob('*/response.json')]
                self.assertEqual(sum(not item['allowed'] for item in responses),1)
