from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from cib.checks import CheckConfigError, load_check_config, run_check
from cib.product_decision import build_product_decision


def _write_fake_codex(bin_dir: Path) -> None:
    executable = bin_dir / "codex"
    executable.parent.mkdir(parents=True)
    executable.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import re
import sys

if "--version" in sys.argv:
    print("codex-cli 1.0.0")
    raise SystemExit(0)

pathlib.Path(sys.argv[0]).with_name("model-called").write_text("yes")
prompt = sys.argv[-1]
fixture = pathlib.Path.cwd()
probe = fixture / ".agents" / "skills" / "canary-resource" / "probe.py"
nonce = re.search(r"CANARY:([0-9a-f]+)", probe.read_text()).group(1)
required = (
    "never" not in pathlib.Path(sys.argv[0]).parent.name
    and "SHOULD_USE" in prompt
    and "SHOULD_NOT_USE" not in prompt
)
if required:
    print(json.dumps({
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "python3 .agents/skills/canary-resource/probe.py",
            "aggregated_output": f"CANARY:{nonce}\\n",
            "exit_code": 0,
            "status": "completed",
        },
    }))
print(json.dumps({
    "type": "item.completed",
    "item": {
        "type": "agent_message",
        "text": json.dumps({
            "answer": "complete",
            "resource_nonce": nonce if required else None,
        }),
    },
}))
print(json.dumps({"type": "turn.completed", "usage": {"total_tokens": 10}}))
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)


def _write_passing_config(path: Path) -> None:
    path.write_text(
        """schema_version: cib-check/2
name: deploy-routing
instruction:
  condition: the request contains SHOULD_USE
  placement: skill_description
  policy: strict
cases:
  required:
    - The request contains SHOULD_USE.
  unnecessary:
    - The request contains SHOULD_NOT_USE.
execution:
  backend: direct-codex
  model: test-model
  reasoning_effort: medium
  repetitions: 1
  jobs: 2
  seed: 17
  trial_timeout_seconds: 30
  study_timeout_seconds: 180
thresholds:
  minimum_required_use_rate: 1.0
  minimum_avoided_unnecessary_use_rate: 1.0
  maximum_harness_failure_rate: 0.0
""",
        encoding="utf-8",
    )


def test_v2_check_requires_explicit_trial_and_study_timeouts(tmp_path: Path) -> None:
    config = tmp_path / "cib.yaml"
    _write_passing_config(config)

    parsed = load_check_config(config)

    assert parsed.schema_version == "cib-check/2"
    assert parsed.trial_timeout_seconds == 30
    assert parsed.study_timeout_seconds == 180
    assert parsed.timeout_source == "explicit"
    assert parsed.legacy_warning is None


def test_doctor_with_config_reports_resolved_timeout_contract(tmp_path: Path) -> None:
    config = tmp_path / "cib.yaml"
    auth = tmp_path / "auth.json"
    _write_passing_config(config)
    auth.write_text("{}", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cib.cli",
            "doctor",
            "--config",
            str(config),
            "--auth",
            str(auth),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )

    assert completed.returncode in {0, 2}, completed.stderr
    report = json.loads(completed.stdout)
    assert report["check_timeout_policy"] == {
        "schema_version": "cib-check/2",
        "trial_seconds": 30,
        "study_seconds": 180,
        "source": "explicit",
        "legacy_warning": None,
    }


@pytest.mark.parametrize(
    "arguments",
    (
        ["--trial-timeout-seconds", "0"],
        ["--study-timeout-seconds", "-1"],
        ["--timeout", "0"],
    ),
)
def test_study_cli_rejects_nonpositive_timeouts_before_execution(
    tmp_path: Path, arguments: list[str]
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cib.cli",
            "study",
            "--run-id",
            "invalid-timeout",
            "--output-dir",
            str(tmp_path / "must-not-exist"),
            *arguments,
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "must be a positive integer" in completed.stderr
    assert not (tmp_path / "must-not-exist").exists()


def test_promptfoo_outer_watchdog_produces_invalid_check_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "cib.yaml"
    _write_passing_config(config_path)
    config_value = yaml.safe_load(config_path.read_text())
    config_value["execution"].update(
        {
            "backend": "promptfoo-codex-sdk",
            "trial_timeout_seconds": 30,
            "study_timeout_seconds": 1,
        }
    )
    config_path.write_text(
        yaml.safe_dump(config_value, sort_keys=False), encoding="utf-8"
    )
    project_root = tmp_path / "project"
    binary = project_root / "node_modules" / ".bin" / "promptfoo"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys
import time

output = pathlib.Path(sys.argv[sys.argv.index("--output") + 1])
output.write_bytes(b'{"output":"\\xf0\\x9f')
time.sleep(30)
""",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setattr(
        "cib.checks.inspect_environment",
        lambda *args, **kwargs: {"ready": True, "checks": {}},
    )
    monkeypatch.setattr("cib.workflow.PROMPTFOO_PROCESS_EXIT_GRACE_SECONDS", 0)
    monkeypatch.setattr("cib.workflow.PROMPTFOO_TERMINATION_GRACE_SECONDS", 0)

    result = run_check(
        config=load_check_config(config_path),
        output_dir=output,
        auth_path=auth,
        project_root=project_root,
    )

    assert result["verdict"] == "invalid"
    assert result["exit_code"] == 2
    assert (output / "check-result.json").is_file()
    assert (output / "report" / "report.html").is_file()
    report = json.loads((output / "report" / "report.json").read_text())
    assert report["integrity"]["study_timed_out"] is True
    assert report["integrity"]["study_timeout_count"] == 6
    assert report["run"]["timeouts"]["study_seconds"] == 1


@pytest.mark.parametrize(
    ("backend", "trial_timeout", "study_timeout"),
    (
        ("direct-codex", 30, None),
        ("promptfoo-codex-sdk", None, 30),
    ),
)
def test_v1_check_preserves_backend_dependent_timeout_semantics(
    tmp_path: Path,
    backend: str,
    trial_timeout: int | None,
    study_timeout: int | None,
) -> None:
    config = tmp_path / "cib.yaml"
    _write_passing_config(config)
    value = yaml.safe_load(config.read_text())
    value["schema_version"] = "cib-check/1"
    value["execution"]["backend"] = backend
    value["execution"].pop("trial_timeout_seconds")
    value["execution"].pop("study_timeout_seconds")
    value["execution"]["timeout_seconds"] = 30
    config.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

    parsed = load_check_config(config)

    assert parsed.schema_version == "cib-check/1"
    assert parsed.trial_timeout_seconds == trial_timeout
    assert parsed.study_timeout_seconds == study_timeout
    assert parsed.timeout_source == "legacy_cib_check_1"
    assert "deprecated" in parsed.legacy_warning.lower()


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_trial",
        "missing_study",
        "mixed_legacy",
        "boolean_trial",
        "zero_study",
    ),
)
def test_v2_check_rejects_incomplete_mixed_or_invalid_timeouts(
    tmp_path: Path, mutation: str
) -> None:
    config = tmp_path / "cib.yaml"
    _write_passing_config(config)
    value = yaml.safe_load(config.read_text())
    execution = value["execution"]
    if mutation == "missing_trial":
        execution.pop("trial_timeout_seconds")
    elif mutation == "missing_study":
        execution.pop("study_timeout_seconds")
    elif mutation == "mixed_legacy":
        execution["timeout_seconds"] = 30
    elif mutation == "boolean_trial":
        execution["trial_timeout_seconds"] = True
    else:
        execution["study_timeout_seconds"] = 0
    config.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

    with pytest.raises(CheckConfigError):
        load_check_config(config)


def test_check_runs_one_user_config_and_writes_one_plain_english_decision(
    tmp_path: Path,
) -> None:
    config = tmp_path / "cib.yaml"
    output = tmp_path / "check-output"
    auth = tmp_path / "auth.json"
    bin_dir = tmp_path / "bin"
    _write_passing_config(config)
    _write_fake_codex(bin_dir)
    auth.write_text("{}", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cib.cli",
            "check",
            str(config),
            "--output-dir",
            str(output),
            "--auth",
            str(auth),
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("PASS — ")
    assert "Required use: 100.0% (minimum 100.0%)" in completed.stdout
    assert "Avoided unnecessary use: 100.0% (minimum 100.0%)" in completed.stdout
    assert str(tmp_path) not in completed.stdout + completed.stderr
    result = json.loads((output / "check-result.json").read_text())
    assert result == {
        "schema_version": "cib-check-result/1",
        "name": "deploy-routing",
        "verdict": "pass",
        "exit_code": 0,
        "headline": "The instruction met both routing thresholds.",
        "required_use": {"rate": 1.0, "threshold": 1.0, "passed": True},
        "avoided_unnecessary_use": {
            "rate": 1.0,
            "threshold": 1.0,
            "passed": True,
        },
        "harness_failures": {"rate": 0.0, "threshold": 0.0, "passed": True},
        "integrity_passed": True,
        "evidence_strength": "smoke_only",
        "report_json": "report/report.json",
        "report_markdown": "report/report.md",
        "report_html": "report/report.html",
    }
    report = json.loads((output / "report" / "report.json").read_text())
    assert report["decision"] == {
        key: result[key]
        for key in (
            "name",
            "verdict",
            "headline",
            "required_use",
            "avoided_unnecessary_use",
            "harness_failures",
            "integrity_passed",
            "evidence_strength",
        )
    }
    markdown = (output / "report" / "report.md").read_text()
    html = (output / "report" / "report.html").read_text()
    assert markdown.index("# PASS") < markdown.index("<summary>Method and evidence</summary>")
    assert "The instruction met both routing thresholds." in markdown
    assert "**Evidence integrity:** **PASS**" in markdown
    assert "**Harness failures:** 0.0% (maximum 0.0%) — **PASS**" in markdown
    assert html.index("<h1>PASS</h1>") < html.index(
        "<summary>Method and evidence</summary>"
    )
    assert "The instruction met both routing thresholds." in html
    assert "<strong>Evidence integrity:</strong>" in html
    assert ">PASS</span>" in html
    assert "maximum 0.0% · PASS" in html
    public_output = (
        completed.stdout
        + completed.stderr
        + json.dumps(result)
        + json.dumps(report)
        + markdown
        + html
    )
    assert "SHOULD_USE" not in public_output
    assert "SHOULD_NOT_USE" not in public_output
    private_config = (output / "check-config.private.yaml").read_text()
    assert "SHOULD_USE" in private_config


def test_check_returns_one_when_valid_evidence_fails_a_threshold(
    tmp_path: Path,
) -> None:
    config = tmp_path / "cib.yaml"
    output = tmp_path / "check-output"
    auth = tmp_path / "auth.json"
    bin_dir = tmp_path / "never-bin"
    _write_passing_config(config)
    _write_fake_codex(bin_dir)
    auth.write_text("{}", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cib.cli",
            "check",
            str(config),
            "--output-dir",
            str(output),
            "--auth",
            str(auth),
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1, completed.stderr
    assert completed.stdout.startswith("FAIL — ")
    assert "The required action did not happen often enough." in completed.stdout
    result = json.loads((output / "check-result.json").read_text())
    assert result["verdict"] == "fail"
    assert result["exit_code"] == 1
    assert result["integrity_passed"] is True
    assert result["required_use"] == {
        "rate": 0.0,
        "threshold": 1.0,
        "passed": False,
    }
    assert (output / "report" / "report.html").is_file()


def test_check_rejects_unknown_config_before_model_calls_without_echoing_values(
    tmp_path: Path,
) -> None:
    config = tmp_path / "cib.yaml"
    output = tmp_path / "check-output"
    auth = tmp_path / "auth.json"
    bin_dir = tmp_path / "bin"
    _write_passing_config(config)
    sensitive_value = "/" + "Users/example/private-check"
    config.write_text(
        config.read_text() + f"unexpected_field: {sensitive_value}\n",
        encoding="utf-8",
    )
    _write_fake_codex(bin_dir)
    auth.write_text("{}", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cib.cli",
            "check",
            str(config),
            "--output-dir",
            str(output),
            "--auth",
            str(auth),
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "Configuration fields are incomplete or unknown" in completed.stderr
    assert sensitive_value not in completed.stdout + completed.stderr
    assert not (bin_dir / "model-called").exists()
    assert not output.exists()


def test_check_rejects_unsafe_public_metadata_before_writing_output(
    tmp_path: Path,
) -> None:
    config = tmp_path / "cib.yaml"
    output = tmp_path / "check-output"
    auth = tmp_path / "auth.json"
    bin_dir = tmp_path / "bin"
    _write_passing_config(config)
    sensitive_value = "/" + "Users/example/private-model"
    parsed = yaml.safe_load(config.read_text())
    parsed["execution"]["model"] = sensitive_value
    config.write_text(yaml.safe_dump(parsed, sort_keys=False), encoding="utf-8")
    _write_fake_codex(bin_dir)
    auth.write_text("{}", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cib.cli",
            "check",
            str(config),
            "--output-dir",
            str(output),
            "--auth",
            str(auth),
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "Model is unsafe for public evidence" in completed.stderr
    assert sensitive_value not in completed.stdout + completed.stderr
    assert not (bin_dir / "model-called").exists()
    assert not output.exists()


def test_check_refuses_output_reuse_before_model_calls(tmp_path: Path) -> None:
    config = tmp_path / "cib.yaml"
    output = tmp_path / "check-output"
    auth = tmp_path / "auth.json"
    bin_dir = tmp_path / "bin"
    _write_passing_config(config)
    _write_fake_codex(bin_dir)
    auth.write_text("{}", encoding="utf-8")
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("user-owned", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cib.cli",
            "check",
            str(config),
            "--output-dir",
            str(output),
            "--auth",
            str(auth),
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "Refusing to reuse check output directory" in completed.stderr
    assert sentinel.read_text() == "user-owned"
    assert not (bin_dir / "model-called").exists()


def test_check_materializes_every_pair_and_repetition_for_all_policies(
    tmp_path: Path,
) -> None:
    config = tmp_path / "cib.yaml"
    output = tmp_path / "check-output"
    auth = tmp_path / "auth.json"
    bin_dir = tmp_path / "bin"
    _write_passing_config(config)
    parsed = yaml.safe_load(config.read_text())
    parsed["cases"] = {
        "required": ["First SHOULD_USE case.", "Second SHOULD_USE case."],
        "unnecessary": [
            "First SHOULD_NOT_USE case.",
            "Second SHOULD_NOT_USE case.",
        ],
    }
    parsed["execution"]["repetitions"] = 2
    parsed["execution"]["jobs"] = 4
    config.write_text(yaml.safe_dump(parsed, sort_keys=False), encoding="utf-8")
    _write_fake_codex(bin_dir)
    auth.write_text("{}", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cib.cli",
            "check",
            str(config),
            "--output-dir",
            str(output),
            "--auth",
            str(auth),
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    rows = [
        json.loads(line)
        for line in (output / "run-manifest.private.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 24
    assert {row["arm"] for row in rows} == {"if", "iff", "if_else_not"}
    assert {row["condition_true"] for row in rows} == {True, False}
    assert {row["case_variant"] for row in rows} == {0, 1, 2, 3}
    report = json.loads((output / "report" / "report.json").read_text())
    assert {cell["n"] for cell in report["cells"]} == {4}


def test_decision_fails_when_a_mandatory_control_arm_has_harness_failure() -> None:
    report = {
        "integrity": {
            "passed": True,
            "result_rows": 4,
            "harness_failures": 1,
        },
        "cells": [
            {
                "arm": "iff",
                "placement": "skill_description",
                "condition_true": True,
                "rate": 1.0,
                "n": 1,
                "harness_failures": 0,
            },
            {
                "arm": "iff",
                "placement": "skill_description",
                "condition_true": False,
                "rate": 1.0,
                "n": 1,
                "harness_failures": 0,
            },
            {
                "arm": "if",
                "placement": "skill_description",
                "condition_true": True,
                "rate": 0.0,
                "n": 1,
                "harness_failures": 1,
            },
        ],
    }
    metadata = {
        "name": "selected-policy-only",
        "policy": "strict",
        "placement": "skill_description",
        "thresholds": {
            "minimum_required_use_rate": 1.0,
            "minimum_avoided_unnecessary_use_rate": 1.0,
            "maximum_harness_failure_rate": 0.0,
        },
    }

    decision = build_product_decision(report, metadata)

    assert decision["verdict"] == "fail"
    assert decision["harness_failures"] == {
        "rate": 0.25,
        "threshold": 0.0,
        "passed": False,
    }


def test_composite_action_runs_check_and_uploads_only_public_artifacts() -> None:
    root = Path(__file__).parents[1]
    action = yaml.safe_load((root / "action.yml").read_text())

    assert action["runs"]["using"] == "composite"
    assert set(action["inputs"]) == {
        "config",
        "openai-api-key",
        "artifact-name",
        "retention-days",
    }
    assert set(action["outputs"]) == {
        "verdict",
        "exit-code",
        "report-path",
        "report-artifact",
    }
    steps = action["runs"]["steps"]
    pinned_uses = [step["uses"] for step in steps if "uses" in step]
    assert pinned_uses
    assert all("@" in value and len(value.rsplit("@", 1)[1]) == 40 for value in pinned_uses)
    serialized = (root / "action.yml").read_text()
    assert "codex-auth-json" not in serialized
    assert "login --with-api-key" in serialized
    assert "uv sync --frozen --no-dev" in serialized
    assert 'npm install --global --prefix "${tool_root}" @openai/codex@0.144.5' in serialized
    assert 'test "$("${codex_bin}" --version)" = "codex-cli 0.144.5"' in serialized
    assert '"${CIB_CODEX_BIN}" login --with-api-key' in serialized
    check_step = next(step for step in steps if step.get("id") == "check")
    assert check_step["if"] == "always()"
    assert "cib check" in check_step["run"]
    assert 'mktemp -d "${RUNNER_TEMP}/cib-check-output-XXXXXX"' in check_step["run"]
    assert "candidate_status == raw_status" in check_step["run"]
    assert "report-path=" in check_step["run"]
    assert 'report_path = result["report_html"]' in check_step["run"]
    assert "result_path.parent / result" not in check_step["run"]
    assert "status = 2" in check_step["run"]
    assert 'expected_status = {"pass": 0, "fail": 1, "invalid": 2}' in check_step["run"]
    upload = next(
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    uploaded_paths = upload["with"]["path"]
    assert "check-result.json" in uploaded_paths
    assert "/report" in uploaded_paths
    assert "/promptfoo" not in uploaded_paths
    assert "/direct" not in uploaded_paths
    assert "private" not in uploaded_paths
    final_gate = steps[-1]
    assert final_gate["if"] == "always()"
    assert 'case "${CIB_EXIT_CODE:-2}"' in final_gate["run"]
    assert "*) exit 2" in final_gate["run"]


def test_hosted_ci_exercises_the_local_composite_action_without_model_quota() -> None:
    root = Path(__file__).parents[1]
    workflow = (root / ".github" / "workflows" / "action-smoke.yml").read_text()

    assert "uses: ./" in workflow
    assert "tests/fixtures/action/cib.yaml" in workflow
    assert "tests/fixtures/action/fake-npm" in workflow
    assert "npm_path=\"$(command -v npm)\"" in workflow
    assert 'npm@11.11.1' in workflow
    assert 'mv "${npm_path}" "${npm_path}.cib-original"' in workflow
    assert 'openai-api-key: "fixture-api-key"' in workflow
    assert 'steps.cib.outputs.verdict == \'pass\'' in workflow
    assert "steps.cib.outputs.report-path" in workflow
    assert 'test -f "${CIB_ACTION_OUTPUT_ROOT}/${CIB_REPORT_PATH}"' in workflow
    assert "id: cib_second" in workflow
    assert "cib-first-output-root" in workflow
