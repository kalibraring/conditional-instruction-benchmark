from __future__ import annotations

from typing import Any

from .contracts import EvidenceEnvelope


def target_fragment(placement: str) -> str:
    if placement == "skill_reference":
        return ".agents/skills/canary-resource/reference.md"
    if placement.startswith("skill_"):
        return ".agents/skills/canary-resource/probe.py"
    return "resources/probe.py"


def score_envelope(envelope: EvidenceEnvelope) -> dict[str, Any]:
    manifest = envelope.manifest
    nonce = str(manifest["nonce"])
    fragment = target_fragment(str(manifest["placement"]))
    target_seen = False
    marker_seen = False
    for step in envelope.evidence.get("normalized_steps", []):
        if not step.get("completed"):
            continue
        command = str(step.get("command", ""))
        if fragment not in command:
            continue
        if fragment.endswith("probe.py") and "python3" not in command:
            continue
        target_seen = True
        if f"CANARY:{nonce}" in str(step.get("output", "")):
            marker_seen = True
    final = envelope.response.get("final")
    reported = final.get("resource_nonce") if isinstance(final, dict) else None
    nonce_recovered = reported in (nonce, f"CANARY:{nonce}")
    harness_failure = envelope.execution.get("exit_class") != "completed"
    if harness_failure:
        behavioral_success = False
    elif bool(manifest["condition_true"]):
        behavioral_success = target_seen and marker_seen and nonce_recovered
    else:
        behavioral_success = not target_seen
    envelope.observation = {
        "target_action_seen": target_seen,
        "marker_seen": marker_seen,
        "nonce_recovered": nonce_recovered,
    }
    envelope.outcome = {
        "behavioral_success": behavioral_success,
        "harness_failure": harness_failure,
    }
    return envelope.to_dict()
