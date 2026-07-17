# Product-quality checklist

Open source makes the code available. Product work makes the outcome usable and
worth returning to.

## Problem and audience

- [x] Name the user, their decision, and why a general eval runner is
  insufficient.
- [x] State non-goals and the alpha claim boundary.
- [x] Keep Codex-only validation explicit while preserving an adapter path.

## First-run experience

- [x] Diagnose prerequisites before model calls with `cib doctor`.
- [x] Preview trial count and assignments with `cib plan`.
- [x] Provide one six-call smoke study and name its passing artifact.
- [x] Generate self-contained JSON, Markdown, and HTML reports from public and
  derived evidence only.
- [x] Explain cost and protected-data behavior before execution.
- [ ] Add a synthetic no-provider demo that renders a complete sample report.

## Core reliability

- [x] Freeze assignments and refuse run-directory reuse.
- [x] Isolate filesystem, HOME, CODEX_HOME, nonce, and session per trial.
- [x] Archive raw evidence before normalization and cleanup.
- [x] Fail closed on identity, nonce-hash, missing-row, and scorer disagreement.
- [ ] Add a first-class separate recovery workflow.
- [ ] Add interruption-safe resume that never mutates primary evidence.

## Trust and privacy

- [x] Keep raw evidence local by default and disable Promptfoo sharing.
- [x] Document auth-link, model-output, nonce, and local-path risks.
- [x] Publish only sanitized aggregate validation evidence.
- [x] Provide private vulnerability reporting.
- [ ] Add an explicit retention/deletion helper for local study directories.

## Distribution and operations

- [x] Publish source, wheel, source distribution, checksums, and an annotated
  Git tag.
- [x] Automate CI and GitHub release creation from version-matched tags.
- [x] Pin Promptfoo and Codex SDK versions.
- [ ] Register PyPI Trusted Publishing with manual environment approval.
- [ ] Add artifact attestations and an SPDX SBOM.
- [ ] Define supported Promptfoo/Codex version windows after more releases.

## Learning loop

- [x] Route product, protocol, and adapter proposals separately.
- [x] Define activation, reproducibility, diagnosis, and adapter-coverage
  measures without collecting user model output.
- [ ] Run README onboarding with an external user.
- [ ] Publish a preregistered follow-up study using the public release.
