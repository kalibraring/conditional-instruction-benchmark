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


PROCESS_GROUP_TERM_GRACE_SECONDS = 5.0


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


def _terminate_process_group(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Terminate a whole Codex process group without losing a boundary exit race."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        return process.communicate(timeout=PROCESS_GROUP_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return process.communicate()


def _write_direct_result(
    row: MaterializedTrial,
    target: Path,
    raw: dict[str, Any],
    study_deadline: float | None = None,
) -> dict[str, Any]:
    scored = score_envelope(normalize_direct_raw(raw, row.manifest))
    if (
        study_deadline is not None
        and raw.get("timeout_scope") != "study"
        and time.monotonic() >= study_deadline
    ):
        raw["exit_code"] = 124
        raw["timed_out"] = True
        raw["timeout_scope"] = "study"
        deadline_message = "Study deadline elapsed during trial completion or scoring."
        raw["stderr"] = "\n".join(
            part for part in (str(raw.get("stderr", "")), deadline_message) if part
        )
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
        "started": raw.get("started", True),
        "timeout_scope": raw.get("timeout_scope"),
    }


def _study_timeout_result(
    row: MaterializedTrial,
    raw_dir: Path,
    *,
    reason: str = "Study deadline elapsed before trial started.",
) -> dict[str, Any]:
    """Write complete fail-closed evidence for a trial that must not be spawned."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / f"{row.manifest.trial_id}.json"
    if target.exists():
        raise FileExistsError(f"Refusing to replace direct evidence: {target}")
    raw: dict[str, Any] = {
        "spec": row.manifest.to_spec().to_dict(),
        "nonce": row.manifest.nonce,
        "exit_code": 124,
        "timed_out": True,
        "timeout_scope": "study",
        "started": False,
        "latency_seconds": 0.0,
        "final_response": None,
        "usage": {},
        "stderr": reason,
        "events": [],
    }
    return _write_direct_result(row, target, raw)


def run_direct_trial(
    row: MaterializedTrial,
    raw_dir: Path,
    timeout_seconds: float = 300,
    codex_path: str = "codex",
    cases: Mapping[str, TaskCase] | None = None,
    study_deadline: float | None = None,
) -> dict[str, Any]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / f"{row.manifest.trial_id}.json"
    if target.exists():
        raise FileExistsError(f"Refusing to replace direct evidence: {target}")
    started = time.monotonic()
    if study_deadline is not None and study_deadline - started <= 0:
        return _study_timeout_result(row, raw_dir)
    trial_deadline = started + float(timeout_seconds)
    process = subprocess.Popen(
        direct_command(row, codex_path, cases),
        cwd=row.working_dir,
        env=_isolated_env(row),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    after_spawn = time.monotonic()
    remaining_trial_seconds = trial_deadline - after_spawn
    remaining_study_seconds = (
        study_deadline - after_spawn if study_deadline is not None else None
    )
    timeout_scope = "trial"
    effective_timeout = remaining_trial_seconds
    if (
        remaining_study_seconds is not None
        and remaining_study_seconds <= effective_timeout
    ):
        effective_timeout = remaining_study_seconds
        timeout_scope = "study"
    timed_out = False
    if effective_timeout <= 0:
        timed_out = True
        stdout, stderr = _terminate_process_group(process)
        exit_code = 124
    else:
        try:
            stdout, stderr = process.communicate(timeout=effective_timeout)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            stdout, stderr = _terminate_process_group(process)
            exit_code = 124
    events = _parse_events(stdout)
    raw: dict[str, Any] = {
        "spec": row.manifest.to_spec().to_dict(),
        "nonce": row.manifest.nonce,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "timeout_scope": timeout_scope if timed_out else None,
        "started": True,
        "latency_seconds": time.monotonic() - started,
        "final_response": _final_response(events),
        "usage": _usage(events),
        "stderr": stderr,
        "events": events,
    }
    return _write_direct_result(row, target, raw, study_deadline)


def run_direct_suite(
    rows: Iterable[MaterializedTrial],
    output_dir: Path,
    jobs: int = 8,
    timeout_seconds: float = 300,
    codex_path: str = "codex",
    cases: Mapping[str, TaskCase] | None = None,
    *,
    trial_timeout_seconds: float | None = None,
    study_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    materialized = list(rows)
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    per_trial_timeout = float(
        timeout_seconds if trial_timeout_seconds is None else trial_timeout_seconds
    )
    if per_trial_timeout <= 0:
        raise ValueError("trial timeout must be greater than zero")
    if study_timeout_seconds is not None and study_timeout_seconds <= 0:
        raise ValueError("study timeout must be greater than zero")
    study_deadline = (
        time.monotonic() + study_timeout_seconds
        if study_timeout_seconds is not None
        else None
    )
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        futures: dict[
            concurrent.futures.Future[dict[str, Any]], MaterializedTrial
        ] = {}
        next_index = 0

        def submit_until_full() -> None:
            nonlocal next_index
            while next_index < len(materialized) and len(futures) < jobs:
                row = materialized[next_index]
                if study_deadline is not None and time.monotonic() >= study_deadline:
                    break
                next_index += 1
                future = executor.submit(
                    run_direct_trial,
                    row,
                    raw_dir,
                    per_trial_timeout,
                    codex_path,
                    cases,
                    study_deadline,
                )
                futures[future] = row

        submit_until_full()
        while futures:
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                futures.pop(future)
                summary.append(future.result())
            submit_until_full()

        # The shared deadline can expire while a running batch is being cleaned up.
        # Preserve one raw file and one summary row for every never-started trial.
        while next_index < len(materialized):
            summary.append(_study_timeout_result(materialized[next_index], raw_dir))
            next_index += 1
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
    trial_timeout_trial_ids = sorted(
        row["trial_id"] for row in summary if row.get("timeout_scope") == "trial"
    )
    study_timeout_trial_ids = sorted(
        row["trial_id"] for row in summary if row.get("timeout_scope") == "study"
    )
    audit.update(
        {
            "study_timed_out": bool(study_timeout_trial_ids),
            "trial_timeout_count": len(trial_timeout_trial_ids),
            "study_timeout_count": len(study_timeout_trial_ids),
            "trial_timeout_trial_ids": trial_timeout_trial_ids,
            "study_timeout_trial_ids": study_timeout_trial_ids,
            "timeout_affected_trial_ids": sorted(
                set(trial_timeout_trial_ids) | set(study_timeout_trial_ids)
            ),
        }
    )
    audit["passed"] = (
        audit["result_rows"] == len(materialized)
        and audit["unique_trial_ids"] == len(materialized)
        and audit["raw_files"] == len(materialized)
        and not audit["study_timed_out"]
    )
    (output_dir / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit
