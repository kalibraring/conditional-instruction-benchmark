import json
import subprocess
import sys
from pathlib import Path


def test_plan_command_writes_six_trials_without_model_call(tmp_path: Path) -> None:
    output = tmp_path / "plan"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cib.cli",
            "plan",
            "--run-id",
            "test-plan",
            "--case",
            "literal_flag",
            "--placement",
            "prompt_start",
            "--replicates",
            "1",
            "--output-dir",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    assert report["trial_count"] == 6
    assert report["model_calls"] == 0
    public_rows = [
        json.loads(line)
        for line in (output / "run-manifest.jsonl").read_text().splitlines()
    ]
    assert len(public_rows) == 6
    assert all("nonce" not in row for row in public_rows)
