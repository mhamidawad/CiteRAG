"""Read-only, allowlisted OpenCode history export; redact before writing/indexing."""
import argparse
import hashlib
import json
import math
import tempfile
from itertools import chain
from collections import Counter
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/context"
PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("provider_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,})\b")),
    ("bearer", re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/-]{8,}=*")),
    ("url_credentials", re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")),
    ("authorization_header", re.compile(r'''(?im)(authorization["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\r\n]+)''')),
    ("credential_assignment", re.compile(r'''(?i)([\w.-]*(?:api[_-]?key|password|access[_-]?token|refresh[_-]?token|client[_-]?secret|secret|token|credential)[\w.-]*["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''')),
]


def redact(text):
    counts = {}
    for name, pattern in PATTERNS:
        replacement = r"\1[REDACTED]@" if name == "url_credentials" else r"\1[REDACTED]" if name in {"credential_assignment", "authorization_header"} else "[REDACTED]"
        text, count = pattern.subn(replacement, text)
        if count:
            counts[name] = count
    def opaque(match):
        value = match.group()
        if re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", value):
            return value
        frequencies = Counter(value)
        entropy = -sum((n / len(value)) * math.log2(n / len(value)) for n in frequencies.values())
        mixed = any(c.isupper() for c in value) and any(c.islower() for c in value) and any(c.isdigit() for c in value)
        if mixed and entropy >= 4.2:
            counts["opaque_token"] = counts.get("opaque_token", 0) + 1
            return "[REDACTED]"
        return value
    text = re.sub(r"(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{40,}(?![A-Za-z0-9_+/=-])", opaque, text)
    return text, counts


def plain_text(role, payload):
    if role == "user":
        value = payload.get("text")
        return value if isinstance(value, str) else ""
    if role == "assistant":
        parts = payload.get("content", [])
        if not isinstance(parts, list):
            return ""
        return "\n".join(part["text"] for part in parts if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str))
    return ""


def session_documents(config, report):
    path = Path(config["database"])
    con = sqlite3.connect("file:" + quote(str(path.resolve())) + "?mode=ro", uri=True, timeout=3)
    con.execute("PRAGMA query_only=ON")
    con.execute("BEGIN")
    try:
        report["total_sessions_available"] = con.execute("SELECT count(*) FROM session_v2").fetchone()[0]
        for directory in config["session_directories"]:
            sessions = con.execute("SELECT id,time_created,time_updated FROM session_v2 WHERE directory=? ORDER BY time_created DESC,id LIMIT ?", (directory, config["sessions_per_directory"])).fetchall()
            report["selected_sessions"] += len(sessions)
            for session_id, created, updated in sessions:
                rows = con.execute("SELECT id,type,seq,time_created,data FROM session_message WHERE session_id=? AND type IN ('user','assistant') ORDER BY seq LIMIT ?", (session_id, config["max_messages_per_session"])).fetchall()
                if not any(role == "assistant" and plain_text(role, json.loads(data)).strip() for _, role, _, _, data in rows):
                    report["skipped_unanswered_sessions"] += 1
                    continue
                text = ["# Archived OpenCode conversation", "Historical conversation evidence; not a verified statement of current runtime state. Bounded plain-text excerpts only; tool outputs and reasoning are excluded.", "Session: " + session_id, "Project directory: " + directory, "Created (Unix milliseconds): " + str(created), "Updated (Unix milliseconds): " + str(updated)]
                size = 0
                included = 0
                for message_id, role, seq, timestamp, data in rows:
                    payload = json.loads(data)
                    if not isinstance(payload, dict):
                        continue
                    body = plain_text(role, payload).strip()
                    if not body:
                        continue
                    clean, counts = redact(body)
                    remaining = config["max_session_characters"] - size
                    if len(clean) > remaining:
                        report["bounded_sessions"] += 1
                        break
                    size += len(clean)
                    for key, value in counts.items():
                        report["redactions"][key] = report["redactions"].get(key, 0) + value
                    text.extend(["\n## " + role + " message " + message_id, "Sequence: " + str(seq) + "; timestamp: " + str(timestamp), clean])
                    included += 1
                    report["exported_messages"] += 1
                    report[role + "_messages"] += 1
                if included:
                    name = "sessions/" + hashlib.sha256(session_id.encode()).hexdigest()[:24] + ".md"
                    yield name, "\n\n".join(text), {"kind": "opencode_session", "session_id": session_id, "project": directory, "created": created, "updated": updated, "messages": included}
    finally:
        con.rollback()
        con.close()


def file_documents(config, report):
    for project, location in config["document_roots"].items():
        root = Path(location)
        if root.is_symlink() or not root.is_dir():
            report["skipped_sources"].append(location)
            continue
        resolved = root.resolve()
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
                continue
            if not path.resolve().is_relative_to(resolved) or any(part.startswith(".") for part in path.relative_to(root).parts) or path.stat().st_size > 256000:
                continue
            yield from sanitized_file(path, "projects/" + project + "/" + path.relative_to(root).as_posix(), project, report)
    for name, location in config.get("files", {}).items():
        path = Path(location)
        if Path(name).name != name or path.is_symlink() or not path.is_file() or path.stat().st_size > 256000:
            report["skipped_sources"].append(location)
            continue
        yield from sanitized_file(path, "project/" + name, "default", report)


def sanitized_file(path, output, project, report):
    clean, counts = redact(path.read_text(encoding="utf-8"))
    for key, value in counts.items():
        report["redactions"][key] = report["redactions"].get(key, 0) + value
    yield output, "# Source document\nOriginal source: " + str(path) + "\nProject: " + project + "\n\n" + clean, {"kind": "native_answer" if project=="native-history" else "project_document", "project": project, "original_path": str(path)}


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Output file must not be a symlink")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".context-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sync(config, apply=False):
    report = {"apply": apply, "selected_sessions": 0, "skipped_unanswered_sessions": 0, "exported_messages": 0, "user_messages": 0, "assistant_messages": 0, "bounded_sessions": 0, "redactions": {}, "skipped_sources": [], "created_or_changed": 0, "unchanged": 0, "removed": 0, "conflicts": []}
    if OUTPUT.is_symlink():
        raise ValueError("Output directory must not be a symlink")
    generated = {}
    total = 0
    for name, body, metadata in chain(session_documents(config, report), file_documents(config, report)):
        path = OUTPUT / name
        if path.is_symlink() or not path.resolve().is_relative_to(OUTPUT.resolve()):
            raise ValueError("Unsafe output path")
        encoded = body.encode()
        total += len(encoded)
        if len(generated) >= 500 or len(encoded) > 256000 or total > 1500000:
            raise ValueError("Export exceeds bounded context budget; no source files were written")
        digest = hashlib.sha256(encoded).hexdigest()
        generated[name] = {**metadata, "sha256": digest, "bytes": len(encoded), "body": body}
    manifest_path = OUTPUT / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Manifest must not be a symlink")
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    preserved = {}
    for name, entry in generated.items():
        path = OUTPUT / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        unchanged = actual == entry["sha256"]
        if actual is not None and not unchanged and (name not in previous or actual != previous[name].get("sha256")):
            report["conflicts"].append(name)
            if name in previous:
                preserved[name] = previous[name]
            continue
        report["unchanged" if unchanged else "created_or_changed"] += 1
        if apply and not unchanged:
            atomic_write(path, entry["body"])
    for name in previous:
        path = OUTPUT / name
        if name not in generated and path.resolve().is_relative_to(OUTPUT.resolve()) and not path.is_symlink():
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() != previous[name].get("sha256"):
                report["conflicts"].append(name)
                preserved[name] = previous[name]
                continue
            report["removed"] += 1
            if apply and path.is_file():
                path.unlink()
    report["documents"] = len(generated)
    report["bytes"] = total
    if apply:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        manifest = {name: {key: value for key, value in entry.items() if key != "body"} for name, entry in generated.items() if name not in report["conflicts"]}
        manifest.update(preserved)
        atomic_write(manifest_path,json.dumps(manifest,indent=2)+"\n")
    return report


def refresh():
    from citerag.semantic import ingest
    import fcntl
    from datetime import datetime,timezone
    lock=ROOT/'data/context-refresh.lock'
    lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'deferred','reason':'Another context refresh is active'}
        try:
            sources=ROOT/'context-sources.json'
            if sources.exists():
                config=json.loads(sources.read_text())
                summary=sync(config,apply=True)
                if summary['conflicts']:return {'status':'failed','reason':'User-edited context files were preserved','conflicts':summary['conflicts']}
            else:
                # Standalone mode: only approved local docs/ are indexed.
                # Ingest verifies the source set; no missing external exporter is assumed fresh.
                summary={'mode':'standalone-docs','selected_sessions':0}
            result={'status':'completed','sync':summary,'index':ingest(),'updated_at':datetime.now(timezone.utc).isoformat()}
            atomic_write(ROOT/'data/context-status.json',json.dumps(result,indent=2)+'\n')
            return result
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "context-sources.json"))
    parser.add_argument("--apply", action="store_true", help="Write sanitized context; otherwise preview counts only")
    args = parser.parse_args()
    if args.apply:
        from citerag.freshness import check_writer_access
        check_writer_access()
    report = sync(json.loads(Path(args.config).read_text()), apply=args.apply)
    (ROOT / "reports/context-sync.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    raise SystemExit(1 if report["conflicts"] else 0)

if __name__ == "__main__":
    main()
