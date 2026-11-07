import json
from pathlib import Path
from citerag.semantic import ingest,search,ROOT
from citerag.quotes import verbatim_answer
from citerag.native_result import citation_and_claim_checks,ABSTENTION
p=ROOT/"docs/sample.md"
orig=p.read_bytes()
try:
    one=ingest()
    print("REINDEX",json.dumps({k:one[k] for k in ("chunks","new_embeddings","reused_embeddings","removed_chunks")}))
    assert one["new_embeddings"]==0 and one["reused_embeddings"]==one["chunks"]
    rows=search("OpenCode coding agents",limit=3)
    print("SEARCH",len(rows),[r["source"] for r in rows])
    assert rows and all("source" in r and "id" in r for r in rows)
    quote=verbatim_answer("OpenCode coding agents",rows[0])
    cited,supported=citation_and_claim_checks(quote,[rows[0]])
    print("CITED",cited,"SUPPORTED",supported)
    assert cited and supported
    unknown=search("Quantum jellyfish spectroscopy protocol",limit=3)
    print("UNSUPPORTED_RESULTS",len(unknown))
    assert unknown==[], "unsupported evidence was returned"
    p.unlink()
    deleted=ingest()
    print("DELETION",json.dumps({k:deleted[k] for k in ("chunks","new_embeddings","reused_embeddings","removed_chunks")}))
    assert deleted["removed_chunks"]>=1
finally:
    p.write_bytes(orig)
    restored=ingest()
    print("RESTORED_CHUNKS",restored["chunks"])
