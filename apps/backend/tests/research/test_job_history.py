import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from v3_backend.research.jobs import Jobs
from v3_backend.research.storage import Store
from v3_backend.research.workbench import workspace, save_conversation
from v3_backend.research.ai import _stage_status, attached_experiments


class JobHistoryTest(unittest.TestCase):
    def test_clear_preserves_experiments_and_does_not_restore_on_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'app')
            project = store.create_project(Path(directory) / 'project', '研究')
            jobs = Jobs(store, lambda _: None)
            for key, status in [('finished', 'completed'), ('failed', 'failed'), ('active', 'running')]:
                jobs._save(dict(id=key, projectId=project['id'], strategyId='default', status=status,
                                kind='backtest.run', createdAt='2026-09-09', experimentId=key if key == 'finished' else None))
            store.save_experiment(project['id'], dict(id='finished', artifacts=[], createdAt='2026-09-09'))
            self.assertTrue(next(j for j in jobs.list() if j['id'] == 'finished')['resultAvailable'])
            result = jobs.clear({'jobIds': ['finished', 'failed', 'active']})
            self.assertEqual(result, {'removedIds': ['finished', 'failed'], 'skippedIds': ['active']})
            self.assertEqual(store.experiment(project['id'], 'finished')['id'], 'finished')
            store.open_project(project['path'])
            self.assertEqual([j['id'] for j in jobs.list()], ['active'])

    def test_paging_scope_deleted_results_and_finishing_process(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'app')
            first = store.create_project(Path(directory) / 'first', '一')
            second = store.create_project(Path(directory) / 'second', '二')
            jobs = Jobs(store, lambda _: None)
            for i in range(4):
                project = first if i < 3 else second
                jobs._save(dict(id=str(i), projectId=project['id'], strategyId='default', status='completed',
                                kind='factor.analyze', createdAt=f'2026-09-0{i + 1}', experimentId='deleted'))
            page = jobs.list({'projectId': first['id'], 'statuses': ['completed'], 'offset': 1, 'limit': 1})
            self.assertEqual([j['id'] for j in page], ['1'])
            self.assertFalse(page[0]['resultAvailable'])
            jobs.processes['2'] = object()
            result = jobs.clear({'projectId': first['id']})
            self.assertEqual(set(result['removedIds']), {'0', '1'})
            self.assertEqual(result['skippedIds'], ['2'])
            self.assertEqual({j['id'] for j in jobs.list()}, {'2', '3'})
            jobs.processes.clear()

    def test_workspace_keeps_each_conversations_reading_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            first = {'draft': '继续分析', 'scrollTop': 123, 'atBottom': False}
            workspace(store, {'sidebarVisible': False, 'rightPanel': 'parameters', 'conversationViews': {'first': first}})
            workspace(store, {'conversationViews': {'second': {'draft': '', 'scrollTop': 0, 'atBottom': True}}})
            saved = workspace(Store(directory))
            self.assertFalse(saved['sidebarVisible'])
            self.assertEqual(saved['rightPanel'], 'parameters')
            self.assertEqual(saved['conversationViews']['first'], first)

    def test_clear_keeps_stage_result_for_an_unopened_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'app')
            project = store.create_project(Path(directory) / 'project', '研究')
            jobs = Jobs(store, lambda _: None)
            conversation = dict(id='conversation', name='阶段', context=[], createdAt='2026-09-09',
                                state=dict(messages=[], phase='研究', proposals=[], stageJobIds=['job']))
            store.put('conversation', conversation)
            jobs._save(dict(id='job', projectId=project['id'], kind='backtest.run', status='completed',
                            createdAt='2026-09-09', experimentId='result'))
            store.save_experiment(project['id'], dict(id='result', projectId=project['id'], artifacts=[]))
            self.assertEqual(jobs.clear()['removedIds'], ['job'])
            # A stale client's draft save cannot erase the retained terminal event.
            save_conversation(store, {**conversation, 'state': {**conversation['state'], 'stageEvents': []}})
            service = SimpleNamespace(store=Store(store.root))
            stage = _stage_status(service, conversation_id='conversation')
            self.assertEqual(stage['jobs'][0]['status'], 'completed')
            self.assertEqual(stage['jobs'][0]['experimentId'], 'result')
            self.assertEqual(attached_experiments(service, [], conversation_id='conversation')[0]['id'], 'result')
            store.project_store(project['id']).delete('experiment', 'result')
            self.assertEqual(attached_experiments(service, [], conversation_id='conversation'), [])


if __name__ == '__main__':
    unittest.main()
