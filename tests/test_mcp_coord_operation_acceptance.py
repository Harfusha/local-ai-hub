"""Operation-specific behavior coverage for unlinked local_ai_coord actions."""

import asyncio
import json
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import quote

import mcp.types as mcp_types
import pytest

from local_ai_hub import mcp_server
from local_ai_hub import http_server
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskCheckpoint, TaskStore


class CoordBackend:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def coord(self, **payload):
        self.calls.append(payload)
        return self.response


class ApiBackend:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, payload, **kwargs):
        if path != "/api/telemetry/tool-accounting":
            self.calls.append((path, payload, kwargs))
        return self.response

    def get(self, path, **kwargs):
        self.calls.append((path, None, kwargs))
        return self.response


def test_local_ai_coord_task_get_forwards_task_and_root_identity(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = CoordBackend(
        {"success": True, "summary": "task t-get-1 is active", "task": {"task_id": "t-get-1", "status": "active"}}
    )
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_get", task_id="t-get-1", root=root, include_stale=True
    )

    assert backend.calls == [{
        "action": "task_get", "task_id": "t-get-1", "contract": None,
        "checkpoint": None, "status": "", "reason": "", "root": root,
        "ttl_seconds": 0, "include_stale": True,
    }]
    assert result["success"] is True
    assert result["summary"] == "task t-get-1 is active"


def test_local_ai_coord_task_checkpoint_preserves_checkpoint_payload(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    checkpoint = {"phase": "verify", "next_action": "run focused suite", "revision": "r17"}
    backend = CoordBackend({"success": True, "summary": "checkpoint recorded for t-check-1"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_checkpoint", task_id="t-check-1", checkpoint=checkpoint, root=root,
        max_response_tokens=768,
    )

    assert backend.calls == [{
        "action": "task_checkpoint", "task_id": "t-check-1", "contract": None,
        "checkpoint": checkpoint, "status": "", "reason": "", "root": root,
        "ttl_seconds": 0, "include_stale": False, "response_budget_tokens": 768,
    }]
    assert result["success"] is True
    assert result["summary"] == "checkpoint recorded for t-check-1"


def test_local_ai_coord_task_transition_forwards_target_state_and_reason(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = CoordBackend({"success": True, "summary": "task t-transition-1 moved to verifying"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_transition", task_id="t-transition-1", status="verifying",
        reason="focused checks are ready", root=root, max_response_tokens=768,
    )

    assert backend.calls == [{
        "action": "task_transition", "task_id": "t-transition-1", "contract": None,
        "checkpoint": None, "status": "verifying", "reason": "focused checks are ready",
        "root": root, "ttl_seconds": 0, "include_stale": False, "response_budget_tokens": 768,
    }]
    assert result["success"] is True
    assert result["summary"] == "task t-transition-1 moved to verifying"


def test_local_ai_coord_task_list_forwards_status_and_stale_filter(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = CoordBackend({"success": True, "summary": "one active task", "tasks": [{"task_id": "t-list-1"}]})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_list", status="active", root=root, include_stale=True
    )

    assert backend.calls == [{
        "action": "task_list", "task_id": "", "contract": None,
        "checkpoint": None, "status": "active", "reason": "", "root": root, "query": "",
        "ttl_seconds": 0, "include_stale": True,
    }]
    assert result["success"] is True
    assert result["summary"] == "one active task"


def test_local_ai_coord_task_complete_forwards_reason_and_identity(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = CoordBackend({"success": True, "summary": "task t-done-1 completed"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_complete", task_id="t-done-1", reason="acceptance receipts attached", root=root,
        max_response_tokens=768,
    )

    assert backend.calls == [{
        "action": "task_complete", "task_id": "t-done-1", "contract": None,
        "checkpoint": None, "status": "", "reason": "acceptance receipts attached",
        "root": root, "ttl_seconds": 0, "include_stale": False, "response_budget_tokens": 768,
    }]
    assert result["success"] is True
    assert result["summary"] == "task t-done-1 completed"


def test_local_ai_coord_memo_put_posts_root_key_value_and_ttl(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = ApiBackend({"success": True, "summary": "memo stored", "key": "handoff:cli"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="memo_put", root=root, key="handoff:cli", value="CLI audit complete",
        ttl_seconds=3600,
    )

    assert backend.calls == [(
        "/api/memory/put",
        {"root": root, "key": "handoff:cli", "value": "CLI audit complete", "ttl_seconds": 3600},
        {},
    )]
    assert result["success"] is True
    assert result["summary"] == "memo stored"


def test_local_ai_coord_memo_search_posts_query_with_root_scope(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = ApiBackend({"success": True, "summary": "one matching memo", "records": [{"key": "handoff:cli"}]})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="memo_search", root=root, query="CLI audit"
    )

    assert backend.calls == [(
        "/api/memory/search", {"root": root, "query": "CLI audit", "limit": 12}, {}
    )]
    assert result["success"] is True
    assert result["summary"] == "one matching memo"


def test_local_ai_coord_memo_delete_posts_exact_root_and_key(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = ApiBackend({"success": True, "summary": "memo deleted", "key": "handoff:old"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="memo_delete", root=root, key="handoff:old"
    )

    assert backend.calls == [
        ("/api/memory/delete", {"root": root, "key": "handoff:old"}, {})
    ]
    assert result["success"] is True
    assert result["summary"] == "memo deleted"


def test_local_ai_coord_claim_forwards_owned_paths_and_lease_identity(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    paths = ["tools/surface_inventory.py", "tests/test_surface_inventory.py"]
    backend = ApiBackend({"success": True, "summary": "lease granted", "lease_id": "lease-42"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="claim", root=root, paths=paths, ttl_seconds=1200, value="T01 matcher tests"
    )

    assert backend.calls == [(
        "/api/leases/claim_batch",
        {"root": root, "paths": paths, "ttl_seconds": 1200, "purpose": "T01 matcher tests"},
        {},
    )]
    assert result["success"] is True
    assert result["summary"] == "lease granted"


def _direct_post(app, path, payload):
    handler = object.__new__(http_server.Handler)
    handler.path = path
    handler.headers = {"Content-Type": "application/json", "X-LocalAI-Agent": "T08-test"}
    replies = []
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: payload
    handler._send = lambda status, body: replies.append((status, body))
    previous_app = http_server.APP
    http_server.APP = app
    try:
        http_server.Handler.do_POST(handler)
    finally:
        http_server.APP = previous_app
    assert len(replies) == 1
    return replies[0]


def _assert_candidate_import_origin():
    candidate_root = Path(__file__).resolve().parents[1]
    assert Path(mcp_server.__file__).resolve() == (
        candidate_root / "src" / "local_ai_hub" / "mcp_server.py"
    )
    assert Path(http_server.__file__).resolve() == (
        candidate_root / "src" / "local_ai_hub" / "http_server.py"
    )


def test_http_agent_task_rejects_unknown_action_without_store_mutation(tmp_path, monkeypatch):
    _assert_candidate_import_origin()
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite3")
    tasks = TaskStore(state_store)
    app = SimpleNamespace(agent_state=state_store, agent_tasks=tasks, config={"security": {}})

    status, result = _direct_post(
        app, "/api/agent-state/tasks",
        {"action": "delete_all", "task_id": "task-1", "root": str(tmp_path.resolve())},
    )

    assert status == 400
    assert result["success"] is False
    assert result["error"] == "unknown task action"
    assert tasks.list_tasks() == []
    assert state_store.events("task:task-1") == []


def test_local_ai_coord_task_rollback_restores_and_persists_previous_checkpoint(
    monkeypatch, tmp_path
):
    _assert_candidate_import_origin()
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mcp_server, "load_operational_mode",
        lambda *_args, **_kwargs: SimpleNamespace(mode="active", revision=1, degraded=False),
    )
    db_path = tmp_path / "agent-state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task_id = "task-rollback-acceptance"
    target = tmp_path / "rollback-target.txt"
    target.write_text("baseline", encoding="utf-8")
    tasks.create(
        GoalContract(goal="exercise rollback"),
        ScopeContext(
            repository_id=str(tmp_path.resolve()),
            task_id=task_id,
            session_id="api-token-default",
        ),
        task_id=task_id,
    )
    tasks.checkpoint(
        task_id,
        TaskCheckpoint(
            phase="baseline",
            state_data={"file_snapshots": {str(target): "baseline"}},
        ),
    )
    target.write_text("changed", encoding="utf-8")
    tasks.checkpoint(
        task_id,
        TaskCheckpoint(
            phase="changed",
            state_data={"file_snapshots": {str(target): "changed"}},
        ),
    )
    app = SimpleNamespace(agent_state=state_store, agent_tasks=tasks, config={"security": {}})
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)

    def post_without_socket(path, payload, **_kwargs):
        assert path == "/api/agent-state/tasks"
        assert payload["action"] == "rollback"
        assert payload["task_id"] == task_id
        status, response = _direct_post(app, path, payload)
        assert status == 200
        return response

    monkeypatch.setattr(mcp_server.CLIENT, "post", post_without_socket)
    tool_result = asyncio.run(
        mcp_server.mcp.call_tool(
            "local_ai_coord", {
                "action": "task_rollback", "task_id": task_id,
                "root": str(tmp_path.resolve()),
            }
        )
    )
    if isinstance(tool_result, tuple):
        content = tool_result[0][0]
    else:
        assert isinstance(tool_result, list)
        content = tool_result[0]
    assert isinstance(content, mcp_types.TextContent)
    result = json.loads(content.text)

    assert result["success"] is True, result
    assert target.read_text(encoding="utf-8") == "baseline"
    reopened = TaskStore(AgentStateStore(db_path))
    persisted = reopened.get(task_id)
    assert persisted is not None
    assert persisted.checkpoint.phase == "baseline"
    assert reopened.state_store.events(f"task:{task_id}")[-1].kind == "task.rolled_back"


def test_local_ai_coord_feature_disabled_rejects_valid_action_before_backend_dispatch(monkeypatch):
    _assert_candidate_import_origin()

    class NeverDispatch:
        def __getattr__(self, name):
            raise AssertionError(f"disabled local_ai_coord reached CLIENT.{name}")

    monkeypatch.setattr(
        mcp_server, "load_operational_mode",
        lambda *_args, **_kwargs: SimpleNamespace(mode="active", revision=1, degraded=False),
    )
    monkeypatch.setattr(mcp_server.FEATURES, "coord", False)
    monkeypatch.setattr(mcp_server, "CLIENT", NeverDispatch())
    tool_result = asyncio.run(
        mcp_server.mcp.call_tool(
            "local_ai_coord", {"action": "task_rollback", "task_id": "disabled-task"}
        )
    )
    if isinstance(tool_result, tuple):
        content = tool_result[0][0]
    else:
        assert isinstance(tool_result, list)
        content = tool_result[0]
    assert isinstance(content, mcp_types.TextContent)
    result = json.loads(content.text)

    assert result["success"] is False
    assert result.get("unsupported") is True, result
    assert result["error"] == "local_ai_coord is disabled in configuration"


def _prepare_coord_api(monkeypatch):
    backend = ApiBackend({"success": True, "summary": "forwarded"})
    # Forwarding fixtures own their mode; operator/background state is unrelated.
    monkeypatch.setattr(
        mcp_server, "load_operational_mode",
        lambda *_args, **_kwargs: SimpleNamespace(mode="active", revision=1, degraded=False),
    )
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    return backend


def _prepare_coord_rpc(monkeypatch):
    backend = CoordBackend({"success": True, "summary": "forwarded"})
    monkeypatch.setattr(
        mcp_server, "load_operational_mode",
        lambda *_args, **_kwargs: SimpleNamespace(mode="active", revision=1, degraded=False),
    )
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    return backend


def test_local_ai_coord_blackboard_get_forwards_board_and_section(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='blackboard_get', root=root, board_id="board-17", section="planning")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/agent-state/blackboard",
        {"action": "get", "root": root, "board_id": "board-17", "section": "planning"},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_blackboard_list_forwards_action_and_root(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='blackboard_list', root=root)
    assert result["success"] is True
    calls = backend.calls
    assert calls[0][0] == "/api/agent-state/blackboard"
    assert calls[0][1] == {
        "action": "list", "root": root,
    }
    assert calls[0][2] == {"timeout": mcp_server._timeout("quick")}


def test_local_ai_coord_blackboard_merge_forwards_remote_sections(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    remote = {"remote": {"summary": "preserve"}}
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='blackboard_merge', root=root, board_id="board-19", remote_sections=remote)
    assert result["success"] is True
    calls = backend.calls
    assert calls[0][0] == "/api/agent-state/blackboard"
    assert calls[0][1] == {
        "action": "merge", "root": root, "board_id": "board-19",
        "remote_sections": remote,
    }
    assert calls[0][2] == {"timeout": mcp_server._timeout("quick")}


def test_local_ai_coord_blackboard_delete_forwards_board_and_section(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='blackboard_delete', root=root, board_id="board-20", section="archive")
    assert result["success"] is True
    calls = backend.calls
    assert calls[0][0] == "/api/agent-state/blackboard"
    assert calls[0][1] == {
        "action": "delete", "root": root, "board_id": "board-20", "section": "archive",
    }
    assert calls[0][2] == {"timeout": mcp_server._timeout("quick")}


def test_local_ai_coord_leases_forwards_root_filter(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='leases', root=root)
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(f"/api/leases?root={mcp_server.quote(root)}", None, {})]


def test_local_ai_coord_memo_get_forwards_root_and_key(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='memo_get', root=root, key="handoff:active")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/memory/get", {"root": root, "key": "handoff:active"}, {}
    )]


def test_local_ai_coord_memory_promote_forwards_record_identity(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    result = mcp_server.local_ai_coord(action='memory_promote', root=root, record_id="memory-42", target_scope="project", approver="reviewer", scope="task", scope_id="task-42", task_id="task-42", session_id="session-3")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [{
        "action": "memory_promote", "record": None, "record_id": "memory-42",
        "target_scope": "project", "approver": "reviewer", "key": "",
        "value": "", "query": "", "root": root, "scope": "task",
        "scope_id": "task-42", "task_id": "task-42", "session_id": "session-3",
        "clone_id": "", "worktree_id": "", "branch": "",
        "repository_id": "", "tenant": "",
    }]


def test_local_ai_coord_memory_reap_is_private(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    result = mcp_server.local_ai_coord(action='memory_reap', root=root)
    assert result["success"] is False
    assert result["terminal"] is True
    assert "Unknown local_ai_coord action 'memory_reap'" in result["error"]
    assert backend.calls == []


def test_local_ai_coord_negative_knowledge_find_forwards_query_and_limit(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='negative_knowledge_find', root=root, query="retry exhausted", limit=12)
    assert result["success"] is True, result
    calls = backend.calls
    assert calls == [(
        "/api/agent-state/incidents",
        {"action": "find", "root": root, "tenant": "",
         "query": "retry exhausted", "limit": 12},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_negative_knowledge_record_forwards_verified_fix(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    record = {
        "operation_class": "ValueError", "message": "invalid payload",
        "root_cause": "caller omitted field", "verified_fix": "validate before retry",
    }
    result = mcp_server.local_ai_coord(action='negative_knowledge_record', root=root, record=record)
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/agent-state/incidents",
        {**record, "action": "record", "root": root, "tenant": ""},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_pubsub_poll_forwards_topic_and_cursor(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    result = mcp_server.local_ai_coord(action='pubsub_poll', root=root, topic="build-status", limit=9, after_ts=173.5)
    assert result["success"] is True
    calls = backend.calls
    assert calls == [{
        "action": "pubsub_poll", "topic": "build-status", "after_seq": None,
        "limit": 9, "after_ts": 173.5, "root": root,
    }]


def test_local_ai_coord_pubsub_publish_forwards_topic_message_and_publisher(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    message = {"state": "ready", "revision": "r8"}
    backend = _prepare_coord_rpc(monkeypatch)
    result = mcp_server.local_ai_coord(action='pubsub_publish', root=root, topic="build-status", message=message, publisher="worker-2")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [{
        "action": "pubsub_publish", "topic": "build-status", "message": message,
        "publisher": "worker-2", "root": root,
    }]


def test_local_ai_coord_relation_actions_are_private(monkeypatch):
    backend = _prepare_coord_rpc(monkeypatch)
    for action in ("relation_record", "relation_find", "relation_traverse"):
        result = mcp_server.local_ai_coord(action=action)
        assert result["success"] is False
        assert result["terminal"] is True
        assert f"Unknown local_ai_coord action '{action}'" in result["error"]
    assert backend.calls == []


def test_local_ai_coord_release_forwards_lease_identity(monkeypatch):
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='release', lease_id="lease-41")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/leases/release", {"lease_id": "lease-41"}, {}
    )]


def test_local_ai_coord_renew_forwards_lease_identity_and_ttl(monkeypatch):
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='renew', lease_id="lease-42", ttl_seconds=240)
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/leases/renew", {"lease_id": "lease-42", "ttl_seconds": 240}, {}
    )]


def test_local_ai_coord_swarm_cancel_forwards_reason(monkeypatch, tmp_path):
    backend = _prepare_coord_api(monkeypatch)
    root = str(tmp_path.resolve())
    result = mcp_server.local_ai_coord(action='swarm_cancel', root=root, swarm_id="swarm-52", reason="scope closed")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/agent-state/swarm/cancel",
        {"swarm_id": "swarm-52", "reason": "scope closed", "root": root},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_swarm_dispatch_forwards_goal_paths_and_test_command(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    paths = ["src/worker.py", "tests/test_worker.py"]
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='swarm_dispatch', root=root, goal="review worker", target_paths=paths, test_command="pytest -q tests/test_worker.py", author="reviewer")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/agent-state/swarm/dispatch",
        {"goal": "review worker", "target_paths": paths,
         "test_command": "pytest -q tests/test_worker.py", "author": "reviewer",
         "root": root},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_swarm_list_forwards_state_filter(monkeypatch, tmp_path):
    backend = _prepare_coord_api(monkeypatch)
    root = str(tmp_path.resolve())
    result = mcp_server.local_ai_coord(action='swarm_list', root=root, state="active")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        f"/api/agent-state/swarm?root={quote(root)}&state=active", None,
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_swarm_status_forwards_swarm_identity(monkeypatch, tmp_path):
    backend = _prepare_coord_api(monkeypatch)
    root = str(tmp_path.resolve())
    result = mcp_server.local_ai_coord(action='swarm_status', root=root, swarm_id="swarm-53")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        f"/api/agent-state/swarm/swarm-53?root={quote(root)}", None,
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_swarm_step_forwards_role_action_and_payload(monkeypatch, tmp_path):
    payload = {"patch": "diff --git a/a b/a"}
    backend = _prepare_coord_api(monkeypatch)
    root = str(tmp_path.resolve())
    result = mcp_server.local_ai_coord(action='swarm_step', root=root, swarm_id="swarm-54", role="Reviewer", swarm_action="approve_patch", payload=payload)
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/agent-state/swarm/step",
        {"swarm_id": "swarm-54", "role": "Reviewer",
         "action": "approve_patch", "payload": payload, "root": root},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_task_cleanup_worktree_forwards_task_identity(monkeypatch):
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='task_cleanup_worktree', task_id="task-55")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/agent-state/tasks",
        {"action": "cleanup_worktree", "task_id": "task-55"},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_task_fail_forwards_failure_reason(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    result = mcp_server.local_ai_coord(action='task_fail', root=root, task_id="task-56", reason="acceptance failed", status="failed", max_response_tokens=768)
    assert result["success"] is True
    calls = backend.calls
    assert calls == [{
        "action": "task_fail", "task_id": "task-56", "contract": None,
        "checkpoint": None, "status": "failed", "reason": "acceptance failed",
        "root": root, "ttl_seconds": 0, "include_stale": False, "response_budget_tokens": 768,
    }]


def test_local_ai_coord_task_heartbeat_forwards_task_identity_and_ttl(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    result = mcp_server.local_ai_coord(action='task_heartbeat', root=root, task_id="task-57", ttl_seconds=180)
    assert result["success"] is True
    calls = backend.calls
    assert calls == [{
        "action": "task_heartbeat", "task_id": "task-57", "contract": None,
        "checkpoint": None, "status": "", "reason": "", "root": root,
        "ttl_seconds": 180, "include_stale": False,
    }]


def test_local_ai_coord_task_resume_forwards_task_identity_and_reason(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    result = mcp_server.local_ai_coord(action='task_resume', root=root, task_id="task-58", reason="operator resumed")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [{
        "action": "task_resume", "task_id": "task-58", "contract": None,
        "checkpoint": None, "status": "", "reason": "operator resumed",
        "root": root, "ttl_seconds": 0, "include_stale": False,
    }]


def test_local_ai_coord_task_sync_forwards_export_and_import_payloads(monkeypatch):
    backend = ApiBackend({"success": True, "summary": "forwarded"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    exported = mcp_server.local_ai_coord(
        action="task_sync", sync_action="export", stream_id="stream-59",
        after_seq=3, limit=12,
    )
    events = [{"seq": 4, "kind": "task.updated"}]
    imported = mcp_server.local_ai_coord(
        action="task_sync", sync_action="import", events=events
    )
    assert exported["success"] is True
    assert imported["success"] is True
    assert backend.calls == [
        ("/api/agent-state/events/delta",
         {"action": "export", "stream_id": "stream-59", "after_seq": 3,
          "limit": 12}, {"timeout": mcp_server._timeout("quick")}),
        ("/api/agent-state/events/delta",
         {"action": "import", "events": events},
         {"timeout": mcp_server._timeout("quick")}),
    ]


def test_local_ai_coord_task_sync_forwards_canonical_cursor_and_limit(monkeypatch):
    backend = ApiBackend({"success": True, "summary": "forwarded"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_sync", sync_action="export", stream_id="stream-60",
        after_seq=7, limit=12,
    )

    assert result["success"] is True
    assert backend.calls[0][1]["after_seq"] == 7


def test_local_ai_coord_task_sync_preserves_explicit_zero_cursor(monkeypatch):
    backend = ApiBackend({"success": True, "summary": "forwarded"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_sync", sync_action="export", stream_id="stream-61",
        after_seq=0, limit=12,
    )

    assert result["success"] is True
    assert backend.calls[0][1]["after_seq"] == 0


def test_local_ai_coord_task_sync_rejects_retired_fields_before_network(
    monkeypatch, tmp_path
):
    backend = _prepare_coord_api(monkeypatch)
    root = str(tmp_path.resolve())

    tool_result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {
            "action": "task_sync", "root": root, "sync_action": "import",
            "events": [{"seq": 8}], "status": "import", "record": [{"seq": 8}],
        }
    ))

    result = _mcp_coord_json(tool_result)
    assert result["success"] is False
    assert backend.calls == []


def test_local_ai_coord_task_zombie_reap_forwards_recovery_flag(monkeypatch, tmp_path):
    backend = _prepare_coord_api(monkeypatch)
    root = str(tmp_path.resolve())
    result = mcp_server.local_ai_coord(action='task_zombie_reap', root=root, task_id="expired-task")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/agent-state/tasks",
        {"action": "reap_expired", "auto_recover": True, "root": root, "task_id": "expired-task"},
        {"timeout": mcp_server._timeout("quick")},
    )]


@pytest.mark.parametrize("task_id", ["", None, True, 3])
def test_local_ai_coord_task_zombie_reap_rejects_missing_or_nonstring_identity(monkeypatch, task_id):
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action="task_zombie_reap", task_id=task_id)
    assert result["success"] is False
    assert result["terminal"] is True
    assert backend.calls == []


def test_local_ai_coord_verify_completion_forwards_task_revision(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='verify_completion', root=root, task_id="task-60", repository_revision="rev-60")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/agent-state/verification",
        {"action": "completion", "task_id": "task-60", "root": root,
         "repository_revision": "rev-60"},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_worktree_lease_forwards_root_and_branch(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    result = mcp_server.local_ai_coord(action='worktree_lease', root=root, branch="feature/coord")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [{
        "action": "worktree_lease", "root": root, "branch": "feature/coord",
    }]


def test_local_ai_coord_worktree_release_forwards_path_and_branch_policy(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    result = mcp_server.local_ai_coord(action='worktree_release', root=root, worktree_path="C:/worktrees/coord", branch="feature/coord", delete_branch=False)
    assert result["success"] is True
    calls = backend.calls
    assert calls == [{
        "action": "worktree_release", "root": root,
        "worktree_path": "C:/worktrees/coord", "delete_branch": False,
        "worktree_id": "",
        "branch": "feature/coord",
    }]


def test_local_ai_coord_curate_dataset_forwards_output_policy(monkeypatch):
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action='curate_dataset', output_path="dataset.jsonl", min_receipts=3, format="jsonl")
    assert result["success"] is True
    calls = backend.calls
    assert calls == [(
        "/api/agent-state/tasks",
        {"action": "curate_dataset", "output_path": "dataset.jsonl",
         "min_receipts": 3, "format": "jsonl"},
        {"timeout": mcp_server._timeout("quick")},
    )]


def _mcp_coord_json(tool_result):
    if isinstance(tool_result, dict):
        return tool_result
    if isinstance(tool_result, tuple):
        content = tool_result[0][0]
    else:
        assert isinstance(tool_result, list)
        content = tool_result[0]
    assert isinstance(content, mcp_types.TextContent)
    return json.loads(content.text)


def test_local_ai_coord_blackboard_update_posts_content_and_version(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    tool_result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "blackboard_update", "root": root,
         "board_id": "board-61", "section": "release", "content": "ready",
         "author": "reviewer", "expected_version": 5}
    ))
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls == [(
        "/api/agent-state/blackboard",
        {"action": "update", "board_id": "board-61", "section": "release",
         "root": root, "content": "ready", "author": "reviewer",
         "expected_version": 5},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_context_compile_posts_scope_and_budget(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    tool_result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "context_compile", "root": root,
         "task_id": "task-62", "max_tokens": 512, "paths": ["src/a.py"],
         "since_hash": "base-62", "include_diagnostics": True,
         "focus": ["route", "test"], "preload_profile": "fast"}
    ))
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls == [(
        "/api/agent-state/context",
        {"action": "compile", "task_id": "task-62", "token_budget": 512,
         "root": root, "changed_paths": ["src/a.py"], "since_hash": "base-62",
         "compact": True, "include_diagnostics": True, "clone_id": "",
         "worktree_id": "", "branch": "", "repository_id": "", "session_id": "",
         "repository_revision": "", "phase": "", "focus": ["route", "test"],
         "preload_profile": "fast"},
        {"timeout": mcp_server._timeout("context")},
    )]


def test_local_ai_coord_incident_decision_forwards_fingerprint_and_revision(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    fingerprint = {
        "error_class": "TimeoutError", "operation_class": "artifact_read",
        "signature_hash": "timeout-fingerprint-1",
    }
    state_revision = "revision-17"
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "incident_decision", "root": root,
         "fingerprint": fingerprint, "state_revision": state_revision}
    ))
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls == [{
        "action": "incident_decision", "fingerprint": fingerprint,
        "state_revision": state_revision, "root": root, "tenant": "",
    }]


def test_local_ai_coord_memory_find_forwards_query_and_scope(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "memory_find", "root": root,
         "query": "lease timeout", "scope": "task", "scope_id": "task-63",
         "task_id": "task-63", "tenant": "tenant-3"}
    ))
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls == [{
        "action": "memory_find", "record": None, "record_id": "",
        "target_scope": "", "approver": "", "key": "", "value": "",
        "query": "lease timeout", "root": root, "scope": "task",
        "scope_id": "task-63", "task_id": "task-63", "session_id": "",
        "clone_id": "", "worktree_id": "", "branch": "", "repository_id": "",
        "tenant": "tenant-3",
    }]


def test_local_ai_coord_memory_get_forwards_record_identity(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "memory_get", "root": root,
         "record_id": "memory-64", "scope": "project", "scope_id": "project-4"}
    ))
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls == [{
        "action": "memory_get", "record": None, "record_id": "memory-64",
        "target_scope": "", "approver": "", "key": "", "value": "",
        "query": "", "root": root, "scope": "project", "scope_id": "project-4",
        "task_id": "", "session_id": "", "clone_id": "", "worktree_id": "",
        "branch": "", "repository_id": "", "tenant": "",
    }]


def test_local_ai_coord_memory_record_forwards_record_and_ttl(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    record = {"finding": "bounded retry", "verified": True}
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "memory_record", "root": root,
         "record": record, "record_id": "memory-65", "ttl_seconds": 3600,
         "scope": "task", "scope_id": "task-65"}
    ))
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls == [{
        "action": "memory_record", "record": record, "record_id": "memory-65",
        "target_scope": "", "approver": "", "key": "", "value": "",
        "query": "", "root": root, "scope": "task", "scope_id": "task-65",
        "task_id": "", "session_id": "", "clone_id": "", "worktree_id": "",
        "branch": "", "repository_id": "", "tenant": "", "ttl_seconds": 3600,
    }]


def test_local_ai_coord_simulate_merge_forwards_branch_pair(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "simulate_merge", "root": root,
         "source_branch": "feature/source", "target_branch": "main"}
    ))
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls == [{
        "action": "simulate_merge", "root": root,
        "source_branch": "feature/source", "target_branch": "main",
    }]


def test_local_ai_coord_task_create_forwards_goal_and_contract(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    contract = {"objective": "verify scoped dispatch", "success_criteria": ["receipt"]}
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "task_create", "root": root,
         "task": "dispatch acceptance", "task_id": "task-66", "contract": contract,
         "max_response_tokens": 768}
    ))
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls == [{
        "action": "task_create", "task_id": "task-66", "contract": contract,
        "checkpoint": None, "status": "", "reason": "", "root": root,
        "ttl_seconds": 0, "include_stale": False, "task": "dispatch acceptance", "response_budget_tokens": 768,
    }]


def test_local_ai_coord_verify_receipt_forwards_criterion_and_pass_state(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    tool_result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "verify_receipt", "root": root,
         "receipt": {"task_id": "task-67", "criterion": "selector passed",
                     "passed": True, "evidence_id": "mock-command-evidence-67"}}
    ))
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls == [(
        "/api/agent-state/verification",
        {"action": "receipt", "receipt": {"task_id": "task-67",
         "criterion": "selector passed", "passed": True,
         "evidence_id": "mock-command-evidence-67"}, "root": root},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_context_compile_dispatch(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="context_compile", root=root, task_id="task-68"
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0][0] == "/api/agent-state/context"
    assert backend.calls[0][1]["action"] == "compile"
    assert backend.calls[0][1]["task_id"] == "task-68"


def test_local_ai_coord_context_compile_dispatch_with_task_id(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="context_compile", root=root, task_id="task-69"
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0][0] == "/api/agent-state/context"
    assert backend.calls[0][1]["action"] == "compile"
    assert backend.calls[0][1]["task_id"] == "task-69"


def test_local_ai_coord_negative_knowledge_record_dispatch(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    record = {
        "operation_class": "ValueError", "message": "bad input",
        "root_cause": "missing field",
    }
    tool_result = mcp_server.local_ai_coord(
        action="negative_knowledge_record", root=root, record=record,
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0][0] == "/api/agent-state/incidents"
    assert backend.calls[0][1]["action"] == "record"
    assert backend.calls[0][1]["operation_class"] == "ValueError"
    assert backend.calls[0][1]["root_cause"] == "missing field"


def test_local_ai_coord_negative_knowledge_find_dispatch(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_api(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="negative_knowledge_find", root=root, query="bad input"
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0][0] == "/api/agent-state/incidents"
    assert backend.calls[0][1]["action"] == "find"
    assert backend.calls[0][1]["query"] == "bad input"


def test_local_ai_coord_memory_record_dispatch(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    record = {"note": "accepted"}
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="memory_record", root=root, record=record
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0]["action"] == "memory_record"
    assert backend.calls[0]["record"] == record


def test_local_ai_coord_memory_record_dispatch_from_record_payload(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    record = {"note": "recorded"}
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="memory_record", root=root, record=record
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0]["action"] == "memory_record"
    assert backend.calls[0]["record"] == record


def test_local_ai_coord_memory_get_dispatch(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="memory_get", root=root, record_id="memory-70"
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0]["action"] == "memory_get"
    assert backend.calls[0]["record_id"] == "memory-70"


def test_local_ai_coord_memory_find_dispatch(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="memory_find", root=root, query="deadline"
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0]["action"] == "memory_find"
    assert backend.calls[0]["query"] == "deadline"


def test_local_ai_coord_memory_find_dispatch_with_query(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="memory_find", root=root, query="status receipt"
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0]["action"] == "memory_find"
    assert backend.calls[0]["query"] == "status receipt"


def test_local_ai_coord_task_create_dispatch(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="task_create", root=root, task="canonical task", task_id="canonical-task-71"
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0]["action"] == "task_create"
    assert backend.calls[0]["task"] == "canonical task"
    assert backend.calls[0]["task_id"] == "canonical-task-71"


def test_local_ai_coord_task_checkpoint_dispatch(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    checkpoint = {"phase": "verify", "revision": "r72"}
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="task_checkpoint", root=root, task_id="task-72", checkpoint=checkpoint
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0]["action"] == "task_checkpoint"
    assert backend.calls[0]["checkpoint"] == checkpoint
    assert backend.calls[0]["task_id"] == "task-72"


def test_local_ai_coord_task_complete_dispatch(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = _prepare_coord_rpc(monkeypatch)
    tool_result = mcp_server.local_ai_coord(
        action="task_complete", root=root, task_id="task-73", reason="verified"
    )
    result = _mcp_coord_json(tool_result)
    assert result["success"] is True
    assert backend.calls[0]["action"] == "task_complete"
    assert backend.calls[0]["task_id"] == "task-73"
    assert backend.calls[0]["reason"] == "verified"


def test_local_ai_coord_claim_forwards_owned_paths(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    paths = ["src/worker.py", "tests/test_worker.py"]
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(
        action="claim", root=root, paths=paths, ttl_seconds=300,
        value="bounded worker edit",
    )
    assert result["success"] is True
    assert backend.calls == [(
        "/api/leases/claim_batch",
        {"root": root, "paths": paths, "ttl_seconds": 300,
         "purpose": "bounded worker edit"},
        {},
    )]


def test_local_ai_coord_curate_dataset_forwards_policy(monkeypatch):
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(
        action="curate_dataset", output_path="accepted.jsonl", min_receipts=4,
        format="jsonl",
    )
    assert result["success"] is True
    assert backend.calls == [(
        "/api/agent-state/tasks",
        {"action": "curate_dataset", "output_path": "accepted.jsonl",
         "min_receipts": 4, "format": "jsonl"},
        {"timeout": mcp_server._timeout("quick")},
    )]


def test_local_ai_coord_renew_forwards_lease_and_ttl(monkeypatch):
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(
        action="renew", lease_id="lease-74", ttl_seconds=210,
    )
    assert result["success"] is True
    assert backend.calls == [(
        "/api/leases/renew", {"lease_id": "lease-74", "ttl_seconds": 210}, {}
    )]


@pytest.mark.parametrize("action", ["claim_batch", "lease_renew", "curate_training_dataset"])
def test_retired_coord_action_aliases_reject_without_dispatch(monkeypatch, action):
    backend = _prepare_coord_api(monkeypatch)
    result = mcp_server.local_ai_coord(action=action)
    assert result["success"] is False
    assert result["error"].startswith(f"Unknown local_ai_coord action '{action}'.")
    assert backend.calls == []


def test_local_ai_coord_schema_gap_delete_is_rejected_without_dispatch(monkeypatch):
    backend = ApiBackend({"success": True, "summary": "unexpected dispatch"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    result = mcp_server.local_ai_coord(action="delete")
    assert result["success"] is False
    assert result["error"].startswith("Unknown local_ai_coord action 'delete'.")
    assert backend.calls == []


def test_local_ai_coord_schema_gap_get_is_rejected_without_dispatch(monkeypatch):
    backend = ApiBackend({"success": True, "summary": "unexpected dispatch"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    result = mcp_server.local_ai_coord(action="get")
    assert result["success"] is False
    assert result["error"].startswith("Unknown local_ai_coord action 'get'.")
    assert backend.calls == []


def test_local_ai_coord_schema_gap_list_is_rejected_without_dispatch(monkeypatch):
    backend = ApiBackend({"success": True, "summary": "unexpected dispatch"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    result = mcp_server.local_ai_coord(action="list")
    assert result["success"] is False
    assert result["error"].startswith("Unknown local_ai_coord action 'list'.")
    assert backend.calls == []


def test_local_ai_coord_schema_gap_merge_is_rejected_without_dispatch(monkeypatch):
    backend = ApiBackend({"success": True, "summary": "unexpected dispatch"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    result = mcp_server.local_ai_coord(action="merge")
    assert result["success"] is False
    assert result["error"].startswith("Unknown local_ai_coord action 'merge'.")
    assert backend.calls == []
