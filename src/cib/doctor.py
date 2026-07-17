from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _version(command: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    output = "\n".join((completed.stdout, completed.stderr)).strip().splitlines()
    version_lines = [
        line.strip()
        for line in output
        if re.search(r"(?:^|\s)v?\d+\.\d+\.\d+(?:\s|$)", line.strip())
    ]
    detail = version_lines[-1] if version_lines else (
        output[0].strip() if output else "no version output"
    )
    return completed.returncode == 0, detail


def inspect_environment(
    project_root: Path,
    auth_path: Path,
    backend: str | None = None,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    checks["python"] = {
        "ok": sys.version_info >= (3, 11),
        "detail": sys.version.split()[0],
    }
    commands = [("codex", ["codex", "--version"])]
    if backend in (None, "promptfoo-codex-sdk"):
        commands.append(("node", ["node", "--version"]))
    for name, command in commands:
        executable = shutil.which(command[0])
        ok, detail = _version(command) if executable else (False, "not found on PATH")
        checks[name] = {"ok": ok, "detail": detail}

    if backend in (None, "promptfoo-codex-sdk"):
        local_promptfoo = project_root / "node_modules" / ".bin" / "promptfoo"
        promptfoo = local_promptfoo if local_promptfoo.exists() else None
        if promptfoo is None:
            discovered = shutil.which("promptfoo")
            promptfoo = Path(discovered) if discovered else None
        ok, detail = (
            _version([str(promptfoo), "--version"])
            if promptfoo
            else (False, "run npm ci or install Promptfoo on PATH")
        )
        checks["promptfoo"] = {"ok": ok, "detail": detail}
    checks["codex_auth"] = {
        "ok": auth_path.is_file(),
        "detail": "present" if auth_path.is_file() else "not found",
    }
    if backend is None or (
        backend == "promptfoo-codex-sdk"
        and (project_root / "package.json").is_file()
    ):
        package_json = project_root / "package.json"
        pinned = None
        if package_json.is_file():
            pinned = json.loads(package_json.read_text(encoding="utf-8")).get(
                "dependencies", {}
            ).get("promptfoo")
        checks["promptfoo_pin"] = {
            "ok": bool(pinned),
            "detail": str(pinned or "package.json dependency missing"),
        }
    return {
        "ready": all(check["ok"] for check in checks.values()),
        "checks": checks,
    }
