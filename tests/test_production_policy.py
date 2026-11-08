"""Production boundaries must reject before the backend sees a request."""
import concurrent.futures
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from citerag.auth import BearerAuth, validate_binding, AuthenticationConfigurationError
from citerag.policy import admit

TOKEN = "synthetic-production-policy-" + "x" * 40

async def echo(request: Request):
    data = await request.json() if request.method == "POST" else {}
    return JSONResponse({"received": data})

class ProductionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = {"CITERAG_API_TOKEN": TOKEN, "CITERAG_PRODUCTION": "1",
                    "CITERAG_WORKSPACE_ID": "tenant-a", "CITERAG_RATE_LIMIT_PER_MINUTE": "20",
                    "CITERAG_GENERATION_LIMIT_PER_DAY": "2",
                    "CITERAG_POLICY_DB": str(Path(self.temp.name) / "policy.sqlite3")}
        self.patch = patch.dict(os.environ, self.env, clear=True)
        self.patch.start()
        self.app = Starlette(routes=[Route("/api/ask", echo, methods=["POST"]),
                                     Route("/mcp", echo, methods=["POST"]),
                                     Route("/api/reindex", echo, methods=["POST"]),
                                     Route("/api/context", echo),
                                     Route("/api/jobs/test", echo)])
        self.app.add_middleware(BearerAuth)
        self.client = TestClient(self.app, headers={"Authorization": "Bearer " + TOKEN})

    def tearDown(self):
        self.client.close()
        self.patch.stop()
        self.temp.cleanup()

    def test_production_requires_explicit_workspace_budgets_and_auth(self):
        validate_binding("0.0.0.0")
        for key in ("CITERAG_API_TOKEN", "CITERAG_WORKSPACE_ID", "CITERAG_POLICY_DB",
                    "CITERAG_RATE_LIMIT_PER_MINUTE", "CITERAG_GENERATION_LIMIT_PER_DAY"):
            with self.subTest(key=key), patch.dict(os.environ, {key: ""}):
                with self.assertRaises(AuthenticationConfigurationError):
                    validate_binding("127.0.0.1")

    def test_wrong_workspace_header_query_and_body_denied(self):
        self.assertEqual(self.client.get("/api/context", headers={"X-CiteRAG-Workspace": "tenant-b"}).status_code, 403)
        self.assertEqual(self.client.get("/api/context?workspace=tenant-b").status_code, 403)
        for key in ("workspace", "workspace_id"):
            self.assertEqual(self.client.post("/api/ask", json={key: "tenant-b"}).status_code, 403)
        self.assertEqual(self.client.post("/mcp", json={"method": "tools/call", "params": {
            "arguments": {"workspace": "tenant-b"}}}).status_code, 403)

    def test_authorized_body_forwarded_unchanged(self):
        payload = {"question": "test", "adapter": "retrieval-only", "workspace": "tenant-a"}
        response = self.client.post("/api/ask", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["received"], payload)
        rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "rag_search", "arguments": {"query": "hello"}}}
        self.assertEqual(self.client.post("/mcp", json=rpc).json()["received"], rpc)

    def test_generation_day_budget_survives_client_restart(self):
        for _ in range(2):
            self.assertEqual(self.client.post("/api/ask", json={"adapter": "opencode"}).status_code, 200)
        with TestClient(self.app, headers={"Authorization": "Bearer " + TOKEN}) as second:
            self.assertEqual(second.post("/api/ask", json={"adapter": "omniroute"}).status_code, 429)
            self.assertEqual(second.post("/api/ask", json={"adapter": "retrieval-only"}).status_code, 200)

    def test_polling_and_retrieval_do_not_charge_generation(self):
        with patch.dict(os.environ, {"CITERAG_RATE_LIMIT_PER_MINUTE": "3"}):
            for _ in range(30):
                self.assertEqual(self.client.get("/api/jobs/test").status_code, 200)
            self.assertEqual(self.client.post("/api/ask", json={"retrieval_only": True}).status_code, 200)
            self.assertEqual(self.client.post("/mcp", json={"method": "tools/call"}).status_code, 200)
            self.assertEqual(self.client.post("/api/ask", json={"adapter": "opencode"}).status_code, 200)
            self.assertEqual(self.client.post("/api/ask", json={"adapter": "retrieval-only"}).status_code, 429)

    def test_reindex_shares_rate_budget_without_charging_generation(self):
        with patch.dict(os.environ, {"CITERAG_RATE_LIMIT_PER_MINUTE": "3",
                                     "CITERAG_GENERATION_LIMIT_PER_DAY": "1"}):
            self.assertEqual(self.client.post("/api/reindex", json={}).status_code, 200)
            self.assertEqual(self.client.post("/api/reindex", json={}).status_code, 200)
            self.assertEqual(self.client.post("/api/ask", json={"adapter": "opencode"}).status_code, 200)
            self.assertEqual(self.client.post("/api/reindex", json={}).status_code, 429)

    def test_reindex_workspace_override_denied_before_admission(self):
        with patch.dict(os.environ, {"CITERAG_RATE_LIMIT_PER_MINUTE": "1"}):
            self.assertEqual(self.client.post("/api/reindex", json={"workspace": "tenant-b"}).status_code, 403)
            response = self.client.post("/api/reindex", json={})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["received"], {})

    def test_mcp_initialization_does_not_charge_tool_budget(self):
        with patch.dict(os.environ, {"CITERAG_RATE_LIMIT_PER_MINUTE": "1"}):
            for method in ("initialize", "notifications/initialized"):
                self.assertEqual(self.client.post("/mcp", json={"method": method}).status_code, 200)
            self.assertEqual(self.client.post("/mcp", json={"method": "tools/call"}).status_code, 200)
            self.assertEqual(self.client.post("/mcp", json={"method": "tools/call"}).status_code, 429)

    def test_rejects_oversized_body(self):
        self.assertEqual(self.client.post("/api/ask", content=b"x" * 65537).status_code, 413)

    def test_unavailable_policy_fails_closed(self):
        with patch.dict(os.environ, {"CITERAG_POLICY_DB": "/missing-production-policy/ledger.db"}):
            self.assertEqual(self.client.post("/api/ask", json={"retrieval_only": True}).status_code, 503)
        with patch.dict(os.environ, {"CITERAG_RATE_LIMIT_PER_MINUTE": "0"}):
            self.assertEqual(self.client.get("/api/context").status_code, 503)

    def test_concurrent_admission_has_one_shared_limit(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: admit(self.env["CITERAG_POLICY_DB"], "tenant-a",
                {"CITERAG_RATE_LIMIT_PER_MINUTE": 5}, now=120), range(20)))
        self.assertEqual(sum(results), 5)

    def test_budget_renews_at_window_boundary(self):
        db = self.env["CITERAG_POLICY_DB"]
        limits = {"CITERAG_RATE_LIMIT_PER_MINUTE": 1}
        self.assertTrue(admit(db, "tenant-a", limits, now=60))
        self.assertFalse(admit(db, "tenant-a", limits, now=119))
        self.assertTrue(admit(db, "tenant-a", limits, now=120))

if __name__ == "__main__":
    unittest.main()
