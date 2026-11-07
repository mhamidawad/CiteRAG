"""Thirty distinct fail-closed CircleCI worker preflight slots."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("circleci_worker",ROOT/"tasks/circleci_worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

class ThirtyWorkerTests(unittest.TestCase):
    def test_thirty_distinct_role_shard_pairs(self):
        slots=[worker.slot(i,30) for i in range(30)]
        self.assertEqual(len(slots),30)
        self.assertEqual(len(set(slots)),30)
        self.assertEqual(set(role for role,_,_ in slots),set(worker.ROLES))
        self.assertEqual(set(shard for _,shard,_ in slots),set(range(6)))

    def test_invalid_workers_rejected(self):
        for i,n in ((-1,30),(30,30),(0,5),(0,29),(0,31),(999,30)):
            with self.subTest(i=i,n=n):
                with self.assertRaises(ValueError):
                    worker.slot(i,n)

    def test_all_thirty_preflights(self):
        for index in range(30):
            with self.subTest(slot=index):
                result=worker.check(index,30)
                self.assertEqual(result["status"],"preflight_pass")
                self.assertFalse(result["ai_inference"])
                self.assertFalse(result["writes_to_repository"])
                self.assertEqual(result["slot"],index)

    def test_manual_only_pipeline(self):
        text=(ROOT/".circleci/config.yml").read_text()
        self.assertIn("parallelism: 30",text)
        self.assertIn("default: false",text)
        self.assertIn("when: << pipeline.parameters.run_workers >>",text)
        self.assertIn("resource_class: small",text)
