#!/usr/bin/env python3
"""Check a bounded native OpenCode trace without rerunning inference.

This is an evidence-consumer, not a native runner or backend attestation.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from citerag.native_result import evaluate

MAX_TRACE_BYTES = 5 * 1024 * 1024
ALLOWED_TOOLS = frozenset(("moe-rag_rag_search", "citerag_search"))


class EvidenceError(RuntimeError):
    pass


def verify(trace, *, exit_code, tool, expected_source=None):
    if tool not in ALLOWED_TOOLS:
        raise EvidenceError("UNAPPROVED_TOOL_NAME")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise EvidenceError("INVALID_EXIT_CODE")
    if expected_source and (not isinstance(expected_source, str) or
                            not re.fullmatch(r"docs/[A-Za-z0-9_./-]+\.(md|txt)", expected_source) or
                            ".." in Path(expected_source).parts):
        raise EvidenceError("INVALID_SOURCE_CONSTRAINT")
    if not isinstance(trace, str) or len(trace.encode("utf-8")) > MAX_TRACE_BYTES:
        raise EvidenceError("TRACE_SIZE_INVALID")
    report = evaluate(trace, exit_code, tool_name=tool)
    sources = sorted({row.get("source", "") for row in report.get("retrieved_sources", [])})
    match_source = expected_source is None or expected_source in sources
    passed = report["status"] == "PASS" and match_source
    # Do NOT print answers or tool output, which may contain untrusted text.
    return {
        "status": "PASS" if passed else "FAIL",
        "native_tool_calls": report["native_tool_calls"],
        "citations_verified": bool(report["citations_verified"]),
        "claims_supported": bool(report["claims_supported"]),
        "stopped": bool(report["stop_observed"]),
        "unexpected_tool_calls": report["unexpected_tool_calls"],
        "error_events": report["error_events"],
        "evidence_source_count": len(sources),
        "source_constraint_matched": match_source,
        "model_inference_started": False,
        "backend_identity_attested": False,
        "standalone_production_certified": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trace", type=Path)
    ap.add_argument("--tool", choices=sorted(ALLOWED_TOOLS), required=True)
    ap.add_argument("--exit-code", type=int, required=True)
    ap.add_argument("--expected-source", default=None)
    args = ap.parse_args(argv)
    try:
        path = args.trace
        if not path.is_file() or path.is_symlink():
            raise EvidenceError("TRACE_FILE_MISSING_OR_SYMLINKED")
        if not 0 < path.stat().st_size <= MAX_TRACE_BYTES:
            raise EvidenceError("TRACE_SIZE_INVALID")
        report = verify(path.read_text(encoding="utf-8"),
                        exit_code=args.exit_code, tool=args.tool,
                        expected_source=args.expected_source)
    except (EvidenceError, UnicodeError, OSError) as err:
        report = {"status": "FAIL", "reason": type(err).__name__,
                  "model_inference_started": False,
                  "backend_identity_attested": False,
                  "standalone_production_certified": False}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
