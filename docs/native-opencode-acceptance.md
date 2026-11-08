# Native OpenCode / CiteRAG milestone — bounded acceptance

**Status:** Native inference passed in the original RAG host environment.
Authenticated CiteRAG MCP connectivity from the OpenCode Docker network passed
separately. A combined model-generated answer using CiteRAG's own MCP backend
has **not** passed; do not advertise standalone native OpenCode as ready.

## Observed acceptance

- The original isolated OpenCode runner completed one real local-model
  invocation via the existing router, with one completed MCP tool call,
  verified citations and claims, a consistent service identity, and a closed
  temporary listener. The verified run took about 149 seconds.
- A temporary authenticated CiteRAG MCP container was attached to the OpenCode
  Docker network, without publishing a host port. An isolated temporary
  OpenCode profile pointed its existing RAG retrieval tool at the protected
  CiteRAG endpoint and supplied a temporary Authorization header.
- OpenCode's bounded `mcp list` completed with exit code 0 and
  an authenticated MCP tool marked connected. No inference was sent by this probe;
  the temporary token-bearing profile and temporary MCP container were removed.
- This proves transport and authentication reachability, **not** an end-to-end
  generated answer against standalone CiteRAG sources.
- CircleCI's 20-way read-only workload remains unverified. Two bounded manual
  pipeline launch attempts, against different reviewed branches, returned
  HTTP 404 with the response `Pipeline not found.`. Do not auto-retry.

## Host-only resource gate

Before **any new local-model acceptance test**, run:

```sh
python3 tasks/native_inference_preflight.py
```

The command does not load models or initiate inference. It reads host memory,
swap, CPU load and root-disk usage; it fails closed if host telemetry is
missing. A Docker container's `/proc` accounting may not reflect host limits,
so the command must run on the host, not inside the application container.

The gate uses conservative defaults, pending performance benchmarking:

| Signal | Require |
| --- | --- |
| Available host memory | at least 5 GiB |
| Free swap | at least 1 GiB |
| 1-minute load | at most half the logical CPU count |
| Root disk utilization | below 85% |

A BLOCKED status exits 2, with safe reason codes; a READY status exits 0.
It does **not** certify model price, tool correctness, network authorization,
tenant access, production rollback, or the exact available memory inside a
container. A fresh runner still needs its own timeout and model-cost checks.

## Next mandatory verification

1. Resolve the CircleCI project-definition/manual-run 404 through authorized
   CircleCI account diagnostics before another 20-worker launch.
2. When resource guard returns READY, run **one** isolated OpenCode invocation
   against authenticated CiteRAG MCP (not the original RAG MCP). Require a
   completed tool event, CiteRAG source and chunk provenance, validated final
   citations and claims, and teardown of the isolated service.
3. Package a dedicated, least-privileged standalone CiteRAG executor or
   delegated agent worker. The original host-specific verification script
   cannot simply be copied into the GHCR image, and no Docker socket should
   be mounted into the public application.
4. Verify TLS/private access, per-workspace authorization, quotas, secret
   rotation, rollback and model budgets before full production.

**Current release decision:** retrieval-only authenticated staging accepted;
full autonomous production remains NO-GO.
