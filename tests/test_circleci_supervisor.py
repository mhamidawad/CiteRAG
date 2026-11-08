"""Fail-closed CircleCI Supervisor controller unit tests; no external network."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("circleci_supervisor", ROOT / "tasks/circleci_supervisor.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class ControllerTests(unittest.TestCase):
    def test_token_file_is_not_executed_and_permissions_restricted(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "token.env"
            p.write_text("CIRCLECI_TOKEN=CCIPAT_safevalue\n")
            p.chmod(0o600)
            self.assertEqual(c.token_from_file(p), "CCIPAT_safevalue")
            p.write_text('CIRCLECI_TOKEN=$(touch /tmp/this-must-not-be-executed)\n')
            with self.assertRaises(c.GateError): c.token_from_file(p)
            p.write_text("CIRCLECI_TOKEN=CCIPAT_safevalue\n")
            p.chmod(0o644)
            with self.assertRaises(c.GateError): c.token_from_file(p)

    def service(self, pipelines=None, workflows=None, fail=None):
        calls=[]
        def getter(token, method, path, body=None):
            calls.append((method,path,body))
            if path == "me":return {"id":"fake"}
            if path == "project/" + c.PROJECT:
                return {"id":"92a7b55f-2fa6-4db1-88f2-7437c381c958","name":"supervisor"}
            if path == "project/" + c.PROJECT + "/pipeline":
                if fail == "paginate":return {"items":[],"next_page_token":"nonempty"}
                return {"items": pipelines or []}
            if path.startswith("pipeline/") and path.endswith("/workflow"):
                return {"items": workflows or []}
            if method == "POST":return {"id":"created-test","number":9,"state":"pending"}
            raise AssertionError("unanticipated API call")
        return getter,calls

    def test_no_active_pipeline_dispatches_one_bounded_run(self):
        getter,calls=self.service()
        result=c.trigger("fake",getter)
        self.assertEqual(result["slots_requested"],20)
        posts=[call for call in calls if call[0]=="POST"]
        self.assertEqual(len(posts),1)
        self.assertEqual(posts[0][2]["parameters"],{"run_workers":True})
        self.assertEqual(posts[0][2]["checkout"]["branch"],c.BRANCH)

    def test_active_workflow_denies_dispatch(self):
        getter,calls=self.service([{"id":"p1","number":4,"state":"created"}],
                                  [{"name":"manual_supervisor_preflight","status":"running"}])
        with self.assertRaises(c.GateError):c.trigger("fake",getter)
        self.assertFalse(any(x[0]=="POST" for x in calls))

    def test_created_pipeline_without_workflow_denies_dispatch(self):
        getter,calls=self.service([{"id":"p1","number":4,"state":"created"}],[])
        with self.assertRaises(c.GateError):c.trigger("fake",getter)

    def test_pagination_denies_dispatch(self):
        getter,calls=self.service(fail="paginate")
        with self.assertRaises(c.GateError):c.trigger("fake",getter)

    def test_auth_failure_prevents_dispatch(self):
        def rejected(*args,**kwargs):raise c.GateError("CircleCI API HTTP 401")
        with self.assertRaisesRegex(c.GateError, "401"):c.trigger("fake",rejected)

    def test_cli_default_requires_explicit_confirmation(self):
        self.assertEqual(c.main(["dispatch"]),2)

if __name__ == "__main__":
    unittest.main()
