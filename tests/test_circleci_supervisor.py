"""Fail-closed CircleCI Supervisor controller unit tests; no external network."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

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

    def test_recent_created_pipeline_without_workflow_denies_dispatch(self):
        now = datetime.now(timezone.utc).isoformat()
        getter,calls=self.service([{"id":"p1","number":4,"state":"created",
                                   "created_at":now}],[])
        with self.assertRaises(c.GateError):c.trigger("fake",getter)

    def test_stale_empty_workflow_and_errored_pipeline_are_terminal(self):
        old = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        getter,calls=self.service([{"id":"p1","number":4,"state":"created",
                                   "created_at":old},
                                  {"id":"p2","number":5,"state":"errored"}],[])
        self.assertTrue(c.inspect("fake",getter)["can_dispatch"])

    def test_missing_timestamp_denies_dispatch(self):
        getter,calls=self.service([{"id":"p1","number":4,"state":"created"}],[])
        with self.assertRaises(c.GateError):c.trigger("fake",getter)

    def test_pagination_without_second_page_denies_dispatch(self):
        getter,calls=self.service(fail="paginate")
        with self.assertRaises((c.GateError, AssertionError)):c.trigger("fake",getter)

    def test_paginated_history_is_checked(self):
        calls=[]
        old = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        def get(token,method,path,body=None):
            calls.append(path)
            if path=="me":return {"id":"safe"}
            if path=="project/"+c.PROJECT:return {
                "id":"92a7b55f-2fa6-4db1-88f2-7437c381c958","name":"supervisor"}
            if path=="project/"+c.PROJECT+"/pipeline":
                return {"items":[{"id":"p1","number":1,"state":"created",
                                   "created_at":old}],"next_page_token":"page2"}
            if path=="project/"+c.PROJECT+"/pipeline?page-token=page2":
                return {"items":[{"id":"p2","number":2,"state":"errored"}]}
            if path=="pipeline/p1/workflow":return {"items":[]}
            raise AssertionError(path)
        result=c.inspect("fake",get)
        self.assertEqual(result["examined_pipelines"],2)
        self.assertTrue(result["can_dispatch"])
        self.assertIn("project/"+c.PROJECT+"/pipeline?page-token=page2",calls)

    def test_repeated_pagination_token_fails_closed(self):
        old=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        def get(token,method,path,body=None):
            if path=="me":return {"id":"safe"}
            if path=="project/"+c.PROJECT:return {
                "id":"92a7b55f-2fa6-4db1-88f2-7437c381c958","name":"supervisor"}
            if "/pipeline" in path:return {
                "items":[{"id":"p1","state":"created","number":1,"created_at":old}],
                "next_page_token":"repeat"}
            raise AssertionError(path)
        with self.assertRaises(c.GateError): c.inspect("fake",get)

    def test_auth_failure_prevents_dispatch(self):
        def rejected(*args,**kwargs):raise c.GateError("CircleCI API HTTP 401")
        with self.assertRaisesRegex(c.GateError, "401"):c.trigger("fake",rejected)

    def test_cli_default_requires_explicit_confirmation(self):
        self.assertEqual(c.main(["dispatch"]),2)

if __name__ == "__main__":
    unittest.main()
