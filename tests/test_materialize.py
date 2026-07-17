import json
import hashlib
import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cib.manifest import build_manifest
from cib.materialize import (
    CLOUD_CONFIG_CACHE,
    load_cloud_config_seed,
    materialize_run,
)
from cib.promptfoo import export_promptfoo_suite


class MaterializationTests(unittest.TestCase):
    @staticmethod
    def _cache_bytes(now: datetime, *, expires_in: int = 3600) -> bytes:
        return json.dumps(
            {
                "signature": "signed-value",
                "signed_payload": {
                    "account_id": "private-account",
                    "chatgpt_user_id": "private-user",
                    "bundle": {"private": True},
                    "cached_at": now.isoformat(),
                    "expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
                    "version": 7,
                },
            },
            separators=(",", ":"),
        ).encode()

    def test_materializes_unique_fixtures_and_promptfoo_rows(self) -> None:
        rows = build_manifest(
            run_id="small",
            case_ids=("literal_flag",),
            placements=("prompt_start",),
            replicates=1,
            seed=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            materialized = materialize_run(rows, root / "run", auth)
            self.assertEqual(len(materialized), 6)
            self.assertEqual(
                len({row.working_dir for row in materialized}), len(materialized)
            )
            for row in materialized:
                self.assertTrue((Path(row.working_dir) / ".git").exists())
                self.assertTrue(Path(row.codex_home, "auth.json").is_symlink())
                self.assertTrue(row.fixture_hash)

            public_rows = [
                json.loads(line)
                for line in (root / "run" / "materialized-manifest.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertTrue(public_rows)
            for public_row in public_rows:
                self.assertNotIn("working_dir", public_row)
                self.assertNotIn("home", public_row)
                self.assertNotIn("codex_home", public_row)
                self.assertNotIn(str(root), json.dumps(public_row))

            config_path, tests_path = export_promptfoo_suite(
                materialized,
                root / "run" / "promptfoo",
                trial_timeout_seconds=30,
                study_timeout_seconds=180,
            )
            self.assertTrue(config_path.exists())
            config = config_path.read_text()
            self.assertIn("timeoutMs: 30000", config)
            self.assertIn("maxEvalTimeMs: 180000", config)
            tests = [json.loads(line) for line in tests_path.read_text().splitlines()]
            self.assertEqual(len(tests), 6)
            self.assertEqual(
                len({test["options"]["working_dir"] for test in tests}), 6
            )
            self.assertTrue(
                all(test["options"]["cli_env"]["CODEX_HOME"] for test in tests)
            )

    def test_copies_one_validated_cache_snapshot_privately(self) -> None:
        rows = build_manifest(
            run_id="seeded",
            case_ids=("literal_flag",),
            placements=("prompt_start",),
            replicates=1,
            seed=1,
        )[:2]
        now = datetime.now(timezone.utc)
        data = self._cache_bytes(now)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            source = root / CLOUD_CONFIG_CACHE
            source.write_bytes(data)
            seed = load_cloud_config_seed(
                auth, now=now, minimum_remaining_seconds=600
            )
            self.assertIsNotNone(seed)
            assert seed is not None
            materialized = materialize_run(
                rows, root / "run", auth, cloud_config_seed=seed
            )
            copies = [Path(row.codex_home) / CLOUD_CONFIG_CACHE for row in materialized]
            self.assertEqual(len(copies), 2)
            self.assertEqual({path.read_bytes() for path in copies}, {data})
            self.assertTrue(
                all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in copies)
            )
            self.assertNotEqual(copies[0].stat().st_ino, copies[1].stat().st_ino)
            self.assertEqual(seed.sha256, hashlib.sha256(data).hexdigest())
            self.assertNotIn("private-account", json.dumps(seed.to_safe_dict()))

    def test_rejects_or_skips_unsafe_and_stale_cache_seeds(self) -> None:
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            source = root / CLOUD_CONFIG_CACHE
            source.write_bytes(self._cache_bytes(now, expires_in=10))
            self.assertIsNone(
                load_cloud_config_seed(
                    auth, now=now, minimum_remaining_seconds=11
                )
            )
            source.write_text('{"signed_payload":{}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "signed-bundle"):
                load_cloud_config_seed(auth, now=now)
            unsafe = json.loads(self._cache_bytes(now))
            unsafe["signed_payload"]["version"] = "/" + "Users/private/account"
            source.write_text(json.dumps(unsafe), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "version"):
                load_cloud_config_seed(auth, now=now)
            source.unlink()
            target = root / "elsewhere.json"
            target.write_bytes(self._cache_bytes(now))
            os.symlink(target, source)
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                load_cloud_config_seed(auth, now=now)


if __name__ == "__main__":
    unittest.main()
