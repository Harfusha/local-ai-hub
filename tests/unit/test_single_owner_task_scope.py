"""Task repository scope replaces tenancy without weakening lifecycle guards."""

from contextlib import closing
import json
from types import SimpleNamespace
import sqlite3

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore, _task_scope_root
from local_ai_hub import http_server


@pytest.mark.parametrize("method,arguments", [
    ("get_active_task", {}),
    ("reap_expired_heartbeats", {}),
    ("recover_zombie_tasks", {}),
    ("curate_training_dataset", {"output_path": "dataset.jsonl"}),
])
@pytest.mark.parametrize("value", [None, "", False, "former-owner"])
def test_retired_scope_arguments_reject_before_state_access(method, arguments, value):
    store = TaskStore.__new__(TaskStore)
    with pytest.raises(TypeError, match="tenant"):
        getattr(store, method)(**arguments, tenant=value)


def test_create_pins_root_without_transport_identity(tmp_path):
    store = TaskStore(AgentStateStore(tmp_path / "state.sqlite3"))
    task = store.create(
        GoalContract(goal="Preserve root scope"), ScopeContext(repository_id="logical-repository", session_id="chat-one"),
        task_id="task-one", repo_root=str(tmp_path),
    )
    assert task.checkpoint.state_data["_agent_task_scope"] == {"version": 2, "repo_root": str(tmp_path.resolve())}
    assert _task_scope_root(task) == str(tmp_path.resolve())
    assert task.context.session_id == "chat-one"
    assert http_server.Handler._task_matches_request(task, str(tmp_path))


@pytest.mark.parametrize("value", [None, False, "former-owner"])
def test_retired_metadata_never_becomes_an_owner_constant(tmp_path, value):
    task = SimpleNamespace(checkpoint=SimpleNamespace(state_data={"_agent_task_scope": {
        "version": 2, "repo_root": str(tmp_path), "tenant_key": value,
    }}))
    with pytest.raises(RuntimeError, match="offline conversion"):
        _task_scope_root(task)


def test_retired_checkpoint_blocks_startup_without_rewriting_projection(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    store = TaskStore(AgentStateStore(db_path))
    task = store.create(GoalContract(goal="Preserve saved scope"), ScopeContext(), task_id="task-one", repo_root=str(tmp_path))
    with closing(sqlite3.connect(db_path)) as con:
        checkpoint = json.loads(con.execute("SELECT checkpoint FROM agent_tasks_projection WHERE task_id = ?", (task.task_id,)).fetchone()[0])
        checkpoint["state_data"]["_agent_task_scope"] = {"version": 1, "repo_root": str(tmp_path), "tenant_key": "preserve-old-key"}
        original = json.dumps(checkpoint)
        con.execute("UPDATE agent_tasks_projection SET checkpoint = ? WHERE task_id = ?", (original, task.task_id))
        con.commit()
    with pytest.raises(RuntimeError, match="offline conversion"):
        TaskStore(AgentStateStore(db_path))
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute("SELECT checkpoint FROM agent_tasks_projection WHERE task_id = ?", (task.task_id,)).fetchone()[0] == original


@pytest.mark.parametrize("timestamp", [True, "123", float("nan"), float("inf")])
def test_reaper_rejects_invalid_time_before_state_access(timestamp):
    with pytest.raises(ValueError, match="finite timestamp"):
        TaskStore.__new__(TaskStore).reap_expired_heartbeats(now=timestamp)


@pytest.mark.parametrize("format", ["JSON", "xml", None, False])
def test_dataset_format_has_no_implicit_fallback(format):
    with pytest.raises(ValueError, match="format"):
        TaskStore.__new__(TaskStore).curate_training_dataset("data", format=format)


def test_watchdog_root_inventory_is_expired_only_and_cursor_bounded(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    store = TaskStore(AgentStateStore(db_path))
    roots = []
    for name in ("a", "b", "c"):
        root = tmp_path / name
        root.mkdir()
        roots.append(str(root.resolve()))
        store.create(GoalContract(goal="Scoped watchdog"), ScopeContext(), task_id=name, repo_root=str(root))
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("UPDATE agent_tasks_projection SET heartbeat_expires_at = 10")
        con.execute("UPDATE agent_tasks_projection SET heartbeat_expires_at = 30 WHERE task_id = 'c'")
        con.commit()
    assert store._expired_repository_roots(now=20, limit=1) == roots[:1]
    assert store._expired_repository_roots(now=20, limit=1, after_root=roots[0]) == roots[1:2]
    assert store._expired_repository_roots(now=20, after_root=roots[1]) == []
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("UPDATE agent_tasks_projection SET status = 'completed' WHERE task_id = 'b'")
        con.commit()
    assert store._expired_repository_roots(now=20) == roots[:1]


@pytest.mark.parametrize("arguments", [
    {"now": True}, {"now": float("nan")}, {"now": 1, "limit": True},
    {"now": 1, "limit": 0}, {"now": 1, "limit": 65},
    {"now": 1, "after_root": None}, {"now": 1, "after_root": " bad "},
])
def test_watchdog_inventory_rejects_invalid_bounds_before_state_access(arguments):
    with pytest.raises(ValueError):
        TaskStore.__new__(TaskStore)._expired_repository_roots(**arguments)


@pytest.mark.parametrize("deadline", [True, "123", float("nan"), float("inf")])
def test_reaper_rejects_invalid_deadline_before_state_access(deadline):
    with pytest.raises(ValueError, match="deadline"):
        TaskStore.__new__(TaskStore).reap_expired_heartbeats(_deadline_monotonic=deadline)
