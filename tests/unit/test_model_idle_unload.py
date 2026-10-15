"""Deferred bundle regressions; no inference, model unload or service restart."""
import threading
import time
from types import SimpleNamespace

import pytest

from local_ai_hub.scheduler import AffinityScheduler
from local_ai_hub.tiered_ollama import TieredOllamaRuntime


def _scheduler():
    scheduler = object.__new__(AffinityScheduler)
    scheduler._cond = threading.Condition()
    scheduler._running = True
    scheduler.idle_timeout_seconds = 300
    scheduler._switching = False
    scheduler._pending = []
    scheduler._inflight = 0
    scheduler._background_gpu_lease = False
    scheduler._active_model = "owned"
    scheduler._idle_owned_model = "owned"
    scheduler._last_model_activity = 100
    scheduler._active_since = 100
    scheduler._active_dispatched = 1
    scheduler._stats = {}
    return scheduler


def test_idle_release_reserves_then_calls_runtime_outside_condition_lock():
    scheduler = _scheduler()
    observed = []

    def unload(model, *, should_stop, deadline):
        entered = threading.Event()

        def enter_condition():
            with scheduler._cond:
                entered.set()

        peer = threading.Thread(target=enter_condition)
        peer.start()
        assert entered.wait(1), "network/model release must not hold scheduler condition"
        peer.join(timeout=1)
        observed.append((model, should_stop(), deadline - time.monotonic()))
        return True

    scheduler.runtime = SimpleNamespace(unload_model=unload)
    with scheduler._cond:
        assert scheduler._claim_idle_unload(399) is None
        target = scheduler._claim_idle_unload(400)
        assert scheduler._switching is True
    scheduler._perform_idle_unload(target)
    assert observed[0][0:2] == ("owned", False)
    assert 0 < observed[0][2] <= 5
    assert scheduler._active_model is None
    assert scheduler._switching is False
    assert scheduler._stats["idle_unloads"] == 1


@pytest.mark.parametrize("attribute,value", [
    ("_pending", [object()]), ("_inflight", 1), ("_switching", True),
    ("_background_gpu_lease", True), ("idle_timeout_seconds", 0),
    ("_idle_owned_model", None), ("_running", False),
])
def test_idle_timer_never_claims_busy_disabled_or_foreign_model(attribute, value):
    scheduler = _scheduler()
    setattr(scheduler, attribute, value)
    with scheduler._cond:
        assert scheduler._claim_idle_unload(1000) is None


def test_unconfirmed_release_drops_affinity_without_retry_loop():
    scheduler = _scheduler()
    scheduler.runtime = SimpleNamespace(unload_model=lambda *_args, **_kwargs: False)
    with scheduler._cond:
        target = scheduler._claim_idle_unload(400)
    scheduler._perform_idle_unload(target)
    assert scheduler._idle_unload_state == "unconfirmed"
    assert scheduler._active_model is None
    with scheduler._cond:
        assert scheduler._claim_idle_unload(10000) is None


def test_tiered_runtime_forwards_release_deadline_and_cancellation():
    runtime = object.__new__(TieredOllamaRuntime)
    calls = []
    target = SimpleNamespace(unload_model=lambda model, **kwargs: calls.append((model, kwargs)) or True)
    runtime._runtime_for_model = lambda model: ("smart", target, model)
    stopped = lambda: False
    assert runtime.unload_model("owned", should_stop=stopped, deadline=123)
    assert calls == [("owned", {"should_stop": stopped, "deadline": 123})]
