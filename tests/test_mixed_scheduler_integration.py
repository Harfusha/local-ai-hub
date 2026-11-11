from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from local_ai_hub.ollama import OllamaRuntime
from local_ai_hub.scheduler import AffinityScheduler, Job, SchedulerTimeoutError


@pytest.mark.parametrize("available_mb, admitted, resize, preloaded", [(6144, True, False, False), (256, False, False, False), (6144, True, True, False), (6144, True, False, True)])
@pytest.mark.parametrize("client_path", ["runtime", "benchmark", "eval_suite"])
def test_scheduler_prepares_fallback_before_inference_and_releases_on_unload(tmp_path, available_mb, admitted, resize, preloaded, client_path):
    state = {"loaded": resize or preloaded, "context": 512 if resize else 131072, "calls": [], "unprotected": False, "admission_loaded": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path != "/api/ps":
                self.send_error(404)
                return
            rows = [{"name": "candidate", "context_length": state["context"]}] if state["loaded"] else []
            body = json.dumps({"models": rows}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["calls"].append(payload)
            with socket.socket() as contender:
                try:
                    contender.bind(("127.0.0.1", cuda_port))
                except OSError:
                    pass
                else:
                    state["unprotected"] = True
            if payload.get("keep_alive") == 0:
                state["loaded"] = False
                answer = {"done": True, "done_reason": "unload"}
            else:
                state["loaded"] = True
                state["context"] = payload.get("options", {}).get("num_ctx", state["context"])
                answer = {"done": True, "response": "2" if payload.get("prompt") else ""}
            body = (json.dumps(answer) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    cuda_port = probe.getsockname()[1]
    probe.close()
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": f"http://127.0.0.1:{server.server_port}", "request_timeout_seconds": 10},
        "ollama": {"enabled": True, "request_attempts": 1},
        "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                      "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                      "fallback_to_ollama": True, "model_load_timeout_seconds": 10,
                      "models": {"candidate": {"url": f"http://127.0.0.1:{cuda_port}"}}},
        "scheduler": {"model_vram_estimates_bytes": {"candidate": 1024**3}, "max_loaded_models": 1},
    }
    runtime = OllamaRuntime(config)
    def telemetry(force=False):
        if force:
            state["admission_loaded"].append(state["loaded"])
        return {"available": True, "vram_total_mb": 8192, "vram_available_mb": available_mb if force else 6144}

    runtime.vram_balancer = SimpleNamespace(status=telemetry)
    scheduler = None
    try:
        with patch.object(runtime, "ensure_running", return_value=True):
            scheduler = AffinityScheduler(runtime, config)
            if client_path == "benchmark":
                from local_ai_hub.benchmark import HardwareBenchmarkRunner
                result = HardwareBenchmarkRunner(
                    tmp_path / "benchmark.json", runtime=runtime,
                    vram_balancer=runtime.vram_balancer, config=config, scheduler=scheduler,
                ).run(model="candidate", prompt="1+1", num_tokens=2)
            elif client_path == "eval_suite":
                from local_ai_hub.services import LocalAIServices
                services = LocalAIServices.__new__(LocalAIServices)
                services.config = config
                services.runtime = runtime
                services.scheduler = scheduler
                result = services.eval_suite({
                    "model": "candidate", "cases": [{"id": "case", "input": "1+1", "expected": "2"}],
                })
            else:
                result = scheduler.submit("candidate", source="test", wait_timeout=10, execute=lambda: runtime.request(
                    "/api/generate", {"model": "candidate", "prompt": "1+1", "stream": False}, timeout=5,
                ))
            if not preloaded:
                assert state["admission_loaded"] and not any(state["admission_loaded"])
            if not admitted:
                if client_path == "benchmark":
                    assert result["admission"]["vram_admission"] == "rejected"
                elif client_path == "eval_suite":
                    assert result["summary"]["execution_failures"] == 1
                    assert result["cases"][0]["status"] == "error"
                else:
                    assert result["_lah_scheduler_model_switch"]["post_unload_admission"]["state"] == "rejected"
                assert state["calls"] == []
                assert runtime._mixed_fallback_guard is not None
                assert not runtime._mixed_fallback_admitted
                return
            if client_path == "benchmark":
                assert result["success"] is True
                assert result["tokens_per_second"] > 0
            elif client_path == "eval_suite":
                assert result["summary"]["quality_pass_rate"] == 1.0
            else:
                assert result["response"] == "2"
                assert result["_lah_provider"] == "ollama"
            if not preloaded and client_path == "runtime":
                assert result["_lah_scheduler_model_switch"]["post_unload_admission"]["state"] == "admitted"
            assert [item.get("prompt") for item in state["calls"]] == (["1+1"] if preloaded else ["", "", "1+1"] if resize else ["", "1+1"])
            assert not state["unprotected"]
            # A different local client can unload a runner behind the scheduler.
            # The detection happens before inference, so the next job can safely
            # prepare it again without replaying the failed request.
            state["loaded"] = False
            calls_before = len(state["calls"])
            rejected = scheduler.submit("candidate", source="test", wait_timeout=10, execute=lambda: runtime.request(
                "/api/generate", {"model": "candidate", "prompt": "must not run", "stream": False}, timeout=5,
            ))
            assert rejected["operation_not_started"] is True
            assert rejected["error_code"] == "model_preparation_required"
            assert len(state["calls"]) == calls_before
            recovered = scheduler.submit("candidate", source="test", wait_timeout=10, execute=lambda: runtime.request(
                "/api/generate", {"model": "candidate", "prompt": "1+1", "stream": False}, timeout=5,
            ))
            assert recovered["response"] == "2"
            scheduler.submit("candidate", source="test", wait_timeout=10, execute=lambda: {
                "success": False, "error": "ambiguous", "operation_not_started": True,
                "error_code": "model_preparation_required", "outcome_unknown": True,
            })
            assert scheduler._internal_gpu_uncertain
            with socket.socket() as other:
                try:
                    other.bind(("127.0.0.1", cuda_port))
                except OSError:
                    pass
                else:
                    raise AssertionError("CUDA port was not reserved")
            assert runtime.unload_model("candidate")
            with socket.socket() as other:
                other.bind(("127.0.0.1", cuda_port))
    finally:
        if scheduler is not None:
            scheduler.close()
        runtime._release_mixed_fallback_guard("candidate")
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_scheduler_timeout_reports_gpu_reservation_wait_reason(tmp_path):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
    }
    runtime = OllamaRuntime(config)
    scheduler = AffinityScheduler(runtime, config)
    token = None
    try:
        token = scheduler.reserve_external_gpu(
            owner="legacy-test-external-session", owner_vram_budget_bytes=1,
        )
        assert token
        reservation = scheduler._external_gpu_store.read()
        reservation.pop("owner_vram_budget_bytes")
        assert scheduler._external_gpu_store._write_metadata(reservation)
        scheduler_state = scheduler.status()
        assert scheduler_state["gpu_admission_state"] == "external_reservation"
        assert token not in repr(scheduler_state)
        with pytest.raises(SchedulerTimeoutError) as caught:
            scheduler.submit(
                "candidate", source="benchmark", execute=lambda: {"success": True}, wait_timeout=0.05,
            )
        assert caught.value.state == "pending"
        assert caught.value.wait_reason == "gpu-reservation"
    finally:
        if token:
            assert scheduler.release_external_gpu(token)
        scheduler.close()


@pytest.mark.parametrize("request_gib, completes", [(4, True), (9, False)])
def test_scheduler_dispatch_coadmits_around_resident_capacity_lease(tmp_path, request_gib, completes):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
        "scheduler": {"model_vram_estimates_bytes": {"candidate": request_gib * 1024**3}},
    }
    runtime = OllamaRuntime(config)
    runtime.loaded_models = lambda: []
    unloaded = []
    runtime.unload_model = lambda *args, **kwargs: unloaded.append((args, kwargs)) or True
    runtime.vram_balancer = SimpleNamespace(status=lambda force=False: {
        "available": True, "vram_total_mb": 16 * 1024, "vram_available_mb": 8 * 1024,
        "pressure_level": "nominal", "context_budget_factor": 1.0,
    })
    scheduler = AffinityScheduler(runtime, config)
    store = scheduler._external_gpu_store
    reservation = store.reserve(
        "a" * 64, owner="test-external-owner", owner_vram_budget_bytes=4 * 1024**3,
    )
    assert reservation is not None
    resident_result = scheduler.acquire_gpu_capacity_lease("laya:resident-model", 4 * 1024**3)
    assert resident_result["state"] == "admitted"
    resident = {key: value for key, value in resident_result.items() if key != "state"}
    with scheduler._cond:
        scheduler._active_model = "candidate" if completes else None
        scheduler._model_vram_bytes["candidate"] = request_gib * 1024**3
    called = threading.Event()
    try:
        if completes:
            result = scheduler.submit(
                "candidate", source="capacity-test",
                execute=lambda: (called.set() or {"success": True}), wait_timeout=2,
            )
            assert result["success"] is True
            assert called.is_set()
            snapshot = store.capacity_snapshot()
            assert [item["lease_id"] for item in snapshot["leases"]] == [resident["lease_id"]]
        else:
            with pytest.raises(SchedulerTimeoutError) as caught:
                scheduler.submit(
                    "candidate", source="capacity-test", execute=lambda: {"success": True},
                    wait_timeout=0.05,
                )
            assert caught.value.state == "pending"
            assert caught.value.wait_reason == "gpu-capacity"
            assert unloaded == []
            assert store.read()["generation"] == reservation["generation"]
            assert store.capacity_snapshot()["leases"] == [resident]
    finally:
        scheduler.close()


def test_scheduler_admission_uses_measured_free_capacity_not_reservation_budget(tmp_path):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
        "scheduler": {"model_vram_estimates_bytes": {"candidate": 4 * 1024**3}},
    }
    runtime = OllamaRuntime(config)
    runtime.vram_balancer = SimpleNamespace(status=lambda force=False: {
        "available": True, "vram_total_mb": 16 * 1024, "vram_available_mb": 8 * 1024,
        "pressure_level": "nominal", "context_budget_factor": 1.0,
    })
    scheduler = AffinityScheduler(runtime, config)
    reservation = scheduler._external_gpu_store.reserve(
        "a" * 64, owner="test-external-owner", owner_vram_budget_bytes=16 * 1024**3,
    )
    try:
        admission = scheduler._admission(background=False, model="candidate")
        assert reservation is not None
        assert admission["state"] == "accepted"
        assert admission["vram_admission"] == "admitted"
        assert admission["vram_admission_budget_bytes"] == 8 * 1024**3
    finally:
        scheduler.close()


def test_laya_capacity_lease_coadmits_legacy_reservation_from_measured_free_vram(tmp_path):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
    }
    runtime = OllamaRuntime(config)
    runtime.vram_balancer = SimpleNamespace(status=lambda force=False: {
        "available": True, "vram_total_mb": 16 * 1024, "vram_available_mb": 8 * 1024,
        "pressure_level": "nominal", "context_budget_factor": 1.0,
    })
    scheduler = AffinityScheduler(runtime, config)
    store = scheduler._external_gpu_store
    reservation = store.reserve(
        "b" * 64, owner="legacy-external-owner", owner_vram_budget_bytes=16 * 1024**3,
    )
    legacy_record = store.read()
    legacy_record.pop("owner_vram_budget_bytes")
    assert store._write_metadata(legacy_record)
    try:
        lease = scheduler.acquire_gpu_capacity_lease("laya:resident-model", 4 * 1024**3)
        assert reservation is not None
        assert lease["state"] == "admitted"
        assert lease["reservation_generation"] == reservation["generation"]
        assert scheduler._capacity_sharing_active()
    finally:
        scheduler.close()


def test_internal_digest_reservation_is_not_shared_capacity(tmp_path):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
    }
    runtime = OllamaRuntime(config)
    runtime.vram_balancer = SimpleNamespace(status=lambda force=False: {
        "available": True, "vram_total_mb": 16 * 1024, "vram_available_mb": 8 * 1024,
        "pressure_level": "nominal", "context_budget_factor": 1.0,
    })
    scheduler = AffinityScheduler(runtime, config)
    try:
        assert scheduler._claim_internal_gpu()
        assert scheduler._external_gpu_store.capacity_snapshot() is None
        assert not scheduler._capacity_sharing_active()
    finally:
        scheduler.close()


def test_laya_capacity_lease_coadmits_during_owned_internal_digest(tmp_path):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
    }
    runtime = OllamaRuntime(config)
    runtime.vram_balancer = SimpleNamespace(status=lambda force=False: {
        "available": True, "vram_total_mb": 16 * 1024, "vram_available_mb": 8 * 1024,
        "pressure_level": "nominal", "context_budget_factor": 1.0,
    })
    scheduler = AffinityScheduler(runtime, config)
    lease = None
    try:
        assert scheduler._claim_internal_gpu()
        digest = scheduler._internal_gpu_digest
        lease = scheduler.acquire_gpu_capacity_lease("laya:resident-model", 4 * 1024**3)
        assert digest
        assert lease["state"] == "admitted"
        snapshot = scheduler._external_gpu_store.capacity_snapshot(expected_internal_digest=digest)
        assert snapshot is not None
        assert snapshot["leases"] == [{key: value for key, value in lease.items() if key != "state"}]
        assert scheduler._internal_gpu_digest == digest
        assert scheduler._capacity_sharing_active()
        with scheduler._cond:
            assert not scheduler._release_internal_gpu()
        assert scheduler._internal_gpu_digest == digest
        assert scheduler.release_gpu_capacity_lease(
            lease["lease_id"], lease["owner"], lease["generation"],
        )
        lease = None
        with scheduler._cond:
            assert scheduler._release_internal_gpu()
        assert scheduler._internal_gpu_digest is None
    finally:
        if lease and lease.get("state") == "admitted":
            scheduler.release_gpu_capacity_lease(lease["lease_id"], lease["owner"], lease["generation"])
        with scheduler._cond:
            scheduler._release_internal_gpu()
        scheduler.close()


def test_scheduler_switch_preserves_other_resident_when_shared_capacity_fits(tmp_path):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
        "scheduler": {"model_vram_estimates_bytes": {"candidate": 4 * 1024**3}},
    }
    runtime = OllamaRuntime(config)
    residents = {"laya-model"}
    prepare_calls = []
    unload_calls = []
    runtime.loaded_models = lambda: list(residents)
    runtime.prepare_model = lambda model, **kwargs: (prepare_calls.append((model, kwargs)) or residents.add(model) or [])
    runtime.unload_model = lambda *args, **kwargs: unload_calls.append((args, kwargs)) or True
    runtime.vram_balancer = SimpleNamespace(status=lambda force=False: {
        "available": True, "vram_total_mb": 16 * 1024, "vram_available_mb": 8 * 1024,
        "pressure_level": "nominal", "context_budget_factor": 1.0,
    })
    scheduler = AffinityScheduler(runtime, config)
    scheduler._observe_model_vram_bytes = lambda *args, **kwargs: None
    store = scheduler._external_gpu_store
    resident_result = scheduler.acquire_gpu_capacity_lease("laya:resident-model", 4 * 1024**3)
    assert resident_result["state"] == "admitted"
    resident = {key: value for key, value in resident_result.items() if key != "state"}
    try:
        result = scheduler.submit(
            "candidate", source="capacity-switch-test",
            execute=lambda: {"success": True}, wait_timeout=2,
        )
        assert result["success"] is True
        assert prepare_calls and prepare_calls[0][1]["unload_others"] is False
        assert "laya-model" in residents and "candidate" in residents
        assert unload_calls == []
        assert store.capacity_snapshot()["leases"] == [resident]
        assert scheduler.release_gpu_capacity_lease(
            resident["lease_id"], resident["owner"], resident["generation"],
        )
    finally:
        scheduler.close()


def test_capacity_deferred_model_does_not_block_admitted_active_model_job(tmp_path):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
    }
    runtime = OllamaRuntime(config)
    runtime.vram_balancer = SimpleNamespace(status=lambda force=False: {
        "available": True, "vram_total_mb": 16 * 1024, "vram_available_mb": 8 * 1024,
        "pressure_level": "nominal", "context_budget_factor": 1.0,
    })
    scheduler = AffinityScheduler(runtime, config)
    store = scheduler._external_gpu_store
    resident = scheduler.acquire_gpu_capacity_lease("laya:resident-model", 4 * 1024**3)
    assert resident["state"] == "admitted"
    called = threading.Event()
    deferred = Job(
        id=1, model="too-large", source="capacity-test", priority=10,
        execute=lambda: {"success": True},
    )
    admitted = Job(
        id=2, model="resident", source="capacity-test", priority=5,
        execute=lambda: (called.set() or {"success": True}),
    )
    with scheduler._cond:
        scheduler._gpu_prepare_in_progress = True
        scheduler._active_model = "resident"
        scheduler._model_vram_bytes["too-large"] = 9 * 1024**3
        scheduler._pending.extend([deferred, admitted])
        scheduler._job_id = 2
        scheduler._gpu_prepare_in_progress = False
        scheduler._cond.notify_all()
    try:
        assert admitted.done.wait(2)
        assert called.is_set()
        assert not deferred.done.is_set()
        assert deferred.gpu_capacity_lease is None
        assert [item["lease_id"] for item in store.capacity_snapshot()["leases"]] == [
            resident["lease_id"],
        ]
    finally:
        scheduler.close()


def test_authorized_store_release_clears_scheduler_owned_fence(tmp_path):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
    }
    scheduler = AffinityScheduler(OllamaRuntime(config), config)
    try:
        token = scheduler.reserve_external_gpu(owner="release-test", owner_vram_budget_bytes=1)
        assert token
        store = scheduler._external_gpu_store
        assert store is not None
        assert store.release_current_with_consent(
            consent=True,
            audit_reason="focused test of the authorized coordination release path",
        )
        assert scheduler.status()["gpu_admission_state"] == "available"
    finally:
        scheduler.close()


def test_authorized_scheduler_release_uses_live_store_and_syncs_admission(tmp_path):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
    }
    scheduler = AffinityScheduler(OllamaRuntime(config), config)
    try:
        token = scheduler.reserve_external_gpu(owner="release-test", owner_vram_budget_bytes=1)
        assert token
        result = scheduler.gpu_reservation_operation(
            action="release_authorized",
            consent=True,
            audit_reason="focused test of scheduler-authoritative GPU release",
        )
        assert result["success"] is True
        assert scheduler.status()["gpu_admission_state"] == "available"
        assert scheduler._external_gpu_store.read() is None
    finally:
        scheduler.close()


def test_authorized_release_clears_reservation_fence_with_queued_waiter(tmp_path, monkeypatch):
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "ollama": {"enabled": True},
    }
    monkeypatch.setattr(AffinityScheduler, "_dispatch_loop", lambda _scheduler: None)
    scheduler = AffinityScheduler(OllamaRuntime(config), config)
    try:
        token = scheduler.reserve_external_gpu(owner="release-test", owner_vram_budget_bytes=1)
        assert token
        with scheduler._cond:
            scheduler._pending.append(Job(
                id=1, model="candidate", source="benchmark", priority=10,
                execute=lambda: {"success": True},
            ))

        released = scheduler.gpu_reservation_operation(
            action="release_authorized",
            consent=True,
            audit_reason="focused test: clear stale reservation fence with a queued waiter",
        )
        assert released["success"] is True
        assert scheduler.status()["gpu_admission_state"] == "available"
    finally:
        with scheduler._cond:
            scheduler._pending.clear()
        scheduler.close()


@pytest.mark.parametrize("available_mb, outcome", [(6144, "success"), (256, "reject"), (6144, "partial")])
def test_scheduler_routes_cuda_only_after_ollama_unload_and_admission(tmp_path, available_mb, outcome):
    state = {"ollama_loaded": True, "cuda_loaded": False, "events": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, body, content_type="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.server.kind == "ollama" and self.path == "/api/ps":
                models = [{"name": "other", "context_length": 4096}] if state["ollama_loaded"] else []
                self.respond(json.dumps({"models": models}).encode())
            elif self.server.kind == "cuda" and self.path == "/health":
                self.respond(b'{}')
            elif self.server.kind == "cuda" and self.path == "/models":
                status = "loaded" if state["cuda_loaded"] else "unloaded"
                self.respond(json.dumps({"data": [{"id": "alias", "status": {"value": status}}]}).encode())
            else:
                self.send_error(404)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.server.kind == "ollama" and self.path == "/api/generate" and payload.get("keep_alive") == 0:
                state["events"].append("unload_ollama")
                state["ollama_loaded"] = False
                self.respond(b'{"done":true,"done_reason":"unload"}\n')
            elif self.server.kind == "cuda" and self.path == "/models/load":
                state["events"].append("load_cuda")
                state["cuda_loaded"] = True
                self.respond(b'{"success":true}')
            elif self.server.kind == "cuda" and self.path == "/v1/chat/completions":
                state["events"].append("generate_cuda")
                state["generation_payload"] = payload
                events = [
                    {"choices": [{"index": 0, "delta": {"content": "2"}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                ]
                if outcome == "partial":
                    body = "data: " + json.dumps(events[0]) + "\n\n"
                else:
                    body = "".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n"
                self.respond(body.encode(), "text/event-stream")
            else:
                self.send_error(404)

    ollama = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    cuda = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ollama.kind, cuda.kind = "ollama", "cuda"
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (ollama, cuda)]
    for thread in threads:
        thread.start()
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": f"http://127.0.0.1:{ollama.server_port}", "request_timeout_seconds": 10},
        "ollama": {"enabled": True, "request_attempts": 1},
        "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                      "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate", "fallback_to_ollama": True,
                      "model_load_timeout_seconds": 10,
                      "models": {"candidate": {"url": f"http://127.0.0.1:{cuda.server_port}", "served_model": "alias", "context_length": 131072}}},
        "scheduler": {"model_vram_estimates_bytes": {"candidate": 1024**3}, "max_loaded_models": 1},
    }
    runtime = OllamaRuntime(config)
    def telemetry(force=False):
        if force:
            state["events"].append("admit_while_loaded" if state["ollama_loaded"] else "admit")
        return {"available": True, "vram_total_mb": 8192, "vram_available_mb": available_mb if force else 6144}
    runtime.vram_balancer = SimpleNamespace(status=telemetry)
    scheduler = None
    try:
        with patch.object(runtime.llama_cpp_managed, "status", return_value={"online": True, "mode": "CUDA0"}):
            scheduler = AffinityScheduler(runtime, config)
            result = scheduler.submit("candidate", source="test", wait_timeout=10, execute=lambda: runtime.request(
                "/api/generate", {"model": "candidate", "prompt": "1+1", "stream": False, "think": False}, timeout=5,
            ))
        if outcome == "success":
            assert result["response"] == "2"
            assert result["_lah_provider"] == "llama.cpp-cuda"
            assert state["generation_payload"]["reasoning_effort"] == "none"
            assert state["events"] == ["unload_ollama", "admit", "load_cuda", "generate_cuda"]
        elif outcome == "reject":
            assert result["_lah_scheduler_model_switch"]["post_unload_admission"]["state"] == "rejected"
            assert state["events"] == ["unload_ollama", "admit"]
        else:
            assert result["_lah_partial_response"] is True
            assert scheduler._internal_gpu_uncertain
            assert state["events"] == ["unload_ollama", "admit", "load_cuda", "generate_cuda"]
    finally:
        if scheduler is not None:
            scheduler.close()
        for server in (ollama, cuda):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
