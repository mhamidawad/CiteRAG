"""Container deployment guards; tests never build, pull, or activate services."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("container_release", ROOT / "deploy/activate-container-release.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class ContainerReleaseTests(unittest.TestCase):
    def test_mutable_tag_rejected_before_any_command(self):
        args = SimpleNamespace(image="ghcr.io/mhamidawad/citerag:latest", source_sha="a"*40)
        with patch.object(deploy, "run") as command:
            with self.assertRaises(deploy.DeploymentError):
                deploy.validate(args)
            command.assert_not_called()

    def test_containers_have_no_control_socket_or_host_secret_mounts(self):
        account = SimpleNamespace(pw_uid=1234, pw_gid=1234)
        values = {"CITERAG_MODEL_CACHE_DIR": "/safe/cache"}
        command = deploy.container_command("web", "ghcr.io/mhamidawad/citerag@sha256:"+"a"*64,
            Path("/safe/releases/one"), Path("/safe/releases/one/web.env"), values,
            Path("/safe/state"), [Path("/safe/repository")], account)
        joined = " ".join(command)
        self.assertIn("--user 1234:1234", joined)
        for flag in ("--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                     "--memory 1500m", "--cpus 1", "--network host"):
            self.assertIn(flag, joined)
        for forbidden in ("docker.sock", "native.env", "binary-dir", "src=/,"):
            self.assertNotIn(forbidden, joined)
        self.assertIn("src=/safe/repository,dst=/safe/repository,readonly", joined)
        self.assertIn("src=/safe/state,dst=/safe/state", joined)
        self.assertEqual(command[-3:], ["python", "-m", "citerag.web"])

    def test_mcp_environment_keeps_public_host_allowlist_without_extra_secrets(self):
        values = {
            "CITERAG_API_TOKEN": "api",
            "CITERAG_OMNIROUTE_API_KEY": "web-only",
            "CITERAG_NATIVE_BRIDGE_TOKEN": "bridge-only",
            "CITERAG_MCP_ALLOWED_HOSTS": "127.0.0.1:*,localhost:*,citerag.example.invalid:8443",
            "CITERAG_MCP_ALLOWED_ORIGINS": "https://citerag.example.invalid:8443",
            "CITERAG_NATIVE_ENV_FILE": "/safe/native.env",
            "CITERAG_NATIVE_BINARY_DIR": "/safe/opencode",
        }
        mcp = deploy.runtime_environment(values, "mcp")
        web = deploy.runtime_environment(values, "web")
        self.assertEqual(mcp["CITERAG_MCP_ALLOWED_HOSTS"], values["CITERAG_MCP_ALLOWED_HOSTS"])
        self.assertEqual(mcp["CITERAG_MCP_ALLOWED_ORIGINS"], values["CITERAG_MCP_ALLOWED_ORIGINS"])
        self.assertNotIn("CITERAG_OMNIROUTE_API_KEY", mcp)
        self.assertNotIn("CITERAG_NATIVE_BRIDGE_TOKEN", mcp)
        self.assertNotIn("CITERAG_NATIVE_ENV_FILE", mcp)
        self.assertIn("CITERAG_OMNIROUTE_API_KEY", web)

    def test_mcp_uses_same_persistent_state_without_source_writes(self):
        account = SimpleNamespace(pw_uid=1234, pw_gid=1234)
        values = {"CITERAG_MODEL_CACHE_DIR": "/safe/cache"}
        commands = [deploy.container_command("mcp", "image", Path("/safe/releases/"+release),
            Path("/safe/"+release+".env"), values, Path("/safe/state"),
            [Path("/safe/repository")], account) for release in ("one", "two")]
        for command in commands:
            self.assertIn("type=bind,src=/safe/state,dst=/safe/state", command)
            self.assertIn("type=bind,src=/safe/repository,dst=/safe/repository,readonly", command)
            self.assertEqual(command[-1], "citerag.server")

    def test_bridge_contract_rejects_recursive_configuration_and_mismatch(self):
        values = {"CITERAG_NATIVE_BRIDGE_URL": deploy.BRIDGE_URL,
                  "CITERAG_NATIVE_BRIDGE_TOKEN": "synthetic-"+"x"*40,
                  "CITERAG_BACKEND_ID": "backend", "CITERAG_MCP_PORT": "60761",
                  "CITERAG_API_TOKEN": "synthetic-api"}
        bridge = {"CITERAG_NATIVE_BRIDGE_TOKEN": values["CITERAG_NATIVE_BRIDGE_TOKEN"],
                  "CITERAG_BACKEND_ID": "backend", "CITERAG_NATIVE_MCP_URL": "http://127.0.0.1:60761/mcp",
                  "CITERAG_NATIVE_BRIDGE_URL": deploy.BRIDGE_URL}
        with self.assertRaises(deploy.DeploymentError):
            deploy.validate_bridge(values, bridge, os.getuid())
        bridge.pop("CITERAG_NATIVE_BRIDGE_URL")
        bridge["CITERAG_NATIVE_BRIDGE_TOKEN"] = "wrong"
        with self.assertRaises(deploy.DeploymentError):
            deploy.validate_bridge(values, bridge, os.getuid())

    def test_bridge_contract_checks_issued_api_and_executable_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "bin"; binary.mkdir()
            (binary/"opencode").write_text("#!/bin/sh\nexit 0\n"); (binary/"opencode").chmod(0o700)
            credentials = root / "native.env"
            credentials.write_text("CITERAG_API_TOKEN=synthetic-api\n")
            credentials.chmod(0o600)
            values = {"CITERAG_NATIVE_BRIDGE_URL": deploy.BRIDGE_URL,
                      "CITERAG_NATIVE_BRIDGE_TOKEN": "synthetic-"+"x"*40,
                      "CITERAG_BACKEND_ID": "backend", "CITERAG_MCP_PORT": "60761",
                      "CITERAG_API_TOKEN": "synthetic-api"}
            bridge = {"CITERAG_NATIVE_BRIDGE_TOKEN": values["CITERAG_NATIVE_BRIDGE_TOKEN"],
                      "CITERAG_BACKEND_ID": "backend", "CITERAG_NATIVE_MCP_URL": "http://127.0.0.1:60761/mcp",
                      "CITERAG_NATIVE_ENV_FILE": str(credentials),
                      "CITERAG_NATIVE_BINARY_DIR": str(binary)}
            deploy.validate_bridge(values, bridge, os.getuid())
            bridge["CITERAG_NATIVE_MCP_URL"] = "http://127.0.0.1:48761/mcp"
            with self.assertRaises(deploy.DeploymentError):
                deploy.validate_bridge(values, bridge, os.getuid())

    def test_approved_source_paths_cannot_inject_mount_or_unit_arguments(self):
        for path in ("/safe/path,readonly=false", "/safe/path with space", "/safe/%n", "/safe/../root"):
            with self.assertRaises(deploy.DeploymentError):
                deploy.source_roots({"CITERAG_REPOSITORY_SOURCES": json.dumps({"source": path})})

    def test_environment_is_private_and_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"config.env"
            path.write_text("CITERAG_BACKEND_ID=a\nCITERAG_BACKEND_ID=b\n")
            path.chmod(0o600)
            with self.assertRaises(deploy.DeploymentError):
                deploy.private_environment(path, os.getuid())
            path.write_text("CITERAG_BACKEND_ID=a\n")
            path.chmod(0o644)
            with self.assertRaises(deploy.DeploymentError):
                deploy.private_environment(path, os.getuid())

    def test_extraction_is_source_only_and_bridge_does_not_load_backend_dependencies(self):
        self.assertEqual(set(deploy.SOURCE_PARTS), {"citerag", "configs", "docs", "tasks", "requirements.lock.txt"})
        self.assertNotIn("python-packages", deploy.SOURCE_PARTS)
        text = deploy.unit_text("native-bridge", [], Path("/safe/releases/one"),
             Path("/safe/bridge.env"), Path("/safe/state"), "runtimeuser")
        self.assertIn("/usr/bin/python3.12 /safe/releases/one/src/tasks/native-host-bridge.py", text)
        self.assertNotIn("site-packages", text)
        self.assertNotIn("docker.sock", text)
        self.assertIn("ProtectSystem=strict", text)
        self.assertIn("NoNewPrivileges=true", text)

    def test_rollback_manages_only_three_named_units_and_verifies_prior_state(self):
        states = {name: {"enabled":"not-found","active":False} for name in deploy.UNITS}
        with patch.object(deploy, "run") as command, patch.object(deploy.subprocess, "run"), \
             patch.object(deploy.guards, "unit_state", side_effect=lambda unit: states[unit]):
            self.assertTrue(deploy.restore({}, states, Path("/safe/backups")))
        calls = [args[0][0] for args in command.call_args_list]
        self.assertFalse(any("restart" in call for call in calls))
        self.assertTrue(any(call[-1].endswith("citerag-production-native-bridge.service") for call in calls))

    def test_missing_vendor_artifact_identity_fails_before_release_creation(self):
        args = SimpleNamespace(image="ghcr.io/mhamidawad/citerag@sha256:"+"a"*64,
                               source_sha="b"*40)
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)/"new-release"
            info = [{"RepoDigests":[args.image],"Architecture":"amd64","Os":"linux",
                     "Config":{"Labels":{"org.opencontainers.image.revision":"c"*40}}}]
            with patch.object(deploy, "run", side_effect=["", json.dumps(info)]):
                with self.assertRaises(deploy.DeploymentError):
                    deploy.activate(args, release, {}, {}, [], None)
            self.assertFalse(release.exists())


if __name__ == "__main__":
    unittest.main()
