# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
the project uses [Semantic Versioning](https://semver.org/) within its pre-1.0
compatibility boundary.

## [Unreleased]

### Planned

- Separate recovery-run command and development profile.
- First non-Codex adapter capability spike.

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

[Unreleased]: https://github.com/kalibraring/conditional-instruction-benchmark/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/kalibraring/conditional-instruction-benchmark/releases/tag/v0.2.1
[0.2.0]: https://github.com/kalibraring/conditional-instruction-benchmark/releases/tag/v0.2.0
