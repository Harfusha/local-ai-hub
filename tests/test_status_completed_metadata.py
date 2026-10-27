from concurrent.futures import ThreadPoolExecutor
import threading
import time
import pytest

from local_ai_hub import app as app_module


def test_diagnostic_probe_timeouts_do_not_degrade_core_hub_health():
    assert not app_module._status_probe_affects_core_health("telemetry.summary", healthy=False)
    assert not app_module._status_probe_affects_core_health("preprocessing.stats", healthy=False)
    assert not app_module._status_probe_affects_core_health("accelerators", healthy=False)
    assert app_module._status_probe_affects_core_health("runtime.online", healthy=False)
    assert app_module._status_probe_affects_core_health("scheduler", healthy=False)
    assert not app_module._status_probe_affects_core_health("telemetry.summary", healthy=True)


def test_metadata_refreshes_before_expiry_without_blocking_cached_dashboard():
    lock, release, started = threading.Lock(), threading.Event(), threading.Event()
    key = app_module._status_probe_key("live", "window", "telemetry.summary")
    completed = threading.Event()
    completed.set()
    cached = {"completed": completed, "outcome": {"value": {"accounted": 25}},
              "completed_at": time.monotonic() - app_module._STATUS_METADATA_CACHE_SECONDS * 0.6}
    cache, inflight, calls = {key: cached}, {}, []

    def slow_report():
        calls.append(1)
        started.set()
        assert release.wait(2)
        return {"accounted": 26}

    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            for _ in range(2):
                diagnostic = {}
                value, healthy = app_module._status_dependency(
                    slow_report, {}, key=key, lock=lock, inflight=inflight,
                    slots=threading.BoundedSemaphore(1), executor=executor,
                    deadline=time.monotonic() + 0.02, diagnostic=diagnostic,
                    completed_cache=cache,
                )
                assert healthy and value == {"accounted": 25}
                assert diagnostic["dependency_refreshing"] is True
            assert started.wait(1)
            assert calls == [1]
        finally:
            release.set()


def test_timed_out_metadata_completion_is_reused_then_expires_without_stale_success():
    lock = threading.Lock()
    inflight = {}
    completed_cache = {}
    slots = threading.BoundedSemaphore(1)
    started, release = threading.Event(), threading.Event()
    calls = []
    key = app_module._status_probe_key("live", "process", "preprocessing.status")

    def callback():
        calls.append(1)
        started.set()
        assert release.wait(2)
        return {"projects": [{"status": "running"}]}

    with ThreadPoolExecutor(max_workers=1) as executor:
        def read(diagnostic):
            return app_module._status_dependency(
                callback, {"unavailable": True}, key=key, lock=lock,
                inflight=inflight, slots=slots, executor=executor,
                deadline=time.monotonic() + 0.02, diagnostic=diagnostic,
                completed_cache=completed_cache,
            )

        try:
            diagnostic = {}
            assert read(diagnostic) == ({"unavailable": True}, False)
            assert started.is_set()
            assert diagnostic["reason"] == "probe_timeout"
            entry = inflight[key]
            release.set()
            assert entry["completed"].wait(1)
            assert inflight == {}
            assert completed_cache[key] is entry
            diagnostic = {}
            value, healthy = read(diagnostic)
            assert healthy
            assert diagnostic["dependency_cached"] is True
            assert 0 <= diagnostic["dependency_age_ms"] < 5000
            value["projects"][0]["status"] = "caller mutation"
            assert read({})[0]["projects"][0]["status"] == "running"
            assert calls == [1]
            # Expired metadata must not be reported as a fresh success.
            release.clear()
            started.clear()
            entry["completed_at"] -= app_module._STATUS_METADATA_CACHE_SECONDS + 1
            diagnostic = {}
            assert read(diagnostic) == ({"unavailable": True}, False)
            assert started.is_set()
            assert diagnostic["reason"] == "probe_timeout"
            assert not diagnostic.get("dependency_cached")
            assert calls == [1, 1]
        finally:
            release.set()


@pytest.mark.parametrize("error_type", [RuntimeError, BaseException])
def test_metadata_cache_separates_scope_and_view_and_does_not_retain_errors(error_type):
    lock = threading.Lock()
    inflight = {}
    completed_cache = {}
    slots = threading.BoundedSemaphore(1)
    calls = []
    keys = [app_module._status_probe_key(view, scope, "telemetry.summary")
            for view in ("live", "full") for scope in ("process", "window")]
    assert len(set(keys)) == 4
    assert len(app_module._STATUS_METADATA_KEYS) == 8
    with ThreadPoolExecutor(max_workers=1) as executor:
        for key in keys:
            value, healthy = app_module._status_dependency(
                lambda key=key: {"key": key}, {}, key=key, lock=lock,
                inflight=inflight, slots=slots, executor=executor,
                deadline=time.monotonic() + 1,
                completed_cache=completed_cache,
            )
            assert healthy and value == {"key": key}

        key = keys[0]
        completed_cache[key]["completed_at"] -= app_module._STATUS_METADATA_CACHE_SECONDS + 1

        def failed():
            calls.append(1)
            raise error_type("unavailable metadata")

        for _ in range(2):
            diagnostic = {}
            value, healthy = app_module._status_dependency(
                failed, {}, key=key, lock=lock, inflight=inflight, slots=slots,
                executor=executor, deadline=time.monotonic() + 1, diagnostic=diagnostic,
                completed_cache=completed_cache,
            )
            assert not healthy and value == {}
            assert diagnostic["reason"] == "probe_error"
            assert key not in inflight
            assert key not in completed_cache
        assert calls == [1, 1]
