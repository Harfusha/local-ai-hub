import pytest

from local_ai_hub.command_python import (
    classify_python_command,
    classify_hubctl_command,
    classify_python_inline_code,
    classify_python_script_command,
    is_python_interpreter_name,
    python_inline_code_argument,
    python_inline_code_syntax_is_valid,
)
from local_ai_hub.command_broker import CommandBroker


def test_extracted_python_read_classification_respects_read_gate():
    tokens = ["python", "-m", "pip", "list"]
    assert classify_python_command(tokens, tokens, {}) == {
        "class": "read",
        "cacheable": True,
        "allowed": True,
        "reason": "python -m pip list",
    }
    assert classify_python_command(tokens, tokens, {"allow_read": False})["allowed"] is False


def test_python_script_build_and_mutating_results_keep_their_policy_fields():
    build_tokens = ["python", "tools/make_build.py"]
    assert classify_python_script_command(
        build_tokens, build_tokens[1:], {"allow_build": False}
    ) == {
        "class": "build",
        "cacheable": True,
        "allowed": False,
        "reason": "python build/generate script",
    }


def test_python_inline_dangerous_unknown_and_read_results_keep_their_policy_fields():
    assert classify_python_inline_code("os.system('echo unsafe')", {}) == {
        "class": "dangerous",
        "cacheable": False,
        "allowed": False,
        "reason": "python -c inline code contains potentially dangerous call",
    }


def test_hubctl_mutation_and_build_results_keep_their_policy_fields():
    assert classify_hubctl_command(
        ["tasks", "--complete"], ["hubctl", "tasks", "--complete"],
        {"allow_mutating": True},
    ) == {
        "class": "mutating",
        "cacheable": False,
        "allowed": True,
        "reason": "hubctl tasks status mutation",
    }
    assert classify_hubctl_command(
        ["generate"], ["hubctl", "generate"], {"allow_build": False}
    ) == {
        "class": "build",
        "cacheable": True,
        "allowed": False,
        "reason": "hubctl generate dynamic artifacts",
    }
    assert classify_hubctl_command(
        ["restart"], ["hubctl", "restart"], {"allow_mutating": False}
    ) == {
        "class": "mutating",
        "cacheable": False,
        "allowed": False,
        "reason": "hubctl restart service lifecycle mutation",
    }
    assert classify_python_inline_code("unknown()", {"allow_unknown": True}) == {
        "class": "unknown",
        "cacheable": False,
        "allowed": True,
        "reason": "python -c inline code has unverified call: unknown",
    }
    assert classify_python_inline_code("print(1)", {"allow_read": False}) == {
        "class": "read",
        "cacheable": True,
        "allowed": False,
        "reason": "python inline read",
    }

    custom_tokens = ["python", "/tmp/custom_script.py"]
    assert classify_python_script_command(
        custom_tokens, custom_tokens[1:], {"allow_mutating": True}
    ) == {
        "class": "mutating",
        "cacheable": False,
        "allowed": True,
        "replay_safe": False,
        "reason": "unclassified Python script may have side effects",
    }


def test_recognizes_supported_python_interpreter_names():
    for executable in (
        "python",
        "python3",
        "py",
        "python3.11",
        "python3.11.exe",
        r"C:\Python\python3.13.exe",
    ):
        assert is_python_interpreter_name(executable) is True


def test_rejects_names_that_only_contain_python_prefix():
    for executable in ("pythonwin", "python311", "python3.11-script", ""):
        assert is_python_interpreter_name(executable) is False


@pytest.mark.parametrize(
    ("tokens", "valid"),
    [
        (["python", "-c", "print(1)"], True),
        (["python", "-c", "def"], False),
        (["python", "-c", ""], False),
        (["python", "-c"], False),
        (["python", "--version"], True),
    ],
)
def test_python_inline_code_syntax_validation(tokens, valid):
    assert python_inline_code_syntax_is_valid(tokens) is valid


@pytest.mark.parametrize(
    ("command", "valid"),
    [
        ("python -c 'print(1)'", True),
        ('python -c "def"', False),
        ("python -c", False),
        (["python", "-m", "pytest"], True),
        (["python", "\x00"], False),
        (b"python -c print(1)", False),
        ("", False),
    ],
)
def test_well_formed_command_input_preserves_structure_and_python_checks(command, valid):
    assert CommandBroker._well_formed_command_input(command) is valid


def test_well_formed_command_input_preserves_subclass_interpreter_policy():
    class NonPythonBroker(CommandBroker):
        @staticmethod
        def _is_python_interpreter_name(_executable):
            return False

    assert NonPythonBroker._well_formed_command_input(["python", "-c", "def"]) is True


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["python", "-c", "print(1)"], "print(1)"),
        (["python", "-c"], None),
        (["python", "--version"], None),
        (["python", "-c", "-c", "print(1)"], "-c"),
        (["python", "-c", ""], ""),
    ],
)
def test_extracts_first_python_inline_code_argument(tokens, expected):
    assert python_inline_code_argument(tokens) == expected


@pytest.mark.parametrize(
    ("tokens", "lower"),
    [
        (["python", "-m", "pytest"], ["-m", "pytest"]),
        (["python", "-c", "print(1)"], ["-c", "print(1)"]),
        (["python", "src/test_check.py"], ["src/test_check.py"]),
    ],
)
def test_dispatches_python_module_inline_and_script_commands(tokens, lower):
    assert classify_python_command(tokens, lower, {}) is not None
