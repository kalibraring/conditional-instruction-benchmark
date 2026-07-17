# Conditional Instruction Benchmark

[![CI](https://github.com/kalibraring/conditional-instruction-benchmark/actions/workflows/ci.yml/badge.svg)](https://github.com/kalibraring/conditional-instruction-benchmark/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kalibraring/conditional-instruction-benchmark)](https://github.com/kalibraring/conditional-instruction-benchmark/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**Prove your AI agent did the thing—not just that it said it did.**

CIB is evidence-backed CI for agent instructions. Give it a routing condition,
matched prompts where a resource should and should not be used, and pass/fail
thresholds. One command runs isolated trials, verifies an exact nonce-bearing
action, and produces a merge-ready decision report.

```bash
cib check cib.yaml
```

The current product wedge validates Codex resource routing. It does not
automatically understand arbitrary existing skill files: CIB owns the isolated
canary resource while you own the condition and matched cases.

## What makes the proof stronger?

CIB does not grade a chat response that merely claims “I used the skill.” It
requires completed action evidence and exact recovery of a unique per-trial
nonce. It also checks the negative boundary: did the agent avoid the resource
when use was unnecessary?

The scientific engine beneath that product check measures whether small changes
in conditional wording change how coding agents route to designated resources.

It compares three causal arms—`IF`, `IF AND ONLY IF`, and an expanded
`IF + ELSE-NOT` control—across true and false conditions and across prompts,
`AGENTS.md`, skill descriptions, skill bodies, and referenced documents.

## Why use it?

General evaluation runners can execute prompts and assertions. CIB adds the
scientific layer needed to answer a narrower question defensibly:

- frozen randomized assignments before any model call;
- exact designated-resource canaries instead of heuristic “skill used” labels;
- one fixture, HOME, CODEX_HOME, nonce, and session per trial;
- separate necessary-use, avoided-unnecessary-use, behavioral-failure, and
  harness-failure outcomes;
- Promptfoo and direct Codex backends behind the same evidence contract;
- public manifests and protected raw evidence with fail-closed identity checks.

Status: **alpha**. Codex is the only validated target agent. The protocol and
adapters are designed for more agents, but unsupported surfaces stay explicit.

## Quick start: one command, one report

Requirements:

- Python 3.11 or newer;
- Node 22.22 or newer;
- npm 11.11.1, as pinned by `packageManager` in `package.json`;
- an installed and authenticated Codex CLI;
- `uv` for the documented development workflow.

```bash
git clone https://github.com/kalibraring/conditional-instruction-benchmark.git
cd conditional-instruction-benchmark
uv sync --frozen --group dev
npm ci
cp cib.example.yaml cib.yaml
uv run cib check cib.yaml
```

The example runs six agent calls: three internal wording policies across one
required and one unnecessary case. A passing check prints:

```text
PASS — The instruction met both routing thresholds.
Required use: 100.0% (minimum 100.0%)
Avoided unnecessary use: 100.0% (minimum 100.0%)
Harness failures: 0.0% (maximum 0.0%)
Evidence: smoke only
Report: report/report.html
```

The output directory contains one public decision and one safe report bundle:

```text
check-result.json             CI-readable verdict and thresholds
report/report.json            sanitized machine-readable evidence
report/report.md              portable decision report
report/report.html            self-contained ten-second report
```

Exit code `0` means the declared thresholds passed, `1` means valid evidence
failed a threshold, and `2` means the configuration, environment, execution, or
integrity evidence was invalid. One replicate is deliberately labeled
`smoke only`; it is not a general causal claim or a guarantee of future model
behavior.

Edit `cib.yaml` to describe your routing check. The complete schema and claim
boundary are in [the v0.4.0 product contract](docs/V0_4_0_PRODUCT_WEDGE.md).

## GitHub Action

Store a dedicated OpenAI API key as `OPENAI_API_KEY`, then add:

```yaml
name: Agent instruction check
on: [pull_request]

permissions:
  contents: read

jobs:
  cib:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: kalibraring/conditional-instruction-benchmark@v0.4.0
        with:
          config: cib.yaml
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
```

The action performs a non-interactive API-key login in an ephemeral Codex home,
runs the same `cib check` command, uploads only `check-result.json` and the safe
report directory, and fails the job for threshold or integrity failures. It
never uploads protected raw evidence, the private config copy, or authentication
material.

## Scientific workflow

The individual commands remain available for researchers and advanced users.
Preview a randomized six-trial design without making a model call:

```bash
uv run cib plan \
  --run-id smoke-plan-v1 \
  --case literal_flag \
  --placement prompt_start \
  --replicates 1 \
  --output-dir plans/smoke-plan-v1
```

Run and report it through the default Promptfoo Codex SDK backend:

```bash
uv run cib study \
  --run-id smoke-v1 \
  --case literal_flag \
  --placement prompt_start \
  --replicates 1 \
  --jobs 2
uv run cib report results/smoke-v1
```

The six-trial report is an onboarding and evidence-integrity smoke test. It
does not establish that one wording is generally superior.

Use the direct reference backend when you need a shadow run:

```bash
uv run cib study \
  --backend direct-codex \
  --run-id smoke-direct-v1 \
  --case literal_flag \
  --placement prompt_start \
  --replicates 1
```

## Commands

| Command | Use it for | Model calls |
|---|---|---:|
| `cib check` | Run one configured instruction check and emit a CI verdict | Yes |
| `cib doctor` | Prove local Python, Node, Codex, Promptfoo, and auth readiness | 0 |
| `cib plan` | Freeze and inspect a randomized manifest | 0 |
| `cib study` | Run a new immutable scientific study | Yes |
| `cib report` | Generate safe JSON, Markdown, and HTML study reports | 0 |
| `cib capabilities` | Inspect backend evidence and surface declarations | 0 |
| `cib analyze` | Analyze a completed compatible result directory | 0 |

Run `uv run cib <command> --help` for the complete options.

## Evidence layout

Every study writes a public manifest, a protected nonce-bearing manifest,
materialized fixture identities, per-trial isolated state, and an audit. A
Promptfoo study additionally writes:

```text
promptfoo/results.jsonl               portable Promptfoo projection
promptfoo/protected/raw/<id>.json     unsanitized provider archive
promptfoo/derived/evidence/<id>.json  canonical CIB envelope
promptfoo/derived/summary.json        canonical scored rows
promptfoo/derived/audit.json          completeness and disagreement proof
report/report.{json,md,html}          sanitized human-facing report
```

The protected archive is authoritative. Do not commit `results/`: it may contain
model output, synthetic nonces, absolute local paths, and auth symlinks. The
repository ignore rules and publication check block these paths from release.

## Method and validation

The Promptfoo backend passed a 24-trial isolation trap, a 144-trial operational
slice, archive re-scoring over 1,211 historical raw trials, and an exact frozen
shadow comparison against direct Codex. These were migration-validation runs,
not a new causal finding. See:

- [methodology and evidence gates](protocol/EVIDENCE_PARITY.md);
- [target architecture](architecture/TARGET_ARCHITECTURE.md);
- [sanitized migration evidence](evidence/migration-summary.json);
- [paper-style migration report](docs/MIGRATION_REPORT.md);
- [Promptfoo capability research](research/PROMPTFOO_RESEARCH.md).
- [v0.3.0 reporting contract](docs/V0_3_0_RESEARCH_READY.md).
- [v0.4.0 one-command product contract](docs/V0_4_0_PRODUCT_WEDGE.md).

## Product and project

- [Product definition](docs/PRODUCT.md)
- [Open-source readiness checklist](docs/OPEN_SOURCE_PROJECT.md)
- [Product-quality checklist](docs/PRODUCT_CHECKLIST.md)
- [Publication and release plan](docs/PUBLICATION_PLAN.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Support](SUPPORT.md)

## License and citation

CIB is available under the [MIT License](LICENSE). Use [CITATION.cff](CITATION.cff)
when citing the software or its methodology.
