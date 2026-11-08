# Release certification checklist

The source repository is already public and GitHub release `v1.0.0` exists. Earlier statements that the repository remains private or all PRs are drafts are historical. The owner authorized completing release and production work on 2026-11-08; this checklist records technical evidence, not a request for repeated permission.

## Previously verified foundations

- [x] Fresh-history source-derived repository and isolated sample-document retrieval.
- [x] Citation validation, abstention, embedding reuse and deleted-chunk cleanup.
- [x] Independent MCP client and retrieval-only REST acceptance.
- [x] Authenticated REST/MCP staging, including anonymous rejection.
- [x] GitHub Actions test/build runs and remote GHCR images at earlier reviewed baselines.
- [x] Authentication-equivalent isolated image rollback and re-promotion.
- [x] CircleCI retirement; GitHub Actions remains the CI provider.

## Exact candidate acceptance

- [ ] Green tests, compilation and source/history scans for the exact release commit.
- [ ] Real standalone OpenCode → authenticated CiteRAG MCP tool event → bounded free/local OmniRoute answer, with source/chunk and backend identity evidence.
- [ ] Real repository ingestion and workspace/tenant authorization acceptance.
- [ ] Rate limits, inference quotas/cost caps and private network boundaries.
- [ ] Authorized credential rotation and old-key revocation evidence.
- [ ] Browser visual/function acceptance, source management, diagnostics and settings export.
- [ ] Fresh-host installation/model-cache bootstrap and measured resource evidence.
- [ ] Dependency/license review, dependency/image security scan, image/source attestation.
- [ ] GitHub secret scanning, push protection, Dependabot and branch protection verified.
- [ ] Final immutable release image and secure rollback target verified.
- [ ] Production deployment, health/authorization tests and rollback acceptance.
- [ ] Dated signed acceptance and reproducible evidence, with unresolved limits stated.

See [release-certification.md](release-certification.md) for the audit snapshot. Do not mark a gate passed solely because code exists, a model replies, or a release tag exists.
