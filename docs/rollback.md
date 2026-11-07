# Rollback and isolation

1. Verify the CiteRAG service and exact branch/commit before taking action. Confirm the source project and its containers are not targets.
2. Stop only the isolated CiteRAG process/container. Do not stop `opencode-agent`, OmniRoute or any original production service.
3. If changing a database schema, back up **only** the CiteRAG data directory outside Git. Keep permissions private.
4. Revert the unmerged CiteRAG feature branch or restart an earlier approved CiteRAG image, if one exists. No image or staged installation is currently accepted.
5. Check local loopback ports are closed after shutdown. Re-run tests and check that the source repo checkout remains untouched.

Never force-push or merge the source repository. Do not change GitHub visibility or tag v0.1.0 before explicit owner approval.
