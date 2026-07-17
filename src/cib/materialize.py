from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Iterable, Mapping

from .contracts import ManifestRow, MaterializedTrial
from .trials import write_fixture
from .tasks import TaskCase


def read_materialized_manifest(path: Path) -> list[MaterializedTrial]:
    return [
        MaterializedTrial.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _fixture_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def materialize_run(
    rows: Iterable[ManifestRow],
    run_dir: Path,
    auth_path: Path,
    cases: Mapping[str, TaskCase] | None = None,
) -> list[MaterializedTrial]:
    if not auth_path.exists():
        raise FileNotFoundError(f"Codex auth not found: {auth_path}")
    run_dir.mkdir(parents=True, exist_ok=True)
    output: list[MaterializedTrial] = []
    for row in rows:
        trial_root = run_dir / "trials" / row.trial_id
        fixture = trial_root / "fixture"
        home = trial_root / "home"
        codex_home = trial_root / "codex-home"
        if trial_root.exists():
            raise FileExistsError(f"Refusing to reuse trial directory: {trial_root}")
        fixture.mkdir(parents=True)
        home.mkdir()
        codex_home.mkdir()
        write_fixture(fixture, row.to_spec(), row.nonce, cases)
        subprocess.run(
            ["git", "init", "-q"],
            cwd=fixture,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.symlink(auth_path.resolve(), codex_home / "auth.json")
        output.append(
            MaterializedTrial(
                manifest=row,
                working_dir=str(fixture.resolve()),
                home=str(home.resolve()),
                codex_home=str(codex_home.resolve()),
                fixture_hash=_fixture_hash(fixture),
            )
        )
    manifest_path = run_dir / "materialized-manifest.private.jsonl"
    manifest_path.write_text(
        "".join(json.dumps(row.to_private_dict(), sort_keys=True) + "\n" for row in output),
        encoding="utf-8",
    )
    public_path = run_dir / "materialized-manifest.jsonl"
    public_path.write_text(
        "".join(json.dumps(row.to_public_dict(), sort_keys=True) + "\n" for row in output),
        encoding="utf-8",
    )
    return output
