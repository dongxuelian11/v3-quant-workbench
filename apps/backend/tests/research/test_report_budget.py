from copy import deepcopy
import unittest
import test_reports


class ReportBudgetTests(unittest.TestCase):
    setUp = test_reports.ReportsTests.setUp
    tearDown = test_reports.ReportsTests.tearDown
    plan = test_reports.ReportsTests.plan
    # Use the existing real storage/scheduler fixture, not its unrelated cases.
    def test_trial_budget_counts_failed_jobs_when_resuming(self):
        plan = self.plan()
        step = deepcopy(plan['steps'][0])
        step['spec'] = {'kind': 'optimize.run', 'parameters': {
            'trials': 12, 'target': 'backtest', 'sampler':'grid','baseParameters':{},'searchSpace': {'topN': [2, 3]},
            'startDate': '2025-07-01', 'endDate': '2025-12-31'}}
        plan['steps'] = [step]
        plan = self.tasks.dispatch('reproductions.save', {'projectId': self.project['id'], 'plan': plan})
        params = {'projectId': self.project['id'], 'planId': plan['id']}
        run = self.tasks.dispatch('reproductions.run', params)
        self.assertEqual(run['budget']['reserved']['trials'], 12)
        job = self.store.get('job', run['steps'][0]['jobId'])
        job['status'] = 'failed'
        self.store.put('job', job, self.project['id'])
        self.tasks._advance(run)
        resumed = self.tasks.dispatch('reproductions.run', {**params, 'runId': run['id']})
        self.assertEqual(len(self.jobs.calls), 1)
        self.assertEqual(resumed['status'], 'failed')
        self.assertIn('预算', resumed['steps'][0]['message'])
        self.assertEqual(resumed['budget']['reserved']['trials'], 12)

    def test_whole_plan_over_limit_submits_nothing(self):
        plan = self.plan()
        for step in plan['steps']:
            step['spec'] = {'kind': 'optimize.run', 'parameters': {'trials': 8,'target':'backtest','sampler':'grid','baseParameters':{},'searchSpace':{'topN':[2,3]},
                'startDate': '2025-07-01', 'endDate': '2025-12-31'}}
        plan = self.tasks.dispatch('reproductions.save', {'projectId': self.project['id'], 'plan': plan})
        self.assertEqual(plan['plannedWork']['trials'], 24)
        with self.assertRaisesRegex(ValueError, '20'):
            self.tasks.dispatch('reproductions.run', {'projectId': self.project['id'], 'planId': plan['id']})
        self.assertEqual(self.jobs.calls, [])
