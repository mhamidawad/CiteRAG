# Authenticated rollback gate (read-only)

The standalone CiteRAG application is **not certified for autonomous-agent production**. Before switching any private HTTPS proxy, verify candidate identity, digest, root filesystem, loopback binding, anonymous denial and authorized access:

```sh
python3 tasks/rollback_auth_preflight.py \
  --candidate-container citerag-auth-web-stage-20261108 \
  --candidate-port 48762 \
  --token-env-file "$HOME/.config/citerag/auth-staging.env"
```

The command makes read-only Docker inspections and two loopback GETs to
`/api/context`. It does **not** change Tailscale Serve, route traffic,
restart containers, start inference, or commit credentials.

Exit 0 / PASS requires an immutable digest reference, running unprivileged
container with read-only root filesystem and loopback-only publishing, no
Docker socket mount, HTTP 401 without a token, and HTTP 200 with the
approved local token. Unknown observations fail closed with exit 2.

The prior GHCR image is intentionally **not** an acceptable fallback: its
anonymous `/api/context` returns HTTP 200. The guard returns
`ANONYMOUS_ACCESS_NOT_DENIED` for it. Never route protected production
traffic to that older image.

A separate temporary instance of the current authenticated MCP image
successfully initialized and returned an authorized retrieval result on
loopback; the container was removed afterward. This is a **recovery startup
drill**, not a version rollback, failover under load, or traffic-cutover test.

To certify production rollback: build a distinct authenticated rollback
candidate through remote CI, sign/pin its digest, run its integration tests
and protected API/MCP checks, then exercise a reversible **private**
cutover with end-user probes, logging, latency/consistency checks, and
restoration to the known-good current release. Never use Funnel.
