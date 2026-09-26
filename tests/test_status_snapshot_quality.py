import threading
import time
from types import SimpleNamespace

import local_ai_hub.app as app_module
from local_ai_hub.app import LocalAIApp


class Probe:
    def __init__(self, **responses):
        self.calls = {}
        self.responses = responses

    def __getattr__(self, name):
        if name not in {"status", "stats", "summary", "snapshot_stats"}:
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.calls[name] = self.calls.get(name, 0) + 1
            response = self.responses.get(name, {})
            if callable(response):
                return response(*args, **kwargs)
            return response

        return call


class RuntimeProbe(Probe):
    def __init__(self, online=True, **responses):
        super().__init__(**responses)
        self.online = online

    def is_online(self):
        self.calls["is_online"] = self.calls.get("is_online", 0) + 1
        return self.online

    def version(self):
        self.calls["version"] = self.calls.get("version", 0) + 1
        return "test-version"

    def installed_models(self):
        self.calls["installed_models"] = self.calls.get("installed_models", 0) + 1
        return ["model-a"]

    def loaded_model_details(self):
        self.calls["loaded_model_details"] = self.calls.get("loaded_model_details", 0) + 1
        return [{"name": "model-a"}]

    def managed_profile_status(self):
        self.calls["managed_profile_status"] = self.calls.get("managed_profile_status", 0) + 1
        return {"active": "test"}


def make_app(*, scheduler=None, runtime=None):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"models": {}, "features": {}, "_hardware": {}}
    app.started_at = time.time()
    app.runtime = runtime or RuntimeProbe()
    app.telemetry = Probe(summary={"events": 1})
    app.services = SimpleNamespace(
        model_policy=Probe(summary={"policy": "test"}),
        generation_cache=Probe(stats={}),
        semantic_cache=Probe(stats={}),
        repo_cache=Probe(stats={}),
        breakers=Probe(status={}),
        fallback_count=0,
    )
    app.recovery = Probe(status={})
    app.background_gpu = Probe(status={})
    app.scheduler = scheduler or Probe(status={"state": "ready"})
    app.commands = Probe(stats={})
    app.repo_tools = Probe(snapshot_stats={})
    app.token_router = Probe(stats={})
    app.pipeline = Probe(stats={})
    app.preprocessor = Probe(stats={})
    app.tool_agent = Probe(stats={})
    app.code_index = Probe(status={})
    app.deterministic = Probe(status={})
    app.evidence = Probe(stats={})
    app.learner = Probe(stats={})
    app.tuner = Probe(stats={})
    app.embeddings = Probe(status={})
    app.reranker = Probe(status={})
    app.external_tools = Probe(status={})
    app.debug_traces = Probe(stats={})
    app._status_full_cache = {}
    app._status_full_cache_lock = threading.Lock()
    app._status_dependency_lock = threading.Lock()
    app._status_dependency_inflight = {}
    app._status_dependency_slots = threading.BoundedSemaphore(app_module._STATUS_MAX_INFLIGHT_DEPENDENCIES)
    return app


def test_cached_status_snapshot_isolated_from_caller_mutation():
    app = make_app()

    first = app.status()
    first["installed_models"].append("caller-added")
    second = app.status()

    assert second["installed_models"] == ["model-a"]
    assert app.scheduler.calls.get("status") == 1, (second["success"], second["scheduler"], len(app._status_dependency_inflight))


def test_concurrent_status_requests_share_one_snapshot_build():
    entered = threading.Event()
    release = threading.Event()

    def slow_status():
        entered.set()
        assert release.wait(1.0)
        return {"state": "ready"}

    scheduler = Probe(status=slow_status)
    app = make_app(scheduler=scheduler)
    results = []
    first = threading.Thread(target=lambda: results.append(app.status()))
    second = threading.Thread(target=lambda: results.append(app.status()))

    first.start()
    assert entered.wait(1.0)
    second.start()
    try:
        time.sleep(0.03)
        assert scheduler.calls["status"] == 1
    finally:
        release.set()
        first.join(1.0)
        second.join(1.0)

    assert len(results) == 2
    assert scheduler.calls["status"] == 1


def test_status_cache_ttl_starts_after_snapshot_collection(monkeypatch):
    now = [10.0]

    def advance_during_collection():
        now[0] += 3.0
        return {"state": "ready"}

    scheduler = Probe(status=advance_during_collection)
    app = make_app(scheduler=scheduler)
    monkeypatch.setattr(app_module.time, "monotonic", lambda: now[0])

    app.status()
    app.status()

    assert scheduler.calls["status"] == 1


def test_slow_status_dependency_degrades_within_deadline_and_keeps_shape(monkeypatch):
    def slow_online():
        time.sleep(0.12)
        return True

    runtime = RuntimeProbe()
    runtime.is_online = slow_online
    app = make_app(runtime=runtime)
    monkeypatch.setattr(app_module, "_STATUS_DEPENDENCY_TIMEOUT_SECONDS", 0.02, raising=False)

    started = time.monotonic()
    result = app.status()
    elapsed = time.monotonic() - started

    assert elapsed < 0.10
    assert result["success"] is False
    assert result["ollama_online"] is False
    assert result["scheduler"] == {"state": "ready"}
    assert result["degraded"] is True
    assert result["dependency_status"]["runtime.online"]["degraded"] is True
    assert result["dependency_status"]["runtime.online"]["deadline_ms"] == 20


def test_slow_agent_state_summary_uses_dependency_deadline(monkeypatch):
    def slow_summary():
        time.sleep(0.12)
        return {"enabled": True}

    app = make_app()
    app._agent_state_summary = slow_summary
    monkeypatch.setattr(app_module, "_STATUS_DEPENDENCY_TIMEOUT_SECONDS", 0.02)

    started = time.monotonic()
    result = app.status()
    elapsed = time.monotonic() - started

    assert elapsed < 0.10
    assert result["success"] is False
    assert result["agent_state"] == {"enabled": False}


def test_cached_status_snapshot_does_not_requery_agent_state():
    app = make_app()
    first = app.status()
    app._agent_state_summary = lambda: (_ for _ in ()).throw(AssertionError("unexpected status dependency call"))

    cached = app.status()

    assert cached["agent_state"] == first["agent_state"]
    assert cached["snapshot_cached"] is True


def make_live_app(monkeypatch, runtime=None):
    app = make_app(runtime=runtime)
    app._live_status_cache = {}
    app._live_status_lock = threading.Lock()
    app.repo_state = Probe(stats={})
    app.vram_balancer = Probe(status={})
    app.benchmark_runner = SimpleNamespace(get_latest_summary=lambda: {"available": False})
    app._headless_status = lambda: {"enabled": False, "supervisor": False}
    app.telemetry.realtime_summary = lambda **kwargs: {"events": 1}
    app._agent_state_summary = lambda: {"enabled": True}
    monkeypatch.setattr(app_module, "accelerator_status", lambda config: {})
    return app


def test_live_status_cache_does_not_requery_agent_state(monkeypatch):
    app = make_live_app(monkeypatch)

    first = app.realtime_status(light=True)
    app._agent_state_summary = lambda: (_ for _ in ()).throw(AssertionError("unexpected live status dependency call"))
    cached = app.realtime_status(light=True)

    assert cached["agent_state"] == first["agent_state"]
    assert cached["snapshot_cached"] is True


def test_live_status_cache_covers_normal_dashboard_poll_interval(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(app_module.time, "monotonic", lambda: now[0])
    app = make_live_app(monkeypatch)

    app.realtime_status(light=True)
    calls_after_first_snapshot = dict(app.runtime.calls)
    now[0] += 1.1
    cached = app.realtime_status(light=True)

    assert cached["snapshot_cached"] is True
    assert app.runtime.calls == calls_after_first_snapshot


def test_live_status_slow_dependency_returns_degraded_within_deadline(monkeypatch):
    runtime = RuntimeProbe()

    def slow_online():
        time.sleep(0.12)
        return True

    runtime.is_online = slow_online
    app = make_live_app(monkeypatch, runtime=runtime)
    monkeypatch.setattr(app_module, "_STATUS_DEPENDENCY_TIMEOUT_SECONDS", 0.02)

    started = time.monotonic()
    result = app.realtime_status(light=True)

    assert time.monotonic() - started < 0.10
    assert result["degraded"] is True
    assert result["success"] is False
    assert result["dependency_status"]["runtime.online"]["degraded"] is True
