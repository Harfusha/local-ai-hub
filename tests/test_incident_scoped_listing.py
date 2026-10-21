"""Repository incident listing must filter before truncating results."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from local_ai_hub import http_server
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome


@pytest.fixture
def incident_rows(tmp_path):
    store = IncidentStore(AgentStateStore(tmp_path / "incidents.sqlite3"))
    root = str(tmp_path / "repo")
    foreign_root = str(tmp_path / "foreign")
    rows = {}
    for label, repository, resolved, ignored, updated in (
        ("open", root, 0, 0, 10),
        ("fixed", root, 1, 0, 20),
        ("ignored", root, 0, 1, 30),
        ("foreign", foreign_root, 0, 0, 100),
    ):
        row = store.capture(ToolOutcome(
            tool_name="command", command="python -m pytest",
            error=f"RuntimeError: {label} command failed", exit_code=1,
            state_revision="fixture-revision", repository_root=repository,
        ))
        assert row is not None
        with closing(sqlite3.connect(store.state_store.db_path)) as db:
            db.execute(
                "UPDATE agent_incidents SET resolved=?, ignored=?, updated_at=? "
                "WHERE incident_id=?",
                (resolved, ignored, updated, row.incident_id),
            )
            db.commit()
        rows[label] = row.incident_id
    return store, root, foreign_root, rows


def test_repository_filter_precedes_limit_and_global_listing_is_preserved(incident_rows):
    store, root, _, rows = incident_rows
    assert [r.incident_id for r in store.list_incidents(limit=1)] == [rows["foreign"]]
    assert [r.incident_id for r in store.list_incidents(root=root, limit=1)] == [rows["ignored"]]
    assert store.list_incidents(root=root + "-missing", limit=1) == []


@pytest.mark.parametrize("status,label", [
    ("unresolved", "open"), ("resolved", "fixed"), ("ignored", "ignored"),
])
def test_repository_listing_retains_status_filters_before_limit(incident_rows, status, label):
    store, root, _, rows = incident_rows
    result = store.list_incidents(root=root, status=status, limit=1)
    assert [r.incident_id for r in result] == [rows[label]]


def test_repository_listing_retains_resolved_filter(incident_rows):
    store, root, _, rows = incident_rows
    result = store.list_incidents(root=root, resolved="false")
    assert {r.incident_id for r in result} == {rows["open"], rows["ignored"]}


@pytest.mark.parametrize("root", ["", " ", 0, False, "repo\x00bad"])
def test_explicit_invalid_repository_never_selects_global_listing(incident_rows, root):
    store, _, _, _ = incident_rows
    with pytest.raises(ValueError, match="root"):
        store.list_incidents(root=root)


def test_negative_knowledge_search_still_rejects_empty_query(incident_rows):
    store, root, _, _ = incident_rows
    with pytest.raises(ValueError, match="query"):
        store.find_negative_knowledge("", root=root)


def _get_incidents(monkeypatch, store, query, *, allow_root=True):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_incidents=store))
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_: None)
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/agent-state/incidents?" + urlencode(query)
    handler._reject_identity_fields = lambda _: True
    handler._require_authorized = lambda *args, **kwargs: True
    handler._begin_trace = lambda _: None
    responses, roots = [], []
    handler._send = lambda status, payload: responses.append((status, payload))

    def bind_root(values):
        roots.append(values["root"][0])
        if not allow_root:
            handler._send(403, {"success": False, "error": "root is not authorized"})
        return allow_root

    handler._bind_repository_root_query = bind_root
    handler.do_GET()
    assert len(responses) == 1
    return responses[0], roots


def test_scoped_get_uses_listing_and_retains_filters(monkeypatch, incident_rows):
    store, root, _, rows = incident_rows
    (status, payload), roots = _get_incidents(
        monkeypatch, store, {"root": root, "status": "unresolved", "limit": 1},
    )
    assert status == 200 and payload["success"] is True
    assert [r["incident_id"] for r in payload["incidents"]] == [rows["open"]]
    assert roots == [root]


@pytest.mark.parametrize("root", ["", "all", "__all__"])
def test_global_get_keeps_existing_listing(monkeypatch, incident_rows, root):
    store, _, _, rows = incident_rows
    (status, payload), roots = _get_incidents(monkeypatch, store, {"root": root, "limit": 1})
    assert status == 200 and payload["success"] is True
    assert [r["incident_id"] for r in payload["incidents"]] == [rows["foreign"]]
    assert roots == []


def test_scoped_get_authorizes_root_before_reading(monkeypatch, incident_rows):
    store, root, _, _ = incident_rows
    def unexpected_read(*args, **kwargs):
        pytest.fail("unauthorized incident store read")
    monkeypatch.setattr(store, "list_incidents", unexpected_read)
    monkeypatch.setattr(store, "find_negative_knowledge", unexpected_read)
    (status, payload), roots = _get_incidents(
        monkeypatch, store, {"root": root}, allow_root=False,
    )
    assert status == 403 and payload["success"] is False
    assert roots == [root]
