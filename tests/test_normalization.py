import unittest

from cib.contracts import ManifestRow
from cib.normalization import normalize_direct_raw, normalize_promptfoo_response
from cib.scoring import score_envelope


def manifest(condition_true: bool = True) -> ManifestRow:
    return ManifestRow.create(
        run_id="r",
        trial_id="t",
        block_id="b",
        random_order=0,
        arm="if",
        condition_true=condition_true,
        case_id="literal_flag",
        case_variant=0,
        placement="prompt_start",
        model="gpt-5.6-sol",
        reasoning_effort="high",
        target_adapter="test",
        nonce="abc",
    )


class NormalizationTests(unittest.TestCase):
    def test_direct_and_promptfoo_items_score_identically(self) -> None:
        item = {
            "type": "command_execution",
            "command": "python3 resources/probe.py",
            "aggregated_output": "CANARY:abc\n",
            "exit_code": 0,
            "status": "completed",
        }
        direct = {
            "spec": manifest().to_spec().to_dict(),
            "nonce": "abc",
            "exit_code": 0,
            "timed_out": False,
            "latency_seconds": 1.0,
            "final_response": {"answer": "complete", "resource_nonce": "abc"},
            "usage": {},
            "stderr": "",
            "events": [
                {"type": "item.completed", "item": item},
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": '{"answer":"complete","resource_nonce":"abc"}',
                    },
                },
            ],
        }
        promptfoo = {
            "output": '{"answer":"complete","resource_nonce":"abc"}',
            "raw": {"items": [item], "usage": {}},
            "metadata": {},
        }
        direct_score = score_envelope(normalize_direct_raw(direct, manifest()))
        promptfoo_score = score_envelope(
            normalize_promptfoo_response(promptfoo, manifest())
        )
        self.assertEqual(direct_score["outcome"], promptfoo_score["outcome"])
        self.assertTrue(direct_score["outcome"]["behavioral_success"])

    def test_promptfoo_raw_json_string_is_normalized(self) -> None:
        item = {
            "type": "command_execution",
            "command": "python3 resources/probe.py",
            "aggregated_output": "CANARY:abc\n",
            "exit_code": 0,
            "status": "completed",
        }
        response = {
            "output": '{"answer":"complete","resource_nonce":"abc"}',
            "raw": __import__("json").dumps({"items": [item], "usage": {}}),
        }
        scored = score_envelope(normalize_promptfoo_response(response, manifest()))
        self.assertTrue(scored["outcome"]["behavioral_success"])

    def test_reading_probe_source_is_not_target_execution(self) -> None:
        response = {
            "output": '{"answer":"complete","resource_nonce":"abc"}',
            "raw": {
                "items": [
                    {
                        "type": "command_execution",
                        "command": "sed -n '1p' resources/probe.py",
                        "aggregated_output": "print('CANARY:abc')",
                        "exit_code": 0,
                    }
                ]
            },
        }
        scored = score_envelope(normalize_promptfoo_response(response, manifest()))
        self.assertFalse(scored["observation"]["target_action_seen"])
        self.assertFalse(scored["outcome"]["behavioral_success"])

    def test_promptfoo_synthetic_evidence_classes_remain_distinguishable(self) -> None:
        def score(item=None, *, output=None, error=None):
            response = {
                "output": output,
                "raw": {"items": [] if item is None else [item]},
            }
            if error is not None:
                response["error"] = error
            return score_envelope(normalize_promptfoo_response(response, manifest()))

        correct = score(
            {
                "type": "command_execution",
                "command": "python3 resources/probe.py",
                "aggregated_output": "CANARY:abc",
                "exit_code": 0,
                "status": "completed",
            },
            output='{"resource_nonce":"abc"}',
        )
        wrong_resource = score(
            {
                "type": "command_execution",
                "command": "python3 resources/other.py",
                "aggregated_output": "CANARY:abc",
                "exit_code": 0,
                "status": "completed",
            },
            output='{"resource_nonce":"abc"}',
        )
        copied_nonce = score(output='{"resource_nonce":"abc"}')
        missing_recovery = score(
            {
                "type": "command_execution",
                "command": "python3 resources/probe.py",
                "aggregated_output": "CANARY:abc",
                "exit_code": 0,
                "status": "completed",
            },
            output='{"resource_nonce":null}',
        )
        incomplete = score(
            {
                "type": "command_execution",
                "command": "python3 resources/probe.py",
                "aggregated_output": "CANARY:abc",
                "exit_code": None,
                "status": "in_progress",
            },
            output='{"resource_nonce":"abc"}',
        )
        nonzero = score(
            {
                "type": "command_execution",
                "command": "python3 resources/probe.py",
                "aggregated_output": "CANARY:abc",
                "exit_code": 7,
                "status": "completed",
            },
            output='{"resource_nonce":"abc"}',
        )
        timeout = score(error="provider timeout")
        scheduler = score(error="scheduler exhausted")

        self.assertTrue(correct["outcome"]["behavioral_success"])
        self.assertFalse(wrong_resource["observation"]["target_action_seen"])
        self.assertFalse(copied_nonce["observation"]["target_action_seen"])
        self.assertTrue(copied_nonce["observation"]["nonce_recovered"])
        self.assertTrue(missing_recovery["observation"]["target_action_seen"])
        self.assertFalse(missing_recovery["observation"]["nonce_recovered"])
        self.assertFalse(incomplete["observation"]["target_action_seen"])
        self.assertEqual(
            nonzero["evidence"]["normalized_steps"][0]["exit_code"], 7
        )
        self.assertTrue(timeout["outcome"]["harness_failure"])
        self.assertTrue(scheduler["outcome"]["harness_failure"])
        self.assertNotEqual(
            timeout["evidence"]["raw_provider_response"]["error"],
            scheduler["evidence"]["raw_provider_response"]["error"],
        )


if __name__ == "__main__":
    unittest.main()
