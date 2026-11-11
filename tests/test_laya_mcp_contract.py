from __future__ import annotations

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
            "training_content": {"task_input": "summarize indexed evidence"},
        },
    }


def _http_post_via_handler(monkeypatch, tmp_path, payload):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {"enabled": False}}}
    app.recovery = None
    app.agent_tasks = SimpleNamespace(state_store=SimpleNamespace(enabled=True))
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


@pytest.mark.parametrize(
    "action, expected_diagnostic",
    [
        ("evaluate_decision", False),
        ("evaluate_context_source", False),
        ("candidate_list", True),
        ("train_export", True),
    ],
)
def test_only_laya_evaluation_operations_bypass_diagnostic_gate(action, expected_diagnostic):
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
    assert valid_body["error"] == "Laya shadow runtime is disabled"

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
