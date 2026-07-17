from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .capabilities import CAPABILITIES, SURFACES
from .doctor import inspect_environment
from .product_decision import POLICY_ARMS
from .reporting import ReportValidationError, validate_public_text, write_report
from .tasks import TaskCase
from .workflow import run_direct_study, run_promptfoo_study


CHECK_SCHEMA_VERSION = "cib-check/2"
LEGACY_CHECK_SCHEMA_VERSION = "cib-check/1"
CHECK_RESULT_SCHEMA_VERSION = "cib-check-result/1"
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
LEGACY_TIMEOUT_WARNING = (
    "cib-check/1 is deprecated; timeout_seconds retains its legacy "
    "backend-dependent meaning. Migrate to cib-check/2 with explicit "
    "trial_timeout_seconds and study_timeout_seconds."
)


class CheckConfigError(ValueError):
    """A check configuration error whose message is safe for CLI output."""


@dataclass(frozen=True)
class CheckConfig:
    schema_version: str
    name: str
    condition: str
    placement: str
    policy: str
    required_cases: tuple[str, ...]
    unnecessary_cases: tuple[str, ...]
    backend: str
    model: str
    reasoning_effort: str
    repetitions: int
    jobs: int
    seed: int
    trial_timeout_seconds: int | None
    study_timeout_seconds: int | None
    timeout_source: str
    legacy_warning: str | None
    minimum_required_use_rate: float
    minimum_avoided_unnecessary_use_rate: float
    maximum_harness_failure_rate: float
    source_hash: str
    private_source: str = field(repr=False)

    @property
    def arm(self) -> str:
        return POLICY_ARMS[self.policy]

    @property
    def manifest_replicates(self) -> int:
        return len(self.required_cases) * self.repetitions

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": "cib-check-metadata/1",
            "name": self.name,
            "policy": self.policy,
            "selected_arm": self.arm,
            "placement": self.placement,
            "matched_case_pairs": len(self.required_cases),
            "repetitions": self.repetitions,
            "config_sha256": self.source_hash,
            "thresholds": {
                "minimum_required_use_rate": self.minimum_required_use_rate,
                "minimum_avoided_unnecessary_use_rate": (
                    self.minimum_avoided_unnecessary_use_rate
                ),
                "maximum_harness_failure_rate": self.maximum_harness_failure_rate,
            },
        }


def load_check_config(path: Path) -> CheckConfig:
    try:
        source = path.read_bytes()
        parsed = yaml.safe_load(source)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise CheckConfigError("Unable to read a valid check configuration") from error
    root = _mapping(parsed, "configuration")
    _keys(
        root,
        {
            "schema_version",
            "name",
            "instruction",
            "cases",
            "execution",
            "thresholds",
        },
        "configuration",
    )
    schema_version = root.get("schema_version")
    if schema_version not in (CHECK_SCHEMA_VERSION, LEGACY_CHECK_SCHEMA_VERSION):
        raise CheckConfigError("Unsupported check configuration schema")
    name = _text(root.get("name"), "name")
    if not SAFE_NAME.fullmatch(name):
        raise CheckConfigError("Check name must be a safe lowercase identifier")

    instruction = _mapping(root.get("instruction"), "instruction")
    _keys(instruction, {"condition", "placement", "policy"}, "instruction")
    condition = _text(instruction.get("condition"), "instruction condition")
    placement = _text(instruction.get("placement"), "instruction placement")
    policy = _text(instruction.get("policy"), "instruction policy")
    if placement not in SURFACES:
        raise CheckConfigError("Unsupported instruction placement")
    if policy not in POLICY_ARMS:
        raise CheckConfigError("Unsupported instruction policy")

    cases = _mapping(root.get("cases"), "cases")
    _keys(cases, {"required", "unnecessary"}, "cases")
    required_cases = _text_list(cases.get("required"), "required cases")
    unnecessary_cases = _text_list(cases.get("unnecessary"), "unnecessary cases")
    if len(required_cases) != len(unnecessary_cases):
        raise CheckConfigError("Required and unnecessary cases must be paired")

    execution = _mapping(root.get("execution"), "execution")
    common_execution_fields = {
        "backend",
        "model",
        "reasoning_effort",
        "repetitions",
        "jobs",
        "seed",
    }
    timeout_fields = (
        {"trial_timeout_seconds", "study_timeout_seconds"}
        if schema_version == CHECK_SCHEMA_VERSION
        else {"timeout_seconds"}
    )
    _keys(execution, common_execution_fields | timeout_fields, "execution")
    backend = _text(execution.get("backend"), "execution backend")
    if backend not in CAPABILITIES:
        raise CheckConfigError("Unsupported execution backend")
    model = _text(execution.get("model"), "model")
    reasoning_effort = _text(execution.get("reasoning_effort"), "reasoning effort")
    for value, public_field in (
        (model, "model"),
        (reasoning_effort, "reasoning_effort"),
    ):
        try:
            validate_public_text(value, public_field)
        except ReportValidationError as error:
            raise CheckConfigError(
                f"{public_field.replace('_', ' ').capitalize()} "
                "is unsafe for public evidence"
            ) from error
    repetitions = _positive_int(execution.get("repetitions"), "repetitions")
    jobs = _positive_int(execution.get("jobs"), "jobs")
    seed = _integer(execution.get("seed"), "seed")
    if schema_version == CHECK_SCHEMA_VERSION:
        trial_timeout_seconds = _positive_int(
            execution.get("trial_timeout_seconds"), "trial timeout seconds"
        )
        study_timeout_seconds = _positive_int(
            execution.get("study_timeout_seconds"), "study timeout seconds"
        )
        timeout_source = "explicit"
        legacy_warning = None
    else:
        legacy_timeout_seconds = _positive_int(
            execution.get("timeout_seconds"), "timeout seconds"
        )
        if backend == "promptfoo-codex-sdk":
            trial_timeout_seconds = None
            study_timeout_seconds = legacy_timeout_seconds
        else:
            trial_timeout_seconds = legacy_timeout_seconds
            study_timeout_seconds = None
        timeout_source = "legacy_cib_check_1"
        legacy_warning = LEGACY_TIMEOUT_WARNING

    thresholds = _mapping(root.get("thresholds"), "thresholds")
    _keys(
        thresholds,
        {
            "minimum_required_use_rate",
            "minimum_avoided_unnecessary_use_rate",
            "maximum_harness_failure_rate",
        },
        "thresholds",
    )
    minimum_required = _rate(
        thresholds.get("minimum_required_use_rate"), "minimum required-use rate"
    )
    minimum_unnecessary = _rate(
        thresholds.get("minimum_avoided_unnecessary_use_rate"),
        "minimum avoided-unnecessary-use rate",
    )
    maximum_harness = _rate(
        thresholds.get("maximum_harness_failure_rate"),
        "maximum harness-failure rate",
    )
    return CheckConfig(
        schema_version=schema_version,
        name=name,
        condition=condition,
        placement=placement,
        policy=policy,
        required_cases=required_cases,
        unnecessary_cases=unnecessary_cases,
        backend=backend,
        model=model,
        reasoning_effort=reasoning_effort,
        repetitions=repetitions,
        jobs=jobs,
        seed=seed,
        trial_timeout_seconds=trial_timeout_seconds,
        study_timeout_seconds=study_timeout_seconds,
        timeout_source=timeout_source,
        legacy_warning=legacy_warning,
        minimum_required_use_rate=minimum_required,
        minimum_avoided_unnecessary_use_rate=minimum_unnecessary,
        maximum_harness_failure_rate=maximum_harness,
        source_hash=hashlib.sha256(source).hexdigest(),
        private_source=source.decode("utf-8"),
    )


def default_check_output(config: CheckConfig) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("results") / "checks" / f"{config.name}-{timestamp}"


def run_check(
    *,
    config: CheckConfig,
    output_dir: Path,
    auth_path: Path,
    project_root: Path,
    cloud_config_seed_path: Path | None = None,
    cloud_config_min_remaining_seconds: int | None = None,
) -> dict[str, Any]:
    if output_dir.exists():
        raise CheckConfigError("Refusing to reuse check output directory")
    environment = inspect_environment(project_root, auth_path, backend=config.backend)
    if not environment["ready"]:
        raise CheckConfigError("Environment is not ready; run cib doctor for details")

    case_id = f"check_{config.name.replace('-', '_')}_{config.source_hash[:8]}"
    custom_case = TaskCase(
        case_id=case_id,
        condition=config.condition,
        true_facts=config.required_cases,
        false_facts=config.unnecessary_cases,
        layer="product_check",
        source="user-owned cib.yaml",
    )
    run_id = f"{config.name}-{uuid.uuid4().hex[:12]}"
    common = {
        "run_dir": output_dir,
        "run_id": run_id,
        "case_ids": (case_id,),
        "placements": (config.placement,),
        "replicates": config.manifest_replicates,
        "seed": config.seed,
        "jobs": config.jobs,
        "auth_path": auth_path,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "cloud_config_seed_path": cloud_config_seed_path,
        "cloud_config_min_remaining_seconds": cloud_config_min_remaining_seconds,
    }
    if config.backend == "promptfoo-codex-sdk":
        run_promptfoo_study(
            project_root=project_root,
            trial_timeout_seconds=config.trial_timeout_seconds,
            study_timeout_seconds=config.study_timeout_seconds,
            timeout_source=config.timeout_source,
            custom_case=custom_case,
            **common,
        )
    else:
        run_direct_study(
            trial_timeout_seconds=config.trial_timeout_seconds,
            study_timeout_seconds=config.study_timeout_seconds,
            timeout_source=config.timeout_source,
            custom_case=custom_case,
            **common,
        )

    metadata_path = output_dir / "check-metadata.json"
    (output_dir / "check-config.private.yaml").write_text(
        config.private_source, encoding="utf-8"
    )
    metadata_path.write_text(
        json.dumps(config.public_metadata(), indent=2), encoding="utf-8"
    )
    paths = write_report(output_dir)
    report = json.loads((output_dir / paths["report_json"]).read_text(encoding="utf-8"))
    decision = report["decision"]
    exit_code = (
        0
        if decision["verdict"] == "pass"
        else (1 if decision["verdict"] == "fail" else 2)
    )
    result = {
        "schema_version": CHECK_RESULT_SCHEMA_VERSION,
        **decision,
        "exit_code": exit_code,
        "report_json": paths["report_json"],
        "report_markdown": paths["report_markdown"],
        "report_html": paths["report_html"],
    }
    (output_dir / "check-result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def render_check_console(result: dict[str, Any]) -> str:
    verdict = str(result["verdict"]).upper()
    required = result["required_use"]
    unnecessary = result["avoided_unnecessary_use"]
    harness = result["harness_failures"]
    return "\n".join(
        (
            f"{verdict} — {result['headline']}",
            f"Required use: {_percent(required['rate'])} "
            f"(minimum {_percent(required['threshold'])})",
            f"Avoided unnecessary use: {_percent(unnecessary['rate'])} "
            f"(minimum {_percent(unnecessary['threshold'])})",
            f"Harness failures: {_percent(harness['rate'])} "
            f"(maximum {_percent(harness['threshold'])})",
            f"Evidence: {result['evidence_strength'].replace('_', ' ')}",
            f"Report: {result['report_html']}",
        )
    )


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CheckConfigError(f"{label.capitalize()} must be a mapping")
    return value


def _keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise CheckConfigError(f"{label.capitalize()} fields are incomplete or unknown")


def _text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(char) < 32 for char in value)
    ):
        raise CheckConfigError(f"{label.capitalize()} must be non-empty text")
    return value.strip()


def _text_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CheckConfigError(f"{label.capitalize()} must be a non-empty list")
    return tuple(_text(item, label) for item in value)


def _integer(value: Any, label: str) -> int:
    if type(value) is not int:
        raise CheckConfigError(f"{label.capitalize()} must be an integer")
    return value


def _positive_int(value: Any, label: str) -> int:
    result = _integer(value, label)
    if result < 1:
        raise CheckConfigError(f"{label.capitalize()} must be positive")
    return result


def _rate(value: Any, label: str) -> float:
    if type(value) not in (int, float):
        raise CheckConfigError(f"{label.capitalize()} must be a number")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise CheckConfigError(f"{label.capitalize()} must be between zero and one")
    return result


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"
