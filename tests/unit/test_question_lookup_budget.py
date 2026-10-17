from types import SimpleNamespace

import pytest

from local_ai_hub import agent_tasks as agent_tasks_module


def test_existing_question_lookup_preflights_response_budget(monkeypatch):
    store = agent_tasks_module.TaskStore.__new__(agent_tasks_module.TaskStore)
    store.state_store = SimpleNamespace(db_path="unused")
    monkeypatch.setattr(store, "_db_path_available", lambda: True)
    monkeypatch.setattr(
        store,
        "_validate_question_scope",
        lambda *_args: ("root", "tenant", "session"),
    )
    monkeypatch.setattr(store, "_init_projection_table", lambda: None)
    monkeypatch.setattr(
        store,
        "_question_row_to_dict",
        lambda _row: {
            "question_id": "q_existing",
            "session_id": "session",
            "task_id": "",
            "question": "Stored question",
            "answer": "Stored answer",
            "status": "answered",
            "asked_by": "agent",
            "answered_by": "operator",
            "created_at": 1.0,
            "answered_at": 2.0,
        },
    )

    class _Cursor:
        def fetchone(self):
            return object()

    class _Connection:
        def execute(self, *_args):
            return _Cursor()

        def close(self):
            pass

    monkeypatch.setattr(
        agent_tasks_module, "connect_sqlite", lambda _path: _Connection()
    )
    monkeypatch.setattr(
        agent_tasks_module, "retry_busy", lambda callback, **_kwargs: callback()
    )
    monkeypatch.setattr(
        agent_tasks_module,
        "mcp_wire_tokens",
        lambda _value, **_kwargs: 129,
    )

    with pytest.raises(agent_tasks_module.CheckpointResponseBudgetError):
        store.ask_question(
            root="root",
            tenant="tenant",
            session_id="session",
            question_id="q_existing",
            response_budget_tokens=128,
        )
