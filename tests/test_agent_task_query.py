from __future__ import annotations

from contextlib import closing
from pathlib import Path
import threading

import pytest

import local_ai_hub.agent_tasks as agent_tasks
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskCheckpoint, TaskList, TaskStore
from local_ai_hub.client import HubClient
from local_ai_hub import mcp_server


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))


def _create(store: TaskStore, task_id: str, goal: str) -> None:
    store.create(
        GoalContract(goal=goal),
        ScopeContext(repository_id="repo-1", branch="main", task_id=task_id),
        task_id=task_id,
    )


def test_task_query_matches_goal_and_checkpoint_fields(store: TaskStore) -> None:
    _create(store, "header-task", "Improve dashboard header")
    _create(store, "search-task", "Improve repository search")
    store.checkpoint(
        "search-task",
        TaskCheckpoint(phase="implementation", next_action="verify header"),
        actor="agent",
        idempotency_key="search-checkpoint",
    )

    matches = store.list_tasks(query="HEADER")

    assert {task.task_id for task in matches} == {"header-task", "search-task"}


def test_task_query_reports_bounded_scan_truncation(
    store: TaskStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_tasks, "MAX_TASK_QUERY_SCAN_ROWS", 2, raising=False)
    for index in range(3):
        _create(store, f"task-{index}", f"Unrelated task {index}")

    matches = store.list_tasks(query="not-present")

    assert matches == []
    assert matches.query_truncated is True


def test_client_list_tasks_sends_query_to_agent_state_route() -> None:
    client = object.__new__(HubClient)
    captured: dict[str, object] = {}

    def post(path: str, payload: dict[str, object]) -> dict[str, object]:
        captured.update(path=path, payload=payload)
        return {"success": True, "tasks": []}

    client.post = post  # type: ignore[method-assign]

    client.list_tasks(query="find header")

    assert captured == {
        "path": "/api/agent-state/tasks",
        "payload": {"action": "list", "limit": 100, "query": "find header"},
    }


def test_coord_task_list_forwards_query_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Client:
        def coord(self, **kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"success": True, "tasks": []}

    monkeypatch.setattr(mcp_server, "CLIENT", Client())

    mcp_server.local_ai_coord(action="task_list", query="find header")

    assert captured["action"] == "task_list"
    assert captured["query"] == "find header"


@pytest.fixture
def live_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{(tmp_path / "state").as_posix()}"\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    client = HubClient(config_path=str(config), auto_start=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, client
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()


def test_http_task_query_searches_contract_checkpoint_and_owner_before_limit(live_api) -> None:
    from local_ai_hub.agent_identity import ScopeContext

    app, client = live_api
    assert client.create_task(
        "goal-needle", acceptance_criteria=["criterion-needle"], task_id="query-match"
    )["success"]
    assert client.post("/api/agent-state/tasks", {
        "action": "checkpoint",
        "task_id": "query-match",
        "checkpoint": {
            "phase": "phase-needle",
            "next_action": "action-needle",
            "affected_paths": ["path-needle"],
            "blockers": ["blocker-needle"],
        },
    })["success"]
    assert client.create_task("Newest unrelated task", task_id="query-other")["success"]
    app.agent_tasks.create(
        GoalContract(goal="Owner-only task"), ScopeContext(), task_id="query-owner", actor="distinct-owner"
    )

    for term in (
        "query-match", "goal-needle", "criterion-needle", "phase-needle", "action-needle",
        "path-needle", "blocker-needle",
    ):
        result = client.list_tasks(query=term.upper(), limit=1)
        assert [task["task_id"] for task in result["tasks"]] == ["query-match"], term
    assert [task["task_id"] for task in client.list_tasks(query="DISTINCT-OWNER", limit=1)["tasks"]] == ["query-owner"]
    assert [task["task_id"] for task in client.get("/api/agent-state/tasks?query=BLOCKER-NEEDLE&limit=1")["tasks"]] == ["query-match"]
    assert {task["task_id"] for task in client.list_tasks(query="  ", limit=10)["tasks"]} == {
        "query-match", "query-other", "query-owner"
    }


def test_http_task_query_skips_stale_matches_before_page_limit(live_api) -> None:
    from local_ai_hub.agent_tasks import GoalContract
    from local_ai_hub.sqlite_support import connect_sqlite

    app, _client = live_api
    stale = app.agent_tasks.create(GoalContract(goal="page-needle stale"), ScopeContext(), task_id="stale-match")
    fresh = app.agent_tasks.create(GoalContract(goal="page-needle fresh"), ScopeContext(), task_id="fresh-match")
    with closing(connect_sqlite(app.agent_state.db_path)) as con:
        con.execute(
            "UPDATE agent_tasks_projection SET heartbeat_expires_at=?, updated_at=? WHERE task_id=?",
            (1.0, 2.0, stale.task_id),
        )
        con.execute(
            "UPDATE agent_tasks_projection SET heartbeat_expires_at=?, updated_at=? WHERE task_id=?",
            (0.0, 1.0, fresh.task_id),
        )
        con.commit()

    matches = app.agent_tasks.list_tasks(query="page-needle", limit=1)

    assert [task.task_id for task in matches] == ["fresh-match"]


def test_http_task_query_rejects_non_string_payload(live_api) -> None:
    _app, client = live_api

    result = client.post("/api/agent-state/tasks", {"action": "list", "query": ["needle"]})

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "query" in result["error"].lower()


def test_http_task_query_surfaces_scan_truncation(live_api, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client = live_api
    monkeypatch.setattr(
        app.agent_tasks,
        "list_tasks",
        lambda **_kwargs: TaskList([], query_truncated=True),
    )

    result = client.list_tasks(query="needle")

    assert result["success"] is True
    assert result["tasks"] == []
    assert result["query_truncated"] is True
