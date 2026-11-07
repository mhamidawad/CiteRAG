# CiteRAG - Self-hosted, source-cited RAG for OpenCode and AI coding agents

**Private development preview — not production ready.** CiteRAG is self-hosted RAG for coding agents, built around CPU-friendly local embeddings, LanceDB hybrid search and source-cited responses. It is derived from the owner's private `moe-opencode-rag` project, with original history and runtime data deliberately excluded.

## Current capabilities (verified locally)

- Python retrieval works without OpenCode or an LLM.
- CPU `sentence-transformers/all-MiniLM-L6-v2` embeddings; LanceDB vectors and SQLite FTS5 keyword search with reciprocal rank fusion.
- Local re-indexing reused unchanged embeddings and removed deleted chunks in the isolated smoke test.
- Extractive source citations are validated against retrieved content; unsupported queries can abstain instead of generating unsupported text.
- An independent Python MCP client discovered and called `rag_search` over an isolated localhost streamable HTTP endpoint, then confirmed cleanup.
- REST `/api/ask` can return validated cited excerpts or an exact abstention in `retrieval-only` mode.
- A preliminary adapter registry lists `opencode`, `omniroute`, `retrieval-only`, and the dashboard reads the registry. Listing an adapter is **not** proof of its generation acceptance.

## Quick start — local developer checkout

Requirements: Python 3.12; preinstalled dependencies from the pinned `requirements.lock.txt`; a locally cached MiniLM model. **A clean dependency install has not yet been independently accepted.** The existing CI workflow cannot be pushed until workflow permissions are corrected.

```bash
python -m venv .venv
. .venv/bin/activate
# Check that pinned CPU dependencies and the configured PyTorch index are available.
python -m pip install -r requirements.lock.txt
python -m unittest discover -s tests -q
python -m compileall -q citerag
python -m citerag.semantic ingest
python -m citerag.cli ingest
python -m citerag.cli search "OpenCode"
python tasks/verify-retrieval.py
python tasks/verify-mcp-client.py
```

The two ingest examples exercise different modes: `semantic` uses LanceDB + MiniLM + FTS5; `cli` is the standard-library-only SQLite FTS5 fallback. Place approved `.md`/`.txt` documents under `docs/` before indexing. The current code does **not** automatically ingest an arbitrary full source-code repository.

## Local API and MCP

The web app provides `GET /api/health`, `GET /api/adapters`, `GET /api/context`, `POST /api/ask`, and `GET /api/jobs/{job_id}`. The MCP server provides `rag_search(query, limit)` over streamable HTTP. Restrict access to trusted local clients. Remote authentication is not implemented; do not expose these listeners publicly.

```bash
CITERAG_WEB_HOST=127.0.0.1 CITERAG_WEB_PORT=18762 python -m citerag.web
# In a separate process, only on a trusted local machine:
CITERAG_MCP_HOST=127.0.0.1 CITERAG_MCP_PORT=18761 python -m citerag.server
```

### Agent support

| Integration | Status |
| --- | --- |
| Retrieval-only REST | Tested locally against sample documents |
| Independent MCP Python client | Tested locally over isolated loopback HTTP |
| OpenCode generation adapter | Registered; **not accepted** as standalone integration |
| OmniRoute direct generation | Configured opt-in; real standalone generation **not tested** |
| Continue, custom MCP clients | Candidates; no tested profile or compatibility claim |

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CITERAG_MCP_HOST` | MCP listener interface | `127.0.0.1` |
| `CITERAG_MCP_PORT` | MCP listener port | `18761` |
| `CITERAG_WEB_HOST` | REST/dashboard listener interface | `127.0.0.1` |
| `CITERAG_WEB_PORT` | REST/dashboard listener port | `18762` |
| `CITERAG_EMBEDDING_MODEL` | Local embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| `CITERAG_MODEL_CACHE_DIR` | Model cache location | `data/models` |
| `CITERAG_OFFLINE` | Use local model files only | `1` |
| `CITERAG_OMNIROUTE_URL` | Optional OmniRoute base URL | Unset |
| `CITERAG_OMNIROUTE_API_KEY` | Optional generation credential | Unset |
| `CITERAG_MODEL` | Optional generation model ID | Unset |
| `CITERAG_WRITER_OWNER` | Optional writer-lease owner | Unset |

No browser form accepts API keys; do not commit credentials. The dashboard adapter preference uses browser localStorage, guarded against storage exceptions.

## Safety and limitations

The approach is a source-cited RAG MCP server; it is **not** a guarantee of perfect factual correctness or "RAG without hallucination." Claim validation is conservative and extractive; a valid quote is not proof that an underlying source is true. Redaction is heuristic, workspace-level authorization and authenticated remote MCP transport remain unfinished, and no full fresh-install, image-build, production rollout or browser visual acceptance has passed. The source owner's previously exposed Context7/OmniRoute credentials still require coordinated rotation before any public release.

See [architecture](docs/architecture.md), [adapters](docs/adapters.md), [rollback](docs/rollback.md), [security](SECURITY.md) and [NOTICE](NOTICE).

## Troubleshooting / rollback

If model loading fails, confirm the local MiniLM cache and `CITERAG_OFFLINE`. If no relevant source exists, the service should abstain. If an isolated MCP port is unexpectedly in use, do not kill another process. For rollback, stop only CiteRAG processes, retain a private snapshot of CiteRAG's own data if needed, and return to the verified previous branch; never modify original OpenCode or OmniRoute services. See [rollback](docs/rollback.md).

**Status:** Private draft PRs only. There is no approved public release or v0.1.0 artifact.
