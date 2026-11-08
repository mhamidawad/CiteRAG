# CiteRAG security policy

CiteRAG source is public. Public source or a release tag does not certify internet-facing or multitenant deployment.

Report vulnerabilities privately to the repository owner using GitHub private vulnerability reporting where available. Never include credentials, private documents or session exports in public issues.

## Implemented foundations

- Source allowlists, path/symlink/size checks, conservative citations and writer locking have tests.
- Source and reachable-history heuristic scanners report locations rather than secret values.
- REST and MCP bearer authentication fail closed for protected network listeners; use private HTTPS and owner-only secret provisioning.
- Isolated authenticated image rollback has been exercised. Production routes require their own acceptance.

## Required release evidence

Verify credential rotation and old-key revocation with the issuer; do not copy credentials out of existing production services. Verify per-workspace permissions, quotas, rate limits, retention/log controls, browser surfaces and actual bounded model calls. Run security checks against the exact release source and image.

As audited on 2026-11-08 at source `ae7ae79`, GitHub secret scanning, push protection and Dependabot security updates were disabled and `main` was unprotected. These are dated observations; recheck before release. The heuristic scanner is not a replacement for independent security review or GitHub controls.

Never commit real environment files, private endpoints, runtime stores, model credentials, original conversation history or raw inference traces. Keep deployment secret files outside the repository with restricted ownership and permissions.
