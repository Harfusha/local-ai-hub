from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace

import pytest

import local_ai_hub.async_jobs as async_jobs
from local_ai_hub.async_jobs import AsyncJobManager


class _Artifacts:
    def put(self, _content, _tenant, _kind):
        return "artifact-1"


def _manager(tmp_path, executor=None):
    return AsyncJobManager(
        {"server": {"state_dir": str(tmp_path)}, "async_jobs": {"wait_max_seconds": 2}},
        scheduler=None,
        artifacts=_Artifacts(),
        executor=executor or (lambda action, payload, tenant: {"success": True, "action": action}),
    )


def _mode(name: str, *, revision: int = 1, degraded: bool = False):
    return SimpleNamespace(mode=name, revision=revision, updated_at=None, degraded=degraded, error="")


def _states(manager):
    with closing(sqlite3.connect(manager.path)) as con:
        return {str(job_id): (str(action), str(state), bool(cancel_requested)) for job_id, action, state, cancel_requested in con.execute(
            "SELECT job_id,action,state,cancel_requested FROM async_jobs"
        )}


def test_gaming_rejects_new_inference_before_database_insert(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    monkeypatch.setattr(async_jobs, "load_operational_mode", lambda _path: _mode("gaming"), raising=False)
    try:
        result = manager.submit("tenant-a", "reason", {"task": "blocked"}, dispatch_delay_seconds=30)

        assert result["success"] is False
        assert result["mode"] == "gaming"
        assert result["error"] == "hub paused: gaming mode active"
        assert result["terminal"] is True
        assert result["retryable"] is False
        assert _states(manager) == {}
    finally:
        manager.close()


def test_gaming_cancels_queued_inference_and_preserves_speculative_lint(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    monkeypatch.setattr(async_jobs, "load_operational_mode", lambda _path: _mode("active"), raising=False)
    try:
        inference = manager.submit("tenant-a", "reason", {"task": "queued"}, dispatch_delay_seconds=30)
        lint = manager.submit("tenant-a", "speculative_lint", {"task": "lint"}, dispatch_delay_seconds=30)

        manager.on_operational_mode_changed(_mode("gaming"))
        rows = _states(manager)

        assert rows[inference["job_id"]] == ("reason", "cancelled", True)
        assert rows[lint["job_id"]] == ("speculative_lint", "queued", False)
    finally:
        manager.close()


@pytest.mark.parametrize("mode_name", ["gaming", "maintenance"])
def test_mode_change_cancels_running_job_cooperatively(tmp_path, monkeypatch, mode_name):
    started = threading.Event()
    release = threading.Event()

    def executor(_action, _payload, _tenant):
        started.set()
        assert release.wait(3)
        return {"success": True, "artifact_id": "artifact-1"}

    manager = _manager(tmp_path, executor)
    monkeypatch.setattr(async_jobs, "load_operational_mode", lambda _path: _mode("active"), raising=False)
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "running"})
        assert started.wait(2)

        manager.on_operational_mode_changed(_mode(mode_name))
        row = _states(manager)[submitted["job_id"]]
        assert row == ("reason", "running", True)

        release.set()
        result = manager.wait("tenant-a", submitted["job_id"], 2)
        assert result["state"] == "cancelled"
        assert result["terminal"] is True
        assert result["cancel_requested"] is True
    finally:
        release.set()
        manager.close()


def test_submit_before_gaming_is_cancelled_at_dispatch(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    calls = []
    monkeypatch.setattr(async_jobs, "load_operational_mode", lambda _path: _mode("active"), raising=False)
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "queued"}, dispatch_delay_seconds=30)
        monkeypatch.setattr(async_jobs, "load_operational_mode", lambda _path: _mode("gaming"), raising=False)

        manager._dispatch(submitted["job_id"])

        assert _states(manager)[submitted["job_id"]] == ("reason", "cancelled", True)
        assert calls == []
    finally:
        manager.close()


@pytest.mark.parametrize(
    ("mode_name", "action"),
    (("gaming", "reason"), ("maintenance", "speculative_lint")),
)
def test_mode_change_at_executor_boundary_prevents_start(tmp_path, monkeypatch, mode_name, action):
    mode = _mode("active")
    executor_calls = []
    boundary_entered = threading.Event()
    release_boundary = threading.Event()

    def executor(actual_action, _payload, _tenant):
        executor_calls.append(actual_action)
        return {"success": True, "artifact_id": "artifact-1"}

    manager = _manager(tmp_path, executor)
    original_start = manager._invoke_executor_if_allowed

    def pause_at_boundary(job_id, actual_action, payload, tenant):
        boundary_entered.set()
        assert release_boundary.wait(2)
        return original_start(job_id, actual_action, payload, tenant)

    monkeypatch.setattr(async_jobs, "load_operational_mode", lambda _path: mode, raising=False)
    monkeypatch.setattr(manager, "_invoke_executor_if_allowed", pause_at_boundary)
    try:
        submitted = manager.submit(
            "tenant-a", action, {"task": "mode start race"}, dispatch_delay_seconds=0
        )
        manager._dispatch(submitted["job_id"])
        assert boundary_entered.wait(1)

        with manager.operational_mode_change_guard():
            mode.mode = mode_name
            mode.revision = 3
            manager.on_operational_mode_changed(mode)
        release_boundary.set()

        result = manager.wait("tenant-a", submitted["job_id"], 2)
        assert executor_calls == []
        assert result["state"] == "cancelled"
        assert result["terminal"] is True
        assert result["retryable"] is False
    finally:
        release_boundary.set()
        manager.close()
