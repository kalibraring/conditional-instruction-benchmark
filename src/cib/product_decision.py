from __future__ import annotations

from typing import Any


POLICY_ARMS = {
    "flexible": "if",
    "strict": "iff",
    "explicit_boundary": "if_else_not",
}


def build_product_decision(
    report: dict[str, Any], metadata: dict[str, Any]
) -> dict[str, Any]:
    arm = POLICY_ARMS[metadata["policy"]]
    placement = metadata["placement"]
    selected = {
        bool(cell["condition_true"]): cell
        for cell in report["cells"]
        if cell["arm"] == arm and cell["placement"] == placement
    }
    if set(selected) != {True, False}:
        return _invalid_decision(metadata, "Required decision cells are missing.")

    required = selected[True]
    unnecessary = selected[False]
    thresholds = metadata["thresholds"]
    required_rate = float(required["rate"])
    unnecessary_rate = float(unnecessary["rate"])
    row_count = int(report["integrity"]["result_rows"])
    harness_rate = (
        float(report["integrity"]["harness_failures"]) / row_count
        if row_count
        else 1.0
    )
    required_passed = required_rate >= thresholds["minimum_required_use_rate"]
    unnecessary_passed = (
        unnecessary_rate >= thresholds["minimum_avoided_unnecessary_use_rate"]
    )
    harness_passed = harness_rate <= thresholds["maximum_harness_failure_rate"]
    integrity_passed = bool(report["integrity"]["passed"])

    if not integrity_passed:
        verdict = "invalid"
        headline = "The evidence failed integrity checks."
    elif required_passed and unnecessary_passed and harness_passed:
        verdict = "pass"
        headline = "The instruction met both routing thresholds."
    elif not harness_passed:
        verdict = "fail"
        headline = "Harness failures exceeded the configured threshold."
    elif not required_passed and not unnecessary_passed:
        verdict = "fail"
        headline = "The instruction was unreliable in both routing directions."
    elif not required_passed:
        verdict = "fail"
        headline = "The required action did not happen often enough."
    else:
        verdict = "fail"
        headline = "The agent used the resource when it was unnecessary."

    evidence_strength = (
        "smoke_only"
        if min(int(required["n"]), int(unnecessary["n"])) == 1
        else "descriptive_only"
    )
    return {
        "name": metadata["name"],
        "verdict": verdict,
        "headline": headline,
        "required_use": {
            "rate": required_rate,
            "threshold": thresholds["minimum_required_use_rate"],
            "passed": required_passed,
        },
        "avoided_unnecessary_use": {
            "rate": unnecessary_rate,
            "threshold": thresholds[
                "minimum_avoided_unnecessary_use_rate"
            ],
            "passed": unnecessary_passed,
        },
        "harness_failures": {
            "rate": harness_rate,
            "threshold": thresholds["maximum_harness_failure_rate"],
            "passed": harness_passed,
        },
        "integrity_passed": integrity_passed,
        "evidence_strength": evidence_strength,
    }


def _invalid_decision(metadata: dict[str, Any], headline: str) -> dict[str, Any]:
    return {
        "name": metadata["name"],
        "verdict": "invalid",
        "headline": headline,
        "required_use": {"rate": None, "threshold": None, "passed": False},
        "avoided_unnecessary_use": {
            "rate": None,
            "threshold": None,
            "passed": False,
        },
        "harness_failures": {"rate": None, "threshold": None, "passed": False},
        "integrity_passed": False,
        "evidence_strength": "invalid",
    }
