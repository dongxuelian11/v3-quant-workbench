import tempfile
import unittest
from copy import deepcopy
from v3_backend.research.storage import Store
from v3_backend.research.reminders import Reminders, evaluate_observation


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.api = Reminders(self.store)

    def create(self, request_id='create'):
        scope = self.api.preview({'symbol': '600000'})
        params = dict(requestId=request_id, name='价格提醒', snapshotId=scope['id'], condition=dict(operator='gte', threshold=10))
        return self.api.create(params), params

    def test_snapshot_survives_watchlist_changes_and_restart(self):
        self.store.put('watchlist', dict(id='w', name='自选', updatedAt='old', symbols=['600000', 'SH600000', '000001']))
        scope = self.api.preview({'watchlistId': 'w'})
        self.store.put('watchlist', dict(id='w', name='已改名', updatedAt='new', symbols=['300001']))
        rule = self.api.create(dict(requestId='r', name='固定范围', snapshotId=scope['id'], condition=dict(operator='lte', threshold=20)))
        self.assertEqual(rule['scope']['symbols'], ['SH600000', 'SZ000001'])
        self.assertEqual(rule['scope']['sourceWatchlist'], dict(id='w', name='自选', updatedAt='old'))
        self.assertIsNotNone(rule['scope']['confirmedAt'])
        restarted = Reminders(Store(self.temp.name))
        self.assertEqual(restarted.dispatch('reminders.get', {'ruleId':rule['id']}), rule)
        self.assertNotEqual(restarted.runtime()['sessionId'], self.api.runtime()['sessionId'])
        self.assertFalse(restarted.runtime()['running'])
        self.assertIn('没有监控', restarted.runtime()['message'])

    def test_create_and_check_idempotency(self):
        rule, params = self.create()
        self.assertEqual(self.api.create(params), rule)
        with self.assertRaisesRegex(ValueError, '不同提醒意图'):
            self.api.create({**params, 'name':'另一个'})
        check = self.api.check(dict(ruleId=rule['id'], requestId='c'))
        self.assertEqual(self.api.check(dict(ruleId=rule['id'], requestId='c')), check)
        self.assertEqual(self.api.history({'ruleId':rule['id']})['total'], 1)
        row = check['rows'][0]
        self.assertEqual(row['result'], 'unknown')
        self.assertEqual(row['reasonCodes'], ['mode_pending', 'source_unavailable'])
        self.assertIsNone(row['observation']['price'])
        self.assertIsNone(row['observation']['fetchedAt'])
        self.assertFalse(row['notified'])
        other, _ = self.create('other')
        with self.assertRaisesRegex(ValueError, '不同提醒'):
            self.api.check(dict(ruleId=other['id'], requestId='c'))

    def test_versions_soft_delete_and_history_pagination(self):
        rule, _ = self.create()
        for i in range(3): self.api.check(dict(ruleId=rule['id'], requestId=str(i)))
        paused = self.api.update(dict(ruleId=rule['id'], expectedVersion=1, status='paused'))
        self.assertEqual(paused['version'], 2)
        with self.assertRaisesRegex(ValueError, '版本冲突'):
            self.api.update(dict(ruleId=rule['id'], expectedVersion=1, name='过期修改'))
        deleted = self.api.update(dict(ruleId=rule['id'], expectedVersion=2), delete=True)
        self.assertEqual(deleted['status'], 'deleted')
        self.assertEqual(self.api.dispatch('reminders.list', {}), [])
        self.assertEqual(self.api.dispatch('reminders.list', {'includeDeleted': True})[0]['id'], rule['id'])
        page = self.api.history(dict(ruleId=rule['id'], offset=1, limit=1))
        self.assertEqual((page['total'], len(page['items'])), (3, 1))
        self.assertEqual(page['items'][0]['ruleVersion'], 1)
        with self.assertRaisesRegex(ValueError, '已删除'):
            self.api.check(dict(ruleId=rule['id'], requestId='new'))

    def test_reject_enable_fake_observation_and_bad_scopes(self):
        rule, _ = self.create()
        with self.assertRaisesRegex(ValueError, '不能启用'):
            self.api.update(dict(ruleId=rule['id'], expectedVersion=1, status='enabled'))
        with self.assertRaisesRegex(ValueError, '不能提交外部观察'):
            self.api.check(dict(ruleId=rule['id'], requestId='fake', observation={'price':11}))
        for symbol in ['SH000001', '511000', 'garbage', 'BJ920001', '920001']:
            with self.assertRaises(ValueError): self.api.preview({'symbol':symbol})
        for threshold in [True, float('inf'), 0]:
            with self.assertRaises(ValueError):
                self.api.update(dict(ruleId=rule['id'], expectedVersion=1, condition=dict(operator='gte',threshold=threshold)))

    def test_invalid_stale_and_unknown_do_not_rearm(self):
        condition = dict(operator='gte', threshold=10)
        clock = '2026-09-24T02:00:10+00:00'
        observation = dict(id='a', symbol='SH600000', kind='minute_close', price=11, priceBasis='raw',
                           source={'provider':'test','endpoint':'test'}, sourceTime='2026-09-24T02:00:00+00:00', validity='valid', reasonCodes=[])
        def evaluate(obs, state):
            return evaluate_observation(condition, obs, state, checked_at=clock, max_age_seconds=60)
        result, state, _ = evaluate(observation, {})
        self.assertEqual(result, 'triggered')
        for changes in [dict(price=float('inf')), dict(validity='unknown'), dict(sourceTime='2026-09-23T02:00:00+00:00'), dict(sourceTime=None), dict(price=0)]:
            outcome, unchanged, _ = evaluate({**observation, **changes, 'id':'bad'}, state)
            self.assertEqual(outcome, 'unknown')
            self.assertEqual(unchanged, state)
        self.assertEqual(evaluate(observation, state)[0], 'not_triggered')
        newer = {**observation, 'id':'b', 'sourceTime':'2026-09-24T02:00:01+00:00'}
        result, state, _ = evaluate(newer, state)
        self.assertEqual(result, 'not_triggered')
        result, state, _ = evaluate({**newer, 'id':'c','sourceTime':'2026-09-24T02:00:02+00:00','price':9}, state)
        self.assertFalse(state['satisfied'])
        result, state, _ = evaluate({**newer, 'id':'d','sourceTime':'2026-09-24T02:00:03+00:00'}, state)
        self.assertEqual(result, 'triggered')

    def test_price_modes_persist_and_conflicting_retry_is_rejected(self):
        _, params = self.create()
        for mode in ('intraday', 'daily_close'):
            intent = {**params, 'requestId': mode, 'priceMode': mode}
            rule = self.api.create(intent)
            self.assertEqual(Reminders(Store(self.temp.name)).dispatch('reminders.get', {'ruleId': rule['id']})['priceMode'], mode)
            self.assertEqual(self.api.create(intent), rule)
            with self.assertRaisesRegex(ValueError, '不同提醒意图'):
                self.api.create({**intent, 'priceMode': 'daily_close' if mode == 'intraday' else 'intraday'})
            check = self.api.check(dict(ruleId=rule['id'], requestId=mode))
            self.assertEqual(check['rows'][0]['reasonCodes'], ['source_unavailable'])
            self.assertFalse(check['rows'][0]['notified'])

    def test_service_routes_and_migration_pause(self):
        from v3_backend.research.server import Service
        service = Service(self.temp.name)
        self.addCleanup(service.close)
        service.migrations.pause.set()
        scope = service.request('reminders.scope.preview', {'symbol':'600000'})
        rule = service.request('reminders.create', dict(requestId='r', name='草稿', snapshotId=scope['id'], condition=dict(operator='gte',threshold=10)))
        self.assertEqual(service.request('reminders.get', {'ruleId':rule['id']})['version'], 1)
        service.request('reminders.update', dict(ruleId=rule['id'], expectedVersion=1, status='paused'))
        self.assertEqual(service.request('reminders.history', {'ruleId':rule['id']})['total'], 0)
        self.assertFalse(service.request('reminders.runtime', {})['running'])
        with self.assertRaisesRegex(ValueError, '迁移期间'):
            service.request('reminders.check', dict(ruleId=rule['id'], requestId='check'))
        service.migrations.pause.clear()
        self.assertEqual(service.request('reminders.check', dict(ruleId=rule['id'], requestId='check'))['rows'][0]['result'], 'unknown')


if __name__ == '__main__':
    unittest.main()
