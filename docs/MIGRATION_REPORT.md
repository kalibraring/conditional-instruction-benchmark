# A dual-backend scientific runner for conditional-instruction experiments

## Abstract

We tested whether Promptfoo can replace the operational runner of the
Conditional Instruction Benchmark without replacing its causal methodology.
The migration retained frozen three-arm assignments, per-trial nonce canaries,
isolated fixtures, exact designated-resource scoring, canonical evidence, and
separate harness/behavioral outcomes. Promptfoo executed a 24-trial isolation
test, a 12-trial behavioral slice, and a balanced 144-trial parity slice with
zero missing evidence, duplicate IDs, session reuse, harness failures, or
Promptfoo/CIB scoring disagreements. The same frozen 144 assignments then ran
through direct Codex with exact assignment and fixture-hash parity. Aggregate
behavior differed by seven successes, all in a realistic image-generation
family; with two repetitions per cell and independent stochastic calls, this is
reported as run-to-run variation rather than a backend effect. We accept
Promptfoo as the default operational backend for new Codex pilots while
retaining direct Codex as the scientific reference backend.

## Research question

Can Promptfoo execute CIB trials without changing assignment, isolation,
observable designated-resource use, failure classification, or the authority
of the scientific protocol?

The experiment did not ask whether both backends produce identical model
answers. Independent agent calls are nondeterministic, so row-level behavioral
equality is not an evidence-parity requirement.

## Design

The benchmark generated every atomic trial before execution. Each assignment
fixed the arm (`IF`, `IFF`, or expanded `IF+ELSE-NOT`), truth state, task family,
placement, repetition, random order, model, reasoning effort, and nonce hash.
Public manifests omit the nonce. Private manifests and raw evidence retain it.

Promptfoo received atomic JSONL tests rather than generating the factorial. A
test carried a unique git fixture, HOME, CODEX_HOME, model configuration,
structured-output schema, and exact CIB assertion. Scientific runs disabled
cache, sharing, thread persistence, plugins, and write access. An `afterEach`
extension archived each unsanitized provider response before normalization.

Both backends normalized into `cib-evidence/1`. The same Python scorer required
the exact target command, its exact `CANARY:<nonce>` output, and nonce recovery
for true conditions; false conditions succeeded only when the target action was
absent. Provider or scheduler errors remained harness failures rather than
behavioral failures.

## Evidence gates

| Gate | Proof | Result |
|---|---|---|
| A: isolation | 24 concurrent true-case traps with unique fixtures, homes, nonces, and sessions | 24/24 rows and archives; zero contamination or scorer disagreement |
| B: archive parity | Re-score the immutable v0.1.0 archive | 1,211/1,211 raw trials checked; zero unadjudicated published-summary disagreements |
| C: trace sufficiency | Synthetic correct, read-only, wrong-resource, nonzero, copied-nonce, missing-recovery, incomplete, timeout, and scheduler cases | All scorer-required distinctions retained; deterministic adapter tests pass |
| D: operational slice | Six surfaces × three arms × two truths × two families × two repetitions | 144/144 rows and protected archives; 144 unique sessions; zero harness or scorer disagreements |
| E: shadow backend | Same frozen 144 assignments through both backends | Exact trial, assignment, nonce-hash, and fixture-hash parity; zero harness failures |

Gate B found 428 raw files with stale embedded convenience fields. Published
summaries, not those cached fields, were the historical authority. One published
row was explicitly adjudicated: its old summary predated support for the
`CANARY:<nonce>` recovery form, and the historical causal rerun had passed.

## Results

The controlled `literal_flag` family succeeded in all 72 trials on both
backends. The realistic `imagegen` family succeeded in 55/72 Promptfoo trials
and 62/72 direct trials.

| Backend | Successes | Rate | Wilson 95% interval | Harness failures |
|---|---:|---:|---:|---:|
| Promptfoo Codex SDK | 127/144 | 88.2% | 81.9%–92.5% | 0 |
| Direct Codex CLI | 134/144 | 93.1% | 87.7%–96.2% | 0 |

Seven of 72 task-by-placement-by-arm-by-truth cells differed, each by one of two
repetitions and each in the realistic family. All differences favored the
direct run. This comparison cannot identify a backend effect: backend order was
not randomized as a treatment, calls were independent, and each cell had only
two repetitions. The migration therefore uses contract and evidence parity as
its acceptance criterion and reports aggregate behavior as diagnostic context.

The final one-command verification also passed:

| Command path | Trials | Behavioral successes | Evidence audit | Duration |
|---|---:|---:|---:|---:|
| `cib study` default Promptfoo backend | 6 | 6 | Passed | 43 s |
| `cib study --backend direct-codex` | 6 | 6 | Passed | 35 s |

## Defects found by the migration

The vertical slices found and fixed four integration defects before cutover:

1. Promptfoo exposed the Codex SDK raw payload as a JSON string in one response
   path; the normalizer now accepts either a mapping or serialized mapping.
2. Promptfoo's export sanitizer altered some descriptive trial IDs; future IDs
   are opaque assignment hashes, and protected per-trial archives are the
   canonical join source.
3. A provider assertion error string was initially classified as a provider
   execution error; classification now uses structured response state.
4. Unscoped pytest collection entered copied plugin caches under `results/`;
   project configuration now limits collection to `tests/` and declares its
   test runtime explicitly.

## Decision and boundaries

Promptfoo becomes the default backend for new Codex pilot studies because it
passed Gates A–E and supplies provider integration, concurrency, output formats,
UI, filtering, and future provider reach. CIB remains authoritative for the
causal design, trial generation, isolation, exact scorer, missingness policy,
statistical analysis, recovery policy, and paper claims.

Direct Codex remains available as the reference backend. Promptfoo's generic
retry/resume commands remain outside the scientific workflow because they can
mutate primary history. Recovery must use a new run ID, manifest, and directory.
The migration runs are engineering validation and must not be pooled with the
v0.1.0 study.

## Expansion rule

A new agent adapter must declare its supported instruction surfaces, skill
selection semantics, exact action evidence, isolation guarantees, thread and
cache behavior, and unavailable evidence. It must then pass synthetic evidence,
isolation, operational-slice, and frozen shadow gates. Unsupported surfaces stay
explicitly unsupported; the framework must not manufacture symmetry between
Codex, Claude, OpenCode, or future agents.

## Reproducibility record

- CIB `0.2.0`
- Promptfoo `0.121.18`
- OpenAI Codex SDK `0.144.1`
- Codex CLI `0.144.1`
- Node `25.8.2`
- npm `11.11.1`
- Python requirement `>=3.11`; verification used the uv-managed environment
- Public release verification: 25 tests passed

The public repository contains the sanitized aggregate acceptance record in
`evidence/migration-summary.json`. Raw provider records, private manifests,
canonical per-trial envelopes, and local runtime state remain in the private
research archive and are intentionally excluded from publication.
