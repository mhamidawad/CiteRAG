"""Bounded local semantic retrieval; never calls a generation provider."""
import argparse, hashlib, json, os, re, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MODEL = os.getenv("CITERAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
KEYWORDS = ROOT / "data/keyword.sqlite3"
_model = None
def model():
    global _model
    if _model is None:
        import torch
        from sentence_transformers import SentenceTransformer
        torch.set_num_threads(2)
        _model = SentenceTransformer(MODEL, device="cpu", cache_folder=os.getenv("CITERAG_MODEL_CACHE_DIR", str(ROOT / "data/models")), local_files_only=os.environ.get("CITERAG_OFFLINE","1") == "1", trust_remote_code=False)
    return _model
def documents():
    total = 0
    for path in sorted(DOCS.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.suffix not in {".md",".txt"}:
            continue
        if not path.resolve().is_relative_to(DOCS.resolve()) or path.stat().st_size > 256000:
            continue
        if any(part.startswith(".") for part in path.relative_to(DOCS).parts):
            continue
        text = path.read_text(encoding="utf-8")
        total += len(text)
        if total > 2000000:
            raise ValueError("Corpus exceeds 2 MB limit")
        yield path.relative_to(ROOT).as_posix(), text
def chunks():
    tokenizer = model().tokenizer
    provenance_path = DOCS / "context/manifest.json"
    provenance = json.loads(provenance_path.read_text()) if provenance_path.exists() else {}
    for source, text in documents():
        metadata = provenance.get(source.removeprefix("docs/context/"), {})
        tokens = tokenizer.encode(text, add_special_tokens=False, truncation=False, verbose=False)
        for start in range(0,len(tokens),160):
            body = tokenizer.decode(tokens[start:start+200], skip_special_tokens=True)
            if body.strip():
                yield {"id":hashlib.sha256((source+str(start)+body).encode()).hexdigest(), "source":source, "token_start":start, "text":body, "kind":metadata.get("kind", "project_document"), "project":metadata.get("project", "default"), "session_id":metadata.get("session_id", ""), "source_sha256":hashlib.sha256(text.encode()).hexdigest()}
def ingest():
    from citerag.freshness import check_writer_access
    check_writer_access()
    import lancedb
    rows = list(chunks())
    if not rows:
        raise ValueError("No approved documents; existing index preserved")
    db = lancedb.connect(str(ROOT/"data/lancedb"))
    old_rows = []
    if "documents" in db.table_names():
        old_rows = db.open_table("documents").to_arrow().to_pylist()
    dimension = model().get_sentence_embedding_dimension()
    reusable = {row["id"]:row["vector"] for row in old_rows if row.get("embedding_model")==MODEL and len(row.get("vector",[]))==dimension}
    fresh = [row for row in rows if row["id"] not in reusable]
    if fresh:
        vectors = model().encode([row["text"] for row in fresh],batch_size=16,normalize_embeddings=True,show_progress_bar=False)
        for row, vector in zip(fresh,vectors):
            row["vector"] = vector.tolist()
    for row in rows:
        if row["id"] in reusable:
            row["vector"] = reusable[row["id"]]
        row["embedding_model"] = MODEL
    fingerprint = hashlib.sha256("".join(sorted(r["id"] for r in rows)).encode()).hexdigest()
    for row in rows:
        row["corpus_version"] = fingerprint
    db.create_table("documents",rows,mode="overwrite")
    build_keywords(rows, fingerprint)
    return {"chunks":len(rows),"model":MODEL,"corpus_version":fingerprint,"keyword_index":True,"new_embeddings":len(fresh),"reused_embeddings":len(rows)-len(fresh),"removed_chunks":len({r["id"] for r in old_rows}-{r["id"] for r in rows})}
def build_keywords(rows, fingerprint, path=None):
    path = Path(path or KEYWORDS)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        with con:
            con.execute("DROP TABLE IF EXISTS chunks")
            con.execute("CREATE VIRTUAL TABLE chunks USING fts5(id UNINDEXED, source, text, tokenize='porter unicode61')")
            con.executemany("INSERT INTO chunks(id,source,text) VALUES (?,?,?)", [(r["id"],r["source"],r["text"]) for r in rows])
            con.execute("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT)")
            con.execute("INSERT OR REPLACE INTO metadata VALUES ('corpus_version',?)", (fingerprint,))
    finally:
        con.close()


def keyword_ids(query, fingerprint, limit=30, path=None, allowed_ids=None):
    path = Path(path or KEYWORDS)
    if not path.exists():
        return []
    stop = set("a an the is are was were what which where when how does do did this that project projects use used uses please about in on of and or to for with from".split())
    terms = list(dict.fromkeys(t.lower() for t in re.findall(r"\w+",query) if len(t)>1 and t.lower() not in stop))[:32]
    if not terms:
        return []
    expression = " OR ".join('"'+term+'"' for term in terms)
    con = sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True,timeout=3)
    try:
        row = con.execute("SELECT value FROM metadata WHERE key='corpus_version'").fetchone()
        if not row or row[0] != fingerprint:
            return []
        if allowed_ids is not None and not allowed_ids:return []
        scope_sql=" AND id IN ("+','.join('?' for _ in allowed_ids)+")" if allowed_ids is not None else ''
        params=[expression]+(list(allowed_ids) if allowed_ids is not None else [])+[max(1,min(int(limit),30))]
        return [r[0] for r in con.execute("SELECT id FROM chunks WHERE chunks MATCH ?"+scope_sql+" ORDER BY bm25(chunks,0,5,1) LIMIT ?",params)]
    except sqlite3.DatabaseError:
        return []
    finally:
        con.close()


def support_terms(text):
    stop=set("a an the is are was were what which where when how does do did this that project projects use used uses please about in on of and or to for with from can could would should be been being me my our your show find tell give explain associated containing contain".split())
    synonyms={"doc":"document","docs":"document","documentation":"document","ingest":"index","index":"index","rout":"route","routing":"route","route":"route","embedd":"embedding","embed":"embedding","embedding":"embedding","old":"history","historical":"history","previous":"history","earlier":"history","archived":"history","archiv":"history","eva":"lab","evaluation":"lab"}
    result=set()
    for term in re.findall(r"\w+",text.casefold()):
        if len(term)<2 or term in stop:continue
        if term.endswith('s') and len(term)>4 and not term.endswith('ss'):term=term[:-1]
        if term.endswith('ing') and len(term)>5:term=term[:-3]
        elif term.endswith('ed') and len(term)>5:term=term[:-2]
        result.add(synonyms.get(term,term))
    return result


def evidence_coverage(query,row):
    wanted=support_terms(query)
    if not wanted:return 0.0
    available=support_terms(' '.join(str(row.get(k,'')) for k in ('text','source','project','session_id','id')))
    if row.get('kind') in {'opencode_session','native_answer'}:
        available.update({'history','session','conversation','directory'})
    return len(wanted & available)/len(wanted)


def lexical_content_query(query,scopes,aliases):
    if not scopes:return query
    content=query
    for scope in scopes:
        for alias in sorted(aliases[scope],key=len,reverse=True):
            content=re.sub(r'(?i)(?<![\w-])'+re.escape(alias)+r'(?![\w-])',' ',content)
    content=re.sub(r'(?i)(?<![\w.-])(archived|historical|history|old|conversation|conversations|session|sessions|project|projects|opencode)(?![\w.-])',' ',content)
    return content if support_terms(content) else query


def search(query, limit=5, max_distance=0.9):
    if not query.strip():
        return []
    if len(query)>4000:
        raise ValueError("Query exceeds 4000 characters")
    import lancedb
    table = lancedb.connect(str(ROOT/"data/lancedb")).open_table("documents")
    # Project scopes come only from explicitly approved source directories.
    aliases={}
    config_path=ROOT/"context-sources.json"
    if config_path.exists():
        for location in json.loads(config_path.read_text()).get("session_directories",[]):
            name=Path(location).name
            if name: aliases[name]={name}
    generic={'use','uses','used','documentation','documents','directory','context','history','knowledge','currently','this','our','the','plan','status','configuration','integration','goals','architecture','stack','overview','features','requirements','workflow','retrieval','constraints','setup'}
    named=re.search(r"(?i)\bproject\s+[`\"']?([a-z][\w.-]*)",query)
    if named and named.group(1).lower() not in generic and not any(named.group(1).lower() in values for values in aliases.values()):return []
    scopes={key for key,values in aliases.items() if any(re.search(r'(?i)(?<![\w-])'+re.escape(value)+r'(?![\w-])',query) for value in values)}
    count = max(1,min(int(limit),10))
    vector = model().encode(query,normalize_embeddings=True).tolist()
    project_filter=None
    allowed_ids=None
    if scopes:
        values=set()
        for scope in scopes:
            values.update(aliases[scope])
        project_filter='project IN ('+','.join("'"+value.replace("'","''")+"'" for value in sorted(values))+')'
        scoped_rows=table.search().where(project_filter).limit(20000).to_list()
        allowed_ids=[row['id'] for row in scoped_rows]
    dense_query=table.search(vector).distance_type("cosine")
    if project_filter:dense_query=dense_query.where(project_filter,prefilter=True)
    dense = dense_query.limit(30).to_list()
    dense = [row for row in dense if row["_distance"] <= max_distance]
    fingerprint = table.head(1).to_pylist()[0].get("corpus_version", "") if "corpus_version" in table.schema.names else ""
    lexical_query=lexical_content_query(query,scopes,aliases)
    ids = keyword_ids(lexical_query,fingerprint,allowed_ids=allowed_ids) if fingerprint else []
    ids = [value for value in ids if re.fullmatch(r"[a-f0-9]{64}",value)]
    lexical = []
    if ids:
        found = table.search().where("id IN ("+",".join("'"+value+"'" for value in ids)+")").limit(len(ids)).to_list()
        by_id = {row["id"]:row for row in found}
        lexical = [by_id[value] for value in ids if value in by_id]
    scores = {}
    rows = {}
    for channel, candidates in [("semantic",dense),("keyword",lexical)]:
        for rank,row in enumerate(candidates,1):
            key = row["id"]
            scores[key] = scores.get(key,0)+1/(60+rank)
            if key not in rows:
                rows[key] = {k:v for k,v in row.items() if k!="vector"}
                rows[key]["retrieval_channels"] = []
            rows[key]["retrieval_channels"].append(channel)
    historical = bool(re.search(r"(?i)\b(old|history|historical|previous|earlier|session|conversation|archived)\b|سابق|جلسة|محادثة",query))
    for key,row in rows.items():
        is_history = row.get("kind") in {"opencode_session","native_answer"}
        scores[key] *= (1.15 if is_history else 1.0) if historical else (0.85 if is_history else 1.15)
    policy_path=ROOT/"retrieval-policy.json"
    policy=json.loads(policy_path.read_text()) if policy_path.exists() else {}
    minimum=float(policy.get("minimum_evidence_coverage",0.5))
    weights=policy.get("current_project_source_weights",{})
    other_project=bool(scopes)
    for key in list(scores):
        if scopes and not any(rows[key].get('project')==scope or any(alias in str(rows[key].get('project','')) for alias in aliases[scope]) for scope in scopes):
            del scores[key]
            continue
        coverage=evidence_coverage(query,rows[key])
        if coverage<minimum:
            del scores[key]
            continue
        scores[key] *= coverage*coverage
        if not historical and not other_project:
            scores[key] *= float(weights.get(rows[key].get('source'),1.0))
        rows[key]['evidence_coverage']=coverage
    prefer_original=historical and not re.search(r'(?i)\bnative\b|verified answer',query)
    ordered = sorted(scores,key=lambda key:(prefer_original and rows[key].get('kind')!='opencode_session',-scores[key],key))[:count]
    return [{**rows[key],"retrieval_score":scores[key]} for key in ordered]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("command",choices=["ingest","search"])
    p.add_argument("query",nargs="?",default="")
    a=p.parse_args()
    print(json.dumps(ingest() if a.command=="ingest" else search(a.query),ensure_ascii=False))
if __name__=="__main__":
    main()
