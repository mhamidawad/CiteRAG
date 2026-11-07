# CiteRAG architecture

## Boundaries

CiteRAG has three conceptual layers. The document layer reads allowlisted Markdown/text under `docs/`, enforces limits, splits into overlapping token windows, and stores local vectors in LanceDB plus keyword candidates in SQLite FTS5. A lexical/semantic retrieval layer combines candidates with reciprocal-rank fusion and applies scope/evidence checks. The answer layer returns source-cited excerpts or an abstention. The optional generation layer can call an explicitly configured OmniRoute endpoint without using a Docker inspection lookup.

The REST/dashboard and MCP endpoints are interfaces to this core. The source of truth is local approved documentation; data files and model cache are gitignored. The standalone mode refreshes `docs/` before retrieval. An optional exporter configuration is distinct from standalone mode and must never ingest private directories by default.

## Security boundaries

Default listeners are loopback. There is no authenticated remote MCP transport or reliable per-workspace authorization yet. Do not publish ports, use in multitenant environments, or interpret this architecture note as a security certification. The base repository and production containers are excluded from the new project's mutation scope.

## Verified and outstanding

Local tests and isolated indexing, deletion, reused embeddings, cited retrieval, abstention, REST calls and a separate MCP client have executed. Authenticated MCP, integrated OpenCode answer generation, OmniRoute generation, independent fresh installs, CI/OCI images, deployment and real-browser QA are unverified or blocked. See GitHub milestone Issues #1–#7 for evidence and blockers.
