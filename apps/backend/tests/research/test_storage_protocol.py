import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import time
from unittest.mock import patch

from v3_backend.research.storage import Store
from v3_backend.research.server import Service
from v3_backend.research.framing import encode_frame, read_frames


class StorageProtocolTest(unittest.TestCase):
    def test_portable_project_template_and_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = Service(root / 'app')
            project = service.request('projects.create', dict(path=str(root / 'project'), name='研究', objective='测试'))
            template = service.request('universe.saveTemplate', dict(name='模板', universe=project['universe']))
            project['universe']['symbols'].append('SH600000')
            service.request('projects.save', {'project': project})
            self.assertEqual(service.request('universe.templates', {})[0]['universe']['symbols'], [])
            self.assertEqual(service.request('charts.save', dict(projectId=project['id'], symbol='600000', annotations=[{'name': 'line'}])), {'annotations': [{'name': 'line'}]})
            service.close()
            second = Store(root / 'other-app')
            restored = second.open_project(root / 'project')
            self.assertEqual(restored['universe']['symbols'], ['SH600000'])
            self.assertEqual(second.settings()['defaultDataSource'], 'baostock')

    def test_restart_marks_unfinished_jobs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root / 'app')
            project = store.create_project(root / 'project', 'p')
            store.put('job', dict(id='test', projectId=project['id'], status='running', createdAt='', updatedAt=''), project['id'])
            service = Service(root / 'app')
            self.assertEqual(service.request('jobs.list', {})[0]['status'], 'interrupted')
            service.close()

    def test_stdio_is_only_frames_and_no_old_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = os.environ.copy()
            environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[2] / 'src')
            request = encode_frame({'id': 1, 'method': 'settings.get', 'params': {}})
            process = subprocess.run([sys.executable, '-m', 'v3_backend.research.server', '--app-data', temporary], input=request, capture_output=True, env=environment, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr.decode())
            frames = list(read_frames(io.BytesIO(process.stdout)))
            self.assertEqual(frames[0]['id'], 1)
            self.assertEqual(frames[0]['result']['defaultDataSource'], 'baostock')
            self.assertNotIn('v3_backend.runtime', sys.modules)

    def test_cancel_kills_owned_child_and_keeps_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = Service(root / 'app')
            project = service.store.create_project(root / 'project', 'p')
            original_popen = subprocess.Popen

            def sleeper(command, **kwargs):
                return original_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)

            with patch('v3_backend.research.jobs.subprocess.Popen', side_effect=sleeper):
                event = service.jobs.submit(dict(projectId=project['id'], kind='data.import', parameters={'files': ['unused.csv']}))
                child = service.jobs.processes[event['id']]
                service.store.open_project(project['path'])
                self.assertEqual(service.store.get('job', event['id'])['status'], 'running')
                service.jobs.cancel(event['id'])
                child.wait(timeout=3)
                deadline = time.monotonic() + 3
                while service.jobs.processes and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(service.store.get('job', event['id'])['status'], 'cancelled')
                self.assertTrue((root / 'project' / '.research' / 'runs' / event['id'] / 'request.json').exists())
            service.close()


if __name__ == '__main__':
    unittest.main()
