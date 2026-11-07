import tempfile
import unittest
from pathlib import Path
from citerag.inference_lock import inference_lock,InferenceBusy

class InferenceLockTests(unittest.TestCase):
    def test_second_owner_is_rejected_and_release_works(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'lock'
            with inference_lock(path):
                with self.assertRaises(InferenceBusy):
                    with inference_lock(path):pass
            with inference_lock(path):pass
    def test_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'lock'
            with self.assertRaises(ValueError):
                with inference_lock(path):raise ValueError('test')
            with inference_lock(path):pass
