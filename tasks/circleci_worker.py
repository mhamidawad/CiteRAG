#!/usr/bin/env python3
"""Fail-closed thirty-slot CircleCI preflight. NOT autonomous AI inference."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("planner", "retrieval", "tests", "security", "review")
# Five job roles, six independent shards each. No model calls, credentials or
# repository writes. The controller is still OpenCode on the Oracle VM.
SHARDS = {
    "planner": ("README.md", "CONTRIBUTING.md", "docs/architecture.md", ".circleci/config.yml", ".github/pull_request_template.md", "docs/go-public-checklist.md"),
    "retrieval": ("citerag/semantic.py", "citerag/quotes.py", "citerag/context.py", "citerag/server.py", "citerag/answer.py", "citerag/cli.py"),
    "tests": ("tests/test_retrieval.py", "tests/test_web.py", "tests/test_adapters.py", "tests/test_secret_scanner.py", "tests/test_dashboard_contract.py", "tests/test_deployment_preflight.py"),
    "security": ("tasks/scan-secrets.py", "SECURITY.md", "citerag/native_result.py", "citerag/freshness.py", "tests/test_native_result.py", "docs/rollback.md"),
    "review": ("Dockerfile", "compose.yaml", "docs/private-preview-acceptance.md", "requirements.lock.txt", "LICENSE", "docs/docker.md"),
}
TOTAL = len(ROLES) * 6

def slot(index, total):
    if total != TOTAL or index not in range(TOTAL):
        raise ValueError("Expected exactly 30 CircleCI nodes numbered 0–29")
    role = ROLES[index // 6]
    shard = index % 6
    return role, shard, SHARDS[role][shard]

def check(index, total):
    role, shard, name = slot(index, total)
    file = (ROOT / name).resolve()
    if not file.is_relative_to(ROOT.resolve()) or not file.is_file() or file.is_symlink():
        raise RuntimeError("Approved tracked task file missing or unsafe")
    # Only the assigned, immutable source file is inspected; never run user
    # instructions, model calls or arbitrary shell tasks.
    if file.suffix == ".py":
        command = [sys.executable, "-B", "-c",
                   "import ast,sys;ast.parse(open(sys.argv[1], encoding='utf-8').read())",
                   str(file)]
    else:
        command = [sys.executable, "-B", "-c",
                   "import pathlib,sys; p=pathlib.Path(sys.argv[1]);"
                   "assert 0<p.stat().st_size<2000000",str(file)]
    result = subprocess.run(command, cwd=ROOT, timeout=30, check=False,
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Worker task scope check failed")
    return {"slot": index, "total": total, "role": role, "shard": shard,
            "source": name, "status": "preflight_pass",
            "ai_inference": False, "writes_to_repository": False}

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=None)
    parser.add_argument("--total", type=int, default=None)
    args = parser.parse_args(argv)
    index = args.index if args.index is not None else int(os.environ["CIRCLE_NODE_INDEX"])
    total = args.total if args.total is not None else int(os.environ["CIRCLE_NODE_TOTAL"])
    result = check(index, total)
    output = Path("/tmp/citerag-worker-result.json")
    output.write_text(json.dumps(result, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
