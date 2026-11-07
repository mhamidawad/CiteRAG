# Isolated Docker staging (not yet accepted)

The multi-stage Dockerfile installs Python dependencies from the version-pinned lockfile using a CPU-only PyTorch package index, runs with UID/GID 65532, and is intended to be built **only by GitHub Actions**. Neither a GHCR image nor a running Docker deployment has been verified. The current GitHub authorization cannot push new workflow files; see Issue #6.

The minimal Compose template binds MCP and web to host loopback-only high ports 28761 and 28762. It uses distinct containers, mounted docs/config and persistent LanceDB/model-cache volumes, read-only root filesystems, dropped capabilities, no-new-privileges, health probes, and initial (not measured) CPU/memory limits. It does not modify production containers.

Do not run this template before GHCR and independent security acceptance. The model cache must be populated with the approved local embedding model; outbound inference is not configured. Remote authenticated MCP, browser QA, and safe image rollback remain pending. Review network/firewall rules before any deployment.
