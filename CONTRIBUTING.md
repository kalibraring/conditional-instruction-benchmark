# Contributing

Thank you for helping improve CIB. Small, evidence-backed changes are easiest to
review and safest for the benchmark's scientific contract.

## Before opening a change

Use an issue first when you want to change treatment semantics, scoring,
missingness policy, evidence schemas, supported agent surfaces, or published
claims. Bug fixes, documentation corrections, and focused test improvements can
go directly to a pull request.

## Setup

```bash
git clone https://github.com/kalibraring/conditional-instruction-benchmark.git
cd conditional-instruction-benchmark
uv sync --frozen --group dev
npm ci
uv run cib doctor
```

`cib doctor` requires Codex auth because it proves readiness for behavioral
runs. Unit tests and publication checks do not require model access.

## Development workflow

1. Define the behavior your change must preserve or create.
2. Add or update the narrowest deterministic test.
3. Run that test directly.
4. Run the repository proof before opening a pull request:

```bash
uv run python -m pytest -q
uv run python scripts/publication_check.py
uv build
npm run verify
```

5. Run a behavioral study only when deterministic tests cannot prove the agent
   behavior. Put it under a fresh run ID and never commit its `results/` tree.

## Scientific compatibility

Changes must preserve these boundaries unless an accepted design issue changes
the protocol deliberately:

- CIB owns treatment construction, manifests, isolation, scoring, inference,
  recovery policy, and claims.
- Execution adapters own provider invocation and trace collection.
- Public manifests never contain a raw nonce.
- Primary evidence is immutable; recovery uses a new run and directory.
- Unsupported agent surfaces remain unsupported rather than approximated.
- Promptfoo UI status is a projection; canonical CIB evidence is authoritative.

Schema or outcome changes require a version bump, migration notes, and archive
parity evidence.

## Pull requests

Explain:

- the behavior that changed;
- why it should change;
- the proof you ran;
- any effect on compatibility, cost, privacy, or scientific claims.

Do not include credentials, raw study evidence, absolute workstation paths,
private manifests, generated homes, or copied dependency trees. Contributions
are accepted under the repository's MIT License.
