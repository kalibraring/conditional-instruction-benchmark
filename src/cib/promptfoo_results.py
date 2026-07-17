from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .contracts import ManifestRow
from .normalization import normalize_promptfoo_response
from .scoring import score_envelope


TRIAL_TIMEOUT_FRAGMENT = "Evaluation timed out after "
STUDY_TIMEOUT_FRAGMENT = "Evaluation exceeded max duration of "
STUDY_ABORT_FRAGMENTS = (
    "OpenAI Codex SDK call aborted",
    "OpenAI Codex SDK call aborted before it started",
)


def _timeout_scope(row: dict[str, Any]) -> str | None:
    explicit_scope = row.get("cib_timeout_scope")
    if explicit_scope in {"trial", "study"}:
        return str(explicit_scope)
    response = row.get("response") or {}
    messages = (
        row.get("error"),
        response.get("error") if isinstance(response, dict) else None,
        (row.get("gradingResult") or {}).get("reason"),
    )
    combined = "\n".join(str(message) for message in messages if message)
    if STUDY_TIMEOUT_FRAGMENT in combined:
        return "study"
    if any(fragment in combined for fragment in STUDY_ABORT_FRAGMENTS):
        # CIB does not send any other cooperative abort signal to Promptfoo.
        # With maxEvalTimeMs enabled, the global study controller is therefore
        # the only source of these pinned Codex SDK abort results.
        return "study"
    if TRIAL_TIMEOUT_FRAGMENT in combined:
        return "trial"
    return None


def complete_outer_watchdog_results(
    result_path: Path,
    manifests: Iterable[ManifestRow],
    *,
    study_timeout_seconds: int,
) -> None:
    """Make a hard-killed Promptfoo run complete enough to report INVALID safely."""
    parsed_rows: list[dict[str, Any]] = []
    if result_path.exists():
        for raw_line in result_path.read_bytes().splitlines():
            if not raw_line.strip():
                continue
            try:
                line = raw_line.decode("utf-8")
                value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                # A hard process kill can leave one partial trailing JSONL row,
                # including a UTF-8 code point cut between bytes. Its trial is
                # recovered from the frozen private manifest below.
                continue
            if isinstance(value, dict):
                parsed_rows.append(value)

    manifest_rows = list(manifests)
    manifest_by_id = {row.trial_id: row for row in manifest_rows}
    seen_ids: set[str] = set()
    for row in parsed_rows:
        metadata = row.get("metadata") or (row.get("testCase") or {}).get(
            "metadata"
        ) or {}
        variables = row.get("vars") or (row.get("testCase") or {}).get("vars") or {}
        trial_id = metadata.get("trial_id")
        if not trial_id and isinstance(variables.get("cib_manifest"), dict):
            trial_id = variables["cib_manifest"].get("trial_id")
        if trial_id in manifest_by_id:
            seen_ids.add(str(trial_id))
        # The outer watchdog means Promptfoo did not complete its governed run,
        # even if a row was already flushed. Keep its response but mark the
        # evidence as affected by the whole-study boundary.
        row["cib_timeout_scope"] = "study"

    error = (
        "Evaluation exceeded max duration of "
        f"{study_timeout_seconds * 1000}ms (CIB outer watchdog)"
    )
    for manifest in manifest_rows:
        if manifest.trial_id in seen_ids:
            continue
        variables = {"cib_manifest": manifest.to_private_dict()}
        metadata = {"trial_id": manifest.trial_id}
        parsed_rows.append(
            {
                "metadata": metadata,
                "vars": variables,
                "testCase": {"metadata": metadata, "vars": variables},
                "error": error,
                "success": False,
                "cib_timeout_scope": "study",
            }
        )

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        "".join(json.dumps(row) + "\n" for row in parsed_rows),
        encoding="utf-8",
    )


def normalize_promptfoo_jsonl(
    result_path: Path,
    output_dir: Path,
    protected_raw_dir: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = output_dir / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    result_rows = [
        json.loads(line)
        for line in result_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary_rows: list[dict[str, Any]] = []
    ids: list[str] = []
    promptfoo_disagreements: list[dict[str, Any]] = []
    archive_identity_disagreements: list[dict[str, str]] = []
    trial_timeout_trial_ids: list[str] = []
    study_timeout_trial_ids: list[str] = []
    protected_source_rows = 0
    for row in result_rows:
        row_metadata = row.get("metadata") or row.get("testCase", {}).get("metadata") or {}
        stable_trial_id = row_metadata.get("trial_id")
        timeout_scope = _timeout_scope(row)
        protected = None
        if protected_raw_dir and stable_trial_id:
            protected_path = protected_raw_dir / f"{stable_trial_id}.json"
            if timeout_scope and not protected_path.exists():
                protected_test = dict(row.get("testCase") or {})
                protected_test.setdefault("vars", row.get("vars") or {})
                protected_test.setdefault("metadata", row_metadata)
                protected_path.write_text(
                    json.dumps(
                        {"test": protected_test, "result": row},
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            if protected_path.exists():
                protected = json.loads(protected_path.read_text(encoding="utf-8"))
        if protected:
            protected_source_rows += 1
            protected_test = protected.get("test") or {}
            variables = protected_test.get("vars") or {}
            protected_result = protected.get("result") or {}
            provider_response = protected_result.get("response") or {}
            promptfoo_success = bool(protected_result.get("success", False))
        else:
            variables = row.get("vars") or row.get("testCase", {}).get("vars") or {}
            provider_response = row.get("response") or {}
            promptfoo_success = bool(row.get("success", False))
        manifest = ManifestRow.from_dict(variables["cib_manifest"])
        if stable_trial_id and stable_trial_id != manifest.trial_id:
            archive_identity_disagreements.append(
                {
                    "jsonl_trial_id": str(stable_trial_id),
                    "protected_trial_id": manifest.trial_id,
                }
            )
        if (
            row.get("error")
            and not provider_response
            and not row.get("gradingResult")
        ):
            provider_response = {**provider_response, "error": row["error"]}
        scored = score_envelope(normalize_promptfoo_response(provider_response, manifest))
        trial_id = manifest.trial_id
        if timeout_scope == "trial":
            trial_timeout_trial_ids.append(trial_id)
        elif timeout_scope == "study":
            study_timeout_trial_ids.append(trial_id)
        ids.append(trial_id)
        evidence_path = evidence_dir / f"{trial_id}.json"
        evidence_path.write_text(json.dumps(scored, indent=2), encoding="utf-8")
        cib_success = bool(scored["outcome"]["behavioral_success"])
        if promptfoo_success != cib_success:
            promptfoo_disagreements.append(
                {
                    "trial_id": trial_id,
                    "promptfoo_success": promptfoo_success,
                    "cib_success": cib_success,
                }
            )
        summary_rows.append(
            {
                "trial_id": trial_id,
                "random_order": manifest.random_order,
                "arm": manifest.arm,
                "condition_true": manifest.condition_true,
                "case_id": manifest.case_id,
                "case_variant": manifest.case_variant,
                "placement": manifest.placement,
                "promptfoo_success": promptfoo_success,
                **scored["observation"],
                **scored["outcome"],
                "session_id": scored["response"].get("session_id"),
                "timeout_scope": timeout_scope,
            }
        )
    summary_rows.sort(key=lambda item: item["random_order"])
    (output_dir / "summary.json").write_text(
        json.dumps(summary_rows, indent=2), encoding="utf-8"
    )
    unique_ids = set(ids)
    raw_ids = (
        {path.stem for path in protected_raw_dir.glob("*.json")}
        if protected_raw_dir and protected_raw_dir.exists()
        else set()
    )
    sessions = [row["session_id"] for row in summary_rows if row["session_id"]]
    timeout_affected_trial_ids = sorted(
        set(trial_timeout_trial_ids) | set(study_timeout_trial_ids)
    )
    expected_session_count = len(result_rows) - len(timeout_affected_trial_ids)
    audit = {
        "result_rows": len(result_rows),
        "unique_trial_ids": len(unique_ids),
        "duplicate_trial_ids": len(ids) - len(unique_ids),
        "protected_raw_files": len(raw_ids),
        "protected_source_rows": protected_source_rows,
        "missing_protected_raw": sorted(unique_ids - raw_ids),
        "unexpected_protected_raw": sorted(raw_ids - unique_ids),
        "unique_session_ids": len(set(sessions)),
        "behavioral_successes": sum(row["behavioral_success"] for row in summary_rows),
        "harness_failures": sum(row["harness_failure"] for row in summary_rows),
        "promptfoo_cib_disagreements": promptfoo_disagreements,
        "archive_identity_disagreements": archive_identity_disagreements,
        "study_timed_out": bool(study_timeout_trial_ids),
        "trial_timeout_count": len(trial_timeout_trial_ids),
        "study_timeout_count": len(study_timeout_trial_ids),
        "trial_timeout_trial_ids": sorted(trial_timeout_trial_ids),
        "study_timeout_trial_ids": sorted(study_timeout_trial_ids),
        "timeout_affected_trial_ids": timeout_affected_trial_ids,
    }
    audit["passed"] = bool(result_rows) and all(
        (
            audit["duplicate_trial_ids"] == 0,
            not audit["missing_protected_raw"],
            not audit["unexpected_protected_raw"],
            audit["unique_session_ids"] == expected_session_count,
            not promptfoo_disagreements,
            not archive_identity_disagreements,
            (not protected_raw_dir or protected_source_rows == len(result_rows)),
            not audit["study_timed_out"],
        )
    )
    (output_dir / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit
