# v0.3.0 research-ready tracer bullet

## User outcome

A new user can follow the public CLI journey
`doctor -> plan -> study -> report` and obtain a self-contained Markdown and
HTML report from a six-trial controlled study without understanding CIB's
internal evidence layout.

## Public seam

The acceptance seam is the installed `cib` command and the files it creates.
Tests may replace a model provider only at the execution-backend boundary; they
must not assert private implementation calls.

## Required behavior

1. `cib report RUN_DIR` reads the frozen public manifest, canonical derived
   summary, integrity audit, and study result.
2. It writes `report.json`, `report.md`, and a self-contained `report.html` to
   a new report directory.
3. The report includes run configuration, integrity status, necessary-use and
   avoided-unnecessary-use rates by arm, Wilson intervals, descriptive
   task-family-weighted contrasts, and explicit claim boundaries.
4. It verifies exact trial identity between the public manifest and derived
   summary before writing anything.
5. It never opens private manifests or protected raw responses. From the
   required public and derived inputs, it never reproduces nonces, session
   identifiers, provider transcripts, credentials, or absolute workstation
   paths in report files or CLI output.
6. It refuses to replace an existing report directory.
7. The README documents the complete six-trial path and identifies the report
   files that prove success.

## Claim boundary

The six-trial report is an onboarding and evidence-integrity smoke test. With
one task family and one replicate per arm/truth cell, it is not confirmatory
evidence that one wording is generally superior. Reports without an attached
preregistration remain descriptive regardless of trial count.

## Proof

- A subprocess test drives `cib report` through its public CLI.
- Known fixture outcomes produce independently specified rates and contrasts.
- Canary secrets, session IDs, and an injected absolute path are absent from
  every generated report.
- Identity mismatch and output-directory reuse fail closed.
- The full deterministic suite, package build, publication scan, and hosted CI
  pass before release.
