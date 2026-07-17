from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskCase:
    case_id: str
    condition: str
    true_facts: tuple[str, ...]
    false_facts: tuple[str, ...]
    layer: str = "controlled"
    source: str | None = None

    def facts(self, condition_true: bool, variant: int) -> str:
        choices = self.true_facts if condition_true else self.false_facts
        return choices[variant % len(choices)]


CASES: dict[str, TaskCase] = {
    case.case_id: case
    for case in (
        TaskCase(
            "literal_flag",
            "the task flag is ALPHA",
            ("The task flag is ALPHA.",),
            ("The task flag is BETA.",),
        ),
        TaskCase(
            "compound_gate",
            "the task flag is ALPHA, the target is WEB, and dry-run mode is off",
            (
                "The task flag is ALPHA. The target is WEB. Dry-run mode is off.",
            ),
            (
                "The task flag is BETA. The target is WEB. Dry-run mode is off.",
                "The task flag is ALPHA. The target is MOBILE. Dry-run mode is off.",
                "The task flag is ALPHA. The target is WEB. Dry-run mode is on.",
            ),
        ),
        TaskCase(
            "severity_threshold",
            "severity is at least 7 and the environment is production",
            (
                "Severity is 7. The environment is production.",
                "Severity is 9. The environment is production.",
            ),
            (
                "Severity is 6. The environment is production.",
                "Severity is 9. The environment is staging.",
            ),
        ),
        TaskCase(
            "exclusive_degradation",
            "exactly one of the cache and database is degraded",
            (
                "The cache is degraded. The database is healthy.",
                "The cache is healthy. The database is degraded.",
            ),
            (
                "The cache is healthy. The database is healthy.",
                "The cache is degraded. The database is degraded.",
            ),
        ),
        TaskCase(
            "artifact_membership",
            "the requested artifact format is DOCX or PPTX",
            (
                "The requested artifact format is DOCX.",
                "The requested artifact format is PPTX.",
            ),
            (
                "The requested artifact format is PDF.",
                "The requested artifact format is XLSX.",
            ),
        ),
        TaskCase(
            "negative_state",
            "the environment is not staging",
            (
                "The environment is production.",
                "The environment is development.",
            ),
            ("The environment is staging.",),
        ),
        TaskCase(
            "nested_boolean",
            "priority is HIGH or CRITICAL, and an owner is assigned",
            (
                "Priority is HIGH. An owner is assigned.",
                "Priority is CRITICAL. An owner is assigned.",
            ),
            (
                "Priority is HIGH. No owner is assigned.",
                "Priority is LOW. An owner is assigned.",
                "Priority is LOW. No owner is assigned.",
            ),
        ),
        TaskCase(
            "realistic_docx",
            "the user asks to create or edit a Microsoft Word DOCX document",
            (
                "The user asks: Create a polished Microsoft Word DOCX report.",
                "The user asks: Edit the attached DOCX and preserve its layout.",
            ),
            (
                "The user asks: Create a polished PDF report.",
                "The user asks: Update this Google Doc in place.",
            ),
            "realistic",
            "anthropics/skills docx trigger boundaries",
        ),
        TaskCase(
            "realistic_imagegen",
            "the user asks to generate or edit a raster image",
            (
                "The user asks: Generate a watercolor illustration of a lighthouse.",
                "The user asks: Remove the background from this product photo.",
            ),
            (
                "The user asks: Plot quarterly revenue as a bar chart.",
                "The user asks: Create a Mermaid architecture diagram.",
            ),
            "realistic",
            "OpenAI image-generation skill boundaries",
        ),
        TaskCase(
            "realistic_diagnosis",
            "the user reports a bug or failure and asks for diagnosis",
            (
                "The user says: This command is failing with exit code 2. Diagnose it.",
                "The user says: The app crashes after rotation. Debug the cause.",
            ),
            (
                "The user says: Implement a new export button from this specification.",
                "The user says: Explain the architecture of this working module.",
            ),
            "realistic",
            "Matt Pocock diagnosing-bugs skill family",
        ),
        TaskCase(
            "realistic_openai_docs",
            "the user asks how to build with or configure an OpenAI product",
            (
                "The user asks: How does implicit Codex skill activation work?",
                "The user asks: Which Responses API field enables structured output?",
            ),
            (
                "The user asks: Write a Python function that sorts integers.",
                "The user asks: Explain how a binary search tree works.",
            ),
            "realistic",
            "OpenAI Codex skills documentation",
        ),
        TaskCase(
            "realistic_diagram",
            "the user asks for a Mermaid or software-system diagram",
            (
                "The user asks: Create a Mermaid sequence diagram for this login flow.",
                "The user asks: Draw a component diagram for these services.",
            ),
            (
                "The user asks: Summarize this login flow in three sentences.",
                "The user asks: Rename a variable in this function.",
            ),
            "realistic",
            "Web Dev Cody diagram skill, paraphrased",
        ),
    )
}


def case_ids() -> tuple[str, ...]:
    return tuple(CASES)


def case_ids_for_layer(layer: str) -> tuple[str, ...]:
    if layer == "all":
        return case_ids()
    return tuple(case_id for case_id, case in CASES.items() if case.layer == layer)
