from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .trials import TrialSpec, prompt_for, write_fixture


@dataclass
class TrialResult:
    spec: dict[str, object]
    nonce: str
    exit_code: int
    timed_out: bool
    latency_seconds: float
    resource_touched: bool
    target_resource_used: bool
    marker_executed: bool
    nonce_recovered: bool
    final_response: dict[str, Any] | None
    usage: dict[str, Any] | None
    commands: list[str]
    stderr: str
    events: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CodexAdapter:
    def __init__(self, raw_dir: Path, timeout_seconds: int = 300) -> None:
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds
        self.real_codex_home = Path(
            os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
        ).expanduser()
        self.auth_path = self.real_codex_home / "auth.json"

    def run(self, spec: TrialSpec) -> TrialResult:
        if not self.auth_path.exists():
            raise RuntimeError(f"Codex auth not found at {self.auth_path}")

        nonce = secrets.token_hex(16)
        with tempfile.TemporaryDirectory(prefix="cib-trial-") as tmp:
            root = Path(tmp)
            fixture = root / "fixture"
            fixture.mkdir()
            write_fixture(fixture, spec, nonce)
            subprocess.run(
                ["git", "init", "-q"],
                cwd=fixture,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            isolated_home = root / "home"
            isolated_codex_home = root / "codex-home"
            isolated_home.mkdir()
            isolated_codex_home.mkdir()
            (isolated_codex_home / "auth.json").symlink_to(self.auth_path)

            env = os.environ.copy()
            env["HOME"] = str(isolated_home)
            env["CODEX_HOME"] = str(isolated_codex_home)
            env.pop("OPENAI_API_KEY", None)
            env.pop("CODEX_API_KEY", None)

            command = [
                "codex",
                "exec",
                "--json",
                "--ephemeral",
                "--ignore-user-config",
                "--disable",
                "plugins",
                "--disable",
                "remote_plugin",
                "--disable",
                "plugin_sharing",
                "--sandbox",
                "read-only",
                "--model",
                spec.model,
                "-c",
                f'model_reasoning_effort="{spec.reasoning_effort}"',
                "-C",
                str(fixture),
                "--output-schema",
                str(fixture / "output-schema.json"),
                prompt_for(spec),
            ]

            started = time.monotonic()
            process = subprocess.Popen(
                command,
                cwd=fixture,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=self.timeout_seconds)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                exit_code = 124
            latency = time.monotonic() - started

        events = _parse_events(stdout)
        commands = _commands(events)
        final_response = _final_response(events)
        usage = _usage(events)
        resource_touched = any(
            any(
                path in command
                for path in (
                    ".agents/skills/canary-resource",
                    "resources/probe.py",
                    "resources/policy-card.md",
                )
            )
            for command in commands
        )
        target_fragment = (
            ".agents/skills/canary-resource/reference.md"
            if spec.placement == "skill_reference"
            else (
                ".agents/skills/canary-resource/probe.py"
                if spec.placement.startswith("skill_")
                else "resources/probe.py"
            )
        )
        target_resource_used, marker_executed = _target_observation(
            events, target_fragment, nonce
        )
        reported_nonce = (
            final_response.get("resource_nonce") if final_response else None
        )
        nonce_recovered = reported_nonce in (nonce, f"CANARY:{nonce}")

        result = TrialResult(
            spec=spec.to_dict(),
            nonce=nonce,
            exit_code=exit_code,
            timed_out=timed_out,
            latency_seconds=latency,
            resource_touched=resource_touched,
            target_resource_used=target_resource_used,
            marker_executed=marker_executed,
            nonce_recovered=nonce_recovered,
            final_response=final_response,
            usage=usage,
            commands=commands,
            stderr=stderr,
            events=events,
        )
        output = self.raw_dir / f"{spec.trial_id}.json"
        output.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        return result


def _parse_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _commands(events: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        command = item.get("command")
        if isinstance(command, str):
            commands.append(command)
        elif isinstance(command, list):
            commands.append(" ".join(str(part) for part in command))
    return commands


def _final_response(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _usage(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("type") == "turn.completed" and isinstance(
            event.get("usage"), dict
        ):
            return event["usage"]
    return None


def _target_observation(
    events: list[dict[str, Any]], target_fragment: str, nonce: str
) -> tuple[bool, bool]:
    used = False
    marker = False
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        command = item.get("command")
        command_text = (
            command
            if isinstance(command, str)
            else " ".join(str(part) for part in command or [])
        )
        if target_fragment not in command_text:
            continue
        if target_fragment.endswith("probe.py") and "python3" not in command_text:
            continue
        used = True
        output = item.get("aggregated_output")
        if isinstance(output, str) and f"CANARY:{nonce}" in output:
            marker = True
    return used, marker
