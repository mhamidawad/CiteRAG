"""Unit tests for twenty bounded, provider-independent source preflight slots."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("worker_preflight", ROOT / "tasks/worker_preflight.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class TwentyWorkerTests(unittest.TestCase):
    def test_twenty_distinct_role_shard_pairs(self):
        slots = [worker.slot(index, 20) for index in range(20)]
        self.assertEqual(len(slots), 20)
        self.assertEqual(len(set(slots)), 20)
        self.assertEqual(set(role for role, _, _ in slots), set(worker.ROLES))
        self.assertEqual(set(shard for _, shard, _ in slots), set(range(4)))

    def test_invalid_workers_rejected(self):
        for index, total in ((-1, 20), (20, 20), (0, 5), (0, 19), (0, 21), (999, 20)):
            with self.subTest(index=index, total=total):
                with self.assertRaises(ValueError):
                    worker.slot(index, total)

    def test_all_twenty_preflights(self):
        for index in range(20):
            with self.subTest(index=index):
                result = worker.check(index, 20)
                self.assertEqual(result["status"], "preflight_pass")
                self.assertFalse(result["ai_inference"])
                self.assertFalse(result["writes_to_repository"])
                self.assertEqual(result["slot"], index)

    def test_existing_baseline_executes_unit_tests(self):
        workflow = (ROOT / ".github/workflows/tests.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("unittest discover", workflow)
        self.assertNotIn("matrix:", workflow)
