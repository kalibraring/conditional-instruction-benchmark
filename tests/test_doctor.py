from pathlib import Path

from cib.doctor import inspect_environment


def test_doctor_fails_closed_when_auth_and_tools_are_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("PATH", "")
    report = inspect_environment(tmp_path, tmp_path / "missing-auth.json")
    assert report["ready"] is False
    assert report["checks"]["python"]["ok"] is True
    assert report["checks"]["codex"]["ok"] is False
    assert report["checks"]["promptfoo"]["ok"] is False
    assert report["checks"]["codex_auth"]["detail"] == "not found"
