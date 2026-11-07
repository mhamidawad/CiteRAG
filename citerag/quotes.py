"""Select an exact evidence span; no generated facts or external calls."""
import re
from citerag.semantic import support_terms

def verbatim_answer(question,row):
    quote=evidence_quote(question,row)
    return '\n'.join('> '+line for line in quote.splitlines())+'\nSource: '+row['source']+'\nChunk: '+row['id']


def tool_payload(question,rows):
    # Full provenance stays in LanceDB. Avoid duplicate hashes/metrics in the LLM context.
    fields=('id','source','text','kind','project','session_id')
    return {'results':[{**{key:row[key] for key in fields if key in row and row[key]!=''},'text':evidence_quote(question,row)} for row in rows],
            'verbatim_answer':verbatim_answer(question,rows[0]) if rows else 'Insufficient evidence in the approved project sources.'}


def evidence_quote(question,row):
    text=row['text']
    sentences=[s.strip() for s in re.split(r'(?<=[.!?])\s+',text) if s.strip()]
    wanted=support_terms(question)
    ranked=sorted(range(len(sentences)),key=lambda n:(-len(wanted & support_terms(sentences[n])),n))
    quote='\n'.join(sentences[n] for n in sorted(ranked[:2]))
    # Keep the exact source span but bound prompt growth in normal coding-agent catalogs.
    words=list(re.finditer(r'\S+',quote))
    return quote[:words[59].end()] if len(words)>60 else quote
