from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_surface import diagnostic_http_operation, diagnostic_mcp_operation
from local_ai_hub import http_server, mcp_server
from local_ai_hub.app import LocalAIApp


def _decision_operation() -> dict[str, object]:
    return {
        "action": "evaluate_decision",
        "task_id": "task-wire-1",
        "decision": {
            "category": "context_budget",
            "evidence_ids": ["ev-verified-1"],
            "options": ["compact"],
            "state": {"current_tokens": 1200},
            "training_content": {
                "task_input": "summarize indexed evidence",
                "model_response": "Authorization: Bearer abc.def",
                "tool_output_excerpt": "api_key=secret-value",
            },
        },
    }


def _http_post_via_handler(monkeypatch, tmp_path, payload, *, app_overrides=None):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {"enabled": False}}}
    app.recovery = None
    app.agent_tasks = SimpleNamespace(state_store=SimpleNamespace(enabled=True))
    for name, value in (app_overrides or {}).items():
        setattr(app, name, value)
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)

    class Request:
        path = "/api/agent-state/tasks"
        headers = {}

        def __init__(self):
            self._authorization_root = str(tmp_path)
            self.response = None

        def _require_authorized(self):
            return True

        def _begin_trace(self, _path):
            return None

        def _async_delivery(self, _path, _payload):
            return None

        def _read_json(self):
            return payload

        def _validate_payload(self, path, value):
            return http_server.Handler._validate_payload(path, value)

        def _agent(self):
            return "wire-test"

        def _bind_task_payload(self, value):
            if value.get("root") == self._authorization_root:
                return True
            self._send(403, {"success": False, "error": "root identity mismatch"})
            return False

        def _claim_recovery(self, *_args, **_kwargs):
            return True

        def _send(self, status, body):
            self.response = (status, body)

    request = Request()
    http_server.Handler.do_POST(request)
    return request.response


def test_mcp_curate_dataset_forwards_nested_laya_operation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)

    def post(path, payload, *, timeout):
        calls.append((path, payload, timeout))
        return {"success": True, "status": "proposal"}

    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=post))
    operation = _decision_operation()

    result = mcp_server.local_ai_coord(
        action="curate_dataset",
        root=str(tmp_path),
        laya_operation=operation,
    )

    assert result["success"] is True, result
    assert len(calls) == 1
    path, payload, _timeout = calls[0]
    assert path == "/api/agent-state/tasks"
    assert payload["action"] == "curate_dataset"
    assert payload["laya_operation"] == operation
    assert "mode" not in payload["laya_operation"]

    review_operation = {
        "action": "model_review",
        "candidate_id": "laya-candidate-1",
        "decision": "fast",
        "confidence": 0.8,
    }
    review_result = mcp_server.local_ai_coord(
        action="curate_dataset",
        root=str(tmp_path),
        laya_operation=review_operation,
    )
    assert review_result["success"] is True
    task_calls = [call for call in calls if call[0] == "/api/agent-state/tasks"]
    assert task_calls[-1][1]["laya_operation"] == review_operation

    history_operation = {
        "action": "model_review_history",
        "candidate_id": "laya-candidate-1",
    }
    history_result = mcp_server.local_ai_coord(
        action="curate_dataset",
        root=str(tmp_path),
        laya_operation=history_operation,
    )
    assert history_result["success"] is True
    task_calls = [call for call in calls if call[0] == "/api/agent-state/tasks"]
    assert task_calls[-1][1]["laya_operation"] == history_operation


@pytest.mark.parametrize("laya_action", ["model_review", "model_review_history"])
def test_laya_local_model_review_uses_existing_non_diagnostic_curation_surface(laya_action):
    assert diagnostic_mcp_operation(
        "local_ai_coord",
        {
            "action": "curate_dataset",
            "root": "C:/repo",
            "laya_operation": {"action": laya_action},
        },
    ) is False


def test_http_curate_dataset_forwards_laya_local_review_operations(monkeypatch, tmp_path):
    calls = []
    laya_candidates = SimpleNamespace(
        handle=lambda operation, **kwargs: calls.append((operation, kwargs)) or {"success": True}
    )
    operations = [
        {
            "action": "model_review",
            "candidate_id": "laya-candidate-1",
            "decision": "fast",
            "confidence": 0.8,
        },
        {
            "action": "model_review_history",
            "candidate_id": "laya-candidate-1",
        },
    ]
    for operation in operations:
        response = _http_post_via_handler(
            monkeypatch,
            tmp_path,
            {"action": "curate_dataset", "root": str(tmp_path), "laya_operation": operation},
            app_overrides={"laya_candidates": laya_candidates, "evidence": object()},
        )
        assert response == (200, {"success": True}), response
        assert calls[-1][0] == operation
        assert calls[-1][1]["root"] == str(tmp_path)
        assert diagnostic_http_operation(
            "POST",
            "/api/agent-state/tasks",
            {"action": "curate_dataset", "laya_operation": operation},
        ) is False


def test_mcp_curate_dataset_forwards_scoped_candidate_get(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)

    def post(path, payload, *, timeout):
        calls.append((path, payload, timeout))
        return {"success": True, "candidate": {"state": "bounded review input"}}

    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=post))
    operation = {"action": "get", "candidate_id": "laya-example"}

    result = mcp_server.local_ai_coord(
        action="curate_dataset",
        root=str(tmp_path),
        laya_operation=operation,
    )

    assert result["success"] is True, result
    assert len(calls) == 1
    path, payload, _timeout = calls[0]
    assert path == "/api/agent-state/tasks"
    assert payload["action"] == "curate_dataset"
    assert payload["laya_operation"] == operation


@pytest.mark.parametrize(
    "action, expected_diagnostic",
    [
        ("evaluate_decision", False),
        ("evaluate_context_source", False),
        ("model_review", False),
        ("model_review_history", False),
        ("list", False),
        ("get", False),
        ("label", False),
        ("verify", False),
        ("reject", False),
        ("delete", False),
        ("prepare_splits", False),
        ("export", False),
        ("capture", True),
        ("capture_batch", True),
        ("candidate_list", True),
        ("train_export", True),
    ],
)
def test_laya_runtime_and_scoped_curation_bypass_diagnostic_gate(action, expected_diagnostic):
    laya_operation = {"action": action}
    mcp_arguments = {"action": "curate_dataset", "laya_operation": laya_operation}
    http_payload = {"action": "curate_dataset", "laya_operation": laya_operation}

    assert diagnostic_mcp_operation("local_ai_coord", mcp_arguments) is expected_diagnostic
    assert diagnostic_http_operation("POST", "/api/agent-state/tasks", http_payload) is expected_diagnostic


def test_laya_http_wire_accepts_typed_shape_and_rejects_extra_nested_fields(monkeypatch, tmp_path):
    operation = _decision_operation()
    valid_status, valid_body = _http_post_via_handler(
        monkeypatch,
        tmp_path,
        {"action": "curate_dataset", "root": str(tmp_path), "laya_operation": operation},
    )
    assert valid_status == 503
    assert valid_body["error"] == "Laya shadow checkpoint is not configured"

    malformed = _decision_operation()
    malformed["decision"]["caller_mode"] = "advisory"
    invalid_status, invalid_body = _http_post_via_handler(
        monkeypatch,
        tmp_path,
        {"action": "curate_dataset", "root": str(tmp_path), "laya_operation": malformed},
    )
    assert invalid_status == 400
    assert invalid_body["error"] == "Laya decision input fields invalid"

    caller_mode = {**_decision_operation(), "mode": "advisory"}
    invalid_mode_status, invalid_mode_body = _http_post_via_handler(
        monkeypatch,
        tmp_path,
        {"action": "curate_dataset", "root": str(tmp_path), "laya_operation": caller_mode},
    )
    assert invalid_mode_status == 400
    assert invalid_mode_body["error"] == "Laya decision fields invalid"


def test_laya_runtime_adapter_uses_shared_scheduler_for_capacity(monkeypatch):
    from local_ai_hub import laya_runtime

    scheduler = object()
    captured = {}

    class Adapter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(laya_runtime, "LayaRuntimeAdapter", Adapter)
    monkeypatch.setattr(laya_runtime, "discover_torch_devices", lambda: ())

    app = LocalAIApp.__new__(LocalAIApp)
    app._laya_runtime_adapter_lock = threading.Lock()
    app._laya_runtime_adapter = None
    app.scheduler = scheduler

    result = app._get_laya_runtime_adapter(
        {"allow_cpu": True},
        checkpoint_path="checkpoint",
        revision="revision",
        expected_sha256={},
    )

    assert isinstance(result, Adapter)
    assert captured["capacity_manager"] is scheduler


def test_mcp_curate_dataset_forwards_runtime_status(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(
        mcp_server,
        "CLIENT",
        SimpleNamespace(post=lambda path, payload, *, timeout: calls.append((path, payload, timeout)) or {
            "success": True,
            "service_available": True,
            "model_resident": False,
        }),
    )

    operation = {"action": "runtime_status"}
    result = mcp_server.local_ai_coord(
        action="curate_dataset",
        root=str(tmp_path),
        laya_operation=operation,
    )

    assert result["success"] is True
    assert calls[0][1]["laya_operation"] == operation


def test_http_curate_dataset_returns_laya_lifecycle_status(monkeypatch, tmp_path):
    lifecycle = {
        "available": False,
        "provider_close_configured": True,
        "idle_unload_seconds": 600.0,
        "inflight": 0,
        "loading": False,
        "closing": False,
        "runtime_verification": "NOT_VERIFIED",
    }
    response = _http_post_via_handler(
        monkeypatch,
        tmp_path,
        {
            "action": "curate_dataset",
            "root": str(tmp_path),
            "laya_operation": {"action": "runtime_status"},
        },
        app_overrides={"laya_lifecycle": SimpleNamespace(status=lifecycle)},
    )

    assert response == (
        200,
        {
            "success": True,
            "service_available": True,
            "model_resident": False,
            "runtime": lifecycle,
        },
    )


def test_http_laya_runtime_status_reports_unavailable_lifecycle(monkeypatch, tmp_path):
    response = _http_post_via_handler(
        monkeypatch,
        tmp_path,
        {
            "action": "curate_dataset",
            "root": str(tmp_path),
            "laya_operation": {"action": "runtime_status"},
        },
        app_overrides={"laya_lifecycle": SimpleNamespace(status=None)},
    )

    assert response == (
        503,
        {
            "success": False,
            "error": "Laya lifecycle status is unavailable",
            "terminal": True,
            "retryable": False,
        },
    )


def test_laya_runtime_status_does_not_require_detailed_diagnostics():
    operation = {"action": "runtime_status"}

    assert diagnostic_mcp_operation(
        "local_ai_coord", {"action": "curate_dataset", "laya_operation": operation}
    ) is False
    assert diagnostic_http_operation(
        "POST", "/api/agent-state/tasks", {"action": "curate_dataset", "laya_operation": operation}
    ) is False
