import json
import subprocess
import sys
from pathlib import Path


ARMS = ("if", "iff", "if_else_not")


def _write_completed_study(run_dir: Path) -> str:
    run_id = "six-trial-report"
    run_dir.mkdir()
    summary_dir = run_dir / "promptfoo" / "derived"
    summary_dir.mkdir(parents=True)
    manifest_rows = []
    summary_rows = []
    outcomes = {
        ("if", True): True,
        ("if", False): False,
        ("iff", True): True,
        ("iff", False): True,
        ("if_else_not", True): False,
        ("if_else_not", False): True,
    }
    for order, (arm, truth) in enumerate(
        (arm, truth) for arm in ARMS for truth in (True, False)
    ):
        trial_id = f"trial-{order}"
        manifest_rows.append(
            {
                "protocol_version": "cib/1",
                "run_id": run_id,
                "trial_id": trial_id,
                "block_id": "prompt_start:literal_flag:000",
                "random_order": order,
                "arm": arm,
                "condition_true": truth,
                "case_id": "literal_flag",
                "case_variant": 0,
                "placement": "prompt_start",
                "model": "test-model",
                "reasoning_effort": "medium",
                "target_adapter": "promptfoo-codex-sdk",
                "nonce_hash": f"hash-{order}",
                "profile": "scientific",
                "is_primary": True,
            }
        )
        summary_rows.append(
            {
                "trial_id": trial_id,
                "random_order": order,
                "behavioral_success": outcomes[(arm, truth)],
                "harness_failure": False,
                "session_id": f"private-session-{order}",
            }
        )
    (run_dir / "run-manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in manifest_rows),
        encoding="utf-8",
    )
    (run_dir / "run-manifest.private.jsonl").write_text(
        json.dumps({"nonce": "private-nonce-value"}) + "\n", encoding="utf-8"
    )
    (summary_dir / "summary.json").write_text(
        json.dumps(summary_rows, indent=2), encoding="utf-8"
    )
    audit = {
        "result_rows": 6,
        "unique_trial_ids": 6,
        "unique_session_ids": 6,
        "behavioral_successes": 4,
        "harness_failures": 0,
        "passed": True,
    }
    (summary_dir / "audit.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )
    (run_dir / "study-result.json").write_text(
        json.dumps(
            {
                "execution": {
                    "run_id": run_id,
                    "profile": "scientific",
                    "trial_count": 6,
                    "duration_seconds": 12.5,
                    "command": ["/" + "Users/example/private/bin/promptfoo"],
                },
                "audit": audit,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return run_id


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


def test_report_command_writes_safe_self_contained_reports(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_id = _write_completed_study(run_dir)

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    command_result = json.loads(completed.stdout)
    report_dir = run_dir / "report"
    assert command_result == {
        "run_id": run_id,
        "report_json": str(report_dir / "report.json"),
        "report_markdown": str(report_dir / "report.md"),
        "report_html": str(report_dir / "report.html"),
    }
    report = json.loads((report_dir / "report.json").read_text())
    assert report["schema_version"] == "cib-report/1"
    assert report["provenance"]["generator_version"] == "0.3.0"
    assert report["claim"]["status"] == "exploratory_smoke"
    assert next(
        cell
        for cell in report["cells"]
        if cell["arm"] == "if" and cell["condition_true"] is False
    )["rate"] == 0.0
    assert next(
        contrast
        for contrast in report["contrasts"]
        if contrast["contrast"] == "operational_iff_minus_if"
        and contrast["condition_true"] is False
    )["risk_difference"] == 1.0
    markdown = (report_dir / "report.md").read_text()
    html = (report_dir / "report.html").read_text()
    assert "# Conditional Instruction Benchmark report" in markdown
    assert "<!doctype html>" in html.lower()
    assert "<style>" in html
    assert "<script" not in html
    public_reports = json.dumps(report) + markdown + html
    assert "private-nonce-value" not in public_reports
    assert "private-session" not in public_reports
    assert "/" + "Users/example" not in public_reports


def test_report_command_rejects_trial_identity_mismatch_before_writing(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    summary_path = run_dir / "promptfoo" / "derived" / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary[0]["trial_id"] = "unexpected-trial"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "Manifest and summary trial IDs disagree" in completed.stderr
    assert not (run_dir / "report").exists()


def test_report_command_refuses_to_replace_existing_report(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    command = [sys.executable, "-m", "cib.cli", "report", str(run_dir)]
    subprocess.run(command, check=True, capture_output=True, text=True)

    completed = subprocess.run(command, capture_output=True, text=True)

    assert completed.returncode != 0
    assert "Refusing to replace report directory" in completed.stderr


def test_report_command_reads_direct_backend_canonical_summary(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    manifest_path = run_dir / "run-manifest.jsonl"
    manifest = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    for row in manifest:
        row["target_adapter"] = "direct-codex"
    manifest_path.write_text(
        "".join(json.dumps(row) + "\n" for row in manifest), encoding="utf-8"
    )
    direct_dir = run_dir / "direct"
    direct_dir.mkdir()
    derived_dir = run_dir / "promptfoo" / "derived"
    (derived_dir / "summary.json").rename(direct_dir / "summary.json")
    (derived_dir / "audit.json").rename(direct_dir / "audit.json")

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    report = json.loads(Path(result["report_json"]).read_text())
    assert report["run"]["backend"] == "direct-codex"
    assert report["integrity"]["passed"] is True
