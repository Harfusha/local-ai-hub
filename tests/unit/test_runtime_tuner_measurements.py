from __future__ import annotations

import threading

import pytest

from local_ai_hub import autotune


@pytest.mark.parametrize(
    ("field", "value_factory"),
    [
        (field, factory)
        for field in ("ema_alpha", "resident_latency_ratio", "persist_interval_seconds")
        for factory in (
            lambda: float("nan"),
            lambda: float("inf"),
            lambda: float("-inf"),
            lambda: True,
            lambda: "0.5",
            lambda: 10**10000,
        )
    ],
    ids=[
        f"{field}-{case}"
        for field in ("alpha", "resident-ratio", "persist-interval")
        for case in ("nan", "infinity", "negative-infinity", "bool", "string", "overflow")
    ],
)
def test_invalid_tuner_numeric_config_fails_before_state_access(
    field, value_factory, monkeypatch
):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid config reached state access")

    monkeypatch.setattr(autotune, "configured_state_dir", fail_if_called)
    monkeypatch.setattr(autotune.Path, "read_text", fail_if_called)
    monkeypatch.setattr(autotune.Path, "mkdir", fail_if_called)
    monkeypatch.setattr(autotune.Path, "write_text", fail_if_called)

    with pytest.raises(ValueError):
        autotune.RuntimeTuner({"autotune": {field: value_factory()}})


@pytest.mark.parametrize(
    "config",
    [
        [],
        {"autotune": []},
        {"server": []},
        {"server": {"state_dir": True}},
        {"server": {"state_dir": "bad\x00path"}},
    ],
    ids=[
        "invalid-root",
        "invalid-autotune",
        "invalid-server",
        "boolean-state-dir",
        "nul-state-dir",
    ],
)
def test_malformed_config_fails_before_profile_read_or_persist(config, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("malformed config reached profile access")

    monkeypatch.setattr(autotune.Path, "read_text", fail_if_called)
    monkeypatch.setattr(autotune.Path, "mkdir", fail_if_called)
    monkeypatch.setattr(autotune.Path, "write_text", fail_if_called)

    with pytest.raises((TypeError, ValueError)):
        autotune.RuntimeTuner(config)


def test_missing_config_uses_isolated_process_state_directory(tmp_path, monkeypatch):
    calls = []

    def isolated_state_dir(config, *, create):
        calls.append((config, create))
        return tmp_path

    monkeypatch.setattr(autotune, "configured_state_dir", isolated_state_dir)

    tuner = autotune.RuntimeTuner({})

    assert calls == [({}, False)]
    assert tuner._state_path == tmp_path / "runtime-tuner.json"


def test_finite_numeric_config_keeps_existing_clamps(tmp_path, monkeypatch):
    monkeypatch.setattr(autotune, "configured_state_dir", lambda config, *, create: tmp_path)

    tuner = autotune.RuntimeTuner(
        {
            "autotune": {
                "ema_alpha": -1.0,
                "resident_latency_ratio": -1.0,
                "persist_interval_seconds": -1.0,
                "min_samples": 0,
                "persist": False,
            }
        }
    )

    assert tuner.alpha == 0.01
    assert tuner.resident_latency_ratio == 0.5
    assert tuner._persist_interval_seconds == 0.0
    assert tuner.min_samples == 1


def _tuner_without_io(tmp_path, monkeypatch):
    tuner = autotune.RuntimeTuner.__new__(autotune.RuntimeTuner)
    tuner.enabled = True
    tuner.alpha = 0.5
    tuner.min_samples = 2
    tuner.resident_latency_ratio = 1.15
    tuner._lock = threading.RLock()
    tuner._models = {}
    tuner._persist_enabled = True
    tuner._persist_interval_seconds = 0.0
    tuner._last_persist_seconds = 0.0
    tuner._state_path = tmp_path / "runtime-tuner.json"
    persisted = []
    monkeypatch.setattr(tuner, "_persist_locked", lambda *, force=False: persisted.append(force))
    return tuner, persisted


@pytest.mark.parametrize(
    ("model", "result", "elapsed_ms"),
    [
        ("", {}, 1.0),
        (" ", {}, 1.0),
        (42, {}, 1.0),
        ("model-a", [], 1.0),
        ("model-a", {}, float("nan")),
        ("model-a", {}, float("inf")),
        ("model-a", {}, -1.0),
        ("model-a", {"load_duration_ns": float("inf")}, 1.0),
        ("model-a", {"eval_count": -1}, 1.0),
        ("model-a", {"eval_duration_ns": "bad"}, 1.0),
        ("model-a", {"eval_count": 1e308, "eval_duration_ns": 1e6}, 1.0),
    ],
    ids=[
        "empty-model",
        "blank-model",
        "nonstring-model",
        "nonmapping-result",
        "nan-latency",
        "infinite-latency",
        "negative-latency",
        "bad-load",
        "negative-count",
        "bad-duration",
        "tps-overflow",
    ],
)
def test_invalid_observation_does_not_create_model_or_persist(
    tmp_path, monkeypatch, model, result, elapsed_ms
):
    tuner, persisted = _tuner_without_io(tmp_path, monkeypatch)

    tuner.observe(model, result, elapsed_ms)

    assert tuner._models == {}
    assert persisted == []


def test_valid_observation_updates_ema_and_zero_eval_duration_has_zero_tps(tmp_path, monkeypatch):
    tuner, persisted = _tuner_without_io(tmp_path, monkeypatch)
    tuner._models["model-a"] = {
        "latency_ms": 200.0,
        "load_ms": 10.0,
        "tps": 4.0,
        "samples": 1.0,
    }

    tuner.observe(
        "model-a",
        {"load_duration_ns": 10_000_000, "eval_count": 4, "eval_duration_ns": 2_000_000_000},
        100.0,
    )

    assert tuner._models["model-a"] == {
        "latency_ms": 150.0,
        "load_ms": 10.0,
        "tps": 3.0,
        "samples": 2.0,
    }
    assert persisted == [True]

    tuner.observe("model-b", {"eval_count": 10, "eval_duration_ns": 0}, 10.0)
    assert tuner._models["model-b"]["tps"] == 0.0


@pytest.mark.parametrize(
    "profile",
    [
        {"latency_ms": True, "load_ms": 0, "tps": 0, "samples": 1},
        {"latency_ms": float("nan"), "load_ms": 0, "tps": 0, "samples": 1},
        {"latency_ms": float("inf"), "load_ms": 0, "tps": 0, "samples": 1},
        {"latency_ms": -1, "load_ms": 0, "tps": 0, "samples": 1},
        {"latency_ms": 10**10000, "load_ms": 0, "tps": 0, "samples": 1},
    ],
    ids=["bool", "nan", "infinity", "negative", "overflow"],
)
def test_profile_rejects_invalid_persisted_measurements(profile):
    assert autotune.RuntimeTuner._profile(profile) is None
