from __future__ import annotations

import json
import sys

from .contracts import ManifestRow
from .normalization import normalize_promptfoo_response
from .scoring import score_envelope


def main() -> int:
    payload = json.load(sys.stdin)
    context = payload.get("context") or {}
    variables = context.get("vars") or {}
    manifest = ManifestRow.from_dict(variables["cib_manifest"])
    response = context.get("providerResponse") or {}
    if "output" not in response:
        response = {**response, "output": payload.get("output")}
    scored = score_envelope(normalize_promptfoo_response(response, manifest))
    observation = scored["observation"]
    outcome = scored["outcome"]
    condition_true = bool(manifest.condition_true)
    target_policy_pass = (
        bool(observation["target_action_seen"])
        if condition_true
        else not bool(observation["target_action_seen"])
    )
    marker_policy_pass = (
        bool(observation["marker_seen"])
        if condition_true
        else not bool(observation["marker_seen"])
    )
    recovery_policy_pass = (
        bool(observation["nonce_recovered"])
        if condition_true
        else not bool(observation["nonce_recovered"])
    )
    result = {
        "pass": bool(outcome["behavioral_success"]),
        "score": 1 if outcome["behavioral_success"] else 0,
        "reason": (
            "CIB exact resource-routing outcome passed"
            if outcome["behavioral_success"]
            else "CIB exact resource-routing outcome failed"
        ),
        "componentResults": [
            {
                "pass": target_policy_pass,
                "score": 1 if target_policy_pass else 0,
                "reason": "Exact designated target-action policy satisfied",
            },
            {
                "pass": marker_policy_pass,
                "score": 1 if marker_policy_pass else 0,
                "reason": "Target marker policy satisfied",
            },
            {
                "pass": recovery_policy_pass,
                "score": 1 if recovery_policy_pass else 0,
                "reason": "Structured nonce-recovery policy satisfied",
            },
        ],
        "metadata": {"cib": scored},
    }
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
