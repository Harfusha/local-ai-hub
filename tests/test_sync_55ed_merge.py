"""T19 behaviors retained against the current master operation registry."""
from __future__ import annotations

from types import SimpleNamespace
from threading import Lock
import time

import pytest

from local_ai_hub import mcp_server as server
from local_ai_hub.features import FeatureSet
from local_ai_hub.operation_contracts import (
    MAX_EVENT_SEQUENCE, operation_parameters_schema, validate_operation_arguments,
)
from local_ai_hub.repo_tools import RepositoryTools


def test_external_codegraph_data_stays_ignored(tmp_path):
    tools = RepositoryTools({})
    assert ".codegraphcontext" in tools.ignore_dirs
    assert not hasattr(FeatureSet({}), "codegraph")


def test_pipeline_keeps_duplicate_actions_and_failure_state(tmp_path, monkeypatch):
    calls = []

    def post(endpoint, payload, **kwargs):
        calls.append(endpoint)
        if endpoint == "/api/evidence/verify":
            return {"success": False, "terminal": True, "retryable": False, "error": "failed", "cancel": {"requested": False}}
        return {"success": True, "affected": payload["paths"]}

    monkeypatch.setattr(server, "CLIENT", SimpleNamespace(post=post))
    monkeypatch.setattr(server, "FEATURES", FeatureSet({}))
    result = server._local_ai_repo_impl(action="pipeline", root=str(tmp_path), steps=[
        {"action": "affected_tests", "path": "a.py"},
        {"action": "verify", "evidence": [{"id": "E-test"}]},
        {"action": "affected_tests", "path": "b.py"},
    ])
    assert result["success"] is False
    assert result["steps_total"] == result["steps_attempted"] == result["steps_completed"] == 3
    assert result["steps_failed"] == 1
    assert [step["index"] for step in result["step_results"]] == [0, 1, 2]
    assert result["step_results"][0]["result"]["affected"] == ["a.py"]
    assert result["step_results"][2]["result"]["affected"] == ["b.py"]
    assert result["step_results"][1]["result"]["cancel"] == {"requested": False}


@pytest.mark.parametrize("step", [{"action": "pipeline"}, {"action": "profile", "unknown": True}, {"action": "context", "max_tokens": float("nan")}])
def test_pipeline_rejects_bad_step_before_backend(step, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("malformed step reached backend")
    monkeypatch.setattr(server, "CLIENT", SimpleNamespace(post=forbidden))
    result = server._local_ai_repo_impl(action="pipeline", root=str(tmp_path), steps=[step])
    assert result["success"] is False
    assert result["steps_failed"] == 1


def test_pubsub_sequence_and_timestamp_are_distinct_canonical_filters(monkeypatch, tmp_path):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    calls = []
    monkeypatch.setattr(server, "CLIENT", SimpleNamespace(coord=lambda **kwargs: calls.append(kwargs) or {"success": True}))
    monkeypatch.setattr(server, "FEATURES", FeatureSet({}))
    monkeypatch.setattr(server, "load_operational_mode", lambda _state_dir: OperationalModeSnapshot("active", 1, None))
    monkeypatch.setattr(server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(server, "_record_adoption", lambda *_args, **_kwargs: None)
    result = server.local_ai_coord(action="pubsub_poll", root=str(tmp_path), after_seq=17, after_ts=3.5)
    assert result["success"] is True
    assert calls[0]["after_seq"] == 17
    assert calls[0]["since_timestamp"] == 3.5
    retired = server.local_ai_coord(action="pubsub_poll", root=str(tmp_path), expected_version=3)
    assert retired["terminal"] is True
    for value in (-1, True, MAX_EVENT_SEQUENCE + 1):
        result = server.local_ai_coord(action="pubsub_poll", root=str(tmp_path), after_seq=value)
        assert result["terminal"] is True
    assert len(calls) == 1


def test_registry_preserves_nullable_and_phase_bounds():
    schema = operation_parameters_schema("local_ai_repo")
    assert schema["properties"]["steps"]["items"]["additionalProperties"] is False
    assert validate_operation_arguments("local_ai_repo", "context", {"phase": "invalid"})
    assert validate_operation_arguments("local_ai_repo", "context", {"max_tokens": True})
    assert validate_operation_arguments("local_ai_repo", "context", {"max_tokens": 100001})


def test_full_and_agent_status_skip_light_request(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "CLIENT", SimpleNamespace(
        get=lambda path: calls.append(path) or {"success": True, "hub_online": True, "runtime_stats": {}},
        status=lambda **kwargs: calls.append(kwargs["detail"]) or {"success": True, "active_tasks": []},
    ))
    server.local_ai_status(detail="full")
    assert calls == ["/api/status?scope=process", "/api/capabilities"]
    calls.clear()
    server.local_ai_status(detail="agent_state")
    assert calls == ["agent_state"]


@pytest.mark.parametrize("actions, ceiling", [(["profile"] * 8, 4), (["preprocess", "profile", "preprocess"], 1)])
def test_pipeline_parallel_ceiling_and_mutation_serialization(actions, ceiling, tmp_path, monkeypatch):
    lock = Lock()
    active = peak = 0
    def post(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.015)
        with lock:
            active -= 1
        return {"success": True}
    monkeypatch.setattr(server, "CLIENT", SimpleNamespace(post=post))
    result = server._local_ai_repo_impl(action="pipeline", root=str(tmp_path), steps=[{"action": action} for action in actions])
    assert result["success"] is True
    assert peak <= ceiling
    assert peak > 1 if ceiling == 4 else peak == 1
