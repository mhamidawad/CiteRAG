# CircleCI GitHub App: 20-shard acceptance

The existing 20-way CircleCI job is read-only, manual, and disabled by default. It does not deploy to production or run models. Local execution of 20 worker slots is not equivalent to 20 successful cloud executions.

CircleCI API v3 is the current API and provides the GitHub App pipeline definition, runs, workflows, jobs, and artifact data. The legacy API v2 launch can return an ambiguous 404 for this project. A failed or timed-out launch must **not** be retried blindly.

Use the authenticated CircleCI project UI or an explicitly authorized connection to launch **exactly one** run on reviewed `main`, setting `run_workers=true`. Check the account credit quota and ensure no other active run first. Never reuse this flag for deployment, build, migrations or paid inference.

For a completed run, execute:

```bash
python tasks/circleci_v3_verify.py ACTUAL_RUN_UUID
```

The read-only verifier must observe a successful run, a single matching workflow and job, and fetch exactly 20 CircleCI-hosted artifact files. Each file must contain a valid `worker-result.json` with its own unique 0–19 slot, approved source, role and shard, `status=preflight_pass`, and false values for both `ai_inference` and `writes_to_repository`. Any missing evidence fails closed. Unknown artifact URL hosts, redirects or pagination are not accepted without separate review. A pipeline ID alone is not acceptance evidence.

Official references: https://circleci.com/docs/api/v3/ and https://circleci.com/docs/guides/toolkit/api-v3-developers-guide/ .
