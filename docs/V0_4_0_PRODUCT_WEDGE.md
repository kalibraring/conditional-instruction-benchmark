# v0.4.0 one-command product wedge

## Product sentence

Prove your AI agent did the thing—not just that it said it did.

For this release, “the thing” is exact operational use of a CIB-instrumented
Codex resource under a user-supplied routing condition. CIB proves the action
with an isolated nonce canary and completed command evidence.

## User outcome

A developer writes one `cib.yaml` file and runs:

```bash
cib check cib.yaml
```

CIB validates the environment, freezes the study, executes it, scores exact
resource use, applies declared thresholds, writes one report, and exits with a
CI-compatible status. The developer does not need to call `doctor`, `plan`,
`study`, or `report` separately.

## Public seams

The acceptance seams are:

1. the installed `cib check CONFIG` command, its exit status, and its generated
   artifacts;
2. the repository-root `action.yml` interface used from GitHub Actions.

Tests may replace Codex only at the external execution boundary. They must not
assert private implementation calls.

## Configuration contract

`cib.yaml` declares:

- schema version and a safe check name;
- the routing condition, instruction placement, and selected wording policy;
- matched prompts where resource use is required and unnecessary;
- backend, model, reasoning, repetition, concurrency, seed, and timeout;
- minimum required-use rate, minimum avoided-unnecessary-use rate, and maximum
  harness-failure rate.

The first schema supports one Codex routing condition. CIB owns the isolated
canary resource and treatment rendering; user prompts remain in protected local
study state and are not copied into the public report.

## Decision contract

The selected policy passes only when:

- the integrity audit passes;
- its necessary-use rate meets the configured minimum;
- its avoided-unnecessary-use rate meets the configured minimum;
- the total harness-failure rate does not exceed the configured maximum.

The top of every report contains a ten-second decision with:

- `PASS`, `FAIL`, or `INVALID`;
- a plain-language headline;
- required-use and avoided-unnecessary-use rates with thresholds;
- evidence-integrity and harness-failure status;
- an explicit evidence-strength label.

One replicate per cell is a smoke check. Passing configured thresholds is not a
general causal claim and does not prove future model behavior.

## Required behavior

1. `cib check` fails before model calls when configuration or environment
   validation fails.
2. It refuses to reuse an output directory.
3. It materializes every matched positive/negative prompt for all three
   scientific arms. Behavioral routing thresholds apply only to the selected
   policy; the harness-failure threshold covers all mandatory arms.
4. It preserves the v0.3 isolation, nonce, canonical scoring, and protected-raw
   evidence boundaries.
5. It writes `check-result.json` and `report/report.{json,md,html}`.
6. Public output contains no prompts, nonces, sessions, provider transcripts,
   credentials, auth content, or absolute workstation paths.
7. Exit code `0` means thresholds passed; exit code `1` means valid evidence
   failed thresholds; exit code `2` means invalid configuration, environment,
   execution, or integrity evidence.
8. The GitHub Action runs the same installed CLI, exposes the verdict and report
   path as outputs, and uploads the safe report directory even when thresholds
   fail.

## Non-goals

- Automatically understanding or rewriting an arbitrary existing skill file.
- Claiming that one six-cell smoke proves a stable causal effect.
- Comparing base and head revisions in v0.4.0.
- Adding another target agent or execution backend.
- Uploading protected raw evidence or authentication material.

## Proof

- A subprocess acceptance test drives `cib check` with a fake Codex executable
  at the provider boundary and independently specified outcomes.
- Failure fixtures prove threshold, malformed-config, output-reuse, privacy,
  and invalid-execution exit behavior.
- Report tests prove the decision is identical across JSON, Markdown, and HTML.
- Action metadata tests prove the public inputs, outputs, pinned dependencies,
  CLI invocation, and safe artifact upload.
- A built wheel, fresh clone, publication scan, hosted CI, and one real
  six-trial check with valid evidence integrity complete before release. The
  behavioral verdict may pass or fail and is reported without selection.
