# CiteRAG security policy

This is a **private development preview**, not approved for internet or multitenant deployment.

Report suspected vulnerabilities privately to the repository owner via GitHub's private vulnerability reporting where available; do not post secrets, exploit payloads with credentials, or private user data in public issues. Keep the source repo and existing production OpenCode/OmniRoute services separate.

## Known security work

- Local source allowlists, redaction, path/symlink/size checks, writer lock and conservative citation checks exist with tests.
- A generic scanner reports only file/line/category and must pass before review; GitHub's own secret scanning is still required.
- Remote authentication, per-workspace authorization, complete audit logging controls and browser security review remain outstanding.
- Previously exposed source-system Context7 and OmniRoute credentials require owner-coordinated rotation before publication.
- Never commit real `.env` files, histories, session exports, traces, runtime stores, model credentials, or private endpoints.

Public source/release is blocked until credential rotation, independent security review, verified clean Git history, CI and deployment acceptance, and explicit owner authorization.
