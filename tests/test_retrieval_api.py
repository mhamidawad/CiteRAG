import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from citerag import web
from citerag.native_result import ABSTENTION

class OfflineApiTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(web.app)
    @patch.object(web,"prepare_context",return_value={"status":"completed"})
    @patch.object(web,"search",return_value=[{"source":"docs/sample.md","id":"a"*64,"text":"OpenCode coding agents use source-cited retrieval."}])
    def test_offline_answer_has_grounded_citation(self,search,fresh):
        response=self.client.post("/api/ask",json={"question":"OpenCode coding agents","adapter":"retrieval-only"})
        self.assertEqual(response.status_code,202)
        job=self.client.get("/api/jobs/"+response.json()["job_id"]).json()
        self.assertEqual(job["status"],"completed")
        self.assertTrue(job["citations_verified"])
        self.assertTrue(job["claims_supported"])
        self.assertIn("docs/sample.md",job["answer"])
        self.assertIn("a"*64,job["answer"])
    @patch.object(web,"prepare_context",return_value={"status":"completed"})
    @patch.object(web,"search",return_value=[])
    def test_unsupported_abstains_exactly(self,search,fresh):
        response=self.client.post("/api/ask",json={"question":"Quantum jellyfish","adapter":"retrieval-only"})
        job=self.client.get("/api/jobs/"+response.json()["job_id"]).json()
        self.assertEqual(job["answer"],ABSTENTION)
