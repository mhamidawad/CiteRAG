"""Rollback preflight must reject insecure legacy candidates."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

p=Path(__file__).resolve().parents[1]/"tasks/rollback_auth_preflight.py"
spec=importlib.util.spec_from_file_location("rollback_auth_preflight",p)
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def docker_inspect(*, image="ghcr.io/demo/citerag@sha256:"+("a"*64),
                   host="127.0.0.1", privileged=False, running=True):
    return [{
        "Config": {"Image": image, "User": "65532:65532"},
        "HostConfig": {"ReadonlyRootfs": True, "Privileged": privileged,
                       "PortBindings": {"18762/tcp": [{"HostIp": host,"HostPort": "48762"}]}},
        "State":{"Running":running}, "Mounts":[]
    }]


class RollbackTests(unittest.TestCase):
    def test_safe_candidate_structure(self):
        with patch.object(gate.subprocess,"check_output",
                          return_value=json.dumps(docker_inspect()).encode()):
            self.assertTrue(gate.inspect_candidate("safe-candidate",48762)["digest_pinned"])

    def test_reject_unpinned_image(self):
        with patch.object(gate.subprocess,"check_output",
                          return_value=json.dumps(docker_inspect(image="citerag:latest")).encode()):
            with self.assertRaises(ValueError):
                gate.inspect_candidate("safe-candidate",48762)

    def test_reject_public_binding(self):
        with patch.object(gate.subprocess,"check_output",
                          return_value=json.dumps(docker_inspect(host="0.0.0.0")).encode()):
            with self.assertRaises(ValueError):
                gate.inspect_candidate("safe-candidate",48762)

    def test_reject_privileged(self):
        with patch.object(gate.subprocess,"check_output",
                          return_value=json.dumps(docker_inspect(privileged=True)).encode()):
            with self.assertRaises(ValueError):
                gate.inspect_candidate("safe-candidate",48762)

    def test_reject_anonymous_legacy(self):
        with patch.object(gate,"inspect_candidate",return_value={"digest_pinned":True}),patch.object(gate,"request_status",return_value=200):
            result=gate.certify("legacy",38762,"x"*36)
            self.assertEqual(result["reason"],"ANONYMOUS_ACCESS_NOT_DENIED")

    def test_accept_auth_only(self):
        with patch.object(gate,"inspect_candidate",return_value={"digest_pinned":True}),patch.object(gate,"request_status",side_effect=[401,200]):
            self.assertEqual(gate.certify("candidate",48762,"x"*36)["status"],"PASS")

    def test_token_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"env"
            f.write_text("CITERAG_API_TOKEN="+"a"*40+"\n")
            f.chmod(0o644)
            with self.assertRaises(ValueError):gate.read_token(f)
            f.chmod(0o600)
            self.assertEqual(len(gate.read_token(f)),40)

if __name__=="__main__":
    unittest.main()
