from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from .manifest import build_manifest, write_manifest
from .materialize import (
    CLOUD_CONFIG_CACHE,
    load_cloud_config_seed,
    materialize_run,
    private_snapshot_sha256,
)
from .direct_backend import run_direct_suite
from .promptfoo import export_promptfoo_suite
from .promptfoo_results import (
    complete_outer_watchdog_results,
    normalize_promptfoo_jsonl,
)
from .tasks import CASES, TaskCase


PROMPTFOO_BEHAVIORAL_FAILURE_EXIT = 100
PROMPTFOO_TERMINATION_GRACE_SECONDS = 5.0
PROMPTFOO_PROCESS_EXIT_GRACE_SECONDS = 30


def derive_study_timeout_seconds(
    *, trial_count: int, jobs: int, trial_timeout_seconds: int
) -> int:
    if trial_count < 1 or jobs < 1 or trial_timeout_seconds < 1:
        raise ValueError("timeout derivation inputs must be positive")
    base = math.ceil(trial_count / min(jobs, trial_count)) * trial_timeout_seconds
    overhead = max(60, math.ceil(base * 0.1))
    return base + overhead


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


def promptfoo_environment(run_dir: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PROMPTFOO_CONFIG_DIR"] = str(
        (run_dir / "promptfoo" / "state").resolve()
    )
    environment["CIB_PYTHON"] = sys.executable
    environment["PROMPTFOO_DISABLE_TELEMETRY"] = "true"
    return environment


def _cloud_config_post_run(
    materialized: Iterable[Any], seed_sha256: str
) -> dict[str, int]:
    digests = [
        private_snapshot_sha256(Path(trial.codex_home) / CLOUD_CONFIG_CACHE)
        for trial in materialized
    ]
    return {
        "trial_copies": len(digests),
        "unchanged": sum(digest == seed_sha256 for digest in digests),
        "changed": sum(digest not in (None, seed_sha256) for digest in digests),
        "missing": sum(digest is None for digest in digests),
    }


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
    trial_timeout_seconds: int | None = 300,
    study_timeout_seconds: int | None = None,
    cloud_config_seed_path: Path | None = None,
    cloud_config_min_remaining_seconds: int | None = None,
    timeout_source: str = "derived_api",
    custom_case: TaskCase | None = None,
) -> dict[str, Any]:
    if run_dir.exists():
        raise FileExistsError(f"Refusing to reuse run directory: {run_dir}")
    if (
        cloud_config_min_remaining_seconds is not None
        and cloud_config_seed_path is None
    ):
        raise ValueError("Cloud config minimum validity requires an explicit seed")
    if jobs < 1:
        raise ValueError("jobs must be positive")
    if trial_timeout_seconds is not None and trial_timeout_seconds < 1:
        raise ValueError("trial timeout must be positive")
    if study_timeout_seconds is not None and study_timeout_seconds < 1:
        raise ValueError("study timeout must be positive")

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
    if study_timeout_seconds is None:
        if trial_timeout_seconds is None:
            raise ValueError("Promptfoo requires a trial or study timeout")
        study_timeout_seconds = derive_study_timeout_seconds(
            trial_count=len(rows),
            jobs=jobs,
            trial_timeout_seconds=trial_timeout_seconds,
        )
    legacy_promptfoo_timeout = (
        timeout_source in {"legacy_cib_check_1", "legacy_cli"}
        and trial_timeout_seconds is None
    )
    cases = dict(CASES)
    if custom_case is not None:
        cases[custom_case.case_id] = custom_case
    cache_minimum = (
        cloud_config_min_remaining_seconds
        if cloud_config_min_remaining_seconds is not None
        else (trial_timeout_seconds or 0) + 300
    )
    cloud_config_seed = (
        load_cloud_config_seed(
            auth_path,
            source_path=cloud_config_seed_path,
            minimum_remaining_seconds=cache_minimum,
        )
        if cloud_config_seed_path is not None
        else None
    )
    if cloud_config_seed_path is not None and cloud_config_seed is None:
        raise ValueError("Explicit cloud config seed is not fresh enough")
    materialized = materialize_run(
        rows, run_dir, auth_path, cases, cloud_config_seed=cloud_config_seed
    )
    promptfoo_dir = run_dir / "promptfoo"
    config_path, tests_path = export_promptfoo_suite(
        materialized,
        promptfoo_dir,
        cases,
        trial_timeout_seconds=trial_timeout_seconds,
        study_timeout_seconds=(
            None if legacy_promptfoo_timeout else study_timeout_seconds
        ),
    )
    result_path = promptfoo_dir / "results.jsonl"
    suite_hashes = {
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "tests_sha256": hashlib.sha256(tests_path.read_bytes()).hexdigest(),
    }
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
        "timeout_policy": {
            "schema_version": "cib-timeout-policy/2",
            "trial_seconds": trial_timeout_seconds,
            "study_seconds": study_timeout_seconds,
            "source": timeout_source,
            "backend_enforcement": (
                "legacy process-group watchdog"
                if legacy_promptfoo_timeout
                else "promptfoo evaluateOptions plus process-group watchdog"
            ),
        },
        "timeout_scope": "none",
        "timeout_occurred": False,
        "state_isolation": {
            "promptfoo_config_dir": "per_run",
        },
        "cloud_config_seed": (
            {**cloud_config_seed.to_safe_dict(), "minimum_remaining_seconds": cache_minimum}
            if cloud_config_seed is not None
            else {
                "present": False,
                "mode": "network_bootstrap",
                "minimum_remaining_seconds": cache_minimum,
            }
        ),
        "frozen_suite": suite_hashes,
    }
    execution_path = run_dir / "execution.json"
    execution_path.write_text(json.dumps(execution, indent=2), encoding="utf-8")
    if (
        cloud_config_seed is not None
        and not cloud_config_seed.has_minimum_remaining(cache_minimum)
    ):
        raise ValueError("Cloud config seed lost its required freshness during setup")
    process = subprocess.Popen(
        command,
        cwd=project_root,
        env=promptfoo_environment(run_dir),
        start_new_session=True,
    )
    outer_watchdog_timed_out = False
    try:
        watchdog_seconds = (
            study_timeout_seconds
            if legacy_promptfoo_timeout
            else study_timeout_seconds + PROMPTFOO_PROCESS_EXIT_GRACE_SECONDS
        )
        return_code = process.wait(timeout=watchdog_seconds)
    except subprocess.TimeoutExpired:
        outer_watchdog_timed_out = True
        _terminate_process_group(process)
        execution["finished_at_unix"] = time.time()
        execution["duration_seconds"] = (
            execution["finished_at_unix"] - execution["started_at_unix"]
        )
        execution["promptfoo_exit_code"] = None
        execution["timed_out"] = True
        execution["timeout_scope"] = "outer_watchdog"
        execution["timeout_occurred"] = True
        execution_path.write_text(json.dumps(execution, indent=2), encoding="utf-8")
        complete_outer_watchdog_results(
            result_path,
            (row.manifest for row in materialized),
            study_timeout_seconds=study_timeout_seconds,
        )
    else:
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

    final_suite_hashes = {
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "tests_sha256": hashlib.sha256(tests_path.read_bytes()).hexdigest(),
    }
    execution["frozen_suite_unchanged"] = final_suite_hashes == suite_hashes
    if not execution["frozen_suite_unchanged"]:
        execution_path.write_text(json.dumps(execution, indent=2), encoding="utf-8")
        raise RuntimeError("Promptfoo frozen suite changed during execution")
    if cloud_config_seed is not None:
        execution["cloud_config_seed_post_run"] = _cloud_config_post_run(
            materialized, cloud_config_seed.sha256
        )
    audit = normalize_promptfoo_jsonl(
        result_path,
        promptfoo_dir / "derived",
        promptfoo_dir / "protected" / "raw",
        tests_path=tests_path,
        expected_tests_sha256=suite_hashes["tests_sha256"],
    )
    if outer_watchdog_timed_out:
        execution["timeout_scope"] = "outer_watchdog"
        execution["timeout_occurred"] = True
    elif audit.get("study_timed_out"):
        execution["timeout_scope"] = "study"
        execution["timeout_occurred"] = True
    elif audit.get("trial_timeout_count"):
        execution["timeout_scope"] = "trial"
        execution["timeout_occurred"] = True
    execution_path.write_text(json.dumps(execution, indent=2), encoding="utf-8")
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
    trial_timeout_seconds: int | None = 300,
    study_timeout_seconds: int | None = None,
    cloud_config_seed_path: Path | None = None,
    cloud_config_min_remaining_seconds: int | None = None,
    timeout_source: str = "derived_api",
    custom_case: TaskCase | None = None,
) -> dict[str, Any]:
    if run_dir.exists():
        raise FileExistsError(f"Refusing to reuse run directory: {run_dir}")
    if (
        cloud_config_min_remaining_seconds is not None
        and cloud_config_seed_path is None
    ):
        raise ValueError("Cloud config minimum validity requires an explicit seed")
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
    cache_minimum = (
        cloud_config_min_remaining_seconds
        if cloud_config_min_remaining_seconds is not None
        else (trial_timeout_seconds or 0) + 300
    )
    cloud_config_seed = (
        load_cloud_config_seed(
            auth_path,
            source_path=cloud_config_seed_path,
            minimum_remaining_seconds=cache_minimum,
        )
        if cloud_config_seed_path is not None
        else None
    )
    if cloud_config_seed_path is not None and cloud_config_seed is None:
        raise ValueError("Explicit cloud config seed is not fresh enough")
    materialized = materialize_run(
        rows, run_dir, auth_path, cases, cloud_config_seed=cloud_config_seed
    )
    started = time.time()
    if trial_timeout_seconds is None:
        raise ValueError("Direct Codex requires a per-trial timeout")
    if study_timeout_seconds is None and timeout_source not in {
        "legacy_cib_check_1",
        "legacy_cli",
    }:
        study_timeout_seconds = derive_study_timeout_seconds(
            trial_count=len(materialized),
            jobs=jobs,
            trial_timeout_seconds=trial_timeout_seconds,
        )
    if (
        cloud_config_seed is not None
        and not cloud_config_seed.has_minimum_remaining(cache_minimum)
    ):
        raise ValueError("Cloud config seed lost its required freshness during setup")
    audit = run_direct_suite(
        materialized,
        run_dir / "direct",
        jobs=jobs,
        trial_timeout_seconds=trial_timeout_seconds,
        study_timeout_seconds=study_timeout_seconds,
        cases=cases,
    )
    execution = {
        "run_id": run_id,
        "profile": "scientific",
        "backend": "direct-codex",
        "trial_count": len(rows),
        "started_at_unix": started,
        "finished_at_unix": time.time(),
        "timeout_policy": {
            "schema_version": "cib-timeout-policy/2",
            "trial_seconds": trial_timeout_seconds,
            "study_seconds": study_timeout_seconds,
            "source": timeout_source,
            "backend_enforcement": "direct Codex process deadlines",
        },
        "timeout_scope": (
            "study"
            if audit.get("study_timed_out")
            else ("trial" if audit.get("trial_timeout_count") else "none")
        ),
        "timeout_occurred": bool(
            audit.get("study_timed_out") or audit.get("trial_timeout_count")
        ),
        "cloud_config_seed": (
            {**cloud_config_seed.to_safe_dict(), "minimum_remaining_seconds": cache_minimum}
            if cloud_config_seed is not None
            else {
                "present": False,
                "mode": "network_bootstrap",
                "minimum_remaining_seconds": cache_minimum,
            }
        ),
    }
    if cloud_config_seed is not None:
        execution["cloud_config_seed_post_run"] = _cloud_config_post_run(
            materialized, cloud_config_seed.sha256
        )
    execution["duration_seconds"] = (
        execution["finished_at_unix"] - execution["started_at_unix"]
    )
    outcome = {"execution": execution, "audit": audit}
    (run_dir / "study-result.json").write_text(
        json.dumps(outcome, indent=2), encoding="utf-8"
    )
    return outcome
