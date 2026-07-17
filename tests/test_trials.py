import unittest

from cib.trials import instruction_for


class InstructionTests(unittest.TestCase):
    def test_arms_preserve_requested_strings(self) -> None:
        self.assertEqual(
            instruction_for("if"),
            "Use this skill if the task flag is ALPHA.",
        )
        self.assertEqual(
            instruction_for("iff"),
            "Use this skill if and only if the task flag is ALPHA.",
        )

    def test_expanded_arm_matches_biconditional_policy(self) -> None:
        expanded = instruction_for("if_else_not")
        self.assertIn("if the task flag is ALPHA", expanded)
        self.assertIn("do not use this skill", expanded)

    def test_action_can_target_post_selection_resource(self) -> None:
        text = instruction_for("iff", "Run `probe.py`")
        self.assertEqual(
            text,
            "Run `probe.py` if and only if the task flag is ALPHA.",
        )


if __name__ == "__main__":
    unittest.main()
