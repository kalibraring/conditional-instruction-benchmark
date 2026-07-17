from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .tasks import CASES


ARMS = ("if", "iff", "if_else_not")
CONTRASTS = (
    ("operational_iff_minus_if", "iff", "if"),
    ("boundary_expanded_minus_if", "if_else_not", "if"),
    ("form_iff_minus_expanded", "iff", "if_else_not"),
)


def rebuild_summary(result_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for raw_path in sorted((result_dir / "raw").glob("*.json")):
        raw = json.loads(raw_path.read_text())
        spec = raw["spec"]
        target_used, target_marker = _target_from_raw(raw)
        rows.append(
            {
                "trial_id": spec["trial_id"],
                "arm": spec["arm"],
                "condition_true": spec["condition_true"],
                "case_id": spec.get("case_id", "literal_flag"),
                "case_variant": spec.get("case_variant", 0),
                "layer": CASES.get(
                    spec.get("case_id", "literal_flag"), CASES["literal_flag"]
                ).layer,
                "placement": spec["placement"],
                "representation": spec.get("representation", "literal"),
                "exit_code": raw["exit_code"],
                "resource_touched": raw["resource_touched"],
                "target_resource_used": target_used,
                "marker_executed": target_marker,
                "nonce_recovered": raw["nonce_recovered"],
                "latency_seconds": round(float(raw["latency_seconds"]), 3),
            }
        )
    rows.sort(key=lambda row: row["trial_id"])
    (result_dir / "probe-summary.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )
    report = {
        "raw_trials": len(rows),
        "unique_trial_ids": len({row["trial_id"] for row in rows}),
        "nonzero_exits": sum(row["exit_code"] != 0 for row in rows),
    }
    (result_dir / "rebuild-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def analyze(result_dir: Path, bootstrap_samples: int = 10_000) -> dict[str, Any]:
    rows = json.loads((result_dir / "probe-summary.json").read_text())
    for row in rows:
        row.setdefault("case_id", "literal_flag")
        row.setdefault("case_variant", 0)
        row["success"] = _success(row)
        raw_path = result_dir / "raw" / f"{row['trial_id']}.json"
        if raw_path.exists():
            raw = json.loads(raw_path.read_text())
            target_used, target_marker = _target_from_raw(raw)
            row["target_resource_used"] = target_used
            row["marker_executed"] = target_marker
            row["usage"] = raw.get("usage") or {}
            row["stderr_nonempty"] = bool(raw.get("stderr"))
        else:
            row["usage"] = {}
            row["stderr_nonempty"] = False

    cells = _cell_summaries(rows)
    contrasts = _contrasts(rows, bootstrap_samples)
    harness = {
        "trials": len(rows),
        "nonzero_exits": sum(row["exit_code"] != 0 for row in rows),
        "stderr_nonempty": sum(row["stderr_nonempty"] for row in rows),
        "mean_latency_seconds": mean(float(row["latency_seconds"]) for row in rows),
        "mean_input_tokens": _mean_usage(rows, "input_tokens"),
        "mean_output_tokens": _mean_usage(rows, "output_tokens"),
    }
    result = {"harness": harness, "cells": cells, "contrasts": contrasts}
    derived = result_dir / "derived"
    derived.mkdir(exist_ok=True)
    (derived / "analysis.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    _write_cells(derived / "cells.csv", cells)
    _write_markdown(derived / "summary.md", result)
    _write_figure(derived / "success-rates.png", cells)
    return result


def _success(row: dict[str, Any]) -> bool:
    if row["exit_code"] != 0:
        return False
    if row["condition_true"]:
        return bool(row["marker_executed"] and row["nonce_recovered"])
    return not bool(row["marker_executed"])


def _target_from_raw(raw: dict[str, Any]) -> tuple[bool, bool]:
    spec = raw["spec"]
    placement = spec["placement"]
    fragment = (
        ".agents/skills/canary-resource/reference.md"
        if placement == "skill_reference"
        else (
            ".agents/skills/canary-resource/probe.py"
            if placement.startswith("skill_")
            else "resources/probe.py"
        )
    )
    used = False
    marker = False
    for event in raw.get("events", []):
        if event.get("type") != "item.completed":
            continue
        item = event.get("item") or {}
        if item.get("type") != "command_execution":
            continue
        command = item.get("command")
        command_text = command if isinstance(command, str) else " ".join(command or [])
        if fragment not in command_text:
            continue
        if fragment.endswith("probe.py") and "python3" not in command_text:
            continue
        used = True
        if f"CANARY:{raw['nonce']}" in str(item.get("aggregated_output", "")):
            marker = True
    return used, marker


def _wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (center - half, center + half)


def _cell_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, bool], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["placement"], row["arm"], row["condition_true"])].append(row)
    cells: list[dict[str, Any]] = []
    for (placement, arm, truth), members in sorted(groups.items()):
        successes = sum(member["success"] for member in members)
        completed = [member for member in members if member["exit_code"] == 0]
        completed_successes = sum(member["success"] for member in completed)
        low, high = _wilson(successes, len(members))
        cells.append(
            {
                "placement": placement,
                "arm": arm,
                "condition_true": truth,
                "n": len(members),
                "successes": successes,
                "rate": successes / len(members),
                "harness_failures": len(members) - len(completed),
                "completed_n": len(completed),
                "completed_successes": completed_successes,
                "completed_rate": (
                    completed_successes / len(completed) if completed else math.nan
                ),
                "wilson_low": low,
                "wilson_high": high,
                "mean_latency_seconds": mean(
                    float(member["latency_seconds"]) for member in members
                ),
            }
        )
    return cells


def _contrasts(rows: list[dict[str, Any]], samples: int) -> list[dict[str, Any]]:
    placements = sorted({row["placement"] for row in rows})
    cases = sorted({row["case_id"] for row in rows})
    output: list[dict[str, Any]] = []
    rng = random.Random(20260714)
    for placement in placements:
        for truth in (False, True):
            subset = [
                row
                for row in rows
                if row["placement"] == placement and row["condition_true"] == truth
            ]
            for name, treatment, reference in CONTRASTS:
                observed = _task_weighted_difference(
                    subset, cases, treatment, reference
                )
                draws: list[float] = []
                for _ in range(samples):
                    sampled = [rng.choice(cases) for _ in cases]
                    value = _task_weighted_difference(
                        subset, sampled, treatment, reference
                    )
                    if not math.isnan(value):
                        draws.append(value)
                draws.sort()
                output.append(
                    {
                        "placement": placement,
                        "condition_true": truth,
                        "contrast": name,
                        "risk_difference": observed,
                        "cluster_bootstrap_low": _quantile(draws, 0.025),
                        "cluster_bootstrap_high": _quantile(draws, 0.975),
                        "task_families": len(cases),
                    }
                )
    return output


def _task_weighted_difference(
    rows: list[dict[str, Any]],
    cases: Iterable[str],
    treatment: str,
    reference: str,
) -> float:
    differences: list[float] = []
    for case_id in cases:
        treated = [
            row["success"]
            for row in rows
            if row["case_id"] == case_id and row["arm"] == treatment
        ]
        control = [
            row["success"]
            for row in rows
            if row["case_id"] == case_id and row["arm"] == reference
        ]
        if treated and control:
            differences.append(mean(treated) - mean(control))
    return mean(differences) if differences else math.nan


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return math.nan
    index = min(len(values) - 1, max(0, round(probability * (len(values) - 1))))
    return values[index]


def _mean_usage(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row["usage"].get(key) for row in rows if row["usage"].get(key) is not None]
    return mean(values) if values else None


def _write_cells(path: Path, cells: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(cells[0]))
        writer.writeheader()
        writer.writerows(cells)


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Pilot results",
        "",
        f"Trials: {result['harness']['trials']}",
        f"Nonzero exits: {result['harness']['nonzero_exits']}",
        "",
        "| Placement | Arm | Truth | ITT success | Harness failures | Complete-case rate | 95% Wilson interval |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for cell in result["cells"]:
        lines.append(
            "| {placement} | {arm} | {truth} | {successes}/{n} ({rate:.1%}) | "
            "{harness_failures} | {completed_successes}/{completed_n} ({completed_rate:.1%}) | "
            "{wilson_low:.1%}–{wilson_high:.1%} |".format(
                truth="true" if cell["condition_true"] else "false", **cell
            )
        )
    lines.extend(
        [
            "",
            "Risk differences use equal task-family weighting. Intervals resample task "
            "families and are exploratory because this is the calibration pilot.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_figure(path: Path, cells: list[dict[str, Any]]) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    placements = sorted({cell["placement"] for cell in cells})
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for axis, truth in zip(axes, (True, False), strict=True):
        for index, arm in enumerate(ARMS):
            values = [
                next(
                    (
                        cell["rate"]
                        for cell in cells
                        if cell["placement"] == placement
                        and cell["arm"] == arm
                        and cell["condition_true"] == truth
                    ),
                    math.nan,
                )
                for placement in placements
            ]
            axis.plot(placements, values, marker="o", label=arm)
        axis.set_title("Necessary Use" if truth else "Avoided Unnecessary Use")
        axis.set_ylim(-0.03, 1.03)
        axis.tick_params(axis="x", rotation=45)
        axis.grid(alpha=0.25)
    axes[0].set_ylabel("Success rate")
    axes[1].legend(title="Instruction arm", loc="lower left")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
