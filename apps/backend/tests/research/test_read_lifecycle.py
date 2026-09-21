"""Service registration and cancellation ordering, separate from batch helpers."""
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from v3_backend.research.server import Service


class ReadLifecycle(unittest.TestCase):
    def test_queued_request_cancelled_before_route_other_request_still_works(self):
        with tempfile.TemporaryDirectory() as root:
            service = Service(root)
            entered, release = threading.Event(), threading.Event()
            def hold():
                entered.set()
                release.wait(5)
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(hold)
                    self.assertTrue(entered.wait(2))
                    params = {'readId': 'queued'}
                    operation = service.read_operations.begin('experiments.table', params)
                    with patch.object(service, '_request', return_value={'rows': []}) as route:
                        pending = pool.submit(service.request, 'experiments.table', params, read_operation=operation)
                        self.assertEqual(service.request('reads.cancel', params), {'requested': True})
                        release.set()
                        with self.assertRaisesRegex(InterruptedError, '读取已取消'):
                            pending.result(3)
                        route.assert_not_called()
                        self.assertEqual(service.request('experiments.table', {'readId': 'next'}), {'rows': []})
                self.assertEqual(service.request('reads.cancel', params), {'requested': False})
            finally:
                release.set()
                service.close()

    def test_running_request_cancelled_but_commit_is_not_retracted(self):
        with tempfile.TemporaryDirectory() as root:
            service = Service(root)
            entered, release = threading.Event(), threading.Event()
            def work(method, params):
                entered.set()
                release.wait(5)
                service.check_read_cancel()
            try:
                with ThreadPoolExecutor(max_workers=1) as pool, patch.object(service, '_request', side_effect=work):
                    pending = pool.submit(service.request, 'experiments.analysis', {'readId': 'running'})
                    self.assertTrue(entered.wait(2))
                    self.assertTrue(service.request('reads.cancel', {'readId': 'running'})['requested'])
                    release.set()
                    with self.assertRaises(InterruptedError):
                        pending.result(3)
                def committed(method, params):
                    service.read_operations.cancel(params['readId'])
                    return {'path': 'committed.csv'}
                with patch.object(service, '_request', side_effect=committed):
                    self.assertEqual(service.request('exports.create', {'readId': 'done'}), {'path': 'committed.csv'})
                self.assertFalse(service.request('reads.cancel', {'readId': 'done'})['requested'])
            finally:
                release.set()
                service.close()


if __name__ == '__main__':
    unittest.main()
