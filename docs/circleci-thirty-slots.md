# CircleCI 30 concurrent cloud-job slots — Supervisor preflight

**Status: configured in Git, not activated on CircleCI.**

The manual-only job in `.circleci/config.yml` is a 30-container
**cloud** preflight, not 30 independent language-model agents. It is gated by
`run_workers=false` by default and the approved parameter must be set
explicitly to `true` when running one bounded acceptance pipeline. Each
container uses `CIRCLE_NODE_INDEX` and `CIRCLE_NODE_TOTAL` to inspect
one of 30 distinct, allowlisted tracked source files (five roles × six
shards), with no repository edits and no model calls. No Oracle VM resources
are consumed by these cloud executors except any later authenticated
controller polling.

CircleCI Free currently advertises up to **30 concurrent cloud jobs**,
subject to remaining credits and organization-level capacity. Free
**self-hosted runner** concurrency is separately limited to five, so
installing CircleCI runner on Oracle would not meet the goal.

## Required to activate

1. Connect the GitHub repository to the intended CircleCI organization.
2. Verify plan, remaining free credits and concurrent-job usage in CircleCI.
3. Configure the CircleCI project to read this feature branch's configuration.
4. Trigger one `run_workers=true` pipeline *manually*; inspect 30
   artifacts and credit consumption before attempting another.
5. Keep `run_workers` false for ordinary pushes. Do not enable
   automatic 30-executor launches on every commit.

## To delegate real OpenCode agent tasks

The existing Supervisor still runs on `moe-instance`. This preflight
**does not** migrate OpenCode or enable autonomous AI workers. Real
delegation requires a separately reviewed queue and dispatcher, authenticated
CircleCI project/API credentials, immutable task IDs, branch- and
workspace-scoped GitHub worktrees, capped task runtime, budget check,
allowed tool set, a result verification channel (e.g. GitHub issue/PR)
and cancellation. Do not serialize model-provider secrets or Oracle
production configuration into CircleCI artifacts. The remote scheduler
is **not configured or verified** while credentials/project are missing.

No AI inference, public deployments, production container modifications,
or unattended paid builds are authorized by the 30-slot preflight.
