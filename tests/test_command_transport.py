from __future__ import annotations

from pathlib import Path

from local_ai_hub.commands import build_invocation, validate_invocation


def test_command_arguments_are_passed_as_argv_not_nested_shell_text() -> None:
    invocation = build_invocation("python", ["-c", "print('a b')"], cwd="C:\\repo")

    assert invocation.argv == ["python", "-c", "print('a b')"]
    assert invocation.cwd == "C:\\repo"
    assert invocation.shell is False


def test_structured_arguments_preserve_spaces_quotes_shell_text_and_unicode() -> None:
    args = ["--label", "two words; $HOME | harmless", "--path", "žluťoučký.txt"]

    invocation = build_invocation("tool with spaces", args, cwd=Path("C:/repo with spaces"))

    assert invocation.argv == ["tool with spaces", *args]
    assert invocation.cwd == str(Path("C:/repo with spaces"))


def test_powershell_command_is_rejected_when_only_string_quoting_is_available() -> None:
    result = validate_invocation("powershell -Command Write-Host $HOME")

    assert result["safe"] is False
    assert result["reason"] == "unstructured_shell_text"
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_non_string_argv_item_returns_bounded_terminal_serialization_error() -> None:
    result = validate_invocation(["python", object()])

    assert result["safe"] is False
    assert result["reason"] == "argv_argument_not_string"
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert len(result["error"]) <= 256


def test_shell_true_invocation_is_rejected() -> None:
    result = validate_invocation({"argv": ["python", "-V"], "shell": True})

    assert result["safe"] is False
    assert result["reason"] == "shell_true_not_allowed"
    assert result["terminal"] is True
    assert result["retryable"] is False
