import time
from types import SimpleNamespace

import pytest

from local_ai_hub.scheduler import AffinityScheduler
from local_ai_hub.scheduler import admission_rejection_message
from local_ai_hub.vram_balancer import VRAMBalancer


@pytest.mark.parametrize("active_model", [None, "target-model"])
def test_mixed_backend_requires_admission_for_initial_or_same_name_switch(active_model):
    import threading
    from collections import Counter

    calls = []
    class Runtime:
        def supports_post_unload_admission(self, _model):
            return True
        def requires_post_unload_admission(self, _model):
            return True
        def resource_status(self):
            return {
                "available": True,
                "vram_total_mb": 8192,
                "vram_available_mb": 6144,
                "telemetry_stale": False,
                "sample_age_seconds": 0.1,
            }
        def loaded_model_details(self):
            return []
        def prepare_model(self, _model, *, post_unload_admission, **_kwargs):
            calls.append(post_unload_admission()["state"])
            return []

    scheduler = object.__new__(AffinityScheduler)
    scheduler.runtime = Runtime()
    scheduler.config = {"scheduler": {"model_vram_estimates_bytes": {"target-model": 1024**3}}}
    scheduler._cond = threading.Condition()
    scheduler._pending = []
    scheduler._model_vram_bytes = {}
    scheduler._active_model = active_model
    scheduler._active_since = 1.0
    scheduler._active_dispatched = 0
    scheduler._last_switch = 0.0
    scheduler._switch_sequence = 0
    scheduler._stats = Counter()
    scheduler._internal_gpu_uncertain = False
    scheduler._internal_gpu_uncertain_since = None
    scheduler._model_blocked_until = {}
    scheduler._model_last_error = {}
    scheduler.switch_failure_cooldown = 1.0
    scheduler.unload_others = True
    assert scheduler._perform_switch("target-model") is True
    assert calls == ["admitted"]


def test_required_mixed_admission_fails_closed_without_telemetry():
    import threading
    from collections import Counter

    calls = []
    runtime = SimpleNamespace(requires_post_unload_admission=lambda _model: True,
                              supports_post_unload_admission=lambda _model: True,
                              loaded_model_details=lambda: [],
                              prepare_model=lambda *_a, **_kw: calls.append("load"))
    scheduler = object.__new__(AffinityScheduler)
    scheduler.runtime, scheduler.config = runtime, {}
    scheduler._cond = threading.Condition()
    scheduler._pending = []
    scheduler._model_vram_bytes = {}
    scheduler._active_model = None
    scheduler._active_since = 1.0
    scheduler._active_dispatched = 0
    scheduler._last_switch = 0.0
    scheduler._switch_sequence = 0
    scheduler._stats = Counter()
    scheduler._internal_gpu_uncertain = False
    scheduler._internal_gpu_uncertain_since = None
    scheduler._model_blocked_until = {}
    scheduler._model_last_error = {}
    scheduler.switch_failure_cooldown = 1.0
    scheduler.unload_others = True
    assert scheduler._perform_switch("target-model") is False
    assert calls == []


@pytest.mark.parametrize("failure_kind", ["admission_rejected", "operation_not_started", "ambiguous"])
def test_preparation_result_preserves_gpu_certainty(failure_kind):
    import threading
    from collections import Counter

    class PreparationFailure(RuntimeError):
        pass

    class Runtime:
        def requires_post_unload_admission(self, _model):
            return failure_kind == "admission_rejected"

        def supports_post_unload_admission(self, _model):
            return failure_kind == "admission_rejected"

        def loaded_model_details(self):
            return []

        def resource_status(self):
            return {"available": True, "vram_total_mb": 8192, "vram_available_mb": 6144}

        def prepare_model(self, _model, *, post_unload_admission=None, **_kwargs):
            if failure_kind == "admission_rejected":
                admission = post_unload_admission()
                admission.update(state="rejected", reason="capacity")
                exc = PreparationFailure("admission rejected")
                exc.admission = admission
            elif failure_kind == "ambiguous":
                raise PreparationFailure("adapter outcome unavailable")
            else:
                exc = PreparationFailure("preparation cancelled")
                exc.operation_not_started = True
                exc.preparation_cancelled = True
            raise exc

    scheduler = object.__new__(AffinityScheduler)
    scheduler.runtime = Runtime()
    scheduler.config = {}
    scheduler._cond = threading.Condition()
    scheduler._pending = []
    scheduler._model_vram_bytes = {}
    scheduler._active_model = "old-model"
    scheduler._active_since = 1.0
    scheduler._active_dispatched = 0
    scheduler._last_switch = 0.0
    scheduler._switch_sequence = 0
    scheduler._stats = Counter()
    scheduler._internal_gpu_uncertain = False
    scheduler._internal_gpu_uncertain_since = None
    scheduler._model_blocked_until = {}
    scheduler._model_last_error = {}
    scheduler._switch_not_started = False
    scheduler.switch_failure_cooldown = 1.0
    scheduler.unload_others = True

    assert scheduler._perform_switch("target-model") is False
    known_not_started = failure_kind != "ambiguous"
    assert scheduler._switch_not_started is known_not_started
    assert scheduler._internal_gpu_uncertain is not known_not_started


def scheduler_with_balancer(balancer):
    scheduler = object.__new__(AffinityScheduler)
    scheduler.runtime = SimpleNamespace(vram_balancer=balancer)
    scheduler.config = {
        "scheduler": {"model_vram_estimates_bytes": {"target-model": 1024**3}},
    }
    scheduler._model_vram_bytes = {}
    return scheduler


def test_post_unload_waits_for_actual_balancer_sample(monkeypatch):
    import local_ai_hub.vram_balancer as module

    monkeypatch.setattr(module, "get_gpu_telemetry", lambda: {
        "available": True, "gpu_name": "Test GPU", "vendor": "nvidia",
        "vram_total_mb": 8192.0, "vram_used_mb": 2048.0,
        "vram_available_mb": 6144.0, "timestamp": time.time(),
    })
    scheduler = scheduler_with_balancer(VRAMBalancer())

    result = scheduler._post_unload_vram_admission("target-model")

    assert result["state"] == "admitted"
    assert result["vram_available_bytes"] == 6144 * 1024**2


@pytest.mark.parametrize("sample", [
    {"available": False, "vram_total_mb": 8192.0, "vram_available_mb": 6144.0},
    {"available": False},
    {"available": "false", "vram_total_mb": 8192.0, "vram_available_mb": 6144.0},
    {"vram_total_mb": 8192.0, "vram_available_mb": 6144.0},
])
def test_post_unload_rejects_explicitly_unavailable_measurement(sample):
    class Balancer:
        def status(self, force=False):
            return dict(sample)

    result = scheduler_with_balancer(Balancer())._post_unload_vram_admission("target-model")

    assert result["state"] == "rejected"
    assert result["reason"] == "post_unload_vram_unavailable"


@pytest.mark.parametrize(
    ("telemetry", "expected_reason"),
    [
        ({"telemetry_stale": True, "sample_age_seconds": 0.2}, "vram_telemetry_stale"),
        ({"telemetry_stale": False, "sample_age_seconds": 5.1}, "vram_telemetry_stale"),
        ({"telemetry_stale": False}, "vram_telemetry_unavailable"),
        ({"telemetry_stale": None, "sample_age_seconds": 0.2}, "vram_telemetry_unavailable"),
        ({"telemetry_stale": False, "sample_age_seconds": float("nan")}, "vram_telemetry_unavailable"),
    ],
)
def test_post_unload_rejects_stale_or_unknown_sample_age(telemetry, expected_reason):
    class Balancer:
        def status(self, force=False):
            return {
                "available": True,
                "vram_total_mb": 8192.0,
                "vram_available_mb": 7168.0,
                **telemetry,
            }

    result = scheduler_with_balancer(Balancer())._post_unload_vram_admission("target-model")

    assert result["state"] == "rejected"
    assert result["reason"] == expected_reason
    assert result["vram_admission"] == "rejected"
    assert result["vram_admission_phase"] == "post_unload"


def test_normal_admission_rejects_unavailable_stale_vram_capacity():
    class Balancer:
        def status(self, force=False):
            return {
                "available": False,
                "pressure_level": "unknown",
                "context_budget_factor": 0.25,
                "throttle_background": True,
                "vram_total_mb": 8192.0,
                "vram_available_mb": 7168.0,
                "telemetry_stale": True,
                "telemetry_wait_timed_out": True,
            }

    result = scheduler_with_balancer(Balancer())._admission(
        background=False,
        model="target-model",
    )

    assert result["state"] == "rejected"
    assert result["reason"] == "vram_telemetry_stale"
    assert result["vram_admission"] == "unknown"
    assert "vram_available_bytes" not in result


@pytest.mark.parametrize(
    ("telemetry", "expected_reason"),
    [
        ({"telemetry_stale": True, "sample_age_seconds": 0.2}, "vram_telemetry_stale"),
        ({"telemetry_stale": False, "sample_age_seconds": 5.1}, "vram_telemetry_stale"),
        ({"telemetry_stale": False}, "vram_telemetry_unavailable"),
        ({"telemetry_stale": None, "sample_age_seconds": 0.2}, "vram_telemetry_unavailable"),
        ({"telemetry_stale": False, "sample_age_seconds": float("nan")}, "vram_telemetry_unavailable"),
        ({"telemetry_stale": False, "sample_age_seconds": "0.2"}, "vram_telemetry_unavailable"),
    ],
)
def test_normal_admission_rejects_stale_or_unknown_sample_age(telemetry, expected_reason):
    class Balancer:
        def status(self, force=False):
            return {
                "available": True,
                "pressure_level": "nominal",
                "context_budget_factor": 1.0,
                "throttle_background": False,
                "vram_total_mb": 8192.0,
                "vram_available_mb": 7168.0,
                **telemetry,
            }

    result = scheduler_with_balancer(Balancer())._admission(
        background=False,
        model="target-model",
    )

    assert result["state"] == "rejected"
    assert result["reason"] == expected_reason
    assert result["vram_admission"] == "unknown"
    assert "vram_available_bytes" not in result


def test_admission_rejection_message_matches_reason_and_request_class():
    assert admission_rejection_message("vram_telemetry_unavailable", background=False) == (
        "VRAM telemetry unavailable; refusing model admission"
    )
    assert admission_rejection_message("resource_pressure", background=False) == (
        "resource pressure blocks foreground admission"
    )
    assert admission_rejection_message("resource_pressure", background=True) == (
        "resource pressure blocks background admission"
    )
    assert admission_rejection_message("vram_budget", background=False) == (
        "insufficient VRAM for model admission"
    )


def test_post_unload_requests_refresh_without_changing_normal_status():
    calls = []

    class Balancer:
        def status(self, force=False):
            calls.append(force)
            return {"available": False}

    scheduler = scheduler_with_balancer(Balancer())
    scheduler._resource_status()
    scheduler._post_unload_vram_admission("target-model")

    assert calls == [False, True]
