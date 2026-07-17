from pathlib import Path

from cib.workflow import promptfoo_command


def test_scientific_promptfoo_command_forces_non_cached_non_shared_run(tmp_path: Path) -> None:
    binary = tmp_path / "promptfoo"
    config = tmp_path / "config.yaml"
    results = tmp_path / "results.jsonl"
    command = promptfoo_command(
        binary=binary, config_path=config, result_path=results, jobs=7
    )

    assert command[0] == str(binary.resolve())
    assert "--no-cache" in command
    assert "--no-share" in command
    assert command[command.index("--max-concurrency") + 1] == "7"
    assert command[command.index("--output") + 1] == str(results.resolve())
