#!/usr/bin/env python3
"""Scan tracked CiteRAG files for private references and secret-shaped content.

Reports file/line/category only; never prints matched values.
"""
from pathlib import Path
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

def issues_for_line(name, line):
    # Only the exact historical attribution is approved, not whole-file exemptions.
    if name in {"NOTICE", "README.md"}:
        line=line.replace("moe-opencode-rag","[approved upstream attribution]")
    # Scanner's own signatures are source code, not detected credential values.
    if name=="tasks/scan-secrets.py" and ("re.compile(" in line or "moe-opencode-rag" in line):
        return []
    return [kind for kind,regex in PATTERNS.items() if regex.search(line)]

def main():
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
