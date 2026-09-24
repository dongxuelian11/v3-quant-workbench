import unittest
from test_reports import ReportsTests
from v3_backend.research.report_ai import safe_step_message

class FailureMessageTests(unittest.TestCase):
    setUp=ReportsTests.setUp
    tearDown=ReportsTests.tearDown
    plan=ReportsTests.plan

    def test_child_reason_survives_retry_history_and_readback(self):
        plan=self.plan();params=dict(projectId=self.project['id'],planId=plan['id'])
        run=self.tasks.dispatch('reproductions.run',params)
        first=run['steps'][0]['jobId']
        job=self.store.get('job',first);job.update(status='failed',message='请选择有效因子');self.store.put('job',job,self.project['id'])
        other=self.store.get('job',run['steps'][2]['jobId']);other.update(status='completed',message='已完成');self.store.put('job',other,self.project['id'])
        self.tasks._advance(run)
        self.assertEqual(run['steps'][0]['message'],'请选择有效因子')
        self.assertEqual(run['steps'][1]['message'],'前置步骤未成功，未提交计算')
        retry=self.tasks.dispatch('reproductions.run',{**params,'runId':run['id'],'retryFailed':True})
        self.assertEqual(retry['steps'][0]['attemptHistory'][0]['message'],'请选择有效因子')
        view=self.tasks.dispatch('reproductions.status',{**params,'runId':run['id']})
        self.assertEqual(view['steps'][0]['attemptHistory'][0]['message'],'请选择有效因子')
        self.assertEqual(view['steps'][0]['message'],'等待执行')

    def test_raw_child_payload_and_existing_history_are_never_exposed(self):
        plan=self.plan();params=dict(projectId=self.project['id'],planId=plan['id'])
        run=self.tasks.dispatch('reproductions.run',params)
        self.assertEqual(safe_step_message('', 'pending'),'等待前置步骤')
        secret='example-private-key'
        payload='Traceback (most recent call last): '+secret+' C:\\private\\research.py /home/private/research.py Authorization: Bearer '+secret
        job=self.store.get('job',run['steps'][0]['jobId']);job.update(status='failed',message=payload);self.store.put('job',job,self.project['id'])
        self.tasks._advance(run)
        self.assertEqual(run['steps'][0]['message'],'任务失败，详细错误保留在本地任务记录中')
        run['steps'][0]['attemptHistory']=[dict(stepId='a',status='failed',message=payload,attempt=0)]
        self.store.put('reproduction_run',run,self.project['id'])
        view=self.tasks.dispatch('reproductions.status',{**params,'runId':run['id']})
        for state in [view['steps'][0],view['steps'][0]['attemptHistory'][0]]:
            self.assertNotIn(secret,state['message']);self.assertNotIn('private',state['message']);self.assertNotIn('Traceback',state['message'])
        self.assertEqual(safe_step_message('[Errno 2] missing C:/private/input.parquet '+secret),'所需本地文件不存在，请核对输入文件')
        self.assertEqual(safe_step_message('所有因子均不可分析: '+payload),'所有因子均不可分析，请检查所需字段和样本区间')
