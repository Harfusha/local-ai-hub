"""Single-owner task maintenance retains repository and lifecycle fences."""

import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from local_ai_hub import app as app_module, operational_mode
from local_ai_hub.app import LocalAIApp
from local_ai_hub.services import LocalAIServices


def watchdog(tmp_path, roots):
    instance = LocalAIApp.__new__(LocalAIApp)
    instance.config = {"security": {"api_token": "protected", "allowed_roots": [str(tmp_path)]}}
    instance._shutdown = threading.Event()
    instance.logger = logging.getLogger(__name__)
    tasks = SimpleNamespace(
        _expired_repository_roots=Mock(return_value=roots),
        reap_expired_heartbeats=Mock(return_value=["expired-task"]),
    )
    instance.agent_state = SimpleNamespace(enabled=True, tasks=tasks)
    return instance, tasks


def test_watchdog_authorizes_each_repository_and_advances_denied_cursor(tmp_path):
    allowed = tmp_path / "repository"
    allowed.mkdir()
    denied = str(tmp_path.parent)
    instance, tasks = watchdog(tmp_path, [str(allowed), denied])
    assert instance._reap_expired_task_scopes() == ["expired-task"]
    call = tasks.reap_expired_heartbeats.call_args.kwargs
    assert call["repo_root"] == str(allowed.resolve())
    assert call["_cancel_event"] is instance._shutdown
    assert instance._task_reap_after_root == denied
    assert tasks.reap_expired_heartbeats.call_count == 1


def test_watchdog_wraps_empty_cursor_once_and_isolates_root_failures(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    instance, tasks = watchdog(tmp_path, [])
    instance._task_reap_after_root = str(second)
    tasks._expired_repository_roots.side_effect = [[], [str(first), str(second)]]
    tasks.reap_expired_heartbeats.side_effect = [RuntimeError("busy"), ["second-task"]]
    assert instance._reap_expired_task_scopes() == ["second-task"]
    assert tasks._expired_repository_roots.call_count == 2
    assert tasks._expired_repository_roots.call_args_list[0].kwargs["after_root"] == str(second)
    assert "after_root" not in tasks._expired_repository_roots.call_args_list[1].kwargs


@pytest.mark.parametrize("shutdown", [False, True])
def test_watchdog_stops_before_mutation_on_deadline_or_shutdown(tmp_path, monkeypatch, shutdown):
    instance, tasks = watchdog(tmp_path, [str(tmp_path)])
    if shutdown:
        instance._shutdown.set()
    clock = iter([10.0, 12.0])
    real_monotonic = time.monotonic
    # Patch only this module's clock; patching the shared stdlib time module
    # also changes unrelated scheduler threads in the full test suite.
    monkeypatch.setattr(app_module, "time", SimpleNamespace(
        time=app_module.time.time, monotonic=lambda: next(clock)
    ))
    assert time.monotonic is real_monotonic
    assert instance._reap_expired_task_scopes() == []
    tasks.reap_expired_heartbeats.assert_not_called()


def warmup(tmp_path, monkeypatch):
    task = SimpleNamespace(
        task_id="task-one", updated_at=100.0, status="active",
        contract=SimpleNamespace(goal="Keep repository scope", acceptance_criteria=["scope"]),
        context=SimpleNamespace(session_id="chat-one"),
        checkpoint=SimpleNamespace(state_data={"_agent_task_scope": {
            "version": 2, "repo_root": str(tmp_path.resolve()),
        }}),
    )
    instance = LocalAIServices.__new__(LocalAIServices)
    instance.config = {"server": {"state_dir": str(tmp_path / "state")},
                       "security": {"api_token": "protected", "allowed_roots": [str(tmp_path)]}}
    instance.task_store = SimpleNamespace(get=Mock(return_value=task))
    instance._context_warmup = SimpleNamespace(submit=Mock(return_value=True))
    instance.adaptive_context_pack = Mock()
    mode = SimpleNamespace(mode="active", degraded=False)
    monkeypatch.setattr(operational_mode, "load_operational_mode", lambda *args: mode)
    return instance, task, mode


def test_warmup_preserves_task_and_actual_session_without_tenant(tmp_path, monkeypatch):
    instance, task, _ = warmup(tmp_path, monkeypatch)
    assert instance.schedule_task_context_warmup(task, root=str(tmp_path))
    instance._context_warmup.submit.call_args.args[1]()
    request = instance.adaptive_context_pack.call_args.args[0]
    assert request.root == str(tmp_path.resolve())
    assert request.task_id == task.task_id
    assert request.session_id == "chat-one"
    assert "tenant" not in vars(request)
    with pytest.raises(TypeError, match="tenant"):
        instance.schedule_task_context_warmup(task, root=str(tmp_path), tenant=None)


@pytest.mark.parametrize("change", ["revision", "root", "terminal", "gaming", "degraded", "authorization"])
def test_warmup_rechecks_fences_when_callback_runs(tmp_path, monkeypatch, change):
    instance, task, mode = warmup(tmp_path, monkeypatch)
    assert instance.schedule_task_context_warmup(task, root=str(tmp_path))
    if change == "revision":
        task.updated_at += 1
    elif change == "root":
        task.checkpoint.state_data["_agent_task_scope"]["repo_root"] = str(tmp_path.parent)
    elif change == "terminal":
        task.status = "completed"
    elif change == "gaming":
        mode.mode = "gaming"
    elif change == "degraded":
        mode.degraded = True
    else:
        instance.config["security"]["allowed_roots"] = []
    instance._context_warmup.submit.call_args.args[1]()
    instance.adaptive_context_pack.assert_not_called()
