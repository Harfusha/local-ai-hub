"""Deferred canonical-input coverage for coordination and verification actions."""
from __future__ import annotations

import asyncio

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import operation_input_schema, validate_operation_arguments


def _activate_coord(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)


def _implementation():
    implementation = mcp_server.local_ai_coord
    while hasattr(implementation, "__wrapped__"):
        implementation = implementation.__wrapped__
    return implementation


class _FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, path, payload, **kwargs):
        self.calls.append(("post", path, payload))
        return {"success": True, **payload}

    def coord(self, **payload):
        self.calls.append(("coord", payload))
        return {"success": True, **payload}


def test_registered_ask_and_answer_use_canonical_fields(monkeypatch, tmp_path):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "ask", "root": str(tmp_path), "tenant": "tenant-a",
        "session_id": "session-a", "question_id": "q-1", "question": "Question?",
    }))
    asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "answer", "root": str(tmp_path), "tenant": "tenant-a",
        "question_id": "q-1", "answer": "Answer.",
    }))

    assert client.calls == [
        ("coord", {
            "action": "ask", "root": str(tmp_path), "tenant": "tenant-a",
            "session_id": "session-a", "question_id": "q-1", "question": "Question?",
        }),
        ("coord", {
            "action": "answer", "root": str(tmp_path), "tenant": "tenant-a",
            "question_id": "q-1", "answer": "Answer.",
        }),
    ]


def test_context_compile_uses_only_task_id_and_canonical_context_fields(monkeypatch, tmp_path):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "context_compile", "root": str(tmp_path), "task_id": "task-1",
        "since_hash": "source-hash", "paths": ["src/a.py"], "max_tokens": 3500,
    }))

    path, payload = client.calls[0][1:]
    assert path == "/api/agent-state/context"
    assert payload["task_id"] == "task-1"
    assert payload["token_budget"] == 3500
    assert payload["since_hash"] == "source-hash"
    assert payload["changed_paths"] == ["src/a.py"]
    assert payload["include_diagnostics"] is False


def test_context_compile_uses_canonical_default_budget(monkeypatch, tmp_path):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    _implementation()(action="context_compile", root=str(tmp_path), task_id="task-1")

    assert client.calls[0][2]["token_budget"] == 4000
    assert client.calls[0][2]["since_hash"] == ""


def test_verification_receipt_preserves_explicit_false(monkeypatch, tmp_path):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    receipt = {"task_id": "task-1", "criterion": "unit", "passed": False}

    _implementation()(action="verify_receipt", root=str(tmp_path), receipt=receipt)

    assert client.calls == [(
        "post", "/api/agent-state/verification",
        {"action": "receipt", "receipt": receipt, "root": str(tmp_path)},
    )]


def test_verification_receipt_is_required_and_never_synthesized(monkeypatch, tmp_path):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    result = _implementation()(action="verify_receipt", root=str(tmp_path))

    assert result["success"] is False
    assert client.calls == []


@pytest.mark.parametrize(("action", "arguments", "expected"), [
    ("task_cleanup_worktree", {"task_id": "task-1"}, ("/api/agent-state/tasks", {"action": "cleanup_worktree", "task_id": "task-1"})),
    ("verify_completion", {"task_id": "task-1"}, ("/api/agent-state/verification", {"action": "completion", "task_id": "task-1", "root": "."})),
    ("verify_export", {"task_id": "task-1"}, ("/api/agent-state/verification", {"action": "export", "task_id": "task-1", "root": ".", "format": "markdown"})),
])
def test_registered_task_and_verification_payloads_are_canonical(monkeypatch, action, arguments, expected):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {"action": action, **arguments}))

    assert client.calls == [("post", expected[0], expected[1])]


@pytest.mark.parametrize(("action", "canonical", "alias"), [
    ("ask", {"question": "Question?", "session_id": "s"}, {"query": ""}),
    ("answer", {"question_id": "q", "answer": "Answer"}, {"value": ""}),
    ("task_cleanup_worktree", {"task_id": "t"}, {"key": ""}),
    ("context_compile", {"task_id": "t"}, {"ttl_seconds": 0}),
    ("verify_receipt", {"receipt": {"task_id": "t", "criterion": "c", "passed": False}}, {"checkpoint": {}}),
    ("verify_completion", {"task_id": "t"}, {"query": ""}),
    ("verify_export", {"task_id": "t"}, {"status": ""}),
])
def test_shared_contract_rejects_alias_presence_even_with_canonical_input(action, canonical, alias):
    assert validate_operation_arguments(
        "local_ai_coord", action, {**canonical, **alias},
    ) is not None


@pytest.mark.parametrize(("action", "arguments"), [
    ("ask", {"question": "Question?", "session_id": "s", "query": "old"}),
    ("answer", {"question_id": "q", "answer": "Answer", "value": "old"}),
    ("task_cleanup_worktree", {"task_id": "t", "key": "old"}),
    ("context_compile", {"task_id": "t", "ttl_seconds": 10}),
    ("verify_receipt", {"receipt": {"task_id": "t", "criterion": "c", "passed": False}, "status": "passed"}),
    ("verify_completion", {"task_id": "t", "query": "old"}),
    ("verify_export", {"task_id": "t", "section": "jsonl"}),
])
def test_direct_helper_rejects_nonempty_retired_values(monkeypatch, action, arguments):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    result = _implementation()(action=action, **arguments)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert client.calls == []


def test_coord_verification_contract_preserves_required_receipt_proof():
    assert validate_operation_arguments("local_ai_coord", "verify_receipt", {}) is not None
    assert validate_operation_arguments("local_ai_coord", "verify_receipt", {
        "receipt": {"task_id": "task-1", "criterion": "unit", "passed": True},
    }) is not None
    assert validate_operation_arguments("local_ai_coord", "verify_receipt", {
        "receipt": {"task_id": "task-1", "criterion": "unit", "passed": False},
    }) is None


def test_context_compile_contract_uses_token_budget_default():
    assert operation_input_schema("local_ai_coord", "context_compile")["properties"]["max_tokens"]["default"] == 4000
