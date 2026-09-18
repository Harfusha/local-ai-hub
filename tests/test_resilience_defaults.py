from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_default_model_and_transport_budgets_allow_completion_without_retry_storms() -> None:
    configs = [tomllib.loads((ROOT / name).read_text(encoding="utf-8")) for name in ("defaults.toml", "src/local_ai_hub/defaults.toml")]
    for config in configs:
        assert config["server"]["request_timeout_seconds"] >= 900
        assert config["ollama"]["request_attempts"] == 1
        assert config["token_saving"]["max_local_output_tokens"] >= 8192
        assert config["resilience"]["scheduler_wait_timeout_seconds"] >= 900


def test_runtime_caps_do_not_clip_configured_completion_budgets() -> None:
    async_jobs = (ROOT / "src/local_ai_hub/async_jobs.py").read_text(encoding="utf-8")
    services = (ROOT / "src/local_ai_hub/services.py").read_text(encoding="utf-8")
    ollama_subagents = (ROOT / "src/local_ai_hub/ollama_subagents.py").read_text(encoding="utf-8")

    assert 'min(90.0' not in async_jobs
    assert 'max_local_output_tokens", 2400' not in services
    assert 'min(int(raw.get("max_tokens", 800)), 2400)' not in ollama_subagents
