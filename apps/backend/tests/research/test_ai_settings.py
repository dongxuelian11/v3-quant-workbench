import tempfile
import unittest
from pathlib import Path
from v3_backend.research.server import Service
from v3_backend.research.ai_settings import resolve, instructions


class AISettingsTests(unittest.TestCase):
    def test_explicit_purpose_keeps_credentials_and_preferences_separate(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(Path(root)/'app')
            try:
                service.request('settings.save',{'settings':{'ai':{'baseUrl':'https://one.invalid/v1','model':'one','apiKey':'first-secret'},
                    'aiPurposes':{'research':{'baseUrl':'http://localhost:9999/v1','model':'local'},'reports':{'model':'reports'}},'aiInstructions':'中文解释'}})
                self.assertEqual(resolve(service.store,'research')['apiKey'],'')
                self.assertEqual(resolve(service.store,'reports')['apiKey'],'first-secret')
                self.assertEqual(resolve(service.store,'conversation')['model'],'one')
                a=service.store.create_project(Path(root)/'a','A')
                b=service.store.create_project(Path(root)/'b','B')
                a['settings']['aiInstructions']='只研究动量'
                service.store.save_project(a)
                self.assertIn('只研究动量',instructions(service.store,a['id']))
                self.assertNotIn('只研究动量',instructions(service.store,b['id']))
                self.assertIn('中文解释',instructions(service.store,b['id']))
                exported=service.request('settings.export',{})
                self.assertNotIn('aiPurposes',exported['settings'])
            finally:service.close()
