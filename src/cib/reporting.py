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
from .product_decision import POLICY_ARMS, build_product_decision


REPORT_SCHEMA_VERSION = "cib-report/1"
TIMEOUT_POLICY_SCHEMA_VERSION = "cib-timeout-policy/2"
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
UNC_PATH_FRAGMENT = re.compile(
    r"(?:^|[^A-Za-z0-9_.~+/\\-])"
    r"\\\\[A-Za-z0-9_.~-]+\\[A-Za-z0-9_.~-]+"
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
    if not isinstance(execution, dict):
        raise ReportValidationError("Study execution metadata has an invalid shape")
    timeout_policy = _load_timeout_policy(execution)
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
    integrity = _recompute_integrity(
        audit,
        rows,
        summary,
        backend,
        require_timeout_integrity=timeout_policy["schema_version"] is not None,
    )
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
    report = {
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
            "timeouts": timeout_policy,
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
    check_path = run_dir / "check-metadata.json"
    if check_path.exists():
        metadata = _load_check_metadata(check_path, run_dir)
        report["provenance"]["sources"]["check-metadata.json"] = _sha256(
            check_path, run_dir
        )
        report["decision"] = build_product_decision(report, metadata)
    return report


def _load_check_metadata(path: Path, run_dir: Path) -> dict[str, Any]:
    metadata = _load_json(path, run_dir)
    if not isinstance(metadata, dict):
        raise ReportValidationError("Check metadata has an invalid shape")
    expected = {
        "schema_version",
        "name",
        "policy",
        "selected_arm",
        "placement",
        "matched_case_pairs",
        "repetitions",
        "config_sha256",
        "thresholds",
    }
    if set(metadata) != expected:
        raise ReportValidationError("Check metadata fields are incomplete or unknown")
    if metadata["schema_version"] != "cib-check-metadata/1":
        raise ReportValidationError("Unsupported check metadata schema")
    for field in (
        "name",
        "policy",
        "selected_arm",
        "placement",
        "config_sha256",
    ):
        if not isinstance(metadata[field], str):
            raise ReportValidationError("Check metadata text field is invalid")
        validate_public_text(metadata[field], field)
    if metadata["policy"] not in POLICY_ARMS:
        raise ReportValidationError("Check metadata policy is invalid")
    if metadata["selected_arm"] != POLICY_ARMS[metadata["policy"]]:
        raise ReportValidationError("Check metadata policy and arm disagree")
    thresholds = metadata["thresholds"]
    if not isinstance(thresholds, dict) or set(thresholds) != {
        "minimum_required_use_rate",
        "minimum_avoided_unnecessary_use_rate",
        "maximum_harness_failure_rate",
    }:
        raise ReportValidationError("Check metadata thresholds are invalid")
    for value in thresholds.values():
        if type(value) not in (int, float) or not 0 <= float(value) <= 1:
            raise ReportValidationError("Check metadata threshold is invalid")
    for field in ("matched_case_pairs", "repetitions"):
        if type(metadata[field]) is not int or metadata[field] < 1:
            raise ReportValidationError("Check metadata count is invalid")
    return metadata


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
            validate_public_text(str(row[field]), field)
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


def _load_timeout_policy(execution: dict[str, Any]) -> dict[str, Any]:
    if "timeout_policy" not in execution:
        return {
            "schema_version": None,
            "trial_seconds": None,
            "study_seconds": None,
            "source": "legacy_artifact_without_timeout_metadata",
            "backend_enforcement": "not_recorded",
        }
    policy = execution["timeout_policy"]
    expected = {
        "schema_version",
        "trial_seconds",
        "study_seconds",
        "source",
        "backend_enforcement",
    }
    if not isinstance(policy, dict) or set(policy) != expected:
        raise ReportValidationError("Timeout policy fields are incomplete or unknown")
    if policy["schema_version"] != TIMEOUT_POLICY_SCHEMA_VERSION:
        raise ReportValidationError("Unsupported timeout policy schema")
    for field in ("trial_seconds", "study_seconds"):
        value = policy[field]
        if value is not None and (type(value) is not int or value < 1):
            raise ReportValidationError(
                f"Timeout policy field {field} must be a positive integer or null"
            )
    for field in ("source", "backend_enforcement"):
        value = policy[field]
        if not isinstance(value, str) or not value:
            raise ReportValidationError(f"Timeout policy field {field} is invalid")
        validate_public_text(value, f"timeout_policy.{field}")
    return dict(policy)


def _recompute_integrity(
    audit: dict[str, Any],
    rows: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    backend: str,
    *,
    require_timeout_integrity: bool,
) -> dict[str, Any]:
    summary_ids = [str(row["trial_id"]) for row in summary]
    timeout_integrity = _load_timeout_integrity(
        audit,
        summary,
        required=require_timeout_integrity,
    )
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
        observed_session_ids = [session_id for session_id in session_ids if session_id]
        unique_session_ids = len(
            set(observed_session_ids)
        )
        duplicate_session_ids = len(observed_session_ids) - unique_session_ids
        missing_required_session_ids = sorted(
            str(row["trial_id"])
            for row in summary
            if not row["harness_failure"] and not row.get("session_id")
        )
        sessionless_unclassified_harness_ids = sorted(
            str(row["trial_id"])
            for row in summary
            if row["harness_failure"]
            and not row.get("session_id")
            and row.get("failure_class") not in {
                "pre_session_transport", "per_trial_timeout", "study_timeout"
            }
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
        modern_audit = "duplicate_session_ids" in audit
        if modern_audit:
            if _audit_int(audit, "duplicate_session_ids") != duplicate_session_ids:
                raise ReportValidationError(
                    "Audit duplicate session count disagrees with derived summary"
                )
            if _audit_list(audit, "missing_required_session_trial_ids") != missing_required_session_ids:
                raise ReportValidationError(
                    "Audit required-session failures disagree with derived summary"
                )
            if _audit_list(
                audit, "sessionless_unclassified_harness_trial_ids"
            ) != sessionless_unclassified_harness_ids:
                raise ReportValidationError(
                    "Audit unclassified sessionless failures disagree with summary"
                )
            recovered_ids = set(_audit_list(audit, "ledger_recovered_trial_ids"))
            missing_raw = set(_audit_list(audit, "missing_protected_raw"))
            backend_passed = all(
                (
                    _audit_int(audit, "duplicate_trial_ids") == 0,
                    _audit_int(audit, "protected_raw_files")
                    + _audit_int(audit, "ledger_recovered_source_rows")
                    == len(rows),
                    _audit_int(audit, "protected_source_rows")
                    + _audit_int(audit, "ledger_recovered_source_rows")
                    == len(rows),
                    missing_raw == recovered_ids,
                    duplicate_session_ids == 0,
                    not missing_required_session_ids,
                    not sessionless_unclassified_harness_ids,
                    not _audit_list(audit, "unexpected_protected_raw"),
                    not _audit_int(audit, "duplicate_test_indices"),
                    not _audit_list(audit, "missing_test_indices"),
                    not _audit_list(audit, "unexpected_test_indices"),
                    not _audit_list(audit, "test_index_disagreements"),
                    scorer_disagreements == 0,
                    not identity_disagreements,
                )
            )
        else:
            timeout_affected_ids = set(
                timeout_integrity["timeout_affected_trial_ids"]
            )
            expected_session_ids = len(rows) - len(timeout_affected_ids)
            backend_passed = all(
                (
                    _audit_int(audit, "duplicate_trial_ids") == 0,
                    _audit_int(audit, "protected_raw_files") == len(rows),
                    _audit_int(audit, "protected_source_rows") == len(rows),
                    unique_session_ids == expected_session_ids,
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
    recomputed_passed = (
        common_passed and backend_passed and not timeout_integrity["study_timed_out"]
    )
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
        **timeout_integrity,
    }


def _load_timeout_integrity(
    audit: dict[str, Any],
    summary: list[dict[str, Any]],
    *,
    required: bool,
) -> dict[str, Any]:
    summary_ids = [str(row["trial_id"]) for row in summary]
    fields = {
        "study_timed_out",
        "trial_timeout_count",
        "study_timeout_count",
        "trial_timeout_trial_ids",
        "study_timeout_trial_ids",
        "timeout_affected_trial_ids",
    }
    present = fields.intersection(audit)
    if not present:
        if required:
            raise ReportValidationError("Audit timeout fields are required")
        return {
            "study_timed_out": False,
            "trial_timeout_count": 0,
            "study_timeout_count": 0,
            "trial_timeout_trial_ids": [],
            "study_timeout_trial_ids": [],
            "timeout_affected_trial_ids": [],
        }
    if present != fields:
        raise ReportValidationError("Audit timeout fields are incomplete")
    for row in summary:
        if row.get("timeout_scope") not in {None, "trial", "study"}:
            raise ReportValidationError("Derived summary timeout scope is invalid")
    derived_trial_ids = sorted(
        str(row["trial_id"])
        for row in summary
        if row.get("timeout_scope") == "trial"
    )
    derived_study_ids = sorted(
        str(row["trial_id"])
        for row in summary
        if row.get("timeout_scope") == "study"
    )
    derived_affected_ids = sorted(set(derived_trial_ids) | set(derived_study_ids))
    _require_boolean(audit, "study_timed_out")
    trial_count = _audit_nonnegative_int(audit, "trial_timeout_count")
    study_count = _audit_nonnegative_int(audit, "study_timeout_count")
    trial_ids = _audit_trial_ids(audit, "trial_timeout_trial_ids", summary_ids)
    study_ids = _audit_trial_ids(audit, "study_timeout_trial_ids", summary_ids)
    affected_ids = _audit_trial_ids(
        audit, "timeout_affected_trial_ids", summary_ids
    )
    if trial_count != len(trial_ids) or study_count != len(study_ids):
        raise ReportValidationError("Audit timeout counts disagree with timeout scope")
    if audit["study_timed_out"] is not bool(study_count):
        raise ReportValidationError("Audit study timeout status disagrees with scope")
    if set(affected_ids) != set(trial_ids).union(study_ids):
        raise ReportValidationError("Audit timeout affected scope disagrees")
    if (
        sorted(trial_ids) != derived_trial_ids
        or sorted(study_ids) != derived_study_ids
        or sorted(affected_ids) != derived_affected_ids
    ):
        raise ReportValidationError(
            "Audit timeout scope disagrees with derived summary"
        )
    return {
        "study_timed_out": audit["study_timed_out"],
        "trial_timeout_count": trial_count,
        "study_timeout_count": study_count,
        "trial_timeout_trial_ids": trial_ids,
        "study_timeout_trial_ids": study_ids,
        "timeout_affected_trial_ids": affected_ids,
    }


def _audit_nonnegative_int(audit: dict[str, Any], field: str) -> int:
    value = _audit_int(audit, field)
    if value < 0:
        raise ReportValidationError(f"Audit field {field} must be non-negative")
    return value


def _audit_trial_ids(
    audit: dict[str, Any], field: str, summary_ids: list[str]
) -> list[str]:
    values = _audit_list(audit, field)
    if any(not isinstance(value, str) for value in values):
        raise ReportValidationError(f"Audit field {field} must contain trial IDs")
    if len(values) != len(set(values)):
        raise ReportValidationError(f"Audit field {field} contains duplicate trial IDs")
    if not set(values).issubset(summary_ids):
        raise ReportValidationError(f"Audit field {field} contains an unknown trial ID")
    for value in values:
        validate_public_text(value, field)
    return list(values)


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
    lines: list[str] = []
    decision = report.get("decision")
    if isinstance(decision, dict):
        lines.extend(
            [
                f"# {str(decision['verdict']).upper()}",
                "",
                decision["headline"],
                "",
                f"**Required use:** {_percent(decision['required_use']['rate'])} "
                f"(minimum {_percent(decision['required_use']['threshold'])}) — "
                f"**{_pass_fail(decision['required_use']['passed'])}**  ",
                "**Avoided unnecessary use:** "
                f"{_percent(decision['avoided_unnecessary_use']['rate'])} "
                "(minimum "
                f"{_percent(decision['avoided_unnecessary_use']['threshold'])}) — "
                f"**{_pass_fail(decision['avoided_unnecessary_use']['passed'])}**  ",
                f"**Harness failures:** {_percent(decision['harness_failures']['rate'])} "
                f"(maximum {_percent(decision['harness_failures']['threshold'])}) — "
                f"**{_pass_fail(decision['harness_failures']['passed'])}**  ",
                "**Evidence integrity:** "
                f"**{_pass_fail(decision['integrity_passed'])}**  ",
                "**Evidence strength:** "
                f"{str(decision['evidence_strength']).replace('_', ' ')}",
                "",
                "Passing configured thresholds is not a general causal claim or a "
                "guarantee of future model behavior.",
                "",
                "<details>",
                "<summary>Method and evidence</summary>",
                "",
            ]
        )
    lines.extend(
        [
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
        _timeout_limits_markdown(run["timeouts"]),
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
        f"Identity disagreements: {integrity['identity_disagreements']}  ",
        "Timeout outcomes: "
        f"per-trial affected trials {integrity['trial_timeout_count']} · "
        f"whole-study affected trials {integrity['study_timeout_count']} · "
        f"study timed out {'yes' if integrity['study_timed_out'] else 'no'} · "
        "affected trial IDs: "
        f"{_missing_markdown(integrity['timeout_affected_trial_ids'])}",
        "",
        "## Outcomes",
        "",
        "| Placement | Estimand | Arm | Success | Rate | 95% Wilson interval | Harness failures |",
        "|---|---|---|---:|---:|---:|---:|",
        ]
    )
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
    if isinstance(decision, dict):
        lines.extend(["</details>", ""])
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
    integrity_class = "pass" if integrity["passed"] else "fail"
    decision = report.get("decision")
    decision_html = ""
    method_open = ""
    method_close = ""
    if isinstance(decision, dict):
        verdict = str(decision["verdict"]).upper()
        verdict_class = "pass" if decision["verdict"] == "pass" else "fail"
        required_status = _pass_fail(decision["required_use"]["passed"])
        unnecessary_status = _pass_fail(
            decision["avoided_unnecessary_use"]["passed"]
        )
        harness_status = _pass_fail(decision["harness_failures"]["passed"])
        decision_integrity = _pass_fail(decision["integrity_passed"])
        integrity_status_class = (
            "pass" if decision["integrity_passed"] else "fail"
        )
        decision_html = f"""
<section class="decision">
<h1>{html.escape(verdict)}</h1>
<p class="headline {verdict_class}">{html.escape(str(decision['headline']))}</p>
<div class="decision-grid">
<p><strong>Required use</strong><br>{_percent(decision['required_use']['rate'])}<br><small>minimum {_percent(decision['required_use']['threshold'])} · {required_status}</small></p>
<p><strong>Avoided unnecessary use</strong><br>{_percent(decision['avoided_unnecessary_use']['rate'])}<br><small>minimum {_percent(decision['avoided_unnecessary_use']['threshold'])} · {unnecessary_status}</small></p>
<p><strong>Harness failures</strong><br>{_percent(decision['harness_failures']['rate'])}<br><small>maximum {_percent(decision['harness_failures']['threshold'])} · {harness_status}</small></p>
</div>
<p><strong>Evidence integrity:</strong> <span class="{integrity_status_class}">{decision_integrity}</span></p>
<p><strong>Evidence strength:</strong> {html.escape(str(decision['evidence_strength']).replace('_', ' '))}</p>
<p>Passing configured thresholds is not a general causal claim or a guarantee of future model behavior.</p>
</section>
"""
        method_open = '<details class="method"><summary>Method and evidence</summary>'
        method_close = "</details>"
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
.fail {{ color: #c62828; font-weight: 700; }}
.decision {{ padding: 1.25rem; border: 2px solid #8888; border-radius: .8rem; margin-bottom: 2rem; }}
.decision-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: 1rem; }}
.decision-grid p {{ padding: 1rem; background: #8881; border-radius: .5rem; }}
.headline {{ font-size: 1.2rem; }}
.method > summary {{ cursor: pointer; font-size: 1.25rem; font-weight: 700; margin: 1rem 0; }}
</style>
</head>
<body>
<main>
{decision_html}
{method_open}
<h1>Conditional Instruction Benchmark report</h1>
<div class="meta"><strong>Run:</strong> <code>{html.escape(str(run['run_id']))}</code><br>
<strong>Protocol:</strong> <code>{html.escape(str(run['protocol_version']))}</code> · <strong>Profile:</strong> <code>{html.escape(str(run['profile']))}</code><br>
<strong>Backend:</strong> <code>{html.escape(str(run['backend']))}</code><br>
<strong>Model:</strong> <code>{html.escape(str(run['model']))}</code> · <strong>Reasoning:</strong> <code>{html.escape(str(run['reasoning_effort']))}</code><br>
<strong>Placement(s):</strong> {', '.join(f'<code>{html.escape(value)}</code>' for value in run['placements'])}<br>
<strong>Task families:</strong> {html.escape(_case_summary(run['cases']))}<br>
<strong>Blocks:</strong> {run['blocks']} · <strong>Randomization complete:</strong> {'yes' if run['randomization']['complete_permutation'] else 'no'} · <strong>Duration:</strong> {html.escape(_duration(run['duration_seconds']))}<br>
{_timeout_limits_html(run['timeouts'])}<br>
<strong>Trials:</strong> {run['trial_count']} across {run['task_families']} task family/families</div>
<h2>Claim boundary</h2>
<p class="callout"><strong>{html.escape(report['claim']['status'])}</strong> — {html.escape(report['claim']['statement'])}</p>
<h2>Evidence integrity</h2>
<p>Audit passed: <span class="{integrity_class}">{'yes' if integrity['passed'] else 'no'}</span> ·
Unique trials: {integrity['unique_trial_ids']} · Harness failures: {integrity['harness_failures']} ·
Scorer disagreements: {integrity['scorer_disagreements']} · Identity disagreements: {integrity['identity_disagreements']}<br>
Timeout outcomes: per-trial affected trials {integrity['trial_timeout_count']} · whole-study affected trials {integrity['study_timeout_count']} · study timed out {'yes' if integrity['study_timed_out'] else 'no'} · affected trial IDs: {html.escape(_missing_text(integrity['timeout_affected_trial_ids']))}</p>
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
{method_close}
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


def validate_public_text(value: str, field: str) -> None:
    if (
        any(ord(character) < 32 for character in value)
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ABSOLUTE_PATH_FRAGMENT.search(value)
        or UNC_PATH_FRAGMENT.search(value)
        or UNSAFE_PUBLIC_TEXT.search(value)
    ):
        raise ReportValidationError(
            f"Unsafe text in public manifest field {field}"
        )


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _pass_fail(value: bool) -> str:
    return "PASS" if value else "FAIL"


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


def _timeout_limits_markdown(policy: dict[str, Any]) -> str:
    origin = _timeout_policy_origin(policy)
    return (
        "Timeout limits: "
        f"per-trial limit {_timeout_limit(policy['trial_seconds'])} · "
        f"whole-study limit {_timeout_limit(policy['study_seconds'])} · "
        f"source `{policy['source']}` ({origin}) · "
        f"backend enforcement `{policy['backend_enforcement']}`  "
    )


def _timeout_limits_html(policy: dict[str, Any]) -> str:
    origin = _timeout_policy_origin(policy)
    return (
        "<strong>Timeout limits:</strong> "
        f"per-trial limit {html.escape(_timeout_limit(policy['trial_seconds']))} · "
        f"whole-study limit {html.escape(_timeout_limit(policy['study_seconds']))} · "
        f"source <code>{html.escape(policy['source'])}</code> "
        f"({html.escape(origin)}) · backend enforcement "
        f"<code>{html.escape(policy['backend_enforcement'])}</code>"
    )


def _timeout_limit(value: int | None) -> str:
    return "not recorded" if value is None else f"{value}s"


def _timeout_policy_origin(policy: dict[str, Any]) -> str:
    if policy["schema_version"] is None:
        return "legacy artifact; timeout metadata absent"
    if policy["source"].startswith("legacy_"):
        return "legacy compatibility metadata"
    return "explicit metadata"
