from __future__ import annotations

import hashlib
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
PRE_SESSION_CLOUD_CONFIG_FRAGMENT = "timed out waiting for cloud config bundle after "
REDACTED = "[REDACTED]"


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
    *,
    tests_path: Path | None = None,
    expected_tests_sha256: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = output_dir / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    result_rows = [
        json.loads(line)
        for line in result_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    frozen_tests: list[dict[str, Any]] | None = None
    ledger_sha256: str | None = None
    if tests_path is not None:
        if expected_tests_sha256 is None:
            raise ValueError("Frozen Promptfoo tests ledger requires its pre-run digest")
        tests_bytes = tests_path.read_bytes()
        ledger_sha256 = hashlib.sha256(tests_bytes).hexdigest()
        if ledger_sha256 != expected_tests_sha256:
            raise ValueError("Frozen Promptfoo tests ledger digest changed")
        frozen_tests = [
            json.loads(line)
            for line in tests_bytes.decode("utf-8").splitlines()
            if line.strip()
        ]
    summary_rows: list[dict[str, Any]] = []
    ids: list[str] = []
    promptfoo_disagreements: list[dict[str, Any]] = []
    archive_identity_disagreements: list[dict[str, str]] = []
    trial_timeout_trial_ids: list[str] = []
    study_timeout_trial_ids: list[str] = []
    protected_source_rows = 0
    ledger_recovered_source_rows = 0
    ledger_recovered_trial_ids: list[str] = []
    test_indices: list[int] = []
    test_index_disagreements: list[dict[str, Any]] = []
    for row in result_rows:
        row_metadata = row.get("metadata") or row.get("testCase", {}).get("metadata") or {}
        stable_trial_id = row_metadata.get("trial_id")
        timeout_scope = _timeout_scope(row)
        frozen_test: dict[str, Any] | None = None
        frozen_manifest: ManifestRow | None = None
        redacted_identity = False
        if frozen_tests is not None:
            test_index = row.get("testIdx")
            if type(test_index) is not int or not (0 <= test_index < len(frozen_tests)):
                test_index_disagreements.append(
                    {"testIdx": test_index, "reason": "not an exact in-range integer"}
                )
            else:
                test_indices.append(test_index)
                frozen_test = frozen_tests[test_index]
                frozen_variables = frozen_test.get("vars") or {}
                frozen_manifest = ManifestRow.from_dict(frozen_variables["cib_manifest"])
                frozen_description = frozen_test.get("description")
                frozen_random_order = frozen_manifest.random_order
                if frozen_description != frozen_manifest.trial_id or frozen_random_order != test_index:
                    test_index_disagreements.append(
                        {
                            "testIdx": test_index,
                            "reason": "ledger description/random_order mismatch",
                        }
                    )
                if stable_trial_id not in (None, "", REDACTED) and stable_trial_id != frozen_manifest.trial_id:
                    test_index_disagreements.append(
                        {
                            "testIdx": test_index,
                            "reason": "result metadata disagrees with ledger",
                        }
                    )
                row_manifest = (row.get("vars") or {}).get("cib_manifest") or {}
                for field in (
                    "run_id", "block_id", "random_order", "arm", "condition_true",
                    "case_id", "case_variant", "placement", "model",
                    "reasoning_effort", "target_adapter", "nonce",
                ):
                    observed = row_manifest.get(field)
                    expected = frozen_variables["cib_manifest"].get(field)
                    if observed not in (None, REDACTED) and observed != expected:
                        test_index_disagreements.append(
                            {
                                "testIdx": test_index,
                                "reason": f"result {field} disagrees with ledger",
                            }
                        )
                        break
                # Promptfoo may redact the private manifest copy in result vars
                # while retaining the public trial id in metadata. Recovery is
                # needed only when the stable public identity is also absent.
                redacted_identity = stable_trial_id in (None, "", REDACTED)
                if redacted_identity:
                    if timeout_scope != "trial":
                        test_index_disagreements.append(
                            {
                                "testIdx": test_index,
                                "reason": "only a trial timeout may recover redacted identity",
                            }
                        )
                    else:
                        stable_trial_id = frozen_manifest.trial_id
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
        elif frozen_test is not None and timeout_scope == "trial" and stable_trial_id:
            ledger_recovered_source_rows += 1
            ledger_recovered_trial_ids.append(str(stable_trial_id))
            variables = frozen_test.get("vars") or {}
            provider_response = row.get("response") or {}
            promptfoo_success = bool(row.get("success", False))
        elif frozen_test is not None and redacted_identity:
            # Use the frozen assignment only to keep normalization total. The
            # disagreement and absent source evidence still make this run invalid.
            variables = frozen_test.get("vars") or {}
            provider_response = row.get("response") or {}
            promptfoo_success = bool(row.get("success", False))
        else:
            variables = row.get("vars") or row.get("testCase", {}).get("vars") or {}
            provider_response = row.get("response") or {}
            promptfoo_success = bool(row.get("success", False))
        manifest = ManifestRow.from_dict(variables["cib_manifest"])
        if frozen_manifest is not None and manifest != frozen_manifest:
            test_index_disagreements.append(
                {
                    "testIdx": row.get("testIdx"),
                    "reason": "scored manifest disagrees with frozen ledger",
                }
            )
        if stable_trial_id and stable_trial_id != manifest.trial_id:
            archive_identity_disagreements.append(
                {
                    "jsonl_trial_id": str(stable_trial_id),
                    "protected_trial_id": manifest.trial_id,
                }
            )
        if (
            row.get("error")
            and not provider_response.get("error")
            and (
                timeout_scope in {"trial", "study"}
                or (not provider_response and not row.get("gradingResult"))
            )
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
        combined_error = "\n".join(
            str(value)
            for value in (
                row.get("error"),
                (row.get("response") or {}).get("error")
                if isinstance(row.get("response"), dict)
                else None,
            )
            if value
        )
        if timeout_scope == "trial":
            failure_class = "per_trial_timeout"
        elif timeout_scope == "study":
            failure_class = "study_timeout"
        elif (
            PRE_SESSION_CLOUD_CONFIG_FRAGMENT in combined_error
            and scored["outcome"]["harness_failure"]
            and not scored["response"].get("session_id")
            and not any(scored["observation"].values())
        ):
            failure_class = "pre_session_transport"
        elif scored["outcome"]["harness_failure"]:
            failure_class = "unclassified_harness_error"
        else:
            failure_class = None
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
                "failure_class": failure_class,
                "evidence_source": (
                    "protected_archive" if protected else (
                        "frozen_tests_ledger" if frozen_test is not None and timeout_scope == "trial" else "result_jsonl"
                    )
                ),
            }
        )
    summary_rows.sort(key=lambda item: item["random_order"])
    (output_dir / "summary.json").write_text(
        json.dumps(summary_rows, indent=2), encoding="utf-8"
    )
    unique_ids = set(ids)
    all_raw_ids = (
        {path.stem for path in protected_raw_dir.glob("*.json")}
        if protected_raw_dir and protected_raw_dir.exists()
        else set()
    )
    ignored_reserved_raw_ids = sorted(all_raw_ids.intersection({REDACTED}))
    raw_ids = all_raw_ids.difference({REDACTED})
    sessions = [row["session_id"] for row in summary_rows if row["session_id"]]
    timeout_affected_trial_ids = sorted(
        set(trial_timeout_trial_ids) | set(study_timeout_trial_ids)
    )
    missing_required_session_trial_ids = sorted(
        str(row["trial_id"])
        for row in summary_rows
        if not row["harness_failure"] and not row["session_id"]
    )
    sessionless_unclassified_harness_trial_ids = sorted(
        str(row["trial_id"])
        for row in summary_rows
        if row["harness_failure"]
        and not row["session_id"]
        and row["failure_class"] not in {
            "pre_session_transport", "per_trial_timeout", "study_timeout"
        }
    )
    duplicate_session_ids = len(sessions) - len(set(sessions))
    recovered_ids = set(ledger_recovered_trial_ids)
    indexed = set(test_indices)
    expected_indices = set(range(len(frozen_tests or [])))
    audit = {
        "result_rows": len(result_rows),
        "unique_trial_ids": len(unique_ids),
        "duplicate_trial_ids": len(ids) - len(unique_ids),
        "protected_raw_files": len(raw_ids),
        "protected_source_rows": protected_source_rows,
        "ledger_recovered_source_rows": ledger_recovered_source_rows,
        "ledger_recovered_trial_ids": sorted(ledger_recovered_trial_ids),
        "frozen_tests_sha256": ledger_sha256,
        "missing_protected_raw": sorted(unique_ids - raw_ids),
        "unexpected_protected_raw": sorted(raw_ids - unique_ids),
        "ignored_reserved_protected_raw": ignored_reserved_raw_ids,
        "unique_session_ids": len(set(sessions)),
        "duplicate_session_ids": duplicate_session_ids,
        "missing_required_session_trial_ids": missing_required_session_trial_ids,
        "sessionless_unclassified_harness_trial_ids": sessionless_unclassified_harness_trial_ids,
        "duplicate_test_indices": len(test_indices) - len(indexed),
        "missing_test_indices": sorted(expected_indices - indexed),
        "unexpected_test_indices": sorted(indexed - expected_indices),
        "test_index_disagreements": test_index_disagreements,
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
            set(audit["missing_protected_raw"]) == recovered_ids,
            not audit["unexpected_protected_raw"],
            audit["duplicate_session_ids"] == 0,
            not audit["missing_required_session_trial_ids"],
            not audit["sessionless_unclassified_harness_trial_ids"],
            not promptfoo_disagreements,
            not archive_identity_disagreements,
            (
                not protected_raw_dir
                or protected_source_rows + ledger_recovered_source_rows == len(result_rows)
            ),
            not audit["duplicate_test_indices"],
            not audit["missing_test_indices"],
            not audit["unexpected_test_indices"],
            not audit["test_index_disagreements"],
            not audit["study_timed_out"],
        )
    )
    (output_dir / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit
