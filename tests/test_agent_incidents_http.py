from __future__ import annotations

from contextlib import closing
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome
from local_ai_hub.sqlite_support import connect_sqlite


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


def test_resolve_rejects_reserved_placeholder(tmp_path):
    store = IncidentStore(AgentStateStore(tmp_path / "legacy.sqlite3"))
    root = str(tmp_path.resolve())
    incident = store.capture(ToolOutcome(
        tool_name="command", error="fixture worker failure", exit_code=1,
        state_revision="rev-1", repository_root=root,
    ))
    assert incident is not None
    with pytest.raises(ValueError, match="verified_fix must describe a verified fix"):
        store.resolve(incident.incident_id, verified_fix=" ReSoLvEd ", root_cause="worker returned no patch")
    with pytest.raises(ValueError, match="verified_fix must describe a verified fix"):
        store.resolve_all(verified_fix="resolved")
    record = store.get(incident.incident_id)
    assert record is not None and record.resolved is False and record.verified_fix is None


def test_capture_rejects_reserved_verified_fix_placeholder(tmp_path):
    store = IncidentStore(AgentStateStore(tmp_path / "incidents.sqlite3"))
    with pytest.raises(ValueError, match="verified_fix must describe a verified fix"):
        store.capture(ToolOutcome(
            tool_name="command", error="failure", exit_code=1, state_revision="rev-1",
            repository_root=str(tmp_path.resolve()), metadata={"verified_fix": "resolved"},
        ))


def test_http_record_rejects_reserved_verified_fix_placeholder(monkeypatch, tmp_path):
    (status, payload), store = _post_incident(monkeypatch, tmp_path, {
        "message": "fixture operation failed",
        "operation_class": "command",
        "verified_fix": "resolved",
    })
    assert status == 400
    assert payload["terminal"] is True and payload["retryable"] is False
    assert store.list_incidents(root=str(tmp_path.resolve())) == []


def test_incident_store_rejects_noncanonical_persisted_placeholder(tmp_path):
    database = tmp_path / "incidents.sqlite3"
    initial = IncidentStore(AgentStateStore(database))
    incident = initial.capture(ToolOutcome(
        tool_name="command", error="fixture worker failure", exit_code=1,
        state_revision="rev-1", repository_root=str(tmp_path.resolve()),
    ))
    assert incident is not None
    with closing(connect_sqlite(database)) as con:
        con.execute("UPDATE agent_incidents SET verified_fix=' resolved ', resolved=1 WHERE incident_id=?", (incident.incident_id,))
        con.commit()

    with pytest.raises(RuntimeError, match="retired verified_fix placeholder"):
        IncidentStore(AgentStateStore(database)).get(incident.incident_id)
