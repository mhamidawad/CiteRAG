"""Bounded server-side native OpenCode adapter; credentials never enter requests."""
import json
import hashlib
from functools import lru_cache
import os
import subprocess
import sys
from pathlib import Path
from citerag.semantic import ROOT
from citerag.native_result import runtime_fingerprint
from citerag.freshness import prepare_context


@lru_cache(maxsize=4)
def _binary_digest(path, dev, ino, size, mtime_ns, ctime_ns):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def deployment_fingerprint(*,env_path=None,binary_dir=None,mcp_url=None,backend_id=None,
                           model="ollama-local/qwen3.5:4b-opencode"):
    env=Path(env_path or os.environ["CITERAG_NATIVE_ENV_FILE"])
    binary=Path(binary_dir or os.environ["CITERAG_NATIVE_BINARY_DIR"])/"opencode"
    stat=binary.stat()
    fields={"binary":_binary_digest(str(binary),stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns),
            "credentials":hashlib.sha256(env.read_bytes()).hexdigest(),
            "mcp_url":mcp_url or os.environ.get("CITERAG_NATIVE_MCP_URL","http://127.0.0.1:48761/mcp"),
            "backend_id":backend_id or os.environ.get("CITERAG_BACKEND_ID"),
            "model":model}
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()


def configuration_status():
    env = Path(os.environ.get("CITERAG_NATIVE_ENV_FILE", "/nonexistent"))
    binary = Path(os.environ.get("CITERAG_NATIVE_BINARY_DIR", "/nonexistent"))
    if (not env.is_absolute() or not env.is_file() or env.is_symlink()
            or env.stat().st_mode & 0o077 or not binary.is_absolute()
            or not (binary / "opencode").is_file()
            or not os.access(binary / "opencode", os.X_OK)
            or not os.environ.get("CITERAG_BACKEND_ID")):
        return "not_configured"
    return "ready"


def verification_status():
    if configuration_status() != "ready":
        return "unavailable"
    proof = ROOT / "reports/native-current-verification.json"
    if not proof.is_file() or proof.is_symlink():
        return "not_verified"
    try:
        data = json.loads(proof.read_text())
        return "verified" if (
            data.get("status") == "PASS"
            and data.get("automatic_tool_selection_verified")
            and data.get("backend_identity_attested")
            and data.get("acceptance_terms_verified")
            and bool(data.get("required_acceptance_terms"))
            and data.get("backend_id") == os.environ.get("CITERAG_BACKEND_ID")
            and data.get("runtime_fingerprint") == runtime_fingerprint()
            and data.get("deployment_fingerprint") == deployment_fingerprint()
        ) else "not_verified"
    except (ValueError, OSError, KeyError):
        return "not_verified"


def answer(question):
    if not (ROOT / "tasks/verify-native.py").is_file() or configuration_status() != "ready":
        return {"status": "failed", "error": "NativeAdapterUnavailable",
                "detail": "Dedicated native runner configuration is missing."}
    try:
        fresh = prepare_context()
    except Exception:
        fresh = {"status": "failed"}
    if fresh.get("status") != "completed":
        return {"status": "failed", "error": "ContextNotFresh"}
    command = [
        sys.executable, str(ROOT / "tasks/verify-native.py"),
        "--question", question,
        "--env-file", os.environ["CITERAG_NATIVE_ENV_FILE"],
        "--binary-dir", os.environ["CITERAG_NATIVE_BINARY_DIR"],
        "--mcp-url", os.environ.get("CITERAG_NATIVE_MCP_URL", "http://127.0.0.1:48761/mcp"),
        "--expected-backend-id", os.environ["CITERAG_BACKEND_ID"],
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=260)
        report = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "failed", "error": "NativeRunnerFailed"}
    if result.returncode or report.get("status") != "PASS" or not report.get("backend_identity_attested"):
        return {"status": "failed", "error": "NativeVerificationFailed",
                "detail": report.get("reason", "Native tool or grounding acceptance failed.")}
    return {
        "status": "insufficient_evidence" if report.get("abstained") else "completed",
        "mode": "native_opencode", "model": report.get("model"),
        "answer": report["final_answer"],
        "sources": [r["source"] for r in report.get("retrieved_sources", [])],
        "native_tool_calls": report["native_tool_calls"],
        "citations_verified": report["citations_verified"],
        "claims_supported": report["claims_supported"],
        "backend_identity_attested": True,
        "grounding_contract": report["grounding_contract"],
    }
