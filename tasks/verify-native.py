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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from citerag.native_result import sanitize_trace
from tasks.native_bridge_evidence import verify as verify_trace

IMAGE="local/opencode-agent:2.0.0"
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

def container_command(env,binary_dir,container,question):
    profile=ROOT/"configs/native-citerag.json"
    if not profile.is_file() or profile.is_symlink():raise AdmissionError("PROFILE_MISSING")
    if not binary_dir.is_absolute() or not (binary_dir/"opencode").is_file():
        raise AdmissionError("PINNED_BINARY_MISSING")
    script=("set -eu; mkdir -p /tmp/oc-home/config/opencode; "
       "cp /opt/native-profile.json /tmp/oc-home/config/opencode/opencode.json; "
       "timeout -s TERM -k 5 35 /opt/opencode/opencode mcp list 1>&2; "
       "timeout -s TERM -k 5 190 /opt/opencode/opencode run "
       "--agent citerag-answer --model omniroute/"+MODEL+" "
       "--format json --auto --title native-citerag-acceptance \"$1\"")
    return ["docker","run","--rm","--name",container,"--network","host",
       "--user","65534:65534","--read-only","--cap-drop","ALL",
       "--security-opt","no-new-privileges","--pids-limit","96",
       "--memory","3g","--cpus","2","--tmpfs","/tmp:rw,nosuid,size=384m",
       "--env-file",str(env),"-e","HOME=/tmp/oc-home",
       "-e","XDG_CONFIG_HOME=/tmp/oc-home/config",
       "-e","XDG_DATA_HOME=/tmp/oc-home/data",
       "-e","XDG_STATE_HOME=/tmp/oc-home/state",
       "-e","XDG_CACHE_HOME=/tmp/oc-home/cache",
       "-e","OPENCODE_DISABLE_PROJECT_CONFIG=true",
       "-e","OPENCODE_DISABLE_MODELS_FETCH=true",
       "-e","OPENCODE_DISABLE_AUTOUPDATE=true",
       "--mount",f"type=bind,src={profile},dst=/opt/native-profile.json,readonly",
       "--mount",f"type=bind,src={binary_dir},dst=/opt/opencode,readonly",
       "--entrypoint","/bin/sh",IMAGE,"-c",script,"_",question]

def run(question,env_path,binary_path):
    if not isinstance(question,str) or not 1<=len(question.strip())<=400:
        raise AdmissionError("QUESTION_SCOPE_INVALID")
    env=env_file(env_path)
    snapshot=preflight()
    container="citerag-native-"+uuid.uuid4().hex[:12]
    binary_dir=binary_path.resolve()
    command=container_command(env,binary_dir,container,question.strip())
    report_dir=ROOT/"reports"/"native"/container
    report_dir.mkdir(parents=True,exist_ok=False)
    result=None
    try:
        result=subprocess.run(command,text=True,capture_output=True,timeout=245)
    finally:
        # Cleanup names only the disposable invocation, never any production container.
        subprocess.run(["docker","rm","-f",container],stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,timeout=12,check=False)
    clean=sanitize_trace(result.stdout)
    (report_dir/"native-trace.jsonl").write_text(clean)
    (report_dir/"native-trace.jsonl").chmod(0o600)
    tool_ready=("citerag" in result.stderr.lower() and "connected" in result.stderr.lower())
    check=verify_trace(clean,exit_code=result.returncode,tool="citerag_rag_search",
                       expected_source="docs/architecture.md")
    ok=check["status"]=="PASS" and tool_ready
    answer={"status":"PASS" if ok else "FAIL","started_at":datetime.now(timezone.utc).isoformat(),
       "model":MODEL,"attempts":1,"free_local_model":True,
       "resource_gate":"READY","resource_snapshot":snapshot,
       "mcp_readiness_observed":tool_ready,"container_isolated":True,
       "backend_identity_attested":False,"standalone_production_certified":False,
       "trace":check}
    (report_dir/"native-ready-result.json").write_text(json.dumps(answer,indent=2)+"\n")
    (report_dir/"native-ready-result.json").chmod(0o600)
    return answer

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question",default="Which vector database does this project use?")
    parser.add_argument("--env-file",type=Path,default=None)
    parser.add_argument("--binary-dir",type=Path,default=None)
    args=parser.parse_args()
    try:
        if args.binary_dir is None:raise AdmissionError("PINNED_BINARY_DIR_REQUIRED")
        result=run(args.question,args.env_file,args.binary_dir)
    except subprocess.TimeoutExpired:
        result={"status":"FAIL","reason":"NativeTimeout",
                "inference_started":"unknown","standalone_production_certified":False}
    except (AdmissionError,OSError,ValueError,subprocess.SubprocessError) as exc:
        result={"status":"BLOCKED","reason":type(exc).__name__,
                "inference_started":False,"standalone_production_certified":False}
    print(json.dumps(result,sort_keys=True))
    return 0 if result["status"]=="PASS" else 2

if __name__=="__main__":raise SystemExit(main())
