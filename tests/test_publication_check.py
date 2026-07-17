from pathlib import Path

from scripts.publication_check import scan


def test_publication_check_detects_local_path_and_secret(tmp_path: Path) -> None:
    local_path = "/" + "Users/example/private.txt"
    token = "github_" + "pat_" + "a" * 24
    (tmp_path / "unsafe.txt").write_text(
        f"{local_path}\n{token}\n", encoding="utf-8"
    )
    reasons = {finding["reason"] for finding in scan(tmp_path)}
    assert "absolute workstation path" in reasons
    assert "GitHub token" in reasons


def test_publication_check_accepts_relative_public_source(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "Run `uv run cib doctor` from the repository root.\n", encoding="utf-8"
    )
    assert scan(tmp_path) == []
