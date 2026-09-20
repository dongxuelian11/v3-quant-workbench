import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from v3_backend.research.server import Service


class CandidateTest(unittest.TestCase):
    def test_switching_model_removes_old_hyperparameter_without_overwriting_active(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Path(directory) / 'app')
            try:
                project = service.store.create_project(Path(directory) / 'project', '模型切换')
                strategy = service.request('strategies.create', {'projectId': project['id'], 'name': '研究'})
                service.request('strategies.save', {'projectId': project['id'], 'strategy': {'id': strategy['id']},
                    'settingsPatch': {'model': {'model': 'ridge', 'hyperparameters': {'alpha': 1}, 'labelHorizon': 5}}})
                active = service.request('strategies.activate', {'projectId': project['id'], 'strategyId': strategy['id'], 'enabled': True, 'allocation': .5})
                updated = service.request('strategies.save', {'projectId': project['id'], 'strategy': {'id': strategy['id']},
                    'settingsPatch': {'model': {'model': 'lightgbm', 'hyperparameters': {'alpha': None, 'learning_rate': .1, 'n_estimators': 100}},
                                      'backtest': {'portfolio': {'maxWeight': None}}}})
                self.assertNotIn('alpha', updated['settings']['model']['hyperparameters'])
                self.assertIn('maxWeight', updated['settings']['backtest']['portfolio'])
                self.assertIsNone(updated['settings']['backtest']['portfolio']['maxWeight'])
                self.assertEqual(updated['settings']['model']['labelHorizon'], 5)
                self.assertEqual(updated['active'], active['active'])
            finally:
                service.close()

    def test_editing_generated_code_preserves_source_results_and_active_strategy(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Path(directory) / 'app')
            try:
                project = service.store.create_project(Path(directory) / 'project', '源码研究')
                strategy = service.request('strategies.create', {'projectId': project['id'], 'name': '策略'})
                original = Path(project['path']) / 'native_factor.py'
                original.write_text('value = 1\n', encoding='utf-8')
                candidate = service.request('candidates.save', {'projectId': project['id'], 'candidate': {
                    'strategyId': strategy['id'], 'kind': 'factor', 'name': '原生因子',
                    'spec': {'kind': 'factor.analyze', 'parameters': {'factorIds': ['native'], 'customFactors': [
                        {'id': 'native', 'name': '真实源码', 'source': 'parquet', 'dataPath': 'native.parquet', 'codePath': 'native_factor.py'}]}}}})
                from v3_backend.research.candidates import link_experiment
                link_experiment(service.store, project['id'], candidate['id'], 'first-evaluation', 1)
                request = {'projectId': project['id'], 'candidateId': candidate['id'], 'factorId': 'native'}
                source = service.request('candidates.code.get', request)
                self.assertEqual(source['content'], 'value = 1\n')
                with self.assertRaisesRegex(ValueError, '语法错误'):
                    service.request('candidates.code.save', {**request, 'content': 'def broken(:\n'})
                self.assertEqual(service.request('candidates.get', request)['revision'], 1)
                saved = service.request('candidates.code.save', {**request, 'content': 'value = 2\n'})
                self.assertEqual(saved['candidate']['revision'], 2)
                self.assertNotEqual(saved['code']['path'], 'native_factor.py')
                self.assertEqual(original.read_text(encoding='utf-8'), 'value = 1\n')
                self.assertEqual(saved['candidate']['experiments'][0]['revision'], 1)
                self.assertEqual(service.request('strategies.list', {'projectId': project['id']})[0], strategy)
                repeated = service.request('candidates.code.save', {**request, 'content': 'value = 2\n'})
                self.assertEqual(repeated['candidate']['revision'], 2)
                self.assertEqual(repeated['code']['path'], saved['code']['path'])
            finally:
                service.close()

    def test_adoption_changes_only_draft_and_each_revision_keeps_its_results(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Path(directory) / 'app')
            try:
                project = service.store.create_project(Path(directory) / 'project', '研究')
                strategy = service.request('strategies.create', {'projectId': project['id'], 'name': '策略'})
                service.request('strategies.save', {'projectId': project['id'], 'strategy': {'id': strategy['id']}, 'settingsPatch': {
                    'selectedFactors': ['momentum20'], 'backtest': {'topN': 3, 'costs': {'minCommission': 8, 'slippage': .002}}}})
                active = service.request('strategies.activate', {'projectId': project['id'], 'strategyId': strategy['id'], 'enabled': True, 'allocation': .5})
                candidate = service.request('candidates.save', {'projectId': project['id'], 'candidate': {
                    'strategyId': strategy['id'], 'kind': 'strategy', 'name': '减少持仓',
                    'spec': {'kind': 'backtest.run', 'parameters': {'template': 'single_factor', 'topN': 2}}}})
                self.assertEqual(candidate['spec']['parameters']['costs']['minCommission'], 8)
                self.assertEqual(candidate['spec']['parameters']['factorIds'], ['momentum20'])
                unchanged = service.request('strategies.list', {'projectId': project['id']})
                self.assertEqual(next(s for s in unchanged if s['id'] == strategy['id'])['settings']['backtest']['topN'], 3)
                adopted = service.request('candidates.adopt', {'projectId': project['id'], 'candidateId': candidate['id']})['strategy']
                self.assertEqual(adopted['settings']['backtest']['topN'], 2)
                self.assertEqual(adopted['active'], active['active'])
                self.assertTrue(adopted['enabled'])
                self.assertEqual(adopted['allocation'], .5)
                from v3_backend.research.candidates import link_experiment
                link_experiment(service.store, project['id'], candidate['id'], 'old-result', candidate['revision'])
                changed = deepcopy(candidate)
                changed['spec']['parameters']['topN'] = 4
                saved = service.request('candidates.save', {'projectId': project['id'], 'candidate': changed})
                self.assertEqual(saved['revision'], 2)
                self.assertEqual(saved['experiments'][0]['revision'], 1)
                with patch.object(service.jobs, '_start_next'):
                    with self.assertRaisesRegex(ValueError, '候选已经变更'):
                        service.jobs.submit({**candidate['spec'], 'candidateId': candidate['id']})
                    job = service.jobs.submit({**saved['spec'], 'candidateId': saved['id']})
                    self.assertEqual(job['spec']['candidateSnapshot']['revision'], 2)
                service.jobs.cancel(job['id'])
            finally:
                service.close()


if __name__ == '__main__':
    unittest.main()
