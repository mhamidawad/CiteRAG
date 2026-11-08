"""Ensure the existing GitHub workflow is sufficient: no extra hosted-runner fanout."""
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


class GitHubWorkflowSafety(unittest.TestCase):
    def test_existing_baseline_only_single_runner(self):
        source = (ROOT / ".github/workflows/tests.yml").read_text()
        workflow = yaml.safe_load(source)
        triggers = workflow.get("on", workflow.get(True))
        self.assertIn("workflow_dispatch", triggers)
        self.assertIn("push", triggers)
        self.assertIn("pull_request", triggers)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow["jobs"]), {"unit"})
        unit = workflow["jobs"]["unit"]
        self.assertIn("runs-on", unit)
        self.assertNotIn("strategy", unit)
        commands = "\n".join(step.get("run", "") for step in unit["steps"] if isinstance(step, dict))
        self.assertIn("unittest discover", commands)
        self.assertNotIn("deploy", commands.lower())
        self.assertNotIn("docker run", commands)

    def test_no_external_ci_or_additional_workflow(self):
        self.assertFalse((ROOT / ".circleci/config.yml").is_file())
        self.assertFalse((ROOT / "tasks/circleci_supervisor.py").exists())
        self.assertFalse((ROOT / "tasks/circleci_v3_verify.py").exists())
        self.assertFalse((ROOT / ".github/workflows/worker-preflight.yml").exists())
