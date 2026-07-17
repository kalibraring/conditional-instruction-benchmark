import json
import subprocess
import sys
from pathlib import Path

import pytest


ARMS = ("if", "iff", "if_else_not")


def test_cli_prints_installed_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "cib 0.3.0"


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
                "arm": arm,
                "condition_true": truth,
                "case_id": "literal_flag",
                "case_variant": 0,
                "placement": "prompt_start",
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
        "duplicate_trial_ids": 0,
        "protected_raw_files": 6,
        "protected_source_rows": 6,
        "missing_protected_raw": [],
        "unexpected_protected_raw": [],
        "unique_session_ids": 6,
        "behavioral_successes": 4,
        "harness_failures": 0,
        "promptfoo_cib_disagreements": [],
        "archive_identity_disagreements": [],
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


def _write_audit(run_dir: Path, summary: list[dict[str, object]]) -> None:
    audit = {
        "result_rows": len(summary),
        "unique_trial_ids": len({str(row["trial_id"]) for row in summary}),
        "duplicate_trial_ids": 0,
        "protected_raw_files": len(summary),
        "protected_source_rows": len(summary),
        "missing_protected_raw": [],
        "unexpected_protected_raw": [],
        "unique_session_ids": len(summary),
        "behavioral_successes": sum(bool(row["behavioral_success"]) for row in summary),
        "harness_failures": sum(bool(row["harness_failure"]) for row in summary),
        "promptfoo_cib_disagreements": [],
        "archive_identity_disagreements": [],
        "passed": True,
    }
    audit_path = run_dir / "promptfoo" / "derived" / "audit.json"
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    study_path = run_dir / "study-result.json"
    study = json.loads(study_path.read_text())
    study["execution"]["trial_count"] = len(summary)
    study["audit"] = audit
    study_path.write_text(json.dumps(study, indent=2), encoding="utf-8")


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
        "report_json": "report/report.json",
        "report_markdown": "report/report.md",
        "report_html": "report/report.html",
    }
    report = json.loads((report_dir / "report.json").read_text())
    assert report["schema_version"] == "cib-report/1"
    assert report["provenance"]["generator_version"] == "0.3.0"
    assert report["claim"]["status"] == "exploratory_smoke"
    assert report["run"]["cases"] == [
        {"case_id": "literal_flag", "variants": [0]}
    ]
    assert report["run"]["block_ids"] == ["prompt_start:literal_flag:000"]
    assert report["run"]["randomization"] == {
        "orders": [0, 1, 2, 3, 4, 5],
        "complete_permutation": True,
    }
    expected_rates = {
        ("if", True): 1.0,
        ("if", False): 0.0,
        ("iff", True): 1.0,
        ("iff", False): 1.0,
        ("if_else_not", True): 0.0,
        ("if_else_not", False): 1.0,
    }
    assert {
        (cell["arm"], cell["condition_true"]): cell["rate"]
        for cell in report["cells"]
    } == expected_rates
    success_cell = next(cell for cell in report["cells"] if cell["rate"] == 1.0)
    failure_cell = next(cell for cell in report["cells"] if cell["rate"] == 0.0)
    assert success_cell["wilson_low"] == pytest.approx(0.20654931437723745)
    assert success_cell["wilson_high"] == 1.0
    assert failure_cell["wilson_low"] == 0.0
    assert failure_cell["wilson_high"] == pytest.approx(0.7934506856227626)
    expected_contrasts = {
        ("operational_iff_minus_if", True): 0.0,
        ("boundary_expanded_minus_if", True): -1.0,
        ("form_iff_minus_expanded", True): 1.0,
        ("operational_iff_minus_if", False): 1.0,
        ("boundary_expanded_minus_if", False): 1.0,
        ("form_iff_minus_expanded", False): 0.0,
    }
    assert {
        (contrast["contrast"], contrast["condition_true"]): contrast[
            "risk_difference"
        ]
        for contrast in report["contrasts"]
    } == expected_contrasts
    markdown = (report_dir / "report.md").read_text()
    html = (report_dir / "report.html").read_text()
    assert "# Conditional Instruction Benchmark report" in markdown
    assert "<!doctype html>" in html.lower()
    assert "<style>" in html
    assert "<script" not in html
    public_reports = completed.stdout + json.dumps(report) + markdown + html
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


def test_trial_identity_error_does_not_echo_derived_identifier(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    sensitive_id = "/" + "tmp/private-derived-id"
    summary_path = run_dir / "promptfoo" / "derived" / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary[0]["trial_id"] = sensitive_id
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "Manifest and summary trial IDs disagree" in completed.stderr
    assert sensitive_id not in completed.stdout + completed.stderr


def test_report_command_rejects_assignment_identity_mismatch(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    summary_path = run_dir / "promptfoo" / "derived" / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary[0]["arm"] = "iff"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "assignment fields disagree" in completed.stderr
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
    direct_audit = {
        "result_rows": 6,
        "unique_trial_ids": 6,
        "raw_files": 6,
        "behavioral_successes": 4,
        "harness_failures": 0,
        "passed": True,
    }
    (direct_dir / "audit.json").write_text(
        json.dumps(direct_audit), encoding="utf-8"
    )
    study_path = run_dir / "study-result.json"
    study = json.loads(study_path.read_text())
    study["audit"] = direct_audit
    study_path.write_text(json.dumps(study), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    report = json.loads((run_dir / result["report_json"]).read_text())
    assert report["run"]["backend"] == "direct-codex"
    assert report["integrity"]["passed"] is True


def test_report_command_rejects_undeclared_backend(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    manifest_path = run_dir / "run-manifest.jsonl"
    manifest = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    for row in manifest:
        row["target_adapter"] = "undeclared-agent"
    manifest_path.write_text(
        "".join(json.dumps(row) + "\n" for row in manifest), encoding="utf-8"
    )

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "Unsupported report backend" in completed.stderr
    assert not (run_dir / "report").exists()


@pytest.mark.parametrize(
    "unsafe_run_id",
    (
        "/" + "Users/example/private-study",
        "/" + "tmp/private-study",
        "study at /" + "Volumes/Research/private-study",
        "D:" + "\\private-study",
        "study at D:" + "\\private-study",
        "AKIA" + "A" * 16,
    ),
)
def test_report_command_rejects_sensitive_text_in_public_manifest(
    tmp_path: Path,
    unsafe_run_id: str,
) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    manifest_path = run_dir / "run-manifest.jsonl"
    manifest = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    for row in manifest:
        row["run_id"] = unsafe_run_id
    manifest_path.write_text(
        "".join(json.dumps(row) + "\n" for row in manifest), encoding="utf-8"
    )
    study_path = run_dir / "study-result.json"
    study = json.loads(study_path.read_text())
    study["execution"]["run_id"] = unsafe_run_id
    study_path.write_text(json.dumps(study), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "Unsafe text in public manifest field run_id" in completed.stderr
    assert not (run_dir / "report").exists()


def test_report_command_rejects_non_boolean_outcome(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    summary_path = run_dir / "promptfoo" / "derived" / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary[0]["behavioral_success"] = "false"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "behavioral_success must be a boolean" in completed.stderr
    assert not (run_dir / "report").exists()


def test_report_command_recomputes_audit_outcome_counts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    audit_path = run_dir / "promptfoo" / "derived" / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["behavioral_successes"] = 99
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    study_path = run_dir / "study-result.json"
    study = json.loads(study_path.read_text())
    study["audit"] = audit
    study_path.write_text(json.dumps(study), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "Audit outcome counts disagree with derived summary" in completed.stderr
    assert not (run_dir / "report").exists()


def test_report_command_rejects_symlinked_canonical_input(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    summary_path = run_dir / "promptfoo" / "derived" / "summary.json"
    protected_path = run_dir / "promptfoo" / "protected" / "raw" / "secret.json"
    protected_path.parent.mkdir(parents=True)
    protected_path.write_text(summary_path.read_text(), encoding="utf-8")
    summary_path.unlink()
    summary_path.symlink_to(protected_path)

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "Canonical report input must not be a symlink" in completed.stderr
    assert not (run_dir / "report").exists()


def test_incomplete_design_is_not_labeled_as_six_trial_smoke(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    manifest_path = run_dir / "run-manifest.jsonl"
    manifest = [json.loads(line) for line in manifest_path.read_text().splitlines()][:-1]
    manifest_path.write_text(
        "".join(json.dumps(row) + "\n" for row in manifest), encoding="utf-8"
    )
    summary_path = run_dir / "promptfoo" / "derived" / "summary.json"
    summary = json.loads(summary_path.read_text())[:-1]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_audit(run_dir, summary)

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    report = json.loads((run_dir / result["report_json"]).read_text())
    rendered = (
        (run_dir / result["report_markdown"]).read_text()
        + (run_dir / result["report_html"]).read_text()
    )
    assert report["claim"]["status"] == "descriptive_only"
    assert "six-trial smoke design" not in rendered


def test_incomplete_randomization_is_not_labeled_as_smoke(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    manifest_path = run_dir / "run-manifest.jsonl"
    manifest = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    manifest[-1]["random_order"] = manifest[-2]["random_order"]
    manifest_path.write_text(
        "".join(json.dumps(row) + "\n" for row in manifest), encoding="utf-8"
    )
    summary_path = run_dir / "promptfoo" / "derived" / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary[-1]["random_order"] = summary[-2]["random_order"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    report = json.loads((run_dir / result["report_json"]).read_text())
    assert report["run"]["randomization"]["complete_permutation"] is False
    assert report["claim"]["status"] == "descriptive_only"


def test_report_stratifies_contrasts_by_instruction_placement(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_completed_study(run_dir)
    manifest_path = run_dir / "run-manifest.jsonl"
    manifest = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    summary_path = run_dir / "promptfoo" / "derived" / "summary.json"
    summary = json.loads(summary_path.read_text())
    for row in list(manifest):
        clone = dict(row)
        clone["trial_id"] = f"{row['trial_id']}-skill-body"
        clone["random_order"] = int(row["random_order"]) + 6
        clone["placement"] = "skill_body"
        clone["block_id"] = "skill_body:literal_flag:000"
        manifest.append(clone)
    for row in list(summary):
        clone = dict(row)
        clone["trial_id"] = f"{row['trial_id']}-skill-body"
        clone["random_order"] = int(row["random_order"]) + 6
        clone["placement"] = "skill_body"
        clone["behavioral_success"] = False
        clone["session_id"] = f"{row['session_id']}-skill-body"
        summary.append(clone)
    manifest_path.write_text(
        "".join(json.dumps(row) + "\n" for row in manifest), encoding="utf-8"
    )
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_audit(run_dir, summary)

    completed = subprocess.run(
        [sys.executable, "-m", "cib.cli", "report", str(run_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    report = json.loads((run_dir / result["report_json"]).read_text())
    false_iff_if = {
        row["placement"]: row["risk_difference"]
        for row in report["contrasts"]
        if row["contrast"] == "operational_iff_minus_if"
        and row["condition_true"] is False
    }
    assert false_iff_if == {"prompt_start": 1.0, "skill_body": 0.0}
    assert all(row["missing_task_families"] == [] for row in report["contrasts"])
