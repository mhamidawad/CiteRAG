import unittest
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]

class SafeWorkersTest(unittest.TestCase):
    def test_workers_never_deploy(self):
        c=yaml.safe_load((ROOT/".circleci/config.yml").read_text())
        self.assertEqual(set(c["parameters"]),{"run_workers"})
        self.assertIs(c["parameters"]["run_workers"]["default"],False)
        self.assertEqual(set(c["jobs"]),{"supervisor_worker_preflight"})
        j=c["jobs"]["supervisor_worker_preflight"]
        self.assertEqual(j["parallelism"],20)
        self.assertEqual([list(x)[0] if isinstance(x,dict) else x for x in j["steps"]],["checkout","run","store_artifacts"])
        self.assertEqual(j["steps"][1]["run"]["command"],"python tasks/circleci_worker.py")
        self.assertEqual(set(c["workflows"]),{"manual_supervisor_preflight"})
        self.assertEqual(c["workflows"]["manual_supervisor_preflight"]["jobs"],["supervisor_worker_preflight"])
        self.assertNotIn("deploy",str(c).lower())
        self.assertNotIn("rollback",str(c).lower())
