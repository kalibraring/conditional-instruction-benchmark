# Target architecture

## Principle

Promptfoo is an execution kernel, not the experiment designer or scientific
authority.

```text
Preregistration + protocol schema
              |
              v
 CIB trial generator and randomizer
              |
      frozen run manifest
              |
              v
 fixture renderer + nonce canaries
              |
              v
    execution-backend interface
       /             |             \
 direct Codex   Promptfoo Codex   Promptfoo other agents
  reference       SDK/app-server   Claude/OpenCode/...
       \             |             /
              v
       canonical evidence envelope
              |
       exact CIB canary scorer
              |
              v
 missingness policy + statistical analysis
              |
              v
       paper tables and claims
```

## Ownership boundary

| Responsibility | Owner | Reason |
|---|---|---|
| IF, IFF and IF+ELSE-NOT semantics | CIB core | Defines the causal treatment. |
| Case families and truth labels | CIB core | Defines ground truth. |
| Placement renderer | CIB core | Encodes progressive-disclosure surfaces consistently. |
| Replicate expansion and blocked randomization | CIB core | Must be frozen and auditable before execution. |
| Trial ID, nonce and fixture manifest | CIB core | Connects assignment to exact observable proof. |
| Provider invocation and concurrency | Promptfoo backend | Promptfoo has mature provider and scheduling infrastructure. |
| Native provider trace collection | Promptfoo backend | Avoid recreating each provider's event model. |
| Exact target-action scoring | CIB core through a Promptfoo assertion shim | The generic `skill-used` signal answers a weaker question. |
| Promptfoo pass/fail | Convenience projection | Useful for UI/CI; never the sole canonical result. |
| Canonical normalized evidence | CIB core | Preserves portability and prevents provider schema lock-in. |
| Wilson intervals, weighting, bootstrap and inference | CIB analysis | Scientific estimands must not depend on runner defaults. |
| Recovery-run handling | CIB protocol | Primary evidence must remain immutable. |

## Frozen run manifest

Generate one manifest before any model call. Each row contains:

```json
{
  "protocol_version": "cib/1",
  "run_id": "...",
  "trial_id": "...",
  "block_id": "...",
  "random_order": 17,
  "arm": "iff",
  "condition_true": false,
  "case_id": "realistic_imagegen",
  "case_variant": 0,
  "placement": "skill_description",
  "target_adapter": "promptfoo-codex-sdk",
  "target_version": "...",
  "model": "...",
  "reasoning_effort": "high",
  "fixture_id": "...",
  "fixture_hash": "...",
  "nonce_hash": "...",
  "is_primary": true
}
```

The full nonce belongs only in the isolated target fixture and protected raw
record, not in human-facing summaries.

## Per-trial Promptfoo mapping

The generator emits atomic JSONL tests rather than asking Promptfoo to create
the scientific factorial. Each test carries:

- the rendered task prompt as a variable;
- all treatment labels as metadata;
- a unique fixture directory;
- a unique HOME and CODEX_HOME;
- provider overrides under per-test options;
- the CIB canary assertion;
- secondary Promptfoo trace assertions for diagnostics.

Conceptual mapping:

```yaml
prompts:
  - id: cib-trial
    raw: '{{ rendered_prompt }}'

providers:
  - id: openai:codex-sdk
    config:
      sandbox_mode: read-only
      approval_policy: never
      persist_threads: false
      enable_streaming: true
      deep_tracing: true

tests: file://generated/tests.jsonl
```

Each generated test supplies `options.working_dir`,
`options.cli_env.CODEX_HOME`, model settings and output schema. The vertical
slice must prove that these values are rendered per row under concurrency.

## Canonical evidence envelope

All backends normalize into one versioned object:

```json
{
  "schema_version": "cib-evidence/1",
  "manifest": {},
  "execution": {
    "backend": "promptfoo-codex-sdk",
    "backend_version": "...",
    "provider_version": "...",
    "started_at": "...",
    "latency_seconds": 0,
    "exit_class": "completed",
    "attempt_count": 1,
    "cache_status": "disabled"
  },
  "response": {
    "final": {},
    "usage": {},
    "session_id": null
  },
  "evidence": {
    "raw_provider_response": {},
    "normalized_steps": [],
    "stdout": null,
    "stderr": null,
    "unavailable_fields": []
  },
  "observation": {
    "target_action_seen": false,
    "marker_seen": false,
    "nonce_recovered": false
  },
  "outcome": {
    "behavioral_success": false,
    "harness_failure": false
  },
  "provenance": {
    "fixture_hash": "...",
    "raw_hash": "...",
    "scorer_version": "..."
  }
}
```

Missing raw stderr in a provider must be represented as unavailable, not as an
empty successful stream.

## Adapter capability declaration

Every target adapter declares:

- instruction surfaces it can render;
- whether skills are preselected, implicitly selected or directly invoked;
- first-class versus heuristic skill events;
- exact target-action evidence available;
- filesystem and HOME isolation semantics;
- thread/process reuse semantics;
- provider retry and cache semantics;
- unsupported evidence fields.

Comparisons across target agents are permitted only for estimands supported by
both declarations. This prevents a Claude first-class skill call from being
silently treated as identical to a Codex `SKILL.md` read heuristic.

## Scientific run profile

Primary runs enforce:

- pinned CIB, Promptfoo, provider SDK, CLI and model identifiers;
- `--no-cache` and `--no-share`;
- explicit concurrency and delay;
- no persistent threads;
- one fixture, HOME and CODEX_HOME per trial;
- immutable JSONL plus per-trial canonical envelopes;
- no in-place retry of failed rows;
- separate recovery manifest and output directory;
- hashes of configs, fixtures, manifest and raw evidence.
