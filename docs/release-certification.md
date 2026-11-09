# Release certification evidence — 2026-11-08

Production certification is not yet complete. This record distinguishes source implementation, local live checks and remote release acceptance.

## Current completion evidence

- Source branch contains the integrated retrieval, single-workspace policy, dashboard/source management and bounded native adapter changes. PR [#53](https://github.com/mhamidawad/CiteRAG/pull/53) carries the release/security follow-up at `9309597`; later work must record its own final commit.
- Local completion suite recorded 159 passing tests using an existing runtime. This is not a clean install of the upgraded dependency lock.
- Real approved repository ingestion, unchanged embedding reuse and deletion acceptance passed live checks.
- Authenticated candidate APIs returned anonymous 401, wrong-workspace 403 and correct authorized workspace 200.
- GitHub security controls were enabled during completion work. Earlier disabled/unprotected observations below describe the original baseline.
- Dependency preparation now has 73 version pins and 1,299 official wheel SHA256 entries, with hash verification and wheel-only installation; the supported CPU Torch lock targets CPython 3.12 on Linux amd64. Four vulnerable dependencies were upgraded and seven transitives added. The replacement Transformers version is non-yanked. OSV querybatch reported zero findings for all 73 selected pins at preparation time.
- The Docker Python base is digest-pinned. Hosted baseline/publish workflows include exact-source tests, compilation and pinned MiniLM download/offline real retrieval acceptance. Publication adds dependency audit, HIGH/CRITICAL image scanning and source/image digest artifacts before GHCR.
- These workflow/security changes are source preparation until their actual hosted steps pass. PR #53 status observed at `9309597`: container build succeeded, unit workflow failed; final clean-install/release acceptance remains unresolved.

## Native integration evidence and remaining gate

A live OpenCode probe invoked one actual CiteRAG tool and passed backend/citation plumbing checks, but returned irrelevant UI text. It is not certified native answer acceptance. The known-fact benchmark must retrieve useful evidence and answer the question; `--certify-current` now requires acceptance terms, with `--require-term LanceDB` for the vector database benchmark.

Use evidence from this standalone backend only. Do not substitute source-project historical traces or a successful model-only response.

## Earlier baseline and deployment evidence

Repository visibility is public, default branch `main`, and release `v1.0.0` exists (2026-11-08T02:50:25Z). Those facts do not establish production readiness.

Before completion work, source `ae7ae79` failed source scanning at `.github/workflows/context7-refresh.yml:10` in [42511161095](https://github.com/mhamidawad/CiteRAG/actions/runs/42511161095); the reachable-history scan saw the same file version. The Context7 workflow then targeted `master`, security controls were disabled, `main` unprotected, the image base mutable and dependencies unhashed. The release changes address those source/configuration gaps; preserve the historical finding and verify the final replacement checks.

[Issue #30](https://github.com/mhamidawad/CiteRAG/issues/30) records earlier authenticated REST/MCP staging and isolated secure candidate → previous secure → candidate rollback. This is not final-candidate production cutover. CircleCI was retired; old worker requirements are superseded.

## Final certification criteria

Record the final commit and immutable image digest, green clean-runtime tests/retrieval and image/dependency scans, known-fact native answer with source/chunk/backend evidence, authorization/quota/private-network checks, browser acceptance and production deployment/rollback outcome. Preserve unresolved credential lifecycle or security review limitations explicitly. Do not mark a gate passed because code, a tag, or a route exists.
