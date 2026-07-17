from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def compare_backends(
    promptfoo_summary_path: Path,
    direct_summary_path: Path,
    promptfoo_manifest_path: Path,
    direct_manifest_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    promptfoo_rows = json.loads(promptfoo_summary_path.read_text(encoding="utf-8"))
    direct_rows = json.loads(direct_summary_path.read_text(encoding="utf-8"))
    promptfoo_manifest = {
        row["trial_id"]: row
        for row in map(json.loads, promptfoo_manifest_path.read_text(encoding="utf-8").splitlines())
    }
    direct_manifest = {
        row["trial_id"]: row
        for row in map(json.loads, direct_manifest_path.read_text(encoding="utf-8").splitlines())
    }
    ids_pf = {row["trial_id"] for row in promptfoo_rows}
    ids_direct = {row["trial_id"] for row in direct_rows}
    fixture_mismatches = [
        trial_id
        for trial_id in sorted(set(promptfoo_manifest) & set(direct_manifest))
        if promptfoo_manifest[trial_id]["fixture_hash"]
        != direct_manifest[trial_id]["fixture_hash"]
    ]
    assignment_fields = (
        "arm",
        "condition_true",
        "case_id",
        "case_variant",
        "placement",
        "nonce_hash",
    )
    assignment_mismatches = [
        trial_id
        for trial_id in sorted(set(promptfoo_manifest) & set(direct_manifest))
        if any(
            promptfoo_manifest[trial_id][field] != direct_manifest[trial_id][field]
            for field in assignment_fields
        )
    ]

    def cells(rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], tuple[int, int]]:
        grouped: dict[tuple[Any, ...], list[bool]] = defaultdict(list)
        for row in rows:
            key = (row["case_id"], row["placement"], row["arm"], row["condition_true"])
            grouped[key].append(bool(row["behavioral_success"]))
        return {key: (sum(values), len(values)) for key, values in grouped.items()}

    pf_cells = cells(promptfoo_rows)
    direct_cells = cells(direct_rows)
    cell_rows = [
        {
            "case_id": key[0],
            "placement": key[1],
            "arm": key[2],
            "condition_true": key[3],
            "promptfoo_successes": pf_cells.get(key, (0, 0))[0],
            "promptfoo_n": pf_cells.get(key, (0, 0))[1],
            "direct_successes": direct_cells.get(key, (0, 0))[0],
            "direct_n": direct_cells.get(key, (0, 0))[1],
        }
        for key in sorted(set(pf_cells) | set(direct_cells))
    ]
    report = {
        "promptfoo_rows": len(promptfoo_rows),
        "direct_rows": len(direct_rows),
        "missing_in_promptfoo": sorted(ids_direct - ids_pf),
        "missing_in_direct": sorted(ids_pf - ids_direct),
        "assignment_mismatches": assignment_mismatches,
        "fixture_hash_mismatches": fixture_mismatches,
        "promptfoo_behavioral_successes": sum(row["behavioral_success"] for row in promptfoo_rows),
        "direct_behavioral_successes": sum(row["behavioral_success"] for row in direct_rows),
        "promptfoo_harness_failures": sum(row["harness_failure"] for row in promptfoo_rows),
        "direct_harness_failures": sum(row["harness_failure"] for row in direct_rows),
        "cells": cell_rows,
    }
    report["contract_parity_passed"] = not any(
        (
            report["missing_in_promptfoo"],
            report["missing_in_direct"],
            assignment_mismatches,
            fixture_mismatches,
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
