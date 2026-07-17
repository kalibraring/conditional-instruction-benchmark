import json
import tempfile
import unittest
from pathlib import Path

from cib.manifest import build_manifest
from cib.materialize import materialize_run
from cib.promptfoo import export_promptfoo_suite


class MaterializationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
