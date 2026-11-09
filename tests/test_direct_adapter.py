import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
from citerag import answer

ENV = {"CITERAG_OMNIROUTE_URL": answer.LOCAL_BASE,
       "CITERAG_OMNIROUTE_API_KEY": "unit-private-placeholder",
       "CITERAG_BACKEND_ID": "unit-backend"}
ROW = {"source": "docs/architecture.md", "id": "a" * 64,
       "text": "CiteRAG uses LanceDB as its embedded vector database."}
QUOTE = ROW["text"] + "\nSource: " + ROW["source"] + "\nChunk: " + ROW["id"]

class DirectAdapterTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, ENV); env.start(); self.addCleanup(env.stop)
        model = patch.object(answer, "MODEL", answer.LOCAL_MODEL); model.start(); self.addCleanup(model.stop)

    def stream(self, output):
        calls = []
        Client = httpx.Client
        def handler(request):
            calls.append(request)
            body = "data: " + json.dumps({"choices": [{"delta": {"content": output}, "finish_reason": "stop"}]}) + "\n\ndata: [DONE]\n\n"
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        factory = lambda **kwargs: Client(transport=httpx.MockTransport(handler), **kwargs)
        return calls, patch.object(answer.httpx, "Client", side_effect=factory)

    def test_local_only_config_rejects_external_route_or_other_model(self):
        self.assertEqual(answer.configuration_status(), "ready")
        with patch.dict(os.environ, {"CITERAG_OMNIROUTE_URL": "https://external.example"}):
            self.assertEqual(answer.configuration_status(), "not_configured")
        with patch.object(answer, "MODEL", "paid/model"):
            self.assertEqual(answer.configuration_status(), "not_configured")

    def test_one_real_http_stream_returns_validated_quote(self):
        calls, transport = self.stream(ROW["text"])
        with patch.object(answer, "search", return_value=[ROW]), transport:
            result = answer._answer("Which vector database?")
        self.assertEqual(len(calls), 1)
        self.assertEqual(str(calls[0].url), answer.LOCAL_BASE + "/v1/chat/completions")
        self.assertEqual(json.loads(calls[0].content)["model"], answer.LOCAL_MODEL)
        self.assertTrue(result["citations_verified"] and result["claims_supported"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], QUOTE)
        self.assertNotIn(ENV["CITERAG_OMNIROUTE_API_KEY"], json.dumps(result))

    def test_unsupported_claim_is_rejected_without_retry(self):
        calls, transport = self.stream("The database is ExampleDB.\nSource: docs/architecture.md\nChunk: " + "a" * 64)
        with patch.object(answer, "search", return_value=[ROW]), transport:
            result = answer._answer("Which database?")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["error"], "GroundingValidationFailed")
        self.assertEqual(result["status"], "failed")

    def test_model_supplied_citation_cannot_hide_unsupported_prose(self):
        payload = ROW["text"] + "\nSource: All credentials are publicly readable docs/architecture.md\nChunk: " + "a" * 64
        calls, transport = self.stream(payload)
        with patch.object(answer, "search", return_value=[ROW]), transport:
            result = answer._answer("Which database?")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["claims_supported"])

    def test_empty_evidence_does_not_start_client_or_model(self):
        with patch.object(answer, "search", return_value=[]), patch.object(answer.httpx, "Client") as client:
            result = answer._answer("unsupported")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertFalse(result["model_request_started"])
        self.assertEqual(result["attempts"], 0)
        client.assert_not_called()

    def test_oversized_output_is_rejected(self):
        calls, transport = self.stream("x" * 17000)
        with patch.object(answer, "search", return_value=[ROW]), transport:
            result = answer._answer("Which database?")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "ValueError")

    def test_proof_requires_runtime_configuration_and_abstention_acceptance(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(answer, "ROOT", Path(directory)), patch("citerag.native_result.runtime_fingerprint", return_value="source-sha"):
            root = Path(directory); (root / "reports").mkdir()
            proof = root / "reports/omniroute-current-verification.json"
            report = {"status": "PASS", "citations_verified": True, "claims_supported": True,
                "acceptance_terms_verified": True, "required_acceptance_terms": ["LanceDB"],
                "unsupported_abstention_verified": True, "runtime_fingerprint": "source-sha",
                "deployment_fingerprint": answer.deployment_fingerprint()}
            proof.write_text(json.dumps(report))
            self.assertEqual(answer.verification_status(), "verified")
            with patch.dict(os.environ, {"CITERAG_OMNIROUTE_API_KEY": "rotated-private-placeholder"}):
                self.assertNotEqual(answer.verification_status(), "verified")
            report["unsupported_abstention_verified"] = False; proof.write_text(json.dumps(report))
            self.assertNotEqual(answer.verification_status(), "verified")

if __name__ == "__main__": unittest.main()
