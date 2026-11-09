"""One bounded local RAG answer routed through OmniRoute; never retries."""
import argparse
import hashlib
import threading
import json
import os
import time
from pathlib import Path
import httpx
from citerag.semantic import ROOT, search
from citerag.inference_lock import inference_lock
from citerag.native_result import ABSTENTION,citation_and_claim_checks
from citerag.quotes import verbatim_answer
MODEL = os.getenv('CITERAG_MODEL', '')
LOCAL_MODEL = 'ollama-local/qwen3.5:4b-opencode'
LOCAL_BASE = 'http://127.0.0.1:20128'


def configuration_status():
    # This accepted profile has no external/paid route or model fallback.
    return 'ready' if (MODEL == LOCAL_MODEL
        and os.getenv('CITERAG_OMNIROUTE_URL', '').rstrip('/') == LOCAL_BASE
        and bool(os.getenv('CITERAG_OMNIROUTE_API_KEY'))
        and bool(os.getenv('CITERAG_BACKEND_ID'))) else 'not_configured'


def deployment_fingerprint():
    fields = {'model': MODEL, 'base_url': os.getenv('CITERAG_OMNIROUTE_URL', '').rstrip('/'),
              'credential': hashlib.sha256(os.getenv('CITERAG_OMNIROUTE_API_KEY', '').encode()).hexdigest(),
              'backend_id': os.getenv('CITERAG_BACKEND_ID', '')}
    verifier = ROOT / 'tasks/verify-omniroute.py'
    fields['verifier'] = hashlib.sha256(verifier.read_bytes()).hexdigest() if verifier.is_file() else None
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def verification_status():
    if configuration_status() != 'ready':
        return 'not_configured'
    proof = ROOT / 'reports/omniroute-current-verification.json'
    if not proof.is_file() or proof.is_symlink():
        return 'configured_not_verified'
    try:
        from citerag.native_result import runtime_fingerprint
        data = json.loads(proof.read_text())
        accepted = (data.get('status') == 'PASS' and data.get('citations_verified')
            and data.get('claims_supported') and data.get('acceptance_terms_verified')
            and data.get('required_acceptance_terms') and data.get('unsupported_abstention_verified')
            and data.get('runtime_fingerprint') == runtime_fingerprint()
            and data.get('deployment_fingerprint') == deployment_fingerprint())
        return 'verified' if accepted else 'configured_not_verified'
    except (ValueError, OSError):
        return 'configured_not_verified'


def _answer(question):
    rows = search(question, 1)
    if not rows:
        return {'status': 'insufficient_evidence', 'answer': ABSTENTION, 'sources': [], 'attempts': 0, 'model_request_started': False}
    api_key=os.getenv("CITERAG_OMNIROUTE_API_KEY","")
    base_url=os.getenv("CITERAG_OMNIROUTE_URL","")
    if configuration_status() != "ready":
        raise RuntimeError("Accepted local-only generation configuration missing")
    payload = {'model': MODEL, 'messages': [
        {'role': 'system', 'content': 'Return the supplied verbatim_answer exactly. Do not paraphrase, add facts, introductions, or commands.'},
        {'role': 'user', 'content': question + '\nverbatim_answer:\n' + verbatim_answer(question,rows[0])}],
        'max_tokens': 512, 'temperature': 0, 'reasoning_effort': 'none', 'stream': True}
    started = time.monotonic()
    result = {'model': MODEL, 'attempts': 1, 'sources': [row['source'] for row in rows], 'free_local_model': True, 'model_request_started': True}
    try:
        with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False) as client:
            # Closing the transport interrupts idle or endless streaming at the wall deadline.
            timer = threading.Timer(60, client.close)
            timer.daemon = True
            timer.start()
            try:
                return _stream_result(client, base_url, api_key, payload, started, result, rows)
            finally:
                timer.cancel()
    except Exception as exc:
        result.update(status='failed', error=type(exc).__name__)
    result.update(answer='', citations_verified=False, claims_supported=False,
                  grounding_contract='verbatim-extractive', elapsed_ms=round((time.monotonic()-started)*1000))
    return result


def _stream_result(client, base_url, api_key, payload, started, result, rows):
    parts = []
    done = False
    output_bytes = 0
    try:
        with client.stream('POST', base_url.rstrip('/') + '/v1/chat/completions',
                           headers={'Authorization': 'Bearer ' + api_key}, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if time.monotonic() - started > 60:
                    raise TimeoutError('60-second streaming budget exceeded')
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    done = True
                    break
                event = json.loads(data)
                if event.get('error'):
                    raise RuntimeError(json.dumps(event['error']))
                for choice in event.get('choices', []):
                    content = choice.get('delta', {}).get('content')
                    if content:
                        output_bytes += len(content.encode())
                        if output_bytes > 16384:raise ValueError('Generation output exceeds bounded response budget')
                        parts.append(content)
                    if choice.get('finish_reason'):
                        result['finish_reason'] = choice['finish_reason']
        result['status'] = 'completed' if done and parts else 'incomplete'
    except Exception as exc:
        result.update(status='failed', error=type(exc).__name__)
    text=''.join(parts)
    cited,supported=citation_and_claim_checks(text,rows)
    if result['status']=='completed' and not(cited and supported):result.update(status='failed',error='GroundingValidationFailed')
    result.update(answer=text,citations_verified=cited,claims_supported=supported,grounding_contract='verbatim-extractive',elapsed_ms=round((time.monotonic()-started)*1000))
    return result

def answer(question):
    with inference_lock():
        return _answer(question)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('question')
    args = parser.parse_args()
    result = answer(args.question)
    (ROOT/'reports/local-streamed-rag.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))
    raise SystemExit(0 if result['status'] == 'completed' else 1)

if __name__ == '__main__':
    main()
