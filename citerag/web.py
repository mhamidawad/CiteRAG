"""Private web interface for the bounded local retrieval/generation pipeline."""
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
from citerag.native_result import ABSTENTION,runtime_fingerprint

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
            result = {"status": "completed" if rows else "insufficient_evidence", "answer": "" if rows else ABSTENTION, "sources": [r["source"] for r in rows], "mode": "retrieval_only"}
        elif use_native:
            result=native_answer(question)
        else:
            result = answer(question)
        result.setdefault("evidence",rows)
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        result["state"] = "completed" if result["status"] in {"completed","insufficient_evidence"} else "failed"
    except Exception as exc:
        result = {"state": "failed", "status": "failed", "error": type(exc).__name__, "detail": str(exc)}
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
    return JSONResponse({"status": "ok", "model": MODEL, "generation": "OmniRoute → local Ollama", "retrieval": "LanceDB + MiniLM + keyword retrieval", "native_opencode":native_status(), "busy": _generation.locked()})


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
                        background=BackgroundTask(run_job, job_id, question.strip(), data.get("retrieval_only") is True, data.get("use_native") is True))


async def job(request):
    with _guard:
        result = _jobs.get(request.path_params["job_id"])
    return JSONResponse(result if result is not None else {"error": "Unknown request"}, status_code=200 if result is not None else 404)


app = Starlette(routes=[Route("/", home), Route("/api/health", health), Route("/api/context", context_status), Route("/api/ask", ask, methods=["POST"]), Route("/api/jobs/{job_id}", job)])

if __name__ == "__main__":
    import uvicorn
    model()
    uvicorn.run(app, host="127.0.0.1", port=18762, access_log=False)
