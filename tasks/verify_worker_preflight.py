#!/usr/bin/env python3
"""Offline verification of exactly 20 GitHub Actions worker-preflight artifacts."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tasks.worker_preflight import TOTAL, slot


class EvidenceError(ValueError):
    pass


def validate(rows):
    if type(rows) is not list or len(rows) != TOTAL:
        raise EvidenceError("Expected exactly twenty results")
    slots = set()
    for row in rows:
        if type(row) is not dict:
            raise EvidenceError("Malformed worker result")
        index = row.get("slot")
        if type(index) is not int or index in slots or index not in range(TOTAL):
            raise EvidenceError("Missing or duplicated slot")
        role, shard, source = slot(index, TOTAL)
        expected = {"slot": index, "total": TOTAL, "role": role, "shard": shard,
                    "source": source, "status": "preflight_pass",
                    "ai_inference": False, "writes_to_repository": False}
        if row != expected:
            raise EvidenceError("Shard payload mismatches approved assignment")
        slots.add(index)
    if slots != set(range(TOTAL)):
        raise EvidenceError("Not all slots accounted for")
    return {"status": "PASS", "verified_slots": TOTAL,
            "cloud_worker_claim": False, "model_inference": False}


def verify_directory(directory):
    if not directory.is_dir() or directory.is_symlink():
        raise EvidenceError("Result directory missing or symlinked")
    files = sorted(directory.glob("slot-*.json"))
    if len(files) != TOTAL:
        raise EvidenceError("Exactly 20 result files required")
    rows = []
    for path in files:
        if path.is_symlink() or path.stat().st_size > 4096 or path.stat().st_size == 0:
            raise EvidenceError("Invalid result file")
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return validate(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_directory(args.dir)
    except (EvidenceError, ValueError, OSError) as error:
        result = {"status": "FAIL", "reason": type(error).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
