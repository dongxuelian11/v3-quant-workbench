import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from v3_backend.research.storage import write_json,read_json


class StorageRetryTest(unittest.TestCase):
    def test_transient_windows_replace_and_bounded_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'progress.json'
            original = os.replace
            error = PermissionError('temporary sharing conflict')
            error.winerror = 5
            attempts = []
            def replace(source,target):
                attempts.append(1)
                if len(attempts)<3:
                    raise error
                return original(source,target)
            with patch('v3_backend.research.storage.os.replace',side_effect=replace), patch('v3_backend.research.storage.time.sleep') as sleep:
                write_json(path,{'progress':.73})
                self.assertEqual(sleep.call_count,2)
            self.assertEqual(read_json(path),{'progress':.73})
            with patch('v3_backend.research.storage.os.replace',side_effect=error) as fail, patch('v3_backend.research.storage.time.sleep'):
                with self.assertRaises(PermissionError):
                    write_json(path,{'progress':1})
                self.assertEqual(fail.call_count,5)
            self.assertEqual(read_json(path),{'progress':.73})
