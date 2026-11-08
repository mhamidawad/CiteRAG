#!/usr/bin/env python3
"""Scan tracked CiteRAG files for private references and secret-shaped content.

Reports file/line/category only; never prints matched values.
"""
from pathlib import Path
import hashlib
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private reference": re.compile(r"(?i)\bubuntu\b|moe-|termal|172\.18|phaglp|127\.0\.0\.1:18762"),
    "credential-shaped text": re.compile(r"(?i)ses_[A-Za-z0-9]{18,}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|BEGIN PRIVATE KEY"),
    "bearer value": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{20,}"),
    "embedded URL credentials": re.compile(r"https?://[^/\s:@]+:[^/\s@]+@"),
    "assigned credential": re.compile(r"(?i)^\s*(?:[A-Z_]*(?:API_KEY|ACCESS_TOKEN|SECRET|PASSWORD|PRIVATE_KEY))\s*=\s*[A-Za-z0-9_-]{16,}"),
}

# Audited safe source literals. Fingerprints are exact-line SHA-256 values;
# exemptions cannot be broadened by changing the fixture or runner line.
SAFE_LINE_HASHES = {
    (".github/workflows/tests.yml", "8696328bb3578e73007deb73951f192dd6d9e5894858a0998c4137ba59de553d"),
    ("tests/test_context.py", "37486930fd6cf97bf63d48df6d57cbc111d557a9a35b12d4893baf881fa5d829"),
    ("docs/circleci-thirty-slots.md", "12038242c9bcd10e272d6c5d38b44d1073231f32216ed64dd9e6f3192486ce45"),
}

def issues_for_line(name, line):
    if (name, hashlib.sha256(line.encode()).hexdigest()) in SAFE_LINE_HASHES:
        return []
    # Only the exact historical attribution is approved, not whole-file exemptions.
    if name in {"NOTICE", "README.md"}:
        line=line.replace("moe-opencode-rag","[approved upstream attribution]")
    # Scanner's own signatures are source code, not detected credential values.
    if name=="tasks/scan-secrets.py" and ("re.compile(" in line or "moe-opencode-rag" in line):
        return []
    return [kind for kind,regex in PATTERNS.items() if regex.search(line)]

def scan_history():
    """Audit every reachable commit's blobs; never print matching values."""
    commits=subprocess.check_output(["git","rev-list","--all"],cwd=ROOT,text=True).splitlines()
    if len(commits)>500:
        print("History limit exceeded; use a dedicated offline scanner",file=sys.stderr)
        return 2
    blobs=set()
    for commit in commits:
        tree=subprocess.check_output(["git","ls-tree","-r","-z",commit],cwd=ROOT)
        for item in tree.split(b"\0"):
            if not item:
                continue
            metadata,name=item.split(b"\t",1)
            mode,kind,oid=metadata.split(b" ")
            if kind==b"blob":
                blobs.add((oid.decode(),name.decode(errors="replace")))
    if len(blobs)>5000:
        print("History blob limit exceeded; use a dedicated offline scanner",file=sys.stderr)
        return 2
    found=False
    for oid,name in sorted(blobs):
        data=subprocess.check_output(["git","cat-file","blob",oid],cwd=ROOT)
        if b"\0" in data[:2048]:
            continue
        for lineno,line in enumerate(data.decode(errors="replace").splitlines(),1):
            for category in issues_for_line(name,line):
                print(f"{name}:{lineno}: {category}; blob {oid[:12]}")
                found=True
    print(f"History audited: {len(commits)} commits, {len(blobs)} file versions")
    return 1 if found else 0

def main():
    if sys.argv[1:] == ["--history"]:
        return scan_history()
    if len(sys.argv)>1:
        print("Usage: scan-secrets.py [--history]",file=sys.stderr)
        return 2
    names=subprocess.check_output(["git","ls-files"],cwd=ROOT,text=True).splitlines()
    found=False
    for name in names:
        path=ROOT/name
        if not path.is_file():
            continue
        for lineno,line in enumerate(path.read_text(errors="replace").splitlines(),1):
            for category in issues_for_line(name,line):
                print(f"{name}:{lineno}: {category}")
                found=True
    return 1 if found else 0

if __name__=="__main__":
    sys.exit(main())
