#!/usr/bin/env python3
"""One bounded free-local OmniRoute cited-answer acceptance, with real abstention."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_environment(path):
    if not path or not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError("DedicatedEnvironmentMissing")
    if path.stat().st_mode & 0o077:
        raise ValueError("DedicatedEnvironmentPermissions")
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            if key.startswith("CITERAG_"):
                os.environ[key] = value


def run(question, required_terms):
    from citerag import answer
    from citerag.freshness import prepare_context
    from citerag.native_result import runtime_fingerprint, ABSTENTION
    if answer.configuration_status() != "ready":
        raise ValueError("LocalOnlyConfigurationRequired")
    if not required_terms or any(not term.strip() for term in required_terms):
        raise ValueError("AcceptanceTermsRequired")
    started = datetime.now(timezone.utc).isoformat()
    if prepare_context().get("status") != "completed":
        raise ValueError("ApprovedContextNotFresh")
    result = answer.answer(question)
    # This random opaque topic was never part of the approved corpus.
    unsupported = answer.answer("unsupported_" + uuid.uuid4().hex)
    terms = all(term.casefold() in result.get("answer", "").casefold() for term in required_terms)
    abstained = (unsupported.get("status") == "insufficient_evidence"
        and unsupported.get("answer") == ABSTENTION and unsupported.get("sources") == []
        and unsupported.get("model_request_started") is False and unsupported.get("attempts") == 0)
    ok = (result.get("status") == "completed" and result.get("citations_verified")
        and result.get("claims_supported") and terms and abstained)
    return {"status": "PASS" if ok else "FAIL", "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "model": answer.MODEL, "free_local_model": True, "attempts": result.get("attempts", 0),
        "required_acceptance_terms": required_terms, "acceptance_terms_verified": terms,
        "unsupported_abstention_verified": abstained,
        "citations_verified": bool(result.get("citations_verified")),
        "claims_supported": bool(result.get("claims_supported")),
        "sources": result.get("sources", []), "final_answer": result.get("answer", ""),
        "error": result.get("error"), "runtime_fingerprint": runtime_fingerprint(),
        "deployment_fingerprint": answer.deployment_fingerprint(),
        "standalone_production_certified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--question", default="Which vector database does this project use?")
    parser.add_argument("--require-term", action="append", required=True)
    parser.add_argument("--certify-current", action="store_true")
    args = parser.parse_args()
    try:
        load_environment(args.env_file)
        report = run(args.question, args.require_term)
        directory = ROOT / "reports"
        directory.mkdir(exist_ok=True)
        path = directory / ("omniroute-current-verification.json" if args.certify_current and report["status"] == "PASS"
            else "omniroute-acceptance-" + uuid.uuid4().hex + ".json")
        path.write_text(json.dumps(report, indent=2) + "\n")
        path.chmod(0o600)
    except (ValueError, OSError, RuntimeError) as exc:
        report = {"status": "BLOCKED", "reason": type(exc).__name__,
                  "standalone_production_certified": False}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
