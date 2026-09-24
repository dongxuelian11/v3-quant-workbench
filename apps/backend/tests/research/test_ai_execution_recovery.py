"""Offline recovery fault injection against real conversation, budget and job storage."""
import asyncio
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch
from v3_backend.research.server import Service
from v3_backend.research.ai_budget import ensure_budget, reserve, read_budget


class Crash(BaseException):
    pass


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.service=Service(self.root/'app')
        self.project=self.service.store.create_project(self.root/'project','frozen')
        self.pid=self.project['id']
        self.db=self.service.store.project_store(self.pid).db
        ensure_budget(self.db,'original-budget')
        reserve(self.db,'original-budget','modelRequests',7)

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def seed(self,status='failed',pending=None):
        value=dict(id='old',requestId='old-request',projectId=self.pid,status=status,mode='research',
            pendingMessages=pending or [],submitted={},modelBudget=dict(limit=30,used=7),budgetId='original-budget',
            context=[],projectSnapshots={self.pid+':':deepcopy(self.project)},frozenContext={'configuration':{'original':True}})
        self.service.store.put('conversation',dict(id='recovery',projectId=self.pid,state=dict(execution=value,messages=[])))
        return value

    def resume(self,request='resume'):
        with patch.object(self.service.executions,'run',new=AsyncMock()):
            return self.service.executions.start(dict(conversationId='recovery',requestId=request,message='继续',mode='research'))

    def test_failed_cancelled_without_pending_retain_budget_jobs_and_context(self):
        for status in ('failed','cancelled','paused'):
            with self.subTest(status=status):
                self.seed(status)
                self.service.executions.mutate('recovery','old',lambda state,value:value.update(submitted={'old-spec':'old-job'}))
                budget_store=self.service.store.project_store(self.pid)
                with patch.object(self.service.store,'project_store',return_value=budget_store),patch.object(self.service.store,'project',side_effect=AssertionError('must not read live project')):
                    result=self.resume()
                    replay=self.resume()
                self.assertEqual(result,replay)
                self.assertEqual(result['budgetId'],'original-budget')
                self.assertEqual(result['modelBudget']['used'],7)
                self.assertEqual(result['submitted'],{'old-spec':'old-job'})
                self.assertEqual(result['projectSnapshots'],{self.pid+':':self.project})
                self.assertEqual(result['frozenContext'],{'configuration':{'original':True}})

    def test_pending_survives_failed_and_cancelled_resume(self):
        for status in ('failed','cancelled'):
            self.seed(status,[dict(id='supplement',message='保留补充')])
            result=self.resume()
            self.assertEqual(result['pendingMessages'][0]['id'],'supplement')
            self.assertEqual(bool(result['pendingMessages'][0].get('requiresConfirmation')),status=='cancelled')

    def test_persisted_job_before_conversation_link_crash_reuses_job_and_reservation(self):
        self.seed()
        first=self.resume()
        spec=dict(kind='optimize.run',projectId=self.pid,parameters=dict(trials=3,target='backtest',sampler='grid',baseParameters={},searchSpace={'topN':[1,2,3]}))
        token=json.dumps(spec,sort_keys=True,ensure_ascii=False)
        # Crash inside Jobs after durable job save, before it returns to the conversation.
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next',side_effect=Crash()):
            with self.assertRaises(Crash):asyncio.run(self.service.executions.run_research('recovery',first['id'],spec))
        broken=self.service.executions.status({'conversationId':'recovery'})
        self.assertEqual(broken['submitted'],{})
        job_id=broken['submissionIntents'][token]['id']
        self.assertEqual(self.service.store.get('job',job_id)['status'],'queued')
        self.assertEqual(read_budget(self.db,'original-budget')['used']['trials'],3)
        self.service.close()
        self.service=Service(self.root/'app')
        second=self.resume('after-restart')
        with patch('v3_backend.research.preparation.scope',side_effect=AssertionError('must replay before new preparation')):
            with self.assertRaisesRegex(ValueError,'研究步骤未完成'):
                asyncio.run(self.service.executions.run_research('recovery',second['id'],spec))
        recovered=self.service.executions.status({'conversationId':'recovery'})
        self.assertEqual(recovered['submitted'][token],job_id)
        self.assertEqual(len(self.service.store.list('job')),1)
        self.assertEqual(read_budget(self.db,'original-budget')['used']['trials'],3)
        self.assertIn(job_id,self.service.store.get('conversation','recovery')['state']['stageJobIds'])
        replay=deepcopy(spec)
        replay['name']='renamed presentation only'
        replay['parameters'].update(budgetId='original-budget',budgetProjectId=self.pid)
        self.assertEqual(self.service.jobs.submit(replay,frozen_project=self.project,submission_id=job_id)['id'],job_id)
        with self.assertRaisesRegex(ValueError,'不同'):
            self.service.jobs.submit(replay,frozen_project={**self.project,'id':'other-project'},submission_id=job_id)
        changed=deepcopy(spec)
        changed['parameters'].update(trials=4,budgetId='original-budget',budgetProjectId=self.pid)
        with self.assertRaisesRegex(ValueError,'不同'):
            self.service.jobs.submit(changed,frozen_project=self.project,submission_id=job_id)

    def test_crash_after_reservation_before_job_does_not_charge_twice(self):
        self.seed()
        first=self.resume()
        spec=dict(kind='optimize.run',projectId=self.pid,parameters=dict(trials=3,target='backtest',sampler='grid',baseParameters={},searchSpace={'topN':[1,2,3]}))
        with patch.object(self.service.jobs,'submit',side_effect=Crash()):
            with self.assertRaises(Crash):asyncio.run(self.service.executions.run_research('recovery',first['id'],spec))
        self.assertEqual(read_budget(self.db,'original-budget')['used']['trials'],3)
        self.assertEqual(self.service.store.list('job'),[])
        self.service.executions.mutate('recovery',first['id'],lambda state,value:value.update(status='failed'))
        second=self.resume('retry')
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next',side_effect=Crash()):
            with self.assertRaises(Crash):asyncio.run(self.service.executions.run_research('recovery',second['id'],spec))
        self.assertEqual(read_budget(self.db,'original-budget')['used']['trials'],3)
        self.assertEqual(len(self.service.store.list('job')),1)

    def test_intent_before_reservation_crash_still_charges_once_on_resume(self):
        self.seed()
        first=self.resume()
        spec=dict(kind='optimize.run',projectId=self.pid,parameters=dict(trials=3,target='backtest',sampler='grid',baseParameters={},searchSpace={'topN':[1,2,3]}))
        with patch('v3_backend.research.ai_execution.reserve',side_effect=Crash()):
            with self.assertRaises(Crash):asyncio.run(self.service.executions.run_research('recovery',first['id'],spec))
        self.assertEqual(read_budget(self.db,'original-budget')['used']['trials'],0)
        self.service.executions.mutate('recovery',first['id'],lambda state,value:value.update(status='failed'))
        second=self.resume('retry')
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next',side_effect=Crash()):
            with self.assertRaises(Crash):asyncio.run(self.service.executions.run_research('recovery',second['id'],spec))
        self.assertEqual(read_budget(self.db,'original-budget')['used']['trials'],3)
        self.assertEqual(len(self.service.store.list('job')),1)

    def test_paused_strategy_reference_and_snapshot_survive_live_changes(self):
        self.seed('paused')
        reference=dict(kind='strategy',projectId=self.pid,strategyId='original')
        frozen={**deepcopy(self.project),'strategyId':'original','strategyName':'before edit'}
        self.service.executions.mutate('recovery','old',lambda state,value:value.update(context=[reference],projectSnapshots={self.pid+':':self.project,self.pid+':original':frozen}))
        with patch('v3_backend.research.workbench.strategy_project',side_effect=AssertionError('live strategy must not be reread')):
            result=self.resume()
        self.assertEqual(result['context'],[reference])
        self.assertEqual(result['projectSnapshots'][self.pid+':original'],frozen)
