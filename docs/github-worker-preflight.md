# Low-cost GitHub Actions worker acceptance

CiteRAG uses the existing GitHub Actions baseline workflow for tests. That
workflow already runs on pull requests and the default branch and supports
manual `workflow_dispatch` runs.

The Python regression suite runs twenty **bounded, read-only logical source
checks** within its **one** hosted runner. These are five roles with four
distinct source-file shards each. The checks run sequentially, not as twenty
concurrent hosted runners or autonomous agents. This keeps incremental
runner consumption small and adds no new workflow, schedule, or credentials.

To run manually, visit GitHub → Actions → **CiteRAG baseline tests** →
**Run workflow** → select `main`. The runner executes
`python -m unittest discover -s tests -v`, which includes
`tests/test_worker_preflight.py` and `tests/test_verify_worker_preflight.py`.
The worker can also emit twenty individual temporary JSON records locally
for strict inspection with `tasks/verify_worker_preflight.py`.
The full unit suite is the hosted acceptance evidence. It is **not**
evidence of twenty separate cloud worker jobs.

The checks never start model inference, execute retrieved instructions,
deploy, run migrations or modify checked-out source. Normal GitHub Actions
baseline tests remain pinned and unchanged. No additional hosted runners
or paid CI services are necessary.

Legacy external CI scripts, configuration and local credentials are removed
from the active stack. Historical audit-only source fingerprints and Git
history remain to retain accurate reachable-history scanning, not runtime
integration.

Native OpenCode tool invocation and live production rollback acceptance
remain separate certification gates.
