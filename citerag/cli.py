"""Offline RAG document retrieval. Standard library only."""
import argparse
import pathlib
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = (ROOT / "docs").resolve()

def connect(db_path):
    path = pathlib.Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS documents USING fts5(path UNINDEXED, content)")
    return con

def ingest(db_path, source):
    source = pathlib.Path(source).resolve()
    if source != DOCS and DOCS not in source.parents:
        raise ValueError("Only project docs/ may be indexed")
    if not source.is_dir():
        raise ValueError("Source directory not found")
    con = connect(db_path)
    count = 0
    try:
        with con:
            con.execute("DELETE FROM documents")
            for p in sorted(source.rglob("*")):
                if p.is_symlink() or not p.is_file() or p.suffix.lower() not in {".md", ".txt"}:
                    continue
                if not p.resolve().is_relative_to(DOCS) or p.stat().st_size > 256_000:
                    continue
                content = p.read_text(encoding="utf-8")
                con.execute("INSERT INTO documents(path,content) VALUES (?,?)", (str(p.relative_to(ROOT)), content))
                count += 1
    finally:
        con.close()
    return count

def search(db_path, query, limit=5):
    if not query.strip():
        return []
    con = connect(db_path)
    try:
        return con.execute(
            "SELECT path, snippet(documents,1,'[',']','...',20) FROM documents WHERE documents MATCH ? ORDER BY bm25(documents) LIMIT ?",
            (query, max(1, min(limit, 20))),
        ).fetchall()
    finally:
        con.close()

def main():
    parser = argparse.ArgumentParser(description="Offline, project-scoped RAG retrieval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ingest")
    a.add_argument("source", nargs="?", default=str(DOCS))
    b = sub.add_parser("search")
    b.add_argument("query")
    b.add_argument("--limit", type=int, default=5)
    for p in (a,b):
        p.add_argument("--db", default=str(ROOT / "data/index.sqlite3"))
    args = parser.parse_args()
    if args.cmd == "ingest":
        print(f"Indexed {ingest(args.db, args.source)} documents")
    else:
        for path, excerpt in search(args.db, args.query, args.limit):
            print(f"{path}: {excerpt}")

if __name__ == "__main__":
    main()
