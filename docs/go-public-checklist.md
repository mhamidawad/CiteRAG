# CiteRAG v0.1.0 go-public gate — NOT APPROVED

CiteRAG remains PRIVATE. Do not merge stacked draft PRs, release v0.1.0, make the repository public, or expose network listeners without the owner's explicit approval.

## Verified foundations

- [x] Private `mhamidawad/CiteRAG` repository with new Git history (not a source-repo rename)
- [x] Fixed source baseline: `cc695180be680ae3946880518d34bcca0b648547`
- [x] Standalone local ingestion, matching cited retrieval, unsupported-answer abstention, embedding reuse and deleted-document cleanup on isolated sample docs
- [x] Independent Python MCP client can list/call `rag_search` and close the isolated listener
- [x] Retrieval-only REST workflow returns cited, validated extractive answers; invalid adapter requests return 400 without side effects
- [x] Local unit/security test suite passes (latest recorded count: 73)
- [x] GitHub repository topics and description populated; visibility still PRIVATE

## Required remaining gates — not satisfied

- [ ] Owner-coordinated rotation of previously exposed Context7 and OmniRoute credentials; verify old keys revoked without disrupting production
- [ ] Independent full-tree **and all-commits/refs** secret/history audit, including synthetic test fixtures, docs and images
- [ ] Owner review of code, GitHub Issues, stacked PR ordering, diff/commit history, dependencies and license provenance
- [ ] Fresh Python venv installed from lock on a clean environment, with compileall and all tests passing
- [ ] Full repository code ingestion, safe workspace isolation and per-workspace authorization acceptance
- [ ] Authenticated remote MCP transport and tested tool schema/error behavior
- [ ] End-to-end OpenCode and OmniRoute generating-adapter acceptance with zero unsupported claims
- [ ] Full dashboard visual QA, diagnostics, source management and safe settings export
- [ ] Configure GitHub secret scanning, Dependabot and branch protections
- [ ] Resolve GitHub OAuth **workflow scope** blocker (Issue #6), and any account billing limitations, before enabling Actions
- [ ] Green pinned-SHA CI, remote GHCR image build with digest, dependency review and image scan
- [ ] Verify model-cache bootstrap, isolated loopback Docker deployment, service health and safe teardown
- [ ] Verify rollback from a known image tag and ensure production containers are unaffected
- [ ] Independent security review for path traversal, symlink escapes, data retention, logs, session exports, browser and API surfaces
- [ ] Final documented reproducible acceptance demonstration with real approved sample repository, measured benchmarks and evidence

## Owner-only release decision

After **all** gates pass, the owner may explicitly approve (1) PR merges in dependency order, (2) public visibility, (3) `v0.1.0` release and associated GHCR image publication. Until then, all outputs remain private drafts. No approval is inferred from previous repository access or generic deployment permissions.
