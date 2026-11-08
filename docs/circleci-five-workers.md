# Supervisor → CircleCI: five-worker readiness pipeline

**Status:** prepared, not connected or deployed; **not five AI agents**.

The repository provides a manually triggered CircleCI cloud workflow with
five separate concurrent job containers (`parallelism: 5`). Slots 0–4 run
distinct bounded source/security checks (planner, retrieval, tests, security,
review), and publish one JSON result artifact each. The code intentionally
does **not** call OmniRoute, start OpenCode, modify the repository, read private
secrets or fetch private data.

This is the first safe execution contract for later Supervisor delegation,
not working cloud AI-agent orchestration. The actual Supervisor still runs on
Oracle VM; the real OpenCode agent is not relocated by adding this config.

## Activation prerequisites

1. Connect the owner's CircleCI account and add the GitHub CiteRAG project.
2. Configure CircleCI to read `.circleci/config.yml` from an approved branch
   after review. This workflow is disabled by default on pushes.
3. Manually trigger a pipeline with the boolean parameter
   `run_workers=true`. Record the pipeline ID and five job results.
4. Enforce total <= 5, bounded timeout and free-tier credit budget.
5. To evolve these checks into real AI agents, separately implement verified
   runtime packaging, explicit task scoping and ownership, secure agent-model
   credentials, network access to OmniRoute, GitHub least-privilege results,
   safe cancellation and owner review. **Do not assume access to a private
   Oracle endpoint or copy any tokens to CircleCI logs.**

The CircleCI Free plan's concurrency allowance does not imply unlimited
compute credits or zero-cost model inference.

## Local contract check

`python -m unittest tests.test_circleci_worker -v` (or unittest discovery)
validates five distinct slots and refusal of invalid slot counts. These checks
only use Python's standard library and Git.
