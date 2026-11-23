"""Question namespace, idempotency and preflight without tenancy."""

from contextlib import closing
import sqlite3

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import CheckpointResponseBudgetError, TaskStore
from local_ai_hub.sqlite_support import DurableSchemaMismatchError
from local_ai_hub import agent_tasks, http_server, sqlite_support


@pytest.mark.parametrize("method,arguments", [
    ("ask_question", {"root": "", "session_id": "session-one", "question": "Question?"}),
    ("answer_question", {"root": "", "question_id": "q_one", "answer": "Answer"}),
])
@pytest.mark.parametrize("value", [None, "", False, "former-owner"])
def test_retired_question_argument_rejects_before_database_access(method, arguments, value):
    store = TaskStore.__new__(TaskStore)
    with pytest.raises(TypeError, match="tenant"):
        getattr(store, method)(**arguments, tenant=value)


def test_question_database_has_no_tenant_and_task_binding_is_preserved(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    store = TaskStore(AgentStateStore(db_path))
    pending = store.ask_question(root=str(tmp_path), session_id="chat-one", task_id="task-one", question="Proceed?")
    question_id = pending["question_id"]
    assert store.ask_question(root=str(tmp_path), session_id="chat-one", task_id="other-task", question_id=question_id) is None
    assert store.ask_question(root=str(tmp_path), session_id="chat-two", question_id=question_id) is None
    assert store.answer_question(root=str(tmp_path), task_id="other-task", question_id=question_id, answer="Yes") is None
    answered = store.answer_question(root=str(tmp_path), task_id="task-one", question_id=question_id, answer="Yes")
    assert answered["session_id"] == "chat-one"
    assert answered["task_id"] == "task-one"
    with closing(sqlite3.connect(db_path)) as con:
        columns = [row[1] for row in con.execute("PRAGMA table_info(agent_questions)")]
        indexes = con.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'agent_questions'").fetchall()
    assert len(columns) == 11
    assert "tenant" not in columns
    assert all("tenant" not in (row[0] or "") for row in indexes)


def test_answer_budget_failure_keeps_original_question(tmp_path):
    store = TaskStore(AgentStateStore(tmp_path / "state.sqlite3"))
    pending = store.ask_question(root=str(tmp_path), session_id="chat-one", question="Proceed?")
    with pytest.raises(CheckpointResponseBudgetError):
        store.answer_question(root=str(tmp_path), question_id=pending["question_id"], answer="Yes", response_budget_tokens=1)
    after = store.ask_question(root=str(tmp_path), session_id="chat-one", question_id=pending["question_id"])
    assert after == pending


def test_question_root_requires_existing_absolute_directory(tmp_path):
    for root in (".", str(tmp_path / "missing")):
        with pytest.raises(ValueError):
            TaskStore._validate_question_scope(root, "chat-one")


def test_retired_question_schema_rejects_without_rewriting_saved_answer(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    store = TaskStore(AgentStateStore(db_path))
    pending = store.ask_question(root=str(tmp_path), session_id="chat-one", question="Proceed?")
    store.answer_question(root=str(tmp_path), question_id=pending["question_id"], answer="Preserve this answer")
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("ALTER TABLE agent_questions ADD COLUMN tenant TEXT NOT NULL DEFAULT 'former-owner'")
        con.commit()
        before = con.execute("SELECT * FROM agent_questions").fetchall()
    with pytest.raises(DurableSchemaMismatchError):
        TaskStore(AgentStateStore(db_path))
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute("SELECT * FROM agent_questions").fetchall() == before


def test_http_question_scope_has_no_owner_selector(tmp_path):
    root = str(tmp_path)
    assert http_server._agent_question_scope(payload={"root": root}, authorized_root=root) == str(tmp_path.resolve())
    with pytest.raises(ValueError, match="tenant"):
        http_server._agent_question_scope(payload={"root": root, "tenant": None}, authorized_root=root)
    with pytest.raises(TypeError, match="authorized_tenant"):
        http_server._agent_question_scope(payload={"root": root}, authorized_root=root, authorized_tenant=None)


@pytest.mark.parametrize("operation", ["ask", "answer"])
def test_question_writes_roll_back_when_shared_transaction_budget_expires(
    tmp_path, monkeypatch, operation
):
    store = TaskStore(AgentStateStore(tmp_path / "state.sqlite3"))
    root = str(tmp_path)
    pending = None
    if operation == "answer":
        pending = store.ask_question(
            root=root, session_id="session-a", question="Proceed?"
        )

    def _expired_transaction(con, **kwargs):
        return sqlite_support.write_transaction(
            con, max_duration_seconds=1e-12, **kwargs
        )

    monkeypatch.setattr(agent_tasks, "write_transaction", _expired_transaction, raising=False)
    with pytest.raises(TimeoutError, match="duration budget"):
        if operation == "ask":
            store.ask_question(root=root, session_id="session-a", question="Proceed?")
        else:
            store.answer_question(
                root=root,
                question_id=pending["question_id"],
                answer="Yes",
            )

    with closing(sqlite3.connect(store.state_store.db_path)) as con:
        rows = con.execute(
            "SELECT question_id, status FROM agent_questions ORDER BY question_id"
        ).fetchall()
    if operation == "ask":
        assert rows == []
    else:
        assert rows == [(pending["question_id"], "pending")]
