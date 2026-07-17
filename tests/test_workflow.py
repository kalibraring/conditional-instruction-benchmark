import json
import os
from pathlib import Path
import time

import pytest

from cib.workflow import promptfoo_command, run_promptfoo_study


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

    with pytest.raises(RuntimeError, match="Promptfoo execution timed out"):
        run_promptfoo_study(
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
            timeout_seconds=1,
        )

    execution = json.loads((run_dir / "execution.json").read_text())
    assert execution["trial_count"] == 6
    assert execution["timed_out"] is True
    assert execution["promptfoo_exit_code"] is None
    assert execution["duration_seconds"] >= 6
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
