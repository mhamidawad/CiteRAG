# Contributing to CiteRAG

Until the repository is approved for publication, contributions are private. Reference a GitHub issue, use one dedicated feature branch, and open a draft PR. One writer modifies a workspace at a time; read-only reviews may run in parallel. Preserve reproducible failures and label evidence VERIFIED, FAILED, BLOCKED or NOT TESTED.

Run `python -m unittest discover -s tests -q`, `python -m compileall -q citerag tests tasks`, and `python tasks/scan-secrets.py`. Do not submit secrets or copied runtime data. Never auto-merge, publish images, deploy to production or change repository visibility.
