import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from citerag import web

class AdapterContractTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(web.app)
    def test_registry(self):
        r=self.client.get("/api/adapters")
        self.assertEqual(r.status_code,200)
        self.assertEqual({x["name"] for x in r.json()["adapters"]},{"opencode","omniroute","retrieval-only"})
    @patch.object(web,"prepare_context")
    @patch.object(web,"search")
    @patch.object(web,"answer")
    def test_bad_adapter_has_no_side_effects(self,answer,search,fresh):
        for payload in ({"adapter":"unknown"},{"adapter":"omniroute","adapter_config":{"api_key":"never"}},{"adapter":"retrieval-only","adapter_config":"invalid"}):
            self.assertEqual(self.client.post("/api/ask",json={"question":"Question",**payload}).status_code,400)
        answer.assert_not_called()
        search.assert_not_called()
        fresh.assert_not_called()
        self.assertFalse(web._generation.locked())
    @patch.object(web,"prepare_context",return_value={"status":"completed"})
    @patch.object(web,"search",return_value=[])
    def test_named_retrieval_only_offline(self,search,fresh):
        response=self.client.post("/api/ask",json={"question":"Unknown","adapter":"retrieval-only"})
        self.assertEqual(response.status_code,202)
        result=self.client.get("/api/jobs/"+response.json()["job_id"]).json()
        self.assertEqual(result["status"],"insufficient_evidence")
        self.assertEqual(result["mode"],"retrieval_only")
