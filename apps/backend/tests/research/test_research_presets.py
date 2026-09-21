import tempfile
import unittest
from pathlib import Path
from v3_backend.research.server import Service


class ResearchPresetsTests(unittest.TestCase):
    def test_saved_copy_and_navigation_do_not_mutate_project(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(Path(root)/'app')
            try:
                project=service.store.create_project(Path(root)/'project','独立课题')
                source={'commissionBuy':.0003,'stampDuty':'historical','volumeParticipation':.1}
                saved=service.request('researchPresets.save',{'preset':{'name':'日线费用','category':'costs','value':source}})
                source['commissionBuy']=.9
                loaded=service.request('researchPresets.list',{'category':'costs'})[0]
                self.assertEqual(loaded['value']['commissionBuy'],.0003)
                self.assertEqual(service.store.project(project['id']),project)
                loaded['value']['commissionBuy']=.001
                updated=service.request('researchPresets.save',{'preset':loaded})
                self.assertEqual(updated['revision'],2)
                self.assertEqual(saved['value']['commissionBuy'],.0003)
                service.request('workspace.save',{'state':{'navigation':{'order':['quote','today'],'hidden':['reports'],'pinned':['quote']}}})
                export=service.request('settings.export',{})
                self.assertEqual(export['workspace']['navigation']['hidden'],['reports'])
                with self.assertRaises(ValueError):
                    service.request('researchPresets.save',{'preset':{'name':'坏费用','category':'costs','value':{'commissionBuy':'oops'}}})
                with self.assertRaises(ValueError):
                    service.request('researchPresets.save',{'preset':{'name':'路径','category':'validation','value':{'dataPath':'elsewhere'}}})
            finally:service.close()
