from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

from tools.release_check import run_live_smoke


def _status(*, ollama_online=True, preprocessing_timeout=False):
    dependency_status = {}
    if preprocessing_timeout:
        dependency_status["preprocessing.status"] = {
            "degraded": True,
            "reason": "probe_timeout",
        }
    return {
        "success": not preprocessing_timeout,
        "degraded": preprocessing_timeout,
        "hub_online": True,
        "ollama_online": ollama_online,
        "active_model": "qwen2.5-coder:3b",
        "scheduler": {"active_model": "qwen2.5-coder:3b"},
        "models": {
            "fast_code": "qwen2.5-coder:3b",
            "general": "qwen2.5-coder:3b",
            "heavy_code": "qwen3.5:9b",
            "reasoning": "qwen3.5:9b",
            "vision": "qwen3.5:9b",
        },
        "dependency_status": dependency_status,
    }


class HubClientDouble:
    status_payload = _status()
    transcription_payload = {
        "success": True,
        "engine": "whisper_cli",
        "text": "recognized speech",
    }
    calls: list[tuple[str, dict]] = []
    get_calls: list[str] = []
    models_payload = {
        "object": "list",
        "data": [
            {"id": "qwen2.5-coder:3b", "object": "model", "owned_by": "ollama"},
            {"id": "qwen3.5:9b", "object": "model", "owned_by": "ollama"},
        ],
    }
    async_submit_payload = {"success": True, "job_id": "job-test"}
    async_wait_payload = {"success": True, "job_id": "job-test", "state": "done", "terminal": True}
    async_result_payload = {
        "success": True, "job_id": "job-test", "state": "done", "terminal": True,
        "artifact_id": "artifact-test",
        "result": {"text": "ASYNC_READY", "route": {"model": "qwen3.5:9b"}},
    }
    reason_payload = {
        "success": True, "text": "READY", "model": "qwen3.5:9b",
        "route": {"model": "qwen3.5:9b"},
    }

    def __init__(self, **_kwargs):
        self.calls = type(self).calls

    def get(self, path, **_kwargs):
        self.get_calls.append(path)
        if path == "/health":
            return {"success": True, "hub_online": True, "version": "test"}
        if path == "/api/models":
            return deepcopy(type(self).models_payload)
        if path == "/api/hardware/gpu":
            return {"available": True, "backend": "test"}
        raise AssertionError(f"unexpected GET {path}")

    def status(self, *, detail):
        assert detail == "brief"
        return deepcopy(type(self).status_payload)

    def post(self, path, payload, **_kwargs):
        self.calls.append((path, deepcopy(payload)))
        if path == "/api/reason":
            return deepcopy(type(self).reason_payload)
        if path == "/api/benchmark/run":
            return {"success": True, "model": payload["model"]}
        if path == "/api/task/vision":
            return {"success": True, "response": "A simple image."}
        if path == "/api/task/transcribe":
            return deepcopy(type(self).transcription_payload)
        if path == "/api/async-jobs":
            if payload["action"] == "submit":
                return deepcopy(type(self).async_submit_payload)
            if payload["action"] == "wait":
                return deepcopy(type(self).async_wait_payload)
            if payload["action"] == "result":
                return deepcopy(type(self).async_result_payload)
        raise AssertionError(f"unexpected POST {path}")

    def coord(self, action, **_kwargs):
        if action == "memory_record":
            return {"success": True, "record": {"record_id": "record-test"}}
        if action == "memory_get":
            return {"success": True, "record": {"record_id": "record-test"}}
        if action == "memory_delete":
            return {"success": True}
        raise AssertionError(f"unexpected coordination action {action}")


@pytest.fixture
def smoke(monkeypatch):
    from local_ai_hub import client as client_module

    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(client_module, "HubClient", HubClientDouble)
    monkeypatch.setattr(HubClientDouble, "status_payload", _status())
    monkeypatch.setattr(
        HubClientDouble,
        "transcription_payload",
        {"success": True, "engine": "whisper_cli", "text": "recognized speech"},
    )
    monkeypatch.setattr(HubClientDouble, "calls", [])
    monkeypatch.setattr(HubClientDouble, "get_calls", [])
    monkeypatch.setattr(HubClientDouble, "models_payload", deepcopy(HubClientDouble.models_payload))
    monkeypatch.setattr(HubClientDouble, "async_submit_payload", {"success": True, "job_id": "job-test"})
    monkeypatch.setattr(
        HubClientDouble, "async_wait_payload",
        {"success": True, "job_id": "job-test", "state": "done", "terminal": True},
    )
    monkeypatch.setattr(
        HubClientDouble, "async_result_payload",
        {
            "success": True, "job_id": "job-test", "state": "done", "terminal": True,
            "artifact_id": "artifact-test",
            "result": {"text": "ASYNC_READY", "route": {"model": "qwen3.5:9b"}},
        },
    )
    monkeypatch.setattr(
        HubClientDouble, "reason_payload",
        {
            "success": True, "text": "READY", "model": "qwen3.5:9b",
            "route": {"model": "qwen3.5:9b"},
        },
    )

    def run(tmp_path: Path):
        return run_live_smoke(tmp_path)

    return run


def _checks(result):
    return {check["name"]: check for check in result["checks"]}


def test_live_smoke_uses_runtime_reason_routing_and_keeps_benchmark_model(smoke, tmp_path):
    result = smoke(tmp_path)
    checks = _checks(result)
    requests = HubClientDouble.calls

    reason = next(payload for path, payload in requests if path == "/api/reason")
    async_submit = next(
        payload for path, payload in requests
        if path == "/api/async-jobs" and payload["action"] == "submit"
    )
    benchmark = next(payload for path, payload in requests if path == "/api/benchmark/run")
    post_order = [path for path, _payload in requests]

    assert result["success"] is True
    assert "model" not in reason
    assert "model" not in async_submit
    assert checks["live-model"]["ok"] is True
    assert checks["live-model"]["status"] == "verified"
    assert checks["live-model"]["expected_response"] == "READY"
    assert checks["live-async-job"]["ok"] is True
    assert checks["live-async-job"]["status"] == "verified"
    assert benchmark["model"] == "qwen2.5-coder:3b"
    assert checks["live-hardware-benchmark"]["response_quality"] == "not_verified"
    assert HubClientDouble.get_calls.count("/api/models") == 1
    assert HubClientDouble.get_calls.index("/api/models") < HubClientDouble.get_calls.index("/health")
    assert post_order.index("/api/reason") < post_order.index("/api/async-jobs")
    assert post_order.index("/api/async-jobs") < post_order.index("/api/benchmark/run")
    assert post_order.index("/api/async-jobs") < post_order.index("/api/task/vision")
    assert post_order.index("/api/async-jobs") < post_order.index("/api/task/transcribe")


def test_live_smoke_rejects_wrong_exact_response(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(
        HubClientDouble, "reason_payload",
        {
            "success": True, "text": "WRONG", "model": "qwen3.5:9b",
            "route": {"model": "qwen3.5:9b"},
        },
    )

    result = smoke(tmp_path)
    model_check = _checks(result)["live-model"]

    assert result["success"] is False
    assert model_check["ok"] is False
    assert model_check["status"] == "failed"
    assert model_check["classification"] == "response_mismatch"


def test_live_smoke_skips_preprocessing_only_models(smoke, tmp_path, monkeypatch):
    status = _status()
    status["active_model"] = None
    status["scheduler"]["active_model"] = None
    status["models"].update({
        "fast_code": "qwen2.5-coder:1.5b",
        "general": "qwen2.5-coder:1.5b",
        "heavy_code": "qwen2.5-coder:1.5b",
        "reasoning": "qwen2.5-coder:1.5b",
    })
    monkeypatch.setattr(HubClientDouble, "status_payload", status)
    monkeypatch.setattr(HubClientDouble, "models_payload", {
        "object": "list", "data": [{"id": "qwen2.5-coder:1.5b"}],
    })

    result = smoke(tmp_path)
    checks = _checks(result)
    inference_paths = {
        path for path, _payload in HubClientDouble.calls
        if path in {"/api/reason", "/api/async-jobs", "/api/benchmark/run"}
    }

    assert result["success"] is False
    assert checks["live-model"]["status"] == "not_verified"
    assert checks["live-model"]["classification"] == "foreground_model_not_configured"
    assert checks["live-hardware-benchmark"]["status"] == "not_verified"
    assert inference_paths == set()


@pytest.mark.parametrize(
    ("actual_model", "classification"),
    [
        ("qwen2.5-coder:7b", "model_route_mismatch"),
        ("qwen2.5-coder:1.5b", "preprocessing_model_routed"),
    ],
)
def test_live_smoke_rejects_wrong_reported_reason_route(smoke, tmp_path, monkeypatch, actual_model, classification):
    monkeypatch.setattr(
        HubClientDouble, "reason_payload",
        {
            "success": True, "text": "READY", "model": actual_model,
            "route": {"model": actual_model},
        },
    )

    result = smoke(tmp_path)
    model_check = _checks(result)["live-model"]

    assert result["success"] is False
    assert model_check["ok"] is False
    assert model_check["classification"] == classification


def test_live_smoke_does_not_infer_unreported_reason_route(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(
        HubClientDouble, "reason_payload",
        {"success": True, "text": "READY", "model": "qwen3.5:9b"},
    )

    result = smoke(tmp_path)
    model_check = _checks(result)["live-model"]

    assert result["success"] is False
    assert model_check["status"] == "not_verified"
    assert model_check["classification"] == "model_route_unreported"


def test_live_smoke_rejects_async_result_without_terminal_proof(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(
        HubClientDouble, "async_wait_payload",
        {"success": True, "job_id": "job-test", "state": "running", "terminal": False},
    )

    result = smoke(tmp_path)
    async_check = _checks(result)["live-async-job"]
    async_requests = [payload for path, payload in HubClientDouble.calls if path == "/api/async-jobs"]

    assert result["success"] is False
    assert async_check["ok"] is False
    assert async_check["status"] == "not_verified"
    assert async_check["classification"] == "async_not_terminal"
    assert [payload["action"] for payload in async_requests] == ["submit", "wait"]


def test_live_smoke_rejects_async_artifact_without_exact_result(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(
        HubClientDouble, "async_result_payload",
        {
            "success": True, "job_id": "job-test", "state": "done", "terminal": True,
            "artifact_id": "artifact-only",
        },
    )

    result = smoke(tmp_path)
    async_check = _checks(result)["live-async-job"]

    assert result["success"] is False
    assert async_check["ok"] is False
    assert async_check["status"] == "not_verified"


def test_live_smoke_rejects_async_result_from_wrong_model(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(
        HubClientDouble, "async_result_payload",
        {
            "success": True, "job_id": "job-test", "state": "done", "terminal": True,
            "artifact_id": "artifact-test",
            "result": {
                "text": "ASYNC_READY", "route": {"model": "qwen2.5-coder:7b"},
            },
        },
    )

    result = smoke(tmp_path)
    async_check = _checks(result)["live-async-job"]

    assert result["success"] is False
    assert async_check["ok"] is False
    assert async_check["status"] == "failed"
    assert async_check["classification"] == "model_route_mismatch"


def test_live_smoke_does_not_guess_when_model_inventory_shape_is_unknown(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(HubClientDouble, "models_payload", {"models": ["qwen3.5:9b"]})

    result = smoke(tmp_path)
    checks = _checks(result)
    inference_paths = {
        path for path, _payload in HubClientDouble.calls
        if path in {"/api/reason", "/api/async-jobs", "/api/benchmark/run", "/api/task/vision"}
    }

    assert result["success"] is False
    assert checks["live-model-inventory"]["status"] == "not_verified"
    assert checks["live-model"]["classification"] == "model_inventory_unavailable"
    assert inference_paths == set()


def test_live_smoke_classifies_resource_pressure_without_retry(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(
        HubClientDouble,
        "async_submit_payload",
        {
            "success": False,
            "state": "rejected",
            "error": "async job admission rejected by resource pressure",
            "admission": {"reason": "resource_pressure"},
            "retryable": True,
            "terminal": False,
        },
    )

    result = smoke(tmp_path)
    async_check = _checks(result)["live-async-job"]
    async_requests = [payload for path, payload in HubClientDouble.calls if path == "/api/async-jobs"]

    assert async_check["ok"] is False
    assert async_check["blocked"] is True
    assert async_check["classification"] == "blocked_resource_pressure"
    assert async_check["retryable"] is True
    assert async_check["terminal"] is False
    assert len(async_requests) == 1
    assert async_requests[0]["action"] == "submit"


def test_live_smoke_classifies_queue_limit_separately_without_retry(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(
        HubClientDouble,
        "async_submit_payload",
        {
            "success": False,
            "state": "rejected",
            "admission": {"reason": "queue_limit"},
            "retryable": True,
            "terminal": False,
        },
    )

    result = smoke(tmp_path)
    async_check = _checks(result)["live-async-job"]
    async_requests = [payload for path, payload in HubClientDouble.calls if path == "/api/async-jobs"]

    assert async_check["ok"] is False
    assert async_check["blocked"] is False
    assert async_check["classification"] == "queue_limit"
    assert len(async_requests) == 1
    assert async_requests[0]["action"] == "submit"


def test_live_smoke_keeps_preprocessing_timeout_as_failed_status(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(HubClientDouble, "status_payload", _status(preprocessing_timeout=True))

    result = smoke(tmp_path)
    status = _checks(result)["live-status"]

    assert result["success"] is False
    assert status["ok"] is False
    assert status["degraded_dependencies"] == [
        {"service": "preprocessing.status", "classification": "probe_timeout"}
    ]


@pytest.mark.parametrize(
    ("response", "accepted"),
    [
        ({"success": False, "engine": "whisper_cli", "reason": "empty_transcript", "text": ""}, True),
        ({"success": False, "engine": "other_engine", "reason": "empty_transcript", "text": ""}, False),
        ({"success": False, "engine": "whisper_cli", "reason": "other_empty_result", "text": ""}, False),
    ],
)
def test_live_smoke_accepts_only_verified_empty_silence(smoke, tmp_path, monkeypatch, response, accepted):
    monkeypatch.setattr(HubClientDouble, "transcription_payload", response)

    result = smoke(tmp_path)
    transcription = _checks(result)["live-transcribe"]

    assert transcription["ok"] is accepted
    assert transcription["classification"] == (
        "expected_empty_input" if accepted else "request_failed"
    )
    request = next(payload for path, payload in HubClientDouble.calls if path == "/api/task/transcribe")
    assert "model" not in request


@pytest.mark.parametrize("failure", ["cli_missing", "process_failed", "invalid_audio"])
def test_live_smoke_rejects_transcription_pipeline_failures(smoke, tmp_path, monkeypatch, failure):
    monkeypatch.setattr(
        HubClientDouble,
        "transcription_payload",
        {"success": False, "engine": "whisper_cli", "reason": failure, "text": ""},
    )

    transcription = _checks(smoke(tmp_path))["live-transcribe"]

    assert transcription["ok"] is False
    assert transcription["classification"] == failure


def test_live_smoke_fails_model_services_when_ollama_readiness_unknown(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(HubClientDouble, "status_payload", _status(ollama_online=None))

    checks = _checks(smoke(tmp_path))

    for name in ("live-model", "live-hardware-benchmark", "live-vision", "live-async-job"):
        assert checks[name]["ok"] is False
    for name in ("live-model", "live-async-job"):
        assert checks[name]["classification"] == "ollama_offline"
