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


@pytest.mark.parametrize("command", [
    'tasklist /FI "PID eq 3844" /FO CSV /NH',
    'TASKLIST.EXE /FO CSV', 'netstat -ano', 'ipconfig /all',
    'systeminfo', 'env', 'printenv', 'whoami',
])
def test_host_observations_are_allowed_but_never_repository_cached(tmp_path, command):
    result = _broker(tmp_path).classify(command)
    assert result["allowed"] is True
    assert result["class"] == "read"
    assert result["cacheable"] is False


def test_repository_file_reads_retain_cache_support(tmp_path):
    assert _broker(tmp_path).classify('rg -n needle src')["cacheable"] is True



def _enable_local_transaction(broker: CommandBroker, tmp_path, monkeypatch) -> list[str]:
    target = tmp_path / "candidate.py"
    target.write_text("original = True\n", encoding="utf-8")
    monkeypatch.setattr(broker, "_require_task_worktree", lambda *_args: None)
    monkeypatch.setattr(broker, "_transaction_root_for_context", lambda _transaction_id: tmp_path)
    monkeypatch.setattr(
        broker,
        "_run_private_transaction",
        lambda **kwargs: kwargs["operation"](tmp_path, "test-transaction"),
    )
    return ["candidate.py"]

@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest -q",
        'python -c "assert True"',
        'python -c "assert len([1]) == 1"',
        "python tools/check_contracts.py",
        "python tools/hubctl.py status",
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

def test_compound_validation_replays_only_when_every_part_is_explicitly_safe(tmp_path) -> None:
    broker = _broker(tmp_path)
    safe = broker.classify("python -m pytest -q && python tools/check_contracts.py")
    broker.config["commands"]["extra_allowed_tools"] = ["custom_tool"]
    unclassified = broker.classify("python -m pytest -q && custom_tool --apply")

    assert safe["class"] == "validation"
    assert safe["replay_safe"] is True
    assert unclassified["class"] == "validation"
    assert unclassified["replay_safe"] is False


@pytest.mark.parametrize(
    ("command", "expected_class"),
    [
        ('powershell -NoProfile -Command "Remove-Item -LiteralPath x"', "dangerous"),
        ('pwsh -NoProfile -Command "Set-Content x y"', "mutating"),
        ('bash -c "rm -rf /tmp/x"', None),
        ("cmd /c del /q x", None),
    ],
)
def test_whitelisting_shell_interpreter_does_not_skip_command_safety(
    tmp_path, command: str, expected_class: str | None
) -> None:
    broker = _broker(tmp_path)
    broker.config["commands"].update(
        {"allow_mutating": False, "extra_allowed_tools": ["powershell", "pwsh", "bash", "cmd"]}
    )

    result = broker.classify(command)

    assert result["allowed"] is False
    if expected_class is not None:
        assert result["class"] == expected_class
        assert result["replay_safe"] is False

@pytest.mark.parametrize(
    "command",
    [
        'python -c "open(\'x\', \'a\').write(\'y\')"',
        'python -c "open(\'x\', mode=\'w\').write(\'y\')"',
        'python -c "Path(\'x\').write_text(\'y\')"',
        'python -c "import shutil; shutil.copyfile(\'a\', \'b\')"',
        'python -c "from pathlib import Path; Path(\'x\').symlink_to(\'y\')"',
        'python -c "assert check()"',
    ],
)
def test_python_inline_unverified_file_effects_are_not_replay_safe(tmp_path, command: str) -> None:
    result = _broker(tmp_path).classify(command)

    assert result["class"] == "unknown"
    assert result.get("replay_safe") is not True



def test_repair_loop_skips_validation_when_classifier_omits_replay_safety(
    tmp_path, monkeypatch
) -> None:
    broker = _broker(tmp_path)
    paths = _enable_local_transaction(broker, tmp_path, monkeypatch)
    executions: list[str] = []

    def run(command: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        executions.append(command)
        return {"success": False, "exit_code": 1}

    monkeypatch.setattr(broker, "run", run)
    monkeypatch.setattr(
        broker, "classify",
        lambda _command: {"class": "validation", "cacheable": False, "allowed": True},
    )

    result = broker.repair_loop(
        "unclassified-validator", str(tmp_path), "tenant", max_attempts=1,
        fix_generator=lambda *_args: pytest.fail("unclassified validation must not trigger repair"),
        paths=paths,
    )

    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert executions == ["unclassified-validator"]


def test_repair_loop_honors_explicit_unsafe_validation_classification(
    tmp_path, monkeypatch
) -> None:
    broker = _broker(tmp_path)
    paths = _enable_local_transaction(broker, tmp_path, monkeypatch)
    executions: list[str] = []
    monkeypatch.setattr(
        broker, "run",
        lambda command, *_args, **_kwargs: executions.append(command) or {"success": False, "exit_code": 1},
    )
    monkeypatch.setattr(
        broker, "classify",
        lambda _command: {"class": "validation", "cacheable": False, "allowed": True, "replay_safe": False},
    )

    result = broker.repair_loop(
        "one-shot-validator", str(tmp_path), "tenant", max_attempts=1,
        fix_generator=lambda *_args: pytest.fail("unsafe validation must not trigger repair"),
        paths=paths,
    )

    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert executions == ["one-shot-validator"]


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
    paths = _enable_local_transaction(broker, tmp_path, monkeypatch)
    executions: list[str] = []
    generator_calls: list[str] = []

    def run(actual_command: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        executions.append(actual_command)
        if len(executions) == 1:
            return {"success": False, "exit_code": 1}
        return {"success": True, "exit_code": 0}

    def generate(actual_command: str, *_args: Any) -> dict[str, str]:
        generator_calls.append(actual_command)
        return {"candidate.py": "value = 1\n"}

    monkeypatch.setattr(broker, "run", run)

    result = broker.repair_loop(
        command,
        str(tmp_path),
        "tenant",
        max_attempts=1,
        fix_generator=generate,
        paths=paths,
    )

    assert result["success"] is True
    assert executions == [command, command]
    assert generator_calls == [command]

@pytest.mark.parametrize(
    "command",
    [
        "custom_tool --apply",
        'pwsh -Command "custom_tool --apply"',
        'powershell -Command "custom_tool --apply"',
    ],
)
def test_user_whitelisted_validation_is_explicitly_unsafe(tmp_path, monkeypatch, command: str) -> None:
    broker = _broker(tmp_path)
    paths = _enable_local_transaction(broker, tmp_path, monkeypatch)
    broker.config["commands"]["extra_allowed_tools"] = ["custom_tool"]
    executions: list[str] = []
    monkeypatch.setattr(
        broker, "run",
        lambda actual, *_args, **_kwargs: executions.append(actual) or {"success": False, "exit_code": 1},
    )
    classification = broker.classify(command)

    assert classification["class"] == "validation"
    assert classification.get("replay_safe") is False
    result = broker.repair_loop(
        command, str(tmp_path), "tenant", max_attempts=1,
        fix_generator=lambda *_args: pytest.fail("whitelisted commands must not replay"),
        paths=paths,
    )

    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert executions == [command]
