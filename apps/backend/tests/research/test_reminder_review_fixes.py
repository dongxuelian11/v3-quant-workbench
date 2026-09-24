import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from v3_backend.research.storage import Store, write_json
from v3_backend.research.reminders import Reminders
from v3_backend.research import reminder_source as source


class ReminderReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.api = Reminders(self.store)
        self.addCleanup(self.api.close)
        self.calendar = dict(start='2026-09-24',end='2026-09-24',dates=['2026-09-24'])

    def rule(self, symbols=None):
        if symbols:
            self.store.put('watchlist', dict(id='w',name='fixed',symbols=symbols))
            scope=self.api.preview({'watchlistId':'w'})
        else: scope=self.api.preview({'symbol':'600000'})
        return self.api.create(dict(requestId=scope['id'],name='test',snapshotId=scope['id'],priceMode='intraday',condition=dict(operator='gte',threshold=10)))

    def minute_fetch(self, rows):
        import pandas as pd
        clock=datetime.fromisoformat('2026-09-24T10:00:30+08:00')
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return clock
        request=dict(symbol='SH600000',mode='intraday',settings=dict(daily='akshare',intraday='akshare',quoteFallback=False),calendar=self.calendar)
        upstream=Mock(return_value=pd.DataFrame(rows))
        with patch.object(source,'datetime',Clock), patch.dict('sys.modules',akshare=SimpleNamespace(stock_zh_a_hist_min_em=upstream)):
            result=source._fetch(request)
        upstream.assert_called_once()
        return result

    def test_adapter_selects_completed_previous_minute(self):
        result=self.minute_fetch([dict(date='2026-09-24 09:59:00',close=9,volume=1),dict(date='2026-09-24 10:00:00',close=99,volume=1)])
        self.assertEqual(result['price'],9)
        self.assertEqual(result['sourceTime'],'2026-09-24T09:59:00+08:00')
        self.assertEqual(result['validity'],'valid')
        self.assertEqual(result['_calendar'],self.calendar)

    def test_adapter_rejects_only_unfinished_minute(self):
        result=self.minute_fetch([dict(date='2026-09-24 10:00:00',close=99,volume=1)])
        self.assertEqual(result['validity'],'unknown')
        self.assertEqual(result['reasonCodes'],['period_incomplete'])

    def test_two_budgeted_rounds_query_previously_unprocessed_tail(self):
        symbols=['SH600000','SH600001','SH600002','SH600003','SH600004']
        rule=self.rule(symbols)
        elapsed=[0.0]; calls=[]
        def slow(store,symbol,mode,stop):
            calls.append(symbol); elapsed[0]+=20
            return source.unknown(symbol,mode,'source_unavailable')
        self.api.observe=slow
        with patch('v3_backend.research.reminders.time.monotonic',side_effect=lambda:elapsed[0]):
            first=self.api._perform_in_scope(dict(ruleId=rule['id'],requestId='first'),'manual')
            self.assertEqual(calls,symbols[:3])
            self.assertEqual([r['symbol'] for r in first['rows']],symbols)
            self.assertEqual([r['reasonCodes'] for r in first['rows'][3:]],[['check_budget_exhausted'],['check_budget_exhausted']])
            # Cursor persists independently of the manager instance.
            second_api=Reminders(self.store); self.addCleanup(second_api.close); second_api.observe=slow
            second=second_api._perform_in_scope(dict(ruleId=rule['id'],requestId='second'),'manual')
            self.assertEqual(calls[3:],symbols[3:]+symbols[:1])
            self.assertEqual(set(calls),set(symbols))
            self.assertEqual([r['symbol'] for r in second['rows']],symbols)
        self.assertEqual(self.api.history({'ruleId':rule['id']})['total'],2)

    def test_large_calendar_uses_request_file_and_cancellation_reaps_child(self):
        calendar=dict(start='2000-01-01',end='2040-12-31',dates=['2026-09-24']*20000)
        write_json(self.store.data_root()/'data/trading-calendar.json',calendar)
        write_json(self.store.root/'settings.json',{'dataSources':{'daily':'akshare','intraday':'akshare'}})
        stop=Mock(); stop.is_set.return_value=False; stop.wait.return_value=True
        child=Mock(); child.poll.return_value=None
        paths=[]
        def launch(argv,**kwargs):
            self.assertLess(sum(map(len,argv)),1000)
            request_path=Path(argv[-2]); paths.append(request_path)
            self.assertEqual(request_path.name,'request.json')
            self.assertGreater(request_path.stat().st_size,32767)
            self.assertEqual(json.loads(request_path.read_text(encoding='utf-8'))['calendar'],calendar)
            self.assertNotIn('2026-09-24',' '.join(argv))
            return child
        with patch.object(source.subprocess,'Popen',side_effect=launch) as start:
            result=source.read_observation(self.store,'SH600000','intraday',stop)
        start.assert_called_once(); child.kill.assert_called_once(); child.wait.assert_called_once()
        self.assertEqual(result['reasonCodes'],['cancelled'])
        self.assertFalse(paths[0].exists())

    def test_commit_rechecks_lunch_and_close_and_removes_private_calendar(self):
        for checked, observed in [('2026-09-24T11:31:00+08:00','2026-09-24T11:29:00+08:00'),('2026-09-24T15:01:00+08:00','2026-09-24T14:59:00+08:00'),('2026-09-24T11:30:01+08:00','2026-09-24T11:29:00+08:00'),('2026-09-24T15:00:01+08:00','2026-09-24T14:59:00+08:00')]:
            with self.subTest(checked=checked):
                rule=self.rule()
                value=dict(id=observed,symbol='SH600000',kind='minute_close',price=11,priceBasis='raw',source=dict(provider='test',endpoint='test'),
                           sourceTime=observed,sourceTradeDate='2026-09-24',fetchedAt=observed,validity='valid',reasonCodes=[],_calendar=self.calendar)
                self.api.observe=lambda *args:dict(value)
                with patch('v3_backend.research.reminders.now',return_value=checked):
                    result=self.api._perform_in_scope(dict(ruleId=rule['id'],requestId=checked),'manual')
                row=result['rows'][0]
                self.assertEqual(row['result'],'unknown')
                self.assertEqual(row['reasonCodes'],['market_closed'])
                self.assertFalse(row['notified'])
                self.assertNotIn('_calendar',row['observation'])
                state=self.store.get('reminder_state',rule['id']+':1')
                self.assertEqual(state['symbols']['SH600000'],{})


if __name__=='__main__': unittest.main()
