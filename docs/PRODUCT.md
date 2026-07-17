# Product definition

## Product promise

CIB helps agent builders discover whether small changes in conditional wording
change resource routing—and separate wording effects from accidental policy
changes or runner artifacts.

## Primary users and jobs

| User | Job | Evidence of value |
|---|---|---|
| Agent framework author | Choose reliable activation language for skills, docs, and tools | Reproducible necessary-use and avoided-unnecessary-use rates |
| Prompt or skill author | Test one instruction placement before rollout | Small frozen study with exact designated-resource evidence |
| Model provider or evaluator | Compare instruction-following behavior across surfaces or agents | Versioned portable manifest and evidence contract |
| Researcher | Run a defensible causal experiment rather than a prompt bake-off | Preregistered arms, controls, missingness, uncertainty, and claim boundaries |

## Positioning

CIB complements general evaluation engines. Promptfoo provides provider
integration, concurrency, filtering, outputs, and UI. CIB owns treatment
semantics, task generation, isolation, designated-resource canaries, canonical
scoring, inference, and scientific claims.

The alternative is not “CIB or Promptfoo.” The product is CIB's scientific
protocol running on Promptfoo or another declared execution backend.

## Activation journey

1. `cib doctor` proves the environment without spending model quota.
2. `cib plan` makes cost and assignments visible before execution.
3. A six-trial controlled smoke run proves isolation and evidence capture.
4. `cib report` turns only public and derived evidence into a self-contained
   scientific summary with explicit claim boundaries.
5. The user expands cases, placements, and repetitions deliberately.

## Product principles

- Make cost visible before calls.
- Make the canonical proof obvious.
- Refuse in-place reuse of scientific run directories.
- Keep protected evidence local by default.
- Separate behavioral failure from harness failure.
- Do not manufacture cross-agent equivalence.
- Prefer a small valid experiment over a large ambiguous run.

## Non-goals

- General red teaming, model grading, or prompt management.
- Proving that `IF AND ONLY IF` is universally better.
- Treating a skill-file read as sufficient evidence of operational use.
- Hiding stochasticity behind a single aggregate pass rate.
- Uploading private raw results or credentials to a hosted service.

## Success measures

Near-term product success means:

- a new user reaches a passing six-trial audit from the README;
- setup failures are diagnosed before model calls;
- every attempted trial has a durable raw record and canonical envelope;
- a completed smoke run produces a safe report without exposing protected
  evidence or requiring knowledge of the internal evidence tree;
- releases contain no private evidence or workstation-specific state;
- adapters declare unsupported fields and surfaces;
- issues distinguish setup, behavioral, protocol, and adapter defects.

The project will track release downloads, successful setup reports, issue time
to diagnosis, adapter coverage, and reproducibility reports. It will not collect
benchmark prompts or model outputs through product telemetry.

## Product source

This framing follows the service-product principle of solving a complete user
problem, iterating in small increments, protecting privacy, defining success,
and operating reliably: [GOV.UK Service Standard](https://www.gov.uk/service-manual/service-standard).
