from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable

from .manifest import build_manifest, write_manifest
from .materialize import materialize_run
from .direct_backend import run_direct_suite
from .promptfoo import export_promptfoo_suite
from .promptfoo_results import normalize_promptfoo_jsonl
from .tasks import CASES, TaskCase


PROMPTFOO_BEHAVIORAL_FAILURE_EXIT = 100
PROMPTFOO_TERMINATION_GRACE_SECONDS = 5.0


def promptfoo_command(
    *,
    binary: Path,
    config_path: Path,
    result_path: Path,
    jobs: int,
) -> list[str]:
    return [
        str(binary.resolve()),
        "eval",
        "--config",
        str(config_path.resolve()),
        "--output",
        str(result_path.resolve()),
        "--max-concurrency",
        str(jobs),
        "--no-cache",
        "--no-share",
        "--no-progress-bar",
        "--no-table",
    ]


def run_promptfoo_study(
    *,
    project_root: Path,
    run_dir: Path,
    run_id: str,
    case_ids: Iterable[str],
    placements: Iterable[str],
    replicates: int,
    seed: int,
    jobs: int,
    auth_path: Path,
    model: str,
    reasoning_effort: str,
    timeout_seconds: int = 300,
    custom_case: TaskCase | None = None,
) -> dict[str, Any]:
    if run_dir.exists():
        raise FileExistsError(f"Refusing to reuse run directory: {run_dir}")
    if jobs < 1:
        raise ValueError("jobs must be positive")

    rows = build_manifest(
        run_id=run_id,
        case_ids=tuple(case_ids),
        placements=tuple(placements),
        replicates=replicates,
        seed=seed,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    write_manifest(rows, run_dir)
    cases = dict(CASES)
    if custom_case is not None:
        cases[custom_case.case_id] = custom_case
    materialized = materialize_run(rows, run_dir, auth_path, cases)
    promptfoo_dir = run_dir / "promptfoo"
    config_path, _ = export_promptfoo_suite(materialized, promptfoo_dir, cases)
    result_path = promptfoo_dir / "results.jsonl"
    local_binary = project_root / "node_modules" / ".bin" / "promptfoo"
    discovered_binary = shutil.which("promptfoo")
    binary = local_binary if local_binary.exists() else (
        Path(discovered_binary) if discovered_binary else local_binary
    )
    if not binary.exists():
        raise FileNotFoundError(
            "Promptfoo binary not found; run npm ci in the repository or install "
            "the pinned Promptfoo version on PATH"
        )
    command = promptfoo_command(
        binary=binary,
        config_path=config_path,
        result_path=result_path,
        jobs=jobs,
    )
    execution: dict[str, Any] = {
        "run_id": run_id,
        "profile": "scientific",
        "trial_count": len(rows),
        "command": command,
        "started_at_unix": time.time(),
    }
    execution_path = run_dir / "execution.json"
    execution_path.write_text(json.dumps(execution, indent=2), encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=project_root,
        start_new_session=True,
    )
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        _terminate_process_group(process)
        execution["finished_at_unix"] = time.time()
        execution["duration_seconds"] = (
            execution["finished_at_unix"] - execution["started_at_unix"]
        )
        execution["promptfoo_exit_code"] = None
        execution["timed_out"] = True
        execution_path.write_text(json.dumps(execution, indent=2), encoding="utf-8")
        raise RuntimeError("Promptfoo execution timed out") from error
    execution["finished_at_unix"] = time.time()
    execution["duration_seconds"] = (
        execution["finished_at_unix"] - execution["started_at_unix"]
    )
    execution["promptfoo_exit_code"] = return_code
    execution["timed_out"] = False
    execution_path.write_text(json.dumps(execution, indent=2), encoding="utf-8")
    if return_code not in (0, PROMPTFOO_BEHAVIORAL_FAILURE_EXIT):
        raise RuntimeError(f"Promptfoo execution failed with exit code {return_code}")
    if not result_path.exists():
        raise FileNotFoundError(f"Promptfoo did not write results: {result_path}")

    audit = normalize_promptfoo_jsonl(
        result_path,
        promptfoo_dir / "derived",
        promptfoo_dir / "protected" / "raw",
    )
    outcome = {"execution": execution, "audit": audit}
    (run_dir / "study-result.json").write_text(
        json.dumps(outcome, indent=2), encoding="utf-8"
    )
    return outcome


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    try:
        process.wait(timeout=0.1)
    except subprocess.TimeoutExpired:
        pass
    deadline = time.monotonic() + PROMPTFOO_TERMINATION_GRACE_SECONDS
    while time.monotonic() < deadline and _process_group_exists(process.pid):
        time.sleep(0.05)
    if _process_group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_direct_study(
    *,
    run_dir: Path,
    run_id: str,
    case_ids: Iterable[str],
    placements: Iterable[str],
    replicates: int,
    seed: int,
    jobs: int,
    auth_path: Path,
    model: str,
    reasoning_effort: str,
    timeout_seconds: int = 300,
    custom_case: TaskCase | None = None,
) -> dict[str, Any]:
    if run_dir.exists():
        raise FileExistsError(f"Refusing to reuse run directory: {run_dir}")
    rows = build_manifest(
        run_id=run_id,
        case_ids=tuple(case_ids),
        placements=tuple(placements),
        replicates=replicates,
        seed=seed,
        model=model,
        reasoning_effort=reasoning_effort,
        target_adapter="direct-codex",
    )
    write_manifest(rows, run_dir)
    cases = dict(CASES)
    if custom_case is not None:
        cases[custom_case.case_id] = custom_case
    materialized = materialize_run(rows, run_dir, auth_path, cases)
    started = time.time()
    audit = run_direct_suite(
        materialized,
        run_dir / "direct",
        jobs=jobs,
        timeout_seconds=timeout_seconds,
        cases=cases,
    )
    execution = {
        "run_id": run_id,
        "profile": "scientific",
        "backend": "direct-codex",
        "trial_count": len(rows),
        "started_at_unix": started,
        "finished_at_unix": time.time(),
    }
    execution["duration_seconds"] = (
        execution["finished_at_unix"] - execution["started_at_unix"]
    )
    outcome = {"execution": execution, "audit": audit}
    (run_dir / "study-result.json").write_text(
        json.dumps(outcome, indent=2), encoding="utf-8"
    )
    return outcome
