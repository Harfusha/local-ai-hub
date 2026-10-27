from __future__ import annotations

import threading
import time
import socket
from urllib.parse import urlparse

import pytest


@pytest.fixture
def live_api(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    state_dir = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{state_dir.as_posix()}"\n'
        f'\n[security]\napi_token = "test-api-token"\n'
        f'allowed_roots = ["{tmp_path.as_posix()}"]\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    client = HubClient(config_path=str(config), auto_start=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            res = client.get("/health")
            if res.get("success"):
                break
        except Exception:
            pass
        time.sleep(0.01)
    try:
        yield app, client
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()


def test_resolve_imports_get_and_post_share_auto_default(live_api, tmp_path):
    app, client = live_api
    calls = []
    root = tmp_path / "repo"
    root.mkdir()

    def resolve_imports(root, symbols, language):
        calls.append((root, symbols, language))
        return {"success": True, "language": language}

    app.services.resolve_imports = resolve_imports

    get_result = client.get(f"/api/resolve_imports?root={root}&symbol=Thing")
    post_result = client.post("/api/resolve_imports", {"root": str(root), "symbol": "Thing"})

    assert get_result["language"] == "auto"
    assert post_result["language"] == "auto"
    assert calls == [(str(root.resolve()), ["Thing"], "auto"), (str(root.resolve()), ["Thing"], "auto")]


def test_unsupported_chat_completions_rejects_valid_payload(live_api):
    _app, client = live_api

    result = client.post("/api/chat/completions", {"messages": [{"role": "user", "content": "hello"}]})

    assert result["success"] is False
    assert result["status_code"] == 404
    assert "messages" not in result["error"]


@pytest.mark.parametrize(
    "messages",
    [
        "not-a-list",
        [],
        [{}] * 129,
    ],
)
def test_unsupported_chat_completions_returns_404_for_invalid_payloads(live_api, messages):
    _app, client = live_api

    result = client.post("/api/chat/completions", {"messages": messages})

    assert result["success"] is False
    assert result["status_code"] == 404


def test_unsupported_route_rejects_before_waiting_for_large_body(live_api):
    _app, client = live_api
    endpoint = urlparse(client.base_url)
    with socket.create_connection((endpoint.hostname, endpoint.port), timeout=5) as conn:
        conn.settimeout(5)
        conn.sendall(
            b"POST /api/chat/completions HTTP/1.1\r\n"
            b"Host: localhost\r\nContent-Length: 1000001\r\n\r\n"
        )
        assert conn.recv(4096).startswith(b"HTTP/1.1 404")

    # A full-body client can encounter a reset while the server rejects it;
    # an unknown outcome must not be fabricated into an HTTP response.
    result = client.post("/api/chat/completions", {
        "messages": [{"role": "user", "content": "x" * 1_000_001}]
    })
    assert result["success"] is False
    assert result.get("status_code") == 404 or result.get("outcome_unknown") is True


@pytest.mark.parametrize("message", [None, "text"])
def test_unsupported_chat_completions_returns_404_for_non_object_messages(live_api, message):
    _app, client = live_api

    result = client.post("/api/chat/completions", {"messages": [message]})

    assert result["success"] is False
    assert result["status_code"] == 404


def test_task_list_query_filters_contract_and_checkpoint_before_limit(live_api, tmp_path):
    app, client = live_api
    root = str(tmp_path)

    matching = client.create_task(
        "goal-needle",
        acceptance_criteria=["criterion-needle"],
        task_id="query-match",
        root=root,
    )
    assert matching["success"] is True
    checkpoint = client.post("/api/agent-state/tasks", {
        "action": "checkpoint",
        "task_id": "query-match",
        "root": root,
        "checkpoint": {
            "phase": "phase-needle",
            "next_action": "action-needle",
            "affected_paths": ["path-needle"],
            "blockers": ["blocker-needle"],
        },
    })
    assert checkpoint["success"] is True
    unrelated = client.create_task("Newest unrelated task", task_id="query-other", root=root)
    assert unrelated["success"] is True

    owner_client = type(client)(config_path=str(tmp_path / "config.toml"), auto_start=False)
    owner_client.agent = "distinct-owner"
    try:
        owner_task = owner_client.create_task("Owner-only task", task_id="query-owner", root=root)
        assert owner_task["success"] is True
    finally:
        owner_client.close()
    store_result = app.agent_tasks.list_tasks(query="BLOCKER-NEEDLE", limit=1)
    assert [task.task_id for task in store_result] == ["query-match"]

    queries = [
        "query-match",
        "goal-needle",
        "criterion-needle",
        "phase-needle",
        "action-needle",
        "path-needle",
        "blocker-needle",
    ]
    for query in queries:
        post_result = client.list_tasks(query=query.upper(), limit=1, root=root)
        assert [item["task_id"] for item in post_result["tasks"]] == ["query-match"], query

    owner_result = client.list_tasks(query="DISTINCT-OWNER", limit=1, root=root)
    assert [item["task_id"] for item in owner_result["tasks"]] == ["query-owner"]

    from urllib.parse import urlencode

    get_result = client.get("/api/agent-state/tasks?" + urlencode({"root": root, "query": "BLOCKER-NEEDLE", "limit": 1}))
    assert [task["task_id"] for task in get_result["tasks"]] == ["query-match"]

    unfiltered = client.list_tasks(query="  ", limit=10, root=root)
    assert {task["task_id"] for task in unfiltered["tasks"]} == {"query-match", "query-other", "query-owner"}


def test_task_list_query_skips_stale_matches_before_limit(live_api):
    from local_ai_hub.agent_identity import ScopeContext
    from local_ai_hub.agent_tasks import GoalContract
    from local_ai_hub.sqlite_support import connect_sqlite

    app, _client = live_api
    stale = app.agent_tasks.create(GoalContract(goal="page-needle stale"), ScopeContext(), task_id="stale-match")
    fresh = app.agent_tasks.create(GoalContract(goal="page-needle fresh"), ScopeContext(), task_id="fresh-match")
    con = connect_sqlite(app.agent_state.db_path)
    try:
        con.execute(
            "UPDATE agent_tasks_projection SET heartbeat_expires_at=?, updated_at=? WHERE task_id=?",
            (1.0, 2.0, stale.task_id),
        )
        con.execute(
            "UPDATE agent_tasks_projection SET heartbeat_expires_at=?, updated_at=? WHERE task_id=?",
            (0.0, 1.0, fresh.task_id),
        )
        con.commit()
    finally:
        con.close()

    tasks = app.agent_tasks.list_tasks(query="page-needle", limit=1)

    assert [task.task_id for task in tasks] == ["fresh-match"]


def test_task_list_surfaces_query_scan_truncation(live_api, monkeypatch, tmp_path):
    from local_ai_hub.agent_tasks import TaskList

    app, client = live_api
    monkeypatch.setattr(
        app.agent_tasks,
        "list_tasks",
        lambda **_kwargs: TaskList([], query_truncated=True),
    )

    result = client.list_tasks(query="needle", root=str(tmp_path))

    assert result["success"] is True
    assert result["tasks"] == []
    assert result["query_truncated"] is True


def test_task_list_post_rejects_non_string_query(live_api, tmp_path):
    _app, client = live_api
    root = str(tmp_path)

    response = client.post("/api/agent-state/tasks", {"action": "list", "query": ["needle"], "root": root})

    assert response["success"] is False
    assert response["terminal"] is True
    assert response["retryable"] is False
    assert "query" in response["error"].lower()


def test_coord_task_list_forwards_query(monkeypatch):
    from local_ai_hub import mcp_server

    captured = {}

    class DummyClient:
        def coord(self, action, **kwargs):
            captured.update(action=action, kwargs=kwargs)
            return {"success": True, "tasks": []}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)

    result = mcp_server.local_ai_coord(action="task_list", query="needle")

    assert result["success"] is True
    assert captured["action"] == "task_list"
    assert captured["kwargs"]["query"] == "needle"


def test_lean_rag_description_lists_every_supported_action(monkeypatch):
    from local_ai_hub import mcp_server

    monkeypatch.setattr(mcp_server, "LEAN_SCHEMAS", True)
    description = mcp_server._desc_rag()

    for action in (
        "index",
        "search",
        "list",
        "docset_index",
        "docset_search",
        "ingest_document",
        "ingest_diagram",
    ):
        assert action in description
    for control in ("max_response_tokens", "response_profile", "delta", "reuse_key", "extra_fields"):
        assert control in description


def test_lean_work_description_lists_continuation_and_response_controls(monkeypatch):
    from local_ai_hub import mcp_server

    monkeypatch.setattr(mcp_server, "LEAN_SCHEMAS", True)
    description = mcp_server._desc_work()

    for control in (
        "continue",
        "return_fields",
        "max_output_tokens",
        "max_response_tokens",
        "response_profile",
        "reuse_key",
        "extra_fields",
        "delta",
    ):
        assert control in description


def test_semantic_diff_action_uses_public_call_graph_diff_route(monkeypatch, tmp_path):
    from local_ai_hub import mcp_server

    captured = {}

    def fake_post(path, payload, **kwargs):
        captured.update(path=path, payload=payload)
        return {"success": True, "changes": []}

    monkeypatch.setattr(mcp_server.CLIENT, "post", fake_post)
    root = tmp_path / "repo"
    root.mkdir()
    result = mcp_server.local_ai_repo(
        action="semantic_diff",
        root=str(root),
        diff="diff --git a/a.cs b/a.cs",
    )

    assert result.get("success") is True, result
    assert captured["path"] == "/api/repo/call_graph_diff"
    assert captured["payload"]["root"].endswith("repo")
    assert captured["payload"]["diff"] == "diff --git a/a.cs b/a.cs"


def test_artifact_list_is_bounded_shared_metadata_and_needs_no_id(live_api, monkeypatch):
    from types import SimpleNamespace

    from local_ai_hub import mcp_server

    app, client = live_api
    with app.artifacts.batch() as batch:
        for index in range(105):
            batch.put(f"artifact-{index}", kind="test")

    with app.artifacts.batch() as batch:
        shared_id = batch.put("shared installation artifact", kind="test")

    route_result = client.post("/api/artifact/list", {"limit": 1000})
    assert route_result["success"] is True
    artifacts = route_result["artifacts"]
    assert len(artifacts) == 100
    expected_fields = {"artifact_id", "kind", "size_bytes", "created_at", "mime_type"}
    assert all(set(item) == expected_fields for item in artifacts)
    assert all(left["created_at"] >= right["created_at"] for left, right in zip(artifacts, artifacts[1:]))

    assert shared_id in {item["artifact_id"] for item in artifacts}

    captured = {}

    def fake_post(path, payload):
        captured.update(path=path, payload=payload)
        return {"success": True, "artifacts": artifacts[:20]}

    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=fake_post))
    public_result = mcp_server.local_ai_artifact(action="list")

    assert captured == {"path": "/api/artifact/list", "payload": {"limit": 20}}
    assert public_result["success"] is True
    assert len(public_result["artifacts"]) == 20


def test_artifact_store_rejects_legacy_schema_without_rewriting(tmp_path):
    import sqlite3
    from contextlib import closing

    from local_ai_hub.artifacts import ArtifactStore, UnsupportedArtifactSchema

    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            "CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL, "
            "tenant TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL)"
        )
        con.execute("INSERT INTO artifacts VALUES ('legacy-id', 9999999999, 'tenant', 'text', 'kept')")
        con.commit()

    original = db_path.read_bytes()
    with pytest.raises(UnsupportedArtifactSchema):
        ArtifactStore(tmp_path)
    assert db_path.read_bytes() == original
    assert not db_path.with_name(db_path.name + "-wal").exists()
