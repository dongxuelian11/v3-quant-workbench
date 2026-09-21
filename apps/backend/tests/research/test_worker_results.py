"""Bounded real subprocess result checks and failed-registration recovery."""
import io
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from test_engines import sample_project
from v3_backend.research import data, portfolio
from v3_backend.research.jobs import Jobs
from v3_backend.research.storage import read_json, write_json


class WorkerResults(unittest.TestCase):
    def test_public_submit_empty_parameters_replays_in_real_worker(self):
        from v3_backend.research import input_snapshot
        with tempfile.TemporaryDirectory() as temp:
            project, dates, store = sample_project(Path(temp))
            project['settings']['dataSources']={'daily':'file','financials':'file'}
            folder = Path(project['path']) / '.research/runs/original'
            params = dict(factorIds=['momentum20'], periods=[1], quantiles=3,
                          startDate=str(dates[25].date()), endDate=str(dates[-1].date()))
            _, saved, reference = input_snapshot.capture(store,project,params,folder,{'inputStart':str(dates[0].date())})
            store.save_experiment(project['id'], dict(id='original',projectId=project['id'],kind='factor.analyze',
                name='original',createdAt='',parameters=saved,metrics={},artifacts=[],inputSnapshot=reference))
            store.settings({'dataSources':{'daily':'akshare','financials':'baostock'}})
            jobs=Jobs(store,lambda _:None)
            try:
                job=jobs.submit(dict(projectId=project['id'],kind='factor.analyze',inputExperimentId='original',parameters={}))
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    job=store.get('job',job['id'])
                    if job['status'] in {'completed','failed'} and job['id'] not in jobs.processes: break
                    time.sleep(.05)
                self.assertEqual(job['status'],'completed',job.get('message'))
                self.assertEqual(job['spec']['parameters']['quantiles'],3)
                self.assertEqual(job['spec']['projectSnapshot']['settings']['dataSources']['daily'],'file')
                self.assertIn('/inputs',job['spec']['projectSnapshot']['inputDataRoot'].replace('\\','/'))
                experiment=store.experiment(project['id'],job['experimentId'])
                self.assertEqual(experiment['parameters']['quantiles'],3)
                self.assertTrue(experiment['metrics'])
                self.assertEqual(experiment['inputSnapshot']['sourceExperimentId'],'original')
                with self.assertRaisesRegex(ValueError,'任务类型'):
                    jobs.submit(dict(projectId=project['id'],kind='backtest.run',inputExperimentId='original',parameters={}))
            finally:
                jobs.close()

    def test_replay_rejects_kind_change_and_saves_executed_parameters(self):
        from v3_backend.research import worker
        with tempfile.TemporaryDirectory() as temp:
            project, _, store = sample_project(Path(temp))
            store.save_experiment(project['id'], dict(id='original', projectId=project['id'], kind='factor.analyze',
                name='original', createdAt='', parameters={}, artifacts=[]))
            job = dict(id='replayed', projectId=project['id'], kind='backtest.run', name='replay',
                       spec={'inputExperimentId':'original', 'parameters':{'quantiles':99}})
            with patch('v3_backend.research.input_snapshot.restore') as restore:
                with self.assertRaisesRegex(ValueError, '任务类型'):
                    worker.execute(store, job, project, Path(temp)/'out', lambda *_: None)
                restore.assert_not_called()
            job['kind'] = 'factor.analyze'
            original_params = {'factorIds':['momentum20'], 'quantiles':3}
            computed = {**original_params, 'labelMode':'next_open'}
            def calculate(s, received, p, out, progress):
                self.assertEqual(received['spec']['parameters'], original_params)
                return dict(metrics={}, artifacts=[], summary='test', parameters=computed)
            with patch('v3_backend.research.input_snapshot.restore', return_value=(project, original_params, {'status':'available'})), \
                 patch.object(worker, '_execute', side_effect=calculate):
                result = worker.execute(store, job, project, Path(temp)/'out', lambda *_: None)
            saved = worker.save_result(store, job, project, result, Path(project['path'])/'.research/runs/replayed')
            self.assertEqual(saved['parameters'], computed)
            self.assertEqual(job['spec']['parameters'], {'quantiles':99})

    def test_real_worker_persists_target_and_unfilled_actual_risk(self):
        with tempfile.TemporaryDirectory() as temp:
            project, dates, store = sample_project(Path(temp))
            project['universe'].update(symbols=['SH600000', 'SH600001'], excludeST=False, minListingDays=0)
            project = store.save_project(project)
            frame = data.read_table(project)
            frame['factor'] = 1.
            frame['rawClose'] = frame.close
            frame['rawOpen'] = frame.open
            frame['rawPreclose'] = frame.groupby('symbol').close.shift(1).fillna(frame.close)
            frame['tradestatus'] = '1'
            frame.loc[frame.symbol.eq('SH600001'), 'tradestatus'] = '0'
            data.merge_table(project, frame, 'prices')
            write_json(Path(data.project_data(project)['path']) / 'data/trading-calendar.json',
                       dict(start=str(dates[0].date()), end=str(dates[-1].date()), dates=[str(d.date()) for d in dates]))
            params = dict(template='multi_factor', factorIds=[], startDate=str(dates[35].date()), endDate=str(dates[44].date()),
                          capital=100000., rebalance='daily', portfolio=dict(method='equal', lookback=20, minObservations=10),
                          dailyCode="def decide(context):\n return {'targets': {'SH600000': .45, 'SH600001': .45}}")
            job = dict(id='risk-worker', projectId=project['id'], kind='backtest.run', name='Small synthetic risk check',
                       spec=dict(parameters=params, projectSnapshot=project), status='running')
            folder = Path(project['path']) / '.research/runs' / job['id']
            write_json(folder / 'request.json', dict(appData=str(store.root), job=job))
            env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2] / 'src')}
            python = os.environ.get('V3_TEST_PYTHON', 'D:/V3OpenSource/runtime/research-python/python.exe')
            completed = subprocess.run([python, '-X', 'utf8', '-m', 'v3_backend.research.worker', str(folder)],
                                       env=env, capture_output=True, text=True, encoding='utf8', timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stderr[-5000:])
            experiment = read_json(folder / 'result.json')['experiment']
            self.assertTrue(any(a['name'] == 'risk' for a in experiment['artifacts']))
            risk = pd.read_parquet(folder / 'risk.parquet')
            self.assertFalse(risk.empty)
            halted = risk[risk.symbol.eq('SH600001')]
            self.assertTrue(halted.targetWeight.eq(.45).all())
            self.assertTrue(halted.actualWeight.eq(0).all())
            self.assertTrue(halted.actualRiskContribution.eq(0).all())
            self.assertTrue(halted.targetRiskContribution.gt(0).all())
            self.assertTrue((pd.to_datetime(risk.sampleEnd) <= pd.to_datetime(risk.signalDate)).all())
            self.assertTrue((pd.to_datetime(risk.signalDate) < pd.to_datetime(risk.date)).all())
            self.assertTrue((risk.actualObservations >= 10).all())
            expected_returns = frame[frame.symbol.isin(project['universe']['symbols'])].pivot(index='date', columns='symbol', values='close').pct_change(fill_method=None)
            for _, rows in risk.groupby('date'):
                prior = pd.Timestamp(rows.signalDate.iloc[0])
                expected, _ = portfolio.risk_estimate(expected_returns.loc[:prior], rows.set_index('symbol').targetWeight, params['portfolio'])
                np.testing.assert_allclose(rows.set_index('symbol').targetRiskContribution.sort_index(), expected.sort_index(), atol=1e-10)
            self.assertTrue((folder / 'unfilled.parquet').is_file())

    def test_registration_failure_restart_and_corrupt_result(self):
        with tempfile.TemporaryDirectory() as temp:
            project, _, store = sample_project(Path(temp))
            jobs = Jobs(store, lambda _: None)
            key = 'registration-check'
            folder = Path(project['path']) / '.research/runs' / key
            job = dict(id=key, projectId=project['id'], kind='factor.analyze', name='test', status='running', progress=.9)
            jobs._save(job)
            result = dict(id=key, projectId=project['id'], kind='factor.analyze', name='test', artifacts=[], createdAt='')
            write_json(folder / 'result.json', {'experiment': result})
            write_json(folder / 'request.json', {'job': job})
            child = Mock(returncode=0)
            child.wait.return_value = 0
            jobs.processes[key] = child
            with patch.object(store, 'put', side_effect=OSError('database read-only')), patch.object(jobs, '_start_next'):
                jobs._watch(key, child, folder, io.BytesIO())
            self.assertNotIn(key, jobs.processes)
            self.assertEqual(store.get('job', key)['status'], 'running')
            restarted = Jobs(store, lambda _: None)
            self.assertTrue(store.get('job', key)['registrationPending'])
            with patch('v3_backend.research.jobs.subprocess.Popen', side_effect=AssertionError('must not recompute')):
                done = restarted.recover_result(key)
                self.assertEqual(done['status'], 'completed')
                restarted.recover_result(key)
            self.assertEqual(len(store.experiments(project['id'])), 1)
            write_json(folder / 'result.json', {'experiment': {**result, 'id': 'wrong-job'}})
            with self.assertRaisesRegex(ValueError, '不一致'):
                restarted.recover_result(key)
            self.assertEqual(len(store.experiments(project['id'])), 1)
            write_json(folder / 'process-exit.json', dict(returncode=0, cleanupConfirmed=False))
            with self.assertRaisesRegex(ValueError, '退出确认'):
                restarted.recover_result(key)
