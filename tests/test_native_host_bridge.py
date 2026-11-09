"""The host native bridge never performs database work or arbitrary command execution."""
from contextlib import contextmanager
import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from citerag import native
from citerag.native_result import ABSTENTION

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_host_bridge", ROOT / "tasks/native-host-bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
TOKEN = "synthetic-bridge-fixture-" + "x" * 40


@contextmanager
def serve(service):
    server = ThreadingHTTPServer(("127.0.0.1", 0), bridge.handler_for(service))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


class FakeService:
    token = TOKEN
    calls = 0
    def status(self):
        return {"status": "not_verified"}
    def answer(self, payload):
        self.calls += 1
        return 200, {"accepted": True}


class BridgeHTTPTests(unittest.TestCase):
    def request(self, port, method, path, body=None, headers=None):
        con = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        con.request(method, path, body=body, headers=headers or {})
        response = con.getresponse()
        result = response.status, json.loads(response.read())
        con.close()
        return result

    def test_every_route_requires_authentication_before_dispatch(self):
        service = FakeService()
        with serve(service) as port:
            self.assertEqual(self.request(port,"GET","/status")[0],401)
            self.assertEqual(self.request(port,"POST","/answer",b"{}")[0],401)
            self.assertEqual(service.calls,0)
            self.assertEqual(self.request(port,"GET","/status",headers={"Authorization":"Bearer "+TOKEN})[0],200)

    def test_duplicate_auth_and_oversized_body_are_rejected(self):
        service = FakeService()
        with serve(service) as port:
            con=http.client.HTTPConnection("127.0.0.1",port,timeout=3)
            con.putrequest("GET","/status")
            con.putheader("Authorization","Bearer "+TOKEN)
            con.putheader("Authorization","Bearer "+TOKEN)
            con.endheaders()
            response=con.getresponse()
            self.assertEqual(response.status,401);response.read();con.close()
            headers={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"}
            self.assertEqual(self.request(port,"POST","/answer",b"x"*4097,headers)[0],400)
            self.assertEqual(self.request(port,"POST","/answer",b"bad",headers)[0],400)
            self.assertEqual(service.calls,0)

    def test_no_query_routes_or_untyped_payload(self):
        service = FakeService()
        headers={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"}
        with serve(service) as port:
            self.assertEqual(self.request(port,"GET","/status?token=unsafe",headers=headers)[0],404)
            self.assertEqual(self.request(port,"POST","/command",b"{}",headers)[0],404)
            self.assertEqual(self.request(port,"POST","/answer",b"{}",headers)[0],200)
            self.assertEqual(service.calls,1)


class BridgeServiceTests(unittest.TestCase):
    def fixture(self):
        service=object.__new__(bridge.BridgeService)
        service.backend="fixture"
        service.env_file=Path("/owner/native.env")
        service.binary=Path("/reviewed/binary")
        service.mcp_url="http://127.0.0.1:60761/mcp"
        service.owner=threading.BoundedSemaphore(1)
        return service

    def report(self):
        return {"status":"PASS","backend_identity_attested":True,"backend_id":"fixture",
                "runtime_fingerprint":"code","final_answer":ABSTENTION,
                "native_tool_calls":1,"retrieved_sources":[],"abstained":True}

    def test_request_fields_cannot_change_commands_or_backend(self):
        service=self.fixture()
        with patch.object(bridge.subprocess,"run") as run:
            for payload in ({}, {"question":"q","expected_backend_id":"other"},
                            {"question":"q","expected_backend_id":"fixture","command":"unsafe"},
                            {"question":"x"*401,"expected_backend_id":"fixture"}):
                self.assertEqual(service.answer(payload)[0],400)
            run.assert_not_called()

    def test_single_owner_timeout_and_fixed_runner_arguments(self):
        service=self.fixture()
        payload={"question":"quoted '$HOME'; question","expected_backend_id":"fixture"}
        service.owner.acquire()
        try:self.assertEqual(service.answer(payload)[0],409)
        finally:service.owner.release()
        with patch.object(bridge,"runtime_fingerprint",return_value="code"),patch.object(
            bridge.native,"bridge_code_fingerprint",return_value="bridge"),patch.object(
            bridge.subprocess,"run",return_value=subprocess.CompletedProcess([],0,json.dumps(self.report()),"private")) as run:
            status,report=service.answer(payload)
        self.assertEqual(status,200);self.assertEqual(report["bridge_fingerprint"],"bridge")
        args=run.call_args.args[0]
        self.assertEqual(args[1],str(ROOT/"tasks/verify-native.py"))
        self.assertEqual(args[args.index("--question")+1],payload["question"])
        self.assertEqual(run.call_args.kwargs["timeout"],260)
        with patch.object(bridge.subprocess,"run",side_effect=subprocess.TimeoutExpired(["runner"],260)):
            self.assertEqual(service.answer(payload),(502,{"error":"Native runner failed"}))
        self.assertTrue(service.owner.acquire(blocking=False));service.owner.release()

    def test_wrong_report_identity_never_leaks_upstream_details(self):
        service=self.fixture()
        report={**self.report(),"backend_id":"wrong","credential":"never-return-this"}
        with patch.object(bridge,"runtime_fingerprint",return_value="code"),patch.object(
            bridge.subprocess,"run",return_value=subprocess.CompletedProcess([],0,json.dumps(report),"private")):
            self.assertEqual(service.answer({"question":"q","expected_backend_id":"fixture"}),
                             (502,{"error":"Native verification failed"}))

    def test_host_module_import_requires_no_httpx_or_database_operation(self):
        code=("import runpy,sys,sqlite3; "
              "sqlite3.connect=lambda *a,**k:(_ for _ in ()).throw(AssertionError('database forbidden')); "
              "runpy.run_path("+repr(str(ROOT/"tasks/native-host-bridge.py"))+",run_name='bridge_import'); "
              "assert 'httpx' not in sys.modules; assert 'lancedb' not in sys.modules; "
              "assert 'sentence_transformers' not in sys.modules")
        result=subprocess.run(["/usr/bin/python3.12","-c",code],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_configuration_rejects_recursion_and_non_independent_credentials(self):
        with patch.dict(os.environ,{"CITERAG_NATIVE_BRIDGE_URL":native.BRIDGE_URL},clear=True):
            with self.assertRaises(bridge.BridgeConfigurationError):bridge.BridgeService()
        with tempfile.TemporaryDirectory() as temporary:
            env=Path(temporary)/"native.env"
            env.write_text("CITERAG_API_TOKEN="+TOKEN+"\n");env.chmod(0o600)
            values={"CITERAG_NATIVE_BRIDGE_TOKEN":TOKEN,"CITERAG_BACKEND_ID":"fixture",
                    "CITERAG_NATIVE_ENV_FILE":str(env),"CITERAG_NATIVE_BINARY_DIR":temporary,
                    "CITERAG_NATIVE_MCP_URL":"http://127.0.0.1:60761/mcp"}
            with patch.dict(os.environ,values,clear=True),patch.object(native,"configuration_status",return_value="ready"):
                with self.assertRaises(bridge.BridgeConfigurationError):bridge.BridgeService()


class NativeBridgeClientTests(unittest.TestCase):
    def env(self):
        return {"CITERAG_NATIVE_BRIDGE_URL":native.BRIDGE_URL,
                "CITERAG_NATIVE_BRIDGE_TOKEN":TOKEN,"CITERAG_BACKEND_ID":"fixture"}

    def test_unapproved_bridge_never_falls_back_to_host_runner(self):
        with patch.dict(os.environ,{**self.env(),"CITERAG_NATIVE_BRIDGE_URL":"http://example.invalid"},clear=True),patch.object(
            native.subprocess,"run") as run:
            self.assertEqual(native.configuration_status(),"not_configured")
            self.assertEqual(native.answer("question")["status"],"failed")
            run.assert_not_called()

    def test_remote_readiness_binds_actual_source_bridge_and_backend(self):
        report={"status":"verified","runtime_fingerprint":"code","backend_id":"fixture",
                "bridge_fingerprint":"bridge"}
        with patch.dict(os.environ,self.env(),clear=True),patch.object(native,"runtime_fingerprint",return_value="code"),patch.object(
            native,"bridge_code_fingerprint",return_value="bridge"),patch.object(native,"_bridge_request",return_value=report):
            self.assertEqual(native.verification_status(),"verified")
            report["backend_id"]="other"
            self.assertEqual(native.verification_status(),"not_verified")

    def test_remote_answer_requires_grounding_identity_and_real_tool(self):
        report={"status":"PASS","backend_id":"fixture","runtime_fingerprint":"code",
                "bridge_fingerprint":"bridge","backend_identity_attested":True,
                "native_tool_calls":1,"final_answer":ABSTENTION,
                "retrieved_sources":[],"abstained":True}
        with patch.dict(os.environ,self.env(),clear=True),patch.object(native,"runtime_fingerprint",return_value="code"),patch.object(
            native,"bridge_code_fingerprint",return_value="bridge"),patch.object(native,"_bridge_request",return_value=report):
            self.assertEqual(native.answer("q")["status"],"insufficient_evidence")
            report["abstained"]=False
            self.assertEqual(native.answer("q")["status"],"failed")
            report["abstained"]=True;report["runtime_fingerprint"]="wrong"
            self.assertEqual(native.answer("q")["status"],"failed")

if __name__=="__main__":unittest.main()
