from __future__ import annotations


def _config(state_dir: str) -> dict:
    return {
        "server": {"state_dir": state_dir},
        "autotune": {
            "enabled": True,
            "persist": True,
            "persist_interval_seconds": 0,
            "min_samples": 2,
        },
    }


def _result() -> dict:
    return {
        "load_duration_ns": 1_500_000,
        "eval_count": 12,
        "eval_duration_ns": 6_000_000,
    }


def test_runtime_tuner_restores_numeric_profiles_without_request_content(tmp_path):
    from local_ai_hub.autotune import RuntimeTuner

    config = _config(str(tmp_path))
    first = RuntimeTuner(config)
    first.observe("qwen2.5-coder:7b", _result(), 2400)
    first.observe("qwen2.5-coder:7b", _result(), 2200)

    restored = RuntimeTuner(config)

    assert restored.ready("qwen2.5-coder:7b")
    stats = restored.stats()["models"]["qwen2.5-coder:7b"]
    assert stats["samples"] == 2.0
    assert "prompt" not in str(stats).lower()
    assert "context" not in str(stats).lower()


def test_runtime_tuner_ignores_invalid_persisted_state(tmp_path):
    from local_ai_hub.autotune import RuntimeTuner

    (tmp_path / "runtime-tuner.json").write_text('{"models":{"bad":{"latency_ms":"no"}}}', encoding="utf-8")

    tuner = RuntimeTuner(_config(str(tmp_path)))

    assert tuner.stats()["models"] == {}
