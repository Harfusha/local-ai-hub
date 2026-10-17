"""Deferred regressions for classification denial and unknown-code fencing."""
import threading
from unittest.mock import Mock

import pytest

from local_ai_hub.commands import CommandBroker, CommandInvocation


def _broker(monkeypatch, classification=None):
    broker = object.__new__(CommandBroker)
    broker.config = {"commands": {"allow_unknown": True, "allow_mutating": True}}
    broker.enabled = True
    broker.policy_blocking = False  # Legacy setting must never bypass a denial.
    broker.timeout = 10
    broker._lock = threading.Lock()
    broker.blocked = 0
    broker._blocked_by_reason = {}
    broker._project_command_fingerprints = lambda *args: ("", "", "", "", "")
    broker._project_environment = lambda *args: ("", {}, None)
    if classification is not None:
        broker.classify = lambda *args: dict(classification)
    broker._tool_identity = Mock(return_value={})
    broker._attempt_key = Mock(return_value="attempt")
    broker._unavailable_executable = lambda *args, **kwargs: None
    broker._require_task_worktree = lambda *args, **kwargs: None
    broker._read_cache_entry = Mock(side_effect=AssertionError("cache lookup before authorization"))
    broker._execute = Mock(side_effect=AssertionError("unauthorized process"))
    broker._run_private_transaction = Mock(side_effect=AssertionError("unauthorized transaction"))
    return broker


@pytest.mark.parametrize("command_class", ["unknown", "validation", "read", "mutating", "dangerous"])
@pytest.mark.parametrize("cache_options", [{}, {"force": True}, {"bypass_cache": True}])
def test_denied_classification_never_reaches_cache_or_process(tmp_path, monkeypatch, command_class, cache_options):
    broker = _broker(monkeypatch, {"class": command_class, "allowed": False, "reason": "denied"})
    result = broker.run("python -I -c ignored", str(tmp_path), **cache_options)
    assert result["success"] is False
    assert result["policy_blocked"] is True
    assert result["execution_authorized"] is False
    assert result["request_not_sent"] is True
    assert result["terminal"] is True and result["retryable"] is False
    broker._tool_identity.assert_not_called()
    broker._read_cache_entry.assert_not_called()
    broker._execute.assert_not_called()
    broker._run_private_transaction.assert_not_called()


@pytest.mark.parametrize("allowed", [None, 1, "true"])
def test_non_boolean_allowance_is_not_authorization(tmp_path, monkeypatch, allowed):
    broker = _broker(monkeypatch, {"class": "read", "allowed": allowed, "reason": "malformed"})
    assert broker.run("echo hello", str(tmp_path))["policy_blocked"] is True


def test_unknown_opt_in_still_requires_declared_write_set(tmp_path, monkeypatch):
    broker = _broker(monkeypatch, {"class": "unknown", "allowed": True})
    result = broker.run("custom-tool", str(tmp_path), task_id="owned-task")
    assert result["mutation_write_set_required"] is True
    broker._read_cache_entry.assert_not_called()
    broker._execute.assert_not_called()


def test_unknown_opt_in_still_requires_current_fence(tmp_path, monkeypatch):
    broker = _broker(monkeypatch, {"class": "unknown", "allowed": True})
    result = broker.run("custom-tool", str(tmp_path), task_id="owned-task", paths=["owned.txt"])
    assert result["mutation_fence_required"] is True
    assert result["outcome_unknown"] is False
    broker._run_private_transaction.assert_not_called()


def test_unknown_opt_in_does_not_replace_mutation_permission(tmp_path, monkeypatch):
    broker = _broker(monkeypatch, {"class": "unknown", "allowed": True})
    broker.config["commands"]["allow_mutating"] = False
    result = broker.run("custom-tool", str(tmp_path))
    assert result["policy_blocked"] is True
    assert result["classification_allowed"] is True
    broker._tool_identity.assert_not_called()


def test_unknown_opt_in_authorizes_actual_nonempty_unknown_classification(tmp_path, monkeypatch):
    broker = _broker(monkeypatch)
    broker.config["commands"]["allow_unknown"] = False

    result = broker.run("custom-tool --flag", str(tmp_path), task_id="owned-task")

    assert result["classification"]["class"] == "unknown"
    assert result["classification"]["allowed"] is False
    assert result["classification_allowed"] is True
    assert result["mutation_write_set_required"] is True
    broker._read_cache_entry.assert_not_called()
    broker._execute.assert_not_called()


@pytest.mark.parametrize("command", ["", "   ", "\x00custom-tool", 'python -c "def"'])
def test_unknown_opt_in_still_rejects_empty_or_malformed_commands(tmp_path, monkeypatch, command):
    broker = _broker(monkeypatch)

    result = broker.run(command, str(tmp_path), task_id="owned-task", paths=["owned.txt"])

    assert result["policy_blocked"] is True
    assert result["classification"]["class"] == "unknown"
    assert result["classification_allowed"] is False
    broker._tool_identity.assert_not_called()
    broker._read_cache_entry.assert_not_called()
    broker._execute.assert_not_called()


@pytest.mark.parametrize(
    "argv",
    [[], [""], ["custom-tool", 3], ["custom-tool", "\x00value"]],
)
def test_unknown_opt_in_rejects_malformed_argv_structure(argv, monkeypatch):
    broker = _broker(monkeypatch)

    assert broker._well_formed_command_input(argv) is False


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-c", "def"],
        ["python3.11", "-c", "def"],
        ["python3.12.exe", "-c", "def"],
        ["py", "-3.11", "-c", "def"],
    ],
)
def test_unknown_opt_in_rejects_invalid_python_argv_syntax(tmp_path, monkeypatch, argv):
    broker = _broker(monkeypatch)

    result = broker.run(
        CommandInvocation(argv),
        str(tmp_path),
        task_id="owned-task",
        paths=["owned.txt"],
    )

    assert result["policy_blocked"] is True
    assert result["classification"]["class"] == "unknown"
    assert result["classification_allowed"] is False
    broker._tool_identity.assert_not_called()
    broker._read_cache_entry.assert_not_called()
    broker._execute.assert_not_called()


def test_unknown_opt_in_still_rejects_actual_dangerous_command(tmp_path, monkeypatch):
    broker = _broker(monkeypatch)
    broker.config["commands"]["allow_unknown"] = False

    result = broker.run("rm -rf /", str(tmp_path), task_id="owned-task", paths=["owned.txt"])

    assert result["policy_blocked"] is True
    assert result["classification"]["class"] == "dangerous"
    assert result["classification_allowed"] is False
    broker._tool_identity.assert_not_called()
    broker._read_cache_entry.assert_not_called()
    broker._execute.assert_not_called()


@pytest.mark.parametrize(
    "command",
    [
        "python -c \"os.system('echo denied')\"",
        CommandInvocation(["python", "-c", "os.system('echo denied')"]),
        "python3.11 -c \"os.system('echo denied')\"",
        CommandInvocation(["python3.11", "-c", "os.system('echo denied')"]),
        "python3.12.exe -c \"os.system('echo denied')\"",
        CommandInvocation(["python3.12.exe", "-c", "os.system('echo denied')"]),
        "py -3.11 -c \"os.system('echo denied')\"",
        CommandInvocation(["py", "-3.11", "-c", "os.system('echo denied')"]),
    ],
)
def test_unknown_opt_in_cannot_authorize_dangerous_python_inline_code(tmp_path, monkeypatch, command):
    broker = _broker(monkeypatch)

    result = broker.run(
        command,
        str(tmp_path),
        task_id="owned-task",
        paths=["owned.txt"],
    )

    assert result["policy_blocked"] is True
    assert result["classification"]["class"] == "dangerous"
    assert result["classification_allowed"] is False
    broker._tool_identity.assert_not_called()
    broker._read_cache_entry.assert_not_called()
    broker._execute.assert_not_called()


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-c", "value = 1"],
        ["python3.11", "-c", "value = 1"],
        ["python3.12.exe", "-c", "value = 1"],
        ["py", "-3.11", "-c", "value = 1"],
    ],
)
def test_versioned_python_interpreters_use_inline_classifier(argv, monkeypatch):
    broker = _broker(monkeypatch)

    result = broker.classify(argv)

    assert result["class"] == "read"
    assert result["reason"] == "python inline read"
