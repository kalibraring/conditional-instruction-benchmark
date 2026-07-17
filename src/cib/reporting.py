from __future__ import annotations

import hashlib
import html
import json
import math
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from . import __version__
from .analysis import CONTRASTS, task_weighted_difference, wilson_interval


REPORT_SCHEMA_VERSION = "cib-report/1"
ARMS = ("if", "iff", "if_else_not")
IDENTITY_FIELDS = (
    "random_order",
    "arm",
    "condition_true",
    "case_id",
    "case_variant",
    "placement",
)
BACKEND_LAYOUTS = {
    "direct-codex": ("direct/summary.json", "direct/audit.json"),
    "promptfoo-codex-sdk": (
        "promptfoo/derived/summary.json",
        "promptfoo/derived/audit.json",
    ),
}
UNSAFE_PUBLIC_TEXT = re.compile(
    r"(?:(?:github_pat_|gh[opsu]_)[A-Za-z0-9_]{20,}|"
    r"\bsk-[A-Za-z0-9_-]{20,}|BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY|"
    r"\bAKIA[0-9A-Z]{16}\b)"
)
ABSOLUTE_PATH_FRAGMENT = re.compile(
    r"(?:^|[^A-Za-z0-9_.~+/\\-])"
    r"(?:/{1,3}[A-Za-z0-9_.~+-]|[A-Za-z]:[\\/])"
)
PUBLIC_TEXT_FIELDS = (
    "run_id",
    "trial_id",
    "block_id",
    "arm",
    "case_id",
    "placement",
    "model",
    "reasoning_effort",
    "target_adapter",
    "protocol_version",
    "profile",
)


class ReportValidationError(ValueError):
    """A validation failure whose message is safe to show on the CLI."""


def write_report(run_dir: Path, output_dir: Path | None = None) -> dict[str, str]:
    run_dir = run_dir.resolve()
    target = (output_dir or run_dir / "report").resolve()
    if target.exists():
        raise FileExistsError("Refusing to replace report directory")
    report = build_report(run_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        (temporary / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        (temporary / "report.md").write_text(render_markdown(report), encoding="utf-8")
        (temporary / "report.html").write_text(render_html(report), encoding="utf-8")
        temporary.replace(target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    display_base = target if output_dir is not None else run_dir
    return {
        "run_id": str(report["run"]["run_id"]),
        "report_json": _display_path(target / "report.json", display_base),
        "report_markdown": _display_path(target / "report.md", display_base),
        "report_html": _display_path(target / "report.html", display_base),
    }


def build_report(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "run-manifest.jsonl"
    study_path = run_dir / "study-result.json"
    manifest = _load_manifest(manifest_path, run_dir)
    study = _load_json(study_path, run_dir)
    backend = _single_value(manifest, "target_adapter")
    if backend not in BACKEND_LAYOUTS:
        raise ReportValidationError("Unsupported report backend")
    summary_name, audit_name = BACKEND_LAYOUTS[backend]
    summary_path = run_dir / summary_name
    audit_path = run_dir / audit_name
    summary = _load_json(summary_path, run_dir)
    audit = _load_json(audit_path, run_dir)
    if (
        not isinstance(study, dict)
        or not isinstance(summary, list)
        or not isinstance(audit, dict)
    ):
        raise ReportValidationError("Study summary or audit has an invalid shape")
    if audit != study.get("audit"):
        raise ReportValidationError("Study result and canonical audit disagree")

    manifest_ids = [str(row["trial_id"]) for row in manifest]
    summary_ids = [str(row.get("trial_id")) for row in summary]
    _require_unique(manifest_ids, "public manifest")
    _require_unique(summary_ids, "derived summary")
    if set(manifest_ids) != set(summary_ids):
        raise ReportValidationError("Manifest and summary trial IDs disagree")

    outcomes = {str(row["trial_id"]): row for row in summary}
    for manifest_row in manifest:
        trial_id = str(manifest_row["trial_id"])
        summary_row = outcomes[trial_id]
        disagreements = [
            field
            for field in IDENTITY_FIELDS
            if summary_row.get(field) != manifest_row.get(field)
        ]
        if disagreements:
            raise ReportValidationError(
                "Manifest and summary assignment fields disagree"
            )
    execution = study.get("execution") or {}
    run_id = _single_value(manifest, "run_id")
    if execution.get("run_id") != run_id:
        raise ReportValidationError(
            "Study result and public manifest run IDs disagree"
        )
    if int(execution.get("trial_count", -1)) != len(manifest):
        raise ReportValidationError(
            "Study result trial count disagrees with public manifest"
        )
    if int(audit.get("result_rows", -1)) != len(summary):
        raise ReportValidationError("Audit result count disagrees with derived summary")
    if int(audit.get("unique_trial_ids", -1)) != len(set(summary_ids)):
        raise ReportValidationError(
            "Audit identity count disagrees with derived summary"
        )
    for summary_row in summary:
        _require_boolean(summary_row, "behavioral_success")
        _require_boolean(summary_row, "harness_failure")
    rows = [
        {
            "trial_id": row["trial_id"],
            "arm": row["arm"],
            "condition_true": row["condition_true"],
            "case_id": row["case_id"],
            "placement": row["placement"],
            "success": outcomes[str(row["trial_id"])]["behavioral_success"],
            "harness_failure": outcomes[str(row["trial_id"])]["harness_failure"],
        }
        for row in manifest
    ]
    cases = sorted({str(row["case_id"]) for row in rows})
    cells = _cells(rows)
    contrasts = _contrasts(rows, cases)
    block_count = len({str(row["block_id"]) for row in manifest})
    placements = sorted({str(row["placement"]) for row in rows})
    orders = sorted(int(row["random_order"]) for row in manifest)
    complete_permutation = orders == list(range(len(manifest)))
    integrity = _recompute_integrity(audit, rows, summary, backend)
    is_smoke = (
        len(rows) == 6
        and len(cases) == 1
        and len(placements) == 1
        and block_count == 1
        and len(cells) == 6
        and all(cell["n"] == 1 for cell in cells)
        and complete_permutation
        and integrity["passed"]
    )
    claim = {
        "status": "exploratory_smoke" if is_smoke else "descriptive_only",
        "statement": (
            "This six-cell onboarding run proves the execution and evidence path, "
            "not that one instruction form is generally superior."
            if is_smoke
            else "This report is descriptive. Confirmatory claims require a frozen "
            "preregistration and its declared inference procedure."
        ),
        "contrast_note": (
            "Contrasts use equal task-family weighting and are descriptive. The "
            "six-trial smoke design does not support a general causal claim."
            if is_smoke
            else "Contrasts use equal task-family weighting and remain descriptive. "
            "Confirmatory interpretation requires the run's preregistered inference "
            "and missingness policy."
        ),
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "protocol_version": _single_value(manifest, "protocol_version"),
            "profile": _single_value(manifest, "profile"),
            "backend": backend,
            "model": _single_value(manifest, "model"),
            "reasoning_effort": _single_value(manifest, "reasoning_effort"),
            "trial_count": len(rows),
            "task_families": len(cases),
            "cases": [
                {
                    "case_id": case_id,
                    "variants": sorted(
                        {
                            int(row["case_variant"])
                            for row in manifest
                            if row["case_id"] == case_id
                        }
                    ),
                }
                for case_id in cases
            ],
            "placements": placements,
            "blocks": block_count,
            "block_ids": sorted({str(row["block_id"]) for row in manifest}),
            "randomization": {
                "orders": orders,
                "complete_permutation": complete_permutation,
            },
            "duration_seconds": execution.get("duration_seconds"),
        },
        "integrity": integrity,
        "claim": claim,
        "cells": cells,
        "contrasts": contrasts,
        "provenance": {
            "generator_version": __version__,
            "sources": {
                "run-manifest.jsonl": _sha256(manifest_path, run_dir),
                _relative_source(run_dir, summary_path): _sha256(
                    summary_path, run_dir
                ),
                _relative_source(run_dir, audit_path): _sha256(audit_path, run_dir),
                "study-result.json": _sha256(study_path, run_dir),
            },
            "privacy_boundary": (
                "Generated only from the public manifest, canonical derived summary, "
                "integrity audit, and sanitized study metadata."
            ),
        },
    }


def _load_manifest(path: Path, run_dir: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in _read_source(path, run_dir).splitlines()
        if line.strip()
    ]
    if not rows:
        raise ReportValidationError("Public manifest is empty")
    required = {
        "run_id",
        "trial_id",
        "block_id",
        "arm",
        "condition_true",
        "case_id",
        "placement",
        "model",
        "reasoning_effort",
        "target_adapter",
        "protocol_version",
        "profile",
    }
    for row in rows:
        if "nonce" in row:
            raise ReportValidationError(
                "Public manifest unexpectedly contains a raw nonce"
            )
        missing = sorted(required - set(row))
        if missing:
            raise ReportValidationError(
                f"Public manifest row is missing fields: {missing}"
            )
        for field in PUBLIC_TEXT_FIELDS:
            _validate_public_text(str(row[field]), field)
        _require_boolean(row, "condition_true")
        if row["arm"] not in ARMS:
            raise ReportValidationError("Unsupported instruction arm")
    return rows


def _load_json(path: Path, run_dir: Path) -> Any:
    return json.loads(_read_source(path, run_dir))


def _single_value(rows: list[dict[str, Any]], key: str) -> Any:
    values = {json.dumps(row[key], sort_keys=True) for row in rows}
    if len(values) != 1:
        raise ReportValidationError(
            f"Public manifest contains multiple {key} values"
        )
    return json.loads(next(iter(values)))


def _require_unique(values: list[str], source: str) -> None:
    if len(values) != len(set(values)):
        raise ReportValidationError(f"Duplicate trial ID in {source}")


def _require_boolean(row: dict[str, Any], field: str) -> None:
    if type(row.get(field)) is not bool:
        raise ReportValidationError(f"{field} must be a boolean")


def _recompute_integrity(
    audit: dict[str, Any],
    rows: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    backend: str,
) -> dict[str, Any]:
    summary_ids = [str(row["trial_id"]) for row in summary]
    behavioral_successes = sum(row["success"] for row in rows)
    harness_failures = sum(row["harness_failure"] for row in rows)
    if (
        _audit_int(audit, "behavioral_successes") != behavioral_successes
        or _audit_int(audit, "harness_failures") != harness_failures
    ):
        raise ReportValidationError(
            "Audit outcome counts disagree with derived summary"
        )
    common_passed = (
        _audit_int(audit, "result_rows") == len(rows)
        and _audit_int(audit, "unique_trial_ids") == len(set(summary_ids))
    )
    if backend == "promptfoo-codex-sdk":
        audited_scorer_disagreements = _audit_list(
            audit, "promptfoo_cib_disagreements"
        )
        identity_disagreements = _audit_list(
            audit, "archive_identity_disagreements"
        )
        for summary_row in summary:
            _require_boolean(summary_row, "promptfoo_success")
        session_ids = [row.get("session_id") for row in summary]
        unique_session_ids = len(
            {session_id for session_id in session_ids if session_id}
        )
        scorer_disagreements = sum(
            row["promptfoo_success"] != row["behavioral_success"]
            for row in summary
        )
        if _audit_int(audit, "unique_session_ids") != unique_session_ids:
            raise ReportValidationError(
                "Audit session count disagrees with derived summary"
            )
        if len(audited_scorer_disagreements) != scorer_disagreements:
            raise ReportValidationError(
                "Audit scorer disagreements disagree with derived summary"
            )
        backend_passed = all(
            (
                _audit_int(audit, "duplicate_trial_ids") == 0,
                _audit_int(audit, "protected_raw_files") == len(rows),
                _audit_int(audit, "protected_source_rows") == len(rows),
                unique_session_ids == len(rows),
                not _audit_list(audit, "missing_protected_raw"),
                not _audit_list(audit, "unexpected_protected_raw"),
                scorer_disagreements == 0,
                not identity_disagreements,
            )
        )
    elif backend == "direct-codex":
        scorer_disagreements = 0
        identity_disagreements = []
        backend_passed = _audit_int(audit, "raw_files") == len(rows)
    else:
        raise ReportValidationError("Unsupported report backend")
    recomputed_passed = common_passed and backend_passed
    _require_boolean(audit, "passed")
    if audit["passed"] is not recomputed_passed:
        raise ReportValidationError(
            "Audit passed status disagrees with recomputed integrity"
        )
    return {
        "passed": recomputed_passed,
        "result_rows": len(rows),
        "unique_trial_ids": len(set(summary_ids)),
        "behavioral_successes": behavioral_successes,
        "harness_failures": harness_failures,
        "scorer_disagreements": scorer_disagreements,
        "identity_disagreements": len(identity_disagreements),
    }


def _audit_int(audit: dict[str, Any], field: str) -> int:
    value = audit.get(field)
    if type(value) is not int:
        raise ReportValidationError(f"Audit field {field} must be an integer")
    return value


def _audit_list(audit: dict[str, Any], field: str) -> list[Any]:
    value = audit.get(field)
    if not isinstance(value, list):
        raise ReportValidationError(f"Audit field {field} must be a list")
    return value


def _cells(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for placement in sorted({str(row["placement"]) for row in rows}):
        for truth in (True, False):
            for arm in ARMS:
                members = [
                    row
                    for row in rows
                    if row["placement"] == placement
                    and row["arm"] == arm
                    and row["condition_true"] is truth
                ]
                if not members:
                    continue
                successes = sum(row["success"] for row in members)
                low, high = wilson_interval(successes, len(members))
                output.append(
                    {
                        "placement": placement,
                        "estimand": (
                            "necessary_use" if truth else "avoided_unnecessary_use"
                        ),
                        "condition_true": truth,
                        "arm": arm,
                        "n": len(members),
                        "successes": successes,
                        "rate": successes / len(members),
                        "wilson_low": low,
                        "wilson_high": high,
                        "harness_failures": sum(
                            row["harness_failure"] for row in members
                        ),
                    }
                )
    return output


def _contrasts(
    rows: list[dict[str, Any]], cases: list[str]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for placement in sorted({str(row["placement"]) for row in rows}):
        for truth in (True, False):
            subset = [
                row
                for row in rows
                if row["placement"] == placement
                and row["condition_true"] is truth
            ]
            for name, treatment, reference in CONTRASTS:
                eligible = [
                    case_id
                    for case_id in cases
                    if any(
                        row["case_id"] == case_id and row["arm"] == treatment
                        for row in subset
                    )
                    and any(
                        row["case_id"] == case_id and row["arm"] == reference
                        for row in subset
                    )
                ]
                difference = task_weighted_difference(
                    subset, eligible, treatment, reference
                )
                output.append(
                    {
                        "placement": placement,
                        "estimand": (
                            "necessary_use" if truth else "avoided_unnecessary_use"
                        ),
                        "condition_true": truth,
                        "contrast": name,
                        "treatment": treatment,
                        "reference": reference,
                        "risk_difference": (
                            None if math.isnan(difference) else difference
                        ),
                        "task_families": len(eligible),
                        "missing_task_families": sorted(set(cases) - set(eligible)),
                        "inference": "descriptive_task_family_weighted",
                    }
                )
    return output


def render_markdown(report: dict[str, Any]) -> str:
    run = report["run"]
    integrity = report["integrity"]
    lines = [
        "# Conditional Instruction Benchmark report",
        "",
        f"Run: `{run['run_id']}`  ",
        f"Protocol: `{run['protocol_version']}` · Profile: `{run['profile']}`  ",
        f"Backend: `{run['backend']}`  ",
        f"Model: `{run['model']}` · Reasoning: `{run['reasoning_effort']}`  ",
        f"Placement(s): {', '.join(f'`{value}`' for value in run['placements'])}  ",
        f"Task families: {_case_summary(run['cases'])}  ",
        f"Blocks: {run['blocks']} · Randomization complete: "
        f"{'yes' if run['randomization']['complete_permutation'] else 'no'}  ",
        f"Duration: {_duration(run['duration_seconds'])}  ",
        f"Trials: {run['trial_count']} across {run['task_families']} task family/families",
        "",
        "## Claim boundary",
        "",
        f"**{report['claim']['status']}** — {report['claim']['statement']}",
        "",
        "## Evidence integrity",
        "",
        f"Audit passed: **{'yes' if integrity['passed'] else 'no'}**  ",
        f"Unique trials: {integrity['unique_trial_ids']}  ",
        f"Harness failures: {integrity['harness_failures']}  ",
        f"Scorer disagreements: {integrity['scorer_disagreements']}  ",
        f"Identity disagreements: {integrity['identity_disagreements']}",
        "",
        "## Outcomes",
        "",
        "| Placement | Estimand | Arm | Success | Rate | 95% Wilson interval | Harness failures |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for cell in report["cells"]:
        lines.append(
            f"| `{cell['placement']}` | {_label(cell['estimand'])} | `{cell['arm']}` | "
            f"{cell['successes']}/{cell['n']} | {_percent(cell['rate'])} | "
            f"{_percent(cell['wilson_low'])}–{_percent(cell['wilson_high'])} | "
            f"{cell['harness_failures']} |"
        )
    lines.extend(
        [
            "",
            "## Descriptive contrasts",
            "",
            "| Placement | Estimand | Contrast | Risk difference | Task families | Missing families |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for contrast in report["contrasts"]:
        lines.append(
            f"| `{contrast['placement']}` | {_label(contrast['estimand'])} | `{contrast['treatment']} − "
            f"{contrast['reference']}` | {_signed_percent(contrast['risk_difference'])} | "
            f"{contrast['task_families']} | {_missing_markdown(contrast['missing_task_families'])} |"
        )
    lines.extend(
        [
            "",
            report["claim"]["contrast_note"],
            "",
            "## Reproducibility",
            "",
        ]
    )
    for source, digest in report["provenance"]["sources"].items():
        lines.append(f"- `{source}`: `{digest}`")
    lines.extend(["", report["provenance"]["privacy_boundary"], ""])
    return "\n".join(lines)


def render_html(report: dict[str, Any]) -> str:
    outcome_rows = []
    for cell in report["cells"]:
        outcome_rows.append(
            "<tr>"
            f"<td><code>{html.escape(cell['placement'])}</code></td>"
            f"<td>{html.escape(_label(cell['estimand']))}</td>"
            f"<td><code>{html.escape(cell['arm'])}</code></td>"
            f"<td>{cell['successes']}/{cell['n']}</td>"
            f"<td>{_percent(cell['rate'])}</td>"
            f"<td>{_percent(cell['wilson_low'])}–{_percent(cell['wilson_high'])}</td>"
            f"<td>{cell['harness_failures']}</td>"
            "</tr>"
        )
    contrast_rows = []
    for contrast in report["contrasts"]:
        contrast_rows.append(
            "<tr>"
            f"<td><code>{html.escape(contrast['placement'])}</code></td>"
            f"<td>{html.escape(_label(contrast['estimand']))}</td>"
            f"<td><code>{html.escape(contrast['treatment'])} − "
            f"{html.escape(contrast['reference'])}</code></td>"
            f"<td>{_signed_percent(contrast['risk_difference'])}</td>"
            f"<td>{contrast['task_families']}</td>"
            f"<td>{html.escape(_missing_text(contrast['missing_task_families']))}</td>"
            "</tr>"
        )
    sources = "".join(
        f"<li><code>{html.escape(source)}</code>: <code>{html.escape(digest)}</code></li>"
        for source, digest in report["provenance"]["sources"].items()
    )
    run = report["run"]
    integrity = report["integrity"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CIB report — {html.escape(str(run['run_id']))}</title>
<style>
:root {{ color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
body {{ max-width: 72rem; margin: 0 auto; padding: 2rem; line-height: 1.55; }}
h1, h2 {{ line-height: 1.2; }}
.meta, .callout {{ padding: 1rem; border: 1px solid #8886; border-radius: .6rem; background: #8881; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
th, td {{ border-bottom: 1px solid #8886; padding: .55rem; text-align: left; }}
code {{ overflow-wrap: anywhere; }}
.pass {{ color: #16803a; font-weight: 700; }}
</style>
</head>
<body>
<main>
<h1>Conditional Instruction Benchmark report</h1>
<div class="meta"><strong>Run:</strong> <code>{html.escape(str(run['run_id']))}</code><br>
<strong>Protocol:</strong> <code>{html.escape(str(run['protocol_version']))}</code> · <strong>Profile:</strong> <code>{html.escape(str(run['profile']))}</code><br>
<strong>Backend:</strong> <code>{html.escape(str(run['backend']))}</code><br>
<strong>Model:</strong> <code>{html.escape(str(run['model']))}</code> · <strong>Reasoning:</strong> <code>{html.escape(str(run['reasoning_effort']))}</code><br>
<strong>Placement(s):</strong> {', '.join(f'<code>{html.escape(value)}</code>' for value in run['placements'])}<br>
<strong>Task families:</strong> {html.escape(_case_summary(run['cases']))}<br>
<strong>Blocks:</strong> {run['blocks']} · <strong>Randomization complete:</strong> {'yes' if run['randomization']['complete_permutation'] else 'no'} · <strong>Duration:</strong> {html.escape(_duration(run['duration_seconds']))}<br>
<strong>Trials:</strong> {run['trial_count']} across {run['task_families']} task family/families</div>
<h2>Claim boundary</h2>
<p class="callout"><strong>{html.escape(report['claim']['status'])}</strong> — {html.escape(report['claim']['statement'])}</p>
<h2>Evidence integrity</h2>
<p>Audit passed: <span class="pass">{'yes' if integrity['passed'] else 'no'}</span> ·
Unique trials: {integrity['unique_trial_ids']} · Harness failures: {integrity['harness_failures']} ·
Scorer disagreements: {integrity['scorer_disagreements']} · Identity disagreements: {integrity['identity_disagreements']}</p>
<h2>Outcomes</h2>
<table><thead><tr><th>Placement</th><th>Estimand</th><th>Arm</th><th>Success</th><th>Rate</th><th>95% Wilson interval</th><th>Harness failures</th></tr></thead>
<tbody>{''.join(outcome_rows)}</tbody></table>
<h2>Descriptive contrasts</h2>
<table><thead><tr><th>Placement</th><th>Estimand</th><th>Contrast</th><th>Risk difference</th><th>Task families</th><th>Missing families</th></tr></thead>
<tbody>{''.join(contrast_rows)}</tbody></table>
<p>{html.escape(report['claim']['contrast_note'])}</p>
<h2>Reproducibility</h2>
<ul>{sources}</ul>
<p>{html.escape(report['provenance']['privacy_boundary'])}</p>
</main>
</body>
</html>
"""


def _read_source(path: Path, run_dir: Path) -> str:
    validated = _validated_source(path, run_dir)
    try:
        return validated.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ReportValidationError(
            "Canonical report input must be UTF-8 text"
        ) from error


def _validated_source(path: Path, run_dir: Path) -> Path:
    try:
        relative = path.relative_to(run_dir)
    except ValueError as error:
        raise ReportValidationError(
            "Canonical report input is outside the study directory"
        ) from error
    cursor = run_dir
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ReportValidationError(
                "Canonical report input must not be a symlink"
            )
    if not path.is_file():
        raise ReportValidationError("Canonical report input is missing")
    try:
        path.resolve(strict=True).relative_to(run_dir)
    except (FileNotFoundError, ValueError) as error:
        raise ReportValidationError(
            "Canonical report input is outside the study directory"
        ) from error
    return path


def _sha256(path: Path, run_dir: Path) -> str:
    return hashlib.sha256(_validated_source(path, run_dir).read_bytes()).hexdigest()


def _relative_source(run_dir: Path, path: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def _display_path(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def _validate_public_text(value: str, field: str) -> None:
    if (
        any(ord(character) < 32 for character in value)
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ABSOLUTE_PATH_FRAGMENT.search(value)
        or UNSAFE_PUBLIC_TEXT.search(value)
    ):
        raise ReportValidationError(
            f"Unsafe text in public manifest field {field}"
        )


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _signed_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1%}"


def _label(value: str) -> str:
    return value.replace("_", " ").title()


def _missing_markdown(values: list[str]) -> str:
    return "none" if not values else ", ".join(f"`{value}`" for value in values)


def _missing_text(values: list[str]) -> str:
    return "none" if not values else ", ".join(values)


def _case_summary(cases: list[dict[str, Any]]) -> str:
    return ", ".join(
        f"{case['case_id']} (variant(s) {', '.join(str(value) for value in case['variants'])})"
        for case in cases
    )


def _duration(value: float | int | None) -> str:
    return "n/a" if value is None else f"{float(value):.1f}s"
