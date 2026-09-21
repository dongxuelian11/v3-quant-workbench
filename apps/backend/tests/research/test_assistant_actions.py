import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from v3_backend.research.server import Service
from v3_backend.research.storage import identifier


class AssistantActionsTests(unittest.TestCase):
    def test_draft_preserves_unrelated_and_retry_does_not_submit_twice(self):
        with tempfile.TemporaryDirectory() as root:
            service = Service(Path(root))
            service.report_tasks.close()
            try:
                plan = service.request('screeners.save', dict(plan=dict(name='条件样本', mode='conditions',
                    universe=dict(source='manual', symbols=['SH600000'], excludeST=True, minListingDays=60),
                    conditions=dict(id='root', match='all', children=[
                        dict(id='price', field='close', operator='gt', value=5),
                        dict(id='volume', field='volume', operator='gt', value=100)]))))
                action = dict(kind='filter_patch', namespace='screeners', objectIds=[plan['id']],
                    conditions=dict(id='p', field='close', operator='gt', value=10))
                result = service.request('localAssistant.apply', dict(action=action, draft=plan))
                self.assertEqual(result['kind'], 'draft')
                self.assertEqual({r['field']:r['value'] for r in result['draft']['conditions']['children']},
                                 dict(close=10, volume=100))
                self.assertEqual(result['previousDraft'], plan)
                self.assertEqual(service.request('screeners.get', dict(id=plan['id'])), plan)
                ambiguous = deepcopy(plan); ambiguous['conditions']['match'] = 'any'
                self.assertEqual(service.request('localAssistant.apply', dict(action=action, draft=ambiguous))['kind'], 'clarify')
                submitted = []
                def submit(spec, frozen_project=None):
                    submitted.append(spec)
                    return service.store.put('job', dict(id=identifier(), status='queued', spec=spec))
                command = dict(action=dict(kind='run', namespace='screeners', objectIds=[plan['id']]), operationId='once')
                with patch.object(service.jobs, 'submit', side_effect=submit):
                    first = service.request('localAssistant.apply', command)
                    second = service.request('localAssistant.apply', command)
                self.assertEqual(first['jobs'][0]['id'], second['jobs'][0]['id'])
                self.assertEqual(len(submitted), 1)
            finally:
                service.close()
