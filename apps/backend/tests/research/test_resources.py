import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from v3_backend.research.jobs import Jobs
from v3_backend.research.resources import compute_settings
from v3_backend.research.storage import Store, read_json


class ResourceQueue(unittest.TestCase):
    def until(self, predicate):
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            if predicate(): return
            time.sleep(.04)
        self.fail('子进程未在预期时间到达检查点')

    def scenario(self, shared=False, same_project=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'app');jobs=Jobs(store,lambda _:None)
            projects=[store.create_project(root/str(i),str(i)) for i in range(2)]
            for p in projects:
                p['settings']['dataPath']=str(root/('shared' if shared else p['id'])/'data')
                store.save_project(p)
            if same_project: projects[1]=projects[0]
            source=root/'source.csv'
            source.write_text('symbol,date,open,high,low,close,volume\nSH600000,2020-01-02,10,11,9,10,10000\n')
            store.settings({'compute':{'profile':'compute','maxConcurrentJobs':2,'threadsPerJob':2}})
            actual_popen=subprocess.Popen
            children=[]
            def launch(command, **kwargs):
                process=actual_popen([command[0], str(Path(__file__).with_name('resource_worker_probe.py')), command[-1]], **kwargs)
                children.append(process)
                return process
            folders=[]
            try:
                with patch('v3_backend.research.jobs.subprocess.Popen', side_effect=launch), patch('v3_backend.research.jobs.os.cpu_count', return_value=8):
                    first=jobs.submit(dict(projectId=projects[0]['id'],kind='data.import',parameters={'files':[str(source)]}))
                    a=Path(projects[0]['path'])/'.research/runs'/first['id'];folders.append(a)
                    self.until(lambda:(a/'resource-observed.json').exists())
                    second=jobs.submit(dict(projectId=projects[1]['id'],kind='data.import',parameters={'files':[str(source)]}))
                    b=Path(projects[1]['path'])/'.research/runs'/second['id'];folders.append(b)
                    if shared or same_project:
                        self.assertEqual(second['status'],'queued')
                        self.assertEqual(len(children),1)
                        (a/'release').touch()
                        self.until(lambda:(b/'resource-observed.json').exists())
                    else:
                        self.until(lambda:(b/'resource-observed.json').exists())
                        self.assertEqual(len(jobs.processes),2)
                        self.assertTrue(all(child.poll() is None for child in children))
                    store.settings({'compute':{'profile':'interactive','threadsPerJob':1}})
                    for directory in folders:
                        observed=read_json(directory/'resource-observed.json')
                        self.assertEqual(observed['status'],0)
                        self.assertEqual(observed['lightgbmThreads'],2)
                        self.assertEqual(observed['env']['V3_RESEARCH_THREADS'],'2')
                        blas=[p for p in observed['pools'] if p['user_api']=='blas']
                        self.assertTrue(blas)
                        self.assertTrue(all(p['num_threads']<=2 for p in blas), blas)
                        self.assertEqual(read_json(directory/'request.json')['job']['spec']['effectiveResources']['threadsPerJob'],2)
                        self.assertEqual(read_json(directory/'details.json')['effectiveResources']['threadsPerJob'],2)
                        (directory/'release').touch()
                    self.until(lambda:not jobs.processes)
                    self.assertEqual(store.get('job',first['id'])['status'],'completed')
                    self.assertEqual(store.get('job',second['id'])['status'],'completed')
                    # A new submission uses the changed profile.
                    with patch.object(jobs,'_start_next'):
                        third=jobs.submit(dict(projectId=projects[0]['id'],kind='data.import',parameters={'files':[str(source)]}))
                    self.assertEqual(third['effectiveResources']['threadsPerJob'],1)
                    jobs.cancel(third['id'])
            finally:
                for directory in folders:
                    if directory.exists(): (directory/'release').touch()
                self.until(lambda:not jobs.processes)
                jobs.close()

    def test_two_workers_overlap_and_observe_frozen_thread_limits(self):
        self.scenario()

    def test_shared_data_serializes_real_workers(self):
        self.scenario(shared=True)

    def test_same_project_serializes_real_workers(self):
        self.scenario(same_project=True)

    def test_cpu_shrink_and_invalid_settings(self):
        self.assertEqual(compute_settings({'profile':'compute'},1)['threadsPerJob'],1)
        self.assertEqual(compute_settings({'profile':'compute'},3)['threadsPerJob'],1)
        for value in ({'profile':'bad'}, {'threadsPerJob':True}, {'maxConcurrentJobs':0}):
            with self.assertRaises(ValueError): compute_settings(value,8)
