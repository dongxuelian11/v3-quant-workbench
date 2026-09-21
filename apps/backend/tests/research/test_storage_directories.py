import tempfile
import unittest
from pathlib import Path
from v3_backend.research.server import Service
from v3_backend.research.reports import _folder


class StorageDirectoriesTests(unittest.TestCase):
    def test_new_locations_preserve_existing_projects_and_reports(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);service=Service(root/'app')
            try:
                store=service.store
                old=store.create_project(root/'old','旧研究')
                report_id='a'*32
                legacy=store.root/'shared/reports'/report_id
                legacy.mkdir(parents=True)
                (legacy/'document.pdf').write_bytes(b'unchanged')
                target=root/'new-data'
                service.request('settings.save',{'settings':{'storage':{'dataDirectory':str(target),'newProjectDirectory':str(root/'projects')}}})
                self.assertEqual(store.project(old['id'])['settings']['dataPath'],old['settings']['dataPath'])
                self.assertEqual(_folder(store,report_id),legacy)
                first=_folder(store,'b'*32)
                self.assertEqual(first,target/'reports'/('b'*32))
                fresh=store.create_project(root/'fresh','新研究')
                self.assertEqual(Path(fresh['settings']['dataPath']),target/'data')
                service.request('settings.save',{'settings':{'storage':{'dataDirectory':str(root/'later')}}})
                self.assertEqual(_folder(store,'b'*32),first)
                self.assertEqual((legacy/'document.pdf').read_bytes(),b'unchanged')
                exported=service.request('settings.export',{})
                self.assertNotIn('storage',exported['settings'])
            finally:service.close()
