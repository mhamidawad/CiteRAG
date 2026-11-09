# CiteRAG architecture

CiteRAG uses LanceDB as its embedded vector database.

## Retrieval and ingestion

Local `sentence-transformers/all-MiniLM-L6-v2` embeddings run on CPU. LanceDB supplies dense vector candidates; SQLite FTS5 supplies keyword candidates. Reciprocal-rank fusion combines them before source scope, relevance and citation checks. Retrieval-only responses contain conservative cited excerpts or an explicit insufficient-evidence abstention.

The document layer reads approved Markdown/text under `docs/`, splits overlapping token windows and reuses unchanged embeddings. It also supports operator-configured Git repositories through `CITERAG_REPOSITORY_SOURCES`, a JSON mapping from safe source names to explicit absolute repository roots. Only tracked allowlisted UTF-8 source/document files are eligible; hidden, dependency, generated, sensitive-name, binary and symlink paths are excluded. Redaction precedes embedding. File count, individual size and combined corpus limits bound ingestion. Citation identifiers are `docs/...` or `repositories/<name>/<relative-path>`; host root paths are not source identifiers.

Standalone retrieval refreshes approved sources before search. Index updates share a writer lock. Optional history export is a separate operator configuration; it must not import private directories by default. Model cache, indexes, operational credentials and raw traces stay outside Git.

## Interfaces and generation

REST/dashboard and streamable-HTTP MCP expose the core. MCP `rag_search` returns source/chunk evidence and a deployment backend identifier. REST exposes adapter capabilities, context/source status, operator-approved reindexing and asynchronous answer jobs. Browsers cannot choose arbitrary server paths or submit provider secrets.

The optional native adapter invokes a bounded disposable nonroot, read-only OpenCode worker. Model inference goes through the configured OmniRoute route. Real tool execution, backend identity, citation grounding and answer relevance are separate acceptance requirements. A successful tool call or a quoted but irrelevant passage does not certify a useful answer.

## Security boundaries

Listeners default to loopback. Authenticated REST/MCP operation uses a server-side bearer token and private HTTPS; non-loopback startup requires authentication. Production mode also requires an explicit workspace identifier and persistent admission budgets. A deployment owns one workspace/index/token boundary; separate tenants require separate deployments and data volumes. Alternate requested workspace identifiers are rejected before application work.

Rate and generation admission counters are persistent SQLite transactions. They count admitted operations rather than measuring token billing. Fixed free/local native routing and hard worker timeouts provide additional inference limits. See [authenticated access](authenticated-access.md).

## Acceptance status

Sample and real approved repository ingestion, reuse/deletion, source-cited retrieval, abstention and authenticated staging have live evidence. The local completion suite recorded 159 passing tests on an existing runtime. Candidate authorization returned anonymous 401, wrong-workspace 403 and authorized 200.

A native live probe executed one actual tool call with backend/citation checks but returned irrelevant UI wording; it is plumbing evidence, not native answer certification. Remote clean installation against the patched hash lock, final relevance acceptance and production cutover remain independent gates. See [release certification](release-certification.md).
