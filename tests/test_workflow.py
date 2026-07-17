import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

from cib.workflow import (
    derive_study_timeout_seconds,
    promptfoo_command,
    promptfoo_environment,
    run_direct_study,
    run_promptfoo_study,
)


def test_scientific_promptfoo_command_forces_non_cached_non_shared_run(tmp_path: Path) -> None:
    binary = tmp_path / "promptfoo"
    config = tmp_path / "config.yaml"
    results = tmp_path / "results.jsonl"
    command = promptfoo_command(
        binary=binary, config_path=config, result_path=results, jobs=7
    )

    assert command[0] == str(binary.resolve())
    assert "--no-cache" in command
    assert "--no-share" in command
    assert "--no-write" not in command
    assert command[command.index("--max-concurrency") + 1] == "7"
    assert command[command.index("--output") + 1] == str(results.resolve())


def test_concurrent_promptfoo_processes_use_isolated_state_directories(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).parents[1]
    binary = project_root / "node_modules" / ".bin" / "promptfoo"
    if not binary.is_file():
        pytest.skip("run npm ci to exercise Promptfoo process isolation")
    config = tmp_path / "echo.yaml"
    config.write_text(
        """description: process isolation proof
prompts:
  - "hello {{ value }}"
providers:
  - echo
tests:
  - vars:
      value: world
    assert:
      - type: equals
        value: hello world
""",
        encoding="utf-8",
    )
    processes = []
    state_directories = []
    for index in range(4):
        run_dir = tmp_path / f"run-{index}"
        environment = promptfoo_environment(run_dir)
        assert environment["CIB_PYTHON"] == sys.executable
        assert environment["PROMPTFOO_DISABLE_TELEMETRY"] == "true"
        state_directories.append(environment["PROMPTFOO_CONFIG_DIR"])
        processes.append(
            subprocess.Popen(
                [
                    str(binary),
                    "eval",
                    "--config",
                    str(config),
                    "--output",
                    str(tmp_path / f"result-{index}.json"),
                    "--no-cache",
                    "--no-share",
                    "--no-progress-bar",
                    "--no-table",
                ],
                cwd=project_root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    outcomes = [process.communicate(timeout=30) for process in processes]
    assert len(set(state_directories)) == 4
    assert [process.returncode for process in processes] == [0, 0, 0, 0], outcomes
    for index, state_directory in enumerate(state_directories):
        assert (Path(state_directory) / "promptfoo.db").is_file()
        assert (tmp_path / f"result-{index}.json").stat().st_size > 0


def test_promptfoo_timeout_kills_stubborn_descendants_and_records_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    binary = project_root / "node_modules" / ".bin" / "promptfoo"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        '''#!/usr/bin/env python3
import subprocess
import sys
import time

child = """import os
import pathlib
import signal
import time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path(os.environ['CIB_TIMEOUT_CHILD_PID']).write_text(str(os.getpid()))
time.sleep(30)
"""
subprocess.Popen([sys.executable, "-c", child])
time.sleep(30)
''',
        encoding="utf-8",
    )
    binary.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "run"
    child_pid_path = tmp_path / "child.pid"
    monkeypatch.setenv("CIB_TIMEOUT_CHILD_PID", str(child_pid_path))
    monkeypatch.setattr("cib.workflow.PROMPTFOO_PROCESS_EXIT_GRACE_SECONDS", 0)

    outcome = run_promptfoo_study(
        project_root=project_root,
        run_dir=run_dir,
        run_id="timeout-proof",
        case_ids=("literal_flag",),
        placements=("skill_description",),
        replicates=1,
        seed=17,
        jobs=1,
        auth_path=auth,
        model="test-model",
        reasoning_effort="medium",
        trial_timeout_seconds=30,
        study_timeout_seconds=1,
        timeout_source="explicit",
    )

    execution = json.loads((run_dir / "execution.json").read_text())
    assert execution["trial_count"] == 6
    assert execution["timed_out"] is True
    assert execution["promptfoo_exit_code"] is None
    assert execution["duration_seconds"] >= 6
    assert execution["timeout_scope"] == "outer_watchdog"
    assert execution["timeout_policy"]["trial_seconds"] == 30
    assert execution["timeout_policy"]["study_seconds"] == 1
    assert outcome["audit"]["passed"] is False
    assert outcome["audit"]["study_timeout_count"] == 6
    assert (run_dir / "study-result.json").is_file()
    assert (run_dir / "promptfoo" / "derived" / "summary.json").is_file()
    child_pid = int(child_pid_path.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("Promptfoo timeout left a descendant process running")


def test_study_watchdog_does_not_reuse_one_trial_timeout_for_whole_run(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    binary = project_root / "node_modules" / ".bin" / "promptfoo"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        "#!/usr/bin/env python3\nimport time\ntime.sleep(1.2)\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "run"

    with pytest.raises(FileNotFoundError, match="did not write results"):
        run_promptfoo_study(
            project_root=project_root,
            run_dir=run_dir,
            run_id="multi-batch-proof",
            case_ids=("literal_flag",),
            placements=("skill_description",),
            replicates=1,
            seed=17,
            jobs=1,
            auth_path=auth,
            model="test-model",
            reasoning_effort="medium",
            trial_timeout_seconds=1,
            study_timeout_seconds=3,
            timeout_source="explicit",
        )

    execution = json.loads((run_dir / "execution.json").read_text())
    assert execution["duration_seconds"] >= 1.0
    assert execution["timed_out"] is False


def test_derived_study_timeout_covers_all_batches_plus_cleanup_margin() -> None:
    assert derive_study_timeout_seconds(
        trial_count=36, jobs=4, trial_timeout_seconds=300
    ) == 2970


def test_direct_backend_records_safe_cache_seed_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(timezone.utc)
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    cache = tmp_path / "seed.json"
    cache.write_text(
        json.dumps(
            {
                "signature": "signed",
                "signed_payload": {
                    "account_id": "never-publish",
                    "chatgpt_user_id": "never-publish",
                    "bundle": {},
                    "cached_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=1)).isoformat(),
                    "version": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "cib.workflow.run_direct_suite",
        lambda *args, **kwargs: {
            "study_timed_out": False,
            "trial_timeout_count": 0,
            "passed": True,
        },
    )

    outcome = run_direct_study(
        run_dir=tmp_path / "run",
        run_id="direct-seed",
        case_ids=("literal_flag",),
        placements=("prompt_start",),
        replicates=1,
        seed=1,
        jobs=2,
        auth_path=auth,
        model="m",
        reasoning_effort="medium",
        cloud_config_seed_path=cache,
        cloud_config_min_remaining_seconds=600,
    )

    execution = outcome["execution"]
    self_contained = json.dumps(execution)
    assert execution["cloud_config_seed"]["present"] is True
    assert execution["cloud_config_seed_post_run"]["unchanged"] == 6
    assert "never-publish" not in self_contained


def test_seed_freshness_is_rechecked_before_both_backends_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(timezone.utc)
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    cache = tmp_path / "seed.json"
    cache.write_text(
        json.dumps(
            {
                "signature": "signed",
                "signed_payload": {
                    "bundle": {},
                    "cached_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=1)).isoformat(),
                    "version": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "cib.materialize.CloudConfigSeed.has_minimum_remaining",
        lambda self, seconds: False,
    )
    monkeypatch.setattr(
        "cib.workflow.run_direct_suite",
        lambda *args, **kwargs: pytest.fail("direct backend started with stale seed"),
    )
    with pytest.raises(ValueError, match="lost its required freshness"):
        run_direct_study(
            run_dir=tmp_path / "direct-run",
            run_id="direct-stale",
            case_ids=("literal_flag",),
            placements=("prompt_start",),
            replicates=1,
            seed=1,
            jobs=2,
            auth_path=auth,
            model="m",
            reasoning_effort="medium",
            cloud_config_seed_path=cache,
            cloud_config_min_remaining_seconds=600,
        )

    project_root = tmp_path / "project"
    binary = project_root / "node_modules" / ".bin" / "promptfoo"
    binary.parent.mkdir(parents=True)
    binary.write_text("placeholder", encoding="utf-8")
    real_popen = subprocess.Popen

    def guarded_popen(command, *args, **kwargs):
        if command and command[0] == str(binary.resolve()):
            pytest.fail("Promptfoo started with stale seed")
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr("cib.workflow.subprocess.Popen", guarded_popen)
    with pytest.raises(ValueError, match="lost its required freshness"):
        run_promptfoo_study(
            project_root=project_root,
            run_dir=tmp_path / "promptfoo-run",
            run_id="promptfoo-stale",
            case_ids=("literal_flag",),
            placements=("prompt_start",),
            replicates=1,
            seed=1,
            jobs=2,
            auth_path=auth,
            model="m",
            reasoning_effort="medium",
            cloud_config_seed_path=cache,
            cloud_config_min_remaining_seconds=600,
        )
