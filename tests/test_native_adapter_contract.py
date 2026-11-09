"""Native adapter contract tests use fake subprocesses, never inference."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from citerag import native
from citerag.native_result import ABSTENTION

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("contract_runner", ROOT/"tasks/verify-native.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class NativeAdapterContractTests(unittest.TestCase):
    def test_missing_configuration_fails_without_subprocess(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(native.subprocess, "run") as run:
            self.assertEqual(native.answer("question")["error"], "NativeAdapterUnavailable")
            run.assert_not_called()

    def test_adapter_supplies_private_config_and_consumes_runner_result(self):
        report = {"status":"PASS", "backend_identity_attested":True,
                  "final_answer":ABSTENTION, "retrieved_sources":[],
                  "native_tool_calls":1, "citations_verified":False,
                  "claims_supported":False, "grounding_contract":"verbatim-extractive",
                  "abstained":True}
        with patch.object(native, "prepare_context", return_value={"status":"completed"}), patch.object(native, "configuration_status", return_value="ready"), patch.dict(
            os.environ, {"CITERAG_NATIVE_ENV_FILE":"/private/native.env",
                         "CITERAG_NATIVE_BINARY_DIR":"/reviewed/binary",
                         "CITERAG_BACKEND_ID":"backend-fixture"}), patch.object(
            native.subprocess,"run",return_value=subprocess.CompletedProcess([],0,json.dumps(report),"")) as run:
            result = native.answer("question")
            self.assertEqual(result["status"], "insufficient_evidence")
            args = run.call_args.args[0]
            self.assertIn("--env-file", args)
            self.assertIn("--binary-dir", args)
            self.assertIn("--expected-backend-id", args)
            self.assertNotIn("--report-dir", args)

    def test_unattested_result_is_rejected(self):
        with patch.object(native,"prepare_context",return_value={"status":"completed"}), patch.object(native,"configuration_status",return_value="ready"), patch.dict(
            os.environ,{"CITERAG_NATIVE_ENV_FILE":"/private/native.env",
                        "CITERAG_NATIVE_BINARY_DIR":"/reviewed/binary",
                        "CITERAG_BACKEND_ID":"backend-fixture"}), patch.object(
            native.subprocess,"run",return_value=subprocess.CompletedProcess([],0,'{"status":"PASS"}',"")):
            self.assertEqual(native.answer("q")["error"], "NativeVerificationFailed")

    def test_failed_refresh_never_starts_inference(self):
        with patch.object(native,"configuration_status",return_value="ready"), patch.object(
            native,"prepare_context",return_value={"status":"failed"}), patch.object(
            native.subprocess,"run") as run:
            self.assertEqual(native.answer("q")["error"],"ContextNotFresh")
            run.assert_not_called()

    def test_deployment_fingerprint_changes_for_binary_credentials_and_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/"opencode").write_text("reviewed-binary-fixture")
            env=path/"native.env";env.write_text("dedicated-fixture-one")
            args={"env_path":env,"binary_dir":path,"mcp_url":"http://127.0.0.1:50001/mcp","backend_id":"fixture"}
            baseline=native.deployment_fingerprint(**args)
            self.assertNotEqual(baseline,native.deployment_fingerprint(**{**args,"mcp_url":"http://127.0.0.1:50002/mcp"}))
            env.write_text("dedicated-fixture-two")
            self.assertNotEqual(baseline,native.deployment_fingerprint(**args))
            env.write_text("dedicated-fixture-one")
            (path/"opencode").write_text("changed-binary-fixture")
            self.assertNotEqual(baseline,native.deployment_fingerprint(**args))

    def test_runner_rejects_non_loopback_mcp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/"opencode").touch()
            for url in ("http://example.com/mcp","http://user@localhost/mcp",
                        "https://localhost/mcp","http://localhost/mcp?x=y"):
                with self.assertRaises(runner.AdmissionError):
                    runner.container_command(path/"e",path,"test","q",url)

    def test_success_requires_real_backend_identity(self):
        events = [
            {"type":"tool_use","part":{"tool":"citerag_rag_search","state":{
                "status":"completed","output":json.dumps({"results":[],"backend_id":"fixture-backend"})}}},
            {"type":"text","part":{"text":ABSTENTION}},
            {"type":"step_finish","part":{"reason":"stop"}}]
        trace = "\n".join(json.dumps(e) for e in events)
        process = subprocess.CompletedProcess([],0,trace,"citerag connected")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/"opencode").touch()
            (path/"env").write_text("dedicated-test-fixture")
            with patch.object(runner,"env_file",return_value=path/"env"), patch.object(
                runner,"preflight",return_value={}), patch.object(runner.subprocess,"run",return_value=process):
                result=runner.run("q",path/"env",path,expected_backend_id="fixture-backend",report_dir=path/"report")
            self.assertEqual(result["status"],"PASS")
            self.assertTrue(result["backend_identity_attested"])
            self.assertEqual(result["final_answer"],ABSTENTION)
            with patch.object(runner,"env_file",return_value=path/"env"), patch.object(
                runner,"preflight",return_value={}), patch.object(runner.subprocess,"run",return_value=process):
                result=runner.run("q",path/"env",path,expected_backend_id="other-backend",report_dir=path/"report2")
            self.assertEqual(result["status"],"FAIL")
            with patch.object(runner,"env_file",return_value=path/"env"), patch.object(
                runner,"preflight",return_value={}), patch.object(runner.subprocess,"run",return_value=process):
                result=runner.run("q",path/"env",path,expected_backend_id="fixture-backend",report_dir=path/"report3",required_terms=["LanceDB"])
            self.assertEqual(result["status"],"FAIL")
            self.assertEqual(result["reason"],"AcceptanceFactsMissing")
