"""Opt-in host continuation must fail open on uncertainty and not loop."""
from unittest.mock import MagicMock

import pytest

from local_ai_hub import client
from local_ai_hub.repo_plan.host_hooks import _verified_execution_stop


def _fixture(tmp_path, monkeypatch):
    transport = MagicMock()
    transport._online.return_value = True
    task = {
        "task_id": "task_1", "status": "active", "stale": False, "repo_root": str(tmp_path),
        "context": {"session_id": "session_1"},
        "contract": {"slo_profile": {"verified_execution": {"host_continuation": True}}},
        "checkpoint": {"blockers": []},
    }
    execution = {
        "checkpoint_blocker_count": 0,
        "next_obligation": {"criterion": "untrusted text that must not enter the host prompt"},
        "ready_for_completion_attempt": False,
    }
    transport.post.side_effect = [
        {"success": True, "tasks": [task]},
        {"success": True, "completion": {"complete": False, "execution": execution}},
    ]
    monkeypatch.setattr(client, "HubClient", lambda **kwargs: transport)
    payload = {"session_id": "session_1", "stop_hook_active": False}
    return transport, task, execution, payload


def test_verified_execution_host_stop_continues_once_for_exact_session(tmp_path, monkeypatch):
    transport, _, _, payload = _fixture(tmp_path, monkeypatch)
    decision = _verified_execution_stop(tmp_path, payload)
    assert decision["decision"] == "block"
    assert "untrusted text" not in decision["reason"]
    assert transport.post.call_count == 2
    assert _verified_execution_stop(tmp_path, {**payload, "stop_hook_active": True}) == {}
    assert transport.post.call_count == 2
    transport.close.assert_called_once()


@pytest.mark.parametrize("case", ["other_session", "opt_out", "blocked", "scope", "stagnation", "offline", "background"])
def test_verified_execution_host_stop_does_not_prevent_exit(tmp_path, monkeypatch, case):
    transport, task, execution, payload = _fixture(tmp_path, monkeypatch)
    if case == "other_session":
        task["context"]["session_id"] = "different"
    elif case == "opt_out":
        task["contract"]["slo_profile"]["verified_execution"]["host_continuation"] = False
    elif case == "blocked":
        task["checkpoint"]["blockers"] = ["needs operator"]
    elif case == "scope":
        execution["scope_check"] = {"complete": False}
    elif case == "stagnation":
        execution["progress"] = {"status": "no_recent_verified_evidence"}
    elif case == "offline":
        transport._online.return_value = False
    elif case == "background":
        payload["background_tasks"] = [{"id": "running"}]
    assert _verified_execution_stop(tmp_path, payload) == {}
