import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from v3_backend.research.local_assistant import Assistant
from v3_backend.research.storage import Store

class LocalAssistantTests(unittest.TestCase):
    def test_confirmation_and_drafts_do_not_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            service=SimpleNamespace(store=Store(directory))
            assistant=Assistant(service)
            with patch.object(assistant,'start') as start:
                for params in ({'model':'qwen3:8b'},{'model':'other','confirmed':True}):
                    with self.assertRaises(ValueError): assistant.pull(params)
                start.assert_not_called()
            self.assertEqual(assistant.interpret({'text':'打开持仓'})['status'],'unavailable')
            objects={'screeners':[{'id':'real','name':'真实'}]}
            for action in (
                {'kind':'run','namespace':'screeners','objectIds':['invented']},
                {'kind':'run','namespace':'research','objectIds':[]},
                {'kind':'filter_patch','namespace':'screeners','objectIds':[], 'conditions':{'match':'all','children':[{'field':'invented','operator':'gt','value':1}]}},
            ):
                with self.assertRaises(ValueError): assistant.validate(action,objects)
            action={'kind':'filter_patch','namespace':'screeners','objectIds':[], 'conditions':{'match':'any','children':[{'field':'close','operator':'gt','value':10},{'field':'changeRatio','operator':'gt','value':.02}]}}
            self.assertEqual(assistant.validate(action,objects)['conditions']['match'],'any')
            self.assertEqual(service.store.list('job'),[])

if __name__=='__main__': unittest.main()
