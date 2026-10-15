from __future__ import annotations

from pathlib import Path
import asyncio
import json

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import TaskStore
from local_ai_hub.client import HubClient
from local_ai_hub.operation_contracts import operation_actions
from local_ai_hub import mcp_server


def _task_store(tmp_path: Path) -> TaskStore:
    return TaskStore(AgentStateStore(tmp_path / "agent-state.sqlite"))


def test_question_and_answer_survive_public_mcp_projection(tmp_path, monkeypatch):
    calls = []
    question = {"question_id": "q_123", "session_id": "session-a", "status": "answered", "answer": "Option A"}

    class Client:
        def coord(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "question": question}

    monkeypatch.setattr(mcp_server, "CLIENT", Client())
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    for action in ("ask", "answer"):
        wire = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
            "action": action, "root": str(tmp_path), "session_id": "session-a",
            "question_id": "q_123", "answer": "Option A", "max_response_tokens": 1024,
            "response_profile": "compact",
        }))
        contents = wire[0] if isinstance(wire, tuple) else wire
        result = json.loads(next(item.text for item in contents if item.type == "text"))
        assert result["question"] == question
    assert [call["action"] for call in calls] == ["ask", "answer"]


def test_answer_is_idempotent_and_rejects_overwriting_operator_decision(tmp_path):
    store = _task_store(tmp_path)
    scope = {"root": str(tmp_path), "tenant": "tenant-a"}
    pending = store.ask_question(**scope, session_id="session-a", question="Which option?")
    assert store.ask_question(
        **scope, session_id="session-b", question_id=pending["question_id"]
    ) is None
    arguments = {**scope, "question_id": pending["question_id"], "answer": "Option A"}
    first = store.answer_question(**arguments)
    assert store.answer_question(**arguments) == first
    with pytest.raises(ValueError, match="already been answered"):
        store.answer_question(**{**arguments, "answer": "Option B"})
    assert store.ask_question(
        **scope, session_id="session-a", question_id=pending["question_id"]
    )["answer"] == "Option A"


def test_agent_question_and_operator_answer_persist_across_store_instances(
    tmp_path: Path,
) -> None:
    root = str(tmp_path / "project")
    store = _task_store(tmp_path)

    pending = store.ask_question(
        root=root,
        tenant="tenant-a",
        session_id="session-1",
        question="Which migration should this task target?",
        actor="agent",
    )
    answered = store.answer_question(
        question_id=pending["question_id"],
        root=root,
        tenant="tenant-a",
        answer="Use migration 0042.",
        actor="operator",
    )
    retrieved = _task_store(tmp_path).ask_question(
        root=root,
        tenant="tenant-a",
        session_id="session-1",
        question_id=pending["question_id"],
    )

    assert pending["status"] == "pending"
    assert pending["answer"] == ""
    assert answered["status"] == "answered"
    assert retrieved["answer"] == "Use migration 0042."
    assert retrieved["answered_by"] == "operator"
    assert retrieved["session_id"] == "session-1"


def test_agent_question_and_answer_are_isolated_by_root_and_tenant(
    tmp_path: Path,
) -> None:
    store = _task_store(tmp_path)
    pending = store.ask_question(
        root=str(tmp_path / "project"),
        tenant="tenant-a",
        session_id="session-1",
        question="Need operator input",
        actor="agent",
    )

    assert store.ask_question(
        root=str(tmp_path / "other-project"),
        tenant="tenant-a",
        session_id="session-1",
        question_id=pending["question_id"],
    ) is None
    assert store.ask_question(
        root=str(tmp_path / "project"),
        tenant="tenant-b",
        session_id="session-1",
        question_id=pending["question_id"],
    ) is None
    assert store.answer_question(
        question_id=pending["question_id"],
        root=str(tmp_path / "project"),
        tenant="tenant-b",
        answer="cross-tenant leak",
        actor="operator",
    ) is None


def test_agent_question_rejects_missing_session_and_unbounded_text(
    tmp_path: Path,
) -> None:
    store = _task_store(tmp_path)
    arguments = {
        "root": str(tmp_path / "project"),
        "tenant": "tenant-a",
        "actor": "agent",
    }

    for question, session_id in (("Question?", ""), (" " * 32_769, "session-1")):
        try:
            store.ask_question(
                **arguments,
                session_id=session_id,
                question=question,
            )
        except ValueError:
            continue
        raise AssertionError("invalid question input must be rejected")


def test_agent_question_actions_are_public_and_use_scoped_task_route(monkeypatch) -> None:
    client = HubClient.__new__(HubClient)
    calls: list[tuple[str, dict[str, object]]] = []

    def _post(path: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((path, payload))
        return {"success": True}

    monkeypatch.setattr(client, "post", _post)

    ask_result = client.coord(
        "ask",
        root="C:/repo",
        tenant="tenant-a",
        session_id="session-1",
        question="Need operator input",
    )
    answer_result = client.coord(
        "answer",
        root="C:/repo",
        tenant="tenant-a",
        question_id="q_123",
        answer="Proceed with option A",
    )

    assert {"ask", "answer"}.issubset(set(operation_actions("local_ai_coord")))
    assert ask_result["success"] is True
    assert answer_result["success"] is True
    assert calls == [
        (
            "/api/agent-state/tasks",
            {
                "action": "ask",
                "root": "C:/repo",
                "tenant": "tenant-a",
                "session_id": "session-1",
                "task_id": "",
                "question_id": "",
                "question": "Need operator input",
                "answer": "",
            },
        ),
        (
            "/api/agent-state/tasks",
            {
                "action": "answer",
                "root": "C:/repo",
                "tenant": "tenant-a",
                "session_id": "",
                "task_id": "",
                "question_id": "q_123",
                "question": "",
                "answer": "Proceed with option A",
            },
        ),
    ]
