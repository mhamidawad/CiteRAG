import os
import unittest
from unittest.mock import patch

from citerag.server import transport_security_settings


class MCPTransportSecurityTests(unittest.TestCase):
    def test_default_allows_only_localhost_hosts_and_no_origins(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = transport_security_settings()
        self.assertEqual(settings.allowed_hosts, ["127.0.0.1:*", "localhost:*"])
        self.assertEqual(settings.allowed_origins, [])
        self.assertTrue(settings.enable_dns_rebinding_protection)

    def test_configured_tailnet_host_and_origin_are_exact(self):
        with patch.dict(os.environ, {
            "CITERAG_MCP_ALLOWED_HOSTS": "127.0.0.1:*,localhost:*,citerag.example.invalid:8443",
            "CITERAG_MCP_ALLOWED_ORIGINS": "https://citerag.example.invalid:8443",
        }, clear=True):
            settings = transport_security_settings()
        self.assertEqual(settings.allowed_hosts[-1], "citerag.example.invalid:8443")
        self.assertEqual(settings.allowed_origins, ["https://citerag.example.invalid:8443"])
        self.assertTrue(settings.enable_dns_rebinding_protection)

    def test_rejects_malformed_host_and_origin(self):
        for env in (
            {"CITERAG_MCP_ALLOWED_HOSTS": "*"},
            {"CITERAG_MCP_ALLOWED_HOSTS": "good.example", "CITERAG_MCP_ALLOWED_ORIGINS": "https://good.example/path"},
            {"CITERAG_MCP_ALLOWED_HOSTS": "good.example", "CITERAG_MCP_ALLOWED_ORIGINS": "https://good.example:bad"},
        ):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError):
                    transport_security_settings()


if __name__ == "__main__":
    unittest.main()
