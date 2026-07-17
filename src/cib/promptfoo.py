from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

from .contracts import MaterializedTrial
from .scoring import target_fragment
from .trials import prompt_for
from .tasks import TaskCase


def export_promptfoo_suite(
    rows: Iterable[MaterializedTrial],
    output_dir: Path,
    cases: Mapping[str, TaskCase] | None = None,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "protected" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    package_root = Path(__file__).resolve().parent
    assertion_path = package_root / "promptfoo_assets" / "cib-canary.cjs"
    extension_path = package_root / "promptfoo_assets" / "archive.cjs"
    tests_path = output_dir / "tests.jsonl"
    tests: list[dict[str, object]] = []
    for row in rows:
        manifest = row.manifest
        schema = json.loads(
            (Path(row.working_dir) / "output-schema.json").read_text(encoding="utf-8")
        )
        tests.append(
            {
                "description": manifest.trial_id,
                "vars": {
                    "rendered_prompt": prompt_for(manifest.to_spec(), cases),
                    "cib_manifest": manifest.to_private_dict(),
                    "target_fragment": target_fragment(manifest.placement),
                },
                "metadata": {
                    **manifest.to_public_dict(),
                    "fixture_hash": row.fixture_hash,
                    "raw_dir": str(raw_dir.resolve()),
                },
                "options": {
                    "working_dir": row.working_dir,
                    "model": manifest.model,
                    "model_reasoning_effort": manifest.reasoning_effort,
                    "sandbox_mode": "read-only",
                    "approval_policy": "never",
                    "skip_git_repo_check": False,
                    "persist_threads": False,
                    "enable_streaming": True,
                    "deep_tracing": False,
                    "inherit_process_env": False,
                    "output_schema": schema,
                    "cli_env": {
                        "HOME": row.home,
                        "CODEX_HOME": row.codex_home,
                    },
                    "bustCache": True,
                },
                "assert": [
                    {
                        "type": "javascript",
                        "value": f"file://{assertion_path}",
                    }
                ],
            }
        )
    tests_path.write_text(
        "".join(json.dumps(test, separators=(",", ":")) + "\n" for test in tests),
        encoding="utf-8",
    )
    config_path = output_dir / "promptfooconfig.yaml"
    config_path.write_text(
        "\n".join(
            [
                "# yaml-language-server: $schema=https://promptfoo.dev/config-schema.json",
                "description: CIB scientific execution",
                "prompts:",
                "  - id: cib-trial",
                "    raw: '{{ rendered_prompt }}'",
                "providers:",
                "  - id: openai:codex-sdk",
                "    config:",
                "      sandbox_mode: read-only",
                "      approval_policy: never",
                "      persist_threads: false",
                "      inherit_process_env: false",
                f"tests: file://{tests_path.name}",
                "extensions:",
                f"  - file://{extension_path}:extensionHook",
                "evaluateOptions:",
                "  cache: false",
                "sharing: false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path, tests_path
