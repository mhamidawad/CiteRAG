"""Exercise actual dashboard JavaScript with the built-in Node VM; no npm dependencies."""
import pathlib
import shutil
import subprocess
import unittest

class DashboardBehaviorTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node runtime required for dashboard behavior")
    def test_browser_contract(self):
        result = subprocess.run(
            ["node", str(pathlib.Path(__file__).with_name("dashboard_behavior.cjs"))],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Dashboard behavior PASS", result.stdout)
