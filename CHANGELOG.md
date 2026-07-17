# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
the project uses [Semantic Versioning](https://semver.org/) within its pre-1.0
compatibility boundary.

## [Unreleased]

### Planned

- Separate recovery-run command and development profile.
- First non-Codex adapter capability spike.

## [0.5.2] - 2026-07-18

### Added

- Copy one bounded, fresh signed-format cloud-config cache snapshot into each
  isolated trial as a private 0600 file, with safe digest/freshness provenance.
- Accept an explicit private cache source and minimum-validity window for frozen
  scientific protocols.
- Hash-seal Promptfoo configuration and test ledgers around execution.

### Fixed

- Recover Promptfoo-redacted per-trial timeout assignments only through a
  complete, unique, index-consistent frozen test ledger.
- Distinguish pre-session transport failures from evaluation timeouts.
- Require sessions for completed trials, permit typed sessionless harness
  failures, and reject duplicate sessions across all observed trials.
- Preserve ledger-recovered timeout evidence separately from original protected
  archives instead of synthesizing provenance.
- Include untracked, non-ignored files in the pre-publication secret and
  workstation-path scan.

## [0.5.1] - 2026-07-18

### Fixed

- Give every Promptfoo-backed run its own state directory so concurrent CIB
  processes cannot contend for the same SQLite database.
- Pin the canary assertion bridge to the Python interpreter running CIB, rather
  than an unrelated system `python3` that may not have CIB installed.
- Disable Promptfoo telemetry for deterministic benchmark execution while
  preserving its explicit JSONL evidence export.

## [0.5.0] - 2026-07-17

### Added

- Add explicit per-trial and whole-study limits through `cib-check/2`, the
  scientific CLI, execution metadata, and human-readable reports.
- Add Promptfoo-native per-evaluation and maximum-study limits plus a final
  process-group watchdog.
- Add a shared monotonic study deadline to the direct Codex backend, including
  complete fail-closed evidence for trials that never start.
- Add auditable timeout attribution for trial and study scope.

### Changed

- Preserve `cib-check/1` and `--timeout` with their exact backend-dependent
  legacy behavior, but emit a migration warning.
- Classify any whole-study timeout as invalid evidence rather than a behavioral
  threshold failure.

## [0.4.0] - 2026-07-17

### Added

- Add strict `cib.yaml` configuration and one-command `cib check` execution with
  CI-compatible `PASS`, `FAIL`, and `INVALID` exit behavior.
- Add a ten-second decision above the detailed scientific Markdown and HTML
  reports while preserving public/private evidence boundaries.
- Add a reusable least-privilege GitHub Action with pinned dependencies, scoped
  Codex API-key authentication, safe artifact upload, and a quota-free hosted
  self-test.
- Add the v0.4.0 product contract and a copyable example configuration.

### Changed

- Lead the README and product strategy with the developer outcome; retain the
  multi-command experiment workflow as the advanced path.

## [0.3.0] - 2026-07-17

### Added

- Add `cib report` for deterministic, self-contained JSON, Markdown, and HTML
  reports with integrity checks, claim boundaries, Wilson intervals, and
  task-family-weighted descriptive contrasts.
- Document the v0.3.0 research-ready CLI tracer bullet and complete six-trial
  onboarding path.

## [0.2.1] - 2026-07-17

### Fixed

- Align contributors and CI on the npm 11.11.1 lockfile toolchain used by
  dependency automation.

### Changed

- Update the validated Codex SDK to 0.144.5 and Promptfoo to 0.121.19.

## [0.2.0] - 2026-07-17

### Added

- Promptfoo Codex SDK and direct Codex execution backends.
- Frozen public/private manifests and per-trial isolation.
- Versioned canonical evidence envelopes and exact canary scoring.
- Protected Promptfoo response archiving and fail-closed normalization.
- Backend capability declarations, `cib doctor`, `cib plan`, and `cib study`.
- Community, security, product, release, and reproducibility documentation.

### Validated

- Re-scored 1,211 historical raw trials with no unadjudicated published-summary
  disagreement.
- Passed a 24-trial isolation trap and a 144-trial Promptfoo operational slice.
- Passed exact assignment and fixture parity against a frozen direct-Codex
  shadow run.

[Unreleased]: https://github.com/kalibraring/conditional-instruction-benchmark/compare/v0.5.2...HEAD
[0.5.2]: https://github.com/kalibraring/conditional-instruction-benchmark/releases/tag/v0.5.2
[0.5.1]: https://github.com/kalibraring/conditional-instruction-benchmark/releases/tag/v0.5.1
[0.5.0]: https://github.com/kalibraring/conditional-instruction-benchmark/releases/tag/v0.5.0
[0.4.0]: https://github.com/kalibraring/conditional-instruction-benchmark/releases/tag/v0.4.0
[0.3.0]: https://github.com/kalibraring/conditional-instruction-benchmark/releases/tag/v0.3.0
[0.2.1]: https://github.com/kalibraring/conditional-instruction-benchmark/releases/tag/v0.2.1
[0.2.0]: https://github.com/kalibraring/conditional-instruction-benchmark/releases/tag/v0.2.0
