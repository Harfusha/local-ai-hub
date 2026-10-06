from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from local_ai_hub import agent_context
from local_ai_hub.agent_context import ContextCompiler
from local_ai_hub.agent_events import AgentStateStore


class _CommitAndRollbackFailure:
    def __init__(self) -> None:
        self.closed = False

    def execute(self, statement: str, parameters=()):
        command = statement.strip().upper()
        if command == "COMMIT":
            raise RuntimeError("primary-secret")
        if command == "ROLLBACK":
            raise RuntimeError("cleanup-secret")
        return SimpleNamespace(rowcount=1)

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("operation", ["link", "invalidate"])
def test_rollback_failure_is_visible_without_masking_primary_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, operation: str
) -> None:
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    connection = _CommitAndRollbackFailure()
    monkeypatch.setattr(agent_context, "connect_sqlite", lambda *args, **kwargs: connection)

    caplog.set_level(logging.WARNING, logger=agent_context.__name__)
    with pytest.raises(RuntimeError, match="primary-secret"):
        if operation == "link":
            compiler.link("source", "target", "modifies", path="src/file.py")
        else:
            compiler.invalidate(["src/file.py"], revision="r2")

    assert connection.closed
    assert "rollback failed" in caplog.text.lower()
    assert operation in caplog.text
    assert "RuntimeError" in caplog.text
    assert "primary-secret" not in caplog.text
    assert "cleanup-secret" not in caplog.text


def test_blackboard_lookup_failure_is_logged_without_exception_details(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    class _BrokenBlackboard:
        def get(self, board_id: str) -> dict:
            raise RuntimeError("private-blackboard-payload")

    compiler = ContextCompiler(
        AgentStateStore(tmp_path / "agent-state.sqlite3"),
        blackboard=_BrokenBlackboard(),
    )
    caplog.set_level(logging.WARNING, logger=agent_context.__name__)

    context = compiler.compile(agent_context.ContextRequest(task_id="task-1"))

    assert all(item.source_kind != "blackboard" for item in context.elements)
    assert "blackboard lookup failed" in caplog.text.lower()
    assert "RuntimeError" in caplog.text
    assert "private-blackboard-payload" not in caplog.text
