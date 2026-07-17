from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from .contracts import ManifestRow, MaterializedTrial
from .trials import write_fixture
from .tasks import TaskCase


CLOUD_CONFIG_CACHE = "cloud-config-bundle-cache.json"
MAX_CLOUD_CONFIG_CACHE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class CloudConfigSeed:
    """One private, immutable snapshot of Codex's signed-format config cache."""

    data: bytes
    sha256: str
    version: int
    cached_at: str
    expires_at: str

    def to_safe_dict(self) -> dict[str, str | int | bool]:
        return {
            "present": True,
            "mode": "private_per_trial_snapshot",
            "sha256": self.sha256,
            "version": self.version,
            "cached_at": self.cached_at,
            "expires_at": self.expires_at,
        }

    def has_minimum_remaining(
        self, seconds: int, *, now: datetime | None = None
    ) -> bool:
        if seconds < 0:
            raise ValueError("minimum remaining seconds cannot be negative")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expiry = _parse_utc_timestamp(self.expires_at, "expires_at")
        return expiry.timestamp() - current.timestamp() >= seconds


def _parse_utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Cloud config cache {field} is missing or invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Cloud config cache {field} is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"Cloud config cache {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def load_cloud_config_seed(
    auth_path: Path,
    *,
    source_path: Path | None = None,
    now: datetime | None = None,
    minimum_remaining_seconds: int = 0,
) -> CloudConfigSeed | None:
    """Read and validate one bounded cache snapshot without following symlinks.

    CIB validates structure and freshness. Codex remains responsible for checking
    the signature before using the snapshot.
    """
    if minimum_remaining_seconds < 0:
        raise ValueError("minimum_remaining_seconds cannot be negative")
    source = source_path or (auth_path.parent / CLOUD_CONFIG_CACHE)
    data = read_private_snapshot(source)
    if data is None:
        return None
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Cloud config cache is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Cloud config cache must be an object")
    signature = value.get("signature")
    payload = value.get("signed_payload")
    if not isinstance(signature, str) or not signature or not isinstance(payload, dict):
        raise ValueError("Cloud config cache is not in signed-bundle format")
    cached_at = _parse_utc_timestamp(payload.get("cached_at"), "cached_at")
    expires_at = _parse_utc_timestamp(payload.get("expires_at"), "expires_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if expires_at.timestamp() - current.timestamp() < minimum_remaining_seconds:
        return None
    version = payload.get("version")
    if type(version) is not int or version < 0:
        raise ValueError("Cloud config cache version is missing or invalid")
    return CloudConfigSeed(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        version=version,
        cached_at=cached_at.isoformat(),
        expires_at=expires_at.isoformat(),
    )


def read_private_snapshot(path: Path) -> bytes | None:
    """Read one bounded regular-file snapshot without following symlinks."""
    try:
        source_lstat = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(source_lstat.st_mode) or not stat.S_ISREG(source_lstat.st_mode):
        raise ValueError("Cloud config cache must be a regular non-symlink file")
    if source_lstat.st_size > MAX_CLOUD_CONFIG_CACHE_BYTES:
        raise ValueError("Cloud config cache exceeds the size limit")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("Cloud config cache changed before it was opened")
        if opened.st_size > MAX_CLOUD_CONFIG_CACHE_BYTES:
            raise ValueError("Cloud config cache exceeds the size limit")
        chunks: list[bytes] = []
        remaining = MAX_CLOUD_CONFIG_CACHE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(data) > MAX_CLOUD_CONFIG_CACHE_BYTES:
        raise ValueError("Cloud config cache exceeds the size limit")
    return data


def private_snapshot_sha256(path: Path) -> str | None:
    data = read_private_snapshot(path)
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _write_private_snapshot(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
    finally:
        os.close(descriptor)


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
    cloud_config_seed: CloudConfigSeed | None = None,
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
        home.mkdir(mode=0o700)
        codex_home.mkdir(mode=0o700)
        write_fixture(fixture, row.to_spec(), row.nonce, cases)
        subprocess.run(
            ["git", "init", "-q"],
            cwd=fixture,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.symlink(auth_path.resolve(), codex_home / "auth.json")
        if cloud_config_seed is not None:
            cache_path = codex_home / CLOUD_CONFIG_CACHE
            _write_private_snapshot(cache_path, cloud_config_seed.data)
            if private_snapshot_sha256(cache_path) != cloud_config_seed.sha256:
                raise RuntimeError("Cloud config seed copy failed its digest check")
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
