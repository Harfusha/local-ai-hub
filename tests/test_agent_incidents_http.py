from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome


def _post_incident(monkeypatch, tmp_path, record):
    root = str(tmp_path.resolve())
    store = IncidentStore(AgentStateStore(tmp_path / "incidents.sqlite3"))
    app = SimpleNamespace(
        agent_incidents=store,
        config={"security": {"allowed_roots": [root]}},
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/agent-state/incidents"
    handler.command = "POST"
    handler.headers = {"Content-Type": "application/json"}
    handler._require_authorized = lambda *_args, **_kwargs: True
    handler._begin_trace = lambda *_args: None
    handler._read_json = lambda: {"action": "record", "root": root, **record}
    responses = []
    handler._send = lambda status, payload, **_kwargs: responses.append((status, payload))
    handler.do_POST()
    assert len(responses) == 1
    return responses[0], store


def test_recording_root_cause_does_not_invent_verified_fix(monkeypatch, tmp_path):
    (status, payload), store = _post_incident(monkeypatch, tmp_path, {
        "message": "fixture operation failed",
        "operation_class": "command",
        "root_cause": "worker returned no patch",
    })
    assert status == 200 and payload["success"] is True
    incident = payload["incident"]
    assert incident["root_cause"] == "worker returned no patch"
    assert incident["resolved"] is False
    assert incident["verified_fix"] is None
    persisted = store.get(incident["incident_id"])
    assert persisted is not None and persisted.resolved is False
    assert persisted.verified_fix is None


def test_recording_explicit_verified_fix_resolves_incident(monkeypatch, tmp_path):
    (status, payload), store = _post_incident(monkeypatch, tmp_path, {
        "message": "fixture operation failed",
        "operation_class": "command",
        "root_cause": "worker returned no patch",
        "verified_fix": "validated retry on the same fixture",
    })
    assert status == 200 and payload["success"] is True
    incident = payload["incident"]
    assert incident["resolved"] is True
    assert incident["verified_fix"] == "validated retry on the same fixture"
    assert store.get(incident["incident_id"]).resolved is True


def test_legacy_placeholder_is_not_a_verified_retry(tmp_path):
    store = IncidentStore(AgentStateStore(tmp_path / "legacy.sqlite3"))
    root = str(tmp_path.resolve())
    incident = store.capture(ToolOutcome(
        tool_name="command", error="fixture worker failure", exit_code=1,
        state_revision="rev-1", repository_root=root,
    ))
    assert incident is not None
    store.resolve(incident.incident_id, verified_fix="resolved", root_cause="worker returned no patch")
    record = store.get(incident.incident_id)
    assert record is not None
    assert record.resolved is False
    assert record.to_dict()["verified_fix"] is None
    assert record.to_dict()["resolved"] is False
    assert store.find_negative_knowledge("worker", root=root)[0]["verified_fix"] == ""
    assert [row.incident_id for row in store.list_incidents(root=root, status="unresolved")] == [incident.incident_id]
    assert store.list_incidents(root=root, status="resolved") == []
    assert store.incident_count(resolved=False) == 1
    assert store.incident_count(resolved=True) == 0
    decision = store.retry_decision(incident.fingerprint, "rev-1", root=root)
    assert decision.action == "stop"
