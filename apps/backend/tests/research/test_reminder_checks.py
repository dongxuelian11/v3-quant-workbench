import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from v3_backend.research.storage import Store
from v3_backend.research.reminders import Reminders
from v3_backend.research import reminder_source as source


class ReminderChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.api = Reminders(self.store)
        self.addCleanup(self.api.close)
        self.counter = 0
        self.observed_counter = 0
        self.clock = datetime.fromisoformat('2026-09-24T10:00:00+08:00')
        self.observed_base = self.clock - timedelta(seconds=10)
        clock_patch = patch('v3_backend.research.reminders.now', return_value=self.clock.isoformat())
        clock_patch.start()
        self.addCleanup(clock_patch.stop)

    def rule(self, mode='intraday'):
        scope = self.api.preview({'symbol':'600000'})
        return self.api.create(dict(requestId=str(time.monotonic_ns()), name='test', snapshotId=scope['id'],
                                    condition=dict(operator='gte', threshold=10), priceMode=mode))

    def obs(self, price=11, mode='intraday', seconds=0):
        self.observed_counter += 1
        clock = self.observed_base + timedelta(milliseconds=self.observed_counter) - timedelta(seconds=seconds)
        value = dict(id='observation-'+str(self.observed_counter), symbol='SH600000', kind='daily_close' if mode=='daily_close' else 'minute_close',
                    price=price, priceBasis='raw', source={'provider':'test','endpoint':'test'},
                    sourceTime=None if mode=='daily_close' else clock.isoformat(), sourceTradeDate=clock.date().isoformat(),
                    fetchedAt=clock.isoformat(), validity='valid', reasonCodes=[])
        if mode == 'daily_close':
            # A prior completed session on a declared non-trading test day.
            from zoneinfo import ZoneInfo
            today = self.clock.date()
            day = (today - timedelta(days=1)).isoformat()
            value['sourceTradeDate'] = day
            value['_calendar'] = dict(start=day, end=today.isoformat(), dates=[day])
        else:
            day = self.clock.date().isoformat()
            value['_calendar'] = dict(start=day, end=day, dates=[day])
        return value

    def check(self, rule):
        self.counter += 1
        return self.api.check(dict(ruleId=rule['id'], requestId=str(self.counter)))

    def test_both_modes_and_persisted_reentry_restart(self):
        for mode in ('intraday','daily_close'):
            rule = self.rule(mode)
            value = self.obs(mode=mode)
            self.api.observe = lambda *args: dict(value)
            self.assertEqual(self.check(rule)['rows'][0]['result'], 'triggered')
            self.assertEqual(self.check(rule)['rows'][0]['result'], 'not_triggered')
            self.api.close()
            self.api = Reminders(self.store)
            self.addCleanup(self.api.close)
            self.api.observe = lambda *args: dict(value)
            self.assertEqual(self.check(rule)['rows'][0]['result'], 'not_triggered')
        rule = self.rule()
        self.api.observe = lambda *args: self.obs()
        self.assertEqual(self.check(rule)['rows'][0]['result'], 'triggered')
        self.api.observe = lambda *args: source.unknown('SH600000','intraday','source_error')
        self.assertEqual(self.check(rule)['rows'][0]['result'], 'unknown')
        self.api.observe = lambda *args: self.obs()
        self.assertEqual(self.check(rule)['rows'][0]['result'], 'not_triggered')
        self.api.observe = lambda *args: self.obs(9)
        self.assertEqual(self.check(rule)['rows'][0]['result'], 'not_triggered')
        self.api.observe = lambda *args: self.obs()
        self.assertEqual(self.check(rule)['rows'][0]['result'], 'triggered')

    def test_stale_invalid_and_new_condition_version(self):
        rule = self.rule()
        for value in (self.obs(seconds=181), self.obs(float('nan'))):
            # Invalid source values must not be stored as JSON NaN.
            if value['price'] != value['price']:
                value = source.observation('SH600000','intraday', {'date':datetime.now(timezone.utc).isoformat(),'close':float('nan')}, 'test','test',datetime.now(timezone.utc))
            self.api.observe = lambda *args: value
            self.assertEqual(self.check(rule)['rows'][0]['result'], 'unknown')
        self.api.observe = lambda *args: self.obs()
        self.assertEqual(self.check(rule)['rows'][0]['result'], 'triggered')
        changed = self.api.update(dict(ruleId=rule['id'], expectedVersion=1, condition=dict(operator='gte', threshold=9)))
        self.assertEqual(self.check(changed)['rows'][0]['result'], 'triggered')
        paused = self.api.update(dict(ruleId=rule['id'], expectedVersion=2, status='paused'))
        self.assertEqual(self.check(paused)['rows'][0]['result'], 'not_triggered')

    def test_daily_calendar_revalidated_before_commit(self):
        rule = self.rule('daily_close')
        value = self.obs(mode='daily_close')
        value.pop('_calendar')
        self.api.observe = lambda *args: dict(value)
        row = self.check(rule)['rows'][0]
        self.assertEqual(row['result'], 'unknown')
        self.assertEqual(row['reasonCodes'], ['calendar_missing'])
        value = self.obs(mode='daily_close')
        value['sourceTradeDate'] = '2020-01-01'
        self.api.observe = lambda *args: dict(value)
        row = self.check(rule)['rows'][0]
        self.assertEqual(row['result'], 'unknown')
        self.assertIn('stale', row['reasonCodes'])
        self.assertNotIn('_calendar', row['observation'])

    def test_edit_during_fetch_discards_trigger_and_no_sqlite_lock(self):
        rule = self.rule()
        entered, release = threading.Event(), threading.Event()
        def read(*args):
            entered.set(); self.assertTrue(release.wait(2)); return self.obs()
        self.api.observe = read
        results = []
        task = threading.Thread(target=lambda: results.append(self.check(rule)))
        task.start(); self.assertTrue(entered.wait(2))
        updated = self.api.update(dict(ruleId=rule['id'],expectedVersion=1,name='changed'))
        release.set(); task.join(2)
        self.assertFalse(task.is_alive())
        self.assertEqual(results[0]['rows'][0]['reasonCodes'], ['rule_changed'])
        self.assertFalse(results[0]['rows'][0]['notified'])
        self.assertEqual(self.store.get('reminder',rule['id'])['version'], updated['version'])
        self.assertEqual(self.store.list('reminder_state'), [])

    def test_pause_during_first_symbol_stops_further_source_calls(self):
        self.store.put('watchlist',dict(id='w',name='two',symbols=['600000','000001']))
        scope = self.api.preview({'watchlistId':'w'})
        rule = self.api.create(dict(requestId='multi',name='multi',snapshotId=scope['id'],condition=dict(operator='gte',threshold=10),priceMode='intraday'))
        calls=[]
        def read(*args):
            calls.append(args[1])
            self.api.update(dict(ruleId=rule['id'],expectedVersion=1,status='paused'))
            return self.obs()
        self.api.observe=read
        result=self.check(rule)
        self.assertEqual(calls,['SH600000'])
        self.assertEqual([row['reasonCodes'] for row in result['rows']],[['rule_changed'],['rule_changed']])

    def test_one_worker_duplicate_pending_and_close_cancels(self):
        rule = self.rule()
        entered = threading.Event()
        calls = []
        def read(store, symbol, mode, stop):
            calls.append(threading.get_ident()); entered.set(); stop.wait(3)
            return self.obs()
        self.api.observe = read
        errors = []
        def check():
            try: self.api.check(dict(ruleId=rule['id'],requestId='same'))
            except ValueError as exc: errors.append(str(exc))
        first = threading.Thread(target=check); first.start(); self.assertTrue(entered.wait(2))
        second = threading.Thread(target=check); second.start()
        self.api.close(); first.join(2); second.join(2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(errors), 2)
        self.assertFalse(self.api.runtime()['running'])
        self.assertEqual(self.api.history({'ruleId':rule['id']})['total'], 0)
        with self.assertRaises(ValueError): self.check(rule)

    def test_scheduled_baseline_pause_and_enabled_only(self):
        rule = self.rule()
        with self.assertRaises(ValueError): self.api._perform({'ruleId':rule['id'],'requestId':'draft'},'scheduled')
        rule = self.api.update(dict(ruleId=rule['id'],expectedVersion=1,status='enabled'))
        self.api.start()
        self.api.observe = lambda *args: self.obs()
        # Restarted enabled rules establish an honest current baseline.
        result = self.api._perform(dict(ruleId=rule['id'],requestId='baseline'),'scheduled')
        self.assertEqual(result['rows'][0]['reasonCodes'], ['startup_baseline'])
        self.assertFalse(result['rows'][0]['notified'])
        self.api.update(dict(ruleId=rule['id'],expectedVersion=2,status='paused'))
        with self.assertRaises(ValueError): self.api._perform({'ruleId':rule['id'],'requestId':'paused'},'scheduled')

    def test_source_validity_and_calendar_boundaries(self):
        clock = datetime.fromisoformat('2026-09-24T10:00:00+08:00')
        calendar = dict(start='2026-09-20',end='2026-09-27',dates=['2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-25'])
        self.assertEqual(source.target_day({},clock,'daily_close')[1], 'calendar_missing')
        self.assertEqual(source.target_day(calendar,clock,'daily_close')[1], 'period_incomplete')
        self.assertEqual(source.target_day(calendar,clock,'intraday'), ('2026-09-24',None))
        after = datetime.fromisoformat('2026-09-24T16:00:00+08:00')
        self.assertEqual(source.target_day(calendar,after,'daily_close'), ('2026-09-24',None))
        sunday = datetime.fromisoformat('2026-09-27T16:00:00+08:00')
        self.assertEqual(source.target_day(calendar,sunday,'daily_close'), ('2026-09-25',None))
        fresh = source.observation('SH600000','intraday',dict(date='2026-09-24T09:59:00+08:00',close=11),'test','test',clock)
        self.assertEqual(fresh['validity'],'valid')
        stale = source.observation('SH600000','intraday',dict(date='2026-09-23T09:59:00+08:00',close=11),'test','test',clock)
        self.assertEqual(stale['reasonCodes'],['stale'])
        daily = source.observation('SH600000','daily_close',dict(date='2026-09-24',close=11),'test','test',after)
        self.assertEqual(daily['validity'],'valid'); self.assertIsNone(daily['sourceTime'])
        old = source.observation('SH600000','daily_close',dict(date='2026-09-23',close=11),'test','test',after)
        self.assertEqual(old['validity'],'unknown')

    def test_real_scheduler_thread_runs_once_without_overlap(self):
        rule = self.rule()
        rule = self.api.update(dict(ruleId=rule['id'],expectedVersion=1,status='enabled'))
        done = threading.Event()
        calls = []
        def read(*args):
            calls.append(threading.get_ident())
            done.set()
            return self.obs()
        self.api.observe = read
        self.api.start()
        self.api.next_schedule = 0
        self.assertTrue(done.wait(2))
        self.api.close()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], self.api.thread.ident)
        self.assertFalse(self.api.thread.is_alive())

    def test_adapter_fetches_only_target_date_and_never_fills_source_time(self):
        import pandas as pd
        from types import SimpleNamespace
        clock = datetime.fromisoformat('2026-09-24T16:00:00+08:00')
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None): return clock
        settings = dict(daily='akshare',intraday='akshare',quoteFallback=False)
        request = dict(symbol='SH600000',mode='daily_close',settings=settings,
                       calendar=dict(start='2026-09-24',end='2026-09-24',dates=['2026-09-24']))
        calls = []
        def daily(**kwargs):
            calls.append(kwargs)
            return pd.DataFrame([dict(date='2026-09-24',open=10,high=12,low=9,close=11)])
        with patch.object(source,'datetime',Clock), patch.dict('sys.modules',akshare=SimpleNamespace(stock_zh_a_hist=daily)):
            result = source._fetch(request)
            self.assertEqual(result['validity'],'valid')
            self.assertIsNone(result['sourceTime'])
            self.assertEqual(calls[0]['start_date'],'20260924')
            missing = source._fetch({**request,'calendar':{}})
            self.assertEqual(missing['reasonCodes'],['calendar_missing'])
            self.assertEqual(len(calls),1)
        def old(**kwargs):
            return pd.DataFrame([dict(date='2026-09-23',open=10,high=12,low=9,close=11)])
        with patch.object(source,'datetime',Clock), patch.dict('sys.modules',akshare=SimpleNamespace(stock_zh_a_hist=old)):
            self.assertEqual(source._fetch(request)['reasonCodes'],['source_not_published'])

    def test_cancelled_child_is_killed_and_reaped(self):
        from v3_backend.research.storage import write_json
        write_json(Path(self.temp.name)/'settings.json', {'dataSources':{'daily':'akshare','intraday':'akshare'}})
        from unittest.mock import Mock
        stop = Mock(); stop.is_set.return_value=False; stop.wait.return_value=True
        with patch.object(source.subprocess,'Popen') as launch:
            child=launch.return_value; child.poll.return_value=None
            value=source.read_observation(self.store,'SH600000','intraday',stop)
            self.assertEqual(value['reasonCodes'],['cancelled'])
            child.kill.assert_called_once(); child.wait.assert_called_once()


if __name__=='__main__': unittest.main()
