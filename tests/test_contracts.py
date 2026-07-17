import unittest

from cib.contracts import EvidenceEnvelope, ManifestRow, SCHEMA_VERSION


class ContractTests(unittest.TestCase):
    def test_manifest_round_trip_preserves_assignment(self) -> None:
        row = ManifestRow.create(
            run_id="run-a",
            trial_id="trial-a",
            block_id="block-a",
            random_order=3,
            arm="iff",
            condition_true=False,
            case_id="literal_flag",
            case_variant=1,
            placement="prompt_start",
            model="gpt-5.6-sol",
            reasoning_effort="high",
            target_adapter="promptfoo-codex-sdk",
        )
        rebuilt = ManifestRow.from_dict(row.to_private_dict())
        self.assertEqual(rebuilt, row)
        self.assertEqual(row.protocol_version, SCHEMA_VERSION)
        self.assertNotIn("nonce", row.to_public_dict())
        self.assertEqual(len(row.nonce_hash), 64)

    def test_evidence_envelope_requires_explicit_unavailable_fields(self) -> None:
        envelope = EvidenceEnvelope(
            manifest={"trial_id": "trial-a"},
            execution={"backend": "direct-codex", "exit_class": "completed"},
            response={"final": None, "usage": None},
            evidence={
                "normalized_steps": [],
                "raw_provider_response": {},
                "stdout": None,
                "stderr": None,
                "unavailable_fields": ["stdout", "stderr"],
            },
            observation={},
            outcome={},
            provenance={},
        )
        self.assertEqual(envelope.to_dict()["schema_version"], "cib-evidence/1")


if __name__ == "__main__":
    unittest.main()
