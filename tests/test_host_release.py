"""Host deployment guards; no Docker or systemd mutation is run by these tests."""
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import os

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("host_release", ROOT / "deploy/activate-host-release.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)

class HostReleaseTests(unittest.TestCase):
    def test_digest_and_source_label_are_mandatory_before_mutation(self):
        args = SimpleNamespace(image="ghcr.io/mhamidawad/citerag:latest",
                               source_sha="a"*40, release_dir=Path("/tmp/new/release"),
                               env_file=Path("/tmp/env"), user="serviceuser", replace_existing=False)
        with patch.object(deploy, "run") as run:
            with self.assertRaises(deploy.DeploymentError):
                deploy.validate(args)
            run.assert_not_called()

    def test_environment_requires_private_ownership_loopback_and_persistent_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);release=base/"release";cache=base/"cache";cache.mkdir();state=base/"state";state.mkdir(mode=0o700)
            env=base/"private.env"
            values={"CITERAG_PRODUCTION":"1","CITERAG_REQUIRE_AUTH":"1",
                    "CITERAG_API_TOKEN":"synthetic-value-"+"x"*40,
                    "CITERAG_OFFLINE":"1","HF_HUB_OFFLINE":"1",
                    "CITERAG_WORKSPACE_ID":"citerag",
                    "CITERAG_RATE_LIMIT_PER_MINUTE":"12",
                    "CITERAG_GENERATION_LIMIT_PER_DAY":"20",
                    "CITERAG_POLICY_DB":str(state/"admission.sqlite3"),
                    "CITERAG_MODEL_CACHE_DIR":str(cache),
                    "CITERAG_MCP_HOST":"127.0.0.1","CITERAG_WEB_HOST":"127.0.0.1"}
            def write():
                env.write_text("\n".join(k+"="+v for k,v in values.items())+"\n")
                env.chmod(0o600)
            write()
            self.assertEqual(deploy.environment(env,os.getuid(),release,state)["CITERAG_WORKSPACE_ID"],"citerag")
            env.chmod(0o644)
            with self.assertRaises(deploy.DeploymentError):deploy.environment(env,os.getuid(),release,state)
            write();values["CITERAG_MCP_HOST"]="0.0.0.0";write()
            with self.assertRaises(deploy.DeploymentError):deploy.environment(env,os.getuid(),release,state)
            values["CITERAG_MCP_HOST"]="127.0.0.1";values["CITERAG_POLICY_DB"]="/tmp/shared.sqlite";write()
            with self.assertRaises(deploy.DeploymentError):deploy.environment(env,os.getuid(),release,state)

    def test_environment_cannot_override_interpreter_or_use_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/"state";state.mkdir(mode=0o700);env=root/"env";env.write_text("PYTHONPATH=/tmp/unreviewed\n");env.chmod(0o600)
            with self.assertRaises(deploy.DeploymentError):deploy.environment(env,os.getuid(),root/"release",state)
            link=root/"link";link.symlink_to(env)
            with self.assertRaises(deploy.DeploymentError):deploy.absolute_path(link)

    def test_busy_port_fails_without_stopping_processes(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1",0));server.listen()
            port=server.getsockname()[1]
            with patch.object(deploy,"run") as run:
                with self.assertRaises(deploy.DeploymentError):
                    deploy.free_ports({"CITERAG_MCP_PORT":str(port),"CITERAG_WEB_PORT":"18762"})
                run.assert_not_called()

    def test_units_have_private_bounded_runtime_without_installs(self):
        unit=deploy.unit_text("web",Path("/srv/citerag/release"),Path("/srv/citerag/secret.env"),"serviceuser",Path("/srv/citerag/state"))
        for expected in ("User=serviceuser","MemoryMax=1500M","CPUQuota=100%","NoNewPrivileges=true",
                         "ProtectSystem=strict","/usr/bin/python3.12 -m citerag.web","EnvironmentFile="):
            self.assertIn(expected,unit)
        for forbidden in ("pip install","docker build","0.0.0.0","User=root"):
            self.assertNotIn(forbidden,unit)

    def test_image_identity_mismatch_stops_before_extraction(self):
        args=SimpleNamespace(image="ghcr.io/mhamidawad/citerag@sha256:"+"a"*64,
                             source_sha="b"*40)
        result={"RepoDigests":[args.image],"Architecture":"amd64","Os":"linux",
                "Config":{"Labels":{"org.opencontainers.image.revision":"c"*40}}}
        with tempfile.TemporaryDirectory() as folder:
            release=Path(folder)/"new"
            with patch.object(deploy,"run",side_effect=["",json.dumps([result])]) as run:
                with self.assertRaises(deploy.DeploymentError):deploy.activate(args,release,{})
                self.assertFalse(release.exists());self.assertEqual(run.call_count,2)

    def test_dry_run_does_not_activate(self):
        args=["--image","ghcr.io/mhamidawad/citerag@sha256:"+"a"*64,
              "--source-sha","b"*40,"--release-dir","/srv/citerag/new","--env-file","/srv/citerag/env","--state-dir","/srv/citerag/state"]
        with patch.object(deploy,"validate",return_value=(Path("/srv/citerag/new"),{})),\
             patch.object(deploy,"activate") as activate,patch("builtins.print") as output:
            self.assertEqual(deploy.main(args),0);activate.assert_not_called()
            report=json.loads(output.call_args.args[0]);self.assertFalse(report["activation_requested"])

    def test_budget_survives_releases_and_rollback(self):
        from citerag.policy import admit
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/"state";state.mkdir(mode=0o700)
            cache=root/"cache";cache.mkdir();env=root/"env"
            ledger=state/"admission.sqlite3"
            values={"CITERAG_PRODUCTION":"1","CITERAG_REQUIRE_AUTH":"1",
                    "CITERAG_API_TOKEN":"synthetic-value-"+"x"*40,
                    "CITERAG_OFFLINE":"1","HF_HUB_OFFLINE":"1",
                    "CITERAG_WORKSPACE_ID":"workspace",
                    "CITERAG_RATE_LIMIT_PER_MINUTE":"10",
                    "CITERAG_GENERATION_LIMIT_PER_DAY":"1",
                    "CITERAG_POLICY_DB":str(ledger),"CITERAG_MODEL_CACHE_DIR":str(cache),
                    "CITERAG_MCP_HOST":"127.0.0.1","CITERAG_WEB_HOST":"127.0.0.1"}
            env.write_text("\n".join(k+"="+v for k,v in values.items())+"\n");env.chmod(0o600)
            first=deploy.environment(env,os.getuid(),root/"release-one",state)
            limits={"CITERAG_RATE_LIMIT_PER_MINUTE":10,"CITERAG_GENERATION_LIMIT_PER_DAY":1}
            self.assertTrue(admit(first["CITERAG_POLICY_DB"],"workspace",limits,True,now=100))
            ledger.chmod(0o600)
            second=deploy.environment(env,os.getuid(),root/"release-two",state)
            self.assertEqual(first["CITERAG_POLICY_DB"],second["CITERAG_POLICY_DB"])
            self.assertFalse(admit(second["CITERAG_POLICY_DB"],"workspace",limits,True,now=101))
            rollback=deploy.environment(env,os.getuid(),root/"release-one",state)
            self.assertFalse(admit(rollback["CITERAG_POLICY_DB"],"workspace",limits,True,now=102))

    def test_rollback_restores_only_recorded_active_enabled_states(self):
        states={deploy.UNITS[0]:{"active":True,"enabled":"enabled"},
                deploy.UNITS[1]:{"active":False,"enabled":"disabled"}}
        with patch.object(deploy,"run",return_value="") as run,\
             patch.object(deploy.subprocess,"run"),\
             patch.object(deploy,"unit_state",side_effect=lambda unit:states[unit]):
            self.assertTrue(deploy.restore_units({deploy.UNITS[0]:"old"},states,Path("/srv/backup")))
        commands=[call.args[0] for call in run.call_args_list]
        self.assertIn(["sudo","-n","systemctl","start",deploy.UNITS[0]],commands)
        self.assertNotIn(["sudo","-n","systemctl","start",deploy.UNITS[1]],commands)
        self.assertIn(["sudo","-n","systemctl","enable",deploy.UNITS[0]],commands)
        self.assertNotIn(["sudo","-n","systemctl","enable",deploy.UNITS[1]],commands)

    def test_rollback_reports_state_mismatch(self):
        states={unit:{"active":False,"enabled":"disabled"} for unit in deploy.UNITS}
        with patch.object(deploy,"run",return_value=""),patch.object(deploy.subprocess,"run"),\
             patch.object(deploy,"unit_state",return_value={"active":True,"enabled":"enabled"}):
            self.assertFalse(deploy.restore_units({},states,Path("/srv/backup")))
