"""Public import/apply/submit flow; no source download or research calculation."""
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from v3_backend.research.server import Service
from v3_backend.research.storage import read_json
from v3_backend.research.history import members


class MembershipChain(unittest.TestCase):
    def test_import_apply_next_submit_and_draft_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);service=Service(root/'app')
            try:
                project=service.store.create_project(root/'project','成员应用')
                project['universe'].update(source='manual',symbols=['SH600000'],excludeST=False,minListingDays=0)
                project=service.store.save_project(project)
                other=service.store.create_project(root/'other','其他项目')
                untouched_project=deepcopy(service.store.project(other['id']))
                def get_strategy(key):
                    return next(s for s in service.request('strategies.list',{'projectId':project['id']}) if s['id']==key)
                get_strategy('default')
                active=service.request('strategies.activate',{'projectId':project['id'],'strategyId':'default','enabled':True})['active']
                sibling=service.request('strategies.create',{'projectId':project['id'],'name':'其他策略'})
                source=root/'members.csv'
                source.write_text('symbol,startDate,endDate\nSH600001,2020-01-01,2020-12-31\n')
                imported=service.request('jobs.submit',{'spec':dict(projectId=project['id'],strategyId='default',kind='data.import',parameters={'files':[str(source)]})})
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    imported=service.store.get('job',imported['id'])
                    if imported['status'] in {'completed','failed'} and imported['id'] not in service.jobs.processes:break
                    time.sleep(.04)
                self.assertEqual(imported['status'],'completed',imported.get('message'))
                details=read_json(Path(project['path'])/'.research/runs'/imported['id']/'details.json')
                reference=details['imports'][0]['membershipRef']
                self.assertNotIn('membershipRef',service.store.project(project['id'])['universe'])
                self.assertNotIn('membershipRef',get_strategy('default')['universe'])
                listing=service.request('history.memberships.list',{'projectId':project['id']})
                self.assertIn(reference['version'],str(listing))
                self.assertNotIn(reference['version'],str(service.request('history.memberships.list',{'projectId':other['id']})))
                universe=service.request('history.memberships.apply',{'projectId':project['id'],'membershipRef':reference})
                self.assertEqual(universe['membershipRef'],reference)
                def submit(strategy_id=None):
                    spec=dict(projectId=project['id'],kind='factor.analyze',parameters={'factorIds':['momentum20'],'startDate':'2020-02-01','endDate':'2020-03-01'})
                    if strategy_id:spec['strategyId']=strategy_id
                    with patch.object(service.jobs,'_start_next'):
                        job=service.request('jobs.submit',{'spec':spec})
                    service.jobs.cancel(job['id'])
                    return job['spec']['projectSnapshot']
                fixed=submit()
                self.assertEqual(fixed['universe']['membershipRef'],reference)
                self.assertEqual(members(fixed,'2020-02-03'),{'SH600001'})
                self.assertEqual(members(submit(sibling['id']),'2020-02-03'),{'SH600000'})
                service.request('history.memberships.apply',{'projectId':project['id'],'strategyId':'default','membershipRef':reference})
                self.assertEqual(members(submit('default'),'2020-02-03'),{'SH600001'})
                self.assertEqual(get_strategy('default')['active'],active)
                self.assertEqual(get_strategy(sibling['id']),sibling)
                service.request('history.memberships.apply',{'projectId':project['id'],'membershipRef':None})
                self.assertNotIn('membershipRef',service.store.project(project['id'])['universe'])
                self.assertEqual(members(fixed,'2020-02-03'),{'SH600001'})
                self.assertEqual(members(submit('default'),'2020-02-03'),{'SH600001'})
                service.request('history.memberships.apply',{'projectId':project['id'],'strategyId':'default','membershipRef':None})
                self.assertEqual(members(submit('default'),'2020-02-03'),{'SH600000'})
                self.assertEqual(get_strategy('default')['active'],active)
                with self.assertRaises(ValueError):
                    service.request('history.memberships.apply',{'projectId':other['id'],'membershipRef':reference})
                self.assertEqual(service.store.project(other['id']),untouched_project)
            finally:
                service.close()
