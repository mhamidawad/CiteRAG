"""Release publication must consume exact-source verification in one bounded runner."""
import re
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())

class ReleaseWorkflowGates(unittest.TestCase):
    def test_refresh_is_bounded_main_only_and_handles_missing_credential(self):
        workflow = load("context7-refresh.yml")
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(triggers["push"]["branches"], ["main"])
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["refresh"]
        self.assertLessEqual(job["timeout-minutes"], 3)
        step = job["steps"][0]
        self.assertIn("CONTEXT7_API_KEY", step["env"])
        self.assertNotIn("${{ secrets.", step["run"])
        for required in ("--fail", "--max-time 60", "--connect-timeout 10", "exit 0"):
            self.assertIn(required, step["run"])

    def test_release_tests_and_security_audits_precede_registry_login(self):
        workflow = load("publish.yml")
        self.assertEqual(set(workflow["jobs"]), {"publish"})
        job = workflow["jobs"]["publish"]
        self.assertEqual(job["if"], "github.ref == 'refs/heads/main'")
        self.assertNotIn("strategy", job)
        steps = job["steps"]
        commands = "\n".join(step.get("run", "") for step in steps)
        login = commands.index("docker login ghcr.io")
        for required in ("unittest discover", "compileall", "verify-retrieval.py", "pip-audit", "--severity HIGH,CRITICAL", "--exit-code 1"):
            self.assertLess(commands.index(required), login)
        self.assertIn("--label \"org.opencontainers.image.revision=", commands)
        self.assertIn("aquasec/trivy@sha256:", commands)
        self.assertNotIn("--ignore-unfixed", commands)
        self.assertIn("image-audit-raw.json",commands)
        self.assertIn("--vex /evidence/dhi-python-exact.vex.json",commands)
        self.assertIn("fetch-vendor-vex.py",commands)
        self.assertIn("derive-vendor-vex.py",commands)
        self.assertLess(commands.index("image-audit-raw.json"),commands.index("derive-vendor-vex.py"))
        self.assertLess(commands.index("derive-vendor-vex.py"),commands.index("--vex /evidence/dhi-python-exact.vex.json"))
        self.assertTrue(any(step.get("if") == "always()" and "upload-artifact@" in step.get("uses", "") for step in steps))

    def test_release_actions_and_base_image_are_immutable(self):
        for step in load("publish.yml")["jobs"]["publish"]["steps"]:
            if "uses" in step:
                self.assertRegex(step["uses"], r"@[a-f0-9]{40}$")
        dockerfile = (ROOT / "Dockerfile").read_text()
        for variant in ("BUILD", "RUNTIME"):
            self.assertRegex(dockerfile, rf"(?m)^ARG PYTHON_{variant}_BASE=dhi\.io/python:[^\s]+@sha256:[a-f0-9]{{64}}$")
        self.assertIn("FROM ${PYTHON_BUILD_BASE} AS wheels", dockerfile)
        self.assertIn("FROM ${PYTHON_RUNTIME_BASE} AS runtime", dockerfile)
        runtime = dockerfile.split(" AS runtime", 1)[1]
        self.assertNotRegex(runtime, r"(?m)^RUN\s")
        self.assertIn("PYTHONPATH=/app/python-packages", runtime)
        self.assertIn("USER 65532:65532", runtime)

    def test_clean_dependency_baseline_accepts_actual_model_retrieval(self):
        steps=load("tests.yml")["jobs"]["unit"]["steps"]
        checks=[step for step in steps if "Verify real MiniLM" in step.get("name", "")]
        self.assertEqual(len(checks),1)
        step=checks[0]
        self.assertEqual(step["env"]["CITERAG_OFFLINE"],"1")
        self.assertIn("HF_HUB_OFFLINE=1 python tasks/verify-retrieval.py",step["run"])
        self.assertRegex(step["run"],r'revision="[a-f0-9]{40}"')

    def test_release_dependency_lock_rejects_unpinned_or_unhashed_inputs(self):
        lock=(ROOT / "requirements.lock.txt").read_text()
        self.assertIn("--require-hashes",lock)
        self.assertIn("--only-binary=:all:",lock)
        logical=lock.replace("\\\n", " ").splitlines()
        packages=[]
        for line in logical:
            if not line.strip() or line.lstrip().startswith(("#", "--")):
                continue
            self.assertRegex(line,r"^[a-zA-Z0-9_.-]+==[a-zA-Z0-9.+-]+\s+--hash=sha256:[a-f0-9]{64}")
            self.assertNotIn("://",line)
            packages.append(line.split("==",1)[0])
        self.assertGreater(len(packages),60)
        self.assertEqual(len(packages),len(set(packages)))
        self.assertIn("torch==2.15.0+cpu",lock)

    def test_native_acceptance_profile_is_in_release_image(self):
        dockerfile=(ROOT / "Dockerfile").read_text()
        self.assertIn("configs /app/configs",dockerfile)
