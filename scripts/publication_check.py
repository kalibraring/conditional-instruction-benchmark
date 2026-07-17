from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable


IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "plans",
    "results",
}
FORBIDDEN_SUFFIXES = (
    ".private.jsonl",
    ".private.yaml",
    ".pem",
    ".p12",
    ".pfx",
)
MAX_FILE_BYTES = 5 * 1024 * 1024
SELF = Path("scripts/publication_check.py")
PATTERNS = {
    "absolute workstation path": re.compile(
        r"(?:^|[\s\"'(])(?:/(?:Users|home)/[^/\s]+/|[A-Za-z]:\\Users\\)",
        re.MULTILINE,
    ),
    "GitHub token": re.compile(r"(?:github_pat_|gh[opsu]_)[A-Za-z0-9_]{20,}"),
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY"),
    "private organization domain": re.compile(r"@agoda\.com\b", re.IGNORECASE),
    "local username": re.compile(r"\bmkamar\b", re.IGNORECASE),
}


def _tracked_files(root: Path) -> Iterable[Path]:
    if (root / ".git").exists():
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        for raw in completed.stdout.split(b"\0"):
            if raw:
                yield root / raw.decode("utf-8")
        return
    for path in root.rglob("*"):
        if path.is_file() and not any(part in IGNORED_PARTS for part in path.parts):
            yield path


def scan(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in sorted(_tracked_files(root)):
        relative = path.relative_to(root)
        relative_text = relative.as_posix()
        if any(part in IGNORED_PARTS for part in relative.parts):
            findings.append({"path": relative_text, "reason": "forbidden path"})
            continue
        if relative_text.endswith(FORBIDDEN_SUFFIXES):
            findings.append({"path": relative_text, "reason": "forbidden file type"})
            continue
        if path.is_symlink():
            findings.append({"path": relative_text, "reason": "symlink in release"})
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            findings.append({"path": relative_text, "reason": "file exceeds 5 MiB"})
            continue
        if relative == SELF:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for reason, pattern in PATTERNS.items():
            if pattern.search(content):
                findings.append({"path": relative_text, "reason": reason})
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    findings = scan(root)
    report = {
        "root": str(root),
        "files_checked": sum(1 for _ in _tracked_files(root)),
        "findings": findings,
        "passed": not findings,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
