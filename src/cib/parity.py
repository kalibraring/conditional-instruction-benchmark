from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import ManifestRow
from .normalization import normalize_direct_raw
from .scoring import score_envelope


KNOWN_ADJUDICATIONS = {
    (
        "postselection-screen-v1",
        "probe-if_else_not-true-001",
    ): "Old summary predates CANARY:<nonce> normalization; scorer-fix-rerun passed.",
}


def _manifest_from_archived(raw: dict[str, Any], raw_path: Path) -> ManifestRow:
    spec = raw["spec"]
    run_id = raw_path.parents[1].name
    return ManifestRow.create(
        run_id=run_id,
        trial_id=spec["trial_id"],
        block_id=f"archived:{spec.get('placement', 'unknown')}:{spec.get('case_id', 'literal_flag')}",
        random_order=0,
        arm=spec["arm"],
        condition_true=bool(spec["condition_true"]),
        case_id=spec.get("case_id", "literal_flag"),
        case_variant=int(spec.get("case_variant", 0)),
        placement=spec.get("placement", "skill_description"),
        model=spec.get("model", "unknown"),
        reasoning_effort=spec.get("reasoning_effort", "unknown"),
        target_adapter="direct-codex/archive-v0.1.0",
        nonce=raw["nonce"],
    )


def verify_archive(archive_root: Path, output_path: Path | None = None) -> dict[str, Any]:
    paths = sorted(archive_root.glob("results/**/raw/*.json"))
    published_disagreements: list[dict[str, Any]] = []
    adjudicated_disagreements: list[dict[str, Any]] = []
    embedded_disagreements: list[dict[str, Any]] = []
    checked = 0
    published_rows = 0
    summary_cache: dict[Path, dict[str, dict[str, Any]]] = {}
    for raw_path in paths:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        if not isinstance(raw.get("spec"), dict) or "nonce" not in raw:
            continue
        manifest = _manifest_from_archived(raw, raw_path)
        scored = score_envelope(normalize_direct_raw(raw, manifest))
        observation = scored["observation"]
        outcome = scored["outcome"]
        embedded_comparisons = {
            "target_action_seen": (
                observation["target_action_seen"],
                bool(raw.get("target_resource_used", False)),
            ),
            "marker_seen": (
                observation["marker_seen"], bool(raw.get("marker_executed", False))
            ),
            "nonce_recovered": (
                observation["nonce_recovered"], bool(raw.get("nonce_recovered", False))
            ),
            "harness_failure": (
                outcome["harness_failure"], int(raw.get("exit_code", 1)) != 0
            ),
        }
        embedded_mismatches = {
            key: {"new": actual, "archived": expected}
            for key, (actual, expected) in embedded_comparisons.items()
            if actual != expected
        }
        if embedded_mismatches:
            embedded_disagreements.append(
                {
                    "path": str(raw_path),
                    "trial_id": manifest.trial_id,
                    "mismatches": embedded_mismatches,
                }
            )

        run_dir = raw_path.parent.parent
        if run_dir not in summary_cache:
            summary_path = run_dir / "probe-summary.json"
            if not summary_path.exists():
                summary_path = run_dir / "calibration-summary.json"
            rows = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else []
            summary_cache[run_dir] = {
                str(row["trial_id"]): row
                for row in rows
                if isinstance(row, dict) and "trial_id" in row
            }
        published = summary_cache[run_dir].get(manifest.trial_id)
        if published:
            published_rows += 1
            published_comparisons: dict[str, tuple[bool, bool]] = {
                "marker_seen": (
                    observation["marker_seen"], bool(published.get("marker_executed", False))
                ),
                "nonce_recovered": (
                    observation["nonce_recovered"], bool(published.get("nonce_recovered", False))
                ),
                "harness_failure": (
                    outcome["harness_failure"], int(published.get("exit_code", 1)) != 0
                ),
            }
            if "target_resource_used" in published:
                published_comparisons["target_action_seen"] = (
                    observation["target_action_seen"],
                    bool(published["target_resource_used"]),
                )
            expected_success = False
            if int(published.get("exit_code", 1)) == 0:
                expected_success = (
                    bool(published.get("marker_executed") and published.get("nonce_recovered"))
                    if manifest.condition_true
                    else not bool(published.get("target_resource_used", published.get("marker_executed")))
                )
            published_comparisons["behavioral_success"] = (
                outcome["behavioral_success"], expected_success
            )
            published_mismatches = {
                key: {"new": actual, "published": expected}
                for key, (actual, expected) in published_comparisons.items()
                if actual != expected
            }
            if published_mismatches:
                disagreement = {
                    "path": str(raw_path),
                    "trial_id": manifest.trial_id,
                    "mismatches": published_mismatches,
                }
                adjudication = KNOWN_ADJUDICATIONS.get((run_dir.name, manifest.trial_id))
                if adjudication:
                    disagreement["adjudication"] = adjudication
                    adjudicated_disagreements.append(disagreement)
                else:
                    published_disagreements.append(disagreement)
        checked += 1
    report = {
        "archive_root": str(archive_root.resolve()),
        "raw_json_files": len(paths),
        "checked_trials": checked,
        "published_rows": published_rows,
        "unadjudicated_disagreement_count": len(published_disagreements),
        "adjudicated_disagreement_count": len(adjudicated_disagreements),
        "embedded_stale_field_rows": len(embedded_disagreements),
        "passed": checked > 0 and published_rows > 0 and not published_disagreements,
        "published_disagreements": published_disagreements,
        "adjudicated_disagreements": adjudicated_disagreements,
        "embedded_disagreements": embedded_disagreements,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
