from __future__ import annotations

from typing import Any

import pytest

from local_ai_hub.services import LocalAIServices


class _CommandRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def classify(self, command: str) -> dict[str, Any]:
        is_mutating = "write" in command
        return {"class": "mutating" if is_mutating else "read", "allowed": True}

    def run(
        self,
        *args: Any,
        task_id: str = "",
        paths: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        kwargs.update(task_id=task_id, paths=paths)
        self.calls.append(("run", kwargs))
        return {"success": True}

    def repair_loop(
        self,
        *args: Any,
        task_id: str = "",
        paths: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        kwargs.update(task_id=task_id, paths=paths)
        self.calls.append(("repair_loop", kwargs))
        return {"success": True}

    def patch_and_verify(
        self,
        *args: Any,
        task_id: str = "",
        paths: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        kwargs.update(task_id=task_id, paths=paths)
        self.calls.append(("patch_and_verify", kwargs))
        return {"success": True}

    def format(
        self,
        *args: Any,
        task_id: str = "",
        paths: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        kwargs.update(task_id=task_id, paths=paths)
        self.calls.append(("format", kwargs))
        return {"success": True}

    def lint_fix(
        self,
        *args: Any,
        task_id: str = "",
        paths: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        kwargs.update(task_id=task_id, paths=paths)
        self.calls.append(("lint_fix", kwargs))
        return {"success": True}


@pytest.mark.parametrize(
    ("action", "expected_method"),
    [
        ("run", "run"),
        ("repair_loop", "repair_loop"),
        ("auto_fix", "repair_loop"),
        ("patch_and_verify", "patch_and_verify"),
        ("format", "format"),
        ("lint_fix", "lint_fix"),
    ],
)
def test_command_dispatch_forwards_task_and_explicit_write_set(action: str, expected_method: str) -> None:
    services = LocalAIServices.__new__(LocalAIServices)
    recorder = _CommandRecorder()
    services.commands = recorder
    services.agent_state = None
    paths = ["src/module.py", "tests/test_module.py"]

    result = services.command(
        {
            "action": action,
            "command": "python -m pytest -q",
            "cwd": ".",
            "task_id": "task-123",
            "paths": paths,
        },
        "agent",
    )

    assert result == {"success": True}
    assert recorder.calls[0][0] == expected_method
    assert recorder.calls[0][1]["task_id"] == "task-123"
    assert recorder.calls[0][1]["paths"] == paths


def test_command_dispatch_does_not_coerce_invalid_write_set() -> None:
    services = LocalAIServices.__new__(LocalAIServices)
    recorder = _CommandRecorder()
    services.commands = recorder
    services.agent_state = None

    services.command(
        {"action": "run", "command": "python -m pytest -q", "task_id": "task-123", "paths": ["src/a.py", 7]},
        "agent",
    )

    assert recorder.calls[0][1]["paths"] is None


@pytest.mark.parametrize(
    "request",
    [
        {"action": "run", "command": "python write_output.py", "task_id": "task-123"},
        {"action": "run", "command": "python write_output.py", "paths": ["output.txt"]},
        {"action": "repair_loop", "command": "python -m pytest -q", "task_id": "task-123"},
        {"action": "format", "task_id": "task-123"},
    ],
)
def test_mutating_command_dispatch_rejects_missing_task_or_write_set(request: dict[str, Any]) -> None:
    services = LocalAIServices.__new__(LocalAIServices)
    recorder = _CommandRecorder()
    services.commands = recorder
    services.agent_state = None

    result = services.command({**request, "paths": request.get("paths", [])}, "agent")

    assert result["success"] is False
    assert result["invalid_write_set"] is True
    assert recorder.calls == []




def test_legacy_command_broker_fails_closed_for_mutating_run_without_write_set_api() -> None:
    class LegacyBroker:
        def classify(self, _command: str) -> dict[str, Any]:
            return {"class": "mutating", "allowed": True}

        def run(self, _command: str, _cwd: str, _tenant: str, *, task_id: str = "") -> dict[str, Any]:
            raise AssertionError("mutating command must not reach a broker without paths support")

    services = LocalAIServices.__new__(LocalAIServices)
    services.commands = LegacyBroker()
    services.agent_state = None

    result = services.command(
        {
            "action": "run",
            "command": "python write_output.py",
            "task_id": "task-123",
            "paths": ["output.txt"],
        },
        "agent",
    )

    assert result["success"] is False
    assert result["unsupported"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False


@pytest.mark.parametrize("classification", ["unknown", "dangerous"])
def test_run_fails_closed_when_classifier_does_not_prove_allowed_action(classification: str) -> None:
    services = LocalAIServices.__new__(LocalAIServices)
    recorder = _CommandRecorder()
    recorder.classify = lambda _command: {"class": classification, "allowed": True}
    services.commands = recorder
    services.agent_state = None

    result = services.command(
        {
            "action": "run",
            "command": "unrecognized operation",
            "task_id": "task-123",
            "paths": ["output.txt"],
        },
        "agent",
    )

    assert result["success"] is False
    assert result["unsupported"] is True
    assert recorder.calls == []
