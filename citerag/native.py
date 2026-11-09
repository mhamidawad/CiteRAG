"""Bounded server-side native OpenCode adapter; credentials never enter requests."""
import json
import re
import hashlib
from functools import lru_cache
import os
import subprocess
import sys
from pathlib import Path
from citerag.semantic import ROOT
from citerag.native_result import runtime_fingerprint, ABSTENTION
from citerag.freshness import prepare_context


NATIVE_IMAGE = "local/opencode-agent:2.0.0"


def native_image_id():
    """Resolve the reviewed local tag without pulling or starting any container."""
    result = subprocess.run(["docker", "image", "inspect", NATIVE_IMAGE,
                             "--format", "{{.Id}}"],
                            capture_output=True, text=True, timeout=5)
    image_id = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
        raise ValueError("NATIVE_IMAGE_UNAVAILABLE")
    return image_id


@lru_cache(maxsize=4)
def _binary_digest(path, dev, ino, size, mtime_ns, ctime_ns):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def deployment_fingerprint(*,env_path=None,binary_dir=None,mcp_url=None,backend_id=None,
                           model="ollama-local/qwen3.5:4b-opencode",image_id=None):
    env=Path(env_path or os.environ["CITERAG_NATIVE_ENV_FILE"])
    binary=Path(binary_dir or os.environ["CITERAG_NATIVE_BINARY_DIR"])/"opencode"
    stat=binary.stat()
    fields={"binary":_binary_digest(str(binary),stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns),
            "credentials":hashlib.sha256(env.read_bytes()).hexdigest(),
            "mcp_url":mcp_url or os.environ.get("CITERAG_NATIVE_MCP_URL","http://127.0.0.1:48761/mcp"),
            "backend_id":backend_id or os.environ.get("CITERAG_BACKEND_ID"),
            "model":model,"image_id":image_id or native_image_id()}
    fields["bridge_implementation"] = bridge_code_fingerprint()
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()


BRIDGE_URL = "http://127.0.0.1:60760"


def bridge_code_fingerprint():
    path = ROOT / "tasks/native-host-bridge.py"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def bridge_configuration():
    url = os.environ.get("CITERAG_NATIVE_BRIDGE_URL", "")
    token = os.environ.get("CITERAG_NATIVE_BRIDGE_TOKEN", "")
    if url != BRIDGE_URL or len(token) < 32 or not os.environ.get("CITERAG_BACKEND_ID"):
        raise ValueError("NativeBridgeConfigurationInvalid")
    return url, token


def _bridge_request(path, payload=None):
    # Lazy import keeps the host runner/bridge on the Python standard library only.
    import httpx
    url, token = bridge_configuration()
    with httpx.Client(timeout=httpx.Timeout(270 if payload is not None else 6, connect=2),
                      follow_redirects=False, trust_env=False) as client:
        with client.stream("POST" if payload is not None else "GET", url + path,
                           headers={"Authorization": "Bearer " + token}, json=payload) as response:
            response.raise_for_status()
            chunks=[]; size=0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 262144: raise ValueError("NativeBridgeResponseTooLarge")
                chunks.append(chunk)
    result = json.loads(b"".join(chunks))
    if not isinstance(result, dict): raise ValueError("NativeBridgeResponseInvalid")
    return result


def _bridge_identity(report):
    return (report.get("backend_id") == os.environ.get("CITERAG_BACKEND_ID")
            and report.get("runtime_fingerprint") == runtime_fingerprint()
            and report.get("bridge_fingerprint") == bridge_code_fingerprint())


def _bridge_answer(question):
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 400:
        return {"status":"failed", "error":"NativeQuestionInvalid"}
    try:
        report = _bridge_request("/answer", {"question":question.strip(),
            "expected_backend_id":os.environ.get("CITERAG_BACKEND_ID")})
        calls=report.get("native_tool_calls")
        text=report.get("final_answer")
        sources=report.get("retrieved_sources")
        if (report.get("status") != "PASS" or not _bridge_identity(report)
                or report.get("backend_identity_attested") is not True
                or not isinstance(calls,int) or isinstance(calls,bool) or calls < 1
                or not isinstance(text,str) or not 1 <= len(text) <= 16384
                or not isinstance(sources,list)):
            raise ValueError("NativeBridgeVerificationFailed")
        abstained=(report.get("abstained") is True and text == ABSTENTION and not sources)
        if not abstained and not (report.get("citations_verified") is True and report.get("claims_supported") is True):
            raise ValueError("NativeBridgeGroundingFailed")
        if any(not isinstance(row,dict) or not isinstance(row.get("source"),str) for row in sources):
            raise ValueError("NativeBridgeSourcesInvalid")
        return {"status":"insufficient_evidence" if abstained else "completed",
            "mode":"native_opencode", "model":report.get("model"), "answer":text,
            "sources":[row["source"] for row in sources], "native_tool_calls":calls,
            "citations_verified":report.get("citations_verified") is True,
            "claims_supported":report.get("claims_supported") is True,
            "backend_identity_attested":True, "grounding_contract":"verbatim-extractive"}
    except Exception:
        # Never reflect upstream response bodies, URLs, credentials or exception messages.
        return {"status":"failed", "error":"NativeBridgeVerificationFailed"}


def configuration_status():
    if os.environ.get("CITERAG_NATIVE_BRIDGE_URL"):
        try:
            bridge_configuration(); return "ready"
        except ValueError:
            return "not_configured"
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
    if os.environ.get("CITERAG_NATIVE_BRIDGE_URL"):
        if configuration_status() != "ready": return "unavailable"
        try:
            report = _bridge_request("/status")
            return "verified" if report.get("status") == "verified" and _bridge_identity(report) else "not_verified"
        except Exception:
            return "not_verified"
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
    except (ValueError, OSError, KeyError, subprocess.SubprocessError):
        return "not_verified"


def answer(question):
    if os.environ.get("CITERAG_NATIVE_BRIDGE_URL"):
        return _bridge_answer(question)
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
