from __future__ import annotations

import hashlib
import json
from typing import Any

from .contracts import EvidenceEnvelope, ManifestRow


def _parse_final(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _step_from_item(item: dict[str, Any], completed: bool = True) -> dict[str, Any] | None:
    if item.get("type") != "command_execution":
        return None
    command = item.get("command")
    command_text = (
        command
        if isinstance(command, str)
        else " ".join(str(part) for part in (command or []))
    )
    return {
        "kind": "command",
        "command": command_text,
        "output": item.get("aggregated_output"),
        "exit_code": item.get("exit_code"),
        "status": item.get("status"),
        "completed": completed,
    }


def normalize_direct_raw(
    raw: dict[str, Any], manifest: ManifestRow
) -> EvidenceEnvelope:
    steps: list[dict[str, Any]] = []
    for event in raw.get("events", []):
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if isinstance(item, dict):
            step = _step_from_item(item, completed=True)
            if step:
                steps.append(step)
    raw_hash = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    exit_code = int(raw.get("exit_code", 1))
    timed_out = bool(raw.get("timed_out", False))
    return EvidenceEnvelope(
        manifest=manifest.to_private_dict(),
        execution={
            "backend": "direct-codex",
            "exit_class": "timeout" if timed_out else ("completed" if exit_code == 0 else "error"),
            "exit_code": exit_code,
            "latency_seconds": raw.get("latency_seconds"),
            "attempt_count": 1,
            "cache_status": "disabled",
        },
        response={
            "final": raw.get("final_response"),
            "usage": raw.get("usage"),
            "session_id": None,
        },
        evidence={
            "raw_provider_response": raw,
            "normalized_steps": steps,
            "stdout": None,
            "stderr": raw.get("stderr", ""),
            "unavailable_fields": ["stdout"],
        },
        observation={},
        outcome={},
        provenance={"raw_hash": raw_hash, "scorer_version": "cib/0.2.0"},
    )


def normalize_promptfoo_response(
    provider_response: dict[str, Any], manifest: ManifestRow
) -> EvidenceEnvelope:
    raw = provider_response.get("raw")
    if isinstance(raw, dict):
        raw_dict = raw
    elif isinstance(raw, str):
        try:
            parsed_raw = json.loads(raw)
        except json.JSONDecodeError:
            parsed_raw = {}
        raw_dict = parsed_raw if isinstance(parsed_raw, dict) else {}
    else:
        raw_dict = {}
    items = raw_dict.get("items")
    steps = [
        step
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
        for step in [_step_from_item(item, completed=item.get("status") not in ("in_progress", "started"))]
        if step is not None
    ]
    error = provider_response.get("error")
    raw_hash = hashlib.sha256(
        json.dumps(provider_response, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
    metadata = provider_response.get("metadata")
    metadata_dict = metadata if isinstance(metadata, dict) else {}
    return EvidenceEnvelope(
        manifest=manifest.to_private_dict(),
        execution={
            "backend": "promptfoo-codex-sdk",
            "exit_class": "error" if error else "completed",
            "exit_code": None,
            "latency_seconds": provider_response.get("latencyMs", 0) / 1000
            if isinstance(provider_response.get("latencyMs"), (int, float))
            else None,
            "attempt_count": metadata_dict.get("attemptCount", 1),
            "cache_status": "hit" if provider_response.get("cached") else "disabled",
        },
        response={
            "final": _parse_final(provider_response.get("output")),
            "usage": provider_response.get("tokenUsage") or raw_dict.get("usage"),
            "session_id": provider_response.get("sessionId"),
        },
        evidence={
            "raw_provider_response": provider_response,
            "normalized_steps": steps,
            "stdout": None,
            "stderr": None,
            "unavailable_fields": ["stdout", "stderr"],
        },
        observation={},
        outcome={},
        provenance={"raw_hash": raw_hash, "scorer_version": "cib/0.2.0"},
    )
