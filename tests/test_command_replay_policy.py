from __future__ import annotations

from typing import Any

import pytest

from local_ai_hub.commands import CommandBroker


def _broker(tmp_path) -> CommandBroker:
    return CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "allow_mutating": True},
        },
        artifacts=None,
        repo_state=None,
    )


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest -q",
        'python -c "assert True"',
        "python tools/check_contracts.py",
        'pwsh -NoProfile -Command "Invoke-Pester -Path tests"',
        'powershell -NoProfile -Command "Test-Path src"',
    ],
)
def test_builtin_python_and_powershell_validation_classifiers_declare_replay_safety(
    tmp_path, command: str
) -> None:
    result = _broker(tmp_path)._classify_single(command)

    assert result["class"] == "validation"
    assert result.get("replay_safe") is True


def test_validation_classification_keeps_replay_safety_default(
    tmp_path, monkeypatch
) -> None:
    broker = _broker(tmp_path)
    monkeypatch.setattr(
        broker,
        "_classify_single",
        lambda _command: {"class": "validation", "cacheable": False, "allowed": True},
    )

    result = broker.classify("unclassified-validator")

    assert result.get("replay_safe") is True


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest -q",
        'pwsh -NoProfile -Command "Invoke-Pester -Path tests"',
    ],
)
def test_repair_loop_keeps_retrying_recognized_python_and_powershell_validation(
    tmp_path, monkeypatch, command: str
) -> None:
    broker = _broker(tmp_path)
    executions: list[str] = []
    generator_calls: list[str] = []

    def run(actual_command: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        executions.append(actual_command)
        if len(executions) == 1:
            return {"success": False, "exit_code": 1}
        return {"success": True, "exit_code": 0}

    def generate(actual_command: str, *_args: Any) -> dict[str, str]:
        generator_calls.append(actual_command)
        return {"changed.py": "value = 1\n"}

    monkeypatch.setattr(broker, "run", run)

    result = broker.repair_loop(
        command,
        str(tmp_path),
        "tenant",
        max_attempts=1,
        fix_generator=generate,
    )

    assert result["success"] is True
    assert executions == [command, command]
    assert generator_calls == [command]
