import unittest

from cib.contracts import ManifestRow, MaterializedTrial
from cib.direct_backend import direct_command


class DirectBackendTests(unittest.TestCase):
    def test_command_preserves_scientific_isolation_flags(self) -> None:
        manifest = ManifestRow.create(
            run_id="r",
            trial_id="t",
            block_id="b",
            random_order=0,
            arm="if",
            condition_true=True,
            case_id="literal_flag",
            case_variant=0,
            placement="prompt_start",
            model="m",
            reasoning_effort="high",
            target_adapter="direct-codex",
            nonce="abc",
        )
        row = MaterializedTrial(manifest, "/tmp/work", "/tmp/home", "/tmp/codex", "hash")
        command = direct_command(row)
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("read-only", command)
        self.assertIn("plugin_sharing", command)
        self.assertIn("/tmp/work", command)


if __name__ == "__main__":
    unittest.main()
