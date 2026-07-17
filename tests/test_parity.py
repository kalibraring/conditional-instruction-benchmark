import json
import tempfile
import unittest
from pathlib import Path

from cib.parity import verify_archive


class ParityTests(unittest.TestCase):
    def test_verifies_synthetic_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "results" / "run" / "raw"
            raw_dir.mkdir(parents=True)
            raw = {
                "spec": {
                    "trial_id": "t",
                    "arm": "if",
                    "condition_true": True,
                    "placement": "prompt_start",
                    "case_id": "literal_flag",
                    "case_variant": 0,
                    "model": "m",
                    "reasoning_effort": "high",
                },
                "nonce": "abc",
                "exit_code": 0,
                "timed_out": False,
                "latency_seconds": 1,
                "target_resource_used": True,
                "marker_executed": True,
                "nonce_recovered": True,
                "final_response": {"resource_nonce": "abc"},
                "usage": {},
                "stderr": "",
                "events": [
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "python3 resources/probe.py",
                            "aggregated_output": "CANARY:abc",
                        },
                    }
                ],
            }
            (raw_dir / "t.json").write_text(json.dumps(raw), encoding="utf-8")
            (raw_dir.parent / "probe-summary.json").write_text(
                json.dumps(
                    [
                        {
                            "trial_id": "t",
                            "condition_true": True,
                            "exit_code": 0,
                            "target_resource_used": True,
                            "marker_executed": True,
                            "nonce_recovered": True,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            report = verify_archive(root)
            self.assertTrue(report["passed"])
            self.assertEqual(report["checked_trials"], 1)
            self.assertEqual(report["unadjudicated_disagreement_count"], 0)


if __name__ == "__main__":
    unittest.main()
