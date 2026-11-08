# CiteRAG — Self-hosted, source-cited RAG for coding agents

CiteRAG combines local CPU embeddings, LanceDB vector search, SQLite FTS5 keyword search and source-cited responses. It is derived from the owner's RAG project with original runtime data and history excluded. The source repository is public and a `v1.0.0` GitHub release exists; those facts do not establish production certification.

## Capabilities and acceptance

| Capability | Evidence and limit |
| --- | --- |
| Retrieval | MiniLM/LanceDB/FTS5 retrieval, embedding reuse, deletion and unsupported-query abstention passed isolated sample-document acceptance. |
| REST and MCP | Bearer authentication and independent `rag_search` client acceptance passed isolated staging. |
| Agent selection | Registry exposes `retrieval-only`, `omniroute`, `opencode`; registration alone does not certify generation. |
| Native OpenCode | Bounded standalone acceptance runner exists. A real standalone tool/cited-answer trace must pass before autonomous production. |
| Delivery | GitHub Actions remote test/build workflows and GHCR secure image/rollback rehearsals have passed earlier baselines. Every new release needs checks on its exact source. |
| Isolation | Immutable secure candidate → previous secure → candidate rehearsal passed; production cutover is a separate gate. |

See [release certification](docs/release-certification.md) for the dated evidence and outstanding gates. CircleCI has been retired; the existing GitHub baseline runner executes 20 sequential logical preflight checks, not 20 cloud workers.

## Developer setup

Use Python 3.12 and a locally cached `sentence-transformers/all-MiniLM-L6-v2` model. Runtime containers default to offline model loading. For this project's Oracle deployment, build container images on GitHub Actions rather than the VM.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock.txt
python -m unittest discover -s tests -q
python -m compileall -q citerag
python tasks/scan-secrets.py
python tasks/scan-secrets.py --history
```

Dependency versions are pinned; hash locking, image-base digest pinning and a complete dependency security review require separate acceptance. Hosted CI installs the lock from a fresh runner; full clean-host model bootstrap and end-to-end installation require their own evidence.

Place approved documents under `docs/`, then run `python -m citerag.semantic ingest` for MiniLM/LanceDB/FTS5 or `python -m citerag.cli ingest` for the standard-library SQLite fallback. The document loader currently accepts Markdown/text; arbitrary source-code repository ingestion is not automatic.

## API and security

The REST app provides `/api/health`, `/api/adapters`, `/api/context`, `/api/ask` and `/api/jobs/{job_id}`; MCP provides `rag_search` over streamable HTTP. Listener defaults are loopback ports 18762 (REST) and 18761 (MCP); deployed port mappings may differ.

Set a protected server-side `CITERAG_API_TOKEN` of at least 32 characters and `CITERAG_REQUIRE_AUTH=1` for authenticated operation. Non-loopback binding requires authentication. REST health is public process liveness; all other REST paths and all MCP paths require a bearer token when configured. Use private HTTPS or a trusted TLS reverse proxy. See [authenticated access](docs/authenticated-access.md).

No browser form should accept provider credentials. Do not commit credentials, indexes, session exports or model traces. Credential rotation and revocation must be verified through the authorized issuer.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CITERAG_WEB_HOST` / `CITERAG_WEB_PORT` | REST listener | `127.0.0.1` / `18762` |
| `CITERAG_MCP_HOST` / `CITERAG_MCP_PORT` | MCP listener | `127.0.0.1` / `18761` |
| `CITERAG_API_TOKEN` | Server-side bearer credential | Unset |
| `CITERAG_REQUIRE_AUTH` | Require authentication on loopback too | Unset |
| `CITERAG_EMBEDDING_MODEL` | Local embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| `CITERAG_MODEL_CACHE_DIR` | Model cache | `data/models` |
| `CITERAG_OFFLINE` | Local model files only | `1` |
| `CITERAG_OMNIROUTE_URL` | Generation routing base URL | Unset |
| `CITERAG_OMNIROUTE_API_KEY` | Protected generation credential | Unset |
| `CITERAG_MODEL` | Generation model | Unset |
| `CITERAG_WRITER_OWNER` | Writer lease owner | Unset |

## Limitations and recovery

Citations support checking an answer against retrieved material; they cannot guarantee the truth of the original source. Redaction is heuristic. Workspace permissions, quotas, browser acceptance and real generating-adapter traces need explicit release evidence.

If offline model loading fails, check the approved model cache. Unsupported queries should abstain. Stop or roll back only CiteRAG's own services and preserve its private data snapshot; do not modify original OpenCode or OmniRoute services. See [architecture](docs/architecture.md), [adapters](docs/adapters.md), [Docker](docs/docker.md), [rollback](docs/rollback.md), [security](SECURITY.md) and [NOTICE](NOTICE).
