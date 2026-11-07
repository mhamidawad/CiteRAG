"""Application adapter for the verified native OpenCode worker."""
import json
import subprocess
import sys
import uuid
from pathlib import Path
from citerag.semantic import ROOT
from citerag.context import redact
from citerag.freshness import prepare_context


def answer(question):
    runner=ROOT/'tasks/verify-native.py'
    if not runner.is_file():
        return {'status':'failed','error':'NativeAdapterUnavailable',
                'detail':'The verified OpenCode runner is not installed in this standalone CiteRAG distribution.'}
    fresh=prepare_context()
    if fresh['status']!='completed':return {'status':'failed','error':'ContextNotFresh','detail':fresh.get('reason','Context refresh did not complete; no generation sent.')}
    run_id=uuid.uuid4().hex
    directory=ROOT/'data/native-runs'/run_id
    directory.mkdir(parents=True,exist_ok=False)
    result=subprocess.run([sys.executable,str(ROOT/'tasks/verify-native.py'),'--question',question,'--report-dir',str(directory)],capture_output=True,text=True,timeout=480)
    path=directory/'native-ready-result.json'
    if not path.exists():
        return {'status':'failed','error':'Native worker did not produce a verification result','detail':redact(result.stderr[-1200:])[0]}
    report=json.loads(path.read_text())
    response={'status':('insufficient_evidence' if report.get('abstained') else 'completed') if report.get('status')=='PASS' else 'failed','mode':'native_opencode','model':report.get('model'),'answer':report.get('final_answer',''),'sources':[r['source'] for r in report.get('retrieved_sources',[])],'evidence':report.get('evidence',[]),'elapsed_ms':report.get('elapsed_ms'),'native_tool_calls':report.get('native_tool_calls',0),'citations_verified':report.get('citations_verified',False),'claims_supported':report.get('claims_supported',False),'grounding_contract':report.get('grounding_contract'),'run_id':run_id}
    if response['status'] not in {'completed','insufficient_evidence'}:response.update(error=report.get('error','Native verification failed'),detail=report.get('detail','The native worker did not complete a cited answer.'))
    if response['status']=='completed':
        history=ROOT/'data/native-history';history.mkdir(parents=True,exist_ok=True)
        text='# Verified native OpenCode answer\nRun: '+run_id+'\nTimestamp: '+report['started_at']+'\nOpenCode sessions: '+', '.join(report.get('session_ids',[]))+'\n\n## User question\n'+question+'\n\n## Assistant answer\n'+response['answer']+'\n\nSource references: '+json.dumps(report.get('retrieved_sources',[]))
        (history/(run_id+'.md')).write_text(redact(text)[0])
        try:
            updated=prepare_context();response['context_refresh']={'status':updated['status'],'corpus_version':updated.get('corpus_version')}
        except Exception as exc:
            response['context_refresh']={'status':'failed','error':type(exc).__name__}
    return response
