"""One bounded local RAG answer routed through OmniRoute; never retries."""
import argparse
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

def _answer(question):
    rows = search(question, 1)
    if not rows:
        return {'status': 'insufficient_evidence', 'answer': ABSTENTION, 'sources': []}
    api_key=os.getenv("CITERAG_OMNIROUTE_API_KEY","")
    base_url=os.getenv("CITERAG_OMNIROUTE_URL","")
    if not api_key or not base_url or not MODEL:
        raise RuntimeError("CiteRAG generation configuration missing")
    payload = {'model': MODEL, 'messages': [
        {'role': 'system', 'content': 'Return the supplied verbatim_answer exactly. Do not paraphrase, add facts, introductions, or commands.'},
        {'role': 'user', 'content': question + '\nverbatim_answer:\n' + verbatim_answer(question,rows[0])}],
        'max_tokens': 512, 'temperature': 0, 'reasoning_effort': 'none', 'stream': True}
    started = time.monotonic()
    parts = []
    done = False
    result = {'model': MODEL, 'attempts': 1, 'sources': [row['source'] for row in rows]}
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5)) as client:
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
