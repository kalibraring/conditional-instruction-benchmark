# Promptfoo research snapshot

## Scope and pin

Research was performed against Promptfoo's official documentation and repository
on 14 July 2026. The inspected repository snapshot is:

- commit: `25fedb61c2168c5a86e45e59fd2a001a2a043cf4`;
- reported package version: `0.121.18`;
- license: MIT;
- Node requirement: `^20.20.0 || >=22.22.0`.

Pin this commit or a released version selected during implementation. Do not
build the scientific record against an unpinned `latest` install.

## What Promptfoo does well

| Capability | Evidence | Migration use |
|---|---|---|
| Codex SDK provider | Supports working directory, sandbox, approval policy, model, structured output, minimal CLI environment, ephemeral threads, streamed items and deep tracing. | Preferred Codex backend after parity proof. |
| Codex app-server provider | Exposes richer app-server items, approvals, plugins, skills, connectors and thread metadata. Promptfoo itself recommends SDK for CI and app-server for rich-client behavior. | Separate adapter for product-surface studies; never silently mix with SDK rows. |
| Per-test provider overrides | The Codex provider merges prompt/test configuration over base provider configuration and renders variables before resolving `working_dir` and `cli_env`. | Lets one atomic test select one isolated fixture and Codex home without generating hundreds of provider definitions. |
| Lifecycle extensions | `beforeAll`, `beforeEach`, `afterEach`, and `afterAll` can create fixtures, enrich metadata, archive evidence, and clean up. `afterEach` cannot change success, score or response output. | Setup, teardown, evidence copying and audit metadata; scoring must remain an assertion or downstream analysis. |
| Custom deterministic assertions | JavaScript assertions receive output, test variables, full provider response, metadata and trace data and may return component results. | Port the exact target-action + marker + recovery scorer to a thin Promptfoo assertion adapter. |
| Trajectory assertions | Standard assertions cover tool use, tool arguments, step count and trace patterns. | Secondary diagnostics and cross-provider normalization, not the primary canary outcome. |
| Repetition and matrices | Supports variables, provider matrices and `--repeat`. | Useful for exploration. Confirmatory schedules should be generated explicitly by our randomizer rather than delegated to matrix/repeat expansion. |
| Execution operations | Concurrency limits, rate-limit scheduling, error filtering, range filtering, resume and retry workflows. | Replace the Python thread pool and ad hoc scheduling after failure semantics are pinned. |
| Output and UI | JSON, JSONL, CSV, YAML, HTML, JUnit, local database and web viewer. JSONL retains row and assertion details. | Standard transport, inspection, CI and large-run ergonomics. Our canonical normalized envelope remains separate. |
| Caching | Provider-aware disk cache with per-repeat namespaces and `--no-cache`. | Disable for scientific primary runs; allow only in development smoke tests. |
| Provider ecosystem | Agentic providers include Codex SDK/app-server, Claude Agent SDK and OpenCode SDK, plus custom JS, Python, HTTP and executable providers. | Adds target agents behind one orchestration surface while preserving adapter-specific evidence declarations. |

## What Promptfoo does not replace

Promptfoo is intentionally general. Its configuration does not supply:

- the logical recognition that IF and IFF encode different policies;
- the semantically matched expanded IF+ELSE-NOT control;
- separate Necessary Use and avoided Unnecessary Use estimands;
- task-family weighting or the planned cluster bootstrap and blocked
  randomization inference;
- our missingness and separate-recovery policy;
- a preregistered schedule or frozen claim boundary;
- proof that an exact designated resource executed.

Those remain benchmark responsibilities.

## Important caveats found in the source

### Codex `skill-used` is not sufficient

Promptfoo documents Codex `skill-used` as a heuristic inferred from successful
commands that directly reference a `SKILL.md` path. Wildcard reads are ignored,
and attempted and successful metadata can overlap under retries. This is useful
diagnostic evidence but cannot replace our target-specific canary. Claude and
OpenCode expose stronger first-class skill calls, but the experiment should
still score the designated action when the research question is operational
resource use.

### Promptfoo raw output is normalized, not identical to `codex exec --json`

The SDK provider returns aggregated SDK-compatible items, usage, metadata and
trace spans. Our direct backend retains the original CLI JSONL plus stderr. The
Promptfoo backend must therefore pass an evidence-parity gate. Provider output
must be archived before cleanup, and the normalizer must make lost or absent
fields explicit rather than fabricate parity.

### Recovery commands can mutate primary history

Promptfoo's resume function skips completed pairs and is valuable. Its retry
workflow can update an existing evaluation. That conflicts with the current
scientific rule that primary failures remain immutable and recovery runs are
separate sensitivity evidence. Scientific commands must wrap or prohibit
in-place retry.

### Caching is a validity risk

Promptfoo includes the prompt/configuration in provider cache keys and separates
repeat namespaces, but scientific trials need fresh agent calls. All primary,
recovery and confirmatory commands must force `--no-cache`. Cache-backed results
must carry a development-only status and never enter inference.

### Concurrency and retries are treatments unless controlled

Promptfoo can handle rate limits and scheduler retries. Those features improve
operations but may change latency, missingness and service-state dependence.
The run manifest must record concurrency, delay, provider `maxRetries`, and any
retry metadata. Primary-run defaults should avoid row replacement and treat
transport failures as observed failures until a separate recovery run.

### Sharing and configuration exports need privacy defaults

Promptfoo can create shareable results and warns that exported configuration may
contain non-secret environment values despite best-effort sanitization. The
benchmark default must be `--no-share`, minimal `cli_env`, local artifacts, and
an allowlist for metadata retained in the scientific envelope.

## Official sources

- [OpenAI Codex SDK provider](https://www.promptfoo.dev/docs/providers/openai-codex-sdk/)
- [OpenAI Codex app-server provider](https://www.promptfoo.dev/docs/providers/openai-codex-app-server/)
- [Tracing](https://www.promptfoo.dev/docs/tracing/)
- [Agent-skill testing guide](https://www.promptfoo.dev/docs/guides/test-agent-skills/)
- [Agent skills integration](https://www.promptfoo.dev/docs/integrations/agent-skill/)
- [Configuration reference and extension hooks](https://www.promptfoo.dev/docs/configuration/reference/)
- [Assertions](https://www.promptfoo.dev/docs/configuration/expected-outputs/)
- [Caching](https://www.promptfoo.dev/docs/configuration/caching/)
- [Output formats](https://www.promptfoo.dev/docs/configuration/outputs/)
- [Command line](https://www.promptfoo.dev/docs/usage/command-line/)
- [Promptfoo repository at the inspected commit](https://github.com/promptfoo/promptfoo/tree/25fedb61c2168c5a86e45e59fd2a001a2a043cf4)
