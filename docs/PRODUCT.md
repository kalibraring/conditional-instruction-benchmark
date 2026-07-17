# Product definition

## Product promise

**Prove your AI agent did the thing—not just that it said it did.**

CIB gives agent builders operational evidence that a designated resource was
used when required and avoided when unnecessary. Its scientific engine then
separates wording effects from accidental policy changes or runner artifacts.

## Primary users and jobs

| User | Job | Evidence of value |
|---|---|---|
| Team shipping agent resources | Keep instruction changes from silently breaking routing | A CI verdict backed by exact designated-resource evidence |
| Prompt or skill author | Test one condition and placement before rollout | Required-use and avoided-unnecessary-use rates |
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

1. Copy `cib.example.yaml` and describe one routing condition, matched required
   and unnecessary cases, and pass/fail thresholds.
2. Run `cib check cib.yaml` locally or through the reusable GitHub Action.
3. Read the ten-second decision at the top of the report.
4. Inspect the collapsed scientific evidence when the decision needs diagnosis.
5. Expand cases and repetitions deliberately; use `doctor`, `plan`, `study`,
   and `report` directly only for advanced research workflows.

## Product principles

- Make cost visible before calls.
- Make the first useful path one command and one report.
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

- a new user reaches a passing six-trial check from the README with one command;
- a pull request can enforce declared thresholds with one reusable Action step;
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
