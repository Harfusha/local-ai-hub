import json
import threading
from types import SimpleNamespace
import pytest

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.services import LocalAIServices
from local_ai_hub import mcp_server
from local_ai_hub.token_accounting import json_tokens


@pytest.fixture(autouse=True)
def qualified_batch_actions(monkeypatch):
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "hardware_profile", "balanced")
    monkeypatch.setattr(mcp_server.FEATURES, "local_semantic_analysis", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)


def service_with_artifacts(tmp_path):
    service = object.__new__(LocalAIServices)
    service.config = {"debug_traces": {"enabled": False}}
    service.artifacts = ArtifactStore(tmp_path)
    service.scheduler = SimpleNamespace(status=lambda: {"active_model": "test"})
    service.router = SimpleNamespace(classify=lambda *_: {"model": "test"})
    def delegate(item):
        if item["id"] == "bad":
            return {"success": False, "error": "test failure", "raw_model_output": "secret"}
        return {"success": True, "text": "answer " * 250,
                "admission": {"vram_available_bytes": 123456},
                "execution_profile": {"num_ctx": 16384}, "latency": {"service_ms": 17}}
    service.delegate = delegate
    return service


def test_large_partial_batch_has_recoverable_safe_artifact(tmp_path):
    service = service_with_artifacts(tmp_path)
    result = service.batch_delegate({"tasks": [{"id": "ok", "task": "a"}, {"id": "bad", "task": "b"}],
                                     "response_budget_tokens": 128})
    assert result["success"] is False
    artifact_id = result["output_artifact_id"]
    artifact = service.artifacts.get(artifact_id, max_chars=50000)
    recovered = json.loads(artifact["text"])
    assert [(item["id"], item["success"]) for item in recovered["results"]] == [("ok", True), ("bad", False)]
    assert recovered["results"][0]["text"] == "answer " * 250
    assert recovered["results"][1]["error"] == "test failure"
    assert "secret" not in artifact["text"]
    assert "vram_available_bytes" not in artifact["text"]
    assert "execution_profile" not in artifact["text"]
    assert '"latency"' not in artifact["text"]


def test_small_batch_does_not_create_unneeded_artifact(tmp_path):
    service = service_with_artifacts(tmp_path)
    service.delegate = lambda item: {"success": True, "text": "ok"}
    result = service.batch_delegate({"tasks": [{"task": "a"}], "response_budget_tokens": 4096})
    assert result["success"] is True
    assert "output_artifact_id" not in result


def test_low_budget_batch_exposes_recovery_id_through_mcp_wire(tmp_path, monkeypatch):
    service = service_with_artifacts(tmp_path)
    def post(path, payload, **kwargs):
        if path == "/api/delegate/batch":
            return {**service.batch_delegate(payload), "request_id": "req_0123456789ab"}
        if path == "/api/artifact/get":
            return service.artifacts.get(payload["artifact_id"], offset=payload.get("offset", 0),
                                         max_chars=payload.get("max_chars", 6000))
        return {"success": True}
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    args = {"action": "batch", "max_response_tokens": 128,
            "tasks": [{"id": "ok", "task": "a"}, {"id": "bad", "task": "b"}]}
    response = mcp_server.local_ai_task(**args)
    content, structured = mcp_server._mcp_budget_payload("local_ai_task", args, response)
    artifact_id = structured["output_artifact_id"]
    assert structured["outcome_unknown"] is True
    assert structured["request_id"] == "req_0123456789ab"
    assert json.loads(content[0].text)["output_artifact_id"] == artifact_id
    wire = {"content": [item.model_dump(mode="json", exclude_none=True) for item in content],
            "structuredContent": structured, "isError": False}
    assert json_tokens(wire) <= 128
    recovered = json.loads(service.artifacts.get(artifact_id, max_chars=50000)["text"])
    assert [(item["id"], item["success"]) for item in recovered["results"]] == [("ok", True), ("bad", False)]
    page = mcp_server.local_ai_artifact(action="get", artifact_id=artifact_id, max_response_tokens=4096)
    assert json.loads(page["text"]) == recovered


def test_artifact_failure_does_not_replace_real_batch_result(tmp_path):
    service = service_with_artifacts(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("storage unavailable")
    service.artifacts.put_json = fail
    result = service.batch_delegate({"tasks": [{"id": "ok", "task": "a"}],
                                     "response_budget_tokens": 128})
    assert result["success"] is True
    assert result["results"][0]["id"] == "ok"
    assert result["output_artifact_unavailable"] is True
    assert "output_artifact_id" not in result


def test_recovery_keeps_cancelled_and_unsent_item_identity(tmp_path):
    service = service_with_artifacts(tmp_path)
    cancel = threading.Event()
    def first(item, *, cancel_event=None):
        cancel.set()
        return {"success": True, "text": "answer " * 250}
    service.delegate = first
    result = service.batch_delegate({"tasks": [{"id": "done", "task": "a"}, {"id": "unsent", "task": "b"}],
                                     "response_budget_tokens": 128}, cancel_event=cancel)
    recovered = json.loads(service.artifacts.get(result["output_artifact_id"], max_chars=50000)["text"])
    assert recovered["cancelled"] is True
    assert recovered["results"][0]["id"] == "done"
    assert recovered["results"][1]["id"] == "unsent"
    assert recovered["results"][1]["request_not_sent"] is True
