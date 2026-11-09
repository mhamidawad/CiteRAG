import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from citerag import web, answer

class HealthAccuracyTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(web.app)
    @patch.object(web,"MODEL","")
    def test_no_generation_is_not_reported_connected(self):
        data=self.client.get("/api/health").json()
        self.assertEqual(data["status"],"ok")
        self.assertEqual(data["status_scope"],"HTTP process liveness only")
        self.assertEqual(data["generation"],"not_configured")
        self.assertIn(data["retrieval_index"],{"present","uninitialized"})
    @patch.object(answer,"MODEL",answer.LOCAL_MODEL)
    @patch.dict(web.os.environ,{"CITERAG_OMNIROUTE_API_KEY":"synthetic","CITERAG_OMNIROUTE_URL":answer.LOCAL_BASE,"CITERAG_BACKEND_ID":"test-backend"})
    def test_configured_is_not_claimed_verified(self):
        data=self.client.get("/api/health").json()
        self.assertEqual(data["generation"],"configured_not_verified")

    @patch.object(answer,"MODEL","unapproved-cloud-model")
    @patch.dict(web.os.environ,{"CITERAG_OMNIROUTE_API_KEY":"synthetic","CITERAG_OMNIROUTE_URL":"https://example.invalid","CITERAG_BACKEND_ID":"test-backend"})
    def test_unapproved_cloud_configuration_is_unavailable(self):
        self.assertEqual(self.client.get("/api/health").json()["generation"],"not_configured")
        option=next(a for a in self.client.get("/api/adapters").json()["adapters"] if a["name"]=="omniroute")
        self.assertFalse(option["available"])
