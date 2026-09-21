import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from copy import deepcopy
from v3_backend.research.storage import Store,identifier
from v3_backend.research.scheduled_updates import tick


class ScheduledUpdatesTests(unittest.TestCase):
    def test_opt_in_scoped_once_without_research(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'app');calls=[]
            def submit(spec,frozen_project=None):
                calls.append((deepcopy(spec),deepcopy(frozen_project)))
                return store.put('job',dict(id=identifier(),spec=spec,status='queued'))
            service=SimpleNamespace(store=store,jobs=SimpleNamespace(submit=submit),emit=lambda _:None)
            store.put('watchlist',dict(id='chosen',name='选择的自选',symbols=['SH600000']))
            store.put('watchlist',dict(id='other',name='未选择',symbols=['SZ000001']))
            clock=datetime(2026,9,21,16,1)
            tick(service,clock);self.assertEqual(calls,[])
            store.settings({'dataUpdates':{'enabled':True,'watchlistIds':['chosen']}})
            tick(service,clock.replace(hour=14));self.assertEqual(calls,[])
            tick(service,clock);tick(service,clock)
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][0]['kind'],'data.update')
            self.assertEqual(calls[0][1]['universe']['symbols'],['SH600000'])
            store.delete('scheduled_update','2026-09-21-watchlist-chosen')
            tick(service,clock)
            self.assertEqual(len(calls),1) # submit persisted, status record was lost
