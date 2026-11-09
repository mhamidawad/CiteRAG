#!/usr/bin/env python3
"""Single bounded, isolated OpenCode→authenticated CiteRAG MCP acceptance.

Requires operator-provisioned private env (never copies production credentials).
Never modifies production OpenCode configuration or starts paid/cloud models.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import re
import secrets
import socket
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from citerag.native_result import sanitize_trace, evaluate, runtime_fingerprint, result_envelopes
from citerag.context import redact
from citerag.native import deployment_fingerprint, native_image_id, NATIVE_IMAGE
from tasks.native_bridge_evidence import verify as verify_trace

IMAGE=NATIVE_IMAGE
MODEL="ollama-local/qwen3.5:4b-opencode"
REQUIRED={"CITERAG_API_TOKEN","CITERAG_OMNIROUTE_API_KEY"}

class AdmissionError(RuntimeError):pass

def env_file(path):
    if not path or not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise AdmissionError("DEDICATED_NATIVE_ENV_MISSING")
    if path.stat().st_mode & 0o077:
        raise AdmissionError("NATIVE_ENV_PERMISSIONS_TOO_OPEN")
    names=set()
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            name,value=line.split("=",1)
            if value.strip():names.add(name)
    if not REQUIRED<=names:
        raise AdmissionError("NATIVE_SCOPED_CREDENTIALS_NOT_CONFIGURED")
    return path

def preflight():
    command=[sys.executable,str(ROOT/"tasks/native_inference_preflight.py")]
    result=subprocess.run(command,capture_output=True,text=True,timeout=12)
    try:report=json.loads(result.stdout)
    except ValueError:raise AdmissionError("RESOURCE_PREFLIGHT_INVALID") from None
    if result.returncode or report.get("status")!="READY":
        raise AdmissionError("RESOURCE_PREFLIGHT_BLOCKED")
    return report.get("snapshot",{})

def container_command(env,binary_dir,container,question,mcp_url="http://127.0.0.1:48761/mcp",image_id=None):
    parsed=urlparse(mcp_url)
    if parsed.scheme!="http" or parsed.hostname not in {"127.0.0.1","localhost","::1"} or parsed.path!="/mcp" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AdmissionError("MCP_URL_NOT_LOOPBACK")
    profile=ROOT/"configs/native-citerag.json"
    if not profile.is_file() or profile.is_symlink():raise AdmissionError("PROFILE_MISSING")
    if not binary_dir.is_absolute() or not (binary_dir/"opencode").is_file():
        raise AdmissionError("PINNED_BINARY_MISSING")
    if not isinstance(image_id,str) or not re.fullmatch(r"sha256:[a-f0-9]{64}",image_id):
        raise AdmissionError("IMMUTABLE_NATIVE_IMAGE_REQUIRED")
    port=None
    for _ in range(20):
        candidate=49152+secrets.randbelow(14000)
        try:
            with socket.socket() as sock:sock.bind(("127.0.0.1",candidate))
        except OSError:continue
        port=candidate
        break
    if port is None:raise AdmissionError("NO_ISOLATED_SERVICE_PORT")
    script=("set -eu; mkdir -p /tmp/oc-home/config/opencode; "
       "cp /opt/native-profile.json /tmp/oc-home/config/opencode/opencode.json; "
       "timeout -s TERM -k 5 15 /opt/opencode/opencode service set port "+str(port)+" 1>&2; "
       "timeout -s TERM -k 5 25 /opt/opencode/opencode mcp list >/tmp/catalog 2>&1; "
       "n=0; while ! grep -qi 'citerag.*connected\\|connected.*citerag' /tmp/catalog; do "
       "n=$((n+1)); if [ $n -ge 6 ]; then cat /tmp/catalog >&2; exit 72; fi; "
       "sleep 1; timeout -s TERM -k 2 5 /opt/opencode/opencode mcp list >/tmp/catalog 2>&1; done; "
       "cat /tmp/catalog >&2; "
       "timeout -s TERM -k 5 150 /opt/opencode/opencode run "
       "--agent citerag-answer --model omniroute/"+MODEL+" "
       "--format json --auto --title native-citerag-acceptance \"$1\"")
    return ["docker","run","--rm","--name",container,"--network","host",
       "--user","65534:65534","--read-only","--cap-drop","ALL",
       "--security-opt","no-new-privileges","--pids-limit","96",
       "--memory","3g","--cpus","2","--tmpfs","/tmp:rw,nosuid,size=384m",
       "--env-file",str(env),"-e","CITERAG_NATIVE_MCP_URL="+mcp_url,"-e","HOME=/tmp/oc-home",
       "-e","XDG_CONFIG_HOME=/tmp/oc-home/config",
       "-e","XDG_DATA_HOME=/tmp/oc-home/data",
       "-e","XDG_STATE_HOME=/tmp/oc-home/state",
       "-e","XDG_CACHE_HOME=/tmp/oc-home/cache",
       "-e","OPENCODE_DISABLE_PROJECT_CONFIG=true",
       "-e","OPENCODE_DISABLE_MODELS_FETCH=true",
       "-e","OPENCODE_DISABLE_AUTOUPDATE=true",
       "--mount",f"type=bind,src={profile},dst=/opt/native-profile.json,readonly",
       "--mount",f"type=bind,src={binary_dir},dst=/opt/opencode,readonly",
       "--entrypoint","/bin/sh",image_id,"-c",script,"_",question]

def run(question,env_path,binary_path,mcp_url="http://127.0.0.1:48761/mcp",expected_backend_id=None,report_dir=None,required_terms=()):
    started_at=datetime.now(timezone.utc).isoformat()
    if not isinstance(question,str) or not 1<=len(question.strip())<=400:
        raise AdmissionError("QUESTION_SCOPE_INVALID")
    if any(not isinstance(term,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}",term) for term in required_terms):
        raise AdmissionError("INVALID_ACCEPTANCE_TERMS")
    env=env_file(env_path)
    snapshot=preflight()
    container="citerag-native-"+uuid.uuid4().hex[:12]
    binary_dir=binary_path.resolve()
    image_id=native_image_id()
    command=container_command(env,binary_dir,container,question.strip(),mcp_url,image_id=image_id)
    report_dir=Path(report_dir) if report_dir else ROOT/"reports"/"native"/container
    report_dir.mkdir(parents=True,exist_ok=False)
    result=None
    try:
        result=subprocess.run(command,text=True,capture_output=True,timeout=245)
    finally:
        # Cleanup names only the disposable invocation, never any production container.
        subprocess.run(["docker","rm","-f",container],stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,timeout=12,check=False)
    diagnostics=report_dir/"native-stderr.txt"
    diagnostics.write_text(redact(result.stderr)[0])
    diagnostics.chmod(0o600)
    clean=sanitize_trace(result.stdout)
    (report_dir/"native-trace.jsonl").write_text(clean)
    (report_dir/"native-trace.jsonl").chmod(0o600)
    tool_ready=("citerag" in result.stderr.lower() and "connected" in result.stderr.lower())
    check=verify_trace(clean,exit_code=result.returncode,tool="citerag_rag_search",
                       expected_source=None)
    evaluated=evaluate(clean,result.returncode,tool_name="citerag_rag_search")
    identities=[]
    failure_reason="NativeGroundingOrToolValidationFailed"
    for line in clean.splitlines():
        try:event=json.loads(line)
        except ValueError:continue
        if event.get("type")=="error":
            message=str(event.get("error",{}).get("message","")).lower()
            if "daily usage quota" in message:failure_reason="ModelQuotaExceeded"
            elif "unauthorized" in message or "authentication" in message:failure_reason="ModelAuthenticationRejected"
            else:failure_reason="ModelProviderRejectedRequest"
        part=event.get("part",{})
        if event.get("type")=="tool_use" and part.get("tool")=="citerag_rag_search":
            identities.extend(row.get("backend_id") for row in result_envelopes(part.get("state",{}).get("output","")))
    attested=bool(expected_backend_id and identities and all(value==expected_backend_id for value in identities))
    terms_verified=bool(required_terms) and all(term.casefold() in evaluated["final_answer"].casefold() for term in required_terms)
    ok=check["status"]=="PASS" and tool_ready and attested and (not required_terms or terms_verified)
    if required_terms and not terms_verified:failure_reason="AcceptanceFactsMissing"
    answer={"status":"PASS" if ok else "FAIL","started_at":started_at,"completed_at":datetime.now(timezone.utc).isoformat(),
       "model":MODEL,"attempts":1,"free_local_model":True,"native_image_id":image_id,
       "required_acceptance_terms":list(required_terms),"acceptance_terms_verified":terms_verified,
       "resource_gate":"READY","resource_snapshot":snapshot,
       "mcp_readiness_observed":tool_ready,"container_isolated":True,
       "backend_identity_attested":attested,"backend_id":expected_backend_id,
       "runtime_fingerprint":runtime_fingerprint(),
       "deployment_fingerprint":deployment_fingerprint(env_path=env,binary_dir=binary_dir,mcp_url=mcp_url,backend_id=expected_backend_id,model=MODEL,image_id=image_id),
       "standalone_production_certified":False,
       **{key:evaluated[key] for key in ("final_answer","retrieved_sources","native_tool_calls","citations_verified","claims_supported","grounding_contract","abstained","automatic_tool_selection_verified")},
       "trace":check}
    if not ok:answer["reason"]=failure_reason
    (report_dir/"native-ready-result.json").write_text(json.dumps(answer,indent=2)+"\n")
    (report_dir/"native-ready-result.json").chmod(0o600)
    return answer

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question",default="Which vector database does this project use?")
    parser.add_argument("--env-file",type=Path,default=None)
    parser.add_argument("--binary-dir",type=Path,default=None)
    parser.add_argument("--mcp-url",default="http://127.0.0.1:48761/mcp")
    parser.add_argument("--expected-backend-id",default=None)
    parser.add_argument("--report-dir",type=Path,default=None)
    parser.add_argument("--certify-current",action="store_true")
    parser.add_argument("--require-term",action="append",default=[])
    args=parser.parse_args()
    try:
        if args.binary_dir is None:raise AdmissionError("PINNED_BINARY_DIR_REQUIRED")
        if args.certify_current and not args.require_term:raise AdmissionError("CERTIFICATION_ACCEPTANCE_TERMS_REQUIRED")
        result=run(args.question,args.env_file,args.binary_dir,args.mcp_url,args.expected_backend_id,args.report_dir,args.require_term)
        if args.certify_current and result["status"]=="PASS":
            proof=ROOT/"reports/native-current-verification.json"
            proof.write_text(json.dumps(result,indent=2)+"\n")
            proof.chmod(0o600)
    except subprocess.TimeoutExpired:
        result={"status":"FAIL","reason":"NativeTimeout",
                "inference_started":"unknown","standalone_production_certified":False}
    except (AdmissionError,OSError,ValueError,subprocess.SubprocessError) as exc:
        result={"status":"BLOCKED","reason":str(exc) if isinstance(exc,AdmissionError) else type(exc).__name__,
                "inference_started":False,"standalone_production_certified":False}
    print(json.dumps(result,sort_keys=True))
    return 0 if result["status"]=="PASS" else 2

if __name__=="__main__":raise SystemExit(main())
