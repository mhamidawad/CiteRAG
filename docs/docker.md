# Docker build and isolated deployment

The multi-stage Dockerfile uses a version-pinned Python dependency list and CPU PyTorch index. Runtime UID/GID is 65532, offline model loading is the default, and image import checks exercise a nonroot read-only container. Build images through GitHub Actions; do not build on the Oracle VM.

GitHub Actions container and publication workflows have produced GHCR images at earlier reviewed baselines. The final release must repeat source/history scans, tests and build checks on its exact source. The Python base image is mutable and dependency hashes are not locked; these remain supply-chain review items.

The checked-in Compose template is a staging starting point, not evidence of a running secure deployment. Its default host mappings are loopback 28761/28762. Mounted docs/config, index and model caches must be owned and provisioned for the runtime identity. It sets read-only root filesystems, dropped capabilities, no-new-privileges, health probes and initial CPU/memory limits.

Use external protected credentials with `CITERAG_REQUIRE_AUTH=1`; template services binding to `0.0.0.0` require a valid server-side API token. Never put tokens into image build arguments or committed Compose configuration. Pin deployed artifacts by full digest, verify matching source and keep an authentication-equivalent secure rollback digest.

Previously tested authenticated staging uses separate port mappings; inspect live configuration rather than assuming the template ports. Native agent generation requires additional scoped model/MCP credentials and trace acceptance. Consult [authenticated access](authenticated-access.md), [rollback](rollback.md), and [release gates](go-public-checklist.md).
