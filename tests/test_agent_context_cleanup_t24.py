from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from local_ai_hub import agent_context
from local_ai_hub.agent_context import ContextCompiler
from local_ai_hub.agent_events import AgentStateStore


class _PrimaryAndRollbackFailure:
    def __init__(self, *, failing_statement: str, primary_error: RuntimeError) -> None:
        self.failing_statement = failing_statement
        self.primary_error = primary_error
        self.statements: list[str] = []
        self.closed = False

    def execute(self, statement: str, parameters=()):
        command = " ".join(statement.strip().upper().split())
        self.statements.append(command)
        if self.failing_statement in command:
            raise self.primary_error
        if command == "ROLLBACK":
            raise RuntimeError("private-cleanup-payload")
        return SimpleNamespace(rowcount=1)

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("operation", "failing_statement"),
    [
        ("knowledge_link_save", "INSERT INTO AGENT_KNOWLEDGE_LINKS"),
        ("knowledge_link_invalidate", "UPDATE AGENT_KNOWLEDGE_LINKS"),
    ],
)
def test_knowledge_link_transaction_failure_logs_redacted_and_reraises_primary(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    operation: str,
    failing_statement: str,
) -> None:
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    compiler._init_table()
    primary_error = RuntimeError("private-primary-payload")
    connection = _PrimaryAndRollbackFailure(
        failing_statement=failing_statement,
        primary_error=primary_error,
    )
    monkeypatch.setattr(agent_context, "connect_sqlite", lambda *args, **kwargs: connection)
    caplog.set_level(logging.WARNING, logger=agent_context.__name__)

    with pytest.raises(RuntimeError) as raised:
        if operation == "knowledge_link_save":
            compiler.link("source", "target", "modifies", path="src/file.py")
        else:
            compiler.invalidate(["src/file.py"], revision="r2")

    assert raised.value is primary_error
    assert connection.closed
    assert "BEGIN IMMEDIATE" in connection.statements
    assert "ROLLBACK" in connection.statements
    assert operation in caplog.text
    assert "RuntimeError" in caplog.text
    assert "private-primary-payload" not in caplog.text
    assert "private-cleanup-payload" not in caplog.text
