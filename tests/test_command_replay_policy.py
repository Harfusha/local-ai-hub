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
    ("tokens", "cfg", "expected"),
    [
        (
            ["python", "-m", "pytest", "-q"],
            {"allow_validation": True},
            {
                "class": "validation",
                "cacheable": True,
                "allowed": True,
                "replay_safe": True,
                "reason": "python -m pytest validation",
            },
        ),
        (
            ["python", "-m", "pip", "list"],
            {"allow_read": True},
            {
                "class": "read",
                "cacheable": True,
                "allowed": True,
                "reason": "python -m pip list",
            },
        ),
        (
            ["python", "-m", "pip", "install", "sample"],
            {"allow_mutating": False},
            {
                "class": "mutating",
                "cacheable": False,
                "allowed": False,
                "reason": "python -m pip install changes environment",
            },
        ),
        (
            ["python", "-m", "black", "--check", "src"],
            {"allow_validation": True},
            {
                "class": "validation",
                "cacheable": True,
                "allowed": True,
                "replay_safe": True,
                "reason": "python -m black validation",
            },
        ),
        (
            ["python", "-m", "black", "src"],
            {"allow_mutating": False},
            {
                "class": "mutating",
                "cacheable": False,
                "allowed": False,
                "reason": "python -m black format without --check",
            },
        ),
    ],
)
def test_python_module_classifier_helper_preserves_contract(tokens, cfg, expected):
    from local_ai_hub.command_python import classify_python_module_command

    lower = [token.lower() for token in tokens]
    assert classify_python_module_command(tokens, lower, cfg) == expected


def test_python_module_classifier_helper_ignores_non_module_commands():
    from local_ai_hub.command_python import classify_python_module_command

    tokens = ["python", "tools/check_contracts.py"]
    assert classify_python_module_command(tokens, [token.lower() for token in tokens], {}) is None


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

    assert result["class"] in {"unknown", "dangerous"}
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
        "unclassified-validator", str(tmp_path), max_attempts=1,
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
        "one-shot-validator", str(tmp_path), max_attempts=1,
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
        command, str(tmp_path), max_attempts=1,
        fix_generator=lambda *_args: pytest.fail("whitelisted commands must not replay"),
        paths=paths,
    )

    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert executions == [command]


@pytest.mark.parametrize(
    ("exe_base", "lower", "expected"),
    [
        (
            "rg",
            ["--pre=python", "needle"],
            {
                "class": "unknown",
                "cacheable": False,
                "allowed": False,
                "reason": "ripgrep preprocessor may execute arbitrary programs",
            },
        ),
        (
            "rg",
            ["--pre", "python", "needle"],
            {
                "class": "unknown",
                "cacheable": False,
                "allowed": False,
                "reason": "ripgrep preprocessor may execute arbitrary programs",
            },
        ),
        (
            "find",
            [".", "-exec", "python", "-c", "print(1)", ";"],
            {
                "class": "unknown",
                "cacheable": False,
                "allowed": False,
                "reason": "find execution flags are not allowed",
            },
        ),
        (
            "rg",
            ["-n", "needle", "src"],
            {"class": "read", "cacheable": True, "allowed": True, "reason": "rg read command"},
        ),
        (
            "tasklist",
            [],
            {"class": "read", "cacheable": False, "allowed": True, "reason": "tasklist read command"},
        ),
    ],
)
def test_read_only_classifier_helper_preserves_policy(exe_base, lower, expected):
    from local_ai_hub.command_policy import READ_ONLY, VOLATILE_READS
    from local_ai_hub.command_read import classify_read_only_command

    assert classify_read_only_command(
        exe_base,
        lower,
        {"allow_read": True},
        read_only=READ_ONLY,
        volatile_reads=VOLATILE_READS,
    ) == expected


def test_read_only_classifier_helper_ignores_non_read_commands():
    from local_ai_hub.command_policy import READ_ONLY, VOLATILE_READS
    from local_ai_hub.command_read import classify_read_only_command

    assert classify_read_only_command(
        "python",
        [],
        {},
        read_only=READ_ONLY,
        volatile_reads=VOLATILE_READS,
    ) is None


def test_broker_keeps_execution_options_blocked_for_read_tools(tmp_path):
    broker = _broker(tmp_path)

    ripgrep = broker.classify("rg --pre=python needle")
    find = broker.classify(["find", ".", "-exec", "python", "-c", "print(1)", ";"])

    assert (ripgrep["class"], ripgrep["allowed"], ripgrep["cacheable"]) == ("unknown", False, False)
    assert ripgrep["reason"] == "ripgrep preprocessor may execute arbitrary programs"
    assert (find["class"], find["allowed"], find["cacheable"]) == ("unknown", False, False)
    assert find["reason"] == "find execution flags are not allowed"


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("write", ("write",)),
        ("sys.stdout.write", ("sys", "stdout", "write")),
        ("obj._private", None),
        ("items[0].method", None),
    ],
)
def test_python_call_chain_helper_preserves_safe_attribute_rules(expression, expected):
    import ast

    from local_ai_hub.command_python import _get_call_chain

    node = ast.parse(expression, mode="eval").body
    assert _get_call_chain(node) == expected


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1", True),
        ("-2", True),
        ("1 + 2", True),
        ("[1, (2,), {3}]", True),
        ("{'a': 1}", True),
        ("{**data}", False),
        ("name", False),
        ("open('x')", False),
    ],
)
def test_python_literal_only_helper_classifies_literal_ast(expression, expected):
    import ast

    from local_ai_hub.command_python import _literal_only

    node = ast.parse(expression, mode="eval").body
    assert _literal_only(node) is expected


def _python_inline_safety(**overrides):
    from local_ai_hub.command_python import PythonInlineCodeSafety

    options = {
        "safe_builtin_calls": {"len"},
        "shadowed_names": set(),
        "defined_function_names": {"defined"},
        "safe_module_calls": {("math", "sqrt")},
        "func_param_names": set(),
        "safe_method_names": {"count"},
        "safe_module_names": {"math"},
        "safe_value_names": {"safe_name"},
    }
    options.update(overrides)
    return PythonInlineCodeSafety(**options)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("len([1])", True),
        ("defined('x')", True),
        ("math.sqrt(1)", True),
        ("open('x')", False),
        ("safe_name.count('x')", True),
        ("math.count('x')", False),
        ("obj._private()", False),
    ],
)
def test_python_inline_safety_classifies_calls(expression, expected):
    import ast

    safety = _python_inline_safety()
    node = ast.parse(expression, mode="eval").body
    assert safety.is_safe_call(node) is expected


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("-2", True),
        ("safe_name", True),
        ("unknown_name", False),
        ("[safe_name, {'x': len([1])}]", True),
        ("math.sqrt(unknown_name)", False),
        ("safe_name.count('x')", True),
        ("math.count('x')", False),
        ("{**payload}", False),
    ],
)
def test_python_inline_safety_classifies_recursive_values(expression, expected):
    import ast

    safety = _python_inline_safety()
    node = ast.parse(expression, mode="eval").body
    assert safety.is_safe_inline_value(node) is expected


def test_python_inline_safety_propagates_safe_values_through_assignments():
    import ast

    tree = ast.parse("final = middle + 1\nmiddle = source + 1\nsource = len([1])")
    safe_values = set()
    safety = _python_inline_safety(safe_value_names=safe_values)

    safety.propagate_safe_values(tree)

    assert safe_values == {"source", "middle", "final"}


def test_python_inline_safety_propagates_annotated_and_named_assignments():
    import ast

    tree = ast.parse("value: int = len([1])\n(alias := value)")
    safe_values = set()
    safety = _python_inline_safety(safe_value_names=safe_values)

    safety.propagate_safe_values(tree)

    assert safe_values == {"value", "alias"}


def test_python_inline_safety_propagates_loop_targets_but_not_destructuring():
    import ast

    tree = ast.parse("for item in [1]:\n    pass\n(left, right) = [1, 2]")
    safe_values = set()
    safety = _python_inline_safety(safe_value_names=safe_values)

    safety.propagate_safe_values(tree)

    assert safe_values == {"item"}


def test_python_inline_safety_keeps_five_pass_propagation_limit():
    import ast

    tree = ast.parse(
        "a = b\nb = c\nc = d\nd = e\ne = f\nf = g\ng = len([1])"
    )
    safe_values = set()
    safety = _python_inline_safety(safe_value_names=safe_values)

    safety.propagate_safe_values(tree)

    assert safe_values == {"g", "f", "e", "d", "c"}


@pytest.mark.parametrize(
    ("source", "cfg", "expected"),
    [
        (
            "assert len([1]) == 1",
            {"allow_validation": True},
            {
                "class": "validation",
                "cacheable": True,
                "allowed": True,
                "replay_safe": True,
                "reason": "python inline validation",
            },
        ),
        (
            "print(1)",
            {"allow_read": False},
            {
                "class": "read",
                "cacheable": True,
                "allowed": False,
                "reason": "python inline read",
            },
        ),
        (
            "open('x')",
            {"allow_unknown": False},
            {
                "class": "unknown",
                "cacheable": False,
                "allowed": False,
                "reason": "python -c inline code may mutate: open",
            },
        ),
        (
            "os.system('echo nope')",
            {},
            {
                "class": "dangerous",
                "cacheable": False,
                "allowed": False,
                "reason": "python -c inline code contains potentially dangerous call",
            },
        ),
        (
            "import requests",
            {},
            {
                "class": "unknown",
                "cacheable": False,
                "allowed": False,
                "reason": "python -c inline code imports module with unknown side effects",
            },
        ),
        (
            "if",
            {"allow_unknown": True},
            {
                "class": "unknown",
                "cacheable": False,
                "allowed": True,
                "reason": "python -c inline code contains invalid syntax",
            },
        ),
    ],
)
def test_python_inline_classifier_helper_preserves_policy(source, cfg, expected):
    from local_ai_hub.command_python import classify_python_inline_code

    assert classify_python_inline_code(source, cfg) == expected


@pytest.mark.parametrize(
    ("tokens", "lower", "cfg", "expected"),
    [
        (
            ["python", "tools/check_contracts.py"],
            ["python", "tools/check_contracts.py"],
            {"allow_validation": False},
            {
                "class": "validation",
                "cacheable": True,
                "allowed": False,
                "replay_safe": True,
                "reason": "python validation script",
            },
        ),
        (
            ["python", "./tools/surface_inventory.py", "--check"],
            ["python", "./tools/surface_inventory.py", "--check"],
            {},
            {
                "class": "validation",
                "cacheable": True,
                "allowed": True,
                "replay_safe": True,
                "reason": "python validation script",
            },
        ),
        (
            ["python", "hubctl.py", "tasks", "--fail"],
            ["python", "hubctl.py", "tasks", "--fail"],
            {},
            {
                "class": "mutating",
                "cacheable": False,
                "allowed": False,
                "reason": "hubctl tasks status mutation",
            },
        ),
        (
            ["python", "hubctl.py", "status"],
            ["python", "hubctl.py", "status"],
            {},
            {
                "class": "validation",
                "cacheable": True,
                "allowed": True,
                "replay_safe": True,
                "reason": "hubctl status status check",
            },
        ),
        (
            ["python", "setup.py", "--help"],
            ["python", "setup.py", "--help"],
            {},
            {
                "class": "build",
                "cacheable": True,
                "allowed": True,
                "reason": "setup.py generate dynamic artifacts",
            },
        ),
        (
            ["python", "scripts/generate_docs.py"],
            ["python", "scripts/generate_docs.py"],
            {},
            {
                "class": "build",
                "cacheable": True,
                "allowed": True,
                "reason": "python build/generate script",
            },
        ),
        (
            ["python", "custom.py"],
            ["python", "custom.py"],
            {},
            {
                "class": "mutating",
                "cacheable": False,
                "allowed": False,
                "replay_safe": False,
                "reason": "unclassified Python script may have side effects",
            },
        ),
        (["python"], ["python"], {}, None),
    ],
)
def test_python_script_classifier_helper_preserves_policy(tokens, lower, cfg, expected):
    from local_ai_hub.command_python import classify_python_script_command

    assert classify_python_script_command(tokens, lower, cfg) == expected


@pytest.mark.parametrize(
    ("subcommands", "lower", "cfg", "expected"),
    [
        (["tasks", "--fail"], ["tasks", "--fail"], {}, {"class": "mutating", "cacheable": False, "allowed": False, "reason": "hubctl tasks status mutation"}),
        (["tasks"], ["tasks"], {"allow_validation": False}, {"class": "validation", "cacheable": True, "allowed": False, "replay_safe": True, "reason": "hubctl tasks status check"}),
        (["status"], ["status"], {}, {"class": "validation", "cacheable": True, "allowed": True, "replay_safe": True, "reason": "hubctl status status check"}),
        (["generate"], ["generate"], {"allow_build": False}, {"class": "build", "cacheable": True, "allowed": False, "reason": "hubctl generate dynamic artifacts"}),
        (["restart"], ["restart"], {"allow_mutating": True}, {"class": "mutating", "cacheable": False, "allowed": True, "reason": "hubctl restart service lifecycle mutation"}),
        (["unknown"], ["unknown"], {}, None),
        ([], [], {}, None),
    ],
)
def test_hubctl_classifier_helper_preserves_policy(subcommands, lower, cfg, expected):
    from local_ai_hub.command_python import classify_hubctl_command

    assert classify_hubctl_command(subcommands, lower, cfg) == expected


@pytest.mark.parametrize(
    ("command", "expected_class"),
    [
        ("hubctl tasks --fail", "mutating"),
        ("hubctl status", "validation"),
        ("hubctl generate", "build"),
    ],
)
def test_native_hubctl_commands_use_shared_classifier(tmp_path, command, expected_class):
    assert _broker(tmp_path).classify(command)["class"] == expected_class
