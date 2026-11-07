#!/usr/bin/env python3
"""Fail-closed five-slot CircleCI preflight. NOT autonomous AI inference."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("planner", "retrieval", "tests", "security", "review")
MANDATORY = {
    "planner": ("README.md", ".circleci/config.yml"),
    "retrieval": ("citerag/semantic.py", "citerag/quotes.py"),
    "tests": ("tests/test_retrieval.py", "tests/test_web.py"),
    "security": ("tasks/scan-secrets.py",),
    "review": ("CONTRIBUTING.md", "SECURITY.md"),
}

def slot(index, total):
    if total != 5 or index not in range(5):
        raise ValueError("Expected exactly five CircleCI nodes numbered 0–4")
    return ROLES[index]

def check(index, total):
    role = slot(index, total)
    for name in MANDATORY[role]:
        file = (ROOT / name).resolve()
        if not file.is_relative_to(ROOT) or not file.is_file():
            raise RuntimeError("Expected approved tracked file is missing")
    # Preflight jobs never execute an LLM, pull private data or accept arbitrary commands.
    if role == "security":
        command = [sys.executable, "tasks/scan-secrets.py"]
    elif role == "tests":
        command = [sys.executable, "-B", "-c",
                   "import ast,pathlib;root=pathlib.Path('.');"
                   "files=[*root.glob('citerag/*.py'),*root.glob('tests/*.py'),*root.glob('tasks/*.py')];"
                   "assert files;"
                   "[ast.parse(p.read_text(),filename=str(p)) for p in files]"]
    elif role == "review":
        command = ["git", "diff", "--check", "HEAD"]
    else:
        command = [sys.executable, "-c", "print('scoped source files verified')"]
    result = subprocess.run(command, cwd=ROOT, timeout=90, check=False,
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Worker scope check failed")
    return {"slot": index, "total": total, "role": role, "status": "preflight_pass",
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
