"""Explicit, bounded Git-tracked source ingestion; no browser-selected host paths."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from citerag.context import redact

MAX_FILES = 500
MAX_FILE_BYTES = 256000
MAX_TOTAL_BYTES = 2000000
MAX_LIST_BYTES = 2000000
SOURCE_SUFFIXES = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs",
    ".java", ".kt", ".swift", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb",
    ".php", ".sh", ".bash", ".sql", ".html", ".css", ".scss", ".vue",
    ".svelte", ".md", ".txt", ".toml", ".yaml", ".yml", ".json",
})
EXCLUDED_PARTS = frozenset({
    "node_modules", "vendor", "dist", "build", "coverage", "__pycache__",
    "data", "reports", "logs", "models", "target", "venv", "env",
})
SENSITIVE_NAME = re.compile(
    r"(?i)(?:^|[._-])(?:secret|secrets|credential|credentials|password|passwords|"
    r"private[-_]?key|token|tokens|auth[-_]?staging|service[-_]?account)(?:[._-]|$)"
)

def configured_sources():
    """Read operator configuration; fail closed for invalid or ambiguous names."""
    raw = os.getenv("CITERAG_REPOSITORY_SOURCES", "{}")
    if len(raw) > 16384:
        raise ValueError("Repository source configuration exceeds limit")
    data = json.loads(raw)
    if not isinstance(data, dict) or len(data) > 8:
        raise ValueError("Repository source configuration must map at most eight names")
    result = {}
    for name, value in data.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name):
            raise ValueError("Invalid repository source name")
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("Repository roots must be explicit absolute paths")
        path = Path(value)
        # Reject symlinks at every path component, not only the leaf.
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_dir():
            raise ValueError("Repository root unavailable or symlinked")
        root = path.resolve()
        if root == Path("/"):
            raise ValueError("Filesystem root is not a repository source")
        result[name] = root
    return result

def _git(root, *args):
    # Temporary file prevents an unbounded subprocess output allocation.
    with tempfile.TemporaryFile() as output:
        try:
            subprocess.run(["git", "-C", str(root), *args], stdout=output,
                           stderr=subprocess.DEVNULL, timeout=10, check=True)
        except (subprocess.SubprocessError, OSError):
            raise ValueError("Approved source is not a readable Git repository") from None
        if output.tell() > MAX_LIST_BYTES:
            raise ValueError("Repository listing exceeds bounded limit")
        output.seek(0)
        return output.read()

def _approved_path(relative):
    parts = relative.parts
    return (bool(parts) and re.fullmatch(r"[A-Za-z0-9_./-]+", relative.as_posix()) is not None and
            not relative.is_absolute() and
            all(part not in {"", ".", ".."} and not part.startswith(".")
                and part.casefold() not in EXCLUDED_PARTS for part in parts) and
            not any(SENSITIVE_NAME.search(part) for part in parts) and
            (relative.suffix.casefold() in SOURCE_SUFFIXES or relative.name == "Dockerfile"))

def _scan(name, root):
    top = _git(root, "rev-parse", "--show-toplevel").decode().strip()
    if Path(top).resolve() != root:
        raise ValueError("Approved root must be the Git repository root")
    raw = _git(root, "ls-files", "--cached", "-z")
    paths = sorted(set(raw.split(b"\0")) - {b""})
    # Bound before reading bodies even when most listed paths would be excluded.
    if len(paths) > 20000:
        raise ValueError("Repository has too many tracked entries")
    revision = _git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    documents, excluded, total = [], 0, 0
    for item in paths:
        try:
            relative = PurePosixPath(item.decode("utf-8", errors="strict"))
        except UnicodeError:
            excluded += 1
            continue
        if not _approved_path(relative):
            excluded += 1
            continue
        path = root.joinpath(*relative.parts)
        if (any(p.is_symlink() for p in (path, *path.parents) if p != root.parent)
                or not path.is_file() or not path.resolve().is_relative_to(root)):
            excluded += 1
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            excluded += 1
            continue
        body = path.read_bytes()
        if len(body) > MAX_FILE_BYTES or b"\0" in body:
            excluded += 1
            continue
        try:
            text = body.decode("utf-8", errors="strict")
        except UnicodeError:
            excluded += 1
            continue
        text, _ = redact(text)
        total += len(text.encode("utf-8"))
        if len(documents) >= MAX_FILES or total > MAX_TOTAL_BYTES:
            raise ValueError("Approved source exceeds ingestion budget")
        source = "repositories/" + name + "/" + relative.as_posix()
        documents.append((source, text))
    return documents, {"name": name, "state": "ready", "documents": len(documents),
                       "bytes": total, "excluded": excluded, "revision": revision}

def repository_documents():
    """Yield sanitized current tracked files; removed paths disappear on reindex."""
    total_files = total_bytes = 0
    # Build the entire source set before yielding so invalid later roots fail closed.
    combined = []
    for name, root in configured_sources().items():
        documents, _ = _scan(name, root)
        for source, text in documents:
            total_files += 1
            total_bytes += len(text.encode("utf-8"))
            if total_files > MAX_FILES or total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("Combined approved repositories exceed ingestion budget")
            combined.append((source, text))
    yield from combined

def source_status():
    """Content-free inventory for an authenticated dashboard."""
    result = []
    for name, root in configured_sources().items():
        try:
            _, status = _scan(name, root)
        except ValueError:
            status = {"name": name, "state": "unavailable"}
        result.append(status)
    return result
