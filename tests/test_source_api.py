import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from citerag import web

class SourceAPITests(unittest.TestCase):
    def test_approved_inventory_and_no_arbitrary_path(self):
        with patch("citerag.repository_sources.source_status",return_value=[{"name":"sample","state":"ready"}]):
            c=TestClient(web.app)
            self.assertEqual(c.get("/api/sources").json()["sources"][0]["name"],"sample")
            self.assertEqual(c.post("/api/reindex",json={"path":"/etc"}).status_code,400)
    def test_reindex_success_failure_and_lock(self):
        c=TestClient(web.app)
        with patch.object(web,"prepare_context",return_value={"status":"completed","corpus_version":"a"}):
            r=c.post("/api/reindex",json={});self.assertEqual(r.status_code,202)
            self.assertEqual(c.get("/api/jobs/"+r.json()["job_id"]).json()["state"],"completed")
        with patch.object(web,"prepare_context",side_effect=RuntimeError("private-path")):
            r=c.post("/api/reindex",json={})
            body=c.get("/api/jobs/"+r.json()["job_id"]).json()
            self.assertEqual(body["state"],"failed");self.assertNotIn("private-path",str(body))
        web._generation.acquire()
        try:self.assertEqual(c.post("/api/reindex",json={}).status_code,409)
        finally:web._generation.release()
    def test_legacy_generation_cannot_bypass_readiness(self):
        c=TestClient(web.app)
        with patch.object(web,"native_status",return_value="unavailable"):
            self.assertEqual(c.post("/api/ask",json={"question":"test","use_native":True}).status_code,503)
