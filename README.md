# Conditional Instruction Benchmark

[![CI](https://github.com/kalibraring/conditional-instruction-benchmark/actions/workflows/ci.yml/badge.svg)](https://github.com/kalibraring/conditional-instruction-benchmark/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kalibraring/conditional-instruction-benchmark)](https://github.com/kalibraring/conditional-instruction-benchmark/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

CIB measures whether small changes in conditional wording change how coding
agents route to designated resources.

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

## Quick start

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
uv run cib doctor
```

Preview a randomized six-trial design without making a model call:

```bash
uv run cib plan \
  --run-id smoke-plan-v1 \
  --case literal_flag \
  --placement prompt_start \
  --replicates 1 \
  --output-dir plans/smoke-plan-v1
```

Run it through the default Promptfoo Codex SDK backend:

```bash
uv run cib study \
  --run-id smoke-v1 \
  --case literal_flag \
  --placement prompt_start \
  --replicates 1 \
  --jobs 2
```

This smoke design makes six agent calls: three wording arms × two truth states.
It can consume paid model quota. A successful run writes
`results/smoke-v1/study-result.json` with `audit.passed: true`.

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
| `cib doctor` | Prove local Python, Node, Codex, Promptfoo, and auth readiness | 0 |
| `cib plan` | Freeze and inspect a randomized manifest | 0 |
| `cib study` | Run a new immutable scientific study | Yes |
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
