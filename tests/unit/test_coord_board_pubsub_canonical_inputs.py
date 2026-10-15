"""Deferred canonical-input coverage for coordination blackboard and pubsub."""

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.client import HubClient
from local_ai_hub.operation_contracts import operation_contract, validate_operation_arguments


class RecordingClient:
    def __init__(self):
        self.calls = []

    def post(self, path, payload, **kwargs):
        self.calls.append(("post", path, payload, kwargs))
        return {"success": True}

    def coord(self, **payload):
        self.calls.append(("coord", payload))
        return {"success": True}


@pytest.mark.parametrize("content", [None, False, 0, "", [], {}])
def test_blackboard_update_preserves_falsey_content(monkeypatch, tmp_path, content):
    client = RecordingClient()
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    result = mcp_server.local_ai_coord(
        action="blackboard_update", root=str(tmp_path), board_id="board-a",
        section="review", content=content, expected_version=0,
    )

    assert result["success"] is True
    assert client.calls[0][2]["content"] == content
    assert client.calls[0][2]["expected_version"] == 0
    assert "remote_sections" not in client.calls[0][2]


@pytest.mark.parametrize("message", [None, False, 0, "", [], {}])
def test_pubsub_publish_preserves_falsey_message(monkeypatch, tmp_path, message):
    client = RecordingClient()
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    result = mcp_server.local_ai_coord(
        action="pubsub_publish", root=str(tmp_path), topic="events",
        message=message, publisher="agent-x",
    )

    assert result["success"] is True
    assert client.calls == [("coord", {
        "action": "pubsub_publish", "topic": "events", "message": message,
        "publisher": "agent-x", "root": str(tmp_path),
    })]


def test_pubsub_poll_forwards_sequence_limit_and_timestamp(monkeypatch, tmp_path):
    client = RecordingClient()
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    result = mcp_server.local_ai_coord(
        action="pubsub_poll", root=str(tmp_path), topic="events",
        after_seq=0, limit=17, after_ts=12.5,
    )

    assert result["success"] is True
    assert client.calls == [("coord", {
        "action": "pubsub_poll", "topic": "events", "after_seq": 0,
        "limit": 17, "since_timestamp": 12.5, "root": str(tmp_path),
    })]


def test_board_and_pubsub_aliases_are_rejected_before_backend(monkeypatch, tmp_path):
    client = RecordingClient()
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    board_result = mcp_server.local_ai_coord(
        action="blackboard_update", root=str(tmp_path), content="canonical", value="legacy",
    )
    pubsub_result = mcp_server.local_ai_coord(
        action="pubsub_publish", root=str(tmp_path), message="canonical", key="legacy-topic",
    )

    assert board_result["success"] is False
    assert pubsub_result["success"] is False
    assert client.calls == []


def test_contract_requires_canonical_write_payloads_and_limits_action_fields():
    contract = operation_contract("local_ai_coord")
    assert "content" in contract["actions"]["blackboard_update"]["required"]
    assert "message" in contract["actions"]["pubsub_publish"]["required"]
    assert validate_operation_arguments(
        "local_ai_coord", "pubsub_publish", {"message": {}, "value": "old"}
    ) is not None
    assert validate_operation_arguments(
        "local_ai_coord", "blackboard_get", {"board_id": "b", "expected_version": 3}
    ) is not None


@pytest.mark.parametrize("message", [None, False, 0, "", [], {}])
def test_client_pubsub_publish_preserves_present_falsey_message(monkeypatch, message):
    client = object.__new__(HubClient)
    calls = []
    monkeypatch.setattr(client, "post", lambda path, payload: calls.append((path, payload)) or {"success": True})

    result = client.coord("pubsub_publish", topic="events", message=message)

    assert result["success"] is True
    assert calls == [("/api/coord/pubsub_publish", {
        "root": ".", "topic": "events", "message": message, "publisher": "agent",
    })]


@pytest.mark.parametrize("kwargs", [
    {"message": "m", "value": "alias"},
    {"message": "m", "topic": None},
    {"message": "m", "publisher": None},
])
def test_client_pubsub_publish_rejects_noncanonical_fields(monkeypatch, kwargs):
    client = object.__new__(HubClient)
    calls = []
    monkeypatch.setattr(client, "post", lambda *args: calls.append(args) or {"success": True})

    result = client.coord("pubsub_publish", **kwargs)

    assert result["success"] is False
    assert calls == []


def test_client_pubsub_poll_forwards_canonical_timestamp_filter(monkeypatch):
    client = object.__new__(HubClient)
    calls = []
    monkeypatch.setattr(client, "post", lambda path, payload: calls.append((path, payload)) or {"success": True})

    result = client.coord("pubsub_poll", topic="events", after_seq=0, limit=17, since_timestamp=12.5)

    assert result["success"] is True
    assert calls == [("/api/coord/pubsub_poll", {
        "root": ".", "topic": "events", "limit": 17, "after_seq": 0,
        "since_timestamp": 12.5,
    })]


@pytest.mark.parametrize("kwargs", [
    {"key": "legacy"},
    {"limit": True},
    {"after_seq": 1.5},
    {"since_timestamp": float("inf")},
    {"since_timestamp": True},
    {"since_timestamp": 10**1000},
])
def test_client_pubsub_poll_rejects_invalid_filters(monkeypatch, kwargs):
    client = object.__new__(HubClient)
    calls = []
    monkeypatch.setattr(client, "post", lambda *args: calls.append(args) or {"success": True})

    result = client.coord("pubsub_poll", **kwargs)

    assert result["success"] is False
    assert calls == []
