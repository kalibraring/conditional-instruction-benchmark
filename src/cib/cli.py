from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
from pathlib import Path

from .codex_adapter import CodexAdapter
from .analysis import analyze, rebuild_summary
from .tasks import CASES, case_ids, case_ids_for_layer
from .trials import TrialSpec
from .capabilities import CAPABILITIES
from .doctor import inspect_environment
from .manifest import build_manifest, write_manifest
from .reporting import write_report
from .workflow import run_direct_study, run_promptfoo_study


PLACEMENTS = (
    "prompt_start",
    "prompt_end",
    "root_agents",
    "skill_description",
    "skill_body",
    "skill_reference",
)


def _promptfoo_study(args: argparse.Namespace) -> int:
    args.backend = "promptfoo-codex-sdk"
    return _study(args)


def _doctor(args: argparse.Namespace) -> int:
    report = inspect_environment(Path.cwd(), args.auth)
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 2


def _plan(args: argparse.Namespace) -> int:
    output_dir = args.output_dir
    if output_dir.exists():
        raise FileExistsError(f"Refusing to reuse plan directory: {output_dir}")
    selected_cases = (
        case_ids_for_layer(args.layer) if "all" in args.case else tuple(args.case)
    )
    selected_placements = (
        PLACEMENTS if "all" in args.placement else tuple(args.placement)
    )
    rows = build_manifest(
        run_id=args.run_id,
        case_ids=selected_cases,
        placements=selected_placements,
        replicates=args.replicates,
        seed=args.seed,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        target_adapter=args.backend,
    )
    public_path, private_path = write_manifest(rows, output_dir)
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "trial_count": len(rows),
                "public_manifest": str(public_path),
                "private_manifest": str(private_path),
                "model_calls": 0,
            },
            indent=2,
        )
    )
    return 0


def _report(args: argparse.Namespace) -> int:
    result = write_report(args.run_dir, args.output_dir)
    print(json.dumps(result, indent=2))
    return 0


def _study(args: argparse.Namespace) -> int:
    selected_cases = (
        case_ids_for_layer(args.layer)
        if "all" in args.case
        else tuple(args.case)
    )
    selected_placements = PLACEMENTS if "all" in args.placement else tuple(args.placement)
    run_dir = args.output_dir or Path("results") / args.run_id
    common = {
        "run_dir": run_dir,
        "run_id": args.run_id,
        "case_ids": selected_cases,
        "placements": selected_placements,
        "replicates": args.replicates,
        "seed": args.seed,
        "jobs": args.jobs,
        "auth_path": args.auth,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
    }
    if args.backend == "promptfoo-codex-sdk":
        result = run_promptfoo_study(
            project_root=Path.cwd(), **common
        )
    else:
        result = run_direct_study(
            timeout_seconds=getattr(args, "timeout", 300), **common
        )
    print(json.dumps(result, indent=2))
    return 0 if result["audit"]["passed"] else 2


def _calibrate(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    adapter = CodexAdapter(root / "raw", timeout_seconds=args.timeout)
    specs: list[TrialSpec] = []
    for repeat in range(args.replicates):
        specs.extend(
            [
                TrialSpec(
                    trial_id=f"cal-explicit-{repeat:03d}",
                    arm="if",
                    condition_true=True,
                    mode="explicit",
                    placement=args.placement,
                    representation=args.representation,
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                ),
                TrialSpec(
                    trial_id=f"cal-implicit-true-{repeat:03d}",
                    arm="if",
                    condition_true=True,
                    placement=args.placement,
                    representation=args.representation,
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                ),
                TrialSpec(
                    trial_id=f"cal-implicit-false-{repeat:03d}",
                    arm="if",
                    condition_true=False,
                    placement=args.placement,
                    representation=args.representation,
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                ),
            ]
        )

    rows: list[dict[str, object]] = []
    for index, spec in enumerate(specs, start=1):
        print(f"[{index}/{len(specs)}] {spec.trial_id}", flush=True)
        result = adapter.run(spec)
        row = {
            "trial_id": spec.trial_id,
            "mode": spec.mode,
            "condition_true": spec.condition_true,
            "exit_code": result.exit_code,
            "resource_touched": result.resource_touched,
            "target_resource_used": result.target_resource_used,
            "marker_executed": result.marker_executed,
            "nonce_recovered": result.nonce_recovered,
            "latency_seconds": round(result.latency_seconds, 3),
        }
        rows.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)

    summary_path = root / "calibration-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0 if all(row["exit_code"] == 0 for row in rows) else 1


def _probe(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    adapter = CodexAdapter(root / "raw", timeout_seconds=args.timeout)
    selected_cases = (
        case_ids_for_layer(args.layer) if args.case == "all" else (args.case,)
    )
    placements = (
        (
            "prompt_start",
            "prompt_end",
            "root_agents",
            "skill_description",
            "skill_body",
            "skill_reference",
        )
        if args.placement == "all"
        else (args.placement,)
    )
    specs = [
        TrialSpec(
            trial_id=(
                f"probe-{placement}-{case_id}-{arm}-{truth_name}-{repeat:03d}"
            ),
            arm=arm,
            condition_true=condition_true,
            placement=placement,
            representation=args.representation,
            case_id=case_id,
            case_variant=repeat,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
        )
        for repeat in range(args.replicates)
        for placement in placements
        for case_id in selected_cases
        for arm in ("if", "iff", "if_else_not")
        for truth_name, condition_true in (("true", True), ("false", False))
    ]
    random.Random(args.seed).shuffle(specs)

    def run_one(spec: TrialSpec) -> dict[str, object]:
        result = adapter.run(spec)
        return {
            "trial_id": spec.trial_id,
            "arm": spec.arm,
            "condition_true": spec.condition_true,
            "case_id": spec.case_id,
            "case_variant": spec.case_variant,
            "layer": CASES[spec.case_id].layer,
            "placement": spec.placement,
            "representation": spec.representation,
            "exit_code": result.exit_code,
            "resource_touched": result.resource_touched,
            "marker_executed": result.marker_executed,
            "nonce_recovered": result.nonce_recovered,
            "latency_seconds": round(result.latency_seconds, 3),
        }

    rows: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(run_one, spec): spec for spec in specs}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = future.result()
            rows.append(row)
            if (
                index == len(specs)
                or index % args.progress_every == 0
                or row["exit_code"] != 0
            ):
                print(
                    f"[{index}/{len(specs)}] {json.dumps(row, sort_keys=True)}",
                    flush=True,
                )

    rows.sort(key=lambda row: str(row["trial_id"]))
    summary_path = root / "probe-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0 if all(row["exit_code"] == 0 for row in rows) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cib")
    subparsers = parser.add_subparsers(dest="command", required=True)
    calibrate = subparsers.add_parser("calibrate")
    calibrate.add_argument("--replicates", type=int, default=1)
    calibrate.add_argument("--timeout", type=int, default=300)
    calibrate.add_argument("--model", default="gpt-5.6-sol")
    calibrate.add_argument("--reasoning-effort", default="high")
    calibrate.add_argument(
        "--placement", choices=(
            "skill_description", "skill_body", "skill_reference",
            "prompt_start", "prompt_end", "root_agents"
        ),
        default="skill_description"
    )
    calibrate.add_argument(
        "--representation", choices=("literal", "negated"), default="literal"
    )
    calibrate.add_argument(
        "--output-dir", default="results/calibration", type=Path
    )
    calibrate.set_defaults(func=_calibrate)
    probe = subparsers.add_parser("probe")
    probe.add_argument("--replicates", type=int, default=2)
    probe.add_argument("--jobs", type=int, default=4)
    probe.add_argument("--seed", type=int, default=20260714)
    probe.add_argument("--timeout", type=int, default=300)
    probe.add_argument("--model", default="gpt-5.6-sol")
    probe.add_argument("--reasoning-effort", default="high")
    probe.add_argument(
        "--placement", choices=(
            "all", "skill_description", "skill_body", "skill_reference",
            "prompt_start", "prompt_end", "root_agents"
        ),
        default="skill_description"
    )
    probe.add_argument(
        "--representation", choices=("literal", "negated"), default="literal"
    )
    probe.add_argument("--case", choices=("all",) + case_ids(), default="literal_flag")
    probe.add_argument(
        "--layer", choices=("controlled", "realistic", "all"), default="controlled"
    )
    probe.add_argument("--progress-every", type=int, default=1)
    probe.add_argument("--output-dir", default="results/probe", type=Path)
    probe.set_defaults(func=_probe)
    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("result_dir", type=Path)
    analyze_parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    analyze_parser.set_defaults(
        func=lambda args: (analyze(args.result_dir, args.bootstrap_samples) and 0)
    )
    rebuild_parser = subparsers.add_parser("rebuild-summary")
    rebuild_parser.add_argument("result_dir", type=Path)
    rebuild_parser.set_defaults(
        func=lambda args: (print(json.dumps(rebuild_summary(args.result_dir))) or 0)
    )
    study = subparsers.add_parser(
        "promptfoo-study",
        help="Plan, isolate, execute, archive, and normalize one scientific run",
    )
    study.add_argument("--run-id", required=True)
    study.add_argument(
        "--case",
        action="append",
        choices=("all",) + case_ids(),
        default=None,
        help="Repeat to select cases; use all with --layer",
    )
    study.add_argument(
        "--placement",
        action="append",
        choices=("all",) + PLACEMENTS,
        default=None,
        help="Repeat to select placements",
    )
    study.add_argument(
        "--layer", choices=("controlled", "realistic", "all"), default="controlled"
    )
    study.add_argument("--replicates", type=int, default=2)
    study.add_argument("--jobs", type=int, default=8)
    study.add_argument("--seed", type=int, default=20260714)
    study.add_argument("--model", default="gpt-5.6-sol")
    study.add_argument("--reasoning-effort", default="high")
    study.add_argument("--auth", type=Path, default=Path.home() / ".codex" / "auth.json")
    study.add_argument("--output-dir", type=Path)
    study.set_defaults(func=_promptfoo_study)
    generic_study = subparsers.add_parser(
        "study",
        help="Run one immutable study through a declared execution backend",
    )
    generic_study.add_argument(
        "--backend",
        choices=tuple(CAPABILITIES),
        default="promptfoo-codex-sdk",
    )
    generic_study.add_argument("--run-id", required=True)
    generic_study.add_argument(
        "--case", action="append", choices=("all",) + case_ids(), default=None
    )
    generic_study.add_argument(
        "--placement", action="append", choices=("all",) + PLACEMENTS, default=None
    )
    generic_study.add_argument(
        "--layer", choices=("controlled", "realistic", "all"), default="controlled"
    )
    generic_study.add_argument("--replicates", type=int, default=2)
    generic_study.add_argument("--jobs", type=int, default=8)
    generic_study.add_argument("--seed", type=int, default=20260714)
    generic_study.add_argument("--timeout", type=int, default=300)
    generic_study.add_argument("--model", default="gpt-5.6-sol")
    generic_study.add_argument("--reasoning-effort", default="high")
    generic_study.add_argument(
        "--auth", type=Path, default=Path.home() / ".codex" / "auth.json"
    )
    generic_study.add_argument("--output-dir", type=Path)
    generic_study.set_defaults(func=_study)
    capabilities = subparsers.add_parser(
        "capabilities", help="Print declared evidence capabilities for each backend"
    )
    capabilities.set_defaults(
        func=lambda args: (
            print(
                json.dumps(
                    {key: value.to_dict() for key, value in CAPABILITIES.items()},
                    indent=2,
                )
            )
            or 0
        )
    )
    doctor = subparsers.add_parser(
        "doctor", help="Check local prerequisites without making a model call"
    )
    doctor.add_argument(
        "--auth", type=Path, default=Path.home() / ".codex" / "auth.json"
    )
    doctor.set_defaults(func=_doctor)
    plan = subparsers.add_parser(
        "plan", help="Freeze a randomized manifest without making a model call"
    )
    plan.add_argument("--run-id", required=True)
    plan.add_argument(
        "--backend", choices=tuple(CAPABILITIES), default="promptfoo-codex-sdk"
    )
    plan.add_argument(
        "--case", action="append", choices=("all",) + case_ids(), default=None
    )
    plan.add_argument(
        "--placement", action="append", choices=("all",) + PLACEMENTS, default=None
    )
    plan.add_argument(
        "--layer", choices=("controlled", "realistic", "all"), default="controlled"
    )
    plan.add_argument("--replicates", type=int, default=2)
    plan.add_argument("--seed", type=int, default=20260714)
    plan.add_argument("--model", default="gpt-5.6-sol")
    plan.add_argument("--reasoning-effort", default="high")
    plan.add_argument("--output-dir", type=Path, required=True)
    plan.set_defaults(func=_plan)
    report = subparsers.add_parser(
        "report",
        help="Create safe Markdown, HTML, and JSON reports from a completed study",
    )
    report.add_argument("run_dir", type=Path)
    report.add_argument("--output-dir", type=Path)
    report.set_defaults(func=_report)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command in ("promptfoo-study", "study", "plan"):
        args.case = args.case or ["literal_flag"]
        args.placement = args.placement or ["skill_description"]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
