import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from v3_backend.research.storage import Store, write_json
from v3_backend.research import workbench


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = Store(self.root / 'app')
        self.project = self.store.create_project(self.root / 'project', '研究')
        self.service = SimpleNamespace(store=self.store)

    def tearDown(self):
        self.directory.cleanup()

    def call(self, method, **params):
        handled, result = workbench.dispatch(self.service, method, params)
        self.assertTrue(handled)
        return result

    def test_draft_activation_and_budget_are_independent(self):
        key = self.project['id']
        a = self.call('strategies.create', projectId=key, name='方案 A')
        b = self.call('strategies.create', projectId=key, name='方案 B')
        a['settings']['backtest'] = {'topN': 10}
        a = self.call('strategies.save', projectId=key, strategy=a)
        self.call('strategies.activate', projectId=key, strategyId=a['id'], enabled=True, allocation=.6)
        frozen = workbench.strategy_project(self.store, key, a['id'], active=True)
        a['settings']['backtest']['topN'] = 20
        a['enabled'] = False  # stale autosave payload from before activation
        a = self.call('strategies.save', projectId=key, strategy=a)
        self.assertTrue(a['enabled'])
        self.assertEqual(a['active']['settings']['backtest']['topN'], 10)
        self.assertEqual(frozen['settings']['backtest']['topN'], 10)
        self.assertEqual(workbench.strategy_project(self.store, key, a['id'])['settings']['backtest']['topN'], 20)
        self.assertNotIn('backtest', workbench.get_strategy(self.store, key, b['id'])['settings'])
        a = self.call('strategies.activate', projectId=key, strategyId=a['id'], allocation=.3)
        self.assertEqual(a['active']['settings']['backtest']['topN'], 10)
        self.assertEqual(a['allocation'], .3)
        a = self.call('strategies.activate', projectId=key, strategyId=a['id'])
        self.assertEqual(a['active']['settings']['backtest']['topN'], 20)

    def test_legacy_files_preserved_and_deleted_objects_do_not_reappear(self):
        project_file = self.root / 'project' / 'project.json'
        original = project_file.read_bytes()
        values = self.call('strategies.list', projectId=self.project['id'])
        self.assertEqual(values[0]['id'], 'default')
        self.assertEqual(project_file.read_bytes(), original)
        self.call('strategies.delete', projectId=self.project['id'], strategyId='default')
        self.assertEqual(self.call('strategies.list', projectId=self.project['id']), [])
        history = self.root / 'project' / 'ai' / 'conversation.json'
        write_json(history, {'messages': [{'role': 'user', 'content': '历史研究内容'}]})
        original_history = history.read_bytes()
        conversation = self.call('ai.conversations.list')[0]
        self.call('ai.conversations.delete', conversationId=conversation['id'])
        self.assertEqual(self.call('ai.conversations.list'), [])
        self.assertEqual(history.read_bytes(), original_history)

    def test_global_conversations_and_workspace_preserve_other_objects(self):
        a = self.call('ai.conversations.create', name='趋势', context=[{'kind': 'stock', 'symbol': 'SH600000'}])
        b = self.call('ai.conversations.create', name='估值', context=[])
        self.call('ai.conversations.save', conversation={'id': a['id'], 'state': {'phase': '检查因子', 'messages': [{'role': 'user', 'content': '盈利水平'}]}})
        changed = self.call('ai.conversations.save', conversation={'id': a['id'], 'name': '趋势改名'})
        self.assertEqual(changed['context'], a['context'])
        self.assertEqual(changed['state']['phase'], '检查因子')
        self.assertEqual(self.call('ai.conversations.get', conversationId=b['id'])['state']['messages'], [])
        self.assertEqual(len(self.call('ai.conversations.list', search='盈利')), 1)
        self.call('workspace.save', state={'theme': 'dark', 'tablePreferences': {'market': {'order': ['symbol', 'name']}}})
        result = self.call('workspace.save', state={'density': 'compact', 'tablePreferences': {'holdings': {'width': 120}}})
        self.assertEqual(result['theme'], 'dark')
        self.assertIn('market', result['tablePreferences'])
        self.assertIn('holdings', result['tablePreferences'])


if __name__ == '__main__':
    unittest.main()
