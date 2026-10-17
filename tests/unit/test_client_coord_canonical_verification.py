"""Deferred client coverage for canonical coordination verification inputs."""
from __future__ import annotations

import pytest

from local_ai_hub.client import HubClient


@pytest.fixture
def client_and_calls(monkeypatch):
    client = HubClient.__new__(HubClient)
    calls = []

    def fake_post(path, payload=None, **kwargs):
        calls.append((path, payload, kwargs))
        return {"success": True}

    monkeypatch.setattr(client, "post", fake_post)
    return client, calls


def test_coord_context_compile_maps_canonical_fields_and_preserves_metadata(client_and_calls):
    client, calls = client_and_calls

    result = client.coord(
        "context_compile", task_id="task-1", max_tokens=3500,
        paths=["src/a.py"], since_hash="source-hash", include_diagnostics=True,
        repository_revision="rev-4", phase="review",
    )

    assert result["success"] is True
    assert calls == [(
        "/api/agent-state/context",
        {
            "action": "compile", "task_id": "task-1", "token_budget": 3500,
            "changed_paths": ["src/a.py"], "since_hash": "source-hash",
            "include_diagnostics": True, "repository_revision": "rev-4",
            "phase": "review", "root": ".",
        },
        {},
    )]


def test_coord_context_compile_defaults_budget(client_and_calls):
    client, calls = client_and_calls

    client.coord("context_compile", task_id="task-1")

    assert calls[0][1]["token_budget"] == 4000
    assert calls[0][1]["changed_paths"] == []


@pytest.mark.parametrize("retired", [
    {"query": "task-2"}, {"task": "task-2"}, {"token_budget": 1200},
    {"changed_paths": ["old.py"]},
])
def test_coord_context_compile_rejects_retired_inputs_before_post(client_and_calls, retired):
    client, calls = client_and_calls

    result = client.coord("context_compile", task_id="task-1", **retired)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert calls == []


def test_coord_verify_receipt_forwards_explicit_receipt_without_synthesis(client_and_calls):
    client, calls = client_and_calls
    receipt = {"task_id": "task-1", "criterion": "unit", "passed": False}

    client.coord("verify_receipt", receipt=receipt)

    assert calls == [(
        "/api/agent-state/verification",
        {"action": "receipt", "receipt": receipt, "root": "."},
        {},
    )]


@pytest.mark.parametrize("retired", [
    {"task_id": "task-1", "criterion": "unit"},
    {"receipt": {"task_id": "task-1", "criterion": "unit", "passed": False}, "passed": True},
    {"receipt": {"task_id": "task-1", "criterion": "unit", "passed": False}, "checkpoint": {}},
])
def test_coord_verify_receipt_rejects_synthesis_and_retired_fields(client_and_calls, retired):
    client, calls = client_and_calls

    result = client.coord("verify_receipt", **retired)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert calls == []


def test_coord_verify_completion_preserves_repository_revision(client_and_calls):
    client, calls = client_and_calls

    client.coord("verify_completion", task_id="task-1", repository_revision="rev-7")

    assert calls == [(
        "/api/agent-state/verification",
        {
            "action": "completion", "task_id": "task-1", "root": ".",
            "repository_revision": "rev-7",
        },
        {},
    )]


@pytest.mark.parametrize("retired", [{"query": "task-2"}, {"task": "task-2"}])
def test_coord_verify_completion_rejects_task_aliases(client_and_calls, retired):
    client, calls = client_and_calls

    result = client.coord("verify_completion", task_id="task-1", **retired)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert calls == []


def test_coord_verify_export_uses_task_id_and_format(client_and_calls):
    client, calls = client_and_calls

    client.coord("verify_export", task_id="task-1", format="jsonl")

    assert calls == [(
        "/api/agent-state/verification",
        {"action": "export", "task_id": "task-1", "root": ".", "format": "jsonl"},
        {},
    )]


def test_coord_verify_export_uses_canonical_default_format(client_and_calls):
    client, calls = client_and_calls

    client.coord("verify_export", task_id="task-1")

    assert calls[0][1]["format"] == "markdown"


@pytest.mark.parametrize(
    "action",
    ("memo_put", "memo_get", "memo_search", "memo_delete", "memo_future"),
)
def test_coord_rejects_retired_memo_actions_before_http_dispatch(client_and_calls, action):
    client, calls = client_and_calls

    result = client.coord(action, root="C:/repo", key="legacy")

    assert result == {
        "success": False,
        "status_code": 400,
        "terminal": True,
        "retryable": False,
        "error": f"retired coord action '{action}'",
    }
    assert calls == []


def test_coord_memory_find_keeps_canonical_agent_state_route(client_and_calls):
    client, calls = client_and_calls

    result = client.coord(
        "memory_find", root="C:/repo", query="known", tenant="caller-tenant",
        repository_id="caller-repo", coordination_id="caller-coordination",
    )

    assert result["success"] is True
    assert calls == [("/api/agent-state/memory", {
        "root": "C:/repo", "query": "known", "action": "find",
    }, {})]
