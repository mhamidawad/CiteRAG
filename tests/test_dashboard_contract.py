"""Verify visible adapter choices fail closed before generation is verified."""
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from citerag import web

class DashboardContractTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(web.app)

    def test_only_retrieval_is_selectable_without_verified_generation(self):
        with patch.object(web, "native_status", return_value="unavailable"), patch.object(web, "MODEL", ""):
            rows=self.client.get("/api/adapters").json()["adapters"]
            enabled={row["name"] for row in rows if row["available"]}
        self.assertEqual(enabled, {"retrieval-only"})
        self.assertEqual(len(rows),3)

    @patch.object(web, "prepare_context")
    @patch.object(web, "answer")
    def test_explicit_unverified_generation_rejected_before_refresh(self, answer, fresh):
        with patch.object(web, "native_status", return_value="unavailable"), patch.object(web, "MODEL", ""):
            for adapter in ("opencode", "omniroute"):
                result=self.client.post("/api/ask",json={"question":"Test","adapter":adapter})
                self.assertEqual(result.status_code,503)
        fresh.assert_not_called()
        answer.assert_not_called()

    def test_html_does_not_reference_removed_checkbox(self):
        html=self.client.get("/").text
        self.assertNotIn("$('retrieval').checked",html)
        self.assertNotIn("architecture.mds/",html)
        self.assertIn("option.disabled=item.available!==true",html)
