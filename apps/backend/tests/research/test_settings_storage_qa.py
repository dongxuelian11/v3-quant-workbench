"""Independent portable-settings and cross-scope cache safety examples."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from v3_backend.research.server import Service
from v3_backend.research.storage import write_json


class SettingsStorageQA(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.service=Service(self.root/'app')
        self.store=self.service.store
        self.source=self.store.create_project(self.root/'source','QA source')
        self.other=self.store.create_project(self.root/'other','QA other')
        self.guard=patch('socket.socket.connect',side_effect=AssertionError('QA forbids network'))
        self.guard.start();self.addCleanup(self.guard.stop)

    def tearDown(self):
        self.service.close();self.tmp.cleanup()

    def cache_file(self):
        cache=Path(self.source['path'])/'.research/cache'
        cache.mkdir(parents=True,exist_ok=True)
        artifact=cache/'features.parquet';artifact.write_bytes(b'QA cache')
        return artifact

    def assert_cache_kept(self, artifact):
        try:
            result=self.service.request('storage.clearCache',{'projectId':self.source['id']})
            self.assertFalse(result['cleared'],'referenced cache reported cleared')
        except ValueError:
            pass
        self.assertTrue(artifact.is_file(),'cross-scope input was deleted')

    def test_normal_export_excludes_ai_paths_and_workspace_objects(self):
        self.service.request('settings.save',{'settings':{'ai':{'apiKey':'QA_SECRET_CANARY','baseUrl':'http://private.local'},'tdxDirectory':str(self.root/'private')}})
        self.service.request('workspace.save',{'state':{'windows':[{'id':'old-window','panels':[{'id':'old-project-panel','projectId':self.source['id']}]}],
            'activeConversationId':'QA_PRIVATE_CONVERSATION','presets':{'old':{'panels':['QA_OLD_OBJECT']}}}})
        result=self.service.request('settings.export',{})
        text=json.dumps(result)
        for forbidden in ['QA_SECRET_CANARY','private.local',str(self.root),'old-project-panel','QA_PRIVATE_CONVERSATION','QA_OLD_OBJECT']:
            self.assertNotIn(forbidden,text)

    def test_export_and_diagnostics_strip_nested_compute_secrets_and_paths(self):
        self.service.request('settings.save',{'settings':{'compute':{'profile':'interactive',
            'legacyProvider':{'apiKey':'QA_NESTED_SECRET','cachePath':str(self.root/'private-data')}}}})
        for method in ['settings.export','diagnostics.preview']:
            with self.subTest(method=method):
                value=self.service.request(method,{})
                text=json.dumps(value)
                self.assertNotIn('QA_NESTED_SECRET',text)
                self.assertNotIn('private-data',text)

    def test_preview_strips_old_objects_inside_layout_before_display(self):
        value=dict(format='v3-settings',version=1,workspace={'layoutPresets':{'Old':{
            'layout':'single','panels':[{'projectId':'QA_OLD_PROJECT','path':'D:/QA_PRIVATE_PATH'}],
            'conversationId':'QA_OLD_CONVERSATION'}}},settings={})
        result=self.service.request('settings.importPreview',{'package':value})
        text=json.dumps(result)
        for forbidden in ['QA_OLD_PROJECT','QA_PRIVATE_PATH','QA_OLD_CONVERSATION']:
            self.assertNotIn(forbidden,text)

    def test_conflict_keep_replace_preserve_other_layouts(self):
        self.service.request('workspace.save',{'state':{'layoutPresets':{
            'same':{'layout':'single','sidebarVisible':True},'local-only':{'layout':'rows'}}}})
        incoming=dict(format='v3-settings',version=1,workspace={'layoutPresets':{
            'same':{'layout':'columns','sidebarVisible':False},'new':{'layout':'rows'}}},settings={})
        preview=self.service.request('settings.importPreview',{'package':incoming})
        self.assertEqual(preview['layoutConflicts'],['same'])
        kept=self.service.request('settings.import',{'package':incoming,'conflict':'keep'})['workspace']['layoutPresets']
        self.assertEqual(kept['same']['layout'],'single');self.assertIn('new',kept);self.assertIn('local-only',kept)
        replaced=self.service.request('settings.import',{'package':incoming,'conflict':'replace'})['workspace']['layoutPresets']
        self.assertEqual(replaced['same']['layout'],'columns');self.assertIn('local-only',replaced)

    def test_cache_referenced_by_other_project_candidate_is_preserved(self):
        artifact=self.cache_file()
        self.store.project_store(self.other['id']).put('candidate',dict(id='cross-candidate',projectId=self.other['id'],
            spec={'parameters':{'dataPath':str(artifact)}}),self.other['id'])
        self.assert_cache_kept(artifact)

    def test_cache_reference_path_aliases_are_not_missed(self):
        artifact=self.cache_file()
        aliases=['./.research/cache/features.parquet',str(artifact).upper()]
        for reference in aliases:
            with self.subTest(reference=reference):
                artifact=self.cache_file()
                self.store.project_store(self.source['id']).put('candidate',dict(id='alias-candidate',projectId=self.source['id'],
                    spec={'parameters':{'dataPath':reference}}),self.source['id'])
                self.assert_cache_kept(artifact)

    def test_cache_referenced_by_global_plan_is_preserved(self):
        artifact=self.cache_file()
        self.store.put('screener',dict(id='global-plan',name='Global reference',assets=[dict(projectId=self.source['id'],
            snapshot={'dataPath':str(artifact)})]))
        self.assert_cache_kept(artifact)

    def test_global_selection_pending_tasks_protect_source_project_cache(self):
        for status,flags in [('running',{}),('failed',{'registrationPending':True}),('failed',{'cleanupPending':True})]:
            with self.subTest(status=status,flags=flags):
                artifact=self.cache_file()
                self.store.put('job',dict(id='global-selection',kind='selection.run',projectId=None,status=status,
                    spec={'strategySnapshots':[{'project':deepcopy(self.source)}]},**flags))
                self.assert_cache_kept(artifact)

    def test_unreferenced_cache_clear_keeps_user_data_and_results(self):
        artifact=self.cache_file()
        data=Path(self.source['path'])/'data/qa-data.txt';data.parent.mkdir(parents=True,exist_ok=True);data.write_text('data')
        result=Path(self.source['path'])/'.research/runs/qa/qa-result.txt';result.parent.mkdir(parents=True,exist_ok=True);result.write_text('result')
        response=self.service.request('storage.clearCache',{'projectId':self.source['id']})
        self.assertTrue(response['cleared']);self.assertFalse(artifact.exists())
        self.assertEqual(data.read_text(),'data');self.assertEqual(result.read_text(),'result')

    def test_file_daily_custom_period_does_not_fetch_hidden_calendar(self):
        from v3_backend.research import data,quotes
        self.service.request('settings.save',{'settings':{'dataSources':{'daily':'file'}}})
        frame=pd.DataFrame(dict(symbol=['SH600000']*2,date=pd.to_datetime(['2025-01-02','2025-01-03']),
            open=[10.,11.],high=[10.,11.],low=[10.,11.],close=[10.,11.],volume=[100.,100.]))
        data.merge_table(self.source,frame,'prices',return_all=False)
        with patch.object(quotes,'_baostock',side_effect=AssertionError('hidden calendar network')) as network:
            with self.assertRaisesRegex(ValueError,'来源|日历'):
                self.service.request('data.bars',dict(projectId=self.source['id'],symbol='SH600000',period='trading_days',tradingDays=4))
            network.assert_not_called()


if __name__=='__main__':unittest.main()
