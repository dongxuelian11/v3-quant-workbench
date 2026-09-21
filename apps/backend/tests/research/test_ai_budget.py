import asyncio
import unittest

import httpx
from openai import AsyncOpenAI
from v3_backend.research.ai_budget import consume_model_request, model_budget, budget_failure
from v3_backend.research.ai_execution import temporary_failure


class ModelBudgetTests(unittest.TestCase):
    def test_worker_actual_computations_share_plan_budget(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from v3_backend.research.storage import Store
        from v3_backend.research.ai_budget import ensure_budget, read_budget, observe_computation
        from v3_backend.research.worker import execute
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root))
            db = store.project_store(None).db
            ensure_budget(db, 'shared')
            job = dict(kind='model.train', spec=dict(parameters=dict(budgetId='shared', budgetProjectId=None)))
            def compute(*args):
                observe_computation('trainingTasks')
                observe_computation('backtestTasks')
                return {'done': True}
            with patch('v3_backend.research.worker._prepared_execute', side_effect=compute):
                execute(store, job, {}, root, lambda *_: None)
                execute(store, job, {}, root, lambda *_: None)
            budget = read_budget(db, 'shared')
            self.assertEqual(budget['used']['trainingTasks'], 2)
            self.assertEqual(budget['used']['backtestTasks'], 2)
            self.assertEqual(budget['used']['modelRequests'], 0)

    def test_failed_wire_attempts_and_continuation_share_ceiling(self):
        async def run():
            state = {'modelBudget': {'limit': 2, 'used': 0, 'scope': 'execution'}}
            sent = []
            async def count(request):
                consume_model_request(state)
            def wire(request):
                sent.append(request)
                return httpx.Response(429, json={'error': {'message': 'limited', 'type': 'rate_limit'}})
            client = AsyncOpenAI(base_url='https://offline.invalid/v1', api_key='offline', max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(wire), event_hooks={'request': [count]}))
            try:
                for _ in range(2):
                    with self.assertRaises(Exception) as caught:
                        await client.chat.completions.create(model='offline', messages=[{'role': 'user', 'content': 'test'}])
                    self.assertTrue(temporary_failure(caught.exception))
                state['modelBudget'] = model_budget(state['modelBudget'])
                with self.assertRaises(Exception) as caught:
                    await client.chat.completions.create(model='offline', messages=[{'role': 'user', 'content': 'continue'}])
                self.assertIsNotNone(budget_failure(caught.exception))
                self.assertFalse(temporary_failure(caught.exception))
                self.assertEqual(len(sent), 2)
                self.assertEqual(state['modelBudget']['used'], 2)
            finally:
                await client.close()
        asyncio.run(run())


class SharedBudgetTests(unittest.TestCase):
    def test_atomic_wire_ceiling_and_restart(self):
        import tempfile
        from pathlib import Path
        from concurrent.futures import ThreadPoolExecutor
        from v3_backend.research.storage import Store
        from v3_backend.research.ai_budget import ensure_budget,reserve,read_budget,BudgetExhausted
        with tempfile.TemporaryDirectory() as temp:
            db=Store(Path(temp)).db
            ensure_budget(db,'plan',{'modelRequests':7})
            def attempt(_):
                try:reserve(db,'plan','modelRequests');return True
                except BudgetExhausted:return False
            with ThreadPoolExecutor(max_workers=8) as pool:self.assertEqual(sum(pool.map(attempt,range(20))),7)
            self.assertEqual(ensure_budget(db,'plan')['used']['modelRequests'],7)
            with self.assertRaises(BudgetExhausted):reserve(db,'plan','modelRequests')
            reserve(db,'plan','candidateGroups',operation_id='native:group:1')
            reserve(db,'plan','candidateGroups',operation_id='native:group:1')
            self.assertEqual(read_budget(db,'plan')['used']['candidateGroups'],1)
            with self.assertRaises(ValueError):reserve(db,'plan','trials',operation_id='native:group:1')
            with self.assertRaises(ValueError):ensure_budget(db,'plan',{'modelRequests':8})
            self.assertNotIn('rollingWindows',read_budget(db,'plan')['used'])
