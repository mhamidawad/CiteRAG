# Rollback and isolation

1. Verify the CiteRAG service and exact branch/commit before taking action. Confirm the source project and its containers are not targets.
2. Stop only the isolated CiteRAG process/container. Do not stop `opencode-agent`, OmniRoute or any original production service.
3. If changing a database schema, back up **only** the CiteRAG data directory outside Git. Keep permissions private.
4. Revert the unmerged CiteRAG feature branch or restart an earlier approved CiteRAG image, if one exists. Earlier secure GHCR images and isolated staging were accepted; verify the exact target and current authorization before use.
5. Check local loopback ports are closed after shutdown. Re-run tests and check that the source repo checkout remains untouched.

Never force-push or merge the source repository. Public source and a v1.0.0 release already exist. Preserve Git history and use a reviewed release candidate for deployment.

## Isolated authentication-equivalent rehearsal (2026-11-08)

Two distinct, immutable GHCR digests were exercised, with an offline model/index copy and a loopback-only read-only HTTP routing probe. The previous secured digest ends in `...61e66`, and the newer reviewed release digest ends in `...85607`. Both ran non-root with a read-only root filesystem and returned 401 for anonymous protected routes, 200 for authenticated context, and 200 for health.

The isolated route changed **candidate → previous secure image → candidate**, validating the rollback and re-promotion path without touching public listeners, existing service container identities, or production routes. The detailed host-side audit is kept outside the public repository. This does **not** certify production cutover or deployment orchestration.

**Never** roll back to a digest that accepts anonymous requests to protected resources. Confirm the actual image digest and source commit at execution time; prefer a staging-only rehearsal with an isolated index and both secure images before changing any production route. Restore only a previously verified authenticated image; keep the private access controls and credential scopes unchanged.
