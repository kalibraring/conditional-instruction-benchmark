import json
import os
import signal
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from cib.contracts import ManifestRow, MaterializedTrial
from cib.direct_backend import direct_command, run_direct_suite, run_direct_trial
from cib.scoring import score_envelope


class DirectBackendTests(unittest.TestCase):
    def _rows(self, root: Path, count: int) -> list[MaterializedTrial]:
        rows = []
        for index in range(count):
            trial_root = root / f"trial-{index}"
            work = trial_root / "work"
            home = trial_root / "home"
            codex_home = trial_root / "codex-home"
            for path in (work, home, codex_home):
                path.mkdir(parents=True)
            manifest = ManifestRow.create(
                run_id="r",
                trial_id=f"t-{index}",
                block_id=f"b-{index}",
                random_order=index,
                arm="if",
                condition_true=True,
                case_id="literal_flag",
                case_variant=0,
                placement="prompt_start",
                model="m",
                reasoning_effort="high",
                target_adapter="direct-codex",
                nonce=f"nonce-{index}",
            )
            rows.append(
                MaterializedTrial(
                    manifest,
                    str(work),
                    str(home),
                    str(codex_home),
                    "hash",
                )
            )
        return rows

    def _executable(self, root: Path, body: str) -> Path:
        script = root / "fake-codex"
        script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return script

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

    def test_study_deadline_does_not_spawn_queued_trials(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spawn_log = root / "spawns"
            codex = self._executable(
                root,
                f"printf x >> {str(spawn_log)!r}\nsleep 30",
            )
            audit = run_direct_suite(
                self._rows(root, 3),
                root / "output",
                jobs=1,
                codex_path=str(codex),
                trial_timeout_seconds=5,
                study_timeout_seconds=1,
            )

            self.assertTrue(
                spawn_log.exists(),
                (root / "output" / "raw" / "t-0.json").read_text(),
            )
            self.assertEqual(spawn_log.read_text(), "x")
            self.assertFalse(audit["passed"])
            self.assertTrue(audit["study_timed_out"])
            self.assertEqual(audit["study_timeout_count"], 3)
            self.assertEqual(audit["study_timeout_trial_ids"], ["t-0", "t-1", "t-2"])
            summary = json.loads((root / "output" / "summary.json").read_text())
            self.assertEqual([row["started"] for row in summary], [True, False, False])
            self.assertTrue(all(row["harness_failure"] for row in summary))
            queued_raw = json.loads(
                (root / "output" / "raw" / "t-1.json").read_text()
            )
            self.assertEqual(queued_raw["timeout_scope"], "study")
            self.assertFalse(queued_raw["started"])
            self.assertEqual(queued_raw["exit_code"], 124)

    def test_study_timeout_kills_running_child_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child_pid_path = root / "child.pid"
            codex = self._executable(
                root,
                f"sleep 30 &\necho $! > {str(child_pid_path)!r}\nwait",
            )
            audit = run_direct_suite(
                self._rows(root, 1),
                root / "output",
                jobs=1,
                codex_path=str(codex),
                trial_timeout_seconds=5,
                study_timeout_seconds=1,
            )
            self.assertTrue(
                child_pid_path.exists(),
                (root / "output" / "raw" / "t-0.json").read_text(),
            )
            child_pid = int(child_pid_path.read_text())

            child_alive = True
            for _ in range(100):
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    child_alive = False
                    break
                time.sleep(0.02)
            self.assertFalse(child_alive, "timed-out Codex child process leaked")
            self.assertEqual(audit["study_timeout_trial_ids"], ["t-0"])

    def test_process_group_exit_race_during_timeout_is_safe(self) -> None:
        class BoundaryExitProcess:
            pid = 424242
            returncode = 0

            def __init__(self) -> None:
                self.calls = 0

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired(["fake-codex"], timeout)
                return "", ""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process = BoundaryExitProcess()
            with (
                mock.patch("cib.direct_backend.subprocess.Popen", return_value=process),
                mock.patch("cib.direct_backend.os.killpg", side_effect=ProcessLookupError),
            ):
                result = run_direct_trial(
                    self._rows(root, 1)[0],
                    root / "raw",
                    timeout_seconds=0.01,
                    codex_path="fake-codex",
                )

            self.assertTrue(result["harness_failure"])
            self.assertEqual(result["timeout_scope"], "trial")
            self.assertEqual(process.calls, 2)

    def test_delayed_popen_rechecks_shared_deadline_before_communicate(self) -> None:
        class DelayedStartProcess:
            pid = 424243
            returncode = None

            def __init__(self) -> None:
                self.communicate_timeouts: list[float | None] = []

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                self.communicate_timeouts.append(timeout)
                return "", ""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process = DelayedStartProcess()

            def delayed_popen(*args: object, **kwargs: object) -> DelayedStartProcess:
                time.sleep(0.05)
                return process

            with (
                mock.patch("cib.direct_backend.subprocess.Popen", side_effect=delayed_popen),
                mock.patch("cib.direct_backend.os.killpg") as killpg,
            ):
                audit = run_direct_suite(
                    self._rows(root, 2),
                    root / "output",
                    jobs=1,
                    trial_timeout_seconds=1,
                    study_timeout_seconds=0.02,
                    codex_path="fake-codex",
                )

            self.assertEqual(killpg.call_args_list, [mock.call(process.pid, 15)])
            self.assertEqual(len(process.communicate_timeouts), 1)
            self.assertGreater(process.communicate_timeouts[0] or 0, 0)
            self.assertEqual(audit["study_timeout_trial_ids"], ["t-0", "t-1"])
            summary = json.loads((root / "output" / "summary.json").read_text())
            self.assertEqual([row["started"] for row in summary], [True, False])

    def test_crossing_deadline_during_scoring_is_study_timeout(self) -> None:
        class CompletedProcess:
            pid = 424244
            returncode = 0

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                return "", ""

        scoring_calls = 0

        def delayed_score(envelope: object) -> dict[str, object]:
            nonlocal scoring_calls
            scoring_calls += 1
            if scoring_calls == 1:
                time.sleep(0.03)
            return score_envelope(envelope)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                mock.patch(
                    "cib.direct_backend.subprocess.Popen",
                    return_value=CompletedProcess(),
                ),
                mock.patch("cib.direct_backend.score_envelope", side_effect=delayed_score),
            ):
                audit = run_direct_suite(
                    self._rows(root, 1),
                    root / "output",
                    jobs=1,
                    trial_timeout_seconds=1,
                    study_timeout_seconds=0.02,
                    codex_path="fake-codex",
                )

            self.assertFalse(audit["passed"])
            self.assertEqual(audit["study_timeout_trial_ids"], ["t-0"])
            self.assertEqual(scoring_calls, 2)

    def test_multi_batch_total_can_exceed_per_trial_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex = self._executable(root, "sleep 0.6")
            started = time.monotonic()
            audit = run_direct_suite(
                self._rows(root, 3),
                root / "output",
                jobs=1,
                codex_path=str(codex),
                trial_timeout_seconds=1.5,
                study_timeout_seconds=5,
            )
            elapsed = time.monotonic() - started

            self.assertGreater(elapsed, 1.5)
            self.assertTrue(audit["passed"])
            self.assertFalse(audit["study_timed_out"])
            self.assertEqual(audit["trial_timeout_count"], 0)
            self.assertEqual(audit["study_timeout_count"], 0)

    def test_legacy_suite_timeout_keeps_integrity_audit_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex = self._executable(root, "sleep 30")
            audit = run_direct_suite(
                self._rows(root, 1),
                root / "output",
                jobs=1,
                timeout_seconds=1,
                codex_path=str(codex),
            )

            self.assertTrue(audit["passed"])
            self.assertFalse(audit["study_timed_out"])
            self.assertEqual(audit["trial_timeout_count"], 1)
            self.assertEqual(audit["study_timeout_count"], 0)

    def test_per_trial_timeout_escalates_to_sigkill_for_ignoring_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            parent_pid_path = root / "parent.pid"
            child_pid_path = root / "child.pid"
            codex = self._executable(
                root,
                "trap '' TERM\n"
                f"echo $$ > {str(parent_pid_path)!r}\n"
                "/bin/sh -c 'trap \"\" TERM; while :; do sleep 1; done' &\n"
                f"echo $! > {str(child_pid_path)!r}\n"
                "while :; do sleep 1; done",
            )
            with (
                mock.patch(
                    "cib.direct_backend.PROCESS_GROUP_TERM_GRACE_SECONDS", 0.1
                ),
                mock.patch(
                    "cib.direct_backend.os.killpg", wraps=os.killpg
                ) as killpg,
            ):
                audit = run_direct_suite(
                    self._rows(root, 1),
                    root / "output",
                    jobs=1,
                    timeout_seconds=1,
                    codex_path=str(codex),
                )

            pids = [int(parent_pid_path.read_text()), int(child_pid_path.read_text())]
            remaining = set(pids)
            for _ in range(100):
                for pid in tuple(remaining):
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        remaining.remove(pid)
                if not remaining:
                    break
                time.sleep(0.02)

            self.assertFalse(remaining, f"SIGKILL left process IDs alive: {remaining}")
            self.assertEqual(
                [call.args[1] for call in killpg.call_args_list],
                [signal.SIGTERM, signal.SIGKILL],
            )
            self.assertTrue(audit["passed"])
            self.assertEqual(audit["trial_timeout_trial_ids"], ["t-0"])


if __name__ == "__main__":
    unittest.main()
