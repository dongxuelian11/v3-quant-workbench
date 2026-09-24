"""Explicit dependency-closed subsets; fixture Jobs never launch calculations."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from test_reports import ReportsTests
from v3_backend.research.ai_budget import read_budget
from v3_backend.research.ai_execution import Executions

class SubsetTests(unittest.TestCase):
    setUp=ReportsTests.setUp
    tearDown=ReportsTests.tearDown
    plan=ReportsTests.plan

    def subset_plan(self):
        plan=self.plan();template=plan['steps'][0]
        plan['steps']=[{**deepcopy(template),'id':key,'name':key,'dependsOn':deps} for key,deps in [('A',[]),('B',[]),('C',['B']),('D',['A'])]]
        plan['steps'][1]['missingConditions']=['end date unknown']
        plan['steps'][1]['spec']['parameters'].pop('endDate')
        return self.tasks.dispatch('reproductions.save',dict(projectId=self.project['id'],plan=plan))
    def start(self,plan,**extra):return self.tasks.dispatch('reproductions.run',dict(projectId=self.project['id'],planId=plan['id'],revision=plan['revision'],**extra))
    def finish(self,run):
        for state in run['steps']:
            if state.get('jobId'):
                job=self.store.get('job',state['jobId']);job.update(status='completed',experimentId='result-'+state['stepId']);self.store.put('job',job,self.project['id'])
        self.tasks._advance(run)

    def test_local_missing_blocks_descendants_but_selected_dependency_chain_runs(self):
        plan=self.subset_plan()
        self.assertEqual(plan['readiness']['runnableStepIds'],['A','D'])
        self.assertEqual(plan['readiness']['blockedSteps'][1]['blockedByStepIds'],['B'])
        with self.assertRaisesRegex(ValueError,'缺失条件'):self.start(plan)
        self.assertEqual(self.jobs.calls,[])
        run=self.start(plan,selectedStepIds=['D','A'])
        self.assertEqual(run['selectedStepIds'],['A','D']);self.assertEqual(run['excludedStepIds'],['B','C'])
        self.assertEqual(run['executionScope'],'subset');self.assertEqual([s['stepId'] for s in run['steps']],['A','D'])
        self.finish(run);self.finish(run)
        self.assertEqual(run['status'],'completed');self.assertIn('所选2/4步完成',run['message']);self.assertIn('未执行其余',run['message'])
        self.assertEqual([s['reproduction']['stepId'] for s in self.jobs.calls],['A','D'])
        self.assertEqual(len(run['planSnapshot']['steps']),4)

    def test_empty_duplicate_unknown_and_nonclosed_selections_are_refused(self):
        plan=self.subset_plan()
        for selected in ([],['A','A'],['unknown'],['D'],['B'],['B','C'],None,'A'):
            with self.subTest(selected=selected),self.assertRaises(ValueError):self.start(plan,selectedStepIds=selected)
        self.assertEqual(self.jobs.calls,[]);self.assertEqual(self.store.list('reproduction_run'),[])

    def test_global_missing_still_blocks_every_subset(self):
        plan=self.subset_plan();plan['missingConditions']=['cost impact unknown']
        saved=self.tasks.dispatch('reproductions.save',dict(projectId=self.project['id'],plan=plan))
        self.assertEqual(saved['readiness']['runnableStepIds'],[])
        with self.assertRaisesRegex(ValueError,'全局缺失'):self.start(saved,selectedStepIds=['A'])
        self.assertEqual(self.jobs.calls,[])

    def test_declared_missing_is_not_a_blanket_validation_bypass(self):
        plan=self.subset_plan()
        bad=deepcopy(plan);bad['steps'][0]['spec']['parameters'].pop('endDate')
        with self.assertRaisesRegex(ValueError,'明确 startDate/endDate'):self.tasks.dispatch('reproductions.save',dict(projectId=self.project['id'],plan=bad))
        bad=deepcopy(plan);bad['steps'][1]['spec']['parameters']['startDate']='not-a-date'
        with self.assertRaisesRegex(ValueError,'步骤日期'):self.tasks.dispatch('reproductions.save',dict(projectId=self.project['id'],plan=bad))
        bad=deepcopy(plan);bad['steps'][1]['missingConditions']=['']
        with self.assertRaisesRegex(ValueError,'缺失条件'):self.tasks.dispatch('reproductions.save',dict(projectId=self.project['id'],plan=bad))
        incomplete=deepcopy(plan);incomplete['steps'][1]['spec']['parameters'].pop('factorIds')
        self.tasks.dispatch('reproductions.save',dict(projectId=self.project['id'],plan=incomplete))

    def test_distinct_subsets_share_budget_and_cannot_split_to_reset_trials(self):
        plan=self.plan();template=plan['steps'][0]
        template['spec']=dict(kind='optimize.run',parameters=dict(trials=12,target='backtest',sampler='grid',baseParameters={},searchSpace={'topN':[1,2]},startDate='2025-01-02',endDate='2025-02-01'))
        plan['steps']=[{**deepcopy(template),'id':key,'dependsOn':[]} for key in ['A','B']]
        plan=self.tasks.dispatch('reproductions.save',dict(projectId=self.project['id'],plan=plan))
        first=self.start(plan,selectedStepIds=['A']);replay=self.start(plan,selectedStepIds=['A'])
        self.assertEqual(first['runId'],replay['runId']);self.assertEqual(len(self.jobs.calls),1)
        second=self.start(plan,selectedStepIds=['B'])
        self.assertNotEqual(first['runId'],second['runId']);self.assertEqual(first['budgetId'],second['budgetId'])
        self.assertEqual(second['status'],'failed');self.assertEqual(second['budget']['planned']['trials'],12)
        self.assertEqual(second['budget']['reserved']['trials'],12)
        self.assertEqual(read_budget(self.store.project_store(self.project['id']).db,first['budgetId'])['used']['trials'],12)
        self.assertEqual(len(self.jobs.calls),1)
        with self.assertRaisesRegex(ValueError,'不能替换'):self.start(plan,selectedStepIds=['A'],budgetId='fresh-budget')

    def test_stale_running_parent_honors_retry_and_resume_keeps_frozen_subset(self):
        plan=self.subset_plan();run=self.start(plan,selectedStepIds=['A','D']);old=run['steps'][0]['jobId']
        job=self.store.get('job',old);job['status']='failed';self.store.put('job',job,self.project['id'])
        # Parent is still running until its next scheduler tick.
        self.assertEqual(self.store.get('reproduction_run',run['id'])['status'],'running')
        retried=self.start(plan,runId=run['id'],retryFailed=True)
        self.assertNotEqual(retried['steps'][0]['jobId'],old);self.assertEqual(retried['steps'][0]['attempt'],2)
        changed=deepcopy(plan);changed['steps'][0]['name']='edited live';changed['missingConditions']=['new global issue']
        self.tasks.dispatch('reproductions.save',dict(projectId=self.project['id'],plan=changed))
        same=self.tasks.dispatch('reproductions.run',dict(projectId=self.project['id'],planId=plan['id'],runId=run['id']))
        self.assertEqual(same['selectedStepIds'],['A','D']);self.assertEqual(same['revision'],plan['revision'])
        with self.assertRaisesRegex(ValueError,'冻结'):
            self.tasks.dispatch('reproductions.run',dict(projectId=self.project['id'],planId=plan['id'],runId=run['id'],selectedStepIds=['A']))

    def test_ai_tool_passes_explicit_selection_and_returns_scope(self):
        owner=object.__new__(Executions);value=dict(projectId=self.project['id'],projectSnapshots={self.project['id']+':':{}},budgetId='budget',steps=[],activeJobIds=[])
        owner.status=lambda params:value;owner.supplements=lambda *args:[]
        owner.mutate=lambda cid,eid,fn:fn({},value)
        def run(params,cid,eid):
            self.assertEqual(params['selectedStepIds'],['A'])
            return dict(runId='run',planId='plan',revision=1,status='completed',steps=[],message='selected done',selectedStepIds=['A'],excludedStepIds=['B'],executionScope='subset')
        owner.service=SimpleNamespace(report_tasks=SimpleNamespace(run_for_execution=run))
        result=asyncio.run(owner.run_reproduction('chat','execution','plan',selected_step_ids=['A']))
        self.assertEqual(result['executionScope'],'subset');self.assertEqual(result['excludedStepIds'],['B'])

    def test_stale_running_default_resume_does_not_retry_failed_child(self):
        plan=self.subset_plan();run=self.start(plan,selectedStepIds=['A','D']);old=run['steps'][0]['jobId']
        job=self.store.get('job',old);job['status']='failed';self.store.put('job',job,self.project['id'])
        resumed=self.start(plan,runId=run['id'])
        self.assertEqual(resumed['status'],'failed');self.assertEqual(resumed['steps'][0]['jobId'],old)
        self.assertEqual(len(self.jobs.calls),1)

    def test_openui_does_not_offer_run_all_for_local_missing(self):
        from v3_backend.research.report_ai import saved_plan_blocks
        plan=self.subset_plan()
        service=SimpleNamespace(store=self.store,report_tasks=self.tasks)
        step=dict(id='saved',tool='save_reproduction_plan',status='completed',planId=plan['id'],projectId=self.project['id'],planRevision=plan['revision'])
        blocks=saved_plan_blocks(service,[step],{self.project['id']})
        self.assertEqual(len(blocks),1)
        self.assertNotIn('保存参数并运行',blocks[0]['content'])
        self.assertIn('明确选择依赖闭合',blocks[0]['content'])

    def test_completed_subset_displays_current_shared_revision_budget(self):
        plan=self.plan();template=plan['steps'][0]
        template['spec']=dict(kind='optimize.run',parameters=dict(trials=6,target='backtest',sampler='grid',baseParameters={},searchSpace={'topN':[1,2]},startDate='2025-01-02',endDate='2025-02-01'))
        plan['steps']=[{**deepcopy(template),'id':key,'dependsOn':[]} for key in ['A','B']]
        plan=self.tasks.dispatch('reproductions.save',dict(projectId=self.project['id'],plan=plan))
        first=self.start(plan,selectedStepIds=['A']);self.finish(first)
        second=self.start(plan,selectedStepIds=['B'])
        view=self.tasks.dispatch('reproductions.status',dict(projectId=self.project['id'],runId=first['id']))
        self.assertEqual(view['status'],'completed');self.assertEqual(view['budget']['planned']['trials'],6)
        self.assertEqual(view['budget']['reserved']['trials'],12)
        self.assertEqual(view['budget']['shared']['used']['trials'],12)
        self.assertEqual(second['budgetId'],first['budgetId'])


class SubsetRestartTests(unittest.TestCase):
    from test_report_recovery import RecoveryTests as Fixture
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    quiet_scheduler=Fixture.quiet_scheduler
    restart=Fixture.restart

    def test_real_service_restart_and_retry_never_expand_frozen_subset(self):
        from unittest.mock import patch
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next'):
            first=self.service.report_tasks.dispatch('reproductions.run',{**self.params,'selectedStepIds':['a']})
        self.restart()
        params={**self.params,'runId':first['runId']}
        restored=self.service.report_tasks.dispatch('reproductions.run',params)
        self.assertEqual(restored['selectedStepIds'],['a']);self.assertEqual(restored['excludedStepIds'],['b'])
        self.assertEqual(restored['steps'][0]['status'],'interrupted')
        with patch('v3_backend.research.preparation.scope'),patch.object(self.service.jobs,'_start_next'):
            retried=self.service.report_tasks.dispatch('reproductions.run',{**params,'retryFailed':True})
        self.assertEqual(retried['selectedStepIds'],['a']);self.assertEqual(retried['executionScope'],'subset')
        self.assertEqual(len(retried['steps']),1);self.assertEqual(retried['steps'][0]['attempt'],2)
        self.assertEqual({j['spec']['reproduction']['stepId'] for j in self.service.store.list('job')},{'a'})
