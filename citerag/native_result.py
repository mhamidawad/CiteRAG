"""Evaluate an actual native OpenCode trace; exit zero alone is insufficient."""
import json
import re
import hashlib
from pathlib import Path

ABSTENTION="Insufficient evidence in the approved project sources."


def evidence_in(value):
    if isinstance(value,str):
        try:
            return evidence_in(json.loads(value))
        except (ValueError,TypeError):
            return []
    if isinstance(value,list):
        return [row for item in value for row in evidence_in(item)]
    if not isinstance(value,dict):
        return []
    results=value.get('results')
    if isinstance(results,list):
        return [row for row in results if isinstance(row,dict) and isinstance(row.get('source'),str) and isinstance(row.get('id'),str) and row['source'].startswith('docs/') and re.fullmatch(r'[a-f0-9]{64}',row['id'])]
    return [row for key in ('content','text','structuredContent','output','value') if key in value for row in evidence_in(value[key])]


def result_envelopes(value):
    """Recognize a valid MCP result, preserving the empty-list distinction."""
    if isinstance(value,str):
        try:return result_envelopes(json.loads(value))
        except (ValueError,TypeError):return []
    if isinstance(value,list):return [x for item in value for x in result_envelopes(item)]
    if not isinstance(value,dict) or value.get('isError') or value.get('error'):return []
    if isinstance(value.get('results'),list):
        return [value] if len(evidence_in(value))==len(value['results']) else []
    return [x for key in ('content','text','structuredContent','output','value') if key in value for x in result_envelopes(value[key])]


def sanitize_trace(stdout):
    """Redact string leaves without corrupting JSON event structure."""
    from citerag.context import redact
    def clean(value):
        if isinstance(value,str):
            try:nested=json.loads(value)
            except ValueError:return redact(value)[0]
            if isinstance(nested,(dict,list)):return json.dumps(clean(nested))
            return redact(value)[0]
        if isinstance(value,list):return [clean(v) for v in value]
        if isinstance(value,dict):
            return {k:('[REDACTED]' if re.search(r'(?i)^(?:api[_-]?key|authorization|password|passwd|access[_-]?token|refresh[_-]?token|client[_-]?secret|secret|credential|token)$',k) else clean(v)) for k,v in value.items()}
        return value
    lines=[]
    for line in stdout.splitlines():
        try:lines.append(json.dumps(clean(json.loads(line))))
        except ValueError:lines.append(redact(line)[0])
    return '\n'.join(lines)+'\n'


def runtime_fingerprint():
    root=Path(__file__).resolve().parents[1]
    files=['citerag/native_result.py','citerag/native.py','citerag/semantic.py','citerag/context.py','citerag/freshness.py','citerag/server.py','citerag/quotes.py','citerag/answer.py','citerag/web.py']
    return hashlib.sha256(b''.join(name.encode()+b'\0'+(root/name).read_bytes() for name in files)).hexdigest()


def citation_and_claim_checks(text,evidence):
    """Conservative extractive contract; never label paraphrase as verified grounding."""
    pairs={(row['source'],row['id']) for row in evidence}
    citation_blocks=re.findall(r'\[[^\]\n]*docs/[^\]\n]*\]',text)
    citation_lines=re.findall(r'(?im)^\s*(?:source(?:s)?|chunk(?:\s+id)?|citation)\s*:[^\n]*$',text)
    citation_text='\n'.join(citation_blocks+citation_lines)
    paths=set(re.findall(r'docs/[A-Za-z0-9_./-]+\.(?:md|txt)',citation_text))
    ids=set(re.findall(r'(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])',citation_text))
    cited=bool(pairs) and bool(paths) and bool(ids)
    cited=cited and paths<={s for s,_ in pairs} and ids<={i for _,i in pairs}
    path_matches=list(re.finditer(r'docs/[A-Za-z0-9_./-]+\.(?:md|txt)',citation_text))
    paired_ids=set()
    for n,match in enumerate(path_matches):
        end=path_matches[n+1].start() if n+1<len(path_matches) else len(citation_text)
        following=re.search(r'(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])',citation_text[match.end():end])
        if not following or (match.group(),following.group()) not in pairs:cited=False
        else:paired_ids.add(following.group())
    cited=cited and paired_ids==ids
    # Remove only explicit citation blocks/lines, preserving factual text for validation.
    body=re.sub(r'\[[^\]\n]*docs/[^\]\n]*\]','',text)
    body=re.sub(r'(?im)^\s*(?:source(?:s)?|chunk(?:\s+id)?|citation)\s*:[^\n]*$','',body)
    normalize=lambda value:' '.join(re.findall(r'\w+',value.casefold()))
    passages=[normalize(row.get('text','')) for row in evidence if row.get('text')]
    claims=[normalize(x) for x in re.split(r'\n+|(?<=[.!?])\s+',body) if normalize(x)]
    supported=bool(claims) and bool(passages) and all(any(claim in passage for passage in passages) for claim in claims)
    return bool(cited),supported


def evaluate(stdout,exit_code,tool_name='citerag_search'):
    events=[]
    malformed=0
    for line in stdout.splitlines():
        if not line.startswith('{'):
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            malformed+=1
    text='\n'.join(e.get('part',{}).get('text','') for e in events if e.get('type')=='text')
    evidence=[]
    calls=0
    tool_errors=0
    valid_results=0
    unexpected=0
    for event in events:
        part=event.get('part',{})
        if event.get('type')!='tool_use':continue
        if part.get('tool')!=tool_name:
            unexpected+=1
            continue
        calls+=1
        state=part.get('state',{})
        if state.get('status')=='completed':
            envelopes=result_envelopes(state.get('output',''))
            if not envelopes:tool_errors+=1
            else:valid_results+=1
            evidence.extend(evidence_in(state.get('output','')))
        else:
            tool_errors+=1
    sources={(r['source'],r['id']) for r in evidence}
    abstained=bool(calls) and valid_results==calls and not sources and text.strip().strip('`*').casefold()==ABSTENTION.casefold()
    cited,supported=citation_and_claim_checks(text,evidence)
    stopped=any(e.get('type')=='step_finish' and e.get('part',{}).get('reason')=='stop' for e in events)
    errors=unexpected+sum(e.get('type')=='error' for e in events)+tool_errors+malformed
    passed=exit_code==0 and calls>0 and bool(text.strip()) and stopped and ((cited and supported) or abstained) and errors==0
    return {'status':'PASS' if passed else 'FAIL','exit_code':exit_code,'native_tool':tool_name,'native_tool_calls':calls,'retrieved_sources':[{'source':s,'id':i} for s,i in sorted(sources)],'citations_verified':cited,'claims_supported':supported,'grounding_contract':'verbatim-extractive','abstained':abstained,'stop_observed':stopped,'error_events':errors,'unexpected_tool_calls':unexpected,'valid_result_calls':valid_results,'final_answer':text,'automatic_tool_selection_verified':passed,'session_ids':sorted({e['sessionID'] for e in events if isinstance(e.get('sessionID'),str)})}
