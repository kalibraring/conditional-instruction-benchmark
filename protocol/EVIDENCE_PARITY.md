# Evidence-parity protocol

## Completion record

Gates A–E passed on 14 July 2026. Promptfoo is accepted as the default Codex
backend for new pilot studies; direct Codex remains the reference backend.

| Gate | Public evidence |
|---|---|
| A | Isolation counts in `evidence/migration-summary.json` |
| B | Archive-parity counts in `evidence/migration-summary.json` |
| C | `tests/test_normalization.py` and `tests/test_scoring.py` |
| D | Operational-slice counts in `evidence/migration-summary.json` |
| E | Shadow assignment and fixture-parity counts in `evidence/migration-summary.json` |

The raw gate records remain in the private research archive because they contain
model output, local paths, private manifests, and isolated runtime state. The
public summary contains only aggregate acceptance facts.

The acceptance concerns execution and evidence parity. It does not claim
row-level model-output equivalence or treat the 144-trial engineering slice as
a new scientific finding.

## Question

Can Promptfoo execute a CIB trial without changing assignment, isolation,
observable resource-use semantics, or failure classification?

The migration cannot answer this by comparing final pass rates alone.

## Gate A — configuration and fixture identity

For every generated trial:

1. the frozen manifest maps to exactly one Promptfoo row;
2. the Promptfoo row retains trial ID, block, arm, truth, case, variant and
   placement without coercion;
3. `working_dir`, HOME and CODEX_HOME are unique across concurrently running
   rows;
4. the target sees the fixture whose hash appears in the manifest;
5. the nonce appears only in the designated resource and protected scorer
   context;
6. cache and thread persistence are disabled.

Required proof: a concurrency test with at least 24 rows and deliberate nonce
cross-contamination traps. Zero cross-row reads are allowed.

## Gate B — scorer parity on archived evidence

Create a provider-independent observation layer. Run the new scorer against all
archived v0.1.0 direct-Codex raw traces and require exact agreement with the
published `target_resource_used`, `marker_executed`, `nonce_recovered`,
behavioral outcome and harness-failure labels.

This gate must include the four historical defect classes:

- `CANARY:<nonce>` normalization;
- nonce visible in an untargeted resource;
- `probe.py` read but not executed;
- subprocess timeout with a potentially surviving child.

Required proof: 100% label agreement or an adjudicated correction that triggers
a full rebuild of both old and new summaries.

## Gate C — Promptfoo trace sufficiency

Run synthetic fixtures that produce each relevant event:

- correct target execution and marker output;
- target read without execution;
- wrong resource executes the same-looking marker;
- target exits nonzero after printing;
- final response copies the nonce without target action;
- target action succeeds but final nonce recovery fails;
- tool/command starts and never completes;
- provider timeout and scheduler error.

The normalized Promptfoo evidence must distinguish every pair needed by the CIB
scorer. If the SDK provider omits a necessary fact, evaluate app-server or keep
the direct runner for that surface.

## Gate D — operational vertical slice

Run a balanced, randomized slice containing:

- all three wording arms;
- both truth states;
- prompt, AGENTS, description, body and reference stages;
- at least one controlled and one realistic family;
- at least two variants;
- at least two repetitions.

This is at least 144 trials for six surfaces. It is large enough to exercise
isolation and failure paths but remains a migration test, not a new scientific
result.

Acceptance requires:

- no duplicate or missing trial IDs;
- zero fixture or nonce contamination;
- raw evidence saved for every attempted row;
- harness failures separated from behavioral failures;
- recovery rows written to a different run;
- canonical summaries reproducible from raw evidence only;
- no unexplained scorer disagreement between Promptfoo UI status and CIB status.

## Gate E — shadow-backend comparison

Run the same frozen slice once through the direct backend and once through
Promptfoo. Model nondeterminism means row-level behavioral equality is not
required. Compare instead:

- assignment and fixture hashes: exact equality;
- evidence fields required by scoring: complete or explicitly unavailable;
- scorer behavior on synthetic equivalent traces: exact equality;
- harness-failure taxonomy: one-to-one mapping;
- aggregate outcomes: reported with uncertainty, not used as a parity oracle;
- latency/token/retry changes: documented as backend effects.

## Cutover rule

Promptfoo becomes the default Codex execution backend only when Gates A–E pass.
The direct backend remains available for reference runs and for surfaces whose
evidence declaration Promptfoo cannot satisfy. Removing it requires a separate
decision after at least one full reproducible study succeeds on the new backend.
