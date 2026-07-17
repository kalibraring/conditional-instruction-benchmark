from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AdapterCapability:
    adapter_id: str
    instruction_surfaces: tuple[str, ...]
    exact_action_evidence: str
    filesystem_isolation: str
    thread_reuse: str
    cache_control: str
    unavailable_evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SURFACES = (
    "prompt_start",
    "prompt_end",
    "root_agents",
    "skill_description",
    "skill_body",
    "skill_reference",
)


CAPABILITIES = {
    "direct-codex": AdapterCapability(
        adapter_id="direct-codex",
        instruction_surfaces=SURFACES,
        exact_action_evidence="completed Codex CLI command event plus exact canary output",
        filesystem_isolation="unique git fixture, HOME, and CODEX_HOME per trial",
        thread_reuse="ephemeral; disabled",
        cache_control="direct invocation; no benchmark cache",
        unavailable_evidence=("aggregated stdout outside command events",),
    ),
    "promptfoo-codex-sdk": AdapterCapability(
        adapter_id="promptfoo-codex-sdk",
        instruction_surfaces=SURFACES,
        exact_action_evidence="completed Codex SDK command_execution item plus exact canary output",
        filesystem_isolation="unique git fixture, HOME, and CODEX_HOME per atomic test",
        thread_reuse="persist_threads false; unique observed session per trial",
        cache_control="--no-cache and per-test bustCache in scientific profile",
        unavailable_evidence=("provider process stdout", "provider process stderr"),
    ),
}


def capability(adapter_id: str) -> AdapterCapability:
    try:
        return CAPABILITIES[adapter_id]
    except KeyError as error:
        raise ValueError(f"Unknown adapter: {adapter_id}") from error
