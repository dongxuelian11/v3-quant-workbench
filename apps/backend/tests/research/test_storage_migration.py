import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from v3_backend.research.storage import Store,write_json,read_json
from v3_backend.research.storage_migration import inventory,copy_verified,resolve_location

class MigrationCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=Store(self.root/'app');self.source=self.store.data_root()
        (self.source/'data').mkdir(parents=True);(self.source/'data/prices.bin').write_bytes(b'actual prices')
        (self.source/'reports/a').mkdir(parents=True);(self.source/'reports/a/document.pdf').write_bytes(b'report bytes')
        self.target=self.root/'destination'
    def tearDown(self):self.temp.cleanup()
    def test_preview_no_writes_and_space_or_nonempty_target_rejected(self):
        before={str(p):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        view,files=inventory(self.store,str(self.target))
        self.assertTrue(view['canStart'],view);self.assertEqual(view['fileCount'],2);self.assertFalse(self.target.exists())
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.source.rglob('*') if p.is_file()})
        with patch('v3_backend.research.storage_migration.shutil.disk_usage',return_value=type('Disk',(),{'free':0})()):
            self.assertFalse(inventory(self.store,str(self.target))[0]['canStart'])
        self.target.mkdir();(self.target/'unrelated').write_text('keep')
        self.assertFalse(inventory(self.store,str(self.target))[0]['canStart'])
    def test_copy_failure_keeps_source_settings_and_resume_verifies_existing_files(self):
        view,files=inventory(self.store,str(self.target));state=dict(id='test',**{k:view[k] for k in ('sourceDirectory','targetDirectory')})
        calls=[]
        def fail():
            calls.append(1)
            if len(calls)==5:raise OSError('injected interruption')
        with self.assertRaises(OSError):copy_verified(state,files,lambda:None,fail)
        self.assertEqual(self.store.data_root(),self.source);self.assertTrue((self.source/'data/prices.bin').exists())
        view,files=inventory(self.store,str(self.target),owned='test');self.assertTrue(view['canStart'],view)
        copy_verified(state,files,lambda:None)
        self.assertEqual(state['status'],'verifying');self.assertEqual(state['filesVerified'],2)
        self.assertEqual((self.target/'data/prices.bin').read_bytes(),b'actual prices')
        self.assertEqual(self.store.data_root(),self.source)
    def test_sources_target_and_path_mapping_cannot_loop(self):
        self.assertFalse(inventory(self.store,str(self.source/'child'))[0]['canStart'])
        self.assertFalse(inventory(self.store,str(self.root))[0]['canStart'])
        locations=[dict(source=str(self.source/'data'),target=str(self.target/'data'))]
        self.assertEqual(resolve_location(self.source/'data/prices.bin',locations),self.target/'data/prices.bin')
        unchanged=self.root/'project/.research/runs/frozen/data'
        self.assertEqual(resolve_location(unchanged,locations),unchanged)
        with self.assertRaisesRegex(ValueError,'循环'):
            resolve_location(self.source/'data',locations+[dict(source=str(self.target/'data'),target=str(self.source/'data'))])


class MigrationJourneyTests(unittest.TestCase):
    def setUp(self):
        from v3_backend.research.server import Service
        import pandas as pd
        from v3_backend.research import data
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.service=Service(self.root/'app')
        self.service.report_tasks.stop.set();self.service.report_tasks.thread.join(timeout=2)
        self.store=self.service.store;self.source=self.store.data_root();self.target=self.root/'moved'
        self.project=self.store.create_project(self.root/'project','migration')
        frame,_=data.normalize(pd.DataFrame([dict(symbol='SH600000',date='2025-01-02',open=10.,high=11.,low=9.,close=10.,volume=100.)]),'prices')
        data.merge_table(self.project,frame,'prices')
        self.report_id='a'*32;folder=self.source/'reports'/self.report_id;folder.mkdir(parents=True)
        (folder/'document.pdf').write_bytes(b'kept report')
        self.store.put('report',dict(id=self.report_id,title='report'));self.store.put('report_location',dict(id=self.report_id,path=str(folder)))
    def tearDown(self):self.service.close();self.temp.cleanup()
    def finish(self):
        self.service.migrations.thread.join(timeout=5)
        self.assertFalse(self.service.migrations.thread.is_alive())
        return self.service.request('storage.migration.status',{})
    def test_real_copy_switch_old_references_frozen_inputs_and_next_import(self):
        import pandas as pd
        from copy import deepcopy
        from v3_backend.research import data,reports,worker
        from v3_backend.research.storage_migration import location_scope
        frozen=deepcopy(self.project);account=dict(id='account',sourceVersion='unchanged',holdingValuationSources=[dict(project=deepcopy(self.project))])
        self.store.put('simulation_account',account)
        original=self.store.get('simulation_account','account')
        snapshot=self.root/'project/.research/runs/old/input/data';snapshot.mkdir(parents=True);(snapshot/'prices.parquet').write_bytes(b'fixed-input')
        fixed={**deepcopy(self.project),'inputDataRoot':str(snapshot.parent)}
        source_file=self.source/'data/prices/SH600000.parquet';before=source_file.read_bytes()
        state=self.service.request('storage.migration.start',dict(targetDirectory=str(self.target),requestId='move'))
        result=self.finish();self.assertEqual(result['status'],'completed',result)
        self.assertEqual(self.store.data_root(),self.target);self.assertEqual(source_file.read_bytes(),before)
        self.assertEqual(self.store.get('simulation_account','account'),original)
        with location_scope(self.store):
            self.assertEqual(Path(data.project_data(frozen)['path']),self.target)
            self.assertEqual(data.read_table(original['holdingValuationSources'][0]['project']).close.tolist(),[10.])
            self.assertEqual(Path(data.project_data(fixed)['path'])/'data',snapshot)
        self.assertEqual(Path(reports.document(self.store,self.report_id)['path']),self.target/'reports'/self.report_id/'document.pdf')
        csv=self.root/'new.csv';pd.DataFrame([dict(symbol='SH600000',date='2025-01-03',open=11.,high=12.,low=10.,close=11.,volume=100.)]).to_csv(csv,index=False)
        with patch.object(self.service.jobs,'_start_next'):
            job=self.service.jobs.submit(dict(kind='data.import',projectId=self.project['id'],parameters=dict(files=[str(csv)])))
        directory=self.root/'project/.research/runs'/job['id'];directory.mkdir(parents=True)
        write_json(directory/'request.json',dict(appData=str(self.store.root),job=job))
        self.assertEqual(worker.run(directory),0);self.assertEqual(source_file.read_bytes(),before)
        self.assertEqual(len(pd.read_parquet(self.target/'data/prices/SH600000.parquet')),2)
        self.assertEqual((snapshot/'prices.parquet').read_bytes(),b'fixed-input')
    def test_failure_resume_and_restart_after_settings_commit(self):
        from v3_backend.research.server import Service
        with patch('v3_backend.research.storage_migration.copy_verified',side_effect=OSError('copy failed')):
            started=self.service.request('storage.migration.start',dict(targetDirectory=str(self.target),requestId='failure'))
            failed=self.finish()
        self.assertEqual(failed['status'],'failed');self.assertEqual(self.store.data_root(),self.source)
        self.assertIn('sidebarVisible',self.service.request('workspace.get',{}))
        self.assertIsInstance(self.service.request('factors.list',{}),list)
        self.assertIn('sidebarVisible',self.service.request('workspace.save',{'state':{'sidebarVisible':True}}))
        with self.assertRaisesRegex(ValueError,'暂停'):self.service.request('market.quote.import',{})
        self.service.request('storage.migration.resume',dict(migrationId=started['id']))
        self.assertEqual(self.finish()['status'],'completed')
        self.service.migrations.state.update(status='switching');self.service.migrations._save()
        self.service.close();self.service=Service(self.root/'app');self.store=self.service.store
        self.assertEqual(self.service.request('storage.migration.status',{})['status'],'completed')
        self.assertFalse(self.service.migrations.pause.is_set());self.assertEqual(self.store.data_root(),self.target)
    def test_active_request_and_minute_future_wait_queue_stays_queued_until_cancel(self):
        from concurrent.futures import Future
        from v3_backend.research import intraday
        future=Future();key=('migration-test',)
        with intraday._lock:intraday._pending[key]=future
        try:
            with self.service.migrations.request_scope('test-existing-write'):
                started=self.service.request('storage.migration.start',dict(targetDirectory=str(self.target),requestId='waiting'))
                self.assertEqual(started['status'],'waiting')
                self.assertFalse(self.target.exists())
                self.service.jobs._start_next(None)
                self.assertEqual(self.service.migrations.status()['status'],'waiting')
            self.assertFalse(self.target.exists())
            self.service.request('storage.migration.cancel',dict(migrationId=started['id']))
            future.set_result(None)
            self.assertEqual(self.finish()['status'],'cancelled');self.assertEqual(self.store.data_root(),self.source)
        finally:
            if not future.done():future.set_result(None)
            with intraday._lock:intraday._pending.pop(key,None)

    def test_queue_pause_and_existing_context_resolves_new_location_after_switch(self):
        from v3_backend.research import data
        from v3_backend.research.storage_migration import location_scope
        with patch.object(self.service.jobs,'_launch') as launch:
            self.service.jobs.submit(dict(kind='data.import',projectId=self.project['id'],parameters=dict(files=[str(self.root/'queued.csv')])))
            launch.reset_mock()
            with location_scope(self.store):
                self.assertEqual(Path(data.project_data(self.project)['path']),self.source)
                with self.service.migrations.request_scope('existing-write'):
                    self.service.request('storage.migration.start',dict(targetDirectory=str(self.target),requestId='context'))
                    self.service.jobs._start_next(None);launch.assert_not_called()
                    self.assertEqual(self.store.list('job')[0]['status'],'queued')
                result=self.finish();self.assertEqual(result['status'],'completed',result)
                self.assertEqual(Path(data.project_data(self.project)['path']),self.target)
            launch.assert_called_once()
    def test_missing_source_and_verification_failure_never_switch(self):
        original=self.store.data_root()
        with patch('v3_backend.research.storage_migration._digest',side_effect=OSError('cannot read source')):
            self.service.request('storage.migration.start',dict(targetDirectory=str(self.target),requestId='verify-error'))
            state=self.finish()
        self.assertEqual(state['status'],'failed');self.assertEqual(self.store.data_root(),original)
        self.assertTrue((self.source/'data/prices/SH600000.parquet').exists())
        self.service.request('storage.migration.cancel',dict(migrationId=state['id']))

    def test_nested_project_is_blocked_without_scanning_or_copying_fixed_inputs(self):
        nested=self.store.create_project(self.source/'data/nested-project','nested')
        frozen=Path(nested['path'])/'.research/runs/test/input';frozen.mkdir(parents=True);(frozen/'fixed.bin').write_bytes(b'fixed')
        view,files=inventory(self.store,str(self.target))
        self.assertFalse(view['canStart']);self.assertTrue(any('包含已有项目' in b for b in view['blockers']))
        self.assertFalse(any('nested-project' in f['source'] for f in files));self.assertFalse(self.target.exists())
        with self.assertRaisesRegex(ValueError,'包含已有项目'):
            self.service.request('storage.migration.start',dict(targetDirectory=str(self.target),requestId='nested'))
        self.assertEqual((frozen/'fixed.bin').read_bytes(),b'fixed')

    def test_waiting_allows_readonly_and_recovery_but_rejects_submit_before_preparation(self):
        import time
        self.store.put('job',dict(id='needs-register',projectId=self.project['id'],name='待登记',status='failed',registrationPending=True))
        self.service.request('storage.migration.start',dict(targetDirectory=str(self.target),requestId='recover'))
        for _ in range(100):
            if self.service.migrations.status()['blockers']:break
            time.sleep(.01)
        self.assertTrue(any('恢复结果登记' in b for b in self.service.migrations.status()['blockers']))
        self.assertEqual(len(self.service.request('projects.list',{})),1)
        self.assertEqual(self.service.request('experiments.list',dict(projectId=self.project['id'])),[])
        with patch.object(self.service.executions,'start',return_value={'mode':'ask'}):
            self.assertEqual(self.service.request('ai.chat.start',dict(mode='ask'))['mode'],'ask')
            with self.assertRaisesRegex(ValueError,'暂停'):self.service.request('ai.chat.start',dict(mode='research'))
        with patch.object(self.service.jobs,'_submit_in_scope',side_effect=AssertionError('must not prepare')):
            with self.assertRaisesRegex(ValueError,'暂停'):self.service.jobs.submit({})
        def recover(key):
            value=self.store.get('job',key);value['registrationPending']=False;self.store.put('job',value);return {'status':'failed'}
        with patch.object(self.service.jobs,'recover_result',side_effect=recover):
            self.service.request('jobs.recoverResult',dict(jobId='needs-register'))
        self.assertEqual(self.finish()['status'],'completed')

    def test_slow_start_preflight_does_not_hold_status_lock_and_preview_is_cancellable(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        import v3_backend.research.storage_migration as migration
        entered=threading.Event();release=threading.Event();original=migration.inventory
        def slow(*args,**kwargs):
            entered.set()
            if not release.wait(2):raise AssertionError('barrier expired')
            return original(*args,**kwargs)
        with ThreadPoolExecutor(max_workers=2) as pool:
            with patch.object(migration,'inventory',side_effect=slow):
                future=pool.submit(self.service.request,'storage.migration.start',dict(targetDirectory=str(self.target),requestId='slow'))
                self.assertTrue(entered.wait(1))
                try:self.assertIsNone(pool.submit(self.service.request,'storage.migration.status',{}).result(timeout=.5))
                finally:release.set()
                future.result(timeout=2)
        self.assertEqual(self.finish()['status'],'completed')
        with self.assertRaises(InterruptedError):inventory(self.store,str(self.root/'next'),check=lambda:(_ for _ in ()).throw(InterruptedError('cancel')))
