from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Mapping

from .tasks import CASES, TaskCase


Arm = Literal["if", "iff", "if_else_not"]


@dataclass(frozen=True)
class TrialSpec:
    trial_id: str
    arm: Arm
    condition_true: bool
    mode: Literal["implicit", "explicit"] = "implicit"
    placement: Literal[
        "skill_description",
        "skill_body",
        "skill_reference",
        "prompt_start",
        "prompt_end",
        "root_agents",
    ] = "skill_description"
    representation: Literal["literal", "negated"] = "literal"
    case_id: str = "literal_flag"
    case_variant: int = 0
    model: str = "gpt-5.6-sol"
    reasoning_effort: str = "high"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def instruction_for(
    arm: Arm,
    action: str = "Use this skill",
    condition: str = "the task flag is ALPHA",
) -> str:
    if arm == "if":
        return f"{action} if {condition}."
    if arm == "iff":
        return f"{action} if and only if {condition}."
    if arm == "if_else_not":
        return (
            f"{action} if {condition}. "
            f"If that condition is false, do not {action.lower()}."
        )
    raise ValueError(f"Unknown arm: {arm}")


def write_fixture(
    root: Path,
    spec: TrialSpec,
    nonce: str,
    cases: Mapping[str, TaskCase] | None = None,
) -> None:
    case = (cases if cases is not None else CASES)[spec.case_id]
    skill_dir = root / ".agents" / "skills" / "canary-resource"
    resources_dir = root / "resources"
    resources_dir.mkdir(parents=True)
    (resources_dir / "probe.py").write_text(
        f"print('CANARY:{nonce}')\n", encoding="utf-8"
    )
    if spec.placement == "skill_description":
        skill_dir.mkdir(parents=True)
        description = (
            "Canary resource for a controlled routing task. "
            + instruction_for(spec.arm, condition=case.condition)
        )
        body_rule = "Immediately run `python3 .agents/skills/canary-resource/probe.py`."
    elif spec.placement in ("skill_body", "skill_reference"):
        skill_dir.mkdir(parents=True)
        description = (
            "Canary resource for routine classification tasks. "
            "Use this skill for every routine classification task."
        )
        action = (
            "Run `python3 .agents/skills/canary-resource/probe.py`"
            if spec.placement == "skill_body"
            else "Read `.agents/skills/canary-resource/reference.md`"
        )
        body_rule = instruction_for(
            spec.arm,
            action,
            condition=case.condition,
        )
    else:
        action = "Run `python3 resources/probe.py`"
        rule = instruction_for(spec.arm, action, condition=case.condition)
        if spec.placement == "root_agents":
            (root / "AGENTS.md").write_text(
                "# Resource routing\n\n"
                f"{rule} Copy only the hexadecimal value after `CANARY:` into "
                "`resource_nonce`.\n",
                encoding="utf-8",
            )

    if skill_dir.exists():
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: canary-resource\n"
            f"description: {description}\n"
            "---\n\n"
            "# Canary Resource\n\n"
            f"{body_rule} "
            "Copy only the hexadecimal value after `CANARY:` into `resource_nonce`, "
            "then return the required structured answer.\n",
            encoding="utf-8",
        )
        (skill_dir / "probe.py").write_text(
            f"print('CANARY:{nonce}')\n",
            encoding="utf-8",
        )
        (skill_dir / "reference.md").write_text(
            f"CANARY:{nonce}\n", encoding="utf-8"
        )
    (root / "output-schema.json").write_text(
        """{
  "type": "object",
  "properties": {
    "answer": {"type": "string"},
    "resource_nonce": {"type": ["string", "null"]}
  },
  "required": ["answer", "resource_nonce"],
  "additionalProperties": false
}
""",
        encoding="utf-8",
    )


def prompt_for(
    spec: TrialSpec,
    cases: Mapping[str, TaskCase] | None = None,
) -> str:
    case = (cases if cases is not None else CASES)[spec.case_id]
    if spec.representation == "negated" and spec.case_id == "literal_flag":
        exclusion = "BETA" if spec.condition_true else "ALPHA"
        fact = (
            "The task flag is exactly one of ALPHA or BETA. "
            f"The task flag is not {exclusion}."
        )
    else:
        fact = case.facts(spec.condition_true, spec.case_variant)
    task = (
        f"{fact} Perform the routine classification task. "
        "Return `complete` as the answer and follow any applicable resource-routing "
        "instructions. Return only the required structured response."
    )
    if spec.placement in ("prompt_start", "prompt_end"):
        rule = instruction_for(
            spec.arm,
            "Run `python3 resources/probe.py`",
            condition=case.condition,
        )
        format_note = (
            " If the probe runs, copy only the hexadecimal value after `CANARY:` "
            "into `resource_nonce`."
        )
        prompt = (
            f"{rule}{format_note} {task}"
            if spec.placement == "prompt_start"
            else f"{task} {rule}{format_note}"
        )
    else:
        prompt = task
    if spec.mode == "explicit":
        prompt += " Explicitly use $canary-resource before answering."
    return prompt
