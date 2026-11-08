#!/usr/bin/env python3
"""Fail-closed read-only authentication gate for an isolated rollback candidate.

This checks a Docker container and loopback REST endpoint; it never changes
routes, images, containers or secrets, and is NOT a completed rollback drill.
"""
import argparse
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.request

PINNED = re.compile(r"^[a-z0-9./_-]+@sha256:[0-9a-f]{64}$")


def inspect_candidate(name, port):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,100}", name):
        raise ValueError("INVALID_CONTAINER_NAME")
    if not 1024 <= port <= 65535:
        raise ValueError("INVALID_LOOPBACK_PORT")
    raw = subprocess.check_output(["docker", "inspect", name], timeout=9)
    objects = json.loads(raw)
    if len(objects) != 1:
        raise ValueError("CONTAINER_IDENTITY_MISMATCH")
    c = objects[0]
    cfg, host, state = c["Config"], c["HostConfig"], c["State"]
    mapped = host.get("PortBindings") or {}
    bindings = [binding for rows in mapped.values() for binding in (rows or [])]
    safe = (
        state.get("Running") is True
        and bool(PINNED.fullmatch(cfg.get("Image") or ""))
        and cfg.get("User") not in ("", "root", "0", "0:0", None)
        and host.get("ReadonlyRootfs") is True
        and host.get("Privileged") is False
        and any(b.get("HostIp") == "127.0.0.1"
                and b.get("HostPort") == str(port) for b in bindings)
        and all(b.get("HostIp") == "127.0.0.1" for b in bindings)
        and not any("docker.sock" in (m.get("Source") or "")
                    for m in c.get("Mounts", []))
    )
    if not safe:
        raise ValueError("CANDIDATE_ISOLATION_OR_DIGEST_INVALID")
    return {"digest_pinned": True, "loopback_only": True, "nonroot": True}


def read_token(path):
    p = pathlib.Path(path)
    st = p.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
        raise ValueError("UNSAFE_SECRET_PERMISSIONS")
    token = next((line.partition("=")[2] for line in p.read_text().splitlines()
                  if line.startswith("CITERAG_API_TOKEN=")), None)
    if not token or len(token) < 32 or any(x in token for x in "\r\n\t "):
        raise ValueError("MISSING_OR_WEAK_AUTH_TOKEN")
    return token


def request_status(port, token=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/context",
        headers={"Authorization": "Bearer " + token} if token else {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=7) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def certify(name, port, token):
    controls = inspect_candidate(name, port)
    anon = request_status(port)
    if anon != 401:
        return {"status": "BLOCKED", "reason": "ANONYMOUS_ACCESS_NOT_DENIED",
                "anonymous_http": anon, **controls}
    authorized = request_status(port, token)
    if authorized != 200:
        return {"status": "BLOCKED", "reason": "AUTHENTICATED_ACCESS_FAILED",
                "authorized_http": authorized, **controls}
    return {"status": "PASS", "anonymous_http": 401, "authorized_http": 200,
            **controls}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-container", required=True)
    parser.add_argument("--candidate-port", required=True, type=int)
    parser.add_argument("--token-env-file", required=True)
    args = parser.parse_args(argv)
    try:
        token = read_token(args.token_env_file)
        result = certify(args.candidate_container, args.candidate_port, token)
    except (ValueError, OSError, subprocess.SubprocessError,
            urllib.error.URLError, KeyError, IndexError) as exc:
        result = {"status": "BLOCKED", "reason": type(exc).__name__}
    result.update(traffic_cutover_performed=False, image_rollback_performed=False,
                  autonomous_production_certified=False)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
