# Authenticated CiteRAG REST and MCP — release gate

**Status:** implemented and tested in isolated processes; **not deployed to production**.

## Behavior

The REST API and streamable-HTTP MCP server accept an optional
`CITERAG_API_TOKEN` environment variable. When set, all REST routes except
`/api/health` and **all MCP routes** require exactly one
`Authorization: Bearer <token>` header. Missing, incorrect or duplicate
headers receive HTTP 401. Responses carry `Cache-Control: no-store`.

Server-side startup calls `validate_binding()`: a non-loopback listener
(`0.0.0.0` or anything other than `127.0.0.1`, `::1`, `localhost`) **must**
have a token of at least 32 characters. Setting `CITERAG_REQUIRE_AUTH=1`
requires a token even for loopback. The standalone loopback development
defaults remain usable without a token; never expose unauthenticated loopback
development services via a public reverse proxy or port mapping.

## Credential handling

Generate a cryptographically random token with Python's `secrets` module,
store it outside Git, and pass it using a permission-restricted secret store.
Do **not** put it in GitHub Actions output, Docker image build arguments,
Compose source, URL query parameters, model prompts or logs. Production
runbooks should use external secret injection and rotation, not a committed
`.env`. Tokens are checked with constant-time comparison.

The unauthenticated `/api/health` path provides **process liveness only**;
it is not a readiness or security certification endpoint.

## Isolated acceptance evidence

- Full local test suite: 100 tests passed.
- REST temporary server: health 200, anonymous adapters 401, token-bearing
  adapters 200 (3 adapters listed), temporary process stopped.
- MCP temporary server: anonymous `/mcp` 401, authenticated session
  initialized and `rag_search` listed, temporary process stopped.
- Native OpenCode and OmniRoute AI inference **not verified** by these tests.

## Required production controls not yet certified

Transport encryption / trusted private network or reverse proxy; token
provisioning and rotation; per-workspace authorization; rate limits;
security review; bounded inference model costs; secret scanning; service
upgrade and rollback acceptance; and actual manual GitHub Actions read-only worker preflight.

Do not claim complete production authorization from bearer authentication
alone. Do not expose these endpoints publicly until the above controls pass.
