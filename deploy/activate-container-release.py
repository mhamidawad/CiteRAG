#!/usr/bin/env python3
"""Activate scanned containers plus an authenticated stdlib native host bridge.

Dry-run by default. No host package installation, local image build, or heavy
Python dependency extraction occurs. Only the three named CiteRAG units are managed.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import sys
import uuid

_spec = importlib.util.spec_from_file_location("citerag_host_guards",
    Path(__file__).with_name("activate-host-release.py"))
guards = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guards)
DeploymentError = guards.DeploymentError
absolute_path, run = guards.absolute_path, guards.run
UNITS = ("citerag-production-mcp", "citerag-production-web",
         "citerag-production-native-bridge")
BRIDGE_URL = "http://127.0.0.1:60760"
SOURCE_PARTS = ("citerag", "configs", "docs", "tasks", "requirements.lock.txt")


def private_environment(path, uid):
    path = absolute_path(path)
    if not path.is_file() or path.stat().st_uid != uid or path.stat().st_mode & 0o077:
        raise DeploymentError("Environment must be owned by the runtime user and mode 0600")
    values = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"CITERAG_[A-Z0-9_]+|HF_HUB_OFFLINE", key) or key in values:
            raise DeploymentError("Invalid or duplicate environment entry")
        values[key] = value
    return values


def validate_bridge(values, bridge, uid):
    if values.get("CITERAG_NATIVE_BRIDGE_URL") != BRIDGE_URL:
        raise DeploymentError("Explicit loopback native bridge required")
    token = values.get("CITERAG_NATIVE_BRIDGE_TOKEN", "")
    if len(token) < 32 or token == values.get("CITERAG_API_TOKEN") or bridge.get("CITERAG_NATIVE_BRIDGE_TOKEN") != token:
        raise DeploymentError("Independent matching bridge credential required")
    if "CITERAG_NATIVE_BRIDGE_URL" in bridge:
        raise DeploymentError("Host bridge environment must not recurse to itself")
    if not values.get("CITERAG_BACKEND_ID") or bridge.get("CITERAG_BACKEND_ID") != values["CITERAG_BACKEND_ID"]:
        raise DeploymentError("Backend identity must match")
    expected = "http://127.0.0.1:" + values.get("CITERAG_MCP_PORT", "18761") + "/mcp"
    if bridge.get("CITERAG_NATIVE_MCP_URL") != expected:
        raise DeploymentError("Bridge must target this deployment MCP listener")
    native_env = private_environment(bridge.get("CITERAG_NATIVE_ENV_FILE", ""), uid)
    if native_env.get("CITERAG_API_TOKEN") != values["CITERAG_API_TOKEN"]:
        raise DeploymentError("Scoped native API credential must match this backend")
    binary = absolute_path(bridge.get("CITERAG_NATIVE_BINARY_DIR", "")) / "opencode"
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise DeploymentError("Reviewed native executable missing")


def source_roots(values):
    try:
        sources = json.loads(values.get("CITERAG_REPOSITORY_SOURCES", "{}"))
    except ValueError as exc:
        raise DeploymentError("Invalid approved source mapping") from exc
    if not isinstance(sources, dict) or len(sources) > 8:
        raise DeploymentError("Invalid approved source mapping")
    roots = []
    for name, value in sources.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name) or not isinstance(value, str):
            raise DeploymentError("Invalid approved source name")
        path = absolute_path(value)
        if not path.is_dir():
            raise DeploymentError("Approved source directory missing")
        roots.append(path)
    return sorted(set(roots))


def validate(args):
    if not guards.IMAGE.fullmatch(args.image) or not re.fullmatch(r"[a-f0-9]{40}", args.source_sha):
        raise DeploymentError("Exact scoped image digest and source SHA required")
    release = absolute_path(args.release_dir)
    if release.exists() or len(release.parts) < 4:
        raise DeploymentError("Release directory must be new and narrowly scoped")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", args.user):
        raise DeploymentError("Invalid runtime user")
    account = pwd.getpwnam(args.user)
    if account.pw_uid == 0 or account.pw_uid != os.getuid():
        raise DeploymentError("Run as the non-root runtime account")
    values = guards.environment(args.env_file, account.pw_uid, release, args.state_dir)
    bridge = private_environment(args.bridge_env_file, account.pw_uid)
    validate_bridge(values, bridge, account.pw_uid)
    roots = source_roots(values)
    ports = [int(values.get("CITERAG_MCP_PORT", "18761")),
             int(values.get("CITERAG_WEB_PORT", "18762")), 60760]
    if len(set(ports)) != 3:
        raise DeploymentError("Listener ports must differ")
    for port in ports:
        try:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", port))
        except OSError as exc:
            raise DeploymentError("Occupied listener; no process was stopped") from exc
    if not Path("/usr/bin/python3.12").is_file():
        raise DeploymentError("Host Python 3.12 required for the stdlib bridge")
    if shutil.disk_usage(release.parent if release.parent.exists() else Path("/")).free < 4 * 1024**3:
        raise DeploymentError("At least 4 GiB free disk required")
    for unit in UNITS:
        path = Path("/etc/systemd/system/" + unit + ".service")
        if path.is_symlink():
            raise DeploymentError("Symlinked installed unit requires review")
        if path.exists() and (not args.replace_existing or guards.unit_state(unit)["active"]):
            raise DeploymentError("Existing named units require explicit stopped replacement")
        # Never remove or stop an unrelated container with a colliding name.
        found = subprocess.run(["docker", "container", "inspect", unit],
                               text=True, capture_output=True, timeout=10)
        if found.returncode == 0:
            raise DeploymentError("Named container already exists; review it explicitly")
    return release, values, bridge, roots, account


def container_command(kind, image, release, runtime_env, values, state, roots, account):
    if kind not in {"mcp", "web"}:
        raise DeploymentError("Invalid service kind")
    name = "citerag-production-" + kind
    command = ["/usr/bin/docker", "run", "--rm", "--name", name,
        "--label", "org.citerag.managed=production", "--network", "host",
        "--user", str(account.pw_uid) + ":" + str(account.pw_gid),
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "160", "--memory", "1500m", "--cpus", "1",
        "--tmpfs", "/tmp:rw,nosuid,size=64m,mode=1777",
        "--env-file", str(runtime_env)]
    mounts = [(release / "src/data", Path("/app/data"), False),
              (release / "src/reports", Path("/app/reports"), False),
              (Path(values["CITERAG_MODEL_CACHE_DIR"]), Path(values["CITERAG_MODEL_CACHE_DIR"]), True),
              (Path(state), Path(state), False)]
    mounts += [(path, path, True) for path in roots]
    for source, destination, readonly in mounts:
        command += ["--mount", "type=bind,src=" + str(source) + ",dst=" + str(destination) +
                    (",readonly" if readonly else "")]
    # No Docker socket, host root, native binary, or host credential file is mounted.
    return command + [image, "python", "-m", "citerag.server" if kind == "mcp" else "citerag.web"]


def unit_text(kind, command, release, env_file=None, state=None, user=None):
    if kind == "native-bridge":
        service = ("User=" + user + "\nWorkingDirectory=" + str(release / "src") +
            "\nEnvironment=PYTHONPATH=" + str(release / "src") +
            "\nEnvironment=PYTHONDONTWRITEBYTECODE=1\nEnvironmentFile=" + str(env_file) +
            "\nExecStart=/usr/bin/python3.12 " + str(release / "src/tasks/native-host-bridge.py") +
            "\nMemoryMax=256M\nCPUQuota=50%\nTasksMax=96\nPrivateTmp=true" +
            "\nProtectSystem=strict\nProtectHome=read-only\nReadWritePaths=" +
            str(release / "src/reports") + " " + str(release / "src/data") + " " + str(state))
    else:
        # Validated paths and arguments contain neither whitespace nor systemd specifiers.
        service = ("User=" + user + "\nExecStart=" + " ".join(command) +
            "\nExecStop=/usr/bin/docker stop --time 10 citerag-production-" + kind +
            "\nMemoryMax=128M\nCPUQuota=50%\nTasksMax=96")
    return ("[Unit]\nDescription=CiteRAG isolated production " + kind +
        "\nAfter=docker.service network-online.target\nWants=network-online.target" +
        "\nStartLimitIntervalSec=120\nStartLimitBurst=3\n\n[Service]\nType=simple\n" +
        service + "\nRestart=on-failure\nRestartSec=5\nTimeoutStopSec=20" +
        "\nNoNewPrivileges=true\nUMask=0077\n\n[Install]\nWantedBy=multi-user.target\n")


def restore(old, states, backups):
    failures = []
    def attempt(command):
        try:
            run(command, timeout=30)
        except (DeploymentError, OSError, subprocess.SubprocessError):
            failures.append(True)
    attempt(["sudo", "-n", "systemctl", "stop", *UNITS])
    for unit in UNITS:
        try:
            subprocess.run(["sudo", "-n", "systemctl", "disable", unit], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            failures.append(True)
        target = "/etc/systemd/system/" + unit + ".service"
        if unit in old:
            attempt(["sudo", "-n", "install", "-m", "0644", str(backups / (unit + ".service")), target])
        else:
            attempt(["sudo", "-n", "rm", "-f", "--", target])
    attempt(["sudo", "-n", "systemctl", "daemon-reload"])
    for unit, previous in states.items():
        if previous["enabled"] in {"enabled", "enabled-runtime"}:
            extra = ["--runtime"] if previous["enabled"] == "enabled-runtime" else []
            attempt(["sudo", "-n", "systemctl", "enable", *extra, unit])
        if previous["active"]:
            attempt(["sudo", "-n", "systemctl", "start", unit])
        try:
            if guards.unit_state(unit) != previous:
                failures.append(True)
        except (OSError, subprocess.SubprocessError):
            failures.append(True)
    return not failures


def activate(args, release, values, bridge, roots, account):
    run(["docker", "pull", args.image], capture=False, timeout=600)
    info = json.loads(run(["docker", "image", "inspect", args.image]))[0]
    if args.image not in info.get("RepoDigests", []) or info.get("Architecture") != "amd64" or info.get("Os") != "linux":
        raise DeploymentError("Artifact digest/platform mismatch")
    if (info.get("Config", {}).get("Labels") or {}).get("org.opencontainers.image.revision") != args.source_sha:
        raise DeploymentError("Artifact source mismatch")
    release.mkdir(parents=True, exist_ok=False)
    source = release / "src"
    source.mkdir(mode=0o700)
    container = "citerag-extract-" + uuid.uuid4().hex[:12]
    created = False
    try:
        run(["docker", "create", "--name", container, "--network", "none", args.image])
        created = True
        for part in SOURCE_PARTS:
            run(["docker", "cp", container + ":/app/" + part, str(source / part)], timeout=120)
    finally:
        if created:
            run(["docker", "rm", container])
    if any(path.is_symlink() for path in source.rglob("*")):
        raise DeploymentError("Unexpected source artifact symlink")
    for part in ("data", "reports"):
        (source / part).mkdir(mode=0o700)
    ledger = Path(args.state_dir) / "admission.sqlite3"
    descriptor = os.open(ledger, os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(descriptor)
    runtime = release / "environments"
    runtime.mkdir(mode=0o700)
    runtime_paths = {}
    mcp_allowed = {"CITERAG_API_TOKEN", "CITERAG_PRODUCTION", "CITERAG_REQUIRE_AUTH",
        "CITERAG_WORKSPACE_ID", "CITERAG_POLICY_DB", "CITERAG_RATE_LIMIT_PER_MINUTE",
        "CITERAG_GENERATION_LIMIT_PER_DAY", "CITERAG_OFFLINE", "HF_HUB_OFFLINE",
        "CITERAG_MODEL_CACHE_DIR", "CITERAG_EMBEDDING_MODEL", "CITERAG_EMBEDDING_REVISION",
        "CITERAG_REPOSITORY_SOURCES", "CITERAG_MCP_HOST", "CITERAG_MCP_PORT", "CITERAG_BACKEND_ID"}
    for kind in ("mcp", "web"):
        selected = {key: value for key, value in values.items()
                    if kind == "web" or key in mcp_allowed}
        for key in ("CITERAG_NATIVE_ENV_FILE", "CITERAG_NATIVE_BINARY_DIR"):
            selected.pop(key, None)
        path = runtime / (kind + ".env")
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
            for key, value in selected.items():
                handle.write(key + "=" + value + "\n")
        runtime_paths[kind] = path
    # Use the image's patched Python and SQLite libraries for every retrieval import.
    run(["docker", "run", "--rm", "--network", "none", "--read-only",
         "--user", str(account.pw_uid) + ":" + str(account.pw_gid),
         "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
         "--memory", "1500m", "--cpus", "1", "--tmpfs", "/tmp:rw,size=64m",
         args.image, "python", "-c",
         "import citerag.web,citerag.server,torch,lancedb,sentence_transformers,sqlite3"], timeout=90)
    # Host control process imports only stdlib modules; never the backend dependency tree.
    run(["/usr/bin/python3.12", "-m", "py_compile", str(source / "tasks/native-host-bridge.py")], timeout=10)
    staged, backups = release / "units", release / "unit-backups"
    staged.mkdir()
    backups.mkdir(mode=0o700)
    for kind in ("mcp", "web"):
        command = container_command(kind, args.image, release, runtime_paths[kind], values,
                                    args.state_dir, roots, account)
        (staged / ("citerag-production-" + kind + ".service")).write_text(
            unit_text(kind, command, release, user=args.user))
    (staged / "citerag-production-native-bridge.service").write_text(
        unit_text("native-bridge", [], release, args.bridge_env_file, args.state_dir, args.user))
    run(["systemd-analyze", "verify", *[str(path) for path in staged.glob("*.service")]])
    old, states = {}, {unit: guards.unit_state(unit) for unit in UNITS}
    if any(state["active"] for state in states.values()):
        raise DeploymentError("Prior named units must remain stopped")
    for unit in UNITS:
        previous = Path("/etc/systemd/system/" + unit + ".service")
        if previous.exists():
            old[unit] = previous.read_text()
            (backups / previous.name).write_text(old[unit])
    (backups / "prior-state.json").write_text(json.dumps(states, indent=2) + "\n")
    manifest = {"image": args.image, "image_id": info["Id"], "source_sha": args.source_sha,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "backend_runtime": "scanned-container", "native_control_runtime": "host-stdlib-only",
        "persistent_state": str(args.state_dir), "listener_scope": "IPv4 loopback"}
    (release / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    try:
        for unit in UNITS:
            run(["sudo", "-n", "install", "-m", "0644", str(staged / (unit + ".service")),
                 "/etc/systemd/system/" + unit + ".service"])
        run(["sudo", "-n", "systemctl", "daemon-reload"])
        run(["sudo", "-n", "systemctl", "enable", "--now", *UNITS], timeout=45)
        for unit in UNITS:
            run(["systemctl", "is-active", "--quiet", unit])
    except Exception:
        if restore(old, states, backups):
            raise DeploymentError("Activation failed; prior unit definitions and states restored") from None
        raise DeploymentError("Activation failed; manual unit restoration required") from None
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--bridge-env-file", type=Path, required=True)
    parser.add_argument("--user", default=pwd.getpwuid(os.getuid()).pw_name)
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args(argv)
    try:
        validated = validate(args)
        result = {"status": "VALIDATED", "activation_requested": args.activate,
                  "image": args.image, "source_sha": args.source_sha,
                  "release_dir": str(validated[0]), "units": list(UNITS), "secrets_printed": False}
        if args.activate:
            result.update(activate(args, *validated))
            result["status"] = "ACTIVE_NOT_CERTIFIED"
        print(json.dumps(result, sort_keys=True))
        return 0
    except (DeploymentError, OSError, ValueError, KeyError, subprocess.SubprocessError):
        print(json.dumps({"status": "BLOCKED", "reason": "ContainerDeploymentFailed",
                          "secrets_printed": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
