"""Bounded pre-retrieval refresh with one writer and visible attempt/success state."""
import json,os
from datetime import datetime,timezone
from pathlib import Path
from citerag.context import ROOT,refresh,atomic_write
from citerag.inference_lock import inference_lock,InferenceBusy


def check_writer_access(owner=None,path=None):
    lease=Path(path or ROOT/'data/active-writer.json')
    if not lease.exists():return
    state=json.loads(lease.read_text())
    if not state.get('active'):return
    expires=state.get('expires_at')
    try:active=not expires or datetime.fromisoformat(expires.replace('Z','+00:00'))>datetime.now(timezone.utc)
    except (ValueError,TypeError):active=True
    if active and (owner or os.environ.get('CITERAG_WRITER_OWNER'))!=state.get('owner'):
        raise InferenceBusy('Project writer lease is active; retrieval refresh and generation are deferred.')


def prepare_context():
    check_writer_access()
    attempt={'attempted_at':datetime.now(timezone.utc).isoformat()}
    try:
        with inference_lock():
            result=refresh()
        attempt.update(status=result['status'])
        if result.get('reason'):attempt['reason']=result['reason']
        if result['status']=='completed':attempt['corpus_version']=result['index']['corpus_version']
    except InferenceBusy:
        raise
    except Exception as exc:
        attempt.update(status='failed',reason=type(exc).__name__)
    atomic_write(ROOT/'data/context-refresh-attempt.json',json.dumps(attempt,indent=2)+'\n')
    return attempt
