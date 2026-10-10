from __future__ import annotations

from contextlib import contextmanager, nullcontext
from io import BytesIO
from types import SimpleNamespace
import threading
import time
from urllib.error import HTTPError

import pytest

import local_ai_hub.ollama as ollama_module
from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.ollama import OllamaRuntime
from local_ai_hub.scheduler import AffinityScheduler, Job, QueueFullError, SchedulerTimeoutError
from local_ai_hub.services import LocalAIServices


class _ConfiguredLlamaCpp:
    def __init__(self, online: bool, models: list[str]) -> None:
        self.online = online
        self.models = models

    def is_online(self) -> bool:
        return self.online

    def available_models(self) -> list[str]:
        return list(self.models)


def _runtime_for_availability(llama_cpp: _ConfiguredLlamaCpp) -> OllamaRuntime:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {"llama_cpp": {"fallback_to_ollama": False}}
    runtime.llama_cpp = llama_cpp
    runtime._meta_cache = {}
    runtime._meta_cache_at = {}
    return runtime


def test_disabled_fallback_does_not_advertise_models_from_offline_llama_cpp() -> None:
    runtime = _runtime_for_availability(_ConfiguredLlamaCpp(False, ["configured.gguf"]))

    result = runtime.request("/api/tags")

    assert "error" in result
    assert result.get("models", []) == []


def test_installed_models_ignores_configured_llama_cpp_models_when_backend_offline() -> None:
    runtime = _runtime_for_availability(_ConfiguredLlamaCpp(False, ["configured.gguf"]))
    runtime.request = lambda *_args, **_kwargs: {"error": "backend unavailable"}

    assert runtime.installed_models() == []


def test_installed_models_uses_llama_cpp_models_only_when_backend_online() -> None:
    runtime = _runtime_for_availability(_ConfiguredLlamaCpp(True, ["configured.gguf"]))
    runtime.request = lambda *_args, **_kwargs: {"error": "Ollama unavailable"}

    assert runtime.installed_models() == ["configured.gguf"]


class _OfflineRuntime:
    def is_online(self) -> bool:
        return False


class _NoSubmitScheduler:
    def submit(self, *_args, **_kwargs):
        raise AssertionError("offline runtime must not enqueue model work")


class _TimeoutScheduler:
    def __init__(self):
        self.calls = 0
        self.cancel_events = []

    def submit(self, *_args, **_kwargs):
        self.calls += 1
        cancel_event = _kwargs.get("cancel_event")
        if cancel_event is not None:
            self.cancel_events.append(cancel_event)
        error = TimeoutError("job 17 did not finish before caller timeout (running)")
        error.error_code = "scheduler_caller_timeout"
        error.job_id = 17
        error.state = "running"
        raise error


class _PassthroughCache:
    def get_or_compute(self, _key, compute):
        return compute(), False, False


class _NoSemanticCache:
    def get(self, *_args, **_kwargs):
        return None, 0.0

    def set(self, *_args, **_kwargs):
        return None


class _NoStaleCache:
    def get(self, _key):
        return None

    def set(self, *_args, **_kwargs):
        return None


class _Breakers:
    def allow(self, _key):
        return True

    def success(self, _key):
        return None

    def failure(self, _key):
        return None


class _Telemetry:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


def _offline_services() -> LocalAIServices:
    services = object.__new__(LocalAIServices)
    services.config = {
        "models": {"fast_code": "fast", "general": "general"},
        "token_saving": {"max_local_input_tokens": 4096, "max_local_output_tokens": 512},
        "model_execution": {"fast": {"context_tokens": 4096, "max_context_tokens": 4096}},
        "resilience": {"model_fallback_enabled": True, "max_model_fallbacks": 2},
        "ollama": {"keep_alive": "-1"},
    }
    services.runtime = _OfflineRuntime()
    services.scheduler = _NoSubmitScheduler()
    services.model_policy = ModelExecutionPolicy(services.config)
    services.semantic_cache = _NoSemanticCache()
    services.generation_cache = _PassthroughCache()
    services.stale_generation_cache = _NoStaleCache()
    services.breakers = _Breakers()
    services.telemetry = _Telemetry()
    services.artifacts = SimpleNamespace(compact=lambda result, *_args: result)
    services.tuner = None
    services.vram_balancer = None
    services.fallback_count = 0
    services._semantic_lock_guard = threading.Lock()
    services._semantic_scope_locks = {}
    return services


def test_vram_status_accessor_does_not_hide_unexpected_errors() -> None:
    services = _offline_services()

    class BrokenBalancer:
        def status(self):
            raise RuntimeError("unexpected status failure")

    services.vram_balancer = BrokenBalancer()

    with pytest.raises(RuntimeError, match="unexpected status failure"):
        services._available_vram_mb()


def test_tuner_observation_logs_expected_metric_errors_without_payload(caplog) -> None:
    services = object.__new__(LocalAIServices)

    class BrokenTuner:
        @staticmethod
        def observe(*_args, **_kwargs):
            raise ValueError("private model metric payload")

    services.tuner = BrokenTuner()

    with caplog.at_level("DEBUG", logger="local_ai_hub.services"):
        services._observe_tuner_safely("model", {"eval_count": "invalid"}, 12.0)

    messages = [record.getMessage() for record in caplog.records]
    assert any("Model tuning observation skipped (ValueError)" in message for message in messages)
    assert all("private" not in message and "invalid" not in message for message in messages)


def test_tuner_observation_propagates_unexpected_errors() -> None:
    services = object.__new__(LocalAIServices)

    class BrokenTuner:
        @staticmethod
        def observe(*_args, **_kwargs):
            raise RuntimeError("unexpected tuner programming failure")

    services.tuner = BrokenTuner()

    with pytest.raises(RuntimeError, match="unexpected tuner programming failure"):
        services._observe_tuner_safely("model", {}, 12.0)


def test_generate_fails_fast_without_backend_and_skips_scheduler() -> None:
    services = _offline_services()

    result = LocalAIServices._generate(
        services,
        "fast",
        "tiny",
        "",
        64,
        0.0,
        "tenant",
        "delegate:general",
        5,
    )

    assert result["success"] is False
    assert result["retryable"] is True
    assert result["error_code"] == "local_backend_unavailable"


def test_generate_persists_semantic_cache_result_once() -> None:
    services = _offline_services()

    class _OnlineRuntime:
        def is_online(self) -> bool:
            return True

        def request(self, _endpoint, _payload):
            return {"response": "A useful generated response."}

    class _InlineScheduler:
        def submit(self, _model, _tenant, _source, execute, **_kwargs):
            return execute()

    class _RecordingSemanticCache(_NoSemanticCache):
        def __init__(self) -> None:
            self.writes = []

        def set(self, scope, query, value):
            self.writes.append((scope, query, value))

    semantic_cache = _RecordingSemanticCache()
    services.runtime = _OnlineRuntime()
    services.scheduler = _InlineScheduler()
    services.semantic_cache = semantic_cache
    services.inference_admission = lambda _action: nullcontext(None)

    result = LocalAIServices._generate(
        services,
        "fast",
        "A bounded test request",
        "",
        64,
        0.0,
        "tenant",
        "delegate:general",
        5,
    )

    assert result["success"] is True
    assert len(semantic_cache.writes) == 1


def test_generate_exposes_retryable_scheduler_timeout_metadata() -> None:
    services = _offline_services()
    services.runtime = type("OnlineRuntime", (), {"is_online": lambda self: True})()
    services.scheduler = _TimeoutScheduler()

    result = LocalAIServices._generate(
        services,
        "fast",
        "A bounded test request",
        "",
        64,
        0.0,
        "tenant",
        "delegate:general",
        5,
    )

    assert result["success"] is False
    assert result["retryable"] is True
    assert result["terminal"] is False
    assert result["error_code"] == "model_request_timeout"
    assert "scheduler_job_id" not in result  # final failure stays compact and safe
    assert services.scheduler.calls == 1  # do not start a fallback beside a timed-out job
    assert len(services.scheduler.cancel_events) == 1
    assert services.scheduler.cancel_events[0].is_set()


def test_generate_fallback_does_not_downgrade_model_tier() -> None:
    services = _offline_services()
    services.config["models"] = {
        "fast_code": "fast",
        "general": "general",
        "heavy_code": "heavy",
        "reasoning": "reasoning",
    }
    services.model_policy = ModelExecutionPolicy(services.config)
    requested_models: list[str] = []

    class _FailingRuntime:
        def is_online(self) -> bool:
            return True

        def request_stream(self, _endpoint, payload, _on_chunk, **_kwargs):
            requested_models.append(str(payload.get("model", "")))
            return {"error": "Ollama unavailable"}

    class _InlineScheduler:
        def submit(self, _model, _tenant, _source, execute, **_kwargs):
            return execute()

    services.runtime = _FailingRuntime()
    services.scheduler = _InlineScheduler()

    result = LocalAIServices._generate(
        services,
        "heavy",
        "Review this large patch for correctness and evidence.",
        "",
        64,
        0.0,
        "tenant",
        "review",
        5,
    )

    assert result["success"] is False
    assert requested_models == ["heavy"]


def _scheduler_harness(*, max_queue: int = 4, max_queued_per_tenant: int = 2) -> AffinityScheduler:
    scheduler = object.__new__(AffinityScheduler)
    scheduler.runtime = SimpleNamespace()
    scheduler.unload_others = True
    scheduler.config = {"scheduler": {}}
    scheduler._cond = threading.Condition()
    scheduler._pending = []
    scheduler._job_id = 0
    scheduler._model_blocked_until = {}
    scheduler._model_last_error = {}
    scheduler._stats = {
        "submitted": 0,
        "background_submitted": 0,
        "queue_rejections": 0,
        "caller_timeouts": 0,
        "cancelled_pending": 0,
    }
    scheduler.max_queue = max_queue
    scheduler.max_queued_per_tenant = max_queued_per_tenant
    scheduler.max_caller_wait_timeout = 0.05
    scheduler.default_caller_wait_timeout = 0.05
    scheduler._foreground_preempt_hook = None
    scheduler._foreground_preempting = False
    scheduler._background_gpu_lease = False
    scheduler._foreground_generation = 0
    scheduler._last_foreground_activity = time.monotonic()
    scheduler._inflight_by_tenant = {}
    scheduler._tenant_vruntime = {}
    scheduler._active_model = "model"
    scheduler.max_inflight_per_tenant = 1
    scheduler.background_idle_grace = 0.0
    return scheduler


def test_scheduler_rejects_global_and_per_tenant_queue_overflow() -> None:
    global_limited = _scheduler_harness(max_queue=1, max_queued_per_tenant=4)
    global_limited.enqueue("model", "one", "test", lambda: {})
    with pytest.raises(QueueFullError):
        global_limited.enqueue("model", "two", "test", lambda: {})

    tenant_limited = _scheduler_harness(max_queue=4, max_queued_per_tenant=1)
    tenant_limited.enqueue("model", "one", "test", lambda: {})
    with pytest.raises(QueueFullError):
        tenant_limited.enqueue("model", "one", "test", lambda: {})
    assert len(tenant_limited._pending) == 1


def test_scheduler_pending_timeout_releases_queue_slot() -> None:
    scheduler = _scheduler_harness(max_queue=1, max_queued_per_tenant=1)

    with pytest.raises(SchedulerTimeoutError) as timeout:
        scheduler.submit("model", "one", "test", lambda: {}, wait_timeout=0.05)

    assert timeout.value.state == "pending"
    assert scheduler._pending == []
    assert scheduler._stats["cancelled_pending"] == 1
    replacement = scheduler.enqueue("model", "one", "test", lambda: {})
    assert scheduler._pending == [replacement]


def test_scheduler_priority_aging_eventually_serves_old_foreground_job() -> None:
    scheduler = _scheduler_harness()
    now = time.monotonic()
    old = Job(1, "model", "old-tenant", "test", 0, lambda: {})
    old.created_at = now - 400
    fresh = Job(2, "model", "fresh-tenant", "test", 9, lambda: {})

    selected = scheduler._choose_job_for_active_model(now, [fresh, old])

    assert selected is old


def test_scheduler_timeout_signals_running_job_and_keeps_capacity_until_exit() -> None:
    scheduler = _scheduler_harness()
    scheduler.max_caller_wait_timeout = 0.3
    scheduler.default_caller_wait_timeout = 0.3
    scheduler._inflight = 0
    scheduler._inflight_background = 0
    scheduler._inflight_jobs = {}
    scheduler._stats.update({"completed": 0, "failed": 0, "background_completed": 0, "background_failed": 0})
    cancel_event = threading.Event()
    execute_started = threading.Event()
    cancel_observed = threading.Event()
    allow_finish = threading.Event()
    submit_errors: list[BaseException] = []

    def execute() -> dict[str, bool]:
        execute_started.set()
        if cancel_event.wait(timeout=2.0):
            cancel_observed.set()
        allow_finish.wait(timeout=2.0)
        return {"success": True}

    def submit() -> None:
        try:
            scheduler.submit("model", "one", "test", execute, wait_timeout=0.3, cancel_event=cancel_event)
        except BaseException as exc:
            submit_errors.append(exc)

    submitter = threading.Thread(target=submit, daemon=True)
    submitter.start()
    runner: threading.Thread | None = None
    try:
        deadline = time.monotonic() + 1.0
        with scheduler._cond:
            while not scheduler._pending and time.monotonic() < deadline:
                scheduler._cond.wait(timeout=0.01)
            assert scheduler._pending
            job = scheduler._pending.pop(0)
            job.dispatched_at = time.monotonic()
            scheduler._inflight = 1
            scheduler._inflight_jobs[job.id] = job
            scheduler._inflight_by_tenant[job.tenant] = 1

        runner = threading.Thread(target=scheduler._run_job, args=(job,), daemon=True)
        runner.start()
        assert execute_started.wait(timeout=1.0)
        submitter.join(timeout=1.0)

        assert not submitter.is_alive()
        assert len(submit_errors) == 1
        assert isinstance(submit_errors[0], SchedulerTimeoutError)
        assert submit_errors[0].state == "running"
        assert cancel_event.is_set()
        assert cancel_observed.wait(timeout=1.0)
        with scheduler._cond:
            assert scheduler._inflight == 1
            assert job.id in scheduler._inflight_jobs
    finally:
        allow_finish.set()
        if runner is not None:
            runner.join(timeout=2.0)
        submitter.join(timeout=2.0)


def test_scheduler_external_cancel_removes_pending_job_promptly() -> None:
    scheduler = _scheduler_harness()
    scheduler.max_caller_wait_timeout = 0.8
    scheduler.default_caller_wait_timeout = 0.8
    cancel_event = threading.Event()
    submit_done = threading.Event()
    submit_errors: list[BaseException] = []

    def submit() -> None:
        try:
            scheduler.submit(
                "model", "one", "test", lambda: {},
                wait_timeout=0.8, cancel_event=cancel_event,
            )
        except BaseException as exc:
            submit_errors.append(exc)
        finally:
            submit_done.set()

    submitter = threading.Thread(target=submit, daemon=True)
    submitter.start()
    try:
        deadline = time.monotonic() + 0.5
        with scheduler._cond:
            while not scheduler._pending and time.monotonic() < deadline:
                scheduler._cond.wait(timeout=0.01)
            assert scheduler._pending

        cancel_event.set()

        assert submit_done.wait(timeout=0.25), "external cancellation did not wake the queued caller promptly"
        assert scheduler._pending == []
        assert len(submit_errors) == 1
        assert isinstance(submit_errors[0], InterruptedError)
        assert getattr(submit_errors[0], "state", None) == "pending"
        assert scheduler._stats["cancelled_pending"] == 1
    finally:
        cancel_event.set()
        submitter.join(timeout=1.0)

    assert scheduler._pending == []


def test_scheduler_prepare_cancel_keeps_same_model_waiters_and_avoids_cooldown() -> None:
    scheduler = _scheduler_harness()
    scheduler._stats.update({
        "switch_time_ms": 0.0,
        "evictions": 0,
        "model_switch_failures": 0,
        "model_switches": 0,
    })
    scheduler.switch_failure_cooldown = 1.0
    scheduler._active_model = "previous"
    scheduler._active_since = time.monotonic()
    scheduler._switching = True

    first_cancel = threading.Event()
    second_cancel = threading.Event()
    first = scheduler.enqueue("target", "one", "test", lambda: {})
    second = scheduler.enqueue("target", "two", "test", lambda: {})
    expired = scheduler.enqueue("target", "three", "test", lambda: {})
    first.cancel_event = first_cancel
    second.cancel_event = second_cancel
    expired.cancel_event = threading.Event()
    expired.deadline = time.monotonic() - 1.0

    class _CancelledPreparation(InterruptedError):
        preparation_cancelled = True

    class _Runtime:
        def prepare_model(self, _model, *, unload_others=True, should_stop=None, deadline=None):
            assert callable(should_stop)
            assert should_stop() is False
            first_cancel.set()
            assert should_stop() is False, "one cancelled waiter must not stop shared preparation"
            second_cancel.set()
            assert should_stop() is True, "preparation should stop after the final waiter cancels"
            raise _CancelledPreparation("all target waiters cancelled")

    scheduler.runtime = _Runtime()
    scheduler._perform_switch(
        "target",
        should_stop=lambda: not scheduler._has_active_preparation_waiter("target"),
    )

    assert scheduler._stats["model_switch_failures"] == 0
    assert "target" not in scheduler._model_blocked_until
    assert scheduler._active_model is None
    assert scheduler._switching is False
    assert scheduler._pending == []


def test_prepare_model_propagates_cancel_and_deadline_to_llama_cpp() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {"llama_cpp": {"model_load_timeout_seconds": 5.0}}
    stop_event = threading.Event()
    received: dict[str, object] = {}
    requested_deadline = time.monotonic() + 2.0

    class _LlamaCpp:
        def ensure_model(self, model, *, timeout=None, should_stop=None, deadline=None):
            received.update({
                "model": model,
                "timeout": timeout,
                "should_stop": should_stop,
                "deadline": deadline,
            })
            return True

    runtime.llama_cpp = _LlamaCpp()

    assert runtime.prepare_model(
        "model", should_stop=stop_event.is_set, deadline=requested_deadline,
    ) == []

    assert received["model"] == "model"
    assert callable(received["should_stop"])
    assert received["deadline"] <= requested_deadline
    assert received["deadline"] > time.monotonic()


def test_interruptible_json_retries_http_5xx(monkeypatch) -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {"ollama": {"enabled": True, "request_attempts": 2, "retry_delay_seconds": 0}}
    runtime.base_url = "http://ollama"
    runtime.timeout = 2.0
    calls: list[int] = []

    class _Response:
        status = 200

        def __init__(self, body: bytes) -> None:
            self.body = body

        def read(self, _size: int = -1) -> bytes:
            body, self.body = self.body, b""
            return body

    @contextmanager
    def open_response(request, _deadline, _should_stop):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 503, "temporarily unavailable", {}, BytesIO(b"retry"))
        yield _Response(b'{"loaded":true}')

    monkeypatch.setattr(ollama_module, "_open_interruptible_response", open_response)
    result = runtime.request(
        "/api/ps", should_stop=lambda: False, deadline=time.monotonic() + 2.0,
    )

    assert calls == [1, 2]
    assert result["loaded"] is True
    assert result["_lah_retry_count"] == 1


def test_loaded_model_details_does_not_probe_adapter_after_cancel() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime._meta_cache = {}
    runtime._meta_cache_at = {}
    runtime.request = lambda *_args, **_kwargs: {"preempted": True, "error": "cancelled"}

    class _LlamaCpp:
        def loaded_model_details(self):
            raise AssertionError("cancelled preparation must not start an adapter probe")

    runtime.llama_cpp = _LlamaCpp()

    with pytest.raises(InterruptedError):
        runtime.loaded_model_details(should_stop=lambda: False, deadline=time.monotonic() + 2.0)


def test_loaded_model_details_passes_controls_to_adapter_fallback() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime._meta_cache = {}
    runtime._meta_cache_at = {}
    runtime.request = lambda *_args, **_kwargs: {"error": "Ollama unavailable"}
    stop = lambda: False
    deadline = time.monotonic() + 2.0
    received: dict[str, object] = {}

    class _LlamaCpp:
        def loaded_model_details(self, *, should_stop=None, deadline=None):
            received.update({"should_stop": should_stop, "deadline": deadline})
            return [{"name": "adapter-model"}]

    runtime.llama_cpp = _LlamaCpp()

    assert runtime.loaded_model_details(should_stop=stop, deadline=deadline) == [{"name": "adapter-model"}]
    assert received == {"should_stop": stop, "deadline": deadline}
