import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from cib.contracts import ManifestRow
from cib.promptfoo_results import normalize_promptfoo_jsonl


class PromptfooResultTests(unittest.TestCase):
    @staticmethod
    def _ledger_test(manifest: ManifestRow) -> dict:
        return {
            "description": manifest.trial_id,
            "vars": {"cib_manifest": manifest.to_private_dict()},
            "metadata": {"trial_id": manifest.trial_id},
        }

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

    def test_archives_trial_timeout_row_and_keeps_integrity_auditable(self) -> None:
        manifest = ManifestRow.create(
            run_id="r",
            trial_id="timeout-trial",
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
        row = {
            "success": False,
            "error": "Evaluation timed out after 1000ms",
            "testIdx": 0,
            "vars": {
                "cib_manifest": {
                    **manifest.to_private_dict(),
                    "trial_id": "[REDACTED]",
                    "nonce_hash": "[REDACTED]",
                }
            },
            "metadata": {},
            "testCase": {
                "vars": {
                    "cib_manifest": {
                        **manifest.to_private_dict(),
                        "trial_id": "[REDACTED]",
                        "nonce_hash": "[REDACTED]",
                    }
                },
                "metadata": {"trial_id": "[REDACTED]"},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "results.jsonl"
            result_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            raw_dir = root / "raw"
            raw_dir.mkdir()
            tests_path = root / "tests.jsonl"
            tests_path.write_text(
                json.dumps(self._ledger_test(manifest)) + "\n", encoding="utf-8"
            )
            tests_hash = hashlib.sha256(tests_path.read_bytes()).hexdigest()

            audit = normalize_promptfoo_jsonl(
                result_path,
                root / "derived",
                raw_dir,
                tests_path=tests_path,
                expected_tests_sha256=tests_hash,
            )

            self.assertTrue(audit["passed"])
            self.assertEqual(audit["trial_timeout_count"], 1)
            self.assertEqual(audit["study_timeout_count"], 0)
            self.assertEqual(audit["unique_session_ids"], 0)
            self.assertFalse((raw_dir / "timeout-trial.json").exists())
            self.assertEqual(audit["ledger_recovered_source_rows"], 1)
            summary = json.loads((root / "derived" / "summary.json").read_text())
            self.assertEqual(summary[0]["failure_class"], "per_trial_timeout")
            self.assertEqual(summary[0]["evidence_source"], "frozen_tests_ledger")

    def test_sessionless_cloud_bootstrap_error_is_typed_not_a_timeout(self) -> None:
        manifest = ManifestRow.create(
            run_id="r", trial_id="cloud", block_id="b", random_order=0,
            arm="iff", condition_true=False, case_id="literal_flag",
            case_variant=0, placement="prompt_start", model="m",
            reasoning_effort="high", target_adapter="promptfoo-codex-sdk", nonce="abc",
        )
        error = (
            "Error calling OpenAI Codex SDK: Codex Exec exited with code 1: "
            "Error: timed out waiting for cloud config bundle after 15s"
        )
        row = {
            "testIdx": 0,
            "success": False,
            "error": error,
            "response": {"error": error},
            "metadata": {"trial_id": manifest.trial_id},
            "vars": {"cib_manifest": manifest.to_private_dict()},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "results.jsonl"
            result_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            raw_dir = root / "raw"
            raw_dir.mkdir()
            (raw_dir / "cloud.json").write_text(
                json.dumps({
                    "test": self._ledger_test(manifest),
                    "result": row,
                }), encoding="utf-8"
            )
            tests_path = root / "tests.jsonl"
            tests_path.write_text(
                json.dumps(self._ledger_test(manifest)) + "\n", encoding="utf-8"
            )
            audit = normalize_promptfoo_jsonl(
                result_path,
                root / "derived",
                raw_dir,
                tests_path=tests_path,
                expected_tests_sha256=hashlib.sha256(tests_path.read_bytes()).hexdigest(),
            )
            self.assertTrue(audit["passed"])
            self.assertEqual(audit["trial_timeout_count"], 0)
            self.assertEqual(audit["harness_failures"], 1)
            summary = json.loads((root / "derived" / "summary.json").read_text())
            self.assertEqual(summary[0]["failure_class"], "pre_session_transport")
            self.assertFalse(summary[0]["behavioral_success"])

    def test_completed_row_without_session_fails_integrity(self) -> None:
        manifest = ManifestRow.create(
            run_id="r", trial_id="no-session", block_id="b", random_order=0,
            arm="if", condition_true=False, case_id="literal_flag", case_variant=0,
            placement="prompt_start", model="m", reasoning_effort="high",
            target_adapter="promptfoo-codex-sdk", nonce="abc",
        )
        row = {
            "success": True,
            "metadata": {"trial_id": manifest.trial_id},
            "vars": {"cib_manifest": manifest.to_private_dict()},
            "response": {"output": '{"answer":"complete","resource_nonce":null}'},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "results.jsonl"
            result_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            raw_dir = root / "raw"
            raw_dir.mkdir()
            (raw_dir / "no-session.json").write_text(
                json.dumps({"test": self._ledger_test(manifest), "result": row}),
                encoding="utf-8",
            )
            audit = normalize_promptfoo_jsonl(result_path, root / "derived", raw_dir)
            self.assertFalse(audit["passed"])
            self.assertEqual(audit["missing_required_session_trial_ids"], ["no-session"])

    def test_changed_ledger_digest_fails_before_identity_recovery(self) -> None:
        manifest = ManifestRow.create(
            run_id="r", trial_id="t", block_id="b", random_order=0, arm="if",
            condition_true=True, case_id="literal_flag", case_variant=0,
            placement="prompt_start", model="m", reasoning_effort="high",
            target_adapter="promptfoo-codex-sdk", nonce="abc",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results.jsonl"
            results.write_text("", encoding="utf-8")
            tests_path = root / "tests.jsonl"
            tests_path.write_text(
                json.dumps(self._ledger_test(manifest)) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "digest changed"):
                normalize_promptfoo_jsonl(
                    results,
                    root / "derived",
                    tests_path=tests_path,
                    expected_tests_sha256="0" * 64,
                )
            with self.assertRaisesRegex(ValueError, "pre-run digest"):
                normalize_promptfoo_jsonl(
                    results,
                    root / "derived-unsealed",
                    tests_path=tests_path,
                )

    def test_duplicate_test_index_and_session_fail_integrity(self) -> None:
        manifests = [
            ManifestRow.create(
                run_id="r", trial_id=f"t-{index}", block_id=f"b-{index}",
                random_order=index, arm="if", condition_true=False,
                case_id="literal_flag", case_variant=index,
                placement="prompt_start", model="m", reasoning_effort="high",
                target_adapter="promptfoo-codex-sdk", nonce=f"abc{index}",
            )
            for index in range(2)
        ]
        rows = [
            {
                "testIdx": 0,
                "success": True,
                "metadata": {"trial_id": manifest.trial_id},
                "vars": {"cib_manifest": manifest.to_private_dict()},
                "response": {
                    "output": '{"answer":"complete","resource_nonce":null}',
                    "sessionId": "duplicate-session",
                },
            }
            for manifest in manifests
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "results.jsonl"
            result_path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            raw_dir = root / "raw"
            raw_dir.mkdir()
            for manifest, row in zip(manifests, rows, strict=True):
                (raw_dir / f"{manifest.trial_id}.json").write_text(
                    json.dumps({"test": self._ledger_test(manifest), "result": row}),
                    encoding="utf-8",
                )
            tests_path = root / "tests.jsonl"
            tests_path.write_text(
                "".join(
                    json.dumps(self._ledger_test(manifest)) + "\n"
                    for manifest in manifests
                ),
                encoding="utf-8",
            )
            audit = normalize_promptfoo_jsonl(
                result_path,
                root / "derived",
                raw_dir,
                tests_path=tests_path,
                expected_tests_sha256=hashlib.sha256(tests_path.read_bytes()).hexdigest(),
            )
            self.assertFalse(audit["passed"])
            self.assertEqual(audit["duplicate_test_indices"], 1)
            self.assertEqual(audit["duplicate_session_ids"], 1)

    def test_partial_timeout_response_is_still_a_harness_failure(self) -> None:
        manifest = ManifestRow.create(
            run_id="r", trial_id="partial-timeout", block_id="b", random_order=0,
            arm="iff", condition_true=False, case_id="literal_flag", case_variant=0,
            placement="prompt_start", model="m", reasoning_effort="high",
            target_adapter="promptfoo-codex-sdk", nonce="abc",
        )
        row = {
            "testIdx": 0,
            "success": False,
            "error": "Evaluation timed out after 1000ms",
            "metadata": {"trial_id": manifest.trial_id},
            "vars": {"cib_manifest": manifest.to_private_dict()},
            "response": {"output": '{"answer":"complete","resource_nonce":null}'},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "results.jsonl"
            result_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            raw_dir = root / "raw"
            raw_dir.mkdir()
            (raw_dir / f"{manifest.trial_id}.json").write_text(
                json.dumps({"test": self._ledger_test(manifest), "result": row}),
                encoding="utf-8",
            )
            tests_path = root / "tests.jsonl"
            tests_path.write_text(
                json.dumps(self._ledger_test(manifest)) + "\n", encoding="utf-8"
            )
            audit = normalize_promptfoo_jsonl(
                result_path,
                root / "derived",
                raw_dir,
                tests_path=tests_path,
                expected_tests_sha256=hashlib.sha256(tests_path.read_bytes()).hexdigest(),
            )
            summary = json.loads((root / "derived" / "summary.json").read_text())
            self.assertTrue(audit["passed"])
            self.assertTrue(summary[0]["harness_failure"])
            self.assertFalse(summary[0]["behavioral_success"])
            self.assertEqual(summary[0]["failure_class"], "per_trial_timeout")

    def test_protected_manifest_must_exactly_match_frozen_ledger(self) -> None:
        manifest = ManifestRow.create(
            run_id="r", trial_id="tamper", block_id="b", random_order=0,
            arm="if", condition_true=False, case_id="literal_flag", case_variant=0,
            placement="prompt_start", model="m", reasoning_effort="high",
            target_adapter="promptfoo-codex-sdk", nonce="abc",
        )
        tampered = {**manifest.to_private_dict(), "condition_true": True}
        response = {
            "output": '{"answer":"complete","resource_nonce":null}',
            "sessionId": "session-tamper",
        }
        row = {
            "testIdx": 0,
            "success": True,
            "metadata": {"trial_id": manifest.trial_id},
            "vars": {"cib_manifest": manifest.to_private_dict()},
            "response": response,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "results.jsonl"
            result_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            raw_dir = root / "raw"
            raw_dir.mkdir()
            (raw_dir / f"{manifest.trial_id}.json").write_text(
                json.dumps({
                    "test": {"vars": {"cib_manifest": tampered}},
                    "result": row,
                }),
                encoding="utf-8",
            )
            tests_path = root / "tests.jsonl"
            tests_path.write_text(
                json.dumps(self._ledger_test(manifest)) + "\n", encoding="utf-8"
            )
            audit = normalize_promptfoo_jsonl(
                result_path,
                root / "derived",
                raw_dir,
                tests_path=tests_path,
                expected_tests_sha256=hashlib.sha256(tests_path.read_bytes()).hexdigest(),
            )
            self.assertFalse(audit["passed"])
            self.assertIn(
                "scored manifest disagrees with frozen ledger",
                {item["reason"] for item in audit["test_index_disagreements"]},
            )

    def test_grading_error_does_not_become_a_harness_failure(self) -> None:
        manifest = ManifestRow.create(
            run_id="r", trial_id="grading-failure", block_id="b", random_order=0,
            arm="if", condition_true=True, case_id="literal_flag", case_variant=0,
            placement="prompt_start", model="m", reasoning_effort="high",
            target_adapter="promptfoo-codex-sdk", nonce="abc",
        )
        response = {
            "output": '{"answer":"complete","resource_nonce":null}',
            "sessionId": "session-grading-failure",
        }
        row = {
            "success": False,
            "error": "CIB exact resource-routing outcome failed",
            "gradingResult": {"pass": False, "reason": "routing failed"},
            "metadata": {"trial_id": manifest.trial_id},
            "vars": {"cib_manifest": manifest.to_private_dict()},
            "response": response,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "results.jsonl"
            result_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            raw_dir = root / "raw"
            raw_dir.mkdir()
            (raw_dir / f"{manifest.trial_id}.json").write_text(
                json.dumps({"test": self._ledger_test(manifest), "result": row}),
                encoding="utf-8",
            )
            audit = normalize_promptfoo_jsonl(result_path, root / "derived", raw_dir)
            summary = json.loads((root / "derived" / "summary.json").read_text())
            self.assertTrue(audit["passed"])
            self.assertFalse(summary[0]["harness_failure"])
            self.assertFalse(summary[0]["behavioral_success"])

    def test_whole_study_timeout_is_integrity_invalid(self) -> None:
        manifest = ManifestRow.create(
            run_id="r",
            trial_id="study-timeout-trial",
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
        row = {
            "success": False,
            "error": "Evaluation exceeded max duration of 3000ms",
            "vars": {"cib_manifest": manifest.to_private_dict()},
            "metadata": {"trial_id": manifest.trial_id},
            "testCase": {
                "vars": {"cib_manifest": manifest.to_private_dict()},
                "metadata": {"trial_id": manifest.trial_id},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "results.jsonl"
            result_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            raw_dir = root / "raw"
            raw_dir.mkdir()

            audit = normalize_promptfoo_jsonl(result_path, root / "derived", raw_dir)

            self.assertFalse(audit["passed"])
            self.assertTrue(audit["study_timed_out"])
            self.assertEqual(audit["study_timeout_count"], 1)

    def test_final_in_flight_codex_abort_is_whole_study_timeout(self) -> None:
        manifest = ManifestRow.create(
            run_id="r",
            trial_id="final-batch-abort",
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
        row = {
            "success": False,
            "response": {"error": "OpenAI Codex SDK call aborted"},
            "vars": {"cib_manifest": manifest.to_private_dict()},
            "metadata": {"trial_id": manifest.trial_id},
            "testCase": {
                "vars": {"cib_manifest": manifest.to_private_dict()},
                "metadata": {"trial_id": manifest.trial_id},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "results.jsonl"
            result_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            raw_dir = root / "raw"
            raw_dir.mkdir()

            audit = normalize_promptfoo_jsonl(result_path, root / "derived", raw_dir)

            self.assertFalse(audit["passed"])
            self.assertEqual(audit["study_timeout_trial_ids"], [manifest.trial_id])


if __name__ == "__main__":
    unittest.main()
