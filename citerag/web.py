"""Private web interface for the bounded local retrieval/generation pipeline."""
import os
import threading
import secrets
import time
from pathlib import Path
import json
from datetime import datetime, timezone
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from citerag.semantic import search, model
from citerag.answer import answer, MODEL
from citerag.native import answer as native_answer
from citerag.freshness import prepare_context
from citerag.native_result import ABSTENTION,runtime_fingerprint,citation_and_claim_checks
from citerag.quotes import verbatim_answer
from citerag.auth import BearerAuth, validate_binding

# Stable public adapter identifiers. Configuration is server-side only; no secret fields.
ADAPTERS = {
    "opencode": {"name": "opencode", "schema": {"type": "object", "additionalProperties": False}, "generation": True},
    "omniroute": {"name": "omniroute", "schema": {"type": "object", "additionalProperties": False}, "generation": True},
    "retrieval-only": {"name": "retrieval-only", "schema": {"type": "object", "additionalProperties": False}, "generation": False},
}

def adapter_capabilities():
    """Advertise only verified functionality as selectable, never infer from config."""
    native=native_status()
    generation_configured=bool(MODEL and os.getenv("CITERAG_OMNIROUTE_API_KEY") and os.getenv("CITERAG_OMNIROUTE_URL"))
    states={"retrieval-only":"ready", "opencode":native,
            "omniroute":"configured_not_verified" if generation_configured else "not_configured"}
    return [{**data,"available":(name=="retrieval-only" or
                                  (name=="opencode" and native=="verified")),
             "status":states[name]} for name,data in ADAPTERS.items()]

async def adapters(request):
    return JSONResponse({"adapters": adapter_capabilities()})


_jobs = {}
_guard = threading.Lock()
_generation = threading.Lock()


def run_job(job_id, question, retrieval_only, use_native=False):
    started = time.monotonic()
    try:
        rows=[]
        if not use_native or retrieval_only:
            fresh=prepare_context()
            if fresh['status']!='completed':raise RuntimeError('Context refresh failed; no stale answer was generated.')
            rows=search(question,1)
        if retrieval_only:
            if rows:
                cited_answer=verbatim_answer(question,rows[0])
                cited,supported=citation_and_claim_checks(cited_answer,rows)
                if not (cited and supported):
                    raise ValueError("Retrieved citation or claim validation failed")
                result={"status":"completed","answer":cited_answer,"sources":[r["source"] for r in rows],"mode":"retrieval_only","citations_verified":True,"claims_supported":True}
            else:
                result={"status":"insufficient_evidence","answer":ABSTENTION,"sources":[],"mode":"retrieval_only"}
        elif use_native:
            result=native_answer(question)
        else:
            result = answer(question)
        result.setdefault("evidence",rows)
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        result["state"] = "completed" if result["status"] in {"completed","insufficient_evidence"} else "failed"
    except Exception as exc:
        result = {"state": "failed", "status": "failed", "error": type(exc).__name__}
    finally:
        _generation.release()
    with _guard:
        _jobs[job_id] = result


def native_status():
    root=Path(__file__).resolve().parents[1]
    proof=root/'reports/native-current-verification.json'
    binary=root/'data/tools/opencode-v2.2.5/extracted/opencode'
    if not binary.is_file():return 'unavailable'
    if not proof.exists():return 'not_verified'
    data=json.loads(proof.read_text())
    return 'verified' if data.get('status')=='PASS' and data.get('automatic_tool_selection_verified') and data.get('runtime_fingerprint')==runtime_fingerprint() else 'not_verified'


async def home(request):
    return HTMLResponse(Path(__file__).with_name("web.html").read_text())


async def health(request):
    root=Path(__file__).resolve().parents[1]
    index_ready=(root/"data/lancedb/documents.lance").is_dir() and (root/"data/keyword.sqlite3").is_file()
    generation_configured=bool(MODEL and os.getenv("CITERAG_OMNIROUTE_API_KEY") and os.getenv("CITERAG_OMNIROUTE_URL"))
    return JSONResponse({"status":"ok","status_scope":"HTTP process liveness only",
                         "retrieval_index":"present" if index_ready else "uninitialized",
                         "generation":"configured_not_verified" if generation_configured else "not_configured",
                         "model":MODEL if generation_configured else None,
                         "native_opencode":native_status(),"busy":_generation.locked()})


async def context_status(request):
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / "docs/context/manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    index_path = root / "reports/context-index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    runtime_path=root/"data/context-status.json"
    runtime=json.loads(runtime_path.read_text()) if runtime_path.exists() else {}
    if runtime:index=runtime.get('index',index)
    attempt_path=root/'data/context-refresh-attempt.json'
    attempt=json.loads(attempt_path.read_text()) if attempt_path.exists() else {}
    task_path = root / "tasks/manifest.json"
    task = json.loads(task_path.read_text()) if task_path.exists() else {}
    return JSONResponse({"imported_documents": len(manifest), "selected_sessions": sum(row.get("kind")=="opencode_session" for row in manifest.values()), "imported_messages": sum(row.get("messages",0) for row in manifest.values()), "indexed_chunks": index.get("chunks",0), "last_sync": datetime.fromtimestamp(manifest_path.stat().st_mtime,timezone.utc).isoformat() if manifest_path.exists() else None, "freshness":attempt,"last_successful_ingestion":runtime.get("updated_at"),"phase":task.get("phase","unknown"), "coverage":"Selected bounded history and approved project documents; not all historical sessions", "native_opencode":native_status(), "native_answers":len(list((root/"data/native-history").glob("*.md")))})


async def ask(request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Expected JSON"}, status_code=400)
    question = data.get("question") if isinstance(data, dict) else None
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
        return JSONResponse({"error": "Enter a question between 1 and 4000 characters."}, status_code=400)
    # Validate adapter and config before acquiring the lock or refreshing any sources.
    explicit_adapter=data.get("adapter")
    adapter_config=data.get("adapter_config",{})
    if explicit_adapter is not None:
        if not isinstance(explicit_adapter,str) or explicit_adapter not in ADAPTERS:
            return JSONResponse({"error":"Unknown adapter"},status_code=400)
        if not isinstance(adapter_config,dict) or adapter_config:
            return JSONResponse({"error":"Invalid adapter config"},status_code=400)
        if not next(item for item in adapter_capabilities() if item["name"]==explicit_adapter)["available"]:
            return JSONResponse({"error":"Adapter is unavailable or unverified"},status_code=503)
        selected_native=explicit_adapter=="opencode"
        selected_retrieval=explicit_adapter=="retrieval-only"
    else:
        if "adapter_config" in data and (not isinstance(adapter_config,dict) or adapter_config):
            return JSONResponse({"error":"Invalid adapter config"},status_code=400)
        selected_native=data.get("use_native") is True
        selected_retrieval=data.get("retrieval_only") is True
    if not _generation.acquire(blocking=False):
        return JSONResponse({"error": "A request is already running. Wait for it to finish."}, status_code=409)
    job_id = secrets.token_urlsafe(18)
    with _guard:
        if len(_jobs) >= 20:
            for old in list(_jobs):
                if _jobs[old].get("state") != "running":
                    del _jobs[old]
                    break
        _jobs[job_id] = {"state": "running"}
    return JSONResponse({"job_id": job_id, "state": "running"}, status_code=202,
                        background=BackgroundTask(run_job, job_id, question.strip(), selected_retrieval, selected_native))


async def job(request):
    with _guard:
        result = _jobs.get(request.path_params["job_id"])
    return JSONResponse(result if result is not None else {"error": "Unknown request"}, status_code=200 if result is not None else 404)


app = Starlette(routes=[Route("/", home), Route("/api/health", health), Route("/api/adapters", adapters), Route("/api/context", context_status), Route("/api/ask", ask, methods=["POST"]), Route("/api/jobs/{job_id}", job)])
app.add_middleware(BearerAuth, public_paths=("/api/health",))

if __name__ == "__main__":
    import uvicorn
    model()
    uvicorn.run(app, host=os.getenv("CITERAG_WEB_HOST","127.0.0.1"), port=int(os.getenv("CITERAG_WEB_PORT","18762")), access_log=False)
