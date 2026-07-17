from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import ManifestRow
from .normalization import normalize_promptfoo_response
from .scoring import score_envelope


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
    protected_source_rows = 0
    for row in result_rows:
        row_metadata = row.get("metadata") or row.get("testCase", {}).get("metadata") or {}
        stable_trial_id = row_metadata.get("trial_id")
        protected = None
        if protected_raw_dir and stable_trial_id:
            protected_path = protected_raw_dir / f"{stable_trial_id}.json"
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
    }
    audit["passed"] = bool(result_rows) and all(
        (
            audit["duplicate_trial_ids"] == 0,
            not audit["missing_protected_raw"],
            not audit["unexpected_protected_raw"],
            audit["unique_session_ids"] == len(result_rows),
            not promptfoo_disagreements,
            not archive_identity_disagreements,
            (not protected_raw_dir or protected_source_rows == len(result_rows)),
        )
    )
    (output_dir / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit
