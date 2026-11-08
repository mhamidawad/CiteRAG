# Oracle Supervisor → CircleCI controller (20-slot bounded preflight)

**Status:** implementation/tested locally; live dispatch blocked until a valid
CircleCI personal API token and 20-cloud-job acceptance are verified.
This is **not** a 20-agent OpenCode inference executor.

## Control plane

- Oracle remains the OpenCode Supervisor host.
- `tasks/circleci_supervisor.py status` queries the verified CircleCI project
  and scans up to five pages / 100 pipelines; unknown or incomplete state blocks dispatch.
- `tasks/circleci_supervisor.py dispatch --confirm-readonly-20` explicitly
  requests **one** 20-way read-only preflight for the reviewed branch. It
  refuses dispatch if any inspected pipeline is active, or if CircleCI API
  authentication, pagination, or state inspection fails.
- CircleCI `resource_class: small`, `parallelism: 20` and
  `run_workers=false` remain the default, so ordinary commits do not launch
  this workload. The worker reads allowlisted repo files, writes a local
  artifact, and makes **no AI model calls** or repository modifications.
- The controller uses a local `~/.config/citerag/circleci.env` with mode
  `600`. It never emits tokens; no token is stored in the repository.
  It does not evaluate the credential file as shell code.

## Operational procedure

1. Verify the connected CircleCI project's identity and available credits.
   Organization **MOeHami**, project ID
   `92a7b55f-2fa6-4db1-88f2-7437c381c958`.
2. Store a working personal token in the local permission-restricted file.
   Do not paste the token in chat or logs.
3. Run `python tasks/circleci_supervisor.py status`. Any HTTP error or
   uncertain pipeline state blocks dispatch; do not bypass it.
4. Only after confirming plan limits, current runs, and credit budget,
   run `python tasks/circleci_supervisor.py dispatch --confirm-readonly-20`
   once. Review the reported pipeline ID in CircleCI.
5. Inspect all 20 shard artifacts and billing/credits. If the workflow fails,
   inspect the precise job error before submitting a new pipeline.

**Limitations:** Local preflight tests cannot prove the cloud service's
available concurrency. CircleCI plan and credit limits are not guaranteed
by this controller. The controller is intended for a single operator on one
host; it does not provide a distributed lock across multiple controllers.
To execute arbitrary coding tasks via CircleCI, a separate reviewed
task manifest/queue, isolated model credentials, GitHub write scopes,
bounded retries, attested results, cancellation, credit limits, and
Supervisor orchestration integration are required. Do not enable
agent inference or production deployment through this scaffold.

## Verified blockers at implementation time

The previously accepted personal API token began returning HTTP 401 for
`/api/v2/me` and the exact project endpoint. No new CircleCI pipeline
was started while these requests failed. A past workflow also surfaced
a GitHub `error` check and needs job-level inspection before acceptance.

The release controller targets the reviewed default `main` branch and is
validated for CircleCI paginated history; it is not automatically scheduled.
