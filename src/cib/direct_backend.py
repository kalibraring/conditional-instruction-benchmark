from __future__ import annotations

import concurrent.futures
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from .codex_adapter import _final_response, _parse_events, _usage
from .contracts import MaterializedTrial
from .normalization import normalize_direct_raw
from .scoring import score_envelope
from .trials import prompt_for
from .tasks import TaskCase


def direct_command(
    row: MaterializedTrial,
    codex_path: str = "codex",
    cases: Mapping[str, TaskCase] | None = None,
) -> list[str]:
    manifest = row.manifest
    return [
        codex_path,
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--disable",
        "plugins",
        "--disable",
        "remote_plugin",
        "--disable",
        "plugin_sharing",
        "--sandbox",
        "read-only",
        "--model",
        manifest.model,
        "-c",
        f'model_reasoning_effort="{manifest.reasoning_effort}"',
        "-c",
        'approval_policy="never"',
        "-C",
        row.working_dir,
        "--output-schema",
        str(Path(row.working_dir) / "output-schema.json"),
        prompt_for(manifest.to_spec(), cases),
    ]


def _isolated_env(row: MaterializedTrial) -> dict[str, str]:
    allowed = (
        "PATH",
        "SHELL",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "USER",
        "LOGNAME",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["HOME"] = row.home
    env["CODEX_HOME"] = row.codex_home
    return env


def run_direct_trial(
    row: MaterializedTrial,
    raw_dir: Path,
    timeout_seconds: int = 300,
    codex_path: str = "codex",
    cases: Mapping[str, TaskCase] | None = None,
) -> dict[str, Any]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / f"{row.manifest.trial_id}.json"
    if target.exists():
        raise FileExistsError(f"Refusing to replace direct evidence: {target}")
    started = time.monotonic()
    process = subprocess.Popen(
        direct_command(row, codex_path, cases),
        cwd=row.working_dir,
        env=_isolated_env(row),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        exit_code = 124
    events = _parse_events(stdout)
    raw: dict[str, Any] = {
        "spec": row.manifest.to_spec().to_dict(),
        "nonce": row.manifest.nonce,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "latency_seconds": time.monotonic() - started,
        "final_response": _final_response(events),
        "usage": _usage(events),
        "stderr": stderr,
        "events": events,
    }
    scored = score_envelope(normalize_direct_raw(raw, row.manifest))
    raw["target_resource_used"] = scored["observation"]["target_action_seen"]
    raw["marker_executed"] = scored["observation"]["marker_seen"]
    raw["nonce_recovered"] = scored["observation"]["nonce_recovered"]
    target.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return {
        "trial_id": row.manifest.trial_id,
        "random_order": row.manifest.random_order,
        "arm": row.manifest.arm,
        "condition_true": row.manifest.condition_true,
        "case_id": row.manifest.case_id,
        "case_variant": row.manifest.case_variant,
        "placement": row.manifest.placement,
        **scored["observation"],
        **scored["outcome"],
        "latency_seconds": raw["latency_seconds"],
    }


def run_direct_suite(
    rows: Iterable[MaterializedTrial],
    output_dir: Path,
    jobs: int = 8,
    timeout_seconds: int = 300,
    codex_path: str = "codex",
    cases: Mapping[str, TaskCase] | None = None,
) -> dict[str, Any]:
    materialized = list(rows)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(
                run_direct_trial,
                row,
                raw_dir,
                timeout_seconds,
                codex_path,
                cases,
            ): row
            for row in materialized
        }
        for future in concurrent.futures.as_completed(futures):
            summary.append(future.result())
    summary.sort(key=lambda item: item["random_order"])
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    audit = {
        "result_rows": len(summary),
        "unique_trial_ids": len({row["trial_id"] for row in summary}),
        "raw_files": len(list(raw_dir.glob("*.json"))),
        "behavioral_successes": sum(row["behavioral_success"] for row in summary),
        "harness_failures": sum(row["harness_failure"] for row in summary),
    }
    audit["passed"] = (
        audit["result_rows"] == len(materialized)
        and audit["unique_trial_ids"] == len(materialized)
        and audit["raw_files"] == len(materialized)
    )
    (output_dir / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit
