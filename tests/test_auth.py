"""Authentication contract for REST and streamable HTTP MCP services."""
import os
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from citerag.auth import BearerAuth, AuthenticationConfigurationError, validate_binding
from citerag.web import app as web_app
from citerag.server import mcp

TOKEN = "a" * 48

class AuthTests(unittest.TestCase):
    def test_fail_closed_external_bind_and_short_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AuthenticationConfigurationError):
                validate_binding("0.0.0.0")
            validate_binding("127.0.0.1")
        with patch.dict(os.environ, {"CITERAG_API_TOKEN": "short"}, clear=True):
            with self.assertRaises(AuthenticationConfigurationError):
                validate_binding("127.0.0.1")
        with patch.dict(os.environ, {"CITERAG_REQUIRE_AUTH": "1"}, clear=True):
            with self.assertRaises(AuthenticationConfigurationError):
                validate_binding("localhost")

    def test_rest_protected_paths_and_health(self):
        with patch.dict(os.environ, {"CITERAG_API_TOKEN": TOKEN}, clear=True):
            with TestClient(web_app) as client:
                self.assertEqual(client.get("/api/health").status_code, 200)
                for path in ("/", "/api/adapters", "/api/context", "/api/jobs/synthetic"):
                    with self.subTest(path=path):
                        r = client.get(path)
                        self.assertEqual(r.status_code, 401)
                        self.assertEqual(r.headers.get("cache-control"), "no-store")
                        self.assertEqual(client.get(path, headers={"Authorization": "Bearer wrong"}).status_code,401)
                self.assertEqual(client.post("/api/ask",json={"question":"test"}).status_code,401)
                self.assertEqual(client.get("/api/adapters",headers={"Authorization":"Bearer "+TOKEN}).status_code,200)

    def test_mcp_protected_before_session_initialization(self):
        mcp_app=mcp.streamable_http_app()
        mcp_app.add_middleware(BearerAuth)
        with patch.dict(os.environ, {"CITERAG_API_TOKEN": TOKEN}, clear=True):
            with TestClient(mcp_app) as client:
                self.assertEqual(client.post("/mcp", json={}).status_code,401)
                self.assertEqual(client.get("/mcp").status_code,401)
                r=client.post("/mcp",json={},headers={"Authorization":"Bearer "+TOKEN})
                self.assertNotEqual(r.status_code,401)

    def test_authenticated_client_missing_token_if_auth_required(self):
        with patch.dict(os.environ, {"CITERAG_REQUIRE_AUTH":"1"}, clear=True):
            with TestClient(web_app) as client:
                self.assertEqual(client.get("/api/adapters").status_code,401)

if __name__ == "__main__":
    unittest.main()
