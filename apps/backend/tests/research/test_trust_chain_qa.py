"""Independent phase-one acceptance examples. Synthetic temp data; no network/model.

Failures are unresolved acceptance conditions, not expected-failure passes.
"""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from v3_backend.research import accounting, candidates, data, history, portfolio
from v3_backend.research.server import Service
from v3_backend.research.storage import write_json


class TrustChainQA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = Service(self.root / 'app')
        self.store = self.service.store
        self.project = self.store.create_project(self.root / 'project', 'QA synthetic')

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def experiment(self, key='qa-result', frame=None):
        folder = Path(self.project['path']) / '.research/runs' / key
        folder.mkdir(parents=True, exist_ok=True)
        artifacts = []
        if frame is not None:
            target = folder / 'samples.parquet'
            frame.to_parquet(target, index=False, row_group_size=1000)
            artifacts.append(dict(name='samples', type='parquet', path=str(target)))
        value = dict(id=key, projectId=self.project['id'], kind='factor.analyze',
                     name=key, createdAt='2026-01-01', parameters={}, metrics={}, artifacts=artifacts)
        self.store.save_experiment(self.project['id'], value)
        return folder

    def test_shared_membership_does_not_replace_other_pool_or_all_market(self):
        a = self.project
        b = self.store.create_project(self.root / 'other', 'Other pool')
        for project, source in ((a, 'csi300'), (b, 'csi500')):
            project['settings']['dataPath'] = str(self.root / 'shared/data')
            project['universe']['source'] = source
        history.import_membership(a, pd.DataFrame([dict(symbol='600000', startDate='2020-01-01', endDate=None)]))
        history.import_membership(b, pd.DataFrame([dict(symbol='600001', startDate='2020-01-01', endDate=None)]))
        with self.subTest(scope='first pool'):
            self.assertEqual(history.members(a, '2020-01-02'), {'SH600000'})
        with self.subTest(scope='second pool'):
            self.assertEqual(history.members(b, '2020-01-02'), {'SH600001'})
        all_market = self.store.create_project(self.root / 'all-market', 'All market')
        all_market['settings']['dataPath'] = str(self.root / 'shared/data')
        all_market['universe']['source'] = 'all'
        with self.subTest(scope='all market'):
            self.assertIsNone(history.members(all_market, '2020-01-02'))

    def test_legacy_snapshot_cannot_silently_read_updated_prices(self):
        frame = pd.DataFrame([dict(symbol='SH600000', date=pd.Timestamp('2020-01-02'),
                                   open=10., high=10., low=10., close=10., volume=100.)])
        data.merge_table(self.project, frame, 'prices', return_all=False)
        folder = self.experiment()
        write_json(folder / 'project.json', self.project)
        data.merge_table(self.project, frame.assign(close=20., high=20.), 'prices', return_all=False)
        selected, _, warning = self.service.chart_source(dict(projectId=self.project['id'], experimentId='qa-result'))
        close = float(data.read_table(selected).iloc[0]['close'])
        self.assertTrue(close == 10. or bool(warning), f'legacy experiment silently reads changed close={close}')

    def test_preview_and_filtered_page_do_not_materialize_entire_table(self):
        frame = pd.DataFrame(dict(symbol=['SH600000'] * 10000 + ['SH600001'] * 10000,
                                  date=pd.date_range('2000-01-01', periods=10000).tolist() * 2,
                                  value=np.arange(20000)))
        self.experiment(frame=frame)
        original = pd.read_parquet
        for method in ('experiments.get', 'experiments.table'):
            materialized = []
            def read(*args, **kwargs):
                result = original(*args, **kwargs)
                materialized.append(len(result))
                return result
            with self.subTest(method=method), patch.object(pd, 'read_parquet', side_effect=read):
                result = self.service.request(method, dict(projectId=self.project['id'], experimentId='qa-result',
                    table='samples', symbol='SH600001', offset=2, limit=3))
                if method.endswith('.table'):
                    self.assertEqual(result['total'], 10000)
                    self.assertEqual([r['value'] for r in result['rows']], [10002, 10003, 10004])
                else:
                    self.assertLessEqual(len(result['tables'][0]['rows']), 500)
                self.assertFalse(any(n >= len(frame) for n in materialized), f'full pandas materialization: {materialized}')

    def test_exited_worker_registration_failure_releases_queue_slot(self):
        jobs = self.service.jobs
        job = dict(id='qa-exited', projectId=self.project['id'], kind='factor.analyze', name='QA',
                   status='running', progress=.9, spec={'parameters': {}}, createdAt='', updatedAt='')
        jobs._save(job)
        folder = self.experiment('qa-exited')
        write_json(folder / 'result.json', {'experiment': self.store.experiment(self.project['id'], 'qa-exited')})
        # Worker finished on disk; no experiment has been registered yet.
        self.store.project_store(self.project['id']).delete('experiment', 'qa-exited')
        child = Mock(returncode=0)
        child.wait.return_value = 0
        child.poll.return_value = 0
        jobs.processes[job['id']] = child
        caught = None
        try:
            with patch.object(self.store, 'save_experiment', side_effect=OSError('QA injected result registration failure')):
                try:
                    jobs._watch(job['id'], child, folder, io.BytesIO())
                except Exception as exc:
                    caught = str(exc)
            self.assertNotIn(job['id'], jobs.processes, f'exited child retained after failure: {caught}')
            self.assertNotEqual(self.store.get('job', job['id'])['status'], 'completed')
            self.assertTrue((folder / 'result.json').exists())
            with patch('v3_backend.research.jobs.subprocess.Popen', side_effect=AssertionError('recovery must not recompute')):
                jobs.recover_result(job['id'])
                jobs.recover_result(job['id'])
            self.assertEqual(self.store.get('job', job['id'])['status'], 'completed')
            self.assertEqual(len(self.store.experiments(self.project['id'])), 1)
        finally:
            jobs.processes.pop(job['id'], None)  # Only the fake owned process; allow isolated teardown.

    def test_repeated_recovery_preserves_user_experiment_metadata(self):
        key = 'qa-recovery-metadata'
        folder = self.experiment(key)
        original = self.store.experiment(self.project['id'], key)
        write_json(folder / 'result.json', {'experiment': original})
        write_json(folder / 'process-exit.json', {'cleanupConfirmed': True, 'returncode': 0})
        self.service.jobs._save(dict(id=key, projectId=self.project['id'], kind='factor.analyze',
            name='QA', status='failed', registrationPending=True, progress=.9,
            spec={'parameters': {}}, createdAt='', updatedAt=''))
        self.service.request('jobs.recoverResult', {'jobId': key})
        self.service.request('experiments.update', dict(projectId=self.project['id'],
            experimentId=key, name='User reviewed result', starred=True))
        with patch('v3_backend.research.jobs.subprocess.Popen', side_effect=AssertionError('must not recompute')):
            self.service.request('jobs.recoverResult', {'jobId': key})
        persisted = self.store.experiment(self.project['id'], key)
        self.assertEqual(persisted['name'], 'User reviewed result')
        self.assertTrue(persisted.get('starred'))

    def test_recovery_rejects_missing_result_artifact(self):
        key = 'qa-recovery-missing-artifact'
        folder = self.experiment(key, pd.DataFrame({'value': [1.0]}))
        original = self.store.experiment(self.project['id'], key)
        write_json(folder / 'result.json', {'experiment': original})
        write_json(folder / 'process-exit.json', {'cleanupConfirmed': True, 'returncode': 0})
        self.store.project_store(self.project['id']).delete('experiment', key)
        (folder / 'samples.parquet').unlink()
        self.service.jobs._save(dict(id=key, projectId=self.project['id'], kind='factor.analyze',
            name='QA', status='failed', registrationPending=True, progress=.9,
            spec={'parameters': {}}, createdAt='', updatedAt=''))
        with self.assertRaises(ValueError, msg='missing result artifact was registered as completed'):
            self.service.request('jobs.recoverResult', {'jobId': key})
        self.assertNotEqual(self.store.get('job', key)['status'], 'completed')
        self.assertEqual(self.store.experiments(self.project['id']), [])

    def test_replay_chain_protects_original_input_directory(self):
        from v3_backend.research import input_snapshot
        prices = pd.DataFrame([dict(symbol='SH600000', date=pd.Timestamp('2020-01-02'),
            open=10., high=10., low=10., close=10., volume=100.)])
        data.merge_table(self.project, prices, 'prices', return_all=False)
        original_folder = self.experiment('qa-chain-original')
        _, params, reference = input_snapshot.capture(self.store, self.project,
            {'factorIds': ['momentum20']}, original_folder, {})
        original = self.store.experiment(self.project['id'], 'qa-chain-original')
        self.store.save_experiment(self.project['id'], {**original, 'parameters': params, 'inputSnapshot': reference})
        for source, target in [('qa-chain-original', 'qa-chain-first'), ('qa-chain-first', 'qa-chain-second')]:
            _, frozen_params, ref = input_snapshot.restore(self.store, self.project, source)
            self.experiment(target)
            exp = self.store.experiment(self.project['id'], target)
            self.store.save_experiment(self.project['id'], {**exp, 'parameters': frozen_params, 'inputSnapshot': ref})
        for key in ['qa-chain-original', 'qa-chain-first']:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.service.request('experiments.delete', dict(projectId=self.project['id'], experimentId=key))
        frozen, _, _ = input_snapshot.restore(self.store, self.project, 'qa-chain-second')
        self.assertEqual(float(data.read_table(frozen).iloc[0]['close']), 10.)

    def test_referenced_candidate_result_cannot_be_deleted(self):
        folder = self.experiment()
        candidate = candidates.save(self.store, self.project['id'], dict(kind='factor', name='QA linked factor',
            spec=dict(kind='factor.analyze', parameters={'factorIds': ['momentum20']})))
        candidates.link_experiment(self.store, self.project['id'], candidate['id'], 'qa-result', 1)
        blocked = False
        try:
            result = self.service.request('experiments.delete', dict(projectId=self.project['id'], experimentId='qa-result'))
            blocked = result.get('deleted') is False
        except ValueError:
            blocked = True
        self.assertTrue(blocked and folder.exists(), 'referenced experiment was deleted')

    def test_restore_rejects_missing_captured_financial_input(self):
        from v3_backend.research import input_snapshot
        prices = pd.DataFrame([dict(symbol='SH600000', date=pd.Timestamp('2020-01-02'),
            open=10., high=10., low=10., close=10., volume=100.)])
        financial = pd.DataFrame([dict(symbol='SH600000', announcementDate=pd.Timestamp('2019-10-01'),
            reportDate=pd.Timestamp('2019-09-30'), roeAvg=.1)])
        data.merge_table(self.project, prices, 'prices', return_all=False)
        data.merge_table(self.project, financial, 'financials', return_all=False)
        folder = self.experiment('qa-incomplete')
        _, params, reference = input_snapshot.capture(self.store, self.project,
            {'factorIds': ['roe'], 'startDate': '2020-01-02', 'endDate': '2020-01-03'}, folder, {})
        experiment = self.store.experiment(self.project['id'], 'qa-incomplete')
        self.store.save_experiment(self.project['id'], {**experiment, 'parameters': params, 'inputSnapshot': reference})
        financial_inputs = list((folder / 'inputs/data').rglob('*.parquet'))
        financial_inputs = [path for path in financial_inputs if 'financials' in path.parts or path.name == 'financials.parquet']
        self.assertTrue(financial_inputs, 'fixture financial input was not captured')
        financial_inputs[0].unlink()
        with self.assertRaises(ValueError, msg='restore accepted missing financials despite available snapshot status'):
            input_snapshot.restore(self.store, self.project, 'qa-incomplete')

    def test_real_worker_replay_ignores_changed_live_prices(self):
        from v3_backend.research import input_snapshot, worker
        from test_engines import sample_project
        project, dates, store = sample_project(self.root / 'worker-fixture')
        folder = Path(project['path']) / '.research/runs/qa-original'
        params = {'factorIds': ['momentum20'], 'periods': [1, 5], 'quantiles': 3}
        _, frozen_params, reference = input_snapshot.capture(store, project, params, folder, {})
        store.save_experiment(project['id'], dict(id='qa-original', projectId=project['id'],
            kind='factor.analyze', name='Synthetic original inputs', createdAt='', metrics={}, artifacts=[],
            parameters=frozen_params, inputSnapshot=reference))
        job = dict(id='qa-replay', kind='factor.analyze', projectId=project['id'],
            spec={'inputExperimentId': 'qa-original', 'parameters': params})
        first = Path(project['path']) / '.research/runs/qa-replay-one'
        second = Path(project['path']) / '.research/runs/qa-replay-two'
        first.mkdir(parents=True); second.mkdir(parents=True)
        with patch('v3_backend.research.preparation.prepare', side_effect=AssertionError('original replay must not prepare live inputs')):
            result1 = worker.execute(store, job, project, first, lambda *_: None)
            live = data.read_table(project)
            live['close'] = live['close'].to_numpy()[::-1]
            live['open'] = live['close']; live['high'] = live['close'] * 1.02; live['low'] = live['close'] * .98
            data.merge_table(project, live, 'prices', return_all=False)
            result2 = worker.execute(store, job, project, second, lambda *_: None)
        self.assertTrue(result1['metrics'])
        self.assertEqual(result1['metrics'], result2['metrics'])
        for artifact in result1['artifacts']:
            if artifact['type'] != 'parquet':
                continue
            match = next(item for item in result2['artifacts'] if item['name'] == artifact['name'])
            with self.subTest(artifact=artifact['name']):
                pd.testing.assert_frame_equal(pd.read_parquet(artifact['path']), pd.read_parquet(match['path']))

    def test_optimizer_nested_model_prerequisite_is_frozen(self):
        from v3_backend.research import input_snapshot
        prices = pd.DataFrame([dict(symbol='SH600000', date=pd.Timestamp('2020-01-02'),
            open=10., high=10., low=10., close=10., volume=100.)])
        data.merge_table(self.project, prices, 'prices', return_all=False)
        self.experiment('qa-model', pd.DataFrame({'score': [.5]}))
        model = self.store.experiment(self.project['id'], 'qa-model')
        self.store.save_experiment(self.project['id'], {**model, 'kind': 'model.train'})
        folder = Path(self.project['path']) / '.research/runs/qa-optimizer'
        frozen, _, _ = input_snapshot.capture(self.store, self.project,
            {'target': 'backtest', 'baseParameters': {'template': 'model_score', 'modelExperimentId': 'qa-model'}}, folder, {})
        self.assertIn('qa-model', frozen['inputPrerequisites'], 'nested model used by optimizer remains live')

    def test_real_risk_contribution_survives_accounting_decision(self):
        dates = pd.bdate_range('2020-01-01', periods=180)
        rng = np.random.default_rng(812)
        rows = []
        for symbol, volatility in [('SH600000', .01), ('SH600001', .025)]:
            for date, close in zip(dates, 10 * np.cumprod(1 + rng.normal(0, volatility, len(dates)))):
                rows.append(dict(symbol=symbol, date=date, close=close, rawClose=close))
        prices = pd.DataFrame(rows)
        scores = pd.Series({'SH600000': 2., 'SH600001': 1.})
        config = {**portfolio.DEFAULTS, 'method': 'risk_parity'}
        captured = []
        original = portfolio.construct_portfolio
        def construct(*args, **kwargs):
            result = original(*args, **kwargs)
            captured.append(result)
            return result
        with patch.object(portfolio, 'construct_portfolio', side_effect=construct):
            decision = accounting.make_decision(self.project, {'topK': 2}, accounting.create(100000),
                dates[-1], prices, scores, None, 100000, config)
        self.assertTrue(captured[0]['executable'])
        self.assertTrue(captured[0]['riskContributions'].notna().all())
        expected = captured[0]['riskContributions'].sort_index()
        actual = pd.Series(decision['targetRiskContributions']).sort_index()
        np.testing.assert_allclose(actual, expected, atol=1e-10)
        self.assertEqual(decision['riskEstimate']['observations'], 179)
        self.assertLessEqual(pd.Timestamp(decision['riskEstimate']['sampleEnd']), dates[-1])
        scarce = accounting.make_decision(self.project, {'topK': 2}, accounting.create(100000),
            dates[10], prices, scores, None, 100000, {**config, 'method': 'equal'})
        self.assertEqual(scarce['riskEstimate']['status'], 'unavailable')
        self.assertTrue(pd.Series(scarce['targetRiskContributions']).isna().all())


if __name__ == '__main__':
    unittest.main()
