import unittest

from cib.manifest import build_manifest


class ManifestTests(unittest.TestCase):
    def test_plan_is_balanced_unique_and_seeded(self) -> None:
        first = build_manifest(
            run_id="seeded",
            case_ids=("literal_flag",),
            placements=("prompt_start",),
            replicates=2,
            seed=42,
        )
        second = build_manifest(
            run_id="seeded",
            case_ids=("literal_flag",),
            placements=("prompt_start",),
            replicates=2,
            seed=42,
        )
        self.assertEqual(len(first), 12)
        self.assertEqual(
            [row.trial_id for row in first],
            [row.trial_id for row in second],
        )
        self.assertEqual(len({row.trial_id for row in first}), 12)
        self.assertTrue(all("if_else_not" not in row.trial_id for row in first))
        self.assertEqual(len({row.nonce for row in first}), 12)
        self.assertEqual(
            {(row.arm, row.condition_true) for row in first},
            {
                ("if", True),
                ("if", False),
                ("iff", True),
                ("iff", False),
                ("if_else_not", True),
                ("if_else_not", False),
            },
        )

    def test_truth_filter_builds_24_row_contamination_plan(self) -> None:
        rows = build_manifest(
            run_id="contamination",
            case_ids=("literal_flag",),
            placements=("prompt_start",),
            replicates=8,
            seed=7,
            truth_values=(True,),
        )
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(row.condition_true for row in rows))


if __name__ == "__main__":
    unittest.main()
