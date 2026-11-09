"""Explicit, bounded Git-tracked source ingestion without a Git runtime dependency."""
import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
from citerag.context import redact

MAX_FILES = 500
MAX_FILE_BYTES = 256000
MAX_TOTAL_BYTES = 2000000
MAX_LIST_BYTES = 2000000
MAX_INDEX_ENTRIES = 20000
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
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_dir():
            raise ValueError("Repository root unavailable or symlinked")
        root = path.resolve()
        if root == Path("/"):
            raise ValueError("Filesystem root is not a repository source")
        result[name] = root
    return result


def _git_directory(root):
    marker = root / ".git"
    if marker.is_symlink():
        raise ValueError("Git metadata must not be symlinked")
    if marker.is_dir():
        gitdir = marker
    elif marker.is_file():
        content = marker.read_text(encoding="utf-8").strip()
        if not content.startswith("gitdir: ") or len(content) > 4096:
            raise ValueError("Invalid Git directory pointer")
        target = Path(content[8:])
        gitdir = target if target.is_absolute() else root / target
    else:
        raise ValueError("Approved source is not a readable Git repository")
    gitdir = gitdir.resolve()
    if not gitdir.is_dir() or any(p.is_symlink() for p in (gitdir, *gitdir.parents)):
        raise ValueError("Git metadata directory unavailable or symlinked")
    return gitdir


def _object_format(gitdir):
    config_path = gitdir / "config"
    if config_path.is_symlink():
        raise ValueError("Symlinked Git config is unsupported")
    parser = configparser.ConfigParser(interpolation=None)
    if config_path.is_file():
        try:
            if config_path.stat().st_size > 65536:
                raise ValueError("Git config exceeds limit")
            parser.read(config_path, encoding="utf-8")
        except (OSError, configparser.Error) as exc:
            raise ValueError("Invalid Git config") from exc
    name = parser.get("extensions", "objectformat", fallback="sha1").lower()
    if name not in {"sha1", "sha256"}:
        raise ValueError("Unsupported Git object format")
    return name


def _read_index(gitdir, algorithm):
    index = gitdir / "index"
    if index.is_symlink() or not index.is_file() or index.stat().st_size > MAX_LIST_BYTES:
        raise ValueError("Git index unavailable or exceeds limit")
    data = index.read_bytes()
    digest_size = hashlib.new(algorithm).digest_size
    if len(data) < 12 + digest_size or data[:4] != b"DIRC":
        raise ValueError("Invalid Git index header")
    if hashlib.new(algorithm, data[:-digest_size]).digest() != data[-digest_size:]:
        raise ValueError("Git index checksum mismatch")
    version, count = struct.unpack(">II", data[4:12])
    if version not in {2, 3, 4} or count > MAX_INDEX_ENTRIES:
        raise ValueError("Unsupported Git index version or entry count")
    end = len(data) - digest_size
    offset = 12
    previous = b""
    paths = set()
    oid_size = digest_size
    for _ in range(count):
        start = offset
        if offset + 40 + oid_size + 2 > end:
            raise ValueError("Truncated Git index entry")
        offset += 40 + oid_size
        flags = struct.unpack(">H", data[offset:offset + 2])[0]
        offset += 2
        if flags & 0x4000:
            if version < 3 or offset + 2 > end:
                raise ValueError("Invalid extended Git index flag")
            offset += 2
        if version == 4:
            if offset >= end:
                raise ValueError("Truncated Git index path prefix")
            byte = data[offset]
            offset += 1
            remove = byte & 0x7f
            while byte & 0x80:
                if offset >= end:
                    raise ValueError("Truncated Git index path prefix")
                byte = data[offset]
                offset += 1
                remove = ((remove + 1) << 7) | (byte & 0x7f)
            if remove > len(previous):
                raise ValueError("Invalid Git index path prefix")
            nul = data.find(b"\0", offset, end)
            if nul < 0:
                raise ValueError("Unterminated Git index path")
            path = previous[:len(previous) - remove] + data[offset:nul]
            offset = nul + 1
        else:
            nul = data.find(b"\0", offset, end)
            if nul < 0:
                raise ValueError("Unterminated Git index path")
            path = data[offset:nul]
            offset = nul + 1
            padded = start + ((offset - start + 7) & ~7)
            if padded > end or any(data[offset:padded]):
                raise ValueError("Invalid Git index entry padding")
            offset = padded
        if not path or b"/" not in path and path in {b".", b".."}:
            raise ValueError("Invalid Git index path")
        try:
            path.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError("Git path is not UTF-8") from exc
        paths.add(path)
        previous = path
    while offset < end:
        if offset + 8 > end:
            raise ValueError("Truncated Git index extension")
        signature = data[offset:offset + 4]
        length = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        offset += 8
        if offset + length > end:
            raise ValueError("Invalid Git index extension length")
        # Optional uppercase extensions (TREE, REUC, FSMN, UNTR, EOIE, IEOT)
        # carry no file paths. Split/sparse indexes are intentionally rejected.
        if not signature[:1].isupper():
            raise ValueError("Split or unsupported Git index extension")
        offset += length
    if offset != end:
        raise ValueError("Git index has trailing data")
    return paths


def _head_revision(gitdir, algorithm):
    head = gitdir / "HEAD"
    if head.is_symlink() or not head.is_file() or head.stat().st_size > 4096:
        raise ValueError("Git HEAD unavailable")
    value = head.read_text(encoding="ascii").strip()
    if value.startswith("ref: "):
        ref = value[5:]
        parts = ref.split("/")
        if not ref.startswith("refs/") or any(p in {"", ".", ".."} for p in parts) or not re.fullmatch(r"[A-Za-z0-9._/-]+", ref):
            raise ValueError("Invalid Git HEAD reference")
        loose = gitdir / ref
        if loose.is_symlink():
            raise ValueError("Symlinked Git reference is unsupported")
        if loose.is_file():
            if loose.stat().st_size > 256:
                raise ValueError("Git reference exceeds limit")
            value = loose.read_text(encoding="ascii").strip()
        else:
            packed = gitdir / "packed-refs"
            if packed.is_symlink() or not packed.is_file() or packed.stat().st_size > MAX_LIST_BYTES:
                raise ValueError("Git reference unavailable")
            value = ""
            for line in packed.read_text(encoding="ascii").splitlines():
                if not line or line.startswith(("#", "^")):
                    continue
                fields = line.split(" ", 1)
                if len(fields) == 2 and fields[1] == ref:
                    value = fields[0]
                    break
    if not re.fullmatch(r"[0-9a-fA-F]{" + str(hashlib.new(algorithm).digest_size * 2) + r"}", value):
        raise ValueError("Invalid Git HEAD object ID")
    return value.lower()


def _git_inventory(root):
    gitdir = _git_directory(root)
    algorithm = _object_format(gitdir)
    return _read_index(gitdir, algorithm), _head_revision(gitdir, algorithm)


def _approved_path(relative):
    parts = relative.parts
    return (bool(parts) and re.fullmatch(r"[A-Za-z0-9_./-]+", relative.as_posix()) is not None and
            not relative.is_absolute() and
            all(part not in {"", ".", ".."} and not part.startswith(".")
                and part.casefold() not in EXCLUDED_PARTS for part in parts) and
            not any(SENSITIVE_NAME.search(part) for part in parts) and
            (relative.suffix.casefold() in SOURCE_SUFFIXES or relative.name == "Dockerfile"))


def _scan(name, root):
    raw_paths, revision = _git_inventory(root)
    paths = sorted(raw_paths)
    if len(paths) > MAX_INDEX_ENTRIES:
        raise ValueError("Repository has too many tracked entries")
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
