# Supervisor → CircleCI: 20 concurrent cloud-job preflight slots

**Status:** code prepared and locally testable; CircleCI account/project connection
and actual cloud execution are **NOT VERIFIED**. These are not 20 AI agents.

The manually triggered `.circleci/config.yml` sets `parallelism: 20`
for a small Docker executor, with `run_workers=false` by default. The
`CIRCLE_NODE_INDEX` (0–19) and `CIRCLE_NODE_TOTAL` (20) select one of
20 distinct immutable read-only tasks (five roles × four shards).
All tasks inspect approved tracked files and write only one JSON result to
the runner's `/tmp`; none invokes a model, accesses an Oracle service,
installs software on the VM, modifies source or performs delegation.

CircleCI's published Free cloud concurrency allowance is 30 jobs, but
**20 jobs may consume compute credits quickly**. The Free tier is not a
guarantee of free or unlimited AI inference. Self-hosted CircleCI runners
have separate concurrency limits and are **not** used here.

## Activation prerequisites

1. Connect a CircleCI account and import the GitHub CiteRAG project.
2. Make the reviewed CircleCI configuration available on the CircleCI
   configured source branch. The workflow remains disabled by default.
3. Trigger a **single** manual pipeline with `run_workers=true` and check
   that exactly 20 distinct slot artifacts are produced; stop on failures.
4. Inspect actual credit usage and cap/budget before repeating.
5. For true remote **AI agents**, implement separately: scoped task queue,
   explicit permissions, controlled model proxy/auth, independent workspaces,
   result verification, lease expiry, cancellation, credit budget enforcement
   and audit trails. Production OpenCode Supervisor remains on Oracle.

No CircleCI token was available in the checked VM environment at the time
this scaffold was created. Do not commit or log CircleCI credentials.

The local contract can be exercised with
`python -m unittest tests.test_circleci_worker -v`, followed by the full
test suite and tracked/history secret scans. This verifies only preflight
logic, not external job scheduling or AI delegation.
