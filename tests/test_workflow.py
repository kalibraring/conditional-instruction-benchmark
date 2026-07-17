import json
from pathlib import Path

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


def test_promptfoo_timeout_is_enforced_and_recorded(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    binary = project_root / "node_modules" / ".bin" / "promptfoo"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        "#!/usr/bin/env python3\nimport time\ntime.sleep(5)\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "run"

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
    assert execution["duration_seconds"] >= 1
