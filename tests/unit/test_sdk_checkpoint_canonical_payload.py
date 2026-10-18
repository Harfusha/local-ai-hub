from __future__ import annotations

import pytest

from local_ai_hub.agent_tasks import TaskCheckpoint
from local_ai_hub.client import HubClient


def test_sdk_checkpoint_task_posts_canonical_nested_checkpoint(monkeypatch):
    client = HubClient.__new__(HubClient)
    captured = {}

    def capture(path, payload):
        captured.update(path=path, payload=payload)
        return {"success": True}

    monkeypatch.setattr(client, "post", capture)
    result = client.checkpoint_task(
        "task-1",
        phase="runtime-acceptance",
        next_action="review receipt",
        affected_paths=["src/module.py"],
        evidence_ids=["E1"],
        blockers=["pending integration"],
        state_data={"repository_revision": "rev-1"},
        root="C:/repo",
        response_budget_tokens=1200,
        idempotency_key="checkpoint-1",
    )

    checkpoint = {
        "phase": "runtime-acceptance",
        "next_action": "review receipt",
        "affected_paths": ["src/module.py"],
        "evidence_ids": ["E1"],
        "blockers": ["pending integration"],
        "state_data": {"repository_revision": "rev-1"},
    }
    payload = captured["payload"]
    assert result["success"] is True
    assert captured["path"] == "/api/agent-state/tasks"
    assert payload == {
        "action": "checkpoint",
        "task_id": "task-1",
        "checkpoint": checkpoint,
        "root": "C:/repo",
        "response_budget_tokens": 1200,
        "idempotency_key": "checkpoint-1",
    }
    assert TaskCheckpoint.from_dict(payload["checkpoint"]).to_dict() == checkpoint


def test_sdk_checkpoint_task_does_not_accept_retired_or_unknown_fields():
    client = HubClient.__new__(HubClient)

    with pytest.raises(TypeError):
        client.checkpoint_task("task-1", tenant=None)


@pytest.mark.parametrize("field", ["affected_paths", "evidence_ids", "blockers", "state_data"])
def test_sdk_checkpoint_rejects_invalid_falsey_values_before_transport(monkeypatch, field):
    client = HubClient.__new__(HubClient)
    monkeypatch.setattr(client, "post", lambda *args: pytest.fail("invalid payload reached transport"))
    with pytest.raises(TypeError, match=field):
        client.checkpoint_task("task-1", **{field: False})


def test_sdk_checkpoint_rejects_nonstring_idempotency_before_transport():
    client = HubClient.__new__(HubClient)
    with pytest.raises(TypeError, match="idempotency_key"):
        client.checkpoint_task("task-1", idempotency_key=False)

