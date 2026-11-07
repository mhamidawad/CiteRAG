"""Five distinct fail-closed CircleCI worker preflight slots."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("circleci_worker",ROOT/"tasks/circleci_worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

class FiveWorkerTests(unittest.TestCase):
    def test_exact_five_roles(self):
        self.assertEqual(tuple(worker.slot(i,5) for i in range(5)),
            ("planner","retrieval","tests","security","review"))

    def test_invalid_workers_rejected(self):
        for i,n in ((-1,5),(5,5),(0,4),(0,6)):
            with self.subTest(i=i,n=n):
                with self.assertRaises(ValueError):
                    worker.slot(i,n)

    def test_all_five_preflights(self):
        for index in range(5):
            with self.subTest(slot=index):
                result=worker.check(index,5)
                self.assertEqual(result["status"],"preflight_pass")
                self.assertFalse(result["ai_inference"])

    def test_manual_only_pipeline(self):
        text=(ROOT/".circleci/config.yml").read_text()
        self.assertIn("parallelism: 5",text)
        self.assertIn("default: false",text)
        self.assertIn("when: << pipeline.parameters.run_workers >>",text)
