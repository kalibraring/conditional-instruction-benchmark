import unittest

from cib.codex_adapter import _target_observation


class TargetObservationTests(unittest.TestCase):
    def test_ignores_nonce_from_untargeted_resource(self) -> None:
        events = [
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "sed resources/policy-card.md",
                    "aggregated_output": "CANARY:abc",
                },
            }
        ]
        self.assertEqual(
            _target_observation(events, "resources/probe.py", "abc"),
            (False, False),
        )

    def test_requires_target_and_marker_output(self) -> None:
        events = [
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "python3 resources/probe.py",
                    "aggregated_output": "CANARY:abc",
                },
            }
        ]
        self.assertEqual(
            _target_observation(events, "resources/probe.py", "abc"),
            (True, True),
        )

    def test_reading_probe_source_is_not_execution(self) -> None:
        events = [
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "sed -n '1,20p' resources/probe.py",
                    "aggregated_output": "print('CANARY:abc')",
                },
            }
        ]
        self.assertEqual(
            _target_observation(events, "resources/probe.py", "abc"),
            (False, False),
        )


if __name__ == "__main__":
    unittest.main()
