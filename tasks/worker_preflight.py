#!/usr/bin/env python3
"""Bounded, read-only 20-slot source preflight. No AI calls or repository writes."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("planner", "retrieval", "tests", "security", "review")
SHARDS = {
    "planner": ("README.md", "CONTRIBUTING.md", "docs/architecture.md", ".github/workflows/tests.yml"),
    "retrieval": ("citerag/semantic.py", "citerag/quotes.py", "citerag/context.py", "citerag/server.py"),
    "tests": ("tests/test_retrieval.py", "tests/test_web.py", "tests/test_adapters.py", "tests/test_secret_scanner.py"),
    "security": ("tasks/scan-secrets.py", "SECURITY.md", "citerag/native_result.py", "citerag/freshness.py"),
    "review": ("Dockerfile", "compose.yaml", "docs/private-preview-acceptance.md", "requirements.lock.txt"),
}
TOTAL = len(ROLES) * 4


def slot(index, total):
    if total != TOTAL or type(index) is not int or index not in range(TOTAL):
        raise ValueError("Expected exactly 20 preflight slots numbered 0–19")
    role = ROLES[index // 4]
    shard = index % 4
    return role, shard, SHARDS[role][shard]


def check(index, total):
    role, shard, name = slot(index, total)
    original = ROOT / name
    source = original.resolve()
    if not source.is_relative_to(ROOT.resolve()) or not source.is_file() or original.is_symlink():
        raise RuntimeError("Approved tracked source missing or unsafe")
    if source.suffix == ".py":
        command = [sys.executable, "-B", "-c",
                   "import ast,sys;ast.parse(open(sys.argv[1], encoding='utf-8').read())",
                   str(source)]
    else:
        command = [sys.executable, "-B", "-c",
                   "import pathlib,sys; p=pathlib.Path(sys.argv[1]);"
                   "assert 0<p.stat().st_size<2000000", str(source)]
    result = subprocess.run(command, cwd=ROOT, timeout=30, check=False,
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Worker scope preflight failed")
    return {"slot": index, "total": total, "role": role, "shard": shard,
            "source": name, "status": "preflight_pass",
            "ai_inference": False, "writes_to_repository": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--total", type=int, default=TOTAL)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    allowed = Path(os.environ.get("RUNNER_TEMP", "/tmp")).resolve()
    if not allowed.is_dir():
        raise RuntimeError("Temporary result directory unavailable")
    target = args.output.resolve()
    if not target.is_relative_to(allowed) or target.is_symlink() or target.suffix != ".json":
        raise ValueError("Output must be a JSON file inside the temporary runner directory")
    result = check(args.index, args.total)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
