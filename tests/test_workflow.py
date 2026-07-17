import json
import os
from pathlib import Path
import time

import pytest

from cib.workflow import (
    derive_study_timeout_seconds,
    promptfoo_command,
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
    assert command[command.index("--max-concurrency") + 1] == "7"
    assert command[command.index("--output") + 1] == str(results.resolve())


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
