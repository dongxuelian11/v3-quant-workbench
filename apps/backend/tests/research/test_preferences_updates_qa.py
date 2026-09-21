"""Targeted public preferences and opt-in update QA, no network or workers."""
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta
from types import SimpleNamespace
from copy import deepcopy
from unittest.mock import patch
from v3_backend.research.server import Service
from v3_backend.research.storage import identifier
from v3_backend.research.scheduled_updates import tick

class PreferencesUpdatesQA(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.service=Service(self.root/'app');self.service.report_tasks.close()
        self.guard=patch('socket.socket.connect',side_effect=AssertionError('QA prohibits external network'));self.guard.start()
        self.a=self.service.store.create_project(self.root/'a','A');self.b=self.service.store.create_project(self.root/'b','B')
    def tearDown(self):
        self.guard.stop();self.service.close();self.temp.cleanup()
    def test_daily_plan_update_retains_resolved_watchlist_intersection(self):
        s=self.service;store=s.store;calls=[]
        store.put('watchlist',dict(id='selected',name='one',symbols=['SH600000']))
        plan=s.request('screeners.save',dict(plan=dict(name='manual intersect watchlist',mode='conditions',universe=dict(source='manual',symbols=['SH600000','SH600001'],watchlistId='selected',excludeST=False,minListingDays=0),conditions=dict(id='root',match='all',children=[]),assets=[],factors=[])))
        daily=s.request('dailyPlans.save',dict(planId=plan['id'],enabled=True))
        s.request('settings.save',dict(settings=dict(dataUpdates=dict(enabled=True,dailyPlanIds=[daily['id']]))))
        def submit(spec,frozen_project=None):
            calls.append(deepcopy(frozen_project));return dict(id='qa-job')
        with patch.object(s.jobs,'submit',side_effect=submit):tick(s,datetime(2026,9,21,16,1))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['universe']['symbols'],['SH600000'])
        self.assertNotIn('watchlistId',calls[0]['universe'])
    def test_submission_failure_does_not_repeat_same_day_but_next_day_retries(self):
        s=self.service;s.store.put('watchlist',dict(id='one',name='one',symbols=['SH600000']))
        s.request('settings.save',dict(settings=dict(dataUpdates=dict(enabled=True,watchlistIds=['one','one']))))
        day=datetime(2026,9,21,16,1)
        with patch.object(s.jobs,'submit',side_effect=ValueError('controlled unavailable')) as submit:
            tick(s,day);tick(s,day);self.assertEqual(submit.call_count,1)
            tick(s,day+timedelta(days=1));self.assertEqual(submit.call_count,2)
    def test_project_display_isolation_and_clear_to_latest_global(self):
        s=self.service;s.request('workspace.save',dict(state=dict(readingFontSize=14,density='compact')))
        a=s.request('workspace.project.save',dict(projectId=self.a['id'],overrides=dict(readingFontSize=20,sidebarVisible=False)))
        s.request('workspace.save',dict(state=dict(readingFontSize=16)))
        self.assertEqual(s.request('workspace.project.get',dict(projectId=self.b['id']))['effective']['readingFontSize'],16)
        self.assertEqual(s.request('workspace.project.get',dict(projectId=self.a['id']))['effective']['readingFontSize'],20)
        for forbidden in ('windows','dataDirectory','aiInstructions'):
            with self.assertRaises(ValueError):s.request('workspace.project.save',dict(projectId=self.a['id'],overrides={forbidden:'bad'}))
        cleared=s.request('workspace.project.save',dict(projectId=self.a['id'],overrides={}))
        self.assertEqual(cleared['effective']['readingFontSize'],16)
        self.assertEqual(s.store.project(self.a['id']),self.a)
    def test_ai_instruction_narrow_save_and_clear_survive_stale_project(self):
        s=self.service;stale=deepcopy(self.a)
        s.request('projects.aiInstructions.save',dict(projectId=self.a['id'],text='Only A'))
        stale['name']='renamed';s.request('projects.save',dict(project=stale))
        self.assertEqual(s.store.project(self.a['id'])['settings']['aiInstructions'],'Only A')
        self.assertNotIn('aiInstructions',s.store.project(self.b['id'])['settings'])
        old=s.store.project(self.a['id'])
        s.request('projects.aiInstructions.save',dict(projectId=self.a['id'],text=''))
        s.request('projects.save',dict(project=old))
        self.assertEqual(s.store.project(self.a['id'])['settings']['aiInstructions'],'')
    def test_old_legacy_project_without_data_path_remains_at_its_data(self):
        s=self.service;p=deepcopy(self.a);p['settings'].pop('dataPath');s.store.save_project(p)
        olddata=Path(p['path'])/'data';olddata.mkdir();(olddata/'marker').write_text('old')
        from v3_backend.research.data import project_data
        before=project_data(s.store.project(p['id']))['path']
        s.request('settings.save',dict(settings=dict(storage=dict(dataDirectory=str(self.root/'new-data')))))
        after=project_data(s.store.project(p['id']))['path']
        self.assertEqual(before,after);self.assertEqual((olddata/'marker').read_text(),'old')
