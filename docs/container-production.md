# Container production release

## Runtime layout

The production retrieval services run from the scanned GHCR image with the image's pinned Python and SQLite libraries. The deployment host runs only the standard-library OpenCode bridge and the Docker/systemd service wrappers. The native worker is not granted the Docker socket; the bridge starts one fixed, bounded verify-native.py invocation using the existing reviewed OpenCode image and a dedicated scoped credential file.

The MCP and dashboard containers share the persistent admission database outside their release directory. The model cache and approved source trees are read-only mounts. Both listeners bind to IPv4 loopback. Containers run nonroot, read-only, without Linux capabilities, with CPU, memory, task and PID bounds. The native bridge binds only to 127.0.0.1:60760; application listeners use the ports in the private production environment file.

## Build and scan

Only GitHub Actions builds and publishes the image. The publish job requires the protected default branch, authenticates to the free Docker Hardened Images registry, verifies the reviewed signed vendor VEX pin, builds the digest-pinned Python 3.12 Debian 13 runtime, retains a raw Trivy HIGH/CRITICAL report, then derives exact scanner PURLs only when Trivy's dpkg inventory maps the installed binary to a signed vendor versioned source product and the installed version matches. The derived OpenVEX preserves the vendor disposition and is applied by the strict Trivy gate; unmatched findings remain blocking. Python dependency advisories are audited separately. The workflow preserves the release evidence artifact even when an earlier step fails.

## Prepare a release

Run deploy/activate-container-release.py as the nonroot service account on the deployment host. Supply the repository-scoped immutable GHCR image digest, the matching reviewed source SHA, a new release directory, the existing persistent state directory, the private runtime environment file and a separate private bridge environment file. The default run validates only. Review its VALIDATED JSON result, the release artifact evidence, the resolved image ID and the three named systemd units before adding --activate.

Activation pulls the exact digest, checks its OCI source label and platform, extracts only source files (never Python packages), validates the container import surface, stages service units, and records their previous state and definitions. It manages only citerag-production-mcp, citerag-production-web and citerag-production-native-bridge. On activation failure it restores those units to their recorded definitions and active/enabled states. The admission ledger remains outside the versioned release so a software rollback cannot reset its counters.

## Acceptance and rollback

A started release is ACTIVE_NOT_CERTIFIED until current-image retrieval, native OpenCode tool use, direct OmniRoute grounding, dashboard browser acceptance, authorization boundaries, quota behavior and route rollback rehearsal all pass against the same artifact identity. Preserve raw reports and bind them to the image digest, source SHA, backend ID and bridge fingerprints. Never label a prior report as current after source, binary, credentials, endpoint, model or image identity changes.

For rollback, run the same helper using the prior verified digest and a new release directory while keeping the same state ledger and credentials. The route switch is a separate operation; snapshot the private Tailscale Serve map first and preserve unrelated routes. Do not remove previous image data or repository/model data as part of software rollback.