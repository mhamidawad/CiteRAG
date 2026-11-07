#!/usr/bin/env python3
"""Conservative generic leak scanner; emits locations, never matched contents."""
import pathlib, re, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
patterns={
    'private path or brand': re.compile(r'(?i)ubuntu|moe-|termal|172\.18|phaglp'),
    'credential-shaped material': re.compile(r'(?i)ses_[A-Za-z0-9]{18,}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|BEGIN PRIVATE KEY'),
}
files=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
failed=False
for name in files:
    p=ROOT/name
    if not p.is_file():continue
    if name in {'NOTICE','README.md','tasks/scan-secrets.py'}:continue  # provenance and scanner pattern definitions
    lines=p.read_text(errors='replace').splitlines()
    for i,line in enumerate(lines,1):
        for label,pattern in patterns.items():
            if pattern.search(line):
                print(f'{name}:{i}: {label}')
                failed=True
sys.exit(1 if failed else 0)
