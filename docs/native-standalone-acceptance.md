# Bounded standalone OpenCode acceptance

The operator-only `tasks/verify-native.py` runner is a fail-closed acceptance probe, not a production web service or deployment authorization. It launches one disposable, non-root, read-only OpenCode container with one permitted CiteRAG MCP tool. Model inference routes through the reviewed free local OmniRoute model and is bounded by a hard deadline. Offline unit tests never start a model.

Provision a separate owner-only environment file (mode 0600) containing valid `CITERAG_API_TOKEN` and `CITERAG_OMNIROUTE_API_KEY` entries. Credentials must be provisioned by an authorized issuer. Never commit or print them, and do not extract or copy secrets from existing production services.

Select a reviewed, pinned OpenCode binary directory and run:

```bash
python tasks/verify-native.py --env-file /path/to/private-native.env --binary-dir /path/to/reviewed-opencode-binary --question "Which vector database does this project use?"
```

The runner checks host resource admission before executing Docker, uses only the configured project-scoped MCP search tool and a fixed free model, and saves a sanitized JSONL trace and verification report in a per-run directory. Verification requires a real native tool event, approved source path and chunk ID, and a supported verbatim claim. An exit code, a historical trace, or a successful model-only response is not production certification.

A missing scoped credential or reviewed binary, unsafe permissions, timeout, denied MCP access, unsupported claims, or other unexpected tool use must fail closed. Backend identity attestation, CircleCI cloud-worker evidence, and the production web-adapter integration remain independent gates.
