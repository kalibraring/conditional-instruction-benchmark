import json
import tempfile
import unittest
from pathlib import Path

from cib.contracts import ManifestRow
from cib.promptfoo_results import normalize_promptfoo_jsonl


class PromptfooResultTests(unittest.TestCase):
    def test_normalizes_and_audits_promptfoo_jsonl(self) -> None:
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
            target_adapter="promptfoo-codex-sdk",
            nonce="abc",
        )
        provider_response = {
            "output": '{"answer":"complete","resource_nonce":"abc"}',
            "sessionId": "session-1",
            "raw": json.dumps(
                {
                    "items": [
                        {
                            "type": "command_execution",
                            "command": "python3 resources/probe.py",
                            "aggregated_output": "CANARY:abc",
                            "exit_code": 0,
                            "status": "completed",
                        }
                    ]
                }
            ),
        }
        row = {
            "success": True,
            "vars": {"cib_manifest": manifest.to_private_dict()},
            "metadata": {"trial_id": "t"},
            "response": provider_response,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "results.jsonl"
            result_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            raw_dir = root / "raw"
            raw_dir.mkdir()
            (raw_dir / "t.json").write_text(
                json.dumps(
                    {
                        "test": {
                            "vars": {"cib_manifest": manifest.to_private_dict()},
                            "metadata": {"trial_id": "t"},
                        },
                        "result": {"success": True, "response": provider_response},
                    }
                ),
                encoding="utf-8",
            )
            audit = normalize_promptfoo_jsonl(result_path, root / "derived", raw_dir)
            self.assertTrue(audit["passed"])
            self.assertEqual(audit["behavioral_successes"], 1)


if __name__ == "__main__":
    unittest.main()
