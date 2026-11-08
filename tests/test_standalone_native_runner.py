"""Fail-closed standalone OpenCode runner: no real credentials, no network."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import importlib.util
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("verify_native",ROOT/"tasks/verify-native.py")
r=importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class IsolatedNativeRunnerTests(unittest.TestCase):
 def test_missing_scoped_env_blocks(self):
  with self.assertRaises(r.AdmissionError):r.env_file(None)
  with self.assertRaises(r.AdmissionError):r.env_file(Path("missing.env"))
 def test_private_env_required(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/"test.env"
   p.write_text("CITERAG_API_TOKEN=fake-local-test-only\n")
   p.chmod(0o600)
   with self.assertRaises(r.AdmissionError):r.env_file(p)
   p.write_text("CITERAG_API_TOKEN=fake-local-test-only\nCITERAG_OMNIROUTE_API_KEY=local-test-only\n")
   self.assertEqual(r.env_file(p),p)
   p.chmod(0o644)
   with self.assertRaises(r.AdmissionError):r.env_file(p)
 def test_no_paid_provider_or_extra_mcp(self):
  p=json.loads((r.ROOT/"configs/native-citerag.json").read_text())
  self.assertEqual(p["model"]["model"],r.MODEL)
  self.assertEqual(set(p["mcp"]["servers"]),{"citerag"})
  self.assertEqual(p["mcp"]["servers"]["citerag"]["headers"],
                   {"Authorization":"Bearer {env:CITERAG_API_TOKEN}"})
  self.assertEqual(set(p["providers"]),{"omniroute"})
  self.assertEqual(p["permissions"][0]["effect"],"deny")
  self.assertEqual(p["permissions"][1]["resource"],"*")
  self.assertEqual(p["permissions"][1]["action"],"citerag_rag_search")
 def test_docker_has_isolation_and_no_project_mount(self):
  with tempfile.TemporaryDirectory() as directory:
   d=Path(directory);(d/"opencode").write_text("fake executable")
   args=r.container_command(d/"test.env",d,"citerag-native-test-123","question")
   self.assertIn("--read-only",args)
   self.assertIn("no-new-privileges",args)
   self.assertIn("65534:65534",args)
   self.assertIn("--memory",args)
   self.assertIn("--cap-drop",args)
   self.assertIn("--env-file",args)
   self.assertEqual(args.count("--mount"),2)
   self.assertNotIn("docker.sock"," ".join(args))
   self.assertNotIn("/workspace"," ".join(args))
 def test_preflight_blocks_before_container(self):
  result=subprocess.CompletedProcess([],2,stdout=json.dumps({"status":"BLOCKED"}),stderr="")
  with patch.object(r.subprocess,"run",return_value=result):
   with self.assertRaises(r.AdmissionError):r.preflight()

if __name__=="__main__":unittest.main()
