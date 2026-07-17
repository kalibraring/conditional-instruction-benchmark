from __future__ import annotations

import json
import hashlib
import random
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .contracts import ManifestRow
from .trials import Arm


ARMS: tuple[Arm, ...] = ("if", "iff", "if_else_not")


def build_manifest(
    *,
    run_id: str,
    case_ids: Iterable[str],
    placements: Iterable[str],
    replicates: int,
    seed: int,
    truth_values: tuple[bool, ...] = (True, False),
    model: str = "gpt-5.6-sol",
    reasoning_effort: str = "high",
    target_adapter: str = "promptfoo-codex-sdk",
    profile: str = "scientific",
    is_primary: bool = True,
) -> list[ManifestRow]:
    if replicates < 1:
        raise ValueError("replicates must be positive")
    rows: list[ManifestRow] = []
    for replicate in range(replicates):
        for placement in placements:
            for case_id in case_ids:
                block_id = f"{placement}:{case_id}:{replicate:03d}"
                for arm in ARMS:
                    for condition_true in truth_values:
                        assignment = json.dumps(
                            {
                                "run_id": run_id,
                                "placement": placement,
                                "case_id": case_id,
                                "arm": arm,
                                "condition_true": condition_true,
                                "replicate": replicate,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        trial_id = f"{run_id}-t-{hashlib.sha256(assignment.encode()).hexdigest()[:20]}"
                        rows.append(
                            ManifestRow.create(
                                run_id=run_id,
                                trial_id=trial_id,
                                block_id=block_id,
                                random_order=-1,
                                arm=arm,
                                condition_true=condition_true,
                                case_id=case_id,
                                case_variant=replicate,
                                placement=placement,
                                model=model,
                                reasoning_effort=reasoning_effort,
                                target_adapter=target_adapter,
                                profile=profile,
                                is_primary=is_primary,
                            )
                        )
    random.Random(seed).shuffle(rows)
    return [replace(row, random_order=index) for index, row in enumerate(rows)]


def write_manifest(rows: Iterable[ManifestRow], directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    private_path = directory / "run-manifest.private.jsonl"
    public_path = directory / "run-manifest.jsonl"
    materialized = list(rows)
    private_path.write_text(
        "".join(json.dumps(row.to_private_dict(), sort_keys=True) + "\n" for row in materialized),
        encoding="utf-8",
    )
    public_path.write_text(
        "".join(json.dumps(row.to_public_dict(), sort_keys=True) + "\n" for row in materialized),
        encoding="utf-8",
    )
    return public_path, private_path


def read_private_manifest(path: Path) -> list[ManifestRow]:
    return [
        ManifestRow.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
