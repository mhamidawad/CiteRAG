# Release certification evidence — 2026-11-08

This audit inspected source `ae7ae798b6ace620954e5d5d468326a4259ccf7d` on branch `feat/complete-production-20261108` before the completion changes. A subsequent release must replace or supplement this snapshot with exact final-commit evidence.

## Verified from repository and GitHub

- Repository visibility is public, default branch is `main`.
- GitHub release `v1.0.0` exists (published 2026-11-08T02:50:25Z); a tag is not autonomous production acceptance.
- Last earlier successful baseline: [42507416078](https://github.com/mhamidawad/CiteRAG/actions/runs/42507416078), source `d1126b4`.
- At the inspected source, baseline [42511161095](https://github.com/mhamidawad/CiteRAG/actions/runs/42511161095) failed at source secret scanning. Local source and history scanners both reported `.github/workflows/context7-refresh.yml:10` as a private reference. History scan audited 96 commits and 176 file versions.
- The new Context7 refresh workflow targets `master` despite default `main`; it has no explicit timeout/permissions and its curl command does not fail on HTTP errors.
- GitHub API reported secret scanning, push protection and Dependabot security updates disabled. `main` branch protection returned 404 (branch not protected).
- Requirements are version-pinned without package hashes; Docker base `python:3.12-slim-bookworm` is not digest-pinned.
- Container CI verifies runtime imports/nonroot/read-only behavior; the publish workflow does not itself execute the full unit suite, dependency review or image vulnerability scan.
- Document ingestion at the inspected source accepts approved Markdown/text under `docs/`; arbitrary source repository ingestion remains a separate feature.

## Prior release tracker evidence

[Issue #30](https://github.com/mhamidawad/CiteRAG/issues/30) records authenticated REST/MCP staging and isolated authentication-preserving candidate → previous secure → candidate rollback. It also records native runner availability, but no accepted standalone OpenCode tool/cited-answer trace and no production cutover. Older issue comments mentioning CircleCI cloud workers are superseded by provider retirement.

## Certification rule

Production acceptance requires green checks and image provenance for the final commit, bounded real native tool/answer evidence from this standalone backend, authorization/quota/private-network acceptance, browser and fresh-install evidence, and a production deployment/rollback record. Keep test-only evidence distinct from live acceptance. Record failures and missing issuer credentials without substituting older project traces.
