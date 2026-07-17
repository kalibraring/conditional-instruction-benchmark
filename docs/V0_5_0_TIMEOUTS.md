# v0.5.0 timeout and migration contract

## Required behavior

`cib-check/2` separates two different failure boundaries:

- `trial_timeout_seconds` limits one agent trial;
- `study_timeout_seconds` limits the complete randomized study.

Both values are required positive integers. The study limit may be lower than
the trial limit; whichever deadline arrives first controls the affected trial.
A per-trial timeout is a harness failure that participates in the configured
harness-failure threshold. A whole-study timeout makes the evidence `INVALID`
because the randomized design did not complete within its declared boundary.

```yaml
schema_version: cib-check/2
execution:
  backend: promptfoo-codex-sdk
  model: gpt-5.6-sol
  reasoning_effort: medium
  repetitions: 1
  jobs: 2
  seed: 20260717
  trial_timeout_seconds: 300
  study_timeout_seconds: 960
```

## Backend enforcement

The Promptfoo backend writes `timeoutMs` and `maxEvalTimeMs` into
`evaluateOptions`. CIB also keeps a process-group watchdog 30 seconds beyond
the declared study limit so Promptfoo can finish its own timeout rows and
cleanup first.

The direct Codex backend uses one monotonic study deadline shared by every
worker. It stops launching queued trials after that deadline, terminates running
process groups, and writes one fail-closed raw and summary row for every trial
that did not start.

Reports record both declared limits, how the backend enforced them, the timeout
scope, and the exact affected trial IDs. Promptfoo timeout rows that bypass its
normal `afterEach` hook are archived by CIB before normalization.

## Migration from `cib-check/1`

Existing `cib-check/1` files remain valid in v0.5.0. Their `timeout_seconds`
field keeps its previous meaning exactly:

| Backend | `cib-check/1` meaning |
|---|---|
| `promptfoo-codex-sdk` | whole-study process watchdog only |
| `direct-codex` | per-trial timeout only |

CIB prints a deprecation warning for these files. It does not silently reinterpret
the old field. Migrate by changing the schema to `cib-check/2`, replacing
`timeout_seconds` with both explicit fields, and choosing a study budget that
covers all expected concurrency batches plus cleanup.

`cib doctor --config cib.yaml` validates the same schema without model calls and
prints the resolved trial limit, study limit, metadata source, and any legacy
warning. `cib check` and the GitHub Action consume that same resolution.

The deprecated scientific CLI `--timeout` follows the same backend-dependent
mapping. New runs should use `--trial-timeout-seconds` and
`--study-timeout-seconds`. When the new CLI omits the study limit, CIB derives a
conservative limit from the trial count, concurrency, trial limit, and cleanup
allowance and records that source in execution metadata.

## Acceptance proof

- A multi-batch study may exceed one trial limit in total while every trial
  remains within its own limit.
- A hung trial is terminated with its process group and cannot leak a child.
- A whole-study watchdog still bounds runaway execution.
- Every canonical report distinguishes trial timeouts from study timeouts.
- Legacy behavior and warnings are covered by compatibility tests.
