"""Real SQLite/Jobs fault boundaries, no subprocess or model transport."""
import asyncio
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from v3_backend.research.server import Service
from v3_backend.research import reports
from v3_backend.research.ai_budget import ensure_budget, read_budget

class Crash(BaseException):pass

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.service=Service(self.root/'app');self.quiet_scheduler()
        self.project=self.service.store.create_project(self.root/'project','report recovery');self.pid=self.project['id']
        report=self.service.store.put('report',dict(id='a'*32,title='report',collectedAt='2026-09-24',publishedAt='2025-01-01'))
        reports._save_pages(self.service.store,report,[dict(page=1,text='source text',method='text')])
        step=dict(id='a',name='optimize',variant='original',dependsOn=[],differences=[],citations=[dict(reportId='a'*32,page=1,excerpt='source text')],spec=dict(kind='optimize.run',parameters=dict(trials=3,target='backtest',sampler='grid',baseParameters={},searchSpace={'topN':[1,2,3]},startDate='2025-01-02',endDate='2025-02-01')))
        dependent={**deepcopy(step),'id':'b','dependsOn':['a']}
        self.plan=self.service.report_tasks.dispatch('reproductions.save',dict(projectId=self.pid,plan=dict(reportId='a'*32,name='plan',steps=[step,dependent],missingConditions=[])))
        self.params=dict(projectId=self.pid,planId=self.plan['id'])

    def quiet_scheduler(self):
        self.service.report_tasks.stop.set();self.service.report_tasks.thread.join(timeout=2)
    def tearDown(self):
        self.service.close();self.temp.cleanup()
    def restart(self):
        self.service.close();self.service=Service(self.root/'app');self.quiet_scheduler()
    def only_run(self):return self.service.store.list('reproduction_run')[0]
    def used(self,run):return read_budget(self.service.store.project_store(self.pid).db,run['budgetId'])['used']['trials']
    def seed_execution(self):
        ensure_budget(self.service.store.project_store(self.pid).db,'ai-budget')
        value=dict(id='execution',requestId='request',projectId=self.pid,status='running',cancelRequested=False,pendingMessages=[],deliveredMessageIds=[],steps=[],activeJobIds=[],budgetId='ai-budget',projectSnapshots={self.pid+':':self.project})
        self.service.store.put('conversation',dict(id='chat',projectId=self.pid,state=dict(execution=value,messages=[])))

    def test_reserved_before_job_restart_recovers_same_attempt(self):
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'submit',side_effect=Crash()):
            with self.assertRaises(Crash):self.service.report_tasks.dispatch('reproductions.run',self.params)
        old=self.only_run();submission=old['steps'][0]['submissionId']
        self.assertEqual(self.used(old),3);self.assertEqual(self.service.store.list('job'),[])
        self.restart()
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next'):
            resumed=self.service.report_tasks.dispatch('reproductions.run',{**self.params,'runId':old['id']})
        self.assertEqual(resumed['steps'][0]['jobId'],submission)
        self.assertEqual(self.used(resumed),3);self.assertEqual(len(self.service.store.list('job')),1)

    def test_persisted_child_restart_never_resubmits_until_explicit_retry(self):
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next',side_effect=Crash()):
            with self.assertRaises(Crash):self.service.report_tasks.dispatch('reproductions.run',self.params)
        old=self.only_run();original=old['steps'][0]['submissionId']
        self.assertNotIn('jobId',old['steps'][0]);self.assertEqual(len(self.service.store.list('job')),1)
        self.restart()
        with patch.object(self.service.jobs,'submit',side_effect=AssertionError('same attempt cannot resubmit')):
            resumed=self.service.report_tasks.dispatch('reproductions.run',{**self.params,'runId':old['id']})
        self.assertEqual(resumed['steps'][0]['jobId'],original)
        self.assertEqual(resumed['steps'][0]['status'],'interrupted');self.assertEqual(self.used(resumed),3)
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next'):
            retried=self.service.report_tasks.dispatch('reproductions.run',{**self.params,'runId':old['id'],'retryFailed':True})
        self.assertNotEqual(retried['steps'][0]['jobId'],original)
        self.assertEqual(retried['steps'][0]['attempt'],2)
        self.assertEqual(retried['steps'][0]['attemptHistory'][0]['jobId'],original)
        self.assertEqual(self.used(retried),6);self.assertEqual(len(self.service.store.list('job')),2)

    def test_cancel_while_submission_thread_has_not_returned(self):
        self.seed_execution();entered=threading.Event();release=threading.Event();real_submit=self.service.jobs.submit
        def blocked(*args,**kwargs):
            job=real_submit(*args,**kwargs);entered.set()
            if not release.wait(5):raise AssertionError('test barrier timed out')
            return job
        async def exercise():
            task=asyncio.create_task(self.service.executions.run_reproduction('chat','execution',self.plan['id']))
            for _ in range(200):
                if entered.is_set():break
                await asyncio.sleep(.01)
            self.assertTrue(entered.is_set())
            intent=self.only_run();self.assertEqual(intent['executionOwner'],dict(conversationId='chat',executionId='execution'))
            self.service.executions.mutate('chat','execution',lambda state,value:value['pendingMessages'].append(dict(id='keep',message='pending supplement')))
            task.cancel();await asyncio.sleep(.02);release.set()
            with self.assertRaises(asyncio.CancelledError):await task
        try:
            with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next'),patch.object(self.service.jobs,'submit',side_effect=blocked):asyncio.run(exercise())
        finally:release.set()
        run=self.only_run();jobs=self.service.store.list('job')
        self.assertEqual(run['status'],'cancelled');self.assertFalse(run['cancelPending'])
        self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['status'],'cancelled')
        conversation=self.service.store.get('conversation','chat')
        self.assertIn(jobs[0]['id'],conversation['state']['stageJobIds'])
        self.assertIn(run['id'],conversation['state']['execution']['reproductionRunIds'])
        self.assertEqual(conversation['state']['execution']['activeJobIds'],[])
        self.assertEqual(conversation['state']['execution']['pendingMessages'][0]['id'],'keep')

    def test_unowned_history_cannot_be_claimed_by_ai(self):
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next'):
            run=self.service.report_tasks.dispatch('reproductions.run',self.params)
        self.seed_execution()
        params={**self.params,'runId':run['id'],'budgetId':'ai-budget','budgetProjectId':self.pid}
        with self.assertRaisesRegex(ValueError,'不属于此会话'):
            self.service.report_tasks.run_for_execution(params,'chat','execution')
        self.assertNotIn('executionOwner',self.only_run())

    def test_cancel_timeout_reports_unconfirmed_then_worker_stops(self):
        self.seed_execution();entered=threading.Event();release=threading.Event();finished=threading.Event();real_submit=self.service.jobs.submit
        def blocked(*args,**kwargs):
            job=real_submit(*args,**kwargs);entered.set()
            if not release.wait(6):raise AssertionError('barrier timed out')
            return job
        original=self.service.report_tasks.run_for_execution
        def run(*args):
            try:return original(*args)
            finally:finished.set()
        async def exercise():
            task=asyncio.create_task(self.service.executions.run_reproduction('chat','execution',self.plan['id']))
            for _ in range(200):
                if entered.is_set():break
                await asyncio.sleep(.01)
            self.assertTrue(entered.is_set());task.cancel()
            try:
                with self.assertRaisesRegex(ValueError,'尚未确认'):await asyncio.wait_for(task,3)
                self.assertNotEqual(self.only_run()['status'],'cancelled')
            finally:release.set()
            for _ in range(200):
                if finished.is_set():break
                await asyncio.sleep(.01)
            self.assertTrue(finished.is_set())
        try:
            with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next'),patch.object(self.service.jobs,'submit',side_effect=blocked),patch.object(self.service.report_tasks,'run_for_execution',side_effect=run):asyncio.run(exercise())
        finally:release.set()
        self.assertEqual(self.only_run()['status'],'cancelled')
        job=self.service.store.list('job')[0]
        self.assertEqual(job['status'],'cancelled')
        self.assertIn(job['id'],self.service.store.get('conversation','chat')['state']['stageJobIds'])

    def test_failed_stop_keeps_unconfirmed_and_blocks_retry(self):
        from types import SimpleNamespace
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next'):
            run=self.service.report_tasks.dispatch('reproductions.run',self.params)
        job_id=run['steps'][0]['jobId']
        with patch.dict(self.service.jobs.processes,{job_id:SimpleNamespace(poll=lambda:None)}),patch.object(self.service.jobs,'cancel',return_value={'status':'cancelled'}):
            with self.assertRaisesRegex(ValueError,'尚未确认'):
                self.service.report_tasks.dispatch('reproductions.cancel',{**self.params,'runId':run['id']})
        state=self.only_run();self.assertTrue(state['cancelPending']);self.assertEqual(state['status'],'failed')
        with self.assertRaisesRegex(ValueError,'停止尚未确认'):
            self.service.report_tasks.dispatch('reproductions.run',{**self.params,'runId':run['id'],'retryFailed':True})
        stopped=self.service.report_tasks.dispatch('reproductions.cancel',{**self.params,'runId':run['id']})
        self.assertFalse(stopped['cancelPending']);self.assertEqual(stopped['status'],'cancelled')

    def test_same_service_saved_queued_child_is_rescheduled_without_new_charge(self):
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next',side_effect=Crash()):
            with self.assertRaises(Crash):self.service.report_tasks.dispatch('reproductions.run',self.params)
        old=self.only_run();key=old['steps'][0]['submissionId']
        def schedule(pid):
            job=self.service.store.get('job',key);job['status']='running';self.service.store.put('job',job,pid)
        with patch.object(self.service.jobs,'_start_next',side_effect=schedule) as start:
            recovered=self.service.report_tasks.dispatch('reproductions.run',{**self.params,'runId':old['id']})
        start.assert_called_once_with(self.pid)
        self.assertEqual(recovered['steps'][0]['jobId'],key)
        self.assertEqual(recovered['steps'][0]['status'],'running')
        self.assertEqual(self.used(recovered),3);self.assertEqual(len(self.service.store.list('job')),1)

    def test_owner_scope_and_budget_are_checked_before_creating_run(self):
        self.seed_execution()
        params={**self.params,'budgetId':'ai-budget','budgetProjectId':self.pid}
        with self.assertRaisesRegex(ValueError,'冻结项目范围'):
            self.service.report_tasks.run_for_execution(params,'chat','another-execution')
        with self.assertRaisesRegex(ValueError,'预算'):
            self.service.report_tasks.run_for_execution({**params,'budgetId':'another-budget'},'chat','execution')
        self.assertEqual(self.service.store.list('reproduction_run'),[])
