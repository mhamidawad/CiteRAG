# CiteRAG - Self-hosted, source-cited RAG for OpenCode and AI coding agents

> **Development preview. Not production ready.** This repository is private pending security review and reproducible integration testing.

CiteRAG is a Python-first, self-hosted RAG for coding agents. Its initial retrieval core uses LanceDB hybrid search with local MiniLM embeddings and SQLite FTS5, with conservative source citations and unsupported-answer abstention. This is a sanitized development fork; MCP interoperability, new adapters, deployment, and browser QA require separate acceptance.

## Status
- Refactoring in progress; do not expose publicly or deploy into production.
- Baseline: 63 existing source tests pass in an isolated workspace with an artificial text fixture.
- Tests use a pre-existing source project virtualenv until dependency-lock fresh-install validation.
- Do not assume the tests establish complete agent or runtime integration.

## Local checks

```bash
python -m unittest discover -s tests -q
python -m compileall -q citerag
```

## Configuration

Generation is opt-in. The retrieval core does not need an LLM. Set `CITERAG_OMNIROUTE_URL`, `CITERAG_OMNIROUTE_API_KEY` and `CITERAG_MODEL` in a private environment before attempting direct generation; never commit credentials. MCP defaults to loopback with `CITERAG_MCP_HOST=127.0.0.1` and `CITERAG_MCP_PORT=18761`. External access and authentication have not yet been approved.

This project is derived from the private `moe-opencode-rag` project by the same owner. See [NOTICE](NOTICE). The repository is not yet approved for public release.
