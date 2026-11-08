#!/usr/bin/env python3
"""Bounded CircleCI preflight controller. No model inference or agent execution."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = "circleci/Kx8pciLC7qhz2rchu5dCCp/K7MgxSTs4WcZYBZn3MYSKh"
BRANCH = "feat/circleci-20-concurrency-cap-20261108"
DEFINITION = "e4883277-27dc-4756-9494-1394cc7c497e"  # build-and-test
MAX_SLOTS = 20
API = "https://circleci.com/api/v2/"
TOKEN_FILE = Path.home() / ".config/citerag/circleci.env"
ACTIVE = {"pending", "queued", "created", "running", "not_run", "on_hold", "blocked"}
PRESENT = {"success", "failed", "error", "errored", "canceled", "cancelled", "failing"}

class GateError(RuntimeError):
    pass

def token_from_file(path=TOKEN_FILE):
    # Do not evaluate shell syntax / execute the credential file.
    if not path.is_file() or path.is_symlink() or (path.stat().st_mode & 0o077):
        raise GateError("Credential file missing, symlinked or permissions too open")
    found = []
    for line in path.read_text().splitlines():
        m = re.fullmatch(r"CIRCLECI_TOKEN=(?:'([^']+)'|\"([^\"]+)\"|([^\s\"']+))", line.strip())
        if m:
            found.append(next(group for group in m.groups() if group is not None))
    if len(found) != 1 or not found[0].startswith("CCIPAT_"):
        raise GateError("Valid CircleCI personal token not found")
    return found[0]

def request(token, method, path, body=None):
    if not path.startswith(("project/", "pipeline/", "workflow/", "me")):
        raise GateError("Unsupported CircleCI API path")
    url = API + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Circle-Token": token, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.load(r)
    except urllib.error.HTTPError as ex:
        raise GateError("CircleCI API HTTP " + str(ex.code)) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise GateError("CircleCI API unavailable or unexpected response") from None

def verify_project(token, get=request):
    me = get(token, "GET", "me")
    proj = get(token, "GET", "project/" + PROJECT)
    if not me.get("id") or proj.get("id") != "92a7b55f-2fa6-4db1-88f2-7437c381c958":
        raise GateError("Account or project identity mismatch")
    if proj.get("name") != "supervisor":
        raise GateError("Wrong CircleCI project")
    return True

def inspect(token, get=request):
    verify_project(token, get)
    data = get(token, "GET", "project/" + PROJECT + "/pipeline")
    entries = data.get("items", [])
    if not isinstance(entries, list):
        raise GateError("Invalid pipeline list")
    # Fail closed on pagination: cannot certify an idle project from a partial listing.
    if data.get("next_page_token"):
        raise GateError("Unbounded pipeline history: pagination requires operator review")
    active = []
    observed = []
    for p in entries:
        state = p.get("state")
        pid = p.get("id")
        if not pid or not isinstance(state, str):
            raise GateError("Malformed CircleCI pipeline")
        observed.append({"number": p.get("number"), "state": state})
        if state in ACTIVE:
            w = get(token, "GET", "pipeline/" + pid + "/workflow")
            if w.get("next_page_token"):
                raise GateError("Unbounded workflow list")
            flows = w.get("items", [])
            if not isinstance(flows, list):
                raise GateError("Invalid workflow list")
            # Pipeline state 'created' is not itself a running workflow in
            # CircleCI. Parameters with run_workers=false create no workflow.
            # Treat empty workflows as inactive only after a 10 minute settle
            # period; malformed timestamps and unknown conditions block launch.
            if not flows:
                created = p.get("created_at")
                try:
                    when = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - when).total_seconds()
                except (AttributeError, TypeError, ValueError):
                    raise GateError("Pipeline timestamp unavailable") from None
                if age < 600:
                    active.append({"pipeline": p.get("number"), "state": state,
                                   "reason": "empty workflow within settle period"})
            for item in flows:
                st = item.get("status")
                if st not in PRESENT:
                    active.append({"pipeline": p.get("number"), "workflow": item.get("name"), "status": st})
        elif state not in PRESENT:
            raise GateError("Unknown pipeline state: fail closed")
    return {"project": "supervisor", "configured_slots": MAX_SLOTS,
            "examined_pipelines": len(observed), "active": active,
            "history": observed[:10], "can_dispatch": not active}

def trigger(token, get=request):
    state = inspect(token, get)
    if not state["can_dispatch"]:
        raise GateError("Existing active CircleCI pipeline: duplicate dispatch denied")
    # This operation launches exactly one 20-slot read-only preflight; not AI work.
    result = get(token, "POST", "project/" + PROJECT + "/pipeline/run",
                 {"definition_id": DEFINITION, "config": {"branch": BRANCH},
                  "checkout": {"branch": BRANCH},
                  "parameters": {"run_workers": True}})
    if not result.get("id"):
        raise GateError("CircleCI did not return a pipeline ID")
    return {"pipeline_id": result["id"], "number": result.get("number"),
            "state": result.get("state"), "slots_requested": MAX_SLOTS}

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("status", "dispatch"))
    ap.add_argument("--confirm-readonly-20", action="store_true",
                    help="Required to start one bounded read-only cloud preflight")
    opts = ap.parse_args(argv)
    try:
        if opts.command == "dispatch" and not opts.confirm_readonly_20:
            raise GateError("Dispatch requires --confirm-readonly-20")
        token = token_from_file()
        answer = inspect(token) if opts.command == "status" else trigger(token)
        print(json.dumps(answer, sort_keys=True))
    except GateError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
