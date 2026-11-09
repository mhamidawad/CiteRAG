#!/usr/bin/env python3
"""Prepare and optionally activate a private host release from a scanned GHCR digest.

No dependency installation or image build occurs on the deployment host.
A dry run validates inputs and prints a non-secret plan. Activation is explicit.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid

IMAGE = re.compile(r"ghcr\.io/mhamidawad/citerag@sha256:[a-f0-9]{64}")
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./-]+")
UNITS = ("citerag-production-mcp", "citerag-production-web")

class DeploymentError(RuntimeError):
    pass

def run(args, *, env=None, cwd=None, capture=True, timeout=60):
    result = subprocess.run(args, env=env, cwd=cwd, text=True,
                            capture_output=capture, timeout=timeout)
    if result.returncode:
        # Child output can contain environment values or upstream credentials.
        raise DeploymentError("Command failed: " + args[0])
    return result.stdout if capture else ""

def absolute_path(value):
    path = Path(value)
    if not path.is_absolute() or not SAFE_PATH.fullmatch(str(path)) or ".." in path.parts:
        raise DeploymentError("Expected a simple absolute path")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise DeploymentError("Symlinked deployment path")
    return path

def environment(path, uid, release, state):
    path = absolute_path(path)
    if not path.is_file() or path.stat().st_uid != uid or path.stat().st_mode & 0o077:
        raise DeploymentError("Environment must be owned by the runtime user and mode 0600")
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"CITERAG_[A-Z0-9_]+|HF_HUB_OFFLINE", key):
            raise DeploymentError("Unexpected environment entry")
        if key in result:
            raise DeploymentError("Duplicate environment entry")
        result[key] = value
    if result.get("CITERAG_PRODUCTION") != "1" or result.get("CITERAG_REQUIRE_AUTH") != "1":
        raise DeploymentError("Production and authentication must be explicit")
    if len(result.get("CITERAG_API_TOKEN", "")) < 32:
        raise DeploymentError("Missing dedicated API credential")
    if result.get("CITERAG_OFFLINE") != "1" or result.get("HF_HUB_OFFLINE") != "1":
        raise DeploymentError("Offline model use required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", result.get("CITERAG_WORKSPACE_ID", "")):
        raise DeploymentError("Explicit workspace required")
    for field in ("CITERAG_RATE_LIMIT_PER_MINUTE", "CITERAG_GENERATION_LIMIT_PER_DAY"):
        value = result.get(field, "")
        if not value.isdecimal() or not 1 <= int(value) <= 1000000:
            raise DeploymentError("Explicit positive admission budgets required")
    state = absolute_path(state)
    if state.is_relative_to(release) or not state.is_dir() or state.stat().st_uid != uid or state.stat().st_mode & 0o077:
        raise DeploymentError("Persistent state must be an external owner-only directory")
    ledger = absolute_path(result.get("CITERAG_POLICY_DB", ""))
    if ledger != state / "admission.sqlite3":
        raise DeploymentError("Policy ledger must belong to the persistent state directory")
    if ledger.exists() and (not ledger.is_file() or ledger.stat().st_uid != uid or ledger.stat().st_mode & 0o077):
        raise DeploymentError("Persistent policy ledger must be an owner-only regular file")
    for name, default in (("MCP", "18761"), ("WEB", "18762")):
        if result.get("CITERAG_" + name + "_HOST") != "127.0.0.1":
            raise DeploymentError("Host services must use IPv4 loopback")
        port = result.get("CITERAG_" + name + "_PORT", default)
        if not port.isdecimal() or not 1024 <= int(port) <= 65535:
            raise DeploymentError("Invalid listener port")
    if result.get("CITERAG_MCP_PORT", "18761") == result.get("CITERAG_WEB_PORT", "18762"):
        raise DeploymentError("Listener ports must differ")
    if not absolute_path(result.get("CITERAG_MODEL_CACHE_DIR", "")).is_dir():
        raise DeploymentError("Pinned local model cache missing")
    return result

def free_ports(values):
    for field, default in (("CITERAG_MCP_PORT", "18761"), ("CITERAG_WEB_PORT", "18762")):
        try:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", int(values.get(field, default))))
        except OSError as exc:
            raise DeploymentError("Requested listener port is occupied; no process was stopped") from exc

def unit_text(kind, release, env_file, user, state):
    if kind not in {"mcp", "web"}:
        raise DeploymentError("Invalid service kind")
    module = "server" if kind == "mcp" else "web"
    source = release / "src"
    return f"""[Unit]
Description=CiteRAG private production {kind}
After=network-online.target docker.service
Wants=network-online.target
StartLimitIntervalSec=120
StartLimitBurst=3

[Service]
Type=simple
User={user}
WorkingDirectory={source}
Environment=PYTHONPATH={source}:{release / 'site-packages'}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
EnvironmentFile={env_file}
ExecStart=/usr/bin/python3.12 -m citerag.{module}
Restart=on-failure
RestartSec=5
TimeoutStopSec=15
MemoryMax=1500M
CPUQuota=100%
TasksMax=160
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={source / 'data'} {source / 'reports'} {state}
UMask=0077

[Install]
WantedBy=multi-user.target
"""

def validate(args):
    if not IMAGE.fullmatch(args.image):
        raise DeploymentError("A repository-scoped SHA256 image digest is required")
    if not re.fullmatch(r"[a-f0-9]{40}", args.source_sha):
        raise DeploymentError("Exact reviewed source SHA required")
    release = absolute_path(args.release_dir)
    if release.exists():
        raise DeploymentError("Release directory must be new")
    if len(release.parts) < 4:
        raise DeploymentError("Release path is too broad")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", args.user):
        raise DeploymentError("Invalid runtime user")
    uid = pwd.getpwnam(args.user).pw_uid
    if uid == 0 or os.getuid() != uid:
        raise DeploymentError("Run as the non-root runtime user")
    values = environment(args.env_file, uid, release, args.state_dir)
    if not Path("/usr/bin/python3.12").is_file() or sys.version_info[:2] != (3, 12):
        raise DeploymentError("Python 3.12 host runtime required")
    if shutil.disk_usage(release.parent if release.parent.exists() else Path("/")).free < 6 * 1024**3:
        raise DeploymentError("At least 6 GiB free disk required")
    free_ports(values)
    for unit in UNITS:
        unit_path = Path("/etc/systemd/system/" + unit + ".service")
        if unit_path.is_symlink():
            raise DeploymentError("Symlinked installed unit requires manual review")
        if unit_path.exists():
            if not args.replace_existing:
                raise DeploymentError("Existing CiteRAG unit requires --replace-existing")
            active = subprocess.run(["systemctl", "is-active", "--quiet", unit], capture_output=True)
            if active.returncode == 0:
                raise DeploymentError("Stop reviewed existing units explicitly before replacement")
    return release, values

def unit_state(unit):
    active = subprocess.run(["systemctl", "is-active", "--quiet", unit], capture_output=True)
    enabled = subprocess.run(["systemctl", "is-enabled", unit], text=True, capture_output=True)
    return {"active": active.returncode == 0,
            "enabled": enabled.stdout.strip() or "not-found"}

def restore_units(old, states, backups):
    """Restore only the two named units, including their prior enabled/active state."""
    failures = []
    def attempt(command):
        try:
            run(command, timeout=30)
        except (DeploymentError, OSError, subprocess.SubprocessError):
            failures.append(command[2] if len(command) > 2 else command[0])
    attempt(["sudo", "-n", "systemctl", "stop", *UNITS])
    # Remove enablement links created by the failed activation before restoring definitions.
    for unit in UNITS:
        try:
            subprocess.run(["sudo", "-n", "systemctl", "disable", unit],
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            failures.append("disable")
    for unit in UNITS:
        destination = "/etc/systemd/system/" + unit + ".service"
        if unit in old:
            attempt(["sudo", "-n", "install", "-m", "0644",
                     str(backups / (unit + ".service")), destination])
        else:
            attempt(["sudo", "-n", "rm", "-f", "--", destination])
    attempt(["sudo", "-n", "systemctl", "daemon-reload"])
    for unit in UNITS:
        enabled = states[unit]["enabled"]
        if enabled in {"enabled", "enabled-runtime"}:
            command = ["sudo", "-n", "systemctl", "enable"]
            if enabled == "enabled-runtime":
                command.append("--runtime")
            attempt([*command, unit])
        if states[unit]["active"]:
            attempt(["sudo", "-n", "systemctl", "start", unit])
    for unit in UNITS:
        try:
            current = unit_state(unit)
            if current != states[unit]:
                failures.append("state-mismatch")
        except (OSError, subprocess.SubprocessError):
            failures.append("state-verification")
    return not failures

def activate(args, release, values):
    run(["docker", "pull", args.image], capture=False, timeout=600)
    info = json.loads(run(["docker", "image", "inspect", args.image]))[0]
    if args.image not in info.get("RepoDigests", []):
        raise DeploymentError("Pulled image digest mismatch")
    if info.get("Architecture") != "amd64" or info.get("Os") != "linux":
        raise DeploymentError("Expected Linux amd64 artifact")
    revision = (info.get("Config", {}).get("Labels") or {}).get("org.opencontainers.image.revision")
    if revision != args.source_sha:
        raise DeploymentError("Artifact source label mismatch")
    release.mkdir(parents=True, exist_ok=False)
    source = release / "src"
    source.mkdir()
    dependencies = release / "site-packages"
    dependencies.mkdir()
    container = "citerag-extract-" + uuid.uuid4().hex[:12]
    created = False
    try:
        run(["docker", "create", "--name", container, "--network", "none", args.image])
        created = True
        run(["docker", "cp", container + ":/app/.", str(source)], timeout=120)
        run(["docker", "cp", container + ":/usr/local/lib/python3.12/site-packages/.",
             str(dependencies)], timeout=300)
    finally:
        if created:
            run(["docker", "rm", container])
    # Imported artifacts are never modified in place by a running service.
    for path in source.rglob("*"):
        if path.is_symlink():
            raise DeploymentError("Unexpected source artifact symlink")
    for name in ("data", "reports"):
        path = source / name
        path.mkdir(exist_ok=True)
        path.chmod(0o700)
    smoke_env = dict(os.environ, **values, PYTHONPATH=str(source) + ":" + str(dependencies),
                     PYTHONDONTWRITEBYTECODE="1")
    run(["/usr/bin/python3.12", "-c",
         "import citerag.web, citerag.server, torch, lancedb, sentence_transformers; "
         "from citerag.auth import validate_binding; validate_binding('127.0.0.1')"],
        env=smoke_env, cwd=source, timeout=90)
    # Validate unit syntax before touching any installed unit.
    backups = release / "unit-backups"
    backups.mkdir(mode=0o700)
    staged = release / "units"
    staged.mkdir()
    for kind in ("mcp", "web"):
        (staged / ("citerag-production-" + kind + ".service")).write_text(
            unit_text(kind, release, args.env_file, args.user, args.state_dir))
    run(["systemd-analyze", "verify", *[str(p) for p in staged.glob("*.service")]])
    free_ports(values)
    manifest = {"source_sha": args.source_sha, "image": args.image,
                "image_id": info.get("Id"), "prepared_at": datetime.now(timezone.utc).isoformat(),
                "host_runtime": "/usr/bin/python3.12", "dependency_source": "digest-pinned-image", "persistent_state": str(args.state_dir)}
    (release / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    old = {}
    states = {unit: unit_state(unit) for unit in UNITS}
    if any(state["active"] for state in states.values()):
        raise DeploymentError("Reviewed prior units must remain stopped before replacement")
    (backups / "prior-state.json").write_text(json.dumps(states, indent=2) + "\n")
    for unit in UNITS:
        destination = Path("/etc/systemd/system/" + unit + ".service")
        if destination.exists():
            old[unit] = destination.read_text()
            (backups / destination.name).write_text(old[unit])
    try:
        for unit in UNITS:
            destination = Path("/etc/systemd/system/" + unit + ".service")
            run(["sudo", "-n", "install", "-m", "0644", str(staged / destination.name), str(destination)])
        run(["sudo", "-n", "systemctl", "daemon-reload"])
        run(["sudo", "-n", "systemctl", "enable", "--now", *UNITS], timeout=45)
        for unit in UNITS:
            run(["systemctl", "is-active", "--quiet", unit])
    except Exception:
        restored = restore_units(old, states, backups)
        if restored:
            raise DeploymentError("Service activation failed; prior definitions and states restored") from None
        raise DeploymentError("Service activation failed; manual unit restoration required") from None
    return manifest

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--user", default=pwd.getpwuid(os.getuid()).pw_name)
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args(argv)
    try:
        release, values = validate(args)
        plan = {"status": "VALIDATED", "activation_requested": args.activate,
                "image": args.image, "source_sha": args.source_sha,
                "release_dir": str(release), "persistent_state": str(args.state_dir), "units": list(UNITS),
                "listener_scope": "IPv4 loopback only", "secrets_printed": False}
        if args.activate:
            plan.update(activate(args, release, values))
            plan["status"] = "ACTIVE_NOT_CERTIFIED"
        print(json.dumps(plan, sort_keys=True))
        return 0
    except (DeploymentError, OSError, KeyError, ValueError, subprocess.SubprocessError):
        print(json.dumps({"status": "BLOCKED", "reason": "DeploymentPreflightOrActivationFailed",
                          "secrets_printed": False}))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
